'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {
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
} = require('../helper/lib/project-intent');

const EXPECTED_PROFILES = Object.freeze([
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
const KNOWN_INTENT_SHA256 =
  'c3bfc4a260163ea9375ec31ac9c704c8e42057d62965e4765e102438734e603e';

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function defaultPreferences() {
  return {
    captions: { enabled: true, preference: 'verbatim' },
    graphics: { enabled: true, preference: 'informational' },
    music: { enabled: true, preference: 'supporting' },
    sfx: { enabled: true, preference: 'motivated_only' },
    transitions: { enabled: false, preference: 'none' },
  };
}

function intent(overrides = {}) {
  return {
    schema_version: PROJECT_INTENT_SCHEMA_VERSION,
    profile: 'dialogue_talking_head',
    delivery: { platform: 'youtube', aspect: '16:9' },
    target_duration: { min_ms: 30000, max_ms: 45000 },
    preferences: defaultPreferences(),
    ...overrides,
  };
}

function rejected(candidate) {
  assert.throws(() => validateProjectIntent(candidate), ProjectIntentError);
}

assert.deepEqual(PROFILE_NAMES, EXPECTED_PROFILES);
assert.equal(PROFILE_NAMES.length, 13);
assert.equal(new Set(PROFILE_NAMES).size, 13);

for (const profile of PROFILE_NAMES) {
  const candidate = intent({ profile });
  assert.equal(validateProjectIntent(candidate).profile, profile);
}

for (const platform of PLATFORMS) {
  assert.ok(PLATFORM_ASPECTS[platform]);
  for (const aspect of PLATFORM_ASPECTS[platform]) {
    const candidate = intent({ delivery: { platform, aspect } });
    assert.deepEqual(validateProjectIntent(candidate).delivery, { platform, aspect });
  }
}

for (const [platform, aspect] of [
  ['youtube_shorts', '16:9'],
  ['tiktok', '4:5'],
  ['instagram_reels', '1:1'],
  ['instagram_feed', '16:9'],
  ['broadcast', '9:16'],
  ['archive', '21:9'],
]) {
  rejected(intent({ delivery: { platform, aspect } }));
}

for (const badProfile of ['', 'talking_head', 'generic_short', null, 13]) {
  rejected(intent({ profile: badProfile }));
}

for (const delivery of [
  { platform: 'unknown', aspect: '16:9' },
  { platform: 'youtube', aspect: 'auto' },
  { platform: 'youtube', aspect: '3:2' },
  { platform: 7, aspect: '16:9' },
  { platform: 'youtube', aspect: null },
]) {
  rejected(intent({ delivery }));
}

for (const targetDuration of [
  { min_ms: 1, max_ms: 1 },
  { min_ms: 1, max_ms: MAX_DURATION_MS },
  { min_ms: MAX_DURATION_MS, max_ms: MAX_DURATION_MS },
]) {
  assert.deepEqual(
    validateProjectIntent(intent({ target_duration: targetDuration })).target_duration,
    targetDuration,
  );
}

for (const targetDuration of [
  { min_ms: 0, max_ms: 1 },
  { min_ms: -1, max_ms: 1 },
  { min_ms: 2, max_ms: 1 },
  { min_ms: 1, max_ms: MAX_DURATION_MS + 1 },
  { min_ms: true, max_ms: 10 },
  { min_ms: 1.5, max_ms: 10 },
  { min_ms: 1, max_ms: Number.NaN },
  { min_ms: 1, max_ms: Number.POSITIVE_INFINITY },
  { min_ms: '1', max_ms: 10 },
]) {
  rejected(intent({ target_duration: targetDuration }));
}

assert.deepEqual(FEATURE_NAMES, [
  'captions', 'graphics', 'music', 'sfx', 'transitions',
]);
for (const feature of FEATURE_NAMES) {
  const modes = FEATURE_PREFERENCES[feature];
  assert.ok(modes.includes('auto'));
  assert.ok(modes.includes('none'));
  assert.equal(new Set(modes).size, modes.length);
  for (const preference of modes) {
    const candidate = intent();
    candidate.preferences[feature] = {
      enabled: preference !== 'none',
      preference,
    };
    assert.deepEqual(
      validateProjectIntent(candidate).preferences[feature],
      candidate.preferences[feature],
    );
  }
}

for (const feature of FEATURE_NAMES) {
  let candidate = intent();
  candidate.preferences[feature] = { enabled: false, preference: 'auto' };
  rejected(candidate);
  candidate = intent();
  candidate.preferences[feature] = { enabled: true, preference: 'none' };
  rejected(candidate);
  candidate = intent();
  candidate.preferences[feature] = { enabled: 1, preference: 'auto' };
  rejected(candidate);
  candidate = intent();
  candidate.preferences[feature] = { enabled: true, preference: 'unsupported' };
  rejected(candidate);
}

{
  const rootMutations = [];
  let candidate = intent();
  candidate.extra = true;
  rootMutations.push(candidate);
  candidate = intent();
  delete candidate.profile;
  rootMutations.push(candidate);
  candidate = intent();
  candidate.delivery.extra = true;
  rootMutations.push(candidate);
  candidate = intent();
  delete candidate.target_duration.max_ms;
  rootMutations.push(candidate);
  candidate = intent();
  candidate.preferences.extra = { enabled: false, preference: 'none' };
  rootMutations.push(candidate);
  candidate = intent();
  delete candidate.preferences.graphics;
  rootMutations.push(candidate);
  candidate = intent();
  candidate.preferences.captions.confidence = 1;
  rootMutations.push(candidate);
  candidate = intent();
  delete candidate.preferences.captions.enabled;
  rootMutations.push(candidate);
  rootMutations.forEach(rejected);
}

{
  const candidate = intent();
  candidate[Symbol('hidden-extra')] = true;
  rejected(candidate);
  const nested = intent();
  nested.delivery[Symbol('hidden-extra')] = true;
  rejected(nested);
}

for (const candidate of [null, [], 'intent', 3, true]) rejected(candidate);

{
  const candidate = intent();
  candidate.schema_version = 'autoeditor-project-intent/v2';
  rejected(candidate);
}

{
  const raw = intent();
  const clean = validateProjectIntent(raw);
  assert.deepEqual(clean, raw);
  assert.notEqual(clean, raw);
  assert.notEqual(clean.delivery, raw.delivery);
  assert.notEqual(clean.target_duration, raw.target_duration);
  assert.notEqual(clean.preferences, raw.preferences);
  for (const feature of FEATURE_NAMES) {
    assert.notEqual(clean.preferences[feature], raw.preferences[feature]);
  }
  raw.preferences.captions.preference = 'selective';
  assert.equal(clean.preferences.captions.preference, 'verbatim');
}

{
  const raw = intent();
  const reordered = {
    target_duration: {
      max_ms: raw.target_duration.max_ms,
      min_ms: raw.target_duration.min_ms,
    },
    schema_version: raw.schema_version,
    preferences: Object.fromEntries(
      Object.entries(raw.preferences).reverse().map(([name, preference]) => [
        name,
        { preference: preference.preference, enabled: preference.enabled },
      ]),
    ),
    profile: raw.profile,
    delivery: { aspect: raw.delivery.aspect, platform: raw.delivery.platform },
  };
  assert.equal(canonicalProjectIntentJson(raw), canonicalProjectIntentJson(reordered));
  assert.equal(projectIntentSha256(raw), projectIntentSha256(reordered));
  assert.equal(projectIntentSha256(raw), KNOWN_INTENT_SHA256);
  assert.equal(
    crypto.createHash('sha256')
      .update(Buffer.from(canonicalProjectIntentJson(raw), 'utf8'))
      .digest('hex'),
    KNOWN_INTENT_SHA256,
  );
  const changed = intent({ profile: 'commercial_product' });
  assert.notEqual(projectIntentSha256(changed), KNOWN_INTENT_SHA256);
}

{
  assert.equal(
    canonicalProjectIntentJson(intent()),
    '{"delivery":{"aspect":"16:9","platform":"youtube"},' +
      '"preferences":{"captions":{"enabled":true,"preference":"verbatim"},' +
      '"graphics":{"enabled":true,"preference":"informational"},' +
      '"music":{"enabled":true,"preference":"supporting"},' +
      '"sfx":{"enabled":true,"preference":"motivated_only"},' +
      '"transitions":{"enabled":false,"preference":"none"}},' +
      '"profile":"dialogue_talking_head",' +
      '"schema_version":"autoeditor-project-intent/v1",' +
      '"target_duration":{"max_ms":45000,"min_ms":30000}}',
  );
}

{
  assert.equal(PROJECT_INTENT_JSON_SCHEMA.additionalProperties, false);
  assert.deepEqual(
    PROJECT_INTENT_JSON_SCHEMA.properties.profile.enum,
    EXPECTED_PROFILES,
  );
  assert.deepEqual(PROJECT_INTENT_JSON_SCHEMA.properties.delivery.properties.aspect.enum, ASPECTS);
  assert.equal(
    PROJECT_INTENT_JSON_SCHEMA.properties.target_duration.properties.max_ms.maximum,
    MAX_DURATION_MS,
  );
  const preferenceSchema = PROJECT_INTENT_JSON_SCHEMA.properties.preferences;
  assert.equal(preferenceSchema.additionalProperties, false);
  assert.deepEqual(preferenceSchema.required, FEATURE_NAMES);
  for (const feature of FEATURE_NAMES) {
    assert.equal(preferenceSchema.properties[feature].additionalProperties, false);
    assert.deepEqual(
      preferenceSchema.properties[feature].properties.preference.enum,
      FEATURE_PREFERENCES[feature],
    );
  }
}

console.log('project intent contract tests passed');
