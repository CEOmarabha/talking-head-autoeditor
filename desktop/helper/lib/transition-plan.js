'use strict';

// Strict JavaScript mirror of autoeditor/transition_plan.py. This module is
// intentionally an inert contract/compiler: it validates trusted sequence
// facts and emits constant-shape FFmpeg primitive tokens, but never resolves
// media paths, attaches stream labels, composes a filter graph, or executes a
// process. Frozen Python vectors in desktop/tests/transition-plan.test.js
// detect cross-runtime schema, canonicalization, and hash drift.

const crypto = require('node:crypto');

const {
  EditPolicyError,
  editPolicySha256,
  validateEditPolicy,
} = require('./edit-policy');

const TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION =
  'autoeditor-transition-sequence-manifest/v1';
const TRANSITION_PLAN_SCHEMA_VERSION = 'autoeditor-transition-plan/v1';
const TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION =
  'autoeditor-transition-compile-receipt/v1';

const MAX_SEGMENTS = 256;
const MAX_TRANSITION_DURATION_MS = 1_000;
const MIN_TRANSITION_FRAMES = 2;
const MIN_DIP_TO_BLACK_FRAMES = 4;
const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;

const TRANSITION_KINDS = Object.freeze([
  'cross_dissolve', 'dip_to_black', 'hard_cut',
]);
const MOTIVATIONS = Object.freeze([
  'beat_or_phrase_motivated',
  'continuity_motivated',
  'location_motivated',
  'motivated_only',
]);
const AUDIO_BEHAVIORS = Object.freeze(['equal_power_crossfade', 'hard_cut']);
const POLICY_DENSITIES = Object.freeze(['dense', 'medium', 'none', 'sparse']);
const POLICY_USAGES = Object.freeze([
  'beat_or_phrase_motivated',
  'continuity_motivated',
  'hard_cut_only',
  'location_motivated',
  'motivated_only',
]);

const TRANSITION_KIND_SET = new Set(TRANSITION_KINDS);
const MOTIVATION_SET = new Set(MOTIVATIONS);
const AUDIO_BEHAVIOR_SET = new Set(AUDIO_BEHAVIORS);
const POLICY_DENSITY_SET = new Set(POLICY_DENSITIES);
const POLICY_USAGE_SET = new Set(POLICY_USAGES);

// Every key list is ASCII-sorted so exactKeys can compare without mutating the
// contract constants and schema "required" arrays match Python's sorted(...).
const MANIFEST_KEYS = Object.freeze([
  'frame_rate',
  'schema_version',
  'segments',
  'sequence_compile_receipt_sha256',
  'sequence_plan_sha256',
]);
const MANIFEST_SEGMENT_KEYS = Object.freeze([
  'audio_leading_handle_ms',
  'audio_trailing_handle_ms',
  'dialogue_at_end',
  'dialogue_at_start',
  'duration_ms',
  'segment_id',
  'source_sha256',
  'video_leading_handle_ms',
  'video_trailing_handle_ms',
]);
const FRAME_RATE_KEYS = Object.freeze(['denominator', 'numerator']);
const PLAN_KEYS = Object.freeze([
  'boundaries',
  'edit_policy_sha256',
  'frame_rate',
  'policy',
  'schema_version',
  'sequence_manifest_sha256',
]);
const POLICY_KEYS = Object.freeze(['density', 'usage']);
const BOUNDARY_KEYS = Object.freeze([
  'audio_behavior',
  'boundary_id',
  'cumulative_boundary_ms',
  'dialogue_preservation_verified',
  'duration_ms',
  'kind',
  'left_segment_id',
  'left_source_sha256',
  'motivation',
  'motivation_verified',
  'right_segment_id',
  'right_source_sha256',
  'semantic_safety_verified',
]);
const RECEIPT_KEYS = Object.freeze([
  'boundary_count',
  'compiled_boundaries_sha256',
  'edit_policy_sha256',
  'frame_rate',
  'non_hard_transition_count',
  'ordered_boundary_ids',
  'output_duration_ms',
  'policy',
  'schema_version',
  'sequence_compile_receipt_sha256',
  'sequence_manifest_sha256',
  'sequence_plan_sha256',
  'source_duration_ms',
  'time_base',
  'transition_plan_sha256',
]);
const TIME_BASE_KEYS = Object.freeze(['denominator', 'numerator']);

const SEGMENT_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/;
const BOUNDARY_ID = /^boundary-[0-9a-f]{64}$/;
const SHA256 = /^[0-9a-f]{64}$/;

function frameRateJsonSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: [...FRAME_RATE_KEYS],
    properties: {
      numerator: { type: 'integer', minimum: 1, maximum: 240_000 },
      denominator: { type: 'integer', minimum: 1, maximum: 10_000 },
    },
  };
}

const TRANSITION_PLAN_JSON_SCHEMA = Object.freeze({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  additionalProperties: false,
  required: [...PLAN_KEYS],
  properties: {
    schema_version: { const: TRANSITION_PLAN_SCHEMA_VERSION },
    sequence_manifest_sha256: { type: 'string', pattern: SHA256.source },
    edit_policy_sha256: { type: 'string', pattern: SHA256.source },
    frame_rate: frameRateJsonSchema(),
    policy: {
      type: 'object',
      additionalProperties: false,
      required: [...POLICY_KEYS],
      properties: {
        density: { type: 'string', enum: [...POLICY_DENSITIES] },
        usage: { type: 'string', enum: [...POLICY_USAGES] },
      },
    },
    boundaries: {
      type: 'array',
      minItems: 0,
      maxItems: MAX_SEGMENTS - 1,
      items: {
        type: 'object',
        additionalProperties: false,
        required: [...BOUNDARY_KEYS],
        properties: {
          boundary_id: { type: 'string', pattern: BOUNDARY_ID.source },
          left_segment_id: { type: 'string', pattern: SEGMENT_ID.source },
          right_segment_id: { type: 'string', pattern: SEGMENT_ID.source },
          left_source_sha256: { type: 'string', pattern: SHA256.source },
          right_source_sha256: { type: 'string', pattern: SHA256.source },
          cumulative_boundary_ms: {
            type: 'integer', minimum: 1, maximum: MAX_SAFE_INTEGER,
          },
          kind: { type: 'string', enum: [...TRANSITION_KINDS] },
          motivation: { type: 'string', enum: [...MOTIVATIONS] },
          duration_ms: {
            type: 'integer', minimum: 0, maximum: MAX_TRANSITION_DURATION_MS,
          },
          audio_behavior: { type: 'string', enum: [...AUDIO_BEHAVIORS] },
          motivation_verified: { type: 'boolean' },
          semantic_safety_verified: { type: 'boolean' },
          dialogue_preservation_verified: { type: 'boolean' },
        },
      },
    },
  },
});

class TransitionPlanError extends Error {
  constructor(message) {
    super(message);
    this.name = 'TransitionPlanError';
  }
}

function fail(message) {
  throw new TransitionPlanError(message);
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
    if (extra.length) details.push(`unknown ${extra.join(', ')}`);
    fail(`${label} has invalid keys (${details.join('; ')})`);
  }
  return value;
}

function integer(value, label, { minimum = 0, maximum = MAX_SAFE_INTEGER } = {}) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function booleanValue(value, label) {
  if (typeof value !== 'boolean') fail(`${label} must be a boolean`);
  return value;
}

function enumValue(value, allowed, label) {
  if (typeof value !== 'string' || !allowed.has(value)) {
    fail(`${label} is unsupported`);
  }
  return value;
}

function identifier(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} has an invalid ASCII identifier`);
  }
  return value;
}

function sha256DigestValue(value, label) {
  if (typeof value !== 'string' || !SHA256.test(value)) {
    fail(`${label} must be a full lowercase SHA-256 digest`);
  }
  return value;
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

function digestCanonical(canonical) {
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

function detach(value) {
  if (Array.isArray(value)) return value.map(detach);
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, detach(item)]));
  }
  return value;
}

function gcd(left, right) {
  let a = left;
  let b = right;
  while (b !== 0) {
    const remainder = a % b;
    a = b;
    b = remainder;
  }
  return a;
}

function normalizeFrameRate(value, label) {
  const raw = exactKeys(value, FRAME_RATE_KEYS, label);
  const numerator = integer(raw.numerator, `${label}.numerator`, {
    minimum: 1,
    maximum: 240_000,
  });
  const denominator = integer(raw.denominator, `${label}.denominator`, {
    minimum: 1,
    maximum: 10_000,
  });
  if (gcd(numerator, denominator) !== 1) {
    fail(`${label} must be a reduced rational`);
  }
  if (numerator < denominator || numerator > 240 * denominator) {
    fail(`${label} must be from 1 to 240 frames per second`);
  }
  return { numerator, denominator };
}

function roundPositiveRatio(numerator, denominator) {
  const n = BigInt(numerator);
  const d = BigInt(denominator);
  return Number(((2n * n) + d) / (2n * d));
}

function durationFrames(durationMs, frameRate) {
  return roundPositiveRatio(
    BigInt(durationMs) * BigInt(frameRate.numerator),
    1_000n * BigInt(frameRate.denominator),
  );
}

function canonicalFrameDurationMs(frames, frameRate) {
  return roundPositiveRatio(
    BigInt(frames) * 1_000n * BigInt(frameRate.denominator),
    BigInt(frameRate.numerator),
  );
}

function minimumFrameMs(frameRate) {
  const numerator = 1_000n * BigInt(frameRate.denominator);
  const denominator = BigInt(frameRate.numerator);
  return Number((numerator + denominator - 1n) / denominator);
}

function ffmpegSeconds(milliseconds) {
  return `${Math.floor(milliseconds / 1_000)}.${String(milliseconds % 1_000).padStart(3, '0')}`;
}

function normalizePolicy(value, label) {
  const raw = exactKeys(value, POLICY_KEYS, label);
  return {
    density: enumValue(raw.density, POLICY_DENSITY_SET, `${label}.density`),
    usage: enumValue(raw.usage, POLICY_USAGE_SET, `${label}.usage`),
  };
}

function validateTransitionSequenceManifest(manifest) {
  const raw = exactKeys(
    manifest,
    MANIFEST_KEYS,
    'transition sequence manifest',
  );
  if (raw.schema_version !== TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION) {
    fail('transition sequence manifest schema_version is unsupported');
  }
  const planHash = sha256DigestValue(
    raw.sequence_plan_sha256,
    'transition sequence manifest.sequence_plan_sha256',
  );
  const receiptHash = sha256DigestValue(
    raw.sequence_compile_receipt_sha256,
    'transition sequence manifest.sequence_compile_receipt_sha256',
  );
  const frameRate = normalizeFrameRate(
    raw.frame_rate,
    'transition sequence manifest.frame_rate',
  );
  if (!isDenseArray(raw.segments) ||
      raw.segments.length < 1 || raw.segments.length > MAX_SEGMENTS) {
    fail(`transition sequence manifest.segments must contain 1-${MAX_SEGMENTS} entries`);
  }

  const segments = [];
  const seenIds = new Set();
  let totalDuration = 0;
  raw.segments.forEach((rawSegment, index) => {
    const label = `transition sequence manifest.segments[${index}]`;
    const item = exactKeys(rawSegment, MANIFEST_SEGMENT_KEYS, label);
    const segmentId = identifier(item.segment_id, SEGMENT_ID, `${label}.segment_id`);
    if (seenIds.has(segmentId)) fail(`${label}.segment_id must be unique`);
    seenIds.add(segmentId);
    const sourceHash = sha256DigestValue(item.source_sha256, `${label}.source_sha256`);
    const duration = integer(item.duration_ms, `${label}.duration_ms`, { minimum: 1 });
    const handles = {};
    for (const key of [
      'video_leading_handle_ms',
      'video_trailing_handle_ms',
      'audio_leading_handle_ms',
      'audio_trailing_handle_ms',
    ]) {
      handles[key] = integer(item[key], `${label}.${key}`, { maximum: duration });
    }
    if (duration > MAX_SAFE_INTEGER - totalDuration) {
      fail('transition sequence duration exceeds exact JSON integer range');
    }
    totalDuration += duration;
    segments.push({
      segment_id: segmentId,
      source_sha256: sourceHash,
      duration_ms: duration,
      ...handles,
      dialogue_at_start: booleanValue(
        item.dialogue_at_start,
        `${label}.dialogue_at_start`,
      ),
      dialogue_at_end: booleanValue(item.dialogue_at_end, `${label}.dialogue_at_end`),
    });
  });

  return detach({
    schema_version: TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
    sequence_plan_sha256: planHash,
    sequence_compile_receipt_sha256: receiptHash,
    frame_rate: frameRate,
    segments,
  });
}

function canonicalTransitionSequenceManifestJson(manifest) {
  return canonicalJsonData(
    validateTransitionSequenceManifest(manifest),
    'transition sequence manifest',
  );
}

function transitionSequenceManifestSha256(manifest) {
  return digestCanonical(canonicalTransitionSequenceManifestJson(manifest));
}

function deriveBoundaryId(
  leftSegmentId,
  rightSegmentId,
  leftSourceSha256,
  rightSourceSha256,
  cumulativeBoundaryMs,
) {
  const binding = {
    cumulative_boundary_ms: integer(
      cumulativeBoundaryMs,
      'boundary binding.cumulative_boundary_ms',
      { minimum: 1 },
    ),
    left_segment_id: identifier(
      leftSegmentId,
      SEGMENT_ID,
      'boundary binding.left_segment_id',
    ),
    left_source_sha256: sha256DigestValue(
      leftSourceSha256,
      'boundary binding.left_source_sha256',
    ),
    right_segment_id: identifier(
      rightSegmentId,
      SEGMENT_ID,
      'boundary binding.right_segment_id',
    ),
    right_source_sha256: sha256DigestValue(
      rightSourceSha256,
      'boundary binding.right_source_sha256',
    ),
  };
  return `boundary-${digestCanonical(canonicalJsonData(binding, 'boundary binding'))}`;
}

function manifestBoundaries(manifest) {
  const boundaries = [];
  let cumulative = 0;
  for (let index = 0; index < manifest.segments.length - 1; index += 1) {
    const left = manifest.segments[index];
    const right = manifest.segments[index + 1];
    cumulative += left.duration_ms;
    boundaries.push({
      boundary_id: deriveBoundaryId(
        left.segment_id,
        right.segment_id,
        left.source_sha256,
        right.source_sha256,
        cumulative,
      ),
      left_segment_id: left.segment_id,
      right_segment_id: right.segment_id,
      left_source_sha256: left.source_sha256,
      right_source_sha256: right.source_sha256,
      cumulative_boundary_ms: cumulative,
    });
  }
  return boundaries;
}

function normalizePlan(plan) {
  const raw = exactKeys(plan, PLAN_KEYS, 'transition plan');
  if (raw.schema_version !== TRANSITION_PLAN_SCHEMA_VERSION) {
    fail('transition plan schema_version is unsupported');
  }
  const manifestHash = sha256DigestValue(
    raw.sequence_manifest_sha256,
    'transition plan.sequence_manifest_sha256',
  );
  const policyHash = sha256DigestValue(
    raw.edit_policy_sha256,
    'transition plan.edit_policy_sha256',
  );
  const frameRate = normalizeFrameRate(raw.frame_rate, 'transition plan.frame_rate');
  const policy = normalizePolicy(raw.policy, 'transition plan.policy');
  if (!isDenseArray(raw.boundaries) || raw.boundaries.length > MAX_SEGMENTS - 1) {
    fail(`transition plan.boundaries must contain 0-${MAX_SEGMENTS - 1} entries`);
  }

  const boundaries = [];
  const seenIds = new Set();
  let previousBoundaryMs = 0;
  raw.boundaries.forEach((rawBoundary, index) => {
    const label = `transition plan.boundaries[${index}]`;
    const item = exactKeys(rawBoundary, BOUNDARY_KEYS, label);
    const leftId = identifier(item.left_segment_id, SEGMENT_ID, `${label}.left_segment_id`);
    const rightId = identifier(
      item.right_segment_id,
      SEGMENT_ID,
      `${label}.right_segment_id`,
    );
    const leftHash = sha256DigestValue(
      item.left_source_sha256,
      `${label}.left_source_sha256`,
    );
    const rightHash = sha256DigestValue(
      item.right_source_sha256,
      `${label}.right_source_sha256`,
    );
    const boundaryMs = integer(
      item.cumulative_boundary_ms,
      `${label}.cumulative_boundary_ms`,
      { minimum: 1 },
    );
    if (boundaryMs <= previousBoundaryMs) {
      fail('transition plan boundaries must be in increasing sequence order');
    }
    previousBoundaryMs = boundaryMs;
    const expectedId = deriveBoundaryId(
      leftId,
      rightId,
      leftHash,
      rightHash,
      boundaryMs,
    );
    const boundaryId = identifier(item.boundary_id, BOUNDARY_ID, `${label}.boundary_id`);
    if (boundaryId !== expectedId) {
      fail(`${label}.boundary_id does not bind its exact adjacency`);
    }
    if (seenIds.has(boundaryId)) fail(`${label}.boundary_id must be unique`);
    seenIds.add(boundaryId);

    const kind = enumValue(item.kind, TRANSITION_KIND_SET, `${label}.kind`);
    const motivation = enumValue(item.motivation, MOTIVATION_SET, `${label}.motivation`);
    const duration = integer(item.duration_ms, `${label}.duration_ms`, {
      maximum: MAX_TRANSITION_DURATION_MS,
    });
    const audioBehavior = enumValue(
      item.audio_behavior,
      AUDIO_BEHAVIOR_SET,
      `${label}.audio_behavior`,
    );
    const motivationVerified = booleanValue(
      item.motivation_verified,
      `${label}.motivation_verified`,
    );
    const semanticVerified = booleanValue(
      item.semantic_safety_verified,
      `${label}.semantic_safety_verified`,
    );
    const dialogueVerified = booleanValue(
      item.dialogue_preservation_verified,
      `${label}.dialogue_preservation_verified`,
    );

    if (kind === 'hard_cut') {
      if (duration !== 0) fail(`${label}.duration_ms must be 0 for a hard cut`);
      if (audioBehavior !== 'hard_cut') {
        fail(`${label}.audio_behavior must be hard_cut for a hard cut`);
      }
    } else {
      if (duration === 0) fail(`${label}.duration_ms must be positive for a transition`);
      if (audioBehavior !== 'equal_power_crossfade') {
        fail(
          `${label}.audio_behavior must be equal_power_crossfade ` +
          'for a timed video transition',
        );
      }
      if (!motivationVerified) fail(`${label}.motivation_verified must be true`);
    }
    if (!semanticVerified) fail(`${label}.semantic_safety_verified must be true`);
    if (!dialogueVerified) fail(`${label}.dialogue_preservation_verified must be true`);

    boundaries.push({
      boundary_id: boundaryId,
      left_segment_id: leftId,
      right_segment_id: rightId,
      left_source_sha256: leftHash,
      right_source_sha256: rightHash,
      cumulative_boundary_ms: boundaryMs,
      kind,
      motivation,
      duration_ms: duration,
      audio_behavior: audioBehavior,
      motivation_verified: motivationVerified,
      semantic_safety_verified: true,
      dialogue_preservation_verified: true,
    });
  });

  return {
    schema_version: TRANSITION_PLAN_SCHEMA_VERSION,
    sequence_manifest_sha256: manifestHash,
    edit_policy_sha256: policyHash,
    frame_rate: frameRate,
    policy,
    boundaries,
  };
}

function canonicalTransitionPlanJson(plan) {
  return canonicalJsonData(normalizePlan(plan), 'transition plan');
}

function transitionPlanSha256(plan) {
  return digestCanonical(canonicalTransitionPlanJson(plan));
}

function densityTransitionLimit(density, boundaryCount) {
  const normalizedDensity = enumValue(
    density,
    POLICY_DENSITY_SET,
    'transition density',
  );
  const normalizedCount = integer(boundaryCount, 'boundary_count', {
    maximum: MAX_SEGMENTS - 1,
  });
  if (normalizedDensity === 'none' || normalizedCount === 0) return 0;
  const divisor = { sparse: 4, medium: 2, dense: 1 }[normalizedDensity];
  return Math.floor((normalizedCount + divisor - 1) / divisor);
}

function validateTransitionPlan(plan, sequenceManifest, editPolicy) {
  const normalized = normalizePlan(plan);
  const manifest = validateTransitionSequenceManifest(sequenceManifest);
  let policy;
  let expectedPolicyHash;
  try {
    policy = validateEditPolicy(editPolicy);
    expectedPolicyHash = editPolicySha256(policy);
  } catch (error) {
    if (error instanceof EditPolicyError) {
      throw new TransitionPlanError('edit policy is invalid');
    }
    throw error;
  }

  const manifestHash = transitionSequenceManifestSha256(manifest);
  if (normalized.sequence_manifest_sha256 !== manifestHash) {
    fail('transition plan does not bind the transition sequence manifest');
  }
  if (normalized.edit_policy_sha256 !== expectedPolicyHash) {
    fail('transition plan does not bind the resolved edit policy');
  }
  if (normalized.frame_rate.numerator !== manifest.frame_rate.numerator ||
      normalized.frame_rate.denominator !== manifest.frame_rate.denominator) {
    fail('transition plan frame_rate does not match the sequence manifest');
  }

  const expectedRule = policy.rules.transitions;
  if (normalized.policy.density !== expectedRule.density ||
      normalized.policy.usage !== expectedRule.usage) {
    fail('transition plan policy density/usage does not match edit policy');
  }

  const expectedBoundaries = manifestBoundaries(manifest);
  if (normalized.boundaries.length !== expectedBoundaries.length) {
    fail('transition plan must decide every and only real sequence boundary');
  }

  let nonHardCount = 0;
  const segmentById = new Map(
    manifest.segments.map((item) => [item.segment_id, item]),
  );
  const expectedMotivation = expectedRule.usage === 'hard_cut_only'
    ? 'motivated_only'
    : expectedRule.usage;
  const oneFrameMs = minimumFrameMs(manifest.frame_rate);

  normalized.boundaries.forEach((boundary, index) => {
    const label = `transition plan.boundaries[${index}]`;
    const expected = expectedBoundaries[index];
    for (const [key, expectedValue] of Object.entries(expected)) {
      if (boundary[key] !== expectedValue) {
        fail(`${label}.${key} does not match the exact sequence boundary`);
      }
    }
    if (boundary.motivation !== expectedMotivation) {
      fail(`${label}.motivation does not match policy usage`);
    }

    const duration = boundary.duration_ms;
    if (boundary.kind !== 'hard_cut') {
      nonHardCount += 1;
      if (expectedRule.density === 'none' || expectedRule.usage === 'hard_cut_only') {
        fail(`${label} violates the cut-only transition policy`);
      }

      const frames = durationFrames(duration, manifest.frame_rate);
      if (frames < MIN_TRANSITION_FRAMES) {
        fail(`${label}.duration_ms is shorter than two output frames`);
      }
      if (canonicalFrameDurationMs(frames, manifest.frame_rate) !== duration) {
        fail(`${label}.duration_ms is not aligned to an output frame`);
      }
      if (boundary.kind === 'dip_to_black' &&
          (frames < MIN_DIP_TO_BLACK_FRAMES || frames % 2 !== 0)) {
        fail(
          `${label}.duration_ms must span an even number of at least ` +
          `${MIN_DIP_TO_BLACK_FRAMES} frames for dip_to_black`,
        );
      }

      const left = segmentById.get(boundary.left_segment_id);
      const right = segmentById.get(boundary.right_segment_id);
      if (duration + oneFrameMs > left.duration_ms ||
          duration + oneFrameMs > right.duration_ms) {
        fail(
          `${label}.duration_ms must leave at least one complete ` +
          'untransformed frame in each adjacent segment',
        );
      }
      for (const [segment, handleKey] of [
        [left, 'video_trailing_handle_ms'],
        [right, 'video_leading_handle_ms'],
        [left, 'audio_trailing_handle_ms'],
        [right, 'audio_leading_handle_ms'],
      ]) {
        if (duration > segment[handleKey]) {
          fail(
            `${label}.duration_ms exceeds decoded ${handleKey} ` +
            `for segment ${segment.segment_id}`,
          );
        }
      }
    }
    const left = segmentById.get(boundary.left_segment_id);
    const right = segmentById.get(boundary.right_segment_id);
    const dialogueCrossing = left.dialogue_at_end || right.dialogue_at_start;
    if (dialogueCrossing && !boundary.dialogue_preservation_verified) {
      fail(`${label} could silently damage dialogue`);
    }
  });

  const limit = densityTransitionLimit(expectedRule.density, expectedBoundaries.length);
  if (nonHardCount > limit) {
    fail(
      `transition plan has ${nonHardCount} timed transitions but ` +
      `policy density permits at most ${limit}`,
    );
  }

  for (let segmentIndex = 1;
    segmentIndex < manifest.segments.length - 1;
    segmentIndex += 1) {
    const incoming = normalized.boundaries[segmentIndex - 1].duration_ms;
    const outgoing = normalized.boundaries[segmentIndex].duration_ms;
    const segment = manifest.segments[segmentIndex];
    if (incoming + outgoing + oneFrameMs > segment.duration_ms) {
      fail(`transition windows overlap inside segment ${segment.segment_id}`);
    }
  }

  return detach(normalized);
}

function normalizeReceipt(receipt) {
  const raw = exactKeys(receipt, RECEIPT_KEYS, 'transition compile receipt');
  if (raw.schema_version !== TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION) {
    fail('transition compile receipt schema_version is unsupported');
  }
  const hashes = {};
  for (const key of [
    'transition_plan_sha256',
    'sequence_manifest_sha256',
    'edit_policy_sha256',
    'sequence_plan_sha256',
    'sequence_compile_receipt_sha256',
    'compiled_boundaries_sha256',
  ]) {
    hashes[key] = sha256DigestValue(raw[key], `transition compile receipt.${key}`);
  }
  if (!isDenseArray(raw.ordered_boundary_ids) ||
      raw.ordered_boundary_ids.length > MAX_SEGMENTS - 1) {
    fail('transition compile receipt.ordered_boundary_ids has invalid cardinality');
  }
  const normalizedIds = [];
  const seenIds = new Set();
  raw.ordered_boundary_ids.forEach((value, index) => {
    const boundaryId = identifier(
      value,
      BOUNDARY_ID,
      `transition compile receipt.ordered_boundary_ids[${index}]`,
    );
    if (seenIds.has(boundaryId)) {
      fail('transition compile receipt boundary ids must be unique');
    }
    seenIds.add(boundaryId);
    normalizedIds.push(boundaryId);
  });
  const count = integer(raw.boundary_count, 'transition compile receipt.boundary_count', {
    maximum: MAX_SEGMENTS - 1,
  });
  if (count !== normalizedIds.length) {
    fail('transition compile receipt.boundary_count does not match ids');
  }
  const nonHard = integer(
    raw.non_hard_transition_count,
    'transition compile receipt.non_hard_transition_count',
    { maximum: count },
  );
  const sourceDuration = integer(
    raw.source_duration_ms,
    'transition compile receipt.source_duration_ms',
    { minimum: 1 },
  );
  const outputDuration = integer(
    raw.output_duration_ms,
    'transition compile receipt.output_duration_ms',
    { minimum: 1, maximum: sourceDuration },
  );
  const timeBase = exactKeys(
    raw.time_base,
    TIME_BASE_KEYS,
    'transition compile receipt.time_base',
  );
  // Python dict equality treats True as the integer 1. Preserve that exact
  // accepted input surface, then normalize it to the numeric 1/1000 rational.
  if (!((timeBase.numerator === 1 || timeBase.numerator === true) &&
      timeBase.denominator === 1_000)) {
    fail('transition compile receipt.time_base must be exact 1/1000');
  }
  const frameRate = normalizeFrameRate(
    raw.frame_rate,
    'transition compile receipt.frame_rate',
  );
  const policy = normalizePolicy(raw.policy, 'transition compile receipt.policy');
  return {
    schema_version: TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION,
    ...hashes,
    ordered_boundary_ids: normalizedIds,
    boundary_count: count,
    non_hard_transition_count: nonHard,
    source_duration_ms: sourceDuration,
    output_duration_ms: outputDuration,
    time_base: { numerator: 1, denominator: 1_000 },
    frame_rate: frameRate,
    policy,
  };
}

function transitionCompileReceiptSha256(receipt) {
  return digestCanonical(canonicalJsonData(
    normalizeReceipt(receipt),
    'transition compile receipt',
  ));
}

function compileTransitionPlan(plan, sequenceManifest, editPolicy) {
  const validated = validateTransitionPlan(plan, sequenceManifest, editPolicy);
  const manifest = validateTransitionSequenceManifest(sequenceManifest);
  const sourceDuration = manifest.segments.reduce(
    (total, item) => total + item.duration_ms,
    0,
  );
  const segmentById = new Map(
    manifest.segments.map((item) => [item.segment_id, item]),
  );

  const compiled = [];
  let cumulativeOverlapMs = 0;
  let nonHardCount = 0;
  validated.boundaries.forEach((boundary, index) => {
    const duration = boundary.duration_ms;
    const outputBoundaryMs = boundary.cumulative_boundary_ms - cumulativeOverlapMs;
    const dialogueCrossing =
      segmentById.get(boundary.left_segment_id).dialogue_at_end ||
      segmentById.get(boundary.right_segment_id).dialogue_at_start;
    let durationFrameCount;
    let videoTokens;
    let audioTokens;
    if (boundary.kind === 'hard_cut') {
      durationFrameCount = 0;
      videoTokens = ['concat=n=2:v=1:a=0'];
      audioTokens = ['concat=n=2:v=0:a=1'];
    } else {
      nonHardCount += 1;
      durationFrameCount = durationFrames(duration, manifest.frame_rate);
      const xfadeName = boundary.kind === 'cross_dissolve' ? 'fade' : 'fadeblack';
      const offsetMs = outputBoundaryMs - duration;
      if (offsetMs < 0) fail('compiled transition offset would be negative');
      videoTokens = [
        `xfade=transition=${xfadeName}` +
        `:duration=${ffmpegSeconds(duration)}` +
        `:offset=${ffmpegSeconds(offsetMs)}`,
      ];
      audioTokens = [
        `acrossfade=d=${ffmpegSeconds(duration)}:o=1:c1=qsin:c2=qsin`,
      ];
    }
    compiled.push({
      boundary_index: index,
      boundary_id: boundary.boundary_id,
      left_segment_id: boundary.left_segment_id,
      right_segment_id: boundary.right_segment_id,
      left_source_sha256: boundary.left_source_sha256,
      right_source_sha256: boundary.right_source_sha256,
      cumulative_boundary_ms: boundary.cumulative_boundary_ms,
      output_boundary_ms: outputBoundaryMs,
      kind: boundary.kind,
      motivation: boundary.motivation,
      duration_ms: duration,
      duration_frames: durationFrameCount,
      audio_behavior: boundary.audio_behavior,
      dialogue_crossing: dialogueCrossing,
      video_ffmpeg_primitive_tokens: videoTokens,
      audio_ffmpeg_primitive_tokens: audioTokens,
    });
    cumulativeOverlapMs += duration;
  });

  const compiledHash = digestCanonical(canonicalJsonData(
    compiled,
    'compiled transition boundaries',
  ));
  const receipt = normalizeReceipt({
    schema_version: TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION,
    transition_plan_sha256: transitionPlanSha256(validated),
    sequence_manifest_sha256: transitionSequenceManifestSha256(manifest),
    edit_policy_sha256: editPolicySha256(editPolicy),
    sequence_plan_sha256: manifest.sequence_plan_sha256,
    sequence_compile_receipt_sha256: manifest.sequence_compile_receipt_sha256,
    compiled_boundaries_sha256: compiledHash,
    ordered_boundary_ids: compiled.map((item) => item.boundary_id),
    boundary_count: compiled.length,
    non_hard_transition_count: nonHardCount,
    source_duration_ms: sourceDuration,
    output_duration_ms: sourceDuration - cumulativeOverlapMs,
    time_base: { numerator: 1, denominator: 1_000 },
    frame_rate: manifest.frame_rate,
    policy: validated.policy,
  });
  return {
    compiled_boundaries: detach(compiled),
    receipt: detach(receipt),
    receipt_sha256: transitionCompileReceiptSha256(receipt),
  };
}

module.exports = Object.freeze({
  TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
  TRANSITION_PLAN_SCHEMA_VERSION,
  TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION,
  MAX_SEGMENTS,
  MAX_TRANSITION_DURATION_MS,
  MIN_TRANSITION_FRAMES,
  MIN_DIP_TO_BLACK_FRAMES,
  MAX_SAFE_INTEGER,
  TRANSITION_KINDS,
  MOTIVATIONS,
  AUDIO_BEHAVIORS,
  POLICY_DENSITIES,
  POLICY_USAGES,
  TRANSITION_PLAN_JSON_SCHEMA,
  TransitionPlanError,
  validateTransitionSequenceManifest,
  canonicalTransitionSequenceManifestJson,
  transitionSequenceManifestSha256,
  deriveBoundaryId,
  canonicalTransitionPlanJson,
  transitionPlanSha256,
  densityTransitionLimit,
  validateTransitionPlan,
  transitionCompileReceiptSha256,
  compileTransitionPlan,
});
