'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {
  SEQUENCE_PLAN_SCHEMA_VERSION,
  SOURCE_MANIFEST_SCHEMA_VERSION,
  COMPILE_RECEIPT_SCHEMA_VERSION,
  MAX_SEGMENTS,
  MIN_SEQUENCE_DURATION_MS,
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
} = require('../helper/lib/sequence-plan');

const KNOWN_VECTORS = Object.freeze({
  // Generated independently by autoeditor/sequence_plan.py. These constants
  // make an accidental canonicalization change fail in either runtime.
  sequencePlanSha256: 'b8f7ea2b2615c7b446874c22305139ffcd80ab7fa78d3a233f6af78740e0523a',
  sourceManifestSha256: '42f059638b17a4d7f9518a692e6f9250220382f3840ebdc38c18dbd46c3e1fa7',
  compiledSegmentsSha256: '86800cd56bf434f7e3d37f384acff2a4517769a93a4b53ebd19515e4f18b8a5d',
  compileReceiptSha256: '4a346b3b23565574698d4783425445064459eeab36aa329a9df8abb4791b6dc1',
  unicodeSequencePlanSha256: 'a461686bc6b141ba5f1e590f56272245e9f671160e27ef0beec5e8fa237d315d',
  unicodeCompileReceiptSha256: 'fc008f373cc9215c8a983246763bf5ce232df9213412ba04b162f531e282ea48',
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function source(sourceId, character, durationMs) {
  return { source_id: sourceId, sha256: character.repeat(64), duration_ms: durationMs };
}

function manifest() {
  return {
    schema_version: SOURCE_MANIFEST_SCHEMA_VERSION,
    sources: [
      source('cam-a', 'a', 10000),
      source('screen-b', 'b', 20000),
      source('reaction-c', 'c', 5000),
    ],
  };
}

function segment(
  segmentId,
  sourceId,
  sourceSha256,
  startMs,
  endMs,
  role = 'development',
  speechAnchor = null,
) {
  return {
    segment_id: segmentId,
    source_id: sourceId,
    source_sha256: sourceSha256,
    source_start_ms: startMs,
    source_end_ms: endMs,
    role,
    reason: `Use ${segmentId} because it advances the sequence.`,
    speech_anchor: speechAnchor,
    transition: { kind: 'hard_cut' },
  };
}

function plan() {
  const sources = manifest().sources;
  const byId = new Map(sources.map((item) => [item.source_id, item]));
  return {
    schema_version: SEQUENCE_PLAN_SCHEMA_VERSION,
    sources: [byId.get('screen-b'), byId.get('cam-a'), byId.get('reaction-c')],
    target_duration: { min_ms: 6000, max_ms: 6000 },
    segments: [
      segment(
        'seg-hook',
        'screen-b',
        'b'.repeat(64),
        1250,
        3000,
        'hook',
        { start_word: 4, end_word: 7, text: 'Here is the exact hook' },
      ),
      segment('seg-demo', 'cam-a', 'a'.repeat(64), 500, 2500, 'demonstration'),
      segment('seg-react', 'reaction-c', 'c'.repeat(64), 0, 1000, 'reaction'),
      segment('seg-close', 'screen-b', 'b'.repeat(64), 1500, 2750, 'closer'),
    ],
  };
}

function rejected(candidate, sourceManifest = manifest()) {
  assert.throws(
    () => validateSequencePlan(candidate, sourceManifest),
    SequencePlanError,
  );
}

{
  const raw = plan();
  const clean = validateSequencePlan(raw, manifest());
  assert.deepEqual(clean.sources.map((item) => item.source_id), [
    'cam-a', 'reaction-c', 'screen-b',
  ]);
  assert.deepEqual(clean.segments.map((item) => item.source_id), [
    'screen-b', 'cam-a', 'reaction-c', 'screen-b',
  ]);
  assert.notEqual(clean, raw);
  assert.notEqual(clean.segments, raw.segments);
}

{
  const result = compileSequencePlan(plan(), manifest());
  assert.deepEqual(result.ffmpeg_segments[0].ffmpeg_trim_args, [
    '-ss', '1.250', '-t', '1.750',
  ]);
  assert.equal(result.ffmpeg_segments[0].duration_ms, 1750);
  assert.deepEqual(result.ffmpeg_segments[0].transition, { kind: 'hard_cut' });
  assert.equal(result.receipt.schema_version, COMPILE_RECEIPT_SCHEMA_VERSION);
  assert.equal(result.receipt.total_duration_ms, 6000);
  assert.equal(result.receipt.segment_count, 4);
  assert.deepEqual(result.receipt.ordered_segment_ids, [
    'seg-hook', 'seg-demo', 'seg-react', 'seg-close',
  ]);
  assert.deepEqual(result.receipt.time_base, { numerator: 1, denominator: 1000 });
  assert.equal(result.receipt_sha256, compileReceiptSha256(result.receipt));

  assert.equal(sequencePlanSha256(plan()), KNOWN_VECTORS.sequencePlanSha256);
  assert.equal(sourceManifestSha256(manifest()), KNOWN_VECTORS.sourceManifestSha256);
  assert.equal(
    result.receipt.compiled_segments_sha256,
    KNOWN_VECTORS.compiledSegmentsSha256,
  );
  assert.equal(result.receipt_sha256, KNOWN_VECTORS.compileReceiptSha256);
}

{
  const reorderedPlan = Object.fromEntries(Object.entries(plan()).reverse());
  const reorderedManifest = manifest();
  reorderedManifest.sources.reverse();
  assert.deepEqual(
    compileSequencePlan(reorderedPlan, reorderedManifest),
    compileSequencePlan(plan(), manifest()),
  );
}

{
  const mutations = [];
  let candidate = plan();
  candidate.comment = 'unsupported';
  mutations.push(candidate);
  candidate = plan();
  delete candidate.target_duration.max_ms;
  mutations.push(candidate);
  candidate = plan();
  candidate.sources[0].path = 'untrusted.mp4';
  mutations.push(candidate);
  candidate = plan();
  candidate.segments[0].confidence = 0.9;
  mutations.push(candidate);
  candidate = plan();
  candidate.segments[0].transition.duration_ms = 0;
  mutations.push(candidate);
  candidate = plan();
  candidate.segments[0].speech_anchor.language = 'en';
  mutations.push(candidate);
  mutations.forEach((invalid) => rejected(invalid));

  const sourceManifest = manifest();
  sourceManifest.generated_at = 'now';
  rejected(plan(), sourceManifest);

  candidate = plan();
  candidate[Symbol('hidden-extra')] = true;
  rejected(candidate);

  candidate = plan();
  delete candidate.sources[1];
  rejected(candidate);
}

{
  let candidate = plan();
  candidate.schema_version = 'autoeditor-sequence-plan/v2';
  rejected(candidate);
  const sourceManifest = manifest();
  sourceManifest.schema_version = 'autoeditor-source-manifest/v2';
  rejected(plan(), sourceManifest);
  for (const transition of ['hard_cut', { kind: 'crossfade' }, null]) {
    candidate = plan();
    candidate.segments[0].transition = transition;
    rejected(candidate);
  }
}

{
  let candidate = plan();
  candidate.target_duration = { min_ms: 4999, max_ms: 6000 };
  rejected(candidate);
  candidate = plan();
  candidate.sources = [];
  rejected(candidate);
  candidate = plan();
  candidate.segments = [];
  rejected(candidate);
  candidate = plan();
  const template = candidate.segments[0];
  candidate.segments = Array.from({ length: MAX_SEGMENTS + 1 }, (_, index) => ({
    ...clone(template), segment_id: `segment-${index}`,
  }));
  candidate.target_duration = {
    min_ms: (MAX_SEGMENTS + 1) * 1750,
    max_ms: (MAX_SEGMENTS + 1) * 1750,
  };
  rejected(candidate);
}

{
  for (const invalidId of ['', ' has-space', 'slash/id', 'é', 'x'.repeat(65)]) {
    const candidate = plan();
    const old = candidate.sources[0].source_id;
    candidate.sources[0].source_id = invalidId;
    candidate.segments.forEach((item) => {
      if (item.source_id === old) item.source_id = invalidId;
    });
    const sourceManifest = manifest();
    sourceManifest.sources.find((item) => item.source_id === old).source_id = invalidId;
    rejected(candidate, sourceManifest);
  }
  let candidate = plan();
  candidate.segments[1].segment_id = 'seg-hook';
  rejected(candidate);
  candidate = plan();
  candidate.sources[1].source_id = 'screen-b';
  rejected(candidate);
  candidate = plan();
  candidate.segments[0].segment_id = 'x'.repeat(97);
  rejected(candidate);
}

{
  for (const badHash of ['a'.repeat(63), 'A'.repeat(64), 'g'.repeat(64), 123]) {
    const candidate = plan();
    candidate.sources[0].sha256 = badHash;
    rejected(candidate);
  }
  let candidate = plan();
  candidate.sources[1].sha256 = candidate.sources[0].sha256;
  rejected(candidate);
  candidate = plan();
  candidate.segments[0].source_sha256 = 'a'.repeat(64);
  rejected(candidate);
}

{
  for (const role of ROLES) {
    const candidate = plan();
    candidate.segments[0].role = role;
    validateSequencePlan(candidate, manifest());
  }
  const candidate = plan();
  candidate.segments[0].role = 'viral_magic';
  rejected(candidate);
}

{
  let candidate = plan();
  candidate.segments[0].reason = '  Use\tthe  fullwidth Ａ proof.  ';
  assert.equal(
    validateSequencePlan(candidate, manifest()).segments[0].reason,
    'Use the fullwidth A proof.',
  );
  for (const reason of ['', '---', 7, 'x'.repeat(501)]) {
    candidate = plan();
    candidate.segments[0].reason = reason;
    rejected(candidate);
  }
}

{
  let candidate = plan();
  candidate.segments[0].speech_anchor = null;
  validateSequencePlan(candidate, manifest());
  candidate = plan();
  candidate.segments[0].speech_anchor.text = '  Here is\t the fullwidth Ｈook  ';
  assert.deepEqual(
    validateSequencePlan(candidate, manifest()).segments[0].speech_anchor,
    { start_word: 4, end_word: 7, text: 'Here is the fullwidth Hook' },
  );
  for (const anchor of [
    {},
    { start_word: 4, end_word: 3, text: 'reversed' },
    { start_word: true, end_word: 3, text: 'boolean' },
    { start_word: 0, end_word: 0, text: '---' },
    { start_word: 0, end_word: 0, text: 'x'.repeat(1001) },
  ]) {
    candidate = plan();
    candidate.segments[0].speech_anchor = anchor;
    rejected(candidate);
  }
}

{
  for (const [key, value] of [
    ['source_start_ms', -1],
    ['source_start_ms', true],
    ['source_start_ms', 0.5],
    ['source_end_ms', 1250],
    ['source_end_ms', 20001],
  ]) {
    const candidate = plan();
    candidate.segments[0][key] = value;
    rejected(candidate);
  }
  const candidate = plan();
  candidate.sources[0].duration_ms = 20000.5;
  // JavaScript has one numeric type, so a mathematically integral 20000.0 is
  // indistinguishable from 20000; a genuinely fractional value is rejected.
  rejected(candidate);
}

{
  const reordered = manifest();
  reordered.sources.reverse();
  validateSequencePlan(plan(), reordered);
  for (const mutation of ['missing', 'hash', 'duration', 'extra']) {
    const sourceManifest = manifest();
    if (mutation === 'missing') sourceManifest.sources.pop();
    else if (mutation === 'hash') sourceManifest.sources[0].sha256 = 'd'.repeat(64);
    else if (mutation === 'duration') sourceManifest.sources[0].duration_ms += 1;
    else sourceManifest.sources.push(source('extra', 'd', 1000));
    rejected(plan(), sourceManifest);
  }
}

{
  for (const target of [
    { min_ms: 6000, max_ms: 6000 },
    { min_ms: 5999, max_ms: 6000 },
    { min_ms: 6000, max_ms: 6001 },
  ]) {
    const candidate = plan();
    candidate.target_duration = target;
    validateSequencePlan(candidate, manifest());
  }
  for (const target of [
    { min_ms: 6001, max_ms: 7000 },
    { min_ms: 1, max_ms: 5999 },
    { min_ms: 7000, max_ms: 6000 },
    { min_ms: true, max_ms: 6000 },
    { min_ms: 6000.5, max_ms: 6001 },
  ]) {
    const candidate = plan();
    candidate.target_duration = target;
    rejected(candidate);
  }
}

{
  const raw = plan();
  const reordered = Object.fromEntries(Object.entries(raw).reverse());
  reordered.sources = [...reordered.sources].reverse();
  reordered.segments[0].reason = 'Use seg-hook because it advances the sequence.';
  assert.equal(sequencePlanSha256(raw), sequencePlanSha256(reordered));
  assert.equal(canonicalJson(raw), canonicalJson(reordered));
  const changed = plan();
  [changed.segments[0], changed.segments[1]] = [changed.segments[1], changed.segments[0]];
  assert.notEqual(sequencePlanSha256(raw), sequencePlanSha256(changed));

  const sourceManifest = manifest();
  const sourceReordered = clone(sourceManifest);
  sourceReordered.sources.reverse();
  assert.equal(sourceManifestSha256(sourceManifest), sourceManifestSha256(sourceReordered));
  assert.equal(
    canonicalSourceManifestJson(sourceManifest),
    canonicalSourceManifestJson(sourceReordered),
  );
}

{
  const result = compileSequencePlan(plan(), manifest());
  const original = result.receipt_sha256;
  for (const [key, replacement] of [
    ['sequence_plan_sha256', 'd'.repeat(64)],
    ['source_manifest_sha256', 'e'.repeat(64)],
    ['compiled_segments_sha256', 'f'.repeat(64)],
    ['total_duration_ms', 6001],
  ]) {
    const changed = clone(result.receipt);
    changed[key] = replacement;
    assert.notEqual(compileReceiptSha256(changed), original);
  }
  const reordered = clone(result.receipt);
  reordered.ordered_segment_ids.reverse();
  assert.notEqual(compileReceiptSha256(reordered), original);
  const invalid = clone(result.receipt);
  invalid.extra = true;
  assert.throws(() => compileReceiptSha256(invalid), SequencePlanError);
  const sparse = clone(result.receipt);
  delete sparse.ordered_segment_ids[1];
  assert.throws(() => compileReceiptSha256(sparse), SequencePlanError);
}

{
  const result = compileSequencePlan(plan(), manifest());
  const decimal = /^(0|[1-9][0-9]*)\.[0-9]{3}$/;
  result.ffmpeg_segments.forEach((item) => {
    assert.equal(item.ffmpeg_trim_args[0], '-ss');
    assert.equal(item.ffmpeg_trim_args[2], '-t');
    assert.match(item.ffmpeg_trim_args[1], decimal);
    assert.match(item.ffmpeg_trim_args[3], decimal);
    assert.doesNotMatch(item.ffmpeg_trim_args.join(''), /[;&|`$(){}[\]<>]/);
  });
}

{
  assert.equal(
    SEQUENCE_PLAN_JSON_SCHEMA.properties.schema_version.const,
    SEQUENCE_PLAN_SCHEMA_VERSION,
  );
  assert.equal(SEQUENCE_PLAN_JSON_SCHEMA.additionalProperties, false);
  assert.equal(SEQUENCE_PLAN_JSON_SCHEMA.properties.sources.maxItems, 20);
  assert.equal(
    SEQUENCE_PLAN_JSON_SCHEMA.properties.sources.items.properties.duration_ms.minimum,
    1,
  );
  assert.equal(
    SEQUENCE_PLAN_JSON_SCHEMA.properties.target_duration.properties.min_ms.minimum,
    MIN_SEQUENCE_DURATION_MS,
  );
  assert.equal(
    SEQUENCE_PLAN_JSON_SCHEMA.properties.target_duration.properties.max_ms.minimum,
    MIN_SEQUENCE_DURATION_MS,
  );
  const segmentSchema = SEQUENCE_PLAN_JSON_SCHEMA.properties.segments;
  assert.equal(segmentSchema.maxItems, MAX_SEGMENTS);
  assert.equal(segmentSchema.items.additionalProperties, false);
  assert.deepEqual(segmentSchema.items.properties.role.enum, ROLES);
  assert.equal(segmentSchema.items.properties.transition.properties.kind.const, 'hard_cut');
}

{
  // Recompute one canonical payload independently with Node's SHA primitive;
  // this catches accidental digesting of UTF-16 strings or pretty JSON.
  const canonical = canonicalJson(plan());
  const independent = crypto.createHash('sha256').update(
    Buffer.from(canonical, 'utf8'),
  ).digest('hex');
  assert.equal(independent, KNOWN_VECTORS.sequencePlanSha256);
}

{
  // Python's ensure_ascii JSON uses lowercase escapes and UTF-16 surrogate
  // pairs. This vector proves non-ASCII editorial rationale hashes identically.
  const unicodePlan = plan();
  unicodePlan.segments[0].reason =
    '  Use\tthe fullwidth \uff21, caf\u00e9 \u{1f600}.  ';
  unicodePlan.segments[0].speech_anchor.text =
    '  Here\tis the exact \uff28ook \u{1f600}  ';
  assert.equal(
    sequencePlanSha256(unicodePlan),
    KNOWN_VECTORS.unicodeSequencePlanSha256,
  );
  assert.equal(
    compileSequencePlan(unicodePlan, manifest()).receipt_sha256,
    KNOWN_VECTORS.unicodeCompileReceiptSha256,
  );
  assert.match(canonicalJson(unicodePlan), /caf\\u00e9 \\ud83d\\ude00/);
}

console.log('sequence plan contract tests passed');
