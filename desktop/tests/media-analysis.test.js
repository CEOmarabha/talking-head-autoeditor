'use strict';

const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const {
  MODEL_ID,
  MODEL_REVISION,
  artifactCaptionRenderEvents,
  artifactVisionCoverage,
  artifactVisionPlan,
  assistantText,
  fileFingerprint,
  parseArtifactCaptions,
  parseSignalReport,
  sampleTimes,
  summarizeProbe,
  visionFrameBatches,
} = require('../helper/lib/media-analysis');

assert.strictEqual(MODEL_ID, 'HuggingFaceTB/SmolVLM2-256M-Video-Instruct');
assert.strictEqual(MODEL_REVISION, '067788b187b95ebe7b2e040b3e4299e342e5b8fd');

assert.deepStrictEqual(sampleTimes(10, 4), [0.1, 1, 2.5, 9.95]);

const fortyFiveSecondSamples = sampleTimes(45, 8);
assert.strictEqual(fortyFiveSecondSamples.length, 8);
assert.deepStrictEqual(fortyFiveSecondSamples.slice(0, 3), [0.1, 1, 2.5]);
assert.strictEqual(fortyFiveSecondSamples.at(-1), 44.95);
assert.ok(fortyFiveSecondSamples.some((time) => time > 15 && time < 30),
  '45-second sampling must cover the timeline interior');
assert.ok(fortyFiveSecondSamples.some((time) => time > 33 && time < 44.95),
  '45-second sampling must cover the late interior before the final frame');

const twoMinuteSamples = sampleTimes(154, 8);
assert.strictEqual(twoMinuteSamples.length, 8);
assert.deepStrictEqual(twoMinuteSamples.slice(0, 3), [0.1, 1, 2.5]);
assert.strictEqual(twoMinuteSamples.at(-1), 153.95);
assert.ok(twoMinuteSamples.some((time) => time > 70 && time < 110),
  '154-second sampling must cover the middle of the artifact');
assert.ok(twoMinuteSamples.some((time) => time > 115 && time < 145),
  '154-second sampling must cover the late interior before the final frame');
assert.deepStrictEqual(sampleTimes(0, 4), [0]);

const plannedEdl = {
  timeline_space: 'post_cut_seconds',
  punch_ins: [{ s: 0.5, e: 1.5 }],
  broll: [],
  graphics: [{ s: 12, e: 14 }],
  transitions: [{ s: 31, e: 31.2 }],
};
assert.ok(!fortyFiveSecondSamples.includes(13),
  'the legacy generic eight-frame spread demonstrates the 12-14s blind spot');
const artifactPlan = artifactVisionPlan(45, plannedEdl);
const graphicFrame = artifactPlan.frames.find((frame) =>
  frame.targets.some((target) => target.id === 'edl-graphics-001'));
assert.ok(graphicFrame, 'every planned graphic must add an exact event frame');
assert.strictEqual(graphicFrame.timeSeconds, 13,
  'the planned 12-14s graphic must be sampled at its midpoint');
assert.ok(artifactPlan.frames.some((frame) =>
  frame.targets.some((target) => target.category === 'hook')));
assert.ok(artifactPlan.frames.some((frame) =>
  frame.targets.some((target) => target.category === 'timeline')));
assert.ok(artifactPlan.frames.some((frame) =>
  frame.targets.some((target) => target.category === 'transitions')));
const transitionTargets = artifactPlan.frames.flatMap((frame) => frame.targets)
  .filter((target) => target.id.startsWith('edl-transitions-001-'));
assert.deepStrictEqual(transitionTargets.map((target) => target.sample),
  ['before', 'midpoint', 'after'],
  'a transition must be inspected on both sides as well as at its midpoint');

const genericPlan = artifactVisionPlan(45, null);
assert.strictEqual(genericPlan.edlBound, false);
assert.ok(genericPlan.frames.length > 0,
  'a successful baseline render must still receive generic final vision coverage');
assert.throws(() => artifactVisionPlan(45, null, { requireEdl: true }),
  /requires a final EDL/,
  'an approved premium edit must continue to fail closed without its EDL');

const captionEvents = parseArtifactCaptions([
  '1', '00:00:00,500 --> 00:00:02,000', 'Readable opening caption', '',
  '2', '00:00:12,000 --> 00:00:14,000', 'Caption over the key graphic', '',
].join('\n'), 45);
assert.strictEqual(captionEvents.length, 2);
const exactCaptionEvents = artifactCaptionRenderEvents({
  schema: 'autoeditor-caption-render-receipt/v1',
  timeline: 'post_cut_seconds', delivery_mode: 'burned', renderer: 'karaoke-band',
  mechanical_qa: { layout_safe: true, subject_clear: true,
    pixel_quality: { ok: true } },
  events: [{ index: 1, start_seconds: 0.5, end_seconds: 2,
    text: 'Readable opening caption', state_count: 3 }],
}, 45);
assert.deepStrictEqual(exactCaptionEvents, [{
  index: 1, startSeconds: 0.5, endSeconds: 2,
  text: 'Readable opening caption', stateCount: 3,
}]);
assert.throws(() => artifactCaptionRenderEvents({
  schema: 'autoeditor-caption-render-receipt/v1',
  timeline: 'post_cut_seconds', delivery_mode: 'burned', renderer: 'karaoke-band',
  mechanical_qa: { layout_safe: true, subject_clear: true,
    pixel_quality: { ok: true } },
  events: [{ index: 1, start_seconds: 0.5, end_seconds: 2,
    text: 'Caption', state_count: 0 }],
}, 45), /caption-render event/);
const renderedCaptionPlan = artifactVisionPlan(45, plannedEdl, {
  captions: exactCaptionEvents,
});
const renderedCaptionTarget = renderedCaptionPlan.frames.flatMap(
  (frame) => frame.targets).find((target) => target.id === 'caption-0001');
assert.match(renderedCaptionTarget.expectation, /"stateCount":3/,
  'the visual prompt must preserve exact burned-caption state evidence');
const captionPlan = artifactVisionPlan(45, plannedEdl, { captions: captionEvents });
for (const caption of captionEvents) {
  assert.ok(captionPlan.frames.some((frame) => frame.targets.some((target) =>
    target.id === `caption-${String(caption.index).padStart(4, '0')}`)),
  `caption ${caption.index} must be represented in the exact visual plan`);
}

const longCaptionReceipt = {
  schema: 'autoeditor-caption-render-receipt/v1',
  timeline: 'post_cut_seconds', delivery_mode: 'burned', renderer: 'karaoke-band',
  mechanical_qa: { layout_safe: true, subject_clear: true,
    pixel_quality: { ok: true } },
  events: Array.from({ length: 240 }, (_, index) => ({
    index: index + 1,
    start_seconds: Number((index * 1.2).toFixed(3)),
    end_seconds: Number((index * 1.2 + 0.9).toFixed(3)),
    text: `Caption ${index + 1}`,
    state_count: 2,
  })),
};
const longCaptions = artifactCaptionRenderEvents(longCaptionReceipt, 300);
assert.strictEqual(longCaptions.length, 240,
  'all caption render events must be mechanically validated before sampling');
const longBoundaries = {
  schema: 'autoeditor-edit-boundaries/v1', timeline: 'post_cut_seconds',
  cuts: [{ index: 0, time_seconds: 100, removed_seconds: 4 }],
  transitions: [], transition_support: 'not_implemented',
};
const longPlan = artifactVisionPlan(300, {
  ...plannedEdl,
  transitions: [],
  graphics: [{ s: 120, e: 124 }],
}, { captions: longCaptions, boundaries: longBoundaries });
assert.ok(longPlan.frames.length <= 128,
  'caption vision sampling must keep the complete plan inside the fixed frame cap');
assert.strictEqual(longPlan.captionSampling.mechanicalEventCount, 240);
assert.ok(longPlan.captionSampling.visionSampledEventCount < 240);
assert.strictEqual(longPlan.captionSampling.exhaustiveMechanicalValidation, true);
assert.match(longPlan.captionSampling.policy, /timeline-stratified/);
assert.match(longPlan.captionSampling.samplingSha256, /^[0-9a-f]{64}$/);
assert.match(longPlan.captionSampling.mechanicalSha256, /^[0-9a-f]{64}$/);
assert.strictEqual(longPlan.captionSampling.sampledTargetIds[0], 'caption-0001');
assert.strictEqual(longPlan.captionSampling.sampledTargetIds.at(-1), 'caption-0240');
const sampledCaptionTimes = longPlan.frames.flatMap((frame) => frame.targets)
  .filter((target) => target.category === 'captions')
  .map((target) => target.timeSeconds);
assert.ok(sampledCaptionTimes.some((time) => time <= 2.5),
  'the bounded sample must retain hook/early caption evidence');
for (const [low, high] of [[60, 90], [135, 165], [210, 240]]) {
  assert.ok(sampledCaptionTimes.some((time) => time >= low && time <= high),
    `the bounded caption sample must cover the ${low}-${high}s timeline stratum`);
}
for (const mandatoryId of [
  'edl-punch_ins-001', 'edl-graphics-001',
  'cut-boundary-001-before', 'cut-boundary-001-after',
]) {
  assert.ok(longPlan.frames.some((frame) => frame.targets.some(
    (target) => target.id === mandatoryId)),
  `mandatory target ${mandatoryId} must never be sampled away`);
}
const longCaptured = longPlan.frames.map((frame) => ({
  ...frame, path: `${frame.id}.jpg`,
}));
const longTargetIds = longPlan.frames.flatMap((frame) =>
  frame.targets.map((target) => target.id));
const longCoverage = artifactVisionCoverage(longPlan, longCaptured, longTargetIds);
assert.strictEqual(longCoverage.complete, true);
assert.strictEqual(longCoverage.captionSampling.mechanicalEventCount, 240);
assert.strictEqual(longCoverage.captionSampling.visionSampledEventCount,
  longPlan.captionSampling.visionSampledEventCount);

const coTimedPlan = artifactVisionPlan(45, {
  ...plannedEdl,
  graphics: Array.from({ length: 12 }, () => ({ s: 12, e: 14 })),
});
const coTimedTargets = coTimedPlan.frames.flatMap((frame) => frame.targets)
  .filter((target) => target.category === 'graphics');
assert.strictEqual(coTimedTargets.length, 12,
  'dense co-timed mandatory targets must never be truncated');
assert.ok(coTimedPlan.frames.every((frame) => frame.targets.length <= 3),
  'dense targets must be deterministically chunked within the prompt contract');

const sidecarCaptionPlan = artifactVisionPlan(45, plannedEdl, {
  captions: [], captionDelivery: 'sidecar',
  captionMechanicalEventCount: 2, captionEvidenceSha256: 'b'.repeat(64),
});
assert.strictEqual(sidecarCaptionPlan.categories.captions.available, false);
assert.strictEqual(sidecarCaptionPlan.categories.captions.deliveryMode, 'sidecar');
assert.strictEqual(sidecarCaptionPlan.captionSampling.mechanicalEventCount, 2);
assert.strictEqual(sidecarCaptionPlan.captionSampling.visionSampledEventCount, 0);
assert.strictEqual(sidecarCaptionPlan.captionSampling.visionInapplicableEventCount, 2);
assert.ok(sidecarCaptionPlan.frames.every((frame) => frame.targets.every(
  (target) => target.category !== 'captions')),
'sidecar caption text must not become a burned-caption visual target');

const cutPlan = artifactVisionPlan(45, plannedEdl, {
  boundaries: {
    schema: 'autoeditor-edit-boundaries/v1', timeline: 'post_cut_seconds',
    cuts: [{ index: 0, time_seconds: 5, removed_seconds: 2 }],
    transitions: [], transition_support: 'not_implemented',
  },
});
const cutTargets = cutPlan.frames.flatMap((frame) => frame.targets)
  .filter((target) => target.id.startsWith('cut-boundary-001-'));
assert.deepStrictEqual(cutTargets.map((target) => target.sample),
  ['before', 'after'], 'a known edit splice must be watched on both sides');
assert.strictEqual(cutPlan.categories.transitions.available, false);

function manyCutPlan(count) {
  const duration = count * 10 + 10;
  return artifactVisionPlan(duration, null, {
    boundaries: {
      schema: 'autoeditor-edit-boundaries/v1', timeline: 'post_cut_seconds',
      cuts: Array.from({ length: count }, (_, index) => ({
        index, time_seconds: index * 10 + 5, removed_seconds: 1,
      })),
      transitions: [], transition_support: 'not_implemented',
    },
    editBoundaryEvidenceSha256: 'c'.repeat(64),
  });
}
for (const [count, expectedSampled] of [[60, 60], [61, 60], [121, 60]]) {
  const plan = manyCutPlan(count);
  assert.ok(plan.frames.length <= 128,
    `${count} cuts must remain within the global visual frame cap`);
  assert.strictEqual(plan.cutSampling.mechanicalCutCount, count);
  assert.strictEqual(plan.cutSampling.visionSampledCutCount, expectedSampled);
  assert.strictEqual(plan.cutSampling.visionOmittedCutCount,
    count - expectedSampled);
  assert.strictEqual(plan.cutSampling.exhaustiveMechanicalValidation, true);
  assert.strictEqual(plan.cutSampling.pairIntegrity, true);
  assert.strictEqual(plan.cutSampling.evidenceSha256, 'c'.repeat(64));
  assert.match(plan.cutSampling.mechanicalSha256, /^[0-9a-f]{64}$/);
  assert.match(plan.cutSampling.samplingSha256, /^[0-9a-f]{64}$/);
  assert.strictEqual(plan.cutSampling.sampledCutPairIds[0],
    'cut-boundary-001');
  assert.strictEqual(plan.cutSampling.sampledCutPairIds.at(-1),
    `cut-boundary-${String(count).padStart(3, '0')}`);
  const samplesByPair = new Map();
  for (const target of plan.frames.flatMap((frame) => frame.targets)
    .filter((target) => target.category === 'cuts')) {
    const pair = target.id.replace(/-(?:before|after)$/, '');
    if (!samplesByPair.has(pair)) samplesByPair.set(pair, []);
    samplesByPair.get(pair).push(target.sample);
  }
  assert.strictEqual(samplesByPair.size, expectedSampled);
  for (const samples of samplesByPair.values()) {
    assert.deepStrictEqual(samples.sort(), ['after', 'before'],
      'cut vision sampling must never split a before/after pair');
  }
}
assert.throws(() => artifactVisionPlan(45, plannedEdl, {
  boundaries: {
    schema: 'autoeditor-edit-boundaries/v1', timeline: 'post_cut_seconds',
    cuts: [], transition_support: 'not_implemented',
    transitions: [{ index: 0, s: 10, e: 11 }],
  },
}), /unsupported artifact transitions/);

const capturedArtifactFrames = artifactPlan.frames.map((frame) => ({
  ...frame, path: `${frame.id}.jpg`,
}));
const artifactBatches = visionFrameBatches(capturedArtifactFrames);
assert.ok(artifactBatches.length > 1,
  'EDL-aware coverage must not be truncated to the generic eight-frame budget');
assert.ok(artifactBatches.every((batch) => batch.length <= 8));
assert.deepStrictEqual(artifactBatches.flat().map((frame) => frame.id),
  capturedArtifactFrames.map((frame) => frame.id));

const allReviewed = artifactVisionCoverage(
  artifactPlan, capturedArtifactFrames,
  capturedArtifactFrames.flatMap((frame) =>
    frame.targets.map((target) => target.id)));
assert.strictEqual(allReviewed.complete, true);
assert.strictEqual(allReviewed.categories.graphics.status, 'reviewed');
assert.strictEqual(allReviewed.categories.broll.status, 'not-planned');

const withoutGraphicReview = artifactVisionCoverage(
  artifactPlan, capturedArtifactFrames,
  capturedArtifactFrames.filter((frame) => frame.id !== graphicFrame.id)
    .flatMap((frame) => frame.targets.map((target) => target.id)));
assert.strictEqual(withoutGraphicReview.complete, false);
assert.ok(withoutGraphicReview.unobservedCategories.includes('graphics'));
assert.ok(withoutGraphicReview.unreviewedFrameIds.includes(graphicFrame.id));
assert.ok(withoutGraphicReview.unreviewedTargetIds.includes('edl-graphics-001'));
assert.throws(() => artifactVisionPlan(45, {
  ...plannedEdl, graphics: [{ s: 12, e: 46 }],
}), /invalid span/);

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
const normalizedHarness = harness.replace(/\r\n/g, '\n');
assert.ok(normalizedHarness.includes('Private local media report:'));
assert.ok(normalizedHarness.includes('original\nvideo was not uploaded to DeepSeek'));

const preload = fs.readFileSync(path.join(__dirname, '..', 'helper', 'preload.js'), 'utf8');
assert.ok(preload.includes("ipcRenderer.send('helper:vision-result'"));
assert.ok(preload.includes("on('helper-vision-request'"));

const renderer = fs.readFileSync(path.join(
  __dirname, '..', 'helper', 'renderer', 'app.js'), 'utf8');
assert.ok(renderer.includes("new Worker('../vision/vision-worker.bundle.js'"));
assert.ok(renderer.includes('window.helper.visionResult'));

// Exercise the real renderer coordinator up to (but not including) the UI
// initialization. A timed-out/canceled request must destroy the busy worker,
// ignore its late message, and let the next request start on a fresh worker.
const coordinatorSource = renderer.split('const CHAT_HISTORY_MAX_ENTRIES')[0];
const bridge = {};
const results = [];
const workers = [];
class FakeWorker {
  constructor() { this.listeners = {}; this.messages = []; this.terminated = false;
    workers.push(this); }
  addEventListener(kind, callback) { this.listeners[kind] = callback; }
  postMessage(value) { this.messages.push(value); }
  terminate() { this.terminated = true; }
}
vm.runInNewContext(coordinatorSource, {
  document: { getElementById: () => null },
  Worker: FakeWorker,
  window: {
    AutoEditorChatState: { createConversationState: () => ({}) },
    AutoEditorViewState: {}, AutoEditorPreferenceForm: {},
    helper: {
      onVisionRequest: (callback) => { bridge.request = callback; },
      onVisionCancel: (callback) => { bridge.cancel = callback; },
      visionProgress: () => {}, visionResult: (value) => results.push(value),
    },
  },
});
bridge.request({ id: 1, images: ['data:image/jpeg;base64,AA=='] });
assert.strictEqual(workers.length, 1);
bridge.cancel({ id: 1, reason: 'timeout' });
assert.strictEqual(workers[0].terminated, true,
  'cancel must terminate the active inference worker');
bridge.request({ id: 2, images: ['data:image/jpeg;base64,AA=='] });
assert.strictEqual(workers.length, 2,
  'a request after cancel must start instead of receiving a permanent busy error');
workers[0].listeners.message({ data: { id: 1, status: 'complete', result: 'stale' } });
assert.strictEqual(results.length, 0, 'a canceled worker result must be ignored');
workers[1].listeners.message({ data: { id: 2, status: 'complete', result: 'fresh' } });
assert.deepStrictEqual(results.map((value) => value.result), ['fresh']);

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
