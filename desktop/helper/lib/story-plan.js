'use strict';

const STORY_PLAN_SCHEMA = 'autoeditor-story-edit/v1';
const STORY_TIMELINE = 'source_seconds';
const MAX_KEEP_RANGES = 64;
const MAX_ANCHOR_TEXT_CHARS = 4000;
const ANCHOR_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function isPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exactKeys(value, expected) {
  if (!isPlainObject(value)) return false;
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index]);
}

function canonicalText(value) {
  return String(value || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
}

function finite(value) {
  return typeof value === 'number' && Number.isFinite(value) && !Number.isNaN(value);
}

function roundTime(value) {
  return Math.round(value * 1000) / 1000;
}

function durationIntent(text) {
  const value = canonicalText(text).toLowerCase();
  const rangedValue = value.replace(/[\u2013\u2014]/g, '-');
  const range = rangedValue.match(
    /(?:about|around|approximately|approx\.?|roughly|~)?\s*(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b/i);
  if (range) {
    const multiplier = /^m(?:in)?/.test(range[3]) ? 60 : 1;
    const first = Number(range[1]) * multiplier;
    const second = Number(range[2]) * multiplier;
    if (first > 0 && second >= first) {
      return Object.freeze({ minSeconds: first, maxSeconds: second });
    }
  }
  const approximate = value.match(
    /(?:about|around|approximately|approx\.?|roughly|~)\s*(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b/i);
  if (approximate) {
    const multiplier = /^m(?:in)?/.test(approximate[2]) ? 60 : 1;
    const seconds = Number(approximate[1]) * multiplier;
    if (seconds > 0) {
      const tolerance = Math.max(1, Math.min(5, seconds * 0.125));
      return Object.freeze({
        minSeconds: Math.max(0.1, seconds - tolerance),
        maxSeconds: seconds + tolerance,
      });
    }
  }
  const exact = value.match(
    /\b(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s|minutes?|mins?|m)(?:\s+(?:video|edit|cut|runtime|long))?\b/i);
  if (!exact) return null;
  const multiplier = /^m(?:in)?/.test(exact[2]) ? 60 : 1;
  const seconds = Number(exact[1]) * multiplier;
  if (!(seconds > 0)) return null;
  const tolerance = Math.max(1, Math.min(5, seconds * 0.125));
  return Object.freeze({
    minSeconds: Math.max(0.1, seconds - tolerance),
    maxSeconds: seconds + tolerance,
  });
}

function storyTranscript(mediaAnalysis) {
  const videos = Array.isArray(mediaAnalysis?.videos) ? mediaAnalysis.videos : [];
  if (!videos.length) {
    return Object.freeze({ complete: false, sourceDuration: 0, words: [] });
  }
  const words = [];
  let offset = 0;
  for (const video of videos) {
    const duration = Number(video?.technical?.durationSeconds);
    const timedWords = video?.timedWords;
    if (!finite(duration) || duration <= 0 || !Array.isArray(timedWords) ||
        !timedWords.length || video?.timedWordsComplete !== true ||
        !Number.isSafeInteger(video?.timedWordCount) ||
        video.timedWordCount !== timedWords.length) {
      return Object.freeze({ complete: false, sourceDuration: 0, words: [] });
    }
    let priorStart = -1;
    let priorEnd = -1;
    for (const rawWord of timedWords) {
      const word = canonicalText(rawWord?.word);
      const start = Number(rawWord?.start);
      const end = Number(rawWord?.end);
      if (!word || word.length > 120 || !finite(start) || !finite(end) ||
          start < 0 || end < start || end > duration + 0.05 ||
          start + 0.001 < priorStart || end + 0.001 < priorEnd) {
        return Object.freeze({ complete: false, sourceDuration: 0, words: [] });
      }
      words.push(Object.freeze({
        index: words.length,
        word,
        start: roundTime(offset + start),
        end: roundTime(offset + end),
      }));
      priorStart = start;
      priorEnd = end;
    }
    offset += duration;
  }
  return Object.freeze({
    complete: true,
    sourceDuration: roundTime(offset),
    words: Object.freeze(words),
  });
}

function normalizeStoryPlan(raw, transcript, requestedDuration = null) {
  if (!exactKeys(raw, [
    'schema_version', 'timeline', 'target_duration', 'hook_anchor_id',
    'closer_anchor_id', 'keep_ranges',
  ])) return null;
  if (raw.schema_version !== STORY_PLAN_SCHEMA || raw.timeline !== STORY_TIMELINE ||
      !transcript?.complete || !Array.isArray(transcript.words) ||
      !transcript.words.length || !finite(transcript.sourceDuration) ||
      transcript.sourceDuration <= 0) return null;
  if (!exactKeys(raw.target_duration, ['min_seconds', 'max_seconds'])) return null;
  const minSeconds = raw.target_duration.min_seconds;
  const maxSeconds = raw.target_duration.max_seconds;
  if (!finite(minSeconds) || !finite(maxSeconds) || minSeconds <= 0 ||
      maxSeconds < minSeconds || maxSeconds > transcript.sourceDuration + 0.001) return null;
  if (requestedDuration && (minSeconds < requestedDuration.minSeconds - 0.001 ||
      maxSeconds > requestedDuration.maxSeconds + 0.001)) return null;
  const hookAnchorId = canonicalText(raw.hook_anchor_id);
  const closerAnchorId = canonicalText(raw.closer_anchor_id);
  if (!ANCHOR_ID.test(hookAnchorId) || !ANCHOR_ID.test(closerAnchorId) ||
      hookAnchorId === closerAnchorId ||
      !Array.isArray(raw.keep_ranges) || raw.keep_ranges.length < 2 ||
      raw.keep_ranges.length > MAX_KEEP_RANGES) return null;

  const keepRanges = [];
  const ids = new Set();
  let priorEndWord = -1;
  let priorEndSeconds = -1;
  let keptSeconds = 0;
  for (const range of raw.keep_ranges) {
    if (!exactKeys(range, [
      'anchor_id', 'anchor_text', 'source_start_word', 'source_end_word',
      'source_start_seconds', 'source_end_seconds',
    ])) return null;
    const anchorId = canonicalText(range.anchor_id);
    const anchorText = canonicalText(range.anchor_text);
    const startWord = range.source_start_word;
    const endWord = range.source_end_word;
    const startSeconds = range.source_start_seconds;
    const endSeconds = range.source_end_seconds;
    if (!ANCHOR_ID.test(anchorId) || ids.has(anchorId) ||
        !anchorText || anchorText.length > MAX_ANCHOR_TEXT_CHARS ||
        !Number.isSafeInteger(startWord) || !Number.isSafeInteger(endWord) ||
        startWord < 0 || endWord < startWord || endWord >= transcript.words.length ||
        startWord <= priorEndWord || !finite(startSeconds) || !finite(endSeconds) ||
        startSeconds < priorEndSeconds - 0.001 || endSeconds <= startSeconds) return null;
    const expectedStart = transcript.words[startWord].start;
    const expectedEnd = transcript.words[endWord].end;
    const expectedText = canonicalText(transcript.words.slice(startWord, endWord + 1)
      .map((word) => word.word).join(' '));
    if (anchorText !== expectedText || Math.abs(startSeconds - expectedStart) > 0.001 ||
        Math.abs(endSeconds - expectedEnd) > 0.001) return null;
    ids.add(anchorId);
    keptSeconds += expectedEnd - expectedStart;
    priorEndWord = endWord;
    priorEndSeconds = expectedEnd;
    keepRanges.push(Object.freeze({
      anchor_id: anchorId,
      anchor_text: expectedText,
      source_start_word: startWord,
      source_end_word: endWord,
      source_start_seconds: expectedStart,
      source_end_seconds: expectedEnd,
    }));
  }
  if (keepRanges[0].anchor_id !== hookAnchorId ||
      keepRanges.at(-1).anchor_id !== closerAnchorId ||
      keptSeconds < minSeconds - 0.05 || keptSeconds > maxSeconds + 0.05) return null;
  return Object.freeze({
    schema_version: STORY_PLAN_SCHEMA,
    timeline: STORY_TIMELINE,
    target_duration: Object.freeze({ min_seconds: minSeconds, max_seconds: maxSeconds }),
    hook_anchor_id: hookAnchorId,
    closer_anchor_id: closerAnchorId,
    keep_ranges: Object.freeze(keepRanges),
  });
}

function structuralStoryPlan(raw) {
  if (!isPlainObject(raw)) throw new TypeError('story plan must be an object');
  if (!exactKeys(raw, [
    'schema_version', 'timeline', 'target_duration', 'hook_anchor_id',
    'closer_anchor_id', 'keep_ranges',
  ]) || raw.schema_version !== STORY_PLAN_SCHEMA || raw.timeline !== STORY_TIMELINE ||
      !exactKeys(raw.target_duration, ['min_seconds', 'max_seconds']) ||
      !Array.isArray(raw.keep_ranges) || raw.keep_ranges.length < 2 ||
      raw.keep_ranges.length > MAX_KEEP_RANGES) {
    throw new Error('story plan does not match the executable contract');
  }
  const minSeconds = raw.target_duration.min_seconds;
  const maxSeconds = raw.target_duration.max_seconds;
  const hookAnchorId = canonicalText(raw.hook_anchor_id);
  const closerAnchorId = canonicalText(raw.closer_anchor_id);
  if (!finite(minSeconds) || !finite(maxSeconds) || minSeconds <= 0 ||
      maxSeconds < minSeconds || !ANCHOR_ID.test(hookAnchorId) ||
      hookAnchorId !== raw.hook_anchor_id || !ANCHOR_ID.test(closerAnchorId) ||
      closerAnchorId !== raw.closer_anchor_id || hookAnchorId === closerAnchorId) {
    throw new Error('story plan target or anchor identity is invalid');
  }
  const ids = new Set();
  let priorEndWord = -1;
  let priorEndSeconds = -1;
  let keptSeconds = 0;
  for (const range of raw.keep_ranges) {
    if (!exactKeys(range, [
      'anchor_id', 'anchor_text', 'source_start_word', 'source_end_word',
      'source_start_seconds', 'source_end_seconds',
    ])) throw new Error('story plan keep range does not match the executable contract');
    const anchorId = canonicalText(range.anchor_id);
    const anchorText = canonicalText(range.anchor_text);
    if (!ANCHOR_ID.test(anchorId) || anchorId !== range.anchor_id || ids.has(anchorId) ||
        !anchorText ||
        anchorText !== range.anchor_text || anchorText.length > MAX_ANCHOR_TEXT_CHARS ||
        !Number.isSafeInteger(range.source_start_word) ||
        !Number.isSafeInteger(range.source_end_word) ||
        range.source_start_word < 0 ||
        range.source_end_word < range.source_start_word ||
        range.source_start_word <= priorEndWord ||
        !finite(range.source_start_seconds) || !finite(range.source_end_seconds) ||
        range.source_start_seconds < 0 ||
        range.source_start_seconds < priorEndSeconds - 0.001 ||
        range.source_end_seconds <= range.source_start_seconds) {
      throw new Error('story plan keep range is invalid or out of order');
    }
    ids.add(anchorId);
    priorEndWord = range.source_end_word;
    priorEndSeconds = range.source_end_seconds;
    keptSeconds += range.source_end_seconds - range.source_start_seconds;
  }
  if (raw.keep_ranges[0].anchor_id !== hookAnchorId ||
      raw.keep_ranges.at(-1).anchor_id !== closerAnchorId ||
      keptSeconds < minSeconds - 0.05 || keptSeconds > maxSeconds + 0.05) {
    throw new Error('story plan hook, closer, or target duration is invalid');
  }
  return raw;
}

module.exports = Object.freeze({
  STORY_PLAN_SCHEMA,
  STORY_TIMELINE,
  canonicalText,
  durationIntent,
  storyTranscript,
  normalizeStoryPlan,
  structuralStoryPlan,
});
