'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  CAPABILITIES,
  PROFILE_NAMES,
  editPolicySha256,
} = require('../helper/lib/edit-policy');
const {
  PROJECT_INTENT_SCHEMA_VERSION,
  CAPABILITY_MANIFEST_SCHEMA_VERSION,
  CAPABILITY_MANIFEST_SOURCE,
  CURRENT_RUNTIME_CAPABILITIES,
  ProjectIntentPolicyBridgeError,
  validateProjectIntent,
  validateCapabilityManifest,
  buildEditPolicyRequest,
  resolveProjectIntentPolicy,
} = require('../helper/lib/project-intent-policy-bridge');

const EXPECTED_CURRENT_RUNTIME_CAPABILITIES = Object.freeze([
  'artifact_receipts',
  'audio_crossfades',
  'audio_quality_analysis',
  'caption_rendering',
  'chart_rendering',
  'color_normalization',
  'cross_dissolves',
  'dialogue_cleanup',
  'graphic_rendering',
  'hard_cuts',
  'loudness_normalization',
  'motion_quality_analysis',
  'project_generated_music',
  'project_generated_sfx',
  'scene_detection',
  'speech_transcription',
  'visual_quality_analysis',
  'word_timestamps',
]);
const PYTHON_PARITY_POLICY_SHA256 =
  '973f80e3c2dcc72dbeee6b2b1aa5e04b4d083f40013ad19f425ec22649d0d3a0';

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function preferences(overrides = {}) {
  const values = {
    captions: 'auto',
    graphics: 'auto',
    music: 'auto',
    sfx: 'auto',
    transitions: 'auto',
    ...overrides,
  };
  return Object.fromEntries(Object.entries(values).map(([name, preference]) => [
    name,
    { enabled: preference !== 'none', preference },
  ]));
}

function intent({
  profile = 'dialogue_talking_head',
  minMs = 30000,
  maxMs = 45000,
  platform = 'youtube',
  aspect = '16:9',
  preferenceOverrides = {},
} = {}) {
  return {
    schema_version: PROJECT_INTENT_SCHEMA_VERSION,
    profile,
    delivery: { platform, aspect },
    target_duration: { min_ms: minMs, max_ms: maxMs },
    preferences: preferences(preferenceOverrides),
  };
}

function manifest(capabilities = CAPABILITIES, overrides = {}) {
  return {
    schema_version: CAPABILITY_MANIFEST_SCHEMA_VERSION,
    source: CAPABILITY_MANIFEST_SOURCE,
    probe_receipt_sha256: 'a'.repeat(64),
    available_capabilities: [...capabilities].sort(),
    ...overrides,
  };
}

function bridgeRejects(callback, pattern = undefined) {
  assert.throws(callback, (error) => (
    error instanceof ProjectIntentPolicyBridgeError &&
    (!pattern || pattern.test(error.message))
  ));
}

assert.deepEqual(CURRENT_RUNTIME_CAPABILITIES, EXPECTED_CURRENT_RUNTIME_CAPABILITIES);
assert.ok(CURRENT_RUNTIME_CAPABILITIES.length < CAPABILITIES.length);
assert.ok(CURRENT_RUNTIME_CAPABILITIES.every((name) => CAPABILITIES.includes(name)));

{
  const raw = intent({ preferenceOverrides: { captions: 'verbatim', music: 'none' } });
  const clean = validateProjectIntent(raw);
  assert.deepEqual(clean, raw);
  assert.notEqual(clean, raw);
  assert.notEqual(clean.delivery, raw.delivery);
  assert.notEqual(clean.preferences, raw.preferences);
  raw.preferences.captions.preference = 'selective';
  assert.equal(clean.preferences.captions.preference, 'verbatim');
}

{
  const raw = manifest(CURRENT_RUNTIME_CAPABILITIES);
  const clean = validateCapabilityManifest(raw);
  assert.deepEqual(clean, raw);
  assert.notEqual(clean, raw);
  assert.notEqual(clean.available_capabilities, raw.available_capabilities);
  raw.available_capabilities.length = 0;
  assert.deepEqual(clean.available_capabilities, CURRENT_RUNTIME_CAPABILITIES);
}

{
  const invalid = [];
  let candidate = manifest();
  candidate.extra = true;
  invalid.push(candidate);
  invalid.push(manifest(CAPABILITIES, { schema_version: 'capabilities/v2' }));
  invalid.push(manifest(CAPABILITIES, { source: 'model_claim' }));
  invalid.push(manifest(CAPABILITIES, { probe_receipt_sha256: 'A'.repeat(64) }));
  invalid.push(manifest(CAPABILITIES, { probe_receipt_sha256: 'a'.repeat(63) }));
  invalid.push(manifest(CAPABILITIES, { available_capabilities: 'hard_cuts' }));
  invalid.push(manifest(CAPABILITIES, { available_capabilities: ['hard_cuts', 7] }));
  candidate = manifest();
  candidate.available_capabilities.reverse();
  invalid.push(candidate);
  candidate = manifest();
  candidate.available_capabilities.push(candidate.available_capabilities[0]);
  invalid.push(candidate);
  candidate = manifest();
  candidate.available_capabilities.push('telepathy');
  candidate.available_capabilities.sort();
  invalid.push(candidate);
  candidate = manifest();
  candidate[Symbol('model-capability-claim')] = true;
  invalid.push(candidate);
  candidate = manifest();
  delete candidate.available_capabilities[0];
  invalid.push(candidate);
  invalid.forEach((value) => bridgeRejects(() => validateCapabilityManifest(value)));
}

{
  // API keys, model names, and user claims are rejected as unknown manifest
  // keys. They cannot be converted into local runtime capability claims.
  for (const claim of [
    { api_key: 'secret' },
    { model: 'deepseek-v4-pro' },
    { user_claimed_capabilities: [...CAPABILITIES] },
  ]) {
    bridgeRejects(
      () => validateCapabilityManifest({ ...manifest([]), ...claim }),
      /invalid keys/,
    );
  }
  const empty = validateCapabilityManifest(manifest([]));
  assert.deepEqual(empty.available_capabilities, []);
  bridgeRejects(
    () => resolveProjectIntentPolicy(intent(), empty),
    /capability gate failed/,
  );
}

{
  const project = intent({
    preferenceOverrides: {
      captions: 'verbatim',
      graphics: 'none',
      music: 'none',
      sfx: 'motivated_only',
      transitions: 'hard_cut_only',
    },
  });
  const request = buildEditPolicyRequest(project, manifest());
  assert.equal(request.profile, 'dialogue_talking_head');
  assert.equal(request.duration_ms, 45000);
  assert.deepEqual(request.delivery, project.delivery);
  assert.deepEqual(request.explicit_intent, {
    cut_density: 'auto',
    sfx_density: 'auto',
    transition_density: 'none',
    dialogue_rule: 'auto',
    music_rule: 'forbidden',
    caption_rule: 'verbatim_required',
    visualization_rule: 'forbidden',
  });
  assert.deepEqual(request.consented_preferences, {
    consented: false,
    values: {
      cut_density: 'auto',
      sfx_density: 'auto',
      transition_density: 'auto',
      dialogue_rule: 'auto',
      music_rule: 'auto',
      caption_rule: 'auto',
      visualization_rule: 'auto',
    },
  });
  assert.deepEqual(request.available_capabilities, [...CAPABILITIES].sort());
}

for (const [feature, preference] of [
  ['captions', 'selective'],
  ['graphics', 'brand_led'],
  ['graphics', 'data_driven'],
  ['graphics', 'informational'],
  ['graphics', 'minimal'],
]) {
  bridgeRejects(
    () => buildEditPolicyRequest(intent({
      preferenceOverrides: { [feature]: preference },
    }), manifest()),
    /cannot represent/,
  );
}

assert.equal(buildEditPolicyRequest(
  intent({ minMs: 15001, maxMs: 60000 }),
  manifest(),
).duration_ms, 60000);
for (const boundary of [15000, 60000, 300000, 1800000]) {
  bridgeRejects(
    () => buildEditPolicyRequest(
      intent({ minMs: boundary, maxMs: boundary + 1 }),
      manifest(),
    ),
    /crosses edit-policy duration bands/,
  );
}

{
  const project = intent({
    preferenceOverrides: {
      captions: 'verbatim',
      graphics: 'none',
      music: 'none',
      sfx: 'motivated_only',
      transitions: 'motivated_only',
    },
  });
  const policy = resolveProjectIntentPolicy(project, manifest());
  assert.deepEqual(policy.duration, { duration_ms: 45000, band: 'short' });
  assert.equal(policy.rules.captions.usage, 'verbatim_required');
  assert.equal(policy.rules.music.usage, 'forbidden');
  assert.equal(policy.rules.sfx.usage, 'motivated_only');
  assert.notEqual(policy.rules.sfx.density, 'none');
  assert.equal(policy.rules.transitions.usage, 'motivated_only');
  assert.notEqual(policy.rules.transitions.density, 'none');
  assert.equal(editPolicySha256(policy), PYTHON_PARITY_POLICY_SHA256);

  const minimal = resolveProjectIntentPolicy(
    project,
    manifest(policy.required_capabilities),
  );
  assert.equal(editPolicySha256(minimal), PYTHON_PARITY_POLICY_SHA256);
}

for (const [feature, preference] of [
  ['sfx', 'event_accent_only'],
  ['transitions', 'location_motivated'],
]) {
  bridgeRejects(
    () => resolveProjectIntentPolicy(intent({
      preferenceOverrides: { [feature]: preference },
    }), manifest()),
    /does not support requested/,
  );
}

{
  const policy = resolveProjectIntentPolicy(intent({
    preferenceOverrides: { transitions: 'hard_cut_only' },
  }), manifest());
  assert.equal(policy.rules.transitions.density, 'none');
}

{
  const missingHardCuts = CAPABILITIES.filter((name) => name !== 'hard_cuts');
  bridgeRejects(
    () => resolveProjectIntentPolicy(intent(), manifest(missingHardCuts)),
    /missing: hard_cuts/,
  );
}

{
  const failures = {};
  const resolved = new Set();
  for (const profile of PROFILE_NAMES) {
    const disabled = {
      captions: 'none',
      graphics: profile === 'course_tutorial_screencast' ? 'auto' : 'none',
      music: profile === 'music_performance' ? 'auto' : 'none',
      sfx: 'none',
      transitions: 'none',
    };
    try {
      resolveProjectIntentPolicy(
        intent({ profile, preferenceOverrides: disabled }),
        manifest(CURRENT_RUNTIME_CAPABILITIES),
      );
      resolved.add(profile);
    } catch (error) {
      assert.ok(error instanceof ProjectIntentPolicyBridgeError);
      assert.match(error.message, /capability gate failed/);
      failures[profile] = error.message;
    }
  }
  assert.deepEqual([...resolved].sort(), [
    'commercial_product', 'dialogue_talking_head', 'utility_faithful',
  ]);
  assert.deepEqual(Object.keys(failures).sort(),
    PROFILE_NAMES.filter((profile) => !resolved.has(profile)).sort());
  assert.match(failures.podcast_interview, /multicam_sync/);
  assert.match(failures.course_tutorial_screencast, /motion_tracking/);
}

{
  const project = intent();
  const trustedManifest = manifest();
  const beforeProject = clone(project);
  const beforeManifest = clone(trustedManifest);
  resolveProjectIntentPolicy(project, trustedManifest);
  assert.deepEqual(project, beforeProject);
  assert.deepEqual(trustedManifest, beforeManifest);

  const request = buildEditPolicyRequest(project, trustedManifest);
  project.delivery.aspect = '9:16';
  trustedManifest.available_capabilities.length = 0;
  assert.equal(request.delivery.aspect, '16:9');
  assert.deepEqual(request.available_capabilities, [...CAPABILITIES].sort());
}

{
  const bridgeSource = fs.readFileSync(path.join(
    __dirname, '..', 'helper', 'lib', 'project-intent-policy-bridge.js'), 'utf8');
  assert.doesNotMatch(bridgeSource, /process\.env|deepseekApiKey|OPENAI_API_KEY/);
  assert.match(bridgeSource, /validateCapabilityManifest\(capabilityManifest\)/);
  assert.doesNotMatch(bridgeSource, /available_capabilities:\s*\[\.\.\.CAPABILITIES\]/);
}

console.log('project intent policy bridge tests passed');
