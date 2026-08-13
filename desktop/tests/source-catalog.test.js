'use strict';

const assert = require('assert');
const {
  SOURCE_CATALOG_SCHEMA, groundSequenceSpeech, sourceCatalog,
  sourceCatalogForPrompt, sourceManifest,
} = require('../helper/lib/source-catalog');

function report({ duplicate = false, complete = true } = {}) {
  const words = [
    { word: 'Exact', start: 0.5, end: 0.8 },
    { word: 'spoken', start: 0.81, end: 1.1 },
    { word: 'anchor', start: 1.11, end: 1.5 },
  ];
  const video = (index) => ({
    sourceId: 'source-' + 'a'.repeat(24), sourceSha256: 'a'.repeat(64),
    sourceBytes: 1000 + index, file: `camera-${index}.mp4`,
    technical: { durationSeconds: 10,
      video: { startOffsetMs: 0 }, audio: { startOffsetMs: 0 } },
    timedWords: words, timedWordCount: complete ? words.length : words.length + 1,
    timedWordsComplete: complete, transcriptComplete: complete,
    transcriptTimeline: 'container-relative-ms/v1',
    signals: { sceneChangeTimes: [2, 5.5] }, visualSummary: 'A visible speaker.',
    localOnly: true,
  });
  return {
    schema: 'autoeditor-local-media-analysis/v4',
    videos: duplicate ? [video(1), video(2)] : [video(1)],
  };
}

function multiSourceReport(wordCounts) {
  const digestCharacters = ['1', '2', '3', '4', '5', '6'];
  return {
    schema: 'autoeditor-local-media-analysis/v4',
    videos: wordCounts.map((wordCount, sourceIndex) => {
      const words = Array.from({ length: wordCount }, (_, wordIndex) => ({
        word: `source${sourceIndex}-word${wordIndex}`,
        start: wordIndex * 0.04,
        end: wordIndex * 0.04 + 0.03,
      }));
      return {
        sourceId: `catalog-source-${sourceIndex}`,
        sourceSha256: digestCharacters[sourceIndex].repeat(64),
        sourceBytes: 10_000 + sourceIndex,
        file: `catalog-source-${sourceIndex}.mp4`,
        technical: {
          durationSeconds: Math.max(10, wordCount * 0.04 + 1),
          video: { startOffsetMs: 0 }, audio: { startOffsetMs: 0 },
        },
        timedWords: words, timedWordCount: words.length,
        timedWordsComplete: true, transcriptComplete: true,
        transcriptTimeline: 'container-relative-ms/v1',
        signals: { sceneChangeTimes: [] },
        visualSummary: `Complete source ${sourceIndex}.`, localOnly: true,
      };
    }),
  };
}

const catalog = sourceCatalog(report());
assert.strictEqual(catalog.schema_version, SOURCE_CATALOG_SCHEMA);
assert.strictEqual(catalog.sources[0].duration_ms, 10000);
assert.strictEqual(catalog.sources[0].transcript.words[2].end_ms, 1500);
assert.deepStrictEqual(catalog.sources[0].scene_change_ms, [2000, 5500]);
assert.deepStrictEqual(catalog.sources[0].timeline, {
  video_start_offset_ms: 0, audio_start_offset_ms: 0,
});
assert.deepStrictEqual(sourceManifest(catalog), {
  schema_version: 'autoeditor-source-manifest/v1',
  sources: [{ source_id: `source-${'a'.repeat(24)}`,
    sha256: 'a'.repeat(64), duration_ms: 10000 }],
});
assert.strictEqual(sourceCatalogForPrompt(catalog).sources[0].transcript.complete,
  true);

const delayedAudioReport = report();
delayedAudioReport.videos[0].technical.audio.startOffsetMs = 500;
delayedAudioReport.videos[0].timedWords = delayedAudioReport.videos[0].timedWords
  .map((word) => ({ ...word, start: word.start + 0.5, end: word.end + 0.5 }));
const delayedAudioCatalog = sourceCatalog(delayedAudioReport);
assert.strictEqual(
  delayedAudioCatalog.sources[0].timeline.audio_start_offset_ms, 500);
assert.strictEqual(delayedAudioCatalog.sources[0].transcript.words[0].start_ms,
  1000, 'the catalog must retain the container-relative +500ms word shift');

assert.throws(() => sourceCatalog(report({ duplicate: true })),
  /same source content/);

const source = catalog.sources[0];
const plan = {
  segments: [{
    segment_id: 'hook', source_id: source.source_id, source_sha256: source.sha256,
    source_start_ms: 400, source_end_ms: 1700,
    speech_anchor: { start_word: 0, end_word: 2, text: 'Exact spoken anchor' },
  }],
};
assert.strictEqual(groundSequenceSpeech(plan, catalog), plan);
assert.throws(() => groundSequenceSpeech({ segments: [{
  ...plan.segments[0], speech_anchor: { start_word: 0, end_word: 2,
    text: 'Exact inverted anchor' },
}] }, catalog), /not exactly source grounded/);
assert.throws(() => groundSequenceSpeech(plan,
  sourceCatalog(report({ complete: false }))), /incomplete transcript/);
assert.throws(() => groundSequenceSpeech({ segments: [{
  ...plan.segments[0], speech_anchor: null,
}] }, catalog), /containing known speech requires an exact anchor/);
assert.strictEqual(groundSequenceSpeech({ segments: [{
  ...plan.segments[0], source_start_ms: 2000, source_end_ms: 2500,
  speech_anchor: null,
}] }, catalog).segments[0].speech_anchor, null,
'a genuinely silent source interval may remain a visual-only segment');
assert.throws(() => sourceCatalog({
  ...report(), schema: report().schema.replace(/v4$/, `v${4 - 1}`),
}), /v4/, 'pre-v4 analysis fixtures must never enter the source catalog');
assert.throws(() => sourceCatalog({ ...report(), videos: [{
  ...report().videos[0], sourceSha256: 'A'.repeat(64),
}] }), /full source identity/);

for (const mutate of [
  (video) => { delete video.timedWordCount; },
  (video) => { delete video.transcriptComplete; },
  (video) => { delete video.transcriptTimeline; },
  (video) => { delete video.technical.audio; },
  (video) => { video.localOnly = false; },
]) {
  const legacy = report();
  mutate(legacy.videos[0]);
  assert.throws(() => sourceCatalog(legacy), /v4|completeness/,
    'legacy fallback fields must not be inferred by the v4 catalog');
}

const stringDuration = report();
stringDuration.videos[0].technical.durationSeconds = '10';
assert.throws(() => sourceCatalog(stringDuration), /finite source time/,
  'numeric strings from legacy fixtures must not be coerced');

const unknownOffset = report();
unknownOffset.videos[0].technical.audio.startOffsetMs = null;
assert.throws(() => sourceCatalog(unknownOffset), /complete source timeline/);

const noAudio = report();
noAudio.videos[0].technical.audio = null;
noAudio.videos[0].transcript = '';
noAudio.videos[0].transcriptComplete = false;
noAudio.videos[0].timedWords = [];
noAudio.videos[0].timedWordCount = 0;
noAudio.videos[0].timedWordsComplete = false;
assert.strictEqual(sourceCatalog(noAudio).sources[0].timeline.audio_start_offset_ms,
  null, 'v4 no-audio evidence must use an explicit null stream');

const fairCatalog = sourceCatalog(multiSourceReport([7000, 7]));
const fairPromptCatalog = sourceCatalogForPrompt(fairCatalog);
const [longPromptSource, shortPromptSource] = fairPromptCatalog.sources;
assert.strictEqual(
  fairPromptCatalog.sources.reduce((total, item) =>
    total + item.transcript.words.length, 0),
  6000,
  'one early long transcript must not consume words reserved for later sources',
);
assert.strictEqual(longPromptSource.transcript.words.length, 5993);
assert.strictEqual(longPromptSource.transcript.complete, false);
assert.strictEqual(shortPromptSource.transcript.words.length, 7);
assert.strictEqual(shortPromptSource.transcript.complete, true,
  'a later short complete transcript must remain fully anchorable');
assert.deepStrictEqual(
  shortPromptSource.transcript.words.map((word) => word.index),
  [0, 1, 2, 3, 4, 5, 6],
  'prompt word indices must remain source-global indices',
);
assert.strictEqual(longPromptSource.transcript.words[0].index, 0);
assert.strictEqual(longPromptSource.transcript.words.at(-1).index, 6999,
  'a truncated long source must expose stratified early and late anchors');
assert(longPromptSource.transcript.words.some((word) =>
  word.index >= 3400 && word.index <= 3600),
'a truncated long source must expose a middle anchor stratum');

const selectedLongIndices = new Set(
  longPromptSource.transcript.words.map((word) => word.index));
const omittedLongWord = fairCatalog.sources[0].transcript.words.find((word) =>
  !selectedLongIndices.has(word.index));
assert(omittedLongWord, 'the bounded public prompt must omit some long-source words');
assert(!JSON.stringify(fairPromptCatalog).includes(`"${omittedLongWord.text}"`),
  'omitted private transcript words must not leak into prompt evidence');
assert(!Object.prototype.hasOwnProperty.call(fairPromptCatalog, 'privateCatalog'));
const privateAnchorPlan = { segments: [{
  source_id: fairCatalog.sources[0].source_id,
  source_sha256: fairCatalog.sources[0].sha256,
  source_start_ms: omittedLongWord.start_ms - 5,
  source_end_ms: omittedLongWord.end_ms + 5,
  speech_anchor: {
    start_word: omittedLongWord.index,
    end_word: omittedLongWord.index,
    text: omittedLongWord.text,
  },
}] };
assert.strictEqual(groundSequenceSpeech(privateAnchorPlan, fairCatalog),
  privateAnchorPlan,
  'private approval grounding must retain the complete immutable transcript');

const stratifiedCatalog = sourceCatalog(multiSourceReport([6100, 6100, 6100, 6100]));
const stratifiedPrompt = sourceCatalogForPrompt(stratifiedCatalog);
assert.deepStrictEqual(
  stratifiedPrompt.sources.map((item) => item.transcript.words.length),
  [1500, 1500, 1500, 1500],
  'the global budget must be divided fairly across every complete source',
);
for (const sourceExcerpt of stratifiedPrompt.sources) {
  const indices = sourceExcerpt.transcript.words.map((word) => word.index);
  assert.strictEqual(indices[0], 0);
  assert.strictEqual(indices.at(-1), 6099);
  assert(indices.some((index) => index >= 3000 && index <= 3100));
  assert(indices.every((index, position) =>
    position === 0 || index > indices[position - 1]),
  'stratified prompt words must preserve ascending global indices');
}

console.log('source catalog contracts passed');
