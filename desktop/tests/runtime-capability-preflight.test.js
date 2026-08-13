'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  CAPABILITY_CHECK_IDS,
} = require('../helper/lib/runtime-capabilities');
const {
  COMPACT_RECEIPT_SCHEMA_VERSION,
  DETAILED_RECEIPT_SCHEMA_VERSION,
  RuntimeCapabilityPreflightError,
  createRuntimeCapabilityPreflight,
  resolvedRuntimeFileBindings,
  validateReceiptPair,
} = require('../helper/lib/runtime-capability-preflight');
const {
  createRuntimeCapabilityCheckRunner,
  runBoundedCommand,
} = require('../helper/lib/runtime-capability-check-runner');

function makeRuntime(root) {
  const files = {
    daemon: 'helper/daemon.exe',
    engine: 'engine/engine.exe',
    ffmpeg: 'bin/ffmpeg.exe',
    ffprobe: 'bin/ffprobe.exe',
    node: 'node/node.exe',
    runtimeManifest: 'runtime-manifest.json',
  };
  const runtime = { root };
  for (const [name, relative] of Object.entries(files)) {
    const file = path.join(root, relative);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, Buffer.from(`pinned runtime/${name}`, 'utf8'));
    runtime[name] = file;
  }
  runtime.capabilityCodeFiles = [
    ['artifact-contract', 'app/artifact-contract.js'],
    ['capability-check-runner', 'app/runtime-capability-check-runner.js'],
    ['capability-contract', 'app/runtime-capabilities.js'],
    ['capability-policy-bridge', 'app/project-intent-policy-bridge.js'],
    ['capability-preflight', 'app/runtime-capability-preflight.js'],
    ['capability-producer', 'app/runtime-capability-probe.js'],
    ['edit-policy', 'app/edit-policy.js'],
    ['project-intent', 'app/project-intent.js'],
    ['sfx-production', 'app/sfx-production.py'],
    ['music-production', 'app/music-production.py'],
    ['asr-runtime-probe', 'app/asr-runtime-probe.py'],
    ['dialogue-cleanup-runtime-probe', 'app/dialogue-cleanup-runtime-probe.py'],
    ['render-capability-runtime-probe',
      'app/render-capability-runtime-probe.py'],
    ['semantic-choice-contract', 'app/calibrated-semantic-choice.js'],
    ['semantic-qualification-contract',
      'app/semantic-visual-qualification.js'],
    ['whisper-small-model', 'models/faster-whisper-small'],
    ['caption-font', 'app/WorkSans-Variable.ttf'],
    ['desktop-main', 'app/main.js'],
    ['process-tree', 'app/process-tree.js'],
  ].map(([name, relative]) => {
    const file = path.join(root, relative);
    if (name === 'whisper-small-model') {
      fs.mkdirSync(file, { recursive: true });
      fs.writeFileSync(path.join(file, 'config.json'),
        Buffer.from('trusted model/config', 'utf8'));
      fs.writeFileSync(path.join(file, 'model.bin'),
        Buffer.from('trusted model/weights', 'utf8'));
      fs.writeFileSync(path.join(file, 'tokenizer.json'),
        Buffer.from('trusted model/tokenizer', 'utf8'));
    } else {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, Buffer.from(`trusted code/${name}`, 'utf8'));
    }
    return { name, path: file };
  });
  return runtime;
}

function passingRunnerFactory({ mutate } = {}) {
  return () => {
    let count = 0;
    const runner = async ({ id, contractBytes, fixtureBytes, runtime }) => {
      assert.equal(contractBytes.toString('utf8'),
        `autoeditor-runtime-capability-check-contract/${id}/v1`);
      assert.equal(fixtureBytes.toString('utf8'),
        `autoeditor-runtime-capability-check-fixture/${id}/v1`);
      assert.ok(runtime.executables.some((item) =>
        item.name === 'capability-check-runner'));
      for (const name of [
        'artifact-contract', 'capability-check-runner', 'capability-contract',
        'capability-policy-bridge', 'capability-preflight',
        'capability-producer', 'desktop-main', 'edit-policy',
        'caption-font', 'process-tree', 'project-intent', 'sfx-production',
        'music-production',
        'asr-runtime-probe', 'dialogue-cleanup-runtime-probe',
        'render-capability-runtime-probe',
        'whisper-small-model',
      ]) assert.ok(runtime.executables.some((item) => item.name === name), name);
      count += 1;
      if (mutate && count === 1) mutate();
      await new Promise((resolve) => setTimeout(resolve, 1));
      return {
        status: 'pass',
        measurements: [{ name: 'executed', unit: 'boolean', value: 1 }],
        evidence: [{
          name: 'local_execution_receipt',
          bytes: Buffer.from(JSON.stringify({
            schema_version: 'test-runtime-check/v1', check_id: id,
            executed: true,
          }), 'utf8'),
        }],
      };
    };
    runner.dispose = () => {};
    return runner;
  };
}

function intent() {
  const disabled = { enabled: false, preference: 'none' };
  return {
    schema_version: 'autoeditor-project-intent/v1',
    profile: 'utility_faithful',
    delivery: { platform: 'archive', aspect: 'source' },
    target_duration: { min_ms: 60_000, max_ms: 60_000 },
    preferences: {
      captions: { ...disabled }, graphics: { ...disabled },
      music: { ...disabled }, sfx: { ...disabled },
      transitions: { ...disabled },
    },
  };
}

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-cap-preflight-'));
  try {
    const runtime = makeRuntime(path.join(root, 'runtime'));
    const userData = path.join(root, 'user-data');
    const controller = createRuntimeCapabilityPreflight({
      runtime, userData, env: {}, platform: 'win32', architecture: 'x64',
      checkTimeoutMs: 500, globalTimeoutMs: 5000,
      runnerFactory: passingRunnerFactory(),
    });
    assert.equal(controller.snapshot().status, 'idle');
    await new Promise((resolve) => setTimeout(resolve, 25));
    assert.equal(controller.snapshot().status, 'idle',
      'construction is nonblocking and must not contend with legacy render');
    const start = controller.start();
    assert.equal(controller.snapshot().status, 'probing');
    const manifest = await start;
    assert.deepEqual(manifest.available_capabilities, CAPABILITY_CHECK_IDS);
    assert.deepEqual(controller.snapshot(), {
      status: 'ready', trusted: true, baselineReady: true,
      availableCapabilities: CAPABILITY_CHECK_IDS,
      passedChecks: CAPABILITY_CHECK_IDS.length,
      completedChecks: CAPABILITY_CHECK_IDS.length,
      totalChecks: CAPABILITY_CHECK_IDS.length,
      failureCode: '',
    });
    const unprobedIntent = intent();
    unprobedIntent.profile = 'podcast_interview';
    await assert.rejects(
      () => controller.resolveProjectIntentPolicy(unprobedIntent),
      /capability gate failed; missing: multicam_sync, speaker_diarization/,
      'the trusted manifest must reach the policy bridge and fail closed on ' +
        'a genuinely unprobed capability',
    );

    const detailedPath = controller.receiptPaths.detailed;
    const compactPath = controller.receiptPaths.compact;
    const detailedText = fs.readFileSync(detailedPath, 'utf8');
    const compactText = fs.readFileSync(compactPath, 'utf8');
    assert.ok(!detailedText.includes(root));
    assert.ok(!compactText.includes(root));
    assert.ok(!/api.?key|secret|token/i.test(detailedText));
    const detailed = JSON.parse(detailedText);
    const compact = JSON.parse(compactText);
    assert.equal(detailed.schema_version, DETAILED_RECEIPT_SCHEMA_VERSION);
    assert.equal(compact.schema_version, COMPACT_RECEIPT_SCHEMA_VERSION);
    assert.equal(detailed.evidence_preimages.length, CAPABILITY_CHECK_IDS.length);
    assert.ok(detailed.evidence_preimages.every((item) =>
      item.evidence.length === 1));
    const runtimeFiles = resolvedRuntimeFileBindings(runtime);
    assert.equal(runtimeFiles.length, 25,
      'the current six base files plus nineteen trusted code/assets must fit');
    await validateReceiptPair(controller.receiptPaths, runtimeFiles);

    const futureRuntime = makeRuntime(path.join(root, 'runtime-with-asr-binding'));
    const asrPath = path.join(futureRuntime.root, 'app', 'asr-runtime.py');
    fs.writeFileSync(asrPath, Buffer.from('trusted code/asr-runtime', 'utf8'));
    futureRuntime.capabilityCodeFiles.push({ name: 'asr-runtime', path: asrPath });
    assert.equal(resolvedRuntimeFileBindings(futureRuntime).length, 26,
      'one additional trusted ASR binding must fit without weakening the bound');

    const originalDetailed = fs.readFileSync(detailedPath);
    const forged = JSON.parse(originalDetailed.toString('utf8'));
    forged.evidence_preimages[0].evidence[0].bytes_base64 =
      Buffer.from('forged evidence', 'utf8').toString('base64');
    fs.writeFileSync(detailedPath, JSON.stringify(forged));
    await assert.rejects(
      () => validateReceiptPair(controller.receiptPaths, runtimeFiles),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'receipt_invalid',
    );
    fs.writeFileSync(detailedPath, originalDetailed);

    const codePath = runtime.capabilityCodeFiles[0].path;
    const originalCode = fs.readFileSync(codePath);
    fs.writeFileSync(codePath, Buffer.from('mutated runner bytes', 'utf8'));
    await assert.rejects(
      () => validateReceiptPair(controller.receiptPaths, runtimeFiles),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'runtime_mutated',
    );
    fs.writeFileSync(codePath, originalCode);

    const intentCodePath = runtime.capabilityCodeFiles.find(
      ({ name }) => name === 'project-intent').path;
    const originalIntentCode = fs.readFileSync(intentCodePath);
    fs.writeFileSync(intentCodePath,
      Buffer.from('mutated project intent semantics', 'utf8'));
    await assert.rejects(
      () => validateReceiptPair(controller.receiptPaths, runtimeFiles),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'runtime_mutated',
    );
    fs.writeFileSync(intentCodePath, originalIntentCode);

    const smallModelPath = runtime.capabilityCodeFiles.find(
      ({ name }) => name === 'whisper-small-model').path;
    const tokenizerPath = path.join(smallModelPath, 'tokenizer.json');
    const originalTokenizer = fs.readFileSync(tokenizerPath);
    fs.writeFileSync(tokenizerPath,
      Buffer.from('mutated ASR tokenizer semantics', 'utf8'));
    await assert.rejects(
      () => validateReceiptPair(controller.receiptPaths, runtimeFiles),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'runtime_mutated',
      'every file in the bound model tree must be remeasured before trust use',
    );
    fs.writeFileSync(tokenizerPath, originalTokenizer);

    const authorityRuntime = makeRuntime(path.join(root, 'runtime-authority'));
    const authority = createRuntimeCapabilityPreflight({
      runtime: authorityRuntime,
      userData: path.join(root, 'user-data-authority'), env: {},
      platform: 'win32', architecture: 'x64',
      checkTimeoutMs: 500, globalTimeoutMs: 5000,
      runnerFactory: passingRunnerFactory(),
    });
    await authority.start();
    fs.writeFileSync(authorityRuntime.ffmpeg,
      Buffer.from('mutated after trusted start', 'utf8'));
    await assert.rejects(
      () => authority.requireTrustedManifest(),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'runtime_mutated',
    );
    assert.equal(authority.snapshot().trusted, false);
    await assert.rejects(
      () => authority.resolveProjectIntentPolicy(intent()),
      (error) => error instanceof RuntimeCapabilityPreflightError,
    );

    const policyRuntime = makeRuntime(path.join(root, 'runtime-policy-authority'));
    const policyAuthority = createRuntimeCapabilityPreflight({
      runtime: policyRuntime,
      userData: path.join(root, 'user-data-policy-authority'), env: {},
      platform: 'win32', architecture: 'x64',
      checkTimeoutMs: 500, globalTimeoutMs: 5000,
      runnerFactory: passingRunnerFactory(),
    });
    await policyAuthority.start();
    fs.writeFileSync(policyRuntime.engine,
      Buffer.from('mutated before policy authority use', 'utf8'));
    await assert.rejects(
      () => policyAuthority.resolveProjectIntentPolicy(intent()),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'runtime_mutated',
    );
    assert.equal(policyAuthority.snapshot().trusted, false);

    const mutationRuntime = makeRuntime(path.join(root, 'runtime-mutates'));
    const mutating = createRuntimeCapabilityPreflight({
      runtime: mutationRuntime,
      userData: path.join(root, 'user-data-mutates'), env: {},
      platform: 'win32', architecture: 'x64',
      checkTimeoutMs: 500, globalTimeoutMs: 5000,
      runnerFactory: passingRunnerFactory({
        mutate: () => fs.writeFileSync(
          mutationRuntime.capabilityCodeFiles[0].path,
          Buffer.from(`mutated/${crypto.randomBytes(8).toString('hex')}`, 'utf8')),
      }),
    });
    const mutationManifest = await mutating.start();
    assert.deepEqual(mutationManifest.available_capabilities, []);
    assert.equal(mutating.snapshot().status, 'failed');
    assert.equal(mutating.snapshot().trusted, true);

    const cancelRuntime = makeRuntime(path.join(root, 'runtime-cancel-retry'));
    const retryPassingFactory = passingRunnerFactory();
    let factoryCalls = 0;
    let signalRunnerEntered;
    let releaseTaskkill;
    const runnerEntered = new Promise((resolve) => {
      signalRunnerEntered = resolve;
    });
    const taskkillFinished = new Promise((resolve) => {
      releaseTaskkill = resolve;
    });
    const cancelController = createRuntimeCapabilityPreflight({
      runtime: cancelRuntime,
      userData: path.join(root, 'user-data-cancel-retry'), env: {},
      platform: 'win32', architecture: 'x64',
      checkTimeoutMs: 500, globalTimeoutMs: 5000,
      runnerFactory: (options) => {
        factoryCalls += 1;
        if (factoryCalls > 1) return retryPassingFactory(options);
        return createRuntimeCapabilityCheckRunner({
          ...options,
          execute: (command, args, executeOptions) => runBoundedCommand(
            command, args, {
              ...executeOptions,
              spawnImpl: () => {
                const child = new EventEmitter();
                child.pid = 54321;
                child.stdout = new EventEmitter();
                child.stderr = new EventEmitter();
                signalRunnerEntered();
                return child;
              },
              stopProcessTreeImpl: () => taskkillFinished,
            }),
        });
      },
    });
    const canceledStart = cancelController.start();
    await runnerEntered;
    const firstCancel = cancelController.cancel();
    const repeatedCancel = cancelController.cancel();
    assert.strictEqual(repeatedCancel, firstCancel,
      'concurrent cancellation callers must await the same cleanup');
    let cancellationSettled = false;
    firstCancel.then(() => { cancellationSettled = true; });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(cancellationSettled, false,
      'preflight cancel must await the held process-tree termination');
    releaseTaskkill();
    assert.equal(await firstCancel, true);
    await assert.rejects(
      () => canceledStart,
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'probe_canceled',
    );
    assert.deepEqual(cancelController.snapshot(), {
      status: 'idle', trusted: false, baselineReady: false,
      availableCapabilities: [], passedChecks: 0, completedChecks: 0,
      totalChecks: CAPABILITY_CHECK_IDS.length,
      failureCode: 'probe_canceled',
    });
    assert.equal(await cancelController.cancel(), false,
      'cancellation is a safe no-op once cleanup has completed');
    await new Promise((resolve) => setTimeout(resolve, 25));
    assert.equal(fs.existsSync(cancelController.receiptPaths.detailed), false);
    assert.equal(fs.existsSync(cancelController.receiptPaths.compact), false);
    assert.equal(cancelController.snapshot().failureCode, 'probe_canceled',
      'late completion from the canceled generation cannot replace its state');

    await assert.rejects(
      () => cancelController.requireSemanticVisualQualification(),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'semantic_visual_qualification_unavailable',
      'semantic visual evaluation stays unavailable without a sealed result');

    const retryManifest = await cancelController.start();
    assert.deepEqual(retryManifest.available_capabilities, CAPABILITY_CHECK_IDS);
    assert.equal(factoryCalls, 2,
      'a start after awaited cancellation must create a fresh runner');
    assert.equal(cancelController.snapshot().status, 'ready');
    assert.equal(cancelController.snapshot().trusted, true);

    const timeoutRuntime = makeRuntime(path.join(root, 'runtime-timeout'));
    const timeoutController = createRuntimeCapabilityPreflight({
      runtime: timeoutRuntime,
      userData: path.join(root, 'user-data-timeout'), env: {},
      platform: 'win32', architecture: 'x64',
      checkTimeoutMs: 20, globalTimeoutMs: 40,
      producer: () => new Promise(() => {}),
      runnerFactory: () => {
        const runner = async () => null;
        runner.dispose = () => {};
        return runner;
      },
    });
    const startedAt = Date.now();
    await assert.rejects(() => timeoutController.start(),
      (error) => error instanceof RuntimeCapabilityPreflightError &&
        error.code === 'probe_timeout');
    assert.ok(Date.now() - startedAt < 1500);
    assert.equal(timeoutController.snapshot().status, 'failed');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }

  console.log('runtime capability preflight integration tests passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
