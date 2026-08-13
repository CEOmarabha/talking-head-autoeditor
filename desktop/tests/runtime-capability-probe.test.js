'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {
  CAPABILITY_CHECK_IDS,
  CHECK_CONTRACT_SHA256,
  CHECK_FIXTURE_SHA256,
  deriveTrustedCapabilityManifest,
  runtimeManifestSha256,
} = require('../helper/lib/runtime-capabilities');
const {
  CHECK_RESULT_RECEIPT_SCHEMA_VERSION,
  CHECK_RESULT_RECEIPT_PRODUCER,
  CHECK_OUTCOMES,
  DEFAULT_CHECK_TIMEOUT_MS,
  MAX_CHECK_TIMEOUT_MS,
  RuntimeCapabilityProbeProducerError,
  fixedCheckContractBytes,
  fixedCheckFixtureBytes,
  validateRuntimeCapabilityCheckResultReceipt,
  canonicalRuntimeCapabilityCheckResultReceiptJson,
  runtimeCapabilityCheckResultReceiptSha256,
  validateRuntimeCapabilityProbeProduction,
  produceRuntimeCapabilityProbe,
} = require('../helper/lib/runtime-capability-probe');

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => (
    `${JSON.stringify(key)}:${canonical(value[key])}`
  )).join(',')}}`;
}

function runtimeFixture() {
  const files = new Map([
    ['C:/runtime/ffmpeg.exe', Buffer.from('pinned ffmpeg executable', 'utf8')],
    ['C:/runtime/ffprobe.exe', Buffer.from('pinned ffprobe executable', 'utf8')],
    ['C:/runtime/node.exe', Buffer.from('pinned node executable', 'utf8')],
  ]);
  const runtimeFiles = [
    { name: 'ffmpeg', path: 'C:/runtime/ffmpeg.exe' },
    { name: 'ffprobe', path: 'C:/runtime/ffprobe.exe' },
    { name: 'node', path: 'C:/runtime/node.exe' },
  ];
  const readFile = async (path) => {
    if (!files.has(path)) throw new Error('missing runtime fixture');
    return Buffer.from(files.get(path));
  };
  return { files, runtimeFiles, readFile };
}

function sizedRuntimeFixture(count) {
  const files = new Map();
  const runtimeFiles = Array.from({ length: count }, (_, index) => {
    const name = `tool-${String(index).padStart(2, '0')}`;
    const path = `C:/runtime/${name}.exe`;
    files.set(path, Buffer.from(`pinned executable/${name}`, 'utf8'));
    return { name, path };
  });
  return {
    files,
    runtimeFiles,
    readFile: async (path) => {
      if (!files.has(path)) throw new Error('missing runtime fixture');
      return Buffer.from(files.get(path));
    },
  };
}

function passingResult(id) {
  return {
    status: 'pass',
    measurements: [
      { name: 'sample_count', unit: 'count', value: 1 },
    ],
    evidence: [
      { name: 'probe_output', bytes: Buffer.from(`local evidence/${id}`, 'utf8') },
    ],
  };
}

async function successfulProduction(overrides = {}) {
  const runtime = runtimeFixture();
  const calls = [];
  const production = await produceRuntimeCapabilityProbe({
    platform: 'win32',
    architecture: 'x64',
    runtimeFiles: runtime.runtimeFiles,
    readFile: runtime.readFile,
    runCheck: async ({ id }) => {
      calls.push(id);
      return passingResult(id);
    },
    ...overrides,
  });
  return { ...runtime, calls, production };
}

async function rejectsAsync(callback, pattern = undefined) {
  await assert.rejects(
    callback,
    (error) => error instanceof RuntimeCapabilityProbeProducerError &&
      (!pattern || pattern.test(error.message)),
  );
}

(async () => {
  assert.equal(
    CHECK_RESULT_RECEIPT_SCHEMA_VERSION,
    'autoeditor-runtime-capability-check-result-receipt/v1',
  );
  assert.equal(CHECK_RESULT_RECEIPT_PRODUCER, 'autoeditor-local-runtime-probe/v1');
  assert.deepEqual(CHECK_OUTCOMES, [
    'completed',
    'invalid_result',
    'runner_error',
    'runtime_mutated',
    'timeout',
    'unrun',
  ]);
  assert.equal(DEFAULT_CHECK_TIMEOUT_MS, 10_000);
  assert.equal(MAX_CHECK_TIMEOUT_MS, 120_000);

  for (const id of CAPABILITY_CHECK_IDS) {
    assert.equal(sha256(fixedCheckContractBytes(id)), CHECK_CONTRACT_SHA256[id]);
    assert.equal(sha256(fixedCheckFixtureBytes(id)), CHECK_FIXTURE_SHA256[id]);
  }
  assert.throws(() => fixedCheckFixtureBytes('telepathy'),
    RuntimeCapabilityProbeProducerError);

  for (const count of [18, 19, 24, 25, 31, 32]) {
    const runtime = sizedRuntimeFixture(count);
    const production = await produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id }) => passingResult(id),
    });
    assert.equal(production.probeReceipt.runtime.executables.length, count);
  }
  {
    const runtime = sizedRuntimeFixture(33);
    await rejectsAsync(() => produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id }) => passingResult(id),
    }), /1-32/);
  }

  {
    const { runtimeFiles, files, calls, production } = await successfulProduction();
    assert.deepEqual(calls, CAPABILITY_CHECK_IDS);
    assert.deepEqual(
      production.probeReceipt.checks.map(({ id, status }) => ({ id, status })),
      CAPABILITY_CHECK_IDS.map((id) => ({ id, status: 'pass' })),
    );
    assert.deepEqual(
      production.resultReceipts.map(({ id, status, outcome }) => ({
        id, status, outcome,
      })),
      CAPABILITY_CHECK_IDS.map((id) => ({ id, status: 'pass', outcome: 'completed' })),
    );
    const expectedExecutables = runtimeFiles.map(({ name, path }) => ({
      name,
      sha256: sha256(files.get(path)),
    }));
    assert.deepEqual(production.probeReceipt.runtime.executables, expectedExecutables);
    assert.equal(
      production.probeReceipt.runtime.runtime_manifest_sha256,
      runtimeManifestSha256('win32', 'x64', expectedExecutables),
    );
    assert.deepEqual(
      deriveTrustedCapabilityManifest(production.probeReceipt).available_capabilities,
      [...CAPABILITY_CHECK_IDS],
    );

    const detached = validateRuntimeCapabilityProbeProduction(production);
    assert.deepEqual(detached, production);
    assert.notEqual(detached, production);
    assert.notEqual(detached.probeReceipt, production.probeReceipt);
    assert.notEqual(detached.resultReceipts, production.resultReceipts);
    for (let index = 0; index < CAPABILITY_CHECK_IDS.length; index += 1) {
      const result = production.resultReceipts[index];
      const check = production.probeReceipt.checks[index];
      assert.equal(result.runtime_manifest_sha256,
        production.probeReceipt.runtime.runtime_manifest_sha256);
      assert.equal(result.contract_sha256, check.contract_sha256);
      assert.equal(result.fixture_sha256, check.fixture_sha256);
      assert.equal(result.status, check.status);
      assert.equal(runtimeCapabilityCheckResultReceiptSha256(result),
        check.result_receipt_sha256);
      assert.equal(result.evidence.length, 1);
      assert.equal(result.evidence[0].sha256,
        sha256(Buffer.from(`local evidence/${result.id}`, 'utf8')));
    }

    const first = production.resultReceipts[0];
    assert.equal(
      canonicalRuntimeCapabilityCheckResultReceiptJson(first),
      canonical(first),
    );
    assert.equal(
      runtimeCapabilityCheckResultReceiptSha256(first),
      '85dae82d3eac8c6728abcd7b8e9369b26df185df2dfbf430f23992cc01dd5737',
    );
  }

  {
    const runtime = runtimeFixture();
    const calls = [];
    const production = await produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      timeoutMs: 5,
      runCheck: ({ id }) => {
        calls.push(id);
        if (id === 'hard_cuts') return new Promise(() => {});
        return passingResult(id);
      },
    });
    assert.deepEqual(calls, CAPABILITY_CHECK_IDS);
    const timedOut = production.resultReceipts.find(({ id }) => id === 'hard_cuts');
    assert.equal(timedOut.status, 'fail');
    assert.equal(timedOut.outcome, 'timeout');
    assert.deepEqual(timedOut.measurements, []);
    assert.deepEqual(timedOut.evidence, []);
    assert.ok(!deriveTrustedCapabilityManifest(production.probeReceipt)
      .available_capabilities.includes('hard_cuts'));
  }

  {
    const runtime = runtimeFixture();
    const calls = [];
    const production = await produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id }) => {
        calls.push(id);
        if (id === 'chart_rendering') return undefined;
        if (id === 'scene_detection') throw new Error('simulated local runner failure');
        return passingResult(id);
      },
    });
    assert.deepEqual(calls, CAPABILITY_CHECK_IDS);
    assert.equal(
      production.resultReceipts.find(({ id }) => id === 'chart_rendering').outcome,
      'unrun',
    );
    assert.equal(
      production.resultReceipts.find(({ id }) => id === 'scene_detection').outcome,
      'runner_error',
    );
    assert.equal(production.probeReceipt.checks.filter(({ status }) => status === 'fail').length,
      2);
  }

  {
    const runtime = runtimeFixture();
    const production = await produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id, fixtureBytes }) => {
        if (id === 'caption_rendering') fixtureBytes[0] ^= 0xff;
        if (id === 'graphic_rendering') {
          return { status: 'pass', measurements: [], evidence: [] };
        }
        if (id === 'audio_quality_analysis') {
          return {
            ...passingResult(id),
            available_capabilities: [...CAPABILITY_CHECK_IDS],
          };
        }
        return passingResult(id);
      },
    });
    for (const id of ['audio_quality_analysis', 'caption_rendering', 'graphic_rendering']) {
      const result = production.resultReceipts.find((item) => item.id === id);
      assert.equal(result.status, 'fail');
      assert.equal(result.outcome, 'invalid_result');
    }
  }

  {
    const runtime = runtimeFixture();
    let mutated = false;
    const production = await produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id }) => {
        if (!mutated) {
          runtime.files.set(
            'C:/runtime/ffmpeg.exe',
            Buffer.from('mutated ffmpeg executable', 'utf8'),
          );
          mutated = true;
        }
        return passingResult(id);
      },
    });
    assert.ok(production.probeReceipt.checks.every(({ status }) => status === 'fail'));
    assert.ok(production.resultReceipts.every(({ status, outcome }) => (
      status === 'fail' && outcome === 'runtime_mutated'
    )));
    assert.deepEqual(
      deriveTrustedCapabilityManifest(production.probeReceipt).available_capabilities,
      [],
    );
    assert.equal(
      production.probeReceipt.runtime.executables[0].sha256,
      sha256(runtime.files.get('C:/runtime/ffmpeg.exe')),
    );
  }

  {
    const { production } = await successfulProduction();
    let forged = clone(production);
    forged.resultReceipts[0].evidence[0].sha256 = '0'.repeat(64);
    assert.throws(
      () => validateRuntimeCapabilityProbeProduction(forged),
      RuntimeCapabilityProbeProducerError,
    );
    forged = clone(production);
    forged.resultReceipts[0].status = 'fail';
    assert.throws(
      () => validateRuntimeCapabilityProbeProduction(forged),
      RuntimeCapabilityProbeProducerError,
    );
    forged = clone(production);
    forged.probeReceipt.checks[0].result_receipt_sha256 = '0'.repeat(64);
    assert.throws(
      () => validateRuntimeCapabilityProbeProduction(forged),
      RuntimeCapabilityProbeProducerError,
    );
    forged = clone(production);
    forged.resultReceipts[0].available_capabilities = ['hard_cuts'];
    assert.throws(
      () => validateRuntimeCapabilityProbeProduction(forged),
      RuntimeCapabilityProbeProducerError,
    );

    const invalid = clone(production.resultReceipts[0]);
    invalid.measurements[0].value = 1.5;
    assert.throws(
      () => validateRuntimeCapabilityCheckResultReceipt(invalid),
      RuntimeCapabilityProbeProducerError,
    );
  }

  {
    const runtime = runtimeFixture();
    await rejectsAsync(() => produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id }) => passingResult(id),
      availableCapabilities: [...CAPABILITY_CHECK_IDS],
    }), /availableCapabilities/);
    await rejectsAsync(() => produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id }) => passingResult(id),
      capabilityMapping: Object.fromEntries(CAPABILITY_CHECK_IDS.map((id) => [id, id])),
    }), /capabilityMapping/);
    await rejectsAsync(() => produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: [...runtime.runtimeFiles].reverse(),
      readFile: runtime.readFile,
      runCheck: ({ id }) => passingResult(id),
    }), /sorted/);
    await rejectsAsync(() => produceRuntimeCapabilityProbe({
      platform: 'win32',
      architecture: 'x64',
      runtimeFiles: runtime.runtimeFiles,
      readFile: runtime.readFile,
      runCheck: ({ id }) => passingResult(id),
      timeoutMs: MAX_CHECK_TIMEOUT_MS + 1,
    }), /timeoutMs/);
  }

  console.log('runtime capability probe producer tests passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
