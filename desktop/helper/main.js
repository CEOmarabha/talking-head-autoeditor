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
const MAX_ENCRYPTED_CONVERSATION_BYTES = 512 * 1024;
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

function conversationFile() {
  return path.join(app.getPath('userData'), 'conversation.enc');
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
    }ßž7¶‰žËkºwµç\°€¡•ÉÉ½È¤€ôøì4(€€€¥˜€ ……Ñ¥½¸¹Ñ•Éµ¥¹…°€˜˜€……Ñ¥½¸¹…¹•±•¤ì4(€€€€€…Ñ¥½¸¹Ñ•Éµ¥¹…°€ôÑÉÕ”ì4(€€€€€Í•¹ ¡•±Á•ÈµÉ•¹‘•Èœ°ì4(€€€€€€€•Ù•¹Ðè€±½…°µ•ÉÉ½Èœ°…Ñ¥½¹%è…Ñ¥½¸¹¥°­¥¹è…Ñ¥½¸¹­¥¹°4(€€€€€€€ÍÑ…”è…Ñ¥½¸¹µ•ÍÍ…”ñð…Ñ¥½¸¹ÍÑ…”°4(€€€€€€€•ÉÉ½ÈèÕÑ½‘¥Ñ½È½Õ±¹½ÐÍÑ…ÉÐè€‘í•ÉÉ½È¹µ•ÍÍ…•õ€°4(€€€€€ô¤ì4(€€€ô4(€ô¤ì4(€¡¥±¹½¸ ±½Í”œ°€¡½‘”¤€ôøì4(€€€ÍÑ‘½ÕÐ¹™±ÕÍ  ¤ì4(€€€ÍÑ‘•ÉÈ¹™±ÕÍ  ¤ì4(€€€¥˜€¡­¥¹€ôôô€É•¹‘•Èœ€˜˜…Ñ¥Ù•I•¹‘•È€ôôô…Ñ¥½¸¤…Ñ¥Ù•I•¹‘•È€ô¹Õ±°ì4(€€€¥˜€¡­¥¹€ôôô€¡…Ðœ€˜˜…Ñ¥Ù•¡…Ð€ôôô…Ñ¥½¸¤…Ñ¥Ù•¡…Ð€ô¹Õ±°ì4(€€€¥˜€ ……Ñ¥½¸¹Ñ•Éµ¥¹…°€˜˜€……Ñ¥½¸¹…¹•±•¤ì4(€€€€€Í•¹ ¡•±Á•ÈµÉ•¹‘•Èœ°ì4(€€€€€€€•Ù•¹Ðè€±½…°µ•ÉÉ½Èœ°…Ñ¥½¹%è…Ñ¥½¸¹¥°­¥¹è…Ñ¥½¸¹­¥¹°4(€€€€€€€ÍÑ…”è…Ñ¥½¸¹µ•ÍÍ…”ñð…Ñ¥½¸¹ÍÑ…”°4(€€€€€€€•ÉÉ½Èè½‘”€ôôô€À4(€€€€€€€€€€ü€ÕÑ½‘¥Ñ½È•¹‘•Ý¥Ñ¡½ÕÐÉ•ÑÕÉ¹¥¹œ„É•ÍÕ±Ðœ4(€€€€€€€€€€èÕÑ½‘¥Ñ½ÈÍÑ½ÁÁ•‰•™½É”™¥¹¥Í¡¥¹œ€ ‘í½‘•ô¥€°4(€€€€€ô¤ì4(€€€ô4(€€€Í•¹ ¡•±Á•ÈµÍÑ…Ñ”œ°ì4(€€€€€ÉÕ¹¹¥¹œè€„……Ñ¥Ù•I•¹‘•È°É•¹‘•É¥¹œè€„……Ñ¥Ù•I•¹‘•È°¡…ÑÑ¥¹œè€„……Ñ¥Ù•¡…Ð°4(€€€€€…Ñ¥Ù•I•¹‘•Èè…Ñ¥Ù•I•¹‘•ÉMÑ…Ñ” ¤°4(€€€ô¤ì4(€ô¤ì4(€¡¥±¹ÍÑ‘¥¸¹•¹¡€‘í)M=8¹ÍÑÉ¥¹¥™ä¡Á…å±½…¥õq¹€¤ì4(€Í•¹ ¡•±Á•ÈµÍÑ…Ñ”œ°ì4(€€€ÉÕ¹¹¥¹œè€„……Ñ¥Ù•I•¹‘•È°É•¹‘•É¥¹œè€„……Ñ¥Ù•I•¹‘•È°¡…ÑÑ¥¹œè€„……Ñ¥Ù•¡…Ð°4(€€€…Ñ¥Ù•I•¹‘•Èè…Ñ¥Ù•I•¹‘•ÉMÑ…Ñ” ¤°4(€ô¤ì4(€É•ÑÕÉ¸…Ñ¥½¸ì4)ô4(4)™Õ¹Ñ¥½¸É•ÅÕ¥É•M•ÕÉ•M•ÑÑ¥¹Ì ¤ì4(€¥˜€ …Í…™•MÑ½É…”¹¥Í¹ÉåÁÑ¥½¹Ù…¥±…‰±” ¤¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È e½ÕÈ=L­•åÍÑ½É”¥ÌÕ¹…Ù…¥±…‰±”°Í¼ÕÑ½‘¥Ñ½È…¹¹½ÐÍ…™•±ä±½…A$­•åÌœ¤ì4(€ô4(€É•ÑÕÉ¸±½…‘M•ÑÑ¥¹Ì ¤ì4)ô4(4)™Õ¹Ñ¥½¸É•ÅÕ¥É•I•…‘ä ¤ì4(€½¹ÍÐÍ•ÑÑ¥¹Ì€ôÉ•ÅÕ¥É•M•ÕÉ•M•ÑÑ¥¹Ì ¤ì4(€½¹ÍÐÉ•…‘ä€ôÁÉ•™±¥¡Ð ¤ì4(€¥˜€ …É•…‘ä¹½¬¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È ‰Õ¥±Ðµ¥¸•‘¥Ñ¥¹œ½µÁ½¹•¹Ð¥Ìµ¥ÍÍ¥¹œ½ÈÑ¡¥Ì½µÁÕÑ•È¡…Ì±•ÍÌÑ¡…¸€ÈÀ™É•”œ¤ì4(€ô4(€É•ÑÕÉ¸Í•ÑÑ¥¹Ìì4)ô4(4)™Õ¹Ñ¥½¸É•ÅÕ¥É•¥…±½M•±•Ñ¥½¸¡É•ÅÕ•ÍÐ¤ì4(€™½È€¡½¹ÍÐ¥¹ÁÕÐ½˜É•ÅÕ•ÍÐ¹¥¹ÁÕÑÌ¤ì4(€€€½¹ÍÐÉ•…°€ô™Ì¹É•…±Á…Ñ¡Må¹Œ¹¹…Ñ¥Ù”¡¥¹ÁÕÐ¤ì4(€€€¥˜€ …Í•±•Ñ•‘Y¥‘•½Ì¹¡…Ì¡É•…°¤¤ì4(€€€€€Ñ¡É½Ü¹•ÜÉÉ½È ¡½½Í”•Ù•Éä¥¹ÁÕÐÙ¥‘•¼Ý¥Ñ Ñ¡”M•±•ÐÙ¥‘•½Ì‰ÕÑÑ½¸œ¤ì4(€€€ô4(€ô4(€½¹ÍÐ½ÕÑÁÕÐ€ô™Ì¹É•…±Á…Ñ¡Må¹Œ¹¹…Ñ¥Ù”¡É•ÅÕ•ÍÐ¹½ÕÑÁÕÑ¥È¤ì4(€¥˜€ …Í•±•Ñ•‘=ÕÑÁÕÑ¥ÉÌ¹¡…Ì¡½ÕÑÁÕÐ¤¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È ¡½½Í”Ñ¡”½ÕÑÁÕÐ™½±‘•ÈÝ¥Ñ Ñ¡”¡½½Í”‰ÕÑÑ½¸œ¤ì4(€ô4)ô4(4)™Õ¹Ñ¥½¸ÑÉ…¹Í±…Ñ•Y¥‘•½A…Ñ¡Ì¡É…Ü¤ì4(€¥˜€ …É…ÜñðÑåÁ•½˜É…Ü€„ôô€½‰©•ÐœñðÉÉ…ä¹¥ÍÉÉ…ä¡É…Ü¤ñð4(€€€€€€…=‰©•Ð¹ÁÉ½Ñ½ÑåÁ”¹¡…Í=Ý¹AÉ½Á•ÉÑä¹…±°¡É…Ü°€Ù¥‘•½A…Ñ¡Ìœ¤¤É•ÑÕÉ¸É…Üì4(€¥˜€¡l¥¹ÁÕÑÌœ°€Ù¥‘•½Ìœ°€±¥ÁÌt¹Í½µ” ¡­•ä¤€ôø4(€€€=‰©•Ð¹ÁÉ½Ñ½ÑåÁ”¹¡…Í=Ý¹AÉ½Á•ÉÑä¹…±°¡É…Ü°­•ä¤¤¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È Y¥‘•¼¥¹ÁÕÑÌÝ•É”ÍÕÁÁ±¥•µ½É”Ñ¡…¸½¹”œ¤ì4(€ô4(€½¹ÍÐÑÉ…¹Í±…Ñ•€ôì€¸¸¹É…Ü°Ù¥‘•½ÌèÉ…Ü¹Ù¥‘•½A…Ñ¡Ìôì4(€‘•±•Ñ”ÑÉ…¹Í±…Ñ•¹Ù¥‘•½A…Ñ¡Ìì4(€É•ÑÕÉ¸ÑÉ…¹Í±…Ñ•ì4)ô4(4)™Õ¹Ñ¥½¸É•¹‘•É1½…°¡É…Ü¤ì4(€¥˜€¡…Ñ¥Ù•I•¹‘•È¤Ñ¡É½Ü¹•ÜÉÉ½È ¸•‘¥Ð¥Ì…±É•…‘äÉ•¹‘•É¥¹œœ¤ì4(€½¹ÍÐÉ•ÅÕ•ÍÐ€ô¹½Éµ…±¥é•1½…±I•ÅÕ•ÍÐ¡ÑÉ…¹Í±…Ñ•Y¥‘•½A…Ñ¡Ì¡É…Ü¤¤ì4(€É•ÅÕ¥É•¥…±½M•±•Ñ¥½¸¡É•ÅÕ•ÍÐ¤ì4(€½¹ÍÐÍ•ÑÑ¥¹Ì€ôÉ•ÅÕ¥É•I•…‘ä ¤ì4(€±½…±AÉ½•ÍÌ œ´µ±½…°µÉ•¹‘•Èœ°É•ÅÕ•ÍÐ°€É•¹‘•Èœ°4(€€€Í•ÑÑ¥¹Í½É1½…±I•¹‘•È¡Í•ÑÑ¥¹Ì¤¤ì4(€É•ÑÕÉ¸ì½¬èÑÉÕ”ôì4)ô4(4)™Õ¹Ñ¥½¸¡…Ñ1½…°¡É…Ü¤ì4(€¥˜€¡…Ñ¥Ù•¡…Ð¤Ñ¡É½Ü¹•ÜÉÉ½È ••ÁM••¬¥Ì…±É•…‘ä…¹ÍÝ•É¥¹œœ¤ì4(€½¹ÍÐÉ•ÅÕ•ÍÐ€ô¹½Éµ…±¥é•¡…ÑI•ÅÕ•ÍÐ¡É…Ü¤ì4(€±•ÐÙ¥‘•½A…Ñ¡Ì€ômtì4(€¥˜€¡É…Ü€˜˜=‰©•Ð¹ÁÉ½Ñ½ÑåÁ”¹¡…Í=Ý¹AÉ½Á•ÉÑä¹…±°¡É…Ü°€Ù¥‘•½A…Ñ¡Ìœ¤¤ì4(€€€Ù¥‘•½A…Ñ¡Ì€ô¹½Éµ…±¥é•Y¥‘•½A…Ñ¡Ì¡É…Ü¹Ù¥‘•½A…Ñ¡Ì¤ì4(€€€™½È€¡½¹ÍÐÙ¥‘•¼½˜Ù¥‘•½A…Ñ¡Ì¤ì4(€€€€€¥˜€ …Í•±•Ñ•‘Y¥‘•½Ì¹¡…Ì¡™Ì¹É•…±Á…Ñ¡Må¹Œ¹¹…Ñ¥Ù”¡Ù¥‘•¼¤¤¤ì4(€€€€€€€Ñ¡É½Ü¹•ÜÉÉ½È ÑÑ… •Ù•ÉäÙ¥‘•¼Ý¥Ñ Ñ¡”Á¥­•È½È‰ä‘É…¥¹œ¥Ð¥¹Ñ¼ÕÑ½‘¥Ñ½Èœ¤ì4(€€€€€ô4(€€€ô4(€ô4(€¥˜€¡É…Ü€˜˜É…Ü¹É•ÍÕ±ÑA…Ñ ¤ì4(€€€½¹ÍÐÉ•…°€ôÉ•…±¥±”¡É…Ü¹É•ÍÕ±ÑA…Ñ ¤ì4(€€€¥˜€ …É•ÑÕÉ¹•‘=ÕÑÁÕÑÌ¹¡…Ì¡É•…°¤¤ì4(€€€€€Ñ¡É½Ü¹•ÜÉÉ½È Q¡…ÐÉ•ÍÕ±Ð¥Ì¹½Ð™É½´Ñ¡¥ÌÕÑ½‘¥Ñ½ÈÍ•ÍÍ¥½¸œ¤ì4(€€€ô4(€ô4(€½¹ÍÐÍ•ÑÑ¥¹Ì€ôÉ•ÅÕ¥É•M•ÕÉ•M•ÑÑ¥¹Ì ¤ì4(€¥˜€ …Í•ÑÑ¥¹Ì¹‘••ÁÍ••­Á¥-•ä¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È ‘å½ÕÈ••ÁM••¬A$­•ä‰•™½É”½Á•¹¥¹œÑ¡”•‘¥Ð¡…Ðœ¤ì4(€ô4(€½¹ÍÐ…Ñ¥½¸€ôì4(€€€¥è€¬­…Ñ¥½¹M•ÅÕ•¹”°­¥¹è€¡…Ðœ°½ÕÑÁÕÑ¥Èè€œœ°ÁÉ½Œè¹Õ±°°4(€€€Ñ•Éµ¥¹…°è™…±Í”°…¹•±•è™…±Í”°ÁÉ½É•ÍÌè¹Õ±°°µ•…ÍÕÉ…‰±”è™…±Í”°4(€€€ÍÑ…”è€…¹…±åÍ¥Ìœ°µ•ÍÍ…”è€¹…±åé¥¹œ¸¸¸œ°4(€€€ÍÑ…ÉÑ•‘Ðè…Ñ”¹¹½Ü ¤°±…ÍÑÑ¥Ù¥ÑåÐè…Ñ”¹¹½Ü ¤°4(€ôì4(€…Ñ¥Ù•¡…Ð€ô…Ñ¥½¸ì4(€Í•¹ ¡•±Á•ÈµÍÑ…Ñ”œ°ì4(€€€ÉÕ¹¹¥¹œè€„……Ñ¥Ù•I•¹‘•È°É•¹‘•É¥¹œè€„……Ñ¥Ù•I•¹‘•È°¡…ÑÑ¥¹œèÑÉÕ”°4(€€€…Ñ¥Ù•I•¹‘•Èè…Ñ¥Ù•I•¹‘•ÉMÑ…Ñ” ¤°4(€ô¤ì4(€€¡…Íå¹Œ€ ¤€ôøì4(€€€±•Ðµ•‘¥…¹…±åÍ¥Ì€ô¹Õ±°ì4(€€€¥˜€¡Ù¥‘•½A…Ñ¡Ì¹±•¹Ñ ¤ì4(€€€€€ÑÉäì4(€€€€€€€µ•‘¥…¹…±åÍ¥Ì€ô…Ý…¥Ð…¹…±åé•5•‘¥„¡ì4(€€€€€€€€€Ù¥‘•½A…Ñ¡Ì°4(€€€€€€€€€ÉÕ¹Ñ¥µ”èÉÕ¹Ñ¥µ•A…Ñ¡Ì ¤°4(€€€€€€€€€•¹Øè‘…•µ½¹¹Ø¡Í•ÑÑ¥¹Í½É1½…±I•¹‘•È¡Í•ÑÑ¥¹Ì¤¤°4(€€€€€€€€€…¡•I½½ÐèÁ…Ñ ¹©½¥¸¡…ÁÀ¹•ÑA…Ñ  ÕÍ•É…Ñ„œ¤°€µ•‘¥„µ…¹…±åÍ¥Ìµ…¡”œ¤°4(€€€€€€€€€‘•ÍÉ¥‰•É…µ•Ìè€¡™É…µ•Ì¤€ôøÉ•ÅÕ•ÍÑY¥Í¥½¸¡™É…µ•Ì°…Ñ¥½¸¤°4(€€€€€€€€€•µ¥Ðè€¡±¥¹”¤€ôøÁÉ½•ÍÍ1½…±Ù•¹Ð¡ì4(€€€€€€€€€€€•Ù•¹Ðè€±½…°µÁÉ½É•ÍÌœ°ÍÑ…”è€µ•‘¥„µ…¹…±åÍ¥Ìœ°±¥¹”°4(€€€€€€€€€ô°…Ñ¥½¸¤°4(€€€€€€€€€½¹¡¥±è€¡¡¥±¤€ôøì4(€€€€€€€€€€€¥˜€¡…Ñ¥Ù•¡…Ð€ôôô…Ñ¥½¸€˜˜€……Ñ¥½¸¹…¹•±•¤…Ñ¥½¸¹ÁÉ½Œ€ô¡¥±ì4(€€€€€€€€€ô°4(€€€€€€€ô¤ì4(€€€€€ô…Ñ €¡•ÉÉ½È¤ì4(€€€€€€€½¹ÍÐ‘•Ñ…¥°€ôMÑÉ¥¹œ¡•ÉÉ½Èü¹µ•ÍÍ…”ñð•ÉÉ½È¤¹Í±¥” À°€ÄÀÀÀ¤ì4(€€€€€€€ÁÉ½•ÍÍ1½…±Ù•¹Ð¡ì4(€€€€€€€€€•Ù•¹Ðè€±½…°µÁÉ½É•ÍÌœ°ÍÑ…”è€µ•‘¥„µ…¹…±åÍ¥Ìœ°4(€€€€€€€€€±¥¹”è1½…°µ•‘¥„…¹…±åÍ¥ÌÍÑ½ÁÁ•Í…™•±äè€‘í‘•Ñ…¥±õ€°4(€€€€€€€ô°…Ñ¥½¸¤ì4(€€€€€€€µ•‘¥…¹…±åÍ¥Ì€ôì4(€€€€€€€€€Í¡•µ„è€…ÕÑ½•‘¥Ñ½Èµ±½…°µµ•‘¥„µ…¹…±åÍ¥Ì½ØÈœ°4(€€€€€€€€€Ù¥‘•½Ìèmt°½É¥¥¹…±Y¥‘•½ÍUÁ±½…‘•è™…±Í”°•ÉÉ½Èè‘•Ñ…¥°°4(€€€€€€€ôì4(€€€€€ô4(€€€ô4(€€€¥˜€¡…Ñ¥Ù•¡…Ð€„ôô…Ñ¥½¸ñð…Ñ¥½¸¹…¹•±•¤É•ÑÕÉ¸ì4(€€€…Ñ¥½¸¹ÁÉ½Œ€ô¹Õ±°ì4(€€€½¹ÍÐ•Ù•¹Ð€ô…Ý…¥ÐÉÕ¹‘¥Ñ¥¹¡…Ð 4(€€€€€ì€¸¸¹É•ÅÕ•ÍÐ°µ•‘¥…¹…±åÍ¥Ì°¡…Í½µÁ±•Ñ•‘I•¹‘•Èè€„…É…Üü¹É•ÍÕ±ÑA…Ñ ô°4(€€€€€Í•ÑÑ¥¹Ì¹‘••ÁÍ••­Á¥-•ä°4(€€€€€€¡ÁÉ½É•ÍÌ¤€ôøÁÉ½•ÍÍ1½…±Ù•¹Ð¡ÁÉ½É•ÍÌ°…Ñ¥½¸¤¤ì4(€€€ÁÉ½•ÍÍ1½…±Ù•¹Ð¡•Ù•¹Ð°…Ñ¥½¸¤ì4(€ô¤ ¤¹…Ñ  ¡•ÉÉ½È¤€ôøì4(€€€ÁÉ½•ÍÍ1½…±Ù•¹Ð¡ì4(€€€€€•Ù•¹Ðè€±½…°µ•ÉÉ½Èœ°4(€€€€€•ÉÉ½Èè••ÁM••¬ÍÑ½ÁÁ•Í…™•±äè€‘í•ÉÉ½È¹µ•ÍÍ…”ñðMÑÉ¥¹œ¡•ÉÉ½È¥õ€°4(€€€ô°…Ñ¥½¸¤ì4(€ô¤¹™¥¹…±±ä  ¤€ôøì4(€€€¥˜€¡…Ñ¥Ù•¡…Ð€ôôô…Ñ¥½¸¤…Ñ¥Ù•¡…Ð€ô¹Õ±°ì4(€€€Í•¹ ¡•±Á•ÈµÍÑ…Ñ”œ°ì4(€€€€€ÉÕ¹¹¥¹œè€„……Ñ¥Ù•I•¹‘•È°É•¹‘•É¥¹œè€„……Ñ¥Ù•I•¹‘•È°¡…ÑÑ¥¹œè™…±Í”°4(€€€€€…Ñ¥Ù•I•¹‘•Èè…Ñ¥Ù•I•¹‘•ÉMÑ…Ñ” ¤°4(€€€ô¤ì4(€ô¤ì4(€É•ÑÕÉ¸ì½¬èÑÉÕ”ôì4)ô4(4)™Õ¹Ñ¥½¸…ÁÁ±å1½…°¡É…Ü¤ì4(€¥˜€¡…Ñ¥Ù•I•¹‘•È¤Ñ¡É½Ü¹•ÜÉÉ½È ¸•‘¥Ð¥Ì…±É•…‘äÉ•¹‘•É¥¹œœ¤ì4(€±•ÐÑÉ…¹Í±…Ñ•€ôÑÉ…¹Í±…Ñ•Y¥‘•½A…Ñ¡Ì¡É…Ü¤ì4(€±•ÐÉ•Ù¥Í¥½¹%¹ÁÕÐ€ô€œœì4(€¥˜€¡É…Ü€˜˜É…Ü¹É•ÍÕ±ÑA…Ñ ¤ì4(€€€É•Ù¥Í¥½¹%¹ÁÕÐ€ôÉ•…±¥±”¡É…Ü¹É•ÍÕ±ÑA…Ñ ¤ì4(€€€¥˜€ …É•ÑÕÉ¹•‘=ÕÑÁÕÑÌ¹¡…Ì¡É•Ù¥Í¥½¹%¹ÁÕÐ¤¤ì4(€€€€€Ñ¡É½Ü¹•ÜÉÉ½È Q¡…ÐÉ•Ù¥Í¥½¸Ñ…É•Ð¥Ì¹½Ð™É½´Ñ¡¥ÌÕÑ½‘¥Ñ½ÈÍ•ÍÍ¥½¸œ¤ì4(€€€ô4(€€€ÑÉ…¹Í±…Ñ•€ôì€¸¸¹ÑÉ…¹Í±…Ñ•°Ù¥‘•½ÌèmÉ•Ù¥Í¥½¹%¹ÁÕÑtôì4(€€€‘•±•Ñ”ÑÉ…¹Í±…Ñ•¹¥¹ÁÕÑÌì4(€€€‘•±•Ñ”ÑÉ…¹Í±…Ñ•¹Ù¥‘•½A…Ñ¡Ìì4(€€€‘•±•Ñ”ÑÉ…¹Í±…Ñ•¹±¥ÁÌì4(€ô4(€½¹ÍÐÉ•ÅÕ•ÍÐ€ô¹½Éµ…±¥é•ÁÁ±åI•ÅÕ•ÍÐ¡ÑÉ…¹Í±…Ñ•°ÁÉ½Á½Í…±]…ÍI•ÑÕÉ¹•¤ì4(€¥˜€¡É•Ù¥Í¥½¹%¹ÁÕÐ¤ì4(€€€¥˜€ …Í•±•Ñ•‘=ÕÑÁÕÑ¥ÉÌ¹¡…Ì¡™Ì¹É•…±Á…Ñ¡Må¹Œ¹¹…Ñ¥Ù”¡É•ÅÕ•ÍÐ¹½ÕÑÁÕÑ¥È¤¤¤ì4(€€€€€Ñ¡É½Ü¹•ÜÉÉ½È ¡½½Í”Ñ¡”½ÕÑÁÕÐ™½±‘•ÈÝ¥Ñ Ñ¡”¡½½Í”‰ÕÑÑ½¸œ¤ì4(€€€ô4(€ô•±Í”ì4(€€€É•ÅÕ¥É•¥…±½M•±•Ñ¥½¸¡É•ÅÕ•ÍÐ¤ì4(€ô4(€½¹ÍÐÍ•ÑÑ¥¹Ì€ôÉ•ÅÕ¥É•I•…‘ä ¤ì4(€±½…±AÉ½•ÍÌ œ´µ±½…°µÉ•¹‘•Èœ°É•ÅÕ•ÍÐ°€É•¹‘•Èœ°4(€€€Í•ÑÑ¥¹Í½É1½…±I•¹‘•È¡Í•ÑÑ¥¹Ì¤¤ì4(€É•ÑÕÉ¸ì½¬èÑÉÕ”ôì4)ô4(4)…Íå¹Œ™Õ¹Ñ¥½¸…¹•±1½…° ¤ì4(€½¹ÍÐ…Ñ¥½¸€ô…Ñ¥Ù•I•¹‘•Èì4(€¥˜€ ……Ñ¥½¸¤É•ÑÕÉ¸ì½¬èÑÉÕ”°…¹•±•è™…±Í”ôì4(€…Ñ¥½¸¹…¹•±•€ôÑÉÕ”ì4(€…Ñ¥Ù•I•¹‘•È€ô¹Õ±°ì4(€…Ý…¥ÐÍÑ½ÁAÉ½•ÍÍQÉ•”¡…Ñ¥½¸¹ÁÉ½Œ¤ì4(€Í•¹ ¡•±Á•ÈµÉ•¹‘•Èœ°ì4(€€€•Ù•¹Ðè€±½…°µÁÉ½É•ÍÌœ°…Ñ¥½¹%è…Ñ¥½¸¹¥°­¥¹è€É•¹‘•Èœ°4(€€€ÍÑ…”è€…¹•±•œ°±¥¹”è€‘¥Ð…¹•±•œ°4(€ô¤ì4(€Í•¹ ¡•±Á•ÈµÍÑ…Ñ”œ°ìÉÕ¹¹¥¹œè™…±Í”°É•¹‘•É¥¹œè™…±Í”°4(€€€¡…ÑÑ¥¹œè€„……Ñ¥Ù•¡…Ð°…Ñ¥Ù•I•¹‘•Èè¹Õ±°ô¤ì4(€É•ÑÕÉ¸ì½¬èÑÉÕ”°…¹•±•èÑÉÕ”ôì4)ô4(4)…Íå¹Œ™Õ¹Ñ¥½¸Á¥­Y¥‘•½Ì ¤ì4(€½¹ÍÐÉ•ÍÕ±Ð€ô…Ý…¥Ð‘¥…±½œ¹Í¡½Ý=Á•¹¥…±½œ¡Ý¥¸°ì4(€€€Ñ¥Ñ±”è€¡½½Í”Ù¥‘•½ÌÑ¼•‘¥Ðœ°4(€€€ÁÉ½Á•ÉÑ¥•Ìèl½Á•¹¥±”œ°€µÕ±Ñ¥M•±•Ñ¥½¹Ìt°4(€€€™¥±Ñ•ÉÌèmì¹…µ”è€Y¥‘•½Ìœ°•áÑ•¹Í¥½¹ÌèlµÀÐœ°€µ½Øœ°€´ÑØœ°€µ­Øœ°€Ý•‰´tõt°4(€ô¤ì4(€¥˜€¡É•ÍÕ±Ð¹…¹•±•¤É•ÑÕÉ¸mtì4(€½¹ÍÐÙ¥‘•½Ì€ô¹½Éµ…±¥é•Y¥‘•½A…Ñ¡Ì¡É•ÍÕ±Ð¹™¥±•A…Ñ¡Ì¤ì4(€™½È€¡½¹ÍÐÙ¥‘•¼½˜Ù¥‘•½Ì¤ì4(€€€¥˜€ …Y%=}aQ9M%=9L¹¡…Ì¡Á…Ñ ¹•áÑ¹…µ”¡Ù¥‘•¼¤¹Ñ½1½Ý•É…Í” ¤¤¤ì4(€€€€€Ñ¡É½Ü¹•ÜÉÉ½È ¡½½Í”5@Ð°5=X°4ÑX°5-X°½È]•‰4Ù¥‘•¼™¥±•Ìœ¤ì4(€€€ô4(€€€Í•±•Ñ•‘Y¥‘•½Ì¹…‘¡™Ì¹É•…±Á…Ñ¡Må¹Œ¹¹…Ñ¥Ù”¡Ù¥‘•¼¤¤ì4(€ô4(€É•ÑÕÉ¸Ù¥‘•½Ìì4)ô4(4)™Õ¹Ñ¥½¸…ÑÑ…¡É½ÁÁ•‘Y¥‘•½Ì¡É…Ü¤ì4(€½¹ÍÐÙ¥‘•½Ì€ô¹½Éµ…±¥é•Y¥‘•½A…Ñ¡Ì¡É…Ü¤ì4(€½¹ÍÐ…•ÁÑ•€ômtì4(€™½È€¡½¹ÍÐÙ¥‘•¼½˜Ù¥‘•½Ì¤ì4(€€€¥˜€ …Y%=}aQ9M%=9L¹¡…Ì¡Á…Ñ ¹•áÑ¹…µ”¡Ù¥‘•¼¤¹Ñ½1½Ý•É…Í” ¤¤¤ì4(€€€€€Ñ¡É½Ü¹•ÜÉÉ½È É½À5@Ð°5=X°4ÑX°5-X°½È]•‰4Ù¥‘•¼™¥±•Ìœ¤ì4(€€€ô4(€€€½¹ÍÐÉ•…°€ô™Ì¹É•…±Á…Ñ¡Må¹Œ¹¹…Ñ¥Ù”¡Ù¥‘•¼¤ì4(€€€Í•±•Ñ•‘Y¥‘•½Ì¹…‘¡É•…°¤ì4(€€€…•ÁÑ•¹ÁÕÍ ¡É•…°¤ì4(€ô4(€É•ÑÕÉ¸…•ÁÑ•ì4)ô4(4)™Õ¹Ñ¥½¸½Á•¹I•Í•…É¡M½ÕÉ”¡ÕÉ°¤ì4(€¥˜€¡ÑåÁ•½˜ÕÉ°€„ôô€ÍÑÉ¥¹œœñð€…É•ÑÕÉ¹•‘I•Í•…É¡M½ÕÉ•Ì¹¡…Ì¡ÕÉ°¤¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È Q¡…ÐÉ•Í•…É Í½ÕÉ”¥Ì¹½Ð™É½´Ñ¡¥ÌÕÑ½‘¥Ñ½ÈÍ•ÍÍ¥½¸œ¤ì4(€ô4(€É•ÑÕÉ¸Í¡•±°¹½Á•¹áÑ•É¹…°¡ÕÉ°¤ì4)ô4(4)…Íå¹Œ™Õ¹Ñ¥½¸Á¥­=ÕÑÁÕÐ ¤ì4(€½¹ÍÐÉ•ÍÕ±Ð€ô…Ý…¥Ð‘¥…±½œ¹Í¡½Ý=Á•¹¥…±½œ¡Ý¥¸°ì4(€€€Ñ¥Ñ±”è€¡½½Í”Ý¡•É”Ñ¼Í…Ù”Ñ¡”™¥¹¥Í¡•Ù¥‘•¼œ°4(€€€ÁÉ½Á•ÉÑ¥•Ìèl½Á•¹¥É•Ñ½Éäœ°€É•…Ñ•¥É•Ñ½Éät°4(€ô¤ì4(€¥˜€¡É•ÍÕ±Ð¹…¹•±•¤É•ÑÕÉ¸€œœì4(€½¹ÍÐ½ÕÑÁÕÐ€ô¹½Éµ…±¥é•=ÕÑÁÕÑ¥È¡É•ÍÕ±Ð¹™¥±•A…Ñ¡ÍlÁt¤ì4(€Í•±•Ñ•‘=ÕÑÁÕÑ¥ÉÌ¹…‘¡™Ì¹É•…±Á…Ñ¡Må¹Œ¹¹…Ñ¥Ù”¡½ÕÑÁÕÐ¤¤ì4(€É•ÑÕÉ¸½ÕÑÁÕÐì4)ô4(4)™Õ¹Ñ¥½¸½Á•¹I•ÍÕ±Ð¡É…Ü°…Ñ¥½¸€ô€É•Ù•…°œ¤ì4(€¥˜€¡ÑåÁ•½˜É…Ü€„ôô€ÍÑÉ¥¹œœ¤Ñ¡É½Ü¹•ÜÉÉ½È I•ÍÕ±ÐÁ…Ñ µÕÍÐ‰”„ÍÑÉ¥¹œœ¤ì4(€¥˜€¡…Ñ¥½¸€„ôô€½Á•¸œ€˜˜…Ñ¥½¸€„ôô€É•Ù•…°œ¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È I•ÍÕ±Ð…Ñ¥½¸µÕÍÐ‰”½Á•¸½ÈÉ•Ù•…°œ¤ì4(€ô4(€½¹ÍÐÉ•…°€ôÉ•…±¥±”¡É…Ü¤ì4(€¥˜€ …É•ÑÕÉ¹•‘=ÕÑÁÕÑÌ¹¡…Ì¡É•…°¤¤ì4(€€€Ñ¡É½Ü¹•ÜÉÉ½È Q¡…ÐÉ•ÍÕ±Ð¥Ì¹½Ð™É½´Ñ¡¥ÌÕÑ½‘¥Ñ½ÈÍ•ÍÍ¥½¸œ¤ì4(€ô4(€¥˜€¡…Ñ¥½¸€ôôô€½Á•¸œ¤É•ÑÕÉ¸Í¡•±°¹½Á•¹A…Ñ ¡É•…°¤ì4(€Í¡•±°¹Í¡½Ý%Ñ•µ%¹½±‘•È¡É•…°¤ì4(€É•ÑÕÉ¸ì½¬èÑÉÕ”°…Ñ¥½¸ôì4)ô4(4)™Õ¹Ñ¥½¸Í•ÑÕÁ%ÁŒ ¤ì4(€¥Á5…¥¸¹½¸ ¡•±Á•ÈéÙ¥Í¥½¸µÁÉ½É•ÍÌœ°¡…¹‘±•Y¥Í¥½¹AÉ½É•ÍÌ¤ì4(€¥Á5…¥¸¹½¸ ¡•±Á•ÈéÙ¥Í¥½¸µÉ•ÍÕ±Ðœ°¡…¹‘±•Y¥Í¥½¹I•ÍÕ±Ð¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•ÈéÍÑ…Ñ”œ°€ ¤€ôøì4(€€€½¹ÍÐÍÉ••¹Í¡½Ñ5½‘”€ô€„…ÁÉ½•ÍÌ¹•¹Ø¹UQ=%Q=I}MI9M!=Q}AQ ì4(€€€½¹ÍÐÍ•ÑÑ¥¹Ì€ôÍÉ••¹Í¡½Ñ5½‘”€üíô€è±½…‘M•ÑÑ¥¹Ì ¤ì4(€€€É•ÑÕÉ¸ì4(€€€€€½¹™¥ÕÉ•èÑÉÕ”°4(€€€€€ÉÕ¹¹¥¹œè€„……Ñ¥Ù•I•¹‘•È°4(€€€€€É•¹‘•É¥¹œè€„……Ñ¥Ù•I•¹‘•È°4(€€€€€¡…ÑÑ¥¹œè€„……Ñ¥Ù•¡…Ð°4(€€€€€…Ñ¥Ù•I•¹‘•Èè…Ñ¥Ù•I•¹‘•ÉMÑ…Ñ” ¤°4(€€€€€Í•ÑÑ¥¹ÌèÍ•ÑÑ¥¹ÍAÉ•Í•¹”¡Í•ÑÑ¥¹Ì¤°4(€€€€€…Á…‰¥±¥Ñ¥•Ìèì4(€€€€€€€‘••ÁÍ••¬è€„…Í•ÑÑ¥¹Ì¹‘••ÁÍ••­Á¥-•ä°4(€€€€€€€Á•á•±Ìè€„…Í•ÑÑ¥¹Ì¹Á•á•±ÍÁ¥-•ä°4(€€€€€€€Á¥á…‰…äè€„…Í•ÑÑ¥¹Ì¹Á¥á…‰…åÁ¥-•ä°4(€€€€€€€•±•Ù•¹±…‰Ìè€„…Í•ÑÑ¥¹Ì¹•±•Ù•¹1…‰ÍÁ¥-•ä°4(€€€€€€€É•µ½Ñ¥½¸èÑÉÕ”°4(€€€€€€€¡åÁ•É™É…µ•ÌèÑÉÕ”°4(€€€€€ô°4(€€€€€ÁÉ•™±¥¡ÐèÁÉ•™±¥¡Ð¡ì¡•­-•åÍÑ½É”è€…ÍÉ••¹Í¡½Ñ5½‘”ô¤°4(€€€€€Ù•ÉÍ¥½¸è…ÁÀ¹•ÑY•ÉÍ¥½¸ ¤°4(€€€€€Á±…Ñ™½É´èÁÉ½•ÍÌ¹Á±…Ñ™½É´°4(€€€€€½¹Ù•ÉÍ…Ñ¥½¸èÍÉ••¹Í¡½Ñ5½‘”€ü¹Õ±°€è±½…‘½¹Ù•ÉÍ…Ñ¥½¸ ¤°4(€€€ôì4(€ô¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•ÈéÁ¥¬µÙ¥‘•½Ìœ°€ ¤€ôøÁ¥­Y¥‘•½Ì ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé…ÑÑ… µ‘É½ÁÁ•µÙ¥‘•½Ìœ°€¡}•Ù•¹Ð°™¥±•Ì¤€ôø4(€€€…ÑÑ…¡É½ÁÁ•‘Y¥‘•½Ì¡™¥±•Ì¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•ÈéÁ¥¬µ½ÕÑÁÕÐœ°€ ¤€ôøÁ¥­=ÕÑÁÕÐ ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•ÈéÍ…Ù”µÍ•ÑÑ¥¹Ìœ°€¡}•Ù•¹Ð°¥¹ÁÕÐ¤€ôøÍ…Ù•M•ÑÑ¥¹Ì¡¥¹ÁÕÐ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•ÈéÍ…Ù”µ½¹Ù•ÉÍ…Ñ¥½¸œ°€¡}•Ù•¹Ð°¥¹ÁÕÐ¤€ôø4(€€€Í…Ù•½¹Ù•ÉÍ…Ñ¥½¸¡¥¹ÁÕÐ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•ÈéÉ•¹‘•Èµ±½…°œ°€¡}•Ù•¹Ð°¥¹ÁÕÐ¤€ôøÉ•¹‘•É1½…°¡¥¹ÁÕÐ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé…¹•°µ±½…°œ°€ ¤€ôø…¹•±1½…° ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé¡…Ðµ±½…°œ°€¡}•Ù•¹Ð°¥¹ÁÕÐ¤€ôø¡…Ñ1½…°¡¥¹ÁÕÐ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé…ÁÁ±äµ±½…°œ°€¡}•Ù•¹Ð°¥¹ÁÕÐ¤€ôø…ÁÁ±å1½…°¡¥¹ÁÕÐ¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé½Á•¸µÉ•ÍÕ±Ðœ°€¡}•Ù•¹Ð°É•ÍÕ±ÑA…Ñ °…Ñ¥½¸¤€ôø4(€€€½Á•¹I•ÍÕ±Ð¡É•ÍÕ±ÑA…Ñ °…Ñ¥½¸¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé½Á•¸µÉ•Í•…É µÍ½ÕÉ”œ°€¡}•Ù•¹Ð°ÕÉ°¤€ôø4(€€€½Á•¹I•Í•…É¡M½ÕÉ”¡ÕÉ°¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé¹½Ñ¥•Ìœ°€ ¤€ôøÍ¡•±°¹½Á•¹A…Ñ ¡ÉÕ¹Ñ¥µ•A…Ñ¡Ì ¤¹¹½Ñ¥•Ì¤¤ì4(€¥Á5…¥¸¹¡…¹‘±” ¡•±Á•Èé½Á•¸œ°€¡}•Ù•¹Ð°­•ä¤€ôøì4(€€€¥˜€¡ÑåÁ•½˜­•ä€„ôô€ÍÑÉ¥¹œœñð€…AI=Y%I}1%9-Mm­•åt¤ì4(€€€€€Ñ¡É½Ü¹•ÜÉÉ½È Q¡…Ð¡•±À±¥¹¬¥Ì¹½Ð…±±½Ý•œ¤ì4(€€€ô4(€€€É•ÑÕÉ¸Í¡•±°¹½Á•¹áÑ•É¹…°¡AI=Y%I}1%9-Mm­•åt¤ì4(€ô¤ì4)ô4(4)™Õ¹Ñ¥½¸Íµ½­•Q•ÍÐ ¤ì4(€½¹ÍÐÍ•ÑÑ¥¹Ì€ôì4(€€€‘••ÁÍ••­Á¥-•äè€œœ°Á•á•±ÍÁ¥-•äè€œœ°Á¥á…‰…åÁ¥-•äè€œœ°4(€€€•±•Ù•¹1…‰ÍÁ¥-•äè€œœ°É•µ½Ñ¥½¹-•äè€™É•”µ±¥•¹Í”œ°4(€ôì4(€½¹ÍÐÀ€ôÉÕ¹Ñ¥µ•A…Ñ¡Ì ¤ì4(€½¹ÍÐ¡¥±€ôÍÁ…Ý¹Må¹Œ¡À¹‘…•µ½¸°mt°ì4(€€€•¹Øèì€¸¸¹‘…•µ½¹¹Ø¡Í•ÑÑ¥¹Ì¤°UQ=%Q=I}!1AI}M5=-}QMPè€œÄœô°4(€€€Ý¥¹‘½ÝÍ!¥‘”èÑÉÕ”°•¹½‘¥¹œè€ÕÑ˜àœ°Ñ¥µ•½ÕÐè€ÌÀÀÀÀ°4(€ô¤ì4(€½¹ÍÐÉ•…Ñ¥Ù”€ôÍÁ…Ý¹Må¹Œ¡À¹‘…•µ½¸°mt°ì4(€€€•¹Øèì€¸¸¹‘…•µ½¹¹Ø¡Í•ÑÑ¥¹Ì¤°UQ=%Q=I}IQ%Y}M5=-}QMPè€œÄœô°4(€€€Ý¥¹‘½ÝÍ!¥‘”èÑÉÕ”°•¹½‘¥¹œè€ÕÑ˜àœ°Ñ¥µ•½ÕÐè€ÌØÀÀÀÀ°4(€ô¤ì4(€€¼¼ÉÑ¥™…ÐÍµ½­”Ù…±¥‘…Ñ•ÌÑ¡”¥¹ÍÑ…±±•ÉÕ¹Ñ¥µ”½¸Íµ…±°¡½ÍÑ•ÉÕ¹¹•ÉÌ¸4(€€¼¼%¹Ñ•É…Ñ¥Ù”…Ñ¥½¹ÌÉ•Ñ…¥¸Ñ¡”€ÈÀ¥…Ñ”¸4(€½¹ÍÐ¡•­Ì€ôÁÉ•™±¥¡Ð¡ì¡•­-•åÍÑ½É”è™…±Í”°¡•­¥Í¬è™…±Í”ô¤ì4(€½¹ÍÐÉ•ÍÕ±Ð€ôì4(€€€Á…­…•èA-°4(€€€ÁÉ•™±¥¡Ðè¡•­Ì¹½¬°4(€€€‘…•µ½¹á¥Ðè¡¥±¹ÍÑ…ÑÕÌ€ôôô€À°4(€€€‘…•µ½¹I••¥ÁÐè€¡¡¥±¹ÍÑ‘½ÕÐñð€œœ¤¹¥¹±Õ‘•Ì ¡•±Á•Èµ‘…•µ½¸µÍµ½­”œ¤°4(€€€É•…Ñ¥Ù•á¥ÐèÉ•…Ñ¥Ù”¹ÍÑ…ÑÕÌ€ôôô€À°4(€€€É•…Ñ¥Ù•I••¥ÁÐè€¡É•…Ñ¥Ù”¹ÍÑ‘½ÕÐñð€œœ¤¹¥¹±Õ‘•Ì ¡•±Á•ÈµÉ•…Ñ¥Ù”µÍµ½­”œ¤°4(€ôì4(€½¹Í½±”¹±½œ¡)M=8¹ÍÑÉ¥¹¥™ä¡ì•Ù•¹Ðè€¡•±Á•Èµ‘•Í­Ñ½ÀµÍµ½­”œ°¡•­ÌèÉ•ÍÕ±Ðô¤¤ì4(€É•ÑÕÉ¸=‰©•Ð¹Ù…±Õ•Ì¡É•ÍÕ±Ð¤¹•Ù•Éä¡	½½±•…¸¤ì4)ô4(4)™Õ¹Ñ¥½¸É•…Ñ•]¥¹‘½Ü ¤ì4(€½¹ÍÐ…ÁÑÕÉ•A…Ñ €ôÁÉ½•ÍÌ¹•¹Ø¹UQ=%Q=I}MI9M!=Q}AQ ñð€œœì4(€Ý¥¸€ô¹•Ü	É½ÝÍ•É]¥¹‘½Ü¡ì4(€€€Ý¥‘Ñ è€äÀÀ°¡•¥¡Ðè…ÁÑÕÉ•A…Ñ €ü€ÄÈÀÀ€è€ÜØÀ°4(€€€µ¥¹]¥‘Ñ è€ÜÀÀ°µ¥¹!•¥¡Ðè€ØÈÀ°Í¡½Üè€……ÁÑÕÉ•A…Ñ °4(€€€Ñ¥Ñ±”è€ÕÑ½‘¥Ñ½Èœ°‰…­É½Õ¹‘½±½Èè€œŒÁˆÁÄÀœ°4(€€€Ý•‰AÉ•™•É•¹•Ìèì4(€€€€€ÁÉ•±½…èÁ…Ñ ¹©½¥¸¡}}‘¥É¹…µ”°€ÁÉ•±½…¹©Ìœ¤°4(€€€€€½¹Ñ•áÑ%Í½±…Ñ¥½¸èÑÉÕ”°¹½‘•%¹Ñ•É…Ñ¥½¸è™…±Í”°Í…¹‘‰½àèÑÉÕ”°4(€€€ô°4(€ô¤ì4(€Ý¥¸¹±½…‘¥±”¡Á…Ñ ¹©½¥¸¡}}‘¥É¹…µ”°€É•¹‘•É•Èœ°€¥¹‘•à¹¡Ñµ°œ¤¤ì4(€¥˜€¡…ÁÑÕÉ•A…Ñ ¤ì4(€€€Ý¥¸¹Ý•‰½¹Ñ•¹ÑÌ¹½¹” ‘¥µ™¥¹¥Í µ±½…œ°…Íå¹Œ€ ¤€ôøì4(€€€€€…Ý…¥Ð¹•ÜAÉ½µ¥Í” ¡É•Í½±Ù”¤€ôøÍ•ÑQ¥µ•½ÕÐ¡É•Í½±Ù”°€àÀÀ¤¤ì4(€€€€€½¹ÍÐ¡•¥¡Ð€ô…Ý…¥ÐÝ¥¸¹Ý•‰½¹Ñ•¹ÑÌ¹•á•ÕÑ•)…Ù…MÉ¥ÁÐ 4(€€€€€€€€5…Ñ ¹µ¥¸ ÐÀÀÀ°‘½Õµ•¹Ð¹‘½Õµ•¹Ñ±•µ•¹Ð¹ÍÉ½±±!•¥¡Ð¤œ¤ì4(€€€€€Ý¥¸¹Í•Ñ½¹Ñ•¹ÑM¥é” äÀÀ°5…Ñ ¹µ…à ÄÈÀÀ°¡•¥¡Ð¤¤ì4(€€€€€½¹ÍÐÍ¡½Ð€ô…Ý…¥ÐÝ¥¸¹Ý•‰½¹Ñ•¹ÑÌ¹…ÁÑÕÉ•A…” ¤ì4(€€€€€™Ì¹ÝÉ¥Ñ•¥±•Må¹Œ¡…ÁÑÕÉ•A…Ñ °Í¡½Ð¹Ñ½A9 ¤¤ì4(€€€€€…ÁÀ¹•á¥Ð À¤ì4(€€€ô¤ì4(€ô4)ô4(4)…ÁÀ¹Ý¡•¹I•…‘ä ¤¹Ñ¡•¸  ¤€ôøì4(€¥˜€¡ÁÉ½•ÍÌ¹•¹Ø¹UQ=%Q=I}M5=-}QMP€ôôô€œÄœ¤ì4(€€€…ÁÀ¹•á¥Ð¡Íµ½­•Q•ÍÐ ¤€ü€À€è€Ä¤ì4(€€€É•ÑÕÉ¸ì4(€ô4(€É•¥ÍÑ•ÉY¥Í¥½¹AÉ½Ñ½½° ¤ì4(€Í•ÑÕÁ%ÁŒ ¤ì4(€É•…Ñ•]¥¹‘½Ü ¤ì4)ô¤ì4(4)…ÁÀ¹½¸ ‰•™½É”µÅÕ¥Ðœ°€ ¤€ôøì4(€É•©•ÑA•¹‘¥¹Y¥Í¥½¸ ÕÑ½‘¥Ñ½È¥Ì±½Í¥¹œœ¤ì4(€¥˜€¡…Ñ¥Ù•I•¹‘•È¤ÍÑ½ÁAÉ½•ÍÍQÉ•”¡…Ñ¥Ù•I•¹‘•È¹ÁÉ½Œ¤ì4(€¥˜€¡…Ñ¥Ù•¡…Ðü¹ÁÉ½Œ¤ÍÑ½ÁAÉ½•ÍÍQÉ•”¡…Ñ¥Ù•¡…Ð¹ÁÉ½Œ¤ì4)ô¤ì4)…ÁÀ¹½¸ Ý¥¹‘½Üµ…±°µ±½Í•œ°€ ¤€ôø…ÁÀ¹ÅÕ¥Ð ¤¤ì4(4)µ½‘Õ±”¹•áÁ½ÉÑÌ€ôìÉÕ¹Ñ¥µ•A…Ñ¡Ìôì4(