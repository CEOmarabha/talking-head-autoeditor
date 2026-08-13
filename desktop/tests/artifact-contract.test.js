'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  ArtifactContractError,
  readArtifactQaReport,
  readContractJsonSidecar,
} = require('../helper/lib/artifact-contract');

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function stableJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) =>
    `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
}

function canonicalHash(value) {
  return sha256(Buffer.from(stableJson(value), 'ascii'));
}

function writeBound(root, file, value) {
  const bytes = Buffer.from(`${JSON.stringify(value)}\n`, 'utf8');
  fs.writeFileSync(path.join(root, file), bytes, { flag: 'wx', mode: 0o600 });
  return { file, bytes: bytes.length, sha256: sha256(bytes) };
}

function fixture(root) {
  const pending = path.join(root, 'edit.UNVERIFIED.mp4');
  const approved = path.join(root, 'edit.mp4');
  const media = Buffer.from('fixed reviewed artifact bytes', 'utf8');
  fs.writeFileSync(pending, media, { flag: 'wx', mode: 0o600 });
  const boundaries = writeBound(root, 'EDIT_BOUNDARIES.json', {
    schema: 'autoeditor-edit-boundaries/v1', timeline: 'post_cut_seconds',
    cuts: [], transitions: [], transition_support: 'not_implemented',
  });
  const mix = writeBound(root, 'AUDIO_MIX_RECEIPT.json', {
    schema: 'autoeditor-audio-mix-receipt/v1', master_sha256: sha256(media),
  });
  const contract = {
    schema: 'autoeditor-engine-artifact-contract/v2',
    mode: 'generic-baseline',
    delivery: { file: path.basename(approved), bytes: media.length,
      sha256: sha256(media) },
    edl: null, captions: null, caption_render: null,
    edit_boundaries: boundaries, audio_mix: mix, sequence: null,
  };
  const report = {
    schema: 'autoeditor-engine-qa/v2', pass: true,
    checks: { fixture: { ok: true } }, artifact_contract: contract,
    release: { delivery: { file: approved, bytes: media.length,
      sha256: sha256(media) } },
  };
  writeBound(root, 'QA_REPORT.json', report);
  const event = {
    output: pending,
    outputs: { delivery: pending },
    finalOutputs: { delivery: approved },
    qaReport: path.join(root, 'QA_REPORT.json'),
  };
  return { pending, approved, media, contract, report, event };
}

const visualThresholds = {
  black_luma_max: 16, black_pixel_ratio_ppm_min: 990000,
  blank_luma_range_max: 4, blank_luma_mad_max: 1,
  near_duplicate_mae_ppm_max: 8000, freeze_duration_us_min: 500000,
  flash_luma_jump_min: 64, flash_outer_mae_ppm_max: 47059,
  overlay_channel_delta_min: 8, overlay_pixel_presence_ppm_min: 2000,
  overlay_state_signal_ppm_min: 10000,
  caption_contrast_ratio_ppm_min: 4500000,
  graphic_contrast_ratio_ppm_min: 3000000,
  transition_endpoint_mae_ppm_min: 20000,
  transition_alpha_ppm_min: 50000, transition_alpha_ppm_max: 950000,
  transition_blend_residual_ppm_max: 30000,
  transition_between_component_ratio_ppm_min: 950000,
  dip_black_pixel_ratio_ppm_min: 950000,
};
const visualScope = {
  claims: [
    'decoded-rgb24-black-and-uniform-frame-measurement',
    'decoded-rgb24-near-duplicate-and-isolated-flash-measurement',
    'trusted-renderer-rectangle-and-safe-area-containment',
    'trusted-receipt-overlay-pixel-presence-contrast-and-state-change',
    'trusted-transition-before-middle-after-pixel-continuity',
  ],
  unsupported: [
    'ocr', 'semantic-content', 'identity-or-target-recognition',
    'aesthetic-quality', 'intent-inference', 'arbitrary-transition-quality',
  ],
};

function deterministicVisualRecord(media) {
  const artifactSha256 = sha256(media);
  const frame = {
    frame_id: 'frame-00000000', frame_index: 0, timestamp_us: 0,
    rgb24_sha256: 'c'.repeat(64), bytes: 16 * 16 * 3,
  };
  const intent = {
    schema_version: 'autoeditor-production-visual-timeline-intent/v1',
    intentional_dark_intervals_ms: [], transitions: [],
    transition_receipt_sha256: null,
  };
  const decoder = {
    schema_version: 'autoeditor-ffmpeg-rgb24-decoder-receipt/v1',
    artifact_sha256: artifactSha256, artifact_bytes: media.length,
    ffmpeg_sha256: '1'.repeat(64),
    source_geometry: { width: 16, height: 16, pixel_format: 'yuv420p' },
    decoded_geometry: { width: 16, height: 16, pixel_format: 'rgb24' },
    frame_rate: { numerator: 1, denominator: 1 },
    source_frame_count: 1, source_duration_ms: 1000,
    filter: {
      selection: 'zero_based_frame_index', scale_width: 16, scale_height: 16,
      scale_flags: 'bilinear', pixel_format: 'rgb24', fps_mode: 'passthrough',
    },
    frames: [frame],
  };
  const decoderSha256 = canonicalHash(decoder);
  const plan = {
    frame_state: [{
      check_id: 'non-blank-000', frame_id: frame.frame_id,
      expected_state: 'non_blank_content',
    }],
    temporal_window: [], geometry: [], overlay: [], transition: [],
  };
  const timelineFrames = [{
    frame_id: frame.frame_id, frame_index: frame.frame_index,
    timestamp_us: frame.timestamp_us, rgb24_sha256: frame.rgb24_sha256,
  }];
  const timelineReceipt = {
    schema_version: 'autoeditor-decoded-frame-timeline-receipt/v1',
    artifact_sha256: artifactSha256,
    decoder_receipt_sha256: decoderSha256,
    intent_sha256: canonicalHash(intent),
    frame_rate: decoder.frame_rate, frames: timelineFrames,
    check_plan: plan, check_plan_sha256: canonicalHash(plan),
  };
  const timelineReceiptSha256 = canonicalHash(timelineReceipt);
  const request = {
    schema_version: 'autoeditor-visual-quality-deterministic-request/v1',
    artifact_sha256: artifactSha256,
    decoder_receipt_sha256: decoderSha256,
    timeline_receipt_sha256: timelineReceiptSha256,
    geometry: decoder.decoded_geometry,
    timeline: { frame_rate: decoder.frame_rate, frames: timelineFrames },
    checks: plan,
  };
  const frameResult = {
    check_id: 'non-blank-000', frame_id: frame.frame_id,
    expected_state: 'non_blank_content', frame_sha256: frame.rgb24_sha256,
    metrics: {
      mean_luma: 100, minimum_luma: 10, maximum_luma: 200,
      luma_range: 190, luma_mad: 20, black_pixel_ratio_ppm: 0,
      quantized_luma_bin_count: 10,
    },
    observations: { black: false, blank: false }, passed: true, defects: [],
  };
  const analyzerReceipt = {
    schema_version: 'autoeditor-visual-quality-deterministic-receipt/v1',
    analyzer: {
      algorithm_version: 'autoeditor-rgb24-technical-evidence/v1',
      thresholds: visualThresholds,
    },
    binding: {
      artifact_sha256: artifactSha256,
      decoder_receipt_sha256: decoderSha256,
      timeline_receipt_sha256: timelineReceiptSha256,
      request_sha256: canonicalHash(request),
      decoded_frames_sha256: canonicalHash([{
        frame_id: frame.frame_id, rgb24_sha256: frame.rgb24_sha256,
        bytes: frame.bytes,
      }]),
      geometry_sha256: canonicalHash(decoder.decoded_geometry),
      timeline_sha256: canonicalHash(request.timeline),
      renderer_receipt_sha256s: [],
    },
    scope: visualScope,
    checks: {
      frame_state: [frameResult], temporal_window: [], geometry: [], overlay: [],
      transition: [],
    },
    summary: {
      check_count: 1, passed_count: 1, failed_count: 0, all_passed: true,
      failed_check_ids: [],
    },
  };
  return {
    schema_version: 'autoeditor-production-deterministic-visual-qa/v1',
    artifact: { sha256: artifactSha256, bytes: media.length },
    runtime: {
      offline: true,
      ffmpeg: { sha256: '1'.repeat(64), bytes: 1000 },
      ffprobe: { sha256: '2'.repeat(64), bytes: 1000 },
    },
    intent, intent_sha256: canonicalHash(intent), decoder_receipt: decoder,
    decoder_receipt_sha256: decoderSha256,
    timeline_receipt: timelineReceipt,
    timeline_receipt_sha256: timelineReceiptSha256,
    analysis: {
      schema_version: 'autoeditor-visual-quality-deterministic-result/v1',
      receipt: analyzerReceipt, receipt_sha256: canonicalHash(analyzerReceipt),
    },
    coverage: {
      artifact_frame_count: 1, decoded_frame_count: 1,
      non_blank_sample_count: 1, temporal_window_count: 0,
      declared_transition_count: 0, analyzed_transition_count: 0,
    },
    pass: true,
  };
}

function attachDeterministicVisual(root, value, schema =
  'autoeditor-engine-artifact-contract/v3') {
  const record = deterministicVisualRecord(value.media);
  const bytes = Buffer.from(`${stableJson(record)}\n`, 'ascii');
  fs.writeFileSync(path.join(root, 'DETERMINISTIC_VISUAL_QA.json'), bytes,
    { flag: 'wx', mode: 0o600 });
  const binding = {
    file: 'DETERMINISTIC_VISUAL_QA.json', bytes: bytes.length,
    sha256: sha256(bytes),
  };
  value.contract.schema = schema;
  value.contract.deterministic_visual_qa = binding;
  if (schema === 'autoeditor-engine-artifact-contract/v5') {
    const authority = { file: 'authority.json', bytes: 1, sha256: 'd'.repeat(64) };
    value.contract.project_intent = authority;
    value.contract.music_production = { ...authority, file: 'music.json' };
    value.contract.sfx_production = { ...authority, file: 'sfx.json' };
  }
  value.report.checks.deterministic_visual_quality = {
    ok: true, artifact_sha256: sha256(value.media),
    receipt_file_sha256: binding.sha256,
    analyzer_receipt_sha256: record.analysis.receipt_sha256,
    check_count: 1, failed_check_ids: [], declared_transition_count: 0,
    analyzed_transition_count: 0, semantic_evaluation: false, note: '',
  };
  overwriteReport(root, value.report);
  value.visualRecord = record;
  return value;
}

function rewriteVisual(root, value, bytes) {
  fs.writeFileSync(path.join(root, 'DETERMINISTIC_VISUAL_QA.json'), bytes);
  const binding = value.report.artifact_contract.deterministic_visual_qa;
  binding.bytes = bytes.length;
  binding.sha256 = sha256(bytes);
  value.report.checks.deterministic_visual_quality.receipt_file_sha256 =
    binding.sha256;
  overwriteReport(root, value.report);
}

function overwriteReport(root, report) {
  fs.writeFileSync(path.join(root, 'QA_REPORT.json'),
    `${JSON.stringify(report)}\n`, { encoding: 'utf8' });
}

function assertRejected(root, value) {
  assert.throws(() => readArtifactQaReport(
    root, value.event, sha256(value.media), value.media.length),
  ArtifactContractError);
}

(() => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-artifact-contract-'));
  try {
    const value = fixture(root);
    const receipt = readArtifactQaReport(
      root, value.event, sha256(value.media), value.media.length);
    assert.equal(receipt.contract.mode, 'generic-baseline');
    assert.equal(receipt.release.file, value.approved);
    assert.equal(readContractJsonSidecar(
      root, receipt.contract, 'edit_boundaries', 'boundaries').report.schema,
    'autoeditor-edit-boundaries/v1');
    assert.equal(readContractJsonSidecar(
      root, receipt.contract, 'audio_mix', 'mix').report.schema,
    'autoeditor-audio-mix-receipt/v1');

    fs.appendFileSync(value.pending, Buffer.from('mutated'));
    assert.throws(() => readArtifactQaReport(
      root, value.event, sha256(value.media), value.media.length),
    ArtifactContractError);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }

  for (const mutation of [
    (value) => { value.report.pass = false; },
    (value) => { value.report.checks.release_blocking_check = { ok: false }; },
    (value) => { value.report.checks.release_blocking_check = { note: 'missing ok' }; },
    (value) => { value.report.schema = 'autoeditor-engine-qa/v1'; },
    (value) => { value.report.artifact_contract.mode = 'premium-edl'; },
    (value) => { value.report.artifact_contract.delivery.file = 'wrong.mp4'; },
    (value) => { value.report.artifact_contract.delivery.sha256 = '0'.repeat(64); },
    (value) => { value.report.release = { wrong: value.report.release.delivery }; },
    (value) => { value.report.release.delivery.file = path.join(path.dirname(
      value.approved), 'other.mp4'); },
    (value) => { value.report.artifact_contract.extra = true; },
  ]) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-artifact-mutation-'));
    try {
      const value = fixture(root);
      mutation(value);
      overwriteReport(root, value.report);
      assertRejected(root, value);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  }

  const sidecarRoot = fs.mkdtempSync(path.join(
    os.tmpdir(), 'autoeditor-artifact-sidecar-'));
  try {
    const value = fixture(sidecarRoot);
    const receipt = readArtifactQaReport(
      sidecarRoot, value.event, sha256(value.media), value.media.length);
    fs.appendFileSync(path.join(sidecarRoot, 'EDIT_BOUNDARIES.json'), '\n{}');
    assert.throws(() => readContractJsonSidecar(
      sidecarRoot, receipt.contract, 'edit_boundaries', 'boundaries'),
    ArtifactContractError);
  } finally { fs.rmSync(sidecarRoot, { recursive: true, force: true }); }

  const bindingRoot = fs.mkdtempSync(path.join(
    os.tmpdir(), 'autoeditor-artifact-binding-'));
  try {
    const value = fixture(bindingRoot);
    value.report.artifact_contract.edit_boundaries.sha256 = '0'.repeat(64);
    overwriteReport(bindingRoot, value.report);
    const receipt = readArtifactQaReport(
      bindingRoot, value.event, sha256(value.media), value.media.length);
    assert.throws(() => readContractJsonSidecar(
      bindingRoot, receipt.contract, 'edit_boundaries', 'boundaries'),
    ArtifactContractError);
  } finally { fs.rmSync(bindingRoot, { recursive: true, force: true }); }

  for (const schema of [
    'autoeditor-engine-artifact-contract/v3',
    'autoeditor-engine-artifact-contract/v5',
  ]) {
    const root = fs.mkdtempSync(path.join(
      os.tmpdir(), 'autoeditor-deterministic-visual-contract-'));
    try {
      const value = attachDeterministicVisual(root, fixture(root), schema);
      const receipt = readArtifactQaReport(
        root, value.event, sha256(value.media), value.media.length);
      assert.equal(receipt.contract.schema, schema);
      assert.equal(receipt.deterministicVisualQa.report.pass, true);
      assert.equal(receipt.deterministicVisualQa.summary.check_count, 1);
      assert.equal(
        receipt.deterministicVisualQa.record.artifact.sha256,
        sha256(value.media));
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  }

  for (const mutation of [
    (root, value) => {
      delete value.report.artifact_contract.deterministic_visual_qa;
      overwriteReport(root, value.report);
    },
    (root, value) => {
      delete value.report.checks.deterministic_visual_quality;
      overwriteReport(root, value.report);
    },
    (root, value) => {
      value.report.artifact_contract.schema =
        'autoeditor-engine-artifact-contract/v2';
      overwriteReport(root, value.report);
    },
    (root, value) => {
      value.visualRecord.artifact.sha256 = '0'.repeat(64);
      rewriteVisual(root, value,
        Buffer.from(`${stableJson(value.visualRecord)}\n`, 'ascii'));
    },
    (root, value) => {
      const summary = value.visualRecord.analysis.receipt.summary;
      summary.check_count = 2;
      value.visualRecord.analysis.receipt_sha256 = canonicalHash(
        value.visualRecord.analysis.receipt);
      value.report.checks.deterministic_visual_quality
        .analyzer_receipt_sha256 = value.visualRecord.analysis.receipt_sha256;
      value.report.checks.deterministic_visual_quality.check_count = 2;
      rewriteVisual(root, value,
        Buffer.from(`${stableJson(value.visualRecord)}\n`, 'ascii'));
    },
    (root, value) => {
      rewriteVisual(root, value,
        Buffer.from(`${JSON.stringify(value.visualRecord)}\n`, 'ascii'));
    },
  ]) {
    const root = fs.mkdtempSync(path.join(
      os.tmpdir(), 'autoeditor-deterministic-visual-mutation-'));
    try {
      const value = attachDeterministicVisual(root, fixture(root));
      mutation(root, value);
      assertRejected(root, value);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  }

  const replayRoot = fs.mkdtempSync(path.join(
    os.tmpdir(), 'autoeditor-deterministic-visual-replay-'));
  try {
    const value = attachDeterministicVisual(replayRoot, fixture(replayRoot));
    const replayedMedia = Buffer.from(value.media.map((byte) => byte ^ 0xff));
    fs.writeFileSync(value.pending, replayedMedia);
    value.media = replayedMedia;
    value.report.artifact_contract.delivery.sha256 = sha256(replayedMedia);
    value.report.release.delivery.sha256 = sha256(replayedMedia);
    overwriteReport(replayRoot, value.report);
    assertRejected(replayRoot, value);
  } finally { fs.rmSync(replayRoot, { recursive: true, force: true }); }

  const changedSidecarRoot = fs.mkdtempSync(path.join(
    os.tmpdir(), 'autoeditor-deterministic-visual-sidecar-change-'));
  try {
    const value = attachDeterministicVisual(
      changedSidecarRoot, fixture(changedSidecarRoot));
    fs.appendFileSync(path.join(
      changedSidecarRoot, 'DETERMINISTIC_VISUAL_QA.json'), '{}');
    assertRejected(changedSidecarRoot, value);
  } finally { fs.rmSync(changedSidecarRoot, { recursive: true, force: true }); }

  console.log('artifact contract reader tests passed');
})();
