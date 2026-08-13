'use strict';

// Fixed, local-only capability checks for the Electron trust boundary. A
// successful check must execute a concrete fixture and return evidence bytes;
// checks without a defensible fixture fail instead of inheriting availability
// from a file-presence inventory, an API key, or a model claim.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { stopProcessTree } = require('../../lib/process-tree');
const { CAPABILITY_CHECK_IDS } = require('./runtime-capabilities');
const {
  readArtifactQaReport,
  readContractJsonSidecar,
} = require('./artifact-contract');

const CHECK_RUNNER_SCHEMA_VERSION =
  'autoeditor-runtime-capability-fixed-check-runner/v1';
const MAX_CAPTURE_BYTES = 2 * 1024 * 1024;
const COMMAND_TIMEOUT_MS = 9_000;
const CREATIVE_TIMEOUT_MS = 25_000;
const CAPTION_RENDER_TIMEOUT_MS = 45_000;
const SFX_PRODUCTION_TIMEOUT_MS = 60_000;
const MUSIC_PRODUCTION_TIMEOUT_MS = 90_000;
const CAPTION_RECEIPT_SCHEMA = 'autoeditor-caption-render-receipt/v1';
const CAPTION_ENGINE_SCHEMA =
  'autoeditor-engine-caption-render-self-test/v1';
const SFX_ENGINE_SCHEMA =
  'autoeditor-sfx-production-self-test/v1';
const MUSIC_ENGINE_EVENT =
  'autoeditor-engine-music-production-self-test';
const MUSIC_ENGINE_SCHEMA =
  'autoeditor-music-production-self-test/v1';
const ASR_ENGINE_EVENT = 'autoeditor-engine-asr-capability-self-test';
const ASR_ENGINE_SCHEMA = 'autoeditor-asr-runtime-probe/v1';
const DIALOGUE_ENGINE_EVENT =
  'autoeditor-engine-dialogue-cleanup-capability-self-test';
const DIALOGUE_ENGINE_SCHEMA =
  'autoeditor-dialogue-cleanup-runtime-probe/v1';
const RENDER_ENGINE_EVENT =
  'autoeditor-engine-render-capability-self-test';
const RENDER_ENGINE_SCHEMA =
  'autoeditor-render-capability-runtime-probe/v1';
const CAPTION_WIDTH = 180;
const CAPTION_HEIGHT = 320;
const CAPTION_FPS_MILLI = 30_000;
const CAPTION_DURATION_MS = 2_000;
const CAPTION_BAND_HEIGHT = 61;
const CAPTION_Y = 26;
const CHECK_ID_SET = new Set(CAPABILITY_CHECK_IDS);
const TRUSTED_CODE_FILE_NAMES = new Set([
  'artifact-contract',
  'asr-runtime-probe',
  'caption-font',
  'capability-check-runner',
  'capability-contract',
  'capability-policy-bridge',
  'capability-preflight',
  'capability-producer',
  'desktop-main',
  'desktop-app-asar',
  'dialogue-cleanup-runtime-probe',
  'edit-policy',
  'engine',
  'ffmpeg',
  'ffprobe',
  'music-production',
  'process-tree',
  'project-intent',
  'render-capability-runtime-probe',
  'semantic-choice-contract',
  'semantic-qualification-contract',
  'sfx-production',
  'whisper-small-model',
]);
const REQUIRED_DEVELOPMENT_CODE_FILES = Object.freeze([
  'artifact-contract',
  'asr-runtime-probe',
  'capability-check-runner',
  'capability-contract',
  'capability-policy-bridge',
  'capability-preflight',
  'capability-producer',
  'desktop-main',
  'dialogue-cleanup-runtime-probe',
  'edit-policy',
  'music-production',
  'process-tree',
  'project-intent',
  'render-capability-runtime-probe',
  'semantic-choice-contract',
  'semantic-qualification-contract',
  'sfx-production',
  'whisper-small-model',
]);
const FIXTURELESS_CHECKS = new Set([
  'visual_quality_analysis',
]);

class RuntimeCapabilityCheckRunnerError extends Error {
  constructor(message) {
    super(message);
    this.name = 'RuntimeCapabilityCheckRunnerError';
  }
}

function fail(message) {
  throw new RuntimeCapabilityCheckRunnerError(message);
}

function sha256Bytes(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function stableJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  return `{${Object.keys(value).sort().map((key) => (
    `${JSON.stringify(key)}:${stableJson(value[key])}`
  )).join(',')}}`;
}

function evidence(id, facts) {
  return [{
    name: 'local_execution_receipt',
    bytes: Buffer.from(stableJson({
      schema_version: CHECK_RUNNER_SCHEMA_VERSION,
      check_id: id,
      ...facts,
    }), 'utf8'),
  }];
}

function measurements(entries) {
  return entries.map(([name, unit, value]) => ({ name, unit, value }))
    .sort((left, right) => left.name < right.name ? -1 : 1);
}

function boundedBuffer(buffer, chunk) {
  const remaining = MAX_CAPTURE_BYTES - buffer.length;
  if (remaining <= 0) return buffer;
  return Buffer.concat([buffer, Buffer.from(chunk).subarray(0, remaining)]);
}

function runBoundedCommand(command, args, {
  cwd,
  env,
  signal,
  timeoutMs = COMMAND_TIMEOUT_MS,
  spawnImpl = spawn,
  platform = process.platform,
  stopProcessTreeImpl = stopProcessTree,
} = {}) {
  if (typeof command !== 'string' || !command || command.includes('\0')) {
    return Promise.reject(new RuntimeCapabilityCheckRunnerError(
      'capability command is invalid'));
  }
  if (!Array.isArray(args) || args.some((item) =>
    typeof item !== 'string' || item.includes('\0'))) {
    return Promise.reject(new RuntimeCapabilityCheckRunnerError(
      'capability command arguments are invalid'));
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 ||
      timeoutMs > MUSIC_PRODUCTION_TIMEOUT_MS) {
    return Promise.reject(new RuntimeCapabilityCheckRunnerError(
      'capability command timeout is invalid'));
  }
  if (signal?.aborted) {
    return Promise.reject(new RuntimeCapabilityCheckRunnerError(
      'capability command was canceled'));
  }
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawnImpl(command, args, {
        cwd,
        env,
        windowsHide: true,
        detached: platform !== 'win32',
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (_) {
      reject(new RuntimeCapabilityCheckRunnerError(
        'capability command could not start'));
      return;
    }
    child.__autoeditorProcessGroup = platform !== 'win32';
    let stdout = Buffer.alloc(0);
    let stderr = Buffer.alloc(0);
    let settled = false;
    let terminating = false;
    let stopPromise = null;
    const stop = () => {
      if (!stopPromise) {
        try {
          stopPromise = Promise.resolve(
            stopProcessTreeImpl(child, platform)).catch(() => {});
        } catch (_) {
          stopPromise = Promise.resolve();
        }
      }
      return stopPromise;
    };
    const finish = (callback) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      callback();
    };
    const onAbort = () => {
      if (settled || terminating) return;
      terminating = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      void stop().then(() => finish(() => reject(
        new RuntimeCapabilityCheckRunnerError(
          'capability command was canceled'))));
    };
    const timer = setTimeout(() => {
      if (settled || terminating) return;
      terminating = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      void stop().then(() => finish(() => reject(
        new RuntimeCapabilityCheckRunnerError(
          'capability command timed out'))));
    }, timeoutMs);
    signal?.addEventListener('abort', onAbort, { once: true });
    child.stdout?.on('data', (chunk) => {
      stdout = boundedBuffer(stdout, chunk);
    });
    child.stderr?.on('data', (chunk) => {
      stderr = boundedBuffer(stderr, chunk);
    });
    child.once('error', () => {
      if (!terminating) finish(() => reject(
        new RuntimeCapabilityCheckRunnerError(
          'capability command could not start')));
    });
    child.once('close', (code, closeSignal) => {
      if (!terminating) finish(() => resolve({
        code: Number.isSafeInteger(code) ? code : null,
        signal: typeof closeSignal === 'string' ? closeSignal : '',
        stdout,
        stderr,
      }));
    });
  });
}

function parseJsonObject(buffer, label) {
  try {
    const parsed = JSON.parse(Buffer.from(buffer).toString('utf8'));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('not an object');
    }
    return parsed;
  } catch (_) {
    throw new RuntimeCapabilityCheckRunnerError(`${label} was invalid`);
  }
}

function typedJsonEvent(buffer, eventName, label) {
  const matches = Buffer.from(buffer).toString('utf8')
    .split(/\r?\n/).filter(Boolean).map((line) => {
      try { return JSON.parse(line); } catch (_) { return null; }
    }).filter((value) => value?.event === eventName);
  if (matches.length !== 1 || !matches[0] || Array.isArray(matches[0])) {
    fail(`${label} was invalid`);
  }
  return matches[0];
}

function plainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null);
}

function exactKeys(value, keys, label) {
  if (!plainObject(value) || Object.keys(value).sort().join('\0') !==
      [...keys].sort().join('\0')) fail(`${label} was invalid`);
  return value;
}

function lowercaseSha256(value) {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
}

function stableBoundedFile(file, root, label, maxBytes = 256 * 1024) {
  let real;
  let before;
  try {
    const rootReal = fs.realpathSync.native(root);
    real = fs.realpathSync.native(file);
    const relative = path.relative(rootReal, real);
    if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) ||
        path.isAbsolute(relative)) throw new Error('outside root');
    before = fs.statSync(real);
    if (!before.isFile() || before.size < 1 || before.size > maxBytes) {
      throw new Error('invalid size');
    }
    const bytes = fs.readFileSync(real);
    const after = fs.statSync(real);
    if (bytes.length !== before.size || before.size !== after.size ||
        before.mtimeMs !== after.mtimeMs || before.dev !== after.dev ||
        before.ino !== after.ino) throw new Error('changed');
    return { bytes, sha256: sha256Bytes(bytes), size: bytes.length, real };
  } catch (_) {
    fail(`${label} was invalid`);
  }
}

function captionFrameDelta(left, right) {
  if (!Buffer.isBuffer(left) || !Buffer.isBuffer(right) || !left.length ||
      left.length !== right.length || left.length % 3 !== 0) {
    fail('caption pixel frame pair was invalid');
  }
  let changedPixels = 0;
  let absoluteError = 0;
  for (let offset = 0; offset < left.length; offset += 3) {
    let maximum = 0;
    for (let channel = 0; channel < 3; channel += 1) {
      const difference = Math.abs(left[offset + channel] - right[offset + channel]);
      maximum = Math.max(maximum, difference);
      absoluteError += difference;
    }
    if (maximum > 12) changedPixels += 1;
  }
  return {
    changed_pixel_ratio: Number((changedPixels / (left.length / 3)).toFixed(6)),
    mean_absolute_error: Number((absoluteError / left.length).toFixed(3)),
  };
}

function validateCaptionRenderReceipt(value) {
  exactKeys(value, [
    'schema', 'timeline', 'delivery_mode', 'renderer', 'events',
    'mechanical_qa',
  ], 'caption render receipt');
  if (value.schema !== CAPTION_RECEIPT_SCHEMA ||
      value.timeline !== 'post_cut_seconds' ||
      value.delivery_mode !== 'burned' || value.renderer !== 'karaoke-band' ||
      !Array.isArray(value.events) || value.events.length !== 1) {
    fail('caption render receipt was invalid');
  }
  const event = exactKeys(value.events[0], [
    'index', 'start_seconds', 'end_seconds', 'text', 'state_count',
  ], 'caption render event');
  if (event.index !== 1 || event.start_seconds !== 0.35 ||
      event.end_seconds !== 1.25 || event.text !== 'CUT IT NOW' ||
      event.state_count !== 3) fail('caption render event was invalid');
  const mechanical = exactKeys(value.mechanical_qa, [
    'layout_safe', 'subject_clear', 'pixel_quality',
  ], 'caption mechanical QA');
  const quality = exactKeys(mechanical.pixel_quality, [
    'ok', 'states_checked', 'minimum_solid_fill_ratio',
    'minimum_contrast_ratio', 'note',
  ], 'caption pixel QA');
  if (mechanical.layout_safe !== true || mechanical.subject_clear !== true ||
      quality.ok !== true || quality.states_checked !== 1 || quality.note !== '' ||
      !Number.isFinite(quality.minimum_solid_fill_ratio) ||
      quality.minimum_solid_fill_ratio < 0.42 ||
      !Number.isFinite(quality.minimum_contrast_ratio) ||
      quality.minimum_contrast_ratio < 7.0) {
    fail('caption mechanical QA was invalid');
  }
  return value;
}

function boundedInteger(value, minimum, maximum, label) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`${label} was invalid`);
  }
  return value;
}

function renderRuntimeIdentity(value, label, expectedFile, expectedSha256) {
  const identity = exactKeys(value, [
    'bytes', 'file', 'sha256',
  ], label);
  if (identity.file !== expectedFile || identity.sha256 !== expectedSha256 ||
      !lowercaseSha256(identity.sha256) ||
      !Number.isSafeInteger(identity.bytes) || identity.bytes < 1) {
    fail(`${label} was invalid`);
  }
  return identity;
}

function renderFrameEvidence(value, expectedFrame, label) {
  const frame = exactKeys(value, [
    'black_pixel_ratio_millionths', 'frame_index', 'mean_luma_millionths',
    'mean_rgb', 'sha256',
  ], label);
  if (frame.frame_index !== expectedFrame || !lowercaseSha256(frame.sha256) ||
      !Array.isArray(frame.mean_rgb) || frame.mean_rgb.length !== 3 ||
      frame.mean_rgb.some((item) => !Number.isSafeInteger(item) ||
        item < 0 || item > 1000000) ||
      !Number.isSafeInteger(frame.mean_luma_millionths) ||
      frame.mean_luma_millionths < 80000 ||
      frame.mean_luma_millionths > 1000000 ||
      !Number.isSafeInteger(frame.black_pixel_ratio_millionths) ||
      frame.black_pixel_ratio_millionths < 0 ||
      frame.black_pixel_ratio_millionths > 100000) {
    fail(`${label} was invalid`);
  }
  return frame;
}

function renderAudioWindow(value, expectedStart, label) {
  const window = exactKeys(value, [
    'duration_ms', 'rms_millionths', 'start_ms',
    'tone_440_millionths', 'tone_880_millionths',
  ], label);
  if (window.start_ms !== expectedStart || window.duration_ms !== 100) {
    fail(`${label} was invalid`);
  }
  for (const name of [
    'rms_millionths', 'tone_440_millionths', 'tone_880_millionths',
  ]) boundedInteger(window[name], 0, 1000000, `${label} ${name}`);
  return window;
}

function validateRenderCapabilityResult(result, bindings) {
  const normalized = exactKeys(result, [
    'artifact', 'evidence', 'fixture', 'production', 'receipt', 'runtime',
    'scope',
  ], 'engine render capability result');
  const scope = exactKeys(normalized.scope, [
    'audio', 'color', 'motion', 'transition', 'unsupported',
  ], 'engine render capability scope');
  if (scope.audio !==
        'fixed-440hz-to-880hz-qsin-overlap-48000hz-stereo' ||
      scope.color !== 'declared-bt470bg-tv-sdr-to-bt709-tv-yuv420p' ||
      scope.motion !==
        'fixed-decoded-frame-blend-progression-and-no-black-flash' ||
      scope.transition !== 'single-400ms-xfade-fade-at-30000-1001fps' ||
      stableJson(scope.unsupported) !== stableJson([
        'hdr', 'optical_flow', 'arbitrary_transition_quality',
      ])) {
    fail('engine render capability scope was invalid');
  }

  const fixture = exactKeys(normalized.fixture, [
    'audio', 'frame_rate', 'geometry', 'schema_version', 'sha256',
    'source_selection_ms', 'sources', 'transition_duration_ms',
  ], 'engine render capability fixture');
  const frameRate = exactKeys(fixture.frame_rate, [
    'denominator', 'numerator',
  ], 'engine render capability fixture frame rate');
  const geometry = exactKeys(fixture.geometry, [
    'height', 'width',
  ], 'engine render capability fixture geometry');
  const audio = exactKeys(fixture.audio, [
    'channels', 'sample_rate', 'source_a_frequency_hz',
    'source_b_frequency_hz',
  ], 'engine render capability fixture audio');
  if (fixture.schema_version !== 'autoeditor-render-capability-fixture/v1' ||
      !lowercaseSha256(fixture.sha256) ||
      frameRate.numerator !== 30000 || frameRate.denominator !== 1001 ||
      geometry.width !== 160 || geometry.height !== 90 ||
      fixture.source_selection_ms !== 3000 ||
      fixture.transition_duration_ms !== 400 ||
      audio.sample_rate !== 48000 || audio.channels !== 2 ||
      audio.source_a_frequency_hz !== 440 ||
      audio.source_b_frequency_hz !== 880 ||
      !Array.isArray(fixture.sources) || fixture.sources.length !== 2) {
    fail('engine render capability fixture was invalid');
  }
  const sourceColors = [{
    codec_name: 'h264', pix_fmt: 'yuv420p', color_range: 'tv',
    color_space: 'bt470bg', color_transfer: 'bt470bg',
    color_primaries: 'bt470bg',
  }, {
    codec_name: 'h264', pix_fmt: 'yuv420p', color_range: 'tv',
    color_space: 'bt709', color_transfer: 'bt709',
    color_primaries: 'bt709',
  }];
  const sourceIds = ['source-a-bt470bg', 'source-b-bt709'];
  const sourceFiles = [
    'render-capability-bt470-source.mp4',
    'render-capability-bt709-source.mp4',
  ];
  for (let index = 0; index < 2; index += 1) {
    const source = exactKeys(fixture.sources[index], [
      'bytes', 'color', 'duration_ms', 'file', 'generator_filter_sha256',
      'id', 'sha256',
    ], `engine render capability fixture source ${index}`);
    if (source.id !== sourceIds[index] || source.file !== sourceFiles[index] ||
        stableJson(source.color) !== stableJson(sourceColors[index]) ||
        !lowercaseSha256(source.sha256) ||
        !lowercaseSha256(source.generator_filter_sha256) ||
        !Number.isSafeInteger(source.bytes) || source.bytes < 1 ||
        !Number.isSafeInteger(source.duration_ms) ||
        source.duration_ms < 3000 || source.duration_ms > 5000) {
      fail('engine render capability fixture source was invalid');
    }
  }
  const fixtureWithoutHash = { ...fixture };
  delete fixtureWithoutHash.sha256;
  if (sha256Bytes(Buffer.from(stableJson(fixtureWithoutHash), 'ascii')) !==
      fixture.sha256) {
    fail('engine render capability fixture hash was invalid');
  }

  const runtimeBinding = exactKeys(normalized.runtime, [
    'contract', 'ffmpeg', 'ffprobe', 'host',
  ], 'engine render capability runtime');
  const host = renderRuntimeIdentity(
    runtimeBinding.host, 'engine render capability host',
    path.basename(bindings.engine.path), bindings.engine.sha256);
  const ffmpeg = renderRuntimeIdentity(
    runtimeBinding.ffmpeg, 'engine render capability FFmpeg',
    path.basename(bindings.ffmpeg.path), bindings.ffmpeg.sha256);
  const ffprobe = renderRuntimeIdentity(
    runtimeBinding.ffprobe, 'engine render capability FFprobe',
    path.basename(bindings.ffprobe.path), bindings.ffprobe.sha256);
  const contract = exactKeys(runtimeBinding.contract, [
    'schemas', 'sha256',
  ], 'engine render capability runtime contract');
  const schemas = [
    'autoeditor-render-capability-runtime-probe/v1',
    'autoeditor-render-capability-fixture/v1',
    'autoeditor-sequence-plan/v1',
    'autoeditor-source-render-manifest/v4',
    'autoeditor-transition-plan/v1',
  ];
  if (stableJson(contract.schemas) !== stableJson(schemas) ||
      contract.sha256 !== sha256Bytes(
        Buffer.from(stableJson(schemas), 'ascii'))) {
    fail('engine render capability runtime contract was invalid');
  }

  const production = exactKeys(normalized.production, [
    'edit_policy_sha256', 'filter_complex_sha256',
    'sequence_compile_receipt_sha256', 'sequence_plan_sha256',
    'topology_sha256', 'transition_compile_receipt_sha256',
    'transition_plan_sha256', 'transition_render_receipt_sha256',
  ], 'engine render capability production');
  if (Object.values(production).some((value) => !lowercaseSha256(value))) {
    fail('engine render capability production hashes were invalid');
  }

  const artifact = exactKeys(normalized.artifact, [
    'audio', 'audio_duration_us', 'audio_sample_frames', 'av_drift_us',
    'bytes', 'delivery_color', 'expected_duration_ms', 'file', 'frame_rate',
    'height', 'sha256', 'video_duration_us', 'video_frames', 'width',
  ], 'engine render capability artifact');
  const artifactRate = exactKeys(artifact.frame_rate, [
    'denominator', 'numerator',
  ], 'engine render capability artifact frame rate');
  const artifactAudio = exactKeys(artifact.audio, [
    'channels', 'sample_rate',
  ], 'engine render capability artifact audio');
  const deliveryColor = exactKeys(artifact.delivery_color, [
    'pixel_format', 'primaries', 'range', 'space', 'transfer',
  ], 'engine render capability delivery color');
  if (artifact.file !== 'render-capability-artifact.mp4' ||
      !lowercaseSha256(artifact.sha256) ||
      !Number.isSafeInteger(artifact.bytes) || artifact.bytes < 1 ||
      artifact.expected_duration_ms !== 5600 ||
      artifact.width !== 160 || artifact.height !== 90 ||
      artifactRate.numerator !== 30000 || artifactRate.denominator !== 1001 ||
      artifactAudio.sample_rate !== 48000 || artifactAudio.channels !== 2 ||
      stableJson(deliveryColor) !== stableJson({
        range: 'tv', space: 'bt709', transfer: 'bt709', primaries: 'bt709',
        pixel_format: 'yuv420p',
      })) {
    fail('engine render capability artifact format was invalid');
  }
  boundedInteger(artifact.video_frames, 167, 169,
    'engine render capability artifact video frames');
  boundedInteger(artifact.audio_sample_frames, 268000, 270500,
    'engine render capability artifact audio frames');
  boundedInteger(artifact.video_duration_us, 5570000, 5634000,
    'engine render capability artifact video duration');
  boundedInteger(artifact.audio_duration_us, 5575000, 5625000,
    'engine render capability artifact audio duration');
  boundedInteger(artifact.av_drift_us, 0, 34000,
    'engine render capability artifact A/V drift');

  const proof = exactKeys(normalized.evidence, [
    'audio_crossfade', 'color', 'transition',
  ], 'engine render capability evidence');
  const color = exactKeys(proof.color, [
    'artifact_to_reference_mae_millionths', 'artifact_yuv_sha256',
    'conversion_filter_sha256', 'frame_index', 'normalization_mode',
    'normalized_reference_yuv_sha256', 'source_declaration',
    'source_to_normalized_mae_millionths', 'source_yuv_sha256',
  ], 'engine render capability color evidence');
  const expectedConversionHash =
    '82749ad88450b4ccef19498768a2ce4e0e2ea27a65bad290b90f7f525f3db037';
  if (stableJson(color.source_declaration) !== stableJson(sourceColors[0]) ||
      color.normalization_mode !== 'declared_sdr_to_bt709_tv' ||
      color.conversion_filter_sha256 !== expectedConversionHash ||
      color.frame_index !== 30 ||
      !lowercaseSha256(color.source_yuv_sha256) ||
      !lowercaseSha256(color.normalized_reference_yuv_sha256) ||
      !lowercaseSha256(color.artifact_yuv_sha256) ||
      color.source_yuv_sha256 === color.normalized_reference_yuv_sha256 ||
      !Number.isSafeInteger(color.source_to_normalized_mae_millionths) ||
      color.source_to_normalized_mae_millionths < 5000 ||
      !Number.isSafeInteger(color.artifact_to_reference_mae_millionths) ||
      color.artifact_to_reference_mae_millionths < 0 ||
      color.artifact_to_reference_mae_millionths > 35000) {
    fail('engine render capability color evidence was invalid');
  }

  const transition = exactKeys(proof.transition, [
    'after', 'before', 'blend_residuals_millionths', 'duration_frames',
    'duration_ms', 'estimated_right_weights_millionths', 'kind',
    'max_adjacent_rgb_mae_millionths', 'max_black_pixel_ratio_millionths',
    'middle', 'min_mean_luma_millionths', 'start_frame',
  ], 'engine render capability transition evidence');
  const beforeFrame = renderFrameEvidence(
    transition.before, 77, 'engine render capability before frame');
  const middleFrame = renderFrameEvidence(
    transition.middle, 84, 'engine render capability middle frame');
  const afterFrame = renderFrameEvidence(
    transition.after, 91, 'engine render capability after frame');
  const weights = transition.estimated_right_weights_millionths;
  const residuals = transition.blend_residuals_millionths;
  if (transition.kind !== 'cross_dissolve' || transition.duration_ms !== 400 ||
      transition.duration_frames !== 12 || transition.start_frame !== 78 ||
      !Array.isArray(weights) || weights.length !== 12 ||
      weights.some((item) => !Number.isSafeInteger(item) ||
        item < 0 || item > 1000000) ||
      weights[0] > 200000 || weights[11] < 700000 ||
      weights[6] < 300000 || weights[6] > 750000 ||
      weights.some((item, index) => index > 0 &&
        item + 70000 < weights[index - 1]) ||
      !Array.isArray(residuals) || residuals.length !== 12 ||
      residuals.some((item) => !Number.isSafeInteger(item) ||
        item < 0 || item > 75000) ||
      !Number.isSafeInteger(transition.max_adjacent_rgb_mae_millionths) ||
      transition.max_adjacent_rgb_mae_millionths < 1 ||
      transition.max_adjacent_rgb_mae_millionths > 250000 ||
      !Number.isSafeInteger(transition.max_black_pixel_ratio_millionths) ||
      transition.max_black_pixel_ratio_millionths < 0 ||
      transition.max_black_pixel_ratio_millionths > 100000 ||
      !Number.isSafeInteger(transition.min_mean_luma_millionths) ||
      transition.min_mean_luma_millionths < 80000 ||
      new Set([beforeFrame.sha256, middleFrame.sha256, afterFrame.sha256]).size
        !== 3) {
    fail('engine render capability transition evidence was invalid');
  }

  const audioCrossfade = exactKeys(proof.audio_crossfade, [
    'after', 'before', 'behavior', 'duration_ms', 'middle',
    'transition_start_ms',
  ], 'engine render capability audio-crossfade evidence');
  const beforeAudio = renderAudioWindow(
    audioCrossfade.before, 2450, 'engine render capability before audio');
  const middleAudio = renderAudioWindow(
    audioCrossfade.middle, 2750, 'engine render capability middle audio');
  const afterAudio = renderAudioWindow(
    audioCrossfade.after, 3050, 'engine render capability after audio');
  if (audioCrossfade.behavior !== 'equal_power_qsin' ||
      audioCrossfade.transition_start_ms !== 2600 ||
      audioCrossfade.duration_ms !== 400 ||
      beforeAudio.tone_440_millionths < 40000 ||
      beforeAudio.tone_880_millionths >
        Math.floor(beforeAudio.tone_440_millionths / 5) ||
      afterAudio.tone_880_millionths < 40000 ||
      afterAudio.tone_440_millionths >
        Math.floor(afterAudio.tone_880_millionths / 5) ||
      middleAudio.tone_440_millionths <
        Math.floor(beforeAudio.tone_440_millionths / 4) ||
      middleAudio.tone_880_millionths <
        Math.floor(afterAudio.tone_880_millionths / 4) ||
      middleAudio.rms_millionths < Math.floor(Math.min(
        beforeAudio.rms_millionths, afterAudio.rms_millionths) * 3 / 4)) {
    fail('engine render capability audio-crossfade evidence was invalid');
  }

  const receipt = exactKeys(normalized.receipt, [
    'bytes', 'file', 'sha256',
  ], 'engine render capability receipt binding');
  if (receipt.file !== 'RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT.json' ||
      !lowercaseSha256(receipt.sha256) ||
      !Number.isSafeInteger(receipt.bytes) || receipt.bytes < 1 ||
      receipt.bytes > 2 * 1024 * 1024) {
    fail('engine render capability receipt binding was invalid');
  }
  return {
    scope, fixture, runtime: { host, ffmpeg, ffprobe, contract }, production,
    artifact, evidence: { color, transition, audioCrossfade }, receipt,
  };
}

function lastJsonObject(buffer, label) {
  const text = Buffer.from(buffer).toString('utf8');
  const matches = [...text.matchAll(/\{[^{}]*\}/gs)];
  for (let index = matches.length - 1; index >= 0; index -= 1) {
    try {
      const value = JSON.parse(matches[index][0]);
      if (value && typeof value === 'object' && !Array.isArray(value)) return value;
    } catch (_) { /* try the preceding bounded object */ }
  }
  throw new RuntimeCapabilityCheckRunnerError(`${label} was invalid`);
}

function finiteNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number)) fail(`${label} was not finite`);
  return number;
}

function safeWorkRoot(root) {
  if (typeof root !== 'string' || !path.isAbsolute(root) || root.includes('\0')) {
    fail('capability work root is invalid');
  }
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  const real = fs.realpathSync.native(root);
  if (!fs.statSync(real).isDirectory()) fail('capability work root is invalid');
  return real;
}

function safeRemoveSession(session, root) {
  let real;
  try { real = fs.realpathSync.native(session); }
  catch (_) { return; }
  const relative = path.relative(root, real);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) ||
      path.isAbsolute(relative)) return;
  fs.rmSync(real, { recursive: true, force: true });
}

function createRuntimeCapabilityCheckRunner({
  runtime,
  workRoot,
  env = process.env,
  execute = runBoundedCommand,
  platform = process.platform,
} = {}) {
  if (!runtime || typeof runtime !== 'object' || Array.isArray(runtime)) {
    fail('runtime paths are required');
  }
  for (const name of ['daemon', 'engine', 'ffmpeg', 'ffprobe']) {
    if (typeof runtime[name] !== 'string' || !path.isAbsolute(runtime[name]) ||
        runtime[name].includes('\0')) fail(`runtime ${name} path is invalid`);
  }
  if (!env || typeof env !== 'object' || Array.isArray(env)) {
    fail('capability environment is invalid');
  }
  if (typeof execute !== 'function') fail('capability executor is invalid');
  const root = safeWorkRoot(workRoot);
  const session = fs.mkdtempSync(path.join(root, 'probe-'));
  const captionFontRoot = (
    typeof runtime.fonts === 'string' && path.isAbsolute(runtime.fonts) &&
    !runtime.fonts.includes('\0')
  ) ? runtime.fonts : '';
  const captionFont = captionFontRoot ?
    path.join(captionFontRoot, 'WorkSans-Variable.ttf') : '';
  const capabilityEnv = captionFontRoot ? {
    ...env, AUTOEDITOR_BUNDLED_FONTS: captionFontRoot,
  } : { ...env };
  const fixture = path.join(session, 'fixture.mp4');
  const hardCut = path.join(session, 'hard-cuts.mp4');
  const normalizedAudio = path.join(session, 'normalized.wav');
  const captionSource = path.join(session, 'caption-source.mp4');
  const captionOutput = path.join(session, 'caption-rendered.mp4');
  const sfxSource = path.join(session, 'sfx-source.mp4');
  const sfxOutput = path.join(session, 'sfx-rendered.mp4');
  const musicSource = path.join(session, 'music-source.mp4');
  const musicOutput = path.join(session, 'music-rendered.mp4');
  let fixturePromise = null;
  let sfxFixturePromise = null;
  let hardCutPromise = null;
  let creativePromise = null;
  let asrPromise = null;
  let dialoguePromise = null;
  let musicPromise = null;
  let renderCapabilityPromise = null;
  let disposed = false;
  let disposalPromise = null;
  const activeCommands = new Set();

  async function command(commandPath, args, options = {}) {
    if (disposed) fail('capability runner is closed');
    const acceptAggregateFailureReceipt =
      options.acceptAggregateFailureReceipt === true;
    const executionOptions = { ...options };
    delete executionOptions.acceptAggregateFailureReceipt;
    const execution = Promise.resolve().then(() => execute(commandPath, args, {
      cwd: session,
      env: capabilityEnv,
      platform,
      ...executionOptions,
    }));
    activeCommands.add(execution);
    let result;
    try { result = await execution; }
    finally { activeCommands.delete(execution); }
    const acceptedExit = result && (
      result.code === 0 ||
      (acceptAggregateFailureReceipt && result.code === 1)
    );
    if (!acceptedExit ||
        !Buffer.isBuffer(result.stdout) || !Buffer.isBuffer(result.stderr)) {
      fail('capability command failed');
    }
    return result;
  }

  async function ensureFixture(signal) {
    if (!fixturePromise) {
      fixturePromise = (async () => {
        await command(runtime.ffmpeg, [
          '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
          '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=30:d=1.000',
          '-f', 'lavfi', '-i',
          'sine=frequency=440:sample_rate=48000:duration=1.000',
          '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
          '-c:a', 'aac', '-ar', '48000', '-ac', '1', fixture,
        ], { signal });
        const stat = fs.statSync(fixture);
        if (!stat.isFile() || stat.size < 1) fail('media fixture was not produced');
        return { bytes: stat.size, sha256: sha256Bytes(fs.readFileSync(fixture)) };
      })();
    }
    return fixturePromise;
  }

  async function ensureSfxFixture(signal) {
    if (!sfxFixturePromise) {
      sfxFixturePromise = (async () => {
        await command(runtime.ffmpeg, [
          '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
          '-f', 'lavfi', '-i', 'color=c=0x142238:s=160x90:r=30:d=3.000',
          '-f', 'lavfi', '-i',
          'anullsrc=channel_layout=stereo:sample_rate=48000:d=3.000',
          '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264',
          '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
          '-ar', '48000', '-ac', '2', '-shortest', sfxSource,
        ], { signal });
        const binding = stableBoundedFile(
          sfxSource, session, 'fixed SFX source fixture', 64 * 1024 * 1024);
        const media = await probeMedia(sfxSource, signal);
        const durationMs = Math.round(finiteNumber(
          media?.format?.duration, 'fixed SFX source duration') * 1000);
        const video = media?.streams?.find((item) => item.codec_type === 'video');
        const audio = media?.streams?.find((item) => item.codec_type === 'audio');
        if (durationMs !== 3000 || video?.width !== 160 || video?.height !== 90 ||
            String(audio?.sample_rate) !== '48000' || audio?.channels !== 2) {
          fail('fixed SFX source fixture was invalid');
        }
        return { sha256: binding.sha256, bytes: binding.size, durationMs };
      })();
    }
    return sfxFixturePromise;
  }

  async function asrCapability(id, signal, boundModelSha256) {
    if (!/^[0-9a-f]{64}$/.test(boundModelSha256 || '')) {
      fail('small ASR model is absent from the runtime identity');
    }
    if (!asrPromise) {
      asrPromise = (async () => {
        const receiptFile = path.join(session, 'ASR_RUNTIME_PROBE_RECEIPT.json');
        const engineResult = await command(runtime.engine, [
          '--asr-capability-self-test', receiptFile, session,
        ], { signal, timeoutMs: CAPTION_RENDER_TIMEOUT_MS });
        const event = typedJsonEvent(
          engineResult.stdout, ASR_ENGINE_EVENT, 'engine ASR capability evidence');
        exactKeys(event, [
          'checks', 'errors', 'event', 'result', 'schema_version',
        ], 'engine ASR capability evidence');
        if (event.schema_version !== ASR_ENGINE_SCHEMA ||
            !plainObject(event.errors) || Object.keys(event.errors).length !== 0) {
          fail('engine ASR capability evidence was invalid');
        }
        const checks = exactKeys(event.checks, [
          'expected_transcript', 'fixture_identity', 'model_identity',
          'offline_small_model', 'ordered_word_timestamps', 'production_asr',
        ], 'engine ASR capability checks');
        if (Object.values(checks).some((value) => value !== true)) {
          fail('engine ASR capability self-test did not attest every check');
        }
        const result = exactKeys(event.result, [
          'fixture', 'model', 'receipt', 'transcript', 'words',
        ], 'engine ASR capability result');
        const fixtureBinding = exactKeys(result.fixture, [
          'bytes', 'name', 'sha256', 'source_revision',
        ], 'engine ASR fixture binding');
        const modelBinding = exactKeys(result.model, [
          'bytes', 'files', 'name', 'tree_sha256',
        ], 'engine ASR model binding');
        const transcript = exactKeys(result.transcript, [
          'language', 'normalized_text', 'text',
        ], 'engine ASR transcript');
        const receiptBinding = exactKeys(result.receipt, [
          'bytes', 'file', 'sha256',
        ], 'engine ASR receipt binding');
        if (!Array.isArray(result.words) || result.words.length < 3 ||
            result.words.length > 64 || fixtureBinding.bytes !== 9743 ||
            fixtureBinding.name !== 'openai-whisper-jfk-excerpt.m4a' ||
            fixtureBinding.sha256 !==
              'b36ddd51100eca8b767f667e90d6d0200a943eb2e25c6c021609582a2dcf4c37' ||
            !String(fixtureBinding.source_revision).startsWith('openai/whisper@') ||
            modelBinding.name !== 'faster-whisper-small' ||
            modelBinding.tree_sha256 !== boundModelSha256 ||
            !/^[0-9a-f]{64}$/.test(modelBinding.tree_sha256 || '') ||
            !Number.isSafeInteger(modelBinding.bytes) || modelBinding.bytes < 1 ||
            !Number.isSafeInteger(modelBinding.files) || modelBinding.files < 1 ||
            transcript.language !== 'en' ||
            typeof transcript.text !== 'string' || !transcript.text.trim() ||
            typeof transcript.normalized_text !== 'string' ||
            !/(^| )my fellow americans( |$)/.test(transcript.normalized_text) ||
            receiptBinding.file !== 'ASR_RUNTIME_PROBE_RECEIPT.json' ||
            !/^[0-9a-f]{64}$/.test(receiptBinding.sha256 || '') ||
            !Number.isSafeInteger(receiptBinding.bytes) || receiptBinding.bytes < 1) {
          fail('engine ASR capability bindings were invalid');
        }
        let priorEnd = 0;
        const normalizedWords = [];
        for (const [index, raw] of result.words.entries()) {
          const word = exactKeys(raw, [
            'end_ms', 'probability_millionths', 'start_ms', 'text',
          ], `engine ASR word ${index}`);
          if (typeof word.text !== 'string' || !word.text.trim() ||
              !Number.isSafeInteger(word.start_ms) || word.start_ms < priorEnd ||
              !Number.isSafeInteger(word.end_ms) || word.end_ms <= word.start_ms ||
              word.end_ms > 10000 ||
              !Number.isSafeInteger(word.probability_millionths) ||
              word.probability_millionths < 0 ||
              word.probability_millionths > 1000000) {
            fail('engine ASR word timing evidence was invalid');
          }
          priorEnd = word.end_ms;
          normalizedWords.push(word.text.toLowerCase().replace(/[^a-z0-9']/g, ''));
        }
        let cursor = 0;
        for (const expected of ['my', 'fellow', 'americans']) {
          cursor = normalizedWords.indexOf(expected, cursor);
          if (cursor < 0) fail('engine ASR expected word evidence was invalid');
          cursor += 1;
        }
        const receipt = stableBoundedFile(
          receiptFile, session, 'ASR runtime probe receipt', 256 * 1024);
        if (receipt.sha256 !== receiptBinding.sha256 ||
            receipt.size !== receiptBinding.bytes) {
          fail('engine ASR receipt file did not match its binding');
        }
        return { event, receipt };
      })();
    }
    const proof = await asrPromise;
    const measurementName = id === 'word_timestamps'
      ? 'ordered_word_timestamp_count' : 'recognized_word_count';
    return {
      status: 'pass',
      measurements: measurements([
        [measurementName, 'count', proof.event.result.words.length],
        ['offline_execution', 'boolean', 1],
      ]),
      evidence: evidence(id, {
        fixture_sha256: proof.event.result.fixture.sha256,
        model_tree_sha256: proof.event.result.model.tree_sha256,
        bound_model_sha256: boundModelSha256,
        receipt_sha256: proof.receipt.sha256,
        expected_terms_verified: true,
        ordered_word_timestamps: true,
        network_used: false,
      }),
    };
  }

  async function dialogueCleanup(signal, boundModelSha256) {
    if (!/^[0-9a-f]{64}$/.test(boundModelSha256 || '')) {
      fail('small ASR model is absent from the runtime identity');
    }
    if (!dialoguePromise) {
      dialoguePromise = (async () => {
        const receiptFile = path.join(
          session, 'DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT.json');
        const engineResult = await command(runtime.engine, [
          '--dialogue-cleanup-capability-self-test', receiptFile, session,
        ], { signal, timeoutMs: SFX_PRODUCTION_TIMEOUT_MS });
        const event = typedJsonEvent(
          engineResult.stdout, DIALOGUE_ENGINE_EVENT,
          'engine dialogue-cleanup capability evidence');
        exactKeys(event, [
          'checks', 'errors', 'event', 'result', 'schema_version',
        ], 'engine dialogue-cleanup capability evidence');
        if (event.schema_version !== DIALOGUE_ENGINE_SCHEMA ||
            !plainObject(event.errors) || Object.keys(event.errors).length !== 0) {
          fail('engine dialogue-cleanup capability evidence was invalid');
        }
        const checks = exactKeys(event.checks, [
          'artifact_identity', 'expected_single_take_after',
          'false_start_detector', 'fixture_identity',
          'frame_sample_accurate_av_cut', 'model_identity',
          'no_retake_residue', 'normalized_av_before_after',
          'offline_small_model', 'production_asr_before_after',
          'production_dialogue_pipeline', 'repeated_take_detected',
          'tool_identity', 'word_safe_kept_take_boundary',
        ], 'engine dialogue-cleanup checks');
        if (Object.values(checks).some((value) => value !== true)) {
          fail('engine dialogue-cleanup self-test did not attest every check');
        }
        const result = exactKeys(event.result, [
          'detectors', 'edit', 'fixture', 'media', 'production_functions',
          'receipt', 'runtime', 'scope', 'transcripts',
        ], 'engine dialogue-cleanup result');
        const scope = exactKeys(result.scope, [
          'certified', 'not_certified',
        ], 'engine dialogue-cleanup scope');
        if (stableJson(scope.certified) !== stableJson([
          'repeated_take_detection', 'false_start_detection',
          'frame_sample_accurate_av_cut', 'post_render_retake_residue_gate',
        ]) || stableJson(scope.not_certified) !== stableJson([
          'cough_classification', 'dead_air_policy_quality',
          'garbled_speech_semantics', 'general_asr_accuracy',
        ])) {
          fail('engine dialogue-cleanup capability scope was invalid');
        }
        const fixture = exactKeys(result.fixture, [
          'bytes', 'false_start_timeline_sha256', 'filter_graph_sha256',
          'name', 'pause_ms', 'sha256', 'source_revision', 'take_count',
        ], 'engine dialogue-cleanup fixture');
        const runtimeBinding = exactKeys(result.runtime, [
          'model', 'tools',
        ], 'engine dialogue-cleanup runtime');
        const model = exactKeys(runtimeBinding.model, [
          'bytes', 'files', 'name', 'tree_sha256',
        ], 'engine dialogue-cleanup model');
        const tools = exactKeys(runtimeBinding.tools, [
          'ffmpeg', 'ffprobe',
        ], 'engine dialogue-cleanup tools');
        for (const [name, item] of Object.entries(tools)) {
          const identity = exactKeys(item, [
            'bytes', 'sha256',
          ], `engine dialogue-cleanup ${name}`);
          if (!lowercaseSha256(identity.sha256) ||
              !Number.isSafeInteger(identity.bytes) || identity.bytes < 1) {
            fail('engine dialogue-cleanup tool identity was invalid');
          }
        }
        if (fixture.name !== 'openai-whisper-jfk-excerpt.m4a' ||
            fixture.bytes !== 9743 || fixture.sha256 !==
              'b36ddd51100eca8b767f667e90d6d0200a943eb2e25c6c021609582a2dcf4c37' ||
            !String(fixture.source_revision).startsWith('openai/whisper@') ||
            fixture.take_count !== 2 || fixture.pause_ms !== 500 ||
            !lowercaseSha256(fixture.filter_graph_sha256) ||
            !lowercaseSha256(fixture.false_start_timeline_sha256) ||
            model.name !== 'faster-whisper-small' ||
            model.tree_sha256 !== boundModelSha256 ||
            !Number.isSafeInteger(model.bytes) || model.bytes < 1 ||
            !Number.isSafeInteger(model.files) || model.files < 1 ||
            model.files > 64) {
          fail('engine dialogue-cleanup bindings were invalid');
        }
        if (stableJson(result.production_functions) !== stableJson([
          'autoeditor.asr.create_model', 'autoeditor.asr.transcribe',
          'autoeditor.pipeline.detect_retakes',
          'autoeditor.pipeline.detect_false_starts',
          'autoeditor.pipeline.apply_cuts',
          'autoeditor.pipeline.verify_no_retakes',
        ])) {
          fail('engine dialogue-cleanup function binding was invalid');
        }
        const transcripts = exactKeys(result.transcripts, [
          'after', 'before',
        ], 'engine dialogue-cleanup transcripts');
        const before = exactKeys(transcripts.before, [
          'normalized_text', 'take_count', 'word_count', 'word_timing_sha256',
        ], 'engine dialogue-cleanup before transcript');
        const after = exactKeys(transcripts.after, [
          'normalized_text', 'take_count', 'word_count', 'word_timing_sha256',
        ], 'engine dialogue-cleanup after transcript');
        const expectedTake = 'and so my fellow americans';
        if (before.normalized_text !== `${expectedTake} ${expectedTake}` ||
            before.take_count !== 2 || before.word_count !== 10 ||
            after.normalized_text !== expectedTake || after.take_count !== 1 ||
            after.word_count !== 5 ||
            !lowercaseSha256(before.word_timing_sha256) ||
            !lowercaseSha256(after.word_timing_sha256)) {
          fail('engine dialogue-cleanup transcript evidence was invalid');
        }
        const edit = exactKeys(result.edit, [
          'cut_end_ms', 'end_frame', 'gap_before_kept_take_ms',
          'kept_take_start_ms', 'removed_frames', 'removed_ms', 'start_frame',
        ], 'engine dialogue-cleanup edit');
        const media = exactKeys(result.media, [
          'edited', 'source',
        ], 'engine dialogue-cleanup media');
        const mediaVideo = (record, label) => {
          const normalized = exactKeys(record, [
            'audio', 'av_duration_drift_ms', 'bytes', 'sha256', 'video',
          ], label);
          const video = exactKeys(normalized.video, [
            'codec', 'duration_ms', 'fps', 'frames', 'height',
            'pixel_format', 'width',
          ], `${label} video`);
          const audio = exactKeys(normalized.audio, [
            'channels', 'codec', 'duration_ms', 'sample_rate',
          ], `${label} audio`);
          if (!lowercaseSha256(normalized.sha256) ||
              !Number.isSafeInteger(normalized.bytes) || normalized.bytes < 1 ||
              video.codec !== 'h264' || video.width !== 320 ||
              video.height !== 180 || video.pixel_format !== 'yuv420p' ||
              video.fps !== 30 || !Number.isSafeInteger(video.frames) ||
              !Number.isSafeInteger(video.duration_ms) ||
              audio.codec !== 'aac' || audio.sample_rate !== 48000 ||
              audio.channels !== 2 || !Number.isSafeInteger(audio.duration_ms) ||
              !Number.isSafeInteger(normalized.av_duration_drift_ms) ||
              normalized.av_duration_drift_ms < 0 ||
              normalized.av_duration_drift_ms > 34) {
            fail('engine dialogue-cleanup media evidence was invalid');
          }
          return normalized;
        };
        const source = mediaVideo(media.source, 'engine dialogue-cleanup source');
        const edited = mediaVideo(media.edited, 'engine dialogue-cleanup edited');
        if (source.video.frames !== 165 || source.video.duration_ms !== 5500 ||
            !Number.isSafeInteger(edit.removed_frames) ||
            edit.removed_frames !== 73 || edited.video.frames !== 92 ||
            edited.video.frames !== source.video.frames - edit.removed_frames) {
          fail('engine dialogue-cleanup edit/media binding was invalid');
        }
        const receiptBinding = exactKeys(result.receipt, [
          'bytes', 'file', 'sha256',
        ], 'engine dialogue-cleanup receipt binding');
        if (receiptBinding.file !==
              'DIALOGUE_CLEANUP_RUNTIME_PROBE_RECEIPT.json' ||
            !lowercaseSha256(receiptBinding.sha256) ||
            !Number.isSafeInteger(receiptBinding.bytes) ||
            receiptBinding.bytes < 1) {
          fail('engine dialogue-cleanup receipt binding was invalid');
        }
        const receipt = stableBoundedFile(
          receiptFile, session, 'dialogue-cleanup runtime probe receipt',
          512 * 1024);
        if (receipt.sha256 !== receiptBinding.sha256 ||
            receipt.size !== receiptBinding.bytes) {
          fail('dialogue-cleanup receipt file did not match its binding');
        }
        return { event, receipt, source, edited, edit };
      })();
    }
    const proof = await dialoguePromise;
    return {
      status: 'pass',
      measurements: measurements([
        ['edited_frame_count', 'count', proof.edited.video.frames],
        ['removed_frame_count', 'count', proof.edit.removed_frames],
        ['source_take_count', 'count', 2],
      ]),
      evidence: evidence('dialogue_cleanup', {
        fixture_sha256: proof.event.result.fixture.sha256,
        model_tree_sha256: proof.event.result.runtime.model.tree_sha256,
        bound_model_sha256: boundModelSha256,
        receipt_sha256: proof.receipt.sha256,
        repeated_take_removed: true,
        false_start_detector_executed: true,
        post_render_residue_gate_passed: true,
        network_used: false,
        certified_scope: proof.event.result.scope.certified,
      }),
    };
  }

  async function renderCapability(id, signal, bindings) {
    if (!bindings || ['engine', 'ffmpeg', 'ffprobe'].some((name) =>
      !bindings[name] || !lowercaseSha256(bindings[name].sha256))) {
      fail('render capability runtime tools are absent from the runtime identity');
    }
    if (!renderCapabilityPromise) {
      renderCapabilityPromise = (async () => {
        const receiptFile = path.join(
          session, 'RENDER_CAPABILITY_RUNTIME_PROBE_RECEIPT.json');
        const engineResult = await command(runtime.engine, [
          '--render-capability-self-test', receiptFile, session,
        ], { signal, timeoutMs: SFX_PRODUCTION_TIMEOUT_MS });
        const event = typedJsonEvent(
          engineResult.stdout, RENDER_ENGINE_EVENT,
          'engine render capability evidence');
        exactKeys(event, [
          'checks', 'errors', 'event', 'result', 'schema_version',
        ], 'engine render capability evidence');
        if (event.schema_version !== RENDER_ENGINE_SCHEMA ||
            !plainObject(event.errors) || Object.keys(event.errors).length !== 0) {
          fail('engine render capability evidence was invalid');
        }
        const checks = exactKeys(event.checks, [
          'audio_crossfades', 'color_normalization', 'cross_dissolves',
          'motion_quality_analysis',
        ], 'engine render capability checks');
        if (Object.values(checks).some((value) => value !== true)) {
          fail('engine render capability self-test did not attest every check');
        }
        const result = validateRenderCapabilityResult(event.result, bindings);
        const receipt = stableBoundedFile(
          receiptFile, session, 'render capability runtime probe receipt',
          2 * 1024 * 1024);
        if (receipt.sha256 !== result.receipt.sha256 ||
            receipt.size !== result.receipt.bytes) {
          fail('render capability receipt file did not match its binding');
        }
        const receiptValue = parseJsonObject(
          receipt.bytes, 'render capability runtime probe receipt');
        const expectedReceipt = {
          schema_version: RENDER_ENGINE_SCHEMA,
          checks,
          scope: event.result.scope,
          fixture: event.result.fixture,
          runtime: event.result.runtime,
          production: event.result.production,
          artifact: event.result.artifact,
          evidence: event.result.evidence,
        };
        if (stableJson(receiptValue) !== stableJson(expectedReceipt) ||
            !receipt.bytes.equals(Buffer.from(
              `${stableJson(expectedReceipt)}\n`, 'ascii'))) {
          fail('render capability receipt was not exact canonical evidence');
        }
        return { event, result, receipt };
      })();
    }
    const proof = await renderCapabilityPromise;
    const color = proof.result.evidence.color;
    const transition = proof.result.evidence.transition;
    const audio = proof.result.evidence.audioCrossfade;
    const facts = {
      artifact_sha256: proof.result.artifact.sha256,
      fixture_sha256: proof.result.fixture.sha256,
      production_transition_render_receipt_sha256:
        proof.result.production.transition_render_receipt_sha256,
      receipt_sha256: proof.receipt.sha256,
      runtime_probe_code_sha256:
        bindings.probe?.sha256 || bindings.engine.sha256,
      runtime_probe_code_binding:
        bindings.probe ? 'development-source' : 'frozen-engine',
      network_used: false,
      narrow_scope: proof.result.scope,
    };
    if (id === 'color_normalization') {
      return {
        status: 'pass',
        measurements: measurements([
          ['artifact_to_reference_mae_millionths', 'millionths',
            color.artifact_to_reference_mae_millionths],
          ['source_to_normalized_mae_millionths', 'millionths',
            color.source_to_normalized_mae_millionths],
        ]),
        evidence: evidence(id, {
          ...facts,
          source_declaration: color.source_declaration,
          normalization_mode: color.normalization_mode,
          conversion_filter_sha256: color.conversion_filter_sha256,
          real_pixel_conversion_verified: true,
        }),
      };
    }
    if (id === 'cross_dissolves') {
      return {
        status: 'pass',
        measurements: measurements([
          ['dissolve_duration_frames', 'frames', transition.duration_frames],
          ['final_right_weight_millionths', 'millionths',
            transition.estimated_right_weights_millionths.at(-1)],
        ]),
        evidence: evidence(id, {
          ...facts,
          kind: transition.kind,
          duration_ms: transition.duration_ms,
          production_xfade_verified: true,
          decoded_blend_progression_verified: true,
        }),
      };
    }
    if (id === 'audio_crossfades') {
      return {
        status: 'pass',
        measurements: measurements([
          ['middle_440_tone_millionths', 'millionths',
            audio.middle.tone_440_millionths],
          ['middle_880_tone_millionths', 'millionths',
            audio.middle.tone_880_millionths],
        ]),
        evidence: evidence(id, {
          ...facts,
          behavior: audio.behavior,
          duration_ms: audio.duration_ms,
          decoded_equal_power_overlap_verified: true,
        }),
      };
    }
    if (id === 'motion_quality_analysis') {
      return {
        status: 'pass',
        measurements: measurements([
          ['av_drift_us', 'us', proof.result.artifact.av_drift_us],
          ['max_adjacent_rgb_mae_millionths', 'millionths',
            transition.max_adjacent_rgb_mae_millionths],
          ['max_black_pixel_ratio_millionths', 'millionths',
            transition.max_black_pixel_ratio_millionths],
        ]),
        evidence: evidence(id, {
          ...facts,
          decoded_motion_continuity_verified: true,
          no_black_flash_verified: true,
          before_frame_sha256: transition.before.sha256,
          middle_frame_sha256: transition.middle.sha256,
          after_frame_sha256: transition.after.sha256,
        }),
      };
    }
    fail('render capability id is unsupported');
  }

  async function probeMedia(file, signal) {
    const result = await command(runtime.ffprobe, [
      '-v', 'error', '-show_entries',
      'format=duration:stream=codec_type,width,height,pix_fmt,r_frame_rate,' +
        'sample_rate,channels',
      '-of', 'json', file,
    ], { signal });
    return parseJsonObject(result.stdout, 'media probe evidence');
  }

  async function ensureHardCuts(signal) {
    if (!hardCutPromise) {
      hardCutPromise = (async () => {
        await command(runtime.ffmpeg, [
          '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
          '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=30:d=0.400',
          '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=30:d=0.400',
          '-filter_complex',
          '[0:v]setpts=PTS-STARTPTS[v0];[1:v]setpts=PTS-STARTPTS[v1];' +
            '[v0][v1]concat=n=2:v=1:a=0[v]',
          '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', hardCut,
        ], { signal });
        const probe = await probeMedia(hardCut, signal);
        const durationMs = Math.round(finiteNumber(
          probe?.format?.duration, 'hard-cut duration') * 1000);
        const samples = [];
        for (const timestamp of ['0.200', '0.600']) {
          const result = await command(runtime.ffmpeg, [
            '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-ss', timestamp, '-i', hardCut, '-frames:v', '1',
            '-vf', 'scale=1:1,format=rgb24', '-f', 'rawvideo', '-',
          ], { signal });
          if (result.stdout.length !== 3) fail('hard-cut sample was invalid');
          samples.push([...result.stdout]);
        }
        if (!(samples[0][0] > samples[0][2] + 40 &&
              samples[1][2] > samples[1][0] + 40 &&
              durationMs >= 760 && durationMs <= 850)) {
          fail('hard-cut fixture did not preserve its boundary');
        }
        return {
          durationMs,
          bytes: fs.statSync(hardCut).size,
          sha256: sha256Bytes(fs.readFileSync(hardCut)),
          samples,
        };
      })();
    }
    return hardCutPromise;
  }

  async function creativeSmoke(signal) {
    if (!creativePromise) {
      creativePromise = (async () => {
        const result = await command(runtime.daemon, [], {
          signal,
          timeoutMs: CREATIVE_TIMEOUT_MS,
          // The daemon's aggregate smoke command exits 1 if either renderer
          // fails. Its typed receipt still lets this trusted runner assess
          // HyperFrames and Remotion independently.
          acceptAggregateFailureReceipt: true,
        });
        const lines = result.stdout.toString('utf8').split(/\r?\n/).filter(Boolean);
        const event = lines.map((line) => {
          try { return JSON.parse(line); } catch (_) { return null; }
        }).find((value) => value?.event === 'helper-creative-smoke');
        if (!event || !event.checks || typeof event.checks !== 'object' ||
            Array.isArray(event.checks)) fail('creative smoke receipt was invalid');
        return {
          hyperframes: event.checks.hyperframes_render === true,
          remotion: event.checks.remotion_render === true,
        };
      })();
    }
    return creativePromise;
  }

  async function audioQuality(signal) {
    const media = await ensureFixture(signal);
    const result = await command(runtime.ffmpeg, [
      '-nostdin', '-hide_banner', '-nostats', '-i', fixture,
      '-vn', '-af', 'volumedetect', '-f', 'null', '-',
    ], { signal });
    const log = result.stderr.toString('utf8');
    const mean = finiteNumber(/mean_volume:\s*(-?[0-9.]+)\s*dB/.exec(log)?.[1],
      'mean volume');
    const peak = finiteNumber(/max_volume:\s*(-?[0-9.]+)\s*dB/.exec(log)?.[1],
      'peak volume');
    if (peak < mean || peak > 0.1) fail('audio analysis evidence was inconsistent');
    return {
      status: 'pass',
      measurements: measurements([
        ['mean_level_millidb', 'millidb', Math.round(mean * 1000)],
        ['peak_level_millidb', 'millidb', Math.round(peak * 1000)],
      ]),
      evidence: evidence('audio_quality_analysis', {
        artifact_sha256: media.sha256,
        analysis: 'ffmpeg-volumedetect',
      }),
    };
  }

  async function creative(id, signal) {
    const receipt = await creativeSmoke(signal);
    const passed = id === 'chart_rendering' ? receipt.remotion : receipt.hyperframes;
    return {
      status: passed ? 'pass' : 'fail',
      measurements: measurements([
        ['render_succeeded', 'boolean', passed ? 1 : 0],
      ]),
      evidence: evidence(id, {
        renderer: id === 'chart_rendering' ? 'remotion' : 'hyperframes',
        render_succeeded: passed,
      }),
    };
  }

  async function hardCuts(signal) {
    const receipt = await ensureHardCuts(signal);
    return {
      status: 'pass',
      measurements: measurements([
        ['boundary_count', 'count', 1],
        ['duration_ms', 'ms', receipt.durationMs],
      ]),
      evidence: evidence('hard_cuts', {
        artifact_sha256: receipt.sha256,
        first_sample_sha256: sha256Bytes(Buffer.from(receipt.samples[0])),
        second_sample_sha256: sha256Bytes(Buffer.from(receipt.samples[1])),
      }),
    };
  }

  async function loudness(signal) {
    await command(runtime.ffmpeg, [
      '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
      '-f', 'lavfi', '-i',
      'sine=frequency=1000:sample_rate=48000:duration=3.000',
      '-af', 'volume=0.2,loudnorm=I=-14:LRA=11:TP=-1.5',
      '-c:a', 'pcm_s16le', normalizedAudio,
    ], { signal });
    const analyzed = await command(runtime.ffmpeg, [
      '-nostdin', '-hide_banner', '-nostats', '-i', normalizedAudio,
      '-af', 'loudnorm=I=-14:LRA=11:TP=-1.5:print_format=json',
      '-f', 'null', '-',
    ], { signal });
    const report = lastJsonObject(analyzed.stderr, 'loudness analysis');
    const integrated = finiteNumber(report.input_i, 'integrated loudness');
    const truePeak = finiteNumber(report.input_tp, 'true peak');
    if (Math.abs(integrated - (-14)) > 1.25 || truePeak > -1.0) {
      fail('loudness fixture missed its bounded target');
    }
    const digest = sha256Bytes(fs.readFileSync(normalizedAudio));
    return {
      status: 'pass',
      measurements: measurements([
        ['integrated_loudness_millilu', 'millilu', Math.round(integrated * 1000)],
        ['true_peak_millidb', 'millidb', Math.round(truePeak * 1000)],
      ]),
      evidence: evidence('loudness_normalization', {
        artifact_sha256: digest,
        analysis: 'ffmpeg-loudnorm',
      }),
    };
  }

  async function sceneDetection(signal) {
    const receipt = await ensureHardCuts(signal);
    const result = await command(runtime.ffmpeg, [
      '-nostdin', '-hide_banner', '-nostats', '-i', hardCut,
      '-vf', "select='gt(scene,0.2)',showinfo", '-an', '-f', 'null', '-',
    ], { signal });
    const times = [...result.stderr.toString('utf8').matchAll(
      /pts_time:\s*([0-9.]+)/g)].map((match) => Number(match[1]))
      .filter(Number.isFinite);
    const boundary = times.find((value) => value >= 0.30 && value <= 0.55);
    if (boundary === undefined) fail('scene boundary was not detected');
    return {
      status: 'pass',
      measurements: measurements([
        ['detected_scene_count', 'count', times.length],
        ['first_boundary_ms', 'ms', Math.round(boundary * 1000)],
      ]),
      evidence: evidence('scene_detection', {
        artifact_sha256: receipt.sha256,
        detector: 'ffmpeg-scene-score',
      }),
    };
  }

  async function artifactReceipts(signal) {
    const media = await ensureFixture(signal);
    const finalName = 'artifact-fixture.mp4';
    const pendingName = 'artifact-fixture.UNVERIFIED.mp4';
    const pending = path.join(session, pendingName);
    const approved = path.join(session, finalName);
    fs.copyFileSync(fixture, pending, fs.constants.COPYFILE_EXCL);
    const artifactBytes = fs.statSync(pending).size;
    const artifactSha256 = sha256Bytes(fs.readFileSync(pending));
    if (artifactSha256 !== media.sha256 || artifactBytes !== media.bytes) {
      fail('artifact receipt fixture bytes drifted while staged');
    }
    const engineResult = await command(runtime.engine, [
      '--artifact-receipt-self-test', pending, approved, session,
    ], { signal, timeoutMs: CREATIVE_TIMEOUT_MS });
    const engineReceipt = parseJsonObject(
      engineResult.stdout, 'engine artifact receipt evidence');
    if (engineReceipt.event !== 'autoeditor-engine-artifact-receipt-self-test' ||
        !engineReceipt.checks ||
        engineReceipt.checks.production_artifact_receipts !== true ||
        engineReceipt.checks.artifact_identity !== true ||
        !engineReceipt.errors || Object.keys(engineReceipt.errors).length !== 0) {
      fail('engine artifact receipt self-test did not attest every check');
    }
    const event = {
      output: pending,
      outputs: { fixture: pending },
      finalOutputs: { fixture: approved },
      qaReport: path.join(session, 'QA_REPORT.json'),
    };
    const qa = readArtifactQaReport(
      session, event, artifactSha256, artifactBytes);
    const boundaryReceipt = readContractJsonSidecar(
      session, qa.contract, 'edit_boundaries', 'edit-boundary receipt');
    const mixReceipt = readContractJsonSidecar(
      session, qa.contract, 'audio_mix', 'audio-mix receipt');
    if (qa.contract.mode !== 'generic-baseline' ||
        qa.release.sha256 !== artifactSha256 ||
        boundaryReceipt.report.schema !== 'autoeditor-edit-boundaries/v1' ||
        mixReceipt.report.schema !== 'autoeditor-audio-mix-receipt/v1') {
      fail('production artifact receipt reader rejected its exact fixture');
    }
    return {
      status: 'pass',
      measurements: measurements([
        ['artifact_bytes', 'bytes', artifactBytes],
        ['bound_sidecar_count', 'count', 2],
      ]),
      evidence: evidence('artifact_receipts', {
        artifact_sha256: artifactSha256,
        engine_qa_sha256: qa.sha256,
        edit_boundaries_sha256: boundaryReceipt.sha256,
        audio_mix_sha256: mixReceipt.sha256,
        reader: 'production-artifact-contract-v2',
      }),
    };
  }

  async function captionPixelFrame(timestamp, signal) {
    const result = await command(runtime.ffmpeg, [
      '-nostdin', '-hide_banner', '-loglevel', 'error',
      '-ss', timestamp, '-i', captionOutput, '-frames:v', '1',
      '-vf', `crop=${CAPTION_WIDTH}:${CAPTION_BAND_HEIGHT}:0:${CAPTION_Y},` +
        'format=rgb24',
      '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-',
    ], { signal });
    const expected = CAPTION_WIDTH * CAPTION_BAND_HEIGHT * 3;
    if (result.stdout.length !== expected) fail('caption pixel frame was invalid');
    return result.stdout;
  }

  async function captionPixelEvidence(signal) {
    const timestampText = {
      blank_before: '0.100', word_cut: '0.450', word_it: '0.750',
      word_now: '1.050', blank_after: '1.600',
    };
    const frames = {};
    for (const [name, timestamp] of Object.entries(timestampText)) {
      frames[name] = await captionPixelFrame(timestamp, signal);
    }
    const blankControl = captionFrameDelta(
      frames.blank_before, frames.blank_after);
    const activeVsBlank = {
      word_cut: captionFrameDelta(frames.blank_before, frames.word_cut),
      word_it: captionFrameDelta(frames.blank_before, frames.word_it),
      word_now: captionFrameDelta(frames.blank_before, frames.word_now),
    };
    const wordStateChanges = {
      cut_to_it: captionFrameDelta(frames.word_cut, frames.word_it),
      it_to_now: captionFrameDelta(frames.word_it, frames.word_now),
    };
    const blankOk = blankControl.changed_pixel_ratio <= 0.003 &&
      blankControl.mean_absolute_error <= 1.5;
    const activeOk = Object.values(activeVsBlank).every((item) =>
      item.changed_pixel_ratio >= 0.01 && item.mean_absolute_error >= 1.0);
    const statesOk = Object.values(wordStateChanges).every((item) =>
      item.changed_pixel_ratio >= 0.002 && item.mean_absolute_error >= 0.15);
    if (!blankOk || !activeOk || !statesOk) {
      fail('caption output did not prove its fixed timed overlay');
    }
    return {
      timestamps_ms: {
        blank_before: 100, word_cut: 450, word_it: 750,
        word_now: 1050, blank_after: 1600,
      },
      frame_sha256: Object.fromEntries(Object.entries(frames)
        .map(([name, frame]) => [name, sha256Bytes(frame)])),
      blank_control: blankControl,
      active_vs_blank: activeVsBlank,
      word_state_changes: wordStateChanges,
    };
  }

  async function captionRendering(signal, boundFontSha256) {
    if (!captionFontRoot || !captionFont) {
      fail('runtime fonts path is invalid');
    }
    const font = stableBoundedFile(
      captionFont, captionFontRoot, 'bundled caption font', 2 * 1024 * 1024);
    if (path.basename(font.real) !== 'WorkSans-Variable.ttf' ||
        font.size < 100_000 || font.sha256 !== boundFontSha256) {
      fail('bundled caption font did not match runtime identity');
    }
    await command(runtime.ffmpeg, [
      '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
      '-f', 'lavfi', '-i',
      `color=c=0x203040:s=${CAPTION_WIDTH}x${CAPTION_HEIGHT}:r=30:d=2.000`,
      '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', captionSource,
    ], { signal });
    const source = await probeMedia(captionSource, signal);
    const sourceVideo = source?.streams?.find((stream) =>
      stream?.codec_type === 'video');
    if (Math.round(finiteNumber(source?.format?.duration,
      'caption source duration') * 1000) !== CAPTION_DURATION_MS ||
        sourceVideo?.width !== CAPTION_WIDTH || sourceVideo?.height !== CAPTION_HEIGHT) {
      fail('caption source fixture was invalid');
    }
    const engineResult = await command(runtime.engine, [
      '--caption-render-self-test', captionSource, captionOutput, session,
    ], { signal, timeoutMs: CAPTION_RENDER_TIMEOUT_MS });
    const engine = typedJsonEvent(
      engineResult.stdout, 'autoeditor-engine-caption-render-self-test',
      'engine caption render evidence');
    exactKeys(engine, [
      'event', 'schema_version', 'checks', 'errors', 'result',
    ], 'engine caption render evidence');
    if (engine.schema_version !== CAPTION_ENGINE_SCHEMA) {
      fail('engine caption render evidence was invalid');
    }
    const checks = exactKeys(engine.checks, [
      'bundled_worksans', 'production_caption_band',
      'production_caption_receipt', 'burned_timed_pixel_evidence',
    ], 'engine caption render checks');
    if (!Object.values(checks).every((value) => value === true) ||
        !plainObject(engine.errors) || Object.keys(engine.errors).length !== 0) {
      fail('engine caption render self-test did not attest every check');
    }
    const result = exactKeys(engine.result, [
      'artifact', 'caption_receipt', 'font', 'overlay',
    ], 'engine caption render result');
    const artifact = exactKeys(result.artifact, [
      'file', 'sha256', 'bytes', 'duration_ms', 'width', 'height', 'fps_milli',
    ], 'engine caption artifact');
    const receiptBinding = exactKeys(result.caption_receipt, [
      'file', 'sha256', 'bytes',
    ], 'engine caption receipt binding');
    const fontBinding = exactKeys(result.font, [
      'file', 'sha256', 'bytes',
    ], 'engine caption font binding');
    const overlay = exactKeys(result.overlay, [
      'caption_y', 'band_height', 'pixel_evidence',
    ], 'engine caption overlay');
    if (artifact.file !== path.basename(captionOutput) ||
        !lowercaseSha256(artifact.sha256) ||
        !Number.isSafeInteger(artifact.bytes) || artifact.bytes < 1 ||
        artifact.duration_ms !== CAPTION_DURATION_MS ||
        artifact.width !== CAPTION_WIDTH || artifact.height !== CAPTION_HEIGHT ||
        artifact.fps_milli !== CAPTION_FPS_MILLI ||
        receiptBinding.file !== 'CAPTION_RENDER_RECEIPT.json' ||
        !lowercaseSha256(receiptBinding.sha256) ||
        !Number.isSafeInteger(receiptBinding.bytes) || receiptBinding.bytes < 1 ||
        fontBinding.file !== 'WorkSans-Variable.ttf' ||
        fontBinding.sha256 !== font.sha256 || fontBinding.bytes !== font.size ||
        overlay.caption_y !== CAPTION_Y ||
        overlay.band_height !== CAPTION_BAND_HEIGHT ||
        !plainObject(overlay.pixel_evidence)) {
      fail('engine caption render bindings were invalid');
    }
    const output = stableBoundedFile(
      captionOutput, session, 'caption render artifact', 64 * 1024 * 1024);
    const receiptFile = stableBoundedFile(
      path.join(session, 'CAPTION_RENDER_RECEIPT.json'), session,
      'caption render receipt');
    if (output.sha256 !== artifact.sha256 || output.size !== artifact.bytes ||
        receiptFile.sha256 !== receiptBinding.sha256 ||
        receiptFile.size !== receiptBinding.bytes) {
      fail('caption render artifact or receipt binding drifted');
    }
    let receipt;
    try { receipt = JSON.parse(receiptFile.bytes.toString('utf8')); }
    catch (_) { fail('caption render receipt was invalid'); }
    validateCaptionRenderReceipt(receipt);
    const media = await probeMedia(captionOutput, signal);
    const video = media?.streams?.find((stream) => stream?.codec_type === 'video');
    const durationMs = Math.round(finiteNumber(
      media?.format?.duration, 'caption output duration') * 1000);
    const [fpsNumerator, fpsDenominator] = String(video?.r_frame_rate || '')
      .split('/').map(Number);
    const fpsMilli = Math.round(fpsNumerator / fpsDenominator * 1000);
    if (durationMs !== CAPTION_DURATION_MS || video?.width !== CAPTION_WIDTH ||
        video?.height !== CAPTION_HEIGHT || fpsMilli !== CAPTION_FPS_MILLI) {
      fail('caption render output timeline was invalid');
    }
    const pixels = await captionPixelEvidence(signal);
    if (stableJson(pixels) !== stableJson(overlay.pixel_evidence)) {
      fail('engine caption pixel evidence did not match independent decoding');
    }
    return {
      status: 'pass',
      measurements: measurements([
        ['caption_event_count', 'count', 1],
        ['caption_state_count', 'count', 3],
        ['duration_ms', 'ms', durationMs],
      ]),
      evidence: evidence('caption_rendering', {
        artifact_sha256: output.sha256,
        caption_receipt_sha256: receiptFile.sha256,
        font_sha256: font.sha256,
        renderer: 'production-karaoke-band-fixed-words',
        pixel_method: 'decoded-fixed-lane-frame-deltas',
        asr_executed: false,
        semantic_vision_executed: false,
      }),
    };
  }

  async function projectGeneratedSfx(signal) {
    const source = await ensureSfxFixture(signal);
    const engineResult = await command(runtime.engine, [
      '--sfx-production-self-test', sfxSource, sfxOutput, session,
    ], { signal, timeoutMs: SFX_PRODUCTION_TIMEOUT_MS });
    const event = typedJsonEvent(
      engineResult.stdout, 'autoeditor-engine-sfx-production-self-test',
      'engine SFX production evidence');
    exactKeys(event, [
      'event', 'schema_version', 'checks', 'errors', 'result',
    ], 'engine SFX production evidence');
    if (event.schema_version !== SFX_ENGINE_SCHEMA ||
        !plainObject(event.errors) || Object.keys(event.errors).length !== 0) {
      fail('engine SFX production evidence was invalid');
    }
    const checks = exactKeys(event.checks, [
      'decoded_cue_placement', 'independent_evidence_verifier',
      'production_sfx_planner', 'production_sfx_renderer',
      'project_generated_rights', 'tamper_rejected',
    ], 'engine SFX production checks');
    if (Object.values(checks).some((value) => value !== true)) {
      fail('engine SFX production self-test did not attest every check');
    }
    const result = exactKeys(event.result, [
      'artifact', 'decoded_placement', 'evidence', 'production_receipt',
    ], 'engine SFX production result');
    const artifact = exactKeys(result.artifact, [
      'bytes', 'duration_ms', 'file', 'sha256',
    ], 'engine SFX artifact');
    const receiptBinding = exactKeys(result.production_receipt, [
      'bytes', 'contract_sha256', 'file', 'sha256',
    ], 'engine SFX production receipt binding');
    const placement = exactKeys(result.decoded_placement, [
      'control_delta_rms_millionths', 'control_window_duration_ms',
      'control_window_start_ms', 'cue_delta_rms_millionths',
      'cue_window_duration_ms', 'cue_window_start_ms',
      'expected_end_ms', 'expected_start_ms',
    ], 'engine SFX decoded placement');
    const evidenceSummary = exactKeys(result.evidence, [
      'external_service_used', 'generation_sidecar_count',
      'rights_basis', 'sidecar_count',
    ], 'engine SFX evidence summary');
    if (artifact.file !== path.basename(sfxOutput) ||
        artifact.duration_ms !== 3000 || !Number.isSafeInteger(artifact.bytes) ||
        artifact.bytes < 1 || !lowercaseSha256(artifact.sha256) ||
        receiptBinding.file !== 'SFX_PRODUCTION_RECEIPT.json' ||
        !Number.isSafeInteger(receiptBinding.bytes) || receiptBinding.bytes < 1 ||
        !lowercaseSha256(receiptBinding.sha256) ||
        !lowercaseSha256(receiptBinding.contract_sha256) ||
        placement.expected_start_ms !== 460 || placement.expected_end_ms !== 1260 ||
        placement.cue_window_start_ms !== 560 ||
        placement.cue_window_duration_ms !== 500 ||
        placement.control_window_start_ms !== 1560 ||
        placement.control_window_duration_ms !== 500 ||
        !Number.isSafeInteger(placement.cue_delta_rms_millionths) ||
        !Number.isSafeInteger(placement.control_delta_rms_millionths) ||
        placement.cue_delta_rms_millionths < Math.max(
          500, placement.control_delta_rms_millionths * 8 + 100) ||
        evidenceSummary.external_service_used !== false ||
        evidenceSummary.generation_sidecar_count !== 1 ||
        evidenceSummary.rights_basis !== 'project_owned' ||
        evidenceSummary.sidecar_count !== 9) {
      fail('engine SFX production result bindings were invalid');
    }

    const output = stableBoundedFile(
      sfxOutput, session, 'SFX production artifact', 64 * 1024 * 1024);
    if (output.sha256 !== artifact.sha256 || output.size !== artifact.bytes ||
        output.sha256 === source.sha256) {
      fail('SFX production artifact identity was invalid');
    }
    const media = await probeMedia(sfxOutput, signal);
    const durationMs = Math.round(finiteNumber(
      media?.format?.duration, 'SFX production output duration') * 1000);
    const audio = media?.streams?.find((item) => item.codec_type === 'audio');
    if (durationMs !== 3000 || String(audio?.sample_rate) !== '48000' ||
        audio?.channels !== 2) {
      fail('SFX production output decode facts were invalid');
    }

    const evidenceRoot = path.join(
      session, 'SFX_PRODUCTION_SELF_TEST', 'evidence');
    const receiptFile = stableBoundedFile(
      path.join(evidenceRoot, receiptBinding.file), session,
      'SFX production receipt', 512 * 1024);
    if (receiptFile.sha256 !== receiptBinding.sha256 ||
        receiptFile.size !== receiptBinding.bytes) {
      fail('SFX production receipt file binding drifted');
    }
    const production = parseJsonObject(
      receiptFile.bytes, 'SFX production receipt');
    exactKeys(production, [
      'actual_duration_ms', 'authorization_id', 'cue_count',
      'cue_manifest_sha256', 'duration_band', 'engine_envelope_sha256',
      'execution_edit_policy_sha256', 'mode', 'output',
      'output_timeline_sha256', 'parent_edit_policy_sha256', 'policy',
      'program_input', 'project_intent_sha256', 'requested_preference',
      'schema_version', 'sfx_compile_receipt_sha256', 'sfx_plan_sha256',
      'sfx_render_receipt_sha256', 'sidecars', 'target_duration',
    ], 'SFX production receipt');
    if (sha256Bytes(Buffer.from(stableJson(production), 'utf8')) !==
          receiptBinding.contract_sha256 ||
        production.schema_version !== 'autoeditor-sfx-production-receipt/v1' ||
        production.mode !== 'rendered' || production.cue_count !== 1 ||
        production.actual_duration_ms !== 3000 || production.duration_band !== 'micro' ||
        production.requested_preference !== 'motivated_only' ||
        !plainObject(production.policy) || production.policy.usage !== 'motivated_only' ||
        production.policy.density !== 'sparse' ||
        production.parent_edit_policy_sha256 ===
          production.execution_edit_policy_sha256 ||
        !plainObject(production.output) ||
        production.output.sha256 !== output.sha256 ||
        production.output.bytes !== output.size ||
        production.output.duration_ms !== durationMs ||
        !plainObject(production.program_input) ||
        production.program_input.sha256 !== source.sha256 ||
        production.program_input.bytes !== source.bytes ||
        !Array.isArray(production.sidecars) || production.sidecars.length !== 9) {
      fail('SFX production receipt contract was invalid');
    }

    const sidecars = new Map();
    for (const raw of production.sidecars) {
      const binding = exactKeys(raw, [
        'bytes', 'file', 'sha256',
      ], 'SFX production sidecar binding');
      if (typeof binding.file !== 'string' ||
          !/^[A-Z][A-Z0-9_]{0,95}\.json$/.test(binding.file) ||
          !Number.isSafeInteger(binding.bytes) || binding.bytes < 1 ||
          !lowercaseSha256(binding.sha256) || sidecars.has(binding.file)) {
        fail('SFX production sidecar binding was invalid');
      }
      const file = stableBoundedFile(
        path.join(evidenceRoot, binding.file), session,
        `SFX production ${binding.file}`, 2 * 1024 * 1024);
      if (file.sha256 !== binding.sha256 || file.size !== binding.bytes) {
        fail('SFX production sidecar bytes drifted');
      }
      sidecars.set(binding.file, {
        binding, value: parseJsonObject(file.bytes, `SFX ${binding.file}`),
      });
    }
    const requiredNames = [
      'SFX_BOUNDARY_ANCHOR_EVIDENCE.json', 'SFX_COMPILE_RECEIPT.json',
      'SFX_CUE_MANIFEST.json', 'SFX_EDL_ANCHOR_EVIDENCE.json',
      'SFX_EXECUTION_EDIT_POLICY.json', 'SFX_GENERATION_WHOOSH.json',
      'SFX_PLAN.json', 'SFX_RENDER_RECEIPT.json', 'SFX_SPEECH_EVIDENCE.json',
    ];
    if (requiredNames.some((name) => !sidecars.has(name)) ||
        sidecars.size !== requiredNames.length) {
      fail('SFX production sidecar inventory was incomplete');
    }
    const generationItem = sidecars.get('SFX_GENERATION_WHOOSH.json');
    const generation = exactKeys(generationItem.value, [
      'asset', 'generator', 'kind', 'parameters', 'rights', 'schema_version',
    ], 'SFX generation evidence');
    const rights = exactKeys(generation.rights, [
      'basis', 'external_service_used', 'license_id', 'licensor',
    ], 'SFX generation rights');
    const generatedAsset = exactKeys(generation.asset, [
      'bytes', 'sha256',
    ], 'SFX generated asset binding');
    if (generation.schema_version !== 'autoeditor-sfx-generation-evidence/v1' ||
        generation.generator !== 'autoeditor-deterministic-pcm/v1' ||
        generation.kind !== 'whoosh' || rights.basis !== 'project_owned' ||
        rights.license_id !== 'project-generated' || rights.licensor !== 'project' ||
        rights.external_service_used !== false ||
        !lowercaseSha256(generatedAsset.sha256) ||
        !Number.isSafeInteger(generatedAsset.bytes) || generatedAsset.bytes < 1) {
      fail('SFX generated asset rights evidence was invalid');
    }
    const manifest = sidecars.get('SFX_CUE_MANIFEST.json').value;
    const plan = sidecars.get('SFX_PLAN.json').value;
    const renderReceipt = sidecars.get('SFX_RENDER_RECEIPT.json').value;
    if (!Array.isArray(manifest.assets) || manifest.assets.length !== 1 ||
        manifest.assets[0].sha256 !== generatedAsset.sha256 ||
        manifest.assets[0].byte_length !== generatedAsset.bytes ||
        manifest.assets[0].provenance !== 'project_generated' ||
        manifest.assets[0].license?.basis !== 'project_owned' ||
        manifest.assets[0].license?.evidence_sha256 !==
          generationItem.binding.sha256 ||
        !Array.isArray(plan.cues) || plan.cues.length !== 1 ||
        plan.cues[0].placement?.start_ms !== placement.expected_start_ms ||
        plan.cues[0].placement?.trim_duration_ms !==
          placement.expected_end_ms - placement.expected_start_ms ||
        renderReceipt.cue_count !== 1 || renderReceipt.render_mode !== 'mixed' ||
        renderReceipt.output?.sha256 !== output.sha256 ||
        renderReceipt.output?.bytes !== output.size) {
      fail('SFX production plan, rights, or render chain was invalid');
    }

    return {
      status: 'pass',
      measurements: measurements([
        ['cue_count', 'count', 1],
        ['cue_delta_rms_millionths', 'millionths',
          placement.cue_delta_rms_millionths],
        ['evidence_sidecar_count', 'count', sidecars.size],
        ['output_duration_ms', 'ms', durationMs],
        ['rights_tamper_rejected', 'boolean', 1],
      ]),
      evidence: evidence('project_generated_sfx', {
        output_sha256: output.sha256,
        production_receipt_sha256: receiptFile.sha256,
        production_contract_sha256: receiptBinding.contract_sha256,
        generator: generation.generator,
        rights_basis: rights.basis,
        external_service_used: false,
        decoded_placement: true,
        tamper_rejected: true,
      }),
    };
  }

  async function projectGeneratedMusic(signal) {
    if (!musicPromise) {
      musicPromise = (async () => {
        await command(runtime.ffmpeg, [
          '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
          '-f', 'lavfi', '-i', 'color=c=0x142238:s=160x90:r=30:d=4.000',
          '-f', 'lavfi', '-i',
          'sine=frequency=880:sample_rate=48000:duration=1.100',
          '-filter_complex',
          '[1:a]adelay=1450:all=1,apad=whole_dur=4,' +
            'atrim=duration=4,aformat=sample_rates=48000:' +
            'channel_layouts=stereo[a]',
          '-map', '0:v:0', '-map', '[a]', '-c:v', 'libx264',
          '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
          '-ar', '48000', '-ac', '2', '-shortest', musicSource,
        ], { signal });
        const source = stableBoundedFile(
          musicSource, session, 'fixed music source fixture',
          64 * 1024 * 1024);
        const sourceMedia = await probeMedia(musicSource, signal);
        const sourceAudio = sourceMedia?.streams?.find((item) =>
          item.codec_type === 'audio');
        const sourceDurationMs = Math.round(finiteNumber(
          sourceMedia?.format?.duration,
          'fixed music source duration') * 1000);
        if (sourceDurationMs !== 4000 ||
            String(sourceAudio?.sample_rate) !== '48000' ||
            sourceAudio?.channels !== 2) {
          fail('fixed music source fixture was invalid');
        }
        const engineResult = await command(runtime.engine, [
          '--music-production-self-test', musicSource, musicOutput, session,
        ], { signal, timeoutMs: MUSIC_PRODUCTION_TIMEOUT_MS });
        const event = typedJsonEvent(
          engineResult.stdout, MUSIC_ENGINE_EVENT,
          'engine music production evidence');
        exactKeys(event, [
          'checks', 'errors', 'event', 'result', 'schema_version',
        ], 'engine music production evidence');
        if (event.schema_version !== MUSIC_ENGINE_SCHEMA ||
            !plainObject(event.errors) || Object.keys(event.errors).length !== 0) {
          fail('engine music production evidence was invalid');
        }
        const checks = exactKeys(event.checks, [
          'decoded_music_placement', 'dialogue_masking',
          'independent_evidence_verifier', 'measured_loudness',
          'omission_rejected', 'production_music_planner',
          'production_music_renderer', 'project_generated_rights',
          'tamper_rejected',
        ], 'engine music production checks');
        if (Object.values(checks).some((value) => value !== true)) {
          fail('engine music production self-test did not attest every check');
        }
        const result = exactKeys(event.result, [
          'artifact', 'decoded_placement', 'evidence', 'measured_audio',
          'production_receipt',
        ], 'engine music production result');
        const artifact = exactKeys(result.artifact, [
          'bytes', 'duration_ms', 'file', 'sha256',
        ], 'engine music artifact');
        const receiptBinding = exactKeys(result.production_receipt, [
          'bytes', 'contract_sha256', 'file', 'sha256',
        ], 'engine music production receipt binding');
        const placement = exactKeys(result.decoded_placement, [
          'bed_delta_rms_millionths', 'bed_music_tone_millionths',
          'bed_window_duration_ms', 'bed_window_start_ms',
          'dialogue_delta_rms_millionths',
          'dialogue_music_tone_millionths',
          'dialogue_window_duration_ms', 'dialogue_window_start_ms',
          'expected_end_ms', 'expected_start_ms',
        ], 'engine music decoded placement');
        const measured = exactKeys(result.measured_audio, [
          'integrated_loudness_millilufs', 'loudness_tolerance_millilufs',
          'passed', 'target_loudness_millilufs',
          'true_peak_ceiling_millidbtp', 'true_peak_millidbtp',
        ], 'engine music measured audio');
        const evidenceSummary = exactKeys(result.evidence, [
          'external_service_used', 'generation_sidecar_count',
          'rights_basis', 'sidecar_count',
        ], 'engine music evidence summary');
        if (artifact.file !== path.basename(musicOutput) ||
            artifact.duration_ms !== 4000 ||
            !Number.isSafeInteger(artifact.bytes) || artifact.bytes < 1 ||
            !lowercaseSha256(artifact.sha256) ||
            receiptBinding.file !== 'MUSIC_PRODUCTION_RECEIPT.json' ||
            !Number.isSafeInteger(receiptBinding.bytes) ||
            receiptBinding.bytes < 1 ||
            !lowercaseSha256(receiptBinding.sha256) ||
            !lowercaseSha256(receiptBinding.contract_sha256) ||
            !Number.isSafeInteger(placement.expected_start_ms) ||
            !Number.isSafeInteger(placement.expected_end_ms) ||
            placement.expected_end_ms <= placement.expected_start_ms ||
            placement.expected_start_ms < 0 || placement.expected_end_ms > 4000 ||
            placement.bed_window_duration_ms !== 500 ||
            placement.dialogue_window_duration_ms !== 500 ||
            placement.dialogue_window_start_ms < 1450 ||
            placement.dialogue_window_start_ms +
              placement.dialogue_window_duration_ms > 2550 ||
            !Number.isSafeInteger(placement.bed_delta_rms_millionths) ||
            !Number.isSafeInteger(placement.dialogue_delta_rms_millionths) ||
            !Number.isSafeInteger(placement.bed_music_tone_millionths) ||
            !Number.isSafeInteger(placement.dialogue_music_tone_millionths) ||
            placement.bed_music_tone_millionths < Math.max(
              100, placement.dialogue_music_tone_millionths * 8) ||
            measured.passed !== true ||
            !Number.isSafeInteger(measured.integrated_loudness_millilufs) ||
            !Number.isSafeInteger(measured.target_loudness_millilufs) ||
            !Number.isSafeInteger(measured.loudness_tolerance_millilufs) ||
            Math.abs(measured.integrated_loudness_millilufs -
              measured.target_loudness_millilufs) >
              measured.loudness_tolerance_millilufs ||
            !Number.isSafeInteger(measured.true_peak_millidbtp) ||
            !Number.isSafeInteger(measured.true_peak_ceiling_millidbtp) ||
            measured.true_peak_millidbtp > measured.true_peak_ceiling_millidbtp ||
            evidenceSummary.external_service_used !== false ||
            evidenceSummary.generation_sidecar_count !== 1 ||
            evidenceSummary.rights_basis !== 'project_owned' ||
            evidenceSummary.sidecar_count !== 10) {
          fail('engine music production result bindings were invalid');
        }
        const output = stableBoundedFile(
          musicOutput, session, 'music production artifact',
          64 * 1024 * 1024);
        if (output.sha256 !== artifact.sha256 || output.size !== artifact.bytes ||
            output.sha256 === source.sha256) {
          fail('music production artifact identity was invalid');
        }
        const outputMedia = await probeMedia(musicOutput, signal);
        const outputAudio = outputMedia?.streams?.find((item) =>
          item.codec_type === 'audio');
        const outputDurationMs = Math.round(finiteNumber(
          outputMedia?.format?.duration,
          'music production output duration') * 1000);
        if (outputDurationMs !== 4000 ||
            String(outputAudio?.sample_rate) !== '48000' ||
            outputAudio?.channels !== 2) {
          fail('music production output decode facts were invalid');
        }
        const evidenceRoot = path.join(
          session, 'MUSIC_PRODUCTION_SELF_TEST', 'evidence');
        const receiptFile = stableBoundedFile(
          path.join(evidenceRoot, receiptBinding.file), session,
          'music production receipt', 512 * 1024);
        if (receiptFile.sha256 !== receiptBinding.sha256 ||
            receiptFile.size !== receiptBinding.bytes) {
          fail('music production receipt file binding drifted');
        }
        const production = parseJsonObject(
          receiptFile.bytes, 'music production receipt');
        exactKeys(production, [
          'actual_duration_ms', 'added_coverage_ms', 'audio_qa',
          'authorization_id', 'capability_used', 'duration_band',
          'engine_envelope_sha256', 'execution_edit_policy_sha256', 'mode',
          'music_asset_manifest_sha256', 'music_compile_receipt_sha256',
          'music_plan_sha256', 'music_render_receipt_sha256', 'output',
          'output_timeline_sha256', 'parent_edit_policy_sha256', 'policy',
          'program_input', 'project_intent_sha256', 'region_count',
          'requested_preference', 'rights', 'schema_version', 'sidecars',
          'target_duration',
        ], 'music production receipt');
        const rights = exactKeys(production.rights, [
          'basis', 'external_service_used', 'generator',
        ], 'music production rights');
        const policy = exactKeys(production.policy, [
          'duck_under_dialogue', 'usage',
        ], 'music production policy');
        if (sha256Bytes(Buffer.from(stableJson(production), 'utf8')) !==
              receiptBinding.contract_sha256 ||
            production.schema_version !==
              'autoeditor-music-production-receipt/v1' ||
            production.mode !== 'rendered' ||
            production.capability_used !== 'project_generated_music' ||
            production.region_count !== 1 || production.added_coverage_ms < 20 ||
            production.actual_duration_ms !== 4000 ||
            production.requested_preference !== 'supporting' ||
            policy.usage !== 'supporting' ||
            rights.basis !== 'project_owned' ||
            rights.generator !== 'autoeditor-deterministic-musical-pcm/v1' ||
            rights.external_service_used !== false ||
            production.output?.sha256 !== output.sha256 ||
            production.output?.bytes !== output.size ||
            production.output?.duration_ms !== 4000 ||
            production.program_input?.sha256 !== source.sha256 ||
            production.program_input?.bytes !== source.size ||
            production.program_input?.duration_ms !== 4000 ||
            !Array.isArray(production.sidecars) ||
            production.sidecars.length !== 10 ||
            stableJson(production.audio_qa) !== stableJson(measured)) {
          fail('music production receipt contract was invalid');
        }
        const sidecars = new Map();
        for (const raw of production.sidecars) {
          const binding = exactKeys(raw, [
            'bytes', 'file', 'sha256',
          ], 'music production sidecar binding');
          if (typeof binding.file !== 'string' ||
              !/^[A-Z][A-Z0-9_]{0,95}\.(?:json|wav)$/.test(binding.file) ||
              sidecars.has(binding.file) ||
              !Number.isSafeInteger(binding.bytes) || binding.bytes < 1 ||
              !lowercaseSha256(binding.sha256)) {
            fail('music production sidecar binding was invalid');
          }
          const file = stableBoundedFile(
            path.join(evidenceRoot, binding.file), session,
            `music production ${binding.file}`, 16 * 1024 * 1024);
          if (file.sha256 !== binding.sha256 || file.size !== binding.bytes) {
            fail('music production sidecar bytes drifted');
          }
          sidecars.set(binding.file, file);
        }
        const required = [
          'MUSIC_ASSET_MANIFEST.json', 'MUSIC_AUDIO_QA.json',
          'MUSIC_COMPILE_RECEIPT.json', 'MUSIC_EXECUTION_EDIT_POLICY.json',
          'MUSIC_GENERATION_EVIDENCE.json', 'MUSIC_PLAN.json',
          'MUSIC_PROJECT_BED.wav', 'MUSIC_RENDER_RECEIPT.json',
          'MUSIC_SOURCE_ANALYSIS.json', 'MUSIC_SPEECH_EVIDENCE.json',
        ];
        if (required.some((name) => !sidecars.has(name)) ||
            sidecars.size !== required.length) {
          fail('music production sidecar inventory was incomplete');
        }
        const generation = parseJsonObject(
          sidecars.get('MUSIC_GENERATION_EVIDENCE.json').bytes,
          'music generation evidence');
        const generationRights = generation?.rights;
        if (generation?.generator !==
              'autoeditor-deterministic-musical-pcm/v1' ||
            generationRights?.basis !== 'project_owned' ||
            generationRights?.external_service_used !== false) {
          fail('music generation rights evidence was invalid');
        }
        return { event, output, receiptFile, placement, measured };
      })();
    }
    const proof = await musicPromise;
    return {
      status: 'pass',
      measurements: measurements([
        ['added_region_count', 'count', 1],
        ['dialogue_masking_verified', 'boolean', 1],
        ['evidence_sidecar_count', 'count', 10],
        ['output_duration_ms', 'ms', 4000],
        ['rights_tamper_rejected', 'boolean', 1],
      ]),
      evidence: evidence('project_generated_music', {
        output_sha256: proof.output.sha256,
        production_receipt_sha256: proof.receiptFile.sha256,
        generator: 'autoeditor-deterministic-musical-pcm/v1',
        rights_basis: 'project_owned',
        external_service_used: false,
        dialogue_masking_verified: true,
        measured_loudness_verified: proof.measured.passed,
        tamper_rejected: true,
      }),
    };
  }

  async function runCheck(context = {}) {
    const { id, signal } = context;
    if (typeof id !== 'string' || !CHECK_ID_SET.has(id)) {
      fail('capability check id is unsupported');
    }
    if (signal?.aborted) fail('capability check was canceled');
    const expectedContract = Buffer.from(
      `autoeditor-runtime-capability-check-contract/${id}/v1`, 'utf8');
    const expectedFixture = Buffer.from(
      `autoeditor-runtime-capability-check-fixture/${id}/v1`, 'utf8');
    if (!Buffer.isBuffer(context.contractBytes) ||
        !context.contractBytes.equals(expectedContract) ||
        !Buffer.isBuffer(context.fixtureBytes) ||
        !context.fixtureBytes.equals(expectedFixture)) {
      fail('fixed capability contract or fixture binding is invalid');
    }
    const executables = context.runtime?.executables;
    const runtimeExecutables = Array.isArray(executables)
      ? executables.filter((item) => item &&
        typeof item.name === 'string' &&
        /^[0-9a-f]{64}$/.test(item.sha256 || ''))
      : [];
    const validExecutables = runtimeExecutables
      .filter((item) =>
        TRUSTED_CODE_FILE_NAMES.has(item.name) &&
        /^[0-9a-f]{64}$/.test(item.sha256 || ''));
    const codeNames = new Set(validExecutables.map((item) => item.name));
    if (!codeNames.has('desktop-app-asar') &&
        !REQUIRED_DEVELOPMENT_CODE_FILES.every((name) => codeNames.has(name))) {
      fail('capability runner code is absent from the runtime identity');
    }
    const boundCaptionFont = validExecutables.find((item) =>
      item.name === 'caption-font');
    const boundSmallModel = validExecutables.find((item) =>
      item.name === 'whisper-small-model');
    const oneRuntimeBinding = (name) => {
      const matches = runtimeExecutables.filter((item) => item.name === name);
      return matches.length === 1 ? matches[0] : null;
    };
    const withRuntimePath = (name) => {
      const binding = oneRuntimeBinding(name);
      return binding ? { ...binding, path: runtime[name] } : null;
    };
    const renderBindings = {
      engine: withRuntimePath('engine'),
      ffmpeg: withRuntimePath('ffmpeg'),
      ffprobe: withRuntimePath('ffprobe'),
      probe: oneRuntimeBinding('render-capability-runtime-probe'),
    };
    if (id === 'caption_rendering' && !boundCaptionFont) {
      fail('caption font is absent from the runtime identity');
    }
    if (FIXTURELESS_CHECKS.has(id)) {
      return {
        status: 'fail',
        measurements: measurements([
          ['fixed_fixture_available', 'boolean', 0],
        ]),
        evidence: evidence(id, {
          executed: false,
          reason: 'no_fixed_production_fixture',
        }),
      };
    }
    switch (id) {
      case 'artifact_receipts': return artifactReceipts(signal);
      case 'audio_crossfades': return renderCapability(
        id, signal, renderBindings);
      case 'audio_quality_analysis': return audioQuality(signal);
      case 'caption_rendering': return captionRendering(
        signal, boundCaptionFont.sha256);
      case 'chart_rendering': return creative(id, signal);
      case 'color_normalization': return renderCapability(
        id, signal, renderBindings);
      case 'cross_dissolves': return renderCapability(
        id, signal, renderBindings);
      case 'graphic_rendering': return creative(id, signal);
      case 'hard_cuts': return hardCuts(signal);
      case 'dialogue_cleanup': return dialogueCleanup(
        signal, boundSmallModel?.sha256);
      case 'loudness_normalization': return loudness(signal);
      case 'motion_quality_analysis': return renderCapability(
        id, signal, renderBindings);
      case 'project_generated_music': return projectGeneratedMusic(signal);
      case 'project_generated_sfx': return projectGeneratedSfx(signal);
      case 'scene_detection': return sceneDetection(signal);
      case 'speech_transcription': return asrCapability(
        id, signal, boundSmallModel?.sha256);
      case 'word_timestamps': return asrCapability(
        id, signal, boundSmallModel?.sha256);
      default: fail('capability check has no fixed implementation');
    }
  }

  runCheck.cancel = () => {
    disposed = true;
    const pending = [...activeCommands];
    return pending.length
      ? Promise.allSettled(pending).then(() => undefined)
      : Promise.resolve();
  };
  runCheck.dispose = () => {
    if (disposalPromise) return disposalPromise;
    disposed = true;
    const pending = [...activeCommands];
    if (!pending.length) {
      safeRemoveSession(session, root);
      disposalPromise = Promise.resolve();
      return disposalPromise;
    }
    disposalPromise = Promise.allSettled(pending).then(() => {
      safeRemoveSession(session, root);
    });
    return disposalPromise;
  };
  return runCheck;
}

module.exports = Object.freeze({
  CHECK_RUNNER_SCHEMA_VERSION,
  MAX_CAPTURE_BYTES,
  COMMAND_TIMEOUT_MS,
  CREATIVE_TIMEOUT_MS,
  SFX_PRODUCTION_TIMEOUT_MS,
  MUSIC_PRODUCTION_TIMEOUT_MS,
  FIXTURELESS_CHECKS: Object.freeze([...FIXTURELESS_CHECKS].sort()),
  RuntimeCapabilityCheckRunnerError,
  runBoundedCommand,
  createRuntimeCapabilityCheckRunner,
});
