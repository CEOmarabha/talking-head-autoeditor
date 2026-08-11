'use strict';

const assert = require('assert');
const {
  DEEPSEEK_MODEL,
  EDITING_CONTEXT,
  EDIT_OPERATIONS,
  RESEARCH_INTENT,
  mediaEvidenceForPrompt,
  validateProposal,
} = require('../helper/lib/editing-harness');

assert.strictEqual(DEEPSEEK_MODEL, 'deepseek-v4-pro');
for (const capability of [
  'Remotion 4.0.507', 'HyperFrames', 'Sound design', 'ElevenLabs',
  'Pexels', 'Pixabay', 'A/V sync', 'Captions', 'PySceneDetect',
  'WhisperX', 'FireRed-OpenStoryline',
]) {
  assert.ok(EDITING_CONTEXT.includes(capability), capability);
}
assert.deepStrictEqual(Object.keys(EDIT_OPERATIONS), [
  'set_edit_style', 'set_aspect_ratio', 'set_caption_mode',
  'set_visual_mode', 'set_edit_profile',
]);
assert.ok(RESEARCH_INTENT.test('What is trending on Reddit and X this week?'));
assert.ok(RESEARCH_INTENT.test('Research useful GitHub editing repos'));
assert.ok(!RESEARCH_INTENT.test('Use short pacing and burned captions'));

const mediaEvidence = mediaEvidenceForPrompt({
  schema: 'autoeditor-local-media-analysis/v2',
  originalVideosUploaded: false,
  videos: Array.from({ length: 20 }, (_, index) => ({
    file: `clip-${index}.mp4`,
    technical: { durationSeconds: 10 + index },
    signals: { detectedSceneChanges: 300, sceneChangeTimes: Array(200).fill(1.25) },
    transcript: `transcript-${index} ${'word '.repeat(10000)}`,
    timedWords: Array(5000).fill({ word: 'word', start: 1, end: 2 }),
    visualSummary: `visible-${index} ${'frame '.repeat(2000)}`,
    localOnly: true,
  })),
});
assert.ok(mediaEvidence.length <= 80000);
const parsedMediaEvidence = JSON.parse(mediaEvidence);
assert.strictEqual(parsedMediaEvidence.originalVideosUploaded, false);
assert.strictEqual(parsedMediaEvidence.videos.length, 20);
assert.ok(parsedMediaEvidence.videos[19].visualSummary.includes('visible-19'));

assert.deepStrictEqual(validateProposal({
  summary: 'Make it a vertical social edit.',
  operations: [
    { op: 'set_edit_style', style: 'short' },
    { op: 'set_aspect_ratio', aspect: '9x16' },
    { op: 'set_caption_mode', mode: 'burned' },
    { op: 'set_visual_mode', mode: 'full' },
    { op: 'set_edit_profile', profile_id: 'generic_short' },
  ],
}), {
  summary: 'Make it a vertical social edit.',
  operations: [
    { op: 'set_edit_style', style: 'short', human: 'Use short edit pacing' },
    { op: 'set_aspect_ratio', aspect: '9x16', human: 'Deliver in 9x16' },
    { op: 'set_caption_mode', mode: 'burned', human: 'Use burned captions' },
    { op: 'set_visual_mode', mode: 'full', human: 'Use the full visual treatment' },
    { op: 'set_edit_profile', profile_id: 'generic_short', human: 'Use the generic_short edit profile' },
  ],
});
assert.strictEqual(validateProposal({ operations: [] }), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'remove_segment', start: 1, end: 5 }],
}), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short', command: 'rm -rf /' }],
}), null);
assert.strictEqual(validateProposal({
  operations: [
    { op: 'set_edit_style', style: 'short' },
    { op: 'set_edit_style', style: 'long' },
  ],
}), null);

console.log('editing harness contracts passed');
