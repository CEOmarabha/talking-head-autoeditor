/** Ryan Reels Editor / PSE AutoEditor: Electron main process.
 *
 * Responsibilities:
 *  - one-screen edit flow (renderer) with IPC to the verified Python engine
 *  - DeepSeek key in the OS keystore via safeStorage (Keychain on macOS,
 *    DPAPI/Credential-vault on Windows). The key travels ONLY through the
 *    child process environment; it is never written to .env, logs, or disk
 *    in plaintext, and never appears in diagnostics.
 *  - multi-clip concat via bundled ffmpeg before the engine runs
 *  - transcript generation (engine --transcribe-only) for the review step
 *  - QA-gated result: "delivered" vs "needs_review", never silently passed
 *  - auto-update via GitHub Releases (per-product channel)
 */
const { app, BrowserWindow, ipcMain, dialog, shell, safeStorage } =
  require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { resolveProduct } = require('./product');

let win = null;
let engineProc = null;
const PACKAGED = app.isPackaged;
const RES = PACKAGED ? process.resourcesPath : path.join(__dirname, '..');
const PRODUCT = resolveProduct(PACKAGED ? process.resourcesPath : '');

// ---------------------------------------------------------------- paths
function binName(name) {
  return process.platform === 'win32' ? `${name}.exe` : name;
}
function enginePath() {
  if (PACKAGED) {
    return path.join(process.resourcesPath, 'engine',
      binName('autoeditor-engine'));
  }
  return null; // dev mode: python -m autoeditor
}
function ffmpegPath() {
  const bundled = path.join(RES, PACKAGED ? 'bin' : 'desktop/bin',
    binName('ffmpeg'));
  if (fs.existsSync(bundled)) return bundled;
  return 'ffmpeg'; // dev fallback: PATH
}
function ffprobePath() {
  const bundled = path.join(RES, PACKAGED ? 'bin' : 'desktop/bin',
    binName('ffprobe'));
  if (fs.existsSync(bundled)) return bundled;
  return 'ffprobe';
}
function profilesDir() {
  return PACKAGED
    ? path.join(process.resourcesPath, 'profiles')
    : path.join(__dirname, '..', 'profiles');
}
function keyFile() {
  return path.join(app.getPath('userData'), 'deepseek.key.enc');
}

// ---------------------------------------------------------------- key store
function storeKey(plain) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('OS keystore unavailable; cannot store the key safely');
  }
  fs.writeFileSync(keyFile(), safeStorage.encryptString(plain.trim()),
    { mode: 0o600 });
}
function loadKey() {
  try {
    if (!fs.existsSync(keyFile())) return null;
    return safeStorage.decryptString(fs.readFileSync(keyFile())).trim();
  } catch (_) { return null; }
}

// ---------------------------------------------------------------- engine
function engineEnv() {
  const env = { ...process.env };
  delete env.DEEPSEEK_API_KEY; // only the vetted copy below may exist
  const key = loadKey();
  if (key) env.DEEPSEEK_API_KEY = key;
  env.AUTOEDITOR_PACKAGED = '1';
  env.AUTOEDITOR_PROGRESS_JSON = '1';
  env.AUTOEDITOR_PROFILES_DIR = profilesDir();
  const ff = ffmpegPath(), fp = ffprobePath();
  if (path.isAbsolute(ff)) env.AUTOEDITOR_FFMPEG = ff;
  if (path.isAbsolute(fp)) env.AUTOEDITOR_FFPROBE = fp;
  const fontsDir = path.join(RES, PACKAGED ? 'fonts' : 'desktop/fonts');
  if (fs.existsSync(fontsDir)) env.AUTOEDITOR_BUNDLED_FONTS = fontsDir;
  return env;
}

function spawnEngine(args, onLine, onExit) {
  const exe = enginePath();
  const cmd = exe || 'python3';
  const fullArgs = exe ? args : ['-m', 'autoeditor', ...args];
  const proc = spawn(cmd, fullArgs, {
    env: engineEnv(),
    cwd: exe ? undefined : path.join(__dirname, '..'),
  });
  let buf = '';
  proc.stdout.on('data', (d) => {
    buf += d.toString();
    let idx;
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx); buf = buf.slice(idx + 1);
      onLine(line);
    }
  });
  proc.stderr.on('data', (d) => onLine(d.toString().trimEnd()));
  proc.on('close', (code) => onExit(code));
  return proc;
}

function parseEvent(line) {
  if (!line.startsWith('{')) return null;
  try {
    const j = JSON.parse(line);
    return j && j.event ? j : null;
  } catch (_) { return null; }
}

// ---------------------------------------------------------------- concat
async function concatClips(clips, workDir) {
  if (clips.length === 1) return clips[0];
  const joined = path.join(workDir, 'joined_input.mp4');
  const listFile = path.join(workDir, 'concat.txt');
  // re-encode to a common grid so heterogeneous phone clips concat safely
  const inputs = [];
  clips.forEach((c) => inputs.push('-i', c));
  const n = clips.length;
  const filt = clips.map((_, i) =>
    `[${i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,` +
    `pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v${i}];` +
    `[${i}:a]aresample=48000[a${i}]`).join(';') + ';' +
    clips.map((_, i) => `[v${i}][a${i}]`).join('') +
    `concat=n=${n}:v=1:a=1[v][a]`;
  await new Promise((resolve, reject) => {
    const p = spawn(ffmpegPath(), ['-y', ...inputs,
      '-filter_complex', filt, '-map', '[v]', '-map', '[a]',
      '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
      '-c:a', 'aac', '-b:a', '192k', joined]);
    let err = '';
    p.stderr.on('data', (d) => { err += d.toString(); });
    p.on('close', (c) => c === 0 ? resolve()
      : reject(new Error('clip join failed: ' + err.slice(-400))));
  });
  fs.rmSync(listFile, { force: true });
  return joined;
}

// ---------------------------------------------------------------- IPC
function setupIpc() {
  ipcMain.handle('state', () => {
    const profs = [];
    for (const id of PRODUCT.profiles) {
      const y = path.join(profilesDir(), id, 'profile.yaml');
      if (!fs.existsSync(y)) continue;
      const txt = fs.readFileSync(y, 'utf8');
      const g = (k) => (txt.match(new RegExp(`${k}:\\s*"?([^"\\n#]+)`)) ||
        [])[1]?.trim();
      profs.push({
        id,
        display_name: g('display_name') || id,
        status: g('status') || 'provisional',
        description: g('description') || '',
      });
    }
    return {
      product: PRODUCT,
      profiles: profs,
      hasKey: !!loadKey(),
      version: app.getVersion(),
      platform: process.platform,
    };
  });

  ipcMain.handle('save-key', (_e, key) => {
    if (!key || key.trim().length < 20) {
      return { ok: false, error: 'That does not look like a DeepSeek key.' };
    }
    try { storeKey(key); return { ok: true }; }
    catch (err) { return { ok: false, error: String(err.message || err) }; }
  });

  ipcMain.handle('pick-files', async (_e, kind) => {
    const filters = kind === 'music'
      ? [{ name: 'Audio', extensions: ['mp3', 'm4a', 'wav', 'aac', 'ogg'] }]
      : [{ name: 'Video', extensions: ['mp4', 'mov', 'm4v', 'mkv', 'webm'] }];
    const r = await dialog.showOpenDialog(win, {
      properties: kind === 'music' ? ['openFile']
        : ['openFile', 'multiSelections'],
      filters,
    });
    return r.canceled ? [] : r.filePaths;
  });

  ipcMain.handle('pick-outdir', async () => {
    const r = await dialog.showOpenDialog(win,
      { properties: ['openDirectory', 'createDirectory'] });
    return r.canceled ? null : r.filePaths[0];
  });

  ipcMain.handle('transcribe', async (_e, { clips }) => {
    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'reels-'));
    const input = await concatClips(clips, work);
    return await new Promise((resolve) => {
      let transcript = null;
      engineProc = spawnEngine(
        [input, '--transcribe-only', '--out', path.join(work, 'tr')],
        (line) => {
          const ev = parseEvent(line);
          if (ev && ev.event === 'transcript') transcript = ev;
          else if (!line.startsWith('{')) send('engine-log', line);
        },
        (code) => {
          engineProc = null;
          if (code === 0 && transcript) {
            const text = fs.readFileSync(transcript.txt, 'utf8');
            resolve({ ok: true, text, words: transcript.words,
              joinedInput: input, workDir: work });
          } else {
            resolve({ ok: false,
              error: 'Transcription failed (see log).' });
          }
        });
    });
  });

  ipcMain.handle('edit', async (_e, job) => {
    // job: {clips, joinedInput, profile, script, music, broll, outDir}
    const work = job.workDir ||
      fs.mkdtempSync(path.join(os.tmpdir(), 'reels-'));
    let input = job.joinedInput;
    if (!input) input = await concatClips(job.clips, work);
    const outDir = job.outDir ||
      path.join(app.getPath('videos') || app.getPath('documents'),
        PRODUCT.name, new Date().toISOString().slice(0, 10) +
        '_' + path.parse(job.clips[0]).name);
    fs.mkdirSync(outDir, { recursive: true });
    const scriptFile = path.join(work, 'script.txt');
    fs.writeFileSync(scriptFile, job.script || '');
    const args = [input, '--profile', job.profile,
      '--script', scriptFile, '--out', outDir];
    if (job.music) args.push('--music', job.music);
    const env = {};
    if (job.broll && job.broll.length) {
      env.CLIP_CATALOGS = job.broll.join(':');
    }
    return await new Promise((resolve) => {
      let result = null;
      const saveEnv = engineEnv();
      const proc = spawn(enginePath() || 'python3',
        enginePath() ? args : ['-m', 'autoeditor', ...args], {
          env: { ...saveEnv, ...env },
          cwd: enginePath() ? undefined : path.join(__dirname, '..'),
        });
      engineProc = proc;
      let buf = '';
      const online = (line) => {
        const ev = parseEvent(line);
        if (ev && ev.event === 'result') result = ev;
        else if (!line.startsWith('{')) send('engine-log', line);
      };
      proc.stdout.on('data', (d) => {
        buf += d.toString();
        let i; while ((i = buf.indexOf('\n')) >= 0) {
          online(buf.slice(0, i)); buf = buf.slice(i + 1);
        }
      });
      proc.stderr.on('data', (d) => send('engine-log',
        d.toString().trimEnd()));
      proc.on('close', (code) => {
        engineProc = null;
        if (result) {
          resolve({ ok: true, ...result, exitCode: code });
        } else {
          resolve({ ok: false, exitCode: code,
            error: code === 0 ? 'Engine ended without a result event.'
              : 'The edit failed before quality checks (see log).' });
        }
      });
    });
  });

  ipcMain.handle('cancel', () => {
    if (engineProc) { engineProc.kill('SIGTERM'); engineProc = null; }
    return true;
  });

  ipcMain.handle('reveal', (_e, p) => { shell.showItemInFolder(p); });
  ipcMain.handle('open-path', (_e, p) => shell.openPath(p));
}

function send(ch, payload) { if (win) win.webContents.send(ch, payload); }

// ---------------------------------------------------------------- window
function createWindow() {
  win = new BrowserWindow({
    width: 980, height: 760, minWidth: 860, minHeight: 640,
    title: PRODUCT.name,
    backgroundColor: '#0b0d10',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(() => {
  setupIpc();
  createWindow();
  // auto-update: per-product channel on the shared GitHub Releases feed
  if (PACKAGED) {
    try {
      const { autoUpdater } = require('electron-updater');
      autoUpdater.channel = PRODUCT.channel;
      autoUpdater.checkForUpdatesAndNotify().catch(() => {});
    } catch (_) { /* updater optional in dev */ }
  }
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
