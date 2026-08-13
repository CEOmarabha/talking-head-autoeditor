'use strict';

// Strict JavaScript mirror of autoeditor/edit_policy.py. Keep the two
// implementations independent: cross-language canonical vectors in
// desktop/tests/edit-policy.test.js detect drift in rules or serialization.

const crypto = require('node:crypto');

const EDIT_POLICY_REQUEST_SCHEMA_VERSION = 'autoeditor-edit-policy-request/v1';
const EDIT_POLICY_SCHEMA_VERSION = 'autoeditor-edit-policy/v1';
const MAX_DURATION_MS = 86_400_000;

const CUT_DENSITIES = Object.freeze([
  'high', 'low', 'medium', 'very_high', 'very_low',
]);
const EFFECT_DENSITIES = Object.freeze(['dense', 'medium', 'none', 'sparse']);
const DIALOGUE_RULES = Object.freeze(['none', 'primary', 'supporting', 'verbatim']);
const MUSIC_RULES = Object.freeze([
  'forbidden', 'optional', 'primary', 'source_primary', 'supporting',
]);
const CAPTION_RULES = Object.freeze([
  'forbidden', 'optional', 'required', 'verbatim_required',
]);
const VISUALIZATION_RULES = Object.freeze([
  'allowed', 'forbidden', 'recommended', 'required',
]);

const CUT_MOTIVATIONS = Object.freeze([
  'beat_motivated',
  'conversion_motivated',
  'event_motivated',
  'factual_narrative_motivated',
  'gameplay_event_motivated',
  'instruction_step_motivated',
  'retention_motivated',
  'source_faithful',
  'space_continuity_motivated',
  'speaker_motivated',
  'speech_motivated',
  'sports_event_motivated',
  'story_motivated',
]);
const JL_CUT_RULES = Object.freeze([
  'allowed_when_continuity_benefits', 'forbidden', 'preferred_for_dialogue',
]);
const SFX_USAGE_RULES = Object.freeze([
  'event_accent_only',
  'forbidden',
  'interface_feedback_only',
  'motivated_only',
  'source_only',
]);
const TRANSITION_USAGE_RULES = Object.freeze([
  'beat_or_phrase_motivated',
  'continuity_motivated',
  'hard_cut_only',
  'location_motivated',
  'motivated_only',
]);

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
const ASPECTS = Object.freeze(['1:1', '16:9', '21:9', '4:5', '9:16', 'source']);

const CAPABILITIES = Object.freeze([
  'artifact_receipts',
  'audio_crossfades',
  'audio_quality_analysis',
  'beat_detection',
  'caption_rendering',
  'chart_rendering',
  'color_normalization',
  'cross_dissolves',
  'dialogue_cleanup',
  'graphic_rendering',
  'hard_cuts',
  'licensed_broll',
  'licensed_music',
  'licensed_sfx',
  'loudness_normalization',
  'motion_quality_analysis',
  'motion_tracking',
  'multicam_sync',
  'ocr',
  'project_generated_music',
  'project_generated_sfx',
  'replay',
  'scene_detection',
  'screen_content_detection',
  'slow_motion',
  'source_music_preservation',
  'speaker_diarization',
  'speech_transcription',
  'stabilization',
  'visual_quality_analysis',
  'word_timestamps',
]);

const RESOLUTION_SOURCES = Object.freeze([
  'baseline',
  'consented_preferences',
  'duration',
  'explicit_intent',
  'hard_invariant',
  'platform',
  'profile',
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
const REQUEST_KEYS = Object.freeze([
  'available_capabilities',
  'consented_preferences',
  'delivery',
  'duration_ms',
  'explicit_intent',
  'profile',
  'schema_version',
]);
const DELIVERY_KEYS = Object.freeze(['aspect', 'platform']);
const PREFERENCES_KEYS = Object.freeze(['consented', 'values']);
const POLICY_KEYS = Object.freeze([
  'delivery',
  'duration',
  'forbidden_actions',
  'profile',
  'qa_checks',
  'required_capabilities',
  'resolution_sources',
  'rules',
  'schema_version',
]);
const DURATION_KEYS = Object.freeze(['band', 'duration_ms']);
const RULE_KEYS = Object.freeze([
  'captions', 'cuts', 'dialogue', 'music', 'sfx', 'transitions', 'visualizations',
]);
const CUT_KEYS = Object.freeze(['density', 'j_l_cuts', 'motivation']);
const SFX_KEYS = Object.freeze(['density', 'usage']);
const TRANSITION_KEYS = Object.freeze(['density', 'usage']);
const DIALOGUE_KEYS = Object.freeze(['preserve_meaning', 'priority']);
const MUSIC_KEYS = Object.freeze(['duck_under_dialogue', 'usage']);
const CAPTION_KEYS = Object.freeze(['max_lines', 'safe_area_required', 'usage']);
const VISUALIZATION_KEYS = Object.freeze(['evidence_required', 'usage']);

const CUT_DENSITY_SET = new Set(CUT_DENSITIES);
const EFFECT_DENSITY_SET = new Set(EFFECT_DENSITIES);
const DIALOGUE_RULE_SET = new Set(DIALOGUE_RULES);
const MUSIC_RULE_SET = new Set(MUSIC_RULES);
const CAPTION_RULE_SET = new Set(CAPTION_RULES);
const VISUALIZATION_RULE_SET = new Set(VISUALIZATION_RULES);
const CUT_MOTIVATION_SET = new Set(CUT_MOTIVATIONS);
const JL_CUT_RULE_SET = new Set(JL_CUT_RULES);
const SFX_USAGE_RULE_SET = new Set(SFX_USAGE_RULES);
const TRANSITION_USAGE_RULE_SET = new Set(TRANSITION_USAGE_RULES);
const PLATFORM_SET = new Set(PLATFORMS);
const ASPECT_SET = new Set(ASPECTS);
const CAPABILITY_SET = new Set(CAPABILITIES);
const RESOLUTION_SOURCE_SET = new Set(RESOLUTION_SOURCES);

function pv(
  cutDensity,
  sfxDensity,
  transitionDensity,
  dialogueRule,
  musicRule,
  captionRule,
  visualizationRule,
) {
  return Object.freeze({
    cut_density: cutDensity,
    sfx_density: sfxDensity,
    transition_density: transitionDensity,
    dialogue_rule: dialogueRule,
    music_rule: musicRule,
    caption_rule: captionRule,
    visualization_rule: visualizationRule,
  });
}

function profile(
  values,
  cutMotivation,
  jlCuts,
  sfxUsage,
  transitionUsage,
  requiredCapabilities,
  forbiddenActions,
  qaChecks,
) {
  return Object.freeze({
    values,
    cut_motivation: cutMotivation,
    j_l_cuts: jlCuts,
    sfx_usage: sfxUsage,
    transition_usage: transitionUsage,
    required_capabilities: Object.freeze(requiredCapabilities),
    forbidden_actions: Object.freeze(forbiddenActions),
    qa_checks: Object.freeze(qaChecks),
  });
}

const BASELINE = pv(
  'medium', 'none', 'sparse', 'supporting', 'optional', 'optional', 'allowed',
);

const DURATION_SPECS = Object.freeze([
  Object.freeze({ maximum_ms: 15_000, name: 'micro', overrides: pv('high') }),
  Object.freeze({ maximum_ms: 60_000, name: 'short', overrides: pv('high') }),
  Object.freeze({ maximum_ms: 300_000, name: 'medium', overrides: pv('medium') }),
  Object.freeze({ maximum_ms: 1_800_000, name: 'long', overrides: pv('low') }),
  Object.freeze({
    maximum_ms: MAX_DURATION_MS,
    name: 'extended',
    overrides: pv('very_low'),
  }),
]);
const DURATION_BANDS = Object.freeze(DURATION_SPECS.map((spec) => spec.name));
const DURATION_BAND_SET = new Set(DURATION_BANDS);

const PROFILE_SPECS = Object.freeze({
  dialogue_talking_head: profile(
    pv('high', 'sparse', 'sparse', 'primary', 'supporting', 'required', 'allowed'),
    'speech_motivated',
    'preferred_for_dialogue',
    'motivated_only',
    'motivated_only',
    ['scene_detection', 'color_normalization'],
    ['cover_speaking_face', 'random_broll_without_anchor'],
    ['face_framing_and_eyeline_verified', 'jump_cut_cadence_reviewed'],
  ),
  podcast_interview: profile(
    pv(null, 'none', 'sparse', 'primary', 'supporting', 'required', 'allowed'),
    'speaker_motivated',
    'preferred_for_dialogue',
    'forbidden',
    'continuity_motivated',
    ['speaker_diarization', 'multicam_sync', 'scene_detection'],
    ['speaker_misattribution', 'reaction_retiming_misrepresentation'],
    ['active_speaker_cut_verified', 'speaker_label_accuracy_verified'],
  ),
  course_tutorial_screencast: profile(
    pv('medium', 'sparse', 'sparse', 'primary', 'optional', 'required', 'required'),
    'instruction_step_motivated',
    'allowed_when_continuity_benefits',
    'interface_feedback_only',
    'motivated_only',
    [
      'screen_content_detection', 'ocr', 'motion_tracking', 'chart_rendering',
      'graphic_rendering',
    ],
    ['cover_critical_ui', 'invent_instruction_step'],
    ['critical_ui_visibility_verified', 'instruction_order_verified'],
  ),
  commercial_product: profile(
    pv(
      'high', 'medium', 'medium', 'supporting', 'supporting', 'required',
      'recommended',
    ),
    'conversion_motivated',
    'allowed_when_continuity_benefits',
    'motivated_only',
    'motivated_only',
    ['scene_detection', 'graphic_rendering', 'chart_rendering', 'color_normalization'],
    ['unsubstantiated_claim', 'unauthorized_brand_asset'],
    ['claim_evidence_verified', 'brand_and_legal_approval_verified'],
  ),
  vlog_travel: profile(
    pv('high', 'medium', null, 'supporting', 'supporting', 'required', 'allowed'),
    'story_motivated',
    'allowed_when_continuity_benefits',
    'motivated_only',
    'location_motivated',
    ['scene_detection', 'stabilization', 'color_normalization'],
    ['misrepresent_location_as_fact', 'unanchored_stock_replacement'],
    ['location_continuity_reviewed', 'unstable_shot_reviewed'],
  ),
  gaming: profile(
    pv(
      'very_high', 'medium', 'sparse', 'supporting', 'optional', 'required',
      'allowed',
    ),
    'gameplay_event_motivated',
    'allowed_when_continuity_benefits',
    'event_accent_only',
    'motivated_only',
    ['scene_detection', 'screen_content_detection', 'ocr', 'motion_tracking'],
    ['cover_hud_or_objective', 'fabricate_gameplay_outcome'],
    ['hud_visibility_verified', 'gameplay_event_order_verified'],
  ),
  wedding_event: profile(
    pv('medium', 'sparse', 'medium', 'supporting', 'supporting', null, 'forbidden'),
    'event_motivated',
    'preferred_for_dialogue',
    'motivated_only',
    'continuity_motivated',
    ['scene_detection', 'multicam_sync', 'stabilization', 'color_normalization'],
    ['reorder_vows_to_change_meaning', 'omit_named_must_keep_event'],
    ['identity_continuity_verified', 'ceremony_and_vows_integrity_verified'],
  ),
  sports_highlights: profile(
    pv(
      'very_high', 'dense', 'medium', 'supporting', 'supporting', 'optional',
      'recommended',
    ),
    'sports_event_motivated',
    'allowed_when_continuity_benefits',
    'event_accent_only',
    'motivated_only',
    ['scene_detection', 'motion_tracking', 'slow_motion', 'replay', 'chart_rendering'],
    ['fabricate_score_or_event_order', 'present_replay_as_live'],
    ['score_and_event_order_verified', 'replay_labeling_verified'],
  ),
  music_performance: profile(
    pv('high', 'sparse', 'medium', 'none', 'source_primary', null, 'forbidden'),
    'beat_motivated',
    'allowed_when_continuity_benefits',
    'source_only',
    'beat_or_phrase_motivated',
    ['beat_detection', 'multicam_sync', 'color_normalization'],
    ['desynchronize_performance', 'replace_source_performance_without_consent'],
    ['performance_sync_verified', 'musical_phrase_integrity_verified'],
  ),
  real_estate: profile(
    pv(
      'medium', 'sparse', 'medium', 'supporting', 'supporting', null,
      'recommended',
    ),
    'space_continuity_motivated',
    'allowed_when_continuity_benefits',
    'motivated_only',
    'continuity_motivated',
    ['scene_detection', 'stabilization', 'color_normalization', 'graphic_rendering'],
    ['alter_room_geometry', 'hide_material_property_defect'],
    ['room_identity_and_geometry_verified', 'property_label_accuracy_verified'],
  ),
  documentary_narrative: profile(
    pv('low', 'none', 'sparse', 'primary', 'supporting', 'required', 'recommended'),
    'factual_narrative_motivated',
    'preferred_for_dialogue',
    'forbidden',
    'motivated_only',
    [
      'speaker_diarization', 'scene_detection', 'licensed_broll',
      'graphic_rendering', 'chart_rendering',
    ],
    ['decontextualize_quote', 'fabricate_archive_source'],
    ['quote_context_verified', 'archive_provenance_verified'],
  ),
  montage_meme: profile(
    pv('very_high', 'dense', 'medium', 'supporting', 'primary', 'required', 'allowed'),
    'retention_motivated',
    'allowed_when_continuity_benefits',
    'event_accent_only',
    'beat_or_phrase_motivated',
    ['scene_detection', 'beat_detection', 'graphic_rendering'],
    ['unlicensed_meme_asset', 'fabricate_subject_context'],
    ['rights_and_sensitive_content_reviewed', 'setup_payoff_comprehension_verified'],
  ),
  utility_faithful: profile(
    pv(null, 'none', 'none', 'verbatim', 'forbidden', null, 'forbidden'),
    'source_faithful',
    'forbidden',
    'forbidden',
    'hard_cut_only',
    ['color_normalization'],
    ['semantic_reordering', 'decorative_overlay', 'content_aware_reframe'],
    ['source_content_fidelity_verified', 'frame_and_audio_continuity_verified'],
  ),
});
const PROFILE_NAMES = Object.freeze(Object.keys(PROFILE_SPECS).sort());
const PROFILE_NAME_SET = new Set(PROFILE_NAMES);

function platform(defaultAspect, allowedAspects, overrides = pv()) {
  return Object.freeze({
    default_aspect: defaultAspect,
    allowed_aspects: Object.freeze(allowedAspects),
    overrides,
  });
}

const PLATFORM_SPECS = Object.freeze({
  youtube: platform('16:9', ['16:9', '9:16', '1:1', '4:5']),
  youtube_shorts: platform(
    '9:16', ['9:16'], pv('high', null, null, null, null, 'required'),
  ),
  tiktok: platform(
    '9:16', ['9:16'], pv('high', null, null, null, null, 'required'),
  ),
  instagram_reels: platform(
    '9:16', ['9:16'], pv('high', null, null, null, null, 'required'),
  ),
  instagram_feed: platform(
    '4:5', ['4:5', '1:1'], pv(null, null, null, null, null, 'required'),
  ),
  facebook: platform('16:9', ['16:9', '9:16', '4:5', '1:1']),
  x: platform(
    '16:9', ['16:9', '9:16', '1:1'],
    pv(null, null, null, null, null, 'required'),
  ),
  linkedin: platform(
    '16:9', ['16:9', '9:16', '4:5', '1:1'],
    pv(null, null, null, null, null, 'required'),
  ),
  web: platform('source', [...ASPECTS]),
  broadcast: platform('16:9', ['16:9']),
  archive: platform('source', ['source', '16:9', '9:16', '4:5', '1:1']),
});

const GLOBAL_REQUIRED_CAPABILITIES = Object.freeze([
  'artifact_receipts',
  'audio_quality_analysis',
  'hard_cuts',
  'loudness_normalization',
  'visual_quality_analysis',
]);
const GLOBAL_FORBIDDEN_ACTIONS = Object.freeze([
  'fabricate_speech_or_event',
  'ship_failed_or_unverified_qa',
  'use_unlicensed_asset',
  'use_untraceable_source',
]);
const GLOBAL_QA_CHECKS = Object.freeze([
  'artifact_hash_and_source_manifest_bound',
  'audio_decode_and_peak_ceiling_verified',
  'color_range_and_video_decode_verified',
  'loudness_delivery_target_verified',
  'manual_review_required_when_automated_qa_is_uncertain',
  'timeline_bounds_verified',
]);

const HARD_EXACT = Object.freeze({
  course_tutorial_screencast: Object.freeze({ visualization_rule: 'required' }),
  music_performance: Object.freeze({ music_rule: 'source_primary' }),
  utility_faithful: Object.freeze({
    sfx_density: 'none',
    transition_density: 'none',
    dialogue_rule: 'verbatim',
    music_rule: 'forbidden',
    visualization_rule: 'forbidden',
  }),
});

class EditPolicyError extends Error {
  constructor(message) {
    super(message);
    this.name = 'EditPolicyError';
  }
}

function fail(message) {
  throw new EditPolicyError(message);
}

function asciiCompare(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
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

function enumValue(value, allowed, label) {
  if (typeof value !== 'string' || !allowed.has(value)) {
    fail(`${label} is unsupported`);
  }
  return value;
}

function booleanValue(value, label) {
  if (typeof value !== 'boolean') fail(`${label} must be boolean`);
  return value;
}

function integer(value, label, minimum, maximum) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function sortedKnownList(value, allowed, label, { allowEmpty = true } = {}) {
  if (!isDenseArray(value) || (!allowEmpty && value.length === 0)) {
    fail(`${label} must be a${allowEmpty ? '' : ' non-empty'} list`);
  }
  const seen = new Set();
  const clean = value.map((item, index) => {
    const member = enumValue(item, allowed, `${label}[${index}]`);
    if (seen.has(member)) fail(`${label} must not contain duplicates`);
    seen.add(member);
    return member;
  });
  return clean.sort(asciiCompare);
}

function policyEnum(field) {
  return {
    cut_density: CUT_DENSITY_SET,
    sfx_density: EFFECT_DENSITY_SET,
    transition_density: EFFECT_DENSITY_SET,
    dialogue_rule: DIALOGUE_RULE_SET,
    music_rule: MUSIC_RULE_SET,
    caption_rule: CAPTION_RULE_SET,
    visualization_rule: VISUALIZATION_RULE_SET,
  }[field];
}

function parsePolicyValues(value, label) {
  const raw = exactKeys(value, [...POLICY_FIELDS].sort(asciiCompare), label);
  const parsed = {};
  for (const field of POLICY_FIELDS) {
    parsed[field] = raw[field] === 'auto'
      ? null
      : enumValue(raw[field], policyEnum(field), `${label}.${field}`);
  }
  return parsed;
}

function durationBand(durationMs) {
  const duration = integer(durationMs, 'duration_ms', 1, MAX_DURATION_MS);
  const spec = DURATION_SPECS.find((candidate) => duration <= candidate.maximum_ms);
  if (!spec) throw new Error('duration band table does not cover MAX_DURATION_MS');
  return spec.name;
}

function durationSpec(durationMs) {
  const band = durationBand(durationMs);
  return DURATION_SPECS.find((spec) => spec.name === band);
}

function overlay(resolved, sources, values, source) {
  for (const field of POLICY_FIELDS) {
    const member = values[field];
    if (member !== null && member !== undefined) {
      resolved[field] = member;
      sources[field] = source;
    }
  }
}

function applyHardInvariants(profileName, resolved, sources) {
  for (const [field, required] of Object.entries(HARD_EXACT[profileName] || {})) {
    if (resolved[field] !== required && sources[field] === 'explicit_intent') {
      fail(`explicit_intent.${field} conflicts with the ${profileName} hard invariant`);
    }
    resolved[field] = required;
    sources[field] = 'hard_invariant';
  }
  if (profileName === 'wedding_event' &&
      !new Set(['none', 'sparse']).has(resolved.sfx_density)) {
    fail('wedding_event hard invariant permits only none or sparse SFX');
  }
  if (profileName === 'documentary_narrative' &&
      !new Set(['primary', 'verbatim']).has(resolved.dialogue_rule)) {
    fail('documentary_narrative hard invariant requires grounded primary dialogue');
  }
  const spec = PROFILE_SPECS[profileName];
  if (spec.sfx_usage === 'forbidden' && resolved.sfx_density !== 'none') {
    fail(`${profileName} forbids added SFX, so sfx_density must be none`);
  }
  if (spec.transition_usage === 'hard_cut_only' &&
      resolved.transition_density !== 'none') {
    fail(`${profileName} permits hard cuts only, so transition_density must be none`);
  }
}

function addAll(target, values) {
  for (const value of values) target.add(value);
}

function requiredCapabilities(profileName, resolved) {
  const spec = PROFILE_SPECS[profileName];
  const required = new Set(GLOBAL_REQUIRED_CAPABILITIES);
  addAll(required, spec.required_capabilities);
  if (new Set(['primary', 'verbatim']).has(resolved.dialogue_rule)) {
    addAll(required, ['speech_transcription', 'word_timestamps', 'dialogue_cleanup']);
  } else if (resolved.dialogue_rule === 'supporting') {
    required.add('dialogue_cleanup');
  }
  if (resolved.caption_rule !== 'forbidden') required.add('caption_rendering');
  if (resolved.caption_rule === 'verbatim_required') {
    addAll(required, ['speech_transcription', 'word_timestamps']);
  }
  if (resolved.music_rule === 'supporting') {
    required.add('project_generated_music');
  } else if (resolved.music_rule === 'primary') {
    required.add('licensed_music');
  } else if (resolved.music_rule === 'source_primary') {
    required.add('source_music_preservation');
  }
  if (resolved.sfx_density !== 'none' && spec.sfx_usage !== 'source_only') {
    required.add('project_generated_sfx');
  }
  if (resolved.transition_density !== 'none') {
    addAll(required, [
      'audio_crossfades', 'cross_dissolves', 'motion_quality_analysis',
    ]);
  }
  if (new Set(['recommended', 'required']).has(resolved.visualization_rule)) {
    required.add('graphic_rendering');
  }
  return [...required].sort(asciiCompare);
}

function forbiddenActions(profileName) {
  const actions = new Set(GLOBAL_FORBIDDEN_ACTIONS);
  addAll(actions, PROFILE_SPECS[profileName].forbidden_actions);
  return [...actions].sort(asciiCompare);
}

function qaChecks(profileName, resolved) {
  const spec = PROFILE_SPECS[profileName];
  const checks = new Set(GLOBAL_QA_CHECKS);
  addAll(checks, spec.qa_checks);
  if (resolved.dialogue_rule !== 'none') {
    addAll(checks, ['dialogue_intelligibility_verified', 'dialogue_sync_verified']);
  }
  if (resolved.caption_rule !== 'forbidden') {
    addAll(checks, [
      'caption_safe_area_and_contrast_verified',
      'caption_text_and_timing_verified',
    ]);
  }
  if (resolved.music_rule === 'supporting') {
    addAll(checks, [
      'dialogue_music_masking_verified',
      'project_generated_music_rights_verified',
    ]);
  } else if (resolved.music_rule === 'primary') {
    addAll(checks, ['dialogue_ducking_verified', 'music_license_receipt_verified']);
  } else if (resolved.music_rule === 'source_primary') {
    checks.add('source_music_integrity_verified');
  }
  if (resolved.sfx_density !== 'none' && spec.sfx_usage !== 'source_only') {
    addAll(checks, [
      'sfx_generation_and_rights_receipt_verified',
      'sfx_motivation_and_masking_verified',
    ]);
  }
  if (resolved.transition_density !== 'none') {
    addAll(checks, [
      'transition_audio_continuity_verified', 'transition_motivation_verified',
    ]);
  }
  if (resolved.visualization_rule !== 'forbidden') {
    addAll(checks, [
      'visualization_data_provenance_verified',
      'visualization_legibility_verified',
    ]);
  }
  return [...checks].sort(asciiCompare);
}

function makeRules(profileName, resolved) {
  const spec = PROFILE_SPECS[profileName];
  const musicUsage = resolved.music_rule;
  const dialoguePriority = resolved.dialogue_rule;
  return {
    cuts: {
      density: resolved.cut_density,
      motivation: spec.cut_motivation,
      j_l_cuts: spec.j_l_cuts,
    },
    sfx: { density: resolved.sfx_density, usage: spec.sfx_usage },
    transitions: {
      density: resolved.transition_density,
      usage: spec.transition_usage,
    },
    dialogue: { priority: dialoguePriority, preserve_meaning: true },
    music: {
      usage: musicUsage,
      duck_under_dialogue: (
        new Set(['supporting', 'primary']).has(musicUsage) &&
        dialoguePriority !== 'none'
      ),
    },
    captions: {
      usage: resolved.caption_rule,
      safe_area_required: true,
      max_lines: 2,
    },
    visualizations: {
      usage: resolved.visualization_rule,
      evidence_required: true,
    },
  };
}

function resolveEditPolicy(request) {
  const raw = exactKeys(request, REQUEST_KEYS, 'edit policy request');
  if (raw.schema_version !== EDIT_POLICY_REQUEST_SCHEMA_VERSION) {
    fail('edit policy request schema_version is unsupported');
  }
  const profileName = enumValue(raw.profile, PROFILE_NAME_SET, 'profile');
  const durationMs = integer(raw.duration_ms, 'duration_ms', 1, MAX_DURATION_MS);

  const delivery = exactKeys(raw.delivery, DELIVERY_KEYS, 'delivery');
  const platformName = enumValue(delivery.platform, PLATFORM_SET, 'delivery.platform');
  let requestedAspect = delivery.aspect;
  if (requestedAspect !== 'auto') {
    requestedAspect = enumValue(requestedAspect, ASPECT_SET, 'delivery.aspect');
  }
  const platformSpec = PLATFORM_SPECS[platformName];
  const aspect = requestedAspect === 'auto'
    ? platformSpec.default_aspect
    : requestedAspect;
  if (!platformSpec.allowed_aspects.includes(aspect)) {
    fail(`delivery.aspect ${aspect} is incompatible with ${platformName}`);
  }

  const explicit = parsePolicyValues(raw.explicit_intent, 'explicit_intent');
  const preferences = exactKeys(
    raw.consented_preferences,
    PREFERENCES_KEYS,
    'consented_preferences',
  );
  const consented = booleanValue(
    preferences.consented,
    'consented_preferences.consented',
  );
  const preferenceValues = parsePolicyValues(
    preferences.values,
    'consented_preferences.values',
  );
  if (!consented && POLICY_FIELDS.some((field) => preferenceValues[field] !== null)) {
    fail('unconsented preference values must all be auto');
  }

  const available = sortedKnownList(
    raw.available_capabilities,
    CAPABILITY_SET,
    'available_capabilities',
  );

  const resolved = {};
  const sources = {};
  overlay(resolved, sources, BASELINE, 'baseline');
  if (consented) {
    overlay(resolved, sources, preferenceValues, 'consented_preferences');
  }
  const chosenDuration = durationSpec(durationMs);
  overlay(resolved, sources, chosenDuration.overrides, 'duration');
  overlay(resolved, sources, PROFILE_SPECS[profileName].values, 'profile');
  overlay(resolved, sources, platformSpec.overrides, 'platform');
  overlay(resolved, sources, explicit, 'explicit_intent');
  applyHardInvariants(profileName, resolved, sources);

  const required = requiredCapabilities(profileName, resolved);
  const availableSet = new Set(available);
  const missing = required.filter((capability) => !availableSet.has(capability));
  if (missing.length) {
    fail(`capability gate failed; missing: ${missing.join(', ')}`);
  }

  sources.aspect = requestedAspect === 'auto' ? 'platform' : 'explicit_intent';
  return validateEditPolicy({
    schema_version: EDIT_POLICY_SCHEMA_VERSION,
    profile: profileName,
    duration: { duration_ms: durationMs, band: chosenDuration.name },
    delivery: { platform: platformName, aspect },
    rules: makeRules(profileName, resolved),
    resolution_sources: sources,
    required_capabilities: required,
    forbidden_actions: forbiddenActions(profileName),
    qa_checks: qaChecks(profileName, resolved),
  });
}

function validateSortedExactList(value, expected, label) {
  if (!isDenseArray(value) || value.length !== expected.length ||
      value.some((item, index) => typeof item !== 'string' || item !== expected[index])) {
    fail(`${label} must exactly equal its sorted derived contract`);
  }
  return [...value];
}

function validateEditPolicy(policy) {
  const raw = exactKeys(policy, POLICY_KEYS, 'edit policy');
  if (raw.schema_version !== EDIT_POLICY_SCHEMA_VERSION) {
    fail('edit policy schema_version is unsupported');
  }
  const profileName = enumValue(raw.profile, PROFILE_NAME_SET, 'profile');
  const spec = PROFILE_SPECS[profileName];

  const duration = exactKeys(raw.duration, DURATION_KEYS, 'duration');
  const durationMs = integer(
    duration.duration_ms, 'duration.duration_ms', 1, MAX_DURATION_MS,
  );
  const band = enumValue(duration.band, DURATION_BAND_SET, 'duration.band');
  if (band !== durationBand(durationMs)) {
    fail('duration.band does not match duration.duration_ms');
  }

  const delivery = exactKeys(raw.delivery, DELIVERY_KEYS, 'delivery');
  const platformName = enumValue(delivery.platform, PLATFORM_SET, 'delivery.platform');
  const aspect = enumValue(delivery.aspect, ASPECT_SET, 'delivery.aspect');
  if (!PLATFORM_SPECS[platformName].allowed_aspects.includes(aspect)) {
    fail('delivery aspect is incompatible with its platform');
  }

  const rules = exactKeys(raw.rules, RULE_KEYS, 'rules');
  const cuts = exactKeys(rules.cuts, CUT_KEYS, 'rules.cuts');
  const cutDensity = enumValue(cuts.density, CUT_DENSITY_SET, 'rules.cuts.density');
  if (enumValue(
    cuts.motivation, CUT_MOTIVATION_SET, 'rules.cuts.motivation',
  ) !== spec.cut_motivation) {
    fail('rules.cuts.motivation does not match profile');
  }
  if (enumValue(cuts.j_l_cuts, JL_CUT_RULE_SET, 'rules.cuts.j_l_cuts') !==
      spec.j_l_cuts) {
    fail('rules.cuts.j_l_cuts does not match profile');
  }

  const sfx = exactKeys(rules.sfx, SFX_KEYS, 'rules.sfx');
  const sfxDensity = enumValue(sfx.density, EFFECT_DENSITY_SET, 'rules.sfx.density');
  if (enumValue(sfx.usage, SFX_USAGE_RULE_SET, 'rules.sfx.usage') !==
      spec.sfx_usage) {
    fail('rules.sfx.usage does not match profile');
  }

  const transitions = exactKeys(
    rules.transitions, TRANSITION_KEYS, 'rules.transitions',
  );
  const transitionDensity = enumValue(
    transitions.density, EFFECT_DENSITY_SET, 'rules.transitions.density',
  );
  if (enumValue(
    transitions.usage,
    TRANSITION_USAGE_RULE_SET,
    'rules.transitions.usage',
  ) !== spec.transition_usage) {
    fail('rules.transitions.usage does not match profile');
  }

  const dialogue = exactKeys(rules.dialogue, DIALOGUE_KEYS, 'rules.dialogue');
  const dialogueRule = enumValue(
    dialogue.priority, DIALOGUE_RULE_SET, 'rules.dialogue.priority',
  );
  if (booleanValue(
    dialogue.preserve_meaning, 'rules.dialogue.preserve_meaning',
  ) !== true) {
    fail('rules.dialogue.preserve_meaning is a hard invariant');
  }

  const music = exactKeys(rules.music, MUSIC_KEYS, 'rules.music');
  const musicRule = enumValue(music.usage, MUSIC_RULE_SET, 'rules.music.usage');
  const expectedDuck = new Set(['supporting', 'primary']).has(musicRule) &&
    dialogueRule !== 'none';
  if (booleanValue(
    music.duck_under_dialogue, 'rules.music.duck_under_dialogue',
  ) !== expectedDuck) {
    fail('rules.music.duck_under_dialogue is inconsistent');
  }

  const captions = exactKeys(rules.captions, CAPTION_KEYS, 'rules.captions');
  const captionRule = enumValue(
    captions.usage, CAPTION_RULE_SET, 'rules.captions.usage',
  );
  if (booleanValue(
    captions.safe_area_required, 'rules.captions.safe_area_required',
  ) !== true) {
    fail('rules.captions.safe_area_required is a hard invariant');
  }
  if (integer(captions.max_lines, 'rules.captions.max_lines', 1, 2) !== 2) {
    fail('rules.captions.max_lines must be 2 in v1');
  }

  const visualizations = exactKeys(
    rules.visualizations, VISUALIZATION_KEYS, 'rules.visualizations',
  );
  const visualizationRule = enumValue(
    visualizations.usage,
    VISUALIZATION_RULE_SET,
    'rules.visualizations.usage',
  );
  if (booleanValue(
    visualizations.evidence_required,
    'rules.visualizations.evidence_required',
  ) !== true) {
    fail('rules.visualizations.evidence_required is a hard invariant');
  }

  const resolved = {
    cut_density: cutDensity,
    sfx_density: sfxDensity,
    transition_density: transitionDensity,
    dialogue_rule: dialogueRule,
    music_rule: musicRule,
    caption_rule: captionRule,
    visualization_rule: visualizationRule,
  };
  const invariantProbe = { ...resolved };
  const invariantSources = Object.fromEntries(
    POLICY_FIELDS.map((field) => [field, 'profile']),
  );
  applyHardInvariants(profileName, invariantProbe, invariantSources);
  if (POLICY_FIELDS.some((field) => invariantProbe[field] !== resolved[field])) {
    fail('resolved rules violate a profile hard invariant');
  }

  const resolutionKeys = [...POLICY_FIELDS, 'aspect'].sort(asciiCompare);
  const resolutionSources = exactKeys(
    raw.resolution_sources, resolutionKeys, 'resolution_sources',
  );
  const normalizedSources = {};
  for (const [key, value] of Object.entries(resolutionSources)) {
    normalizedSources[key] = enumValue(
      value, RESOLUTION_SOURCE_SET, `resolution_sources.${key}`,
    );
  }
  for (const field of Object.keys(HARD_EXACT[profileName] || {})) {
    if (normalizedSources[field] !== 'hard_invariant') {
      fail(`resolution_sources.${field} must record its hard invariant`);
    }
  }

  const required = requiredCapabilities(profileName, resolved);
  validateSortedExactList(raw.required_capabilities, required, 'required_capabilities');
  const forbidden = forbiddenActions(profileName);
  validateSortedExactList(raw.forbidden_actions, forbidden, 'forbidden_actions');
  const checks = qaChecks(profileName, resolved);
  validateSortedExactList(raw.qa_checks, checks, 'qa_checks');

  return {
    schema_version: EDIT_POLICY_SCHEMA_VERSION,
    profile: profileName,
    duration: { duration_ms: durationMs, band },
    delivery: { platform: platformName, aspect },
    rules: {
      cuts: {
        density: cutDensity,
        motivation: spec.cut_motivation,
        j_l_cuts: spec.j_l_cuts,
      },
      sfx: { density: sfxDensity, usage: spec.sfx_usage },
      transitions: {
        density: transitionDensity,
        usage: spec.transition_usage,
      },
      dialogue: { priority: dialogueRule, preserve_meaning: true },
      music: { usage: musicRule, duck_under_dialogue: expectedDuck },
      captions: {
        usage: captionRule,
        safe_area_required: true,
        max_lines: 2,
      },
      visualizations: {
        usage: visualizationRule,
        evidence_required: true,
      },
    },
    resolution_sources: normalizedSources,
    required_capabilities: required,
    forbidden_actions: forbidden,
    qa_checks: checks,
  };
}

function pythonString(value) {
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

function canonicalJsonData(value, label) {
  function serialize(item) {
    if (item === null) return 'null';
    if (item === true) return 'true';
    if (item === false) return 'false';
    if (typeof item === 'string') return pythonString(item);
    if (typeof item === 'number' && Number.isSafeInteger(item)) return String(item);
    if (isDenseArray(item)) return `[${item.map(serialize).join(',')}]`;
    if (isPlainObject(item)) {
      const keys = Object.keys(item).sort(asciiCompare);
      return `{${keys.map((key) => (
        `${pythonString(key)}:${serialize(item[key])}`
      )).join(',')}}`;
    }
    fail(`${label} is not canonical JSON`);
  }
  return serialize(value);
}

function canonicalEditPolicyJson(policy) {
  return canonicalJsonData(validateEditPolicy(policy), 'edit policy');
}

function editPolicySha256(policy) {
  return crypto.createHash('sha256')
    .update(canonicalEditPolicyJson(policy), 'utf8')
    .digest('hex');
}

module.exports = Object.freeze({
  EDIT_POLICY_REQUEST_SCHEMA_VERSION,
  EDIT_POLICY_SCHEMA_VERSION,
  MAX_DURATION_MS,
  CUT_DENSITIES,
  EFFECT_DENSITIES,
  DIALOGUE_RULES,
  MUSIC_RULES,
  CAPTION_RULES,
  VISUALIZATION_RULES,
  PLATFORMS,
  ASPECTS,
  CAPABILITIES,
  PROFILE_NAMES,
  DURATION_BANDS,
  EditPolicyError,
  durationBand,
  resolveEditPolicy,
  validateEditPolicy,
  canonicalEditPolicyJson,
  editPolicySha256,
});
