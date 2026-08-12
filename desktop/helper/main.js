/** AutoEditor: one-window local editor around the frozen render daemon. */
'use strict';

const { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, shell } =
  require('electron');
const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { stopProcessTree } = require('../lib/process-tree');
const { runEditingChat } = require('./lib/editing-harness');
const { analyzeMedia, extractFrames, probeVideo } = require('./lib/media-analysis');
const {
  artifactReviewPrompt,
  parseArtifactReview,
  reviewIssueText,
  reviewPasses,
} = require('./lib/artifact-quality');
const {
  MAX_JOURNAL_BYTES,
  createPreferenceJournal,
  appendPreferenceRecord,
  serializeForEncryption,
  parsePreferenceJournal,
  buildEditingContext,
} = require('./lib/preference-learning');
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
const MAX_ENCRYPTED_CONVERSATION_BYTES = 512 * 1024;
const MAX_ENCRYPTED_PREFERENCE_BYTES = MAX_JOURNAL_BYTES + 64 * 1024;
const PREFERENCE_POLICY_VERSION = '2026-08-12';
const MAX_LOG_LINE = 20000;
const MAX_LINE_BUFFER = 2 * 1024 * 1024;
const MAX_VISION_FRAME_BYTES = 1536 * 1024;
const VISION_TIMEOUT_MS = 30 * 60 * 1000;
const LOCAL_EVENTS = new Set([
  'local-progress', 'local-result', 'local-chat', 'local-error', 'local-canceled',
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

function conversationFile() {
  return path.join(app.getPath('userData'), 'conversation.enc');
}

function preferenceJournalFile() {
  return path.join(app.getPath('userData'), 'preference-journal.enc');
}

function preferenceProfileKeyFile() {
  return path.join(app.getPath('userData'), 'preference-profile-key.enc');
}

function readEncryptedObject(file, maxBytes = MAX_ENCRYPTED_SETTINGS_BYTES) {
  try {
    if (!safeStorage.isEncryptionAvailable() || !fs.existsSync(file)) {
      return null;
    }
    const stat = fs.statSync(file);
    if (!stat.isFile() || stat.size < 1 ||
        stat.size > maxBytes) return null;
    const plain = safeStorage.decryptString(fs.readFileSync(file));
    if (Buffer.byteLength(plain, 'utf8') > maxBytes) {
      return null;
    }
    const value = JSON.parse(plain);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    return value;
  } catch (_) { return null; }
}

function loadConversation() {
  const value = readEncryptedObject(
    conversationFile(), MAX_ENCRYPTED_CONVERSATION_BYTES);
  if (!value || value.schema !== 'autoeditor-chat/v1' ||
      !Array.isArray(value.messages) || value.messages.length > 500) return null;
  return value;
}

function saveConversation(value) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Your OS keystore is unavailable, so the conversation cannot be saved safely');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      value.schema !== 'autoeditor-chat/v1' || !Array.isArray(value.messages) ||
      value.messages.length > 500) throw new Error('Conversation state is invalid');
  const plain = JSON.stringify(value);
  if (Buffer.byteLength(plain, 'utf8') > MAX_ENCRYPTED_CONVERSATION_BYTES) {
    throw new Error('Conversation state is too large to save safely');
  }
  const sealed = safeStorage.encryptString(plain);
  const file = conversationFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, sealed, { mode: 0o600 });
  return { ok: true };
}

function loadPreferenceJournal({ strict = false } = {}) {
  const file = preferenceJournalFile();
  if (!fs.existsSync(file)) return createPreferenceJournal();
  try {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error('Your OS keystore is unavailable');
    }
    const stat = fs.statSync(file);
    if (!stat.isFile() || stat.size < 1 || stat.size > MAX_ENCRYPTED_PREFERENCE_BYTES) {
      throw new Error('the encrypted preference journal has an invalid size');
    }
    const plain = safeStorage.decryptString(fs.readFileSync(file));
    return parsePreferenceJournal(plain);
  } catch (error) {
    if (strict) {
      throw new Error(`The encrypted preference journal could not be verified: ${error.message}`);
    }
    return createPreferenceJournal();
  }
}

function replaceEncryptedFile(file, sealed) {
  const stamp = `${process.pid}.${Date.now()}`;
  const temporary = `${file}.${stamp}.tmp`;
  const backup = `${file}.${stamp}.bak`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(temporary, sealed, { mode: 0o600, flag: 'wx' });
  let backedUp = false;
  try {
    if (fs.existsSync(file)) {
      fs.renameSync(file, backup);
      backedUp = true;
    }
    fs.renameSync(temporary, file);
    if (backedUp) fs.rmSync(backup, { force: true });
  } catch (error) {
    if (!fs.existsSync(file) && backedUp && fs.existsSync(backup)) {
      try { fs.renameSync(backup, file); }
      catch (_) { /* retain the backup rather than destroying recoverable data */ }
    }
    throw error;
  } finally {
    if (fs.existsSync(temporary)) fs.rmSync(temporary, { force: true });
  }
}

function writePreferenceJournal(journal) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Your OS keystore is unavailable, so feedback cannot be saved safely');
  }
  const plain = serializeForEncryption(journal);
  const sealed = safeStorage.encryptString(plain);
  if (sealed.length > MAX_ENCRYPTED_PREFERENCE_BYTES) {
    throw new Error('The encrypted preference journal is too large');
  }
  const file = preferenceJournalFile();
  replaceEncryptedFile(file, sealed);
}

function preferenceProfileKey() {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Your OS keystore is unavailable, so preferences cannot be used safely');
  }
  const file = preferenceProfileKeyFile();
  if (fs.existsSync(file)) {
    try {
      const stat = fs.statSync(file);
      if (!stat.isFile() || stat.size < 1 || stat.size > 4096) throw new Error('invalid key file');
      const encoded = safeStorage.decryptString(fs.readFileSync(file));
      const key = Buffer.from(encoded, 'base64');
      if (key.length !== 32) throw new Error('invalid key length');
      return key;
    } catch (error) {
      throw new Error(`The encrypted preference profile key could not be verified: ${error.message}`);
    }
  }
  const key = crypto.randomBytes(32);
  const sealed = safeStorage.encryptString(key.toString('base64'));
  replaceEncryptedFile(file, sealed);
  return key;
}

function pseudonymousProfileHash(key, namespace, value = '') {
  return crypto.createHmac('sha256', key)
    .update(`autoeditor:${namespace}:v1\0${value}`, 'utf8').digest('hex');
}

function accountProfileHash(key) {
  return pseudonymousProfileHash(key, 'account-profile');
}

function projectProfileHash(key, sourceSha256, projectType) {
  return pseudonymousProfileHash(
    key, 'project-profile', `${sourceSha256}\0${projectType}`);
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

function isActiveAction(action) {
  return !!action && !action.canceled &&
    (activeChat === action || activeRender === action);
}

function activeRenderState() {
  if (!activeRender) return null;
  return {
    id: activeRender.id,
    stage: activeRender.stage,
    message: activeRender.message,
    startedAt: activeRender.startedAt,
    lastActivityAt: activeRender.lastActivityAt,
    measurable: activeRender.measurable,
    progress: activeRender.measurable ? activeRender.progress : null,
  };
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

function requestVision(framePaths, action, {
  mode = 'media-analysis', context = '',
} = {}) {
  if (!win || win.isDestroyed() || !isActiveAction(action)) {
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
    pendingVision.set(id, { action, mode, resolve, reject, timer });
    send('helper-vision-request', {
      id, images,
      mode: String(mode).slice(0, 80),
      context: String(context || '').replace(/\0/g, '').slice(0, 8000),
    });
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
  if (!pending || !isActiveAction(pending.action) ||
      typeof value.line !== 'string') return;
  processLocalEvent({
    event: 'local-progress',
    stage: pending.mode === 'artifact-quality'
      ? 'artifact-quality' : 'media-analysis',
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
  if (!isActiveAction(pending.action)) {
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

function sha256Text(value) {
  return crypto.createHash('sha256').update(String(value), 'utf8').digest('hex');
}

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(file);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('error', reject);
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

async function sourceManifestSha256(inputs) {
  if (!Array.isArray(inputs) || !inputs.length) {
    throw new Error('source lineage is unavailable');
  }
  const entries = [];
  for (const input of inputs) {
    const real = realFile(input);
    const stat = fs.statSync(real);
    entries.push({ bytes: stat.size, sha256: await sha256File(real) });
  }
  return sha256Text(stableJson({ schema: 'autoeditor-source-manifest/v1', entries }));
}

function planSha256(request) {
  return sha256Text(stableJson({
    schema: 'autoeditor-approved-plan/v1',
    projectType: request.projectType,
    proposal: request.proposal || null,
    creativeBrief: request.creativeBrief || '',
  }));
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

function rememberOutput(raw, outputDir, metadata = {}) {
  try {
    const real = realFile(raw);
    if (!isInside(outputDir, real)) return false;
    returnedOutputs.set(real, Object.freeze({
      path: raw,
      real,
      sourceSha256: metadata.sourceSha256 || '',
      sourceInputs: Object.freeze([...(metadata.sourceInputs || [])]),
      planSha256: metadata.planSha256 || '',
      priorResult: metadata.priorResult || '',
      projectType: metadata.projectType || 'custom',
      style: metadata.style || 'auto',
    }));
    return true;
  } catch (_) { return false; }
}

function rememberResult(event, outputDir, metadata = {}) {
  if (typeof event.output === 'string') rememberOutput(event.output, outputDir, metadata);
  if (event.outputs && typeof event.outputs === 'object' &&
      !Array.isArray(event.outputs)) {
    for (const value of Object.values(event.outputs)) {
      if (typeof value === 'string') rememberOutput(value, outputDir, metadata);
    }
  }
}

function editStyle(request) {
  const operation = request.proposal?.operations?.find((item) =>
    item?.op === 'set_edit_style' && typeof item.style === 'string');
  return operation?.style || request.projectType || 'auto';
}

async function approvedResultMetadata(action) {
  const context = action.resultContext || {};
  const sourceSha256 = context.sourceSha256 ||
    await sourceManifestSha256(context.sourceInputs || action.payload?.inputs);
  return {
    sourceSha256,
    sourceInputs: context.sourceInputs || action.payload?.inputs || [],
    planSha256: context.planSha256 || planSha256(action.payload || {}),
    priorResult: context.priorResult || '',
    projectType: action.payload?.projectType || 'custom',
    style: editStyle(action.payload || {}),
  };
}

function preferenceSplit(key, beforeOutputSha256, afterOutputSha256) {
  const assignment = crypto.createHmac('sha256', key)
    .update(`autoeditor-held-out:v1\0${beforeOutputSha256}\0${afterOutputSha256}`)
    .digest();
  return assignment[0] < 32 ? 'held-out' : 'training';
}

function normalizedFeedbackRequest(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('Feedback must be a plain object');
  }
  const allowed = new Set([
    'beforeResultPath', 'afterResultPath', 'preferred', 'defectCategories',
    'timecodes', 'rationale', 'consent', 'profileScope',
  ]);
  if (Object.keys(raw).some((key) => !allowed.has(key))) {
    throw new Error('Feedback has unsupported fields');
  }
  if (typeof raw.beforeResultPath !== 'string' ||
      typeof raw.afterResultPath !== 'string') {
    throw new Error('Choose both reviewed results');
  }
  if (raw.preferred !== 'before' && raw.preferred !== 'after') {
    throw new Error('Choose the version you prefer');
  }
  if (raw.profileScope !== 'project' && raw.profileScope !== 'account') {
    throw new Error('Choose whether this preference applies to the project or account');
  }
  if (!raw.consent || typeof raw.consent !== 'object' || Array.isArray(raw.consent) ||
      raw.consent.given !== true ||
      raw.consent.policyVersion !== PREFERENCE_POLICY_VERSION) {
    throw new Error('Explicit personalization consent is required');
  }
  return raw;
}

async function savePreferenceFeedback(raw) {
  const feedback = normalizedFeedbackRequest(raw);
  const beforeReal = realFile(feedback.beforeResultPath);
  const afterReal = realFile(feedback.afterResultPath);
  const before = returnedOutputs.get(beforeReal);
  const after = returnedOutputs.get(afterReal);
  if (!before || !after || beforeReal === afterReal) {
    throw new Error('Compare two different completed results from this session');
  }
  if (after.priorResult !== beforeReal) {
    throw new Error('Feedback is available only for a result and its direct revision');
  }
  if (!before.sourceSha256 || before.sourceSha256 !== after.sourceSha256 ||
      !before.planSha256 || !after.planSha256) {
    throw new Error('The reviewed result lineage could not be verified');
  }

  const [beforeOutputSha256, afterOutputSha256] = await Promise.all([
    sha256File(beforeReal), sha256File(afterReal),
  ]);
  const key = preferenceProfileKey();
  const accountHash = accountProfileHash(key);
  const projectHash = projectProfileHash(
    key, after.sourceSha256, after.projectType);
  const split = preferenceSplit(key, beforeOutputSha256, afterOutputSha256);
  const payload = {
    capturedAt: new Date().toISOString(),
    consent: {
      given: true,
      purpose: 'personalization',
      method: 'explicit-pairwise-feedback',
      policyVersion: PREFERENCE_POLICY_VERSION,
    },
    split,
    profile: {
      scope: feedback.profileScope,
      accountProfileSha256: accountHash,
      projectProfileSha256: projectHash,
    },
    context: {
      projectType: after.projectType,
      style: after.style,
      aspectRatio: ['short', 'commercial'].includes(after.projectType)
        ? '9:16' : '16:9',
      locale: String(app.getLocale() || 'en-US').slice(0, 120),
      tags: [],
    },
    artifacts: {
      sourceSha256: after.sourceSha256,
      before: {
        outputSha256: beforeOutputSha256,
        planSha256: before.planSha256,
        origin: 'system-output',
        reviewStatus: 'explicit-human-review',
      },
      after: {
        outputSha256: afterOutputSha256,
        planSha256: after.planSha256,
        origin: 'system-output',
        reviewStatus: 'explicit-human-review',
      },
    },
    preference: {
      preferred: feedback.preferred,
      strength: 5,
      rationale: feedback.rationale,
    },
    defectCategories: feedback.defectCategories,
    timecodes: feedback.timecodes,
  };
  const journal = loadPreferenceJournal({ strict: true });
  const next = appendPreferenceRecord(journal, payload);
  writePreferenceJournal(next);
  return {
    ok: true,
    split,
    recordSha256: next.records.at(-1).recordSha256,
  };
}

function preferenceEditingContext(sourceSha256, projectType) {
  if (!fs.existsSync(preferenceJournalFile())) return '';
  try {
    const key = preferenceProfileKey();
    return buildEditingContext(loadPreferenceJournal(), {
      accountProfileSha256: accountProfileHash(key),
      ...(sourceSha256 ? {
        projectProfileSha256: projectProfileHash(key, sourceSha256, projectType),
      } : {}),
      projectType,
    }, { limit: 4, maxChars: 1000 });
  } catch (_) {
    return '';
  }
}

function historyWithPreferenceContext(history, context) {
  if (!context) return history;
  const bounded = [...history, { role: 'assistant', content: context.slice(0, 1000) }];
  let characters = bounded.reduce((sum, entry) => sum + entry.content.length, 0);
  while (bounded.length > 12 || characters > 12000) {
    characters -= bounded.shift().content.length;
  }
  return bounded;
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

function rejectPendingVisionForAction(action, message) {
  for (const [id, pending] of pendingVision.entries()) {
    if (pending.action !== action) continue;
    pendingVision.delete(id);
    clearTimeout(pending.timer);
    pending.reject(new Error(message));
  }
}

function visibleArtifactPath(event, outputDir) {
  const candidates = [event.output];
  if (event.outputs && typeof event.outputs === 'object' &&
      !Array.isArray(event.outputs)) candidates.push(...Object.values(event.outputs));
  for (const candidate of candidates) {
    if (typeof candidate !== 'string') continue;
    try {
      const real = realFile(candidate);
      if (isInside(outputDir, real)) return real;
    } catch (_) { /* malformed daemon output is not reviewable */ }
  }
  throw new Error('the finished artifact is missing or outside the selected folder');
}

function markRenderFinished(action) {
  action.qaPending = false;
  action.terminal = true;
  if (activeRender === action) activeRender = null;
  send('helper-state', {
    running: !!activeRender, rendering: !!activeRender,
    chatting: !!activeChat, activeRender: activeRenderState(),
  });
}

function quarantineRejectedArtifact(artifact) {
  const parsed = path.parse(artifact);
  const stamp = `${Date.now()}.${process.pid}`;
  const rejected = path.join(
    parsed.dir, `${parsed.name}.VISION-REJECTED.${stamp}${parsed.ext}`);
  fs.renameSync(artifact, rejected);
  return rejected;
}

function stageArtifactForVision(artifact) {
  const parsed = path.parse(artifact);
  const pending = path.join(parsed.dir,
    `${parsed.name}.VISION-PENDING.${Date.now()}.${process.pid}${parsed.ext}`);
  fs.renameSync(artifact, pending);
  return { approved: artifact, pending };
}

function replaceEventArtifactPath(event, previous, next) {
  if (event.output === previous) event.output = next;
  if (event.outputs && typeof event.outputs === 'object' &&
      !Array.isArray(event.outputs)) {
    for (const [key, value] of Object.entries(event.outputs)) {
      if (value === previous) event.outputs[key] = next;
    }
  }
}

function retryRejectedRender(action, artifact, issue) {
  if (action.canceled || activeRender !== action) return false;
  const priorAttempts = Number(action.payload?.visionAttempt || 0);
  if (priorAttempts >= 1) return false;
  const rejected = quarantineRejectedArtifact(artifact);
  const correction = String(issue || '').replace(/\0/g, '').trim().slice(0, 2000);
  const payload = {
    ...action.payload,
    creativeBrief: [
      String(action.payload?.creativeBrief || '').trim(),
      'MANDATORY REPAIR FROM THE INDEPENDENT FINAL VISUAL QA:',
      correction,
      'Repair every reported defect. Do not return the same design unchanged.',
    ].filter(Boolean).join('\n\n').slice(0, 8000),
    visionAttempt: priorAttempts + 1,
  };
  delete payload.creativeBriefSha256;
  processLocalEvent({
    event: 'local-progress', stage: 'artifact-repair', measurable: false,
    message: 'The first draft failed visual QA. Re-editing it automatically...',
    line: `Quarantined ${path.basename(rejected)}. Repairing: ${correction}`,
  }, action);
  action.qaPending = false;
  if (activeRender === action) activeRender = null;
  const retryRequest = normalizeApplyRequest(payload);
  localProcess('--local-render', retryRequest, 'render', action.settings,
    { ...action.resultContext, planSha256: planSha256(retryRequest) });
  return true;
}

async function reviewArtifact(event, action) {
  let artifact = '';
  let staged = null;
  let work = '';
  try {
    artifact = visibleArtifactPath(event, action.outputDir);
    staged = stageArtifactForVision(artifact);
    replaceEventArtifactPath(event, artifact, staged.pending);
    artifact = staged.pending;
    work = fs.mkdtempSync(path.join(app.getPath('userData'), 'artifact-review-'));
    processLocalEvent({
      event: 'local-progress', stage: 'artifact-quality', measurable: false,
      message: 'Watching the finished video for visible quality problems...',
      line: 'Premium visual QA is inspecting the complete rendered artifact before release.',
    }, action);
    const runtime = runtimePaths();
    const probe = await probeVideo(artifact, runtime, (child) => {
      if (activeRender === action && !action.canceled) action.proc = child;
    });
    const frames = await extractFrames(
      artifact, probe, work, 8, runtime, (child) => {
        if (activeRender === action && !action.canceled) action.proc = child;
      });
    if (frames.length < 6) {
      throw new Error('premium visual QA could not sample the complete artifact');
    }
    const prompt = artifactReviewPrompt(action.payload?.creativeBrief || '');
    const raw = await requestVision(frames, action, {
      mode: 'artifact-quality', context: prompt,
    });
    const review = parseArtifactReview(raw);
    if (action.canceled || activeRender !== action) return;
    if (!reviewPasses(review)) {
      const issue = reviewIssueText(review);
      const receipt = path.join(action.outputDir, 'VISION_QA_REPORT.json');
      fs.writeFileSync(receipt, `${JSON.stringify({
        ...review, artifact: path.basename(artifact), reviewedAt: new Date().toISOString(),
      }, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
      if (retryRejectedRender(action, artifact, issue)) return;
      throw new Error(`Premium visual QA rejected the draft: ${issue}`);
    }
    event.visionQa = { pass: true, score: review.score };
    fs.renameSync(staged.pending, staged.approved);
    replaceEventArtifactPath(event, staged.pending, staged.approved);
    artifact = staged.approved;
    const metadata = await approvedResultMetadata(action);
    rememberResult(event, action.outputDir, metadata);
    send('helper-render', { ...event, actionId: action.id, kind: action.kind });
    markRenderFinished(action);
  } catch (error) {
    if (artifact && fs.existsSync(artifact) &&
        !/\.VISION-REJECTED(?:\.|$)/i.test(path.basename(artifact))) {
      try { quarantineRejectedArtifact(artifact); }
      catch (_) { /* failure is still reported and never registered as a result */ }
    }
    if (action.canceled) return;
    send('helper-render', {
      event: 'local-error', actionId: action.id, kind: 'render',
      stage: 'premium visual quality assurance',
      error: `${error.message || String(error)} The draft was not exposed as a finished video. Retry after the reported issue is corrected.`,
    });
    markRenderFinished(action);
  } finally {
    if (work) fs.rmSync(work, { recursive: true, force: true });
  }
}

function processLocalEvent(event, action) {
  if (!LOCAL_EVENTS.has(event.event)) return false;
  if (action.canceled) return true;
  action.lastActivityAt = Date.now();
  let visibleEvent = { ...event, actionId: action.id, kind: action.kind };
  if (event.event === 'local-canceled') {
    action.terminal = true;
  } else if (event.event === 'local-progress') {
    const mapped = engineProgress(event.line || event.stage || '');
    if (mapped) {
      visibleEvent = { ...visibleEvent, ...mapped };
    }
    const exact = event.measurable === true &&
      Number.isFinite(Number(event.progress ?? event.percent));
    if (exact) {
      action.measurable = true;
      action.progress = Math.max(0, Math.min(100,
        Math.round(Number(event.progress ?? event.percent))));
      visibleEvent = {
        ...visibleEvent, measurable: true, progress: action.progress,
      };
    } else if (mapped?.measurable === false || event.measurable === false) {
      action.measurable = false;
      action.progress = null;
    }
    action.stage = String(visibleEvent.stage || action.stage || 'working');
    action.message = String(visibleEvent.message || action.message || 'Working...');
  }
  if (event.event === 'local-result' && action.kind === 'render') {
    action.terminal = true;
    if (event.qaPass !== true) {
      try {
        const rejected = visibleArtifactPath(event, action.outputDir);
        if (!/\.UNVERIFIED(?:\.|$)/i.test(path.basename(rejected))) {
          quarantineRejectedArtifact(rejected);
        }
      } catch (_) { /* a missing failed artifact is already unavailable */ }
      visibleEvent = {
        ...visibleEvent, event: 'local-error',
        stage: 'built-in quality assurance',
        error: event.warning ||
          'Built-in quality assurance rejected the draft. It was not released.',
      };
    } else {
      action.qaPending = true;
      void reviewArtifact(event, action);
      return true;
    }
  } else if (event.event === 'local-chat' && action.kind === 'chat') {
    rememberProposal(event);
    rememberResearchSources(event);
    action.terminal = true;
  } else if (event.event === 'local-error') {
    action.terminal = true;
    visibleEvent = {
      ...visibleEvent, stage: event.stage || action.message || action.stage,
    };
  }
  send('helper-render', visibleEvent);
  return true;
}

function localProcess(mode, payload, kind, settings, resultContext = null) {
  const p = runtimePaths();
  const action = {
    id: ++actionSequence,
    kind,
    outputDir: kind === 'render' ? payload.outputDir : '',
    proc: null,
    terminal: false,
    canceled: false,
    progress: null,
    measurable: false,
    stage: kind === 'render' ? 'starting' : 'analysis',
    message: kind === 'render' ? 'Starting the local edit...' : 'Analyzing...',
    startedAt: Date.now(),
    lastActivityAt: Date.now(),
    qaPending: false,
    payload: kind === 'render' ? { ...payload } : null,
    settings: { ...settings },
    resultContext: kind === 'render' && resultContext
      ? { ...resultContext, sourceInputs: [...(resultContext.sourceInputs || [])] }
      : null,
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
    processLocalEvent({
      event: 'local-progress', stage: 'starting', measurable: false,
      message: 'Starting the local edit...',
    }, action);
  }

  const onLine = (line) => {
    action.lastActivityAt = Date.now();
    const event = parseEngineEvent(line);
    if (event && processLocalEvent(event, action)) return;
    if (!event) send('helper-log', {
      line: redact(line, settings), actionId: action.id, kind: action.kind,
    });
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
        event: 'local-error', actionId: action.id, kind: action.kind,
        stage: action.message || action.stage,
        error: `AutoEditor could not start: ${error.message}`,
      });
    }
  });
  child.on('close', (code) => {
    stdout.flush();
    stderr.flush();
    if (kind === 'render' && activeRender === action && !action.qaPending) activeRender = null;
    if (kind === 'chat' && activeChat === action) activeChat = null;
    if (!action.terminal && !action.canceled) {
      send('helper-render', {
        event: 'local-error', actionId: action.id, kind: action.kind,
        stage: action.message || action.stage,
        error: code === 0
          ? 'AutoEditor ended without returning a result'
          : `AutoEditor stopped before finishing (${code})`,
      });
    }
    send('helper-state', {
      running: !!activeRender, rendering: !!activeRender, chatting: !!activeChat,
      activeRender: activeRenderState(),
    });
  });
  child.stdin.end(`${JSON.stringify(payload)}\n`);
  send('helper-state', {
    running: !!activeRender, rendering: !!activeRender, chatting: !!activeChat,
    activeRender: activeRenderState(),
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
    settingsForLocalRender(settings), {
      sourceInputs: request.inputs,
      sourceSha256: '',
      planSha256: planSha256(request),
      priorResult: '',
    });
  return { ok: true };
}

function chatLocal(raw) {
  if (activeChat) throw new Error('DeepSeek is already answering');
  const request = normalizeChatRequest(raw);
  let videoPaths = [];
  let revisionMetadata = null;
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
    revisionMetadata = returnedOutputs.get(real);
  }
  const settings = requireSecureSettings();
  if (!settings.deepseekApiKey) {
    throw new Error('Add your DeepSeek API key before opening the edit chat');
  }
  const action = {
    id: ++actionSequence, kind: 'chat', outputDir: '', proc: null,
    terminal: false, canceled: false, progress: null, measurable: false,
    stage: 'analysis', message: 'Analyzing...',
    startedAt: Date.now(), lastActivityAt: Date.now(),
  };
  activeChat = action;
  send('helper-state', {
    running: !!activeRender, rendering: !!activeRender, chatting: true,
    activeRender: activeRenderState(),
  });
  (async () => {
    const sourceHashPromise = videoPaths.length
      ? sourceManifestSha256(videoPaths).catch(() => '')
      : Promise.resolve(revisionMetadata?.sourceSha256 || '');
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
    const sourceSha256 = await sourceHashPromise;
    const preferenceContext = preferenceEditingContext(
      sourceSha256, request.projectType);
    const event = await runEditingChat(
      {
        ...request,
        history: historyWithPreferenceContext(request.history, preferenceContext),
        mediaAnalysis,
        hasCompletedRender: !!raw?.resultPath,
      },
      settings.deepseekApiKey,
      (progress) => processLocalEvent(progress, action));
    if (mediaAnalysis?.videos?.length) {
      event.transcript = mediaAnalysis.videos
        .map((video) => String(video?.transcript || '').trim())
        .filter(Boolean).join('\n').slice(0, 30_000);
    }
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
      activeRender: activeRenderState(),
    });
  });
  return { ok: true };
}

function applyLocal(raw) {
  if (activeRender) throw new Error('An edit is already rendering');
  let translated = translateVideoPaths(raw);
  let revisionInput = '';
  let revisionMetadata = null;
  if (raw && raw.resultPath) {
    revisionInput = realFile(raw.resultPath);
    if (!returnedOutputs.has(revisionInput)) {
      throw new Error('That revision target is not from this AutoEditor session');
    }
    revisionMetadata = returnedOutputs.get(revisionInput);
    translated = { ...translated, videos: [revisionInput] };
    delete translated.inputs;
    delete translated.videoPaths;
    delete translated.clips;
  }
  const request = normalizeApplyRequest(translated, proposalWasReturned);
  if (revisionInput) {
    if (!selectedOutputDirs.has(fs.realpathSync.native(request.outputDir))) {
      throw new Error('Choose the output folder with the Choose button');
    }
  } else {
    requireDialogSelection(request);
  }
  const settings = requireReady();
  localProcess('--local-render', request, 'render',
    settingsForLocalRender(settings), {
      sourceInputs: revisionMetadata?.sourceInputs || request.inputs,
      sourceSha256: revisionMetadata?.sourceSha256 || '',
      planSha256: planSha256(request),
      priorResult: revisionInput,
    });
  return { ok: true };
}

async function cancelLocal() {
  const action = activeRender;
  if (!action) return { ok: true, canceled: false };
  action.canceled = true;
  activeRender = null;
  rejectPendingVisionForAction(action, 'local vision was canceled');
  await stopProcessTree(action.proc);
  send('helper-render', {
    event: 'local-canceled', actionId: action.id, kind: 'render',
    stage: 'canceled', line: 'Edit canceled',
  });
  send('helper-state', { running: false, rendering: false,
    chatting: !!activeChat, activeRender: null });
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

function openResult(raw, action = 'reveal') {
  if (typeof raw !== 'string') throw new Error('Result path must be a string');
  if (action !== 'open' && action !== 'reveal') {
    throw new Error('Result action must be open or reveal');
  }
  const real = realFile(raw);
  if (!returnedOutputs.has(real)) {
    throw new Error('That result is not from this AutoEditor session');
  }
  if (action === 'open') return shell.openPath(real);
  shell.showItemInFolder(real);
  return { ok: true, action };
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
      activeRender: activeRenderState(),
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
      conversation: screenshotMode ? null : loadConversation(),
    };
  });
  ipcMain.handle('helper:pick-videos', () => pickVideos());
  ipcMain.handle('helper:attach-dropped-videos', (_event, files) =>
    attachDroppedVideos(files));
  ipcMain.handle('helper:pick-output', () => pickOutput());
  ipcMain.handle('helper:save-settings', (_event, input) => saveSettings(input));
  ipcMain.handle('helper:save-conversation', (_event, input) =>
    saveConversation(input));
  ipcMain.handle('helper:save-preference-feedback', (_event, input) =>
    savePreferenceFeedback(input));
  ipcMain.handle('helper:render-local', (_event, input) => renderLocal(input));
  ipcMain.handle('helper:cancel-local', () => cancelLocal());
  ipcMain.handle('helper:chat-local', (_event, input) => chatLocal(input));
  ipcMain.handle('helper:apply-local', (_event, input) => applyLocal(input));
  ipcMain.handle('helper:open-result', (_event, resultPath, action) =>
    openResult(resultPath, action));
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
