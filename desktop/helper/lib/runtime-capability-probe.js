'use strict';

// Trusted local producer for runtime-capability receipts.  This module owns
// orchestration and fixed check ordering, but deliberately does not own a real
// renderer/ASR implementation.  Production must inject one internal
// check-runner at the Electron main-process boundary; model, project, renderer,
// and IPC payloads must never be allowed to provide it.

const crypto = require('node:crypto');
const {
  CAPABILITY_CHECK_IDS,
  CHECK_CONTRACT_SHA256,
  CHECK_FIXTURE_SHA256,
  MAX_EXECUTABLES,
  RuntimeCapabilityError,
  runtimeManifestSha256,
  buildRuntimeCapabilityProbeReceipt,
  validateRuntimeCapabilityProbeReceipt,
} = require('./runtime-capabilities');

const CHECK_RESULT_RECEIPT_SCHEMA_VERSION =
  'autoeditor-runtime-capability-check-result-receipt/v1';
const CHECK_RESULT_RECEIPT_PRODUCER = 'autoeditor-local-runtime-probe/v1';
const CHECK_OUTCOMES = Object.freeze([
  'completed',
  'invalid_result',
  'runner_error',
  'runtime_mutated',
  'timeout',
  'unrun',
]);
const MAX_CHECK_TIMEOUT_MS = 120_000;
const DEFAULT_CHECK_TIMEOUT_MS = 10_000;
const MAX_MEASUREMENTS = 64;
const MAX_EVIDENCE_ITEMS = 64;
const MAX_EVIDENCE_ITEM_BYTES = 32 * 1024 * 1024;
const MAX_TOTAL_EVIDENCE_BYTES = 64 * 1024 * 1024;
const MAX_MEASUREMENT_MAGNITUDE = 1_000_000_000_000_000;

const REQUEST_KEYS = Object.freeze([
  'architecture', 'platform', 'readFile', 'runCheck', 'runtimeFiles',
]);
const REQUEST_OPTIONAL_KEYS = Object.freeze(['timeoutMs']);
const RUNTIME_FILE_KEYS = Object.freeze(['name', 'path']);
const RUNNER_RESULT_KEYS = Object.freeze(['evidence', 'measurements', 'status']);
const RUNNER_MEASUREMENT_KEYS = Object.freeze(['name', 'unit', 'value']);
const RUNNER_EVIDENCE_KEYS = Object.freeze(['bytes', 'name']);
const RECEIPT_KEYS = Object.freeze([
  'contract_sha256',
  'evidence',
  'fixture_sha256',
  'id',
  'measurements',
  'outcome',
  'producer',
  'runtime_manifest_sha256',
  'schema_version',
  'status',
]);
const RECEIPT_MEASUREMENT_KEYS = RUNNER_MEASUREMENT_KEYS;
const RECEIPT_EVIDENCE_KEYS = Object.freeze(['name', 'sha256', 'size_bytes']);
const PRODUCTION_KEYS = Object.freeze(['probeReceipt', 'resultReceipts']);
const SHA256 = /^[0-9a-f]{64}$/;
const IDENTIFIER = /^[a-z][a-z0-9._-]{0,63}$/;
const UNIT = /^[a-z][a-z0-9._/-]{0,31}$/;
const OUTCOME_SET = new Set(CHECK_OUTCOMES);
const CHECK_ID_SET = new Set(CAPABILITY_CHECK_IDS);

class RuntimeCapabilityProbeProducerError extends Error {
  constructor(message) {
    super(message);
    this.name = 'RuntimeCapabilityProbeProducerError';
  }
}

function fail(message) {
  throw new RuntimeCapabilityProbeProducerError(message);
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isDenseArray(value) {
  if (!Array.isArray(value)) return false;
  for (let index = 0; index < value.length; index += 1) {
    if (!Object.prototype.hasOwnProperty.call(value, index)) return false;
  }
  return Reflect.ownKeys(value).every((key) => (
    key === 'length' ||
    (typeof key === 'string' && /^(0|[1-9][0-9]*)$/.test(key) &&
      Number(key) < value.length)
  ));
}

function asciiCompare(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function exactKeys(value, expected, label) {
  if (!isPlainObject(value)) fail(`${label} must be an object`);
  const ownKeys = Reflect.ownKeys(value);
  if (ownKeys.some((key) => typeof key !== 'string')) {
    fail(`${label} has unsupported non-string keys`);
  }
  const actual = ownKeys.sort(asciiCompare);
  if (actual.length !== expected.length ||
      actual.some((key, index) => key !== expected[index])) {
    const actualSet = new Set(actual);
    const expectedSet = new Set(expected);
    const missing = expected.filter((key) => !actualSet.has(key));
    const extra = actual.filter((key) => !expectedSet.has(key));
    const details = [];
    if (missing.length) details.push(`missing ${missing.join(', ')}`);
    if (extra.length) details.push(`unsupported ${extra.join(', ')}`);
    fail(`${label} has invalid keys (${details.join('; ')})`);
  }
  return value;
}

function exactRequestKeys(value) {
  if (!isPlainObject(value)) fail('runtime capability probe request must be an object');
  const ownKeys = Reflect.ownKeys(value);
  if (ownKeys.some((key) => typeof key !== 'string')) {
    fail('runtime capability probe request has unsupported non-string keys');
  }
  const allowed = new Set([...REQUEST_KEYS, ...REQUEST_OPTIONAL_KEYS]);
  const missing = REQUEST_KEYS.filter((key) => !ownKeys.includes(key));
  const extra = ownKeys.filter((key) => !allowed.has(key));
  if (missing.length || extra.length) {
    const details = [];
    if (missing.length) details.push(`missing ${missing.join(', ')}`);
    if (extra.length) details.push(`unsupported ${extra.join(', ')}`);
    fail(`runtime capability probe request has invalid keys (${details.join('; ')})`);
  }
  return value;
}

function pythonString(value) {
  let result = '"';
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (character === '"') result += '\\"';
    else if (character === '\\') result += '\\\\';
    else if (character === '\b') result += '\\b';
    else if (character === '\f') result += '\\f';
    else if (character === '\n') result += '\\n';
    else if (character === '\r') result += '\\r';
    else if (character === '\t') result += '\\t';
    else if (codePoint >= 0x20 && codePoint <= 0x7e) result += character;
    else if (codePoint <= 0xffff) {
      result += `\\u${codePoint.toString(16).padStart(4, '0')}`;
    } else {
      const adjusted = codePoint - 0x10000;
      const high = 0xd800 + (adjusted >> 10);
      const low = 0xdc00 + (adjusted & 0x3ff);
      result += `\\u${high.toString(16)}\\u${low.toString(16)}`;
    }
  }
  return `${result}"`;
}

function canonicalJsonData(value, label) {
  function serialize(item) {
    if (item === null) return 'null';
    if (item === true) return 'true';
    if (item === false) return 'false';
    if (typeof item === 'string') return pythonString(item);
    if (typeof item === 'number' && Number.isSafeInteger(item)) return String(item);
    if (isDenseArray(item)) return `[${item.map(serialize).join(',')}]`;
    if (isPlainObject(item)) {
      const keys = Object.keys(item).sort(asciiCompare);
      return `{${keys.map((key) => (
        `${pythonString(key)}:${serialize(item[key])}`
      )).join(',')}}`;
    }
    fail(`${label} is not canonical JSON`);
  }
  return serialize(value);
}

function sha256Bytes(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function sha256Text(value) {
  return sha256Bytes(Buffer.from(value, 'utf8'));
}

function digest(value, label) {
  if (typeof value !== 'string' || !SHA256.test(value)) {
    fail(`${label} must be a full lowercase SHA-256 digest`);
  }
  return value;
}

function identifier(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} is unsupported`);
  }
  return value;
}

function fixedCheckContractBytes(id) {
  if (!CHECK_ID_SET.has(id)) fail('check id is unsupported');
  return Buffer.from(`autoeditor-runtime-capability-check-contract/${id}/v1`, 'utf8');
}

function fixedCheckFixtureBytes(id) {
  if (!CHECK_ID_SET.has(id)) fail('check id is unsupported');
  return Buffer.from(`autoeditor-runtime-capability-check-fixture/${id}/v1`, 'utf8');
}

for (const id of CAPABILITY_CHECK_IDS) {
  if (sha256Bytes(fixedCheckContractBytes(id)) !== CHECK_CONTRACT_SHA256[id] ||
      sha256Bytes(fixedCheckFixtureBytes(id)) !== CHECK_FIXTURE_SHA256[id]) {
    throw new Error(`fixed runtime capability probe material drifted for ${id}`);
  }
}

function normalizeRuntimeFiles(value) {
  if (!isDenseArray(value) || value.length < 1 ||
      value.length > MAX_EXECUTABLES) {
    fail(`runtimeFiles must contain 1-${MAX_EXECUTABLES} sorted entries`);
  }
  const files = value.map((raw, index) => {
    const label = `runtimeFiles[${index}]`;
    const item = exactKeys(raw, RUNTIME_FILE_KEYS, label);
    const name = identifier(item.name, IDENTIFIER, `${label}.name`);
    if (typeof item.path !== 'string' || item.path.length < 1 ||
        item.path.length > 32_768 || item.path.includes('\0')) {
      fail(`${label}.path is unsupported`);
    }
    return { name, path: item.path };
  });
  const names = files.map((item) => item.name);
  const sortedNames = [...new Set(names)].sort(asciiCompare);
  if (sortedNames.length !== names.length ||
      sortedNames.some((name, index) => name !== names[index])) {
    fail('runtimeFiles must be sorted by unique name');
  }
  return files;
}

function bytesCopy(value, label) {
  if (!Buffer.isBuffer(value) && !(value instanceof Uint8Array)) {
    fail(`${label} must be bytes`);
  }
  return Buffer.from(value);
}

async function measureRuntimeFiles(runtimeFiles, readFile) {
  const executables = [];
  for (const file of runtimeFiles) {
    let raw;
    try {
      raw = await readFile(file.path);
    } catch (error) {
      throw new RuntimeCapabilityProbeProducerError(
        `could not read runtime file ${file.name}`,
        { cause: error },
      );
    }
    let sha256;
    if (isPlainObject(raw)) {
      const measured = exactKeys(
        raw, ['sha256', 'size_bytes'], `runtime file ${file.name} measurement`,
      );
      sha256 = digest(measured.sha256, `runtime file ${file.name} sha256`);
      if (!Number.isSafeInteger(measured.size_bytes) || measured.size_bytes < 1) {
        fail(`runtime file ${file.name} size_bytes is unsupported`);
      }
    } else {
      const bytes = bytesCopy(raw, `runtime file ${file.name}`);
      if (bytes.length < 1) fail(`runtime file ${file.name} is empty`);
      sha256 = sha256Bytes(bytes);
    }
    executables.push({ name: file.name, sha256 });
  }
  return executables;
}

function normalizeMeasurements(value, label) {
  if (!isDenseArray(value) || value.length > MAX_MEASUREMENTS) {
    fail(`${label} must contain at most ${MAX_MEASUREMENTS} measurements`);
  }
  const measurements = value.map((raw, index) => {
    const itemLabel = `${label}[${index}]`;
    const item = exactKeys(raw, RUNNER_MEASUREMENT_KEYS, itemLabel);
    const name = identifier(item.name, IDENTIFIER, `${itemLabel}.name`);
    const unit = identifier(item.unit, UNIT, `${itemLabel}.unit`);
    if (!Number.isSafeInteger(item.value) ||
        Math.abs(item.value) > MAX_MEASUREMENT_MAGNITUDE) {
      fail(`${itemLabel}.value must be a bounded safe integer`);
    }
    return { name, unit, value: item.value };
  });
  const names = measurements.map((item) => item.name);
  const sortedNames = [...new Set(names)].sort(asciiCompare);
  if (sortedNames.length !== names.length ||
      sortedNames.some((name, index) => name !== names[index])) {
    fail(`${label} must be sorted by unique name`);
  }
  return measurements;
}

function hashRunnerEvidence(value, label) {
  if (!isDenseArray(value) || value.length > MAX_EVIDENCE_ITEMS) {
    fail(`${label} must contain at most ${MAX_EVIDENCE_ITEMS} evidence items`);
  }
  let totalBytes = 0;
  const evidence = value.map((raw, index) => {
    const itemLabel = `${label}[${index}]`;
    const item = exactKeys(raw, RUNNER_EVIDENCE_KEYS, itemLabel);
    const name = identifier(item.name, IDENTIFIER, `${itemLabel}.name`);
    const bytes = bytesCopy(item.bytes, `${itemLabel}.bytes`);
    if (bytes.length < 1 || bytes.length > MAX_EVIDENCE_ITEM_BYTES) {
      fail(`${itemLabel}.bytes has unsupported size`);
    }
    totalBytes += bytes.length;
    if (totalBytes > MAX_TOTAL_EVIDENCE_BYTES) {
      fail(`${label} exceeds the total evidence byte limit`);
    }
    return { name, sha256: sha256Bytes(bytes), size_bytes: bytes.length };
  });
  const names = evidence.map((item) => item.name);
  const sortedNames = [...new Set(names)].sort(asciiCompare);
  if (sortedNames.length !== names.length ||
      sortedNames.some((name, index) => name !== names[index])) {
    fail(`${label} must be sorted by unique name`);
  }
  return evidence;
}

function normalizeReceiptEvidence(value, label) {
  if (!isDenseArray(value) || value.length > MAX_EVIDENCE_ITEMS) {
    fail(`${label} must contain at most ${MAX_EVIDENCE_ITEMS} evidence items`);
  }
  let totalBytes = 0;
  const evidence = value.map((raw, index) => {
    const itemLabel = `${label}[${index}]`;
    const item = exactKeys(raw, RECEIPT_EVIDENCE_KEYS, itemLabel);
    const name = identifier(item.name, IDENTIFIER, `${itemLabel}.name`);
    if (!Number.isSafeInteger(item.size_bytes) || item.size_bytes < 1 ||
        item.size_bytes > MAX_EVIDENCE_ITEM_BYTES) {
      fail(`${itemLabel}.size_bytes is unsupported`);
    }
    totalBytes += item.size_bytes;
    if (totalBytes > MAX_TOTAL_EVIDENCE_BYTES) {
      fail(`${label} exceeds the total evidence byte limit`);
    }
    return {
      name,
      sha256: digest(item.sha256, `${itemLabel}.sha256`),
      size_bytes: item.size_bytes,
    };
  });
  const names = evidence.map((item) => item.name);
  const sortedNames = [...new Set(names)].sort(asciiCompare);
  if (sortedNames.length !== names.length ||
      sortedNames.some((name, index) => name !== names[index])) {
    fail(`${label} must be sorted by unique name`);
  }
  return evidence;
}

function validateRuntimeCapabilityCheckResultReceipt(value) {
  const raw = exactKeys(value, RECEIPT_KEYS, 'runtime capability check result receipt');
  if (raw.schema_version !== CHECK_RESULT_RECEIPT_SCHEMA_VERSION) {
    fail('runtime capability check result receipt schema_version is unsupported');
  }
  if (raw.producer !== CHECK_RESULT_RECEIPT_PRODUCER) {
    fail('runtime capability check result receipt producer is untrusted');
  }
  if (typeof raw.id !== 'string' || !CHECK_ID_SET.has(raw.id)) {
    fail('runtime capability check result receipt id is unsupported');
  }
  const id = raw.id;
  const contractHash = digest(raw.contract_sha256, 'contract_sha256');
  if (contractHash !== CHECK_CONTRACT_SHA256[id]) {
    fail('contract_sha256 does not bind the fixed check contract');
  }
  const fixtureHash = digest(raw.fixture_sha256, 'fixture_sha256');
  if (fixtureHash !== CHECK_FIXTURE_SHA256[id]) {
    fail('fixture_sha256 does not bind the fixed check fixture');
  }
  const runtimeHash = digest(raw.runtime_manifest_sha256, 'runtime_manifest_sha256');
  if (raw.status !== 'pass' && raw.status !== 'fail') {
    fail('runtime capability check result receipt status is unsupported');
  }
  if (typeof raw.outcome !== 'string' || !OUTCOME_SET.has(raw.outcome)) {
    fail('runtime capability check result receipt outcome is unsupported');
  }
  const measurements = normalizeMeasurements(raw.measurements, 'measurements');
  const evidence = normalizeReceiptEvidence(raw.evidence, 'evidence');
  if (raw.status === 'pass' && (raw.outcome !== 'completed' || evidence.length < 1)) {
    fail('passing result must be completed and bind at least one evidence item');
  }
  if (raw.outcome !== 'completed' && (measurements.length || evidence.length)) {
    fail('incomplete result cannot carry measurements or evidence');
  }
  return {
    schema_version: CHECK_RESULT_RECEIPT_SCHEMA_VERSION,
    producer: CHECK_RESULT_RECEIPT_PRODUCER,
    id,
    contract_sha256: contractHash,
    fixture_sha256: fixtureHash,
    runtime_manifest_sha256: runtimeHash,
    status: raw.status,
    outcome: raw.outcome,
    measurements,
    evidence,
  };
}

function canonicalRuntimeCapabilityCheckResultReceiptJson(value) {
  return canonicalJsonData(
    validateRuntimeCapabilityCheckResultReceipt(value),
    'runtime capability check result receipt',
  );
}

function runtimeCapabilityCheckResultReceiptSha256(value) {
  return sha256Text(canonicalRuntimeCapabilityCheckResultReceiptJson(value));
}

function buildDetailedResultReceipt({
  id,
  runtimeManifestHash,
  status,
  outcome,
  measurements = [],
  evidence = [],
}) {
  return validateRuntimeCapabilityCheckResultReceipt({
    schema_version: CHECK_RESULT_RECEIPT_SCHEMA_VERSION,
    producer: CHECK_RESULT_RECEIPT_PRODUCER,
    id,
    contract_sha256: CHECK_CONTRACT_SHA256[id],
    fixture_sha256: CHECK_FIXTURE_SHA256[id],
    runtime_manifest_sha256: runtimeManifestHash,
    status,
    outcome,
    measurements,
    evidence,
  });
}

function failedResult(id, runtimeManifestHash, outcome) {
  return buildDetailedResultReceipt({
    id,
    runtimeManifestHash,
    status: 'fail',
    outcome,
  });
}

function normalizeRunnerResult(id, runtimeManifestHash, raw) {
  if (raw === undefined || raw === null) {
    return failedResult(id, runtimeManifestHash, 'unrun');
  }
  try {
    const result = exactKeys(raw, RUNNER_RESULT_KEYS, `check runner result ${id}`);
    if (result.status !== 'pass' && result.status !== 'fail') {
      fail(`check runner result ${id}.status is unsupported`);
    }
    const measurements = normalizeMeasurements(
      result.measurements, `check runner result ${id}.measurements`,
    );
    const evidence = hashRunnerEvidence(
      result.evidence, `check runner result ${id}.evidence`,
    );
    if (result.status === 'pass' && evidence.length < 1) {
      fail(`passing check runner result ${id} must contain evidence bytes`);
    }
    return buildDetailedResultReceipt({
      id,
      runtimeManifestHash,
      status: result.status,
      outcome: 'completed',
      measurements,
      evidence,
    });
  } catch (error) {
    if (!(error instanceof RuntimeCapabilityProbeProducerError)) throw error;
    return failedResult(id, runtimeManifestHash, 'invalid_result');
  }
}

async function runOneCheck({
  id,
  platform,
  architecture,
  runtimeFiles,
  executables,
  runtimeManifestHash,
  runCheck,
  timeoutMs,
}) {
  const contractBytes = fixedCheckContractBytes(id);
  const fixtureBytes = fixedCheckFixtureBytes(id);
  const controller = new AbortController();
  let timeoutHandle;
  const timeout = new Promise((resolve) => {
    timeoutHandle = setTimeout(() => {
      controller.abort();
      resolve({ timedOut: true });
    }, timeoutMs);
  });
  const runner = Promise.resolve()
    .then(() => runCheck({
      id,
      contractBytes,
      fixtureBytes,
      runtime: {
        platform,
        architecture,
        executables: executables.map((item) => ({ ...item })),
        runtimeManifestSha256: runtimeManifestHash,
        files: runtimeFiles.map((item) => ({ ...item })),
      },
      signal: controller.signal,
    }))
    .then(
      (value) => ({ value }),
      () => ({ runnerError: true }),
    );
  const settled = await Promise.race([runner, timeout]);
  clearTimeout(timeoutHandle);
  if (settled.timedOut) {
    return failedResult(id, runtimeManifestHash, 'timeout');
  }
  if (settled.runnerError) {
    return failedResult(id, runtimeManifestHash, 'runner_error');
  }
  if (sha256Bytes(contractBytes) !== CHECK_CONTRACT_SHA256[id] ||
      sha256Bytes(fixtureBytes) !== CHECK_FIXTURE_SHA256[id]) {
    return failedResult(id, runtimeManifestHash, 'invalid_result');
  }
  return normalizeRunnerResult(id, runtimeManifestHash, settled.value);
}

function sameExecutables(left, right) {
  return left.length === right.length && left.every((item, index) => (
    item.name === right[index].name && item.sha256 === right[index].sha256
  ));
}

function validateRuntimeCapabilityProbeProduction(value) {
  const raw = exactKeys(value, PRODUCTION_KEYS, 'runtime capability probe production');
  let probeReceipt;
  try {
    probeReceipt = validateRuntimeCapabilityProbeReceipt(raw.probeReceipt);
  } catch (error) {
    if (error instanceof RuntimeCapabilityError) {
      throw new RuntimeCapabilityProbeProducerError(error.message, { cause: error });
    }
    throw error;
  }
  if (!isDenseArray(raw.resultReceipts) ||
      raw.resultReceipts.length !== CAPABILITY_CHECK_IDS.length) {
    fail(`resultReceipts must contain exactly ${CAPABILITY_CHECK_IDS.length} entries`);
  }
  const resultReceipts = raw.resultReceipts.map((item, index) => {
    const receipt = validateRuntimeCapabilityCheckResultReceipt(item);
    const expectedId = CAPABILITY_CHECK_IDS[index];
    if (receipt.id !== expectedId) {
      fail('resultReceipts must contain every fixed check id in sorted order');
    }
    const check = probeReceipt.checks[index];
    if (receipt.runtime_manifest_sha256 !==
          probeReceipt.runtime.runtime_manifest_sha256 ||
        receipt.contract_sha256 !== check.contract_sha256 ||
        receipt.fixture_sha256 !== check.fixture_sha256 ||
        receipt.status !== check.status ||
        runtimeCapabilityCheckResultReceiptSha256(receipt) !==
          check.result_receipt_sha256) {
      fail(`resultReceipts[${index}] does not bind probe receipt check ${expectedId}`);
    }
    return receipt;
  });
  return { probeReceipt, resultReceipts };
}

async function produceRuntimeCapabilityProbe(value) {
  const request = exactRequestKeys(value);
  const runtimeFiles = normalizeRuntimeFiles(request.runtimeFiles);
  if (typeof request.readFile !== 'function') fail('readFile must be a function');
  if (typeof request.runCheck !== 'function') fail('runCheck must be a function');
  const timeoutMs = request.timeoutMs === undefined
    ? DEFAULT_CHECK_TIMEOUT_MS
    : request.timeoutMs;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 ||
      timeoutMs > MAX_CHECK_TIMEOUT_MS) {
    fail(`timeoutMs must be an integer between 1 and ${MAX_CHECK_TIMEOUT_MS}`);
  }

  const initialExecutables = await measureRuntimeFiles(runtimeFiles, request.readFile);
  let initialRuntimeHash;
  try {
    initialRuntimeHash = runtimeManifestSha256(
      request.platform, request.architecture, initialExecutables,
    );
  } catch (error) {
    if (error instanceof RuntimeCapabilityError) {
      throw new RuntimeCapabilityProbeProducerError(error.message, { cause: error });
    }
    throw error;
  }

  let resultReceipts = [];
  for (const id of CAPABILITY_CHECK_IDS) {
    // Sequential execution avoids resource contention changing probe outcomes;
    // failures never stop later fixed checks from running.
    resultReceipts.push(await runOneCheck({
      id,
      platform: request.platform,
      architecture: request.architecture,
      runtimeFiles,
      executables: initialExecutables,
      runtimeManifestHash: initialRuntimeHash,
      runCheck: request.runCheck,
      timeoutMs,
    }));
  }

  const finalExecutables = await measureRuntimeFiles(runtimeFiles, request.readFile);
  let receiptExecutables = initialExecutables;
  let receiptRuntimeHash = initialRuntimeHash;
  if (!sameExecutables(initialExecutables, finalExecutables)) {
    receiptExecutables = finalExecutables;
    try {
      receiptRuntimeHash = runtimeManifestSha256(
        request.platform, request.architecture, finalExecutables,
      );
    } catch (error) {
      if (error instanceof RuntimeCapabilityError) {
        throw new RuntimeCapabilityProbeProducerError(error.message, { cause: error });
      }
      throw error;
    }
    resultReceipts = CAPABILITY_CHECK_IDS.map((id) => (
      failedResult(id, receiptRuntimeHash, 'runtime_mutated')
    ));
  }

  const checkResults = Object.fromEntries(resultReceipts.map((result) => [
    result.id,
    {
      result_receipt_sha256: runtimeCapabilityCheckResultReceiptSha256(result),
      status: result.status,
    },
  ]));
  let probeReceipt;
  try {
    probeReceipt = buildRuntimeCapabilityProbeReceipt({
      platform: request.platform,
      architecture: request.architecture,
      executables: receiptExecutables,
      checkResults,
    });
  } catch (error) {
    if (error instanceof RuntimeCapabilityError) {
      throw new RuntimeCapabilityProbeProducerError(error.message, { cause: error });
    }
    throw error;
  }
  if (probeReceipt.runtime.runtime_manifest_sha256 !== receiptRuntimeHash) {
    fail('built probe receipt drifted from measured runtime manifest');
  }
  return validateRuntimeCapabilityProbeProduction({
    probeReceipt,
    resultReceipts,
  });
}

module.exports = Object.freeze({
  CHECK_RESULT_RECEIPT_SCHEMA_VERSION,
  CHECK_RESULT_RECEIPT_PRODUCER,
  CHECK_OUTCOMES,
  MAX_CHECK_TIMEOUT_MS,
  DEFAULT_CHECK_TIMEOUT_MS,
  MAX_MEASUREMENTS,
  MAX_EVIDENCE_ITEMS,
  MAX_EVIDENCE_ITEM_BYTES,
  MAX_TOTAL_EVIDENCE_BYTES,
  MAX_MEASUREMENT_MAGNITUDE,
  RuntimeCapabilityProbeProducerError,
  fixedCheckContractBytes,
  fixedCheckFixtureBytes,
  validateRuntimeCapabilityCheckResultReceipt,
  canonicalRuntimeCapabilityCheckResultReceiptJson,
  runtimeCapabilityCheckResultReceiptSha256,
  validateRuntimeCapabilityProbeProduction,
  produceRuntimeCapabilityProbe,
});
