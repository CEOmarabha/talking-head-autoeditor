'use strict';

// Electron-side lifecycle for the trusted local capability probe. The persisted
// files contain hashes, statuses, and bounded measurements only; runtime paths,
// environment values, API keys, and raw evidence bytes are never serialized.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {
  CAPABILITY_CHECK_IDS,
  MAX_EXECUTABLES,
  deriveTrustedCapabilityManifest,
  runtimeCapabilityProbeReceiptSha256,
  runtimeManifestSha256,
} = require('./runtime-capabilities');
const {
  produceRuntimeCapabilityProbe,
  validateRuntimeCapabilityProbeProduction,
} = require('./runtime-capability-probe');
const {
  createRuntimeCapabilityCheckRunner,
} = require('./runtime-capability-check-runner');
const {
  validateCapabilityManifest,
  resolveProjectIntentPolicy,
} = require('./project-intent-policy-bridge');
const {
  RESULT_SCHEMA_VERSION: SEMANTIC_VISUAL_QUALIFICATION_RESULT_SCHEMA,
  validateQualificationResult,
} = require('./semantic-visual-qualification');

const DETAILED_RECEIPT_SCHEMA_VERSION =
  'autoeditor-runtime-capability-detailed/v1';
const COMPACT_RECEIPT_SCHEMA_VERSION =
  'autoeditor-runtime-capability-compact/v1';
const DEFAULT_GLOBAL_TIMEOUT_MS = 75_000;
const MAX_GLOBAL_TIMEOUT_MS = 15 * 60 * 1000;
const MAX_PERSISTED_RECEIPT_BYTES = 2 * 1024 * 1024;
const MAX_PERSISTED_EVIDENCE_BYTES = 64 * 1024 * 1024;
const RUNTIME_BASE_FILE_COUNT = 6;
const MAX_CAPABILITY_CODE_FILES = MAX_EXECUTABLES - RUNTIME_BASE_FILE_COUNT;
const REQUIRED_BASELINE_CAPABILITIES = Object.freeze([
  'artifact_receipts',
  'audio_quality_analysis',
  'hard_cuts',
  'loudness_normalization',
  'visual_quality_analysis',
]);
const STATUS_SET = new Set(['idle', 'probing', 'ready', 'failed']);

class RuntimeCapabilityPreflightError extends Error {
  constructor(message, code = 'capability_probe_failed') {
    super(message);
    this.name = 'RuntimeCapabilityPreflightError';
    this.code = code;
  }
}

function fail(message, code) {
  throw new RuntimeCapabilityPreflightError(message, code);
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exactKeys(value, expected, label) {
  if (!isPlainObject(value)) fail(`${label} is invalid`, 'receipt_invalid');
  const actual = Reflect.ownKeys(value);
  if (actual.some((key) => typeof key !== 'string') ||
      actual.length !== expected.length ||
      expected.some((key) => !actual.includes(key))) {
    fail(`${label} is invalid`, 'receipt_invalid');
  }
  return value;
}

function stableJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => (
    `${JSON.stringify(key)}:${stableJson(value[key])}`
  )).join(',')}}`;
}

function receiptPaths(userData) {
  if (typeof userData !== 'string' || !path.isAbsolute(userData) ||
      userData.includes('\0')) fail('user data root is invalid', 'storage_invalid');
  return Object.freeze({
    detailed: path.join(userData, 'runtime-capability-detailed.json'),
    compact: path.join(userData, 'runtime-capability-compact.json'),
  });
}

function semanticVisualQualificationPaths(userData) {
  if (typeof userData !== 'string' || !path.isAbsolute(userData) ||
      userData.includes('\0')) fail('user data root is invalid', 'storage_invalid');
  const root = path.join(userData, 'semantic-visual-qualification');
  return Object.freeze({
    root,
    manifest: path.join(root, 'manifest.json'),
    corpusBinding: path.join(root, 'corpus-binding.json'),
    runReceipt: path.join(root, 'run.json'),
    result: path.join(root, 'result.json'),
  });
}

function readSealedJson(file, label) {
  let bytes;
  try { bytes = fs.readFileSync(file); }
  catch (_) { fail(`${label} is absent`, 'semantic_visual_qualification_unavailable'); }
  try {
    const parsed = JSON.parse(bytes.toString('utf8'));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('not an object');
    }
    return parsed;
  } catch (_) {
    fail(`${label} is invalid`, 'semantic_visual_qualification_invalid');
  }
}

function pathInside(root, candidate) {
  const relative = path.relative(root, candidate);
  return !!relative && relative !== '..' &&
    !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function stableDirectoryInventory(root, candidate, label) {
  let real;
  try { real = fs.realpathSync.native(candidate); }
  catch (_) { fail(`${label} is unavailable`, 'runtime_unavailable'); }
  if (!pathInside(root, real)) {
    fail(`${label} is unavailable`, 'runtime_unavailable');
  }
  const files = [];
  const walk = (directory, relativeRoot = '') => {
    let entries;
    try {
      entries = fs.readdirSync(directory, { withFileTypes: true })
        .sort((left, right) => Buffer.from(left.name).compare(Buffer.from(right.name)));
    } catch (_) {
      fail(`${label} is unavailable`, 'runtime_unavailable');
    }
    for (const entry of entries) {
      if (!entry.name || entry.name === '.' || entry.name === '..' ||
          entry.name.includes('/') || entry.name.includes('\\') ||
          entry.name.includes('\0') || entry.isSymbolicLink()) {
        fail(`${label} inventory is invalid`, 'runtime_invalid');
      }
      const child = path.join(directory, entry.name);
      const relative = relativeRoot
        ? `${relativeRoot}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(child, relative);
      else if (entry.isFile()) files.push({ name: relative, path: child });
      else fail(`${label} inventory is invalid`, 'runtime_invalid');
      if (files.length > 128) {
        fail(`${label} inventory is too large`, 'runtime_invalid');
      }
    }
  };
  walk(real);
  if (!files.length) fail(`${label} is unavailable`, 'runtime_unavailable');
  return { real, files };
}

function resolvedRuntimeFileBindings(runtime) {
  if (!isPlainObject(runtime)) fail('runtime paths are invalid', 'runtime_invalid');
  const candidates = [
    ['daemon', runtime.daemon],
    ['engine', runtime.engine],
    ['ffmpeg', runtime.ffmpeg],
    ['ffprobe', runtime.ffprobe],
    ['node', runtime.node],
    ['runtime-manifest', runtime.runtimeManifest],
  ];
  if (!Array.isArray(runtime.capabilityCodeFiles) ||
      runtime.capabilityCodeFiles.length < 1 ||
      runtime.capabilityCodeFiles.length > MAX_CAPABILITY_CODE_FILES) {
    fail('capability runner code bindings are invalid', 'runtime_invalid');
  }
  for (const raw of runtime.capabilityCodeFiles) {
    if (!isPlainObject(raw) ||
        !['name', 'path'].every((key) => Object.prototype.hasOwnProperty.call(raw, key)) ||
        Object.keys(raw).length !== 2 ||
        typeof raw.name !== 'string' ||
        !/^[a-z][a-z0-9._-]{0,63}$/.test(raw.name)) {
      fail('capability runner code bindings are invalid', 'runtime_invalid');
    }
    candidates.push([raw.name, raw.path]);
  }
  if (typeof runtime.root !== 'string' || !path.isAbsolute(runtime.root) ||
      runtime.root.includes('\0')) fail('runtime root is invalid', 'runtime_invalid');
  let root;
  try { root = fs.realpathSync.native(runtime.root); }
  catch (_) { fail('runtime root is unavailable', 'runtime_unavailable'); }
  const bindings = candidates.map(([name, candidate]) => {
    if (typeof candidate !== 'string' || !path.isAbsolute(candidate) ||
        candidate.includes('\0')) fail('runtime file is invalid', 'runtime_invalid');
    let real;
    let stat;
    try {
      real = fs.realpathSync.native(candidate);
      stat = fs.statSync(real);
    } catch (_) {
      fail('runtime file is unavailable', 'runtime_unavailable');
    }
    if ((!stat.isFile() && !stat.isDirectory()) || !pathInside(root, real)) {
      fail('runtime file is unavailable', 'runtime_unavailable');
    }
    if (stat.isFile() && stat.size < 1) {
      fail('runtime file is unavailable', 'runtime_unavailable');
    }
    if (stat.isDirectory()) {
      const inventory = stableDirectoryInventory(root, real, `runtime directory ${name}`);
      return { name, path: inventory.real };
    }
    return { name, path: real };
  }).sort((left, right) => left.name < right.name ? -1 : 1);
  if (new Set(bindings.map(({ name }) => name)).size !== bindings.length) {
    fail('runtime file names are not unique', 'runtime_invalid');
  }
  return bindings;
}

async function stableRegularFileMeasurement(file) {
  let before;
  try {
    before = await fs.promises.stat(file);
    if (!before.isFile() || before.size < 1) throw new Error('not a file');
  } catch (_) {
    fail('runtime file could not be measured', 'runtime_unavailable');
  }
  const hash = crypto.createHash('sha256');
  await new Promise((resolve, reject) => {
    const stream = fs.createReadStream(file);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.once('error', reject);
    stream.once('end', resolve);
  }).catch(() => fail('runtime file could not be measured', 'runtime_unavailable'));
  let after;
  try { after = await fs.promises.stat(file); }
  catch (_) { fail('runtime file changed while measured', 'runtime_mutated'); }
  if (before.size !== after.size || before.mtimeMs !== after.mtimeMs ||
      before.dev !== after.dev || before.ino !== after.ino) {
    fail('runtime file changed while measured', 'runtime_mutated');
  }
  return { sha256: hash.digest('hex'), size_bytes: before.size };
}

async function stableFileMeasurement(file) {
  let stat;
  try { stat = await fs.promises.stat(file); }
  catch (_) { fail('runtime file could not be measured', 'runtime_unavailable'); }
  if (stat.isFile()) return stableRegularFileMeasurement(file);
  if (!stat.isDirectory()) {
    fail('runtime file could not be measured', 'runtime_unavailable');
  }
  let root;
  try { root = fs.realpathSync.native(file); }
  catch (_) { fail('runtime directory could not be measured', 'runtime_unavailable'); }
  const inventory = stableDirectoryInventory(
    path.dirname(root), root, 'runtime directory');
  const digest = crypto.createHash('sha256');
  let sizeBytes = 0;
  for (const item of inventory.files) {
    const measured = await stableRegularFileMeasurement(item.path);
    sizeBytes += measured.size_bytes;
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes > 4 * 1024 * 1024 * 1024) {
      fail('runtime directory is too large', 'runtime_invalid');
    }
    digest.update(Buffer.from(item.name, 'utf8'));
    digest.update(Buffer.from([0]));
    digest.update(Buffer.from(String(measured.size_bytes), 'ascii'));
    digest.update(Buffer.from([0]));
    digest.update(Buffer.from(measured.sha256, 'ascii'));
    digest.update(Buffer.from('\n', 'ascii'));
  }
  return { sha256: digest.digest('hex'), size_bytes: sizeBytes };
}

async function currentRuntimeExecutables(runtimeFiles) {
  const measured = [];
  for (const file of runtimeFiles) {
    const value = await stableFileMeasurement(file.path);
    measured.push({ name: file.name, sha256: value.sha256 });
  }
  return measured;
}

function sameExecutables(left, right) {
  return Array.isArray(left) && Array.isArray(right) &&
    left.length === right.length && left.every((item, index) => (
      item.name === right[index]?.name && item.sha256 === right[index]?.sha256
    ));
}

async function revalidateCurrentRuntime(production, runtimeFiles) {
  const executables = await currentRuntimeExecutables(runtimeFiles);
  const runtime = production.probeReceipt.runtime;
  if (!sameExecutables(executables, runtime.executables) ||
      runtimeManifestSha256(runtime.platform, runtime.architecture, executables) !==
        runtime.runtime_manifest_sha256) {
    fail('runtime changed after its capability probe', 'runtime_mutated');
  }
  return executables;
}

function readBoundedJson(file) {
  let stat;
  try { stat = fs.statSync(file); }
  catch (_) { fail('capability receipt is unavailable', 'receipt_unavailable'); }
  if (!stat.isFile() || stat.size < 1 || stat.size > MAX_PERSISTED_RECEIPT_BYTES) {
    fail('capability receipt has an invalid size', 'receipt_invalid');
  }
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (_) { fail('capability receipt is invalid', 'receipt_invalid'); }
}

function atomicReplaceJson(file, value) {
  const directory = path.dirname(file);
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const suffix = `${process.pid}.${Date.now()}.${crypto.randomBytes(6).toString('hex')}`;
  const temporary = `${file}.${suffix}.tmp`;
  const backup = `${file}.${suffix}.bak`;
  const bytes = Buffer.from(`${stableJson(value)}\n`, 'utf8');
  if (bytes.length < 1 || bytes.length > MAX_PERSISTED_RECEIPT_BYTES) {
    fail('capability receipt is too large', 'storage_invalid');
  }
  fs.writeFileSync(temporary, bytes, { mode: 0o600, flag: 'wx' });
  let backedUp = false;
  try {
    if (fs.existsSync(file)) {
      fs.renameSync(file, backup);
      backedUp = true;
    }
    fs.renameSync(temporary, file);
    if (backedUp) fs.rmSync(backup, { force: true });
  } catch (_) {
    if (!fs.existsSync(file) && backedUp && fs.existsSync(backup)) {
      try { fs.renameSync(backup, file); } catch (_) { /* retain recovery copy */ }
    }
    fail('capability receipt could not be stored', 'storage_failed');
  } finally {
    if (fs.existsSync(temporary)) fs.rmSync(temporary, { force: true });
  }
}

function normalizeEvidencePreimages(value, production) {
  if (!Array.isArray(value) || value.length !== CAPABILITY_CHECK_IDS.length) {
    fail('capability evidence preimages are incomplete', 'receipt_invalid');
  }
  let totalBytes = 0;
  return value.map((raw, index) => {
    const item = exactKeys(raw, ['evidence', 'id'],
      `capability evidence preimages[${index}]`);
    const id = CAPABILITY_CHECK_IDS[index];
    if (item.id !== id || !Array.isArray(item.evidence)) {
      fail('capability evidence preimages are out of order', 'receipt_invalid');
    }
    const receipt = production.resultReceipts[index];
    if (item.evidence.length !== receipt.evidence.length) {
      fail('capability evidence preimages do not match their receipt',
        'receipt_invalid');
    }
    const evidence = item.evidence.map((rawEvidence, evidenceIndex) => {
      const record = exactKeys(rawEvidence, ['bytes_base64', 'name'],
        `capability evidence preimages[${index}].evidence[${evidenceIndex}]`);
      if (typeof record.name !== 'string' ||
          !/^[a-z][a-z0-9._-]{0,63}$/.test(record.name) ||
          typeof record.bytes_base64 !== 'string' ||
          !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
            record.bytes_base64)) {
        fail('capability evidence preimage is invalid', 'receipt_invalid');
      }
      const bytes = Buffer.from(record.bytes_base64, 'base64');
      const expected = receipt.evidence[evidenceIndex];
      totalBytes += bytes.length;
      if (bytes.length < 1 || totalBytes > MAX_PERSISTED_EVIDENCE_BYTES ||
          record.name !== expected.name || bytes.length !== expected.size_bytes ||
          crypto.createHash('sha256').update(bytes).digest('hex') !== expected.sha256) {
        fail('capability evidence preimage does not bind its receipt',
          'receipt_invalid');
      }
      return { name: record.name, bytes_base64: record.bytes_base64 };
    });
    return { id, evidence };
  });
}

function capturedEvidencePreimages(captured, production) {
  const byId = new Map(captured.map((item) => [item.id, item.evidence]));
  const candidate = CAPABILITY_CHECK_IDS.map((id, index) => ({
    id,
    evidence: (production.resultReceipts[index].evidence.length
      ? (byId.get(id) || []) : []).map((item) => ({
      name: item.name,
      bytes_base64: Buffer.from(item.bytes).toString('base64'),
    })),
  }));
  return normalizeEvidencePreimages(candidate, production);
}

async function validateReceiptPair(paths, runtimeFiles) {
  const detailed = exactKeys(readBoundedJson(paths.detailed), [
    'evidence_preimages', 'probe_receipt_sha256', 'production', 'schema_version',
  ], 'detailed capability receipt');
  const compact = exactKeys(readBoundedJson(paths.compact), [
    'probe_receipt', 'probe_receipt_sha256', 'schema_version', 'trusted_manifest',
  ], 'compact capability receipt');
  if (detailed.schema_version !== DETAILED_RECEIPT_SCHEMA_VERSION ||
      compact.schema_version !== COMPACT_RECEIPT_SCHEMA_VERSION) {
    fail('capability receipt schema is unsupported', 'receipt_invalid');
  }
  let production;
  try { production = validateRuntimeCapabilityProbeProduction(detailed.production); }
  catch (_) { fail('detailed capability receipt is invalid', 'receipt_invalid'); }
  const evidencePreimages = normalizeEvidencePreimages(
    detailed.evidence_preimages, production);
  const probeHash = runtimeCapabilityProbeReceiptSha256(production.probeReceipt);
  if (detailed.probe_receipt_sha256 !== probeHash ||
      compact.probe_receipt_sha256 !== probeHash ||
      stableJson(compact.probe_receipt) !== stableJson(production.probeReceipt)) {
    fail('capability receipts do not bind the same probe', 'receipt_invalid');
  }

  // Runtime bytes are freshly re-measured before any capability manifest is
  // derived or admitted to the project-intent policy bridge.
  await revalidateCurrentRuntime(production, runtimeFiles);
  let trustedManifest;
  try {
    trustedManifest = validateCapabilityManifest(
      deriveTrustedCapabilityManifest(production.probeReceipt));
  } catch (_) {
    fail('trusted capability manifest is invalid', 'receipt_invalid');
  }
  if (stableJson(compact.trusted_manifest) !== stableJson(trustedManifest)) {
    fail('compact capability manifest does not match the probe', 'receipt_invalid');
  }
  return { production, trustedManifest, evidencePreimages };
}

async function persistAndReloadProduction({
  production, evidencePreimages, paths, runtimeFiles, assertCurrent,
}) {
  let normalized;
  try { normalized = validateRuntimeCapabilityProbeProduction(production); }
  catch (_) { fail('capability probe production is invalid', 'receipt_invalid'); }
  await revalidateCurrentRuntime(normalized, runtimeFiles);
  assertCurrent?.();
  const probeHash = runtimeCapabilityProbeReceiptSha256(normalized.probeReceipt);
  let trustedManifest;
  try {
    trustedManifest = validateCapabilityManifest(
      deriveTrustedCapabilityManifest(normalized.probeReceipt));
  } catch (_) {
    fail('trusted capability manifest is invalid', 'receipt_invalid');
  }
  assertCurrent?.();
  atomicReplaceJson(paths.detailed, {
    schema_version: DETAILED_RECEIPT_SCHEMA_VERSION,
    probe_receipt_sha256: probeHash,
    production: normalized,
    evidence_preimages: normalizeEvidencePreimages(
      evidencePreimages, normalized),
  });
  atomicReplaceJson(paths.compact, {
    schema_version: COMPACT_RECEIPT_SCHEMA_VERSION,
    probe_receipt_sha256: probeHash,
    probe_receipt: normalized.probeReceipt,
    trusted_manifest: trustedManifest,
  });
  assertCurrent?.();
  const validated = await validateReceiptPair(paths, runtimeFiles);
  assertCurrent?.();
  return validated;
}

function combinedSignal(left, right) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (left?.aborted || right?.aborted) controller.abort();
  else {
    left?.addEventListener('abort', abort, { once: true });
    right?.addEventListener('abort', abort, { once: true });
  }
  return {
    signal: controller.signal,
    dispose: () => {
      left?.removeEventListener('abort', abort);
      right?.removeEventListener('abort', abort);
    },
  };
}

function publicSnapshot(state) {
  if (!state || !STATUS_SET.has(state.status)) {
    return Object.freeze({
      status: 'idle', trusted: false, baselineReady: false,
      availableCapabilities: Object.freeze([]), passedChecks: 0,
      completedChecks: 0, totalChecks: CAPABILITY_CHECK_IDS.length,
      failureCode: '',
    });
  }
  return Object.freeze({
    status: state.status,
    trusted: state.trusted === true,
    baselineReady: state.baselineReady === true,
    availableCapabilities: Object.freeze([
      ...(state.availableCapabilities || []),
    ]),
    passedChecks: Number(state.passedChecks || 0),
    completedChecks: Number(state.completedChecks || 0),
    totalChecks: CAPABILITY_CHECK_IDS.length,
    failureCode: String(state.failureCode || ''),
  });
}

function createRuntimeCapabilityPreflight({
  runtime,
  userData,
  env,
  platform = process.platform,
  architecture = process.arch,
  checkTimeoutMs = 10_000,
  globalTimeoutMs = DEFAULT_GLOBAL_TIMEOUT_MS,
  producer = produceRuntimeCapabilityProbe,
  runnerFactory = createRuntimeCapabilityCheckRunner,
} = {}) {
  if (!Number.isSafeInteger(globalTimeoutMs) || globalTimeoutMs < 1 ||
      globalTimeoutMs > MAX_GLOBAL_TIMEOUT_MS) {
    fail('global capability timeout is invalid', 'configuration_invalid');
  }
  if (!Number.isSafeInteger(checkTimeoutMs) || checkTimeoutMs < 1 ||
      checkTimeoutMs > globalTimeoutMs) {
    fail('per-check capability timeout is invalid', 'configuration_invalid');
  }
  if (typeof producer !== 'function' || typeof runnerFactory !== 'function') {
    fail('capability probe implementation is invalid', 'configuration_invalid');
  }
  const paths = receiptPaths(userData);
  const workRoot = path.join(userData, 'runtime-capability-work');
  let state = {
    status: 'idle', trusted: false, baselineReady: false,
    availableCapabilities: [], passedChecks: 0, completedChecks: 0,
    failureCode: '',
  };
  let startPromise = null;
  let trustedManifest = null;
  let trustedProduction = null;
  let trustedRuntimeFiles = null;
  let generation = 0;
  let activeRun = null;
  const noCancellation = Promise.resolve(false);

  function snapshot() {
    return publicSnapshot(state);
  }

  function canceledError() {
    return new RuntimeCapabilityPreflightError(
      'local runtime capability probe was canceled', 'probe_canceled');
  }

  function clearTrustedState(failureCode = '') {
    trustedManifest = null;
    trustedProduction = null;
    trustedRuntimeFiles = null;
    state = {
      status: 'idle', trusted: false, baselineReady: false,
      availableCapabilities: [], passedChecks: 0, completedChecks: 0,
      failureCode,
    };
  }

  function start() {
    if (startPromise) return startPromise;
    const runGeneration = ++generation;
    const globalController = new AbortController();
    let rejectCancellation;
    const cancellation = new Promise((_, reject) => {
      rejectCancellation = reject;
    });
    const run = {
      generation: runGeneration,
      controller: globalController,
      rejectCancellation,
      runner: null,
      promise: null,
      cancelPromise: null,
      canceled: false,
      settled: false,
    };
    activeRun = run;
    state = {
      status: 'probing', trusted: false, baselineReady: false,
      availableCapabilities: [], passedChecks: 0, completedChecks: 0,
      failureCode: '',
    };
    run.promise = (async () => {
      let runtimeFiles;
      let runner;
      let expired = false;
      let timer;
      let resultManifest = null;
      let pendingError = null;
      const assertCurrent = () => {
        if (run.canceled || runGeneration !== generation) throw canceledError();
      };
      try {
        runtimeFiles = resolvedRuntimeFileBindings(runtime);
        runner = runnerFactory({ runtime, workRoot, env, platform });
        run.runner = runner;
        const workflow = (async () => {
          const captured = [];
          const production = await producer({
            platform,
            architecture,
            runtimeFiles,
            readFile: stableFileMeasurement,
            timeoutMs: checkTimeoutMs,
            runCheck: async (context) => {
              if (globalController.signal.aborted) return undefined;
              const combined = combinedSignal(
                context.signal, globalController.signal);
              try {
                const result = await runner({
                  ...context, signal: combined.signal,
                });
                if (result && Array.isArray(result.evidence)) {
                  captured.push({
                    id: context.id,
                    evidence: result.evidence.map((item) => ({
                      name: item.name,
                      bytes: Buffer.from(item.bytes),
                    })),
                  });
                }
                return result;
              }
              finally { combined.dispose(); }
            },
          });
          if (expired) {
            fail('capability probe exceeded its global timeout', 'probe_timeout');
          }
          assertCurrent();
          return persistAndReloadProduction({
            production,
            evidencePreimages: capturedEvidencePreimages(captured, production),
            paths,
            runtimeFiles,
            assertCurrent,
          });
        })();
        const deadline = new Promise((_, reject) => {
          timer = setTimeout(() => {
            expired = true;
            globalController.abort();
            reject(new RuntimeCapabilityPreflightError(
              'capability probe exceeded its global timeout', 'probe_timeout'));
          }, globalTimeoutMs);
        });
        const validated = await Promise.race([workflow, deadline, cancellation]);
        if (expired) {
          fail('capability probe exceeded its global timeout', 'probe_timeout');
        }
        assertCurrent();
        trustedManifest = validated.trustedManifest;
        trustedProduction = validated.production;
        trustedRuntimeFiles = runtimeFiles;
        const available = trustedManifest.available_capabilities;
        const baselineReady = REQUIRED_BASELINE_CAPABILITIES.every((name) =>
          available.includes(name));
        const passedChecks = validated.production.probeReceipt.checks
          .filter((check) => check.status === 'pass').length;
        state = {
          status: baselineReady ? 'ready' : 'failed',
          trusted: true,
          baselineReady,
          availableCapabilities: [...available],
          passedChecks,
          completedChecks: CAPABILITY_CHECK_IDS.length,
          failureCode: baselineReady ? '' : 'required_checks_failed',
        };
        resultManifest = trustedManifest;
      } catch (error) {
        const canceled = run.canceled || runGeneration !== generation;
        pendingError = canceled
          ? canceledError()
          : error instanceof RuntimeCapabilityPreflightError
          ? error
          : new RuntimeCapabilityPreflightError(
            'local runtime capability probe failed', 'capability_probe_failed');
        if (!canceled) {
          trustedManifest = null;
          trustedProduction = null;
          trustedRuntimeFiles = null;
          state = {
            status: 'failed', trusted: false, baselineReady: false,
            availableCapabilities: [], passedChecks: 0,
            completedChecks: 0,
            failureCode: pendingError.code,
          };
        }
      } finally {
        clearTimeout(timer);
        globalController.abort();
        try {
          await Promise.resolve(runner?.dispose?.());
        } catch (_) { /* temp cleanup is best effort */ }
      }
      assertCurrent();
      if (pendingError) throw pendingError;
      return resultManifest;
    })();
    startPromise = run.promise;
    run.promise.then(
      () => {
        run.settled = true;
        if (activeRun === run) activeRun = null;
      },
      () => {
        run.settled = true;
        if (!run.canceled && activeRun === run) activeRun = null;
      },
    );
    // The startup caller intentionally does not await. Attach a rejection
    // handler immediately so a failed background probe is not unhandled.
    startPromise.catch(() => {});
    return startPromise;
  }

  function cancel() {
    const run = activeRun;
    if (!run) return noCancellation;
    if (run.cancelPromise) return run.cancelPromise;
    if (run.settled) return noCancellation;

    run.canceled = true;
    generation += 1;
    clearTrustedState('probe_canceled');
    run.controller.abort();

    let runnerCancellation = noCancellation;
    try {
      runnerCancellation = Promise.resolve(run.runner?.cancel?.())
        .catch(() => false);
    } catch (_) {
      runnerCancellation = noCancellation;
    }
    run.cancelPromise = Promise.allSettled([
      run.promise,
      runnerCancellation,
    ]).then(() => {
      if (startPromise === run.promise) startPromise = null;
      if (activeRun === run) activeRun = null;
      return true;
    });
    run.rejectCancellation(canceledError());
    return run.cancelPromise;
  }

  async function requireTrustedManifest() {
    try { await start(); }
    catch (_) {
      throw new RuntimeCapabilityPreflightError(
        'The built-in editing capability check did not pass',
        state.failureCode || 'capability_probe_failed');
    }
    if (!trustedManifest || state.status !== 'ready' || !state.baselineReady) {
      throw new RuntimeCapabilityPreflightError(
        'The built-in editing capability check did not pass',
        state.failureCode || 'required_checks_failed');
    }
    try {
      await revalidateCurrentRuntime(trustedProduction, trustedRuntimeFiles);
    } catch (error) {
      trustedManifest = null;
      trustedProduction = null;
      trustedRuntimeFiles = null;
      state = {
        status: 'failed', trusted: false, baselineReady: false,
        availableCapabilities: [], passedChecks: 0,
        completedChecks: CAPABILITY_CHECK_IDS.length,
        failureCode: error instanceof RuntimeCapabilityPreflightError
          ? error.code : 'runtime_mutated',
      };
      throw error;
    }
    return validateCapabilityManifest(trustedManifest);
  }

  async function resolvePolicy(projectIntent) {
    await start().catch(() => {});
    if (!trustedManifest || !state.trusted) {
      throw new RuntimeCapabilityPreflightError(
        'A trusted local capability manifest is unavailable',
        state.failureCode || 'capability_probe_failed');
    }
    try {
      await revalidateCurrentRuntime(trustedProduction, trustedRuntimeFiles);
    } catch (error) {
      trustedManifest = null;
      trustedProduction = null;
      trustedRuntimeFiles = null;
      state = {
        status: 'failed', trusted: false, baselineReady: false,
        availableCapabilities: [], passedChecks: 0,
        completedChecks: CAPABILITY_CHECK_IDS.length,
        failureCode: error instanceof RuntimeCapabilityPreflightError
          ? error.code : 'runtime_mutated',
      };
      throw error;
    }
    // resolveProjectIntentPolicy validates the manifest again and fails closed
    // when this exact runtime lacks a capability required by the intent.
    return resolveProjectIntentPolicy(projectIntent, trustedManifest);
  }

  async function requireSemanticVisualQualification() {
    const files = semanticVisualQualificationPaths(userData);
    const manifest = readSealedJson(files.manifest, 'semantic visual qualification manifest');
    const corpusBinding = readSealedJson(
      files.corpusBinding, 'semantic visual corpus binding');
    const runReceipt = readSealedJson(
      files.runReceipt, 'semantic visual qualification run');
    const result = readSealedJson(
      files.result, 'semantic visual qualification result');
    let validated;
    try {
      validated = validateQualificationResult({
        manifest, corpusBinding, runReceipt, result,
      });
    } catch (error) {
      fail(error?.message || 'semantic visual qualification is invalid',
        'semantic_visual_qualification_invalid');
    }
    if (validated.schemaVersion !== SEMANTIC_VISUAL_QUALIFICATION_RESULT_SCHEMA ||
        validated.qualified !== true ||
        !Array.isArray(validated.advertisedCapabilities) ||
        validated.advertisedCapabilities.join('\0') !== 'visual_quality_analysis') {
      fail('sealed semantic visual qualification did not pass every gate',
        'semantic_visual_qualification_failed');
    }
    const model = runReceipt.backends?.[0]?.model || {};
    return Object.freeze({
      qualified: true,
      schemaVersion: validated.schemaVersion,
      resultSha256: validated.seal.sha256,
      modelSha256: typeof model.packTreeSha256 === 'string'
        ? model.packTreeSha256 : '',
      runtimeSha256: typeof model.runtimeSha256 === 'string'
        ? model.runtimeSha256 : '',
      backends: Object.freeze(['webgpu', 'wasm']),
      advertisedCapabilities: Object.freeze([...validated.advertisedCapabilities]),
    });
  }

  return Object.freeze({
    start,
    cancel,
    snapshot,
    requireTrustedManifest,
    requireSemanticVisualQualification,
    resolveProjectIntentPolicy: resolvePolicy,
    receiptPaths: paths,
  });
}

module.exports = Object.freeze({
  DETAILED_RECEIPT_SCHEMA_VERSION,
  COMPACT_RECEIPT_SCHEMA_VERSION,
  DEFAULT_GLOBAL_TIMEOUT_MS,
  MAX_GLOBAL_TIMEOUT_MS,
  MAX_PERSISTED_RECEIPT_BYTES,
  REQUIRED_BASELINE_CAPABILITIES,
  RuntimeCapabilityPreflightError,
  receiptPaths,
  semanticVisualQualificationPaths,
  resolvedRuntimeFileBindings,
  stableFileMeasurement,
  validateReceiptPair,
  persistAndReloadProduction,
  createRuntimeCapabilityPreflight,
});
