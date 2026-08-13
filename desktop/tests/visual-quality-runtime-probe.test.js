'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  MODEL_ID,
  MODEL_PACK_LOCK_SHA256,
  MODEL_PACK_TREE_SHA256,
  MODEL_REVISION,
} = require('../helper/lib/vision-model-pack');
const {
  DEFECTIVE_FALSE_CHECKS,
  SEMANTIC_CANDIDATE_TOKEN_IDS,
  SEMANTIC_CHOICE_THRESHOLDS,
  VisualQualityRuntimeProbeError,
  runVisualQualityRuntimeProbe,
} = require('../helper/lib/visual-quality-runtime-probe');

const workerRuntime = Object.freeze({
  schema_version: 'autoeditor-local-vision-worker-runtime/v1',
  model_id: MODEL_ID,
  model_revision: MODEL_REVISION,
  model_dtype: 'q4',
  model_pack_lock_sha256: MODEL_PACK_LOCK_SHA256,
  model_pack_tree_sha256: MODEL_PACK_TREE_SHA256,
  backend: 'wasm',
  remote_requests: 0,
});

function fixture(root, kind, targetId) {
  const bytes = Buffer.from([0xff, 0xd8, ...Buffer.from(kind), 0xff, 0xd9]);
  const file = path.join(root, `${kind}.jpg`);
  fs.writeFileSync(file, bytes);
  return {
    id: `${kind}-frame`,
    path: file,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    size_bytes: bytes.length,
    timeSeconds: 0,
    targets: [{
      id: targetId,
      category: kind === 'positive' ? 'timeline' : 'captions',
      expectation: kind === 'positive'
        ? 'The professional title and readable caption are visibly complete.'
        : 'The clipped overlapping caption and unfinished design are rejected.',
    }],
  };
}

function choice(kind, descriptor, mutation = {}) {
  const semanticOutcome = mutation[descriptor.assertionKey] ||
    (kind === 'defective' &&
      ['captions', 'productionDesign'].includes(descriptor.assertionKey)
      ? 'contradicted' : 'affirmed');
  if (semanticOutcome === 'abstain') {
    return JSON.stringify({
      label: 'U', scores_ppm: { A: 80_000, B: 100_000, U: 820_000 },
    });
  }
  const affirmed = descriptor.attemptId === 'forward' ? 'A' : 'B';
  const contradicted = descriptor.attemptId === 'forward' ? 'B' : 'A';
  const label = semanticOutcome === 'affirmed' ? affirmed : contradicted;
  return JSON.stringify({
    label,
    scores_ppm: label === 'A'
      ? { A: 820_000, B: 100_000, U: 80_000 }
      : { A: 100_000, B: 820_000, U: 80_000 },
  });
}

async function main() {
  assert.deepEqual(DEFECTIVE_FALSE_CHECKS, ['captions', 'productionDesign']);
  assert.deepEqual(SEMANTIC_CANDIDATE_TOKEN_IDS,
    { A: [49], B: [50], U: [69] });
  assert.deepEqual(SEMANTIC_CHOICE_THRESHOLDS, {
    minimum_margin_ppm: 350_000,
    minimum_selected_score_ppm: 650_000,
  });
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'visual-quality-probe-test-'));
  try {
    const positive = fixture(root, 'positive', 'positive-target-title');
    const defective = fixture(root, 'defective', 'defective-target-caption');
    const controller = new AbortController();
    const calls = [];
    const result = await runVisualQualityRuntimeProbe({
      positiveFrames: [positive],
      defectiveFrames: [defective],
      signal: controller.signal,
      requestChoice: async (request) => {
        calls.push(request);
        assert.deepEqual(Object.keys(request).sort(), [
          'descriptor', 'framePath', 'frameSha256', 'kind', 'mode',
          'modelRequest', 'signal',
        ]);
        assert.ok(path.isAbsolute(request.framePath));
        assert.match(request.frameSha256, /^[0-9a-f]{64}$/);
        assert.equal(request.signal, controller.signal);
        assert.equal(request.mode, 'artifact-assertion');
        assert.deepEqual(Object.keys(request.modelRequest).sort(),
          ['candidate_token_ids', 'candidates', 'prompt']);
        return { result: choice(request.kind, request.descriptor),
          runtime: { ...workerRuntime } };
      },
    });
    assert.equal(calls.length, 10);
    assert.deepEqual(calls.map(({ kind }) => kind), [
      ...Array(4).fill('positive'), ...Array(6).fill('defective'),
    ]);
    assert.equal(result.positive.review.pass, true);
    assert.deepEqual(result.positive.reviewedTargetIds,
      ['positive-target-title']);
    assert.equal(result.defective.review.pass, false);
    assert.equal(result.defective.review.checks.captions, false);
    assert.equal(result.defective.review.checks.productionDesign, false);
    assert.deepEqual(result.defective.reviewedTargetIds,
      ['defective-target-caption']);
    assert.deepEqual(result.runtime, workerRuntime);

    await assert.rejects(runVisualQualityRuntimeProbe({
      positiveFrames: [positive], defectiveFrames: [defective],
      signal: controller.signal,
      requestChoice: async (request) => ({
        result: choice(request.kind, request.descriptor),
        runtime: { ...workerRuntime, remote_requests: 1 },
      }),
    }), (error) => /runtime identity drifted/.test(error.message));

    await assert.rejects(runVisualQualityRuntimeProbe({
      positiveFrames: [positive], defectiveFrames: [defective],
      signal: controller.signal,
      requestChoice: async (request) => ({
        result: choice(request.kind, request.descriptor,
          request.kind === 'defective'
            ? { captions: 'affirmed', productionDesign: 'affirmed' } : {}),
        runtime: { ...workerRuntime },
      }),
    }), (error) => /did not detect the fixed caption\/design defects/.test(
      error.message));

    await assert.rejects(runVisualQualityRuntimeProbe({
      positiveFrames: [positive], defectiveFrames: [defective],
      signal: controller.signal,
      requestChoice: async () => ({ result: 'YES.', runtime: workerRuntime }),
    }), /invalid semantic choice JSON/);

    const canceled = new AbortController();
    canceled.abort();
    await assert.rejects(runVisualQualityRuntimeProbe({
      positiveFrames: [positive], defectiveFrames: [defective],
      signal: canceled.signal, requestChoice: async () => assert.fail(),
    }), (error) => error instanceof VisualQualityRuntimeProbeError &&
      /canceled/.test(error.message));

    const tampered = { ...positive, sha256: '0'.repeat(64) };
    await assert.rejects(runVisualQualityRuntimeProbe({
      positiveFrames: [tampered], defectiveFrames: [defective],
      signal: controller.signal, requestChoice: async () => assert.fail(),
    }), (error) => /identity drifted/.test(error.message));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
  console.log('visual-quality runtime probe tests passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
