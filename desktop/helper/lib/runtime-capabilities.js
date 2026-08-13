'use strict';

// Strict JavaScript mirror of autoeditor/runtime_capabilities.py. A receipt is
// evidence about fixed local checks; it is not allowed to carry its own
// capability mapping or availability claims.

const crypto = require('node:crypto');
const { CAPABILITIES } = require('./edit-policy');

const RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION =
  'autoeditor-runtime-capability-probe-receipt/v1';
const RUNTIME_CAPABILITY_PROBE_PRODUCER = 'autoeditor-local-runtime-probe/v1';
const TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION =
  'autoeditor-trusted-capability-manifest/v1';
const TRUSTED_CAPABILITY_MANIFEST_SOURCE = RUNTIME_CAPABILITY_PROBE_PRODUCER;
const RUNTIME_PLATFORMS = Object.freeze(['darwin', 'linux', 'win32']);
const RUNTIME_ARCHITECTURES = Object.freeze(['arm64', 'x64']);
const CHECK_STATUSES = Object.freeze(['fail', 'pass']);
const MAX_EXECUTABLES = 32;

const CAPABILITY_CHECK_IDS = Object.freeze([
  'artifact_receipts',
  'audio_crossfades',
  'audio_quality_analysis',
  'caption_rendering',
  'chart_rendering',
  'color_normalization',
  'cross_dissolves',
  'dialogue_cleanup',
  'graphic_rendering',
  'hard_cuts',
  'loudness_normalization',
  'motion_quality_analysis',
  'project_generated_music',
  'project_generated_sfx',
  'scene_detection',
  'speech_transcription',
  'visual_quality_analysis',
  'word_timestamps',
]);
const CAPABILITY_CHECK_MAPPING = Object.freeze(Object.fromEntries(
  CAPABILITY_CHECK_IDS.map((id) => [id, id]),
));

const ROOT_KEYS = Object.freeze([
  'checks', 'fixture_set_sha256', 'producer', 'runtime', 'schema_version',
]);
const RUNTIME_KEYS = Object.freeze([
  'architecture', 'executables', 'platform', 'runtime_manifest_sha256',
]);
const EXECUTABLE_KEYS = Object.freeze(['name', 'sha256']);
const CHECK_KEYS = Object.freeze([
  'contract_sha256',
  'fixture_sha256',
  'id',
  'result_receipt_sha256',
  'status',
]);
const SHA256 = /^[0-9a-f]{64}$/;
const EXECUTABLE_NAME = /^[a-z][a-z0-9._-]{0,63}$/;
const PLATFORM_SET = new Set(RUNTIME_PLATFORMS);
const ARCHITECTURE_SET = new Set(RUNTIME_ARCHITECTURES);
const STATUS_SET = new Set(CHECK_STATUSES);
const POLICY_CAPABILITY_SET = new Set(CAPABILITIES);

if (CAPABILITY_CHECK_IDS.some((id, index) => (
  (index > 0 && CAPABILITY_CHECK_IDS[index - 1] >= id) ||
  !POLICY_CAPABILITY_SET.has(id) || CAPABILITY_CHECK_MAPPING[id] !== id
))) {
  throw new Error('runtime capability check surface drifted from edit-policy/v1');
}

class RuntimeCapabilityError extends Error {
  constructor(message) {
    super(message);
    this.name = 'RuntimeCapabilityError';
  }
}

function fail(message) {
  throw new RuntimeCapabilityError(message);
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
    fail(`${label} has invalid keys (unsupported non-string key)`);
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

function digest(value, label) {
  if (typeof value !== 'string' || !SHA256.test(value)) {
    fail(`${label} must be a full lowercase SHA-256 digest`);
  }
  return value;
}

function boundedIdentifier(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} is unsupported`);
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

function sha256Text(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function expectedContractSha256(id) {
  return sha256Text(`autoeditor-runtime-capability-check-contract/${id}/v1`);
}

function expectedFixtureSha256(id) {
  return sha256Text(`autoeditor-runtime-capability-check-fixture/${id}/v1`);
}

const CAPABILITY_CHECK_CONTRACT_SHA256 = Object.freeze(Object.fromEntries(
  CAPABILITY_CHECK_IDS.map((id) => [id, expectedContractSha256(id)]),
));
const CAPABILITY_CHECK_FIXTURE_SHA256 = Object.freeze(Object.fromEntries(
  CAPABILITY_CHECK_IDS.map((id) => [id, expectedFixtureSha256(id)]),
));
const HONEST_RUNTIME_CAPABILITIES = Object.freeze(
  Object.values(CAPABILITY_CHECK_MAPPING).sort(asciiCompare),
);
const EXPECTED_FIXTURE_SET_SHA256 = sha256Text(canonicalJsonData(
  CAPABILITY_CHECK_IDS.map((id) => ({
    id,
    fixture_sha256: CAPABILITY_CHECK_FIXTURE_SHA256[id],
  })),
  'fixture set',
));

function validateExecutables(value) {
  if (!isDenseArray(value) || value.length < 1 || value.length > MAX_EXECUTABLES) {
    fail(`runtime.executables must contain 1-${MAX_EXECUTABLES} sorted entries`);
  }
  const normalized = value.map((raw, index) => {
    const label = `runtime.executables[${index}]`;
    const item = exactKeys(raw, EXECUTABLE_KEYS, label);
    return {
      name: boundedIdentifier(item.name, EXECUTABLE_NAME, `${label}.name`),
      sha256: digest(item.sha256, `${label}.sha256`),
    };
  });
  const names = normalized.map((item) => item.name);
  const sorted = [...new Set(names)].sort(asciiCompare);
  if (sorted.length !== names.length ||
      sorted.some((name, index) => name !== names[index])) {
    fail('runtime.executables must be sorted by unique name');
  }
  return normalized;
}

function runtimeManifestSha256(platform, architecture, executables) {
  if (typeof platform !== 'string' || !PLATFORM_SET.has(platform)) {
    fail('runtime.platform is unsupported');
  }
  if (typeof architecture !== 'string' || !ARCHITECTURE_SET.has(architecture)) {
    fail('runtime.architecture is unsupported');
  }
  const normalizedExecutables = validateExecutables(executables);
  return sha256Text(canonicalJsonData({
    platform,
    architecture,
    executables: normalizedExecutables,
  }, 'runtime manifest'));
}

function fixtureSet(checks) {
  return checks.map((check) => ({ id: check.id, fixture_sha256: check.fixture_sha256 }));
}

function fixtureSetSha256(checks) {
  return sha256Text(canonicalJsonData(fixtureSet(checks), 'fixture set'));
}

function validateRuntimeCapabilityProbeReceipt(value) {
  const raw = exactKeys(value, ROOT_KEYS, 'runtime capability probe receipt');
  if (raw.schema_version !== RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION) {
    fail('runtime capability probe receipt schema_version is unsupported');
  }
  if (raw.producer !== RUNTIME_CAPABILITY_PROBE_PRODUCER) {
    fail('runtime capability probe receipt producer is untrusted');
  }

  const rawRuntime = exactKeys(raw.runtime, RUNTIME_KEYS, 'runtime');
  const runtime = {
    platform: rawRuntime.platform,
    architecture: rawRuntime.architecture,
    executables: validateExecutables(rawRuntime.executables),
    runtime_manifest_sha256: digest(
      rawRuntime.runtime_manifest_sha256, 'runtime.runtime_manifest_sha256',
    ),
  };
  if (typeof runtime.platform !== 'string' || !PLATFORM_SET.has(runtime.platform)) {
    fail('runtime.platform is unsupported');
  }
  if (typeof runtime.architecture !== 'string' ||
      !ARCHITECTURE_SET.has(runtime.architecture)) {
    fail('runtime.architecture is unsupported');
  }
  const measuredRuntimeHash = runtimeManifestSha256(
    runtime.platform, runtime.architecture, runtime.executables,
  );
  if (runtime.runtime_manifest_sha256 !== measuredRuntimeHash) {
    fail('runtime.runtime_manifest_sha256 does not bind the runtime manifest');
  }

  if (!isDenseArray(raw.checks) || raw.checks.length !== CAPABILITY_CHECK_IDS.length) {
    fail(`checks must contain exactly ${CAPABILITY_CHECK_IDS.length} entries`);
  }
  const checks = raw.checks.map((rawCheck, index) => {
    const label = `checks[${index}]`;
    const check = exactKeys(rawCheck, CHECK_KEYS, label);
    const id = check.id;
    if (typeof id !== 'string' || id !== CAPABILITY_CHECK_IDS[index]) {
      fail('checks must contain every fixed check id once in sorted order');
    }
    const contractHash = digest(check.contract_sha256, `${label}.contract_sha256`);
    if (contractHash !== CAPABILITY_CHECK_CONTRACT_SHA256[id]) {
      fail(`${label}.contract_sha256 does not bind the fixed check contract`);
    }
    const fixtureHash = digest(check.fixture_sha256, `${label}.fixture_sha256`);
    if (fixtureHash !== CAPABILITY_CHECK_FIXTURE_SHA256[id]) {
      fail(`${label}.fixture_sha256 does not bind the fixed check fixture`);
    }
    if (typeof check.status !== 'string' || !STATUS_SET.has(check.status)) {
      fail(`${label}.status is unsupported`);
    }
    return {
      id,
      contract_sha256: contractHash,
      fixture_sha256: fixtureHash,
      result_receipt_sha256: digest(
        check.result_receipt_sha256, `${label}.result_receipt_sha256`,
      ),
      status: check.status,
    };
  });

  const fixtureHash = digest(raw.fixture_set_sha256, 'fixture_set_sha256');
  if (fixtureHash !== EXPECTED_FIXTURE_SET_SHA256 ||
      fixtureHash !== fixtureSetSha256(checks)) {
    fail('fixture_set_sha256 does not bind the fixed check fixture set');
  }
  return {
    schema_version: RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION,
    producer: RUNTIME_CAPABILITY_PROBE_PRODUCER,
    runtime,
    fixture_set_sha256: fixtureHash,
    checks,
  };
}

function buildRuntimeCapabilityProbeReceipt(value) {
  const request = exactKeys(
    value,
    ['architecture', 'checkResults', 'executables', 'platform'],
    'runtime capability probe build request',
  );
  const {
    platform, architecture, executables, checkResults,
  } = request;
  if (typeof platform !== 'string' || !PLATFORM_SET.has(platform)) {
    fail('runtime.platform is unsupported');
  }
  if (typeof architecture !== 'string' || !ARCHITECTURE_SET.has(architecture)) {
    fail('runtime.architecture is unsupported');
  }
  const normalizedExecutables = validateExecutables(executables);
  if (!isPlainObject(checkResults)) {
    fail('check_results must be an object keyed by every v1 check id');
  }
  const ownKeys = Reflect.ownKeys(checkResults);
  if (ownKeys.some((key) => typeof key !== 'string')) {
    fail('check_results has invalid check ids (unsupported non-string key)');
  }
  const actual = ownKeys.sort(asciiCompare);
  if (actual.length !== CAPABILITY_CHECK_IDS.length ||
      actual.some((id, index) => id !== CAPABILITY_CHECK_IDS[index])) {
    const actualSet = new Set(actual);
    const expectedSet = new Set(CAPABILITY_CHECK_IDS);
    const missing = CAPABILITY_CHECK_IDS.filter((id) => !actualSet.has(id));
    const extra = actual.filter((id) => !expectedSet.has(id));
    const details = [];
    if (missing.length) details.push(`missing ${missing.join(', ')}`);
    if (extra.length) details.push(`unsupported ${extra.join(', ')}`);
    fail(`check_results has invalid check ids (${details.join('; ')})`);
  }
  const checks = CAPABILITY_CHECK_IDS.map((id) => {
    const raw = exactKeys(
      checkResults[id],
      ['result_receipt_sha256', 'status'],
      `check_results.${id}`,
    );
    if (typeof raw.status !== 'string' || !STATUS_SET.has(raw.status)) {
      fail(`check_results.${id}.status is unsupported`);
    }
    return {
      id,
      contract_sha256: CAPABILITY_CHECK_CONTRACT_SHA256[id],
      fixture_sha256: CAPABILITY_CHECK_FIXTURE_SHA256[id],
      result_receipt_sha256: digest(
        raw.result_receipt_sha256, `check_results.${id}.result_receipt_sha256`,
      ),
      status: raw.status,
    };
  });
  const runtimeHash = runtimeManifestSha256(
    platform, architecture, normalizedExecutables,
  );
  return validateRuntimeCapabilityProbeReceipt({
    schema_version: RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION,
    producer: RUNTIME_CAPABILITY_PROBE_PRODUCER,
    runtime: {
      platform,
      architecture,
      executables: normalizedExecutables,
      runtime_manifest_sha256: runtimeHash,
    },
    fixture_set_sha256: EXPECTED_FIXTURE_SET_SHA256,
    checks,
  });
}

function canonicalRuntimeCapabilityProbeReceiptJson(receipt) {
  return canonicalJsonData(
    validateRuntimeCapabilityProbeReceipt(receipt),
    'runtime capability probe receipt',
  );
}

function runtimeCapabilityProbeReceiptSha256(receipt) {
  return sha256Text(canonicalRuntimeCapabilityProbeReceiptJson(receipt));
}

function deriveTrustedCapabilityManifest(receipt) {
  const normalized = validateRuntimeCapabilityProbeReceipt(receipt);
  const available = normalized.checks
    .filter((check) => check.status === 'pass')
    .map((check) => CAPABILITY_CHECK_MAPPING[check.id])
    .sort(asciiCompare);
  return {
    schema_version: TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION,
    source: TRUSTED_CAPABILITY_MANIFEST_SOURCE,
    probe_receipt_sha256: sha256Text(canonicalJsonData(
      normalized, 'runtime capability probe receipt',
    )),
    available_capabilities: available,
  };
}

module.exports = Object.freeze({
  RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION,
  RUNTIME_CAPABILITY_PROBE_PRODUCER,
  TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION,
  TRUSTED_CAPABILITY_MANIFEST_SOURCE,
  RUNTIME_PLATFORMS,
  RUNTIME_ARCHITECTURES,
  CHECK_STATUSES,
  MAX_EXECUTABLES,
  CAPABILITY_CHECK_IDS,
  CAPABILITY_CHECK_MAPPING,
  HONEST_RUNTIME_CAPABILITIES,
  CHECK_CONTRACT_SHA256: CAPABILITY_CHECK_CONTRACT_SHA256,
  CHECK_FIXTURE_SHA256: CAPABILITY_CHECK_FIXTURE_SHA256,
  EXPECTED_FIXTURE_SET_SHA256,
  RuntimeCapabilityError,
  runtimeManifestSha256,
  validateRuntimeCapabilityProbeReceipt,
  buildRuntimeCapabilityProbeReceipt,
  canonicalRuntimeCapabilityProbeReceiptJson,
  runtimeCapabilityProbeReceiptSha256,
  deriveTrustedCapabilityManifest,
});
