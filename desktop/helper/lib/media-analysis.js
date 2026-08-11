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
const SAMPLE_BYTES = 64 * 1024;

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
  const wanted = Math.max(1, Math.min(count, 6));
  return Array.from({ length: wanted }, (_, index) =>
    Math.max(0, Math.min(duration - 0.05, duration * ((index + 0.5) / wanted))));
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
  CACHE_SCHEMA,
  MODEL_ID,
  MODEL_REVISION,
  analyzeMedia,
  assistantText,
  fileFingerprint,
  parseSignalReport,
  sampleTimes,
  summarizeProbe,
};
