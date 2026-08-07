/** AutoEditor Helper: one-window shell around the frozen render daemon. */
const { app, BrowserWindow, ipcMain, safeStorage, shell } = require('electron');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { stopProcessTree } = require('../lib/process-tree');
const { decodeSetupCode } = require('./lib/setup-code');
const {
  PROVIDER_LINKS, normalizeProviderSetup, validateProviderKeys,
} = require('./lib/provider-setup');

let win = null;
let daemon = null;
const PACKAGED = app.isPackaged;
const RES = PACKAGED ? process.resourcesPath : path.join(__dirname, '../..');
const MIN_FREE_BYTES = 20 * 1024 * 1024 * 1024;

function exe(name) {
  return process.platform === 'win32' ? `${name}.exe` : name;
}

function browserParts() {
  if (process.platform === 'darwin') {
    return ['chrome-headless-shell-mac', 'chrome-headless-shell'];
  }
  if (process.platform === 'win32') {
    return ['chrome-headless-shell-win64', 'chrome-headless-shell.exe'];
  }
  return ['chrome-headless-shell-linux64', 'chrome-headless-shell'];
}

function runtimePaths() {
  const root = RES;
  return {
    root,
    daemon: path.join(root, 'helper', exe('autoeditor-helper-daemon')),
    engine: path.join(root, 'engine', exe('autoeditor-engine')),
    ffmpeg: path.join(root, 'bin', exe('ffmpeg')),
    ffprobe: path.join(root, 'bin', exe('ffprobe')),
    smallModel: path.join(root, 'models', 'faster-whisper-small'),
    mediumModel: path.join(root, 'models', 'faster-whisper-medium'),
    profiles: path.join(root, 'profiles'),
    fonts: path.join(root, 'fonts'),
    caBundle: path.join(root, 'certs', 'cacert.pem'),
    notices: path.join(root, 'licenses', 'THIRD_PARTY_NOTICES.md'),
    node: path.join(root, 'node', exe('node')),
    hyperframesCli: path.join(root, 'creative-runtime', 'node_modules',
      'hyperframes', 'bin', 'hyperframes.mjs'),
    remotionCli: path.join(root, 'creative-runtime', 'node_modules',
      '@remotion', 'cli', 'remotion-cli.js'),
    browser: path.join(root, 'browser', ...browserParts()),
    hyperframesProject: path.join(root, 'creative', 'hyperframes-graphics'),
    remotionProject: path.join(root, 'creative', 'remotion-viz'),
  };
}

function setupFile() {
  return path.join(app.getPath('userData'), 'helper-setup.enc');
}

async function saveSetup(input) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Your OS keystore is unavailable, so setup cannot be saved safely');
  }
  const supplied = normalizeProviderSetup(input);
  const connection = decodeSetupCode(supplied.setupCode);
  await validateProviderKeys(supplied);
  const setup = {
    ...connection,
    pexelsKey: supplied.pexelsKey,
    pixabayKey: supplied.pixabayKey,
    elevenKey: supplied.elevenKey,
    pexelsMode: supplied.pexelsMode,
    pixabayMode: supplied.pixabayMode,
    elevenMode: supplied.elevenMode,
    remotionMode: supplied.remotionMode,
    remotionKey: supplied.remotionKey,
  };
  const ready = preflight();
  if (!ready.ok) {
    throw new Error('A built-in editing component is missing or this computer has less than 20 GB free');
  }
  creativeProbe(setup);
  const sealed = safeStorage.encryptString(JSON.stringify(setup));
  fs.mkdirSync(path.dirname(setupFile()), { recursive: true });
  fs.writeFileSync(setupFile(), sealed, { mode: 0o600 });
  return setup;
}

function loadSetup() {
  try {
    if (!fs.existsSync(setupFile()) || !safeStorage.isEncryptionAvailable()) {
      return null;
    }
    return JSON.parse(safeStorage.decryptString(fs.readFileSync(setupFile())));
  } catch (_) { return null; }
}

function commandOutput(command, args) {
  const result = spawnSync(command, args, {
    windowsHide: true, encoding: 'utf8', timeout: 15000,
  });
  return result.status === 0 ? `${result.stdout || ''}\n${result.stderr || ''}` : '';
}

function preflight() {
  const p = runtimePaths();
  const checks = {
    daemon: fs.existsSync(p.daemon),
    engine: fs.existsSync(p.engine),
    ffmpeg: fs.existsSync(p.ffmpeg),
    ffprobe: fs.existsSync(p.ffprobe),
    smallModel: fs.existsSync(path.join(p.smallModel, 'model.bin')),
    mediumModel: fs.existsSync(path.join(p.mediumModel, 'model.bin')),
    profiles: fs.existsSync(p.profiles),
    fonts: fs.existsSync(p.fonts),
    caBundle: fs.existsSync(p.caBundle),
    notices: fs.existsSync(p.notices),
    node: fs.existsSync(p.node),
    hyperframes: fs.existsSync(p.hyperframesCli) &&
      fs.existsSync(path.join(p.hyperframesProject, 'index.html')),
    remotion: fs.existsSync(p.remotionCli) &&
      fs.existsSync(path.join(p.remotionProject, 'src', 'index.ts')),
    browser: fs.existsSync(p.browser),
    keystore: safeStorage.isEncryptionAvailable(),
    disk: false,
    codecs: false,
    filters: false,
  };
  try {
    const stat = fs.statfsSync(app.getPath('userData'));
    checks.disk = Number(stat.bavail) * Number(stat.bsize) >= MIN_FREE_BYTES;
  } catch (_) { checks.disk = false; }
  if (checks.ffmpeg) {
    const encoders = commandOutput(p.ffmpeg, ['-hide_banner', '-encoders']);
    checks.codecs = encoders.includes('libx264') && /\bAAC\b|\baac\b/.test(encoders);
    const filters = commandOutput(p.ffmpeg, ['-hide_banner', '-filters']);
    const needed = ['fps', 'aresample', 'adelay', 'atrim', 'concat', 'scale',
      'pad', 'setsar', 'overlay', 'chromakey', 'despill', 'alphaextract',
      'dilation', 'erosion', 'alphamerge', 'huesaturation', 'loudnorm'];
    checks.filters = needed.every((name) => filters.includes(name));
  }
  return { ok: Object.values(checks).every(Boolean), checks };
}

function daemonEnv(setup) {
  const p = runtimePaths();
  const env = { ...process.env };
  for (const key of ['DEEPSEEK_API_KEY', 'KEY_WRAP_SECRET', 'ADMIN_TOKEN',
    'WORKER_TOKEN', 'PEXELS_API_KEY', 'PIXABAY_API_KEY', 'ELEVENLABS_API_KEY',
    'REMOTION_LICENSE_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY',
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_HOME_CHANNEL']) delete env[key];
  Object.assign(env, {
    AUTOEDITOR_WEB_API: setup.site,
    WORKER_TOKEN: setup.token,
    AUTOEDITOR_ENGINE: p.engine,
    AUTOEDITOR_INSTALL_ROOT: p.root,
    AUTOEDITOR_FFMPEG: p.ffmpeg,
    AUTOEDITOR_FFPROBE: p.ffprobe,
    AUTOEDITOR_WHISPER_SMALL: p.smallModel,
    AUTOEDITOR_WHISPER_MEDIUM: p.mediumModel,
    AUTOEDITOR_PROFILES_DIR: p.profiles,
    AUTOEDITOR_BUNDLED_FONTS: p.fonts,
    AUTOEDITOR_NODE: p.node,
    AUTOEDITOR_HYPERFRAMES_CLI: p.hyperframesCli,
    AUTOEDITOR_HYPERFRAMES_PROJECT: p.hyperframesProject,
    AUTOEDITOR_REMOTION_CLI: p.remotionCli,
    AUTOEDITOR_REMOTION_PROJECT: p.remotionProject,
    AUTOEDITOR_BROWSER: p.browser,
    HYPERFRAMES_BROWSER_PATH: p.browser,
    HYPERFRAMES_FFMPEG_PATH: p.ffmpeg,
    HYPERFRAMES_FFPROBE_PATH: p.ffprobe,
    HYPERFRAMES_NO_UPDATE_CHECK: '1',
    PEXELS_API_KEY: setup.pexelsMode === 'connect' ? setup.pexelsKey : '',
    PIXABAY_API_KEY: setup.pixabayMode === 'connect' ? setup.pixabayKey : '',
    ELEVENLABS_API_KEY: setup.elevenMode === 'connect' ? setup.elevenKey : '',
    REMOTION_LICENSE_KEY: setup.remotionKey || '',
    AUTOEDITOR_REQUIRE_HYPERFRAMES: '1',
    AUTOEDITOR_REQUIRE_REMOTION: setup.remotionMode === 'skip' ? '0' : '1',
    SSL_CERT_FILE: p.caBundle,
    REQUESTS_CA_BUNDLE: p.caBundle,
    HF_HUB_OFFLINE: '1',
    TRANSFORMERS_OFFLINE: '1',
    AUTOEDITOR_PACKAGED: '1',
    WORK_DIR: path.join(app.getPath('userData'), 'work'),
  });
  return env;
}

function creativeProbe(setup) {
  const p = runtimePaths();
  const child = spawnSync(p.daemon, [], {
    env: { ...daemonEnv(setup), AUTOEDITOR_CREATIVE_SMOKE_TEST: '1' },
    windowsHide: true, encoding: 'utf8', timeout: 360000,
  });
  const output = `${child.stdout || ''}\n${child.stderr || ''}`;
  if (child.status !== 0 || !output.includes('helper-creative-smoke')) {
    throw new Error('The built-in HyperFrames or Remotion render check failed. ' +
      'Restart the app and try again. If it repeats, send the Activity text to Omar');
  }
  return true;
}

function send(channel, value) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, value);
}

function startDaemon() {
  if (daemon) return { ok: true, running: true };
  const setup = loadSetup();
  if (!setup) throw new Error('Paste your Setup code first');
  const ready = preflight();
  if (!ready.ok) throw new Error('The built-in startup check failed');
  const p = runtimePaths();
  daemon = spawn(p.daemon, [], {
    env: daemonEnv(setup), windowsHide: true, cwd: p.root,
  });
  daemon.stdout.on('data', (data) => send('helper-log', data.toString()));
  daemon.stderr.on('data', (data) => send('helper-log', data.toString()));
  daemon.on('error', (err) => send('helper-state', {
    running: false, error: `Helper could not start: ${err.message}`,
  }));
  daemon.on('close', (code) => {
    daemon = null;
    send('helper-state', { running: false, error: code ? `Helper stopped (${code})` : '' });
  });
  send('helper-state', { running: true });
  return { ok: true, running: true };
}

async function stopDaemon() {
  const current = daemon;
  daemon = null;
  await stopProcessTree(current);
  send('helper-state', { running: false });
  return { ok: true, running: false };
}

function setupIpc() {
  ipcMain.handle('helper:state', () => ({
    configured: !!loadSetup(), running: !!daemon, preflight: preflight(),
    capabilities: (() => {
      const setup = loadSetup();
      return setup ? {
        pexels: setup.pexelsMode === 'connect',
        pixabay: setup.pixabayMode === 'connect',
        elevenlabs: setup.elevenMode === 'connect',
        remotion: setup.remotionMode !== 'skip',
        hyperframes: true,
      } : null;
    })(),
  }));
  ipcMain.handle('helper:save', async (_event, input) => {
    await saveSetup(input);
    return { ok: true, preflight: preflight() };
  });
  ipcMain.handle('helper:start', () => startDaemon());
  ipcMain.handle('helper:stop', () => stopDaemon());
  ipcMain.handle('helper:reset', async () => {
    await stopDaemon();
    try { fs.unlinkSync(setupFile()); } catch (_) { /* already clear */ }
    return { ok: true };
  });
  ipcMain.handle('helper:notices', () => shell.openPath(runtimePaths().notices));
  ipcMain.handle('helper:open', (_event, key) => {
    const url = PROVIDER_LINKS[key];
    if (!url) throw new Error('That help link is not allowed');
    return shell.openExternal(url);
  });
}

function smokeTest() {
  const setup = {
    site: 'https://smoke.invalid', token: 'smoke-token-12345678',
    pexelsMode: 'skip', pexelsKey: '', pixabayMode: 'skip', pixabayKey: '',
    elevenMode: 'skip', elevenKey: '',
    remotionMode: 'free', remotionKey: 'free-license',
  };
  const p = runtimePaths();
  const child = spawnSync(p.daemon, [], {
    env: { ...daemonEnv(setup), AUTOEDITOR_HELPER_SMOKE_TEST: '1' },
    windowsHide: true, encoding: 'utf8', timeout: 30000,
  });
  const creative = spawnSync(p.daemon, [], {
    env: { ...daemonEnv(setup), AUTOEDITOR_CREATIVE_SMOKE_TEST: '1' },
    windowsHide: true, encoding: 'utf8', timeout: 360000,
  });
  const checks = preflight();
  const result = {
    packaged: PACKAGED,
    preflight: checks.ok,
    daemonExit: child.status === 0,
    daemonReceipt: (child.stdout || '').includes('helper-daemon-smoke'),
    creativeExit: creative.status === 0,
    creativeReceipt: (creative.stdout || '').includes('helper-creative-smoke'),
  };
  console.log(JSON.stringify({ event: 'helper-desktop-smoke', checks: result }));
  return Object.values(result).every(Boolean);
}

function createWindow() {
  const capturePath = process.env.AUTOEDITOR_SCREENSHOT_PATH || '';
  win = new BrowserWindow({
    width: 720, height: capturePath ? 1200 : 650,
    minWidth: 620, minHeight: 560, show: !capturePath,
    title: 'AutoEditor Helper', backgroundColor: '#0b0d10',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  if (capturePath) {
    win.webContents.once('did-finish-load', async () => {
      await new Promise((resolve) => setTimeout(resolve, 800));
      if (process.env.AUTOEDITOR_SCREENSHOT_SKIP_ACCOUNTS === '1') {
        await win.webContents.executeJavaScript(`
          for (const name of ['pexels-mode', 'pixabay-mode', 'eleven-mode', 'remotion-mode']) {
            const choice = document.querySelector('input[name="' + name + '"][value="skip"]');
            choice.checked = true;
            choice.dispatchEvent(new Event('change', {bubbles: true}));
          }
        `);
      }
      const height = await win.webContents.executeJavaScript(
        'Math.min(4000, document.documentElement.scrollHeight)');
      win.setContentSize(720, Math.max(1200, height));
      const shot = await win.webContents.capturePage();
      fs.writeFileSync(capturePath, shot.toPNG());
      app.exit(0);
    });
  }
}

app.whenReady().then(() => {
  if (process.env.AUTOEDITOR_SMOKE_TEST === '1') {
    app.exit(smokeTest() ? 0 : 1);
    return;
  }
  setupIpc();
  createWindow();
});

app.on('before-quit', () => { if (daemon) stopProcessTree(daemon); });
app.on('window-all-closed', () => app.quit());

module.exports = { runtimePaths };
