/** AutoEditor: one-window local editor around the frozen render daemon. */
'use strict';

const { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, session, shell } =
  require('electron');
const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { stopProcessTree } = require('../lib/process-tree');
const { runEditingChat } = require('./lib/editing-harness');
const {
  analyzeMedia,
  artifactCaptionRenderEvents,
  artifactFrameCaptureCoverage,
  artifactVisionPlan,
  extractArtifactVisionFrames,
  parseArtifactCaptions,
  probeVideo,
} = require('./lib/media-analysis');
const {
  artifactAudioQaReceipt,
  ARTIFACT_SEMANTIC_CANDIDATE_TOKEN_IDS,
  ARTIFACT_SEMANTIC_THRESHOLDS,
  parseArtifactReview,
  reviewArtifactFramesCalibrated,
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
  authorizeProjectIntentRequest,
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
const {
  compileSequencePlan,
  sequencePlanSha256,
  sourceManifestSha256: sourceManifestContractSha256,
} = require('./lib/sequence-plan');
const {
  compileTransitionPlan,
  transitionPlanSha256,
  transitionSequenceManifestSha256,
} = require('./lib/transition-plan');
const {
  createRuntimeCapabilityPreflight,
} = require('./lib/runtime-capability-preflight');
const { CAPABILITY_CHECK_IDS } = require('./lib/runtime-capabilities');
const {
  createVisionProtocolHandler,
  installedVisionModelPackPath,
  MODEL_PACK_TREE_SHA256,
  sourceVisionModelPackPath,
  validateVisionModelPack,
  validateVisionRuntimeAssets,
  VISION_RUNTIME_LOCK_SHA256,
  visionModelRuntimeBindings,
} = require('./lib/vision-model-pack');
const {
  readArtifactQaReport: readTrustedArtifactQaReport,
  readContractJsonSidecar: readTrustedContractJsonSidecar,
  readContractTextSidecar: readTrustedContractTextSidecar,
  validateMusicProductionArtifactBinding,
  validateSfxProductionArtifactBinding,
  validateProjectIntentArtifactBinding,
} = require('./lib/artifact-contract');

let win = null;
let activeRender = null;
let activeChat = null;
let runtimeCapabilityPreflight = null;
let quitDrainStarted = false;
let quitDrainComplete = false;
let actionSequence = 0;
let visionSequence = 0;
let visionSessionNetworkAttempts = 0;
let visionSessionNetworkEnforced = false;
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
const MAX_ARTIFACT_EDL_BYTES = 2 * 1024 * 1024;
const MAX_ARTIFACT_SIDECAR_BYTES = 2 * 1024 * 1024;
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
  const fonts = PACKAGED
    ? path.join(root, 'fonts')
    : path.join(__dirname, 'renderer');
  const visionDir = path.join(__dirname, 'vision');
  const visionModelPack = PACKAGED
    ? installedVisionModelPackPath(root)
    : sourceVisionModelPackPath(root);
  const visionModelBindings = visionModelRuntimeBindings(visionModelPack);
  const capabilityCodeFiles = PACKAGED
    ? [
      { name: 'desktop-app-asar', path: path.join(root, 'app.asar') },
      {
        name: 'caption-font',
        path: path.join(fonts, 'WorkSans-Variable.ttf'),
      },
      {
        name: 'whisper-small-model',
        path: path.join(root, 'models', 'faster-whisper-small'),
      },
      ...visionModelBindings,
    ]
    : [
      {
        name: 'capability-check-runner',
        path: path.join(__dirname, 'lib', 'runtime-capability-check-runner.js'),
      },
      {
        name: 'capability-preflight',
        path: path.join(__dirname, 'lib', 'runtime-capability-preflight.js'),
      },
      {
        name: 'capability-producer',
        path: path.join(__dirname, 'lib', 'runtime-capability-probe.js'),
      },
      {
        name: 'capability-contract',
        path: path.join(__dirname, 'lib', 'runtime-capabilities.js'),
      },
      {
        name: 'capability-policy-bridge',
        path: path.join(__dirname, 'lib', 'project-intent-policy-bridge.js'),
      },
      {
        name: 'edit-policy',
        path: path.join(__dirname, 'lib', 'edit-policy.js'),
      },
      {
        name: 'artifact-contract',
        path: path.join(__dirname, 'lib', 'artifact-contract.js'),
      },
      {
        name: 'sfx-production',
        path: path.join(__dirname, '..', '..', 'autoeditor',
          'sfx_production.py'),
      },
      {
        name: 'music-production',
        path: path.join(__dirname, '..', '..', 'autoeditor',
          'music_production.py'),
      },
      {
        name: 'project-intent',
        path: path.join(__dirname, 'lib', 'project-intent.js'),
      },
      {
        name: 'desktop-main',
        path: __filename,
      },
      {
        name: 'process-tree',
        path: path.join(__dirname, '..', 'lib', 'process-tree.js'),
      },
      {
        name: 'caption-font',
        path: path.join(fonts, 'WorkSans-Variable.ttf'),
      },
      {
        name: 'asr-runtime-probe',
        path: path.join(__dirname, '..', '..', 'autoeditor',
          'asr_runtime_probe.py'),
      },
      {
        name: 'dialogue-cleanup-runtime-probe',
        path: path.join(__dirname, '..', '..', 'autoeditor',
          'dialogue_cleanup_runtime_probe.py'),
      },
      {
        name: 'render-capability-runtime-probe',
        path: path.join(__dirname, '..', '..', 'autoeditor',
          'render_capability_runtime_probe.py'),
      },
      {
        name: 'vision-model-pack-contract',
        path: path.join(__dirname, 'lib', 'vision-model-pack.js'),
      },
      {
        name: 'semantic-choice-contract',
        path: path.join(__dirname, 'lib', 'calibrated-semantic-choice.js'),
      },
      {
        name: 'semantic-qualification-contract',
        path: path.join(__dirname, 'lib', 'semantic-visual-qualification.js'),
      },
      {
        name: 'semantic-promotion-gate',
        path: path.join(__dirname, 'lib',
          'calibrated-semantic-promotion-gate.js'),
      },
      {
        name: 'visual-quality-contract',
        path: path.join(__dirname, 'lib', 'artifact-quality.js'),
      },
      {
        name: 'visual-quality-fixtures',
        path: path.join(__dirname, 'lib', 'visual-quality-fixtures.js'),
      },
      {
        name: 'visual-quality-runtime-probe',
        path: path.join(__dirname, 'lib', 'visual-quality-runtime-probe.js'),
      },
      {
        name: 'vision-worker-bundle',
        path: path.join(visionDir, 'vision-worker.bundle.js'),
      },
      {
        name: 'whisper-small-model',
        path: path.join(root, 'models', 'faster-whisper-small'),
      },
      ...visionModelBindings,
    ];
  return {
    root,
    daemon: path.join(root, 'helper', exe('autoeditor-helper-daemon')),
    engine: path.join(root, 'engine', exe('autoeditor-engine')),
    ffmpeg: path.join(root, 'bin', exe('ffmpeg')),
    ffprobe: path.join(root, 'bin', exe('ffprobe')),
    smallModel: path.join(root, 'models', 'faster-whisper-small'),
    mediumModel: path.join(root, 'models', 'faster-whisper-medium'),
    profiles: path.join(root, 'profiles'),
    fonts,
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
    runtimeManifest: path.join(root, 'runtime-manifest.json'),
    capabilityCodeFiles,
    visionDir,
    visionModelPack,
  };
}

function initializeRuntimeCapabilityPreflight() {
  if (runtimeCapabilityPreflight) return runtimeCapabilityPreflight;
  const runtime = runtimePaths();
  const probeEnv = daemonEnv({
    deepseekApiKey: '', pexelsApiKey: '', pixabayApiKey: '',
    elevenLabsApiKey: '', remotionKey: 'free-license',
  });
  probeEnv.AUTOEDITOR_CREATIVE_SMOKE_TEST = '1';
  // The daemon otherwise treats Remotion as optional in creative smoke mode.
  // A chart capability pass must execute the real bundled Remotion fixture.
  probeEnv.AUTOEDITOR_REQUIRE_REMOTION = '1';
  runtimeCapabilityPreflight = createRuntimeCapabilityPreflight({
    runtime,
    userData: app.getPath('userData'),
    env: probeEnv,
    // The fixed checks run sequentially and now include real ASR, dialogue
    // cleanup, caption, SFX, and music renders.  Keep every subprocess
    // individually bounded while allowing slower supported machines enough
    // time to complete the full local proof without a misleading timeout.
    checkTimeoutMs: 120000,
    globalTimeoutMs: 15 * 60 * 1000,
  });
  return runtimeCapabilityPreflight;
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
    localVision: false,
    // Artifact smoke and screenshot capture are noninteractive. On macOS an
    // ad-hoc acceptance build can block on its first Keychain lookup. Saving
    // settings and starting any local action still require the OS keystore.
    keystore: checkKeystore ? safeStorage.isEncryptionAvailable() : true,
    disk: !checkDisk,
    codecs: false,
    filters: false,
  };
  try {
    validateVisionRuntimeAssets(p.visionDir);
    validateVisionModelPack(p.visionModelPack);
    checks.localVision = true;
  } catch (_) { checks.localVision = false; }
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
      'dilation', 'erosion', 'alphamerge', 'huesaturation', 'loudnorm',
      'colorspace'];
    checks.filters = needed.every((name) => filters.includes(name));
  }
  return {
    ok: Object.values(checks).every(Boolean),
    checks,
    // Observational until the typed project-intent path requests a policy.
    // Legacy rendering remains governed by its existing artifact gates.
    capabilityProbe: runtimeCapabilityPreflight?.snapshot() || {
      status: 'idle', trusted: false, baselineReady: false,
      availableCapabilities: [], passedChecks: 0, completedChecks: 0,
      totalChecks: CAPABILITY_CHECK_IDS.length, failureCode: '',
    },
  };
}

function daemonEnv(settings) {
  const p = runtimePaths();
  const env = { ...process.env };
  for (const key of ['DEEPSEEK_API_KEY', 'KEY_WRAP_SECRET', 'ADMIN_TOKEN',
    'WORKER_TOKEN', 'AUTOEDITOR_WEB_API', 'PEXELS_API_KEY', 'PIXABAY_API_KEY',
    'ELEVENLABS_API_KEY', 'REMOTION_LICENSE_KEY', 'OPENAI_API_KEY',
    'ANTHROPIC_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
    'TELEGRAM_HOME_CHANNEL', 'AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY']) {
    delete env[key];
  }
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
  const runtime = runtimePaths();
  const handler = createVisionProtocolHandler({
    modelPackRoot: runtime.visionModelPack,
    runtimeRoot: runtime.visionDir,
  });
  protocol.handle('autoeditor-vision', handler);
}

function enforceVisionSessionNetworkBoundary() {
  if (visionSessionNetworkEnforced) return;
  session.defaultSession.webRequest.onBeforeRequest({
    urls: ['http://*/*', 'https://*/*'],
  }, (_details, callback) => {
    visionSessionNetworkAttempts += 1;
    callback({ cancel: true });
  });
  session.defaultSession.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false));
  visionSessionNetworkEnforced = true;
}

function readVisionFrame(file, expected = null) {
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
    if (expected !== null) {
      if (!expected || typeof expected !== 'object' || Array.isArray(expected) ||
          Object.keys(expected).sort().join('\0') !== 'sha256\0size_bytes' ||
          !/^[0-9a-f]{64}$/.test(expected.sha256 || '') ||
          !Number.isSafeInteger(expected.size_bytes) ||
          expected.size_bytes !== data.length ||
          crypto.createHash('sha256').update(data).digest('hex') !==
            expected.sha256) {
        throw new Error('a local vision frame no longer matched its trusted capture');
      }
    }
    return `data:image/jpeg;base64,${data.toString('base64')}`;
  } finally {
    fs.closeSync(handle);
  }
}

function requestVision(framePaths, action, {
  mode = 'media-analysis', context = '', expectedFrames = null,
  includeRuntime = false,
} = {}) {
  if (!win || win.isDestroyed() || !isActiveAction(action)) {
    return Promise.reject(new Error('the local vision window is unavailable'));
  }
  if (!Array.isArray(framePaths) || framePaths.length < 1 || framePaths.length > 8) {
    return Promise.reject(new Error('local vision requires between 1 and 8 frames'));
  }
  if (expectedFrames !== null && (!Array.isArray(expectedFrames) ||
      expectedFrames.length !== framePaths.length)) {
    return Promise.reject(new Error('local vision frame evidence is invalid'));
  }
  const images = framePaths.map((file, index) =>
    readVisionFrame(file, expectedFrames?.[index] || null));
  const id = ++visionSequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingVision.delete(id);
      sendVisionCancel(id, 'timeout');
      reject(new Error('the local vision model exceeded 30 minutes'));
    }, VISION_TIMEOUT_MS);
    pendingVision.set(id, {
      action, includeRuntime: includeRuntime === true, mode,
      resolve, reject, timer,
    });
    send('helper-vision-request', {
      id, images,
      mode: String(mode).slice(0, 80),
      context: String(context || '').replace(/\0/g, '').slice(0, 8000),
    });
  });
}

function sendVisionCancel(id, reason) {
  if (!Number.isSafeInteger(id) || id < 1 || !win || win.isDestroyed()) return;
  send('helper-vision-cancel', {
    id, reason: String(reason || 'canceled').replace(/\0/g, '').slice(0, 100),
  });
}

function rejectPendingVision(message) {
  for (const [id, pending] of pendingVision.entries()) {
    clearTimeout(pending.timer);
    sendVisionCancel(id, message);
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
    stage: ['artifact-quality', 'artifact-assertion'].includes(pending.mode)
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
      pending.resolve(pending.includeRuntime
        ? Object.freeze({ result, runtime: value.runtime })
        : result);
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

function pythonJsonString(value) {
  let result = '"';
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (character === '"') result += '\\"';
    else if (character === '\\') result += '\\\\';
    else if (character === '\b') result += '\\b';
    else if (character === '\f') result += '\\f';
    else if (character === '\n') result += '\\n';
    else if (character === '\r') result += '\\r';
    else if (character === '\t') result += '\\t';
    else if (codePoint >= 0x20 && codePoint <= 0x7e) result += character;
    else if (codePoint <= 0xffff) {
      result += `\\u${codePoint.toString(16).padStart(4, '0')}`;
    } else {
      const adjusted = codePoint - 0x10000;
      result += `\\u${(0xd800 + (adjusted >> 10)).toString(16)}`;
      result += `\\u${(0xdc00 + (adjusted & 0x3ff)).toString(16)}`;
    }
  }
  return `${result}"`;
}

function stableJson(value) {
  if (typeof value === 'string') return pythonJsonString(value);
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${pythonJsonString(key)}:${stableJson(value[key])}`).join(',')}}`;
}

function sameCanonical(left, right) {
  return stableJson(left) === stableJson(right);
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

async function assertVisionArtifactUnchanged(file, expectedStat,
                                             expectedSha256) {
  const before = fs.statSync(file);
  const actualSha256 = await sha256File(file);
  const after = fs.statSync(file);
  const sameIdentity = (stat) => stat.size === expectedStat.size &&
    stat.mtimeMs === expectedStat.mtimeMs && stat.dev === expectedStat.dev &&
    stat.ino === expectedStat.ino;
  if (!sameIdentity(before) || !sameIdentity(after) ||
      actualSha256 !== expectedSha256) {
    throw new Error('the finished artifact changed during final visual QA');
  }
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
    if (encoded.length <= 512000) returnedProposals.add(encoded);
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
    sendVisionCancel(id, message);
    pending.reject(new Error(message));
  }
}

function validateFinalOutputTarget(outputDir, pendingRaw, finalRaw) {
  if (typeof pendingRaw !== 'string' || typeof finalRaw !== 'string' ||
      !path.isAbsolute(pendingRaw) || !path.isAbsolute(finalRaw) ||
      pendingRaw.includes('\0') || finalRaw.includes('\0')) {
    throw new Error('the pending/final artifact paths are invalid');
  }
  const root = fs.realpathSync.native(outputDir);
  const pending = fs.realpathSync.native(pendingRaw);
  const pendingRelative = path.relative(root, pending);
  if (!pendingRelative || pendingRelative === '..' ||
      pendingRelative.startsWith(`..${path.sep}`) ||
      path.isAbsolute(pendingRelative) ||
      !fs.statSync(pending).isFile() ||
      !/\.UNVERIFIED(?:\.|$)/i.test(path.basename(pending))) {
    throw new Error('the engine artifact is not a safe pending file');
  }
  const resolvedFinal = path.resolve(finalRaw);
  const finalParent = fs.realpathSync.native(path.dirname(resolvedFinal));
  const final = path.join(finalParent, path.basename(resolvedFinal));
  const finalRelative = path.relative(root, final);
  if (!finalRelative || finalRelative === '..' ||
      finalRelative.startsWith(`..${path.sep}`) || path.isAbsolute(finalRelative) ||
      finalParent !== root || path.extname(final).toLowerCase() !== '.mp4' ||
      final === pending || fs.existsSync(final)) {
    throw new Error('the desired final artifact path is unsafe or already exists');
  }
  return { pending, approved: final };
}

function artifactPromotionTarget(event, outputDir) {
  if (!event?.outputs || typeof event.outputs !== 'object' ||
      Array.isArray(event.outputs) || !event.finalOutputs ||
      typeof event.finalOutputs !== 'object' || Array.isArray(event.finalOutputs)) {
    throw new Error('the engine omitted pending/final artifact mappings');
  }
  const keys = Object.keys(event.outputs);
  const finalKeys = Object.keys(event.finalOutputs);
  if (keys.length !== 1 || finalKeys.length !== keys.length ||
      keys.some((key, index) => !key || key !== finalKeys[index])) {
    throw new Error('the engine pending/final artifact keys do not match exactly');
  }
  const key = keys[0];
  const target = validateFinalOutputTarget(
    outputDir, event.outputs[key], event.finalOutputs[key]);
  if (fs.realpathSync.native(event.output) !== target.pending) {
    throw new Error('the primary artifact does not match its output key');
  }
  return { key, ...target };
}

function visibleArtifactPath(event, outputDir) {
  return artifactPromotionTarget(event, outputDir).pending;
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

async function semanticArtifactReviewCapability() {
  const snapshot = runtimeCapabilityPreflight?.snapshot();
  const advertised = !!snapshot && snapshot.trusted === true &&
    snapshot.baselineReady === true && Array.isArray(snapshot.availableCapabilities) &&
    snapshot.availableCapabilities.includes('visual_quality_analysis');
  if (!advertised) {
    return Object.freeze({
      available: false,
      status: String(snapshot?.status || 'idle'),
      failureCode: String(snapshot?.failureCode || ''),
    });
  }
  try {
    const manifest = await runtimeCapabilityPreflight.requireTrustedManifest();
    if (typeof runtimeCapabilityPreflight.requireSemanticVisualQualification !==
        'function') {
      return Object.freeze({
        available: false,
        status: 'qualification_unavailable',
        failureCode: 'semantic_visual_qualification_unavailable',
      });
    }
    const qualification = await runtimeCapabilityPreflight
      .requireSemanticVisualQualification();
    const qualified = !!qualification && qualification.qualified === true &&
      qualification.schemaVersion ===
        'autoeditor-semantic-visual-qualification-result/v1' &&
      /^[0-9a-f]{64}$/.test(qualification.resultSha256 || '') &&
      qualification.modelSha256 === MODEL_PACK_TREE_SHA256 &&
      qualification.runtimeSha256 === VISION_RUNTIME_LOCK_SHA256 &&
      Array.isArray(qualification.backends) &&
      qualification.backends.join('\0') === 'webgpu\0wasm';
    const available = qualified &&
      Array.isArray(manifest?.available_capabilities) &&
      manifest.available_capabilities.includes('visual_quality_analysis');
    return Object.freeze({
      available,
      status: available ? 'ready' : 'required_checks_failed',
      failureCode: available ? '' : 'visual_quality_analysis_unavailable',
      ...(available ? {
        capabilityManifestSha256: sha256Text(stableJson(manifest)),
        capabilityProbeReceiptSha256: manifest.probe_receipt_sha256,
        qualificationResultSha256: qualification.resultSha256,
        qualificationSchema: qualification.schemaVersion,
        qualifiedBackends: Object.freeze([...qualification.backends]),
        modelSha256: qualification.modelSha256,
        runtimeSha256: qualification.runtimeSha256,
      } : {}),
    });
  } catch (error) {
    return Object.freeze({
      available: false,
      status: 'failed',
      failureCode: String(error?.code || 'runtime_revalidation_failed'),
    });
  }
}

function quarantineRejectedArtifact(artifact) {
  const parsed = path.parse(artifact);
  const stamp = `${Date.now()}.${process.pid}`;
  const rejected = path.join(
    parsed.dir, `${parsed.name}.VISION-REJECTED.${stamp}${parsed.ext}`);
  fs.renameSync(artifact, rejected);
  return rejected;
}

function stageArtifactForVision(actualPending, desiredFinal) {
  return validateFinalOutputTarget(
    path.dirname(desiredFinal), actualPending, desiredFinal);
}

function sha256FileSync(file) {
  const handle = fs.openSync(file, 'r');
  const hash = crypto.createHash('sha256');
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    for (;;) {
      const count = fs.readSync(handle, buffer, 0, buffer.length, null);
      if (!count) break;
      hash.update(buffer.subarray(0, count));
    }
    return hash.digest('hex');
  } finally {
    fs.closeSync(handle);
  }
}

function promoteVisionArtifact(staged, expectedBytes, expectedSha256) {
  if (!staged || fs.existsSync(staged.approved)) {
    throw new Error('the desired final artifact path collided before promotion');
  }
  if (!Number.isSafeInteger(expectedBytes) || expectedBytes < 1 ||
      !/^[0-9a-f]{64}$/.test(expectedSha256 || '')) {
    throw new Error('the reviewed artifact identity is unavailable for promotion');
  }
  // linkSync is an atomic, no-overwrite promotion on both supported desktop
  // platforms/filesystems that support hard links. Removable, exFAT, and some
  // network folders do not; COPYFILE_EXCL preserves no-overwrite semantics and
  // is hash-verified before the pending name is removed.
  try {
    fs.linkSync(staged.pending, staged.approved);
  } catch (error) {
    if (!['EPERM', 'EACCES', 'EXDEV', 'ENOTSUP', 'EOPNOTSUPP', 'EINVAL']
      .includes(error?.code)) throw error;
    let copied = false;
    try {
      fs.copyFileSync(
        staged.pending, staged.approved, fs.constants.COPYFILE_EXCL);
      copied = true;
      const stat = fs.statSync(staged.approved);
      if (stat.size !== expectedBytes ||
          sha256FileSync(staged.approved) !== expectedSha256) {
        throw new Error('the copied final artifact did not match the reviewed bytes');
      }
    } catch (copyError) {
      if (copied) {
        try { fs.unlinkSync(staged.approved); }
        catch (_) { /* retain the original copy error */ }
      }
      throw copyError;
    }
  }
  try { fs.unlinkSync(staged.pending); }
  catch (_) { /* final hard link is already the reviewed immutable bytes */ }
  return staged.approved;
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

function readArtifactEdl(outputDir) {
  const candidate = path.join(outputDir, 'EDL.json');
  const real = fs.realpathSync.native(candidate);
  if (!isInside(outputDir, real)) {
    throw new Error('the final EDL is outside the selected output folder');
  }
  const handle = fs.openSync(real, 'r');
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size < 2 || before.size > MAX_ARTIFACT_EDL_BYTES) {
      throw new Error('the final EDL has an invalid size');
    }
    const raw = Buffer.alloc(before.size);
    if (fs.readSync(handle, raw, 0, before.size, 0) !== before.size) {
      throw new Error('the final EDL changed while it was read');
    }
    const after = fs.fstatSync(handle);
    if (after.size !== before.size || after.mtimeMs !== before.mtimeMs ||
        after.dev !== before.dev || after.ino !== before.ino) {
      throw new Error('the final EDL changed while it was read');
    }
    let edl;
    try { edl = JSON.parse(raw.toString('utf8')); }
    catch (_) { throw new Error('the final EDL is not valid JSON'); }
    return {
      file: path.basename(real),
      bytes: before.size,
      sha256: crypto.createHash('sha256').update(raw).digest('hex'),
      edl,
    };
  } finally {
    fs.closeSync(handle);
  }
}

function readBoundedJsonSidecar(outputDir, file, label,
                                maximum = MAX_ARTIFACT_SIDECAR_BYTES) {
  const candidate = path.join(outputDir, file);
  const real = fs.realpathSync.native(candidate);
  if (!isInside(outputDir, real)) throw new Error(`${label} is outside the output folder`);
  const handle = fs.openSync(real, 'r');
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size < 2 || before.size > maximum) {
      throw new Error(`${label} has an invalid size`);
    }
    const raw = Buffer.alloc(before.size);
    if (fs.readSync(handle, raw, 0, before.size, 0) !== before.size) {
      throw new Error(`${label} changed while it was read`);
    }
    const after = fs.fstatSync(handle);
    if (after.size !== before.size || after.mtimeMs !== before.mtimeMs ||
        after.dev !== before.dev || after.ino !== before.ino) {
      throw new Error(`${label} changed while it was read`);
    }
    let report;
    try { report = JSON.parse(raw.toString('utf8')); }
    catch (_) { throw new Error(`${label} is not valid JSON`); }
    return { file: path.basename(real), bytes: before.size,
      sha256: crypto.createHash('sha256').update(raw).digest('hex'), report };
  } finally { fs.closeSync(handle); }
}

function readBoundedTextSidecar(outputDir, file, label,
                                maximum = MAX_ARTIFACT_SIDECAR_BYTES) {
  const candidate = path.join(outputDir, file);
  const real = fs.realpathSync.native(candidate);
  if (!isInside(outputDir, real)) throw new Error(`${label} is outside the output folder`);
  const handle = fs.openSync(real, 'r');
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size < 1 || before.size > maximum) {
      throw new Error(`${label} has an invalid size`);
    }
    const raw = Buffer.alloc(before.size);
    if (fs.readSync(handle, raw, 0, before.size, 0) !== before.size) {
      throw new Error(`${label} changed while it was read`);
    }
    const after = fs.fstatSync(handle);
    if (after.size !== before.size || after.mtimeMs !== before.mtimeMs ||
        after.dev !== before.dev || after.ino !== before.ino) {
      throw new Error(`${label} changed while it was read`);
    }
    return { file: path.basename(real), bytes: before.size,
      sha256: crypto.createHash('sha256').update(raw).digest('hex'),
      text: raw.toString('utf8') };
  } finally { fs.closeSync(handle); }
}

function sidecarBinding(contract, name, receipt, required = true) {
  const binding = contract?.[name];
  if (!binding && !required) return null;
  if (!binding || typeof binding !== 'object' || Array.isArray(binding) ||
      binding.file !== receipt?.file || binding.sha256 !== receipt?.sha256 ||
      !Number.isSafeInteger(binding.bytes) || binding.bytes < 1 ||
      binding.bytes !== receipt?.bytes || !/^[0-9a-f]{64}$/.test(binding.sha256)) {
    throw new Error(`engine QA does not bind the exact ${name} sidecar`);
  }
  return binding;
}

function contractSidecarFile(contract, name, required = true) {
  const binding = contract?.[name];
  if (!binding && !required) return '';
  if (!binding || typeof binding !== 'object' || Array.isArray(binding) ||
      typeof binding.file !== 'string' || !binding.file ||
      path.basename(binding.file) !== binding.file) {
    throw new Error(`engine QA lacks a safe ${name} sidecar binding`);
  }
  return binding.file;
}

function readContractJsonSidecar(outputDir, contract, name, label,
                                 required = true) {
  return readTrustedContractJsonSidecar(
    outputDir, contract, name, label, required);
}

function readContractTextSidecar(outputDir, contract, name, label,
                                 required = true) {
  return readTrustedContractTextSidecar(
    outputDir, contract, name, label, required);
}

function artifactQaReleaseBinding(report, contract, promotion,
                                  artifactSha256, artifactBytes) {
  const releaseKeys = report.release && typeof report.release === 'object' &&
      !Array.isArray(report.release) ? Object.keys(report.release) : [];
  const release = releaseKeys.length === 1 && releaseKeys[0] === promotion.key
    ? report.release[promotion.key] : null;
  const delivery = contract.delivery;
  const desiredBasename = path.basename(promotion.approved);
  if (!release || !delivery || typeof delivery.file !== 'string' ||
      path.basename(delivery.file) !== delivery.file ||
      delivery.file !== desiredBasename ||
      !Number.isSafeInteger(delivery.bytes) || delivery.bytes < 1 ||
      delivery.sha256 !== artifactSha256 || delivery.bytes !== artifactBytes ||
      typeof release.file !== 'string' ||
      path.basename(release.file) !== desiredBasename ||
      path.resolve(release.file) !== promotion.approved ||
      !Number.isSafeInteger(release.bytes) || release.bytes !== artifactBytes ||
      release.sha256 !== artifactSha256) {
    throw new Error('engine QA does not bind the exact released artifact');
  }
  return release;
}

function readArtifactQaReport(outputDir, event, artifactSha256, artifactBytes) {
  return readTrustedArtifactQaReport(
    outputDir, event, artifactSha256, artifactBytes);
}

function readArtifactCaptions(outputDir, contract, durationSeconds) {
  const receipt = readContractTextSidecar(
    outputDir, contract, 'captions', 'artifact captions', false);
  if (!receipt) return null;
  return { ...receipt, events: parseArtifactCaptions(receipt.text, durationSeconds) };
}

function writeVisionQaReport(action, report) {
  const encoded = `${JSON.stringify(report, null, 2)}\n`;
  if (Buffer.byteLength(encoded, 'utf8') > 512 * 1024) {
    throw new Error('the final vision QA report exceeded its safety bound');
  }
  fs.writeFileSync(path.join(action.outputDir, 'VISION_QA_REPORT.json'), encoded,
    { encoding: 'utf8', mode: 0o600 });
}

function visionReport({ action, staged, artifactStat, qaReceipt, edlReceipt,
                        captionReceipt, captionRenderReceipt, boundaryReceipt,
                        mixReceipt, sequenceReceipt, projectIntentBinding,
                        musicProductionReceipt, musicProductionBinding,
                        sfxProductionReceipt, sfxProductionBinding,
                        audioQa, plan, capture, reviewed, coverage, review,
                        semanticReview,
                        artifactSha256 = '', error = '' }) {
  const planSummary = plan ? {
    schema: plan.schema,
    timeline: plan.timeline,
    edlBound: plan.edlBound,
    durationSeconds: plan.durationSeconds,
    frameCount: plan.frames.length,
    targetCount: plan.frames.reduce((total, frame) =>
      total + frame.targets.length, 0),
    captionSampling: plan.captionSampling || null,
    cutSampling: plan.cutSampling || null,
    sha256: sha256Text(stableJson(plan)),
  } : null;
  const expectedAuthority = action?.payload?.projectIntentAuthority;
  const authoritySummary = projectIntentBinding || (expectedAuthority ? {
    validated: false,
    authorizationId: expectedAuthority.authorization_id || '',
    projectIntentSha256: expectedAuthority.project_intent_sha256 || '',
    editPolicySha256: expectedAuthority.edit_policy_sha256 || '',
    capabilityManifestSha256:
      expectedAuthority.capability_manifest_sha256 || '',
    capabilityProbeReceiptSha256:
      expectedAuthority.capability_manifest?.probe_receipt_sha256 || '',
  } : null);
  const semantic = semanticReview || {
    mode: 'semantic-model', available: true, performed: true,
    capability: 'visual_quality_analysis', reason: '',
  };
  const deterministicOnly = semantic.mode === 'deterministic-only' &&
    semantic.available === false && semantic.performed === false;
  const report = {
    schema: authoritySummary
      ? 'autoeditor-final-vision-qa/v7'
      : 'autoeditor-final-vision-qa/v6',
    pass: !error && !!coverage?.complete && audioQa?.pass === true &&
      qaReceipt?.deterministicVisualQa?.record?.pass === true &&
      (deterministicOnly || reviewPasses(review)),
    artifact: path.basename(staged?.approved || ''),
    artifactBytes: Number(artifactStat?.size || 0),
    artifactSha256,
    edl: edlReceipt ? {
      file: edlReceipt.file, bytes: edlReceipt.bytes, sha256: edlReceipt.sha256,
    } : null,
    engineQa: qaReceipt ? {
      file: qaReceipt.file, bytes: qaReceipt.bytes, sha256: qaReceipt.sha256,
      schema: qaReceipt.report?.schema,
      artifactMode: qaReceipt.contract?.mode,
    } : null,
    captions: captionReceipt ? {
      file: captionReceipt.file, bytes: captionReceipt.bytes,
      sha256: captionReceipt.sha256, eventCount: captionReceipt.events?.length || 0,
    } : null,
    captionRender: captionRenderReceipt ? {
      file: captionRenderReceipt.file, bytes: captionRenderReceipt.bytes,
      sha256: captionRenderReceipt.sha256,
      eventCount: Array.isArray(captionRenderReceipt.report?.events)
        ? captionRenderReceipt.report.events.length : 0,
    } : null,
    editBoundaries: boundaryReceipt ? {
      file: boundaryReceipt.file, bytes: boundaryReceipt.bytes,
      sha256: boundaryReceipt.sha256,
    } : null,
    audioMix: mixReceipt ? {
      file: mixReceipt.file, bytes: mixReceipt.bytes, sha256: mixReceipt.sha256,
    } : null,
    sequence: sequenceReceipt ? {
      file: sequenceReceipt.file, bytes: sequenceReceipt.bytes,
      sha256: sequenceReceipt.sha256,
      orderedSegmentIds: sequenceReceipt.report?.ordered_segment_ids || [],
      totalDurationMs: sequenceReceipt.report?.total_duration_ms || null,
      compileReceiptSha256:
        sequenceReceipt.report?.sequence_compile_receipt_sha256 || '',
    } : null,
    ...(authoritySummary
      ? { projectIntentAuthority: authoritySummary }
      : {}),
    ...(musicProductionReceipt ? { typedMusicProduction: {
      file: musicProductionReceipt.file,
      bytes: musicProductionReceipt.bytes,
      sha256: musicProductionReceipt.sha256,
      validated: musicProductionBinding?.validated === true,
      mode: musicProductionBinding?.mode || '',
      regionCount: musicProductionBinding?.regionCount ?? null,
      productionReceiptSha256:
        musicProductionBinding?.productionReceiptSha256 || '',
    } } : {}),
    ...(sfxProductionReceipt ? { typedSfxProduction: {
      file: sfxProductionReceipt.file,
      bytes: sfxProductionReceipt.bytes,
      sha256: sfxProductionReceipt.sha256,
      validated: sfxProductionBinding?.validated === true,
      mode: sfxProductionBinding?.mode || '',
      cueCount: sfxProductionBinding?.cueCount ?? null,
      productionReceiptSha256:
        sfxProductionBinding?.productionReceiptSha256 || '',
    } } : {}),
    audioQa: audioQa || null,
    deterministicVisualQa: qaReceipt?.deterministicVisualQa ? {
      file: qaReceipt.deterministicVisualQa.file,
      bytes: qaReceipt.deterministicVisualQa.bytes,
      sha256: qaReceipt.deterministicVisualQa.sha256,
      analyzerReceiptSha256:
        qaReceipt.deterministicVisualQa.record.analysis.receipt_sha256,
      checkCount: qaReceipt.deterministicVisualQa.summary.check_count,
      semanticEvaluation: false,
    } : null,
    plan: planSummary,
    coverage: coverage || null,
    coverageSha256: coverage ? sha256Text(stableJson(coverage)) : '',
    semanticReview: semantic,
    captureFailures: Array.isArray(capture?.missing) ? capture.missing.map((item) => ({
      id: String(item?.id || '').slice(0, 100),
      timeSeconds: Number(item?.timeSeconds),
      error: String(item?.error || '').replace(/\0/g, '').trim().slice(0, 500),
    })) : [],
    batches: Array.isArray(reviewed?.batches) ? reviewed.batches : [],
    review: semantic.performed ? (review || parseArtifactReview('')) : null,
    error: String(error || '').replace(/\0/g, '').trim().slice(0, 2000),
    reviewedAt: new Date().toISOString(),
    actionId: action.id,
  };
  return report;
}

async function retryRejectedRender(action, artifact, issue) {
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
  // The daemon consumes ProjectIntent authority exactly once.  A repair is a
  // new render of the same approved proposal and must receive a newly measured,
  // newly signed authority instead of replaying the first process's carrier.
  delete payload.projectIntentAuthority;
  const retryRequest = payload.proposal
    ? normalizeApplyRequest(payload) : normalizeLocalRequest(payload);
  const resultContext = {
    ...action.resultContext,
    planSha256: planSha256(retryRequest),
  };
  processLocalEvent({
    event: 'local-progress', stage: 'artifact-repair', measurable: false,
    message: 'The first draft failed visual QA. Re-editing it automatically...',
    line: `Quarantined ${path.basename(rejected)}. Repairing: ${correction}`,
  }, action);
  action.qaPending = false;
  if (activeRender === action) activeRender = null;
  if (!Object.prototype.hasOwnProperty.call(
    retryRequest.proposal || {}, 'projectIntent')) {
    try {
      localProcess('--local-render', retryRequest, 'render', action.settings,
        resultContext);
    } catch (error) {
      send('helper-render', {
        event: 'local-error', actionId: action.id, kind: 'render',
        stage: 'artifact repair',
        error: `AutoEditor could not start the visual repair: ${
          error.message || String(error)}`,
      });
      send('helper-state', {
        running: false, rendering: false, chatting: !!activeChat,
        activeRender: null,
      });
    }
    return true;
  }

  let reservation = null;
  try {
    reservation = reserveLocalRender(
      retryRequest, action.settings, resultContext);
    const authorized = await authorizeProjectIntentRequest(
      retryRequest, initializeRuntimeCapabilityPreflight(), {
        isCurrent: () => activeRender === reservation && !reservation.canceled,
      });
    if (activeRender !== reservation || reservation.canceled) {
      throw new Error('project intent repair authorization was canceled');
    }
    reservation.projectIntentAuthorityKey = authorized.signingKey;
    localProcess('--local-render', authorized.request, 'render', action.settings,
      resultContext, reservation);
  } catch (error) {
    if (reservation) reservation.projectIntentAuthorityKey = '';
    const failedAction = reservation || action;
    if (!failedAction.canceled) {
      send('helper-render', {
        event: 'local-error', actionId: failedAction.id, kind: 'render',
        stage: 'ProjectIntent repair authorization',
        error: `AutoEditor could not authorize the visual repair: ${
          error.message || String(error)}`,
      });
    }
    if (reservation) markRenderFinished(reservation);
    else {
      send('helper-state', {
        running: false, rendering: false, chatting: !!activeChat,
        activeRender: null,
      });
    }
  }
  return true;
}

function assertVisionAction(action) {
  if (!action || action.canceled || activeRender !== action ||
      action.qaPending !== true) {
    throw new Error('local vision was canceled');
  }
}

async function reviewArtifact(event, action) {
  let artifact = '';
  let staged = null;
  let work = '';
  let artifactStat = null;
  let artifactSha256 = '';
  let qaReceipt = null;
  let edlReceipt = null;
  let captionReceipt = null;
  let captionRenderReceipt = null;
  let boundaryReceipt = null;
  let mixReceipt = null;
  let sequenceReceipt = null;
  let projectIntentReceipt = null;
  let projectIntentBinding = null;
  let musicProductionReceipt = null;
  let musicProductionBinding = null;
  let sfxProductionReceipt = null;
  let sfxProductionBinding = null;
  let audioQa = null;
  let plan = null;
  let capture = { captured: [], missing: [] };
  let reviewed = { reviewedFrameIds: [], reviewedTargetIds: [], batches: [] };
  let coverage = null;
  let review = parseArtifactReview('');
  let semanticReview = {
    mode: 'not-decided', available: false, performed: false,
    capability: 'visual_quality_analysis', reason: '',
  };
  try {
    const promotion = artifactPromotionTarget(event, action.outputDir);
    artifact = promotion.pending;
    staged = stageArtifactForVision(artifact, promotion.approved);
    artifact = staged.pending;
    artifactStat = fs.statSync(artifact);
    artifactSha256 = await sha256File(artifact);
    assertVisionAction(action);
    qaReceipt = readArtifactQaReport(
      action.outputDir, event, artifactSha256, artifactStat.size);
    work = fs.mkdtempSync(path.join(app.getPath('userData'), 'artifact-review-'));
    processLocalEvent({
      event: 'local-progress', stage: 'artifact-quality', measurable: false,
      message: 'Building exact visual coverage for the finished video...',
      line: 'Final QA is binding engine receipts, hook, timeline, captions, edit boundaries, and planned events before release.',
    }, action);
    const runtime = runtimePaths();
    const probe = await probeVideo(artifact, runtime, (child) => {
      if (activeRender === action && !action.canceled) action.proc = child;
    });
    assertVisionAction(action);
    const contract = qaReceipt.contract;
    if (!qaReceipt.deterministicVisualQa ||
        qaReceipt.deterministicVisualQa.record?.pass !== true) {
      throw new Error(
        'engine QA lacks verified deterministic visual-quality evidence');
    }
    boundaryReceipt = readContractJsonSidecar(
      action.outputDir, contract, 'edit_boundaries', 'edit-boundary receipt');
    captionReceipt = readArtifactCaptions(
      action.outputDir, contract, probe.durationSeconds);
    captionRenderReceipt = readContractJsonSidecar(
      action.outputDir, contract, 'caption_render', 'caption-render receipt', false);
    mixReceipt = readContractJsonSidecar(
      action.outputDir, contract, 'audio_mix', 'audio-mix receipt');
    sequenceReceipt = readContractJsonSidecar(
      action.outputDir, contract, 'sequence', 'approved-sequence receipt', false);
    projectIntentReceipt = readContractJsonSidecar(
      action.outputDir, contract, 'project_intent',
      'ProjectIntent render receipt', false);
    musicProductionReceipt = readContractJsonSidecar(
      action.outputDir, contract, 'music_production',
      'typed music production receipt', false);
    sfxProductionReceipt = readContractJsonSidecar(
      action.outputDir, contract, 'sfx_production',
      'typed SFX production receipt', false);
    const projectIntentExpected = Object.prototype.hasOwnProperty.call(
      action.payload?.proposal || {}, 'projectIntent');
    if (projectIntentExpected && !projectIntentReceipt) {
      throw new Error(
        'the approved ProjectIntent lacks its exact engine render receipt');
    }
    if (projectIntentExpected && !sfxProductionReceipt) {
      throw new Error(
        'the approved ProjectIntent lacks its typed SFX production receipt');
    }
    if (projectIntentExpected && !musicProductionReceipt) {
      throw new Error(
        'the approved ProjectIntent lacks its typed music production receipt');
    }
    if (!projectIntentExpected && musicProductionReceipt) {
      throw new Error('engine QA returned an orphaned typed music receipt');
    }
    if (!projectIntentExpected && sfxProductionReceipt) {
      throw new Error('engine QA returned an orphaned typed SFX receipt');
    }
    if (!projectIntentExpected && projectIntentReceipt) {
      throw new Error('engine QA returned an orphaned ProjectIntent receipt');
    }
    if (projectIntentExpected &&
        contract.schema !== 'autoeditor-engine-artifact-contract/v5') {
      throw new Error('the approved ProjectIntent lacks its v5 artifact contract');
    }
    if (!projectIntentExpected &&
        contract.schema !== 'autoeditor-engine-artifact-contract/v3') {
      throw new Error('the legacy render lacks its v3 artifact contract');
    }
    if (!projectIntentExpected &&
        qaReceipt.report?.checks?.project_intent_authority) {
      throw new Error('legacy engine QA returned an orphaned ProjectIntent check');
    }
    const sequenceCheck = qaReceipt.report?.checks?.approved_source_sequence;
    const approvedPlan = action.payload?.proposal?.sequencePlan;
    const approvedManifest = action.payload?.proposal?.sequenceSourceManifest;
    const sequenceExpected = approvedPlan !== undefined || approvedManifest !== undefined;
    if ((approvedPlan !== undefined) !== (approvedManifest !== undefined)) {
      throw new Error('the approved sequence proposal lost its source manifest');
    }
    if (sequenceExpected && !sequenceReceipt) {
      throw new Error('the approved sequence lacks its exact engine receipt');
    }
    if (!sequenceExpected && sequenceReceipt) {
      throw new Error('engine QA returned an unapproved source sequence');
    }
    if (sequenceReceipt) {
      const receipt = sequenceReceipt.report;
      const legacyKeys = [
        'schema_version', 'sequence_compile_receipt',
        'sequence_compile_receipt_sha256', 'sequence_compile',
        'sequence_timing_receipt', 'sequence_timing_receipt_sha256',
        'ordered_segment_ids',
        'segment_durations_ms', 'hard_cut_boundaries_ms',
        'total_duration_ms', 'synthesized_silence_source_ids',
        'used_audio_source_ids',
        'output_sha256', 'output_bytes', 'output_file',
      ];
      const transitionKeys = [
        'source_total_duration_ms', 'boundaries',
        'transition_compile_receipt', 'transition_compile_receipt_sha256',
        'transition_executor_receipt', 'transition_executor_receipt_sha256',
        'transition_topology', 'transition_topology_sha256',
        'transition_artifact_receipt', 'transition_artifact_receipt_sha256',
      ];
      const v2 = receipt?.schema_version ===
        'autoeditor-sequence-handoff-receipt/v2';
      const keys = v2 ? [...legacyKeys, ...transitionKeys] : legacyKeys;
      const approvedTransitionPlan = action.payload?.proposal?.transitionPlan;
      const approvedTransitionManifest =
        action.payload?.proposal?.transitionSequenceManifest;
      const transitionExpected = approvedTransitionPlan !== undefined ||
        approvedTransitionManifest !== undefined;
      const compiledSequence = compileSequencePlan(approvedPlan, approvedManifest);
      const cumulativeHardCuts = [];
      let hardCutPosition = 0;
      for (const duration of compiledSequence.ffmpeg_segments
        .slice(0, -1).map((item) => item.duration_ms)) {
        hardCutPosition += duration;
        cumulativeHardCuts.push(hardCutPosition);
      }
      if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt) ||
          Object.keys(receipt).length !== keys.length ||
          keys.some((key) => !Object.prototype.hasOwnProperty.call(receipt, key)) ||
          !['autoeditor-sequence-handoff-receipt/v1',
            'autoeditor-sequence-handoff-receipt/v2']
            .includes(receipt.schema_version) ||
          v2 !== transitionExpected ||
          (approvedTransitionPlan === undefined) !==
            (approvedTransitionManifest === undefined) ||
          !receipt.sequence_compile ||
          receipt.sequence_compile.receipt_sha256 !==
            receipt.sequence_compile_receipt_sha256 ||
          !sameCanonical(receipt.sequence_compile, compiledSequence) ||
          !sameCanonical(receipt.sequence_compile_receipt,
            compiledSequence.receipt) ||
          receipt.sequence_compile_receipt_sha256 !==
            compiledSequence.receipt_sha256 ||
          sha256Text(stableJson(receipt.sequence_timing_receipt)) !==
            receipt.sequence_timing_receipt_sha256 ||
          !sequenceCheck || sequenceCheck.ok !== true ||
          sequenceCheck.sequence_compile_receipt_sha256 !==
            receipt.sequence_compile_receipt_sha256 ||
          JSON.stringify(sequenceCheck.ordered_segment_ids) !==
            JSON.stringify(receipt.ordered_segment_ids) ||
          sequenceCheck.expected_duration_ms !== receipt.total_duration_ms ||
          receipt.sequence_compile_receipt.sequence_plan_sha256 !==
            sequencePlanSha256(approvedPlan) ||
          receipt.sequence_compile_receipt.source_manifest_sha256 !==
            sourceManifestContractSha256(approvedManifest) ||
          !Array.isArray(receipt.segment_durations_ms) ||
          !Array.isArray(receipt.hard_cut_boundaries_ms) ||
          receipt.segment_durations_ms.length !== receipt.ordered_segment_ids.length ||
          !sameCanonical(receipt.segment_durations_ms,
            compiledSequence.ffmpeg_segments.map((item) => item.duration_ms)) ||
          (!v2 && (!sameCanonical(receipt.hard_cut_boundaries_ms,
            cumulativeHardCuts) || receipt.total_duration_ms !==
              compiledSequence.receipt.total_duration_ms))) {
        throw new Error('engine QA does not validate the approved source sequence');
      }
      if (v2) {
        const compiledTransition = compileTransitionPlan(
          approvedTransitionPlan, approvedTransitionManifest,
          action.payload.projectIntentAuthority.edit_policy);
        const executor = receipt.transition_executor_receipt;
        const topology = receipt.transition_topology;
        const boundaries = receipt.boundaries;
        const artifactEvidence = receipt.transition_artifact_receipt;
        const expectedCarrier = {
          sequence_plan_sha256: sequencePlanSha256(approvedPlan),
          source_manifest_sha256:
            sourceManifestContractSha256(approvedManifest),
          transition_plan_sha256:
            transitionPlanSha256(approvedTransitionPlan),
          transition_sequence_manifest_sha256:
            transitionSequenceManifestSha256(approvedTransitionManifest),
        };
        const publicExecutorKeys = [
          'schema_version', 'output_file', 'sequence_plan_sha256',
          'sequence_compile_receipt_sha256', 'source_manifest_sha256',
          'compiled_segments_sha256', 'ordered_segment_ids', 'segment_count',
          'source_duration_ms', 'transition_plan_sha256',
          'transition_sequence_manifest_sha256',
          'transition_compile_receipt_sha256', 'compiled_boundaries_sha256',
          'ordered_boundary_ids', 'boundary_count',
          'non_hard_transition_count', 'expected_output_duration_ms',
          'frame_rate', 'topology_sha256', 'filter_complex_sha256',
          'timing_receipt_sha256', 'argv_sha256',
        ];
        const artifactKeys = [
          'schema_version', 'output_file', 'output_sha256', 'output_bytes',
          'source_total_duration_ms', 'expected_output_duration_ms',
          'measured_output_duration_ms', 'sequence_compile_receipt_sha256',
          'transition_compile_receipt_sha256',
          'transition_executor_receipt_sha256', 'transition_topology_sha256',
          'filter_complex_sha256', 'argv_sha256',
        ];
        const executorDigestKeys = [
          'sequence_plan_sha256', 'sequence_compile_receipt_sha256',
          'source_manifest_sha256', 'compiled_segments_sha256',
          'transition_plan_sha256',
          'transition_sequence_manifest_sha256',
          'transition_compile_receipt_sha256',
          'compiled_boundaries_sha256', 'topology_sha256',
          'filter_complex_sha256', 'timing_receipt_sha256', 'argv_sha256',
        ];
        let cumulativeOverlap = 0;
        let cumulativeOutput = compiledSequence.ffmpeg_segments[0].duration_ms;
        const projectedBoundaries = [];
        const projectedHardCuts = [];
        const topologyValid = Array.isArray(topology) &&
          topology.length === compiledTransition.compiled_boundaries.length &&
          topology.every((item, index) => {
            const compiledBoundary =
              compiledTransition.compiled_boundaries[index];
            const duration = compiledBoundary.duration_ms;
            cumulativeOutput += compiledSequence.ffmpeg_segments[index + 1]
              .duration_ms - duration;
            const projected = {
              boundary_index: index,
              kind: compiledBoundary.kind,
              output_start_ms:
                compiledBoundary.output_boundary_ms - duration,
              output_end_ms: compiledBoundary.output_boundary_ms,
              overlap_ms: duration,
            };
            projectedBoundaries.push(projected);
            if (compiledBoundary.kind === 'hard_cut') {
              projectedHardCuts.push(compiledBoundary.output_boundary_ms);
            }
            cumulativeOverlap += duration;
            return item && typeof item === 'object' &&
              Object.keys(item).length === 10 &&
              item.boundary_index === index &&
              item.boundary_id === compiledBoundary.boundary_id &&
              item.left_node === (index === 0
                ? `segment:${receipt.ordered_segment_ids[0]}`
                : `boundary:${compiledTransition.compiled_boundaries[index - 1]
                  .boundary_id}`) &&
              item.right_segment_id === receipt.ordered_segment_ids[index + 1] &&
              item.kind === compiledBoundary.kind &&
              item.duration_ms === duration &&
              item.output_boundary_ms === compiledBoundary.output_boundary_ms &&
              item.video_primitive ===
                compiledBoundary.video_ffmpeg_primitive_tokens[0] &&
              item.audio_primitive ===
                compiledBoundary.audio_ffmpeg_primitive_tokens[0] &&
              item.output_duration_ms === cumulativeOutput;
          });
        if (!sameCanonical(receipt.transition_compile_receipt,
          compiledTransition.receipt) ||
            receipt.transition_compile_receipt_sha256 !==
              compiledTransition.receipt_sha256 ||
            receipt.source_total_duration_ms !==
              compiledSequence.receipt.total_duration_ms ||
            receipt.total_duration_ms !== compiledTransition.receipt.output_duration_ms ||
            !sameCanonical(projectIntentReceipt.report.approved_transition_carrier,
              expectedCarrier) ||
            !executor || Object.keys(executor).length !== publicExecutorKeys.length ||
            publicExecutorKeys.some((key) =>
              !Object.prototype.hasOwnProperty.call(executor, key)) ||
            executor.schema_version !==
              'autoeditor-transition-render-public-receipt/v1' ||
            typeof executor.output_file !== 'string' ||
            !executor.output_file ||
            path.basename(executor.output_file) !== executor.output_file ||
            executor.output_file !== receipt.output_file ||
            executorDigestKeys.some((key) =>
              !/^[0-9a-f]{64}$/.test(executor[key] || '')) ||
            sha256Text(stableJson(executor)) !==
              receipt.transition_executor_receipt_sha256 ||
            executor.sequence_plan_sha256 !== expectedCarrier.sequence_plan_sha256 ||
            executor.source_manifest_sha256 !== expectedCarrier.source_manifest_sha256 ||
            executor.transition_plan_sha256 !==
              expectedCarrier.transition_plan_sha256 ||
            executor.transition_sequence_manifest_sha256 !==
              expectedCarrier.transition_sequence_manifest_sha256 ||
            executor.sequence_compile_receipt_sha256 !==
              receipt.sequence_compile_receipt_sha256 ||
            executor.compiled_segments_sha256 !==
              compiledSequence.receipt.compiled_segments_sha256 ||
            !sameCanonical(executor.ordered_segment_ids,
              receipt.ordered_segment_ids) ||
            executor.segment_count !== receipt.ordered_segment_ids.length ||
            executor.source_duration_ms !== receipt.source_total_duration_ms ||
            executor.transition_compile_receipt_sha256 !==
              receipt.transition_compile_receipt_sha256 ||
            executor.compiled_boundaries_sha256 !==
              compiledTransition.receipt.compiled_boundaries_sha256 ||
            !sameCanonical(executor.ordered_boundary_ids,
              compiledTransition.receipt.ordered_boundary_ids) ||
            executor.boundary_count !==
              compiledTransition.receipt.boundary_count ||
            executor.non_hard_transition_count !==
              compiledTransition.receipt.non_hard_transition_count ||
            executor.topology_sha256 !== receipt.transition_topology_sha256 ||
            executor.expected_output_duration_ms !== receipt.total_duration_ms ||
            !sameCanonical(executor.frame_rate,
              compiledTransition.receipt.frame_rate) ||
            executor.timing_receipt_sha256 !==
              receipt.sequence_timing_receipt_sha256 ||
            !topologyValid ||
            sha256Text(stableJson(topology)) !== receipt.transition_topology_sha256 ||
            !sameCanonical(boundaries, projectedBoundaries) ||
            !sameCanonical(receipt.hard_cut_boundaries_ms, projectedHardCuts) ||
            receipt.source_total_duration_ms - cumulativeOverlap !==
              receipt.total_duration_ms ||
            !artifactEvidence ||
            Object.keys(artifactEvidence).length !== artifactKeys.length ||
            artifactKeys.some((key) =>
              !Object.prototype.hasOwnProperty.call(artifactEvidence, key)) ||
            artifactEvidence.schema_version !==
              'autoeditor-transition-artifact-receipt/v1' ||
            sha256Text(stableJson(artifactEvidence)) !==
              receipt.transition_artifact_receipt_sha256 ||
            artifactEvidence.output_file !== receipt.output_file ||
            artifactEvidence.output_sha256 !== receipt.output_sha256 ||
            artifactEvidence.output_bytes !== receipt.output_bytes ||
            artifactEvidence.source_total_duration_ms !==
              receipt.source_total_duration_ms ||
            artifactEvidence.expected_output_duration_ms !==
              receipt.total_duration_ms ||
            !Number.isSafeInteger(
              artifactEvidence.measured_output_duration_ms) ||
            Math.abs(artifactEvidence.measured_output_duration_ms -
              receipt.total_duration_ms) > 100 ||
            artifactEvidence.sequence_compile_receipt_sha256 !==
              receipt.sequence_compile_receipt_sha256 ||
            artifactEvidence.transition_compile_receipt_sha256 !==
              receipt.transition_compile_receipt_sha256 ||
            artifactEvidence.transition_executor_receipt_sha256 !==
              receipt.transition_executor_receipt_sha256 ||
            artifactEvidence.transition_topology_sha256 !==
              receipt.transition_topology_sha256 ||
            artifactEvidence.filter_complex_sha256 !==
              executor.filter_complex_sha256 ||
            artifactEvidence.argv_sha256 !== executor.argv_sha256 ||
            sequenceCheck.transition_compile_receipt_sha256 !==
              receipt.transition_compile_receipt_sha256 ||
            sequenceCheck.transition_executor_receipt_sha256 !==
              receipt.transition_executor_receipt_sha256 ||
            sequenceCheck.transition_topology_sha256 !==
              receipt.transition_topology_sha256 ||
            sequenceCheck.transition_artifact_receipt_sha256 !==
              receipt.transition_artifact_receipt_sha256) {
          throw new Error(
            'engine QA does not validate the approved transition sequence');
        }
      } else if (
          Object.prototype.hasOwnProperty.call(
            sequenceCheck, 'transition_compile_receipt_sha256') ||
          Object.prototype.hasOwnProperty.call(
            sequenceCheck, 'transition_executor_receipt_sha256') ||
          Object.prototype.hasOwnProperty.call(
            sequenceCheck, 'transition_topology_sha256') ||
          Object.prototype.hasOwnProperty.call(
            sequenceCheck, 'transition_artifact_receipt_sha256')) {
        throw new Error('legacy sequence QA contains orphaned transition evidence');
      }
    } else if (sequenceCheck) {
      throw new Error('engine QA sequence check lacks its exact sidecar binding');
    }
    audioQa = artifactAudioQaReceipt(qaReceipt, mixReceipt, artifactSha256);
    if (!audioQa.pass) {
      throw new Error(`deterministic final audio QA failed: ${audioQa.note}`);
    }
    const premium = contract.mode === 'premium-edl';
    if (premium) {
      edlReceipt = readArtifactEdl(action.outputDir);
      sidecarBinding(contract, 'edl', edlReceipt);
    } else if (contract.edl) {
      throw new Error('generic baseline engine QA must not bind a premium EDL');
    }
    const captionDelivery = captionRenderReceipt
      ? 'burned' : (captionReceipt ? 'sidecar' : 'none');
    const captionVisionEvents = captionRenderReceipt
      ? artifactCaptionRenderEvents(
        captionRenderReceipt.report, probe.durationSeconds) : [];
    if (projectIntentReceipt) {
      musicProductionBinding = validateMusicProductionArtifactBinding({
        receipt: musicProductionReceipt,
        outputDir: action.outputDir,
        approvedAuthority: action.payload?.projectIntentAuthority,
        engineCheck:
          qaReceipt.report?.checks?.project_intent_music_production,
        expectedEngineEnvelopeSha256:
          projectIntentReceipt.report?.engine_envelope_sha256,
      });
      sfxProductionBinding = validateSfxProductionArtifactBinding({
        receipt: sfxProductionReceipt,
        outputDir: action.outputDir,
        approvedAuthority: action.payload?.projectIntentAuthority,
        engineCheck: qaReceipt.report?.checks?.project_intent_sfx_production,
        audioMixReceipt: mixReceipt,
        expectedEngineEnvelopeSha256:
          projectIntentReceipt.report?.engine_envelope_sha256,
        expectedMusicOutput: musicProductionBinding.output,
      });
      const transitionBoundaries = Array.isArray(
        sequenceReceipt?.report?.boundaries)
        ? sequenceReceipt.report.boundaries : [];
      const transitionCompile =
        sequenceReceipt?.report?.transition_compile_receipt;
      const transitionPolicy = transitionCompile &&
        typeof transitionCompile === 'object' &&
        !Array.isArray(transitionCompile) &&
        transitionCompile.policy &&
        typeof transitionCompile.policy === 'object' &&
        !Array.isArray(transitionCompile.policy)
        ? transitionCompile.policy : null;
      projectIntentBinding = validateProjectIntentArtifactBinding({
        receipt: projectIntentReceipt,
        approvedProposal: action.payload?.proposal,
        approvedAuthority: action.payload?.projectIntentAuthority,
        engineCheck: qaReceipt.report?.checks?.project_intent_authority,
        observed: {
          duration_ms: Math.round(probe.durationSeconds * 1000),
          width: probe.video.width,
          height: probe.video.height,
          caption_delivery: captionDelivery,
          caption_event_count: captionDelivery === 'burned'
            ? captionVisionEvents.length
            : (captionReceipt?.events?.length || 0),
          graphic_event_count: Array.isArray(edlReceipt?.edl?.graphics)
            ? edlReceipt.edl.graphics.length : 0,
          added_music_present: musicProductionBinding.addedMusicPresent,
          sfx_cue_count: sfxProductionBinding.cueCount,
          sfx_policy_usage: sfxProductionBinding.policyUsage,
          sfx_policy_bound: sfxProductionBinding.policyBound,
          transition_event_count: transitionBoundaries.length,
          non_hard_transition_count: transitionBoundaries.filter(
            (boundary) => boundary?.kind !== 'hard_cut').length,
          transition_policy_usage:
            typeof transitionPolicy?.usage === 'string'
              ? transitionPolicy.usage : 'unverified',
          transition_policy_bound: !!transitionPolicy &&
            transitionCompile.edit_policy_sha256 ===
              action.payload?.projectIntentAuthority?.edit_policy_sha256,
        },
      });
    }
    plan = artifactVisionPlan(probe.durationSeconds, edlReceipt?.edl || null, {
      requireEdl: premium,
      captions: captionVisionEvents,
      captionDelivery,
      captionMechanicalEventCount: captionDelivery === 'burned'
        ? captionVisionEvents.length : (captionReceipt?.events?.length || 0),
      captionEvidenceSha256: captionRenderReceipt?.sha256 ||
        captionReceipt?.sha256 || '',
      editBoundaryEvidenceSha256: boundaryReceipt.sha256,
      boundaries: boundaryReceipt.report,
    });
    capture = await extractArtifactVisionFrames(
      artifact, plan, work, runtime, (child) => {
        if (activeRender === action && !action.canceled) action.proc = child;
      }, () => activeRender === action && !action.canceled);
    assertVisionAction(action);
    coverage = artifactFrameCaptureCoverage(plan, capture.captured);
    if (capture.missing.length || capture.captured.length !== plan.frames.length) {
      const missing = capture.missing.map((frame) =>
        `${frame.id}@${Number(frame.timeSeconds).toFixed(3)}s`).join(', ');
      const issue = `final visual QA could not capture every planned frame: ${missing}`;
      throw new Error(issue);
    }
    const semanticCapability = await semanticArtifactReviewCapability();
    if (!semanticCapability.available && projectIntentExpected) {
      semanticReview = {
        mode: 'required-unavailable', available: false, performed: false,
        capability: 'visual_quality_analysis',
        reason: semanticCapability.failureCode || semanticCapability.status,
      };
      throw new Error(
        'the approved ProjectIntent requires a currently trusted visual quality capability');
    }
    if (semanticCapability.available) {
      semanticReview = {
        mode: 'semantic-model', available: true, attempted: true,
        performed: false,
        capability: 'visual_quality_analysis', reason: '',
      };
      processLocalEvent({
        event: 'local-progress', stage: 'artifact-quality', measurable: false,
        message: 'Running bounded calibrated semantic assertions...',
        line: `All ${plan.frames.length} planned frames were decoded; only applicable, evidence-bearing still-image targets enter the calibrated semantic gate.`,
      }, action);
      if (!visionSessionNetworkEnforced) {
        throw new Error('the local semantic visual session is not offline');
      }
      const networkAttemptsBefore = visionSessionNetworkAttempts;
      reviewed = await reviewArtifactFramesCalibrated(capture.captured, {
        artifactSha256,
        candidateTokenIds: ARTIFACT_SEMANTIC_CANDIDATE_TOKEN_IDS,
        captionDelivery: plan.captionSampling.deliveryMode,
        modelSha256: MODEL_PACK_TREE_SHA256,
        runtimeSha256: VISION_RUNTIME_LOCK_SHA256,
        thresholds: ARTIFACT_SEMANTIC_THRESHOLDS,
        requestAssertion: async (frame, invocation) => {
          assertVisionAction(action);
          const result = await requestVision([frame.path], action, {
            mode: invocation.mode,
            context: JSON.stringify(invocation.model_request),
            expectedFrames: [{
              sha256: frame.sha256, size_bytes: frame.size_bytes,
            }],
            includeRuntime: true,
          });
          assertVisionAction(action);
          return result;
        },
      });
      review = reviewed.review;
      assertVisionAction(action);
      if (visionSessionNetworkAttempts !== networkAttemptsBefore) {
        throw new Error(
          'the local semantic visual session attempted a network request');
      }
      if (!reviewed.coverage?.complete) {
        throw new Error('calibrated semantic visual coverage was incomplete');
      }
      semanticReview = Object.freeze({
        ...semanticReview,
        performed: true,
        reviewSchema: review.schema,
        modelSha256: MODEL_PACK_TREE_SHA256,
        runtimeSha256: VISION_RUNTIME_LOCK_SHA256,
        backend: reviewed.runtime.backend,
        semanticCoverageSha256:
          sha256Text(stableJson(reviewed.coverage)),
        calibratedReviewSha256: sha256Text(stableJson(review)),
        semanticReceiptSetSha256:
          sha256Text(stableJson(reviewed.batches)),
        capabilityManifestSha256:
          semanticCapability.capabilityManifestSha256,
        capabilityProbeReceiptSha256:
          semanticCapability.capabilityProbeReceiptSha256,
        qualificationResultSha256:
          semanticCapability.qualificationResultSha256,
        networkBoundary: Object.freeze({
          attemptedRequests: 0,
          enforced: true,
          scope: 'electron-session',
        }),
      });
    } else {
      // The pinned local model failed its real positive/defective qualification,
      // so legacy renders never call it or claim semantic visual approval. Exact
      // artifact, receipt, audio, timeline, caption, boundary, and frame-decode
      // gates above still bind the bytes released to the user.
      semanticReview = {
        mode: 'deterministic-only', available: false, performed: false,
        capability: 'visual_quality_analysis',
        reason: semanticCapability.failureCode || semanticCapability.status,
      };
      processLocalEvent({
        event: 'local-progress', stage: 'artifact-quality', measurable: false,
        message: 'Verifying deterministic artifact and decoded-frame evidence...',
        line: 'Semantic visual approval is unavailable and is not claimed; exact local evidence gates remain mandatory.',
      }, action);
    }
    await assertVisionArtifactUnchanged(
      artifact, artifactStat, artifactSha256);
    assertVisionAction(action);
    const report = visionReport({
      action, staged, artifactStat, qaReceipt, edlReceipt, captionReceipt,
      captionRenderReceipt, boundaryReceipt, mixReceipt, sequenceReceipt,
      projectIntentBinding, sfxProductionReceipt, sfxProductionBinding,
      musicProductionReceipt, musicProductionBinding,
      audioQa, plan, capture, reviewed, coverage, review, semanticReview,
      artifactSha256,
    });
    writeVisionQaReport(action, report);
    if (!coverage.complete) {
      const categories = (coverage.unobservedCategories ||
        coverage.uncapturedCategories || []).join(', ') || 'unknown';
      throw new Error(
        `Final visual QA coverage was incomplete; unobserved categories: ${categories}`);
    }
    if (semanticReview.performed && !reviewPasses(review)) {
      const issue = reviewIssueText(review);
      if (await retryRejectedRender(action, artifact, issue)) return;
      throw new Error(`Final visual QA rejected the draft: ${issue}`);
    }
    event.visionQa = {
      pass: true,
      semanticPass: semanticReview.performed ? true : null,
      semanticReviewMode: semanticReview.mode,
      score: semanticReview.performed ? review.score : null,
      coverageComplete: true,
      plannedFrames: coverage.plannedFrameCount,
      capturedFrames: coverage.capturedFrameCount,
      reviewedFrames: semanticReview.performed
        ? reviewed.reviewedFrameIds.length : 0,
      batches: reviewed.batches.length,
      artifactMode: qaReceipt.contract.mode,
      engineQaSha256: qaReceipt.sha256,
      edlSha256: edlReceipt?.sha256 || '',
      captionsSha256: captionReceipt?.sha256 || '',
      editBoundariesSha256: boundaryReceipt.sha256,
      audioMixSha256: mixReceipt.sha256,
      sequenceSha256: sequenceReceipt?.sha256 || '',
      deterministicVisualQaSha256:
        qaReceipt.deterministicVisualQa.sha256,
      deterministicVisualAnalyzerReceiptSha256:
        qaReceipt.deterministicVisualQa.record.analysis.receipt_sha256,
      ...(projectIntentBinding ? {
        projectIntentRenderReceiptSha256:
          projectIntentBinding.renderReceiptSha256,
        projectIntentAuthoritySha256:
          projectIntentBinding.engineEnvelopeSha256,
        musicProductionReceiptSha256:
          musicProductionBinding.productionReceiptSha256,
        sfxProductionReceiptSha256:
          sfxProductionBinding.productionReceiptSha256,
      } : {}),
      deterministicAudioPass: audioQa.pass,
      musicRegionCount: musicProductionBinding?.regionCount ?? 0,
      sfxCueCount: sfxProductionBinding?.cueCount ?? audioQa.sfx.boundCueCount,
      perceptualAudioReviewed: false,
      coverageSha256: report.coverageSha256,
      semanticCoverageSha256:
        semanticReview.performed ? semanticReview.semanticCoverageSha256 : '',
      calibratedReviewSha256: semanticReview.performed
        ? semanticReview.calibratedReviewSha256 : '',
      semanticReceiptSetSha256: semanticReview.performed
        ? semanticReview.semanticReceiptSetSha256 : '',
      semanticCapabilityManifestSha256: semanticReview.performed
        ? semanticReview.capabilityManifestSha256 : '',
      semanticCapabilityProbeReceiptSha256: semanticReview.performed
        ? semanticReview.capabilityProbeReceiptSha256 : '',
      semanticQualificationResultSha256: semanticReview.performed
        ? semanticReview.qualificationResultSha256 : '',
    };
    const metadata = await approvedResultMetadata(action);
    assertVisionAction(action);
    await assertVisionArtifactUnchanged(
      artifact, artifactStat, artifactSha256);
    assertVisionAction(action);
    promoteVisionArtifact(staged, artifactStat.size, artifactSha256);
    replaceEventArtifactPath(event, staged.pending, staged.approved);
    artifact = staged.approved;
    assertVisionAction(action);
    rememberResult(event, action.outputDir, metadata);
    assertVisionAction(action);
    send('helper-render', { ...event, actionId: action.id, kind: action.kind });
    markRenderFinished(action);
  } catch (caught) {
    let error = caught;
    if (staged) {
      const progress = caught?.visionProgress;
      if (progress) {
        reviewed = {
          reviewedFrameIds: progress.reviewedFrameIds || [],
          reviewedTargetIds: progress.reviewedTargetIds || [],
          batches: progress.receipts || [],
        };
      }
      if (plan && (!coverage || coverage.complete !== true)) {
        try {
          coverage = artifactFrameCaptureCoverage(plan, capture.captured);
        } catch (_) { coverage = null; }
      }
      try {
        writeVisionQaReport(action, visionReport({
          action, staged, artifactStat, qaReceipt, edlReceipt, captionReceipt,
          captionRenderReceipt, boundaryReceipt, mixReceipt, sequenceReceipt,
          projectIntentBinding, musicProductionReceipt,
          musicProductionBinding, sfxProductionReceipt, sfxProductionBinding,
          audioQa, plan, capture, reviewed, coverage,
          review, semanticReview, artifactSha256, error: error?.message || error,
        }));
      } catch (reportError) {
        error = new Error(`${error?.message || error}; final vision QA report failed: ${
          reportError.message || reportError}`);
      }
    }
    if (artifact && fs.existsSync(artifact) &&
        !/\.VISION-REJECTED(?:\.|$)/i.test(path.basename(artifact))) {
      try { quarantineRejectedArtifact(artifact); }
      catch (_) { /* failure is still reported and never registered as a result */ }
    }
    if (action.canceled || activeRender !== action) return;
    send('helper-render', {
      event: 'local-error', actionId: action.id, kind: 'render',
      stage: 'final artifact quality assurance',
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

function newLocalAction(payload, kind, settings, resultContext = null) {
  return {
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
    projectIntentAuthorityKey: '',
  };
}

function reserveLocalRender(payload, settings, resultContext = null) {
  if (activeRender) throw new Error('An edit is already rendering');
  const action = newLocalAction(payload, 'render', settings, resultContext);
  action.stage = 'policy-authorization';
  action.message = 'Authorizing the approved expert edit policy...';
  activeRender = action;
  processLocalEvent({
    event: 'local-progress', stage: action.stage, measurable: false,
    message: action.message,
    line: 'Binding the approved ProjectIntent to the measured local runtime.',
  }, action);
  send('helper-state', {
    running: true, rendering: true, chatting: !!activeChat,
    activeRender: activeRenderState(),
  });
  return action;
}

function localProcess(mode, payload, kind, settings, resultContext = null,
                      reservedAction = null) {
  const p = runtimePaths();
  const action = reservedAction || newLocalAction(
    payload, kind, settings, resultContext);
  if (reservedAction) {
    if (kind !== 'render' || activeRender !== action || action.canceled) {
      throw new Error('project intent render ownership was canceled');
    }
    action.outputDir = payload.outputDir;
    action.payload = { ...payload };
    action.settings = { ...settings };
    action.resultContext = resultContext
      ? { ...resultContext, sourceInputs: [...(resultContext.sourceInputs || [])] }
      : null;
    action.stage = 'starting';
    action.message = 'Starting the local edit...';
    action.lastActivityAt = Date.now();
  }
  const childEnv = daemonEnv(settings);
  if (kind === 'render' && action.projectIntentAuthorityKey) {
    childEnv.AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY =
      action.projectIntentAuthorityKey;
  }
  let child;
  try {
    child = spawn(p.daemon, [mode], {
      env: childEnv, windowsHide: true, cwd: p.root,
    stdio: ['pipe', 'pipe', 'pipe'],
    detached: process.platform !== 'win32',
    });
  } finally {
    action.projectIntentAuthorityKey = '';
  }
  child.__autoeditorProcessGroup = process.platform !== 'win32';
  action.proc = child;
  if (kind === 'render') {
    // A reserved ProjectIntent action already owns activeRender. Keep that
    // exact identity in the render slot; it must never overwrite chat state.
    if (reservedAction && activeRender !== action) {
      throw new Error('project intent render ownership changed before spawn');
    }
    activeRender = action;
  } else {
    activeChat = action;
  }
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
    if (kind === 'render' && activeRender === action && !action.qaPending && !action.canceled) {
      activeRender = null;
    }
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
          schema: 'autoeditor-local-media-analysis/v4',
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

function createRevisionOutputDir(outputRoot, priorResult) {
  const root = fs.realpathSync.native(outputRoot);
  const revisions = path.join(root, 'Revisions');
  try { fs.mkdirSync(revisions, { mode: 0o700 }); }
  catch (error) {
    if (error?.code !== 'EEXIST') throw error;
  }
  const revisionRoot = fs.realpathSync.native(revisions);
  const rootRelative = path.relative(root, revisionRoot);
  if (!rootRelative || rootRelative === '..' ||
      rootRelative.startsWith(`..${path.sep}`) || path.isAbsolute(rootRelative) ||
      !fs.statSync(revisionRoot).isDirectory()) {
    throw new Error('the revision output root is unsafe');
  }
  const rawStem = path.parse(priorResult).name
    .replace(/\.VISION-(?:PENDING|REJECTED)(?:\..*)?$/i, '')
    .replace(/\.UNVERIFIED(?:\..*)?$/i, '');
  const stem = rawStem.normalize('NFKC').replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^[._-]+|[._-]+$/g, '').slice(0, 60) || 'edit';
  for (let version = 1; version <= 9999; version += 1) {
    const candidate = path.join(
      revisionRoot, `${stem}-v${String(version).padStart(2, '0')}`);
    try { fs.mkdirSync(candidate, { mode: 0o700 }); }
    catch (error) {
      if (error?.code === 'EEXIST') continue;
      throw error;
    }
    const real = fs.realpathSync.native(candidate);
    if (path.dirname(real) !== revisionRoot || !fs.statSync(real).isDirectory()) {
      throw new Error('the generated revision output folder is unsafe');
    }
    return real;
  }
  throw new Error('the revision output folder limit was reached');
}

function applyLocal(raw) {
  if (activeRender) throw new Error('An edit is already rendering');
  let translated = translateVideoPaths(raw);
  let revisionInput = '';
  let revisionMetadata = null;
  let revisionOutputDir = '';
  if (raw && raw.resultPath) {
    revisionInput = realFile(raw.resultPath);
    if (!returnedOutputs.has(revisionInput)) {
      throw new Error('That revision target is not from this AutoEditor session');
    }
    revisionMetadata = returnedOutputs.get(revisionInput);
    const requestedRoot = normalizeOutputDir(translated.outputDir);
    const selectedRoot = fs.realpathSync.native(requestedRoot);
    if (!selectedOutputDirs.has(selectedRoot)) {
      throw new Error('Choose the output folder with the Choose button');
    }
    revisionOutputDir = createRevisionOutputDir(selectedRoot, revisionInput);
    translated = { ...translated, videos: [revisionInput] };
    translated.outputDir = revisionOutputDir;
    delete translated.inputs;
    delete translated.videoPaths;
    delete translated.clips;
  }
  const request = normalizeApplyRequest(translated, proposalWasReturned);
  if (revisionInput) {
    if (fs.realpathSync.native(request.outputDir) !== revisionOutputDir) {
      throw new Error('the generated revision output folder changed');
    }
    selectedOutputDirs.add(revisionOutputDir);
  } else {
    requireDialogSelection(request);
  }
  const settings = requireReady();
  const renderSettings = settingsForLocalRender(settings);
  const resultContext = {
    sourceInputs: revisionMetadata?.sourceInputs || request.inputs,
    sourceSha256: revisionMetadata?.sourceSha256 || '',
    planSha256: planSha256(request),
    priorResult: revisionInput,
  };
  if (!Object.prototype.hasOwnProperty.call(
    request.proposal, 'projectIntent')) {
    // Compatibility invariant: the legacy request bytes and spawn path are
    // unchanged when no typed ProjectIntent was explicitly proposed/approved.
    localProcess('--local-render', request, 'render', renderSettings, resultContext);
    return { ok: true };
  }

  // Ownership is reserved synchronously before the first lazy capability
  // await. Concurrent applies cannot race policy resolution or start a daemon.
  const reservation = reserveLocalRender(request, renderSettings, resultContext);
  return (async () => {
    try {
      const authorized = await authorizeProjectIntentRequest(
        request, initializeRuntimeCapabilityPreflight(), {
          isCurrent: () => activeRender === reservation && !reservation.canceled,
        });
      if (activeRender !== reservation || reservation.canceled) {
        throw new Error('project intent authorization was canceled');
      }
      reservation.projectIntentAuthorityKey = authorized.signingKey;
      localProcess('--local-render', authorized.request, 'render', renderSettings,
        resultContext, reservation);
    } catch (error) {
      reservation.projectIntentAuthorityKey = '';
      if (activeRender === reservation) activeRender = null;
      send('helper-state', {
        running: !!activeRender, rendering: !!activeRender, chatting: !!activeChat,
        activeRender: activeRenderState(),
      });
      throw error;
    }
    return { ok: true };
  })();
}

async function cancelLocal() {
  const action = activeRender;
  if (!action) return { ok: true, canceled: false };
  action.canceled = true;
  action.stage = 'canceling';
  action.message = 'Stopping the local edit...';
  action.projectIntentAuthorityKey = '';
  rejectPendingVisionForAction(action, 'local vision was canceled');
  send('helper-state', {
    running: true, rendering: true, chatting: !!activeChat,
    activeRender: activeRenderState(),
  });
  await Promise.allSettled([
    stopProcessTree(action.proc),
    runtimeCapabilityPreflight?.cancel() || Promise.resolve(false),
  ]);
  if (activeRender === action) activeRender = null;
  send('helper-render', {
    event: 'local-canceled', actionId: action.id, kind: 'render',
    stage: 'canceled', line: 'Edit canceled',
  });
  send('helper-state', {
    running: !!activeRender, rendering: !!activeRender,
    chatting: !!activeChat, activeRender: activeRenderState(),
  });
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
  initializeRuntimeCapabilityPreflight();
  registerVisionProtocol();
  enforceVisionSessionNetworkBoundary();
  setupIpc();
  createWindow();
});

app.on('before-quit', (event) => {
  if (quitDrainComplete) return;
  event.preventDefault();
  if (quitDrainStarted) return;
  quitDrainStarted = true;
  rejectPendingVision('AutoEditor is closing');
  const render = activeRender;
  const chat = activeChat;
  if (render) {
    render.canceled = true;
    render.projectIntentAuthorityKey = '';
  }
  if (chat) chat.canceled = true;
  void Promise.allSettled([
    stopProcessTree(render?.proc),
    stopProcessTree(chat?.proc),
    runtimeCapabilityPreflight?.cancel() || Promise.resolve(false),
  ]).finally(() => {
    quitDrainComplete = true;
    app.quit();
  });
});
app.on('window-all-closed', () => app.quit());

module.exports = { runtimePaths };
