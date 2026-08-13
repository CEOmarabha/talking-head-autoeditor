'use strict';

const {
  PROJECT_INTENT_SCHEMA_VERSION,
  PROFILE_NAMES: INTENT_PROFILE_NAMES,
  validateProjectIntent: validateProjectIntentContract,
} = require('./project-intent');
const {
  EDIT_POLICY_REQUEST_SCHEMA_VERSION,
  MAX_DURATION_MS,
  CAPABILITIES,
  PROFILE_NAMES: POLICY_PROFILE_NAMES,
  EditPolicyError,
  durationBand,
  resolveEditPolicy,
} = require('./edit-policy');

const CAPABILITY_MANIFEST_SCHEMA_VERSION =
  'autoeditor-trusted-capability-manifest/v1';
const CAPABILITY_MANIFEST_SOURCE = 'autoeditor-local-runtime-probe/v1';

// This is an implementation inventory, not an availability default. A local
// preflight may copy a member into a trusted manifest only after its concrete
// probe succeeds for the current job. The bridge never reads this set to fill
// missing claims and never reads API keys, model output, user text, or env.
const CURRENT_RUNTIME_CAPABILITIES = Object.freeze([
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

const FEATURE_NAMES = Object.freeze([
  'captions', 'graphics', 'music', 'sfx', 'transitions',
]);
const POLICY_FIELDS = Object.freeze([
  'cut_density',
  'sfx_density',
  'transition_density',
  'dialogue_rule',
  'music_rule',
  'caption_rule',
  'visualization_rule',
]);
const ADDED_SFX_USAGES = new Set([
  'event_accent_only', 'interface_feedback_only', 'motivated_only',
]);
const TYPED_TRANSITION_USAGES = new Set([
  'beat_or_phrase_motivated',
  'continuity_motivated',
  'location_motivated',
  'motivated_only',
]);
const MANIFEST_KEYS = Object.freeze([
  'available_capabilities', 'probe_receipt_sha256', 'schema_version', 'source',
]);
const SHA256 = /^[0-9a-f]{64}$/;
const CAPABILITY_SET = new Set(CAPABILITIES);

function sameMembers(left, right) {
  return left.length === right.length &&
    [...left].sort().every((value, index) => value === [...right].sort()[index]);
}

if (!sameMembers(INTENT_PROFILE_NAMES, POLICY_PROFILE_NAMES)) {
  throw new Error('project-intent profile surface drifted from edit-policy/v1');
}
if (!CURRENT_RUNTIME_CAPABILITIES.every((name) => CAPABILITY_SET.has(name)) ||
    CURRENT_RUNTIME_CAPABILITIES.length >= CAPABILITIES.length) {
  throw new Error('current runtime capability surface drifted from edit-policy/v1');
}

class ProjectIntentPolicyBridgeError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ProjectIntentPolicyBridgeError';
  }
}

function fail(message) {
  throw new ProjectIntentPolicyBridgeError(message);
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isDenseArray(value) {
  if (!Array.isArray(value)) return false;
  for (let index = 0; index < value.length; index += 1) {
    if (!Object.prototype.hasOwnProperty.call(value, index)) return false;
  }
  return Reflect.ownKeys(value).every((key) => (
    key === 'length' ||
    (typeof key === 'string' && /^(0|[1-9][0-9]*)$/.test(key) &&
      Number(key) < value.length)
  ));
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

function validateProjectIntent(value) {
  try {
    return validateProjectIntentContract(value);
  } catch (error) {
    throw new ProjectIntentPolicyBridgeError(error?.message || String(error));
  }
}

function validateCapabilityManifest(value) {
  const raw = exactKeys(value, MANIFEST_KEYS, 'capability manifest');
  if (raw.schema_version !== CAPABILITY_MANIFEST_SCHEMA_VERSION) {
    fail('capability manifest schema_version is unsupported');
  }
  if (raw.source !== CAPABILITY_MANIFEST_SOURCE) {
    fail('capability manifest source is untrusted');
  }
  if (typeof raw.probe_receipt_sha256 !== 'string' ||
      !SHA256.test(raw.probe_receipt_sha256)) {
    fail('capability manifest probe_receipt_sha256 must be lowercase SHA-256');
  }
  if (!isDenseArray(raw.available_capabilities)) {
    fail('capability manifest available_capabilities must be a sorted list');
  }
  if (raw.available_capabilities.some((item) => typeof item !== 'string')) {
    fail('capability manifest available_capabilities must contain strings');
  }
  const unknown = [...new Set(raw.available_capabilities)]
    .filter((item) => !CAPABILITY_SET.has(item)).sort(asciiCompare);
  if (unknown.length) {
    fail('capability manifest available_capabilities has unsupported values: ' +
      unknown.join(', '));
  }
  const sortedUnique = [...new Set(raw.available_capabilities)].sort(asciiCompare);
  if (sortedUnique.length !== raw.available_capabilities.length ||
      sortedUnique.some((item, index) => item !== raw.available_capabilities[index])) {
    fail('capability manifest available_capabilities must be sorted and unique');
  }
  return {
    schema_version: CAPABILITY_MANIFEST_SCHEMA_VERSION,
    source: CAPABILITY_MANIFEST_SOURCE,
    probe_receipt_sha256: raw.probe_receipt_sha256,
    available_capabilities: [...raw.available_capabilities],
  };
}

function autoPolicyValues() {
  return Object.fromEntries(POLICY_FIELDS.map((field) => [field, 'auto']));
}

function mapPreferences(project) {
  const preferences = project.preferences;
  const captions = preferences.captions.preference;
  const graphics = preferences.graphics.preference;
  const music = preferences.music.preference;
  const sfx = preferences.sfx.preference;
  const transitions = preferences.transitions.preference;

  if (captions === 'selective') {
    fail('edit-policy/v1 cannot represent selective captions without weakening intent');
  }
  if (!['auto', 'none'].includes(graphics)) {
    fail(`edit-policy/v1 cannot represent graphics preference ${graphics} ` +
      'without losing its typed mode');
  }

  const values = autoPolicyValues();
  values.caption_rule = {
    auto: 'auto', none: 'forbidden', verbatim: 'verbatim_required',
  }[captions];
  values.visualization_rule = { auto: 'auto', none: 'forbidden' }[graphics];
  values.music_rule = {
    auto: 'auto',
    none: 'forbidden',
    primary: 'primary',
    source_primary: 'source_primary',
    supporting: 'supporting',
  }[music];
  values.sfx_density = sfx === 'none' ? 'none' : 'auto';
  values.transition_density = ['none', 'hard_cut_only'].includes(transitions)
    ? 'none' : 'auto';
  return values;
}

function buildRequest(project, manifest) {
  const minimum = project.target_duration.min_ms;
  const maximum = project.target_duration.max_ms;
  let minimumBand;
  let maximumBand;
  try {
    minimumBand = durationBand(minimum);
    maximumBand = durationBand(maximum);
  } catch (error) {
    throw new ProjectIntentPolicyBridgeError(error?.message || String(error));
  }
  if (minimumBand !== maximumBand) {
    fail('target_duration crosses edit-policy duration bands; ' +
      'split the range or choose bounds within one band');
  }
  return {
    schema_version: EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    profile: project.profile,
    duration_ms: maximum,
    delivery: { ...project.delivery },
    explicit_intent: mapPreferences(project),
    consented_preferences: {
      consented: false,
      values: autoPolicyValues(),
    },
    available_capabilities: [...manifest.available_capabilities],
  };
}

function buildEditPolicyRequest(projectIntent, capabilityManifest) {
  const project = validateProjectIntent(projectIntent);
  const manifest = validateCapabilityManifest(capabilityManifest);
  return buildRequest(project, manifest);
}

function verifyResolvedIntent(project, policy) {
  const preferences = project.preferences;
  const rules = policy.rules;

  const expectedCaption = {
    none: 'forbidden', verbatim: 'verbatim_required',
  }[preferences.captions.preference];
  if (expectedCaption !== undefined && rules.captions.usage !== expectedCaption) {
    fail('resolved edit policy did not preserve the caption preference');
  }
  if (preferences.graphics.preference === 'none' &&
      rules.visualizations.usage !== 'forbidden') {
    fail('resolved edit policy did not preserve the graphics preference');
  }
  const expectedMusic = {
    none: 'forbidden',
    primary: 'primary',
    source_primary: 'source_primary',
    supporting: 'supporting',
  }[preferences.music.preference];
  if (expectedMusic !== undefined && rules.music.usage !== expectedMusic) {
    fail('resolved edit policy did not preserve the music preference');
  }

  const sfx = preferences.sfx.preference;
  if (sfx === 'none' && rules.sfx.density !== 'none') {
    fail('resolved edit policy did not preserve the disabled SFX preference');
  }
  if (ADDED_SFX_USAGES.has(sfx)) {
    if (rules.sfx.usage !== sfx) {
      fail(`edit policy profile ${project.profile} does not support requested ` +
        `SFX usage ${sfx}`);
    }
    if (rules.sfx.density === 'none') {
      fail('resolved edit policy cannot enable the requested SFX usage');
    }
  }

  const transitions = preferences.transitions.preference;
  if (['none', 'hard_cut_only'].includes(transitions)) {
    if (rules.transitions.density !== 'none') {
      fail('resolved edit policy did not preserve the hard-cut preference');
    }
  } else if (TYPED_TRANSITION_USAGES.has(transitions)) {
    if (rules.transitions.usage !== transitions) {
      fail(`edit policy profile ${project.profile} does not support requested ` +
        `transition usage ${transitions}`);
    }
    if (rules.transitions.density === 'none') {
      fail('resolved edit policy cannot enable the requested transition usage');
    }
  }
}

function resolveProjectIntentPolicy(projectIntent, capabilityManifest) {
  const project = validateProjectIntent(projectIntent);
  const manifest = validateCapabilityManifest(capabilityManifest);
  const request = buildRequest(project, manifest);
  let policy;
  try {
    policy = resolveEditPolicy(request);
  } catch (error) {
    if (error instanceof EditPolicyError) {
      throw new ProjectIntentPolicyBridgeError(error.message);
    }
    throw error;
  }
  verifyResolvedIntent(project, policy);
  return policy;
}

module.exports = Object.freeze({
  PROJECT_INTENT_SCHEMA_VERSION,
  CAPABILITY_MANIFEST_SCHEMA_VERSION,
  CAPABILITY_MANIFEST_SOURCE,
  CURRENT_RUNTIME_CAPABILITIES,
  FEATURE_NAMES,
  ProjectIntentPolicyBridgeError,
  validateProjectIntent,
  validateCapabilityManifest,
  buildEditPolicyRequest,
  resolveProjectIntentPolicy,
});
