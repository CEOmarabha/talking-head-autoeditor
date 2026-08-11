'use strict';

const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
  MODEL_ID,
  MODEL_REVISION,
  assistantText,
  fileFingerprint,
  parseSignalReport,
  sampleTimes,
  summarizeProbe,
} = require('../helper/lib/media-analysis');

assert.strictEqual(MODEL_ID, 'HuggingFaceTB/SmolVLM2-256M-Video-Instruct');
assert.strictEqual(MODEL_REVISION, '067788b187b95ebe7b2e040b3e4299e342e5b8fd');

assert.deepStrictEqual(sampleTimes(10, 4), [1.25, 3.75, 6.25, 8.75]);
assert.deepStrictEqual(sampleTimes(0, 4), [0]);

const probe = summarizeProbe({
  format: { duration: '12.3456', size: '4567', format_name: 'mov,mp4' },
  streams: [
    { codec_type: 'video', codec_name: 'h264', width: 1080, height: 1920,
      avg_frame_rate: '30000/1001' },
    { codec_type: 'audio', codec_name: 'aac', sample_rate: '48000', channels: 2 },
  ],
});
assert.strictEqual(probe.durationSeconds, 12.346);
assert.strictEqual(probe.video.fps, 29.97);
assert.strictEqual(probe.video.width, 1080);
assert.strictEqual(probe.audio.sampleRate, 48000);

const signals = parseSignalReport([
  'silence_start: 1.0', 'silence_end: 2.5 | silence_duration: 1.5',
  'mean_volume: -19.5 dB', 'max_volume: -1.2 dB',
].join('\n'), 'n: 0 pts_time: 3.2\nn: 1 pts_time: 7.8', 10);
assert.strictEqual(signals.silentSeconds, 1.5);
assert.strictEqual(signals.audibleCoveragePercent, 85);
assert.strictEqual(signals.detectedSceneChanges, 2);
assert.strictEqual(signals.meanVolumeDb, -19.5);

assert.strictEqual(assistantText('User: x\nAssistant: visible person and storefront'),
  'visible person and storefront');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'autoeditor-media-test-'));
try {
  const file = path.join(root, 'clip.mp4');
  fs.writeFileSync(file, Buffer.alloc(150000, 1));
  const first = fileFingerprint(file);
  const second = fileFingerprint(file);
  assert.strictEqual(first.digest, second.digest);
  const handle = fs.openSync(file, 'r+');
  fs.writeSync(handle, Buffer.from([9]), 0, 1, 149999);
  fs.closeSync(handle);
  const changed = fileFingerprint(file);
  assert.notStrictEqual(first.digest, changed.digest);
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}

const main = fs.readFileSync(path.join(__dirname, '..', 'helper', 'main.js'), 'utf8');
assert.ok(main.includes('await analyzeMedia({'));
assert.ok(main.includes("stage: 'media-analysis'"));
assert.ok(main.includes('describeFrames: (frames) => requestVision(frames, action)'));
assert.ok(main.includes("ipcMain.on('helper:vision-result'"));
assert.ok(!main.includes('transformers.node.mjs'));

const harness = fs.readFileSync(path.join(
  __dirname, '..', 'helper', 'lib', 'editing-harness.js'), 'utf8');
assert.ok(harness.includes('Private local media report:'));
assert.ok(harness.includes('original\nvideo was not uploaded to DeepSeek'));

const preload = fs.readFileSync(path.join(__dirname, '..', 'helper', 'preload.js'), 'utf8');
assert.ok(preload.includes("ipcRenderer.send('helper:vision-result'"));
assert.ok(preload.includes("on('helper-vision-request'"));

const renderer = fs.readFileSync(path.join(
  __dirname, '..', 'helper', 'renderer', 'app.js'), 'utf8');
assert.ok(renderer.includes("new Worker('../vision/vision-worker.bundle.js'"));
assert.ok(renderer.includes('window.helper.visionResult'));

const visionRoot = path.join(__dirname, '..', 'helper', 'vision');
const lock = JSON.parse(fs.readFileSync(path.join(
  visionRoot, 'vision-runtime.lock.json'), 'utf8'));
assert.strictEqual(lock.schema, 'autoeditor-local-vision-runtime/v1');
assert.strictEqual(lock.model.id, MODEL_ID);
assert.strictEqual(lock.model.revision, MODEL_REVISION);
assert.strictEqual(lock.model.license, 'Apache-2.0');
assert.strictEqual(lock.transformers_js.version, '4.2.0');

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

assert.strictEqual(sha256(path.join(visionRoot, lock.transformers_js.file)),
  lock.transformers_js.sha256);
for (const [file, expected] of Object.entries(lock.onnxruntime_web.files)) {
  assert.strictEqual(sha256(path.join(visionRoot, file)), expected);
}

const worker = fs.readFileSync(path.join(visionRoot, 'vision-worker.js'), 'utf8');
assert.ok(worker.includes(MODEL_ID));
assert.ok(worker.includes(MODEL_REVISION));
assert.ok(worker.includes("from './transformers.web.min.js'"));
assert.ok(worker.includes("device: 'webgpu'"));
assert.ok(worker.includes("device: 'wasm'"));
assert.strictEqual(sha256(path.join(visionRoot, lock.vision_worker.entry)),
  lock.vision_worker.entry_sha256);
assert.strictEqual(sha256(path.join(visionRoot, lock.vision_worker.bundle)),
  lock.vision_worker.bundle_sha256);

const runtime = JSON.parse(fs.readFileSync(path.join(
  __dirname, '..', '..', 'packaging', 'helper-runtime', 'package.json'), 'utf8'));
assert.strictEqual(runtime.dependencies['@huggingface/transformers'], undefined);

console.log('local media analysis contracts passed');
