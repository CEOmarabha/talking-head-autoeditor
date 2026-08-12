const fs = require('fs');
const crypto = require('crypto');
const path = require('path');

const MAX_INPUTS = 20;
const MAX_SCRIPT_CHARS = 200000;
const MAX_CACHED_TRANSCRIPT_CHARS = 30000;
const MAX_CREATIVE_BRIEF_CHARS = 8000;
const MAX_KEY_CHARS = 8192;
const MAX_CHAT_TEXT_CHARS = 4000;
const MAX_TRANSCRIPT_CHARS = 20000;
const MAX_HISTORY_ENTRIES = 12;
const MAX_HISTORY_CONTENT_CHARS = 2000;
const MAX_HISTORY_TOTAL_CHARS = 12000;
const MAX_PROPOSAL_CHARS = 100000;
const MAX_PROPOSAL_DEPTH = 12;
const MAX_PROPOSAL_VALUES = 2000;
const MAX_PATH_CHARS = 32768;

// Python remains authoritative for engine CLI and revision mappings. This
// frozen metadata is only the desktop-side project allowlist and join layout.
const PROJECT_ARGS = Object.freeze({
  short: Object.freeze({ width: 1080, height: 1920 }),
  long: Object.freeze({ width: 1920, height: 1080 }),
  commercial: Object.freeze({ width: 1080, height: 1920 }),
  podcast: Object.freeze({ width: 1920, height: 1080 }),
  course: Object.freeze({ width: 1920, height: 1080 }),
  custom: Object.freeze({ width: 1920, height: 1080 }),
});

const SETTING_KEYS = Object.freeze([
  'deepseekApiKey',
  'pexelsApiKey',
  'pixabayApiKey',
  'elevenLabsApiKey',
  'remotionKey',
]);
const SETTING_KEY_SET = new Set(SETTING_KEYS);
const FORBIDDEN_JSON_KEYS = new Set(['__proto__', 'prototype', 'constructor']);

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function requirePlainObject(value, label) {
  if (!isPlainObject(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value;
}

function normalizePathText(raw, label, { absolute = false } = {}) {
  if (typeof raw !== 'string') {
    throw new TypeError(`${label} must be a string path`);
  }
  if (raw.length === 0) throw new Error(`${label} must not be empty`);
  if (raw.includes('\0')) throw new Error(`${label} must not contain NUL`);
  if (raw.length > MAX_PATH_CHARS) {
    throw new Error(`${label} is longer than ${MAX_PATH_CHARS} characters`);
  }
  if (absolute && !path.isAbsolute(raw)) {
    throw new Error(`${label} must be an absolute path`);
  }
  return path.resolve(raw);
}

function existingPath(raw, label, kind, options) {
  const normalized = normalizePathText(raw, label, options);
  let stat;
  try {
    stat = fs.statSync(normalized);
  } catch (error) {
    if (error && (error.code === 'ENOENT' || error.code === 'ENOTDIR')) {
      throw new Error(`${label} does not exist`);
    }
    throw new Error(`${label} could not be accessed`);
  }
  if (kind === 'file' && !stat.isFile()) {
    throw new Error(`${label} must be an existing regular file`);
  }
  if (kind === 'directory' && !stat.isDirectory()) {
    throw new Error(`${label} must be an existing directory`);
  }
  return normalized;
}

function normalizeVideoPaths(raw) {
  if (!Array.isArray(raw) || raw.length < 1 || raw.length > MAX_INPUTS) {
    throw new Error(`video inputs must contain between 1 and ${MAX_INPUTS} files`);
  }
  const normalized = raw.map((value, index) => existingPath(
    value, `video input ${index + 1}`, 'file'));
  const seen = new Set();
  for (const value of normalized) {
    const key = process.platform === 'win32' ? value.toLowerCase() : value;
    if (seen.has(key)) throw new Error('the same video was selected more than once');
    seen.add(key);
  }
  return normalized;
}

function normalizeOutputDir(raw) {
  return existingPath(raw, 'output directory', 'directory');
}

function normalizeResultPath(raw) {
  return existingPath(raw, 'result path', 'file', { absolute: true });
}

function normalizeProjectType(raw) {
  if (typeof raw !== 'string') {
    throw new TypeError('project type must be a string');
  }
  if (!Object.prototype.hasOwnProperty.call(PROJECT_ARGS, raw)) {
    throw new Error(`unsupported project type: ${raw}`);
  }
  return raw;
}

function normalizeString(raw, label, maxChars, { nonempty = false } = {}) {
  if (typeof raw !== 'string') {
    throw new TypeError(`${label} must be a string`);
  }
  if (raw.length > maxChars) {
    throw new Error(`${label} must be at most ${maxChars} characters`);
  }
  if (nonempty && raw.trim().length === 0) {
    throw new Error(`${label} must not be empty`);
  }
  return raw;
}

function suppliedAlias(input, names, label) {
  const supplied = names.filter((name) =>
    Object.prototype.hasOwnProperty.call(input, name));
  if (supplied.length > 1) {
    throw new Error(`${label} was supplied more than once`);
  }
  return supplied.length === 1 ? input[supplied[0]] : undefined;
}

function normalizeLocalRequest(input) {
  requirePlainObject(input, 'local render request');
  const videos = suppliedAlias(input,
    ['inputs', 'videos', 'videoPaths', 'clips'],
    'video inputs');
  const outputDir = suppliedAlias(input, ['outputDir', 'outDir'],
    'output directory');
  const visionAttempt = input.visionAttempt ?? 0;
  if (!Number.isSafeInteger(visionAttempt) || visionAttempt < 0 || visionAttempt > 1) {
    throw new Error('vision attempt must be 0 or 1');
  }
  const creativeBrief = normalizeString(input.creativeBrief ?? '',
    'creative brief', MAX_CREATIVE_BRIEF_CHARS).trim();
  const creativeBriefSha256 = input.creativeBriefSha256 ?? '';
  if (typeof creativeBriefSha256 !== 'string' ||
      (creativeBriefSha256 && !/^[0-9a-f]{64}$/.test(creativeBriefSha256))) {
    throw new Error('creative brief digest is invalid');
  }
  const measuredDigest = crypto.createHash('sha256')
    .update(creativeBrief, 'utf8').digest('hex');
  if (creativeBriefSha256 && creativeBriefSha256 !== measuredDigest) {
    throw new Error('creative brief digest does not match');
  }
  return {
    inputs: normalizeVideoPaths(videos),
    outputDir: normalizeOutputDir(outputDir),
    projectType: normalizeProjectType(input.projectType),
    script: normalizeString(input.script, 'script', MAX_SCRIPT_CHARS),
    cachedTranscript: normalizeString(input.cachedTranscript ?? '',
      'cached transcript', MAX_CACHED_TRANSCRIPT_CHARS),
    creativeBrief,
    creativeBriefSha256: creativeBrief ? measuredDigest : '',
    visionAttempt,
  };
}

function normalizeLocalSettings(input) {
  requirePlainObject(input, 'local settings');
  const normalized = {};
  for (const key of Reflect.ownKeys(input)) {
    if (typeof key !== 'string' || !SETTING_KEY_SET.has(key)) {
      throw new Error(`unknown setting: ${String(key)}`);
    }
    const value = input[key];
    if (typeof value !== 'string') {
      throw new TypeError(`${key} must be a string`);
    }
    if (value.length > MAX_KEY_CHARS) {
      throw new Error(`${key} must be at most ${MAX_KEY_CHARS} characters`);
    }
    normalized[key] = value.trim();
  }
  return normalized;
}

function settingsForLocalRender(input) {
  return normalizeLocalSettings(input);
}

function normalizeHistory(raw) {
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) throw new TypeError('history must be an array');
  if (raw.length > MAX_HISTORY_ENTRIES) {
    throw new Error(`history must contain at most ${MAX_HISTORY_ENTRIES} entries`);
  }
  let totalChars = 0;
  const history = raw.map((entry, index) => {
    requirePlainObject(entry, `history entry ${index + 1}`);
    const keys = Reflect.ownKeys(entry);
    if (keys.some((key) => key !== 'role' && key !== 'content')) {
      throw new Error(`history entry ${index + 1} has an unknown field`);
    }
    if (entry.role !== 'user' && entry.role !== 'assistant') {
      throw new Error(`history entry ${index + 1} role must be user or assistant`);
    }
    const content = normalizeString(entry.content,
      `history entry ${index + 1} content`, MAX_HISTORY_CONTENT_CHARS);
    totalChars += content.length;
    return { role: entry.role, content };
  });
  if (totalChars > MAX_HISTORY_TOTAL_CHARS) {
    throw new Error(
      `history content must total at most ${MAX_HISTORY_TOTAL_CHARS} characters`);
  }
  return history;
}

function normalizeChatRequest(input) {
  requirePlainObject(input, 'local chat request');
  if (input.research !== undefined && typeof input.research !== 'boolean') {
    throw new TypeError('research must be a boolean');
  }
  if (input.videoCount !== undefined && (!Number.isInteger(input.videoCount) ||
      input.videoCount < 0 || input.videoCount > MAX_INPUTS)) {
    throw new Error(`video count must be between 0 and ${MAX_INPUTS}`);
  }
  return {
    text: normalizeString(input.text, 'chat text', MAX_CHAT_TEXT_CHARS,
      { nonempty: true }),
    projectType: normalizeProjectType(input.projectType),
    transcript: normalizeString(
      input.transcript, 'transcript', MAX_TRANSCRIPT_CHARS),
    history: normalizeHistory(input.history),
    research: input.research === true,
    videoCount: input.videoCount || 0,
  };
}

function cloneJsonValue(value, state, depth) {
  state.values += 1;
  if (state.values > MAX_PROPOSAL_VALUES || depth > MAX_PROPOSAL_DEPTH) {
    throw new Error('proposal must be bounded plain JSON');
  }
  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('proposal must be plain JSON');
    return value;
  }
  if (typeof value !== 'object') throw new Error('proposal must be plain JSON');
  if (state.stack.has(value)) throw new Error('proposal must be plain JSON');
  state.stack.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((item) => cloneJsonValue(item, state, depth + 1));
    }
    if (!isPlainObject(value)) throw new Error('proposal must be plain JSON');
    const clone = Object.create(null);
    for (const key of Reflect.ownKeys(value)) {
      if (typeof key !== 'string' || FORBIDDEN_JSON_KEYS.has(key)) {
        throw new Error('proposal must be plain JSON');
      }
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !descriptor.enumerable || !('value' in descriptor)) {
        throw new Error('proposal must be plain JSON');
      }
      clone[key] = cloneJsonValue(descriptor.value, state, depth + 1);
    }
    return clone;
  } finally {
    state.stack.delete(value);
  }
}

function normalizeProposal(raw) {
  if (!isPlainObject(raw)) throw new TypeError('proposal must be an object');
  const clone = cloneJsonValue(raw, { stack: new WeakSet(), values: 0 }, 0);
  const serialized = JSON.stringify(clone);
  if (serialized.length > MAX_PROPOSAL_CHARS) {
    throw new Error(`proposal must be at most ${MAX_PROPOSAL_CHARS} characters`);
  }
  return JSON.parse(serialized);
}

function normalizeApplyRequest(input, validateProposal) {
  requirePlainObject(input, 'local apply request');
  const request = normalizeLocalRequest(input);
  const proposal = normalizeProposal(input.proposal);
  if (validateProposal !== undefined) {
    if (typeof validateProposal !== 'function') {
      throw new TypeError('proposal validator must be a function');
    }
    if (validateProposal(proposal) === false) {
      throw new Error('proposal was rejected');
    }
  }
  return { ...request, proposal };
}

function joinPlan(inputs, projectType, ffmpeg, joinedPath) {
  const normalizedInputs = normalizeVideoPaths(inputs);
  const project = PROJECT_ARGS[normalizeProjectType(projectType)];
  if (normalizedInputs.length === 1) return null;
  if (typeof ffmpeg !== 'string' || ffmpeg.trim().length === 0 ||
      ffmpeg.includes('\0')) {
    throw new Error('FFmpeg command must be a nonempty string');
  }
  const output = normalizePathText(joinedPath, 'joined output path',
    { absolute: true });
  if (normalizedInputs.includes(output)) {
    throw new Error('joined output path must not overwrite an input file');
  }
  const parent = path.dirname(output);
  let parentStat;
  try {
    parentStat = fs.statSync(parent);
  } catch (_) {
    throw new Error('joined output directory does not exist');
  }
  if (!parentStat.isDirectory()) {
    throw new Error('joined output directory must be a directory');
  }

  const inputArgs = normalizedInputs.flatMap((input) => ['-i', input]);
  const streams = normalizedInputs.map((_, index) =>
    `[${index}:v]scale=${project.width}:${project.height}:` +
    'force_original_aspect_ratio=decrease,' +
    `pad=${project.width}:${project.height}:(ow-iw)/2:(oh-ih)/2,` +
    `setsar=1,fps=30[v${index}];` +
    `[${index}:a]aresample=48000[a${index}]`);
  const concatInputs = normalizedInputs.map((_, index) =>
    `[v${index}][a${index}]`).join('');
  const filter = streams.join(';') + ';' + concatInputs +
    `concat=n=${normalizedInputs.length}:v=1:a=1[v][a]`;
  return {
    command: ffmpeg,
    args: [
      '-y', ...inputArgs,
      '-filter_complex', filter,
      '-map', '[v]', '-map', '[a]',
      '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
      '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', output,
    ],
  };
}

function parseEngineEvent(line) {
  if (typeof line !== 'string') return null;
  const trimmed = line.trim();
  if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) return null;
  try {
    const event = JSON.parse(trimmed);
    if (!isPlainObject(event) || typeof event.event !== 'string' ||
        event.event.trim().length === 0) {
      return null;
    }
    return event;
  } catch (_) {
    return null;
  }
}

function engineProgress(line) {
  if (typeof line !== 'string') return null;
  const text = line.trim().toLowerCase();
  const rules = [
    [/media-analysis|sampling local frames|probing local video/,
      'media-analysis', 'Inspecting the video on this computer...'],
    [/^research$|research:/,
      'research', 'Researching relevant current public sources...'],
    [/^deepseek$|deepseek v4/,
      'deepseek', 'DeepSeek is preparing the edit plan...'],
    [/transcribe-only|faster-whisper word-level transcript|transcrib/,
      'transcription', 'Transcribing audio, still working'],
    [/phase 1:/, 'preparing', 'Preparing the footage...'],
    [/phase 2|silence cut|word-guarded cut/, 'cutting',
      'Removing pauses and tightening the edit...'],
    [/phase 3/, 'captions', 'Aligning speech and captions...'],
    [/phase 4p:/, 'planning', 'Planning the visual edit...'],
    [/phase 5\/6:/, 'visuals', 'Adding visuals and graphics...'],
    [/phase 6:/, 'encoding', 'Building the final format...'],
    [/phase 7:/, 'quality-assurance', 'Checking video and audio quality...'],
    [/phase 8:/, 'saving', 'Saving the finished video...'],
  ];
  for (const [pattern, stage, message] of rules) {
    if (pattern.test(text)) return { stage, message, measurable: false };
  }
  return null;
}

module.exports = {
  PROJECT_ARGS,
  normalizeVideoPaths,
  normalizeOutputDir,
  normalizeResultPath,
  normalizeLocalRequest,
  normalizeChatRequest,
  normalizeApplyRequest,
  normalizeLocalSettings,
  settingsForLocalRender,
  joinPlan,
  parseEngineEvent,
  engineProgress,
};
