'use strict';

const SOURCE_CATALOG_SCHEMA = 'autoeditor-source-catalog/v1';
const SOURCE_MANIFEST_SCHEMA = 'autoeditor-source-manifest/v1';
const MAX_SOURCES = 20;
const MAX_WORDS_PER_SOURCE = 50000;
const MAX_SCENE_CHANGES = 10000;
const MAX_PROMPT_SCENES_PER_SOURCE = 200;
// Keep the complete immutable catalog locally, but bound the private planning
// excerpt so many long sources cannot crowd the instruction/response budget.
// If this prefix is incomplete, speech anchors fail closed; visual-only
// segments can still be planned from exact source/time evidence.
const MAX_PROMPT_WORDS_TOTAL = 6000;
const SHA256 = /^[0-9a-f]{64}$/;
const SOURCE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function canonicalText(value) {
  return String(value || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
}

function milliseconds(value, label, { allowZero = true } = {}) {
  if (typeof value !== 'number' || !Number.isFinite(value) ||
      value < (allowZero ? 0 : 0.001)) {
    throw new Error(`${label} is not a finite source time`);
  }
  const result = Math.round(value * 1000);
  if (!Number.isSafeInteger(result) || (!allowZero && result < 1)) {
    throw new Error(`${label} exceeds the source-time contract`);
  }
  return result;
}

function uniqueSourceIds(videos) {
  const totals = new Map();
  const hashes = new Set();
  for (const video of videos) {
    const base = canonicalText(video?.sourceId);
    totals.set(base, (totals.get(base) || 0) + 1);
    const digest = String(video?.sourceSha256 || '');
    if (hashes.has(digest)) {
      throw new Error('the same source content was attached more than once');
    }
    hashes.add(digest);
  }
  const seen = new Map();
  return videos.map((video) => {
    const base = canonicalText(video?.sourceId);
    if (!SOURCE_ID.test(base)) throw new Error('media evidence has an invalid source id');
    if (totals.get(base) === 1) return base;
    const occurrence = (seen.get(base) || 0) + 1;
    seen.set(base, occurrence);
    const suffix = `-${String(occurrence).padStart(2, '0')}`;
    return `${base.slice(0, 64 - suffix.length)}${suffix}`;
  });
}

function sourceCatalog(mediaAnalysis) {
  if (!mediaAnalysis || mediaAnalysis.schema !== 'autoeditor-local-media-analysis/v4' ||
      !Array.isArray(mediaAnalysis.videos) || mediaAnalysis.videos.length < 1 ||
      mediaAnalysis.videos.length > MAX_SOURCES) {
    throw new Error('complete v4 local media evidence is required');
  }
  const ids = uniqueSourceIds(mediaAnalysis.videos);
  const sources = mediaAnalysis.videos.map((video, sourceIndex) => {
    if (!video || typeof video !== 'object' || Array.isArray(video) ||
        video.localOnly !== true || !video.technical ||
        typeof video.technical !== 'object' || Array.isArray(video.technical) ||
        !video.technical.video || typeof video.technical.video !== 'object' ||
        Array.isArray(video.technical.video) ||
        !Object.prototype.hasOwnProperty.call(video.technical, 'audio') ||
        (video.technical.audio !== null &&
          (typeof video.technical.audio !== 'object' ||
           Array.isArray(video.technical.audio)))) {
      throw new Error('media evidence is not a complete v4 local report');
    }
    const sha256 = String(video?.sourceSha256 || '');
    const sourceBytes = video?.sourceBytes;
    const durationMs = milliseconds(video?.technical?.durationSeconds,
      'source duration', { allowZero: false });
    if (!SHA256.test(sha256) || !Number.isSafeInteger(sourceBytes) || sourceBytes < 1) {
      throw new Error('media evidence lacks full source identity');
    }
    const videoStartOffsetMs = video?.technical?.video?.startOffsetMs;
    const audioStartOffsetMs = video?.technical?.audio
      ? video.technical.audio.startOffsetMs : null;
    if (!Number.isSafeInteger(videoStartOffsetMs) ||
        videoStartOffsetMs >= durationMs ||
        (video?.technical?.audio &&
          (!Number.isSafeInteger(audioStartOffsetMs) ||
           audioStartOffsetMs >= durationMs))) {
      throw new Error('media evidence lacks a complete source timeline');
    }
    const rawWords = video?.timedWords;
    const timedWordCount = video?.timedWordCount;
    if (!Array.isArray(rawWords) || !Number.isSafeInteger(timedWordCount) ||
        timedWordCount < 0 || typeof video?.timedWordsComplete !== 'boolean' ||
        typeof video?.transcriptComplete !== 'boolean' ||
        video?.transcriptTimeline !== 'container-relative-ms/v1') {
      throw new Error('media evidence lacks the v4 transcript completeness contract');
    }
    if (video.technical.audio === null &&
        (rawWords.length !== 0 || timedWordCount !== 0 ||
         video.timedWordsComplete || video.transcriptComplete)) {
      throw new Error('no-audio v4 evidence cannot claim speech timing');
    }
    const wordsComplete = video?.transcriptTimeline === 'container-relative-ms/v1' &&
      video?.timedWordsComplete === true &&
      Array.isArray(rawWords) && Number.isSafeInteger(timedWordCount) &&
      timedWordCount === rawWords.length && timedWordCount <= MAX_WORDS_PER_SOURCE;
    const words = [];
    if (wordsComplete) {
      let priorStart = -1;
      let priorEnd = -1;
      for (const [index, raw] of rawWords.entries()) {
        const text = canonicalText(raw?.word);
        const startMs = milliseconds(raw?.start, 'word start');
        const endMs = milliseconds(raw?.end, 'word end');
        if (!text || text.length > 120 || endMs < startMs || endMs > durationMs + 50 ||
            startMs < priorStart || endMs < priorEnd) {
          throw new Error('media evidence has invalid per-source word timing');
        }
        words.push(Object.freeze({ index, text, start_ms: startMs, end_ms: endMs }));
        priorStart = startMs;
        priorEnd = endMs;
      }
    }
    const sceneChanges = Array.isArray(video?.signals?.sceneChangeTimes)
      ? video.signals.sceneChangeTimes : [];
    if (sceneChanges.length > MAX_SCENE_CHANGES) {
      throw new Error('media evidence has too many scene changes');
    }
    const sceneChangeMs = sceneChanges.map((value) =>
      milliseconds(value, 'scene-change time')).filter((value, index, all) =>
      value <= durationMs && (index === 0 || value > all[index - 1]));
    return Object.freeze({
      source_id: ids[sourceIndex], sha256, bytes: sourceBytes,
      file_label: canonicalText(video?.file).slice(0, 240), duration_ms: durationMs,
      timeline: Object.freeze({
        video_start_offset_ms: videoStartOffsetMs,
        audio_start_offset_ms: audioStartOffsetMs,
      }),
      transcript: Object.freeze({
        complete: wordsComplete,
        total_words: Number.isSafeInteger(timedWordCount) ? timedWordCount : 0,
        words: Object.freeze(words),
      }),
      scene_change_ms: Object.freeze(sceneChangeMs),
      visual_summary: canonicalText(video?.visualSummary).slice(0, 5000),
    });
  });
  const sourceIds = new Set(sources.map((source) => source.source_id));
  if (sourceIds.size !== sources.length) throw new Error('source identities are ambiguous');
  return Object.freeze({
    schema_version: SOURCE_CATALOG_SCHEMA,
    sources: Object.freeze(sources),
  });
}

function sourceManifest(catalog) {
  if (!catalog || catalog.schema_version !== SOURCE_CATALOG_SCHEMA ||
      !Array.isArray(catalog.sources) || !catalog.sources.length) {
    throw new Error('a validated source catalog is required');
  }
  return Object.freeze({
    schema_version: SOURCE_MANIFEST_SCHEMA,
    sources: Object.freeze(catalog.sources.map((source) => Object.freeze({
      source_id: source.source_id,
      sha256: source.sha256,
      duration_ms: source.duration_ms,
    }))),
  });
}

function fairPromptWordAllocations(sources) {
  const allocations = sources.map(() => 0);
  let remaining = Math.min(
    MAX_PROMPT_WORDS_TOTAL,
    sources.reduce((total, source) => total +
      (source.transcript.complete ? source.transcript.words.length : 0), 0),
  );
  let active = sources.map((source, index) => ({ source, index }))
    .filter(({ source }) => source.transcript.complete &&
      source.transcript.words.length > 0);

  // Max-min allocation prevents an early long transcript from consuming the
  // global budget. Short transcripts are completed first; their unused fair
  // share is then redistributed deterministically among the remaining sources.
  while (remaining > 0 && active.length > 0) {
    const fairShare = Math.floor(remaining / active.length);
    if (fairShare === 0) {
      for (const { source, index } of active.slice(0, remaining)) {
        if (allocations[index] < source.transcript.words.length) {
          allocations[index] += 1;
        }
      }
      break;
    }
    let allocated = 0;
    for (const { source, index } of active) {
      const available = source.transcript.words.length - allocations[index];
      const addition = Math.min(available, fairShare);
      allocations[index] += addition;
      allocated += addition;
    }
    if (allocated === 0) break;
    remaining -= allocated;
    active = active.filter(({ source, index }) =>
      allocations[index] < source.transcript.words.length);
  }
  return allocations;
}

function stratifiedPromptWords(words, count) {
  if (count >= words.length) return words.slice();
  if (count <= 0) return [];

  // Keep contiguous, anchorable windows from the beginning, middle, and end
  // instead of a sparse sample or prefix. Original word objects retain their
  // source-global `index`, so an excerpt can never renumber a speech anchor.
  const stratumCount = Math.min(3, count);
  const bounds = Array.from({ length: stratumCount }, (_, stratum) => ({
    start: Math.floor(stratum * words.length / stratumCount),
    end: Math.floor((stratum + 1) * words.length / stratumCount),
  }));
  const takes = bounds.map(() => 0);
  let remaining = count;
  let active = bounds.map((bound, index) => ({ bound, index }));
  while (remaining > 0) {
    const fairShare = Math.floor(remaining / active.length);
    if (fairShare === 0) {
      active.slice(0, remaining).forEach(({ index }) => { takes[index] += 1; });
      break;
    }
    let allocated = 0;
    for (const { bound, index } of active) {
      const available = bound.end - bound.start - takes[index];
      const addition = Math.min(available, fairShare);
      takes[index] += addition;
      allocated += addition;
    }
    remaining -= allocated;
    active = active.filter(({ bound, index }) =>
      takes[index] < bound.end - bound.start);
  }
  const selected = [];
  for (let stratum = 0; stratum < stratumCount; stratum += 1) {
    const stratumStart = bounds[stratum].start;
    const stratumEnd = bounds[stratum].end;
    const take = takes[stratum];
    let windowStart;
    if (stratum === 0) {
      windowStart = stratumStart;
    } else if (stratum === stratumCount - 1) {
      windowStart = stratumEnd - take;
    } else {
      windowStart = stratumStart + Math.floor(
        (stratumEnd - stratumStart - take) / 2,
      );
    }
    selected.push(...words.slice(windowStart, windowStart + take));
  }
  return selected;
}

function sourceCatalogForPrompt(catalog) {
  if (!catalog || catalog.schema_version !== SOURCE_CATALOG_SCHEMA ||
      !Array.isArray(catalog.sources) || !catalog.sources.length) {
    throw new Error('a validated source catalog is required');
  }
  const allocations = fairPromptWordAllocations(catalog.sources);
  const sources = catalog.sources.map((source, sourceIndex) => {
    const keep = allocations[sourceIndex];
    const promptWords = stratifiedPromptWords(source.transcript.words, keep);
    return Object.freeze({
      source_id: source.source_id,
      sha256: source.sha256,
      bytes: source.bytes,
      file_label: source.file_label,
      duration_ms: source.duration_ms,
      timeline: source.timeline,
      transcript: Object.freeze({
        complete: source.transcript.complete && keep === source.transcript.words.length,
        total_words: source.transcript.total_words,
        words: Object.freeze(promptWords),
        ...(keep < source.transcript.words.length
          ? { error: 'complete per-source words exceed the bounded planning context' }
          : {}),
      }),
      scene_change_ms: Object.freeze(
        source.scene_change_ms.slice(0, MAX_PROMPT_SCENES_PER_SOURCE)),
      visual_summary: source.visual_summary,
    });
  });
  return Object.freeze({
    schema_version: SOURCE_CATALOG_SCHEMA,
    sources: Object.freeze(sources),
  });
}

function groundSequenceSpeech(plan, catalog) {
  if (!plan || !Array.isArray(plan.segments) || !catalog ||
      catalog.schema_version !== SOURCE_CATALOG_SCHEMA) {
    throw new Error('sequence speech grounding requires a plan and catalog');
  }
  const sources = new Map(catalog.sources.map((source) => [source.source_id, source]));
  for (const segment of plan.segments) {
    const source = sources.get(segment.source_id);
    if (!source || source.sha256 !== segment.source_sha256) {
      throw new Error('sequence segment is not bound to source evidence');
    }
    const anchor = segment.speech_anchor;
    if (!source.transcript.complete) {
      if (anchor !== null) {
        throw new Error('sequence speech anchor uses an incomplete transcript');
      }
      continue;
    }
    const overlappingWords = source.transcript.words.filter((word) =>
      word.end_ms > segment.source_start_ms &&
      word.start_ms < segment.source_end_ms);
    if (anchor === null) {
      if (overlappingWords.length) {
        throw new Error('a sequence interval containing known speech requires an exact anchor');
      }
      continue;
    }
    const start = source.transcript.words[anchor.start_word];
    const end = source.transcript.words[anchor.end_word];
    if (!start || !end || anchor.end_word < anchor.start_word) {
      throw new Error('sequence speech anchor word bounds are invalid');
    }
    const expected = canonicalText(source.transcript.words
      .slice(anchor.start_word, anchor.end_word + 1)
      .map((word) => word.text).join(' '));
    if (canonicalText(anchor.text) !== expected ||
        start.start_ms < segment.source_start_ms ||
        end.end_ms > segment.source_end_ms) {
      throw new Error('sequence speech anchor is not exactly source grounded');
    }
  }
  return plan;
}

module.exports = Object.freeze({
  SOURCE_CATALOG_SCHEMA,
  SOURCE_MANIFEST_SCHEMA,
  canonicalText,
  groundSequenceSpeech,
  sourceCatalog,
  sourceCatalogForPrompt,
  sourceManifest,
});
