'use strict';

const assert = require('node:assert/strict');
const {
  CALIBRATED_REVIEW_SCHEMA,
  MAX_SEMANTIC_REVIEW_ASSERTIONS,
  MAX_SEMANTIC_REVIEW_FRAMES,
  MAX_SEMANTIC_REVIEW_MODEL_CALLS,
  SEMANTIC_COVERAGE_SCHEMA,
} = require('../helper/lib/artifact-quality');
const {
  PROMOTION_GATE_SCHEMA_VERSION,
  assertCalibratedSemanticPromotionGate,
  sha256Stable,
} = require('../helper/lib/calibrated-semantic-promotion-gate');
const {
  BACKENDS,
  RESULT_SCHEMA_VERSION: QUALIFICATION_RESULT_SCHEMA_VERSION,
} = require('../helper/lib/semantic-visual-qualification');
const {
  MODEL_DTYPE,
  MODEL_ID,
  MODEL_PACK_LOCK_SHA256,
  MODEL_PACK_TREE_SHA256,
  MODEL_REVISION,
  VISION_RUNTIME_LOCK_SHA256,
} = require('../helper/lib/vision-model-pack');

const FRAME_SHA256 = '1'.repeat(64);
const ARTIFACT_SHA256 = 'a'.repeat(64);
const FRAME = Object.freeze({
  id: 'semantic-frame-001', sha256: FRAME_SHA256, size_bytes: 4096,
});

function applicability() {
  const notApplicable = (reason = 'target_category_not_applicable') => ({
    applicable: false, evaluated: false, frameIds: [], reason, targetIds: [],
  });
  return {
    target: {
      applicable: true,
      evaluated: true,
      frameIds: [FRAME.id],
      reason: 'concrete_visible_target_expectation',
      targetIds: ['semantic-target-001'],
    },
    captions: notApplicable(),
    framing: notApplicable(),
    visualVariety: notApplicable('requires_sequence_evidence'),
    graphics: notApplicable(),
    transitions: notApplicable('requires_sequence_evidence'),
    productionDesign: notApplicable(),
  };
}

function passingCoverage() {
  return {
    applicability: applicability(),
    assertionCount: 1,
    complete: true,
    limits: {
      maximumAssertions: MAX_SEMANTIC_REVIEW_ASSERTIONS,
      maximumFrames: MAX_SEMANTIC_REVIEW_FRAMES,
      maximumModelCalls: MAX_SEMANTIC_REVIEW_MODEL_CALLS,
    },
    modelCallCount: 2,
    requiredTargetIds: ['semantic-target-001'],
    reviewedFrameIds: [FRAME.id],
    reviewedTargetIds: ['semantic-target-001'],
    schema: SEMANTIC_COVERAGE_SCHEMA,
    selectedFrameIds: [FRAME.id],
    skippedFrames: [],
  };
}

function passingReview(coverage) {
  return {
    applicability: coverage.applicability,
    checks: {
      captions: false,
      framing: false,
      visualVariety: false,
      graphics: false,
      transitions: false,
      productionDesign: false,
    },
    coverage,
    issues: [],
    observedTargetIds: ['semantic-target-001'],
    pass: true,
    schema: CALIBRATED_REVIEW_SCHEMA,
    score: 100,
    semanticPass: true,
    valid: true,
  };
}

function passingInput() {
  const coverage = passingCoverage();
  return {
    artifact: {
      before: { sha256: ARTIFACT_SHA256, size_bytes: 8_000_000 },
      after: { sha256: ARTIFACT_SHA256, size_bytes: 8_000_000 },
    },
    capability: {
      available: true,
      capability: 'visual_quality_analysis',
      capabilityManifestSha256: 'b'.repeat(64),
      capabilityProbeReceiptSha256: 'c'.repeat(64),
      modelSha256: MODEL_PACK_TREE_SHA256,
      qualificationResultSha256: 'd'.repeat(64),
      qualificationSchema: QUALIFICATION_RESULT_SCHEMA_VERSION,
      qualified: true,
      qualifiedBackends: [...BACKENDS],
      runtimeSha256: VISION_RUNTIME_LOCK_SHA256,
    },
    capture: {
      complete: true,
      frames: [{ ...FRAME }],
    },
    network: {
      attemptedRequests: 0,
      enforced: true,
      scope: 'electron-session',
    },
    semantic: {
      artifactSha256: ARTIFACT_SHA256,
      coverage,
      frames: [{ ...FRAME }],
      modelSha256: MODEL_PACK_TREE_SHA256,
      review: passingReview(coverage),
      runtime: {
        backend: 'wasm',
        model_dtype: MODEL_DTYPE,
        model_id: MODEL_ID,
        model_pack_lock_sha256: MODEL_PACK_LOCK_SHA256,
        model_pack_tree_sha256: MODEL_PACK_TREE_SHA256,
        model_revision: MODEL_REVISION,
        remote_requests: 0,
        schema_version: 'autoeditor-local-vision-worker-runtime/v1',
      },
      runtimeSha256: VISION_RUNTIME_LOCK_SHA256,
    },
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function main() {
  const exact = passingInput();
  const receipt = assertCalibratedSemanticPromotionGate(exact);
  assert.deepEqual(Object.keys(receipt).sort(), [
    'artifactSha256', 'calibratedReviewSha256',
    'capabilityManifestSha256', 'capabilityProbeReceiptSha256',
    'captureFrameSetSha256', 'coverageSha256', 'modelSha256',
    'networkScope', 'pass', 'qualificationResultSha256',
    'runtimeEvidenceSha256', 'runtimeSha256', 'schemaVersion',
    'semanticFrameSetSha256',
  ].sort());
  assert.equal(receipt.schemaVersion, PROMOTION_GATE_SCHEMA_VERSION);
  assert.equal(receipt.pass, true);
  assert.equal(receipt.artifactSha256, ARTIFACT_SHA256);
  assert.equal(receipt.modelSha256, MODEL_PACK_TREE_SHA256);
  assert.equal(receipt.runtimeSha256, VISION_RUNTIME_LOCK_SHA256);
  assert.equal(receipt.networkScope, 'electron-session');
  assert.equal(receipt.calibratedReviewSha256,
    sha256Stable(exact.semantic.review));
  assert.equal(receipt.coverageSha256,
    sha256Stable(exact.semantic.coverage));
  assert.equal(Object.isFrozen(receipt), true);
  assert.deepEqual(assertCalibratedSemanticPromotionGate(passingInput()), receipt,
    'the exact promotion receipt must be deterministic');

  const frameDrift = clone(passingInput());
  frameDrift.semantic.frames[0].sha256 = '2'.repeat(64);
  assert.throws(() => assertCalibratedSemanticPromotionGate(frameDrift),
    /semantic frame identity drifted/);

  const runtimeDrift = clone(passingInput());
  runtimeDrift.semantic.runtime.model_pack_tree_sha256 = '3'.repeat(64);
  assert.throws(() => assertCalibratedSemanticPromotionGate(runtimeDrift),
    /worker runtime identity drifted/);

  const hostRuntimeDrift = clone(passingInput());
  hostRuntimeDrift.semantic.runtimeSha256 = '4'.repeat(64);
  assert.throws(() => assertCalibratedSemanticPromotionGate(hostRuntimeDrift),
    /host runtime identity drifted/);

  const incompleteSemantic = clone(passingInput());
  incompleteSemantic.semantic.coverage.complete = false;
  incompleteSemantic.semantic.review.coverage.complete = false;
  assert.throws(() => assertCalibratedSemanticPromotionGate(incompleteSemantic),
    /semantic coverage is incomplete/);

  const incompleteCapture = clone(passingInput());
  incompleteCapture.capture.complete = false;
  assert.throws(() => assertCalibratedSemanticPromotionGate(incompleteCapture),
    /frame capture coverage is incomplete/);

  const unqualified = clone(passingInput());
  unqualified.capability.qualified = false;
  assert.throws(() => assertCalibratedSemanticPromotionGate(unqualified),
    /not qualified/);

  const networkAttempt = clone(passingInput());
  networkAttempt.network.attemptedRequests = 1;
  assert.throws(() => assertCalibratedSemanticPromotionGate(networkAttempt),
    /network request/);

  const workerNetworkAttempt = clone(passingInput());
  workerNetworkAttempt.semantic.runtime.remote_requests = 1;
  assert.throws(() => assertCalibratedSemanticPromotionGate(
    workerNetworkAttempt), /worker runtime identity drifted/);

  const artifactDrift = clone(passingInput());
  artifactDrift.artifact.after.sha256 = '5'.repeat(64);
  assert.throws(() => assertCalibratedSemanticPromotionGate(artifactDrift),
    /artifact identity drifted/);

  const rejectedReview = clone(passingInput());
  rejectedReview.semantic.review.pass = false;
  rejectedReview.semantic.review.semanticPass = false;
  rejectedReview.semantic.review.score = 0;
  rejectedReview.semantic.review.issues = ['visible target was contradicted'];
  assert.throws(() => assertCalibratedSemanticPromotionGate(rejectedReview),
    /did not pass its closed gate/);

  console.log('calibrated semantic promotion-gate adapter tests passed');
}

main();
