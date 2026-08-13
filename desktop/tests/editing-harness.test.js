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
const {
  durationIntent, storyTranscript,
} = require('../helper/lib/story-plan');
const {
  CREATIVE_CONSTRAINTS_SCHEMA,
  CREATIVE_CONSTRAINTS_SCHEMA_EXAMPLE,
  normalizeCreativeConstraints,
  structuralCreativeConstraints,
} = require('../helper/lib/creative-constraints');

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
assert.ok(mediaEvidence.length <= 700000);
const parsedMediaEvidence = JSON.parse(mediaEvidence);
assert.strictEqual(parsedMediaEvidence.originalVideosUploaded, false);
assert.strictEqual(parsedMediaEvidence.videos.length, 20);
assert.ok(parsedMediaEvidence.videos[19].visualSummary.includes('visible-19'));
assert.strictEqual(parsedMediaEvidence.storyTranscript.complete, false);
assert.deepStrictEqual(parsedMediaEvidence.storyTranscript.words, []);

const sourceWords = Array.from({ length: 417 }, (_, index) => ({
  word: `word${index}`,
  start: Number((index * 0.4).toFixed(3)),
  end: Number(((index + 1) * 0.4).toFixed(3)),
}));
const sourceReport = {
  schema: 'autoeditor-local-media-analysis/v2',
  originalVideosUploaded: false,
  videos: [{
    file: '174-second-source.mov',
    technical: { durationSeconds: 174.9 },
    signals: {}, transcript: sourceWords.map((word) => word.word).join(' '),
    timedWords: sourceWords, visualSummary: 'One speaker', localOnly: true,
  }],
};
const completeEvidence = JSON.parse(mediaEvidenceForPrompt(sourceReport));
assert.strictEqual(completeEvidence.storyTranscript.complete, true);
assert.strictEqual(completeEvidence.storyTranscript.words.length, 417);
assert.strictEqual(storyTranscript(sourceReport).sourceDuration, 174.9);
assert.deepStrictEqual(durationIntent('Make this a premium 35-45s cut.'), {
  minSeconds: 35, maxSeconds: 45,
});

function exactAnchor(start, end) {
  return sourceWords.slice(start, end + 1).map((word) => word.word).join(' ');
}

const approvedStoryPlan = {
  schema_version: 'autoeditor-story-edit/v1',
  timeline: 'source_seconds',
  target_duration: { min_seconds: 35, max_seconds: 45 },
  hook_anchor_id: 'hook',
  closer_anchor_id: 'closer',
  keep_ranges: [
    {
      anchor_id: 'hook', anchor_text: exactAnchor(50, 99),
      source_start_word: 50, source_end_word: 99,
      source_start_seconds: 20, source_end_seconds: 40,
    },
    {
      anchor_id: 'closer', anchor_text: exactAnchor(300, 349),
      source_start_word: 300, source_end_word: 349,
      source_start_seconds: 120, source_end_seconds: 140,
    },
  ],
};
const approvedCreativeConstraints = {
  schema_version: CREATIVE_CONSTRAINTS_SCHEMA,
  opener: { exact_text: 'word50 word51', max_start_seconds: 3 },
  visual_policy: {
    graphics_exact: 1,
    broll_exact: 0,
    opening_punch_required: true,
    opening_visual_required: false,
    max_visual_gap_seconds: null,
  },
  required_graphic: {
    kind: 'callout',
    text: 'WORD60 VS WORD65',
    anchor_text: exactAnchor(60, 65),
  },
  music_allowed: false,
};
const approved = validateProposal({
  summary: 'A source-grounded 40 second story.',
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: approvedStoryPlan,
  creativeConstraints: approvedCreativeConstraints,
}, {
  mediaAnalysis: sourceReport, requireStoryPlan: true,
  requestedDuration: { minSeconds: 35, maxSeconds: 45 },
});
assert.ok(approved);
assert.strictEqual(approved.storyPlan.keep_ranges[0].anchor_text,
  exactAnchor(50, 99));
assert.strictEqual(approved.storyPlan.keep_ranges[0].source_start_word, 50);
assert.deepStrictEqual(approved.creativeConstraints, approvedCreativeConstraints);
assert.strictEqual(approved.creativeConstraints.music_allowed, false);
assert.ok(Object.isFrozen(approved.creativeConstraints));
assert.deepStrictEqual(CREATIVE_CONSTRAINTS_SCHEMA_EXAMPLE, {
  schema_version: 'autoeditor-creative-constraints/v1',
  opener: { exact_text: 'REPLACE WITH EXACT OPENER', max_start_seconds: 3 },
  visual_policy: {
    graphics_exact: 1, broll_exact: 0,
    opening_punch_required: true, opening_visual_required: false,
    max_visual_gap_seconds: null,
  },
  required_graphic: {
    kind: 'callout', text: 'REPLACE DISPLAY COPY',
    anchor_text: 'REPLACE WITH EXACT KEPT ANCHOR',
  },
  music_allowed: false,
});
assert.ok(Object.isFrozen(CREATIVE_CONSTRAINTS_SCHEMA_EXAMPLE));
assert.ok(JSON.stringify(CREATIVE_CONSTRAINTS_SCHEMA_EXAMPLE).includes('REPLACE'));
assert.ok(!JSON.stringify(CREATIVE_CONSTRAINTS_SCHEMA_EXAMPLE)
  .toLowerCase().includes('bad time'));
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
}, { mediaAnalysis: sourceReport, requireStoryPlan: true }), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: approvedStoryPlan,
}, { mediaAnalysis: sourceReport, requireStoryPlan: true }), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: approvedStoryPlan,
  creativeConstraints: {
    ...approvedCreativeConstraints,
    visual_policy: {
      ...approvedCreativeConstraints.visual_policy,
      random_transition_pack: true,
    },
  },
}, { mediaAnalysis: sourceReport, requireStoryPlan: true }), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: approvedStoryPlan,
  creativeConstraints: {
    ...approvedCreativeConstraints,
    visual_policy: {
      ...approvedCreativeConstraints.visual_policy, graphics_exact: 2,
    },
  },
}, { mediaAnalysis: sourceReport, requireStoryPlan: true }), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: approvedStoryPlan,
  creativeConstraints: {
    ...approvedCreativeConstraints,
    opener: { exact_text: 'word51 word52', max_start_seconds: 3 },
  },
}, { mediaAnalysis: sourceReport, requireStoryPlan: true }), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: approvedStoryPlan,
  creativeConstraints: {
    ...approvedCreativeConstraints,
    required_graphic: {
      ...approvedCreativeConstraints.required_graphic,
      anchor_text: exactAnchor(200, 205),
    },
  },
}, { mediaAnalysis: sourceReport, requireStoryPlan: true }), null);
assert.strictEqual(normalizeCreativeConstraints({
  ...approvedCreativeConstraints,
  required_graphic: {
    ...approvedCreativeConstraints.required_graphic,
    text: 'ONE TWO THREE FOUR FIVE',
  },
}, approvedStoryPlan), null);
for (const anchorText of [exactAnchor(60, 63), exactAnchor(60, 80)]) {
  assert.strictEqual(normalizeCreativeConstraints({
    ...approvedCreativeConstraints,
    required_graphic: {
      ...approvedCreativeConstraints.required_graphic,
      anchor_text: anchorText,
    },
  }, approvedStoryPlan), null);
}
assert.throws(() => structuralCreativeConstraints({
  ...approvedCreativeConstraints,
  opener: { exact_text: ' word50 word51 ', max_start_seconds: 3 },
}, approvedStoryPlan), /canonical text/);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: {
    ...approvedStoryPlan,
    target_duration: { min_seconds: 150, max_seconds: 160 },
  },
  creativeConstraints: approvedCreativeConstraints,
}, {
  mediaAnalysis: sourceReport, requireStoryPlan: true,
  requestedDuration: { minSeconds: 35, maxSeconds: 45 },
}), null);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  storyPlan: {
    ...approvedStoryPlan,
    keep_ranges: [
      { ...approvedStoryPlan.keep_ranges[0], anchor_text: 'hallucinated hook' },
      approvedStoryPlan.keep_ranges[1],
    ],
  },
  creativeConstraints: approvedCreativeConstraints,
}, {
  mediaAnalysis: sourceReport, requireStoryPlan: true,
  requestedDuration: { minSeconds: 35, maxSeconds: 45 },
}), null);

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
