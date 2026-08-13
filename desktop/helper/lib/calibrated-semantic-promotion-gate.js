'use strict';

const crypto = require('node:crypto');
const {
  CALIBRATED_REVIEW_SCHEMA,
  SEMANTIC_COVERAGE_SCHEMA,
  calibratedSemanticReviewPasses,
} = require('./artifact-quality');
const {
  BACKENDS,
  RESULT_SCHEMA_VERSION: QUALIFICATION_RESULT_SCHEMA_VERSION,
} = require('./semantic-visual-qualification');
const {
  MODEL_DTYPE,
  MODEL_ID,
  MODEL_PACK_LOCK_SHA256,
  MODEL_PACK_TREE_SHA256,
  MODEL_REVISION,
  VISION_RUNTIME_LOCK_SHA256,
} = require('./vision-model-pack');

const PROMOTION_GATE_SCHEMA_VERSION =
  'autoeditor-calibrated-semantic-promotion-gate/v1';
const WORKER_RUNTIME_SCHEMA_VERSION =
  'autoeditor-local-vision-worker-runtime/v1';
const CAPABILITY = 'visual_quality_analysis';
const SHA256 = /^[0-9a-f]{64}$/;
const MAX_CAPTURE_FRAMES = 128;
const MAX_SEMANTIC_FRAMES = 16;

class CalibratedSemanticPromotionGateError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CalibratedSemanticPromotionGateError';
  }
}

function fail(message) {
  throw new CalibratedSemanticPromotionGateError(message);
}

function plainRecord(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value));
}

function exactKeys(value, keys, label) {
  if (!plainRecord(value) ||
      Reflect.ownKeys(value).some((key) => typeof key !== 'string') ||
      Object.keys(value).sort().join('\0') !== [...keys].sort().join('\0')) {
    fail(`${label} is invalid`);
  }
  return value;
}

function stableJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
}

function sha256Stable(value) {
  return crypto.createHash('sha256').update(stableJson(value), 'utf8')
    .digest('hex');
}

function exactStringArray(value, label, maximum = MAX_CAPTURE_FRAMES) {
  if (!Array.isArray(value) || value.length < 1 || value.length > maximum ||
      value.some((item) => typeof item !== 'string' || !item ||
        item.length > 100) || new Set(value).size !== value.length) {
    fail(`${label} is invalid`);
  }
  return value;
}

function exactFrameBindings(value, label, maximum) {
  if (!Array.isArray(value) || value.length < 1 || value.length > maximum) {
    fail(`${label} is invalid`);
  }
  const ids = new Set();
  return value.map((frame, index) => {
    exactKeys(frame, ['id', 'sha256', 'size_bytes'], `${label}[${index}]`);
    if (typeof frame.id !== 'string' || !frame.id || frame.id.length > 100 ||
        ids.has(frame.id) || !SHA256.test(frame.sha256 || '') ||
        !Number.isSafeInteger(frame.size_bytes) || frame.size_bytes < 4 ||
        frame.size_bytes > 16 * 1024 * 1024) {
      fail(`${label}[${index}] is invalid`);
    }
    ids.add(frame.id);
    return Object.freeze({
      id: frame.id, sha256: frame.sha256, size_bytes: frame.size_bytes,
    });
  });
}

function exactArtifactIdentity(value, label) {
  exactKeys(value, ['sha256', 'size_bytes'], label);
  if (!SHA256.test(value.sha256 || '') ||
      !Number.isSafeInteger(value.size_bytes) || value.size_bytes < 1) {
    fail(`${label} is invalid`);
  }
  return value;
}

function sameArray(left, right) {
  return Array.isArray(left) && Array.isArray(right) &&
    left.length === right.length && left.every(
      (value, index) => value === right[index]);
}

function validateCapability(value) {
  exactKeys(value, [
    'available', 'capability', 'capabilityManifestSha256',
    'capabilityProbeReceiptSha256', 'modelSha256',
    'qualificationResultSha256', 'qualificationSchema', 'qualified',
    'qualifiedBackends', 'runtimeSha256',
  ], 'semantic capability authorization');
  if (value.available !== true || value.qualified !== true ||
      value.capability !== CAPABILITY ||
      value.qualificationSchema !== QUALIFICATION_RESULT_SCHEMA_VERSION ||
      value.modelSha256 !== MODEL_PACK_TREE_SHA256 ||
      value.runtimeSha256 !== VISION_RUNTIME_LOCK_SHA256 ||
      ![value.capabilityManifestSha256,
        value.capabilityProbeReceiptSha256,
        value.qualificationResultSha256].every((hash) => SHA256.test(hash || '')) ||
      !sameArray(value.qualifiedBackends, BACKENDS)) {
    fail('semantic capability is unavailable or not qualified');
  }
  return value;
}

function validateNetwork(value) {
  exactKeys(value, [
    'attemptedRequests', 'enforced', 'scope',
  ], 'semantic network evidence');
  if (value.enforced !== true || value.scope !== 'electron-session' ||
      !Number.isSafeInteger(value.attemptedRequests) ||
      value.attemptedRequests !== 0) {
    fail('semantic runtime made or did not prevent a network request');
  }
  return value;
}

function validateRuntime(value, capability, semantic) {
  exactKeys(value, [
    'backend', 'model_dtype', 'model_id', 'model_pack_lock_sha256',
    'model_pack_tree_sha256', 'model_revision', 'remote_requests',
    'schema_version',
  ], 'semantic worker runtime');
  if (value.schema_version !== WORKER_RUNTIME_SCHEMA_VERSION ||
      value.model_id !== MODEL_ID || value.model_revision !== MODEL_REVISION ||
      value.model_dtype !== MODEL_DTYPE ||
      value.model_pack_lock_sha256 !== MODEL_PACK_LOCK_SHA256 ||
      value.model_pack_tree_sha256 !== MODEL_PACK_TREE_SHA256 ||
      value.model_pack_tree_sha256 !== capability.modelSha256 ||
      semantic.modelSha256 !== value.model_pack_tree_sha256 ||
      semantic.runtimeSha256 !== capability.runtimeSha256 ||
      semantic.runtimeSha256 !== VISION_RUNTIME_LOCK_SHA256 ||
      !capability.qualifiedBackends.includes(value.backend) ||
      value.remote_requests !== 0) {
    fail('semantic worker runtime identity drifted');
  }
  return value;
}

function validateCoverage(value, review, semanticFrames) {
  exactKeys(value, [
    'applicability', 'assertionCount', 'complete', 'limits',
    'modelCallCount', 'requiredTargetIds', 'reviewedFrameIds',
    'reviewedTargetIds', 'schema', 'selectedFrameIds', 'skippedFrames',
  ], 'calibrated semantic coverage');
  if (value.schema !== SEMANTIC_COVERAGE_SCHEMA || value.complete !== true) {
    fail('calibrated semantic coverage is incomplete');
  }
  const semanticFrameIds = semanticFrames.map((frame) => frame.id);
  exactStringArray(value.selectedFrameIds,
    'calibrated semantic selected frames', MAX_SEMANTIC_FRAMES);
  exactStringArray(value.reviewedFrameIds,
    'calibrated semantic reviewed frames', MAX_SEMANTIC_FRAMES);
  exactStringArray(value.requiredTargetIds,
    'calibrated semantic required targets');
  exactStringArray(value.reviewedTargetIds,
    'calibrated semantic reviewed targets');
  if (!sameArray(value.selectedFrameIds, semanticFrameIds) ||
      !sameArray(value.reviewedFrameIds, semanticFrameIds) ||
      !sameArray(value.requiredTargetIds, value.reviewedTargetIds) ||
      !sameArray(review.observedTargetIds, value.reviewedTargetIds) ||
      stableJson(review.coverage) !== stableJson(value)) {
    fail('calibrated semantic coverage binding drifted');
  }
  return value;
}

function assertCalibratedSemanticPromotionGate(input) {
  exactKeys(input, [
    'artifact', 'capability', 'capture', 'network', 'semantic',
  ], 'calibrated semantic promotion input');
  exactKeys(input.artifact, ['after', 'before'], 'artifact evidence');
  const artifactBefore = exactArtifactIdentity(
    input.artifact.before, 'artifact identity before semantic review');
  const artifactAfter = exactArtifactIdentity(
    input.artifact.after, 'artifact identity after semantic review');
  if (stableJson(artifactBefore) !== stableJson(artifactAfter)) {
    fail('artifact identity drifted during semantic review');
  }

  const capability = validateCapability(input.capability);
  validateNetwork(input.network);
  exactKeys(input.capture, ['complete', 'frames'], 'capture evidence');
  if (input.capture.complete !== true) {
    fail('decoded frame capture coverage is incomplete');
  }
  const capturedFrames = exactFrameBindings(
    input.capture.frames, 'captured frame evidence', MAX_CAPTURE_FRAMES);

  exactKeys(input.semantic, [
    'artifactSha256', 'coverage', 'frames', 'modelSha256', 'review',
    'runtime', 'runtimeSha256',
  ], 'calibrated semantic evidence');
  if (input.semantic.artifactSha256 !== artifactBefore.sha256) {
    fail('semantic artifact binding drifted');
  }
  if (input.semantic.modelSha256 !== capability.modelSha256 ||
      input.semantic.runtimeSha256 !== capability.runtimeSha256) {
    fail('semantic host runtime identity drifted');
  }
  const semanticFrames = exactFrameBindings(
    input.semantic.frames, 'semantic frame evidence', MAX_SEMANTIC_FRAMES);
  const capturedById = new Map(capturedFrames.map((frame) => [frame.id, frame]));
  for (const frame of semanticFrames) {
    const captured = capturedById.get(frame.id);
    if (!captured || stableJson(captured) !== stableJson(frame)) {
      fail(`semantic frame identity drifted for ${frame.id}`);
    }
  }

  if (!plainRecord(input.semantic.review) ||
      input.semantic.review.schema !== CALIBRATED_REVIEW_SCHEMA) {
    fail('calibrated semantic review schema drifted');
  }
  const coverage = validateCoverage(
    input.semantic.coverage, input.semantic.review, semanticFrames);
  validateRuntime(input.semantic.runtime, capability, input.semantic);
  if (!calibratedSemanticReviewPasses(input.semantic.review)) {
    fail('calibrated semantic review did not pass its closed gate');
  }

  return Object.freeze({
    artifactSha256: artifactBefore.sha256,
    calibratedReviewSha256: sha256Stable(input.semantic.review),
    capabilityManifestSha256: capability.capabilityManifestSha256,
    capabilityProbeReceiptSha256: capability.capabilityProbeReceiptSha256,
    captureFrameSetSha256: sha256Stable(capturedFrames),
    coverageSha256: sha256Stable(coverage),
    modelSha256: capability.modelSha256,
    networkScope: input.network.scope,
    pass: true,
    qualificationResultSha256: capability.qualificationResultSha256,
    runtimeEvidenceSha256: sha256Stable(input.semantic.runtime),
    runtimeSha256: capability.runtimeSha256,
    schemaVersion: PROMOTION_GATE_SCHEMA_VERSION,
    semanticFrameSetSha256: sha256Stable(semanticFrames),
  });
}

module.exports = Object.freeze({
  CalibratedSemanticPromotionGateError,
  PROMOTION_GATE_SCHEMA_VERSION,
  assertCalibratedSemanticPromotionGate,
  sha256Stable,
});
