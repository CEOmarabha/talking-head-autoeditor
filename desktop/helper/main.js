/** AutoEditor: one-window local editor around the frozen render daemon. */
'use strict';

const { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, shell } =
  require('electron');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { stopProcessTree } = require('../lib/process-tree');
const { runEditingChat } = require('./lib/editing-harness');
const { analyzeMedia } = require('./lib/media-analysis');
const {
  normalizeApplyRequest,
  normalizeChatRequest,
  normalizeLocalRequest,
  normalizeLocalSettings,
  normalizeOutputDir,
  normalizeResultPath,
  normalizeVideoPaths,
  parseEngineEvent,
  settingsForLocalRender,
  engineProgress,
} = require('./lib/local-render');

let win = null;
let activeRender = null;
let activeChat = null;
let actionSequence = 0;
let visionSequence = 0;
const pendingVision = new Map();
const returnedOutputs = new Map();
const returnedProposals = new Set();
const returnedResearchSources = new Set();
const selectedVideos = new Set();
const selectedOutputDirs = new Set();
const PACKAGED = app.isPackaged;
const RES = PACKAGED ? process.resourcesPath : path.join(__dirname, '../..');
const MIN_FREE_BYTES = 20 * 1024 * 1024 * 1024;
const MAX_ENCRYPTED_SETTINGS_BYTES = 128 * 1024;
const MAX_LOG_LINE = 20000;
const MAX_LINE_BUFFER = 2 * 1024 * 1024;
const MAX_VISION_FRAME_BYTES = 1536 * 1024;
const VISION_TIMEOUT_MS = 30 * 60 * 1000;
const LOCAL_EVENTS = new Set([
  'local-progress', 'local-result', 'local-chat', 'local-error',
]);
const VIDEO_EXTENSIONS = new Set(['.mp4', '.mov', '.m4v', '.mkv', '.webm']);
const PROVIDER_LINKS = Object.freeze({
  deepseekApi: 'https://platform.deepseek.com/api_keys',
  pexelsApi: 'https://www.pexels.com/api/',
  pixabayApi: 'https://pixabay.com/api/docs/',
  elevenApiKeys: 'https://elevenlabs.io/app/settings/api-keys',
  remotionDashboard: 'https://remotion.pro/dashboard',
});
const VISION_RUNTIME_FILES = Object.freeze({
  'ort-wasm-simd-threaded.asyncify.mjs': 'text/javascript; charset=utf-8',
  'ort-wasm-simd-threaded.asyncify.wasm': 'application/wasm',
  'ort-wasm-simd-threaded.mjs': 'text/javascript; charset=utf-8',
  'ort-wasm-simd-threaded.wasm': 'application/wasm',
});

protocol.registerSchemesAsPrivileged([{
  scheme: 'autoeditor-vision',
  privileges: {
    standard: true, secure: true, supportFetchAPI: true, corsEnabled: true,
  },
}]);

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
    visionDir: path.join(__dirname, 'vision'),
  };
}

function settingsFile() {
  return path.join(app.getPath('userData'), 'local-settings.enc');
}

function legacySetupFile() {
  return path.join(app.getPath('userData'), 'helper-setup.enc');
}

function readEncryptedObject(file) {
  try {
    if (!safeStorage.isEncryptionAvailable() || !fs.existsSync(file)) {
      return null;
    }
    const stat = fs.statSync(file);
    if (!stat.isFile() || stat.size < 1 ||
        stat.size > MAX_ENCRYPTED_SETTINGS_BYTES) return null;
    const plain = safeStorage.decryptString(fs.readFileSync(file));
    if (Buffer.byteLength(plain, 'utf8') > MAX_ENCRYPTED_SETTINGS_BYTES) {
      return null;
    }
    const value = JSON.parse(plain);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    return value;
  } catch (_) { return null; }
}

function writeSettings(settings) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Your OS keystore is unavailable, so API keys cannot be saved safely');
  }
  const normalized = normalizeLocalSettings(settings);
  const sealed = safeStorage.encryptString(JSON.stringify(normalized));
  const file = settingsFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, sealed, { mode: 0o600 });
  return normalized;
}

function legacyKey(legacy, names) {
  for (const name of names) {
    const value = legacy[name];
    if (typeof value === 'string' && value.length <= 8192) return value;
  }
  return '';
}

function migrateLegacySettings() {
  const legacy = readEncryptedObject(legacySetupFile());
  if (!legacy) return {};
  const candidate = {
    deepseekApiKey: legacyKey(legacy, ['deepseekApiKey', 'deepseekKey']),
    pexelsApiKey: legacyKey(legacy, ['pexelsApiKey', 'pexelsKey']),
    pixabayApiKey: legacyKey(legacy, ['pixabayApiKey', 'pixabayKey']),
    elevenLabsApiKey: legacyKey(legacy, ['elevenLabsApiKey', 'elevenKey']),
    remotionKey: legacyKey(legacy, ['remotionKey']),
  };
  let migrated;
  try { migrated = normalizeLocalSettings(candidate); }
  catch (_) { return {}; }
  const hasValue = Object.values(migrated).some(Boolean);
  if (!hasValue) return {};
  try { return writeSettings(migrated); }
  catch (_) { return {}; }
}

function loadSettings() {
  const stored = readEncryptedObject(settingsFile());
  if (stored) {
    try { return normalizeLocalSettings(stored); }
    catch (_) { return {}; }
  }
  return migrateLegacySettings();
}

function settingsPatch(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error('Settings must be an object');
  }
  const patched = { ...input };
  if (!Object.prototype.hasOwnProperty.call(patched, 'remotionKey') &&
      Object.prototype.hasOwnProperty.call(patched, 'remotionLicenseKey')) {
    patched.remotionKey = patched.remotionLicenseKey;
  }
  delete patched.remotionLicenseKey;
  return normalizeLocalSettings(patched);
}

function settingsPresence(settings) {
  return {
    deepseekApiKey: !!settings.deepseekApiKey,
    pexelsApiKey: !!settings.pexelsApiKey,
    pixabayApiKey: !!settings.pixabayApiKey,
    elevenLabsApiKey: !!settings.elevenLabsApiKey,
    remotionKey: !!settings.remotionKey,
  };
}

function saveSettings(input) {
  const merged = { ...loadSettings(), ...settingsPatch(input) };
  const settings = writeSettings(merged);
  return { ok: true, settings: settingsPresence(settings) };
}

function commandOutput(command, args) {
  const result = spawnSync(command, args, {
    windowsHide: true, encoding: 'utf8', timeout: 15000,
  });
  return result.status === 0 ? `${result.stdout || ''}\n${result.stderr || ''}` : '';
}

function preflight({ checkKeystore = true, checkDisk = true } = {}) {
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
    localVision: fs.existsSync(path.join(p.visionDir, 'vision-worker.bundle.js')) &&
      Object.keys(VISION_RUNTIME_FILES).every((file) =>
        fs.existsSync(path.join(p.visionDir, file))),
    // Artifact smoke and screenshot capture are noninteractive. On macOS an
    // ad-hoc acceptance build can block on its first Keychain lookup. Saving
    // settings and starting any local action still require the OS keystore.
    keystore: checkKeystore ? safeStorage.isEncryptionAvailable() : true,
    disk: !checkDisk,
    codecs: false,
    filters: false,
  };
  if (checkDisk) {
    try {
      const stat = fs.statfsSync(app.getPath('userData'));
      checks.disk = Number(stat.bavail) * Number(stat.bsize) >= MIN_FREE_BYTES;
    } catch (_) { checks.disk = false; }
  }
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

function daemonEnv(settings) {
  const p = runtimePaths();
  const env = { ...process.env };
  for (const key of ['DEEPSEEK_API_KEY', 'KEY_WRAP_SECRET', 'ADMIN_TOKEN',
    'WORKER_TOKEN', 'AUTOEDITOR_WEB_API', 'PEXELS_API_KEY', 'PIXABAY_API_KEY',
    'ELEVENLABS_API_KEY', 'REMOTION_LICENSE_KEY', 'OPENAI_API_KEY',
    'ANTHROPIC_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
    'TELEGRAM_HOME_CHANNEL']) delete env[key];
  Object.assign(env, {
    DEEPSEEK_API_KEY: settings.deepseekApiKey || '',
    PEXELS_API_KEY: settings.pexelsApiKey || '',
    PIXABAY_API_KEY: settings.pixabayApiKey || '',
    ELEVENLABS_API_KEY: settings.elevenLabsApiKey || '',
    REMOTION_LICENSE_KEY: settings.remotionKey || '',
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
    AUTOEDITOR_REQUIRE_HYPERFRAMES: '1',
    AUTOEDITOR_REQUIRE_REMOTION: '1',
    SSL_CERT_FILE: p.caBundle,
    REQUESTS_CA_BUNDLE: p.caBundle,
    HF_HUB_OFFLINE: '1',
    TRANSFORMERS_OFFLINE: '1',
    AUTOEDITOR_PACKAGED: '1',
    AUTOEDITOR_PROGRESS_JSON: '1',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    WORK_DIR: path.join(app.getPath('userData'), 'work'),
  });
  return env;
}

function send(channel, value) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, value);
}

function registerVisionProtocol() {
  const root = runtimePaths().visionDir;
  protocol.handle('autoeditor-vision', (request) => {
    try {
      const url = new URL(request.url);
      const file = url.pathname.replace(/^\//, '');
      const contentType = VISION_RUNTIME_FILES[file];
      if (request.method !== 'GET' || url.hostname !== 'runtime' ||
          url.search || !contentType || file.includes('/') || file.includes('\\')) {
        return new Response('Not found', { status: 404 });
      }
      const target = path.join(root, file);
      const stat = fs.statSync(target);
      if (!stat.isFile() || stat.size < 1 || stat.size > 32 * 1024 * 1024) {
        return new Response('Not found', { status: 404 });
      }
      return new Response(fs.readFileSync(target), { headers: {
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'public, max-age=31536000, immutable',
        'Content-Type': contentType,
        'Cross-Origin-Resource-Policy': 'cross-origin',
      } });
    } catch (_) {
      return new Response('Not found', { status: 404 });
    }
  });
}

function readVisionFrame(file) {
  const handle = fs.openSync(file, 'r');
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size < 4 || before.size > MAX_VISION_FRAME_BYTES) {
      throw new Error('a local vision frame had an invalid size');
    }
    const data = Buffer.alloc(before.size);
    if (fs.readSync(handle, data, 0, before.size, 0) !== before.size) {
      throw new Error('a local vision frame changed while it was read');
    }
    const after = fs.fstatSync(handle);
    if (after.size !== before.size || after.mtimeMs !== before.mtimeMs ||
        after.dev !== before.dev || after.ino !== before.ino) {
      throw new Error('a local vision frame changed while it was read');
    }
    if (data[0] !== 0xff || data[1] !== 0xd8 ||
        data[data.length - 2] !== 0xff || data[data.length - 1] !== 0xd9) {
      throw new Error('a local vision frame was not a complete JPEG');
    }
    return `data:image/jpeg;base64,${data.toString('base64')}`;
  } finally {
    fs.closeSync(handle);
  }
}

function requestVision(framePaths, action) {
  if (!win || win.isDestroyed() || activeChat !== action || action.canceled) {
    return Promise.reject(new Error('the local vision window is unavailable'));
  }
  if (!Array.isArray(framePaths) || framePaths.length < 1 || framePaths.length > 8) {
    return Promise.reject(new Error('local vision requires between 1 and 8 frames'));
  }
  const images = framePaths.map(readVisionFrame);
  const id = ++visionSequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingVision.delete(id);
      reject(new Error('the local vision model exceeded 30 minutes'));
    }, VISION_TIMEOUT_MS);
    pendingVision.set(id, { action, resolve, reject, timer });
    send('helper-vision-request', { id, images });
  });
}

function rejectPendingVision(message) {
  for (const pending of pendingVision.values()) {
    clearTimeout(pending.timer);
    pending.reject(new Error(message));
  }
  pendingVision.clear();
}

function fromMainRenderer(event) {
  return !!win && !win.isDestroyed() && event.sender === win.webContents &&
    (!event.senderFrame || event.senderFrame === win.webContents.mainFrame);
}

function handleVisionProgress(event, value) {
  if (!fromMainRenderer(event) || !value || typeof value !== 'object' ||
      Array.isArray(value) || !Number.isSafeInteger(value.id)) return;
  const pending = pendingVision.get(value.id);
  if (!pending || activeChat !== pending.action || pending.action.canceled ||
      typeof value.line !== 'string') return;
  processLocalEvent({
    event: 'local-progress', stage: 'media-analysis',
    line: value.line.replace(/\0/g, '').trim().slice(0, 1000),
  }, pending.action);
}

function handleVisionResult(event, value) {
  if (!fromMainRenderer(event) || !value || typeof value !== 'object' ||
      Array.isArray(value) || !Number.isSafeInteger(value.id)) return;
  const pending = pendingVision.get(value.id);
  if (!pending) return;
  pendingVision.delete(value.id);
  clearTimeout(pending.timer);
  if (activeChat !== pending.action || pending.action.canceled) {
    pending.reject(new Error('local vision was canceled'));
    return;
  }
  if (value.status === 'complete' && typeof value.result === 'string') {
    const result = value.result.replace(/\0/g, '').trim().slice(0, 5000);
    if (result) {
      pending.resolve(result);
      return;
    }
  }
  const detail = typeof value.error === 'string'
    ? value.error.replace(/\0/g, '').trim().slice(0, 1000)
    : 'the local vision model returned an invalid result';
  pending.reject(new Error(detail || 'the local vision model stopped'));
}

function redact(line, settings) {
  let clean = String(line || '');
  for (const value of Object.values(settings)) {
    if (typeof value === 'string' && value.length >= 4) {
      clean = clean.split(value).join('[redacted]');
    }
  }
  return clean.slice(0, MAX_LOG_LINE);
}

function lineReader(onLine) {
  let buffer = '';
  return {
    push(chunk) {
      buffer += chunk.toString('utf8');
      if (buffer.length > MAX_LINE_BUFFER && !buffer.includes('\n')) {
        onLine(buffer.slice(0, MAX_LOG_LINE));
        buffer = '';
      }
      let index;
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index).replace(/\r$/, '');
        buffer = buffer.slice(index + 1);
        if (line) onLine(line);
      }
    },
    flush() {
      const line = buffer.replace(/\r$/, '');
      buffer = '';
      if (line) onLine(line);
    },
  };
}

function stableJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
}

function realFile(file) {
  return fs.realpathSync.native(normalizeResultPath(file));
}

function isInside(directory, file) {
  const root = fs.realpathSync.native(directory);
  const relative = path.relative(root, file);
  return relative !== '' && relative !== '..' &&
    !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function rememberOutput(raw, outputDir) {
  try {
    const real = realFile(raw);
    if (!isInside(outputDir, real)) return false;
    returnedOutputs.set(real, raw);
    return true;
  } catch (_) { return false; }
}

function rememberResult(event, outputDir) {
  if (typeof event.output === 'string') rememberOutput(event.output, outputDir);
  if (event.outputs && typeof event.outputs === 'object' &&
      !Array.isArray(event.outputs)) {
    for (const value of Object.values(event.outputs)) {
      if (typeof value === 'string') rememberOutput(value, outputDir);
    }
  }
}

function rememberProposal(event) {
  if (event.canApply !== true || !event.proposal ||
      typeof event.proposal !== 'object' || Array.isArray(event.proposal) ||
      !Array.isArray(event.proposal.operations) ||
      event.proposal.operations.length < 1) return;
  try {
    const encoded = stableJson(event.proposal);
    if (encoded.length <= 100000) returnedProposals.add(encoded);
  } catch (_) { /* malformed daemon output is not applicable */ }
}

function rememberResearchSources(event) {
  if (!Array.isArray(event.sources)) return;
  for (const source of event.sources.slice(0, 12)) {
    if (!source || typeof source !== 'object' || Array.isArray(source) ||
        typeof source.url !== 'string' || source.url.length > 2048) continue;
    try {
      const parsed = new URL(source.url);
      if (parsed.protocol === 'https:' && !parsed.username && !parsed.password) {
        returnedResearchSources.add(source.url);
      }
    } catch (_) { /* malformed research source is never opened */ }
  }
}

function proposalWasReturned(proposal) {
  if (!returnedProposals.has(stableJson(proposal))) {
    throw new Error('That edit proposal is no longer available. Ask DeepSeek again');
  }
  return true;
}

function processLocalEvent(event, action) {
  if (!LOCAL_EVENTS.has(event.event)) return false;
  if (action.canceled) return true;
  let visibleEvent = event;
  if (event.event === 'local-progress') {
    const mapped = engineProgress(event.line || event.stage || '');
    if (mapped && mapped.progress > action.progress) {
      action.progress = mapped.progress;
      visibleEvent = { ...event, ...mapped };
    }
  }
  if (event.event === 'local-result' && action.kind === 'render') {
    rememberResult(event, action.outputDir);
    action.terminal = true;
  } else if (event.event === 'local-chat' && action.kind === 'chat') {
    rememberProposal(event);
    rememberResearchSources(event);
    action.terminal = true;
  } else if (event.event === 'local-error') {
    action.terminal = true;
  }
  send('helper-render', visibleEvent);
  return true;
}

function localProcess(mode, payload, kind, settings) {
  const p = runtimePaths();
  const action = {
    id: ++actionSequence,
    kind,
    outputDir: kind === 'render' ? payload.outputDir : '',
    proc: null,
    terminal: false,
    canceled: false,
    progress: 0,
  };
  const child = spawn(p.daemon, [mode], {
    env: daemonEnv(settings), windowsHide: true, cwd: p.root,
    stdio: ['pipe', 'pipe', 'pipe'],
    detached: process.platform !== 'win32',
  });
  child.__autoeditorProcessGroup = process.platform !== 'win32';
  action.proc = child;
  if (kind === 'render') activeRender = action;
  else activeChat = action;
  if (kind === 'render') {
    action.progress = 1;
    send('helper-render', {
      event: 'local-progress', progress: 1,
      message: 'Starting the local edit...',
    });
  }

  const onLine = (line) => {
    const event = parseEngineEvent(line);
    if (event && processLocalEvent(event, action)) return;
    if (!event) send('helper-log', redact(line, settings));
  };
  const stdout = lineReader(onLine);
  const stderr = lineReader(onLine);
  child.stdout.on('data', (chunk) => stdout.push(chunk));
  child.stderr.on('data', (chunk) => stderr.push(chunk));
  child.stdin.on('error', () => { /* child error/close owns the visible result */ });
  child.on('error', (error) => {
    if (!action.terminal && !action.canceled) {
      action.terminal = true;
      send('helper-render', {
        event: 'local-error', error: `AutoEditor could not start: ${error.message}`,
      });
    }
  });
  child.on('close', (code) => {
    stdout.flush();
    stderr.flush();
    if (kind === 'render' && activeRender === action) activeRender = null;
    if (kind === 'chat' && activeChat === action) activeChat = null;
    if (!action.terminal && !action.canceled) {
      send('helper-render', {
        event: 'local-error',
        error: code === 0
          ? 'AutoEditor ended without returning a result'
          : `AutoEditor stopped before finishing (${code})`,
      });
    }
    send('helper-state', {
      running: !!activeRender, rendering: !!activeRender, chatting: !!activeChat,
    });
  });
  child.stdin.end(`${JSON.stringify(payload)}\n`);
  send('helper-state', {
    running: !!activeRender, rendering: !!activeRender, chatting: !!activeChat,
  });
  return action;
}

function requireSecureSettings() {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Your OS keystore is unavailable, so AutoEditor cannot safely load API keys');
  }
  return loadSettings();
}

function requireReady() {
  const settings = requireSecureSettings();
  const ready = preflight();
  if (!ready.ok) {
    throw new Error('A built-in editing component is missing or this computer has less than 20 GB free');
  }
  return settings;
}

function requireDialogSelection(request) {
  for (const input of request.inputs) {
    const real = fs.realpathSync.native(input);
    if (!selectedVideos.has(real)) {
      throw new Error('Choose every input video with the Select videos button');
    }
  }
  const output = fs.realpathSync.native(request.outputDir);
  if (!selectedOutputDirs.has(output)) {
    throw new Error('Choose the output folder with the Choose button');
  }
}

function translateVideoPaths(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) ||
      !Object.prototype.hasOwnProperty.call(raw, 'videoPaths')) return raw;
  if (['inputs', 'videos', 'clips'].some((key) =>
    Object.prototype.hasOwnProperty.call(raw, key))) {
    throw new Error('Video inputs were supplied more than once');
  }
  const translated = { ...raw, videos: raw.videoPaths };
  delete translated.videoPaths;
  return translated;
}

function renderLocal(raw) {
  if (activeRender) throw new Error('An edit is already rendering');
  const request = normalizeLocalRequest(translateVideoPaths(raw));
  requireDialogSelection(request);
  const settings = requireReady();
  localProcess('--local-render', request, 'render',
    settingsForLocalRender(settings));
  return { ok: true };
}

function chatLocal(raw) {
  if (activeChat) throw new Error('DeepSeek is already answering');
  const request = normalizeChatRequest(raw);
  let videoPaths = [];
  if (raw && Object.prototype.hasOwnProperty.call(raw, 'videoPaths')) {
    videoPaths = normalizeVideoPaths(raw.videoPaths);
    for (const video of videoPaths) {
      if (!selectedVideos.has(fs.realpathSync.native(video))) {
        throw new Error('Attach every video with the picker or by dragging it into AutoEditor');
      }
    }
  }
  if (raw && raw.resultPath) {
    const real = realFile(raw.resultPath);
    if (!returnedOutputs.has(real)) {
      throw new Error('That result is not from this AutoEditor session');
    }
  }
  const settings = requireSecureSettings();
  if (!settings.deepseekApiKey) {
    throw new Error('Add your DeepSeek API key before opening the edit chat');
  }
  const action = {
    id: ++actionSequence, kind: 'chat', outputDir: '', proc: null,
    terminal: false, canceled: false, progress: 0,
  };
  activeChat = action;
  send('helper-state', {
    running: !!activeRender, rendering: !!activeRender, chatting: true,
  });
  (async () => {
    let mediaAnalysis = null;
    if (videoPaths.length) {
      try {
        mediaAnalysis = await analyzeMedia({
          videoPaths,
          runtime: runtimePaths(),
          env: daemonEnv(settingsForLocalRender(settings)),
          cacheRoot: path.join(app.getPath('userData'), 'media-analysis-cache'),
          describeFrames: (frames) => requestVision(frames, action),
          emit: (line) => processLocalEvent({
            event: 'local-progress', stage: 'media-analysis', line,
          }, action),
          onChild: (child) => {
            if (activeChat === action && !action.canceled) action.proc = child;
          },
        });
      } catch (error) {
        const detail = String(error?.message || error).slice(0, 1000);
        processLocalEvent({
          event: 'local-progress', stage: 'media-analysis',
          line: `Local media analysis stopped safely: ${detail}`,
        }, action);
        mediaAnalysis = {
          schema: 'autoeditor-local-media-analysis/v2',
          videos: [], originalVideosUploaded: false, error: detail,
        };
      }
    }
    if (activeChat !== action || action.canceled) return;
    action.proc = null;
    const event = await runEditingChat(
      { ...request, mediaAnalysis }, settings.deepseekApiKey,
      (progress) => processLocalEvent(progress, action));
    processLocalEvent(event, action);
  })().catch((error) => {
    processLocalEvent({
      event: 'local-error',
      error: `DeepSeek stopped safely: ${error.message || String(error)}`,
    }, action);
  }).finally(() => {
    if (activeChat === action) activeChat = null;
    send('helper-state', {
      running: !!activeRender, rendering: !!activeRender, chatting: false,
    });
  });
  return { ok: true };
}

function applyLocal(raw) {
  if (activeRender) throw new Error('An edit is already rendering');
  const request = normalizeApplyRequest(
    translateVideoPaths(raw), proposalWasReturned);
  requireDialogSelection(request);
  const settings = requireReady();
  localProcess('--local-render', request, 'render',
    settingsForLocalRender(settings));
  return { ok: true };
}

async function cancelLocal() {
  const action = activeRender;
  if (!action) return { ok: true, canceled: false };
  action.canceled = true;
  activeRender = null;
  await stopProcessTree(action.proc);
  send('helper-render', {
    event: 'local-progress', stage: 'canceled', line: 'Edit canceled',
  });
  send('helper-state', { running: false, rendering: false,
    chatting: !!activeChat });
  return { ok: true, canceled: true };
}

async function pickVideos() {
  const result = await dialog.showOpenDialog(win, {
    title: 'Choose videos to edit',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Videos', extensions: ['mp4', 'mov', 'm4v', 'mkv', 'webm'] }],
  });
  if (result.canceled) return [];
  const videos = normalizeVideoPaths(result.filePaths);
  for (const video of videos) {
    if (!VIDEO_EXTENSIONS.has(path.extname(video).toLowerCase())) {
      throw new Error('Choose MP4, MOV, M4V, MKV, or WebM video files');
    }
    selectedVideos.add(fs.realpathSync.native(video));
  }
  return videos;
}

function attachDroppedVideos(raw) {
  const videos = normalizeVideoPaths(raw);
  const accepted = [];
  for (const video of videos) {
    if (!VIDEO_EXTENSIONS.has(path.extname(video).toLowerCase())) {
      throw new Error('Drop MP4, MOV, M4V, MKV, or WebM video files');
    }
    const real = fs.realpathSync.native(video);
    selectedVideos.add(real);
    accepted.push(real);
  }
  return accepted;
}

function openResearchSource(url) {
  if (typeof url !== 'string' || !returnedResearchSources.has(url)) {
    throw new Error('That research source is not from this AutoEditor session');
  }
  return shell.openExternal(url);
}

async function pickOutput() {
  const result = await dialog.showOpenDialog(win, {
    title: 'Choose where to save the finished video',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled) return '';
  const output = normalizeOutputDir(result.filePaths[0]);
  selectedOutputDirs.add(fs.realpathSync.native(output));
  return output;
}

function openResult(raw) {
  if (typeof raw !== 'string') throw new Error('Result path must be a string');
  const real = realFile(raw);
  if (!returnedOutputs.has(real)) {
    throw new Error('That result is not from this AutoEditor session');
  }
  shell.showItemInFolder(real);
  return { ok: true };
}

function setupIpc() {
  ipcMain.on('helper:vision-progress', handleVisionProgress);
  ipcMain.on('helper:vision-result', handleVisionResult);
  ipcMain.handle('helper:state', () => {
    const screenshotMode = !!process.env.AUTOEDITOR_SCREENSHOT_PATH;
    const settings = screenshotMode ? {} : loadSettings();
    return {
      configured: true,
      running: !!activeRender,
      rendering: !!activeRender,
      chatting: !!activeChat,
      settings: settingsPresence(settings),
      capabilities: {
        deepseek: !!settings.deepseekApiKey,
        pexels: !!settings.pexelsApiKey,
        pixabay: !!settings.pixabayApiKey,
        elevenlabs: !!settings.elevenLabsApiKey,
        remotion: true,
        hyperframes: true,
      },
      preflight: preflight({ checkKeystore: !screenshotMode }),
      version: app.getVersion(),
      platform: process.platform,
    };
  });
  ipcMain.handle('helper:pick-videos', () => pickVideos());
  ipcMain.handle('helper:attach-dropped-videos', (_event, files) =>
    attachDroppedVideos(files));
  ipcMain.handle('helper:pick-output', () => pickOutput());
  ipcMain.handle('helper:save-settings', (_event, input) => saveSettings(input));
  ipcMain.handle('helper:render-local', (_event, input) => renderLocal(input));
  ipcMain.handle('helper:cancel-local', () => cancelLocal());
  ipcMain.handle('helper:chat-local', (_event, input) => chatLocal(input));
  ipcMain.handle('helper:apply-local', (_event, input) => applyLocal(input));
  ipcMain.handle('helper:open-result', (_event, resultPath) => openResult(resultPath));
  ipcMain.handle('helper:open-research-source', (_event, url) =>
    openResearchSource(url));
  ipcMain.handle('helper:notices', () => shell.openPath(runtimePaths().notices));
  ipcMain.handle('helper:open', (_event, key) => {
    if (typeof key !== 'string' || !PROVIDER_LINKS[key]) {
      throw new Error('That help link is not allowed');
    }
    return shell.openExternal(PROVIDER_LINKS[key]);
  });
}

function smokeTest() {
  const settings = {
    deepseekApiKey: '', pexelsApiKey: '', pixabayApiKey: '',
    elevenLabsApiKey: '', remotionKey: 'free-license',
  };
  const p = runtimePaths();
  const child = spawnSync(p.daemon, [], {
    env: { ...daemonEnv(settings), AUTOEDITOR_HELPER_SMOKE_TEST: '1' },
    windowsHide: true, encoding: 'utf8', timeout: 30000,
  });
  const creative = spawnSync(p.daemon, [], {
    env: { ...daemonEnv(settings), AUTOEDITOR_CREATIVE_SMOKE_TEST: '1' },
    windowsHide: true, encoding: 'utf8', timeout: 360000,
  });
  // Artifact smoke validates the installed runtime on small hosted runners.
  // Interactive actions retain the 20 GiB gate.
  const checks = preflight({ checkKeystore: false, checkDisk: false });
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
    width: 900, height: capturePath ? 1200 : 760,
    minWidth: 700, minHeight: 620, show: !capturePath,
    title: 'AutoEditor', backgroundColor: '#0b0d10',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  if (capturePath) {
    win.webContents.once('did-finish-load', async () => {
      await new Promise((resolve) => setTimeout(resolve, 800));
      const height = await win.webContents.executeJavaScript(
        'Math.min(4000, document.documentElement.scrollHeight)');
      win.setContentSize(900, Math.max(1200, height));
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
  registerVisionProtocol();
  setupIpc();
  createWindow();
});

app.on('before-quit', () => {
  rejectPendingVision('AutoEditor is closing');
  if (activeRender) stopProcessTree(activeRender.proc);
  if (activeChat?.proc) stopProcessTree(activeChat.proc);
});
app.on('window-all-closed', () => app.quit());

module.exports = { runtimePaths };
