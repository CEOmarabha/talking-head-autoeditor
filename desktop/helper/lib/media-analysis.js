'use strict';

const crypto = require('crypto');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const MODEL_ID = 'HuggingFaceTB/SmolVLM2-256M-Video-Instruct';
const MODEL_REVISION = '067788b187b95ebe7b2e040b3e4299e342e5b8fd';
const CACHE_SCHEMA = 'autoeditor-local-media-analysis/v2';
const MAX_CAPTURE_BYTES = 2 * 1024 * 1024;
const MAX_TRANSCRIPT_CHARS = 30000;
const MAX_VISUAL_CHARS = 5000;
const MAX_FRAMES_TOTAL = 8;
const MAX_ARTIFACT_VISION_FRAMES = 128;
const MAX_ARTIFACT_TARGETS_PER_FRAME = 3;
const MAX_ARTIFACT_CAPTION_EVENTS = 10000;
const MAX_ARTIFACT_CUT_EVENTS = 10000;
const SAMPLE_BYTES = 64 * 1024;
const ARTIFACT_VISION_PLAN_SCHEMA = 'autoeditor-artifact-vision-plan/v2';
const ARTIFACT_VISION_COVERAGE_SCHEMA =
  'autoeditor-artifact-vision-coverage/v2';
const ARTIFACT_EVENT_LAYERS = Object.freeze([
  'punch_ins', 'broll', 'graphics', 'transitions',
]);
const EDIT_BOUNDARIES_SCHEMA = 'autoeditor-edit-boundaries/v1';
const CAPTION_SAMPLING_SCHEMA = 'autoeditor-caption-vision-sampling/v1';
const CAPTION_SAMPLING_POLICY =
  'all-if-fit-else-first-last-early-timeline-stratified/v1';
const CUT_SAMPLING_SCHEMA = 'autoeditor-cut-vision-sampling/v1';
const CUT_SAMPLING_POLICY =
  'all-if-fit-else-first-last-timeline-stratified-pairs/v1';

function bounded(value, maximum) {
  return String(value || '').replace(/\0/g, '').trim().slice(0, maximum);
}

function runCommand(command, args, {
  cwd, env, timeoutMs, onChild, onLine,
} = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd, env, windowsHide: true,
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.__autoeditorProcessGroup = process.platform !== 'win32';
    if (onChild) onChild(child);
    let stdout = Buffer.alloc(0);
    let stderr = Buffer.alloc(0);
    let lineBuffer = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGTERM'); } catch (_) { /* close owns cleanup */ }
      reject(new Error(`local media command exceeded ${Math.ceil(timeoutMs / 1000)} seconds`));
    }, timeoutMs);

    function collect(kind, chunk) {
      const current = kind === 'stdout' ? stdout : stderr;
      const remaining = MAX_CAPTURE_BYTES - current.length;
      if (remaining > 0) {
        const next = chunk.subarray(0, remaining);
        if (kind === 'stdout') stdout = Buffer.concat([stdout, next]);
        else stderr = Buffer.concat([stderr, next]);
      }
      if (!onLine) return;
      lineBuffer += chunk.toString('utf8');
      if (lineBuffer.length > MAX_CAPTURE_BYTES) lineBuffer = lineBuffer.slice(-MAX_CAPTURE_BYTES);
      let index;
      while ((index = lineBuffer.indexOf('\n')) >= 0) {
        const line = bounded(lineBuffer.slice(0, index).replace(/\r$/, ''), 2000);
        lineBuffer = lineBuffer.slice(index + 1);
        if (line) onLine(line);
      }
    }

    child.stdout.on('data', (chunk) => collect('stdout', chunk));
    child.stderr.on('data', (chunk) => collect('stderr', chunk));
    child.once('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    child.once('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const tail = bounded(lineBuffer, 2000);
      if (tail && onLine) onLine(tail);
      if (code !== 0) {
        reject(new Error(bounded(stderr.toString('utf8'), 1000) ||
          `local media command stopped with code ${code}`));
        return;
      }
      resolve({ stdout: stdout.toString('utf8'), stderr: stderr.toString('utf8') });
    });
  });
}

function fileFingerprint(file) {
  const handle = fs.openSync(file, 'r');
  try {
    const before = fs.fstatSync(handle);
    if (!before.isFile() || before.size < 1) throw new Error('attached video is empty');
    const firstSize = Math.min(SAMPLE_BYTES, before.size);
    const lastSize = Math.min(SAMPLE_BYTES, Math.max(0, before.size - firstSize));
    const first = Buffer.alloc(firstSize);
    const last = Buffer.alloc(lastSize);
    if (firstSize && fs.readSync(handle, first, 0, firstSize, 0) !== firstSize) {
      throw new Error('attached video changed while it was being read');
    }
    if (lastSize && fs.readSync(handle, last, 0, lastSize,
      before.size - lastSize) !== lastSize) {
      throw new Error('attached video changed while it was being read');
    }
    const after = fs.fstatSync(handle);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs) {
      throw new Error('attached video changed while it was being read');
    }
    const identity = `${before.size}:${before.mtimeMs}:${before.dev}:${before.ino}`;
    const digest = crypto.createHash('sha256').update(identity).update(first).update(last).digest('hex');
    return { digest, size: before.size, mtimeMs: before.mtimeMs };
  } finally {
    fs.closeSync(handle);
  }
}

function parseRate(value) {
  if (typeof value !== 'string') return 0;
  const [top, bottom = '1'] = value.split('/');
  const result = Number(top) / Number(bottom);
  return Number.isFinite(result) ? Math.round(result * 1000) / 1000 : 0;
}

function summarizeProbe(raw) {
  const format = raw && typeof raw.format === 'object' ? raw.format : {};
  const streams = Array.isArray(raw?.streams) ? raw.streams : [];
  const video = streams.find((stream) => stream.codec_type === 'video') || {};
  const audio = streams.find((stream) => stream.codec_type === 'audio') || null;
  const duration = Number(format.duration || video.duration || 0);
  return {
    durationSeconds: Number.isFinite(duration) ? Math.round(duration * 1000) / 1000 : 0,
    bytes: Number(format.size || 0) || 0,
    format: bounded(format.format_name, 120),
    video: {
      codec: bounded(video.codec_name, 80),
      width: Number(video.width || 0) || 0,
      height: Number(video.height || 0) || 0,
      fps: parseRate(video.avg_frame_rate || video.r_frame_rate),
    },
    audio: audio ? {
      codec: bounded(audio.codec_name, 80),
      sampleRate: Number(audio.sample_rate || 0) || 0,
      channels: Number(audio.channels || 0) || 0,
    } : null,
  };
}

async function probeVideo(file, runtime, onChild) {
  const result = await runCommand(runtime.ffprobe, [
    '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', file,
  ], { timeoutMs: 30000, onChild });
  return summarizeProbe(JSON.parse(result.stdout));
}

function numericMatch(text, expression) {
  const match = expression.exec(text);
  const value = match ? Number(match[1]) : NaN;
  return Number.isFinite(value) ? value : null;
}

function parseSignalReport(audioLog, sceneLog, analyzedSeconds) {
  const silenceSegments = [];
  const starts = [...audioLog.matchAll(/silence_start:\s*([0-9.]+)/g)]
    .map((match) => Number(match[1]));
  const ends = [...audioLog.matchAll(/silence_end:\s*([0-9.]+)/g)]
    .map((match) => Number(match[1]));
  for (let index = 0; index < Math.min(starts.length, ends.length); index += 1) {
    if (ends[index] >= starts[index]) silenceSegments.push({
      start: Math.round(starts[index] * 1000) / 1000,
      end: Math.round(ends[index] * 1000) / 1000,
      duration: Math.round((ends[index] - starts[index]) * 1000) / 1000,
    });
  }
  const silentSeconds = silenceSegments.reduce((sum, item) => sum + item.duration, 0);
  const sceneTimes = [...sceneLog.matchAll(/pts_time:\s*([0-9.]+)/g)]
    .map((match) => Math.round(Number(match[1]) * 1000) / 1000)
    .filter(Number.isFinite);
  return {
    analyzedSeconds: Math.round(analyzedSeconds * 1000) / 1000,
    meanVolumeDb: numericMatch(audioLog, /mean_volume:\s*(-?[0-9.]+)\s*dB/),
    maxVolumeDb: numericMatch(audioLog, /max_volume:\s*(-?[0-9.]+)\s*dB/),
    silenceSegments: silenceSegments.slice(0, 100),
    silentSeconds: Math.round(silentSeconds * 1000) / 1000,
    audibleCoveragePercent: analyzedSeconds > 0
      ? Math.max(0, Math.min(100,
        Math.round((1 - silentSeconds / analyzedSeconds) * 1000) / 10)) : 0,
    detectedSceneChanges: sceneTimes.length,
    sceneChangeTimes: sceneTimes.slice(0, 200),
  };
}

async function analyzeSignals(file, probe, runtime, emit, onChild) {
  const analyzedSeconds = Math.max(0.05, Math.min(probe.durationSeconds || 0.05, 600));
  emit(`Measuring scenes, pacing, silence, and audio levels in ${path.basename(file)}...`);
  let audioLog = '';
  if (probe.audio) {
    try {
      const audio = await runCommand(runtime.ffmpeg, [
        '-hide_banner', '-nostats', '-t', analyzedSeconds.toFixed(3), '-i', file,
        '-vn', '-af', 'silencedetect=noise=-35dB:d=0.4,volumedetect',
        '-f', 'null', '-',
      ], { timeoutMs: 90000, onChild });
      audioLog = `${audio.stdout}\n${audio.stderr}`;
    } catch (error) { emit(`Audio measurement was unavailable: ${bounded(error.message, 300)}`); }
  }
  let sceneLog = '';
  try {
    const scenes = await runCommand(runtime.ffmpeg, [
      '-hide_banner', '-nostats', '-t', analyzedSeconds.toFixed(3), '-i', file,
      '-an', '-vf', "select='gt(scene,0.32)',showinfo", '-f', 'null', '-',
    ], { timeoutMs: 90000, onChild });
    sceneLog = `${scenes.stdout}\n${scenes.stderr}`;
  } catch (error) { emit(`Scene measurement was unavailable: ${bounded(error.message, 300)}`); }
  return parseSignalReport(audioLog, sceneLog, analyzedSeconds);
}

async function transcribeVideo(file, output, runtime, env, emit, onChild) {
  emit(`Listening and transcribing ${path.basename(file)} locally...`);
  await runCommand(runtime.engine, [file, '--transcribe-only', '--out', output], {
    cwd: runtime.root, env, timeoutMs: 10 * 60 * 1000, onChild,
    onLine: (line) => {
      if (/transcrib|whisper|audio|word/i.test(line)) emit(bounded(line, 1000));
    },
  });
  const textFile = path.join(output, 'TRANSCRIPT.txt');
  const wordsFile = path.join(output, 'TRANSCRIPT.json');
  const transcript = fs.existsSync(textFile)
    ? bounded(fs.readFileSync(textFile, 'utf8'), MAX_TRANSCRIPT_CHARS) : '';
  let words = [];
  if (fs.existsSync(wordsFile)) {
    try {
      const parsed = JSON.parse(fs.readFileSync(wordsFile, 'utf8'));
      if (Array.isArray(parsed)) words = parsed.slice(0, 5000).map((word) => ({
        word: bounded(word?.w, 120),
        start: Number(word?.s || 0),
        end: Number(word?.e || 0),
      })).filter((word) => word.word);
    } catch (_) { /* plain transcript remains authoritative */ }
  }
  return { transcript, words };
}

function sampleTimes(duration, count) {
  if (!(duration > 0)) return [0];
  const wanted = Math.max(1, Math.min(count, MAX_FRAMES_TOTAL));
  const limit = Math.max(0, duration - 0.05);
  const round = (value) => Number(
    Math.max(0, Math.min(limit, value)).toFixed(3));
  const final = round(limit);
  const hooks = [...new Set([0.1, 1.0, 2.5].map(round))]
    .filter((value) => value < final);
  const samples = hooks.slice(0, Math.max(0, wanted - 1));
  samples.push(final);

  // Reserve the hook and final-frame samples first, then distribute the
  // remaining budget across the entire post-hook timeline. Merging a full
  // spread before truncating favored early timestamps and dropped the second
  // half of longer artifacts.
  const remaining = wanted - samples.length;
  const spreadStart = samples.length > 1 ? samples[samples.length - 2] : 0;
  for (let index = 1; index <= remaining; index += 1) {
    samples.push(round(spreadStart +
      (final - spreadStart) * (index / (remaining + 1))));
  }
  return [...new Set(samples)].sort((a, b) => a - b);
}

function finiteSeconds(value, label, { allowEqual = false } = {}) {
  const seconds = value;
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0 ||
      (!allowEqual && Object.is(seconds, -0))) {
    throw new Error(`${label} must be a finite nonnegative time`);
  }
  return seconds;
}

function artifactEventExpectation(layer, event) {
  const value = { layer };
  for (const key of [
    'kind', 'text', 'value', 'items', 'query', 'family', 'viz', 'scale',
    'type', 'name', 'anchor_quote', 'reason',
  ]) {
    if (event[key] === undefined || event[key] === null) continue;
    if (typeof event[key] === 'string' || typeof event[key] === 'number' ||
        typeof event[key] === 'boolean') {
      value[key] = event[key];
    } else if (Array.isArray(event[key])) {
      value[key] = event[key].slice(0, 6).map((item) =>
        typeof item === 'string' || typeof item === 'number' ? item : String(item));
    }
  }
  return bounded(JSON.stringify(value), 200);
}

function parseSrtSeconds(value) {
  const match = /^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$/.exec(value);
  if (!match) return NaN;
  const [, hours, minutes, seconds, millis] = match.map(Number);
  if (minutes > 59 || seconds > 59) return NaN;
  return hours * 3600 + minutes * 60 + seconds + millis / 1000;
}

function parseArtifactCaptions(raw, duration) {
  if (typeof raw !== 'string') {
    throw new TypeError('artifact captions must be SRT text');
  }
  const durationSeconds = finiteSeconds(duration, 'artifact duration');
  const blocks = raw.replace(/\r\n?/g, '\n').trim().split(/\n{2,}/)
    .filter(Boolean);
  if (!blocks.length) throw new Error('artifact captions contain no events');
  if (blocks.length > MAX_ARTIFACT_CAPTION_EVENTS) {
    throw new Error('artifact captions exceed the mechanical validation limit');
  }
  const events = [];
  const indices = new Set();
  for (const [offset, block] of blocks.entries()) {
    const lines = block.split('\n');
    const index = Number(lines.shift());
    const timing = /^(\S+)\s+-->\s+(\S+)(?:\s+.*)?$/.exec(lines.shift() || '');
    const startSeconds = timing ? parseSrtSeconds(timing[1]) : NaN;
    const endSeconds = timing ? parseSrtSeconds(timing[2]) : NaN;
    const text = bounded(lines.join(' '), 500);
    if (!Number.isSafeInteger(index) || index < 1 || indices.has(index) ||
        !Number.isFinite(startSeconds) || !Number.isFinite(endSeconds) ||
        endSeconds <= startSeconds || startSeconds < 0 ||
        endSeconds > durationSeconds + 0.05 || !text) {
      throw new Error(`artifact caption event ${offset + 1} is invalid`);
    }
    indices.add(index);
    events.push({ index, startSeconds, endSeconds, text });
  }
  events.sort((left, right) => left.startSeconds - right.startSeconds ||
    left.index - right.index);
  return events;
}

function artifactCaptionRenderEvents(receipt, duration) {
  const durationSeconds = finiteSeconds(duration, 'artifact duration');
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt) ||
      Object.keys(receipt).length !== 6 ||
      receipt.schema !== 'autoeditor-caption-render-receipt/v1' ||
      receipt.timeline !== 'post_cut_seconds' ||
      receipt.delivery_mode !== 'burned' ||
      !['karaoke-band', 'caption-cards'].includes(receipt.renderer) ||
      receipt.mechanical_qa?.layout_safe !== true ||
      receipt.mechanical_qa?.subject_clear !== true ||
      receipt.mechanical_qa?.pixel_quality?.ok !== true ||
      !Array.isArray(receipt.events) ||
      receipt.events.length > MAX_ARTIFACT_CAPTION_EVENTS) {
    throw new Error('artifact caption-render receipt is invalid');
  }
  const indices = new Set();
  return receipt.events.map((event, offset) => {
    const index = event?.index;
    const startSeconds = event?.start_seconds;
    const endSeconds = event?.end_seconds;
    const text = bounded(event?.text, 500);
    const stateCount = event?.state_count;
    if (index !== offset + 1 || indices.has(index) ||
        !Number.isFinite(startSeconds) || startSeconds < 0 ||
        !Number.isFinite(endSeconds) || endSeconds <= startSeconds ||
        endSeconds > durationSeconds + 0.05 || !text ||
        !Number.isSafeInteger(stateCount) || stateCount < 1) {
      throw new Error(`artifact caption-render event ${offset + 1} is invalid`);
    }
    indices.add(index);
    return { index, startSeconds, endSeconds, text, stateCount };
  }).sort((left, right) => left.startSeconds - right.startSeconds ||
    left.index - right.index);
}

function groupArtifactTargets(targets) {
  const ordered = [...targets].sort((left, right) =>
    left.timeSeconds - right.timeSeconds || left.id.localeCompare(right.id));
  const grouped = [];
  for (const target of ordered) {
    const prior = grouped.at(-1);
    if (prior && prior.targets.length < MAX_ARTIFACT_TARGETS_PER_FRAME &&
        Math.abs(prior.timeSeconds - target.timeSeconds) <= 0.0005) {
      prior.targets.push(target);
    } else {
      grouped.push({ timeSeconds: target.timeSeconds, targets: [target] });
    }
  }
  return grouped;
}

function captionVisionSample(targets, maximum, durationSeconds) {
  if (!Number.isSafeInteger(maximum) || maximum < 0) {
    throw new Error('artifact caption vision budget is invalid');
  }
  if (targets.length <= maximum) return [...targets];
  if (maximum < 2) {
    throw new Error(
      'mandatory artifact targets leave no room for first/last caption vision coverage');
  }
  const selected = new Set([0, targets.length - 1]);
  for (let slot = 1; selected.size < maximum && slot < maximum - 1; slot += 1) {
    const wanted = durationSeconds * slot / (maximum - 1);
    let best = -1;
    let bestDistance = Infinity;
    for (const [index, target] of targets.entries()) {
      if (selected.has(index)) continue;
      const distance = Math.abs(target.timeSeconds - wanted);
      if (distance < bestDistance - 0.0005 ||
          (Math.abs(distance - bestDistance) <= 0.0005 && index < best)) {
        best = index;
        bestDistance = distance;
      }
    }
    if (best >= 0) selected.add(best);
  }
  // Duplicate or clustered timestamps can leave stratified slots tied. Fill
  // deterministically in source order without weakening first/last coverage.
  for (let index = 0; selected.size < maximum && index < targets.length; index += 1) {
    selected.add(index);
  }
  return targets.filter((_target, index) => selected.has(index));
}

function cutPairVisionSample(pairs, maximum, durationSeconds) {
  if (!Number.isSafeInteger(maximum) || maximum < 0) {
    throw new Error('artifact cut-pair vision budget is invalid');
  }
  if (pairs.length <= maximum) return [...pairs];
  if (maximum < 2) {
    throw new Error(
      'mandatory artifact targets leave no room for first/last cut-pair coverage');
  }
  const selected = new Set([0, pairs.length - 1]);
  for (let slot = 1; selected.size < maximum && slot < maximum - 1; slot += 1) {
    const wanted = durationSeconds * slot / (maximum - 1);
    let best = -1;
    let bestDistance = Infinity;
    for (const [index, pair] of pairs.entries()) {
      if (selected.has(index)) continue;
      const distance = Math.abs(pair.timeSeconds - wanted);
      if (distance < bestDistance - 0.0005 ||
          (Math.abs(distance - bestDistance) <= 0.0005 && index < best)) {
        best = index;
        bestDistance = distance;
      }
    }
    if (best >= 0) selected.add(best);
  }
  for (let index = 0; selected.size < maximum && index < pairs.length; index += 1) {
    selected.add(index);
  }
  return pairs.filter((_pair, index) => selected.has(index));
}

function artifactVisionPlan(duration, edl = null, {
  requireEdl = false, captions = [], boundaries = null,
  captionDelivery = captions.length ? 'burned' : 'none',
  captionMechanicalEventCount = captions.length, captionEvidenceSha256 = '',
  editBoundaryEvidenceSha256 = '',
} = {}) {
  const durationSeconds = finiteSeconds(duration, 'artifact duration');
  if (!(durationSeconds > 0)) {
    throw new Error('artifact duration must be greater than zero');
  }
  if (requireEdl && !edl) {
    throw new Error('premium artifact vision requires a final EDL');
  }
  if (edl && (typeof edl !== 'object' || Array.isArray(edl) ||
      edl.timeline_space !== 'post_cut_seconds')) {
    throw new Error('artifact EDL must use the post_cut_seconds timeline');
  }
  if (!Array.isArray(captions)) {
    throw new Error('artifact caption events must be an array');
  }
  if (!['none', 'burned', 'sidecar'].includes(captionDelivery) ||
      !Number.isSafeInteger(captionMechanicalEventCount) ||
      captionMechanicalEventCount < 0 ||
      captionMechanicalEventCount > MAX_ARTIFACT_CAPTION_EVENTS ||
      (captionDelivery === 'burned' &&
        captionMechanicalEventCount !== captions.length) ||
      (captionDelivery !== 'burned' && captions.length) ||
      (captionDelivery === 'none' && captionMechanicalEventCount !== 0) ||
      (captionEvidenceSha256 &&
        !/^[0-9a-f]{64}$/.test(captionEvidenceSha256))) {
    throw new Error('artifact caption delivery evidence is invalid');
  }
  if (editBoundaryEvidenceSha256 &&
      !/^[0-9a-f]{64}$/.test(editBoundaryEvidenceSha256)) {
    throw new Error('artifact edit-boundary evidence hash is invalid');
  }
  const targets = [];
  const categories = Object.create(null);
  if (captionDelivery !== 'none') {
    categories.captions = {
      available: captionDelivery === 'burned',
      deliveryMode: captionDelivery,
      mechanicallyValidated: true,
      mechanicalEventCount: captionMechanicalEventCount,
    };
  }
  const limit = Math.max(0, durationSeconds - 0.05);
  const boundedTime = (value) => Number(
    Math.max(0, Math.min(limit, value)).toFixed(3));
  const addSpanTargets = (prefix, category, kind, start, end, expectation,
                          samples) => {
    for (const [sample, time] of samples(start, end)) {
      targets.push({
        id: `${prefix}-${sample}`,
        category, kind, sample, timeSeconds: boundedTime(time), expectation,
      });
    }
  };
  const anchorTimes = sampleTimes(durationSeconds, MAX_FRAMES_TOTAL);
  for (const [index, timeSeconds] of anchorTimes.entries()) {
    const final = index === anchorTimes.length - 1;
    const category = final ? 'final' : (timeSeconds <= 2.5 ? 'hook' : 'timeline');
    categories[category] = { available: true };
    targets.push({
      id: `anchor-${category}-${String(index + 1).padStart(2, '0')}`,
      category,
      kind: 'anchor',
      timeSeconds,
    });
  }
  for (const layer of edl ? ARTIFACT_EVENT_LAYERS : []) {
    const events = edl[layer];
    categories[layer] = { available: Array.isArray(events) };
    if (events === undefined && layer === 'transitions') continue;
    if (!Array.isArray(events)) {
      throw new Error(`artifact EDL ${layer} must be an array`);
    }
    if (events.length > MAX_ARTIFACT_VISION_FRAMES) {
      throw new Error(`artifact EDL ${layer} exceeds the vision coverage limit`);
    }
    for (const [index, event] of events.entries()) {
      if (!event || typeof event !== 'object' || Array.isArray(event)) {
        throw new Error(`artifact EDL ${layer}[${index}] must be an object`);
      }
      const start = finiteSeconds(event.s, `artifact EDL ${layer}[${index}].s`,
        { allowEqual: true });
      const end = finiteSeconds(event.e, `artifact EDL ${layer}[${index}].e`,
        { allowEqual: true });
      if (end < start || (end === start && layer !== 'transitions') ||
          end > durationSeconds + 0.05) {
        throw new Error(`artifact EDL ${layer}[${index}] has an invalid span`);
      }
      const prefix = `edl-${layer}-${String(index + 1).padStart(3, '0')}`;
      const expectation = artifactEventExpectation(layer, event);
      if (layer === 'transitions') {
        addSpanTargets(prefix, layer, 'edl-transition', start, end,
          expectation, (s, e) => [
            ['before', s - 0.05], ['midpoint', (s + e) / 2], ['after', e + 0.05],
          ]);
      } else {
        targets.push({
          id: prefix,
          category: layer,
          kind: 'edl-event',
          timeSeconds: Number(((start + end) / 2).toFixed(3)),
          expectation,
        });
      }
    }
  }
  const captionTargets = [];
  const captionIds = new Set();
  let priorCaptionStart = -1;
  for (const [offset, caption] of captions.entries()) {
    if (!caption || typeof caption !== 'object' || Array.isArray(caption)) {
      throw new Error(`artifact caption event ${offset + 1} is invalid`);
    }
    const start = finiteSeconds(caption.startSeconds,
      `artifact caption event ${offset + 1} start`, { allowEqual: true });
    const end = finiteSeconds(caption.endSeconds,
      `artifact caption event ${offset + 1} end`, { allowEqual: true });
    if (end <= start || end > durationSeconds + 0.05 ||
        !Number.isSafeInteger(caption.index) || caption.index < 1 ||
        captionIds.has(caption.index) || start < priorCaptionStart) {
      throw new Error(`artifact caption event ${offset + 1} is invalid`);
    }
    captionIds.add(caption.index);
    priorCaptionStart = start;
    captionTargets.push({
      id: `caption-${String(caption.index).padStart(4, '0')}`,
      category: 'captions', kind: 'caption-event',
      timeSeconds: boundedTime((start + end) / 2),
      expectation: bounded(JSON.stringify({
        text: caption.text,
        stateCount: Number.isSafeInteger(caption.stateCount)
          ? caption.stateCount : null,
      }), 200),
    });
  }
  const cutPairs = [];
  let cutMechanicalPayload = [];
  if (boundaries !== null) {
    if (!boundaries || typeof boundaries !== 'object' ||
        Array.isArray(boundaries) || boundaries.schema !== EDIT_BOUNDARIES_SCHEMA ||
        boundaries.timeline !== 'post_cut_seconds' ||
        !Array.isArray(boundaries.cuts) || !Array.isArray(boundaries.transitions) ||
        (boundaries.transition_support !== 'not_implemented' &&
          boundaries.transition_support !== 'implemented')) {
      throw new Error('artifact edit-boundary receipt is invalid');
    }
    if (boundaries.transition_support === 'not_implemented' &&
        boundaries.transitions.length) {
      throw new Error('unsupported artifact transitions cannot be receipted');
    }
    categories.transitions = {
      available: boundaries.transition_support === 'implemented',
    };
    if (boundaries.cuts.length > MAX_ARTIFACT_CUT_EVENTS ||
        boundaries.transitions.length > MAX_ARTIFACT_VISION_FRAMES) {
      throw new Error('artifact edit boundaries exceed the vision coverage limit');
    }
    if (boundaries.cuts.length) categories.cuts = { available: true };
    let priorCutTime = -1;
    for (const [index, cut] of boundaries.cuts.entries()) {
      const time = finiteSeconds(cut?.time_seconds,
        `artifact cut boundary ${index + 1}`, { allowEqual: true });
      if (cut?.index !== index || time > durationSeconds + 0.05 ||
          time < priorCutTime || !Number.isFinite(cut?.removed_seconds) ||
          cut.removed_seconds <= 0) {
        throw new Error(`artifact cut boundary ${index + 1} is invalid`);
      }
      priorCutTime = time;
      const prefix = `cut-boundary-${String(index + 1).padStart(3, '0')}`;
      const expectation = bounded(JSON.stringify({
        removed_seconds: cut?.removed_seconds,
      }), 200);
      cutPairs.push({
        id: prefix, index, timeSeconds: time,
        targets: [
          { id: `${prefix}-before`, category: 'cuts', kind: 'cut-boundary',
            sample: 'before', timeSeconds: boundedTime(time - 0.05), expectation },
          { id: `${prefix}-after`, category: 'cuts', kind: 'cut-boundary',
            sample: 'after', timeSeconds: boundedTime(time + 0.05), expectation },
        ],
      });
    }
    if (boundaries.transitions.length) categories.transitions.available = true;
    let priorTransitionEnd = -1;
    for (const [index, transition] of boundaries.transitions.entries()) {
      const start = finiteSeconds(transition?.s,
        `artifact transition ${index + 1} start`, { allowEqual: true });
      const end = finiteSeconds(transition?.e,
        `artifact transition ${index + 1} end`, { allowEqual: true });
      if (transition?.index !== index || end < start ||
          start < priorTransitionEnd || end > durationSeconds + 0.05) {
        throw new Error(`artifact transition ${index + 1} is invalid`);
      }
      priorTransitionEnd = end;
      addSpanTargets(`transition-boundary-${String(index + 1).padStart(3, '0')}`,
        'transitions', 'transition-boundary', start, end, '', (s, e) => [
          ['before', s - 0.05], ['midpoint', (s + e) / 2], ['after', e + 0.05],
        ]);
    }
    cutMechanicalPayload = boundaries.cuts.map((cut) => ({
      index: cut.index,
      timeSeconds: Number(cut.time_seconds),
      removedSeconds: Number(cut.removed_seconds),
    }));
  }
  const mandatoryFrameCount = groupArtifactTargets(targets).length;
  if (mandatoryFrameCount > MAX_ARTIFACT_VISION_FRAMES) {
    throw new Error('mandatory artifact targets exceed the bounded frame limit');
  }
  const captionFrameReserve = Math.min(captionTargets.length, 8);
  const cutPairBudget = Math.max(0, Math.floor((
    MAX_ARTIFACT_VISION_FRAMES - mandatoryFrameCount - captionFrameReserve) / 2));
  const sampledCutPairs = cutPairVisionSample(
    cutPairs, cutPairBudget, durationSeconds);
  for (const pair of sampledCutPairs) targets.push(...pair.targets);
  const framesBeforeCaptions = groupArtifactTargets(targets).length;
  const captionFrameBudget = MAX_ARTIFACT_VISION_FRAMES - framesBeforeCaptions;
  const sampledCaptions = captionVisionSample(
    captionTargets, captionFrameBudget, durationSeconds);
  targets.push(...sampledCaptions);
  const grouped = groupArtifactTargets(targets);
  if (grouped.length > MAX_ARTIFACT_VISION_FRAMES) {
    throw new Error('artifact vision plan exceeds the bounded frame limit');
  }
  const frames = grouped.map((frame, index) => ({
    id: `vision-frame-${String(index + 1).padStart(3, '0')}`,
    timeSeconds: frame.timeSeconds,
    targets: frame.targets.map((target) => ({ ...target })),
  }));
  const mechanicalCaptionPayload = captions.map((caption) => ({
    index: caption.index,
    startSeconds: caption.startSeconds,
    endSeconds: caption.endSeconds,
    text: caption.text,
    stateCount: Number.isSafeInteger(caption.stateCount) ? caption.stateCount : null,
  }));
  const mechanicalSha256 = crypto.createHash('sha256')
    .update(JSON.stringify(mechanicalCaptionPayload)).digest('hex');
  const sampledTargetIds = sampledCaptions.map((target) => target.id);
  const samplingSha256 = crypto.createHash('sha256').update(JSON.stringify({
    schema: CAPTION_SAMPLING_SCHEMA,
    policy: CAPTION_SAMPLING_POLICY,
    durationSeconds: Number(durationSeconds.toFixed(3)),
    maximumVisionFrames: MAX_ARTIFACT_VISION_FRAMES,
    maximumTargetsPerFrame: MAX_ARTIFACT_TARGETS_PER_FRAME,
    captionDelivery,
    captionMechanicalEventCount,
    captionEvidenceSha256,
    mechanicalSha256,
    mandatoryFrameCount,
    captionFrameBudget,
    sampledTargetIds,
  })).digest('hex');
  const cutMechanicalSha256 = crypto.createHash('sha256')
    .update(JSON.stringify(cutMechanicalPayload)).digest('hex');
  const sampledCutPairIds = sampledCutPairs.map((pair) => pair.id);
  const cutSamplingSha256 = crypto.createHash('sha256').update(JSON.stringify({
    schema: CUT_SAMPLING_SCHEMA,
    policy: CUT_SAMPLING_POLICY,
    durationSeconds: Number(durationSeconds.toFixed(3)),
    maximumVisionFrames: MAX_ARTIFACT_VISION_FRAMES,
    mandatoryFrameCount,
    captionFrameReserve,
    cutPairBudget,
    evidenceSha256: editBoundaryEvidenceSha256 || null,
    mechanicalSha256: cutMechanicalSha256,
    sampledCutPairIds,
  })).digest('hex');
  const cutSampling = boundaries !== null ? {
    schema: CUT_SAMPLING_SCHEMA,
    policy: CUT_SAMPLING_POLICY,
    exhaustiveMechanicalValidation: true,
    evidenceSha256: editBoundaryEvidenceSha256 || null,
    mechanicalCutCount: cutPairs.length,
    visionSampledCutCount: sampledCutPairs.length,
    visionOmittedCutCount: cutPairs.length - sampledCutPairs.length,
    pairIntegrity: true,
    mandatoryFrameCount,
    captionFrameReserve,
    cutPairBudget,
    firstPairId: cutPairs[0]?.id || null,
    lastPairId: cutPairs.at(-1)?.id || null,
    sampledCutPairIds,
    mechanicalSha256: cutMechanicalSha256,
    samplingSha256: cutSamplingSha256,
  } : null;
  const earlyCaption = captionTargets.find((target) => target.timeSeconds <= 2.5);
  const captionSampling = {
    schema: CAPTION_SAMPLING_SCHEMA,
    policy: CAPTION_SAMPLING_POLICY,
    exhaustiveMechanicalValidation: true,
    deliveryMode: captionDelivery,
    evidenceSha256: captionEvidenceSha256 || null,
    mechanicalEventCount: captionMechanicalEventCount,
    visionSampledEventCount: sampledCaptions.length,
    visionOmittedEventCount: captionDelivery === 'burned'
      ? captions.length - sampledCaptions.length : 0,
    visionInapplicableEventCount: captionDelivery === 'sidecar'
      ? captionMechanicalEventCount : 0,
    mandatoryFrameCount,
    captionFrameBudget,
    earlyTargetId: earlyCaption?.id || null,
    firstTargetId: captionTargets[0]?.id || null,
    lastTargetId: captionTargets.at(-1)?.id || null,
    sampledTargetIds,
    mechanicalSha256,
    samplingSha256,
  };
  if (categories.captions) {
    categories.captions = {
      ...categories.captions,
      mechanicalEventCount: captionMechanicalEventCount,
      visionSampledEventCount: sampledCaptions.length,
      samplingPolicy: CAPTION_SAMPLING_POLICY,
      samplingSha256,
    };
  }
  if (categories.cuts) {
    categories.cuts = {
      ...categories.cuts,
      mechanicalCutCount: cutPairs.length,
      visionSampledCutCount: sampledCutPairs.length,
      samplingPolicy: CUT_SAMPLING_POLICY,
      samplingSha256: cutSamplingSha256,
    };
  }
  return {
    schema: ARTIFACT_VISION_PLAN_SCHEMA,
    timeline: 'post_cut_seconds',
    edlBound: !!edl,
    durationSeconds: Number(durationSeconds.toFixed(3)),
    categories,
    captionSampling,
    cutSampling,
    frames,
  };
}

function visionFrameBatches(records, maximum = MAX_FRAMES_TOTAL) {
  if (!Array.isArray(records) || !records.length ||
      records.length > MAX_ARTIFACT_VISION_FRAMES) {
    throw new Error('artifact vision frames must be a bounded nonempty array');
  }
  if (!Number.isSafeInteger(maximum) || maximum < 1 ||
      maximum > MAX_FRAMES_TOTAL) {
    throw new Error('artifact vision batch size must be between 1 and 8');
  }
  const seen = new Set();
  for (const [index, record] of records.entries()) {
    if (!record || typeof record !== 'object' || Array.isArray(record) ||
        typeof record.id !== 'string' || !record.id || seen.has(record.id) ||
        !Number.isFinite(Number(record.timeSeconds))) {
      throw new Error(`artifact vision frame ${index} is invalid`);
    }
    seen.add(record.id);
  }
  const batches = [];
  for (let index = 0; index < records.length; index += maximum) {
    batches.push(records.slice(index, index + maximum));
  }
  return batches;
}

function artifactVisionCoverage(plan, capturedFrames, reviewedTargetIds) {
  if (!plan || plan.schema !== ARTIFACT_VISION_PLAN_SCHEMA ||
      !Array.isArray(plan.frames) || !plan.frames.length) {
    throw new Error('artifact vision plan is invalid');
  }
  const captured = new Map();
  for (const frame of Array.isArray(capturedFrames) ? capturedFrames : []) {
    if (frame && typeof frame.id === 'string' && !captured.has(frame.id)) {
      captured.set(frame.id, frame);
    }
  }
  const reviewed = new Set(
    Array.isArray(reviewedTargetIds) ? reviewedTargetIds : []);
  const plannedTargets = new Map();
  for (const frame of plan.frames) {
    if (!Array.isArray(frame.targets) || !frame.targets.length) {
      throw new Error('artifact vision plan contains a targetless frame');
    }
    for (const target of frame.targets) {
      if (!target || typeof target.id !== 'string' || !target.id ||
          plannedTargets.has(target.id)) {
        throw new Error('artifact vision plan target IDs are invalid');
      }
      plannedTargets.set(target.id, frame.id);
    }
  }
  const missingFrameIds = plan.frames.filter((frame) => !captured.has(frame.id))
    .map((frame) => frame.id);
  const unreviewedFrameIds = plan.frames.filter((frame) =>
    captured.has(frame.id) && frame.targets.some(
      (target) => !reviewed.has(target.id))).map((frame) => frame.id);
  const unreviewedTargetIds = plan.frames.flatMap((frame) =>
    captured.has(frame.id) ? frame.targets.filter((target) =>
      !reviewed.has(target.id)).map((target) => target.id) : []);
  const categoryNames = new Set(Object.keys(plan.categories || {}));
  for (const frame of plan.frames) {
    for (const target of frame.targets || []) categoryNames.add(target.category);
  }
  const categories = Object.create(null);
  const unobservedCategories = [];
  for (const category of [...categoryNames].sort()) {
    const categoryFrames = plan.frames.filter((frame) =>
      (frame.targets || []).some((target) => target.category === category));
    const plannedTargets = categoryFrames.reduce((total, frame) => total +
      frame.targets.filter((target) => target.category === category).length, 0);
    const capturedTargets = categoryFrames.reduce((total, frame) =>
      total + (captured.has(frame.id) ? frame.targets.filter(
        (target) => target.category === category).length : 0), 0);
    const reviewedTargets = categoryFrames.reduce((total, frame) =>
      total + (captured.has(frame.id) ? frame.targets.filter((target) =>
        target.category === category && reviewed.has(target.id)).length : 0), 0);
    const available = plan.categories?.[category]?.available !== false;
    const status = !available ? 'unavailable' : plannedTargets === 0
      ? 'not-planned' : reviewedTargets === plannedTargets
        ? 'reviewed' : 'unobserved';
    categories[category] = {
      available, plannedTargets, capturedTargets, reviewedTargets, status,
    };
    if (status === 'unobserved') unobservedCategories.push(category);
  }
  const unknownReviewedTargetIds = [...reviewed].filter((id) =>
    !plannedTargets.has(id)).sort();
  const reviewedFrameCount = plan.frames.filter((frame) =>
    captured.has(frame.id) && frame.targets.every(
      (target) => reviewed.has(target.id))).length;
  return {
    schema: ARTIFACT_VISION_COVERAGE_SCHEMA,
    complete: missingFrameIds.length === 0 && unreviewedFrameIds.length === 0 &&
      unreviewedTargetIds.length === 0 && unknownReviewedTargetIds.length === 0 &&
      unobservedCategories.length === 0,
    plannedFrameCount: plan.frames.length,
    plannedTargetCount: plannedTargets.size,
    capturedFrameCount: plan.frames.length - missingFrameIds.length,
    reviewedFrameCount,
    reviewedTargetCount: [...reviewed].filter((id) =>
      plannedTargets.has(id)).length,
    missingFrameIds,
    unreviewedFrameIds,
    unreviewedTargetIds,
    unknownReviewedTargetIds,
    unobservedCategories,
    categories,
    captionSampling: plan.captionSampling || null,
    cutSampling: plan.cutSampling || null,
    frames: plan.frames.map((frame) => ({
      id: frame.id,
      timeSeconds: frame.timeSeconds,
      targetIds: frame.targets.map((target) => target.id),
      categories: [...new Set(frame.targets.map((target) => target.category))].sort(),
      captured: captured.has(frame.id),
      reviewed: captured.has(frame.id) && frame.targets.every(
        (target) => reviewed.has(target.id)),
      observedTargetIds: frame.targets.filter((target) =>
        reviewed.has(target.id)).map((target) => target.id),
    })),
  };
}

async function extractFrames(file, probe, output, count, runtime, onChild) {
  const frames = [];
  for (const [index, seconds] of sampleTimes(probe.durationSeconds, count).entries()) {
    const frame = path.join(output, `frame-${String(index + 1).padStart(2, '0')}.jpg`);
    await runCommand(runtime.ffmpeg, [
      '-hide_banner', '-loglevel', 'error', '-ss', seconds.toFixed(3), '-i', file,
      '-frames:v', '1', '-vf', 'scale=640:640:force_original_aspect_ratio=decrease',
      '-q:v', '3', '-y', frame,
    ], { timeoutMs: 45000, onChild });
    if (fs.existsSync(frame) && fs.statSync(frame).size > 0) frames.push(frame);
  }
  return frames;
}

async function extractArtifactVisionFrames(file, plan, output, runtime, onChild,
                                            shouldContinue = () => true) {
  if (!plan || plan.schema !== ARTIFACT_VISION_PLAN_SCHEMA ||
      !Array.isArray(plan.frames) || !plan.frames.length) {
    throw new Error('artifact vision plan is invalid');
  }
  const captured = [];
  const missing = [];
  let captureBlocked = '';
  for (const [index, planned] of plan.frames.entries()) {
    if (!shouldContinue()) throw new Error('local vision was canceled');
    if (captureBlocked) {
      missing.push({ id: planned.id, timeSeconds: planned.timeSeconds,
        error: 'capture skipped after an earlier FFmpeg failure' });
      continue;
    }
    const frame = path.join(output,
      `artifact-${String(index + 1).padStart(3, '0')}.jpg`);
    try {
      await runCommand(runtime.ffmpeg, [
        '-hide_banner', '-loglevel', 'error', '-ss',
        Number(planned.timeSeconds).toFixed(3), '-i', file,
        '-frames:v', '1', '-vf',
        'scale=640:640:force_original_aspect_ratio=decrease',
        '-q:v', '3', '-y', frame,
      ], { timeoutMs: 45000, onChild });
      if (!fs.existsSync(frame) || fs.statSync(frame).size < 1) {
        throw new Error('FFmpeg did not produce a frame');
      }
      captured.push({ ...planned, path: frame });
    } catch (error) {
      captureBlocked = bounded(error?.message || error, 500) ||
        'artifact frame capture failed';
      missing.push({ id: planned.id, timeSeconds: planned.timeSeconds,
        error: captureBlocked });
    }
  }
  return { captured, missing };
}

function assistantText(value) {
  let text = bounded(value, MAX_VISUAL_CHARS);
  const marker = text.lastIndexOf('Assistant:');
  if (marker >= 0) text = text.slice(marker + 'Assistant:'.length).trim();
  return bounded(text, MAX_VISUAL_CHARS);
}

function readCache(file, digest) {
  try {
    const raw = fs.readFileSync(file, 'utf8');
    if (Buffer.byteLength(raw, 'utf8') > 100000) return null;
    const value = JSON.parse(raw);
    if (value?.schema !== CACHE_SCHEMA || value?.digest !== digest ||
        !value.report || typeof value.report !== 'object') return null;
    return value.report;
  } catch (_) { return null; }
}

function writeCache(file, digest, report) {
  const temporary = `${file}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify({ schema: CACHE_SCHEMA, digest, report }), {
    mode: 0o600, flag: 'wx',
  });
  fs.renameSync(temporary, file);
}

async function analyzeOne(file, index, frameCount, {
  runtime, env, cacheRoot, describeFrames, emit, onChild,
}) {
  const before = fileFingerprint(file);
  const cacheFile = path.join(cacheRoot, `${before.digest}.json`);
  const cached = readCache(cacheFile, before.digest);
  if (cached) {
    emit(`Using the saved local analysis for ${path.basename(file)}.`);
    return cached;
  }
  const work = fs.mkdtempSync(path.join(cacheRoot, `work-${index}-`));
  try {
    emit(`Inspecting ${path.basename(file)}...`);
    const probe = await probeVideo(file, runtime, onChild);
    const signals = await analyzeSignals(file, probe, runtime, emit, onChild);
    const transcriptDir = path.join(work, 'transcript');
    fs.mkdirSync(transcriptDir, { recursive: true, mode: 0o700 });
    let speech = { transcript: '', words: [] };
    if (probe.audio) {
      try { speech = await transcribeVideo(file, transcriptDir, runtime, env, emit, onChild); }
      catch (error) { emit(`Local transcription was unavailable: ${bounded(error.message, 500)}`); }
    }
    let visualSummary = '';
    let visualComplete = false;
    try {
      const frames = await extractFrames(file, probe, work, frameCount, runtime, onChild);
      if (frames.length && typeof describeFrames === 'function') {
        emit(`Watching ${frames.length} representative video frames locally...`);
        visualSummary = assistantText(await describeFrames(frames));
        visualComplete = !!visualSummary;
      }
    } catch (error) {
      emit(`Local visual analysis was unavailable: ${bounded(error.message, 500)}`);
    }
    const after = fileFingerprint(file);
    if (after.digest !== before.digest) {
      throw new Error('attached video changed during local analysis');
    }
    const report = {
      file: path.basename(file),
      technical: probe,
      signals,
      transcript: speech.transcript,
      timedWords: speech.words,
      visualSummary,
      localOnly: true,
    };
    if (visualComplete) writeCache(cacheFile, before.digest, report);
    return report;
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

async function analyzeMedia({
  videoPaths, runtime, env, cacheRoot, describeFrames,
  emit = () => {}, onChild = () => {},
}) {
  if (!Array.isArray(videoPaths) || videoPaths.length < 1) return null;
  for (const required of ['engine', 'ffmpeg', 'ffprobe']) {
    if (!runtime[required] || !fs.existsSync(runtime[required])) {
      throw new Error(`the built-in ${required} analyzer is missing`);
    }
  }
  fs.mkdirSync(cacheRoot, { recursive: true, mode: 0o700 });
  const framesPerVideo = Math.max(1,
    Math.min(4, Math.floor(MAX_FRAMES_TOTAL / videoPaths.length)));
  const reports = [];
  for (const [index, file] of videoPaths.entries()) {
    reports.push(await analyzeOne(file, index, framesPerVideo, {
      runtime, env, cacheRoot, describeFrames, emit, onChild,
    }));
  }
  emit('Local watching, listening, and transcription are complete. Sending the private report to DeepSeek...');
  return {
    schema: CACHE_SCHEMA,
    analyzedAt: new Date().toISOString(),
    videos: reports,
    originalVideosUploaded: false,
  };
}

module.exports = {
  ARTIFACT_VISION_COVERAGE_SCHEMA,
  ARTIFACT_VISION_PLAN_SCHEMA,
  CACHE_SCHEMA,
  MODEL_ID,
  MODEL_REVISION,
  analyzeMedia,
  artifactVisionCoverage,
  artifactVisionPlan,
  artifactCaptionRenderEvents,
  assistantText,
  extractArtifactVisionFrames,
  extractFrames,
  fileFingerprint,
  parseArtifactCaptions,
  parseSignalReport,
  probeVideo,
  sampleTimes,
  summarizeProbe,
  visionFrameBatches,
};
