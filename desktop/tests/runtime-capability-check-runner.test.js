'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  CAPABILITY_CHECK_IDS,
} = require('../helper/lib/runtime-capabilities');
const {
  fixedCheckContractBytes,
  fixedCheckFixtureBytes,
} = require('../helper/lib/runtime-capability-probe');
const {
  FIXTURELESS_CHECKS,
  MUSIC_PRODUCTION_TIMEOUT_MS,
  RuntimeCapabilityCheckRunnerError,
  createRuntimeCapabilityCheckRunner,
  runBoundedCommand,
} = require('../helper/lib/runtime-capability-check-runner');

const TEST_FONT_BYTES = Buffer.alloc(120_000, 0x5a);
const TEST_FONT_SHA256 = require('node:crypto').createHash('sha256')
  .update(TEST_FONT_BYTES).digest('hex');
const CAPTION_FRAME_BYTES = 180 * 61 * 3;

function stableJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => (
    `${JSON.stringify(key)}:${stableJson(value[key])}`
  )).join(',')}}`;
}

function captionFrame(name, mode = 'valid') {
  const frame = Buffer.alloc(CAPTION_FRAME_BYTES, 32);
  if (mode !== 'valid' || name.startsWith('blank_')) return frame;
  const range = name === 'word_cut' ? [0, 1_500] :
    name === 'word_it' ? [1_500, 3_000] : [3_000, 4_500];
  for (let pixel = range[0]; pixel < range[1]; pixel += 1) {
    const offset = pixel * 3;
    frame[offset] = 220;
    frame[offset + 1] = 180;
    frame[offset + 2] = 40;
  }
  return frame;
}

function captionDelta(left, right) {
  let changed = 0;
  let absolute = 0;
  for (let offset = 0; offset < left.length; offset += 3) {
    let maximum = 0;
    for (let channel = 0; channel < 3; channel += 1) {
      const value = Math.abs(left[offset + channel] - right[offset + channel]);
      maximum = Math.max(maximum, value);
      absolute += value;
    }
    if (maximum > 12) changed += 1;
  }
  return {
    changed_pixel_ratio: Number((changed / (left.length / 3)).toFixed(6)),
    mean_absolute_error: Number((absolute / left.length).toFixed(3)),
  };
}

function captionPixelEvidence(mode = 'valid') {
  const frames = Object.fromEntries([
    'blank_before', 'word_cut', 'word_it', 'word_now', 'blank_after',
  ].map((name) => [name, captionFrame(name, mode)]));
  return {
    timestamps_ms: {
      blank_before: 100, word_cut: 450, word_it: 750,
      word_now: 1050, blank_after: 1600,
    },
    frame_sha256: Object.fromEntries(Object.entries(frames).map(([name, frame]) => [
      name, require('node:crypto').createHash('sha256').update(frame).digest('hex'),
    ])),
    blank_control: captionDelta(frames.blank_before, frames.blank_after),
    active_vs_blank: {
      word_cut: captionDelta(frames.blank_before, frames.word_cut),
      word_it: captionDelta(frames.blank_before, frames.word_it),
      word_now: captionDelta(frames.blank_before, frames.word_now),
    },
    word_state_changes: {
      cut_to_it: captionDelta(frames.word_cut, frames.word_it),
      it_to_now: captionDelta(frames.word_it, frames.word_now),
    },
  };
}

function fakeExecutor(calls, creative = {
  hyperframes_render: true, remotion_render: true,
}, creativeExitCode = 0, captionOptions = {}, asrOptions = {},
musicOptions = {}, renderOptions = {}) {
  return async (command, args, options) => {
    calls.push({ command, args: [...args], options });
    const joined = args.join(' ');
    let stdout = Buffer.alloc(0);
    let stderr = Buffer.alloc(0);
    const output = args[args.length - 1];
    if (command.endsWith('engine.exe') &&
        args[0] === '--music-production-self-test') {
      const source = args[1];
      const rendered = args[2];
      const session = args[3];
      const digest = (bytes) => require('node:crypto').createHash('sha256')
        .update(bytes).digest('hex');
      const sourceBytes = fs.readFileSync(source);
      const outputBytes = Buffer.from('fixed project-generated music rendered bytes');
      fs.writeFileSync(rendered, outputBytes);
      const evidenceRoot = path.join(
        session, 'MUSIC_PRODUCTION_SELF_TEST', 'evidence');
      fs.mkdirSync(evidenceRoot, { recursive: true });
      const generation = {
        schema_version: 'autoeditor-music-generation-evidence/v1',
        generator: 'autoeditor-deterministic-musical-pcm/v1',
        parameters: { sample_rate_hz: 48000, channels: 2,
          sample_width_bytes: 2, duration_ms: 1000, tempo_millibpm: 96000,
          key: 'C_major', oscillator: 'sine_chord',
          frequencies_millihz: [130813, 164814, 195998, 261626],
          peak_amplitude_millionths: 240000 },
        asset: { sha256: '1'.repeat(64), bytes: 192044 },
        rights: { basis: 'project_owned', license_id: 'project-generated',
          license_name: 'Project ownership', licensor: 'project',
          external_service_used: false, permits_synchronization: true,
          permits_editing: true, permits_looping: false,
          permits_delivery: true },
      };
      const measured = {
        integrated_loudness_millilufs: -14100,
        loudness_tolerance_millilufs: 1000, passed: true,
        target_loudness_millilufs: -14000,
        true_peak_ceiling_millidbtp: -1000,
        true_peak_millidbtp: -1100,
      };
      const sidecarValues = {
        'MUSIC_ASSET_MANIFEST.json': { fixed: true },
        'MUSIC_AUDIO_QA.json': { fixed: true },
        'MUSIC_COMPILE_RECEIPT.json': { fixed: true },
        'MUSIC_EXECUTION_EDIT_POLICY.json': { fixed: true },
        'MUSIC_GENERATION_EVIDENCE.json': generation,
        'MUSIC_PLAN.json': { fixed: true },
        'MUSIC_RENDER_RECEIPT.json': { fixed: true },
        'MUSIC_SOURCE_ANALYSIS.json': { fixed: true },
        'MUSIC_SPEECH_EVIDENCE.json': { fixed: true },
      };
      const sidecars = Object.entries(sidecarValues).sort(([left], [right]) =>
        left < right ? -1 : 1).map(([file, value]) => {
        const bytes = Buffer.from(JSON.stringify(value), 'utf8');
        fs.writeFileSync(path.join(evidenceRoot, file), bytes);
        return { file, sha256: digest(bytes), bytes: bytes.length };
      });
      const waveBytes = Buffer.from('fixed generated music wave bytes');
      fs.writeFileSync(path.join(evidenceRoot, 'MUSIC_PROJECT_BED.wav'), waveBytes);
      sidecars.push({ file: 'MUSIC_PROJECT_BED.wav', sha256: digest(waveBytes),
        bytes: waveBytes.length });
      sidecars.sort((left, right) => left.file < right.file ? -1 : 1);
      const production = {
        schema_version: 'autoeditor-music-production-receipt/v1',
        mode: 'rendered', authorization_id: '7'.repeat(32),
        capability_used: 'project_generated_music',
        engine_envelope_sha256: '8'.repeat(64),
        project_intent_sha256: '9'.repeat(64),
        parent_edit_policy_sha256: 'a'.repeat(64),
        execution_edit_policy_sha256: 'b'.repeat(64),
        target_duration: { min_ms: 3800, max_ms: 4200 },
        actual_duration_ms: 4000, duration_band: 'micro',
        requested_preference: 'supporting',
        policy: { duck_under_dialogue: false, usage: 'supporting' },
        region_count: 1, added_coverage_ms: 1000,
        output_timeline_sha256: 'c'.repeat(64),
        program_input: { sha256: digest(sourceBytes), bytes: sourceBytes.length,
          duration_ms: 4000, audio_present: true, sample_rate_hz: 48000,
          channels: 2 },
        output: { sha256: digest(outputBytes), bytes: outputBytes.length,
          duration_ms: 4000, audio_present: true, sample_rate_hz: 48000,
          channels: 2 },
        rights: { basis: 'project_owned',
          generator: 'autoeditor-deterministic-musical-pcm/v1',
          external_service_used: false },
        audio_qa: measured,
        music_asset_manifest_sha256: 'd'.repeat(64),
        music_plan_sha256: 'e'.repeat(64),
        music_compile_receipt_sha256: 'f'.repeat(64),
        music_render_receipt_sha256: '1'.repeat(64), sidecars,
      };
      const placement = {
        expected_start_ms: 0, expected_end_ms: 1000,
        bed_window_start_ms: 100, bed_window_duration_ms: 500,
        dialogue_window_start_ms: 1550, dialogue_window_duration_ms: 500,
        bed_delta_rms_millionths: 30000,
        dialogue_delta_rms_millionths: 0,
        bed_music_tone_millionths: 20000,
        dialogue_music_tone_millionths: 0,
      };
      if (musicOptions.rightsTamper) {
        generation.rights.external_service_used = true;
        const bytes = Buffer.from(JSON.stringify(generation), 'utf8');
        fs.writeFileSync(
          path.join(evidenceRoot, 'MUSIC_GENERATION_EVIDENCE.json'), bytes);
        const binding = sidecars.find((item) =>
          item.file === 'MUSIC_GENERATION_EVIDENCE.json');
        binding.sha256 = digest(bytes);
        binding.bytes = bytes.length;
      }
      const productionBytes = Buffer.from(JSON.stringify(production), 'utf8');
      const receiptFile = path.join(evidenceRoot, 'MUSIC_PRODUCTION_RECEIPT.json');
      fs.writeFileSync(receiptFile, productionBytes);
      stdout = Buffer.from(JSON.stringify({
        event: 'autoeditor-engine-music-production-self-test',
        schema_version: 'autoeditor-music-production-self-test/v1',
        checks: { decoded_music_placement: true, dialogue_masking: true,
          independent_evidence_verifier: true, measured_loudness: true,
          omission_rejected: true, production_music_planner: true,
          production_music_renderer: true, project_generated_rights: true,
          tamper_rejected: true }, errors: {},
        result: { artifact: { file: path.basename(rendered),
          sha256: digest(outputBytes), bytes: outputBytes.length,
          duration_ms: 4000 }, production_receipt: {
          file: path.basename(receiptFile), sha256: digest(productionBytes),
          bytes: productionBytes.length,
          contract_sha256: digest(Buffer.from(stableJson(production), 'utf8')) },
        decoded_placement: placement, measured_audio: measured,
        evidence: { sidecar_count: 10, generation_sidecar_count: 1,
          rights_basis: 'project_owned', external_service_used: false } },
      }) + '\n', 'utf8');
    } else if (command.endsWith('engine.exe') &&
        args[0] === '--sfx-production-self-test') {
      const source = args[1];
      const rendered = args[2];
      const session = args[3];
      const digest = (bytes) => require('node:crypto').createHash('sha256')
        .update(bytes).digest('hex');
      const sourceBytes = fs.readFileSync(source);
      const outputBytes = Buffer.from('fixed project-generated SFX rendered bytes');
      fs.writeFileSync(rendered, outputBytes);
      const evidenceRoot = path.join(
        session, 'SFX_PRODUCTION_SELF_TEST', 'evidence');
      fs.mkdirSync(evidenceRoot, { recursive: true });
      const generation = {
        schema_version: 'autoeditor-sfx-generation-evidence/v1',
        generator: 'autoeditor-deterministic-pcm/v1', kind: 'whoosh',
        parameters: { sample_rate_hz: 48000, channels: 2,
          sample_width_bytes: 2, duration_ms: 800 },
        asset: { sha256: '1'.repeat(64), bytes: 153644 },
        rights: { basis: 'project_owned', license_id: 'project-generated',
          licensor: 'project', external_service_used: false },
      };
      const generationBytes = Buffer.from(JSON.stringify(generation), 'utf8');
      const generationSha = digest(generationBytes);
      const manifest = {
        schema_version: 'autoeditor-sfx-cue-manifest/v1',
        output_timeline_sha256: '2'.repeat(64), output_duration_ms: 3000,
        output_sample_rate_hz: 48000, output_channels: 2,
        assets: [{ asset_id: `sfxasset-${'3'.repeat(64)}`,
          sha256: generation.asset.sha256, byte_length: generation.asset.bytes,
          duration_ms: 800, sample_rate_hz: 48000, channels: 2,
          source_ref: 'project-generated://autoeditor-sfx-v1/whoosh.wav',
          provenance: 'project_generated', license: { basis: 'project_owned',
            license_id: 'project-generated', licensor: 'project',
            evidence_sha256: generationSha } }],
        anchors: [], speech_windows: [],
      };
      const plan = {
        schema_version: 'autoeditor-sfx-plan/v1',
        cue_manifest_sha256: '4'.repeat(64), edit_policy_sha256: '5'.repeat(64),
        output_timeline_sha256: '2'.repeat(64), output_duration_ms: 3000,
        policy: {}, cues: [{ cue_id: `sfxcue-${'6'.repeat(64)}`,
          asset_id: manifest.assets[0].asset_id,
          asset_sha256: generation.asset.sha256, kind: 'whoosh', motivation: {},
          placement: { start_ms: 460, trim_start_ms: 0,
            trim_duration_ms: 800, gain_millidb: -3000,
            attack_fade_ms: 20, release_fade_ms: 120 }, ducking: null }],
      };
      const renderReceipt = { cue_count: 1, render_mode: 'mixed',
        output: { sha256: digest(outputBytes), bytes: outputBytes.length } };
      const sidecarValues = {
        'SFX_BOUNDARY_ANCHOR_EVIDENCE.json': { fixed: true },
        'SFX_COMPILE_RECEIPT.json': { fixed: true },
        'SFX_CUE_MANIFEST.json': manifest,
        'SFX_EDL_ANCHOR_EVIDENCE.json': { fixed: true },
        'SFX_EXECUTION_EDIT_POLICY.json': { fixed: true },
        'SFX_GENERATION_WHOOSH.json': generation,
        'SFX_PLAN.json': plan,
        'SFX_RENDER_RECEIPT.json': renderReceipt,
        'SFX_SPEECH_EVIDENCE.json': { fixed: true },
      };
      const sidecars = Object.entries(sidecarValues).sort(([left], [right]) =>
        left < right ? -1 : 1).map(([file, value]) => {
        const bytes = Buffer.from(JSON.stringify(value), 'utf8');
        fs.writeFileSync(path.join(evidenceRoot, file), bytes);
        return { file, sha256: digest(bytes), bytes: bytes.length };
      });
      const production = {
        schema_version: 'autoeditor-sfx-production-receipt/v1', mode: 'rendered',
        authorization_id: '7'.repeat(32), engine_envelope_sha256: '8'.repeat(64),
        project_intent_sha256: '9'.repeat(64),
        parent_edit_policy_sha256: 'a'.repeat(64),
        execution_edit_policy_sha256: 'b'.repeat(64),
        target_duration: { min_ms: 2800, max_ms: 3200 },
        actual_duration_ms: 3000, duration_band: 'micro',
        requested_preference: 'motivated_only',
        policy: { density: 'sparse', usage: 'motivated_only' }, cue_count: 1,
        output_timeline_sha256: '2'.repeat(64),
        program_input: { sha256: digest(sourceBytes), bytes: sourceBytes.length,
          duration_ms: 3000 },
        output: { sha256: digest(outputBytes), bytes: outputBytes.length,
          duration_ms: 3000 },
        cue_manifest_sha256: '4'.repeat(64), sfx_plan_sha256: 'c'.repeat(64),
        sfx_compile_receipt_sha256: 'd'.repeat(64),
        sfx_render_receipt_sha256: 'e'.repeat(64), sidecars,
      };
      const productionBytes = Buffer.from(JSON.stringify(production), 'utf8');
      const receiptFile = path.join(evidenceRoot, 'SFX_PRODUCTION_RECEIPT.json');
      fs.writeFileSync(receiptFile, productionBytes);
      stdout = Buffer.from(JSON.stringify({
        event: 'autoeditor-engine-sfx-production-self-test',
        schema_version: 'autoeditor-sfx-production-self-test/v1',
        checks: { decoded_cue_placement: true,
          independent_evidence_verifier: true, production_sfx_planner: true,
          production_sfx_renderer: true, project_generated_rights: true,
          tamper_rejected: true },
        errors: {},
        result: {
          artifact: { file: path.basename(rendered), sha256: digest(outputBytes),
            bytes: outputBytes.length, duration_ms: 3000 },
          production_receipt: { file: path.basename(receiptFile),
            sha256: digest(productionBytes), bytes: productionBytes.length,
            contract_sha256: digest(Buffer.from(stableJson(production), 'utf8')) },
          decoded_placement: { expected_start_ms: 460, expected_end_ms: 1260,
            cue_window_start_ms: 560, cue_window_duration_ms: 500,
            control_window_start_ms: 1560, control_window_duration_ms: 500,
            cue_delta_rms_millionths: 56000,
            control_delta_rms_millionths: 0 },
          evidence: { sidecar_count: 9, generation_sidecar_count: 1,
            rights_basis: 'project_owned', external_service_used: false },
        },
      }) + '\n', 'utf8');
    } else if (command.endsWith('engine.exe') &&
        args[0] === '--render-capability-self-test') {
      const receiptFile = args[1];
      const digest = (bytes) => require('node:crypto').createHash('sha256')
        .update(bytes).digest('hex');
      const checks = {
        audio_crossfades: true,
        color_normalization: true,
        cross_dissolves: true,
        motion_quality_analysis: true,
      };
      if (renderOptions.failedCheck) checks[renderOptions.failedCheck] = false;
      const schemas = [
        'autoeditor-render-capability-runtime-probe/v1',
        'autoeditor-render-capability-fixture/v1',
        'autoeditor-sequence-plan/v1',
        'autoeditor-source-render-manifest/v4',
        'autoeditor-transition-plan/v1',
      ];
      const sourceColor = {
        codec_name: 'h264', pix_fmt: 'yuv420p', color_range: 'tv',
        color_space: 'bt470bg', color_transfer: 'bt470bg',
        color_primaries: 'bt470bg',
      };
      const deliveryColor = {
        codec_name: 'h264', pix_fmt: 'yuv420p', color_range: 'tv',
        color_space: 'bt709', color_transfer: 'bt709',
        color_primaries: 'bt709',
      };
      const fixture = {
        schema_version: 'autoeditor-render-capability-fixture/v1',
        frame_rate: { numerator: 30000, denominator: 1001 },
        geometry: { width: 160, height: 90 },
        source_selection_ms: 3000,
        transition_duration_ms: 400,
        audio: { sample_rate: 48000, channels: 2,
          source_a_frequency_hz: 440, source_b_frequency_hz: 880 },
        sources: [{ id: 'source-a-bt470bg',
          file: 'render-capability-bt470-source.mp4', sha256: '1'.repeat(64),
          bytes: 90000, duration_ms: 3003, color: sourceColor,
          generator_filter_sha256: '2'.repeat(64) },
        { id: 'source-b-bt709',
          file: 'render-capability-bt709-source.mp4', sha256: '3'.repeat(64),
          bytes: 91000, duration_ms: 3003, color: deliveryColor,
          generator_filter_sha256: '4'.repeat(64) }],
      };
      fixture.sha256 = digest(Buffer.from(stableJson(fixture), 'ascii'));
      const frame = (frameIndex, digit, rgb, luma, black = 0) => ({
        frame_index: frameIndex, sha256: digit.repeat(64), mean_rgb: rgb,
        mean_luma_millionths: luma,
        black_pixel_ratio_millionths: black,
      });
      const transitionWeights = renderOptions.badBlend ?
        Array(12).fill(0) :
        [6000, 90000, 172000, 259000, 340000, 425000,
          505000, 590000, 670000, 758000, 840000, 921000];
      const receiptValue = {
        schema_version: 'autoeditor-render-capability-runtime-probe/v1',
        checks,
        scope: {
          audio: 'fixed-440hz-to-880hz-qsin-overlap-48000hz-stereo',
          color: 'declared-bt470bg-tv-sdr-to-bt709-tv-yuv420p',
          motion: 'fixed-decoded-frame-blend-progression-and-no-black-flash',
          transition: 'single-400ms-xfade-fade-at-30000-1001fps',
          unsupported: ['hdr', 'optical_flow', 'arbitrary_transition_quality'],
        },
        fixture,
        runtime: {
          host: { file: 'engine.exe',
            sha256: renderOptions.runtimeHashTamper ? 'b'.repeat(64) :
              'a'.repeat(64), bytes: 30000000 },
          ffmpeg: { file: 'ffmpeg.exe', sha256: 'a'.repeat(64),
            bytes: 100000000 },
          ffprobe: { file: 'ffprobe.exe', sha256: 'a'.repeat(64),
            bytes: 90000000 },
          contract: { schemas,
            sha256: digest(Buffer.from(stableJson(schemas), 'ascii')) },
        },
        production: {
          edit_policy_sha256: '5'.repeat(64),
          filter_complex_sha256: '6'.repeat(64),
          sequence_compile_receipt_sha256: '7'.repeat(64),
          sequence_plan_sha256: '8'.repeat(64),
          topology_sha256: '9'.repeat(64),
          transition_compile_receipt_sha256: 'b'.repeat(64),
          transition_plan_sha256: 'c'.repeat(64),
          transition_render_receipt_sha256: 'd'.repeat(64),
        },
        artifact: {
          file: 'render-capability-artifact.mp4', sha256: 'e'.repeat(64),
          bytes: 168974, expected_duration_ms: 5600, video_frames: 168,
          audio_sample_frames: 269312, video_duration_us: 5605600,
          audio_duration_us: 5610667, av_drift_us: 5067,
          width: 160, height: 90,
          frame_rate: { numerator: 30000, denominator: 1001 },
          audio: { sample_rate: 48000, channels: 2 },
          delivery_color: { range: 'tv', space: 'bt709', transfer: 'bt709',
            primaries: 'bt709', pixel_format: 'yuv420p' },
        },
        evidence: {
          color: {
            source_declaration: sourceColor,
            normalization_mode: 'declared_sdr_to_bt709_tv',
            conversion_filter_sha256:
              '82749ad88450b4ccef19498768a2ce4e0e2ea27a65bad290b90f7f525f3db037',
            frame_index: 30, source_yuv_sha256: 'f'.repeat(64),
            normalized_reference_yuv_sha256: '0'.repeat(64),
            artifact_yuv_sha256: '1'.repeat(64),
            source_to_normalized_mae_millionths: 109610,
            artifact_to_reference_mae_millionths: 1792,
          },
          transition: {
            kind: 'cross_dissolve', duration_ms: 400, duration_frames: 12,
            start_frame: 78,
            estimated_right_weights_millionths: transitionWeights,
            blend_residuals_millionths: Array(12).fill(8000),
            before: frame(77, '2', [757000, 91000, 14000], 225000, 972),
            middle: frame(84, '3', [421000, 213000, 390000], 270000),
            after: frame(91, '4', [100000, 332000, 765000], 315000),
            max_adjacent_rgb_mae_millionths: 59587,
            max_black_pixel_ratio_millionths: 1042,
            min_mean_luma_millionths: 224591,
          },
          audio_crossfade: {
            behavior: 'equal_power_qsin', transition_start_ms: 2600,
            duration_ms: 400,
            before: { start_ms: 2450, duration_ms: 100,
              tone_440_millionths: 87911, tone_880_millionths: 10,
              rms_millionths: 62168 },
            middle: { start_ms: 2750, duration_ms: 100,
              tone_440_millionths: 61839, tone_880_millionths: 62223,
              rms_millionths: 62457 },
            after: { start_ms: 3050, duration_ms: 100,
              tone_440_millionths: 11, tone_880_millionths: 88367,
              rms_millionths: 62493 },
          },
        },
      };
      const receiptPayload = renderOptions.receiptContentTamper ? {
        ...receiptValue,
        checks: { ...checks, color_normalization: false },
      } : receiptValue;
      const receiptBytes = Buffer.from(`${stableJson(receiptPayload)}\n`, 'ascii');
      fs.writeFileSync(receiptFile, receiptBytes);
      const receipt = { file: path.basename(receiptFile),
        sha256: renderOptions.receiptBindingTamper ? '0'.repeat(64) :
          digest(receiptBytes), bytes: receiptBytes.length };
      stdout = Buffer.from(JSON.stringify({
        event: 'autoeditor-engine-render-capability-self-test',
        schema_version: receiptValue.schema_version,
        checks, errors: {}, result: {
          scope: receiptValue.scope, fixture: receiptValue.fixture,
          runtime: receiptValue.runtime, production: receiptValue.production,
          artifact: receiptValue.artifact, evidence: receiptValue.evidence,
          receipt,
        },
      }) + '\n', 'utf8');
    } else if (command.endsWith('engine.exe') &&
        args[0] === '--dialogue-cleanup-capability-self-test') {
      const receiptFile = args[1];
      const expectedTake = 'and so my fellow americans';
      const identity = (digit, bytes) => ({ sha256: digit.repeat(64), bytes });
      const media = (digit, frames, durationMs, driftMs) => ({
        ...identity(digit, 100000),
        video: { codec: 'h264', width: 320, height: 180,
          pixel_format: 'yuv420p', fps: 30, frames, duration_ms: durationMs },
        audio: { codec: 'aac', sample_rate: 48000, channels: 2,
          duration_ms: durationMs - driftMs },
        av_duration_drift_ms: driftMs,
      });
      const checks = Object.fromEntries([
        'artifact_identity', 'expected_single_take_after',
        'false_start_detector', 'fixture_identity',
        'frame_sample_accurate_av_cut', 'model_identity',
        'no_retake_residue', 'normalized_av_before_after',
        'offline_small_model', 'production_asr_before_after',
        'production_dialogue_pipeline', 'repeated_take_detected',
        'tool_identity', 'word_safe_kept_take_boundary',
      ].map((name) => [name, true]));
      const result = {
        schema_version: 'autoeditor-dialogue-cleanup-runtime-probe/v1',
        checks,
        scope: {
          certified: ['repeated_take_detection', 'false_start_detection',
            'frame_sample_accurate_av_cut', 'post_render_retake_residue_gate'],
          not_certified: ['cough_classification', 'dead_air_policy_quality',
            'garbled_speech_semantics', 'general_asr_accuracy'],
        },
        fixture: { name: 'openai-whisper-jfk-excerpt.m4a', bytes: 9743,
          sha256: 'b36ddd51100eca8b767f667e90d6d0200a943eb2e25c6c021609582a2dcf4c37',
          source_revision: 'openai/whisper@6e3be77e1a105e59086e3e21ff5f609fd6fa89a5:tests/jfk.flac',
          take_count: 2, pause_ms: 500,
          filter_graph_sha256: '6'.repeat(64),
          false_start_timeline_sha256: '7'.repeat(64) },
        runtime: { model: { name: 'faster-whisper-small',
          tree_sha256: asrOptions.modelTreeSha256 || 'a'.repeat(64),
          bytes: 486000000, files: 6 },
          tools: { ffmpeg: identity('8', 1000000),
            ffprobe: identity('9', 900000) } },
        production_functions: ['autoeditor.asr.create_model',
          'autoeditor.asr.transcribe', 'autoeditor.pipeline.detect_retakes',
          'autoeditor.pipeline.detect_false_starts',
          'autoeditor.pipeline.apply_cuts',
          'autoeditor.pipeline.verify_no_retakes'],
        detectors: { retake: { cuts: [{ start_ms: 30, end_ms: 2460,
          why: 'retake (5-word repeat)' }] }, false_start: { cuts: [{
          start_ms: 130, end_ms: 1200, why: 'false start (2-word prefix repeat)',
        }] } },
        transcripts: { before: { normalized_text: `${expectedTake} ${expectedTake}`,
          take_count: 2, word_count: 10, word_timing_sha256: 'b'.repeat(64) },
          after: { normalized_text: expectedTake, take_count: 1, word_count: 5,
            word_timing_sha256: 'c'.repeat(64) } },
        edit: { start_frame: 1, end_frame: 74, removed_frames: 73,
          removed_ms: 2433, kept_take_start_ms: 2560, cut_end_ms: 2460,
          gap_before_kept_take_ms: 100 },
        media: { source: media('d', 165, 5500, 0),
          edited: media('e', 92, 3067, 1) },
      };
      const receiptBytes = Buffer.from(stableJson(result) + '\n', 'ascii');
      fs.writeFileSync(receiptFile, receiptBytes);
      result.receipt = { file: path.basename(receiptFile),
        sha256: require('node:crypto').createHash('sha256')
          .update(receiptBytes).digest('hex'), bytes: receiptBytes.length };
      stdout = Buffer.from(JSON.stringify({
        event: 'autoeditor-engine-dialogue-cleanup-capability-self-test',
        schema_version: 'autoeditor-dialogue-cleanup-runtime-probe/v1',
        checks, errors: {},
        result: Object.fromEntries(Object.entries(result)
          .filter(([key]) => !['schema_version', 'checks'].includes(key))),
      }) + '\n', 'utf8');
    } else if (command.endsWith('engine.exe') &&
        args[0] === '--asr-capability-self-test') {
      const receiptFile = args[1];
      const receipt = {
        schema_version: 'autoeditor-asr-runtime-probe/v1',
        checks: {
          expected_transcript: true, fixture_identity: true,
          model_identity: true, offline_small_model: true,
          ordered_word_timestamps: true, production_asr: true,
        },
        fixture: {
          name: 'openai-whisper-jfk-excerpt.m4a', bytes: 9743,
          sha256: 'b36ddd51100eca8b767f667e90d6d0200a943eb2e25c6c021609582a2dcf4c37',
          source_revision: 'openai/whisper@6e3be77e1a105e59086e3e21ff5f609fd6fa89a5:tests/jfk.flac',
        },
        model: { name: 'faster-whisper-small',
          tree_sha256: asrOptions.modelTreeSha256 || 'a'.repeat(64),
          bytes: 486000000, files: 6 },
        transcript: { language: 'en', text: 'And so, my fellow Americans.',
          normalized_text: 'and so my fellow americans' },
        words: [
          { text: 'my', start_ms: 900, end_ms: 1100,
            probability_millionths: 990000 },
          { text: 'fellow', start_ms: 1100, end_ms: 1500,
            probability_millionths: 990000 },
          { text: 'Americans', start_ms: 1500, end_ms: 2050,
            probability_millionths: 990000 },
        ],
      };
      const receiptBytes = Buffer.from(stableJson(receipt) + '\n', 'ascii');
      fs.writeFileSync(receiptFile, receiptBytes);
      const receiptSha256 = require('node:crypto').createHash('sha256')
        .update(receiptBytes).digest('hex');
      stdout = Buffer.from(JSON.stringify({
        event: 'autoeditor-engine-asr-capability-self-test',
        schema_version: receipt.schema_version,
        checks: receipt.checks,
        errors: {},
        result: {
          fixture: receipt.fixture, model: receipt.model,
          transcript: receipt.transcript, words: receipt.words,
          receipt: { file: path.basename(receiptFile),
            sha256: receiptSha256, bytes: receiptBytes.length },
        },
      }) + '\n', 'utf8');
    } else if (command.endsWith('engine.exe') &&
        args[0] === '--caption-render-self-test') {
      const rendered = args[2];
      const session = args[3];
      const font = path.join(options.env.AUTOEDITOR_BUNDLED_FONTS,
        'WorkSans-Variable.ttf');
      const outputBytes = Buffer.from('fixed caption rendered video bytes');
      fs.writeFileSync(rendered, outputBytes);
      const receipt = {
        schema: 'autoeditor-caption-render-receipt/v1',
        timeline: 'post_cut_seconds', delivery_mode: 'burned',
        renderer: 'karaoke-band',
        events: [{ index: 1, start_seconds: 0.35, end_seconds: 1.25,
          text: captionOptions.receiptTamper ? 'CUT IT LATER' :
            'CUT IT NOW', state_count: 3 }],
        mechanical_qa: {
          layout_safe: true, subject_clear: true,
          pixel_quality: { ok: true, states_checked: 1,
            minimum_solid_fill_ratio: 0.5,
            minimum_contrast_ratio: 8.0, note: '' },
        },
      };
      const receiptBytes = Buffer.from(JSON.stringify(receipt), 'utf8');
      const receiptFile = path.join(session, 'CAPTION_RENDER_RECEIPT.json');
      fs.writeFileSync(receiptFile, receiptBytes);
      const digest = (bytes) => require('node:crypto').createHash('sha256')
        .update(bytes).digest('hex');
      const fontBytes = fs.readFileSync(font);
      const pixelMode = captionOptions.pixelMode || 'valid';
      stdout = Buffer.from(JSON.stringify({
        event: 'autoeditor-engine-caption-render-self-test',
        schema_version: 'autoeditor-engine-caption-render-self-test/v1',
        checks: { bundled_worksans: true, production_caption_band: true,
          production_caption_receipt: true,
          burned_timed_pixel_evidence: true },
        errors: {},
        result: {
          artifact: { file: path.basename(rendered), sha256: digest(outputBytes),
            bytes: outputBytes.length, duration_ms: 2000,
            width: 180, height: 320, fps_milli: 30000 },
          caption_receipt: { file: path.basename(receiptFile),
            sha256: captionOptions.receiptBindingTamper ? '0'.repeat(64) :
              digest(receiptBytes), bytes: receiptBytes.length },
          font: { file: path.basename(font), sha256: digest(fontBytes),
            bytes: fontBytes.length },
          overlay: { caption_y: 26, band_height: 61,
            pixel_evidence: captionPixelEvidence(pixelMode) },
        },
      }) + '\n', 'utf8');
    } else if (command.endsWith('engine.exe')) {
      const pending = args[1];
      const approved = args[2];
      const session = args[3];
      const bytes = fs.readFileSync(pending);
      const digest = require('node:crypto').createHash('sha256')
        .update(bytes).digest('hex');
      const binding = (file) => {
        const raw = fs.readFileSync(path.join(session, file));
        return {
          file, bytes: raw.length,
          sha256: require('node:crypto').createHash('sha256')
            .update(raw).digest('hex'),
        };
      };
      fs.writeFileSync(path.join(session, 'EDIT_BOUNDARIES.json'),
        JSON.stringify({
          schema: 'autoeditor-edit-boundaries/v1',
          timeline: 'post_cut_seconds', cuts: [], transitions: [],
          transition_support: 'not_implemented',
        }));
      fs.writeFileSync(path.join(session, 'AUDIO_MIX_RECEIPT.json'),
        JSON.stringify({ schema: 'autoeditor-audio-mix-receipt/v1' }));
      fs.writeFileSync(path.join(session, 'QA_REPORT.json'), JSON.stringify({
        schema: 'autoeditor-engine-qa/v2', pass: true,
        checks: {
          artifact_receipt_fixture: { ok: true },
          audio_mix_receipt: { ok: true },
        },
        artifact_contract: {
          schema: 'autoeditor-engine-artifact-contract/v2',
          mode: 'generic-baseline',
          delivery: { file: path.basename(approved), bytes: bytes.length,
            sha256: digest },
          edl: null, captions: null, caption_render: null,
          edit_boundaries: binding('EDIT_BOUNDARIES.json'),
          audio_mix: binding('AUDIO_MIX_RECEIPT.json'), sequence: null,
        },
        release: { fixture: { file: approved, bytes: bytes.length,
          sha256: digest } },
      }));
      stdout = Buffer.from(JSON.stringify({
        event: 'autoeditor-engine-artifact-receipt-self-test',
        checks: { production_artifact_receipts: true,
          artifact_identity: true }, errors: {},
      }) + '\n');
    } else if (command.endsWith('daemon.exe')) {
      stdout = Buffer.from(JSON.stringify({
        event: 'helper-creative-smoke', checks: creative,
      }) + '\n', 'utf8');
    } else if (command.endsWith('ffprobe.exe')) {
      const hard = path.basename(output) === 'hard-cuts.mp4';
      const caption = path.basename(output).startsWith('caption-');
      const sfx = path.basename(output).startsWith('sfx-');
      const music = path.basename(output).startsWith('music-');
      stdout = Buffer.from(JSON.stringify({
        streams: [{
          codec_type: 'video', width: caption ? 180 : 160,
          height: caption ? 320 : 90, pix_fmt: 'yuv420p',
          r_frame_rate: '30/1',
        }, ...((sfx || music) ? [{ codec_type: 'audio', sample_rate: '48000',
          channels: 2 }] : [])],
        format: { duration: caption ? '2.000000' :
          sfx ? '3.000000' : music ? '4.000000' :
            hard ? '0.800000' : '1.000000' },
      }), 'utf8');
    } else if (joined.includes('crop=180:61:0:26')) {
      const name = joined.includes('-ss 0.100') ? 'blank_before' :
        joined.includes('-ss 0.450') ? 'word_cut' :
          joined.includes('-ss 0.750') ? 'word_it' :
            joined.includes('-ss 1.050') ? 'word_now' : 'blank_after';
      stdout = captionFrame(name, captionOptions.pixelMode || 'valid');
    } else if (joined.includes('-f rawvideo -')) {
      stdout = Buffer.from(joined.includes('-ss 0.200')
        ? [240, 20, 20] : [20, 20, 240]);
    } else if (joined.includes('volumedetect')) {
      stderr = Buffer.from(
        '[Parsed_volumedetect] mean_volume: -17.2 dB\n' +
        '[Parsed_volumedetect] max_volume: -6.1 dB\n', 'utf8');
    } else if (joined.includes("select='gt(scene,0.2)',showinfo")) {
      stderr = Buffer.from('[Parsed_showinfo] n: 0 pts_time:0.400\n', 'utf8');
    } else if (joined.includes('print_format=json')) {
      stderr = Buffer.from(
        '[Parsed_loudnorm]\n{"input_i":"-14.10","input_tp":"-2.20"}\n',
        'utf8');
    } else if (output !== '-' && path.isAbsolute(output)) {
      fs.writeFileSync(output, Buffer.from(`fixture/${path.basename(output)}`));
    }
    return {
      code: command.endsWith('daemon.exe') ? creativeExitCode : 0,
      signal: '', stdout, stderr,
    };
  };
}

function checkContext(id) {
  const codeNames = [
    'artifact-contract', 'caption-font', 'capability-check-runner', 'capability-contract',
    'capability-policy-bridge', 'capability-preflight',
    'capability-producer', 'desktop-main', 'edit-policy', 'engine',
    'ffmpeg', 'ffprobe',
    'process-tree', 'project-intent',
    'sfx-production', 'music-production', 'asr-runtime-probe',
    'dialogue-cleanup-runtime-probe', 'render-capability-runtime-probe',
    'semantic-choice-contract', 'semantic-qualification-contract',
    'whisper-small-model',
  ];
  return {
    id,
    signal: new AbortController().signal,
    contractBytes: fixedCheckContractBytes(id),
    fixtureBytes: fixedCheckFixtureBytes(id),
    runtime: {
      executables: codeNames.map((name) => ({
        name, sha256: name === 'caption-font' ? TEST_FONT_SHA256 : 'a'.repeat(64),
      })),
    },
  };
}

(async () => {
  assert.deepEqual(FIXTURELESS_CHECKS, [
    'visual_quality_analysis',
  ]);

  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-cap-runner-test-'));
  try {
    const fontRoot = path.join(root, 'fonts');
    fs.mkdirSync(fontRoot);
    fs.writeFileSync(path.join(fontRoot, 'WorkSans-Variable.ttf'), TEST_FONT_BYTES);
    const calls = [];
    const runner = createRuntimeCapabilityCheckRunner({
      runtime: {
        daemon: path.join(root, 'daemon.exe'),
        engine: path.join(root, 'engine.exe'),
        ffmpeg: path.join(root, 'ffmpeg.exe'),
        ffprobe: path.join(root, 'ffprobe.exe'),
        fonts: fontRoot,
      },
      workRoot: path.join(root, 'work'),
      env: { AUTOEDITOR_CREATIVE_SMOKE_TEST: '1' },
      execute: fakeExecutor(calls),
      platform: 'win32',
    });
    const results = [];
    for (const id of CAPABILITY_CHECK_IDS) {
      results.push([id, await runner(checkContext(id))]);
    }
    for (const [id, result] of results) {
      const shouldPass = !FIXTURELESS_CHECKS.includes(id);
      assert.equal(result.status, shouldPass ? 'pass' : 'fail', id);
      assert.ok(result.measurements.length > 0, id);
      assert.deepEqual(result.measurements.map(({ name }) => name),
        [...result.measurements.map(({ name }) => name)].sort(), id);
      assert.equal(result.evidence.length, 1, id);
      assert.ok(Buffer.isBuffer(result.evidence[0].bytes), id);
      const rawEvidence = result.evidence[0].bytes.toString('utf8');
      assert.ok(!rawEvidence.includes(root), id);
      assert.ok(!/api.?key|secret|token/i.test(rawEvidence), id);
    }
    assert.equal(calls.filter(({ command }) => command.endsWith('daemon.exe')).length, 1,
      'chart and graphic checks must share one concrete creative smoke execution');
    const renderCalls = calls.filter(({ command, args }) =>
      command.endsWith('engine.exe') &&
      args[0] === '--render-capability-self-test');
    assert.equal(renderCalls.length, 1,
      'the four render checks must share one concrete engine proof');
    assert.equal(renderCalls[0].args.length, 3,
      'the engine proof CLI is exactly output receipt plus isolated workdir');
    assert.equal(calls.filter(({ command, args }) =>
      command.endsWith('ffmpeg.exe') &&
      args.join(' ').includes('concat=n=2:v=1:a=0')).length, 1,
      'hard_cuts must retain its independent decoded fixture');
    runner.dispose();
    assert.deepEqual(fs.readdirSync(path.join(root, 'work')), []);

    const failedCreative = createRuntimeCapabilityCheckRunner({
      runtime: {
        daemon: path.join(root, 'daemon.exe'),
        engine: path.join(root, 'engine.exe'),
        ffmpeg: path.join(root, 'ffmpeg.exe'),
        ffprobe: path.join(root, 'ffprobe.exe'),
        fonts: fontRoot,
      },
      workRoot: path.join(root, 'work'),
      env: {},
      execute: fakeExecutor([], {
        hyperframes_render: true, remotion_render: false,
      }, 1),
      platform: 'win32',
    });
    assert.equal((await failedCreative(checkContext('chart_rendering'))).status, 'fail');
    assert.equal((await failedCreative(checkContext('graphic_rendering'))).status, 'pass');
    failedCreative.dispose();

    const contractCalls = [];
    const contractRunner = createRuntimeCapabilityCheckRunner({
      runtime: {
        daemon: path.join(root, 'daemon.exe'),
        engine: path.join(root, 'engine.exe'),
        ffmpeg: path.join(root, 'ffmpeg.exe'),
        ffprobe: path.join(root, 'ffprobe.exe'),
        fonts: fontRoot,
      },
      workRoot: path.join(root, 'work'), env: {}, execute: fakeExecutor(contractCalls),
      platform: 'win32',
    });
    const mutated = checkContext('hard_cuts');
    mutated.fixtureBytes[0] ^= 0xff;
    await assert.rejects(() => contractRunner(mutated),
      /contract or fixture binding is invalid/);
    const unbound = checkContext('hard_cuts');
    unbound.runtime.executables = [{ name: 'ffmpeg', sha256: 'a'.repeat(64) }];
    await assert.rejects(() => contractRunner(unbound),
      /code is absent from the runtime identity/);
    const captionUnbound = checkContext('caption_rendering');
    captionUnbound.runtime.executables = captionUnbound.runtime.executables
      .filter(({ name }) => name !== 'caption-font');
    await assert.rejects(() => contractRunner(captionUnbound),
      /caption font is absent from the runtime identity/);
    const asrUnbound = checkContext('speech_transcription');
    asrUnbound.runtime.executables = [
      { name: 'desktop-app-asar', sha256: 'a'.repeat(64) },
    ];
    const callCountBeforeUnboundAsr = calls.length;
    await assert.rejects(() => contractRunner(asrUnbound),
      /small ASR model is absent from the runtime identity/);
    assert.equal(calls.length, callCountBeforeUnboundAsr,
      'an unbound model must be rejected before the engine can execute');
    const renderUnbound = checkContext('color_normalization');
    renderUnbound.runtime.executables = renderUnbound.runtime.executables
      .filter(({ name }) => name !== 'ffprobe');
    const callCountBeforeUnboundRender = contractCalls.length;
    await assert.rejects(() => contractRunner(renderUnbound),
      /render capability runtime tools are absent from the runtime identity/);
    assert.equal(contractCalls.length, callCountBeforeUnboundRender,
      'unbound render tools must be rejected before the engine can execute');
    contractRunner.dispose();

    const mismatchedAsr = createRuntimeCapabilityCheckRunner({
      runtime: {
        daemon: path.join(root, 'daemon.exe'),
        engine: path.join(root, 'engine.exe'),
        ffmpeg: path.join(root, 'ffmpeg.exe'),
        ffprobe: path.join(root, 'ffprobe.exe'),
        fonts: fontRoot,
      },
      workRoot: path.join(root, 'work'), env: {},
      execute: fakeExecutor([], undefined, 0, {}, {
        modelTreeSha256: 'b'.repeat(64),
      }),
      platform: 'win32',
    });
    await assert.rejects(
      () => mismatchedAsr(checkContext('speech_transcription')),
      /ASR capability bindings were invalid/,
      'the engine-probed model tree must exactly equal the current runtime tree',
    );
    mismatchedAsr.dispose();

    async function rejectsRender(renderOptions, pattern) {
      const negative = createRuntimeCapabilityCheckRunner({
        runtime: {
          daemon: path.join(root, 'daemon.exe'),
          engine: path.join(root, 'engine.exe'),
          ffmpeg: path.join(root, 'ffmpeg.exe'),
          ffprobe: path.join(root, 'ffprobe.exe'),
          fonts: fontRoot,
        },
        workRoot: path.join(root, 'work'), env: {},
        execute: fakeExecutor([], undefined, 0, {}, {}, {}, renderOptions),
        platform: 'win32',
      });
      try {
        await assert.rejects(
          () => negative(checkContext('color_normalization')), pattern);
      } finally {
        negative.dispose();
      }
    }

    await rejectsRender({ runtimeHashTamper: true },
      /engine render capability host was invalid/);
    await rejectsRender({ receiptBindingTamper: true },
      /receipt file did not match its binding/);
    await rejectsRender({ receiptContentTamper: true },
      /receipt was not exact canonical evidence/);
    await rejectsRender({ badBlend: true },
      /transition evidence was invalid/);
    await rejectsRender({ failedCheck: 'motion_quality_analysis' },
      /did not attest every check/);

    async function rejectsCaption(captionOptions, pattern) {
      const negative = createRuntimeCapabilityCheckRunner({
        runtime: {
          daemon: path.join(root, 'daemon.exe'),
          engine: path.join(root, 'engine.exe'),
          ffmpeg: path.join(root, 'ffmpeg.exe'),
          ffprobe: path.join(root, 'ffprobe.exe'),
          fonts: fontRoot,
        },
        workRoot: path.join(root, 'work'), env: {},
        execute: fakeExecutor([], undefined, 0, captionOptions),
        platform: 'win32',
      });
      try {
        await assert.rejects(
          () => negative(checkContext('caption_rendering')), pattern);
      } finally {
        negative.dispose();
      }
    }

    await rejectsCaption({ receiptTamper: true },
      /caption render event was invalid/);
    await rejectsCaption({ receiptBindingTamper: true },
      /artifact or receipt binding drifted/);
    await rejectsCaption({ pixelMode: 'overlay-omitted' },
      /did not prove its fixed timed overlay/);
    await rejectsCaption({ pixelMode: 'blank-band' },
      /did not prove its fixed timed overlay/);

    const missingFontRoot = path.join(root, 'missing-fonts');
    fs.mkdirSync(missingFontRoot);
    const missingFont = createRuntimeCapabilityCheckRunner({
      runtime: {
        daemon: path.join(root, 'daemon.exe'),
        engine: path.join(root, 'engine.exe'),
        ffmpeg: path.join(root, 'ffmpeg.exe'),
        ffprobe: path.join(root, 'ffprobe.exe'),
        fonts: missingFontRoot,
      },
      workRoot: path.join(root, 'work'), env: {}, execute: fakeExecutor([]),
      platform: 'win32',
    });
    await assert.rejects(
      () => missingFont(checkContext('caption_rendering')),
      /bundled caption font was invalid/);
    missingFont.dispose();

    const longestBounded = await runBoundedCommand(process.execPath, [
      '-e', 'process.stdout.write("bounded")',
    ], { timeoutMs: MUSIC_PRODUCTION_TIMEOUT_MS });
    assert.equal(longestBounded.code, 0);
    assert.equal(longestBounded.stdout.toString('utf8'), 'bounded');
    await assert.rejects(() => runBoundedCommand(process.execPath, [
      '-e', 'process.exit(0)',
    ], { timeoutMs: MUSIC_PRODUCTION_TIMEOUT_MS + 1 }),
    /capability command timeout is invalid/);

    const timeoutStart = Date.now();
    await assert.rejects(() => runBoundedCommand(process.execPath, [
      '-e', 'setInterval(() => {}, 1000)',
    ], { timeoutMs: 40 }), RuntimeCapabilityCheckRunnerError);
    assert.ok(Date.now() - timeoutStart < 2000, 'command timeout must be bounded');

    const controller = new AbortController();
    const canceled = runBoundedCommand(process.execPath, [
      '-e', 'setInterval(() => {}, 1000)',
    ], { timeoutMs: 2000, signal: controller.signal });
    controller.abort();
    await assert.rejects(() => canceled, RuntimeCapabilityCheckRunnerError);

    let releaseTermination;
    const terminationFinished = new Promise((resolve) => {
      releaseTermination = resolve;
    });
    let terminationCalls = 0;
    const heldChild = new EventEmitter();
    heldChild.pid = 4321;
    heldChild.stdout = new EventEmitter();
    heldChild.stderr = new EventEmitter();
    const heldController = new AbortController();
    const heldCancellation = runBoundedCommand('held-command.exe', [], {
      timeoutMs: 2000,
      signal: heldController.signal,
      platform: 'win32',
      spawnImpl: () => heldChild,
      stopProcessTreeImpl: () => {
        terminationCalls += 1;
        return terminationFinished;
      },
    });
    heldController.abort();
    heldChild.emit('close', 1, null);
    let heldSettled = false;
    heldCancellation.catch(() => { heldSettled = true; });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(heldSettled, false,
      'abort must remain pending until process-tree termination finishes');
    assert.equal(terminationCalls, 1,
      'abort and child close must share one process-tree termination');
    releaseTermination();
    await assert.rejects(
      () => heldCancellation,
      (error) => error instanceof RuntimeCapabilityCheckRunnerError &&
        error.message === 'capability command was canceled',
    );

    let releaseTimeoutTermination;
    const timeoutTerminationFinished = new Promise((resolve) => {
      releaseTimeoutTermination = resolve;
    });
    const timeoutChild = new EventEmitter();
    timeoutChild.pid = 4322;
    timeoutChild.stdout = new EventEmitter();
    timeoutChild.stderr = new EventEmitter();
    const heldTimeout = runBoundedCommand('held-timeout.exe', [], {
      timeoutMs: 20,
      platform: 'win32',
      spawnImpl: () => timeoutChild,
      stopProcessTreeImpl: () => timeoutTerminationFinished,
    });
    await new Promise((resolve) => setTimeout(resolve, 35));
    let timeoutSettled = false;
    heldTimeout.catch(() => { timeoutSettled = true; });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(timeoutSettled, false,
      'timeout must remain pending until process-tree termination finishes');
    releaseTimeoutTermination();
    await assert.rejects(
      () => heldTimeout,
      (error) => error instanceof RuntimeCapabilityCheckRunnerError &&
        error.message === 'capability command timed out',
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }

  console.log('runtime capability fixed check runner tests passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
