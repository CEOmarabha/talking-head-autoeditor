'use strict';

const crypto = require('node:crypto');

const PROJECT_INTENT_SCHEMA_VERSION = 'autoeditor-project-intent/v1';
const MAX_DURATION_MS = 86400000;

// Keep this surface identical to autoeditor/edit_policy.py PROFILE_NAMES.
const PROFILE_NAMES = Object.freeze([
  'commercial_product',
  'course_tutorial_screencast',
  'dialogue_talking_head',
  'documentary_narrative',
  'gaming',
  'montage_meme',
  'music_performance',
  'podcast_interview',
  'real_estate',
  'sports_highlights',
  'utility_faithful',
  'vlog_travel',
  'wedding_event',
]);
const PROFILE_SET = new Set(PROFILE_NAMES);

const PLATFORMS = Object.freeze([
  'archive',
  'broadcast',
  'facebook',
  'instagram_feed',
  'instagram_reels',
  'linkedin',
  'tiktok',
  'web',
  'x',
  'youtube',
  'youtube_shorts',
]);
const PLATFORM_SET = new Set(PLATFORMS);
const ASPECTS = Object.freeze(['1:1', '16:9', '21:9', '4:5', '9:16', 'source']);
const ASPECT_SET = new Set(ASPECTS);

const PLATFORM_ASPECTS = Object.freeze({
  youtube: Object.freeze(['16:9', '9:16', '1:1', '4:5']),
  youtube_shorts: Object.freeze(['9:16']),
  tiktok: Object.freeze(['9:16']),
  instagram_reels: Object.freeze(['9:16']),
  instagram_feed: Object.freeze(['4:5', '1:1']),
  facebook: Object.freeze(['16:9', '9:16', '4:5', '1:1']),
  x: Object.freeze(['16:9', '9:16', '1:1']),
  linkedin: Object.freeze(['16:9', '9:16', '4:5', '1:1']),
  web: ASPECTS,
  broadcast: Object.freeze(['16:9']),
  archive: Object.freeze(['source', '16:9', '9:16', '4:5', '1:1']),
});

const FEATURE_NAMES = Object.freeze([
  'captions', 'graphics', 'music', 'sfx', 'transitions',
]);
const FEATURE_PREFERENCES = Object.freeze({
  captions: Object.freeze(['auto', 'none', 'selective', 'verbatim']),
  music: Object.freeze(['auto', 'none', 'primary', 'source_primary', 'supporting']),
  sfx: Object.freeze([
    'auto', 'event_accent_only', 'interface_feedback_only', 'motivated_only', 'none',
  ]),
  graphics: Object.freeze([
    'auto', 'brand_led', 'data_driven', 'informational', 'minimal', 'none',
  ]),
  transitions: Object.freeze([
    'auto',
    'beat_or_phrase_motivated',
    'continuity_motivated',
    'hard_cut_only',
    'location_motivated',
    'motivated_only',
    'none',
  ]),
});
const FEATURE_PREFERENCE_SETS = Object.freeze(Object.fromEntries(
  FEATURE_NAMES.map((name) => [name, new Set(FEATURE_PREFERENCES[name])]),
));

const ROOT_KEYS = Object.freeze([
  'delivery', 'preferences', 'profile', 'schema_version', 'target_duration',
]);
const DELIVERY_KEYS = Object.freeze(['aspect', 'platform']);
const TARGET_DURATION_KEYS = Object.freeze(['max_ms', 'min_ms']);
const PREFERENCE_KEYS = Object.freeze(['enabled', 'preference']);

const PROJECT_INTENT_JSON_SCHEMA = Object.freeze({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  additionalProperties: false,
  required: [...ROOT_KEYS],
  properties: {
    schema_version: { const: PROJECT_INTENT_SCHEMA_VERSION },
    profile: { type: 'string', enum: [...PROFILE_NAMES] },
    delivery: {
      type: 'object',
      additionalProperties: false,
      required: [...DELIVERY_KEYS],
      properties: {
        platform: { type: 'string', enum: [...PLATFORMS] },
        aspect: { type: 'string', enum: [...ASPECTS] },
      },
    },
    target_duration: {
      type: 'object',
      additionalProperties: false,
      required: [...TARGET_DURATION_KEYS],
      properties: {
        min_ms: { type: 'integer', minimum: 1, maximum: MAX_DURATION_MS },
        max_ms: { type: 'integer', minimum: 1, maximum: MAX_DURATION_MS },
      },
    },
    preferences: {
      type: 'object',
      additionalProperties: false,
      required: [...FEATURE_NAMES],
      properties: Object.fromEntries(FEATURE_NAMES.map((name) => [name, {
        type: 'object',
        additionalProperties: false,
        required: [...PREFERENCE_KEYS],
        properties: {
          enabled: { type: 'boolean' },
          preference: { type: 'string', enum: [...FEATURE_PREFERENCES[name]] },
        },
      }])),
    },
  },
});

class ProjectIntentError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ProjectIntentError';
  }
}

function fail(message) {
  throw new ProjectIntentError(message);
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function asciiCompare(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function exactKeys(value, expected, label) {
  if (!isPlainObject(value)) fail(`${label} must be an object`);
  const ownKeys = Reflect.ownKeys(value);
  if (ownKeys.some((key) => typeof key !== 'string')) {
    fail(`${label} has invalid keys (unsupported non-string key)`);
  }
  const actual = ownKeys.sort(asciiCompare);
  if (actual.length !== expected.length ||
      actual.some((key, index) => key !== expected[index])) {
    const actualSet = new Set(actual);
    const expectedSet = new Set(expected);
    const missing = expected.filter((key) => !actualSet.has(key));
    const extra = actual.filter((key) => !expectedSet.has(key));
    const details = [];
    if (missing.length) details.push(`missing ${missing.join(', ')}`);
    if (extra.length) details.push(`unsupported ${extra.join(', ')}`);
    fail(`${label} has invalid keys (${details.join('; ')})`);
  }
  return value;
}

function member(value, allowed, label) {
  if (typeof value !== 'string' || !allowed.has(value)) {
    fail(`${label} is unsupported`);
  }
  return value;
}

function duration(value, label) {
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_DURATION_MS) {
    fail(`${label} must be an integer from 1 to ${MAX_DURATION_MS}`);
  }
  return value;
}

function normalizeFeature(value, name) {
  const raw = exactKeys(value, PREFERENCE_KEYS, `preferences.${name}`);
  if (typeof raw.enabled !== 'boolean') {
    fail(`preferences.${name}.enabled must be boolean`);
  }
  const preference = member(
    raw.preference,
    FEATURE_PREFERENCE_SETS[name],
    `preferences.${name}.preference`,
  );
  if (!raw.enabled && preference !== 'none') {
    fail(`preferences.${name}.preference must be none when disabled`);
  }
  if (raw.enabled && preference === 'none') {
    fail(`preferences.${name}.preference cannot be none when enabled`);
  }
  return { enabled: raw.enabled, preference };
}

function validateProjectIntent(value) {
  const raw = exactKeys(value, ROOT_KEYS, 'project intent');
  if (raw.schema_version !== PROJECT_INTENT_SCHEMA_VERSION) {
    fail('project intent schema_version is unsupported');
  }
  const profile = member(raw.profile, PROFILE_SET, 'profile');

  const rawDelivery = exactKeys(raw.delivery, DELIVERY_KEYS, 'delivery');
  const platform = member(rawDelivery.platform, PLATFORM_SET, 'delivery.platform');
  const aspect = member(rawDelivery.aspect, ASPECT_SET, 'delivery.aspect');
  if (!PLATFORM_ASPECTS[platform].includes(aspect)) {
    fail(`delivery.aspect ${aspect} is incompatible with ${platform}`);
  }

  const rawTarget = exactKeys(
    raw.target_duration,
    TARGET_DURATION_KEYS,
    'target_duration',
  );
  const minimum = duration(rawTarget.min_ms, 'target_duration.min_ms');
  const maximum = duration(rawTarget.max_ms, 'target_duration.max_ms');
  if (minimum > maximum) {
    fail('target_duration.min_ms cannot exceed target_duration.max_ms');
  }

  const rawPreferences = exactKeys(raw.preferences, FEATURE_NAMES, 'preferences');
  const preferences = Object.fromEntries(FEATURE_NAMES.map((name) => [
    name,
    normalizeFeature(rawPreferences[name], name),
  ]));

  return {
    schema_version: PROJECT_INTENT_SCHEMA_VERSION,
    profile,
    delivery: { platform, aspect },
    target_duration: { min_ms: minimum, max_ms: maximum },
    preferences,
  };
}

function pythonAsciiString(value) {
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
      const high = 0xd800 + (adjusted >> 10);
      const low = 0xdc00 + (adjusted & 0x3ff);
      result += `\\u${high.toString(16)}\\u${low.toString(16)}`;
    }
  }
  return `${result}"`;
}

function canonicalData(value) {
  if (value === null) return 'null';
  if (value === true) return 'true';
  if (value === false) return 'false';
  if (typeof value === 'string') return pythonAsciiString(value);
  if (typeof value === 'number' && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(canonicalData).join(',')}]`;
  if (isPlainObject(value)) {
    const keys = Object.keys(value).sort(asciiCompare);
    return `{${keys.map((key) => (
      `${pythonAsciiString(key)}:${canonicalData(value[key])}`
    )).join(',')}}`;
  }
  fail('project intent is not canonical JSON');
}

function canonicalProjectIntentJson(value) {
  return canonicalData(validateProjectIntent(value));
}

function projectIntentSha256(value) {
  return crypto.createHash('sha256')
    .update(canonicalProjectIntentJson(value), 'utf8')
    .digest('hex');
}

module.exports = Object.freeze({
  PROJECT_INTENT_SCHEMA_VERSION,
  MAX_DURATION_MS,
  PROFILE_NAMES,
  PLATFORMS,
  ASPECTS,
  PLATFORM_ASPECTS,
  FEATURE_NAMES,
  FEATURE_PREFERENCES,
  PROJECT_INTENT_JSON_SCHEMA,
  ProjectIntentError,
  validateProjectIntent,
  canonicalProjectIntentJson,
  projectIntentSha256,
});
