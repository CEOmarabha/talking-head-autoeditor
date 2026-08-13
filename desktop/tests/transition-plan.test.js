'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const test = require('node:test');

const {
  CAPABILITIES,
  EDIT_POLICY_REQUEST_SCHEMA_VERSION,
  editPolicySha256,
  resolveEditPolicy,
} = require('../helper/lib/edit-policy');
const {
  AUDIO_BEHAVIORS,
  MAX_TRANSITION_DURATION_MS,
  MOTIVATIONS,
  TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION,
  TRANSITION_KINDS,
  TRANSITION_PLAN_JSON_SCHEMA,
  TRANSITION_PLAN_SCHEMA_VERSION,
  TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
  TransitionPlanError,
  canonicalTransitionPlanJson,
  canonicalTransitionSequenceManifestJson,
  compileTransitionPlan,
  densityTransitionLimit,
  deriveBoundaryId,
  transitionCompileReceiptSha256,
  transitionPlanSha256,
  transitionSequenceManifestSha256,
  validateTransitionPlan,
  validateTransitionSequenceManifest,
} = require('../helper/lib/transition-plan');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function autoValues() {
  return {
    cut_density: 'auto',
    sfx_density: 'auto',
    transition_density: 'auto',
    dialogue_rule: 'auto',
    music_rule: 'auto',
    caption_rule: 'auto',
    visualization_rule: 'auto',
  };
}

function makePolicy({ profile = 'commercial_product', density = 'auto' } = {}) {
  const explicit = autoValues();
  explicit.transition_density = density;
  return resolveEditPolicy({
    schema_version: EDIT_POLICY_REQUEST_SCHEMA_VERSION,
    profile,
    duration_ms: 8_000,
    delivery: { platform: 'youtube', aspect: 'auto' },
    explicit_intent: explicit,
    consented_preferences: { consented: false, values: autoValues() },
    available_capabilities: [...CAPABILITIES].sort(),
  });
}

function makeSegment(
  segmentId,
  digestCharacter,
  {
    durationMs = 2_000,
    handlesMs = 1_000,
    dialogueAtStart = false,
    dialogueAtEnd = false,
  } = {},
) {
  return {
    segment_id: segmentId,
    source_sha256: digestCharacter.repeat(64),
    duration_ms: durationMs,
    video_leading_handle_ms: Math.min(handlesMs, durationMs),
    video_trailing_handle_ms: Math.min(handlesMs, durationMs),
    audio_leading_handle_ms: Math.min(handlesMs, durationMs),
    audio_trailing_handle_ms: Math.min(handlesMs, durationMs),
    dialogue_at_start: dialogueAtStart,
    dialogue_at_end: dialogueAtEnd,
  };
}

function makeManifest({ numerator = 30, denominator = 1 } = {}) {
  return {
    schema_version: TRANSITION_SEQUENCE_MANIFEST_SCHEMA_VERSION,
    sequence_plan_sha256: 'e'.repeat(64),
    sequence_compile_receipt_sha256: 'f'.repeat(64),
    frame_rate: { numerator, denominator },
    segments: [
      makeSegment('seg-a', 'a', { dialogueAtEnd: true }),
      makeSegment('seg-b', 'b', { dialogueAtStart: true }),
      makeSegment('seg-c', 'c'),
      makeSegment('seg-d', 'd'),
    ],
  };
}

function makeBoundary(left, right, cumulativeBoundaryMs, {
  kind,
  durationMs,
  motivation,
}) {
  return {
    boundary_id: deriveBoundaryId(
      left.segment_id,
      right.segment_id,
      left.source_sha256,
      right.source_sha256,
      cumulativeBoundaryMs,
    ),
    left_segment_id: left.segment_id,
    right_segment_id: right.segment_id,
    left_source_sha256: left.source_sha256,
    right_source_sha256: right.source_sha256,
    cumulative_boundary_ms: cumulativeBoundaryMs,
    kind,
    motivation,
    duration_ms: durationMs,
    audio_behavior: kind === 'hard_cut' ? 'hard_cut' : 'equal_power_crossfade',
    motivation_verified: kind !== 'hard_cut',
    semantic_safety_verified: true,
    dialogue_preservation_verified: true,
  };
}

function makePlan(
  manifest = makeManifest(),
  policy = makePolicy(),
  decisions = [
    ['cross_dissolve', 400],
    ['dip_to_black', 200],
    ['hard_cut', 0],
  ],
) {
  const usage = policy.rules.transitions.usage;
  const motivation = usage === 'hard_cut_only' ? 'motivated_only' : usage;
  let cumulative = 0;
  const boundaries = manifest.segments.slice(0, -1).map((left, index) => {
    cumulative += left.duration_ms;
    const [kind, durationMs] = decisions[index];
    return makeBoundary(left, manifest.segments[index + 1], cumulative, {
      kind,
      durationMs,
      motivation,
    });
  });
  return {
    schema_version: TRANSITION_PLAN_SCHEMA_VERSION,
    sequence_manifest_sha256: transitionSequenceManifestSha256(manifest),
    edit_policy_sha256: editPolicySha256(policy),
    frame_rate: clone(manifest.frame_rate),
    policy: clone(policy.rules.transitions),
    boundaries,
  };
}

function reversedObject(value) {
  return Object.fromEntries(Object.entries(value).reverse());
}

function canonicalSchemaJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalSchemaJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => (
    `${JSON.stringify(key)}:${canonicalSchemaJson(value[key])}`
  )).join(',')}}`;
}

// Frozen from CPython 3 against autoeditor/transition_plan.py. These values
// are intentionally literals rather than calculations duplicated from JS.
const PYTHON_VECTOR = Object.freeze({
  schema_sha256: 'fe62a66a9b50d77c03911a10b587c24a87d6e085a009b364639dfc2e282e1c0e',
  manifest_sha256: '51dac73a82e119b845f22c7296ddb581bcb714224642cf70e6aa6680ff4f025f',
  edit_policy_sha256: '5cf6a614eb1e7b2b1aaccf30055ec28b49205565e56e38fe55cbb32a6511d297',
  boundary_ids: Object.freeze([
    'boundary-3a0f2165b96b01dfaa625d5cdc6fa006d96ec4ded86a51d77d7c3c4369c91979',
    'boundary-58f0407eb84ba1f46ebf304f791ac3da5a8cef1960dabcd7774028461bc59dd5',
    'boundary-934fee8407a7aec68760e560f5636aebd3fee7f5f7878d7afaee87bf51b40884',
  ]),
  plan_sha256: 'ba0d3c13ce01de1a8f2d3d167d32ebde9720cb97081ea129ab9011c65aa0a662',
  compiled_boundaries_sha256:
    '5d810b05966ea5560b890fb21eba49686ea814520bbd94c600a2d98d0ad9bcc1',
  receipt_sha256: '41abd44f76fa5725ea96adbd1334fc47f832d632bbb1541c0d15f74374001eb3',
});

test('frozen Python manifest, policy, boundary, plan, compile, and receipt vectors match', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const result = compileTransitionPlan(plan, manifest, policy);

  assert.equal(transitionSequenceManifestSha256(manifest), PYTHON_VECTOR.manifest_sha256);
  assert.equal(editPolicySha256(policy), PYTHON_VECTOR.edit_policy_sha256);
  assert.deepEqual(
    plan.boundaries.map((boundary) => boundary.boundary_id),
    PYTHON_VECTOR.boundary_ids,
  );
  assert.equal(transitionPlanSha256(plan), PYTHON_VECTOR.plan_sha256);
  assert.equal(
    result.receipt.compiled_boundaries_sha256,
    PYTHON_VECTOR.compiled_boundaries_sha256,
  );
  assert.equal(result.receipt_sha256, PYTHON_VECTOR.receipt_sha256);
  assert.equal(result.receipt_sha256, transitionCompileReceiptSha256(result.receipt));
});

test('canonical JSON is Python-compatible and independent of object key insertion order', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const reorderedManifest = reversedObject(manifest);
  reorderedManifest.segments = manifest.segments.map(reversedObject);
  const reorderedPlan = reversedObject(plan);
  reorderedPlan.boundaries = plan.boundaries.map(reversedObject);

  assert.equal(
    canonicalTransitionSequenceManifestJson(manifest),
    canonicalTransitionSequenceManifestJson(reorderedManifest),
  );
  assert.equal(canonicalTransitionPlanJson(plan), canonicalTransitionPlanJson(reorderedPlan));
  assert.equal(transitionPlanSha256(reorderedPlan), PYTHON_VECTOR.plan_sha256);
  assert.match(canonicalTransitionPlanJson(plan), /^\{"boundaries":\[/);
  assert.doesNotMatch(canonicalTransitionPlanJson(plan), /\s/);
});

test('valid plan decides each exact adjacency and returned data is detached', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const raw = makePlan(manifest, policy);
  const clean = validateTransitionPlan(raw, manifest, policy);

  assert.deepEqual(clean, raw);
  assert.notEqual(clean, raw);
  assert.notEqual(clean.boundaries, raw.boundaries);
  assert.deepEqual(clean.boundaries.map((item) => item.cumulative_boundary_ms), [
    2_000, 4_000, 6_000,
  ]);
  assert.deepEqual(clean.policy, { density: 'medium', usage: 'motivated_only' });

  clean.boundaries[0].kind = 'hard_cut';
  assert.equal(raw.boundaries[0].kind, 'cross_dissolve');
});

test('boundary id binds both segment ids, both source hashes, and cumulative time', () => {
  const manifest = makeManifest();
  const first = makePlan(manifest).boundaries[0];
  const argumentsByName = {
    left_segment_id: first.left_segment_id,
    right_segment_id: first.right_segment_id,
    left_source_sha256: first.left_source_sha256,
    right_source_sha256: first.right_source_sha256,
    cumulative_boundary_ms: first.cumulative_boundary_ms,
  };
  const mutations = [
    ['left_segment_id', 'seg-z'],
    ['right_segment_id', 'seg-z'],
    ['left_source_sha256', '9'.repeat(64)],
    ['right_source_sha256', '8'.repeat(64)],
    ['cumulative_boundary_ms', 2_001],
  ];
  for (const [key, value] of mutations) {
    const changed = { ...argumentsByName, [key]: value };
    assert.notEqual(deriveBoundaryId(
      changed.left_segment_id,
      changed.right_segment_id,
      changed.left_source_sha256,
      changed.right_source_sha256,
      changed.cumulative_boundary_ms,
    ), first.boundary_id);
  }

  const plan = makePlan(manifest);
  plan.boundaries[0].boundary_id = `boundary-${'0'.repeat(64)}`;
  assert.throws(
    () => validateTransitionPlan(plan, manifest, makePolicy()),
    TransitionPlanError,
  );
});

test('missing, duplicate, reordered, and phantom boundaries fail closed', () => {
  const manifest = makeManifest();
  const policy = makePolicy();

  const missing = makePlan(manifest, policy);
  missing.boundaries.pop();
  assert.throws(() => validateTransitionPlan(missing, manifest, policy), TransitionPlanError);

  const duplicate = makePlan(manifest, policy);
  duplicate.boundaries.push(clone(duplicate.boundaries.at(-1)));
  assert.throws(() => validateTransitionPlan(duplicate, manifest, policy), TransitionPlanError);

  const reordered = makePlan(manifest, policy);
  [reordered.boundaries[0], reordered.boundaries[1]] = [
    reordered.boundaries[1], reordered.boundaries[0],
  ];
  assert.throws(() => validateTransitionPlan(reordered, manifest, policy), TransitionPlanError);

  const phantom = makePlan(manifest, policy);
  const last = manifest.segments.at(-1);
  const fake = makeSegment('seg-after-last', '9');
  phantom.boundaries.push(makeBoundary(last, fake, 8_000, {
    kind: 'hard_cut', durationMs: 0, motivation: 'motivated_only',
  }));
  assert.throws(() => validateTransitionPlan(phantom, manifest, policy), TransitionPlanError);
});

test('single segment requires an empty decision list', () => {
  const manifest = makeManifest();
  manifest.segments = manifest.segments.slice(0, 1);
  const policy = makePolicy();
  const plan = makePlan(manifest, policy, []);
  assert.deepEqual(validateTransitionPlan(plan, manifest, policy).boundaries, []);

  const other = makeSegment('seg-phantom', '9');
  plan.boundaries.push(makeBoundary(manifest.segments[0], other, 2_000, {
    kind: 'hard_cut', durationMs: 0, motivation: 'motivated_only',
  }));
  assert.throws(() => validateTransitionPlan(plan, manifest, policy), TransitionPlanError);
});

test('duration types, bounds, frame alignment, and dip symmetry are exact', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  for (const invalid of [-1, true, 200.5, MAX_TRANSITION_DURATION_MS + 1]) {
    const plan = makePlan(manifest, policy);
    plan.boundaries[0].duration_ms = invalid;
    assert.throws(() => validateTransitionPlan(plan, manifest, policy), TransitionPlanError);
  }

  for (const invalid of [33, 66, 401]) {
    const plan = makePlan(manifest, policy, [
      ['cross_dissolve', invalid], ['hard_cut', 0], ['hard_cut', 0],
    ]);
    assert.throws(() => validateTransitionPlan(plan, manifest, policy), TransitionPlanError);
  }
  assert.doesNotThrow(() => validateTransitionPlan(makePlan(manifest, policy, [
    ['cross_dissolve', 67], ['hard_cut', 0], ['hard_cut', 0],
  ]), manifest, policy));

  for (const invalid of [67, 100, 300]) {
    const plan = makePlan(manifest, policy, [
      ['dip_to_black', invalid], ['hard_cut', 0], ['hard_cut', 0],
    ]);
    assert.throws(() => validateTransitionPlan(plan, manifest, policy), TransitionPlanError);
  }
  assert.doesNotThrow(() => validateTransitionPlan(makePlan(manifest, policy, [
    ['dip_to_black', 200], ['hard_cut', 0], ['hard_cut', 0],
  ]), manifest, policy));
});

test('NTSC rational frame alignment matches Python integer half-up arithmetic', () => {
  const manifest = makeManifest({ numerator: 30_000, denominator: 1_001 });
  const policy = makePolicy();
  const valid = makePlan(manifest, policy, [
    ['cross_dissolve', 334], ['hard_cut', 0], ['hard_cut', 0],
  ]);
  assert.doesNotThrow(() => validateTransitionPlan(valid, manifest, policy));

  const invalid = clone(valid);
  invalid.boundaries[0].duration_ms = 333;
  assert.throws(() => validateTransitionPlan(invalid, manifest, policy), TransitionPlanError);

  const unreduced = makeManifest({ numerator: 60, denominator: 2 });
  assert.throws(() => validateTransitionSequenceManifest(unreduced), TransitionPlanError);
});

test('decoded video and audio handles, residual frames, and overlap fail independently', () => {
  const policy = makePolicy();
  for (const [segmentIndex, key] of [
    [0, 'video_trailing_handle_ms'],
    [1, 'video_leading_handle_ms'],
    [0, 'audio_trailing_handle_ms'],
    [1, 'audio_leading_handle_ms'],
  ]) {
    const manifest = makeManifest();
    manifest.segments[segmentIndex][key] = 399;
    assert.throws(
      () => validateTransitionPlan(makePlan(manifest, policy), manifest, policy),
      TransitionPlanError,
    );
  }

  const tooShort = makeManifest();
  tooShort.segments[0] = makeSegment('seg-a', 'a', {
    durationMs: 400,
    handlesMs: 400,
    dialogueAtEnd: true,
  });
  assert.throws(() => validateTransitionPlan(makePlan(tooShort, policy, [
    ['cross_dissolve', 400], ['hard_cut', 0], ['hard_cut', 0],
  ]), tooShort, policy), TransitionPlanError);

  const overlap = makeManifest();
  overlap.segments[1] = makeSegment('seg-b', 'b', {
    durationMs: 1_000,
    handlesMs: 1_000,
    dialogueAtStart: true,
  });
  assert.throws(() => validateTransitionPlan(makePlan(overlap, policy, [
    ['cross_dissolve', 600], ['cross_dissolve', 600], ['hard_cut', 0],
  ]), overlap, policy), TransitionPlanError);

  const exactConsumption = makeManifest();
  exactConsumption.segments[1] = makeSegment('seg-b', 'b', {
    durationMs: 800,
    handlesMs: 800,
    dialogueAtStart: true,
  });
  assert.throws(() => validateTransitionPlan(makePlan(exactConsumption, policy, [
    ['cross_dissolve', 400], ['cross_dissolve', 400], ['hard_cut', 0],
  ]), exactConsumption, policy), TransitionPlanError);

  const oneFrameRemains = makeManifest();
  oneFrameRemains.segments[1] = makeSegment('seg-b', 'b', {
    durationMs: 834,
    handlesMs: 834,
    dialogueAtStart: true,
  });
  assert.doesNotThrow(() => validateTransitionPlan(makePlan(oneFrameRemains, policy, [
    ['cross_dissolve', 400], ['cross_dissolve', 400], ['hard_cut', 0],
  ]), oneFrameRemains, policy));

  const ntscExactConsumption = makeManifest({ numerator: 30_000, denominator: 1_001 });
  ntscExactConsumption.segments[1] = makeSegment('seg-b', 'b', {
    durationMs: 668,
    handlesMs: 668,
    dialogueAtStart: true,
  });
  assert.throws(() => validateTransitionPlan(makePlan(ntscExactConsumption, policy, [
    ['cross_dissolve', 334], ['cross_dissolve', 334], ['hard_cut', 0],
  ]), ntscExactConsumption, policy), TransitionPlanError);

  const ntscOneFrameRemains = makeManifest({ numerator: 30_000, denominator: 1_001 });
  ntscOneFrameRemains.segments[1] = makeSegment('seg-b', 'b', {
    durationMs: 702,
    handlesMs: 702,
    dialogueAtStart: true,
  });
  assert.doesNotThrow(() => validateTransitionPlan(makePlan(ntscOneFrameRemains, policy, [
    ['cross_dissolve', 334], ['cross_dissolve', 334], ['hard_cut', 0],
  ]), ntscOneFrameRemains, policy));
});

test('policy usage, motivation, density ceiling, and cut-only behavior are bound', () => {
  assert.deepEqual(
    ['none', 'sparse', 'medium', 'dense'].map((density) => (
      densityTransitionLimit(density, 9)
    )),
    [0, 3, 5, 9],
  );
  const manifest = makeManifest();
  const cutOnly = makePolicy({ profile: 'utility_faithful' });
  const cuts = makePlan(manifest, cutOnly, [
    ['hard_cut', 0], ['hard_cut', 0], ['hard_cut', 0],
  ]);
  assert.deepEqual(validateTransitionPlan(cuts, manifest, cutOnly).policy, {
    density: 'none', usage: 'hard_cut_only',
  });
  assert.throws(() => validateTransitionPlan(makePlan(manifest, cutOnly, [
    ['cross_dissolve', 400], ['hard_cut', 0], ['hard_cut', 0],
  ]), manifest, cutOnly), TransitionPlanError);

  const sparse = makePolicy({ density: 'sparse' });
  assert.doesNotThrow(() => validateTransitionPlan(makePlan(manifest, sparse, [
    ['cross_dissolve', 400], ['hard_cut', 0], ['hard_cut', 0],
  ]), manifest, sparse));
  assert.throws(() => validateTransitionPlan(makePlan(manifest, sparse, [
    ['cross_dissolve', 400], ['cross_dissolve', 400], ['hard_cut', 0],
  ]), manifest, sparse), TransitionPlanError);

  const wrongMotivation = makePlan(manifest, makePolicy());
  wrongMotivation.boundaries[0].motivation = 'location_motivated';
  assert.throws(
    () => validateTransitionPlan(wrongMotivation, manifest, makePolicy()),
    TransitionPlanError,
  );
});

test('motivation, semantic, dialogue, kind, and audio safety flags fail closed', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  for (const key of [
    'motivation_verified',
    'semantic_safety_verified',
    'dialogue_preservation_verified',
  ]) {
    const plan = makePlan(manifest, policy);
    plan.boundaries[0][key] = false;
    assert.throws(() => validateTransitionPlan(plan, manifest, policy), TransitionPlanError);
  }
  for (const key of ['semantic_safety_verified', 'dialogue_preservation_verified']) {
    const plan = makePlan(manifest, policy);
    plan.boundaries[2][key] = false;
    assert.throws(() => validateTransitionPlan(plan, manifest, policy), TransitionPlanError);
  }

  const wrongAudio = makePlan(manifest, policy);
  wrongAudio.boundaries[0].audio_behavior = 'hard_cut';
  assert.throws(() => validateTransitionPlan(wrongAudio, manifest, policy), TransitionPlanError);

  const hardWithDuration = makePlan(manifest, policy);
  hardWithDuration.boundaries[2].duration_ms = 100;
  assert.throws(() => validateTransitionPlan(hardWithDuration, manifest, policy), TransitionPlanError);
});

test('compiler emits only exact inert video and equal-power audio primitive tokens', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const result = compileTransitionPlan(makePlan(manifest, policy), manifest, policy);
  const compiled = result.compiled_boundaries;

  assert.deepEqual(compiled[0].video_ffmpeg_primitive_tokens, [
    'xfade=transition=fade:duration=0.400:offset=1.600',
  ]);
  assert.deepEqual(compiled[0].audio_ffmpeg_primitive_tokens, [
    'acrossfade=d=0.400:o=1:c1=qsin:c2=qsin',
  ]);
  assert.equal(compiled[0].duration_frames, 12);
  assert.equal(compiled[0].dialogue_crossing, true);
  assert.deepEqual(compiled[1].video_ffmpeg_primitive_tokens, [
    'xfade=transition=fadeblack:duration=0.200:offset=3.400',
  ]);
  assert.equal(compiled[1].output_boundary_ms, 3_600);
  assert.deepEqual(compiled[2].video_ffmpeg_primitive_tokens, ['concat=n=2:v=1:a=0']);
  assert.deepEqual(compiled[2].audio_ffmpeg_primitive_tokens, ['concat=n=2:v=0:a=1']);
  assert.equal(result.receipt.schema_version, TRANSITION_COMPILE_RECEIPT_SCHEMA_VERSION);
  assert.equal(result.receipt.source_duration_ms, 8_000);
  assert.equal(result.receipt.output_duration_ms, 7_400);
  assert.equal(result.receipt.boundary_count, 3);
  assert.equal(result.receipt.non_hard_transition_count, 2);
  assert.deepEqual(result.receipt.time_base, { numerator: 1, denominator: 1_000 });

  const allTokens = compiled.flatMap((boundary) => [
    ...boundary.video_ffmpeg_primitive_tokens,
    ...boundary.audio_ffmpeg_primitive_tokens,
  ]);
  assert.equal(allTokens.some((token) => /\[[^\]]+\]|-i\s|[;&|`$]/.test(token)), false);
});

test('plan, manifest, and receipt hashes detect tampering', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const plan = makePlan(manifest, policy);
  const originalPlanHash = transitionPlanSha256(plan);

  const changedKind = clone(plan);
  changedKind.boundaries[0].kind = 'hard_cut';
  changedKind.boundaries[0].duration_ms = 0;
  changedKind.boundaries[0].audio_behavior = 'hard_cut';
  assert.notEqual(transitionPlanSha256(changedKind), originalPlanHash);

  const changedManifest = clone(manifest);
  changedManifest.segments[0].video_trailing_handle_ms -= 1;
  assert.notEqual(
    transitionSequenceManifestSha256(changedManifest),
    transitionSequenceManifestSha256(manifest),
  );

  const receipt = compileTransitionPlan(plan, manifest, policy).receipt;
  const originalReceiptHash = transitionCompileReceiptSha256(receipt);
  const changedReceipt = clone(receipt);
  changedReceipt.output_duration_ms += 1;
  assert.notEqual(transitionCompileReceiptSha256(changedReceipt), originalReceiptHash);
  const unknownReceipt = { ...receipt, extra: true };
  assert.throws(() => transitionCompileReceiptSha256(unknownReceipt), TransitionPlanError);
});

test('manifest is closed, ordered, uniquely identified, handle-bounded, and safe-integer bounded', () => {
  const manifest = makeManifest();
  const clean = validateTransitionSequenceManifest(manifest);
  assert.deepEqual(clean, manifest);
  assert.notEqual(clean, manifest);

  const invalidManifests = [];
  invalidManifests.push({ ...makeManifest(), generated_at: 'today' });
  const segmentExtra = makeManifest();
  segmentExtra.segments[0].extra = true;
  invalidManifests.push(segmentExtra);
  const duplicate = makeManifest();
  duplicate.segments[1].segment_id = 'seg-a';
  invalidManifests.push(duplicate);
  const badHandle = makeManifest();
  badHandle.segments[0].video_leading_handle_ms = 2_001;
  invalidManifests.push(badHandle);
  const boolDuration = makeManifest();
  boolDuration.segments[0].duration_ms = true;
  invalidManifests.push(boolDuration);
  const overflow = makeManifest();
  overflow.segments = [
    makeSegment('seg-a', 'a', { durationMs: Number.MAX_SAFE_INTEGER, handlesMs: 0 }),
    makeSegment('seg-b', 'b', { durationMs: 1, handlesMs: 0 }),
  ];
  invalidManifests.push(overflow);

  for (const invalid of invalidManifests) {
    assert.throws(() => validateTransitionSequenceManifest(invalid), TransitionPlanError);
  }

  const reordered = makeManifest();
  [reordered.segments[0], reordered.segments[1]] = [
    reordered.segments[1], reordered.segments[0],
  ];
  assert.notEqual(
    transitionSequenceManifestSha256(reordered),
    transitionSequenceManifestSha256(manifest),
  );
});

test('closed schemas reject unknown keys, sparse arrays, invalid enums, and loose booleans', () => {
  const manifest = makeManifest();
  const policy = makePolicy();
  const invalidPlans = [];
  invalidPlans.push({ ...makePlan(manifest, policy), comment: 'unknown' });
  const frameExtra = makePlan(manifest, policy);
  frameExtra.frame_rate.drop_frame = false;
  invalidPlans.push(frameExtra);
  const badKind = makePlan(manifest, policy);
  badKind.boundaries[0].kind = 'spin';
  invalidPlans.push(badKind);
  const badMotivation = makePlan(manifest, policy);
  badMotivation.boundaries[0].motivation = 'random';
  invalidPlans.push(badMotivation);
  const badAudio = makePlan(manifest, policy);
  badAudio.boundaries[0].audio_behavior = 'drop_audio';
  invalidPlans.push(badAudio);
  const looseBool = makePlan(manifest, policy);
  looseBool.boundaries[0].semantic_safety_verified = 1;
  invalidPlans.push(looseBool);
  const sparse = makePlan(manifest, policy);
  delete sparse.boundaries[1];
  invalidPlans.push(sparse);

  for (const invalid of invalidPlans) {
    assert.throws(() => validateTransitionPlan(invalid, manifest, policy), TransitionPlanError);
  }
  assert.deepEqual(TRANSITION_KINDS, ['cross_dissolve', 'dip_to_black', 'hard_cut']);
  assert.deepEqual(AUDIO_BEHAVIORS, ['equal_power_crossfade', 'hard_cut']);
  assert.deepEqual(MOTIVATIONS, [
    'beat_or_phrase_motivated',
    'continuity_motivated',
    'location_motivated',
    'motivated_only',
  ]);
});

test('advertised JSON Schema matches the same exact closed surface', () => {
  const schema = TRANSITION_PLAN_JSON_SCHEMA;
  assert.equal(schema.additionalProperties, false);
  assert.equal(schema.properties.schema_version.const, TRANSITION_PLAN_SCHEMA_VERSION);
  assert.equal(schema.properties.boundaries.maxItems, 255);
  assert.equal(schema.properties.boundaries.items.additionalProperties, false);
  const properties = schema.properties.boundaries.items.properties;
  assert.equal(properties.duration_ms.maximum, 1_000);
  assert.deepEqual(properties.kind.enum, ['cross_dissolve', 'dip_to_black', 'hard_cut']);
  assert.deepEqual(properties.motivation.enum, [
    'beat_or_phrase_motivated',
    'continuity_motivated',
    'location_motivated',
    'motivated_only',
  ]);
  assert.equal(
    crypto.createHash('sha256').update(canonicalSchemaJson(schema), 'utf8').digest('hex'),
    PYTHON_VECTOR.schema_sha256,
  );
});
