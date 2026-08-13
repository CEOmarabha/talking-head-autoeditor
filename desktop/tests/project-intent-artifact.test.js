'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  CAPABILITIES,
  editPolicySha256,
} = require('../helper/lib/edit-policy');
const {
  CAPABILITY_MANIFEST_SCHEMA_VERSION,
  CAPABILITY_MANIFEST_SOURCE,
  PROJECT_INTENT_SCHEMA_VERSION,
  resolveProjectIntentPolicy,
} = require('../helper/lib/project-intent-policy-bridge');
const {
  buildProjectIntentAuthority,
} = require('../helper/lib/local-render');
const {
  ArtifactContractError,
  readArtifactQaReport,
  readContractJsonSidecar,
  validateMusicProductionArtifactBinding,
  validateProjectIntentArtifactBinding,
  validateSfxProductionArtifactBinding,
} = require('../helper/lib/artifact-contract');

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function stableJson(value) {
  const pythonString = (text) => JSON.stringify(text).replace(
    /[^\x20-\x7e]/gu, (character) => {
      const codePoint = character.codePointAt(0);
      if (codePoint <= 0xffff) {
        return `\\u${codePoint.toString(16).padStart(4, '0')}`;
      }
      const adjusted = codePoint - 0x10000;
      return `\\u${(0xd800 + (adjusted >> 10)).toString(16)}` +
        `\\u${(0xdc00 + (adjusted & 0x3ff)).toString(16)}`;
    });
  if (typeof value === 'string') return pythonString(value);
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${pythonString(key)}:${stableJson(value[key])}`).join(',')}}`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

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

function manifest() {
  return {
    schema_version: CAPABILITY_MANIFEST_SCHEMA_VERSION,
    source: CAPABILITY_MANIFEST_SOURCE,
    probe_receipt_sha256: 'a'.repeat(64),
    available_capabilities: [...CAPABILITIES].sort(),
  };
}

function fixture({ unicode = false, musicPreference = 'auto' } = {}) {
  const project = intent();
  if (musicPreference === 'none') {
    project.preferences.music = { enabled: false, preference: 'none' };
  }
  const capabilities = manifest();
  const policy = resolveProjectIntentPolicy(project, capabilities);
  const approvedProposal = {
    projectIntent: project,
    ...(unicode ? {
      summary: 'Café launch 🎬',
      operations: [{ op: 'set_edit_style', style: 'long', note: '日本語' }],
    } : {}),
  };
  const authority = buildProjectIntentAuthority(project, policy, capabilities, {
    authorizationId: '1'.repeat(32), signingKey: '2'.repeat(64),
    approvedProposal,
  });
  const envelope = {
    schema_version: 'autoeditor-project-intent-engine-envelope/v2',
    authorization_id: authority.authorization_id,
    approved_proposal_sha256: authority.approved_proposal_sha256,
    approved_transition_carrier: null,
    project_intent: authority.project_intent,
    project_intent_sha256: authority.project_intent_sha256,
    edit_policy: authority.edit_policy,
    edit_policy_sha256: authority.edit_policy_sha256,
    capability_manifest: authority.capability_manifest,
    capability_manifest_sha256: authority.capability_manifest_sha256,
    capability_probe_receipt_sha256:
      authority.capability_manifest.probe_receipt_sha256,
  };
  const envelopeHash = sha256(Buffer.from(stableJson(envelope), 'utf8'));
  const actual = {
    duration_ms: 35000,
    delivery: {
      platform: 'youtube', configured_aspect: '16:9',
      artifact_aspect: '16:9', width: 1920, height: 1080,
    },
    preferences: {
      captions: { delivery: 'burned', event_count: 12 },
      graphics: { event_count: 2 },
      music: {
        added_music_present: musicPreference !== 'none',
        source_music_preserved: false,
      },
      sfx: {
        cue_count: 3, policy_usage: 'motivated_only', policy_bound: true,
      },
      transitions: {
        event_count: 2, non_hard_event_count: 1,
        policy_usage: 'motivated_only', policy_bound: true,
      },
    },
  };
  const report = {
    schema_version: 'autoeditor-project-intent-render-receipt/v2',
    authorization_id: authority.authorization_id,
    approved_proposal_sha256: authority.approved_proposal_sha256,
    approved_transition_carrier: null,
    engine_envelope_sha256: envelopeHash,
    project_intent: authority.project_intent,
    project_intent_sha256: authority.project_intent_sha256,
    edit_policy: authority.edit_policy,
    edit_policy_sha256: authority.edit_policy_sha256,
    capability_manifest: authority.capability_manifest,
    capability_manifest_sha256: authority.capability_manifest_sha256,
    capability_probe_receipt_sha256:
      authority.capability_manifest.probe_receipt_sha256,
    actual_render: actual,
    checks: Object.fromEntries([
      'canonical_authority', 'target_duration', 'delivery', 'captions',
      'graphics', 'music', 'sfx', 'transitions',
    ].map((name) => [name, { ok: true }])),
    pass: true,
  };
  const receiptBytes = Buffer.from(`${JSON.stringify(report, null, 2)}\n`, 'utf8');
  const receipt = {
    file: 'PROJECT_INTENT_RENDER_RECEIPT.json',
    bytes: receiptBytes.length,
    sha256: sha256(receiptBytes), report,
  };
  const engineCheck = {
    ok: true,
    authorization_id: authority.authorization_id,
    approved_proposal_sha256: authority.approved_proposal_sha256,
    approved_transition_carrier: null,
    engine_envelope_sha256: envelopeHash,
    project_intent_sha256: authority.project_intent_sha256,
    edit_policy_sha256: authority.edit_policy_sha256,
    capability_manifest_sha256: authority.capability_manifest_sha256,
    capability_probe_receipt_sha256:
      authority.capability_manifest.probe_receipt_sha256,
    render_receipt_sha256: sha256(Buffer.from(stableJson(report), 'utf8')),
    receipt_file_sha256: receipt.sha256,
    note: '',
  };
  const observed = {
    duration_ms: 35000, width: 1920, height: 1080,
    caption_delivery: 'burned', caption_event_count: 12,
    graphic_event_count: 2,
    added_music_present: musicPreference !== 'none', sfx_cue_count: 3,
    sfx_policy_usage: 'motivated_only', sfx_policy_bound: true,
    transition_event_count: 2, non_hard_transition_count: 1,
    transition_policy_usage: 'motivated_only', transition_policy_bound: true,
  };
  return {
    project, approvedProposal, authority, report, receipt, receiptBytes,
    engineCheck, observed,
  };
}

(() => {
  const value = fixture();
  const result = validateProjectIntentArtifactBinding({
    receipt: value.receipt,
    approvedProposal: value.approvedProposal,
    approvedAuthority: value.authority,
    engineCheck: value.engineCheck,
    observed: value.observed,
  });
  assert.equal(result.authorizationId, '1'.repeat(32));
  assert.equal(result.receiptFileSha256, value.receipt.sha256);

  for (const mutation of [
    (candidate) => { candidate.receipt.report.project_intent_sha256 = '0'.repeat(64); },
    (candidate) => { candidate.receipt.report.actual_render.duration_ms = 46000; },
    (candidate) => { candidate.engineCheck.receipt_file_sha256 = '0'.repeat(64); },
    (candidate) => { candidate.observed.caption_event_count = 11; },
    (candidate) => { candidate.approvedProposal = {}; },
  ]) {
    const candidate = {
      receipt: clone(value.receipt),
      approvedProposal: { projectIntent: clone(value.project) },
      approvedAuthority: clone(value.authority),
      engineCheck: clone(value.engineCheck),
      observed: clone(value.observed),
    };
    mutation(candidate);
    assert.throws(() => validateProjectIntentArtifactBinding(candidate),
      ArtifactContractError);
  }
})();

(() => {
  const value = fixture({ unicode: true });
  const result = validateProjectIntentArtifactBinding({
    receipt: value.receipt,
    approvedProposal: value.approvedProposal,
    approvedAuthority: value.authority,
    engineCheck: value.engineCheck,
    observed: value.observed,
  });
  assert.equal(result.approvedProposalSha256,
    value.authority.approved_proposal_sha256,
    'Unicode proposal canonicalization must match Python ensure_ascii=True');
})();

(() => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-music-binding-'));
  try {
    const value = fixture({ musicPreference: 'none' });
    const duration = 35000;
    const executionPolicy = clone(value.authority.edit_policy);
    executionPolicy.duration.duration_ms = duration;
    const policyBytes = Buffer.from(`${stableJson(executionPolicy)}\n`, 'ascii');
    const policyFile = 'MUSIC_EXECUTION_EDIT_POLICY.json';
    fs.writeFileSync(path.join(root, policyFile), policyBytes);
    const input = {
      sha256: '7'.repeat(64), bytes: 34567, duration_ms: duration,
      audio_present: true, sample_rate_hz: 48000, channels: 2,
    };
    const timeline = sha256(Buffer.from(stableJson({
      schema_version: 'autoeditor-music-output-timeline/v1',
      program_sha256: input.sha256,
      program_bytes: input.bytes,
      duration_ms: duration,
      time_base: { numerator: 1, denominator: 1000 },
    }), 'utf8'));
    const report = {
      schema_version: 'autoeditor-music-production-receipt/v1',
      mode: 'no_music_requested',
      authorization_id: value.authority.authorization_id,
      capability_used: null,
      engine_envelope_sha256: value.report.engine_envelope_sha256,
      project_intent_sha256: value.authority.project_intent_sha256,
      parent_edit_policy_sha256: value.authority.edit_policy_sha256,
      execution_edit_policy_sha256: editPolicySha256(executionPolicy),
      target_duration: clone(value.project.target_duration),
      actual_duration_ms: duration,
      duration_band: executionPolicy.duration.band,
      requested_preference: 'none',
      policy: clone(executionPolicy.rules.music),
      region_count: 0,
      added_coverage_ms: 0,
      output_timeline_sha256: timeline,
      program_input: input,
      output: clone(input),
      rights: { basis: null, generator: null, external_service_used: false },
      audio_qa: null,
      music_asset_manifest_sha256: null,
      music_plan_sha256: null,
      music_compile_receipt_sha256: null,
      music_render_receipt_sha256: null,
      sidecars: [{
        file: policyFile, sha256: sha256(policyBytes), bytes: policyBytes.length,
      }],
    };
    const receiptBytes = Buffer.from(`${stableJson(report)}\n`, 'ascii');
    const receipt = {
      report, sha256: sha256(receiptBytes), bytes: receiptBytes.length,
      file: 'MUSIC_PRODUCTION_RECEIPT.json',
    };
    const productionHash = sha256(Buffer.from(stableJson(report), 'utf8'));
    const engineCheck = {
      ok: true,
      authorization_id: report.authorization_id,
      engine_envelope_sha256: report.engine_envelope_sha256,
      project_intent_sha256: report.project_intent_sha256,
      parent_edit_policy_sha256: report.parent_edit_policy_sha256,
      execution_edit_policy_sha256: report.execution_edit_policy_sha256,
      mode: report.mode,
      region_count: 0,
      policy_usage: report.policy.usage,
      policy_bound: true,
      rights_verified: true,
      dialogue_masking_verified: true,
      loudness_verified: true,
      production_receipt_sha256: productionHash,
      receipt_file_sha256: receipt.sha256,
      program_input_sha256: input.sha256,
      music_output_sha256: input.sha256,
      measured_audio: null,
      note: '',
    };
    const args = {
      receipt, outputDir: root, approvedAuthority: value.authority,
      engineCheck,
      expectedEngineEnvelopeSha256: value.report.engine_envelope_sha256,
    };
    const validated = validateMusicProductionArtifactBinding(args);
    assert.equal(validated.mode, 'no_music_requested');
    assert.equal(validated.regionCount, 0);
    assert.equal(validated.addedMusicPresent, false);

    const swappedOutput = clone(args);
    swappedOutput.receipt.report.output.sha256 = '8'.repeat(64);
    assert.throws(() => validateMusicProductionArtifactBinding(swappedOutput),
    ArtifactContractError);
    const falseRights = clone(args);
    falseRights.receipt.report.rights = {
      basis: 'project_owned',
      generator: 'autoeditor-deterministic-musical-pcm/v1',
      external_service_used: false,
    };
    assert.throws(() => validateMusicProductionArtifactBinding(falseRights),
    ArtifactContractError);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
})();

(() => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-sfx-binding-'));
  try {
    const value = fixture();
    const duration = 35000;
    const executionPolicy = clone(value.authority.edit_policy);
    executionPolicy.duration.duration_ms = duration;
    const policyBytes = Buffer.from(`${JSON.stringify(executionPolicy)}\n`, 'utf8');
    const policyFile = 'SFX_EXECUTION_EDIT_POLICY.json';
    fs.writeFileSync(path.join(root, policyFile), policyBytes);
    const input = {
      sha256: '3'.repeat(64), bytes: 12345, duration_ms: duration,
    };
    const timeline = sha256(Buffer.from(stableJson({
      schema_version: 'autoeditor-sfx-output-timeline/v1',
      program_sha256: input.sha256,
      program_bytes: input.bytes,
      duration_ms: duration,
      time_base: { numerator: 1, denominator: 1000 },
    }), 'utf8'));
    const report = {
      schema_version: 'autoeditor-sfx-production-receipt/v1',
      mode: 'no_motivated_anchor',
      authorization_id: value.authority.authorization_id,
      engine_envelope_sha256: value.report.engine_envelope_sha256,
      project_intent_sha256: value.authority.project_intent_sha256,
      parent_edit_policy_sha256: value.authority.edit_policy_sha256,
      execution_edit_policy_sha256: editPolicySha256(executionPolicy),
      target_duration: clone(value.project.target_duration),
      actual_duration_ms: duration,
      duration_band: executionPolicy.duration.band,
      requested_preference: value.project.preferences.sfx.preference,
      policy: clone(executionPolicy.rules.sfx),
      cue_count: 0,
      output_timeline_sha256: timeline,
      program_input: input,
      output: clone(input),
      cue_manifest_sha256: null,
      sfx_plan_sha256: null,
      sfx_compile_receipt_sha256: null,
      sfx_render_receipt_sha256: null,
      sidecars: [{
        file: policyFile, sha256: sha256(policyBytes), bytes: policyBytes.length,
      }],
    };
    const receiptBytes = Buffer.from(`${JSON.stringify(report)}\n`, 'utf8');
    const receipt = {
      report, sha256: sha256(receiptBytes), bytes: receiptBytes.length,
      file: 'SFX_PRODUCTION_RECEIPT.json',
    };
    const engineCheck = {
      ok: true,
      authorization_id: report.authorization_id,
      engine_envelope_sha256: report.engine_envelope_sha256,
      project_intent_sha256: report.project_intent_sha256,
      parent_edit_policy_sha256: report.parent_edit_policy_sha256,
      mode: report.mode,
      cue_count: 0,
      policy_usage: report.policy.usage,
      policy_bound: true,
      production_receipt_sha256:
        sha256(Buffer.from(stableJson(report), 'utf8')),
      receipt_file_sha256: receipt.sha256,
      master_output_sha256: input.sha256,
      program_input_sha256: input.sha256,
      music_output_sha256: input.sha256,
      program_input_matches_music_output: true,
      note: '',
    };
    const audioMixReceipt = { report: { master: {
      sha256: input.sha256, bytes: input.bytes, duration_seconds: 35,
    } } };
    const args = {
      receipt,
      outputDir: root,
      approvedAuthority: value.authority,
      engineCheck,
      audioMixReceipt,
      expectedEngineEnvelopeSha256: value.report.engine_envelope_sha256,
      expectedMusicOutput: input,
    };
    const validated = validateSfxProductionArtifactBinding(args);
    assert.equal(validated.mode, 'no_motivated_anchor');
    assert.equal(validated.cueCount, 0);

    const changedTimeline = clone(args);
    changedTimeline.receipt.report.output_timeline_sha256 = '4'.repeat(64);
    assert.throws(() => validateSfxProductionArtifactBinding(changedTimeline),
      ArtifactContractError);
    const changedMaster = clone(args);
    changedMaster.audioMixReceipt.report.master.sha256 = '5'.repeat(64);
    assert.throws(() => validateSfxProductionArtifactBinding(changedMaster),
      ArtifactContractError);
    const swappedEnvelope = clone(args);
    swappedEnvelope.expectedEngineEnvelopeSha256 = '6'.repeat(64);
    assert.throws(() => validateSfxProductionArtifactBinding(swappedEnvelope),
      ArtifactContractError);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
})();

(() => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-artifact-v3-'));
  try {
    const value = fixture();
    const pending = path.join(root, 'edit.UNVERIFIED.mp4');
    const approved = path.join(root, 'edit.mp4');
    const media = Buffer.from('reviewed-media', 'utf8');
    fs.writeFileSync(pending, media);
    const writeSidecar = (file, bytes) => {
      fs.writeFileSync(path.join(root, file), bytes);
      return { file, bytes: bytes.length, sha256: sha256(bytes) };
    };
    const boundaries = writeSidecar('EDIT_BOUNDARIES.json',
      Buffer.from('{"schema":"autoeditor-edit-boundaries/v1"}\n', 'utf8'));
    const mix = writeSidecar('AUDIO_MIX_RECEIPT.json',
      Buffer.from('{"schema":"autoeditor-audio-mix-receipt/v1"}\n', 'utf8'));
    const intentReceipt = writeSidecar(value.receipt.file, value.receiptBytes);
    const musicProduction = writeSidecar('MUSIC_PRODUCTION_RECEIPT.json',
      Buffer.from('{"schema_version":"autoeditor-music-production-receipt/v1"}\n',
        'utf8'));
    const sfxProduction = writeSidecar('SFX_PRODUCTION_RECEIPT.json',
      Buffer.from('{"schema_version":"autoeditor-sfx-production-receipt/v1"}\n',
        'utf8'));
    const qa = {
      schema: 'autoeditor-engine-qa/v2', pass: true,
      checks: { project_intent_authority: value.engineCheck },
      artifact_contract: {
        schema: 'autoeditor-engine-artifact-contract/v4',
        mode: 'generic-baseline',
        delivery: { file: path.basename(approved), bytes: media.length,
          sha256: sha256(media) },
        edl: null, captions: null, caption_render: null,
        edit_boundaries: boundaries, audio_mix: mix, sequence: null,
        project_intent: intentReceipt,
        music_production: musicProduction,
        sfx_production: sfxProduction,
      },
      release: { delivery: { file: approved, bytes: media.length,
        sha256: sha256(media) } },
    };
    fs.writeFileSync(path.join(root, 'QA_REPORT.json'),
      `${JSON.stringify(qa)}\n`, 'utf8');
    const qaReceipt = readArtifactQaReport(root, {
      output: pending, outputs: { delivery: pending },
      finalOutputs: { delivery: approved },
      qaReport: path.join(root, 'QA_REPORT.json'),
    }, sha256(media), media.length);
    assert.equal(qaReceipt.contract.schema,
      'autoeditor-engine-artifact-contract/v4');
    assert.equal(readContractJsonSidecar(
      root, qaReceipt.contract, 'project_intent', 'ProjectIntent').report.pass,
    true);

    const changed = clone(qa);
    delete changed.artifact_contract.project_intent;
    fs.writeFileSync(path.join(root, 'QA_REPORT.json'),
      `${JSON.stringify(changed)}\n`, 'utf8');
    assert.throws(() => readArtifactQaReport(root, {
      output: pending, outputs: { delivery: pending },
      finalOutputs: { delivery: approved },
      qaReport: path.join(root, 'QA_REPORT.json'),
    }, sha256(media), media.length), ArtifactContractError);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
})();

console.log('ProjectIntent artifact binding tests passed');
