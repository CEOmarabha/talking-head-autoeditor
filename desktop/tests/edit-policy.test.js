'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const {
  EDIT_POLICY_REQUEST_SCHEMA_VERSION,
  EDIT_POLICY_SCHEMA_VERSION,
  MAX_DURATION_MS,
  CAPABILITIES,
  PLATFORMS,
  ASPECTS,
  PROFILE_NAMES,
  DURATION_BANDS,
  EditPolicyError,
  durationBand,
  resolveEditPolicy,
  validateEditPolicy,
  canonicalEditPolicyJson,
  editPolicySha256,
} = require('../helper/lib/edit-policy');

const POLICY_FIELDS = Object.freeze([
  'cut_density',
  'sfx_density',
  'transition_density',
  'dialogue_rule',
  'music_rule',
  'caption_rule',
  'visualization_rule',
]);

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

const FIXED_VECTORS = Object.freeze({
  // Generated independently with autoeditor/edit_policy.py. These do not
  // change merely because both implementations are edited together.
  talking_head: Object.freeze({
    sha256: '639fe50fc4bd23f368660d11f523e76e4f45ffd563f8dc00e849ad3e62d4d23b',
    canonicalLength: 2185,
  }),
  vlog_override: Object.freeze({
    sha256: 'aa93a7868b1b5ab064f0f17ff8fff8aa8daa13ddb9ced40dc2e7d6412135ff95',
    canonicalLength: 2193,
  }),
  faithful_micro: Object.freeze({
    sha256: '9bfac002a3344036ceca850bf4218481b1d346b5c877d3348df390e6c03168ed',
    canonicalLength: 1691,
  }),
  performance: Object.freeze({
    sha256: '3cf848775403c4546da8468748c4cb975b1b49c7ce71aa2fded1af7dc02ca560',
    canonicalLength: 1906,
  }),
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function autoValues() {
  return Object.fromEntries(POLICY_FIELDS.map((field) => [field, 'auto']));
}

function request({
  profile = 'dialogue_talking_head',
  durationMs = 45_000,
  platform = 'youtube',
  aspect = 'auto',
} = {}) {
  return {
    schema_version: EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    profile,
    duration_ms: durationMs,
    delivery: { platform, aspect },
    explicit_intent: autoValues(),
    consented_preferences: {
      consented: false,
      values: autoValues(),
    },
    available_capabilities: [...CAPABILITIES],
  };
}

function vectorRequests() {
  const talkingHead = request();

  const vlog = request({
    profile: 'vlog_travel',
    durationMs: 2_000_000,
    platform: 'instagram_feed',
    aspect: '1:1',
  });
  vlog.consented_preferences.consented = true;
  vlog.consented_preferences.values.transition_density = 'dense';
  vlog.consented_preferences.values.cut_density = 'very_high';
  vlog.explicit_intent.music_rule = 'forbidden';
  vlog.explicit_intent.caption_rule = 'verbatim_required';
  vlog.explicit_intent.visualization_rule = 'required';

  const faithful = request({
    profile: 'utility_faithful',
    durationMs: 15_000,
    platform: 'tiktok',
  });
  faithful.explicit_intent.caption_rule = 'forbidden';

  const performance = request({
    profile: 'music_performance',
    durationMs: 300_001,
    platform: 'tiktok',
  });
  performance.explicit_intent.transition_density = 'dense';

  return Object.freeze({
    talking_head: talkingHead,
    vlog_override: vlog,
    faithful_micro: faithful,
    performance,
  });
}

function pythonResolve(requests, { canonical = false } = {}) {
  const script = [
    'import json,sys',
    'from autoeditor.edit_policy import resolve_edit_policy, canonical_edit_policy_json, edit_policy_sha256',
    'requests=json.load(sys.stdin)',
    'out=[]',
    'for request in requests:',
    ' policy=resolve_edit_policy(request)',
    ` out.append({'sha256':edit_policy_sha256(policy)${canonical
      ? ",'canonical':canonical_edit_policy_json(policy)"
      : ''}})`,
    "json.dump(out,sys.stdout,separators=(',',':'))",
  ].join('\n');
  const executable = process.env.AUTOEDITOR_PYTHON ||
    (process.platform === 'win32' ? 'python' : 'python3');
  const result = spawnSync(executable, ['-c', script], {
    cwd: path.resolve(__dirname, '..', '..'),
    input: JSON.stringify(requests),
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
  });
  assert.equal(
    result.status,
    0,
    `Python edit-policy vector failed: ${result.stderr || result.stdout}`,
  );
  return JSON.parse(result.stdout);
}

// Surface and profile defaults.
assert.deepEqual(PROFILE_NAMES, EXPECTED_PROFILES);
assert.equal(PROFILE_NAMES.length, 13);
assert.deepEqual(DURATION_BANDS, ['micro', 'short', 'medium', 'long', 'extended']);
assert.deepEqual(PLATFORMS, [
  'archive', 'broadcast', 'facebook', 'instagram_feed', 'instagram_reels',
  'linkedin', 'tiktok', 'web', 'x', 'youtube', 'youtube_shorts',
]);

const expectedDefaults = Object.freeze({
  dialogue_talking_head:
    ['high', 'sparse', 'sparse', 'primary', 'supporting', 'required', 'allowed'],
  podcast_interview:
    ['high', 'none', 'sparse', 'primary', 'supporting', 'required', 'allowed'],
  course_tutorial_screencast:
    ['medium', 'sparse', 'sparse', 'primary', 'optional', 'required', 'required'],
  commercial_product:
    ['high', 'medium', 'medium', 'supporting', 'supporting', 'required', 'recommended'],
  vlog_travel:
    ['high', 'medium', 'sparse', 'supporting', 'supporting', 'required', 'allowed'],
  gaming:
    ['very_high', 'medium', 'sparse', 'supporting', 'optional', 'required', 'allowed'],
  wedding_event:
    ['medium', 'sparse', 'medium', 'supporting', 'supporting', 'optional', 'forbidden'],
  sports_highlights:
    ['very_high', 'dense', 'medium', 'supporting', 'supporting', 'optional', 'recommended'],
  music_performance:
    ['high', 'sparse', 'medium', 'none', 'source_primary', 'optional', 'forbidden'],
  real_estate:
    ['medium', 'sparse', 'medium', 'supporting', 'supporting', 'optional', 'recommended'],
  documentary_narrative:
    ['low', 'none', 'sparse', 'primary', 'supporting', 'required', 'recommended'],
  montage_meme:
    ['very_high', 'dense', 'medium', 'supporting', 'primary', 'required', 'allowed'],
  utility_faithful:
    ['high', 'none', 'none', 'verbatim', 'forbidden', 'optional', 'forbidden'],
});

for (const [profileName, expected] of Object.entries(expectedDefaults)) {
  const policy = resolveEditPolicy(request({ profile: profileName }));
  const rules = policy.rules;
  assert.deepEqual([
    rules.cuts.density,
    rules.sfx.density,
    rules.transitions.density,
    rules.dialogue.priority,
    rules.music.usage,
    rules.captions.usage,
    rules.visualizations.usage,
  ], expected, profileName);
  assert.deepEqual(validateEditPolicy(policy), policy);
  assert.equal(policy.schema_version, EDIT_POLICY_SCHEMA_VERSION);
  assert.equal(policy.rules.dialogue.preserve_meaning, true);
  assert.equal(policy.rules.captions.safe_area_required, true);
  assert.equal(policy.rules.visualizations.evidence_required, true);
  assert.ok(policy.required_capabilities.length > 0);
  assert.ok(policy.forbidden_actions.length > 4);
  assert.ok(policy.qa_checks.length > 7);
}

// Duration boundaries and all profile/band/platform combinations.
const durationCases = new Map([
  [1, 'micro'],
  [15_000, 'micro'],
  [15_001, 'short'],
  [60_000, 'short'],
  [60_001, 'medium'],
  [300_000, 'medium'],
  [300_001, 'long'],
  [1_800_000, 'long'],
  [1_800_001, 'extended'],
  [MAX_DURATION_MS, 'extended'],
]);
for (const [milliseconds, expected] of durationCases) {
  assert.equal(durationBand(milliseconds), expected);
}
for (const invalid of [0, -1, MAX_DURATION_MS + 1, 1.5, '1000', true, null]) {
  assert.throws(() => durationBand(invalid), EditPolicyError);
}

const durationRepresentatives = [1, 15_001, 60_001, 300_001, 1_800_001];
const matrixRequests = [];
for (const profileName of PROFILE_NAMES) {
  for (const durationMs of durationRepresentatives) {
    for (const platform of PLATFORMS) {
      const raw = request({ profile: profileName, durationMs, platform });
      const policy = resolveEditPolicy(raw);
      assert.deepEqual(validateEditPolicy(policy), policy);
      assert.ok(ASPECTS.includes(policy.delivery.aspect));
      matrixRequests.push(raw);
    }
  }
}
assert.equal(matrixRequests.length, 13 * 5 * 11);

// Fixed Python vectors and byte-for-byte cross-language canonical JSON.
const vectors = vectorRequests();
const vectorNames = Object.keys(vectors);
const pythonVectors = pythonResolve(vectorNames.map((name) => vectors[name]), {
  canonical: true,
});
vectorNames.forEach((name, index) => {
  const policy = resolveEditPolicy(vectors[name]);
  const canonical = canonicalEditPolicyJson(policy);
  const digest = editPolicySha256(policy);
  assert.equal(canonical.length, FIXED_VECTORS[name].canonicalLength, name);
  assert.equal(digest, FIXED_VECTORS[name].sha256, name);
  assert.equal(pythonVectors[index].sha256, FIXED_VECTORS[name].sha256, name);
  assert.equal(pythonVectors[index].canonical, canonical, name);
  assert.equal(
    crypto.createHash('sha256').update(canonical, 'utf8').digest('hex'),
    digest,
  );
});

// The entire 715-case profile/band/platform matrix must hash identically in
// Python and JavaScript, not only the four readable fixed vectors.
const pythonMatrix = pythonResolve(matrixRequests);
matrixRequests.forEach((raw, index) => {
  assert.equal(
    editPolicySha256(resolveEditPolicy(raw)),
    pythonMatrix[index].sha256,
    `${raw.profile}/${raw.duration_ms}/${raw.delivery.platform}`,
  );
});

// Explicit precedence: hard > explicit > platform > profile > duration >
// consented preferences.
{
  const raw = request({ platform: 'tiktok' });
  raw.explicit_intent.caption_rule = 'forbidden';
  const policy = resolveEditPolicy(raw);
  assert.equal(policy.rules.captions.usage, 'forbidden');
  assert.equal(policy.resolution_sources.caption_rule, 'explicit_intent');
}
{
  const policy = resolveEditPolicy(request({
    profile: 'music_performance', platform: 'tiktok',
  }));
  assert.equal(policy.rules.captions.usage, 'required');
  assert.equal(policy.resolution_sources.caption_rule, 'platform');
}
{
  const policy = resolveEditPolicy(request({
    profile: 'documentary_narrative', durationMs: 5_000,
  }));
  assert.equal(policy.rules.cuts.density, 'low');
  assert.equal(policy.resolution_sources.cut_density, 'profile');
}
{
  const raw = request({ profile: 'podcast_interview', durationMs: 2_000_000 });
  raw.consented_preferences.consented = true;
  raw.consented_preferences.values.cut_density = 'very_high';
  const policy = resolveEditPolicy(raw);
  assert.equal(policy.rules.cuts.density, 'very_low');
  assert.equal(policy.resolution_sources.cut_density, 'duration');
}
{
  const raw = request({ profile: 'vlog_travel' });
  raw.consented_preferences.consented = true;
  raw.consented_preferences.values.transition_density = 'dense';
  const policy = resolveEditPolicy(raw);
  assert.equal(policy.rules.transitions.density, 'dense');
  assert.equal(
    policy.resolution_sources.transition_density,
    'consented_preferences',
  );
}
{
  const raw = request({ profile: 'vlog_travel' });
  raw.consented_preferences.values.transition_density = 'dense';
  assert.throws(() => resolveEditPolicy(raw), /unconsented/);
}

for (const [profileName, field, value] of [
  ['utility_faithful', 'sfx_density', 'dense'],
  ['utility_faithful', 'music_rule', 'primary'],
  ['music_performance', 'music_rule', 'forbidden'],
  ['course_tutorial_screencast', 'visualization_rule', 'allowed'],
]) {
  const raw = request({ profile: profileName });
  raw.explicit_intent[field] = value;
  assert.throws(() => resolveEditPolicy(raw), /hard invariant/);
}
for (const profileName of ['podcast_interview', 'documentary_narrative']) {
  const raw = request({ profile: profileName });
  raw.explicit_intent.sfx_density = 'sparse';
  assert.throws(() => resolveEditPolicy(raw), /forbids added SFX/);
}

// Capability gates are exact and derived from the resolved rules.
{
  const raw = request({ profile: 'sports_highlights' });
  const policy = resolveEditPolicy(raw);
  for (const capability of policy.required_capabilities) {
    const broken = clone(raw);
    broken.available_capabilities = broken.available_capabilities.filter(
      (candidate) => candidate !== capability,
    );
    assert.throws(() => resolveEditPolicy(broken), /capability gate failed/);
  }
}
{
  const raw = request();
  raw.available_capabilities.push('telepathy');
  assert.throws(() => resolveEditPolicy(raw), EditPolicyError);
}
{
  const raw = request();
  raw.available_capabilities.push(raw.available_capabilities[0]);
  assert.throws(() => resolveEditPolicy(raw), /duplicates/);
}
{
  const raw = request();
  raw.explicit_intent.sfx_density = 'dense';
  raw.explicit_intent.transition_density = 'dense';
  raw.explicit_intent.visualization_rule = 'required';
  const policy = resolveEditPolicy(raw);
  for (const capability of [
    'project_generated_sfx', 'audio_crossfades', 'cross_dissolves',
    'motion_quality_analysis', 'graphic_rendering',
  ]) {
    assert.ok(policy.required_capabilities.includes(capability));
  }
  assert.ok(policy.qa_checks.includes('sfx_motivation_and_masking_verified'));
  assert.ok(policy.qa_checks.includes(
    'sfx_generation_and_rights_receipt_verified'));
  assert.ok(!policy.required_capabilities.includes('licensed_sfx'));
  assert.ok(policy.qa_checks.includes('transition_motivation_verified'));
  assert.ok(policy.qa_checks.includes('visualization_data_provenance_verified'));
}
{
  const full = request({ profile: 'utility_faithful' });
  const fullPolicy = resolveEditPolicy(full);
  const minimal = clone(full);
  minimal.available_capabilities = [...fullPolicy.required_capabilities];
  const minimalPolicy = resolveEditPolicy(minimal);
  assert.deepEqual(fullPolicy, minimalPolicy);
  assert.equal(editPolicySha256(fullPolicy), editPolicySha256(minimalPolicy));
}

// Closed-shape, type-confusion, sparse-array, and mutation rejection.
const requestMutators = [
  (raw) => { raw.profile = 'world_class_everything'; },
  (raw) => { raw.schema_version = 'autoeditor-edit-policy-request/v2'; },
  (raw) => { raw.surprise = true; },
  (raw) => { raw.delivery.fps = 60; },
  (raw) => { raw.explicit_intent.glitch_pack = 'maximum'; },
  (raw) => { delete raw.explicit_intent.music_rule; },
  (raw) => { raw.explicit_intent.caption_rule = true; },
  (raw) => { raw.consented_preferences.consented = 1; },
  (raw) => { raw.available_capabilities = 'hard_cuts'; },
];
for (const mutate of requestMutators) {
  const raw = request();
  mutate(raw);
  assert.throws(() => resolveEditPolicy(raw), EditPolicyError);
}
{
  const raw = request();
  const sparse = [...raw.available_capabilities];
  delete sparse[2];
  raw.available_capabilities = sparse;
  assert.throws(() => resolveEditPolicy(raw), EditPolicyError);
}
{
  const raw = request();
  Object.defineProperty(raw, Symbol('hidden'), { value: true, enumerable: true });
  assert.throws(() => resolveEditPolicy(raw), EditPolicyError);
}

const original = resolveEditPolicy(request());
const policyMutators = [
  (policy) => { policy.debug = true; },
  (policy) => { delete policy.rules.music.usage; },
  (policy) => { policy.duration.band = 'extended'; },
  (policy) => { policy.rules.dialogue.preserve_meaning = false; },
  (policy) => { policy.rules.captions.max_lines = 3; },
  (policy) => { policy.rules.visualizations.evidence_required = false; },
  (policy) => { policy.required_capabilities.pop(); },
  (policy) => { policy.forbidden_actions.reverse(); },
  (policy) => { policy.qa_checks.push('looks_good_to_model'); },
  (policy) => { policy.rules.cuts.motivation = 'retention_motivated'; },
];
for (const mutate of policyMutators) {
  const policy = clone(original);
  mutate(policy);
  assert.throws(() => validateEditPolicy(policy), EditPolicyError);
}

// Returned policies are detached and mapping/capability order is irrelevant.
{
  const validated = validateEditPolicy(original);
  validated.rules.cuts.density = 'very_low';
  assert.equal(original.rules.cuts.density, 'high');
}
{
  const first = request({ profile: 'real_estate', platform: 'instagram_feed' });
  const second = clone(first);
  second.available_capabilities.reverse();
  const reversed = Object.fromEntries(Object.entries(second).reverse());
  const policyA = resolveEditPolicy(first);
  const policyB = resolveEditPolicy(reversed);
  assert.deepEqual(policyA, policyB);
  assert.equal(editPolicySha256(policyA), editPolicySha256(policyB));
}

console.log('edit policy JavaScript/Python mirror tests passed');
