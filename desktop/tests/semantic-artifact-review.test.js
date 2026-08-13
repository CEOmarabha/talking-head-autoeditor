'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  CALIBRATED_REVIEW_SCHEMA,
  MAX_SEMANTIC_REVIEW_ASSERTIONS,
  MAX_SEMANTIC_REVIEW_FRAMES,
  MAX_SEMANTIC_REVIEW_MODEL_CALLS,
  SEMANTIC_COVERAGE_SCHEMA,
  calibratedSemanticReviewPasses,
  reviewArtifactFramesCalibrated,
  reviewPasses,
} = require('../helper/lib/artifact-quality');
const {
  MODEL_DTYPE,
  MODEL_ID,
  MODEL_PACK_LOCK_SHA256,
  MODEL_PACK_TREE_SHA256,
  MODEL_REVISION,
  VISION_RUNTIME_LOCK_SHA256,
} = require('../helper/lib/vision-model-pack');

const CANDIDATE_TOKEN_IDS = Object.freeze({ A: [49], B: [50], U: [69] });
const THRESHOLDS = Object.freeze({
  minimum_margin_ppm: 350_000,
  minimum_selected_score_ppm: 650_000,
});
const RUNTIME = Object.freeze({
  backend: 'wasm',
  model_dtype: MODEL_DTYPE,
  model_id: MODEL_ID,
  model_pack_lock_sha256: MODEL_PACK_LOCK_SHA256,
  model_pack_tree_sha256: MODEL_PACK_TREE_SHA256,
  model_revision: MODEL_REVISION,
  remote_requests: 0,
  schema_version: 'autoeditor-local-vision-worker-runtime/v1',
});
const AFFIRMED = Object.freeze({
  forward: { label: 'A', scores_ppm: { A: 820_000, B: 100_000, U: 80_000 } },
  reverse: { label: 'B', scores_ppm: { A: 100_000, B: 820_000, U: 80_000 } },
});
const CONTRADICTED = Object.freeze({
  forward: { label: 'B', scores_ppm: { A: 100_000, B: 820_000, U: 80_000 } },
  reverse: { label: 'A', scores_ppm: { A: 820_000, B: 100_000, U: 80_000 } },
});
const ABSTAINED = Object.freeze({
  forward: { label: 'U', scores_ppm: { A: 80_000, B: 100_000, U: 820_000 } },
  reverse: { label: 'U', scores_ppm: { A: 80_000, B: 100_000, U: 820_000 } },
});

function fixture(root, index, settings = {}) {
  const {
    category = 'title', kind, targetId = `target-${index}`,
  } = settings;
  const expectation = Object.prototype.hasOwnProperty.call(
    settings, 'expectation')
    ? settings.expectation
    : 'A professional title is fully visible and legible.';
  const bytes = Buffer.from([
    0xff, 0xd8, ...Buffer.from(`closed-frame-${index}`), 0xff, 0xd9,
  ]);
  const file = path.join(root, `frame-${index}.jpg`);
  fs.writeFileSync(file, bytes);
  const target = { category, id: targetId };
  if (expectation !== undefined) target.expectation = expectation;
  if (kind !== undefined) target.kind = kind;
  return {
    id: `frame-${index}`,
    path: file,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    size_bytes: bytes.length,
    targets: [target],
    timeSeconds: index / 4,
  };
}

function options(requestAssertion) {
  return {
    artifactSha256: 'a'.repeat(64),
    candidateTokenIds: CANDIDATE_TOKEN_IDS,
    captionDelivery: 'burned',
    modelSha256: MODEL_PACK_TREE_SHA256,
    requestAssertion,
    runtimeSha256: VISION_RUNTIME_LOCK_SHA256,
    thresholds: THRESHOLDS,
  };
}

function responseFor(descriptor, overrides = {}) {
  const outcome = overrides[descriptor.assertionKey] || AFFIRMED;
  return {
    result: JSON.stringify(outcome[descriptor.attemptId]),
    runtime: { ...RUNTIME },
  };
}

async function main() {
  assert.equal(MAX_SEMANTIC_REVIEW_FRAMES, 16);
  assert.equal(MAX_SEMANTIC_REVIEW_ASSERTIONS, 24);
  assert.equal(MAX_SEMANTIC_REVIEW_MODEL_CALLS, 48);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'semantic-artifact-review-'));
  try {
    const frame = fixture(root, 1, {
      targetId: 'trusted-target-id-never-sent-to-model',
    });
    const calls = [];
    const passed = await reviewArtifactFramesCalibrated([frame], options(
      async (boundFrame, invocation, descriptor) => {
        calls.push({ boundFrame, invocation, descriptor });
        assert.equal(boundFrame, frame);
        assert.deepEqual(Object.keys(invocation).sort(), ['mode', 'model_request']);
        assert.equal(invocation.mode, 'artifact-assertion');
        assert.deepEqual(Object.keys(invocation.model_request).sort(),
          ['candidate_token_ids', 'candidates', 'prompt']);
        assert.equal(invocation.model_request.prompt.includes(frame.targets[0].id),
          false, 'trusted target IDs must remain outside the model request');
        for (const value of [frame.sha256, MODEL_PACK_TREE_SHA256,
          VISION_RUNTIME_LOCK_SHA256, descriptor.targetSha256]) {
          assert.equal(invocation.model_request.prompt.includes(value), false);
        }
        return responseFor(descriptor);
      },
    ));
    assert.equal(calls.length, 6);
    assert.deepEqual(calls.map(({ descriptor }) => descriptor.assertionKey),
      ['target', 'target', 'graphics', 'graphics',
        'productionDesign', 'productionDesign']);
    assert.equal(calls.some(({ descriptor }) =>
      ['transitions', 'visualVariety'].includes(descriptor.assertionKey)), false);
    assert.equal(passed.review.schema, CALIBRATED_REVIEW_SCHEMA);
    assert.equal(passed.review.pass, true);
    assert.equal(passed.review.semanticPass, true);
    assert.equal(passed.review.score, 100);
    assert.equal(calibratedSemanticReviewPasses(passed.review), true);
    assert.equal(reviewPasses(passed.review), true);
    assert.deepEqual(passed.reviewedFrameIds, [frame.id]);
    assert.deepEqual(passed.reviewedTargetIds, [frame.targets[0].id]);
    assert.deepEqual(passed.review.observedTargetIds, [frame.targets[0].id]);
    assert.deepEqual(passed.runtime, RUNTIME);
    assert.equal(passed.review.checks.graphics, true);
    assert.equal(passed.review.checks.productionDesign, true);
    assert.equal(passed.review.checks.transitions, false);
    assert.equal(passed.review.checks.visualVariety, false);
    assert.equal(passed.coverage.schema, SEMANTIC_COVERAGE_SCHEMA);
    assert.equal(passed.coverage.complete, true);
    assert.equal(passed.coverage.assertionCount, 3);
    assert.equal(passed.coverage.modelCallCount, 6);
    assert.deepEqual(passed.coverage.limits, {
      maximumAssertions: 24, maximumFrames: 16, maximumModelCalls: 48,
    });
    for (const key of ['transitions', 'visualVariety']) {
      assert.deepEqual(passed.review.applicability[key], {
        applicable: false,
        evaluated: false,
        frameIds: [],
        reason: 'requires_sequence_evidence',
        targetIds: [],
      });
    }
    const semanticReceipts = passed.batches[0].semanticReceipts;
    assert.equal(semanticReceipts.length, 3);
    for (const item of semanticReceipts) {
      const identity = item.receipt.plan.evidence_identity;
      assert.equal(identity.artifact_sha256, 'a'.repeat(64));
      assert.equal(identity.frame_sha256, frame.sha256);
      assert.equal(identity.model_sha256, MODEL_PACK_TREE_SHA256);
      assert.equal(identity.runtime_sha256, VISION_RUNTIME_LOCK_SHA256);
      assert.equal(identity.target_sha256, item.targetSha256);
      assert.match(item.receiptSha256, /^[0-9a-f]{64}$/);
      assert.equal(item.receipt.decision.semantic_outcome, 'affirmed');
    }

    const captionFrame = fixture(root, 2, {
      category: 'captions',
      expectation: 'The burned caption is fully visible and readable.',
      targetId: 'caption-target',
    });
    const defect = await reviewArtifactFramesCalibrated([captionFrame], options(
      async (_boundFrame, _invocation, descriptor) => responseFor(
        descriptor, { captions: CONTRADICTED }),
    ));
    assert.equal(defect.review.pass, false);
    assert.equal(defect.review.semanticPass, false);
    assert.equal(defect.review.checks.captions, false);
    assert.equal(defect.review.applicability.captions.applicable, true);
    assert.match(defect.review.issues.join(' '), /caption or text quality failed/i);
    assert.deepEqual(defect.reviewedTargetIds, [captionFrame.targets[0].id]);

    const uncertain = await reviewArtifactFramesCalibrated([captionFrame], options(
      async (_boundFrame, _invocation, descriptor) => responseFor(
        descriptor, { productionDesign: ABSTAINED }),
    ));
    assert.equal(uncertain.review.pass, false);
    assert.equal(uncertain.review.checks.productionDesign, false);
    assert.match(uncertain.review.issues.join(' '),
      /insufficient.*productionDesign/i);

    const positionBiased = await reviewArtifactFramesCalibrated([frame], options(
      async (_boundFrame, _invocation, descriptor) => {
        if (descriptor.assertionKey !== 'graphics') return responseFor(descriptor);
        return {
          result: JSON.stringify(AFFIRMED.forward),
          runtime: { ...RUNTIME },
        };
      },
    ));
    assert.equal(positionBiased.review.pass, false);
    assert.equal(positionBiased.review.checks.graphics, false);
    const graphicsReceipt = positionBiased.batches[0].semanticReceipts.find(
      (item) => item.key === 'graphics');
    assert.equal(graphicsReceipt.receipt.decision.reason,
      'semantic_disagreement');
    assert.equal(graphicsReceipt.receipt.decision.status, 'abstained');

    const anchor = fixture(root, 3, {
      category: 'timeline', expectation: undefined, kind: 'anchor',
      targetId: 'non-semantic-anchor',
    });
    const transition = fixture(root, 4, {
      category: 'transitions',
      expectation: '{"layer":"transitions","type":"crossfade"}',
      kind: 'transition-boundary', targetId: 'temporal-transition',
    });
    const graphics = fixture(root, 5, {
      category: 'graphics', expectation: 'A chart is visible and legible.',
      targetId: 'evidence-graphic',
    });
    const captions = fixture(root, 6, {
      category: 'captions', expectation: 'The caption is visibly readable.',
      targetId: 'evidence-caption',
    });
    const selectedCalls = [];
    const selected = await reviewArtifactFramesCalibrated(
      [anchor, transition, graphics, captions], options(
        async (boundFrame, _invocation, descriptor) => {
          selectedCalls.push({ frameId: boundFrame.id, descriptor });
          return responseFor(descriptor);
        }),
    );
    assert.deepEqual(selected.coverage.selectedFrameIds,
      [graphics.id, captions.id]);
    assert.deepEqual(selected.coverage.requiredTargetIds,
      ['evidence-graphic', 'evidence-caption']);
    assert.deepEqual(selected.reviewedTargetIds,
      selected.coverage.requiredTargetIds);
    assert.deepEqual(selected.coverage.skippedFrames.map((entry) => ({
      frameId: entry.frameId, reason: entry.reason,
    })), [anchor, transition].map((entry) => ({
      frameId: entry.id, reason: 'no_supported_visible_target_expectation',
    })));
    assert.equal(selectedCalls.some(({ descriptor }) =>
      ['transitions', 'visualVariety'].includes(descriptor.assertionKey)), false);

    const maximumFrames = Array.from({ length: 8 }, (_unused, index) =>
      fixture(root, 20 + index, {
        category: 'title', targetId: `bounded-target-${index}`,
      }));
    let boundedCalls = 0;
    const bounded = await reviewArtifactFramesCalibrated(maximumFrames, options(
      async (_boundFrame, _invocation, descriptor) => {
        boundedCalls += 1;
        return responseFor(descriptor);
      },
    ));
    assert.equal(bounded.coverage.assertionCount,
      MAX_SEMANTIC_REVIEW_ASSERTIONS);
    assert.equal(boundedCalls, MAX_SEMANTIC_REVIEW_MODEL_CALLS);
    assert.deepEqual(bounded.reviewedTargetIds,
      maximumFrames.map((item) => item.targets[0].id));
    assert.equal(bounded.coverage.complete, true);

    const tooManyAssertions = [...maximumFrames, fixture(root, 40, {
      category: 'title', targetId: 'over-assertion-limit',
    })];
    let overLimitCalls = 0;
    await assert.rejects(reviewArtifactFramesCalibrated(
      tooManyAssertions, options(async () => {
        overLimitCalls += 1;
        return assert.fail('limit failures must precede model execution');
      })), /24-assertion hard limit/);
    assert.equal(overLimitCalls, 0);

    const tooManyFrames = Array.from({ length: 17 }, (_unused, index) =>
      fixture(root, 50 + index, {
        category: 'custom-visible-class',
        expectation: `Visible required target ${index}.`,
        targetId: `frame-limit-target-${index}`,
      }));
    await assert.rejects(reviewArtifactFramesCalibrated(
      tooManyFrames, options(async () => assert.fail(
        'frame-limit failures must precede model execution'))),
    /16-frame hard limit/);

    await assert.rejects(reviewArtifactFramesCalibrated([anchor, transition],
      options(async () => assert.fail('unsupported targets must not be sent'))),
    /no evidence-bearing visible targets/);

    let runtimeCall = 0;
    await assert.rejects(reviewArtifactFramesCalibrated([frame], options(
      async (_boundFrame, _invocation, descriptor) => {
        runtimeCall += 1;
        const response = responseFor(descriptor);
        if (runtimeCall === 2) response.runtime.backend = 'webgpu';
        return response;
      },
    )), /runtime changed during review/);

    await assert.rejects(reviewArtifactFramesCalibrated([frame], options(
      async (_boundFrame, _invocation, descriptor) => ({
        ...responseFor(descriptor),
        result: JSON.stringify({
          ...AFFIRMED[descriptor.attemptId],
          target_sha256: descriptor.targetSha256,
        }),
      }),
    )), /unsupported target_sha256/);

    const tampered = { ...frame, sha256: '0'.repeat(64) };
    await assert.rejects(reviewArtifactFramesCalibrated([tampered], options(
      async () => assert.fail('a drifted frame must fail before model execution'),
    )), /frame identity drifted/);

    await assert.rejects(reviewArtifactFramesCalibrated([frame], {
      ...options(async () => assert.fail()),
      thresholds: {
        ...THRESHOLDS,
        minimum_selected_score_ppm: THRESHOLDS.minimum_selected_score_ppm - 1,
      },
    }), /configuration is invalid/,
    'production and qualification must use one pinned operating point');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
  console.log('bounded calibrated semantic artifact-review tests passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
