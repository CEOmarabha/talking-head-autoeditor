'use strict';

// Trusted desktop bridge from bounded DeepSeek transition decisions to the
// closed transition-plan contract. Model output supplies enums, frame-aligned
// durations, and explicit safety verdicts only. All ids, source hashes,
// cumulative boundaries, policy hashes, and manifest hashes are derived here.

const {
  CAPABILITIES,
  editPolicySha256,
} = require('./edit-policy');
const {
  CAPABILITY_MANIFEST_SCHEMA_VERSION,
  CAPABILITY_MANIFEST_SOURCE,
  resolveProjectIntentPolicy,
} = require('./project-intent-policy-bridge');
const { validateProjectIntent } = require('./project-intent');
const { compileSequencePlan } = require('./sequence-plan');
const {
  TRANSITION_PLAN_SCHEMA_VERSION,
  TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
  deriveBoundaryId,
  transitionSequenceManifestSha256,
  validateTransitionPlan,
  validateTransitionSequenceManifest,
} = require('./transition-plan');

const TRANSITION_DECISION_SCHEMA_VERSION =
  'autoeditor-transition-decisions/v1';
const TYPED_TRANSITION_PREFERENCES = new Set([
  'beat_or_phrase_motivated',
  'continuity_motivated',
  'location_motivated',
  'motivated_only',
]);
const DECISION_PLAN_KEYS = Object.freeze(['boundaries', 'schema_version']);
const DECISION_KEYS = Object.freeze([
  'boundary_index',
  'dialogue_preservation_verified',
  'duration_ms',
  'kind',
  'motivation_verified',
  'semantic_safety_verified',
]);
const DECISION_KINDS = new Set([
  'cross_dissolve', 'dip_to_black', 'hard_cut',
]);

function asciiCompare(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exactKeys(value, expected, label) {
  if (!isPlainObject(value)) throw new Error(`${label} must be an object`);
  const actual = Object.keys(value).sort(asciiCompare);
  if (actual.length !== expected.length ||
      actual.some((key, index) => key !== expected[index])) {
    throw new Error(`${label} has invalid keys`);
  }
  return value;
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function transitionIntent(projectIntent) {
  const project = validateProjectIntent(projectIntent);
  const preference = project.preferences.transitions;
  if (preference.enabled !== true ||
      !TYPED_TRANSITION_PREFERENCES.has(preference.preference)) {
    throw new Error(
      'timed transitions require an explicit non-hard-cut projectIntent preference',
    );
  }
  return project;
}

function planningPolicy(projectIntent) {
  // Availability does not alter policy rules; it only gates them. Resolve
  // against the complete declared capability vocabulary so the proposal can
  // be closed now, then re-run against the measured runtime manifest at apply.
  return resolveProjectIntentPolicy(projectIntent, {
    schema_version: CAPABILITY_MANIFEST_SCHEMA_VERSION,
    source: CAPABILITY_MANIFEST_SOURCE,
    probe_receipt_sha256: '0'.repeat(64),
    available_capabilities: [...CAPABILITIES].sort(asciiCompare),
  });
}

function transitionManifestForSequence(sequencePlan, sourceManifest, catalog) {
  const compiled = compileSequencePlan(sequencePlan, sourceManifest);
  if (!catalog || catalog.schema_version !== 'autoeditor-source-catalog/v1' ||
      !Array.isArray(catalog.sources)) {
    throw new Error('transition planning requires the complete private source catalog');
  }
  const sources = new Map(catalog.sources.map((source) => [source.source_id, source]));
  const segments = compiled.ffmpeg_segments.map((segment) => {
    const source = sources.get(segment.source_id);
    if (!source || source.sha256 !== segment.source_sha256) {
      throw new Error('transition sequence does not bind the private source catalog');
    }
    const videoStart = source.timeline?.video_start_offset_ms;
    const audioStart = source.timeline?.audio_start_offset_ms;
    if (!Number.isSafeInteger(videoStart) ||
        segment.source_start_ms < videoStart) {
      throw new Error('transition segment begins before decoded video evidence');
    }
    let selectedAudioMs = 0;
    let audioLeadingHandleMs = 0;
    let audioTrailingHandleMs = 0;
    if (audioStart !== null) {
      if (!Number.isSafeInteger(audioStart)) {
        throw new Error('transition source has incomplete audio timing evidence');
      }
      const overlapStart = Math.max(segment.source_start_ms, audioStart);
      if (overlapStart < segment.source_end_ms) {
        selectedAudioMs = segment.source_end_ms - overlapStart;
        audioLeadingHandleMs = overlapStart === segment.source_start_ms
          ? selectedAudioMs : 0;
        // The local analysis has an exact stream start but only a container
        // end. The daemon reconstructs the decoded end and requires equality;
        // an early-ending audio stream therefore fails closed before render.
        audioTrailingHandleMs = selectedAudioMs;
      }
    }
    return {
      segment_id: segment.segment_id,
      source_sha256: segment.source_sha256,
      duration_ms: segment.duration_ms,
      video_leading_handle_ms: segment.duration_ms,
      video_trailing_handle_ms: segment.duration_ms,
      audio_leading_handle_ms: audioLeadingHandleMs,
      audio_trailing_handle_ms: audioTrailingHandleMs,
      dialogue_at_start: audioLeadingHandleMs > 0,
      dialogue_at_end: audioTrailingHandleMs > 0,
    };
  });
  return validateTransitionSequenceManifest({
    schema_version: TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
    sequence_plan_sha256: compiled.receipt.sequence_plan_sha256,
    sequence_compile_receipt_sha256: compiled.receipt_sha256,
    frame_rate: { numerator: 30, denominator: 1 },
    segments,
  });
}

function normalizeDecisions(raw, boundaryCount) {
  const value = exactKeys(raw, DECISION_PLAN_KEYS, 'transition decisions');
  if (value.schema_version !== TRANSITION_DECISION_SCHEMA_VERSION ||
      !Array.isArray(value.boundaries) ||
      value.boundaries.length !== boundaryCount) {
    throw new Error('transition decisions must decide every exact boundary');
  }
  let nonHardCount = 0;
  const decisions = value.boundaries.map((item, index) => {
    const decision = exactKeys(item, DECISION_KEYS,
      `transition decisions.boundaries[${index}]`);
    if (decision.boundary_index !== index ||
        !DECISION_KINDS.has(decision.kind) ||
        !Number.isSafeInteger(decision.duration_ms) ||
        decision.duration_ms < 0 || decision.duration_ms > 1_000 ||
        typeof decision.motivation_verified !== 'boolean' ||
        typeof decision.semantic_safety_verified !== 'boolean' ||
        typeof decision.dialogue_preservation_verified !== 'boolean') {
      throw new Error(`transition decision ${index} is malformed`);
    }
    if (decision.kind === 'hard_cut') {
      if (decision.duration_ms !== 0) {
        throw new Error(`hard-cut decision ${index} must have zero duration`);
      }
    } else {
      nonHardCount += 1;
      if (!decision.motivation_verified || decision.duration_ms === 0) {
        throw new Error(`timed transition decision ${index} lacks motivation`);
      }
    }
    if (!decision.semantic_safety_verified ||
        !decision.dialogue_preservation_verified) {
      throw new Error(`transition decision ${index} lacks safety verification`);
    }
    return { ...decision };
  });
  if (nonHardCount === 0) {
    throw new Error('a timed-transition overlay must contain a non-hard cut');
  }
  return decisions;
}

function buildTransitionCarrier({
  sequencePlan, sourceManifest, privateCatalog, projectIntent, decisions,
}) {
  const project = transitionIntent(projectIntent);
  if (sequencePlan.target_duration.min_ms < project.target_duration.min_ms ||
      sequencePlan.target_duration.max_ms > project.target_duration.max_ms) {
    throw new Error('transition sequence duration exceeds projectIntent bounds');
  }
  const manifest = transitionManifestForSequence(
    sequencePlan, sourceManifest, privateCatalog,
  );
  const policy = planningPolicy(project);
  const normalized = normalizeDecisions(decisions, manifest.segments.length - 1);
  let cumulativeMs = 0;
  const boundaries = normalized.map((decision, index) => {
    const left = manifest.segments[index];
    const right = manifest.segments[index + 1];
    cumulativeMs += left.duration_ms;
    return {
      boundary_id: deriveBoundaryId(
        left.segment_id, right.segment_id,
        left.source_sha256, right.source_sha256, cumulativeMs,
      ),
      left_segment_id: left.segment_id,
      right_segment_id: right.segment_id,
      left_source_sha256: left.source_sha256,
      right_source_sha256: right.source_sha256,
      cumulative_boundary_ms: cumulativeMs,
      kind: decision.kind,
      motivation: policy.rules.transitions.usage,
      duration_ms: decision.duration_ms,
      audio_behavior: decision.kind === 'hard_cut'
        ? 'hard_cut' : 'equal_power_crossfade',
      motivation_verified: decision.motivation_verified,
      semantic_safety_verified: decision.semantic_safety_verified,
      dialogue_preservation_verified: decision.dialogue_preservation_verified,
    };
  });
  const plan = validateTransitionPlan({
    schema_version: TRANSITION_PLAN_SCHEMA_VERSION,
    sequence_manifest_sha256: transitionSequenceManifestSha256(manifest),
    edit_policy_sha256: editPolicySha256(policy),
    frame_rate: { numerator: 30, denominator: 1 },
    policy: { ...policy.rules.transitions },
    boundaries,
  }, manifest, policy);
  return { transitionPlan: plan, transitionSequenceManifest: manifest };
}

function validateTransitionCarrier(proposal, editPolicy = null) {
  const hasPlan = Object.prototype.hasOwnProperty.call(proposal, 'transitionPlan');
  const hasManifest = Object.prototype.hasOwnProperty.call(
    proposal, 'transitionSequenceManifest');
  if (hasPlan !== hasManifest) {
    throw new Error('transition plan and sequence manifest must be supplied together');
  }
  if (!hasPlan) return null;
  if (!Object.prototype.hasOwnProperty.call(proposal, 'sequencePlan') ||
      !Object.prototype.hasOwnProperty.call(proposal, 'sequenceSourceManifest') ||
      !Object.prototype.hasOwnProperty.call(proposal, 'projectIntent')) {
    throw new Error(
      'timed transitions require an exact sequence and projectIntent authority',
    );
  }
  const project = transitionIntent(proposal.projectIntent);
  const compiled = compileSequencePlan(
    proposal.sequencePlan, proposal.sequenceSourceManifest,
  );
  const manifest = validateTransitionSequenceManifest(
    proposal.transitionSequenceManifest,
  );
  const expectedSegments = compiled.ffmpeg_segments.map((item) => [
    item.segment_id, item.source_sha256, item.duration_ms,
  ]);
  const manifestSegments = manifest.segments.map((item) => [
    item.segment_id, item.source_sha256, item.duration_ms,
  ]);
  if (manifest.sequence_plan_sha256 !== compiled.receipt.sequence_plan_sha256 ||
      manifest.sequence_compile_receipt_sha256 !== compiled.receipt_sha256 ||
      !sameJson(manifest.frame_rate, { numerator: 30, denominator: 1 }) ||
      !sameJson(manifestSegments, expectedSegments)) {
    throw new Error('transition manifest does not bind the exact sequence');
  }
  if (proposal.sequencePlan.target_duration.min_ms < project.target_duration.min_ms ||
      proposal.sequencePlan.target_duration.max_ms > project.target_duration.max_ms) {
    throw new Error('transition sequence duration exceeds projectIntent bounds');
  }
  const policy = editPolicy || planningPolicy(project);
  const plan = validateTransitionPlan(
    proposal.transitionPlan, manifest, policy,
  );
  if (!plan.boundaries.some((item) => item.kind !== 'hard_cut')) {
    throw new Error('a timed-transition carrier must contain a non-hard cut');
  }
  return { transitionPlan: plan, transitionSequenceManifest: manifest };
}

module.exports = Object.freeze({
  TRANSITION_DECISION_SCHEMA_VERSION,
  TYPED_TRANSITION_PREFERENCES: Object.freeze(
    [...TYPED_TRANSITION_PREFERENCES].sort(asciiCompare)),
  planningPolicy,
  transitionManifestForSequence,
  buildTransitionCarrier,
  validateTransitionCarrier,
});
