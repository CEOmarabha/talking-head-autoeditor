'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const ChatState = require('../helper/renderer/chat-state');
const { engineProgress } = require('../helper/lib/local-render');

assert.deepStrictEqual(ChatState.EVENT_TYPES, [
  'user_message', 'assistant_message',
  'analysis_started', 'analysis_progress', 'analysis_complete',
  'render_started', 'render_progress', 'render_heartbeat',
  'render_complete', 'render_warning', 'render_error', 'render_cancelled',
]);

function runFlow(platform) {
  const state = ChatState.createConversationState({ platform });
  const input = 'C:\\clips\\attached.mov';
  const output = 'C:\\renders\\finished.mp4';
  ChatState.dispatch(state, {
    type: 'user_message', content: 'Turn this into a strong short.',
    attachments: [input],
  }, 1000);
  assert.strictEqual(state.messages[0].role, 'user');
  assert.deepStrictEqual(state.messages[0].attachments, [input]);

  ChatState.dispatch(state, {
    type: 'analysis_started', stage: 'Inspecting and transcribing the attached video locally...',
  }, 2000);
  ChatState.dispatch(state, {
    type: 'analysis_progress', stage: 'Transcribing audio, still working',
    log: 'faster-whisper word-level transcript',
  }, 62000);
  ChatState.dispatch(state, {
    type: 'analysis_complete',
    content: 'Summary: one speaker explains the product. Strongest hook: the opening claim. Useful moments: the proof and demo. Plan: 9:16, fast pacing, word-synced captions, tight cuts, one grounded graphic, sparse sound, about 35 seconds. Say “render it” or request changes.',
    proposal: { operations: [{ op: 'set_edit_style', style: 'short' }] },
    canApply: true,
  }, 63000);
  assert.strictEqual(state.messages[1].kind, 'text');
  assert.match(state.messages[1].content, /Strongest hook/);
  assert.strictEqual(state.messages[1].canApply, true);

  ChatState.dispatch(state, { type: 'user_message', content: 'Render it.' }, 64000);
  const render = ChatState.dispatch(state, {
    type: 'render_started', stage: 'Starting the local edit...',
  }, 65000);
  assert.strictEqual(state.messages[2].content, 'Render it.');
  assert.strictEqual(state.messages[3], render);
  ChatState.dispatch(state, {
    type: 'render_progress', stage: 'Transcribing audio, still working',
    measurable: false, log: 'transcribe-only',
  }, 66000);
  ChatState.dispatch(state, { type: 'render_heartbeat' }, 126000);
  const timing = ChatState.renderTiming(state.activeRender, 126000);
  assert.strictEqual(timing.stale, true);
  assert.strictEqual(state.activeRender.progress, null);
  assert.deepStrictEqual(state.activeRender.logs, ['transcribe-only']);
  assert.match(ChatState.liveStatusReply(state, 126000), /Yes — it is rendering/);
  assert.match(ChatState.liveStatusReply(state, 126000), /last engine update/);

  const beforeStatus = state.messages.length;
  assert.strictEqual(ChatState.isStatusQuestion('Is it rendering?'), true);
  ChatState.dispatch(state, { type: 'user_message', content: 'Is it rendering?' }, 127000);
  ChatState.dispatch(state, {
    type: 'assistant_message', content: ChatState.liveStatusReply(state, 127000),
  }, 127001);
  assert.strictEqual(state.messages.length, beforeStatus + 2);
  assert.strictEqual(state.activeRender, render);

  ChatState.dispatch(state, {
    type: 'render_complete', videoPath: output,
    outputs: { master: output },
  }, 130000);
  assert.strictEqual(state.activeRender, null);
  assert.strictEqual(render.kind, 'video');
  assert.strictEqual(render.videoPath, output);
  assert.match(render.content, /Tell me what you want changed/);

  ChatState.dispatch(state, {
    type: 'user_message', content: 'Make captions bigger.',
    targetResultPath: output,
  }, 131000);
  assert.strictEqual(state.messages.at(-1).targetResultPath, output);
  return state.messages.map((message) => ({
    role: message.role, kind: message.kind, content: message.content,
    attachments: message.attachments, videoPath: message.videoPath,
    targetResultPath: message.targetResultPath,
  }));
}

assert.deepStrictEqual(runFlow('win32'), runFlow('darwin'));
assert.strictEqual(ChatState.isRenderCommand('render it'), true);
assert.strictEqual(ChatState.isRenderCommand('render it again with a new engine'), false);

const warningState = ChatState.createConversationState();
ChatState.dispatch(warningState, { type: 'render_started' }, 1);
ChatState.dispatch(warningState, {
  type: 'render_warning', videoPath: '/tmp/draft.UNVERIFIED.mp4',
  warning: 'caption_safe_area: bottom caption crossed the safe area',
}, 2);
assert.strictEqual(warningState.messages[0].kind, 'warning');
assert.match(warningState.messages[0].warning, /caption_safe_area/);
assert.ok(warningState.messages[0].videoPath);

const errorState = ChatState.createConversationState();
ChatState.dispatch(errorState, { type: 'render_started', stage: 'Encoding video' }, 1);
ChatState.dispatch(errorState, {
  type: 'render_error', stage: 'Encoding video', error: 'FFmpeg exited with code 1',
}, 2);
assert.strictEqual(errorState.messages[0].retry, true);
assert.strictEqual(errorState.messages[0].failedStage, 'Encoding video');

const persisted = ChatState.conversationSnapshot(errorState);
assert.strictEqual(persisted.schema, 'autoeditor-chat/v1');
assert.ok(!JSON.stringify(persisted).includes('proposal'));
const restored = ChatState.restoreConversation(JSON.parse(JSON.stringify(persisted)), {
  platform: 'darwin',
});
assert.strictEqual(restored.messages[0].failedStage, 'Encoding video');
assert.strictEqual(restored.platform, 'darwin');

const interrupted = ChatState.createConversationState();
ChatState.dispatch(interrupted, { type: 'render_started', stage: 'Encoding' }, 10);
const interruptedSnapshot = ChatState.conversationSnapshot(interrupted);
assert.strictEqual(ChatState.restoreConversation(interruptedSnapshot).activeRender.stage, 'Encoding');

assert.deepStrictEqual(engineProgress('faster-whisper word-level transcript'), {
  stage: 'transcription', message: 'Transcribing audio, still working',
  measurable: false,
});
assert.deepStrictEqual(engineProgress('[pse-edit] phase 7: QA gate'), {
  stage: 'quality-assurance', message: 'Checking video and audio quality...',
  measurable: false,
});

const rendererRoot = path.join(__dirname, '..', 'helper', 'renderer');
const html = fs.readFileSync(path.join(rendererRoot, 'index.html'), 'utf8');
const appSource = fs.readFileSync(path.join(rendererRoot, 'app.js'), 'utf8');
const mainSource = fs.readFileSync(path.join(__dirname, '..', 'helper', 'main.js'), 'utf8');
assert.ok(html.includes('Message DeepSeek'));
assert.ok(html.includes('Optional spoken words for generated/scripted content. Do not put editing instructions here.'));
assert.ok(!html.includes('Live edit console'));
assert.ok(appSource.includes("summary.textContent = 'Technical details'"));
assert.ok(appSource.includes("openResult(path, 'open')"));
assert.ok(appSource.includes("openResult(path, 'reveal')"));
assert.ok(appSource.includes('ChatState.restoreConversation'));
assert.ok(appSource.includes('window.helper.saveConversation'));
assert.ok(mainSource.includes('videos: [revisionInput]'));
assert.ok(mainSource.includes('activeRender: activeRenderState()'));

console.log('helper chat timeline tests passed');
