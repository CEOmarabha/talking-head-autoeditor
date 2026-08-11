'use strict';

const assert = require('assert');
const {
  DEEPSEEK_MODEL,
  EDITING_CONTEXT,
  EDIT_OPERATIONS,
  RESEARCH_INTENT,
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
