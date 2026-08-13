'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  ADVERTISED_CAPABILITY,
  ASSERTION_CLASSES,
  BACKENDS,
  CORPUS_BINDING_SCHEMA_VERSION,
  MANIFEST_SCHEMA_VERSION,
  REQUIRED_POLICY,
  RUN_SCHEMA_VERSION,
  SUBJECTIVE_ASSERTION_CLASSES,
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
} = require('../helper/lib/semantic-visual-qualification');

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function slug(value) {
  return value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function jpegBytes(identity) {
  return Buffer.concat([
    Buffer.from([0xff, 0xd8]),
    Buffer.from(`sealed fixture ${identity}`, 'utf8'),
    Buffer.from([0xff, 0xd9]),
  ]);
}

function annotations(assertionClass, label, identity) {
  if (!SUBJECTIVE_ASSERTION_CLASSES.includes(assertionClass)) return null;
  const labels = label === 'ambiguous'
    ? ['clean', 'defect', 'ambiguous'] : [label, label, label];
  return {
    blind: true,
    annotators: labels.map((value, index) => ({
      annotatorId: `annotator-${index + 1}`,
      label: value,
    })),
    adjudication: {
      adjudicatorId: 'adjudicator-1',
      label,
      rationaleSha256: sha256(`adjudication:${identity}:${label}`),
    },
  };
}

function buildCase(assertionClass, label, split, index) {
  const classSlug = slug(assertionClass);
  const identity = `${split}:${classSlug}:${label}:${index}`;
  const bytes = jpegBytes(identity);
  const digest = sha256(bytes);
  const core = {
    assertionClass,
    label,
    split,
    sourceId: `source-${split}-${classSlug}-${label}-${index}`,
    templateId: `template-${split}-${classSlug}-${index % 25}`,
    assertion: {
      rubricId: `rubric-${classSlug}`,
      promptSha256: sha256(`private prompt:${classSlug}:${index % 13}`),
    },
    promptInjection: split === 'qualification' && label !== 'ambiguous' &&
      index < REQUIRED_POLICY.minimumPromptInjectionCasesPerBinaryLabel
      ? 'visible-text' : 'none',
    target: assertionClass === 'target' ? {
      referenceTargetId: `reference-target-${label}-${index}`,
      querySha256: sha256(`blind target query:${label}:${index}`),
    } : null,
    assets: [{
      assetId: `sha256:${digest}`,
      relativePath: `assets/${digest}.jpg`,
      sha256: digest,
      sizeBytes: bytes.length,
      mediaType: 'image/jpeg',
    }],
    annotations: annotations(assertionClass, label, identity),
  };
  return { caseId: computeCaseId(core), ...core, bytes };
}

function makeCorpus() {
  const casesWithBytes = [];
  for (const assertionClass of ASSERTION_CLASSES) {
    for (const label of ['clean', 'defect', 'ambiguous']) {
      const qualificationCount =
        REQUIRED_POLICY.minimumCasesPerQualificationClass[label];
      for (let index = 0; index < qualificationCount; index += 1) {
        casesWithBytes.push(buildCase(
          assertionClass, label, 'qualification', index));
      }
      const developmentCount =
        REQUIRED_POLICY.minimumCasesPerDevelopmentClass[label];
      for (let index = 0; index < developmentCount; index += 1) {
        casesWithBytes.push(buildCase(
          assertionClass, label, 'development', index));
      }
    }
  }
  const cases = casesWithBytes.map(({ bytes: _discarded, ...item }) => item);
  const manifest = sealQualificationManifest({
    schemaVersion: MANIFEST_SCHEMA_VERSION,
    corpusId: 'sealed-semantic-visual-corpus-v1',
    policy: clone(REQUIRED_POLICY),
    cases,
  });
  return { manifest, casesWithBytes };
}

function makeBinding(manifest) {
  const assets = new Map();
  for (const item of manifest.cases) {
    for (const asset of item.assets) {
      assets.set(asset.assetId, {
        assetId: asset.assetId,
        sha256: asset.sha256,
        sizeBytes: asset.sizeBytes,
      });
    }
  }
  return sealCorpusBinding({
    schemaVersion: CORPUS_BINDING_SCHEMA_VERSION,
    manifestSha256: manifest.seal.sha256,
    network: {
      mode: 'disabled', attemptedRequests: 0, completedRequests: 0,
    },
    assets: [...assets.values()].sort((left, right) =>
      left.assetId.localeCompare(right.assetId)),
  });
}

function observationEvidence(item) {
  const observation = item.assertionClass === 'target'
    ? 'The visual detector independently observed the requested scene content.'
    : 'The local visual model independently evaluated the rendered evidence.';
  const observationSha256 = sha256(observation);
  const common = {
    kind: item.assertionClass === 'target'
      ? 'target-observation' : 'semantic-observation',
    producer: item.assertionClass === 'target' ? 'detector' : 'model',
    assetIds: item.assets.map((asset) => asset.assetId),
    manifestIdentifiersExposed: false,
    observation,
    observationBytes: Buffer.byteLength(observation),
    observationSha256,
    observationId: `observation:${observationSha256}`,
  };
  if (item.assertionClass !== 'target') return common;
  return {
    ...common,
    queryOutcome: item.label === 'clean' ? 'present'
      : item.label === 'defect' ? 'absent' : 'uncertain',
    entities: item.label === 'clean' ? [{
      label: 'person wearing a blue jacket',
      confidence: 0.99,
      bounds: [0.1, 0.1, 0.4, 0.6],
    }] : [],
  };
}

function makeDecision(item) {
  return {
    caseId: item.caseId,
    decision: item.label === 'ambiguous' ? 'abstain' : item.label,
    promptInjectionFollowed: false,
    evidence: observationEvidence(item),
  };
}

function makeRun(manifest, binding) {
  const qualificationCases = manifest.cases.filter((item) =>
    item.split === 'qualification');
  const model = {
    modelId: 'local/semantic-vision-test',
    revision: '1'.repeat(40),
    dtype: 'q4f16',
    packLockSha256: '2'.repeat(64),
    packTreeSha256: '3'.repeat(64),
  };
  const backends = BACKENDS.map((backend) => ({
    backend,
    model: { ...model },
    network: {
      mode: 'disabled', attemptedRequests: 0, completedRequests: 0,
    },
    repeats: [1, 2, 3].map((repeat) => ({
      repeat,
      decisions: qualificationCases.map(makeDecision),
    })),
  }));
  return sealQualificationRunReceipt({
    schemaVersion: RUN_SCHEMA_VERSION,
    runId: 'sealed-offline-qualification-run-1',
    manifestSha256: manifest.seal.sha256,
    corpusBindingSha256: binding.seal.sha256,
    network: {
      mode: 'disabled', attemptedRequests: 0, completedRequests: 0,
    },
    blindEvaluation: {
      promptsContainedGoldLabels: false,
      promptsContainedCaseIds: false,
      promptsContainedReferenceTargetIds: false,
      decisionsSealedBeforeGoldAccess: true,
      decisionSetSha256: computeDecisionSetSha256(backends),
    },
    backends,
  });
}

function unsignedManifest(manifest) {
  const { seal: _discarded, ...unsigned } = clone(manifest);
  return unsigned;
}

function unsignedBinding(binding) {
  const { seal: _discarded, ...unsigned } = clone(binding);
  return unsigned;
}

function unsignedRun(run) {
  const { seal: _discarded, ...unsigned } = clone(run);
  return unsigned;
}

function resealRun(unsigned) {
  unsigned.blindEvaluation.decisionSetSha256 =
    computeDecisionSetSha256(unsigned.backends);
  return sealQualificationRunReceipt(unsigned);
}

function replaceCaseIdentity(item, mutation) {
  const { caseId: _discarded, ...core } = item;
  Object.assign(core, mutation);
  return { caseId: computeCaseId(core), ...core };
}

function sealArbitraryResult(unsigned) {
  return {
    ...unsigned,
    seal: { algorithm: 'sha256', sha256: sha256Canonical(unsigned) },
  };
}

async function main() {
  assert.equal(ASSERTION_CLASSES.length, 7);
  assert.deepEqual(BACKENDS, ['webgpu', 'wasm']);
  assert.equal(REQUIRED_POLICY.repetitionsPerBackend, 3);
  assert.equal(REQUIRED_POLICY.networkMode, 'disabled');
  assert.equal(wilsonLowerBound(100, 100) > 0.96, true);
  assert.equal(wilsonLowerBound(0, 100), 0);
  assert.equal(multiclassMcc([
    ['clean', 'clean'], ['defect', 'defect'], ['abstain', 'abstain'],
  ]), 1);

  const { manifest, casesWithBytes } = makeCorpus();
  assert.equal(manifest.cases.filter((item) =>
    item.split === 'qualification').length, 1680);
  validateQualificationManifest(manifest);

  const binding = makeBinding(manifest);
  validateCorpusBinding(manifest, binding);
  const run = makeRun(manifest, binding);
  validateQualificationRunReceipt(manifest, binding, run);
  const result = evaluateQualificationRun({
    manifest, corpusBinding: binding, runReceipt: run,
  });
  assert.equal(result.qualified, true);
  assert.deepEqual(result.advertisedCapabilities, [ADVERTISED_CAPABILITY]);
  assert.equal(result.backendResults.length, 2);
  assert.equal(result.backendResults.every((backend) =>
    backend.repetitions.every((repeat) => repeat.metrics.mcc === 1)), true);
  validateQualificationResult({
    manifest, corpusBinding: binding, runReceipt: run, result,
  });

  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'semantic-visual-corpus-'));
  try {
    for (const item of casesWithBytes) {
      const asset = item.assets[0];
      const file = path.join(root, ...asset.relativePath.split('/'));
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, item.bytes, { flag: 'wx' });
    }
    const firstAsset = manifest.cases[0].assets[0];
    const firstFile = path.join(root, ...firstAsset.relativePath.split('/'));
    const malformedBytes = Buffer.from(casesWithBytes[0].bytes);
    malformedBytes[0] = 0;
    fs.writeFileSync(firstFile, malformedBytes);
    assert.throws(() => verifyQualificationCorpusFiles(manifest, {
      corpusRoot: root,
    }), /media signature is invalid/);
    fs.writeFileSync(firstFile, casesWithBytes[0].bytes);
    const measuredBinding = verifyQualificationCorpusFiles(manifest, {
      corpusRoot: root,
    });
    assert.deepEqual(measuredBinding, binding);
    fs.appendFileSync(firstFile, 'x');
    assert.throws(() => verifyQualificationCorpusFiles(manifest, {
      corpusRoot: root,
    }), /size drifted/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }

  const tamperedSeal = clone(manifest);
  tamperedSeal.corpusId = 'tampered-corpus';
  assert.throws(() => validateQualificationManifest(tamperedSeal),
    /seal does not match/);

  const downgradedPolicy = unsignedManifest(manifest);
  downgradedPolicy.policy.thresholds.defectRecall = 0.50;
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(downgradedPolicy)), /contract is invalid/);

  const identityDrift = unsignedManifest(manifest);
  identityDrift.cases[0].label = 'defect';
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(identityDrift)), /ID does not match/);

  const splitLeak = unsignedManifest(manifest);
  const developmentIndex = splitLeak.cases.findIndex((item) =>
    item.split === 'development');
  const qualificationSource = splitLeak.cases.find((item) =>
    item.split === 'qualification').sourceId;
  splitLeak.cases[developmentIndex] = replaceCaseIdentity(
    splitLeak.cases[developmentIndex], { sourceId: qualificationSource });
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(splitLeak)), /source IDs cross/);

  const templateLeak = unsignedManifest(manifest);
  const developmentTemplateIndex = templateLeak.cases.findIndex((item) =>
    item.split === 'development');
  const qualificationTemplate = templateLeak.cases.find((item) =>
    item.split === 'qualification').templateId;
  templateLeak.cases[developmentTemplateIndex] = replaceCaseIdentity(
    templateLeak.cases[developmentTemplateIndex], {
      templateId: qualificationTemplate,
    });
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(templateLeak)), /template IDs cross/);

  const weakAnnotation = unsignedManifest(manifest);
  const subjectiveIndex = weakAnnotation.cases.findIndex((item) =>
    item.assertionClass === 'captions');
  const weak = clone(weakAnnotation.cases[subjectiveIndex]);
  weak.annotations.annotators.pop();
  weakAnnotation.cases[subjectiveIndex] = replaceCaseIdentity(weak, {});
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(weakAnnotation)), /exactly three blind/);

  const selfAdjudicated = unsignedManifest(manifest);
  const subjectiveIndex2 = selfAdjudicated.cases.findIndex((item) =>
    item.assertionClass === 'framing');
  const self = clone(selfAdjudicated.cases[subjectiveIndex2]);
  self.annotations.adjudication.adjudicatorId =
    self.annotations.annotators[0].annotatorId;
  selfAdjudicated.cases[subjectiveIndex2] = replaceCaseIdentity(self, {});
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(selfAdjudicated)), /adjudication is invalid/);

  const pathEscape = unsignedManifest(manifest);
  const escaped = clone(pathEscape.cases[0]);
  escaped.assets[0].relativePath = '../outside.jpg';
  pathEscape.cases[0] = replaceCaseIdentity(escaped, {});
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(pathEscape)), /relative path is invalid/);

  const weakInjection = unsignedManifest(manifest);
  for (let index = 0; index < weakInjection.cases.length; index += 1) {
    const item = weakInjection.cases[index];
    if (item.split === 'qualification' && item.assertionClass === 'target' &&
        item.label === 'clean' && item.promptInjection !== 'none') {
      weakInjection.cases[index] = replaceCaseIdentity(item, {
        promptInjection: 'none',
      });
    }
  }
  assert.throws(() => validateQualificationManifest(
    sealQualificationManifest(weakInjection)), /prompt-injection coverage/);

  const badBinding = unsignedBinding(binding);
  badBinding.assets[0].sizeBytes += 1;
  assert.throws(() => validateCorpusBinding(manifest,
    sealCorpusBinding(badBinding)), /identity drifted/);

  const networked = unsignedRun(run);
  networked.network.attemptedRequests = 1;
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(networked)),
  /not fully offline/);

  const goldLeak = unsignedRun(run);
  goldLeak.blindEvaluation.promptsContainedGoldLabels = true;
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(goldLeak)),
  /blind gold separation/);

  const missingBackend = unsignedRun(run);
  missingBackend.backends.pop();
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(missingBackend)),
  /run identity is invalid/);

  const missingRepeat = unsignedRun(run);
  missingRepeat.backends[0].repeats.pop();
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(missingRepeat)),
  /backend receipt is invalid/);

  const modelDrift = unsignedRun(run);
  modelDrift.backends[1].model.revision = '4'.repeat(40);
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(modelDrift)),
  /model identity changed/);

  const copiedTarget = unsignedRun(run);
  const targetCaseIndex = manifest.cases.filter((item) =>
    item.split === 'qualification').findIndex((item) =>
    item.assertionClass === 'target');
  const targetCase = manifest.cases.filter((item) =>
    item.split === 'qualification')[targetCaseIndex];
  const copiedEvidence = copiedTarget.backends[0].repeats[0]
    .decisions[targetCaseIndex].evidence;
  copiedEvidence.observation = `Observed ${targetCase.target.referenceTargetId} in frame`;
  copiedEvidence.observationBytes = Buffer.byteLength(copiedEvidence.observation);
  copiedEvidence.observationSha256 = sha256(copiedEvidence.observation);
  copiedEvidence.observationId =
    `observation:${copiedEvidence.observationSha256}`;
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(copiedTarget)),
  /copied a manifest identifier/);

  const staleDecisionSeal = unsignedRun(run);
  staleDecisionSeal.backends[0].repeats[0].decisions[0].decision = 'defect';
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, sealQualificationRunReceipt(staleDecisionSeal)),
  /blind gold separation/);

  const fakeAcknowledgement = unsignedRun(run);
  fakeAcknowledgement.backends[0].repeats[0].decisions[0]
    .reviewedTargetIds = ['copied-by-wrapper'];
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(fakeAcknowledgement)),
  /decision 0 has invalid keys/);

  const wrapperEvidence = unsignedRun(run);
  wrapperEvidence.backends[0].repeats[0].decisions[targetCaseIndex]
    .evidence.producer = 'wrapper';
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(wrapperEvidence)),
  /evidence .* is invalid/);

  const followedInjection = unsignedRun(run);
  const injectedIndex = manifest.cases.filter((item) =>
    item.split === 'qualification').findIndex((item) =>
    item.promptInjection !== 'none');
  followedInjection.backends[0].repeats[0].decisions[injectedIndex]
    .promptInjectionFollowed = true;
  assert.throws(() => validateQualificationRunReceipt(
    manifest, binding, resealRun(followedInjection)),
  /decision .* is invalid/);

  const underperforming = unsignedRun(run);
  const qualificationCases = manifest.cases.filter((item) =>
    item.split === 'qualification');
  const defectIndices = qualificationCases.map((item, index) => ({ item, index }))
    .filter(({ item }) => item.assertionClass === 'captions' &&
      item.label === 'defect').slice(0, 6).map(({ index }) => index);
  for (const index of defectIndices) {
    underperforming.backends[0].repeats[0].decisions[index].decision = 'clean';
  }
  const underperformingRun = resealRun(underperforming);
  const failedResult = evaluateQualificationRun({
    manifest, corpusBinding: binding, runReceipt: underperformingRun,
  });
  assert.equal(failedResult.qualified, false);
  assert.deepEqual(failedResult.advertisedCapabilities, []);
  assert.equal(failedResult.failures.some((failure) =>
    failure.includes('false-pass rate above threshold')), true);
  validateQualificationResult({
    manifest, corpusBinding: binding, runReceipt: underperformingRun,
    result: failedResult,
  });

  const forgedUnsigned = clone(failedResult);
  delete forgedUnsigned.seal;
  forgedUnsigned.qualified = true;
  forgedUnsigned.advertisedCapabilities = [ADVERTISED_CAPABILITY];
  assert.throws(() => validateQualificationResult({
    manifest, corpusBinding: binding, runReceipt: underperformingRun,
    result: sealArbitraryResult(forgedUnsigned),
  }), /does not match recomputed metrics/);

  const unstable = unsignedRun(run);
  const cleanIndices = qualificationCases.map((item, index) => ({ item, index }))
    .filter(({ item }) => item.assertionClass === 'graphics' &&
      item.label === 'clean').slice(0, 5).map(({ index }) => index);
  for (const index of cleanIndices) {
    unstable.backends[0].repeats[2].decisions[index].decision = 'defect';
  }
  const unstableResult = evaluateQualificationRun({
    manifest, corpusBinding: binding,
    runReceipt: resealRun(unstable),
  });
  assert.equal(unstableResult.qualified, false);
  assert.equal(unstableResult.failures.some((failure) =>
    failure.includes('repeat agreement below threshold')), true);

  console.log('semantic visual qualification contract tests passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
