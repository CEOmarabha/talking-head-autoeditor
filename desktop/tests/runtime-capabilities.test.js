'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {
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
  CHECK_CONTRACT_SHA256,
  CHECK_FIXTURE_SHA256,
  EXPECTED_FIXTURE_SET_SHA256,
  RuntimeCapabilityError,
  runtimeManifestSha256,
  validateRuntimeCapabilityProbeReceipt,
  buildRuntimeCapabilityProbeReceipt,
  canonicalRuntimeCapabilityProbeReceiptJson,
  runtimeCapabilityProbeReceiptSha256,
  deriveTrustedCapabilityManifest,
} = require('../helper/lib/runtime-capabilities');
const {
  CAPABILITIES,
} = require('../helper/lib/edit-policy');
const {
  validateCapabilityManifest,
} = require('../helper/lib/project-intent-policy-bridge');

function sha256(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => (
    `${JSON.stringify(key)}:${canonical(value[key])}`
  )).join(',')}}`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function buildReceipt() {
  const executables = [
    { name: 'ffmpeg', sha256: sha256('ffmpeg') },
    { name: 'ffprobe', sha256: sha256('ffprobe') },
    { name: 'python', sha256: sha256('python') },
  ];
  const runtimeManifest = {
    platform: 'win32',
    architecture: 'x64',
    executables,
  };
  const checks = CAPABILITY_CHECK_IDS.map((id, index) => ({
    id,
    contract_sha256: CHECK_CONTRACT_SHA256[id],
    fixture_sha256: CHECK_FIXTURE_SHA256[id],
    result_receipt_sha256: sha256(`probe-result/${id}`),
    status: id === 'scene_detection' ? 'fail' : 'pass',
  }));
  return {
    schema_version: RUNTIME_CAPABILITY_PROBE_RECEIPT_SCHEMA_VERSION,
    producer: RUNTIME_CAPABILITY_PROBE_PRODUCER,
    runtime: {
      ...runtimeManifest,
      runtime_manifest_sha256: sha256(canonical(runtimeManifest)),
    },
    fixture_set_sha256: sha256(canonical(checks.map((check) => ({
      id: check.id,
      fixture_sha256: check.fixture_sha256,
    })))),
    checks,
  };
}

function rejects(value, pattern = undefined) {
  assert.throws(
    () => validateRuntimeCapabilityProbeReceipt(value),
    (error) => error instanceof RuntimeCapabilityError &&
      (!pattern || pattern.test(error.message)),
  );
}

assert.deepEqual(Object.keys(CAPABILITY_CHECK_MAPPING), CAPABILITY_CHECK_IDS);
assert.deepEqual(Object.values(CAPABILITY_CHECK_MAPPING), CAPABILITY_CHECK_IDS);
assert.ok(CAPABILITY_CHECK_IDS.every((id) => CAPABILITIES.includes(id)));
assert.ok(CAPABILITY_CHECK_IDS.length < CAPABILITIES.length);
assert.ok(Object.isFrozen(CAPABILITY_CHECK_MAPPING));

for (const id of CAPABILITY_CHECK_IDS) {
  assert.equal(
    CHECK_CONTRACT_SHA256[id],
    sha256(`autoeditor-runtime-capability-check-contract/${id}/v1`),
  );
  assert.equal(
    CHECK_FIXTURE_SHA256[id],
    sha256(`autoeditor-runtime-capability-check-fixture/${id}/v1`),
  );
}
assert.deepEqual(HONEST_RUNTIME_CAPABILITIES, CAPABILITY_CHECK_IDS);
assert.deepEqual(RUNTIME_PLATFORMS, ['darwin', 'linux', 'win32']);
assert.deepEqual(RUNTIME_ARCHITECTURES, ['arm64', 'x64']);
assert.deepEqual(CHECK_STATUSES, ['fail', 'pass']);
assert.equal(MAX_EXECUTABLES, 32);
assert.equal(
  EXPECTED_FIXTURE_SET_SHA256,
  'f8dcb0a6dcae61cd1bab4f816685f1b381b73807f609a9cab3dc7101d977933e',
);

for (const count of [18, 19, 24, 25, 31, 32]) {
  const value = buildReceipt();
  value.runtime.executables = Array.from({ length: count }, (_, index) => ({
    name: `tool-${String(index).padStart(2, '0')}`,
    sha256: sha256(String(index)),
  }));
  value.runtime.runtime_manifest_sha256 = runtimeManifestSha256(
    value.runtime.platform,
    value.runtime.architecture,
    value.runtime.executables,
  );
  assert.equal(
    validateRuntimeCapabilityProbeReceipt(value).runtime.executables.length,
    count,
  );
}

{
  const raw = buildReceipt();
  const expected = clone(raw);
  const clean = validateRuntimeCapabilityProbeReceipt(raw);
  assert.deepEqual(clean, expected);
  assert.notEqual(clean, raw);
  assert.notEqual(clean.runtime, raw.runtime);
  assert.notEqual(clean.runtime.executables, raw.runtime.executables);
  assert.notEqual(clean.checks, raw.checks);
  raw.runtime.executables[0].name = 'forged';
  raw.checks[0].status = 'fail';
  assert.deepEqual(clean, expected);
}

{
  const receipt = buildReceipt();
  const manifest = deriveTrustedCapabilityManifest(receipt);
  const expectedCapabilities = receipt.checks
    .filter((check) => check.status === 'pass')
    .map((check) => check.id)
    .sort();
  assert.deepEqual(manifest, {
    schema_version: TRUSTED_CAPABILITY_MANIFEST_SCHEMA_VERSION,
    source: TRUSTED_CAPABILITY_MANIFEST_SOURCE,
    probe_receipt_sha256: runtimeCapabilityProbeReceiptSha256(receipt),
    available_capabilities: expectedCapabilities,
  });
  assert.deepEqual(validateCapabilityManifest(manifest), manifest);

  const statusMutation = clone(receipt);
  statusMutation.checks[0].status = 'fail';
  const changed = deriveTrustedCapabilityManifest(statusMutation);
  assert.notEqual(changed.probe_receipt_sha256, manifest.probe_receipt_sha256);
  assert.ok(!changed.available_capabilities.includes(receipt.checks[0].id));

  const resultMutation = clone(receipt);
  resultMutation.checks[0].result_receipt_sha256 = '0'.repeat(64);
  assert.notEqual(
    deriveTrustedCapabilityManifest(resultMutation).probe_receipt_sha256,
    manifest.probe_receipt_sha256,
  );

  const allFailed = clone(receipt);
  allFailed.checks.forEach((check) => { check.status = 'fail'; });
  assert.deepEqual(
    deriveTrustedCapabilityManifest(allFailed).available_capabilities,
    [],
  );
}

{
  const receipt = buildReceipt();
  const canonicalJson = canonicalRuntimeCapabilityProbeReceiptJson(receipt);
  assert.equal(canonicalJson, canonical(receipt));
  assert.equal(
    runtimeCapabilityProbeReceiptSha256(receipt),
    '42c1f89833e385cf1ab61f933c8bb1d1d3ecde0a6191b957a2c5abdc05ead95a',
  );
}

{
  const source = buildReceipt();
  const checkResults = Object.fromEntries(source.checks.map((check) => [
    check.id,
    {
      result_receipt_sha256: check.result_receipt_sha256,
      status: check.status,
    },
  ]));
  const built = buildRuntimeCapabilityProbeReceipt({
    platform: source.runtime.platform,
    architecture: source.runtime.architecture,
    executables: source.runtime.executables,
    checkResults,
  });
  assert.deepEqual(built, source);
  assert.equal(
    runtimeManifestSha256('win32', 'x64', source.runtime.executables),
    'f07a27e50b73960e55b48d7ca3b32f719e6c8333a583dd70eeac7b5c40b4fcc0',
  );

  const missing = clone(checkResults);
  delete missing[CAPABILITY_CHECK_IDS[0]];
  assert.throws(
    () => buildRuntimeCapabilityProbeReceipt({
      platform: 'win32', architecture: 'x64',
      executables: source.runtime.executables, checkResults: missing,
    }),
    RuntimeCapabilityError,
  );
  const forged = clone(checkResults);
  forged.telepathy = { result_receipt_sha256: '0'.repeat(64), status: 'pass' };
  assert.throws(
    () => buildRuntimeCapabilityProbeReceipt({
      platform: 'win32', architecture: 'x64',
      executables: source.runtime.executables, checkResults: forged,
    }),
    RuntimeCapabilityError,
  );
  assert.throws(
    () => buildRuntimeCapabilityProbeReceipt({
      platform: 'win32', architecture: 'x64',
      executables: source.runtime.executables, checkResults,
      availableCapabilities: [...CAPABILITY_CHECK_IDS],
    }),
    RuntimeCapabilityError,
  );
  assert.throws(
    () => buildRuntimeCapabilityProbeReceipt({
      platform: 'win32', architecture: 'x64',
      executables: source.runtime.executables, checkResults,
      capabilityMapping: { hard_cuts: 'hard_cuts' },
    }),
    RuntimeCapabilityError,
  );
}

{
  const forgedRoots = [
    { capability_mapping: { hard_cuts: 'hard_cuts' } },
    { available_capabilities: ['hard_cuts'] },
    { api_key: 'secret' },
    { model_claimed_capabilities: [...CAPABILITIES] },
  ];
  for (const forged of forgedRoots) {
    rejects({ ...buildReceipt(), ...forged }, /invalid keys/);
  }
  const forgedCheck = buildReceipt();
  forgedCheck.checks[0].capability = 'licensed_music';
  rejects(forgedCheck, /invalid keys/);
}

{
  const invalid = [];
  let value = buildReceipt();
  value.schema_version = 'runtime-capabilities/v2';
  invalid.push(value);
  value = buildReceipt();
  value.producer = 'model-runtime-probe/v1';
  invalid.push(value);
  value = buildReceipt();
  value.fixture_set_sha256 = 'A'.repeat(64);
  invalid.push(value);
  value = buildReceipt();
  value.fixture_set_sha256 = '0'.repeat(64);
  invalid.push(value);
  value = buildReceipt();
  value.runtime.runtime_manifest_sha256 = '0'.repeat(64);
  invalid.push(value);
  value = buildReceipt();
  value.runtime.extra = true;
  invalid.push(value);
  value = buildReceipt();
  value.runtime.platform = 'WIN 32';
  invalid.push(value);
  value = buildReceipt();
  value.runtime.architecture = '';
  invalid.push(value);
  value = buildReceipt();
  value.runtime.platform = 'windows';
  invalid.push(value);
  value = buildReceipt();
  value.runtime.architecture = 'amd64';
  invalid.push(value);
  value = buildReceipt();
  value.runtime.executables.reverse();
  invalid.push(value);
  value = buildReceipt();
  value.runtime.executables.push(clone(value.runtime.executables[1]));
  invalid.push(value);
  value = buildReceipt();
  value.runtime.executables[0].sha256 = 'a'.repeat(63);
  invalid.push(value);
  value = buildReceipt();
  value.runtime.executables[0].extra = true;
  invalid.push(value);
  value = buildReceipt();
  value.runtime.executables[0].name = 'FFmpeg';
  invalid.push(value);
  value = buildReceipt();
  value.runtime.executables = Array.from({ length: MAX_EXECUTABLES + 1 }, (_, index) => ({
    name: `tool-${String(index).padStart(2, '0')}`,
    sha256: sha256(String(index)),
  }));
  invalid.push(value);
  invalid.forEach((candidate) => rejects(candidate));
}

{
  const invalid = [];
  let value = buildReceipt();
  value.checks.pop();
  invalid.push(value);
  value = buildReceipt();
  [value.checks[0], value.checks[1]] = [value.checks[1], value.checks[0]];
  invalid.push(value);
  value = buildReceipt();
  value.checks[1] = clone(value.checks[0]);
  invalid.push(value);
  value = buildReceipt();
  value.checks[0].id = 'licensed_music';
  invalid.push(value);
  value = buildReceipt();
  value.checks[0].contract_sha256 = '0'.repeat(64);
  invalid.push(value);
  value = buildReceipt();
  value.checks[0].fixture_sha256 = '0'.repeat(64);
  invalid.push(value);
  value = buildReceipt();
  value.checks[0].result_receipt_sha256 = 'A'.repeat(64);
  invalid.push(value);
  value = buildReceipt();
  value.checks[0].status = 'skip';
  invalid.push(value);
  value = buildReceipt();
  value.checks[0].status = true;
  invalid.push(value);
  value = buildReceipt();
  delete value.checks[0].fixture_sha256;
  invalid.push(value);
  invalid.forEach((candidate) => rejects(candidate));
}

{
  let value = buildReceipt();
  delete value.checks[0];
  rejects(value);
  value = buildReceipt();
  value[Symbol('forged')] = true;
  rejects(value, /non-string key/);
  value = buildReceipt();
  value.runtime.executables[0][Symbol('forged')] = true;
  rejects(value, /non-string key/);
  value = buildReceipt();
  value.checks[0][Symbol('forged')] = true;
  rejects(value, /non-string key/);
}

console.log('runtime capabilities tests passed');
