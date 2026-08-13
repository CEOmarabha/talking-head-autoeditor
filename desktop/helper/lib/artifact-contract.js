'use strict';

// Shared reader for the engine->desktop artifact trust boundary. Production
// final QA and the fixed runtime capability probe both call these exact
// functions; a probe cannot pass by validating a weaker look-alike object.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {
  projectIntentSha256,
  validateProjectIntent,
} = require('./project-intent');
const {
  canonicalEditPolicyJson,
  durationBand,
  editPolicySha256,
  validateEditPolicy,
} = require('./edit-policy');
const {
  resolveProjectIntentPolicy,
  validateCapabilityManifest,
} = require('./project-intent-policy-bridge');
const {
  sequencePlanSha256,
  sourceManifestSha256,
} = require('./sequence-plan');
const {
  transitionPlanSha256,
  transitionSequenceManifestSha256,
} = require('./transition-plan');
const {
  compileMusicPlan,
  musicAssetManifestSha256,
  musicCompileReceiptSha256,
  musicPlanSha256,
  validateMusicAssetManifest,
  validateMusicPlan,
} = require('./music-plan');
const {
  compileSfxPlan,
  sfxCompileReceiptSha256,
  sfxCueManifestSha256,
  sfxPlanSha256,
  validateSfxCueManifest,
  validateSfxPlan,
} = require('./sfx-plan');

const ENGINE_QA_SCHEMA = 'autoeditor-engine-qa/v2';
const ENGINE_ARTIFACT_CONTRACT_SCHEMA =
  'autoeditor-engine-artifact-contract/v2';
const ENGINE_ARTIFACT_CONTRACT_DETERMINISTIC_SCHEMA =
  'autoeditor-engine-artifact-contract/v3';
const ENGINE_ARTIFACT_CONTRACT_INTENT_SCHEMA =
  'autoeditor-engine-artifact-contract/v4';
const ENGINE_ARTIFACT_CONTRACT_INTENT_DETERMINISTIC_SCHEMA =
  'autoeditor-engine-artifact-contract/v5';
const PRODUCTION_DETERMINISTIC_VISUAL_QA_SCHEMA =
  'autoeditor-production-deterministic-visual-qa/v1';
const PRODUCTION_VISUAL_INTENT_SCHEMA =
  'autoeditor-production-visual-timeline-intent/v1';
const RGB24_DECODER_RECEIPT_SCHEMA =
  'autoeditor-ffmpeg-rgb24-decoder-receipt/v1';
const DECODED_TIMELINE_RECEIPT_SCHEMA =
  'autoeditor-decoded-frame-timeline-receipt/v1';
const DETERMINISTIC_VISUAL_RESULT_SCHEMA =
  'autoeditor-visual-quality-deterministic-result/v1';
const DETERMINISTIC_VISUAL_RECEIPT_SCHEMA =
  'autoeditor-visual-quality-deterministic-receipt/v1';
const DETERMINISTIC_VISUAL_REQUEST_SCHEMA =
  'autoeditor-visual-quality-deterministic-request/v1';
const DETERMINISTIC_VISUAL_ALGORITHM =
  'autoeditor-rgb24-technical-evidence/v1';
const PROJECT_INTENT_RENDER_RECEIPT_SCHEMA =
  'autoeditor-project-intent-render-receipt/v2';
const PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA =
  'autoeditor-project-intent-engine-envelope/v2';
const DEFAULT_MAX_SIDECAR_BYTES = 2 * 1024 * 1024;
const MAX_DETERMINISTIC_VISUAL_SIDECAR_BYTES = 4 * 1024 * 1024;
const SHA256 = /^[0-9a-f]{64}$/;
const LEGACY_CONTRACT_KEYS = Object.freeze([
  'schema', 'mode', 'delivery', 'edl', 'captions', 'caption_render',
  'edit_boundaries', 'audio_mix', 'sequence',
]);
const INTENT_CONTRACT_KEYS = Object.freeze([
  ...LEGACY_CONTRACT_KEYS, 'project_intent', 'music_production',
  'sfx_production',
]);
const DETERMINISTIC_CONTRACT_KEYS = Object.freeze([
  ...LEGACY_CONTRACT_KEYS, 'deterministic_visual_qa',
]);
const INTENT_DETERMINISTIC_CONTRACT_KEYS = Object.freeze([
  ...INTENT_CONTRACT_KEYS, 'deterministic_visual_qa',
]);
const PROJECT_INTENT_RENDER_RECEIPT_KEYS = Object.freeze([
  'schema_version', 'authorization_id', 'approved_proposal_sha256',
  'approved_transition_carrier', 'engine_envelope_sha256',
  'project_intent', 'project_intent_sha256', 'edit_policy',
  'edit_policy_sha256', 'capability_manifest',
  'capability_manifest_sha256', 'capability_probe_receipt_sha256',
  'actual_render', 'checks', 'pass',
]);
const PROJECT_INTENT_CHECK_NAMES = Object.freeze([
  'canonical_authority', 'target_duration', 'delivery', 'captions',
  'graphics', 'music', 'sfx', 'transitions',
]);
const PROJECT_INTENT_ENGINE_CHECK_KEYS = Object.freeze([
  'ok', 'authorization_id', 'approved_proposal_sha256',
  'approved_transition_carrier', 'engine_envelope_sha256',
  'project_intent_sha256', 'edit_policy_sha256',
  'capability_manifest_sha256', 'capability_probe_receipt_sha256',
  'render_receipt_sha256', 'receipt_file_sha256', 'note',
]);
const SFX_PRODUCTION_RECEIPT_KEYS = Object.freeze([
  'schema_version', 'mode', 'authorization_id',
  'engine_envelope_sha256', 'project_intent_sha256',
  'parent_edit_policy_sha256', 'execution_edit_policy_sha256',
  'target_duration', 'actual_duration_ms', 'duration_band',
  'requested_preference', 'policy', 'cue_count',
  'output_timeline_sha256', 'program_input', 'output',
  'cue_manifest_sha256', 'sfx_plan_sha256',
  'sfx_compile_receipt_sha256', 'sfx_render_receipt_sha256', 'sidecars',
]);
const SFX_PRODUCTION_ENGINE_CHECK_KEYS = Object.freeze([
  'ok', 'authorization_id', 'engine_envelope_sha256',
  'project_intent_sha256', 'parent_edit_policy_sha256', 'mode', 'cue_count',
  'policy_usage', 'policy_bound', 'production_receipt_sha256',
  'receipt_file_sha256', 'master_output_sha256', 'program_input_sha256',
  'music_output_sha256', 'program_input_matches_music_output', 'note',
]);
const MUSIC_PRODUCTION_RECEIPT_KEYS = Object.freeze([
  'schema_version', 'mode', 'authorization_id', 'capability_used',
  'engine_envelope_sha256', 'project_intent_sha256',
  'parent_edit_policy_sha256', 'execution_edit_policy_sha256',
  'target_duration', 'actual_duration_ms', 'duration_band',
  'requested_preference', 'policy', 'region_count', 'added_coverage_ms',
  'output_timeline_sha256', 'program_input', 'output', 'rights', 'audio_qa',
  'music_asset_manifest_sha256', 'music_plan_sha256',
  'music_compile_receipt_sha256', 'music_render_receipt_sha256', 'sidecars',
]);
const MUSIC_PRODUCTION_ENGINE_CHECK_KEYS = Object.freeze([
  'ok', 'authorization_id', 'engine_envelope_sha256',
  'project_intent_sha256', 'parent_edit_policy_sha256',
  'execution_edit_policy_sha256', 'mode', 'region_count', 'policy_usage',
  'policy_bound', 'rights_verified', 'dialogue_masking_verified',
  'loudness_verified', 'production_receipt_sha256', 'receipt_file_sha256',
  'program_input_sha256', 'music_output_sha256', 'measured_audio', 'note',
]);
const NON_BLOCKING_ENGINE_CHECKS = Object.freeze(new Set([
  'brand_font_worksans',
]));

class ArtifactContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ArtifactContractError';
  }
}

function fail(message) {
  throw new ArtifactContractError(message);
}

function inside(root, candidate) {
  const relative = path.relative(root, candidate);
  return !!relative && relative !== '..' &&
    !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function exactObject(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    fail(`${label} is invalid`);
  }
  const actual = Reflect.ownKeys(value);
  if (actual.some((key) => typeof key !== 'string') ||
      actual.length !== keys.length ||
      keys.some((key) => !actual.includes(key))) {
    fail(`${label} is invalid`);
  }
  return value;
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

function sha256Text(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function sameCanonical(left, right) {
  return stableJson(left) === stableJson(right);
}

function approvedTransitionCarrier(proposal) {
  const hasSequencePlan = Object.prototype.hasOwnProperty.call(
    proposal, 'sequencePlan');
  const hasSequenceManifest = Object.prototype.hasOwnProperty.call(
    proposal, 'sequenceSourceManifest');
  const hasTransitionPlan = Object.prototype.hasOwnProperty.call(
    proposal, 'transitionPlan');
  const hasTransitionManifest = Object.prototype.hasOwnProperty.call(
    proposal, 'transitionSequenceManifest');
  if (!hasTransitionPlan && !hasTransitionManifest) return null;
  if (!hasSequencePlan || !hasSequenceManifest || !hasTransitionPlan ||
      !hasTransitionManifest) {
    fail('approved transition carrier is incomplete');
  }
  return {
    sequence_plan_sha256: sequencePlanSha256(proposal.sequencePlan),
    source_manifest_sha256:
      sourceManifestSha256(proposal.sequenceSourceManifest),
    transition_plan_sha256: transitionPlanSha256(proposal.transitionPlan),
    transition_sequence_manifest_sha256:
      transitionSequenceManifestSha256(proposal.transitionSequenceManifest),
  };
}

function nonnegativeInteger(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) fail(`${label} is invalid`);
  return value;
}

function validateActualRender(value) {
  const raw = exactObject(
    value, ['duration_ms', 'delivery', 'preferences'],
    'ProjectIntent actual render');
  const delivery = exactObject(raw.delivery, [
    'platform', 'configured_aspect', 'artifact_aspect', 'width', 'height',
  ], 'ProjectIntent actual delivery');
  if (![delivery.platform, delivery.configured_aspect, delivery.artifact_aspect]
    .every((item) => typeof item === 'string' && item && /^[\x20-\x7e]+$/.test(item)) ||
      nonnegativeInteger(delivery.width, 'ProjectIntent artifact width') < 1 ||
      nonnegativeInteger(delivery.height, 'ProjectIntent artifact height') < 1) {
    fail('ProjectIntent actual delivery is invalid');
  }
  const preferences = exactObject(raw.preferences, [
    'captions', 'graphics', 'music', 'sfx', 'transitions',
  ], 'ProjectIntent actual preferences');
  const captions = exactObject(preferences.captions,
    ['delivery', 'event_count'], 'ProjectIntent caption facts');
  const graphics = exactObject(preferences.graphics,
    ['event_count'], 'ProjectIntent graphics facts');
  const music = exactObject(preferences.music,
    ['added_music_present', 'source_music_preserved'], 'ProjectIntent music facts');
  const sfx = exactObject(preferences.sfx,
    ['cue_count', 'policy_usage', 'policy_bound'], 'ProjectIntent SFX facts');
  const transitions = exactObject(preferences.transitions, [
    'event_count', 'non_hard_event_count', 'policy_usage', 'policy_bound',
  ], 'ProjectIntent transition facts');
  if (!['none', 'sidecar', 'burned'].includes(captions.delivery) ||
      typeof music.added_music_present !== 'boolean' ||
      typeof music.source_music_preserved !== 'boolean' ||
      typeof sfx.policy_usage !== 'string' ||
      typeof sfx.policy_bound !== 'boolean' ||
      typeof transitions.policy_usage !== 'string' ||
      typeof transitions.policy_bound !== 'boolean') {
    fail('ProjectIntent preference facts are invalid');
  }
  for (const [label, count] of [
    ['caption event count', captions.event_count],
    ['graphics event count', graphics.event_count],
    ['SFX cue count', sfx.cue_count],
    ['transition event count', transitions.event_count],
    ['non-hard transition count', transitions.non_hard_event_count],
  ]) nonnegativeInteger(count, `ProjectIntent ${label}`);
  if (transitions.non_hard_event_count > transitions.event_count) {
    fail('ProjectIntent transition facts are inconsistent');
  }
  nonnegativeInteger(raw.duration_ms, 'ProjectIntent duration');
  return raw;
}

function artifactAspectMatches(aspect, width, height) {
  const ratios = {
    '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1, '4:5': 4 / 5, '21:9': 21 / 9,
  };
  return Object.prototype.hasOwnProperty.call(ratios, aspect) &&
    Math.abs(width / height - ratios[aspect]) <= 0.01;
}

function derivedProjectIntentChecks(project, policy, actual) {
  const preferences = project.preferences;
  const facts = actual.preferences;
  const captionPreference = preferences.captions.preference;
  const captionIntent = captionPreference === 'auto' ||
    (captionPreference === 'none' && facts.captions.delivery === 'none' &&
      facts.captions.event_count === 0) ||
    (captionPreference === 'verbatim' &&
      ['sidecar', 'burned'].includes(facts.captions.delivery) &&
      facts.captions.event_count > 0);
  const captionRule = policy.rules.captions.usage;
  const captionPolicy = captionRule === 'optional' ||
    (captionRule === 'forbidden' && facts.captions.delivery === 'none' &&
      facts.captions.event_count === 0) ||
    (['required', 'verbatim_required'].includes(captionRule) &&
      ['sidecar', 'burned'].includes(facts.captions.delivery) &&
      facts.captions.event_count > 0);
  const captions = captionIntent && captionPolicy;
  const graphicIntent = preferences.graphics.preference === 'auto' ||
    (preferences.graphics.preference === 'none' &&
      facts.graphics.event_count === 0);
  const visualizationRule = policy.rules.visualizations.usage;
  const graphicPolicy = ['allowed', 'recommended'].includes(visualizationRule) ||
    (visualizationRule === 'forbidden' && facts.graphics.event_count === 0) ||
    (visualizationRule === 'required' && facts.graphics.event_count > 0);
  const graphics = graphicIntent && graphicPolicy;
  const musicPreference = preferences.music.preference;
  const musicIntent = musicPreference === 'auto' ||
    (musicPreference === 'none' && !facts.music.added_music_present) ||
    (['primary', 'supporting'].includes(musicPreference) &&
      facts.music.added_music_present) ||
    (musicPreference === 'source_primary' &&
      facts.music.source_music_preserved && !facts.music.added_music_present);
  const musicRule = policy.rules.music.usage;
  const musicPolicy = musicRule === 'optional' ||
    (musicRule === 'forbidden' && !facts.music.added_music_present) ||
    (['primary', 'supporting'].includes(musicRule) &&
      facts.music.added_music_present) ||
    (musicRule === 'source_primary' && facts.music.source_music_preserved &&
      !facts.music.added_music_present);
  const music = musicIntent && musicPolicy;
  const sfxPreference = preferences.sfx.preference;
  const sfxIntent = sfxPreference === 'auto' ||
    (sfxPreference === 'none' && facts.sfx.cue_count === 0) ||
    (!['auto', 'none'].includes(sfxPreference) && facts.sfx.cue_count > 0 &&
      facts.sfx.policy_bound && facts.sfx.policy_usage === sfxPreference);
  const sfxRule = policy.rules.sfx;
  const sfxPolicy = (sfxRule.density === 'none' && facts.sfx.cue_count === 0) ||
    (sfxRule.density !== 'none' && (facts.sfx.cue_count === 0 ||
      (facts.sfx.policy_bound && facts.sfx.policy_usage === sfxRule.usage)));
  const sfx = sfxIntent && sfxPolicy;
  const transitionPreference = preferences.transitions.preference;
  const transitionIntent = transitionPreference === 'auto' ||
    (['none', 'hard_cut_only'].includes(transitionPreference) &&
      facts.transitions.non_hard_event_count === 0) ||
    (!['auto', 'none', 'hard_cut_only'].includes(transitionPreference) &&
      facts.transitions.event_count > 0 &&
      facts.transitions.non_hard_event_count > 0 &&
      facts.transitions.policy_bound &&
      facts.transitions.policy_usage === transitionPreference);
  const transitionRule = policy.rules.transitions;
  const transitionPolicy = (transitionRule.density === 'none' &&
      facts.transitions.non_hard_event_count === 0) ||
    (transitionRule.density !== 'none' &&
      (facts.transitions.non_hard_event_count === 0 ||
       (facts.transitions.policy_bound &&
        facts.transitions.policy_usage === transitionRule.usage)));
  const transitions = transitionIntent && transitionPolicy;
  return {
    target_duration: actual.duration_ms >= project.target_duration.min_ms &&
      actual.duration_ms <= project.target_duration.max_ms,
    delivery: actual.delivery.platform === project.delivery.platform &&
      project.delivery.platform === policy.delivery.platform &&
      actual.delivery.configured_aspect === project.delivery.aspect &&
      project.delivery.aspect === policy.delivery.aspect &&
      actual.delivery.artifact_aspect === project.delivery.aspect &&
      artifactAspectMatches(project.delivery.aspect,
        actual.delivery.width, actual.delivery.height),
    captions, graphics, music, sfx, transitions,
  };
}

function validateMusicMedia(value, label, duration) {
  const media = exactObject(value, [
    'sha256', 'bytes', 'duration_ms', 'audio_present', 'sample_rate_hz',
    'channels',
  ], label);
  if (!SHA256.test(media.sha256) ||
      nonnegativeInteger(media.bytes, `${label} bytes`) < 1 ||
      media.duration_ms !== duration || typeof media.audio_present !== 'boolean') {
    fail(`${label} binding is invalid`);
  }
  if (media.audio_present) {
    if (nonnegativeInteger(media.sample_rate_hz, `${label} sample rate`) < 1 ||
        nonnegativeInteger(media.channels, `${label} channels`) < 1) {
      fail(`${label} audio facts are invalid`);
    }
  } else if (media.sample_rate_hz !== null || media.channels !== null) {
    fail(`${label} silent media claims audio facts`);
  }
  return media;
}

function validateMusicAudioQa(value) {
  if (value === null) return null;
  const qa = exactObject(value, [
    'integrated_loudness_millilufs', 'true_peak_millidbtp',
    'target_loudness_millilufs', 'true_peak_ceiling_millidbtp',
    'loudness_tolerance_millilufs', 'passed',
  ], 'typed music measured audio QA');
  const boundedInteger = (number, minimum, maximum, label) => {
    if (!Number.isSafeInteger(number) || number < minimum || number > maximum) {
      fail(`${label} is invalid`);
    }
    return number;
  };
  boundedInteger(qa.integrated_loudness_millilufs, -70000, 0,
    'typed music measured loudness');
  boundedInteger(qa.true_peak_millidbtp, -100000, 12000,
    'typed music measured true peak');
  boundedInteger(qa.target_loudness_millilufs, -40000, -5000,
    'typed music target loudness');
  boundedInteger(qa.true_peak_ceiling_millidbtp, -9000, -100,
    'typed music true-peak ceiling');
  if (!Number.isSafeInteger(qa.loudness_tolerance_millilufs) ||
      qa.loudness_tolerance_millilufs < 1 || typeof qa.passed !== 'boolean') {
    fail('typed music measured audio QA is invalid');
  }
  const expectedPass = Math.abs(
    qa.integrated_loudness_millilufs - qa.target_loudness_millilufs,
  ) <= qa.loudness_tolerance_millilufs &&
    qa.true_peak_millidbtp <= qa.true_peak_ceiling_millidbtp + 100;
  if (qa.passed !== expectedPass) {
    fail('typed music measured audio QA contradicts its values');
  }
  return qa;
}

function musicOutputTimelineSha256(program, duration) {
  return sha256Text(stableJson({
    schema_version: 'autoeditor-music-output-timeline/v1',
    program_sha256: program.sha256,
    program_bytes: program.bytes,
    duration_ms: duration,
    time_base: { numerator: 1, denominator: 1000 },
  }));
}

function regeneratedMusicBedWave(parameters) {
  const value = exactObject(parameters, [
    'sample_rate_hz', 'channels', 'sample_width_bytes', 'duration_ms',
    'tempo_millibpm', 'key', 'oscillator', 'frequencies_millihz',
    'peak_amplitude_millionths',
  ], 'typed music generation parameters');
  if (value.sample_rate_hz !== 48000 || value.channels !== 2 ||
      value.sample_width_bytes !== 2 ||
      !Number.isSafeInteger(value.duration_ms) || value.duration_ms < 1 ||
      value.tempo_millibpm !== 96000 || value.key !== 'C_major' ||
      value.oscillator !== 'sine_chord' ||
      !sameCanonical(value.frequencies_millihz,
        [130813, 164814, 195998, 261626]) ||
      value.peak_amplitude_millionths !== 240000) {
    fail('typed music generation parameters are invalid');
  }
  const frames = Math.trunc(value.duration_ms * 48000 / 1000);
  const data = Buffer.alloc(frames * 4);
  const frequencies = [130.813, 164.814, 195.998, 261.626];
  const attackFrames = Math.max(1, Math.min(
    Math.trunc(frames / 4), Math.trunc(48000 * 80 / 1000)));
  for (let index = 0; index < frames; index += 1) {
    const seconds = index / 48000;
    const attack = Math.min(1, index / attackFrames);
    const release = Math.min(1, (frames - 1 - index) / attackFrames);
    const envelope = Math.max(0, Math.min(attack, release));
    const pulse = 0.82 + 0.18 * Math.sin(2 * Math.PI * 1.6 * seconds);
    const chord = frequencies.reduce((total, frequency, note) =>
      total + Math.sin(2 * Math.PI * frequency * seconds + note * 0.37), 0) /
      frequencies.length;
    const sample = envelope * pulse * chord * 0.24;
    const scaled = Math.max(-0.72, Math.min(0.72, sample)) * 32767;
    // Python round() is ties-to-even, but this deterministic sine formula does
    // not encounter exact half-integers at the serialized 16-bit boundary.
    const rounded = Math.round(scaled);
    data.writeInt16LE(rounded, index * 4);
    data.writeInt16LE(rounded, index * 4 + 2);
  }
  const header = Buffer.alloc(44);
  header.write('RIFF', 0, 'ascii');
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVEfmt ', 8, 'ascii');
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(2, 22);
  header.writeUInt32LE(48000, 24);
  header.writeUInt32LE(48000 * 4, 28);
  header.writeUInt16LE(4, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36, 'ascii');
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

function validateMusicProductionArtifactBinding({
  receipt, outputDir, approvedAuthority, engineCheck,
  expectedEngineEnvelopeSha256,
}) {
  if (!receipt || !receipt.report || !SHA256.test(receipt.sha256)) {
    fail('typed music production receipt is missing');
  }
  const report = exactObject(
    receipt.report, MUSIC_PRODUCTION_RECEIPT_KEYS,
    'typed music production receipt');
  if (report.schema_version !== 'autoeditor-music-production-receipt/v1' ||
      !['rendered', 'no_music_requested', 'no_safe_gap'].includes(report.mode) ||
      !/^[0-9a-f]{32}$/.test(report.authorization_id)) {
    fail('typed music production receipt is invalid');
  }
  const authority = approvedAuthority;
  if (!authority || report.authorization_id !== authority.authorization_id ||
      report.project_intent_sha256 !== authority.project_intent_sha256 ||
      report.parent_edit_policy_sha256 !== authority.edit_policy_sha256 ||
      !SHA256.test(expectedEngineEnvelopeSha256) ||
      report.engine_envelope_sha256 !== expectedEngineEnvelopeSha256 ||
      !SHA256.test(report.execution_edit_policy_sha256) ||
      !SHA256.test(report.output_timeline_sha256)) {
    fail('typed music production receipt does not bind ProjectIntent authority');
  }
  const target = exactObject(report.target_duration,
    ['min_ms', 'max_ms'], 'typed music target duration');
  const policy = exactObject(report.policy,
    ['usage', 'duck_under_dialogue'], 'typed music policy');
  const project = validateProjectIntent(authority.project_intent);
  const parentPolicy = validateEditPolicy(authority.edit_policy);
  const duration = nonnegativeInteger(
    report.actual_duration_ms, 'typed music actual duration');
  const regionCount = nonnegativeInteger(
    report.region_count, 'typed music region count');
  const addedCoverageMs = nonnegativeInteger(
    report.added_coverage_ms, 'typed music coverage');
  if (duration < 1 || target.min_ms !== project.target_duration.min_ms ||
      target.max_ms !== project.target_duration.max_ms ||
      duration < target.min_ms || duration > target.max_ms ||
      report.duration_band !== durationBand(duration) ||
      report.requested_preference !== project.preferences.music.preference ||
      !sameCanonical(policy, parentPolicy.rules.music) ||
      typeof policy.usage !== 'string' ||
      typeof policy.duck_under_dialogue !== 'boolean' ||
      addedCoverageMs > duration ||
      (report.mode === 'rendered') !== (regionCount > 0 && addedCoverageMs > 0)) {
    fail('typed music production policy or duration is invalid');
  }
  const program = validateMusicMedia(
    report.program_input, 'typed music program input', duration);
  const output = validateMusicMedia(
    report.output, 'typed music output', duration);
  const rights = exactObject(report.rights,
    ['basis', 'generator', 'external_service_used'], 'typed music rights');
  const audioQa = validateMusicAudioQa(report.audio_qa);
  const rendered = report.mode === 'rendered';
  const receiptHashes = [
    'music_asset_manifest_sha256', 'music_plan_sha256',
    'music_compile_receipt_sha256', 'music_render_receipt_sha256',
  ];
  if (receiptHashes.some((name) => rendered
    ? !SHA256.test(report[name]) : report[name] !== null)) {
    fail('typed music production receipt chain is inconsistent');
  }
  if (rendered) {
    if (report.capability_used !== 'project_generated_music' ||
        !sameCanonical(rights, {
          basis: 'project_owned',
          generator: 'autoeditor-deterministic-musical-pcm/v1',
          external_service_used: false,
        }) || !audioQa || audioQa.passed !== true || !output.audio_present ||
        output.sample_rate_hz !== 48000 || output.channels !== 2) {
      fail('typed music production lacks truthful rights or measured QA');
    }
  } else {
    const expectedCapability = report.mode === 'no_music_requested'
      ? null : 'project_generated_music';
    if (report.capability_used !== expectedCapability || regionCount !== 0 ||
        addedCoverageMs !== 0 || audioQa !== null ||
        !sameCanonical(rights, {
          basis: null, generator: null, external_service_used: false,
        }) || !sameCanonical(program, output)) {
      fail('typed music no-op changed program bytes or claimed rights');
    }
  }
  if (report.output_timeline_sha256 !==
      musicOutputTimelineSha256(program, duration)) {
    fail('typed music output timeline is not bound to its exact program');
  }
  if (!Array.isArray(report.sidecars) || report.sidecars.length < 1) {
    fail('typed music evidence inventory is empty');
  }
  const reopened = new Map();
  const rebound = new Map();
  let prior = '';
  for (const raw of report.sidecars) {
    const binding = exactObject(raw, ['file', 'sha256', 'bytes'],
      'typed music evidence binding');
    if (typeof binding.file !== 'string' ||
        !/^[A-Z][A-Z0-9_]{0,95}\.(?:json|wav)$/.test(binding.file) ||
        binding.file <= prior || !SHA256.test(binding.sha256) ||
        nonnegativeInteger(binding.bytes, 'typed music evidence bytes') < 1) {
      fail('typed music evidence inventory is invalid');
    }
    const isWave = binding.file.endsWith('.wav');
    const item = stableRead(
      outputDir, binding.file, `typed music evidence ${binding.file}`,
      isWave ? 64 * 1024 * 1024 : DEFAULT_MAX_SIDECAR_BYTES,
      isWave ? 'binary' : false);
    if (item.sha256 !== binding.sha256 || item.bytes !== binding.bytes) {
      fail(`typed music evidence ${binding.file} changed`);
    }
    rebound.set(binding.file, item);
    reopened.set(binding.file, isWave ? null : item.report);
    prior = binding.file;
  }
  const executionPolicy = reopened.get('MUSIC_EXECUTION_EDIT_POLICY.json');
  if (!executionPolicy ||
      editPolicySha256(validateEditPolicy(executionPolicy)) !==
        report.execution_edit_policy_sha256 ||
      executionPolicy.duration.duration_ms !== duration ||
      executionPolicy.duration.band !== report.duration_band ||
      !sameCanonical(executionPolicy.rules.music, policy)) {
    fail('typed music execution policy evidence does not match');
  }
  if (!rendered) {
    const expected = report.mode === 'no_music_requested'
      ? ['MUSIC_EXECUTION_EDIT_POLICY.json']
      : [
        'MUSIC_EXECUTION_EDIT_POLICY.json', 'MUSIC_SOURCE_ANALYSIS.json',
        'MUSIC_SPEECH_EVIDENCE.json',
      ];
    if (!sameCanonical([...reopened.keys()].sort(), expected.sort())) {
      fail('typed music no-op persisted unexpected evidence');
    }
  } else {
    const required = [
      'MUSIC_ASSET_MANIFEST.json', 'MUSIC_AUDIO_QA.json',
      'MUSIC_COMPILE_RECEIPT.json', 'MUSIC_EXECUTION_EDIT_POLICY.json',
      'MUSIC_GENERATION_EVIDENCE.json', 'MUSIC_PLAN.json',
      'MUSIC_PROJECT_BED.wav', 'MUSIC_RENDER_RECEIPT.json',
      'MUSIC_SOURCE_ANALYSIS.json', 'MUSIC_SPEECH_EVIDENCE.json',
    ].sort();
    if (!sameCanonical([...reopened.keys()].sort(), required)) {
      fail('typed music persisted receipt chain is incomplete');
    }
    const manifest = validateMusicAssetManifest(
      reopened.get('MUSIC_ASSET_MANIFEST.json'));
    const plan = validateMusicPlan(
      reopened.get('MUSIC_PLAN.json'), manifest, executionPolicy);
    const compiled = compileMusicPlan(plan, manifest, executionPolicy);
    const persistedCompile = reopened.get('MUSIC_COMPILE_RECEIPT.json');
    if (manifest.output_timeline_sha256 !== report.output_timeline_sha256 ||
        manifest.output_duration_ms !== duration ||
        manifest.output_sample_rate_hz !== 48000 ||
        manifest.output_channels !== 2 ||
        musicAssetManifestSha256(manifest) !==
          report.music_asset_manifest_sha256 ||
        musicPlanSha256(plan) !== report.music_plan_sha256 ||
        !sameCanonical(compiled.receipt, persistedCompile) ||
        musicCompileReceiptSha256(persistedCompile) !==
          report.music_compile_receipt_sha256 ||
        compiled.receipt.region_count !== regionCount ||
        compiled.receipt.added_coverage_ms !== addedCoverageMs) {
      fail('typed music manifest, plan, or compile evidence is inconsistent');
    }
    const generation = exactObject(
      reopened.get('MUSIC_GENERATION_EVIDENCE.json'), [
        'schema_version', 'generator', 'parameters', 'asset', 'rights',
      ], 'typed music generation evidence');
    const generationBinding = rebound.get('MUSIC_GENERATION_EVIDENCE.json');
    const waveBinding = rebound.get('MUSIC_PROJECT_BED.wav');
    const regeneratedWave = regeneratedMusicBedWave(generation.parameters);
    if (generation.schema_version !==
          'autoeditor-music-generation-evidence/v1' ||
        generation.generator !== 'autoeditor-deterministic-musical-pcm/v1' ||
        !sameCanonical(generation.rights, {
          basis: 'project_owned', license_id: 'project-generated',
          license_name: 'Project ownership', licensor: 'project',
          external_service_used: false, permits_synchronization: true,
          permits_editing: true, permits_looping: false,
          permits_delivery: true,
        }) || manifest.assets.length !== 1 ||
        generation.asset?.sha256 !== waveBinding.sha256 ||
        generation.asset?.bytes !== waveBinding.bytes ||
        regeneratedWave.length !== waveBinding.bytes ||
        !crypto.timingSafeEqual(regeneratedWave, waveBinding.raw) ||
        manifest.assets[0].sha256 !== waveBinding.sha256 ||
        manifest.assets[0].byte_length !== waveBinding.bytes ||
        manifest.assets[0].provenance !== 'project_generated' ||
        manifest.assets[0].license?.basis !== 'project_owned' ||
        manifest.assets[0].license?.evidence_sha256 !== generationBinding.sha256 ||
        manifest.assets[0].rights_receipt?.receipt_sha256 !==
          generationBinding.sha256 ||
        manifest.transcript_sha256 !==
          rebound.get('MUSIC_SPEECH_EVIDENCE.json').sha256 ||
        manifest.source_music?.evidence_sha256 !==
          rebound.get('MUSIC_SOURCE_ANALYSIS.json').sha256) {
      fail('typed music project-owned generation evidence is invalid');
    }
    const persistedAudioQa = exactObject(
      reopened.get('MUSIC_AUDIO_QA.json'), [
        'schema_version', 'output_sha256', 'measurement',
      ], 'typed music audio QA sidecar');
    if (persistedAudioQa.schema_version !== 'autoeditor-music-audio-qa/v1' ||
        persistedAudioQa.output_sha256 !== output.sha256 ||
        !sameCanonical(persistedAudioQa.measurement, audioQa)) {
      fail('typed music persisted audio QA does not match delivery');
    }
    const render = reopened.get('MUSIC_RENDER_RECEIPT.json');
    const renderKeys = [
      'schema_version', 'music_compile_receipt_sha256', 'music_plan_sha256',
      'music_asset_manifest_sha256', 'edit_policy_sha256',
      'output_timeline_sha256', 'ordered_region_ids', 'ordered_asset_ids',
      'region_count', 'source_music_action', 'output_duration_ms',
      'target_loudness_millilufs', 'true_peak_ceiling_millidbtp',
      'render_timeout_seconds', 'program_input', 'runtime_tools',
      'asset_inputs', 'evidence_inputs', 'filter_complex_sha256',
      'render_mode', 'mastering', 'output',
    ];
    exactObject(render, renderKeys, 'typed music render receipt');
    if (sha256Text(stableJson(render)) !== report.music_render_receipt_sha256 ||
        render.schema_version !== 'autoeditor-music-render-receipt/v2' ||
        render.music_compile_receipt_sha256 !==
          report.music_compile_receipt_sha256 ||
        render.music_plan_sha256 !== report.music_plan_sha256 ||
        render.music_asset_manifest_sha256 !==
          report.music_asset_manifest_sha256 ||
        render.edit_policy_sha256 !== report.execution_edit_policy_sha256 ||
        render.output_timeline_sha256 !== report.output_timeline_sha256 ||
        render.region_count !== regionCount ||
        render.output_duration_ms !== duration || render.render_mode !== 'mixed' ||
        render.program_input?.sha256 !== program.sha256 ||
        render.program_input?.bytes !== program.bytes ||
        render.output?.sha256 !== output.sha256 ||
        render.output?.bytes !== output.bytes ||
        render.output?.duration_ms !== duration ||
        render.output?.sample_rate_hz !== 48000 ||
        render.output?.channels !== 2 || render.mastering?.passed !== true ||
        !sameCanonical(render.mastering?.delivered_measurement, {
          integrated_loudness_millilufs:
            audioQa.integrated_loudness_millilufs,
          true_peak_millidbtp: audioQa.true_peak_millidbtp,
        }) || !Array.isArray(render.asset_inputs) ||
        render.asset_inputs.length !== 1 ||
        render.asset_inputs[0]?.sha256 !== waveBinding.sha256 ||
        render.asset_inputs[0]?.bytes !== waveBinding.bytes) {
      fail('typed music render evidence does not bind the exact output');
    }
  }
  const check = exactObject(engineCheck, MUSIC_PRODUCTION_ENGINE_CHECK_KEYS,
    'engine typed music production check');
  const canonicalReceiptHash = sha256Text(stableJson(report));
  if (check.ok !== true || check.note !== '' ||
      check.authorization_id !== report.authorization_id ||
      check.engine_envelope_sha256 !== report.engine_envelope_sha256 ||
      check.project_intent_sha256 !== report.project_intent_sha256 ||
      check.parent_edit_policy_sha256 !== report.parent_edit_policy_sha256 ||
      check.execution_edit_policy_sha256 !==
        report.execution_edit_policy_sha256 || check.mode !== report.mode ||
      check.region_count !== regionCount || check.policy_usage !== policy.usage ||
      check.policy_bound !== true || check.rights_verified !== true ||
      check.dialogue_masking_verified !== true ||
      check.loudness_verified !== true ||
      check.production_receipt_sha256 !== canonicalReceiptHash ||
      check.receipt_file_sha256 !== receipt.sha256 ||
      check.program_input_sha256 !== program.sha256 ||
      check.music_output_sha256 !== output.sha256 ||
      !sameCanonical(check.measured_audio, audioQa)) {
    fail('engine QA does not bind the exact typed music production receipt');
  }
  return {
    validated: true, mode: report.mode, regionCount,
    addedMusicPresent: regionCount > 0, policyUsage: policy.usage,
    policyBound: true, productionReceiptSha256: canonicalReceiptHash,
    receiptFileSha256: receipt.sha256, programInput: { ...program },
    output: { ...output }, actualDurationMs: duration,
  };
}

function validateSfxProductionArtifactBinding({
  receipt, outputDir, approvedAuthority, engineCheck, audioMixReceipt,
  expectedEngineEnvelopeSha256, expectedMusicOutput,
}) {
  if (!receipt || !receipt.report || !SHA256.test(receipt.sha256)) {
    fail('typed SFX production receipt is missing');
  }
  const report = exactObject(
    receipt.report, SFX_PRODUCTION_RECEIPT_KEYS,
    'typed SFX production receipt');
  if (report.schema_version !== 'autoeditor-sfx-production-receipt/v1' ||
      !['rendered', 'no_sfx_requested', 'no_motivated_anchor']
        .includes(report.mode) ||
      !/^[0-9a-f]{32}$/.test(report.authorization_id)) {
    fail('typed SFX production receipt is invalid');
  }
  const authority = approvedAuthority;
  if (!authority || report.authorization_id !== authority.authorization_id ||
      report.project_intent_sha256 !== authority.project_intent_sha256 ||
      report.parent_edit_policy_sha256 !== authority.edit_policy_sha256 ||
      !SHA256.test(expectedEngineEnvelopeSha256) ||
      report.engine_envelope_sha256 !== expectedEngineEnvelopeSha256 ||
      !SHA256.test(report.execution_edit_policy_sha256) ||
      !SHA256.test(report.output_timeline_sha256)) {
    fail('typed SFX production receipt does not bind ProjectIntent authority');
  }
  const target = exactObject(report.target_duration,
    ['min_ms', 'max_ms'], 'typed SFX target duration');
  const policy = exactObject(report.policy,
    ['density', 'usage'], 'typed SFX policy');
  const project = validateProjectIntent(authority.project_intent);
  const parentPolicy = validateEditPolicy(authority.edit_policy);
  const cueCount = nonnegativeInteger(report.cue_count, 'typed SFX cue count');
  const duration = nonnegativeInteger(
    report.actual_duration_ms, 'typed SFX actual duration');
  if (duration < 1 || !sameCanonical(target, project.target_duration) ||
      duration < target.min_ms || duration > target.max_ms ||
      report.requested_preference !== project.preferences.sfx.preference ||
      !sameCanonical(policy, parentPolicy.rules.sfx) ||
      typeof report.duration_band !== 'string' || !report.duration_band ||
      (report.mode === 'rendered') !== (cueCount > 0)) {
    fail('typed SFX production policy or duration is invalid');
  }
  const media = ['program_input', 'output'].map((name) => {
    const value = exactObject(report[name],
      ['sha256', 'bytes', 'duration_ms'], `typed SFX ${name}`);
    if (!SHA256.test(value.sha256) ||
        nonnegativeInteger(value.bytes, `typed SFX ${name} bytes`) < 1 ||
        value.duration_ms !== duration) {
      fail(`typed SFX ${name} binding is invalid`);
    }
    return value;
  });
  if (expectedMusicOutput) {
    const fullMusicMedia = [
      'sha256', 'bytes', 'duration_ms', 'audio_present', 'sample_rate_hz',
      'channels',
    ];
    const expectedKeys = Object.keys(expectedMusicOutput).sort();
    const expected = exactObject(expectedMusicOutput,
      expectedKeys.join('\0') === ['bytes', 'duration_ms', 'sha256'].join('\0')
        ? ['sha256', 'bytes', 'duration_ms'] : fullMusicMedia,
      'typed music output supplied to SFX');
    if (report.program_input.sha256 !== expected.sha256 ||
        report.program_input.bytes !== expected.bytes ||
        report.program_input.duration_ms !== expected.duration_ms) {
      fail('typed SFX program input is not the exact typed music output');
    }
  }
  const chainNames = [
    'cue_manifest_sha256', 'sfx_plan_sha256',
    'sfx_compile_receipt_sha256', 'sfx_render_receipt_sha256',
  ];
  if (chainNames.some((name) => report.mode === 'rendered'
    ? !SHA256.test(report[name]) : report[name] !== null)) {
    fail('typed SFX production receipt chain is inconsistent');
  }
  if (report.mode !== 'rendered' && !sameCanonical(media[0], media[1])) {
    fail('typed SFX no-op changed program bytes');
  }
  const expectedTimelineSha256 = sha256Text(stableJson({
    schema_version: 'autoeditor-sfx-output-timeline/v1',
    program_sha256: report.program_input.sha256,
    program_bytes: report.program_input.bytes,
    duration_ms: duration,
    time_base: { numerator: 1, denominator: 1000 },
  }));
  if (report.output_timeline_sha256 !== expectedTimelineSha256) {
    fail('typed SFX output timeline is not bound to its exact input program');
  }
  const audioMaster = audioMixReceipt?.report?.master;
  if (!audioMaster || audioMaster.sha256 !== report.output.sha256 ||
      audioMaster.bytes !== report.output.bytes ||
      typeof audioMaster.duration_seconds !== 'number' ||
      !Number.isFinite(audioMaster.duration_seconds) ||
      Math.abs(Math.round(audioMaster.duration_seconds * 1000) - duration) > 1) {
    fail('typed SFX output is not the exact audio-mix master');
  }
  if (!Array.isArray(report.sidecars) || report.sidecars.length < 1) {
    fail('typed SFX evidence inventory is empty');
  }
  const reopened = new Map();
  let prior = '';
  for (const raw of report.sidecars) {
    const binding = exactObject(raw, ['file', 'sha256', 'bytes'],
      'typed SFX evidence binding');
    if (typeof binding.file !== 'string' ||
        !/^[A-Z][A-Z0-9_]{0,95}\.json$/.test(binding.file) ||
        binding.file <= prior || !SHA256.test(binding.sha256) ||
        nonnegativeInteger(binding.bytes, 'typed SFX evidence bytes') < 1) {
      fail('typed SFX evidence inventory is invalid');
    }
    const reopenedItem = stableRead(
      outputDir, binding.file, `typed SFX evidence ${binding.file}`,
      DEFAULT_MAX_SIDECAR_BYTES, false);
    if (reopenedItem.sha256 !== binding.sha256 ||
        reopenedItem.bytes !== binding.bytes) {
      fail(`typed SFX evidence ${binding.file} changed`);
    }
    reopened.set(binding.file, reopenedItem.report);
    prior = binding.file;
  }
  const executionPolicy = reopened.get('SFX_EXECUTION_EDIT_POLICY.json');
  if (!executionPolicy ||
      editPolicySha256(validateEditPolicy(executionPolicy)) !==
        report.execution_edit_policy_sha256 ||
      executionPolicy.duration.duration_ms !== duration ||
      !sameCanonical(executionPolicy.rules.sfx, policy)) {
    fail('typed SFX execution policy evidence does not match');
  }
  if (report.mode === 'rendered') {
    const required = [
      'SFX_CUE_MANIFEST.json', 'SFX_PLAN.json',
      'SFX_COMPILE_RECEIPT.json', 'SFX_RENDER_RECEIPT.json',
      'SFX_EDL_ANCHOR_EVIDENCE.json',
      'SFX_BOUNDARY_ANCHOR_EVIDENCE.json', 'SFX_SPEECH_EVIDENCE.json',
    ];
    if (required.some((name) => !reopened.has(name)) ||
        sha256Text(stableJson(reopened.get('SFX_RENDER_RECEIPT.json'))) !==
          report.sfx_render_receipt_sha256) {
      fail('typed SFX persisted receipt chain does not match production');
    }
    const manifest = validateSfxCueManifest(
      reopened.get('SFX_CUE_MANIFEST.json'));
    const plan = validateSfxPlan(
      reopened.get('SFX_PLAN.json'), manifest, executionPolicy);
    const compiled = compileSfxPlan(plan, manifest, executionPolicy);
    const persistedCompile = reopened.get('SFX_COMPILE_RECEIPT.json');
    if (manifest.output_timeline_sha256 !== report.output_timeline_sha256 ||
        sfxCueManifestSha256(manifest) !== report.cue_manifest_sha256 ||
        sfxPlanSha256(plan) !== report.sfx_plan_sha256 ||
        !sameCanonical(compiled.receipt, persistedCompile) ||
        sfxCompileReceiptSha256(persistedCompile) !==
          report.sfx_compile_receipt_sha256 ||
        compiled.receipt.cue_count !== cueCount) {
      fail('typed SFX manifest, plan, or compile evidence is inconsistent');
    }
    const renderReceipt = reopened.get('SFX_RENDER_RECEIPT.json');
    if (renderReceipt?.sfx_compile_receipt_sha256 !==
          report.sfx_compile_receipt_sha256 ||
        renderReceipt?.output?.sha256 !== report.output.sha256 ||
        renderReceipt?.output?.bytes !== report.output.bytes ||
        renderReceipt?.cue_count !== cueCount ||
        renderReceipt?.output_timeline_sha256 !==
          report.output_timeline_sha256) {
      fail('typed SFX render evidence does not bind the final master');
    }
    const generation = [...reopened.entries()].filter(([name]) =>
      name.startsWith('SFX_GENERATION_'));
    if (!generation.length || generation.some(([, value]) =>
      value?.generator !== 'autoeditor-deterministic-pcm/v1' ||
      value?.rights?.basis !== 'project_owned' ||
      value?.rights?.license_id !== 'project-generated' ||
      value?.rights?.licensor !== 'project' ||
      value?.rights?.external_service_used !== false)) {
      fail('typed SFX project-owned generation evidence is invalid');
    }
  } else if (reopened.size !== 1) {
    fail('typed SFX no-op persisted unexpected evidence');
  }
  const check = exactObject(
    engineCheck, SFX_PRODUCTION_ENGINE_CHECK_KEYS,
    'engine typed SFX production check');
  const canonicalReceiptHash = sha256Text(stableJson(report));
  if (check.ok !== true || check.note !== '' ||
      check.authorization_id !== report.authorization_id ||
      check.engine_envelope_sha256 !== report.engine_envelope_sha256 ||
      check.project_intent_sha256 !== report.project_intent_sha256 ||
      check.parent_edit_policy_sha256 !== report.parent_edit_policy_sha256 ||
      check.mode !== report.mode || check.cue_count !== cueCount ||
      check.policy_usage !== policy.usage || check.policy_bound !== true ||
      check.production_receipt_sha256 !== canonicalReceiptHash ||
      check.receipt_file_sha256 !== receipt.sha256 ||
      check.master_output_sha256 !== report.output.sha256 ||
      check.program_input_sha256 !== report.program_input.sha256 ||
      check.music_output_sha256 !== (expectedMusicOutput?.sha256 || '') ||
      check.program_input_matches_music_output !== true) {
    fail('engine QA does not bind the exact typed SFX production receipt');
  }
  return {
    validated: true, mode: report.mode, cueCount,
    policyUsage: policy.usage, policyBound: true,
    productionReceiptSha256: canonicalReceiptHash,
    receiptFileSha256: receipt.sha256,
    masterOutputSha256: report.output.sha256,
    actualDurationMs: duration,
  };
}

function validateProjectIntentArtifactBinding({
  receipt, approvedProposal, approvedAuthority, engineCheck, observed,
}) {
  if (!receipt || !receipt.report) fail('ProjectIntent render receipt is missing');
  const report = exactObject(
    receipt.report, PROJECT_INTENT_RENDER_RECEIPT_KEYS,
    'ProjectIntent render receipt');
  if (report.schema_version !== PROJECT_INTENT_RENDER_RECEIPT_SCHEMA ||
      report.pass !== true || !SHA256.test(receipt.sha256)) {
    fail('ProjectIntent render receipt did not pass');
  }
  if (!approvedProposal || typeof approvedProposal !== 'object' ||
      !Object.prototype.hasOwnProperty.call(approvedProposal, 'projectIntent')) {
    fail('ProjectIntent render receipt is orphaned');
  }
  const approvedProject = validateProjectIntent(approvedProposal.projectIntent);
  const authority = exactObject(approvedAuthority, [
    'schema_version', 'authorization_id', 'approved_proposal_sha256',
    'project_intent',
    'project_intent_sha256', 'edit_policy', 'edit_policy_sha256',
    'capability_manifest', 'capability_manifest_sha256',
    'authorization_hmac_sha256',
  ], 'approved ProjectIntent authority');
  if (authority.schema_version !== 'autoeditor-project-intent-authority/v2' ||
      !/^[0-9a-f]{32}$/.test(authority.authorization_id) ||
      !SHA256.test(authority.approved_proposal_sha256) ||
      !SHA256.test(authority.authorization_hmac_sha256)) {
    fail('approved ProjectIntent authority is invalid');
  }
  const project = validateProjectIntent(authority.project_intent);
  const manifest = validateCapabilityManifest(authority.capability_manifest);
  const policy = validateEditPolicy(authority.edit_policy);
  const resolved = resolveProjectIntentPolicy(project, manifest);
  const projectHash = projectIntentSha256(project);
  const policyHash = editPolicySha256(policy);
  const manifestHash = sha256Text(stableJson(manifest));
  const approvedProposalHash = sha256Text(stableJson(approvedProposal));
  const transitionCarrier = approvedTransitionCarrier(approvedProposal);
  if (!sameCanonical(project, approvedProject) ||
      !sameCanonical(policy, resolved) ||
      authority.approved_proposal_sha256 !== approvedProposalHash ||
      authority.project_intent_sha256 !== projectHash ||
      authority.edit_policy_sha256 !== policyHash ||
      authority.capability_manifest_sha256 !== manifestHash) {
    fail('approved ProjectIntent authority objects or digests do not match');
  }
  const envelope = {
    schema_version: PROJECT_INTENT_ENGINE_ENVELOPE_SCHEMA,
    authorization_id: authority.authorization_id,
    approved_proposal_sha256: approvedProposalHash,
    approved_transition_carrier: transitionCarrier,
    project_intent: project,
    project_intent_sha256: projectHash,
    edit_policy: policy,
    edit_policy_sha256: policyHash,
    capability_manifest: manifest,
    capability_manifest_sha256: manifestHash,
    capability_probe_receipt_sha256: manifest.probe_receipt_sha256,
  };
  const envelopeHash = sha256Text(stableJson(envelope));
  if (report.authorization_id !== authority.authorization_id ||
      report.approved_proposal_sha256 !== approvedProposalHash ||
      !sameCanonical(report.approved_transition_carrier, transitionCarrier) ||
      report.engine_envelope_sha256 !== envelopeHash ||
      report.project_intent_sha256 !== projectHash ||
      report.edit_policy_sha256 !== policyHash ||
      report.capability_manifest_sha256 !== manifestHash ||
      report.capability_probe_receipt_sha256 !== manifest.probe_receipt_sha256 ||
      !sameCanonical(report.project_intent, project) ||
      !sameCanonical(report.edit_policy, policy) ||
      !sameCanonical(report.capability_manifest, manifest)) {
    fail('ProjectIntent render receipt was swapped or does not match approval');
  }
  const actual = validateActualRender(report.actual_render);
  const derived = derivedProjectIntentChecks(project, policy, actual);
  const checks = exactObject(
    report.checks, PROJECT_INTENT_CHECK_NAMES, 'ProjectIntent render checks');
  const expectedChecks = {
    canonical_authority: true,
    ...derived,
  };
  for (const name of PROJECT_INTENT_CHECK_NAMES) {
    const check = exactObject(checks[name], ['ok'], `ProjectIntent ${name} check`);
    if (check.ok !== expectedChecks[name] || check.ok !== true) {
      fail(`ProjectIntent ${name} release check failed`);
    }
  }
  const expectedObserved = exactObject(observed, [
    'duration_ms', 'width', 'height', 'caption_delivery',
    'caption_event_count', 'graphic_event_count', 'added_music_present',
    'sfx_cue_count', 'sfx_policy_usage', 'sfx_policy_bound',
    'transition_event_count', 'non_hard_transition_count',
    'transition_policy_usage', 'transition_policy_bound',
  ], 'observed ProjectIntent render facts');
  if (actual.duration_ms !== expectedObserved.duration_ms ||
      actual.delivery.width !== expectedObserved.width ||
      actual.delivery.height !== expectedObserved.height ||
      actual.preferences.captions.delivery !== expectedObserved.caption_delivery ||
      actual.preferences.captions.event_count !== expectedObserved.caption_event_count ||
      actual.preferences.graphics.event_count !== expectedObserved.graphic_event_count ||
      actual.preferences.music.added_music_present !==
        expectedObserved.added_music_present ||
      actual.preferences.music.source_music_preserved !== false ||
      actual.preferences.sfx.cue_count !== expectedObserved.sfx_cue_count ||
      actual.preferences.sfx.policy_usage !== expectedObserved.sfx_policy_usage ||
      actual.preferences.sfx.policy_bound !== expectedObserved.sfx_policy_bound ||
      actual.preferences.transitions.event_count !==
        expectedObserved.transition_event_count ||
      actual.preferences.transitions.non_hard_event_count !==
        expectedObserved.non_hard_transition_count ||
      actual.preferences.transitions.policy_usage !==
        expectedObserved.transition_policy_usage ||
      actual.preferences.transitions.policy_bound !==
        expectedObserved.transition_policy_bound) {
    fail('ProjectIntent render receipt does not match independently observed output');
  }
  const check = exactObject(
    engineCheck, PROJECT_INTENT_ENGINE_CHECK_KEYS,
    'engine ProjectIntent authority check');
  const renderReceiptHash = sha256Text(stableJson(report));
  if (check.ok !== true || check.note !== '' ||
      check.authorization_id !== authority.authorization_id ||
      check.approved_proposal_sha256 !== approvedProposalHash ||
      !sameCanonical(check.approved_transition_carrier, transitionCarrier) ||
      check.engine_envelope_sha256 !== envelopeHash ||
      check.project_intent_sha256 !== projectHash ||
      check.edit_policy_sha256 !== policyHash ||
      check.capability_manifest_sha256 !== manifestHash ||
      check.capability_probe_receipt_sha256 !== manifest.probe_receipt_sha256 ||
      check.render_receipt_sha256 !== renderReceiptHash ||
      check.receipt_file_sha256 !== receipt.sha256) {
    fail('engine QA does not bind the exact ProjectIntent render receipt');
  }
  return {
    validated: true,
    authorizationId: authority.authorization_id,
    approvedProposalSha256: approvedProposalHash,
    approvedTransitionCarrier: transitionCarrier,
    engineEnvelopeSha256: envelopeHash,
    projectIntentSha256: projectHash,
    editPolicySha256: policyHash,
    capabilityManifestSha256: manifestHash,
    capabilityProbeReceiptSha256: manifest.probe_receipt_sha256,
    renderReceiptSha256: renderReceiptHash,
    receiptFileSha256: receipt.sha256,
  };
}

function realOutputRoot(outputDir) {
  if (typeof outputDir !== 'string' || !path.isAbsolute(outputDir) ||
      outputDir.includes('\0')) fail('artifact output folder is invalid');
  let root;
  try { root = fs.realpathSync.native(outputDir); }
  catch (_) { fail('artifact output folder is unavailable'); }
  if (!fs.statSync(root).isDirectory()) fail('artifact output folder is invalid');
  return root;
}

function stableRead(outputDir, file, label, maximumBytes, text = false) {
  const root = realOutputRoot(outputDir);
  if (typeof file !== 'string' || !file || path.basename(file) !== file ||
      file.includes('\0')) fail(`${label} has an unsafe filename`);
  let real;
  try { real = fs.realpathSync.native(path.join(root, file)); }
  catch (_) { fail(`${label} is unavailable`); }
  if (!inside(root, real)) fail(`${label} is outside the output folder`);
  const handle = fs.openSync(real, 'r');
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size < 1 || before.size > maximumBytes) {
      fail(`${label} has an invalid size`);
    }
    const raw = Buffer.alloc(before.size);
    if (fs.readSync(handle, raw, 0, before.size, 0) !== before.size) {
      fail(`${label} changed while it was read`);
    }
    const after = fs.fstatSync(handle);
    if (after.size !== before.size || after.mtimeMs !== before.mtimeMs ||
        after.dev !== before.dev || after.ino !== before.ino) {
      fail(`${label} changed while it was read`);
    }
    const receipt = {
      file: path.basename(real),
      bytes: before.size,
      sha256: crypto.createHash('sha256').update(raw).digest('hex'),
    };
    if (text === 'binary') return { ...receipt, raw };
    if (text) return { ...receipt, text: raw.toString('utf8') };
    try { return { ...receipt, report: JSON.parse(raw.toString('utf8')) }; }
    catch (_) { fail(`${label} is not valid JSON`); }
  } finally {
    fs.closeSync(handle);
  }
}

function stableFileIdentity(file, label, expectedSha256, expectedBytes) {
  let handle;
  try { handle = fs.openSync(file, 'r'); }
  catch (_) { fail(`${label} is unavailable`); }
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size !== expectedBytes) {
      fail(`${label} no longer has the reviewed byte length`);
    }
    const hash = crypto.createHash('sha256');
    const buffer = Buffer.alloc(Math.min(1024 * 1024, expectedBytes));
    let position = 0;
    while (position < expectedBytes) {
      const count = fs.readSync(
        handle, buffer, 0, Math.min(buffer.length, expectedBytes - position), position);
      if (count < 1) fail(`${label} changed while it was read`);
      hash.update(buffer.subarray(0, count));
      position += count;
    }
    const after = fs.fstatSync(handle);
    if (after.size !== before.size || after.mtimeMs !== before.mtimeMs ||
        after.dev !== before.dev || after.ino !== before.ino ||
        hash.digest('hex') !== expectedSha256) {
      fail(`${label} no longer matches the reviewed bytes`);
    }
  } finally {
    fs.closeSync(handle);
  }
}

function readBoundedJsonSidecar(outputDir, file, label,
                                maximumBytes = DEFAULT_MAX_SIDECAR_BYTES) {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 2 ||
      maximumBytes > 64 * 1024 * 1024) fail('sidecar byte limit is invalid');
  return stableRead(outputDir, file, label, maximumBytes, false);
}

function readBoundedTextSidecar(outputDir, file, label,
                                maximumBytes = DEFAULT_MAX_SIDECAR_BYTES) {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 1 ||
      maximumBytes > 64 * 1024 * 1024) fail('sidecar byte limit is invalid');
  return stableRead(outputDir, file, label, maximumBytes, true);
}

function validateFinalOutputTarget(outputDir, pendingRaw, finalRaw) {
  if (typeof pendingRaw !== 'string' || typeof finalRaw !== 'string' ||
      !path.isAbsolute(pendingRaw) || !path.isAbsolute(finalRaw) ||
      pendingRaw.includes('\0') || finalRaw.includes('\0')) {
    fail('the pending/final artifact paths are invalid');
  }
  const root = realOutputRoot(outputDir);
  let pending;
  try { pending = fs.realpathSync.native(pendingRaw); }
  catch (_) { fail('the pending artifact is unavailable'); }
  if (!inside(root, pending) || !fs.statSync(pending).isFile() ||
      !/\.UNVERIFIED(?:\.|$)/i.test(path.basename(pending))) {
    fail('the engine artifact is not a safe pending file');
  }
  const resolvedFinal = path.resolve(finalRaw);
  let finalParent;
  try { finalParent = fs.realpathSync.native(path.dirname(resolvedFinal)); }
  catch (_) { fail('the final artifact parent is unavailable'); }
  const final = path.join(finalParent, path.basename(resolvedFinal));
  if (!inside(root, final) || finalParent !== root ||
      path.extname(final).toLowerCase() !== '.mp4' || final === pending ||
      fs.existsSync(final)) {
    fail('the desired final artifact path is unsafe or already exists');
  }
  return { pending, approved: final };
}

function artifactPromotionTarget(event, outputDir) {
  if (!event || typeof event !== 'object' || Array.isArray(event) ||
      !event.outputs || typeof event.outputs !== 'object' ||
      Array.isArray(event.outputs) || !event.finalOutputs ||
      typeof event.finalOutputs !== 'object' || Array.isArray(event.finalOutputs)) {
    fail('the engine omitted pending/final artifact mappings');
  }
  const keys = Object.keys(event.outputs);
  const finalKeys = Object.keys(event.finalOutputs);
  if (keys.length !== 1 || finalKeys.length !== 1 || !keys[0] ||
      keys[0] !== finalKeys[0]) {
    fail('the engine pending/final artifact keys do not match exactly');
  }
  const key = keys[0];
  const target = validateFinalOutputTarget(
    outputDir, event.outputs[key], event.finalOutputs[key]);
  let primary;
  try { primary = fs.realpathSync.native(event.output); }
  catch (_) { fail('the primary engine artifact is unavailable'); }
  if (primary !== target.pending) {
    fail('the primary artifact does not match its output key');
  }
  return { key, ...target };
}

function sidecarBinding(contract, name, receipt, required = true) {
  const binding = contract?.[name];
  if (!binding && !required) return null;
  if (!binding || typeof binding !== 'object' || Array.isArray(binding)) {
    fail(`engine QA does not bind the exact ${name} sidecar`);
  }
  exactObject(binding, ['file', 'bytes', 'sha256'], `${name} sidecar binding`);
  if (
      binding.file !== receipt?.file || binding.sha256 !== receipt?.sha256 ||
      !Number.isSafeInteger(binding.bytes) || binding.bytes < 1 ||
      binding.bytes !== receipt?.bytes || !SHA256.test(binding.sha256)) {
    fail(`engine QA does not bind the exact ${name} sidecar`);
  }
  return binding;
}

function contractSidecarFile(contract, name, required = true) {
  const binding = contract?.[name];
  if (!binding && !required) return '';
  if (!binding || typeof binding !== 'object' || Array.isArray(binding) ||
      typeof binding.file !== 'string' || !binding.file ||
      path.basename(binding.file) !== binding.file) {
    fail(`engine QA lacks a safe ${name} sidecar binding`);
  }
  return binding.file;
}

function readContractJsonSidecar(outputDir, contract, name, label,
                                 required = true) {
  const file = contractSidecarFile(contract, name, required);
  if (!file) return null;
  const receipt = readBoundedJsonSidecar(outputDir, file, label);
  sidecarBinding(contract, name, receipt, required);
  return receipt;
}

function readContractTextSidecar(outputDir, contract, name, label,
                                 required = true) {
  const file = contractSidecarFile(contract, name, required);
  if (!file) return null;
  const receipt = readBoundedTextSidecar(outputDir, file, label);
  sidecarBinding(contract, name, receipt, required);
  return receipt;
}

const DETERMINISTIC_VISUAL_THRESHOLDS = Object.freeze({
  black_luma_max: 16,
  black_pixel_ratio_ppm_min: 990000,
  blank_luma_range_max: 4,
  blank_luma_mad_max: 1,
  near_duplicate_mae_ppm_max: 8000,
  freeze_duration_us_min: 500000,
  flash_luma_jump_min: 64,
  flash_outer_mae_ppm_max: 47059,
  overlay_channel_delta_min: 8,
  overlay_pixel_presence_ppm_min: 2000,
  overlay_state_signal_ppm_min: 10000,
  caption_contrast_ratio_ppm_min: 4500000,
  graphic_contrast_ratio_ppm_min: 3000000,
  transition_endpoint_mae_ppm_min: 20000,
  transition_alpha_ppm_min: 50000,
  transition_alpha_ppm_max: 950000,
  transition_blend_residual_ppm_max: 30000,
  transition_between_component_ratio_ppm_min: 950000,
  dip_black_pixel_ratio_ppm_min: 950000,
});
const DETERMINISTIC_VISUAL_SCOPE = Object.freeze({
  claims: Object.freeze([
    'decoded-rgb24-black-and-uniform-frame-measurement',
    'decoded-rgb24-near-duplicate-and-isolated-flash-measurement',
    'trusted-renderer-rectangle-and-safe-area-containment',
    'trusted-receipt-overlay-pixel-presence-contrast-and-state-change',
    'trusted-transition-before-middle-after-pixel-continuity',
  ]),
  unsupported: Object.freeze([
    'ocr', 'semantic-content', 'identity-or-target-recognition',
    'aesthetic-quality', 'intent-inference', 'arbitrary-transition-quality',
  ]),
});
const VISUAL_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/;

function visualInteger(value, minimum, maximum, label) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`${label} is not a bounded integer`);
  }
  return value;
}

function visualDigest(value, label) {
  if (typeof value !== 'string' || !SHA256.test(value)) {
    fail(`${label} is not a SHA-256 digest`);
  }
  return value;
}

function visualId(value, label) {
  if (typeof value !== 'string' || !VISUAL_ID.test(value)) {
    fail(`${label} is not a bounded identifier`);
  }
  return value;
}

function visualList(value, minimum, maximum, label) {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) {
    fail(`${label} is outside its list bound`);
  }
  return value;
}

function visualHash(value) {
  return sha256Text(stableJson(value));
}

function visualGcd(left, right) {
  let a = left;
  let b = right;
  while (b) [a, b] = [b, a % b];
  return a;
}

function visualTimestampUs(frameIndex, rate) {
  const numerator = BigInt(frameIndex) * BigInt(rate.denominator) * 1000000n;
  const rounded = (numerator + BigInt(Math.floor(rate.numerator / 2))) /
    BigInt(rate.numerator);
  const value = Number(rounded);
  if (!Number.isSafeInteger(value)) fail('deterministic visual frame time overflowed');
  return value;
}

function validateVisualGeometry(value, label, rgb24 = false) {
  const geometry = exactObject(value, ['width', 'height', 'pixel_format'], label);
  const width = visualInteger(geometry.width, 16, 4096, `${label} width`);
  const height = visualInteger(geometry.height, 16, 4096, `${label} height`);
  if (width * height > 3840 * 2160 || typeof geometry.pixel_format !== 'string' ||
      !geometry.pixel_format || (rgb24 && geometry.pixel_format !== 'rgb24')) {
    fail(`${label} is invalid`);
  }
  return geometry;
}

function validateVisualRate(value) {
  const rate = exactObject(
    value, ['numerator', 'denominator'], 'deterministic visual frame rate');
  visualInteger(rate.numerator, 1, 240000, 'visual frame-rate numerator');
  visualInteger(rate.denominator, 1, 10000, 'visual frame-rate denominator');
  if (visualGcd(rate.numerator, rate.denominator) !== 1 ||
      rate.numerator < rate.denominator ||
      rate.numerator > 240 * rate.denominator) {
    fail('deterministic visual frame rate is invalid');
  }
  return rate;
}

function validateVisualIntent(value, sourceDurationMs) {
  const intent = exactObject(value, [
    'schema_version', 'intentional_dark_intervals_ms', 'transitions',
    'transition_receipt_sha256',
  ], 'deterministic visual intent');
  if (intent.schema_version !== PRODUCTION_VISUAL_INTENT_SCHEMA) {
    fail('deterministic visual intent schema is invalid');
  }
  let priorStart = -1;
  for (const interval of visualList(
    intent.intentional_dark_intervals_ms, 0, 128, 'visual dark intervals')) {
    exactObject(interval, ['start_ms', 'end_ms'], 'visual dark interval');
    visualInteger(interval.start_ms, 0, sourceDurationMs, 'visual dark start');
    visualInteger(interval.end_ms, 1, sourceDurationMs, 'visual dark end');
    if (interval.start_ms < priorStart || interval.end_ms <= interval.start_ms) {
      fail('deterministic visual dark intervals are invalid');
    }
    priorStart = interval.start_ms;
  }
  let priorIndex = -1;
  priorStart = -1;
  let supported = 0;
  for (const transition of visualList(
    intent.transitions, 0, 128, 'visual transitions')) {
    exactObject(transition, [
      'boundary_index', 'kind', 'output_start_ms', 'output_end_ms', 'overlap_ms',
    ], 'visual transition');
    visualInteger(transition.boundary_index, 0, 127, 'transition index');
    visualInteger(transition.output_start_ms, 0, sourceDurationMs,
      'transition start');
    visualInteger(transition.output_end_ms, 0, sourceDurationMs,
      'transition end');
    visualInteger(transition.overlap_ms, 0, sourceDurationMs,
      'transition overlap');
    if (!['hard_cut', 'cross_dissolve', 'dip_to_black'].includes(transition.kind) ||
        transition.boundary_index <= priorIndex ||
        transition.output_start_ms < priorStart) {
      fail('deterministic visual transitions are invalid');
    }
    if (transition.kind === 'hard_cut') {
      if (transition.output_start_ms !== transition.output_end_ms ||
          transition.overlap_ms !== 0) fail('visual hard cut is invalid');
    } else {
      supported += 1;
      if (transition.output_end_ms <= transition.output_start_ms ||
          transition.overlap_ms !==
            transition.output_end_ms - transition.output_start_ms) {
        fail('visual transition interval is invalid');
      }
    }
    priorIndex = transition.boundary_index;
    priorStart = transition.output_start_ms;
  }
  if ((supported && !SHA256.test(intent.transition_receipt_sha256 || '')) ||
      (!supported && intent.transition_receipt_sha256 !== null)) {
    fail('deterministic visual transition receipt binding is invalid');
  }
  return { intent, supported };
}

function validateVisualPlan(value, frameById) {
  const plan = exactObject(value, [
    'frame_state', 'temporal_window', 'geometry', 'overlay', 'transition',
  ], 'deterministic visual check plan');
  if (!sameCanonical(plan.geometry, []) || !sameCanonical(plan.overlay, []) ||
      !sameCanonical(plan.transition, [])) {
    fail('production deterministic visual check plan exceeded its v1 scope');
  }
  const ids = new Set();
  for (const check of visualList(plan.frame_state, 1, 128, 'visual frame checks')) {
    exactObject(check, ['check_id', 'frame_id', 'expected_state'],
      'visual frame check');
    visualId(check.check_id, 'visual frame check id');
    visualId(check.frame_id, 'visual frame id');
    if (ids.has(check.check_id) || !frameById.has(check.frame_id) ||
        check.expected_state !== 'non_blank_content') {
      fail('production deterministic frame check is invalid');
    }
    ids.add(check.check_id);
  }
  for (const check of visualList(
    plan.temporal_window, 0, 128, 'visual temporal checks')) {
    exactObject(check, ['check_id', 'frame_ids', 'expected_state'],
      'visual temporal check');
    visualId(check.check_id, 'visual temporal check id');
    const frames = visualList(check.frame_ids, 3, 64, 'visual temporal frame ids');
    if (ids.has(check.check_id) || check.expected_state !== 'observe' ||
        new Set(frames).size !== frames.length) {
      fail('production deterministic temporal check is invalid');
    }
    for (let index = 0; index < frames.length; index += 1) {
      visualId(frames[index], 'visual temporal frame id');
      const current = frameById.get(frames[index]);
      if (!current || (index && current.frame_index !==
          frameById.get(frames[index - 1]).frame_index + 1)) {
        fail('production deterministic temporal frames are invalid');
      }
    }
    ids.add(check.check_id);
  }
  return plan;
}

function validateFrameMetrics(value) {
  const metrics = exactObject(value, [
    'mean_luma', 'minimum_luma', 'maximum_luma', 'luma_range', 'luma_mad',
    'black_pixel_ratio_ppm', 'quantized_luma_bin_count',
  ], 'deterministic frame metrics');
  for (const name of ['mean_luma', 'minimum_luma', 'maximum_luma',
    'luma_range', 'luma_mad']) {
    visualInteger(metrics[name], 0, 255, `deterministic frame metric ${name}`);
  }
  visualInteger(metrics.black_pixel_ratio_ppm, 0, 1000000,
    'deterministic black ratio');
  visualInteger(metrics.quantized_luma_bin_count, 1, 16,
    'deterministic luma bin count');
  return metrics;
}

function validateTemporalMetrics(value, pairCount, frameCount) {
  const metrics = exactObject(value, [
    'pair_count', 'exact_duplicate_pair_count', 'near_duplicate_pair_count',
    'longest_exact_duplicate_run_frames',
    'longest_exact_duplicate_duration_us',
    'longest_near_duplicate_run_frames',
    'longest_near_duplicate_duration_us', 'maximum_pair_mae_ppm',
    'minimum_pair_mae_ppm', 'flash_count', 'maximum_isolated_luma_jump',
  ], 'deterministic temporal metrics');
  if (metrics.pair_count !== pairCount) fail('temporal pair count is invalid');
  for (const name of ['exact_duplicate_pair_count', 'near_duplicate_pair_count']) {
    visualInteger(metrics[name], 0, pairCount, `deterministic temporal ${name}`);
  }
  for (const name of ['longest_exact_duplicate_run_frames',
    'longest_near_duplicate_run_frames']) {
    visualInteger(metrics[name], 0, frameCount, `deterministic temporal ${name}`);
  }
  for (const name of ['longest_exact_duplicate_duration_us',
    'longest_near_duplicate_duration_us']) {
    visualInteger(metrics[name], 0, 86400000000,
      `deterministic temporal ${name}`);
  }
  for (const name of ['maximum_pair_mae_ppm', 'minimum_pair_mae_ppm']) {
    visualInteger(metrics[name], 0, 1000000, `deterministic temporal ${name}`);
  }
  visualInteger(metrics.flash_count, 0, Math.max(0, frameCount - 2),
    'deterministic temporal flash count');
  visualInteger(metrics.maximum_isolated_luma_jump, 0, 255,
    'deterministic temporal luma jump');
  return metrics;
}

function validateVisualResults(checks, plan, frameById) {
  exactObject(checks, [
    'frame_state', 'temporal_window', 'geometry', 'overlay', 'transition',
  ], 'deterministic visual results');
  if (!sameCanonical(checks.geometry, []) || !sameCanonical(checks.overlay, []) ||
      !sameCanonical(checks.transition, []) ||
      checks.frame_state.length !== plan.frame_state.length ||
      checks.temporal_window.length !== plan.temporal_window.length) {
    fail('deterministic visual results do not match the production plan');
  }
  const ordered = [];
  for (let index = 0; index < checks.frame_state.length; index += 1) {
    const result = exactObject(checks.frame_state[index], [
      'check_id', 'frame_id', 'expected_state', 'frame_sha256', 'metrics',
      'observations', 'passed', 'defects',
    ], 'deterministic frame result');
    const projected = {
      check_id: result.check_id, frame_id: result.frame_id,
      expected_state: result.expected_state,
    };
    const observations = exactObject(
      result.observations, ['black', 'blank'], 'deterministic frame observations');
    validateFrameMetrics(result.metrics);
    const frame = frameById.get(result.frame_id);
    if (!sameCanonical(projected, plan.frame_state[index]) || !frame ||
        result.frame_sha256 !== frame.rgb24_sha256 ||
        typeof observations.black !== 'boolean' ||
        typeof observations.blank !== 'boolean' || observations.black ||
        observations.blank || result.passed !== true ||
        !sameCanonical(result.defects, [])) {
      fail('deterministic frame result did not pass its exact probe');
    }
    ordered.push(result);
  }
  for (let index = 0; index < checks.temporal_window.length; index += 1) {
    const result = exactObject(checks.temporal_window[index], [
      'check_id', 'frame_ids', 'expected_state', 'frame_sha256s',
      'pair_mae_ppm', 'metrics', 'observations', 'flash_frame_ids', 'passed',
      'defects',
    ], 'deterministic temporal result');
    const projected = {
      check_id: result.check_id, frame_ids: result.frame_ids,
      expected_state: result.expected_state,
    };
    const pairCount = result.frame_ids.length - 1;
    const pairMae = visualList(
      result.pair_mae_ppm, pairCount, pairCount, 'temporal pair measurements');
    pairMae.forEach((item) => visualInteger(item, 0, 1000000,
      'temporal pair measurement'));
    validateTemporalMetrics(result.metrics, pairCount, result.frame_ids.length);
    const observations = exactObject(result.observations,
      ['freeze_run', 'isolated_flash', 'stable'], 'temporal observations');
    if (Object.values(observations).some((item) => typeof item !== 'boolean') ||
        !sameCanonical(projected, plan.temporal_window[index]) ||
        !sameCanonical(result.frame_sha256s,
          result.frame_ids.map((id) => frameById.get(id)?.rgb24_sha256)) ||
        !Array.isArray(result.flash_frame_ids) ||
        result.flash_frame_ids.some((id) => !result.frame_ids.includes(id)) ||
        result.metrics.flash_count !== result.flash_frame_ids.length ||
        result.passed !== true || !sameCanonical(result.defects, [])) {
      fail('deterministic temporal result did not match its exact probe');
    }
    ordered.push(result);
  }
  return ordered;
}

function validateProductionDeterministicVisualQa(value, artifactSha256,
                                                artifactBytes) {
  const record = exactObject(value, [
    'schema_version', 'artifact', 'runtime', 'intent', 'intent_sha256',
    'decoder_receipt', 'decoder_receipt_sha256', 'timeline_receipt',
    'timeline_receipt_sha256', 'analysis', 'coverage', 'pass',
  ], 'production deterministic visual QA');
  if (record.schema_version !== PRODUCTION_DETERMINISTIC_VISUAL_QA_SCHEMA ||
      record.pass !== true) fail('production deterministic visual QA did not pass');
  const artifact = exactObject(record.artifact, ['sha256', 'bytes'],
    'deterministic visual artifact');
  if (artifact.sha256 !== artifactSha256 || artifact.bytes !== artifactBytes) {
    fail('deterministic visual QA was replayed from another artifact');
  }
  const runtime = exactObject(
    record.runtime, ['offline', 'ffmpeg', 'ffprobe'], 'visual QA runtime');
  if (runtime.offline !== true) fail('deterministic visual runtime was not offline');
  for (const name of ['ffmpeg', 'ffprobe']) {
    const tool = exactObject(runtime[name], ['sha256', 'bytes'], `visual ${name}`);
    visualDigest(tool.sha256, `visual ${name} sha256`);
    visualInteger(tool.bytes, 1, Number.MAX_SAFE_INTEGER, `visual ${name} bytes`);
  }

  const decoder = exactObject(record.decoder_receipt, [
    'schema_version', 'artifact_sha256', 'artifact_bytes', 'ffmpeg_sha256',
    'source_geometry', 'decoded_geometry', 'frame_rate', 'source_frame_count',
    'source_duration_ms', 'filter', 'frames',
  ], 'deterministic visual decoder receipt');
  const decoderSha256 = visualDigest(
    record.decoder_receipt_sha256, 'visual decoder receipt hash');
  if (decoder.schema_version !== RGB24_DECODER_RECEIPT_SCHEMA ||
      decoderSha256 !== visualHash(decoder) ||
      decoder.artifact_sha256 !== artifactSha256 ||
      decoder.artifact_bytes !== artifactBytes ||
      decoder.ffmpeg_sha256 !== runtime.ffmpeg.sha256) {
    fail('deterministic visual decoder receipt binding is invalid');
  }
  const sourceGeometry = validateVisualGeometry(
    decoder.source_geometry, 'visual decoder source geometry');
  const decodedGeometry = validateVisualGeometry(
    decoder.decoded_geometry, 'visual decoder output geometry', true);
  const rate = validateVisualRate(decoder.frame_rate);
  visualInteger(decoder.source_frame_count, 1, 20000000,
    'visual source frame count');
  visualInteger(decoder.source_duration_ms, 1, 86400000,
    'visual source duration');
  const expectedDuration = Number((
    BigInt(decoder.source_frame_count) * 1000n * BigInt(rate.denominator) +
    BigInt(Math.floor(rate.numerator / 2))) / BigInt(rate.numerator));
  if (Math.abs(expectedDuration - decoder.source_duration_ms) > Math.max(
    100, Math.ceil(2000 * rate.denominator / rate.numerator))) {
    fail('deterministic visual source duration is invalid');
  }
  const filter = exactObject(decoder.filter, [
    'selection', 'scale_width', 'scale_height', 'scale_flags', 'pixel_format',
    'fps_mode',
  ], 'deterministic visual decoder filter');
  if (!sameCanonical(filter, {
    selection: 'zero_based_frame_index',
    scale_width: decodedGeometry.width,
    scale_height: decodedGeometry.height,
    scale_flags: 'bilinear', pixel_format: 'rgb24', fps_mode: 'passthrough',
  })) fail('deterministic visual decoder filter is invalid');
  const frames = visualList(decoder.frames, 1, 128, 'decoded visual frames');
  const frameById = new Map();
  let priorIndex = -1;
  const frameBytes = decodedGeometry.width * decodedGeometry.height * 3;
  for (const frame of frames) {
    exactObject(frame, [
      'frame_id', 'frame_index', 'timestamp_us', 'rgb24_sha256', 'bytes',
    ], 'decoded visual frame');
    visualInteger(frame.frame_index, 0, decoder.source_frame_count - 1,
      'decoded frame index');
    visualInteger(frame.timestamp_us, 0, 86400000000, 'decoded frame timestamp');
    visualDigest(frame.rgb24_sha256, 'decoded frame hash');
    if (frame.frame_id !== `frame-${String(frame.frame_index).padStart(8, '0')}` ||
        frame.frame_index <= priorIndex ||
        frame.timestamp_us !== visualTimestampUs(frame.frame_index, rate) ||
        frame.bytes !== frameBytes || frameById.has(frame.frame_id)) {
      fail('decoded deterministic visual frame binding is invalid');
    }
    frameById.set(frame.frame_id, frame);
    priorIndex = frame.frame_index;
  }
  if (sourceGeometry.width < decodedGeometry.width ||
      sourceGeometry.height < decodedGeometry.height) {
    fail('deterministic visual decoder unexpectedly enlarged the artifact');
  }

  const { intent, supported } = validateVisualIntent(
    record.intent, decoder.source_duration_ms);
  const intentSha256 = visualDigest(record.intent_sha256, 'visual intent hash');
  if (intentSha256 !== visualHash(intent)) fail('visual intent hash is invalid');
  const timeline = exactObject(record.timeline_receipt, [
    'schema_version', 'artifact_sha256', 'decoder_receipt_sha256',
    'intent_sha256', 'frame_rate', 'frames', 'check_plan', 'check_plan_sha256',
  ], 'deterministic visual timeline receipt');
  const timelineSha256 = visualDigest(
    record.timeline_receipt_sha256, 'visual timeline receipt hash');
  const timelineFrames = frames.map((frame) => ({
    frame_id: frame.frame_id, frame_index: frame.frame_index,
    timestamp_us: frame.timestamp_us, rgb24_sha256: frame.rgb24_sha256,
  }));
  const plan = validateVisualPlan(timeline.check_plan, frameById);
  if (timeline.schema_version !== DECODED_TIMELINE_RECEIPT_SCHEMA ||
      timelineSha256 !== visualHash(timeline) ||
      timeline.artifact_sha256 !== artifactSha256 ||
      timeline.decoder_receipt_sha256 !== decoderSha256 ||
      timeline.intent_sha256 !== intentSha256 || !sameCanonical(timeline.frame_rate, rate) ||
      !sameCanonical(timeline.frames, timelineFrames) ||
      timeline.check_plan_sha256 !== visualHash(plan)) {
    fail('deterministic visual timeline receipt binding is invalid');
  }

  const analysis = exactObject(
    record.analysis, ['schema_version', 'receipt', 'receipt_sha256'],
    'deterministic visual analysis');
  const analysisReceipt = exactObject(analysis.receipt, [
    'schema_version', 'analyzer', 'binding', 'scope', 'checks', 'summary',
  ], 'deterministic visual analyzer receipt');
  if (analysis.schema_version !== DETERMINISTIC_VISUAL_RESULT_SCHEMA ||
      analysisReceipt.schema_version !== DETERMINISTIC_VISUAL_RECEIPT_SCHEMA ||
      analysis.receipt_sha256 !== visualHash(analysisReceipt)) {
    fail('deterministic visual analyzer receipt hash is invalid');
  }
  const analyzer = exactObject(
    analysisReceipt.analyzer, ['algorithm_version', 'thresholds'],
    'deterministic visual analyzer');
  if (analyzer.algorithm_version !== DETERMINISTIC_VISUAL_ALGORITHM ||
      !sameCanonical(analyzer.thresholds, DETERMINISTIC_VISUAL_THRESHOLDS) ||
      !sameCanonical(analysisReceipt.scope, DETERMINISTIC_VISUAL_SCOPE)) {
    fail('deterministic visual analyzer scope or thresholds drifted');
  }
  const binding = exactObject(analysisReceipt.binding, [
    'artifact_sha256', 'decoder_receipt_sha256', 'timeline_receipt_sha256',
    'request_sha256', 'decoded_frames_sha256', 'geometry_sha256',
    'timeline_sha256', 'renderer_receipt_sha256s',
  ], 'deterministic visual analyzer binding');
  Object.entries(binding).forEach(([name, digest]) => {
    if (name !== 'renderer_receipt_sha256s') visualDigest(digest, `visual ${name}`);
  });
  if (!sameCanonical(binding.renderer_receipt_sha256s, [])) {
    fail('production visual analyzer has unsupported renderer bindings');
  }
  const orderedResults = validateVisualResults(
    analysisReceipt.checks, plan, frameById);
  const request = {
    schema_version: DETERMINISTIC_VISUAL_REQUEST_SCHEMA,
    artifact_sha256: artifactSha256,
    decoder_receipt_sha256: decoderSha256,
    timeline_receipt_sha256: timelineSha256,
    geometry: decodedGeometry,
    timeline: { frame_rate: rate, frames: timelineFrames },
    checks: plan,
  };
  const decodedIdentities = frames.map((frame) => ({
    frame_id: frame.frame_id, rgb24_sha256: frame.rgb24_sha256,
    bytes: frame.bytes,
  }));
  if (binding.artifact_sha256 !== artifactSha256 ||
      binding.decoder_receipt_sha256 !== decoderSha256 ||
      binding.timeline_receipt_sha256 !== timelineSha256 ||
      binding.request_sha256 !== visualHash(request) ||
      binding.decoded_frames_sha256 !== visualHash(decodedIdentities) ||
      binding.geometry_sha256 !== visualHash(decodedGeometry) ||
      binding.timeline_sha256 !== visualHash(request.timeline)) {
    fail('deterministic visual analyzer evidence binding is invalid');
  }
  const summary = exactObject(analysisReceipt.summary, [
    'check_count', 'passed_count', 'failed_count', 'all_passed',
    'failed_check_ids',
  ], 'deterministic visual summary');
  if (summary.check_count !== orderedResults.length ||
      summary.passed_count !== orderedResults.length || summary.failed_count !== 0 ||
      summary.all_passed !== true || !sameCanonical(summary.failed_check_ids, [])) {
    fail('deterministic visual analyzer summary is invalid');
  }
  const coverage = exactObject(record.coverage, [
    'artifact_frame_count', 'decoded_frame_count', 'non_blank_sample_count',
    'temporal_window_count', 'declared_transition_count',
    'analyzed_transition_count',
  ], 'deterministic visual coverage');
  for (const [name, count] of Object.entries(coverage)) {
    visualInteger(count, 0, 20000000, `deterministic visual coverage ${name}`);
  }
  if (coverage.artifact_frame_count !== decoder.source_frame_count ||
      coverage.decoded_frame_count !== frames.length ||
      coverage.non_blank_sample_count !== plan.frame_state.length ||
      coverage.temporal_window_count !== plan.temporal_window.length ||
      coverage.declared_transition_count !== supported ||
      coverage.analyzed_transition_count !== 0) {
    fail('deterministic visual coverage does not match its exact evidence');
  }
  return { record, analysisReceipt, summary, coverage };
}

function readDeterministicVisualQaSidecar(outputDir, contract, engineCheck,
                                          artifactSha256, artifactBytes) {
  const file = contractSidecarFile(contract, 'deterministic_visual_qa', true);
  if (file !== 'DETERMINISTIC_VISUAL_QA.json') {
    fail('deterministic visual QA sidecar filename is invalid');
  }
  const receipt = stableRead(
    outputDir, file, 'deterministic visual QA receipt',
    MAX_DETERMINISTIC_VISUAL_SIDECAR_BYTES, 'binary');
  sidecarBinding(contract, 'deterministic_visual_qa', receipt, true);
  let report;
  try { report = JSON.parse(receipt.raw.toString('ascii')); }
  catch (_) { fail('deterministic visual QA receipt is not valid JSON'); }
  const expectedBytes = Buffer.from(`${stableJson(report)}\n`, 'ascii');
  if (!receipt.raw.equals(expectedBytes)) {
    fail('deterministic visual QA receipt is not canonical JSON');
  }
  const validated = validateProductionDeterministicVisualQa(
    report, artifactSha256, artifactBytes);
  const check = exactObject(engineCheck, [
    'ok', 'artifact_sha256', 'receipt_file_sha256',
    'analyzer_receipt_sha256', 'check_count', 'failed_check_ids',
    'declared_transition_count', 'analyzed_transition_count',
    'semantic_evaluation', 'note',
  ], 'engine deterministic visual QA check');
  if (check.ok !== true || check.artifact_sha256 !== artifactSha256 ||
      check.receipt_file_sha256 !== receipt.sha256 ||
      check.analyzer_receipt_sha256 !== report.analysis.receipt_sha256 ||
      check.check_count !== validated.summary.check_count ||
      !sameCanonical(check.failed_check_ids, []) ||
      check.declared_transition_count !==
        validated.coverage.declared_transition_count ||
      check.analyzed_transition_count !== 0 ||
      check.semantic_evaluation !== false || typeof check.note !== 'string') {
    fail('engine deterministic visual QA check does not bind its sidecar');
  }
  return { ...receipt, report, ...validated };
}

function artifactQaReleaseBinding(report, contract, promotion,
                                  artifactSha256, artifactBytes) {
  const releaseKeys = report.release && typeof report.release === 'object' &&
      !Array.isArray(report.release) ? Object.keys(report.release) : [];
  const release = releaseKeys.length === 1 && releaseKeys[0] === promotion.key
    ? report.release[promotion.key] : null;
  const delivery = contract.delivery;
  if (release && typeof release === 'object' && !Array.isArray(release)) {
    exactObject(release, ['file', 'bytes', 'sha256'], 'engine QA release binding');
  }
  if (delivery && typeof delivery === 'object' && !Array.isArray(delivery)) {
    exactObject(delivery, ['file', 'bytes', 'sha256'], 'engine QA delivery binding');
  }
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
      release.sha256 !== artifactSha256 || !SHA256.test(release.sha256)) {
    fail('engine QA does not bind the exact released artifact');
  }
  return release;
}

function validateEngineChecks(report) {
  const checks = report.checks;
  if (!checks || typeof checks !== 'object' || Array.isArray(checks) ||
      Reflect.ownKeys(checks).some((key) => typeof key !== 'string') ||
      Object.keys(checks).length < 1) {
    fail('the engine QA report has no closed release checks');
  }
  for (const [name, check] of Object.entries(checks)) {
    if (!check || typeof check !== 'object' || Array.isArray(check) ||
        typeof check.ok !== 'boolean') {
      fail(`engine QA check ${name} is invalid`);
    }
    if (!NON_BLOCKING_ENGINE_CHECKS.has(name) && check.ok !== true) {
      fail(`engine QA release-blocking check ${name} failed`);
    }
  }
}

function readArtifactQaReport(outputDir, event, artifactSha256, artifactBytes) {
  if (typeof artifactSha256 !== 'string' || !SHA256.test(artifactSha256) ||
      !Number.isSafeInteger(artifactBytes) || artifactBytes < 1) {
    fail('reviewed artifact identity is invalid');
  }
  const promotion = artifactPromotionTarget(event, outputDir);
  stableFileIdentity(
    promotion.pending, 'pending engine artifact', artifactSha256, artifactBytes);
  const requested = typeof event.qaReport === 'string' && event.qaReport
    ? path.basename(event.qaReport) : 'QA_REPORT.json';
  if (requested !== 'QA_REPORT.json') fail('the engine QA report path is invalid');
  const receipt = readBoundedJsonSidecar(
    outputDir, requested, 'engine QA report');
  const report = receipt.report;
  if (report?.schema !== ENGINE_QA_SCHEMA || report.pass !== true ||
      !report.artifact_contract ||
      typeof report.artifact_contract !== 'object' ||
      Array.isArray(report.artifact_contract)) {
    fail('the engine QA report lacks the versioned artifact contract');
  }
  validateEngineChecks(report);
  const contractSchema = report.artifact_contract.schema;
  const deterministicContract = [
    ENGINE_ARTIFACT_CONTRACT_DETERMINISTIC_SCHEMA,
    ENGINE_ARTIFACT_CONTRACT_INTENT_DETERMINISTIC_SCHEMA,
  ].includes(contractSchema);
  const intentContract = [
    ENGINE_ARTIFACT_CONTRACT_INTENT_SCHEMA,
    ENGINE_ARTIFACT_CONTRACT_INTENT_DETERMINISTIC_SCHEMA,
  ].includes(contractSchema);
  const contractKeys = intentContract
    ? deterministicContract
      ? INTENT_DETERMINISTIC_CONTRACT_KEYS : INTENT_CONTRACT_KEYS
    : deterministicContract ? DETERMINISTIC_CONTRACT_KEYS : LEGACY_CONTRACT_KEYS;
  const contract = exactObject(
    report.artifact_contract, contractKeys, 'engine QA artifact contract');
  if (![ENGINE_ARTIFACT_CONTRACT_SCHEMA,
    ENGINE_ARTIFACT_CONTRACT_DETERMINISTIC_SCHEMA,
    ENGINE_ARTIFACT_CONTRACT_INTENT_SCHEMA,
    ENGINE_ARTIFACT_CONTRACT_INTENT_DETERMINISTIC_SCHEMA,
  ].includes(contract.schema) ||
      !['generic-baseline', 'premium-edl'].includes(contract.mode)) {
    fail('the engine QA artifact mode is invalid');
  }
  if (intentContract &&
      (!contract.project_intent || typeof contract.project_intent !== 'object' ||
       Array.isArray(contract.project_intent) ||
       !contract.music_production ||
       typeof contract.music_production !== 'object' ||
       Array.isArray(contract.music_production) ||
       !contract.sfx_production ||
       typeof contract.sfx_production !== 'object' ||
       Array.isArray(contract.sfx_production))) {
    fail('the intent-governed artifact contract lacks its authority sidecars');
  }
  if ((contract.mode === 'generic-baseline' && contract.edl !== null) ||
      (contract.mode === 'premium-edl' && !contract.edl)) {
    fail('the engine QA artifact mode has an invalid EDL binding');
  }
  const release = artifactQaReleaseBinding(
    report, contract, promotion, artifactSha256, artifactBytes);
  const deterministicVisualQa = deterministicContract
    ? readDeterministicVisualQaSidecar(
      outputDir, contract, report.checks.deterministic_visual_quality,
      artifactSha256, artifactBytes)
    : null;
  return {
    ...receipt, contract, release, promotion, deterministicVisualQa,
  };
}

module.exports = Object.freeze({
  ENGINE_QA_SCHEMA,
  ENGINE_ARTIFACT_CONTRACT_SCHEMA,
  ENGINE_ARTIFACT_CONTRACT_DETERMINISTIC_SCHEMA,
  ENGINE_ARTIFACT_CONTRACT_INTENT_SCHEMA,
  ENGINE_ARTIFACT_CONTRACT_INTENT_DETERMINISTIC_SCHEMA,
  DEFAULT_MAX_SIDECAR_BYTES,
  ArtifactContractError,
  readBoundedJsonSidecar,
  readBoundedTextSidecar,
  validateFinalOutputTarget,
  artifactPromotionTarget,
  sidecarBinding,
  contractSidecarFile,
  readContractJsonSidecar,
  readContractTextSidecar,
  readDeterministicVisualQaSidecar,
  validateProductionDeterministicVisualQa,
  artifactQaReleaseBinding,
  validateEngineChecks,
  validateMusicProductionArtifactBinding,
  validateSfxProductionArtifactBinding,
  validateProjectIntentArtifactBinding,
  readArtifactQaReport,
});
