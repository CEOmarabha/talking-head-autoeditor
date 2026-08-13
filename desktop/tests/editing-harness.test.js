'use strict';

const assert = require('assert');
const {
  DEEPSEEK_MODEL,
  EDITING_CONTEXT,
  EDIT_OPERATIONS,
  RESEARCH_INTENT,
  mediaEvidenceForPrompt,
  runEditingChat,
  sequenceEvidenceForPrompt,
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
const {
  TRANSITION_DECISION_SCHEMA_VERSION,
} = require('../helper/lib/transition-proposal');

assert.strictEqual(DEEPSEEK_MODEL, 'deepseek-v4-pro');
for (const capability of [
  'Remotion 4.0.507', 'HyperFrames', 'Sound design', 'ElevenLabs',
  'Pexels', 'Pixabay', 'A/V sync', 'Captions', 'PySceneDetect',
  'WhisperX', 'FireRed-OpenStoryline',
]) {
  assert.ok(EDITING_CONTEXT.includes(capability), capability);
}
assert.match(EDITING_CONTEXT,
  /typed expert policy[\s\S]*"auto" or "supporting" music/,
  'the proposal author must know the narrow governed project-generated music seam');
assert.match(EDITING_CONTEXT,
  /Never propose external, licensed, primary, or source-primary\s+music/,
  'the proposal manual must not invent broader music rights or capabilities');
assert.deepStrictEqual(Object.keys(EDIT_OPERATIONS), [
  'set_edit_style', 'set_aspect_ratio', 'set_caption_mode',
  'set_visual_mode', 'set_edit_profile',
]);
assert.ok(RESEARCH_INTENT.test('What is trending on Reddit and X this week?'));
assert.ok(RESEARCH_INTENT.test('Research useful GitHub editing repos'));
assert.ok(!RESEARCH_INTENT.test('Use short pacing and burned captions'));

const mediaEvidence = mediaEvidenceForPrompt({
  schema: 'autoeditor-local-media-analysis/v4',
  originalVideosUploaded: false,
  videos: Array.from({ length: 20 }, (_, index) => ({
    file: `clip-${index}.mp4`,
    technical: { durationSeconds: 10 + index,
      video: { startOffsetMs: 0 }, audio: { startOffsetMs: 0 } },
    signals: { detectedSceneChanges: 300, sceneChangeTimes: Array(200).fill(1.25) },
    transcript: `transcript-${index} ${'word '.repeat(10000)}`,
    timedWords: Array(5000).fill({ word: 'word', start: 1, end: 2 }),
    timedWordCount: 5001, timedWordsComplete: false,
    transcriptComplete: false,
    transcriptTimeline: 'container-relative-ms/v1',
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
  schema: 'autoeditor-local-media-analysis/v4',
  originalVideosUploaded: false,
  videos: [{
    file: '174-second-source.mov',
    technical: { durationSeconds: 174.9,
      video: { startOffsetMs: 0 }, audio: { startOffsetMs: 0 } },
    signals: {}, transcript: sourceWords.map((word) => word.word).join(' '),
    timedWords: sourceWords, timedWordCount: sourceWords.length,
    timedWordsComplete: true, transcriptComplete: true,
    transcriptTimeline: 'container-relative-ms/v1',
    visualSummary: 'One speaker', localOnly: true,
  }],
};
const completeEvidence = JSON.parse(mediaEvidenceForPrompt(sourceReport));
assert.strictEqual(completeEvidence.storyTranscript.complete, true);
assert.strictEqual(completeEvidence.storyTranscript.words.length, 417);
assert.strictEqual(storyTranscript(sourceReport).sourceDuration, 174.9);
assert.strictEqual(sequenceEvidenceForPrompt(sourceReport), null,
  'the multi-source planner must not accept media without full source identity');
const sourceReportWithIdentity = {
  ...sourceReport,
  videos: [{ ...sourceReport.videos[0],
    sourceId: `source-${'a'.repeat(24)}`, sourceSha256: 'a'.repeat(64),
    sourceBytes: 123456,
  }],
};
const sequenceEvidence = sequenceEvidenceForPrompt(sourceReportWithIdentity);
assert.strictEqual(sequenceEvidence.catalog.sources[0].transcript.complete, true);
assert.strictEqual(sequenceEvidence.privateCatalog.sources[0].transcript.complete, true);
assert.strictEqual(sequenceEvidence.manifest.sources[0].duration_ms, 174900);
const secondSourceWords = [
  { word: 'Second', start: 0.5, end: 0.8 },
  { word: 'camera', start: 0.81, end: 1.1 },
  { word: 'hook', start: 1.11, end: 1.5 },
];
const multiSourceReport = {
  schema: 'autoeditor-local-media-analysis/v4',
  videos: [sourceReportWithIdentity.videos[0], {
    file: 'second.mp4', sourceId: `source-${'b'.repeat(24)}`,
    sourceSha256: 'b'.repeat(64), sourceBytes: 654321,
    technical: { durationSeconds: 10,
      video: { startOffsetMs: 0 }, audio: { startOffsetMs: 0 } }, signals: {},
    transcript: 'Second camera hook', timedWords: secondSourceWords,
    timedWordCount: secondSourceWords.length, timedWordsComplete: true,
    transcriptComplete: true, transcriptTimeline: 'container-relative-ms/v1',
    visualSummary: 'A second speaker', localOnly: true,
  }],
};
const multiEvidence = sequenceEvidenceForPrompt(multiSourceReport);
const sequencePlan = {
  schema_version: 'autoeditor-sequence-plan/v1',
  sources: multiEvidence.manifest.sources,
  target_duration: { min_ms: 5000, max_ms: 5000 },
  segments: [{
    segment_id: 'second-hook', source_id: `source-${'b'.repeat(24)}`,
    source_sha256: 'b'.repeat(64), source_start_ms: 400,
    source_end_ms: 1700, role: 'hook', reason: 'Open on the second camera.',
    speech_anchor: { start_word: 0, end_word: 2, text: 'Second camera hook' },
    transition: { kind: 'hard_cut' },
  }, {
    segment_id: 'first-development', source_id: `source-${'a'.repeat(24)}`,
    source_sha256: 'a'.repeat(64), source_start_ms: 0,
    source_end_ms: 2200, role: 'development', reason: 'Continue with source one.',
    speech_anchor: { start_word: 0, end_word: 4,
      text: sourceWords.slice(0, 5).map((word) => word.word).join(' ') },
    transition: { kind: 'hard_cut' },
  }, {
    segment_id: 'first-closer', source_id: `source-${'a'.repeat(24)}`,
    source_sha256: 'a'.repeat(64), source_start_ms: 2200,
    source_end_ms: 3700, role: 'closer', reason: 'Close with source one.',
    speech_anchor: { start_word: 6, end_word: 8,
      text: sourceWords.slice(6, 9).map((word) => word.word).join(' ') },
    transition: { kind: 'hard_cut' },
  }],
};
const multiApproved = validateProposal({
  summary: 'A source-grounded multi-camera sequence.',
  operations: [{ op: 'set_edit_style', style: 'short' }],
  sequencePlan, sequenceSourceManifest: multiEvidence.manifest,
}, { mediaAnalysis: multiSourceReport, requireSequencePlan: true });
assert.ok(multiApproved);
assert.strictEqual(multiApproved.sequencePlan.segments[0].segment_id, 'second-hook');
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  sequencePlan: { ...sequencePlan, segments: [{
    ...sequencePlan.segments[0], speech_anchor: null,
  }, sequencePlan.segments[1]] },
  sequenceSourceManifest: multiEvidence.manifest,
}, { mediaAnalysis: multiSourceReport, requireSequencePlan: true }), null,
'known speech cannot bypass exact grounding by declaring a visual-only segment');

const transitionProjectIntent = {
  schema_version: 'autoeditor-project-intent/v1',
  profile: 'commercial_product',
  delivery: { platform: 'youtube', aspect: '16:9' },
  target_duration: { min_ms: 5000, max_ms: 5000 },
  preferences: {
    captions: { enabled: true, preference: 'auto' },
    graphics: { enabled: true, preference: 'auto' },
    music: { enabled: true, preference: 'auto' },
    sfx: { enabled: true, preference: 'auto' },
    transitions: { enabled: true, preference: 'motivated_only' },
  },
};
const transitionDecisions = {
  schema_version: TRANSITION_DECISION_SCHEMA_VERSION,
  boundaries: [{
    boundary_index: 0, kind: 'cross_dissolve', duration_ms: 200,
    motivation_verified: true, semantic_safety_verified: true,
    dialogue_preservation_verified: true,
  }, {
    boundary_index: 1, kind: 'hard_cut', duration_ms: 0,
    motivation_verified: false, semantic_safety_verified: true,
    dialogue_preservation_verified: true,
  }],
};
const transitionApproved = validateProposal({
  summary: 'Use one motivated dissolve and one hard cut.',
  operations: [{ op: 'set_edit_style', style: 'short' }],
  sequencePlan, sequenceSourceManifest: multiEvidence.manifest,
  projectIntent: transitionProjectIntent,
  transitionDecisions,
}, {
  mediaAnalysis: multiSourceReport,
  requireSequencePlan: true,
  allowProjectIntent: true,
});
assert.ok(transitionApproved);
assert.ok(!Object.prototype.hasOwnProperty.call(
  transitionApproved, 'transitionDecisions'));
assert.strictEqual(transitionApproved.transitionPlan.boundaries[0].kind,
  'cross_dissolve');
assert.strictEqual(transitionApproved.transitionPlan.boundaries[0].duration_ms, 200);
assert.strictEqual(
  transitionApproved.transitionSequenceManifest.segments.length,
  sequencePlan.segments.length,
);
assert.match(transitionApproved.transitionPlan.sequence_manifest_sha256,
  /^[0-9a-f]{64}$/);
assert.match(transitionApproved.transitionPlan.edit_policy_sha256,
  /^[0-9a-f]{64}$/);
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  sequencePlan, sequenceSourceManifest: multiEvidence.manifest,
  projectIntent: transitionProjectIntent,
  transitionDecisions,
}, { mediaAnalysis: multiSourceReport, requireSequencePlan: true }), null,
'projectIntent and timed transitions require explicit current-user opt-in');
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  sequencePlan, sequenceSourceManifest: multiEvidence.manifest,
  projectIntent: {
    ...transitionProjectIntent,
    preferences: {
      ...transitionProjectIntent.preferences,
      transitions: { enabled: true, preference: 'auto' },
    },
  },
  transitionDecisions,
}, {
  mediaAnalysis: multiSourceReport, requireSequencePlan: true,
  allowProjectIntent: true,
}), null, 'auto is not explicit authority for a timed transition overlay');
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  sequencePlan, sequenceSourceManifest: multiEvidence.manifest,
  projectIntent: transitionProjectIntent,
  transitionDecisions: {
    ...transitionDecisions,
    boundaries: transitionDecisions.boundaries.slice(0, 1),
  },
}, {
  mediaAnalysis: multiSourceReport, requireSequencePlan: true,
  allowProjectIntent: true,
}), null, 'the transition overlay must decide every sequence boundary');
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'short' }],
  sequencePlan, sequenceSourceManifest: multiEvidence.manifest,
  projectIntent: transitionProjectIntent,
  transitionDecisions: {
    ...transitionDecisions,
    boundaries: [{
      ...transitionDecisions.boundaries[0],
      ffmpeg: 'xfade=evil',
    }, transitionDecisions.boundaries[1]],
  },
}, {
  mediaAnalysis: multiSourceReport, requireSequencePlan: true,
  allowProjectIntent: true,
}), null, 'model-provided FFmpeg tokens never enter the approved carrier');

const longWords = Array.from({ length: 6001 }, (_, index) => ({
  word: `long${index}`, start: index * 0.04, end: index * 0.04 + 0.03,
}));
const longReport = {
  schema: 'autoeditor-local-media-analysis/v4',
  videos: [{
    file: 'long-source.mp4', sourceId: 'long-source',
    sourceSha256: 'c'.repeat(64), sourceBytes: 999999,
    technical: { durationSeconds: 300,
      video: { startOffsetMs: 0 }, audio: { startOffsetMs: 0 } },
    signals: {}, transcript: 'bounded prompt transcript',
    timedWords: longWords, timedWordCount: longWords.length,
    timedWordsComplete: true, transcriptComplete: true,
    transcriptTimeline: 'container-relative-ms/v1',
    visualSummary: 'Long-form speaking source', localOnly: true,
  }],
};
const longEvidence = sequenceEvidenceForPrompt(longReport);
assert.strictEqual(longEvidence.catalog.sources[0].transcript.complete, false,
  'the DeepSeek prompt excerpt must remain bounded');
assert.strictEqual(longEvidence.privateCatalog.sources[0].transcript.complete, true,
  'the on-device approval catalog must remain complete');
const longUnanchoredPlan = {
  schema_version: 'autoeditor-sequence-plan/v1',
  sources: longEvidence.manifest.sources,
  target_duration: { min_ms: 5000, max_ms: 5000 },
  segments: [{
    segment_id: 'late-speech', source_id: 'long-source',
    source_sha256: 'c'.repeat(64), source_start_ms: 240000,
    source_end_ms: 245000, role: 'development',
    reason: 'Select a known late spoken interval.', speech_anchor: null,
    transition: { kind: 'hard_cut' },
  }],
};
assert.strictEqual(validateProposal({
  operations: [{ op: 'set_edit_style', style: 'long' }],
  sequencePlan: longUnanchoredPlan,
  sequenceSourceManifest: longEvidence.manifest,
}, { mediaAnalysis: longReport, requireSequencePlan: true }), null,
'prompt truncation must not bypass private full-transcript grounding');
assert.strictEqual(storyTranscript({
  ...sourceReport,
  videos: [{ ...sourceReport.videos[0], timedWordsComplete: false,
    timedWordCount: sourceWords.length + 1 }],
}).complete, false,
'a truncated timed transcript must never become an executable story transcript');
assert.deepStrictEqual(durationIntent('Make this a premium 35-45s cut.'), {
  minSeconds: 35, maxSeconds: 45,
});

async function shortSequenceRequestIsExplainedNotSilentlyRewritten() {
  let capturedPrompt = '';
  const originalFetch = global.fetch;
  global.fetch = async (_url, init) => {
    capturedPrompt = JSON.parse(init.body).messages[0].content;
    return {
      ok: true,
      json: async () => ({ choices: [{ message: { content: JSON.stringify({
        message: 'The multi-source sequence minimum is 5 seconds.',
        summary: 'Nothing rendered.',
        operations: [],
      }) } }] }),
    };
  };
  try {
    const result = await runEditingChat({
      text: 'Make these clips exactly 2 seconds total',
      history: [], research: false, videoCount: 2, projectType: 'short',
      transcript: '', mediaAnalysis: multiSourceReport,
      hasCompletedRender: false,
    }, 'test-key', () => {});
    assert.ok(capturedPrompt.includes('hard product minimum of\n  5000ms'));
    assert.ok(capturedPrompt.includes('return operations as []'));
    assert.ok(capturedPrompt.includes('do not silently lengthen'));
    assert.deepStrictEqual(result.proposal, { operations: [] });
  } finally {
    global.fetch = originalFetch;
  }
}

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

shortSequenceRequestIsExplainedNotSilentlyRewritten().then(() => {
  console.log('editing harness contracts passed');
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
