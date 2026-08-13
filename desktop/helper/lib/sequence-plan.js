'use strict';

const crypto = require('node:crypto');

const SEQUENCE_PLAN_SCHEMA_VERSION = 'autoeditor-sequence-plan/v1';
const SOURCE_MANIFEST_SCHEMA_VERSION = 'autoeditor-source-manifest/v1';
const COMPILE_RECEIPT_SCHEMA_VERSION = 'autoeditor-sequence-compile-receipt/v1';

const MAX_SOURCES = 20;
const MAX_SEGMENTS = 256;
const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;
// Shared with Python. These caps make every schema-valid 256-segment plan fit
// the bounded desktop, IPC, daemon, and persisted-receipt contracts even when
// Unicode is escaped for canonical cross-runtime hashing.
const MAX_REASON_CHARACTERS = 200;
const MAX_SPEECH_ANCHOR_CHARACTERS = 500;
const MIN_SEQUENCE_DURATION_MS = 5000;
const MIN_SEGMENT_DURATION_MS = 34;

const ROLES = Object.freeze([
  'bridge',
  'closer',
  'cta',
  'demonstration',
  'development',
  'establishing',
  'evidence',
  'highlight',
  'hook',
  'other',
  'payoff',
  'reaction',
  'setup',
  'transition',
]);
const ROLE_SET = new Set(ROLES);

const ROOT_KEYS = Object.freeze([
  'schema_version', 'segments', 'sources', 'target_duration',
]);
const SOURCE_MANIFEST_KEYS = Object.freeze(['schema_version', 'sources']);
const SOURCE_KEYS = Object.freeze(['duration_ms', 'sha256', 'source_id']);
const TARGET_KEYS = Object.freeze(['max_ms', 'min_ms']);
const SEGMENT_KEYS = Object.freeze([
  'reason',
  'role',
  'segment_id',
  'source_end_ms',
  'source_id',
  'source_sha256',
  'source_start_ms',
  'speech_anchor',
  'transition',
]);
const SPEECH_ANCHOR_KEYS = Object.freeze(['end_word', 'start_word', 'text']);
const TRANSITION_KEYS = Object.freeze(['kind']);
const RECEIPT_KEYS = Object.freeze([
  'compiled_segments_sha256',
  'ordered_segment_ids',
  'schema_version',
  'segment_count',
  'sequence_plan_sha256',
  'source_manifest_sha256',
  'time_base',
  'total_duration_ms',
]);
const TIME_BASE_KEYS = Object.freeze(['denominator', 'numerator']);

const SOURCE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SEGMENT_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const CONTROL_OR_FORMAT = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/u;
const ALPHANUMERIC = /[\p{L}\p{N}]/u;

function sourceJsonSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: [...SOURCE_KEYS],
    properties: {
      source_id: { type: 'string', pattern: SOURCE_ID.source },
      sha256: { type: 'string', pattern: SHA256.source },
      duration_ms: {
        type: 'integer', minimum: 1, maximum: MAX_SAFE_INTEGER,
      },
    },
  };
}

const SEQUENCE_PLAN_JSON_SCHEMA = Object.freeze({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  additionalProperties: false,
  required: [...ROOT_KEYS],
  properties: {
    schema_version: { const: SEQUENCE_PLAN_SCHEMA_VERSION },
    sources: {
      type: 'array',
      minItems: 1,
      maxItems: MAX_SOURCES,
      items: sourceJsonSchema(),
    },
    target_duration: {
      type: 'object',
      additionalProperties: false,
      required: [...TARGET_KEYS],
      properties: {
        min_ms: {
          type: 'integer', minimum: MIN_SEQUENCE_DURATION_MS,
          maximum: MAX_SAFE_INTEGER,
        },
        max_ms: {
          type: 'integer', minimum: MIN_SEQUENCE_DURATION_MS,
          maximum: MAX_SAFE_INTEGER,
        },
      },
    },
    segments: {
      type: 'array',
      minItems: 1,
      maxItems: MAX_SEGMENTS,
      items: {
        type: 'object',
        additionalProperties: false,
        required: [...SEGMENT_KEYS],
        properties: {
          segment_id: { type: 'string', pattern: SEGMENT_ID.source },
          source_id: { type: 'string', pattern: SOURCE_ID.source },
          source_sha256: { type: 'string', pattern: SHA256.source },
          source_start_ms: {
            type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER,
          },
          source_end_ms: {
            type: 'integer', minimum: 1, maximum: MAX_SAFE_INTEGER,
          },
          role: { type: 'string', enum: [...ROLES] },
          reason: {
            type: 'string', minLength: 1, maxLength: MAX_REASON_CHARACTERS,
          },
          speech_anchor: {
            anyOf: [
              { type: 'null' },
              {
                type: 'object',
                additionalProperties: false,
                required: [...SPEECH_ANCHOR_KEYS],
                properties: {
                  start_word: {
                    type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER,
                  },
                  end_word: {
                    type: 'integer', minimum: 0, maximum: MAX_SAFE_INTEGER,
                  },
                  text: {
                    type: 'string',
                    minLength: 1,
                    maxLength: MAX_SPEECH_ANCHOR_CHARACTERS,
                  },
                },
              },
            ],
          },
          transition: {
            type: 'object',
            additionalProperties: false,
            required: ['kind'],
            properties: { kind: { const: 'hard_cut' } },
          },
        },
      },
    },
  },
});

class SequencePlanError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SequencePlanError';
  }
}

function fail(message) {
  throw new SequencePlanError(message);
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
    (typeof key === 'string' && /^(0|[1-9][0-9]*)$/.test(key) && Number(key) < value.length)
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

function integer(value, label, { minimum = 0, maximum = MAX_SAFE_INTEGER } = {}) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function identifier(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} has an invalid ASCII identifier`);
  }
  return value;
}

function sha256Digest(value, label) {
  if (typeof value !== 'string' || !SHA256.test(value)) {
    fail(`${label} must be a full lowercase SHA-256 digest`);
  }
  return value;
}

function canonicalText(value, label, { maximum }) {
  if (typeof value !== 'string') fail(`${label} must be a string`);
  const text = value.normalize('NFKC').trim().replace(/\s+/gu, ' ');
  const characterCount = Array.from(text).length;
  if (!text || characterCount > maximum) {
    fail(`${label} must contain 1-${maximum} canonical characters`);
  }
  if (!ALPHANUMERIC.test(text)) {
    fail(`${label} must contain an alphanumeric character`);
  }
  if (CONTROL_OR_FORMAT.test(text)) {
    fail(`${label} must not contain control or format characters`);
  }
  return text;
}

function normalizeSources(value, label) {
  if (!isDenseArray(value) || value.length < 1 || value.length > MAX_SOURCES) {
    fail(`${label} must contain 1-${MAX_SOURCES} sources`);
  }
  const normalized = [];
  const seenIds = new Set();
  const seenHashes = new Set();
  value.forEach((raw, index) => {
    const itemLabel = `${label}[${index}]`;
    const item = exactKeys(raw, SOURCE_KEYS, itemLabel);
    const sourceId = identifier(item.source_id, SOURCE_ID, `${itemLabel}.source_id`);
    const digest = sha256Digest(item.sha256, `${itemLabel}.sha256`);
    const duration = integer(item.duration_ms, `${itemLabel}.duration_ms`, { minimum: 1 });
    if (seenIds.has(sourceId)) fail(`${itemLabel}.source_id must be unique`);
    if (seenHashes.has(digest)) {
      fail(`${itemLabel}.sha256 must identify one unique source`);
    }
    seenIds.add(sourceId);
    seenHashes.add(digest);
    normalized.push({ source_id: sourceId, sha256: digest, duration_ms: duration });
  });
  return normalized.sort((left, right) => asciiCompare(left.source_id, right.source_id));
}

function normalizeManifest(value) {
  const manifest = exactKeys(value, SOURCE_MANIFEST_KEYS, 'source manifest');
  if (manifest.schema_version !== SOURCE_MANIFEST_SCHEMA_VERSION) {
    fail('source manifest schema_version is unsupported');
  }
  return {
    schema_version: SOURCE_MANIFEST_SCHEMA_VERSION,
    sources: normalizeSources(manifest.sources, 'source manifest sources'),
  };
}

function normalizeSpeechAnchor(value, label) {
  if (value === null) return null;
  const anchor = exactKeys(value, SPEECH_ANCHOR_KEYS, label);
  const start = integer(anchor.start_word, `${label}.start_word`);
  const end = integer(anchor.end_word, `${label}.end_word`);
  if (start > end) fail(`${label} has reversed inclusive word bounds`);
  const text = canonicalText(anchor.text, `${label}.text`, {
    maximum: MAX_SPEECH_ANCHOR_CHARACTERS,
  });
  return { start_word: start, end_word: end, text };
}

function normalizePlan(value) {
  const plan = exactKeys(value, ROOT_KEYS, 'sequence plan');
  if (plan.schema_version !== SEQUENCE_PLAN_SCHEMA_VERSION) {
    fail('sequence plan schema_version is unsupported');
  }
  const sources = normalizeSources(plan.sources, 'sequence plan sources');
  const sourcesById = new Map(sources.map((source) => [source.source_id, source]));

  const target = exactKeys(plan.target_duration, TARGET_KEYS, 'target_duration');
  const minimum = integer(target.min_ms, 'target_duration.min_ms', {
    minimum: MIN_SEQUENCE_DURATION_MS,
  });
  const maximum = integer(target.max_ms, 'target_duration.max_ms', {
    minimum: MIN_SEQUENCE_DURATION_MS,
  });
  if (minimum > maximum) fail('target_duration.min_ms cannot exceed max_ms');

  const rawSegments = plan.segments;
  if (!isDenseArray(rawSegments) || rawSegments.length < 1 ||
      rawSegments.length > MAX_SEGMENTS) {
    fail(`segments must contain 1-${MAX_SEGMENTS} ordered entries`);
  }

  const segments = [];
  const seenSegmentIds = new Set();
  let totalDuration = 0;
  rawSegments.forEach((raw, index) => {
    const label = `segments[${index}]`;
    const item = exactKeys(raw, SEGMENT_KEYS, label);
    const segmentId = identifier(item.segment_id, SEGMENT_ID, `${label}.segment_id`);
    if (seenSegmentIds.has(segmentId)) fail(`${label}.segment_id must be unique`);
    seenSegmentIds.add(segmentId);

    const sourceId = identifier(item.source_id, SOURCE_ID, `${label}.source_id`);
    const source = sourcesById.get(sourceId);
    if (!source) fail(`${label}.source_id is absent from sequence plan sources`);
    const digest = sha256Digest(item.source_sha256, `${label}.source_sha256`);
    if (digest !== source.sha256) {
      fail(`${label}.source_sha256 does not bind its source_id`);
    }

    const start = integer(item.source_start_ms, `${label}.source_start_ms`);
    const end = integer(item.source_end_ms, `${label}.source_end_ms`, { minimum: 1 });
    if (end - start < MIN_SEGMENT_DURATION_MS) {
      fail(`${label} must be at least ${MIN_SEGMENT_DURATION_MS}ms to produce a 30fps frame`);
    }
    if (end > source.duration_ms) fail(`${label} ends beyond its source duration`);

    if (typeof item.role !== 'string' || !ROLE_SET.has(item.role)) {
      fail(`${label}.role is unsupported`);
    }
    const reason = canonicalText(item.reason, `${label}.reason`, {
      maximum: MAX_REASON_CHARACTERS,
    });
    const speechAnchor = normalizeSpeechAnchor(
      item.speech_anchor,
      `${label}.speech_anchor`,
    );
    const transition = exactKeys(item.transition, TRANSITION_KEYS, `${label}.transition`);
    if (typeof transition.kind !== 'string' || transition.kind !== 'hard_cut') {
      fail(`${label}.transition.kind must be hard_cut in v1`);
    }

    const segmentDuration = end - start;
    totalDuration += segmentDuration;
    if (!Number.isSafeInteger(totalDuration)) {
      fail('total segment duration exceeds the exact JSON integer range');
    }
    segments.push({
      segment_id: segmentId,
      source_id: sourceId,
      source_sha256: digest,
      source_start_ms: start,
      source_end_ms: end,
      role: item.role,
      reason,
      speech_anchor: speechAnchor,
      transition: { kind: 'hard_cut' },
    });
  });

  if (totalDuration < minimum || totalDuration > maximum) {
    fail('sum of ordered segment durations is outside target_duration');
  }
  return {
    schema_version: SEQUENCE_PLAN_SCHEMA_VERSION,
    sources,
    target_duration: { min_ms: minimum, max_ms: maximum },
    segments,
  };
}

function validateSequencePlan(plan, sourceManifest) {
  const normalizedPlan = normalizePlan(plan);
  const manifest = normalizeManifest(sourceManifest);
  if (canonicalJsonData(normalizedPlan.sources, 'sequence plan sources') !==
      canonicalJsonData(manifest.sources, 'source manifest sources')) {
    fail('sequence plan sources do not exactly match the source manifest');
  }
  return normalizedPlan;
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
    else if (codePoint <= 0xffff) result += `\\u${codePoint.toString(16).padStart(4, '0')}`;
    else {
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
    if (Array.isArray(item)) return `[${item.map(serialize).join(',')}]`;
    if (isPlainObject(item)) {
      const keys = Object.keys(item).sort(asciiCompare);
      return `{${keys.map((key) => `${pythonString(key)}:${serialize(item[key])}`).join(',')}}`;
    }
    fail(`${label} is not canonical JSON`);
  }
  return serialize(value);
}

function digestCanonical(canonical) {
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

function canonicalJson(plan) {
  return canonicalJsonData(normalizePlan(plan), 'sequence plan');
}

function sequencePlanSha256(plan) {
  return digestCanonical(canonicalJson(plan));
}

function canonicalSourceManifestJson(sourceManifest) {
  return canonicalJsonData(normalizeManifest(sourceManifest), 'source manifest');
}

function sourceManifestSha256(sourceManifest) {
  return digestCanonical(canonicalSourceManifestJson(sourceManifest));
}

function ffmpegSeconds(milliseconds) {
  return `${Math.floor(milliseconds / 1000)}.${String(milliseconds % 1000).padStart(3, '0')}`;
}

function normalizeReceipt(value) {
  const receipt = exactKeys(value, RECEIPT_KEYS, 'compile receipt');
  if (receipt.schema_version !== COMPILE_RECEIPT_SCHEMA_VERSION) {
    fail('compile receipt schema_version is unsupported');
  }
  const planHash = sha256Digest(
    receipt.sequence_plan_sha256,
    'compile receipt.sequence_plan_sha256',
  );
  const manifestHash = sha256Digest(
    receipt.source_manifest_sha256,
    'compile receipt.source_manifest_sha256',
  );
  const compiledHash = sha256Digest(
    receipt.compiled_segments_sha256,
    'compile receipt.compiled_segments_sha256',
  );
  if (!isDenseArray(receipt.ordered_segment_ids) ||
      receipt.ordered_segment_ids.length < 1 ||
      receipt.ordered_segment_ids.length > MAX_SEGMENTS) {
    fail('compile receipt.ordered_segment_ids has invalid cardinality');
  }
  const seenIds = new Set();
  const ordered = receipt.ordered_segment_ids.map((valueId, index) => {
    const segmentId = identifier(
      valueId,
      SEGMENT_ID,
      `compile receipt.ordered_segment_ids[${index}]`,
    );
    if (seenIds.has(segmentId)) {
      fail('compile receipt ordered segment ids must be unique');
    }
    seenIds.add(segmentId);
    return segmentId;
  });
  const count = integer(receipt.segment_count, 'compile receipt.segment_count', {
    minimum: 1,
    maximum: MAX_SEGMENTS,
  });
  if (count !== ordered.length) {
    fail('compile receipt.segment_count does not match ordered ids');
  }
  const total = integer(receipt.total_duration_ms, 'compile receipt.total_duration_ms', {
    minimum: 1,
  });
  const timeBase = exactKeys(receipt.time_base, TIME_BASE_KEYS, 'compile receipt.time_base');
  if (!Number.isSafeInteger(timeBase.numerator) ||
      !Number.isSafeInteger(timeBase.denominator) ||
      timeBase.numerator !== 1 || timeBase.denominator !== 1000) {
    fail('compile receipt.time_base must be the exact 1/1000 rational');
  }
  return {
    schema_version: COMPILE_RECEIPT_SCHEMA_VERSION,
    sequence_plan_sha256: planHash,
    source_manifest_sha256: manifestHash,
    compiled_segments_sha256: compiledHash,
    ordered_segment_ids: ordered,
    segment_count: count,
    total_duration_ms: total,
    time_base: { numerator: 1, denominator: 1000 },
  };
}

function compileReceiptSha256(receipt) {
  return digestCanonical(canonicalJsonData(normalizeReceipt(receipt), 'compile receipt'));
}

function compileSequencePlan(plan, sourceManifest) {
  const validated = validateSequencePlan(plan, sourceManifest);
  let totalDuration = 0;
  const ffmpegSegments = validated.segments.map((segment, sequenceIndex) => {
    const start = segment.source_start_ms;
    const duration = segment.source_end_ms - start;
    totalDuration += duration;
    return {
      sequence_index: sequenceIndex,
      segment_id: segment.segment_id,
      source_id: segment.source_id,
      source_sha256: segment.source_sha256,
      source_start_ms: start,
      source_end_ms: segment.source_end_ms,
      duration_ms: duration,
      transition: { kind: 'hard_cut' },
      ffmpeg_trim_args: ['-ss', ffmpegSeconds(start), '-t', ffmpegSeconds(duration)],
    };
  });
  const receipt = normalizeReceipt({
    schema_version: COMPILE_RECEIPT_SCHEMA_VERSION,
    sequence_plan_sha256: sequencePlanSha256(validated),
    source_manifest_sha256: sourceManifestSha256(sourceManifest),
    compiled_segments_sha256: digestCanonical(
      canonicalJsonData(ffmpegSegments, 'compiled segments'),
    ),
    ordered_segment_ids: ffmpegSegments.map((segment) => segment.segment_id),
    segment_count: ffmpegSegments.length,
    total_duration_ms: totalDuration,
    time_base: { numerator: 1, denominator: 1000 },
  });
  return {
    receipt,
    receipt_sha256: compileReceiptSha256(receipt),
    ffmpeg_segments: ffmpegSegments,
  };
}

module.exports = Object.freeze({
  SEQUENCE_PLAN_SCHEMA_VERSION,
  SOURCE_MANIFEST_SCHEMA_VERSION,
  COMPILE_RECEIPT_SCHEMA_VERSION,
  MAX_SOURCES,
  MAX_SEGMENTS,
  MAX_SAFE_INTEGER,
  MAX_REASON_CHARACTERS,
  MAX_SPEECH_ANCHOR_CHARACTERS,
  MIN_SEQUENCE_DURATION_MS,
  MIN_SEGMENT_DURATION_MS,
  ROLES,
  SEQUENCE_PLAN_JSON_SCHEMA,
  SequencePlanError,
  validateSequencePlan,
  canonicalJson,
  sequencePlanSha256,
  canonicalSourceManifestJson,
  sourceManifestSha256,
  compileReceiptSha256,
  compileSequencePlan,
});
