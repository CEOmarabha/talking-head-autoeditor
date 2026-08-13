'use strict';

// Sealed, fail-closed qualification contract for semantic visual evaluation.
//
// This module deliberately does not contain benchmark media or model prompts.
// It binds a source/template-disjoint corpus to exact local bytes, validates
// blind offline run receipts from both supported backends, recomputes every
// metric from per-case decisions, and only advertises the capability when all
// conservative gates pass on all three repetitions.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const MANIFEST_SCHEMA_VERSION =
  'autoeditor-semantic-visual-qualification-manifest/v1';
const CORPUS_BINDING_SCHEMA_VERSION =
  'autoeditor-semantic-visual-corpus-binding/v1';
const RUN_SCHEMA_VERSION =
  'autoeditor-semantic-visual-qualification-run/v1';
const RESULT_SCHEMA_VERSION =
  'autoeditor-semantic-visual-qualification-result/v1';
// This is the existing runtime-policy capability identifier. A qualification
// result is the only authority allowed to advertise it.
const CAPABILITY = 'visual_quality_analysis';

const ASSERTION_CLASSES = Object.freeze([
  'target',
  'captions',
  'framing',
  'visualVariety',
  'graphics',
  'transitions',
  'productionDesign',
]);
const SUBJECTIVE_ASSERTION_CLASSES = Object.freeze(
  ASSERTION_CLASSES.filter((value) => value !== 'target'),
);
const LABELS = Object.freeze(['clean', 'defect', 'ambiguous']);
const DECISIONS = Object.freeze(['clean', 'defect', 'abstain']);
const SPLITS = Object.freeze(['development', 'qualification']);
const BACKENDS = Object.freeze(['webgpu', 'wasm']);
const PROMPT_INJECTION_TAGS = Object.freeze([
  'none',
  'visible-text',
  'metadata',
  'visible-text-and-metadata',
]);

const THRESHOLDS = deepFreeze({
  defectRecall: 0.95,
  defectRecallWilsonLower: 0.90,
  cleanPassRate: 0.90,
  cleanPassWilsonLower: 0.85,
  falsePassRateMax: 0.05,
  ambiguousAbstainRate: 0.95,
  ambiguousAbstainWilsonLower: 0.90,
  macroBalancedAccuracy: 0.92,
  mcc: 0.84,
  repeatAgreement: 0.98,
  backendAgreement: 0.98,
});

const REQUIRED_POLICY = deepFreeze({
  developmentSplit: 'development',
  qualificationSplit: 'qualification',
  requiredBackends: [...BACKENDS],
  repetitionsPerBackend: 3,
  networkMode: 'disabled',
  minimumCasesPerQualificationClass: {
    clean: 100,
    defect: 100,
    ambiguous: 40,
  },
  minimumCasesPerDevelopmentClass: {
    clean: 1,
    defect: 1,
    ambiguous: 1,
  },
  minimumUniqueSourcesPerQualificationClass: 25,
  minimumUniqueTemplatesPerQualificationClass: 10,
  minimumUniqueAssetsPerQualificationClass: 100,
  minimumPromptInjectionCasesPerBinaryLabel: 10,
  thresholds: THRESHOLDS,
});

const SHA256 = /^[0-9a-f]{64}$/;
const SIMPLE_ID = /^[a-z][a-z0-9._-]{0,95}$/;
const CASE_ID = /^svq-[0-9a-f]{64}$/;
const ASSET_ID = /^sha256:[0-9a-f]{64}$/;
const MAX_CASES = 20_000;
const MAX_ASSETS_PER_CASE = 8;
const MAX_IMAGE_BYTES = 64 * 1024 * 1024;
const MAX_VIDEO_BYTES = 1024 * 1024 * 1024;
const MAX_OBSERVATION_BYTES = 4096;
const Z_95 = 1.959963984540054;

const MEDIA_LIMITS = Object.freeze({
  'image/jpeg': MAX_IMAGE_BYTES,
  'image/png': MAX_IMAGE_BYTES,
  'video/mp4': MAX_VIDEO_BYTES,
  'video/webm': MAX_VIDEO_BYTES,
});

class SemanticVisualQualificationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SemanticVisualQualificationError';
  }
}

function fail(message) {
  throw new SemanticVisualQualificationError(message);
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) {
    return value;
  }
  Object.freeze(value);
  for (const child of Object.values(value)) deepFreeze(child);
  return value;
}

function isPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exactKeys(value, keys, label) {
  if (!isPlainObject(value) ||
      Object.keys(value).sort().join('\0') !== [...keys].sort().join('\0')) {
    fail(`${label} has invalid keys`);
  }
  return value;
}

function canonicalJson(value) {
  const seen = new Set();
  function encode(input, location) {
    if (input === null) return 'null';
    if (typeof input === 'string' || typeof input === 'boolean') {
      return JSON.stringify(input);
    }
    if (typeof input === 'number') {
      if (!Number.isFinite(input)) fail(`${location} is not canonical JSON`);
      return JSON.stringify(Object.is(input, -0) ? 0 : input);
    }
    if (Array.isArray(input)) {
      if (seen.has(input)) fail(`${location} is cyclic`);
      seen.add(input);
      const encoded = `[${input.map((entry, index) =>
        encode(entry, `${location}[${index}]`)).join(',')}]`;
      seen.delete(input);
      return encoded;
    }
    if (!isPlainObject(input) || seen.has(input)) {
      fail(`${location} is not canonical JSON`);
    }
    seen.add(input);
    const entries = Object.keys(input).sort().map((key) => {
      if (key === '__proto__' || key === 'prototype' || key === 'constructor' ||
          typeof input[key] === 'undefined' || typeof input[key] === 'function' ||
          typeof input[key] === 'symbol' || typeof input[key] === 'bigint') {
        fail(`${location} is not canonical JSON`);
      }
      return `${JSON.stringify(key)}:${encode(input[key], `${location}.${key}`)}`;
    });
    seen.delete(input);
    return `{${entries.join(',')}}`;
  }
  return encode(value, 'value');
}

function sha256Canonical(value) {
  return crypto.createHash('sha256').update(canonicalJson(value), 'utf8')
    .digest('hex');
}

function sealUnsigned(unsigned) {
  return {
    ...unsigned,
    seal: {
      algorithm: 'sha256',
      sha256: sha256Canonical(unsigned),
    },
  };
}

function validateSeal(value, unsignedKeys, label) {
  exactKeys(value, [...unsignedKeys, 'seal'], label);
  const seal = exactKeys(value.seal, ['algorithm', 'sha256'], `${label} seal`);
  if (seal.algorithm !== 'sha256' || !SHA256.test(seal.sha256)) {
    fail(`${label} seal is invalid`);
  }
  const unsigned = {};
  for (const key of unsignedKeys) unsigned[key] = value[key];
  if (sha256Canonical(unsigned) !== seal.sha256) {
    fail(`${label} seal does not match its contents`);
  }
  return unsigned;
}

function cloneCanonical(value) {
  return JSON.parse(canonicalJson(value));
}

function sealQualificationManifest(unsignedManifest) {
  exactKeys(unsignedManifest, [
    'schemaVersion', 'corpusId', 'policy', 'cases',
  ], 'unsigned semantic visual manifest');
  return sealUnsigned(cloneCanonical(unsignedManifest));
}

function sealCorpusBinding(unsignedBinding) {
  exactKeys(unsignedBinding, [
    'schemaVersion', 'manifestSha256', 'network', 'assets',
  ], 'unsigned semantic visual corpus binding');
  return sealUnsigned(cloneCanonical(unsignedBinding));
}

function sealQualificationRunReceipt(unsignedRun) {
  exactKeys(unsignedRun, [
    'schemaVersion', 'runId', 'manifestSha256', 'corpusBindingSha256',
    'network', 'blindEvaluation', 'backends',
  ], 'unsigned semantic visual qualification run');
  return sealUnsigned(cloneCanonical(unsignedRun));
}

function computeDecisionSetSha256(backends) {
  if (!Array.isArray(backends)) {
    fail('semantic visual decision set is invalid');
  }
  return sha256Canonical(backends.map((backend, backendIndex) => {
    if (!isPlainObject(backend) || !Array.isArray(backend.repeats)) {
      fail(`semantic visual decision set backend ${backendIndex} is invalid`);
    }
    return {
      backend: backend.backend,
      repeats: backend.repeats.map((repeat, repeatIndex) => {
        if (!isPlainObject(repeat) || !Array.isArray(repeat.decisions)) {
          fail(`semantic visual decision set repeat ${repeatIndex} is invalid`);
        }
        return { repeat: repeat.repeat, decisions: repeat.decisions };
      }),
    };
  }));
}

function computeCaseId(caseWithoutId) {
  if (!isPlainObject(caseWithoutId) ||
      Object.prototype.hasOwnProperty.call(caseWithoutId, 'caseId')) {
    fail('semantic visual case identity input is invalid');
  }
  return `svq-${sha256Canonical(caseWithoutId)}`;
}

function validId(value, label) {
  if (typeof value !== 'string' || !SIMPLE_ID.test(value)) {
    fail(`${label} is invalid`);
  }
  return value;
}

function validateRelativePath(value, label) {
  if (typeof value !== 'string' || value.length < 1 || value.length > 240 ||
      value.includes('\0') || value.includes('\\') || value.includes(':') ||
      value.startsWith('/') || value.endsWith('/') ||
      value.split('/').some((part) => part === '' || part === '.' ||
        part === '..')) {
    fail(`${label} is invalid`);
  }
}

function validateAsset(raw, label) {
  const asset = exactKeys(raw, [
    'assetId', 'relativePath', 'sha256', 'sizeBytes', 'mediaType',
  ], label);
  if (typeof asset.assetId !== 'string' || !ASSET_ID.test(asset.assetId) ||
      typeof asset.sha256 !== 'string' || !SHA256.test(asset.sha256) ||
      asset.assetId !== `sha256:${asset.sha256}` ||
      !Object.prototype.hasOwnProperty.call(MEDIA_LIMITS, asset.mediaType) ||
      !Number.isSafeInteger(asset.sizeBytes) || asset.sizeBytes < 4 ||
      asset.sizeBytes > MEDIA_LIMITS[asset.mediaType]) {
    fail(`${label} is invalid`);
  }
  validateRelativePath(asset.relativePath, `${label} relative path`);
  return asset;
}

function validateAnnotations(raw, assertionClass, goldLabel, label) {
  if (!SUBJECTIVE_ASSERTION_CLASSES.includes(assertionClass)) {
    if (raw !== null) fail(`${label} must be null for objective target cases`);
    return;
  }
  const annotations = exactKeys(raw, [
    'blind', 'annotators', 'adjudication',
  ], label);
  if (annotations.blind !== true || !Array.isArray(annotations.annotators) ||
      annotations.annotators.length !== 3) {
    fail(`${label} requires exactly three blind annotators`);
  }
  const annotatorIds = new Set();
  for (let index = 0; index < annotations.annotators.length; index += 1) {
    const annotation = exactKeys(annotations.annotators[index], [
      'annotatorId', 'label',
    ], `${label} annotator ${index}`);
    validId(annotation.annotatorId, `${label} annotator ${index} ID`);
    if (annotatorIds.has(annotation.annotatorId) ||
        !LABELS.includes(annotation.label)) {
      fail(`${label} annotators are invalid`);
    }
    annotatorIds.add(annotation.annotatorId);
  }
  const adjudication = exactKeys(annotations.adjudication, [
    'adjudicatorId', 'label', 'rationaleSha256',
  ], `${label} adjudication`);
  validId(adjudication.adjudicatorId, `${label} adjudicator ID`);
  if (annotatorIds.has(adjudication.adjudicatorId) ||
      adjudication.label !== goldLabel ||
      typeof adjudication.rationaleSha256 !== 'string' ||
      !SHA256.test(adjudication.rationaleSha256)) {
    fail(`${label} adjudication is invalid`);
  }
}

function validateTarget(raw, assertionClass, label) {
  if (assertionClass !== 'target') {
    if (raw !== null) fail(`${label} must be null outside target cases`);
    return;
  }
  const target = exactKeys(raw, [
    'referenceTargetId', 'querySha256',
  ], label);
  validId(target.referenceTargetId, `${label} reference target ID`);
  if (typeof target.querySha256 !== 'string' ||
      !SHA256.test(target.querySha256)) {
    fail(`${label} query digest is invalid`);
  }
}

function validateCase(raw, index) {
  const label = `semantic visual case ${index}`;
  const item = exactKeys(raw, [
    'caseId', 'assertionClass', 'label', 'split', 'sourceId', 'templateId',
    'assertion', 'promptInjection', 'target', 'assets', 'annotations',
  ], label);
  if (typeof item.caseId !== 'string' || !CASE_ID.test(item.caseId) ||
      !ASSERTION_CLASSES.includes(item.assertionClass) ||
      !LABELS.includes(item.label) || !SPLITS.includes(item.split) ||
      !PROMPT_INJECTION_TAGS.includes(item.promptInjection)) {
    fail(`${label} is invalid`);
  }
  validId(item.sourceId, `${label} source ID`);
  validId(item.templateId, `${label} template ID`);
  const assertion = exactKeys(item.assertion, [
    'rubricId', 'promptSha256',
  ], `${label} assertion`);
  validId(assertion.rubricId, `${label} rubric ID`);
  if (typeof assertion.promptSha256 !== 'string' ||
      !SHA256.test(assertion.promptSha256)) {
    fail(`${label} assertion prompt digest is invalid`);
  }
  validateTarget(item.target, item.assertionClass, `${label} target`);
  validateAnnotations(item.annotations, item.assertionClass, item.label,
    `${label} annotations`);
  if (!Array.isArray(item.assets) || item.assets.length < 1 ||
      item.assets.length > MAX_ASSETS_PER_CASE) {
    fail(`${label} assets are invalid`);
  }
  const localAssets = new Set();
  item.assets.forEach((asset, assetIndex) => {
    validateAsset(asset, `${label} asset ${assetIndex}`);
    if (localAssets.has(asset.assetId)) fail(`${label} repeats an asset`);
    localAssets.add(asset.assetId);
  });
  const { caseId: _discarded, ...identity } = item;
  if (computeCaseId(identity) !== item.caseId) {
    fail(`${label} ID does not match its sealed identity`);
  }
  return item;
}

function policyMatches(raw) {
  return canonicalJson(raw) === canonicalJson(REQUIRED_POLICY);
}

function counterKey(assertionClass, label) {
  return `${assertionClass}\0${label}`;
}

function validateQualificationManifest(manifest) {
  const unsignedKeys = ['schemaVersion', 'corpusId', 'policy', 'cases'];
  validateSeal(manifest, unsignedKeys, 'semantic visual manifest');
  if (manifest.schemaVersion !== MANIFEST_SCHEMA_VERSION ||
      typeof manifest.corpusId !== 'string' ||
      !/^[a-z][a-z0-9._-]{2,79}$/.test(manifest.corpusId) ||
      !policyMatches(manifest.policy) || !Array.isArray(manifest.cases) ||
      manifest.cases.length < 1 || manifest.cases.length > MAX_CASES) {
    fail('semantic visual manifest contract is invalid');
  }

  const caseIds = new Set();
  const assetDescriptors = new Map();
  const sourceSplits = new Map();
  const templateSplits = new Map();
  const counts = new Map();
  const injectedCounts = new Map();
  const qualificationSources = new Map();
  const qualificationTemplates = new Map();
  const qualificationAssets = new Map();

  for (let index = 0; index < manifest.cases.length; index += 1) {
    const item = validateCase(manifest.cases[index], index);
    if (caseIds.has(item.caseId)) fail('semantic visual case IDs overlap');
    caseIds.add(item.caseId);

    const priorSourceSplit = sourceSplits.get(item.sourceId);
    if (priorSourceSplit && priorSourceSplit !== item.split) {
      fail('semantic visual source IDs cross development and qualification splits');
    }
    sourceSplits.set(item.sourceId, item.split);
    const priorTemplateSplit = templateSplits.get(item.templateId);
    if (priorTemplateSplit && priorTemplateSplit !== item.split) {
      fail('semantic visual template IDs cross development and qualification splits');
    }
    templateSplits.set(item.templateId, item.split);

    const countKey = `${item.split}\0${counterKey(
      item.assertionClass, item.label)}`;
    counts.set(countKey, (counts.get(countKey) || 0) + 1);
    if (item.split === REQUIRED_POLICY.qualificationSplit) {
      if (!qualificationSources.has(item.assertionClass)) {
        qualificationSources.set(item.assertionClass, new Set());
        qualificationTemplates.set(item.assertionClass, new Set());
        qualificationAssets.set(item.assertionClass, new Set());
      }
      qualificationSources.get(item.assertionClass).add(item.sourceId);
      qualificationTemplates.get(item.assertionClass).add(item.templateId);
      for (const asset of item.assets) {
        qualificationAssets.get(item.assertionClass).add(asset.assetId);
      }
      if (item.promptInjection !== 'none' && item.label !== 'ambiguous') {
        const injectionKey = counterKey(item.assertionClass, item.label);
        injectedCounts.set(injectionKey,
          (injectedCounts.get(injectionKey) || 0) + 1);
      }
    }

    for (const asset of item.assets) {
      const prior = assetDescriptors.get(asset.assetId);
      if (prior && canonicalJson(prior) !== canonicalJson(asset)) {
        fail('semantic visual asset IDs do not identify one exact byte descriptor');
      }
      assetDescriptors.set(asset.assetId, asset);
    }
  }

  for (const assertionClass of ASSERTION_CLASSES) {
    for (const label of LABELS) {
      const qualificationMinimum =
        REQUIRED_POLICY.minimumCasesPerQualificationClass[label];
      const developmentMinimum =
        REQUIRED_POLICY.minimumCasesPerDevelopmentClass[label];
      if ((counts.get(`qualification\0${counterKey(assertionClass, label)}`) ||
          0) < qualificationMinimum) {
        fail(`semantic visual qualification coverage is insufficient for ${
          assertionClass}/${label}`);
      }
      if ((counts.get(`development\0${counterKey(assertionClass, label)}`) ||
          0) < developmentMinimum) {
        fail(`semantic visual development coverage is insufficient for ${
          assertionClass}/${label}`);
      }
    }
    if ((qualificationSources.get(assertionClass)?.size || 0) <
          REQUIRED_POLICY.minimumUniqueSourcesPerQualificationClass ||
        (qualificationTemplates.get(assertionClass)?.size || 0) <
          REQUIRED_POLICY.minimumUniqueTemplatesPerQualificationClass ||
        (qualificationAssets.get(assertionClass)?.size || 0) <
          REQUIRED_POLICY.minimumUniqueAssetsPerQualificationClass) {
      fail(`semantic visual qualification diversity is insufficient for ${
        assertionClass}`);
    }
    for (const label of ['clean', 'defect']) {
      if ((injectedCounts.get(counterKey(assertionClass, label)) || 0) <
          REQUIRED_POLICY.minimumPromptInjectionCasesPerBinaryLabel) {
        fail(`semantic visual prompt-injection coverage is insufficient for ${
          assertionClass}/${label}`);
      }
    }
  }
  return manifest;
}

function expectedAssetDescriptors(manifest) {
  const descriptors = new Map();
  for (const item of manifest.cases) {
    for (const asset of item.assets) descriptors.set(asset.assetId, asset);
  }
  return [...descriptors.values()].sort((left, right) =>
    left.assetId.localeCompare(right.assetId));
}

function validateNetworkReceipt(raw, label) {
  const network = exactKeys(raw, [
    'mode', 'attemptedRequests', 'completedRequests',
  ], label);
  if (network.mode !== 'disabled' || network.attemptedRequests !== 0 ||
      network.completedRequests !== 0) {
    fail(`${label} proves the run was not fully offline`);
  }
}

function validateCorpusBinding(manifest, binding) {
  validateQualificationManifest(manifest);
  validateSeal(binding, [
    'schemaVersion', 'manifestSha256', 'network', 'assets',
  ], 'semantic visual corpus binding');
  if (binding.schemaVersion !== CORPUS_BINDING_SCHEMA_VERSION ||
      binding.manifestSha256 !== manifest.seal.sha256 ||
      !Array.isArray(binding.assets)) {
    fail('semantic visual corpus binding identity is invalid');
  }
  validateNetworkReceipt(binding.network, 'semantic visual corpus binding network');
  const expected = expectedAssetDescriptors(manifest);
  if (binding.assets.length !== expected.length) {
    fail('semantic visual corpus binding does not cover every asset');
  }
  for (let index = 0; index < expected.length; index += 1) {
    const measured = exactKeys(binding.assets[index], [
      'assetId', 'sha256', 'sizeBytes',
    ], `semantic visual corpus binding asset ${index}`);
    const descriptor = expected[index];
    if (measured.assetId !== descriptor.assetId ||
        measured.sha256 !== descriptor.sha256 ||
        measured.sizeBytes !== descriptor.sizeBytes) {
      fail('semantic visual corpus binding asset identity drifted');
    }
  }
  return binding;
}

function assertMediaSignature(descriptor, size, mediaType) {
  const first = Buffer.alloc(Math.min(12, size));
  const last = Buffer.alloc(Math.min(12, size));
  if (fs.readSync(descriptor, first, 0, first.length, 0) !== first.length ||
      fs.readSync(descriptor, last, 0, last.length,
        size - last.length) !== last.length) {
    fail('semantic visual corpus asset ended while checking its media signature');
  }
  const valid = mediaType === 'image/jpeg'
    ? first.length >= 2 && first[0] === 0xff && first[1] === 0xd8 &&
      last.length >= 2 && last[last.length - 2] === 0xff &&
      last[last.length - 1] === 0xd9
    : mediaType === 'image/png'
      ? first.length >= 8 && first.subarray(0, 8).equals(
        Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))
      : mediaType === 'video/mp4'
        ? first.length >= 8 && first.subarray(4, 8).equals(
          Buffer.from('ftyp', 'ascii'))
        : mediaType === 'video/webm'
          ? first.length >= 4 && first.subarray(0, 4).equals(
            Buffer.from([0x1a, 0x45, 0xdf, 0xa3]))
          : false;
  if (!valid) fail('semantic visual corpus asset media signature is invalid');
}

function hashOpenFile(descriptor, expected) {
  let handle;
  try { handle = fs.openSync(descriptor, 'r'); }
  catch (_) { fail('semantic visual corpus asset is unavailable'); }
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size !== expected.sizeBytes) {
      fail('semantic visual corpus asset size drifted');
    }
    assertMediaSignature(handle, before.size, expected.mediaType);
    const digest = crypto.createHash('sha256');
    const chunk = Buffer.allocUnsafe(256 * 1024);
    let offset = 0;
    while (offset < before.size) {
      const count = fs.readSync(handle, chunk, 0,
        Math.min(chunk.length, before.size - offset), offset);
      if (count < 1) fail('semantic visual corpus asset ended while measured');
      digest.update(chunk.subarray(0, count));
      offset += count;
    }
    const after = fs.fstatSync(handle);
    if (after.size !== before.size || after.mtimeMs !== before.mtimeMs ||
        after.dev !== before.dev || after.ino !== before.ino) {
      fail('semantic visual corpus asset changed while measured');
    }
    const sha256 = digest.digest('hex');
    if (sha256 !== expected.sha256) {
      fail('semantic visual corpus asset digest drifted');
    }
    return { assetId: expected.assetId, sha256, sizeBytes: before.size };
  } finally {
    fs.closeSync(handle);
  }
}

function verifyQualificationCorpusFiles(manifest, { corpusRoot } = {}) {
  validateQualificationManifest(manifest);
  if (typeof corpusRoot !== 'string' || !path.isAbsolute(corpusRoot) ||
      corpusRoot.includes('\0')) {
    fail('semantic visual corpus root is invalid');
  }
  let realRoot;
  try { realRoot = fs.realpathSync.native(corpusRoot); }
  catch (_) { fail('semantic visual corpus root is unavailable'); }
  const rootStat = fs.lstatSync(corpusRoot);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    fail('semantic visual corpus root is invalid');
  }
  const measurements = [];
  for (const asset of expectedAssetDescriptors(manifest)) {
    const candidate = path.resolve(realRoot, ...asset.relativePath.split('/'));
    const relative = path.relative(realRoot, candidate);
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
      fail('semantic visual corpus asset escaped its root');
    }
    let real;
    try { real = fs.realpathSync.native(candidate); }
    catch (_) { fail('semantic visual corpus asset is unavailable'); }
    const realRelative = path.relative(realRoot, real);
    if (!realRelative || realRelative.startsWith('..') ||
        path.isAbsolute(realRelative) || fs.lstatSync(candidate).isSymbolicLink()) {
      fail('semantic visual corpus asset is not a sealed regular file');
    }
    measurements.push(hashOpenFile(real, asset));
  }
  return sealCorpusBinding({
    schemaVersion: CORPUS_BINDING_SCHEMA_VERSION,
    manifestSha256: manifest.seal.sha256,
    network: {
      mode: 'disabled',
      attemptedRequests: 0,
      completedRequests: 0,
    },
    assets: measurements,
  });
}

function validateModelIdentity(raw, label) {
  const model = exactKeys(raw, [
    'modelId', 'revision', 'dtype', 'packLockSha256', 'packTreeSha256',
  ], label);
  if (typeof model.modelId !== 'string' || model.modelId.length < 3 ||
      model.modelId.length > 160 || model.modelId.includes('\0') ||
      typeof model.revision !== 'string' || !/^[0-9a-f]{40}$/.test(
        model.revision) || !['q4', 'q4f16', 'int8', 'fp16'].includes(
        model.dtype) || typeof model.packLockSha256 !== 'string' ||
      !SHA256.test(model.packLockSha256) ||
      typeof model.packTreeSha256 !== 'string' ||
      !SHA256.test(model.packTreeSha256)) {
    fail(`${label} is invalid`);
  }
  return model;
}

function validateEntity(raw, caseItem, index) {
  const entity = exactKeys(raw, [
    'label', 'confidence', 'bounds',
  ], `target observation entity ${index}`);
  if (typeof entity.label !== 'string' || entity.label.trim().length < 2 ||
      entity.label.length > 160 || entity.label.includes('\0') ||
      !Number.isFinite(entity.confidence) || entity.confidence < 0 ||
      entity.confidence > 1) {
    fail(`target observation entity ${index} is invalid`);
  }
  const forbidden = [caseItem.caseId, caseItem.sourceId, caseItem.templateId,
    caseItem.target.referenceTargetId].map((value) => value.toLowerCase());
  const normalized = entity.label.toLowerCase();
  if (forbidden.some((value) => normalized.includes(value))) {
    fail('target observation copied a manifest identifier');
  }
  if (entity.bounds !== null) {
    if (!Array.isArray(entity.bounds) || entity.bounds.length !== 4 ||
        entity.bounds.some((value) => !Number.isFinite(value) || value < 0 ||
          value > 1) || entity.bounds[0] + entity.bounds[2] > 1.000001 ||
        entity.bounds[1] + entity.bounds[3] > 1.000001) {
      fail(`target observation entity ${index} bounds are invalid`);
    }
  }
}

function validateEvidence(raw, caseItem) {
  const commonKeys = [
    'kind', 'producer', 'assetIds', 'manifestIdentifiersExposed',
    'observation', 'observationBytes', 'observationSha256', 'observationId',
  ];
  const targetKeys = [...commonKeys, 'queryOutcome', 'entities'];
  const evidence = exactKeys(raw,
    caseItem.assertionClass === 'target' ? targetKeys : commonKeys,
    `semantic visual decision evidence for ${caseItem.caseId}`);
  const observationBytes = typeof evidence.observation === 'string'
    ? Buffer.byteLength(evidence.observation, 'utf8') : -1;
  const observationSha256 = observationBytes >= 0
    ? crypto.createHash('sha256').update(evidence.observation, 'utf8')
      .digest('hex') : '';
  if (!['model', 'detector'].includes(evidence.producer) ||
      evidence.manifestIdentifiersExposed !== false ||
      !Array.isArray(evidence.assetIds) ||
      evidence.assetIds.length !== caseItem.assets.length ||
      evidence.assetIds.some((id, index) => id !==
        caseItem.assets[index].assetId) || observationBytes < 12 ||
      observationBytes > MAX_OBSERVATION_BYTES ||
      evidence.observationBytes !== observationBytes ||
      evidence.observationSha256 !== observationSha256 ||
      evidence.observationId !== `observation:${observationSha256}`) {
    fail(`semantic visual decision evidence for ${caseItem.caseId} is invalid`);
  }
  const normalizedObservation = evidence.observation.toLowerCase();
  const forbidden = [caseItem.caseId, caseItem.sourceId, caseItem.templateId];
  if (caseItem.target) forbidden.push(caseItem.target.referenceTargetId);
  if (forbidden.some((value) => normalizedObservation.includes(
    value.toLowerCase()))) {
    fail('semantic visual observation copied a manifest identifier');
  }
  if (caseItem.assertionClass === 'target') {
    if (evidence.kind !== 'target-observation' ||
        !['present', 'absent', 'uncertain'].includes(evidence.queryOutcome) ||
        !Array.isArray(evidence.entities) || evidence.entities.length > 64 ||
        (evidence.queryOutcome === 'present' &&
          evidence.entities.length < 1)) {
      fail('target decision lacks detector/model observation evidence');
    }
    evidence.entities.forEach((entity, index) =>
      validateEntity(entity, caseItem, index));
  } else if (evidence.kind !== 'semantic-observation') {
    fail('semantic visual decision lacks model/detector observation evidence');
  }
}

function validateDecision(raw, caseItem, label) {
  const decision = exactKeys(raw, [
    'caseId', 'decision', 'promptInjectionFollowed', 'evidence',
  ], label);
  if (decision.caseId !== caseItem.caseId ||
      !DECISIONS.includes(decision.decision) ||
      decision.promptInjectionFollowed !== false) {
    fail(`${label} is invalid`);
  }
  validateEvidence(decision.evidence, caseItem);
  return decision;
}

function validateQualificationRunReceipt(manifest, binding, runReceipt) {
  validateQualificationManifest(manifest);
  validateCorpusBinding(manifest, binding);
  validateSeal(runReceipt, [
    'schemaVersion', 'runId', 'manifestSha256', 'corpusBindingSha256',
    'network', 'blindEvaluation', 'backends',
  ], 'semantic visual qualification run');
  if (runReceipt.schemaVersion !== RUN_SCHEMA_VERSION ||
      typeof runReceipt.runId !== 'string' ||
      !/^[a-z][a-z0-9._-]{2,95}$/.test(runReceipt.runId) ||
      runReceipt.manifestSha256 !== manifest.seal.sha256 ||
      runReceipt.corpusBindingSha256 !== binding.seal.sha256 ||
      !Array.isArray(runReceipt.backends) ||
      runReceipt.backends.length !== BACKENDS.length) {
    fail('semantic visual qualification run identity is invalid');
  }
  validateNetworkReceipt(runReceipt.network,
    'semantic visual qualification run network');
  const blind = exactKeys(runReceipt.blindEvaluation, [
    'promptsContainedGoldLabels', 'promptsContainedCaseIds',
    'promptsContainedReferenceTargetIds', 'decisionsSealedBeforeGoldAccess',
    'decisionSetSha256',
  ], 'semantic visual blind-evaluation receipt');
  if (blind.promptsContainedGoldLabels !== false ||
      blind.promptsContainedCaseIds !== false ||
      blind.promptsContainedReferenceTargetIds !== false ||
      blind.decisionsSealedBeforeGoldAccess !== true ||
      typeof blind.decisionSetSha256 !== 'string' ||
      !SHA256.test(blind.decisionSetSha256) ||
      blind.decisionSetSha256 !== computeDecisionSetSha256(
        runReceipt.backends)) {
    fail('semantic visual run did not preserve blind gold separation');
  }

  const qualificationCases = manifest.cases.filter((item) =>
    item.split === REQUIRED_POLICY.qualificationSplit);
  let boundModel = null;
  for (let backendIndex = 0; backendIndex < BACKENDS.length;
    backendIndex += 1) {
    const expectedBackend = BACKENDS[backendIndex];
    const backend = exactKeys(runReceipt.backends[backendIndex], [
      'backend', 'model', 'network', 'repeats',
    ], `semantic visual backend ${backendIndex}`);
    if (backend.backend !== expectedBackend || !Array.isArray(backend.repeats) ||
        backend.repeats.length !== REQUIRED_POLICY.repetitionsPerBackend) {
      fail(`semantic visual ${expectedBackend} backend receipt is invalid`);
    }
    validateNetworkReceipt(backend.network,
      `semantic visual ${expectedBackend} backend network`);
    const model = validateModelIdentity(backend.model,
      `semantic visual ${expectedBackend} model identity`);
    if (boundModel && canonicalJson(boundModel) !== canonicalJson(model)) {
      fail('semantic visual model identity changed between backends');
    }
    boundModel = model;
    for (let repeatIndex = 0; repeatIndex < backend.repeats.length;
      repeatIndex += 1) {
      const repeat = exactKeys(backend.repeats[repeatIndex], [
        'repeat', 'decisions',
      ], `semantic visual ${expectedBackend} repeat ${repeatIndex + 1}`);
      if (repeat.repeat !== repeatIndex + 1 ||
          !Array.isArray(repeat.decisions) ||
          repeat.decisions.length !== qualificationCases.length) {
        fail(`semantic visual ${expectedBackend} repeat ${
          repeatIndex + 1} coverage is invalid`);
      }
      for (let caseIndex = 0; caseIndex < qualificationCases.length;
        caseIndex += 1) {
        validateDecision(repeat.decisions[caseIndex],
          qualificationCases[caseIndex],
          `semantic visual ${expectedBackend} repeat ${
            repeatIndex + 1} decision ${caseIndex}`);
      }
    }
  }
  return runReceipt;
}

function wilsonLowerBound(successes, total, z = Z_95) {
  if (!Number.isInteger(successes) || !Number.isInteger(total) || total < 1 ||
      successes < 0 || successes > total || !Number.isFinite(z) || z <= 0) {
    fail('Wilson interval inputs are invalid');
  }
  if (successes === 0) return 0;
  const probability = successes / total;
  const zSquared = z * z;
  const center = probability + zSquared / (2 * total);
  const adjustment = z * Math.sqrt(
    probability * (1 - probability) / total + zSquared / (4 * total * total),
  );
  return Math.max(0, Math.min(1,
    (center - adjustment) / (1 + zSquared / total)));
}

function multiclassMcc(pairs) {
  if (!Array.isArray(pairs) || pairs.length < 1) {
    fail('MCC input is invalid');
  }
  const classes = ['clean', 'defect', 'abstain'];
  const matrix = classes.map(() => classes.map(() => 0));
  for (const pair of pairs) {
    if (!Array.isArray(pair) || pair.length !== 2 ||
        !classes.includes(pair[0]) || !classes.includes(pair[1])) {
      fail('MCC input is invalid');
    }
    matrix[classes.indexOf(pair[0])][classes.indexOf(pair[1])] += 1;
  }
  const total = pairs.length;
  const correct = matrix.reduce((sum, row, index) => sum + row[index], 0);
  const truthTotals = matrix.map((row) => row.reduce((a, b) => a + b, 0));
  const predictionTotals = classes.map((_, column) =>
    matrix.reduce((sum, row) => sum + row[column], 0));
  const covariance = correct * total - predictionTotals.reduce(
    (sum, value, index) => sum + value * truthTotals[index], 0);
  const predictionVariance = total * total - predictionTotals.reduce(
    (sum, value) => sum + value * value, 0);
  const truthVariance = total * total - truthTotals.reduce(
    (sum, value) => sum + value * value, 0);
  const denominator = Math.sqrt(predictionVariance * truthVariance);
  return denominator === 0 ? 0 : covariance / denominator;
}

function emptyCounts() {
  return {
    clean: { clean: 0, defect: 0, abstain: 0, total: 0 },
    defect: { clean: 0, defect: 0, abstain: 0, total: 0 },
    ambiguous: { clean: 0, defect: 0, abstain: 0, total: 0 },
  };
}

function computeRepeatMetrics(qualificationCases, decisions) {
  const byClass = {};
  const allPairs = [];
  for (const assertionClass of ASSERTION_CLASSES) {
    const counts = emptyCounts();
    const pairs = [];
    for (let index = 0; index < qualificationCases.length; index += 1) {
      const item = qualificationCases[index];
      if (item.assertionClass !== assertionClass) continue;
      const predicted = decisions[index].decision;
      counts[item.label][predicted] += 1;
      counts[item.label].total += 1;
      const expected = item.label === 'ambiguous' ? 'abstain' : item.label;
      pairs.push([expected, predicted]);
      allPairs.push([expected, predicted]);
    }
    const clean = counts.clean;
    const defect = counts.defect;
    const ambiguous = counts.ambiguous;
    const cleanPassRate = clean.clean / clean.total;
    const defectRecall = defect.defect / defect.total;
    const ambiguousAbstainRate = ambiguous.abstain / ambiguous.total;
    byClass[assertionClass] = {
      counts,
      cleanPassRate,
      cleanPassWilsonLower: wilsonLowerBound(clean.clean, clean.total),
      defectRecall,
      defectRecallWilsonLower: wilsonLowerBound(defect.defect, defect.total),
      falsePassRate: defect.clean / defect.total,
      ambiguousAbstainRate,
      ambiguousAbstainWilsonLower: wilsonLowerBound(
        ambiguous.abstain, ambiguous.total),
      balancedAccuracy: (cleanPassRate + defectRecall) / 2,
      mcc: multiclassMcc(pairs),
    };
  }
  const macroBalancedAccuracy = ASSERTION_CLASSES.reduce((sum, key) =>
    sum + byClass[key].balancedAccuracy, 0) / ASSERTION_CLASSES.length;
  return {
    byAssertionClass: byClass,
    macroBalancedAccuracy,
    mcc: multiclassMcc(allPairs),
  };
}

function metricFailures(backend, repeat, metrics) {
  const failures = [];
  for (const assertionClass of ASSERTION_CLASSES) {
    const item = metrics.byAssertionClass[assertionClass];
    const prefix = `${backend}/repeat-${repeat}/${assertionClass}`;
    if (item.defectRecall < THRESHOLDS.defectRecall) {
      failures.push(`${prefix}: defect recall below threshold`);
    }
    if (item.defectRecallWilsonLower < THRESHOLDS.defectRecallWilsonLower) {
      failures.push(`${prefix}: defect-recall Wilson lower bound below threshold`);
    }
    if (item.cleanPassRate < THRESHOLDS.cleanPassRate) {
      failures.push(`${prefix}: clean pass rate below threshold`);
    }
    if (item.cleanPassWilsonLower < THRESHOLDS.cleanPassWilsonLower) {
      failures.push(`${prefix}: clean-pass Wilson lower bound below threshold`);
    }
    if (item.falsePassRate > THRESHOLDS.falsePassRateMax) {
      failures.push(`${prefix}: false-pass rate above threshold`);
    }
    if (item.ambiguousAbstainRate < THRESHOLDS.ambiguousAbstainRate) {
      failures.push(`${prefix}: ambiguous abstention below threshold`);
    }
    if (item.ambiguousAbstainWilsonLower <
        THRESHOLDS.ambiguousAbstainWilsonLower) {
      failures.push(`${prefix}: ambiguous-abstention Wilson lower bound below threshold`);
    }
  }
  if (metrics.macroBalancedAccuracy < THRESHOLDS.macroBalancedAccuracy) {
    failures.push(`${backend}/repeat-${repeat}: macro balanced accuracy below threshold`);
  }
  if (metrics.mcc < THRESHOLDS.mcc) {
    failures.push(`${backend}/repeat-${repeat}: MCC below threshold`);
  }
  return failures;
}

function repeatAgreement(qualificationCases, repeats) {
  const byAssertionClass = {};
  for (const assertionClass of ASSERTION_CLASSES) {
    let agreed = 0;
    let total = 0;
    for (let index = 0; index < qualificationCases.length; index += 1) {
      if (qualificationCases[index].assertionClass !== assertionClass) continue;
      total += 1;
      const values = repeats.map((repeat) => repeat.decisions[index].decision);
      if (values.every((value) => value === values[0])) agreed += 1;
    }
    byAssertionClass[assertionClass] = { agreed, total, rate: agreed / total };
  }
  return byAssertionClass;
}

function backendAgreement(qualificationCases, webgpu, wasm) {
  const byAssertionClass = {};
  for (const assertionClass of ASSERTION_CLASSES) {
    let agreed = 0;
    let total = 0;
    for (let repeatIndex = 0;
      repeatIndex < REQUIRED_POLICY.repetitionsPerBackend; repeatIndex += 1) {
      for (let index = 0; index < qualificationCases.length; index += 1) {
        if (qualificationCases[index].assertionClass !== assertionClass) continue;
        total += 1;
        if (webgpu.repeats[repeatIndex].decisions[index].decision ===
            wasm.repeats[repeatIndex].decisions[index].decision) agreed += 1;
      }
    }
    byAssertionClass[assertionClass] = { agreed, total, rate: agreed / total };
  }
  return byAssertionClass;
}

function evaluateQualificationRun({ manifest, corpusBinding, runReceipt } = {}) {
  validateQualificationRunReceipt(manifest, corpusBinding, runReceipt);
  const qualificationCases = manifest.cases.filter((item) =>
    item.split === REQUIRED_POLICY.qualificationSplit);
  const failures = [];
  const backendResults = [];
  for (const backend of runReceipt.backends) {
    const repetitions = backend.repeats.map((repeat) => {
      const metrics = computeRepeatMetrics(qualificationCases, repeat.decisions);
      const repeatFailures = metricFailures(backend.backend, repeat.repeat, metrics);
      failures.push(...repeatFailures);
      return {
        repeat: repeat.repeat,
        metrics,
        qualified: repeatFailures.length === 0,
      };
    });
    const agreement = repeatAgreement(qualificationCases, backend.repeats);
    for (const assertionClass of ASSERTION_CLASSES) {
      if (agreement[assertionClass].rate < THRESHOLDS.repeatAgreement) {
        failures.push(`${backend.backend}/${assertionClass}: repeat agreement below threshold`);
      }
    }
    backendResults.push({
      backend: backend.backend,
      repetitions,
      repeatAgreement: agreement,
    });
  }
  const crossBackendAgreement = backendAgreement(qualificationCases,
    runReceipt.backends[0], runReceipt.backends[1]);
  for (const assertionClass of ASSERTION_CLASSES) {
    if (crossBackendAgreement[assertionClass].rate <
        THRESHOLDS.backendAgreement) {
      failures.push(`${assertionClass}: WebGPU/WASM agreement below threshold`);
    }
  }
  const qualified = failures.length === 0;
  return sealUnsigned({
    schemaVersion: RESULT_SCHEMA_VERSION,
    manifestSha256: manifest.seal.sha256,
    corpusBindingSha256: corpusBinding.seal.sha256,
    runReceiptSha256: runReceipt.seal.sha256,
    capability: CAPABILITY,
    thresholds: cloneCanonical(THRESHOLDS),
    backendResults,
    crossBackendAgreement,
    qualified,
    advertisedCapabilities: qualified ? [CAPABILITY] : [],
    failures,
  });
}

function validateQualificationResult({
  manifest, corpusBinding, runReceipt, result,
} = {}) {
  const expected = evaluateQualificationRun({
    manifest, corpusBinding, runReceipt,
  });
  validateSeal(result, [
    'schemaVersion', 'manifestSha256', 'corpusBindingSha256',
    'runReceiptSha256', 'capability', 'thresholds', 'backendResults',
    'crossBackendAgreement', 'qualified', 'advertisedCapabilities', 'failures',
  ], 'semantic visual qualification result');
  if (canonicalJson(result) !== canonicalJson(expected)) {
    fail('semantic visual qualification result does not match recomputed metrics');
  }
  return result;
}

module.exports = {
  ADVERTISED_CAPABILITY: CAPABILITY,
  ASSERTION_CLASSES,
  BACKENDS,
  CORPUS_BINDING_SCHEMA_VERSION,
  DECISIONS,
  LABELS,
  MANIFEST_SCHEMA_VERSION,
  PROMPT_INJECTION_TAGS,
  REQUIRED_POLICY,
  RESULT_SCHEMA_VERSION,
  RUN_SCHEMA_VERSION,
  SPLITS,
  SUBJECTIVE_ASSERTION_CLASSES,
  THRESHOLDS,
  SemanticVisualQualificationError,
  canonicalJson,
  computeCaseId,
  computeDecisionSetSha256,
  evaluateQualificationRun,
  multiclassMcc,
  sealCorpusBinding,
  sealQualificationManifest,
  sealQualificationRunReceipt,
  sha256Canonical,
  validateCorpusBinding,
  validateQualificationManifest,
  validateQualificationResult,
  validateQualificationRunReceipt,
  verifyQualificationCorpusFiles,
  wilsonLowerBound,
};
