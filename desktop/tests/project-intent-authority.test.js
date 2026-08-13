'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { CAPABILITIES } = require('../helper/lib/edit-policy');
const {
  CAPABILITY_MANIFEST_SCHEMA_VERSION,
  CAPABILITY_MANIFEST_SOURCE,
  PROJECT_INTENT_SCHEMA_VERSION,
  resolveProjectIntentPolicy,
} = require('../helper/lib/project-intent-policy-bridge');
const {
  PROJECT_INTENT_AUTHORITY_SCHEMA_VERSION,
  attachProjectIntentAuthority,
  authorizeProjectIntentRequest,
  normalizeApplyRequest,
} = require('../helper/lib/local-render');
const { validateProposal } = require('../helper/lib/editing-harness');
const {
  TRANSITION_DECISION_SCHEMA_VERSION,
  buildTransitionCarrier,
} = require('../helper/lib/transition-proposal');

function intent() {
  return {
    schema_version: PROJECT_INTENT_SCHEMA_VERSION,
    profile: 'dialogue_talking_head',
    delivery: { platform: 'youtube', aspect: '16:9' },
    target_duration: { min_ms: 30000, max_ms: 45000 },
    preferences: {
      captions: { enabled: true, preference: 'auto' },
      graphics: { enabled: true, preference: 'auto' },
      music: { enabled: true, preference: 'auto' },
      sfx: { enabled: true, preference: 'auto' },
      transitions: { enabled: true, preference: 'auto' },
    },
  };
}

function manifest(capabilities = CAPABILITIES) {
  return {
    schema_version: CAPABILITY_MANIFEST_SCHEMA_VERSION,
    source: CAPABILITY_MANIFEST_SOURCE,
    probe_receipt_sha256: 'a'.repeat(64),
    available_capabilities: [...capabilities].sort(),
  };
}

function transitionIntent(preference = 'motivated_only') {
  return {
    schema_version: PROJECT_INTENT_SCHEMA_VERSION,
    profile: 'commercial_product',
    delivery: { platform: 'youtube', aspect: '16:9' },
    target_duration: { min_ms: 5000, max_ms: 5000 },
    preferences: {
      captions: { enabled: true, preference: 'auto' },
      graphics: { enabled: true, preference: 'auto' },
      music: { enabled: true, preference: 'auto' },
      sfx: { enabled: true, preference: 'auto' },
      transitions: { enabled: true, preference },
    },
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

async function run() {
  const proposed = validateProposal({
    summary: 'Use the explicitly selected expert policy.',
    operations: [{ op: 'set_edit_style', style: 'long' }],
    projectIntent: intent(),
  }, { allowProjectIntent: true });
  assert.deepEqual(proposed.projectIntent, intent());
  assert.equal(validateProposal({
    operations: [{ op: 'set_edit_style', style: 'long' }],
    projectIntent: { ...intent(), extra: true },
  }, { allowProjectIntent: true }), null,
  'ProjectIntent must validate before canApply can become true');
  assert.deepEqual(validateProposal({
    summary: 'Legacy proposal.',
    operations: [{ op: 'set_edit_style', style: 'long' }],
  }), {
    operations: [{
      op: 'set_edit_style', style: 'long', human: 'Use long edit pacing',
    }],
    summary: 'Legacy proposal.',
  }, 'an absent ProjectIntent must preserve the legacy proposal shape');

  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-authority-'));
  try {
    const input = path.join(temp, 'input.mp4');
    const outputDir = path.join(temp, 'output');
    fs.writeFileSync(input, 'video');
    fs.mkdirSync(outputDir);
    const normalized = normalizeApplyRequest({
      videos: [input], outputDir, projectType: 'long', script: '',
      proposal: proposed,
    });
    assert.notEqual(normalized.proposal.projectIntent, proposed.projectIntent);

    const trustedManifest = manifest();
    const policy = resolveProjectIntentPolicy(intent(), trustedManifest);
    let resolveCalls = 0;
    let manifestCalls = 0;
    const authorized = await authorizeProjectIntentRequest(normalized, {
      resolveProjectIntentPolicy: async (project) => {
        resolveCalls += 1;
        assert.deepEqual(project, intent());
        return policy;
      },
      requireTrustedManifest: async () => {
        manifestCalls += 1;
        return trustedManifest;
      },
    }, {
      authorizationId: '1'.repeat(32),
      signingKey: '2'.repeat(64),
    });
    assert.equal(resolveCalls, 1);
    assert.equal(manifestCalls, 1);
    assert.equal(authorized.request.projectIntentAuthority.schema_version,
      PROJECT_INTENT_AUTHORITY_SCHEMA_VERSION);
    assert.deepEqual({
      proposal:
        authorized.request.projectIntentAuthority.approved_proposal_sha256,
      project: authorized.request.projectIntentAuthority.project_intent_sha256,
      manifest:
        authorized.request.projectIntentAuthority.capability_manifest_sha256,
      policy: authorized.request.projectIntentAuthority.edit_policy_sha256,
      hmac:
        authorized.request.projectIntentAuthority.authorization_hmac_sha256,
    }, {
      proposal: '512fde48a8e0ee0414c4744bc6f0a0679603e860b6412ed78bf17fd8252ea88e',
      project: '99c128648be416902001bebfd42c04510176bed773f168f4a49d062bb6377878',
      manifest: '5611d54d339631516875844a7fad0233593d6badd87a2d4818eb060f9955a62c',
      policy: '1e97411c7109bbf98cdd4a15d133a9569321a846958f537a705bd39a7a769ff8',
      hmac: 'f37bb74552080231af17fc2d80782697ce632d4bcdcc85586bfc4e69e5ea05a4',
    }, 'the JavaScript authority wire vector must stay Python-canonical');
    assert.equal(authorized.signingKey, '2'.repeat(64));
    assert.ok(!JSON.stringify(authorized.request).includes(authorized.signingKey),
      'the daemon-only signing key must not enter renderer-controlled JSON');
    assert.ok(Object.isFrozen(authorized.request.projectIntentAuthority));
    assert.ok(Object.isFrozen(
      authorized.request.projectIntentAuthority.capability_manifest));

    const unicodeProposal = validateProposal({
      summary: 'Use caf\u00e9 pacing \u{1f600}.',
      operations: [{ op: 'set_edit_style', style: 'long' }],
      projectIntent: intent(),
    }, { allowProjectIntent: true });
    const unicodeNormalized = normalizeApplyRequest({
      videos: [input], outputDir, projectType: 'long', script: '',
      proposal: unicodeProposal,
    });
    const unicodeAuthorized = await authorizeProjectIntentRequest(
      unicodeNormalized, {
        resolveProjectIntentPolicy: async () => policy,
        requireTrustedManifest: async () => trustedManifest,
      }, {
        authorizationId: '7'.repeat(32),
        signingKey: '8'.repeat(64),
      },
    );
    assert.equal(
      unicodeAuthorized.request.projectIntentAuthority.approved_proposal_sha256,
      '94d710251c57c7899af8c29f8da950f33e3402ee4e6b7ae2273d28f3c832f6e5',
      'proposal authority must use Python-canonical Unicode escaping',
    );

    const secondInput = path.join(temp, 'second.mp4');
    fs.writeFileSync(secondInput, 'second-video');
    const transitionSources = [{
      source_id: 'source-a', sha256: 'c'.repeat(64), duration_ms: 3000,
    }, {
      source_id: 'source-b', sha256: 'd'.repeat(64), duration_ms: 3000,
    }];
    const transitionSourceManifest = {
      schema_version: 'autoeditor-source-manifest/v1',
      sources: transitionSources,
    };
    const transitionSequencePlan = {
      schema_version: 'autoeditor-sequence-plan/v1',
      sources: transitionSources,
      target_duration: { min_ms: 5000, max_ms: 5000 },
      segments: transitionSources.map((source, index) => ({
        segment_id: `segment-${index}`,
        source_id: source.source_id,
        source_sha256: source.sha256,
        source_start_ms: 0,
        source_end_ms: 2500,
        role: index === 0 ? 'hook' : 'closer',
        reason: 'Exact project-intent transition authority fixture.',
        speech_anchor: null,
        transition: { kind: 'hard_cut' },
      })),
    };
    const transitionCarrier = buildTransitionCarrier({
      sequencePlan: transitionSequencePlan,
      sourceManifest: transitionSourceManifest,
      privateCatalog: {
        schema_version: 'autoeditor-source-catalog/v1',
        sources: transitionSources.map((source) => ({
          ...source,
          timeline: { video_start_offset_ms: 0, audio_start_offset_ms: 0 },
        })),
      },
      projectIntent: transitionIntent(),
      decisions: {
        schema_version: TRANSITION_DECISION_SCHEMA_VERSION,
        boundaries: [{
          boundary_index: 0, kind: 'cross_dissolve', duration_ms: 200,
          motivation_verified: true, semantic_safety_verified: true,
          dialogue_preservation_verified: true,
        }],
      },
    });
    const transitionNormalized = normalizeApplyRequest({
      videos: [input, secondInput], outputDir, projectType: 'commercial', script: '',
      proposal: {
        operations: [{ op: 'set_edit_style', style: 'short' }],
        projectIntent: transitionIntent(),
        sequencePlan: transitionSequencePlan,
        sequenceSourceManifest: transitionSourceManifest,
        ...transitionCarrier,
      },
    });
    const transitionPolicy = resolveProjectIntentPolicy(
      transitionIntent(), trustedManifest,
    );
    const transitionAuthorized = await authorizeProjectIntentRequest(
      transitionNormalized, {
        resolveProjectIntentPolicy: async () => transitionPolicy,
        requireTrustedManifest: async () => trustedManifest,
      }, {
        authorizationId: '3'.repeat(32),
        signingKey: '4'.repeat(64),
      },
    );
    assert.deepEqual(
      transitionAuthorized.request.proposal.transitionPlan,
      transitionCarrier.transitionPlan,
      'the exact approved transition carrier must survive runtime authorization',
    );
    let transitionMismatchManifestCalled = false;
    const hardCutPolicy = resolveProjectIntentPolicy(
      transitionIntent('hard_cut_only'), trustedManifest,
    );
    await assert.rejects(authorizeProjectIntentRequest(
      transitionNormalized, {
        resolveProjectIntentPolicy: async () => hardCutPolicy,
        requireTrustedManifest: async () => {
          transitionMismatchManifestCalled = true;
          return trustedManifest;
        },
      }, {
        authorizationId: '5'.repeat(32),
        signingKey: '6'.repeat(64),
      },
    ), /does not bind the resolved edit policy/);
    assert.equal(transitionMismatchManifestCalled, false,
      'a policy-mismatched transition must fail before authority attachment');

    const digestTamper = clone(authorized.request.projectIntentAuthority);
    digestTamper.edit_policy_sha256 = '0'.repeat(64);
    assert.throws(() => attachProjectIntentAuthority(
      normalized, digestTamper, authorized.signingKey), /digest does not match/);
    const signatureTamper = clone(authorized.request.projectIntentAuthority);
    signatureTamper.authorization_hmac_sha256 = '0'.repeat(64);
    assert.throws(() => attachProjectIntentAuthority(
      normalized, signatureTamper, authorized.signingKey), /signature does not match/);
    const swappedProposal = clone(normalized);
    swappedProposal.proposal.summary = 'Swapped after authorization.';
    assert.throws(() => attachProjectIntentAuthority(
      swappedProposal, authorized.request.projectIntentAuthority,
      authorized.signingKey), /digest does not match/);
    assert.throws(() => normalizeApplyRequest({
      videos: [input], outputDir, projectType: 'long', script: '',
      proposal: proposed,
      projectIntentAuthority: authorized.request.projectIntentAuthority,
    }), /must be generated by the trusted desktop/,
    'renderer IPC must not inject a main-owned authority envelope');

    const legacy = normalizeApplyRequest({
      videos: [input], outputDir, projectType: 'long', script: '',
      proposal: { operations: [{ op: 'set_edit_style', style: 'long' }] },
    });
    const legacyResult = await authorizeProjectIntentRequest(legacy, {
      resolveProjectIntentPolicy: async () => { throw new Error('called'); },
      requireTrustedManifest: async () => { throw new Error('called'); },
    });
    assert.equal(legacyResult.request, legacy);
    assert.equal(legacyResult.signingKey, '');

    let missingManifestCalled = false;
    await assert.rejects(authorizeProjectIntentRequest(normalized, {
      resolveProjectIntentPolicy: async () => {
        throw new Error('required capability caption_rendering is unavailable');
      },
      requireTrustedManifest: async () => {
        missingManifestCalled = true;
        return trustedManifest;
      },
    }), /caption_rendering is unavailable/);
    assert.equal(missingManifestCalled, false);

    let current = true;
    let finishResolve;
    const deferredPolicy = new Promise((resolve) => { finishResolve = resolve; });
    let canceledManifestCalled = false;
    const canceled = authorizeProjectIntentRequest(normalized, {
      resolveProjectIntentPolicy: () => deferredPolicy,
      requireTrustedManifest: async () => {
        canceledManifestCalled = true;
        return trustedManifest;
      },
    }, { isCurrent: () => current });
    current = false;
    finishResolve(policy);
    await assert.rejects(canceled, /authorization was canceled/);
    assert.equal(canceledManifestCalled, false);

    await assert.rejects(authorizeProjectIntentRequest(normalized, {
      resolveProjectIntentPolicy: async () => policy,
      requireTrustedManifest: async () => {
        throw new Error('runtime changed after its capability probe');
      },
    }), /runtime changed/);

    const main = fs.readFileSync(path.join(__dirname, '../helper/main.js'), 'utf8');
    const applyStart = main.indexOf('function applyLocal(');
    const applyEnd = main.indexOf('\nasync function cancelLocal', applyStart);
    const applyBody = main.slice(applyStart, applyEnd);
    const reservationIndex = applyBody.indexOf('reserveLocalRender(');
    const resolveIndex = applyBody.indexOf('await authorizeProjectIntentRequest(');
    const spawnIndex = applyBody.indexOf(
      "localProcess('--local-render', authorized.request", resolveIndex);
    assert.ok(reservationIndex >= 0 && resolveIndex > reservationIndex &&
      spawnIndex > resolveIndex,
    'render ownership must be reserved before lazy preflight and spawn after it');
    assert.ok(main.includes("'AUTOEDITOR_PROJECT_INTENT_AUTHORITY_KEY'"));
    assert.ok(main.includes('if (activeRender) throw new Error('),
      'a reserved authorization must hold the existing render lock');
    const processStart = main.indexOf('function localProcess(');
    const processEnd = main.indexOf('\nfunction renderLocal(', processStart);
    const processBody = main.slice(processStart, processEnd);
    assert.match(processBody,
      /if \(kind === 'render'\)[\s\S]*activeRender = action;[\s\S]*else \{\s*activeChat = action;/,
      'reserved and unreserved renders must remain in the render slot');
    assert.doesNotMatch(processBody,
      /if \(kind === 'render' && !reservedAction\) activeRender = action;\s*else activeChat = action;/,
      'a reserved ProjectIntent render must never overwrite chat ownership');
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

run().then(() => {
  console.log('project intent authority contracts passed');
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
