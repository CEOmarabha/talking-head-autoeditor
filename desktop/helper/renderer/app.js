const $ = (id) => document.getElementById(id);
const ChatState = window.AutoEditorChatState;
const ViewState = window.AutoEditorViewState;

const app = {
  videos: [], outputDir: '', resultPath: '', transcript: '', proposal: null,
  conversation: ChatState.createConversationState(),
  attachmentsDirty: false, chatQueue: [], currentChat: null,
  lastRenderPayload: null, proposalTargetResultPath: '', proposalBrief: '', platform: '',
  attachmentRevision: 0,
};

let visionWorker = null;
let activeVisionId = null;
let lastSavedConversation = '';
let conversationSaveTimer = null;

function asError(error) {
  const text = error?.message || String(error || 'Something went wrong.');
  return text.replace(/^Error invoking remote method '[^']+':\s*(Error:\s*)?/, '');
}

function localVisionWorker() {
  if (visionWorker) return visionWorker;
  visionWorker = new Worker('../vision/vision-worker.bundle.js', {
    name: 'autoeditor-local-vision',
  });
  visionWorker.addEventListener('message', (event) => {
    const value = event.data;
    if (!value || typeof value !== 'object' || value.id !== activeVisionId) return;
    if (value.status === 'progress') {
      window.helper.visionProgress({ id: value.id, line: value.line });
      return;
    }
    activeVisionId = null;
    window.helper.visionResult(value);
  });
  visionWorker.addEventListener('error', (event) => {
    if (!activeVisionId) return;
    const id = activeVisionId;
    activeVisionId = null;
    window.helper.visionResult({
      id, status: 'error',
      error: String(event.message || 'the local vision worker could not start').slice(0, 1000),
    });
    visionWorker.terminate();
    visionWorker = null;
  });
  return visionWorker;
}

window.helper.onVisionRequest((request) => {
  const id = request?.id;
  const images = request?.images;
  if (!Number.isSafeInteger(id) || id < 1 || !Array.isArray(images) ||
      images.length < 1 || images.length > 8) return;
  if (activeVisionId !== null) {
    window.helper.visionResult({ id, status: 'error', error: 'the local vision model is already working' });
    return;
  }
  activeVisionId = id;
  try {
    localVisionWorker().postMessage({
      id, images,
      mode: typeof request.mode === 'string' ? request.mode.slice(0, 80) : '',
      context: typeof request.context === 'string'
        ? request.context.slice(0, 8000) : '',
    });
  } catch (error) {
    activeVisionId = null;
    window.helper.visionResult({ id, status: 'error', error: asError(error).slice(0, 1000) });
  }
});

const CHAT_HISTORY_MAX_ENTRIES = 12;
const CHAT_HISTORY_MAX_ENTRY_CHARS = 2000;
const CHAT_HISTORY_MAX_TOTAL_CHARS = 12000;

function boundedChatHistory(messages) {
  const entries = messages
    .filter((message) => message.kind === 'text' && message.content &&
      (message.role === 'user' || message.role === 'assistant'))
    .slice(-CHAT_HISTORY_MAX_ENTRIES)
    .map(({ role, content }) => ({
      role,
      content: content.length > CHAT_HISTORY_MAX_ENTRY_CHARS
        ? content.slice(0, CHAT_HISTORY_MAX_ENTRY_CHARS - 3) + '...'
        : content,
    }));
  let total = entries.reduce((sum, entry) => sum + entry.content.length, 0);
  while (entries.length && total > CHAT_HISTORY_MAX_TOTAL_CHARS) {
    total -= entries.shift().content.length;
  }
  return entries;
}

function fileName(path) {
  return String(path || '').split(/[\\/]/).filter(Boolean).pop() || String(path || 'Video');
}

function localFileUrl(raw) {
  const normalized = String(raw || '').replace(/\\/g, '/');
  const encoded = normalized.split('/').map((part) =>
    /^[A-Za-z]:$/.test(part) ? part : encodeURIComponent(part)).join('/');
  return normalized.startsWith('/') ? `file://${encoded}` : `file:///${encoded}`;
}

function normalizePaths(value) {
  const paths = Array.isArray(value) ? value
    : value?.paths || value?.videos || value?.videoPaths || (value?.path ? [value.path] : []);
  return paths.filter((path) => typeof path === 'string' && path.trim());
}

function normalizePath(value) {
  if (typeof value === 'string') return value;
  return value?.path || value?.outputDir || value?.resultPath || '';
}

function setStatus(label, tone = '') {
  $('status').textContent = label;
  $('status').className = `pill ${tone}`.trim();
}

function providerSaved(state, name) {
  const providers = state?.providers || state?.settings || state?.configuredProviders || {};
  return Boolean(providers[name] || providers[`${name}Configured`] ||
    providers[`${name}Saved`] || providers[`${name}ApiKey`] ||
    (name === 'remotion' && (providers.remotionKey || providers.remotionLicenseKey)) ||
    state?.[`${name}Configured`] || state?.[`${name}ApiKey`] ||
    (name === 'remotion' && (state?.remotionKey || state?.remotionLicenseKey)));
}

function renderProviderStates(state) {
  const inputIds = {
    deepseek: 'deepseek-key', pexels: 'pexels-key', pixabay: 'pixabay-key',
    eleven: 'eleven-key', remotion: 'remotion-key',
  };
  ['deepseek', 'pexels', 'pixabay', 'eleven', 'remotion'].forEach((name) => {
    const saved = providerSaved(state, name) ||
      (name === 'eleven' && providerSaved(state, 'elevenLabs'));
    const target = $(`${name}-saved`);
    target.textContent = saved ? 'Saved securely and reused automatically' : '';
    target.classList.toggle('visible', saved);
    const input = $(inputIds[name]);
    if (!input.dataset.emptyPlaceholder) input.dataset.emptyPlaceholder = input.placeholder;
    input.placeholder = saved
      ? 'Saved. Paste a new key only if you want to replace it.'
      : input.dataset.emptyPlaceholder;
  });
}

function renderVideos() {
  const hasVideos = app.videos.length > 0;
  $('video-list-wrap').classList.toggle('hidden', !hasVideos);
  $('video-empty').textContent = hasVideos
    ? `${app.videos.length} ready for your next message`
    : 'Drag and drop here';
  $('video-count').textContent = `${app.videos.length} ${app.videos.length === 1 ? 'video' : 'videos'} ready to attach`;
  $('video-list').replaceChildren();
  app.videos.forEach((path, index) => {
    const item = document.createElement('li');
    const copy = document.createElement('div');
    const name = document.createElement('strong');
    const location = document.createElement('span');
    const remove = document.createElement('button');
    name.textContent = fileName(path);
    location.textContent = path;
    copy.append(name, location);
    remove.type = 'button';
    remove.className = 'remove-file';
    remove.textContent = 'Remove';
    remove.addEventListener('click', () => {
      app.videos.splice(index, 1);
      invalidateAttachmentAnalysis();
      app.attachmentsDirty = true;
      renderVideos();
    });
    item.append(copy, remove);
    $('video-list').appendChild(item);
  });
}

function sourceList(sources) {
  if (!Array.isArray(sources) || !sources.length) return null;
  const list = document.createElement('ol');
  list.className = 'source-list';
  sources.slice(0, 12).forEach((source, index) => {
    if (!source || typeof source.url !== 'string') return;
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'source-button';
    button.textContent = `[${index + 1}] ${source.title || source.source || 'Research source'}${source.date ? `, ${source.date}` : ''}`;
    button.addEventListener('click', async () => {
      try { await window.helper.openResearchSource(source.url); }
      catch (error) { $('chat-error').textContent = asError(error); }
    });
    item.appendChild(button);
    list.appendChild(item);
  });
  return list.childElementCount ? list : null;
}

function mediaMessage(path, allowActions, mediaKey) {
  const wrap = document.createElement('div');
  const video = document.createElement('video');
  const footer = document.createElement('div');
  const copy = document.createElement('div');
  const name = document.createElement('strong');
  const location = document.createElement('span');
  wrap.className = 'chat-media';
  video.controls = true;
  video.preload = 'metadata';
  video.src = localFileUrl(path);
  video.dataset.mediaKey = mediaKey;
  footer.className = 'chat-media-footer';
  name.textContent = fileName(path);
  location.textContent = path;
  copy.append(name, location);
  footer.appendChild(copy);
  if (allowActions) {
    const actions = document.createElement('div');
    actions.className = 'result-actions';
    const open = document.createElement('button');
    open.type = 'button';
    open.textContent = 'Open';
    open.addEventListener('click', () => window.helper.openResult(path, 'open'));
    const reveal = document.createElement('button');
    reveal.type = 'button';
    reveal.textContent = 'Show in folder';
    reveal.addEventListener('click', () => window.helper.openResult(path, 'reveal'));
    actions.append(open, reveal);
    footer.appendChild(actions);
  }
  wrap.append(video, footer);
  return wrap;
}

function technicalDetails(logs, detailsKey) {
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  const pre = document.createElement('pre');
  details.className = 'technical-details';
  details.dataset.detailsKey = detailsKey;
  summary.textContent = 'Technical details';
  pre.textContent = logs.length ? logs.join('\n') : 'Waiting for engine output...';
  details.append(summary, pre);
  return details;
}

function renderActivity(message, messageKey) {
  const card = document.createElement('div');
  const stage = document.createElement('strong');
  const timing = document.createElement('div');
  card.className = `activity-card ${message.kind}`;
  stage.className = 'activity-stage';
  stage.textContent = message.stage || 'Working...';
  card.appendChild(stage);
  if (message.kind === 'render') {
    const value = ChatState.renderTiming(message, Date.now());
    timing.className = 'activity-timing';
    timing.textContent = value.stale
      ? `Elapsed ${value.elapsed} · Still working; last engine update ${value.lastActivity}`
      : `Elapsed ${value.elapsed} · Last activity ${value.lastActivity}`;
    card.appendChild(timing);
    if (message.measurable && Number.isFinite(message.progress)) {
      const progress = document.createElement('progress');
      progress.max = 100;
      progress.value = message.progress;
      progress.textContent = `${message.progress}%`;
      const label = document.createElement('span');
      label.className = 'progress-label';
      label.textContent = `${message.progress}%`;
      card.append(progress, label);
    } else {
      const working = document.createElement('div');
      working.className = 'working-indicator';
      working.innerHTML = '<i></i><i></i><i></i><span>Working</span>';
      card.appendChild(working);
    }
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'ghost';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', cancelRender);
    card.appendChild(cancel);
  }
  card.appendChild(technicalDetails(message.logs || [], `${messageKey}:details`));
  return card;
}

function addProposalButton(row, message) {
  if (!message.canApply || !message.proposal || app.conversation.activeRender) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'primary proposal-button';
  button.textContent = 'Render these changes';
  button.addEventListener('click', () => {
    ChatState.dispatch(app.conversation, {
      type: 'user_message', content: 'Render it.',
      targetResultPath: message.targetResultPath || '',
    });
    renderChat();
    startRender(message.proposal, null, message.targetResultPath || '');
  });
  row.appendChild(button);
}

function renderChat(options = {}) {
  scheduleConversationSave();
  const transcript = $('chat-transcript');
  const viewSnapshot = ViewState.captureTranscriptView(transcript);
  transcript.replaceChildren();
  if (!app.conversation.messages.length) {
    const empty = document.createElement('p');
    empty.id = 'chat-empty';
    empty.className = 'chat-empty';
    empty.textContent = 'Attach a video and tell DeepSeek how you want it edited.';
    transcript.appendChild(empty);
    ViewState.restoreTranscriptView(transcript, viewSnapshot, options);
    return;
  }
  app.conversation.messages.forEach((message, messageIndex) => {
    const row = document.createElement('div');
    const role = document.createElement('span');
    const messageKey = message.id || `message-${messageIndex}`;
    row.className = `chat-message ${message.role === 'user' ? 'user' : 'assistant'} ${message.kind || 'text'}`;
    row.dataset.messageId = messageKey;
    role.textContent = message.role === 'user' ? 'You' : 'DeepSeek';
    row.appendChild(role);
    if (message.content) {
      const content = document.createElement('p');
      content.textContent = message.kind === 'error' && message.failedStage
        ? `Failed during ${message.failedStage}: ${message.content}` : message.content;
      row.appendChild(content);
    }
    (message.attachments || []).forEach((path, attachmentIndex) =>
      row.appendChild(mediaMessage(path, false, `${messageKey}:attachment:${attachmentIndex}`)));
    if (message.kind === 'analysis' || message.kind === 'render') {
      row.appendChild(renderActivity(message, messageKey));
    }
    if (message.kind === 'warning' && message.warning) {
      const warning = document.createElement('div');
      warning.className = 'warning-banner';
      warning.textContent = `Needs review: ${message.warning}`;
      row.appendChild(warning);
    }
    if (message.videoPath) {
      row.appendChild(mediaMessage(message.videoPath, true, `${messageKey}:result`));
    }
    if ((message.kind === 'video' || message.kind === 'warning') && (message.logs || []).length) {
      row.appendChild(technicalDetails(message.logs, `${messageKey}:details`));
    }
    if (message.kind === 'error' && message.retry) {
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'primary';
      retry.textContent = 'Retry';
      retry.disabled = !app.lastRenderPayload;
      retry.addEventListener('click', () => startRender(null, app.lastRenderPayload));
      row.appendChild(retry);
      if ((message.logs || []).length) {
        row.appendChild(technicalDetails(message.logs, `${messageKey}:details`));
      }
    }
    const sources = sourceList(message.sources);
    if (sources) row.appendChild(sources);
    addProposalButton(row, message);
    transcript.appendChild(row);
  });
  ViewState.restoreTranscriptView(transcript, viewSnapshot, options);
  const rendering = !!app.conversation.activeRender;
  const analyzing = !!app.conversation.activeAnalysis;
  setStatus(rendering ? 'Rendering' : (analyzing ? 'Analyzing' : 'Ready'),
    rendering || analyzing ? 'on' : '');
}

function invalidateAttachmentAnalysis() {
  app.attachmentRevision += 1;
  app.transcript = '';
  app.proposal = null;
  app.proposalBrief = '';
  app.proposalTargetResultPath = '';
  app.lastRenderPayload = null;
}

function refreshActiveRenderClock(clock = Date.now()) {
  const render = app.conversation.activeRender;
  if (!render) return;
  const messageId = String(render.id || '');
  const row = Array.from($('chat-transcript').querySelectorAll('[data-message-id]'))
    .find((candidate) => candidate.dataset.messageId === messageId);
  const timing = row?.querySelector('.activity-timing');
  if (!timing) return;
  const value = ChatState.renderTiming(render, clock);
  timing.textContent = value.stale
    ? `Elapsed ${value.elapsed} \u00b7 Still working; last engine update ${value.lastActivity}`
    : `Elapsed ${value.elapsed} \u00b7 Last activity ${value.lastActivity}`;
}

function scheduleConversationSave() {
  const snapshot = ChatState.conversationSnapshot(app.conversation);
  const encoded = JSON.stringify(snapshot);
  if (encoded === lastSavedConversation || conversationSaveTimer) return;
  conversationSaveTimer = setTimeout(async () => {
    conversationSaveTimer = null;
    const current = ChatState.conversationSnapshot(app.conversation);
    const currentEncoded = JSON.stringify(current);
    if (currentEncoded === lastSavedConversation) return;
    try {
      await window.helper.saveConversation(current);
      lastSavedConversation = currentEncoded;
    } catch (error) {
      $('chat-error').textContent = `Conversation could not be saved securely: ${asError(error)}`;
    }
  }, 150);
}

function assistantMessage(content, kind = 'text') {
  ChatState.dispatch(app.conversation, { type: 'assistant_message', content, kind });
  renderChat();
}

function renderRequest() {
  const script = $('script').value.trim();
  return {
    videos: [...app.videos], outputDir: app.outputDir,
    projectType: $('project-type').value, script,
    cachedTranscript: script ? '' : app.transcript.slice(0, 30000),
    creativeBrief: app.proposalBrief.slice(0, 8000),
  };
}

async function startRender(proposal, retryPayload = null, targetResultPath) {
  if (app.conversation.activeRender) {
    const state = await window.helper.state();
    assistantMessage(ChatState.liveStatusReply(
      app.conversation, Date.now(), state?.activeRender));
    return;
  }
  const payload = retryPayload || (proposal ? {
    ...renderRequest(), proposal,
    resultPath: (targetResultPath ?? app.proposalTargetResultPath) || undefined,
  } : null);
  if (!payload) {
    assistantMessage('I need an executable edit plan before I can render. Ask for the changes you want first.');
    return;
  }
  if (!payload.videos?.length && !payload.resultPath) {
    assistantMessage('Attach at least one video before rendering.', 'error');
    return;
  }
  if (!payload.outputDir) {
    assistantMessage('Choose a save folder in Optional settings before rendering.', 'error');
    document.querySelector('.edit-options').open = true;
    return;
  }
  app.lastRenderPayload = payload;
  ChatState.dispatch(app.conversation, {
    type: 'render_started', stage: retryPayload
      ? 'Retrying the local edit...' : 'Starting the local edit...',
  });
  app.proposal = null;
  renderChat();
  try {
    await window.helper.applyLocal(payload);
  } catch (error) {
    ChatState.dispatch(app.conversation, {
      type: 'render_error', stage: 'starting the render', error: asError(error),
    });
    renderChat();
  }
}

async function cancelRender() {
  try {
    await window.helper.cancelLocal();
  } catch (error) {
    $('render-error').textContent = asError(error);
  }
}

async function answerLiveStatus() {
  let snapshot = null;
  try { snapshot = (await window.helper.state())?.activeRender || null; }
  catch (_) { /* mirrored state still gives a truthful last-known answer */ }
  assistantMessage(ChatState.liveStatusReply(app.conversation, Date.now(), snapshot));
}

function queueChat(job) {
  app.chatQueue.push(job);
  drainChatQueue();
}

async function drainChatQueue() {
  if (app.currentChat || !app.chatQueue.length) return;
  const job = app.chatQueue.shift();
  app.currentChat = job;
  ChatState.dispatch(app.conversation, {
    type: 'analysis_started',
    stage: job.attachments.length
      ? 'Inspecting and transcribing the attached video locally...'
      : 'DeepSeek is reviewing the conversation...',
  });
  renderChat();
  $('chat-status').textContent = app.chatQueue.length
    ? `${app.chatQueue.length} message(s) queued` : '';
  try {
    await window.helper.chatLocal({
      text: job.text, history: job.history,
      projectType: $('project-type').value,
      transcript: (app.transcript || $('script').value.trim()).slice(0, 20000),
      videoCount: job.attachments.length,
      ...(job.attachments.length ? { videoPaths: job.attachments } : {}),
      resultPath: job.targetResultPath || undefined,
      research: $('live-research').checked,
    });
  } catch (error) {
    ChatState.dispatch(app.conversation, {
      type: 'analysis_complete', kind: 'error',
      content: `DeepSeek could not answer: ${asError(error)}`,
    });
    app.currentChat = null;
    renderChat();
    drainChatQueue();
  }
}

async function submitMessage() {
  const text = $('chat-prompt').value.trim();
  if (!text) return;
  $('chat-prompt').value = '';
  $('chat-error').textContent = '';
  const before = [...app.conversation.messages];
  const attachments = app.attachmentsDirty ? [...app.videos] : [];
  app.attachmentsDirty = false;
  ChatState.dispatch(app.conversation, {
    type: 'user_message', content: text, attachments,
    targetResultPath: app.resultPath,
  });
  renderChat();
  if (ChatState.isStatusQuestion(text)) {
    await answerLiveStatus();
    return;
  }
  if (ChatState.isRenderCommand(text)) {
    if (app.conversation.activeRender) await answerLiveStatus();
    else await startRender(app.proposal);
    return;
  }
  queueChat({
    text, attachments, history: boundedChatHistory(before),
    targetResultPath: attachments.length ? '' : app.resultPath,
    attachmentRevision: app.attachmentRevision,
  });
}

function handleRenderEvent(event = {}) {
  if (typeof event === 'string') {
    const kind = app.conversation.activeRender ? 'render' : 'chat';
    handleRawLog({ line: event, kind });
    return;
  }
  const kind = event.kind || (event.event === 'local-chat' ? 'chat'
    : (app.conversation.activeRender ? 'render' : 'chat'));
  if (event.event === 'local-canceled') {
    ChatState.dispatch(app.conversation, {
      type: 'render_cancelled', content: 'Edit canceled.',
    });
    renderChat();
    return;
  }
  if (event.event === 'local-error') {
    if (kind === 'render') {
      ChatState.dispatch(app.conversation, {
        type: 'render_error', stage: event.stage || 'rendering',
        error: event.error || 'The render could not finish.',
      });
    } else {
      ChatState.dispatch(app.conversation, {
        type: 'analysis_complete', kind: 'error',
        content: event.error || 'DeepSeek could not finish the analysis.',
      });
      app.currentChat = null;
      drainChatQueue();
    }
    renderChat();
    return;
  }
  if (event.event === 'local-chat') {
    if (app.currentChat &&
        app.currentChat.attachmentRevision !== app.attachmentRevision) {
      ChatState.dispatch(app.conversation, {
        type: 'analysis_complete', kind: 'error',
        content: 'The attached footage changed during analysis. Send the edit request again for the current files.',
      });
      app.currentChat = null;
      renderChat();
      drainChatQueue();
      return;
    }
    const operations = event.proposal?.operations;
    const applicable = event.canApply === true && Array.isArray(operations) && operations.length;
    app.proposal = applicable ? event.proposal : null;
    app.proposalBrief = applicable && typeof event.message === 'string'
      ? event.message.slice(0, 8000) : '';
    if (typeof event.transcript === 'string' && event.transcript.trim()) {
      app.transcript = event.transcript.slice(0, 30000);
    }
    app.proposalTargetResultPath = app.currentChat
      ? app.currentChat.targetResultPath : (app.resultPath || '');
    ChatState.dispatch(app.conversation, {
      type: 'analysis_complete', content: event.message || 'Analysis complete.',
      sources: event.sources, proposal: app.proposal, canApply: !!app.proposal,
      targetResultPath: app.proposalTargetResultPath,
    });
    app.currentChat = null;
    $('chat-status').textContent = '';
    renderChat();
    drainChatQueue();
    return;
  }
  if (event.event === 'local-result') {
    const outputs = event.outputs && typeof event.outputs === 'object' ? event.outputs : {};
    const output = event.output || Object.values(outputs)[0] || '';
    app.transcript = typeof event.transcript === 'string' ? event.transcript : app.transcript;
    app.resultPath = output;
    ChatState.dispatch(app.conversation, event.qaPass === false ? {
      type: 'render_warning', videoPath: output, outputs,
      warning: event.warning || 'The built-in quality checks rejected this draft.',
      content: 'A playable draft was created, but it needs review. Tell me what you want changed.',
    } : {
      type: 'render_complete', videoPath: output, outputs,
      content: 'Your edited video is ready. Tell me what you want changed.',
    });
    renderChat();
    return;
  }
  if (event.event === 'local-progress' && event.stage === 'canceled') {
    ChatState.dispatch(app.conversation, { type: 'render_cancelled' });
    renderChat();
    return;
  }
  if (event.event === 'local-progress') {
    const message = event.message || event.userStage || event.stage || 'Working...';
    const log = event.log || event.line || '';
    if (kind === 'chat') {
      ChatState.dispatch(app.conversation, {
        type: 'analysis_progress', stage: message, log, engineActivity: true,
      });
    } else {
      const exact = event.measurable === true &&
        Number.isFinite(Number(event.progress ?? event.percent));
      ChatState.dispatch(app.conversation, {
        type: 'render_progress', stage: message, log, engineActivity: true,
        measurable: exact, progress: exact ? Number(event.progress ?? event.percent) : undefined,
      });
    }
    renderChat();
  }
}

function handleRawLog(value) {
  const line = typeof value === 'string' ? value : value?.line || value?.message || '';
  if (!line) return;
  const kind = typeof value === 'object' && value?.kind
    ? value.kind : (app.conversation.activeRender ? 'render' : 'chat');
  if (kind === 'render' && app.conversation.activeRender) {
    ChatState.dispatch(app.conversation, {
      type: 'render_progress', log: line, engineActivity: true,
    });
  } else if (app.conversation.activeAnalysis) {
    ChatState.dispatch(app.conversation, {
      type: 'analysis_progress', log: line, engineActivity: true,
    });
  }
  renderChat();
}

function renderState(state = {}) {
  const videos = normalizePaths(state.videos || state.videoPaths || state.selectedVideos || []);
  if (videos.length && !app.videos.length) {
    app.videos = videos;
    app.attachmentsDirty = true;
  }
  const outputDir = normalizePath(state.outputDir || state.outputFolder || '');
  if (outputDir) {
    app.outputDir = outputDir;
    $('output-folder').value = outputDir;
  }
  app.platform = state.platform || app.platform;
  app.conversation.platform = app.platform;
  if (state.projectType) $('project-type').value = state.projectType;
  if (typeof state.script === 'string' && !$('script').value) $('script').value = state.script;
  renderProviderStates(state);
  if (state.activeRender && !app.conversation.activeRender) {
    ChatState.dispatch(app.conversation, {
      type: 'render_started', id: state.activeRender.id,
      stage: state.activeRender.message || state.activeRender.stage,
      startedAt: state.activeRender.startedAt,
      lastActivityAt: state.activeRender.lastActivityAt,
    });
  } else if (!state.activeRender && app.conversation.activeRender) {
    ChatState.dispatch(app.conversation, {
      type: 'render_error', stage: app.conversation.activeRender.stage,
      error: 'AutoEditor closed before this render finished. Retry to start it again.',
    });
  }
  if (!state.chatting && app.conversation.activeAnalysis) {
    ChatState.dispatch(app.conversation, {
      type: 'analysis_complete', kind: 'error',
      content: 'AutoEditor closed before this analysis finished. Send the message again to retry.',
    });
  }
  renderVideos();
  renderChat();
}

async function addPickedVideos(promise) {
  $('render-error').textContent = '';
  try {
    const picked = normalizePaths(await promise);
    const before = app.videos.length;
    app.videos = [...new Set([...app.videos, ...picked])];
    if (app.videos.length !== before) {
      invalidateAttachmentAnalysis();
      app.attachmentsDirty = true;
    }
    renderVideos();
  } catch (error) {
    $('render-error').textContent = asError(error);
  }
}

$('select-videos').addEventListener('click', () => addPickedVideos(window.helper.pickVideos()));
$('drop-zone').addEventListener('keydown', (event) => {
  if ((event.key === 'Enter' || event.key === ' ') && event.target === $('drop-zone')) {
    event.preventDefault();
    $('select-videos').click();
  }
});
for (const name of ['dragenter', 'dragover']) {
  $('drop-zone').addEventListener(name, (event) => {
    event.preventDefault(); event.stopPropagation();
    $('drop-zone').classList.add('dragging');
  });
}
for (const name of ['dragleave', 'drop']) {
  $('drop-zone').addEventListener(name, (event) => {
    event.preventDefault(); event.stopPropagation();
    $('drop-zone').classList.remove('dragging');
  });
}
$('drop-zone').addEventListener('drop', (event) => {
  if (event.dataTransfer?.files?.length) {
    addPickedVideos(window.helper.attachDroppedVideos(event.dataTransfer.files));
  }
});
window.addEventListener('dragover', (event) => event.preventDefault());
window.addEventListener('drop', (event) => event.preventDefault());

$('clear-videos').addEventListener('click', () => {
  app.videos = [];
  invalidateAttachmentAnalysis();
  app.attachmentsDirty = true;
  renderVideos();
});

$('select-output').addEventListener('click', async () => {
  try {
    const picked = normalizePath(await window.helper.pickOutput());
    if (picked) {
      app.outputDir = picked;
      $('output-folder').value = picked;
    }
  } catch (error) { $('render-error').textContent = asError(error); }
});

$('ask-deepseek').addEventListener('click', submitMessage);
$('chat-prompt').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    submitMessage();
  }
});

$('save-settings').addEventListener('click', async () => {
  const fields = {
    deepseekApiKey: $('deepseek-key'), pexelsApiKey: $('pexels-key'),
    pixabayApiKey: $('pixabay-key'), elevenLabsApiKey: $('eleven-key'),
    remotionKey: $('remotion-key'),
  };
  const settings = {};
  Object.entries(fields).forEach(([name, input]) => {
    const value = input.value.trim();
    if (value) settings[name] = value;
  });
  $('settings-error').textContent = '';
  if (!Object.keys(settings).length) {
    $('settings-error').textContent = 'Paste at least one new key to save. Blank fields keep their saved keys.';
    return;
  }
  $('save-settings').disabled = true;
  $('settings-status').textContent = 'Encrypting and saving on this computer...';
  try {
    const state = await window.helper.saveSettings(settings);
    Object.values(fields).forEach((input) => { input.value = ''; });
    renderProviderStates(state || Object.fromEntries(Object.keys(settings).map((key) => [key, true])));
    $('settings-status').textContent = 'Saved and reused automatically.';
  } catch (error) {
    $('settings-error').textContent = asError(error);
    $('settings-status').textContent = '';
  } finally { $('save-settings').disabled = false; }
});

document.querySelectorAll('[data-open]').forEach((button) => {
  button.addEventListener('click', () => window.helper.open(button.dataset.open));
});
$('notices').addEventListener('click', () => window.helper.notices());
window.helper.onState(renderState);
window.helper.onLog(handleRawLog);
window.helper.onRender(handleRenderEvent);

setInterval(() => {
  if (!app.conversation.activeRender) return;
  ChatState.dispatch(app.conversation, { type: 'render_heartbeat' });
  refreshActiveRenderClock();
}, 1000);

async function boot() {
  const state = await window.helper.state() || {};
  if (state.conversation) {
    app.conversation = ChatState.restoreConversation(state.conversation, {
      platform: state.platform,
    });
    app.resultPath = app.conversation.latestResultPath || '';
    lastSavedConversation = JSON.stringify(
      ChatState.conversationSnapshot(app.conversation));
  }
  renderVideos();
  renderChat();
  renderState(state);
}

boot().catch((error) => {
  setStatus('Needs attention', 'bad');
  assistantMessage(asError(error), 'error');
});
