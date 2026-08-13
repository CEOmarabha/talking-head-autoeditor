'use strict';

// Truthful local capability proof for the same production artifact-review
// parser, batching, target acknowledgement, and worker request path used after
// a render. The caller owns the fixed JPEG fixtures and their hash descriptors;
// this module remeasures them before asking the real local VLM to judge them.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {
  ARTIFACT_SEMANTIC_CANDIDATE_TOKEN_IDS,
  ARTIFACT_SEMANTIC_THRESHOLDS,
  REQUIRED_CHECKS,
  reviewArtifactFramesCalibrated,
  reviewPasses,
} = require('./artifact-quality');
const {
  MODEL_PACK_TREE_SHA256,
  VISION_RUNTIME_LOCK_SHA256,
} = require('./vision-model-pack');

const WORKER_RUNTIME_SCHEMA_VERSION =
  'autoeditor-local-vision-worker-runtime/v1';
const DEFECTIVE_FALSE_CHECKS = Object.freeze([
  'captions',
  'productionDesign',
]);
const MAX_FIXTURE_BYTES = 3 * 1024 * 1024;
const SHA256 = /^[0-9a-f]{64}$/;
const SEMANTIC_CANDIDATE_TOKEN_IDS =
  ARTIFACT_SEMANTIC_CANDIDATE_TOKEN_IDS;
const SEMANTIC_CHOICE_THRESHOLDS = ARTIFACT_SEMANTIC_THRESHOLDS;

class VisualQualityRuntimeProbeError extends Error {
  constructor(message) {
    super(message);
    this.name = 'VisualQualityRuntimeProbeError';
  }
}

function fail(message) {
  throw new VisualQualityRuntimeProbeError(message);
}

function exactKeys(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join('\0') !== [...keys].sort().join('\0')) {
    fail(`${label} has invalid keys`);
  }
  return value;
}

function assertRunning(signal) {
  if (!signal || typeof signal.aborted !== 'boolean') {
    fail('visual-quality probe signal is invalid');
  }
  if (signal.aborted) fail('visual-quality probe was canceled');
}

function measureFixture(file, expectedBytes, expectedSha256) {
  let descriptor;
  try { descriptor = fs.openSync(file, 'r'); }
  catch (_) { fail('visual-quality fixture is unavailable'); }
  try {
    const before = fs.fstatSync(descriptor);
    if (!before.isFile() || before.size !== expectedBytes ||
        before.size < 4 || before.size > MAX_FIXTURE_BYTES) {
      fail('visual-quality fixture size drifted');
    }
    const digest = crypto.createHash('sha256');
    const first = Buffer.alloc(2);
    const last = Buffer.alloc(2);
    if (fs.readSync(descriptor, first, 0, 2, 0) !== 2 ||
        fs.readSync(descriptor, last, 0, 2, before.size - 2) !== 2 ||
        !first.equals(Buffer.from([0xff, 0xd8])) ||
        !last.equals(Buffer.from([0xff, 0xd9]))) {
      fail('visual-quality fixture is not a complete JPEG');
    }
    const chunk = Buffer.allocUnsafe(256 * 1024);
    let offset = 0;
    while (offset < before.size) {
      const count = fs.readSync(
        descriptor, chunk, 0,
        Math.min(chunk.length, before.size - offset), offset,
      );
      if (count < 1) fail('visual-quality fixture ended while measured');
      digest.update(chunk.subarray(0, count));
      offset += count;
    }
    const after = fs.fstatSync(descriptor);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs ||
        before.dev !== after.dev || before.ino !== after.ino ||
        digest.digest('hex') !== expectedSha256) {
      fail('visual-quality fixture identity drifted');
    }
  } finally {
    fs.closeSync(descriptor);
  }
}

function validateFrames(value, kind) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 8) {
    fail(`${kind} visual-quality fixtures are invalid`);
  }
  const frameIds = new Set();
  const targetIds = new Set();
  return value.map((raw, index) => {
    const frame = exactKeys(raw, [
      'id', 'path', 'sha256', 'size_bytes', 'targets', 'timeSeconds',
    ], `${kind} visual-quality fixture ${index}`);
    if (typeof frame.id !== 'string' ||
        !/^[a-z][a-z0-9-]{0,63}$/.test(frame.id) || frameIds.has(frame.id) ||
        typeof frame.path !== 'string' || !path.isAbsolute(frame.path) ||
        frame.path.includes('\0') || !Number.isSafeInteger(frame.size_bytes) ||
        frame.size_bytes < 4 || frame.size_bytes > MAX_FIXTURE_BYTES ||
        !SHA256.test(frame.sha256) || !Number.isFinite(frame.timeSeconds) ||
        frame.timeSeconds < 0 || !Array.isArray(frame.targets) ||
        frame.targets.length < 1 || frame.targets.length > 3) {
      fail(`${kind} visual-quality fixture ${index} is invalid`);
    }
    frameIds.add(frame.id);
    const targets = frame.targets.map((rawTarget, targetIndex) => {
      const target = exactKeys(rawTarget, [
        'category', 'expectation', 'id',
      ], `${kind} visual-quality target ${index}.${targetIndex}`);
      if (typeof target.id !== 'string' ||
          !/^[a-z][a-z0-9-]{0,79}$/.test(target.id) ||
          targetIds.has(target.id) || typeof target.category !== 'string' ||
          !/^[a-z][a-z0-9-]{0,39}$/.test(target.category) ||
          typeof target.expectation !== 'string' ||
          target.expectation.length < 1 || target.expectation.length > 200) {
        fail(`${kind} visual-quality target ${index}.${targetIndex} is invalid`);
      }
      targetIds.add(target.id);
      return { ...target };
    });
    let real;
    try { real = fs.realpathSync.native(frame.path); }
    catch (_) { fail(`${kind} visual-quality fixture ${index} is unavailable`); }
    if (fs.lstatSync(frame.path).isSymbolicLink()) {
      fail(`${kind} visual-quality fixture ${index} is invalid`);
    }
    measureFixture(real, frame.size_bytes, frame.sha256);
    return {
      id: frame.id,
      path: real,
      sha256: frame.sha256,
      size_bytes: frame.size_bytes,
      timeSeconds: frame.timeSeconds,
      targets,
    };
  });
}

function exactTargetIds(frames) {
  return frames.flatMap((frame) => frame.targets.map((target) => target.id));
}

function validateReviewedTargets(result, expected, kind) {
  if (!result || typeof result !== 'object' || Array.isArray(result) ||
      !Array.isArray(result.reviewedTargetIds) ||
      result.reviewedTargetIds.length !== expected.length ||
      result.reviewedTargetIds.some((id, index) => id !== expected[index])) {
    const error = new VisualQualityRuntimeProbeError(
      `${kind} visual-quality target acknowledgement drifted`);
    error.reviewEvidence = {
      kind,
      expectedTargetIds: [...expected],
      reviewedTargetIds: Array.isArray(result?.reviewedTargetIds)
        ? [...result.reviewedTargetIds] : [],
      review: result?.review || null,
    };
    throw error;
  }
}

function sameRuntime(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

async function runVisualQualityRuntimeProbe({
  positiveFrames,
  defectiveFrames,
  signal,
  requestChoice,
} = {}) {
  assertRunning(signal);
  if (typeof requestChoice !== 'function') {
    fail('visual-quality probe configuration is invalid');
  }
  const positive = validateFrames(positiveFrames, 'positive');
  const defective = validateFrames(defectiveFrames, 'defective');
  if (positive.length !== 1 || defective.length !== 1 ||
      positive[0].targets.length !== 1 || defective[0].targets.length !== 1) {
    fail('visual-quality closed probe requires one target and frame per class');
  }
  const positiveTargetIds = exactTargetIds(positive);
  const defectiveTargetIds = exactTargetIds(defective);
  if (positiveTargetIds.some((id) => defectiveTargetIds.includes(id))) {
    fail('visual-quality fixture target IDs overlap');
  }
  let boundRuntime = null;
  const review = async (kind, frame) => reviewArtifactFramesCalibrated([frame], {
    artifactSha256: frame.sha256,
    candidateTokenIds: SEMANTIC_CANDIDATE_TOKEN_IDS,
    captionDelivery: 'burned',
    modelSha256: MODEL_PACK_TREE_SHA256,
    runtimeSha256: VISION_RUNTIME_LOCK_SHA256,
    thresholds: SEMANTIC_CHOICE_THRESHOLDS,
    requestAssertion: async (_boundFrame, invocation, descriptor) => {
      assertRunning(signal);
      let response;
      try {
        response = await requestChoice({
          kind,
          framePath: frame.path,
          frameSha256: frame.sha256,
          descriptor,
          mode: invocation.mode,
          modelRequest: invocation.model_request,
          signal,
        });
      } catch (error) {
        throw new VisualQualityRuntimeProbeError(
          `local vision ${kind} request failed: ${String(
            error?.message || error).replace(/\0/g, '').slice(0, 300)}`,
        );
      }
      assertRunning(signal);
      return response;
    },
  });

  const positiveResult = await review('positive', positive[0]);
  boundRuntime = positiveResult.runtime;
  validateReviewedTargets(positiveResult, positiveTargetIds, 'positive');
  const defectiveResult = await review('defective', defective[0]);
  if (!sameRuntime(boundRuntime, defectiveResult.runtime)) {
    fail('local vision worker runtime changed during its probe');
  }
  validateReviewedTargets(defectiveResult, defectiveTargetIds, 'defective');
  const positivePass = reviewPasses(positiveResult.review);
  const defectivePass = defectiveResult.review?.valid &&
      defectiveResult.review.pass === false &&
      Number.isFinite(defectiveResult.review.score) &&
      defectiveResult.review.score < 92 &&
      Array.isArray(defectiveResult.review.issues) &&
      defectiveResult.review.issues.length >= 1 &&
      DEFECTIVE_FALSE_CHECKS.every(
        (check) => defectiveResult.review.checks?.[check] === false) &&
      REQUIRED_CHECKS.every(
        (check) => typeof defectiveResult.review.checks?.[check] === 'boolean');
  if (!positivePass || !defectivePass) {
    const kind = !positivePass ? 'positive' : 'defective';
    const error = new VisualQualityRuntimeProbeError(
      !positivePass
        ? 'local vision did not approve the fixed positive artifact'
        : 'local vision did not detect the fixed caption/design defects');
    error.reviewEvidence = {
      kind,
      expectedTargetIds: kind === 'positive'
        ? positiveTargetIds : defectiveTargetIds,
      reviewedTargetIds: kind === 'positive'
        ? positiveResult.reviewedTargetIds : defectiveResult.reviewedTargetIds,
      review: kind === 'positive'
        ? positiveResult.review : defectiveResult.review,
    };
    error.evaluationEvidence = {
      positive: {
        expectedTargetIds: positiveTargetIds,
        reviewedTargetIds: positiveResult.reviewedTargetIds,
        review: positiveResult.review,
      },
      defective: {
        expectedTargetIds: defectiveTargetIds,
        reviewedTargetIds: defectiveResult.reviewedTargetIds,
        review: defectiveResult.review,
      },
    };
    throw error;
  }
  assertRunning(signal);
  if (!boundRuntime) fail('local vision worker runtime was not observed');
  return Object.freeze({
    positive: positiveResult,
    defective: defectiveResult,
    runtime: Object.freeze(boundRuntime),
  });
}

module.exports = Object.freeze({
  DEFECTIVE_FALSE_CHECKS,
  SEMANTIC_CANDIDATE_TOKEN_IDS,
  SEMANTIC_CHOICE_THRESHOLDS,
  VisualQualityRuntimeProbeError,
  WORKER_RUNTIME_SCHEMA_VERSION,
  runVisualQualityRuntimeProbe,
});
