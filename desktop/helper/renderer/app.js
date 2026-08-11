const $ = (id) => document.getElementById(id);

const app = {
  videos: [],
  outputDir: '',
  resultPath: '',
  transcript: '',
  rendering: false,
  chatting: false,
  chat: [],
  proposal: null,
};

let visionWorker = null;
let activeVisionId = null;

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
    window.helper.visionResult({
      id, status: 'error', error: 'the local vision model is already working',
    });
    return;
  }
  activeVisionId = id;
  try {
    localVisionWorker().postMessage({ id, images });
  } catch (error) {
    activeVisionId = null;
    window.helper.visionResult({
      id, status: 'error', error: asError(error).slice(0, 1000),
    });
  }
});

function asError(error) {
  const text = error?.message || String(error || 'Something went wrong.');
  return text.replace(/^Error invoking remote method '[^']+':\s*(Error:\s*)?/, '');
}

const CHAT_HISTORY_MAX_ENTRIES = 12;
const CHAT_HISTORY_MAX_ENTRY_CHARS = 2000;
const CHAT_HISTORY_MAX_TOTAL_CHARS = 12000;

function boundedChatHistory(messages) {
  const entries = messages
    .filter((message) => message.content)
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

function providerSaved(state, name) {
  const providers = state?.providers || state?.settings || state?.configuredProviders || {};
  return Boolean(
    providers[name]
    || providers[`${name}Configured`]
    || providers[`${name}Saved`]
    || providers[`${name}ApiKey`]
    || (name === 'remotion' && (providers.remotionKey || providers.remotionLicenseKey))
    || state?.[`${name}Configured`]
    || state?.[`${name}ApiKey`]
    || (name === 'remotion' && (state?.remotionKey || state?.remotionLicenseKey))
  );
}

function setStatus(label, tone = '') {
  $('status').textContent = label;
  $('status').className = `pill ${tone}`.trim();
}

function renderVideos() {
  const hasVideos = app.videos.length > 0;
  $('video-list-wrap').classList.toggle('hidden', !hasVideos);
  $('video-empty').textContent = hasVideos
    ? `${app.videos.length} ${app.videos.length === 1 ? 'video attached' : 'videos attached'}`
    : 'Drag footage here, or choose files from this computer.';
  $('video-count').textContent = `${app.videos.length} ${app.videos.length === 1 ? 'video attached' : 'videos attached'}`;
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
    remove.setAttribute('aria-label', `Remove ${fileName(path)}`);
    remove.addEventListener('click', () => {
      app.videos.splice(index, 1);
      renderVideos();
    });
    item.append(copy, remove);
    $('video-list').appendChild(item);
  });
  renderChat();
}

function renderProviderStates(state) {
  const inputIds = {
    deepseek: 'deepseek-key', pexels: 'pexels-key', pixabay: 'pixabay-key',
    eleven: 'eleven-key', remotion: 'remotion-key',
  };
  ['deepseek', 'pexels', 'pixabay', 'eleven', 'remotion'].forEach((name) => {
    const saved = providerSaved(state, name)
      || (name === 'eleven' && providerSaved(state, 'elevenLabs'));
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

function renderState(state = {}) {
  const videos = normalizePaths(state.videos || state.videoPaths || state.selectedVideos || []);
  if (videos.length) app.videos = videos;
  const outputDir = normalizePath(state.outputDir || state.outputFolder || '');
  if (outputDir) {
    app.outputDir = outputDir;
    $('output-folder').value = outputDir;
  }
  if (state.projectType) $('project-type').value = state.projectType;
  if (typeof state.script === 'string' && !$('script').value) $('script').value = state.script;
  renderProviderStates(state);
  renderVideos();
  const resultPath = normalizePath(state.resultPath || state.latestResult || '');
  if (resultPath) showResult(resultPath);
  if (state.error) {
    setStatus('Needs attention', 'bad');
    $('render-error').textContent = state.error;
  } else if (!app.rendering && !app.chatting) {
    setStatus('Ready');
  }
}

function setRendering(value, message = '') {
  app.rendering = value;
  $('select-videos').disabled = value;
  $('select-output').disabled = value;
  $('apply-changes').disabled = value;
  $('cancel').classList.toggle('hidden', !value);
  if (value) $('progress-section').classList.remove('hidden');
  if (message) $('progress-message').textContent = message;
  setStatus(value ? 'Rendering' : (app.chatting ? 'Thinking' : 'Ready'),
    value ? 'on' : '');
}

function setProgress(value, message) {
  let progress = Number(value);
  if (!Number.isFinite(progress)) progress = 0;
  if (progress > 0 && progress <= 1) progress *= 100;
  progress = Math.max(0, Math.min(100, Math.round(progress)));
  $('progress').value = progress;
  $('progress').textContent = `${progress}%`;
  $('progress-value').textContent = `${progress}%`;
  if (message) $('progress-message').textContent = message;
}

function appendLog(line) {
  const text = typeof line === 'string' ? line : line?.message || line?.line || '';
  if (!text) return;
  $('progress-section').classList.remove('hidden');
  const current = $('log').textContent === 'Ready. Every edit stage will appear here.'
    ? '' : $('log').textContent;
  const suffix = text.endsWith('\n') ? '' : '\n';
  $('log').textContent = (current + text + suffix).slice(-24000);
  $('log').scrollTop = $('log').scrollHeight;
}

function mediaMessage(path, allowReveal) {
  const wrap = document.createElement('div');
  const video = document.createElement('video');
  const footer = document.createElement('div');
  const name = document.createElement('strong');
  wrap.className = 'chat-media';
  video.controls = true;
  video.preload = 'metadata';
  video.src = localFileUrl(path);
  footer.className = 'chat-media-footer';
  name.textContent = fileName(path);
  footer.appendChild(name);
  if (allowReveal) {
    const reveal = document.createElement('button');
    reveal.type = 'button';
    reveal.textContent = 'Show in Finder';
    reveal.addEventListener('click', () => window.helper.openResult(path));
    footer.appendChild(reveal);
  }
  wrap.append(video, footer);
  return wrap;
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
    const date = source.date ? `, ${source.date}` : '';
    button.textContent = `[${index + 1}] ${source.title || source.source || 'Research source'}${date}`;
    button.addEventListener('click', async () => {
      try { await window.helper.openResearchSource(source.url); }
      catch (error) { $('chat-error').textContent = asError(error); }
    });
    item.appendChild(button);
    list.appendChild(item);
  });
  return list.childElementCount ? list : null;
}

function renderChat() {
  $('chat-transcript').replaceChildren();
  if (!app.videos.length && !app.chat.length) {
    const empty = document.createElement('p');
    empty.id = 'chat-empty';
    empty.className = 'chat-empty';
    empty.textContent = 'Ask DeepSeek about a video idea, or attach footage and describe the edit you want.';
    $('chat-transcript').appendChild(empty);
    return;
  }

  app.videos.forEach((path) => {
    const row = document.createElement('div');
    const role = document.createElement('span');
    row.className = 'chat-message user';
    role.textContent = 'Attached from this computer';
    row.append(role, mediaMessage(path, false));
    $('chat-transcript').appendChild(row);
  });

  app.chat.forEach((message) => {
    const row = document.createElement('div');
    const role = document.createElement('span');
    row.className = `chat-message ${message.role === 'user' ? 'user' : 'assistant'}`;
    role.textContent = message.role === 'user' ? 'You' : 'DeepSeek';
    row.appendChild(role);
    if (message.content) {
      const content = document.createElement('p');
      content.textContent = message.content;
      row.appendChild(content);
    }
    if (message.videoPath) row.appendChild(mediaMessage(message.videoPath, true));
    const sources = sourceList(message.sources);
    if (sources) row.appendChild(sources);
    $('chat-transcript').appendChild(row);
  });
  $('chat-transcript').scrollTop = $('chat-transcript').scrollHeight;
}

function showProposal(proposal) {
  app.proposal = proposal;
  const summary = typeof proposal?.summary === 'string' && proposal.summary.trim()
    ? proposal.summary.trim() : 'DeepSeek mapped your request to the local editor.';
  $('proposal-text').textContent = summary;
  $('proposal').classList.toggle('hidden', !proposal);
}

function showResult(path) {
  if (!path) return;
  app.resultPath = path;
  if (!app.chat.some((message) => message.videoPath === path)) {
    app.chat.push({
      role: 'assistant',
      content: 'Your edited video is ready. Reply directly below it with anything you want changed.',
      videoPath: path,
    });
  }
  renderChat();
  $('ask-deepseek').disabled = false;
  $('chat-status').textContent = '';
  setProgress(100, 'Finished, checked, and saved on this computer.');
  setRendering(false);
  setStatus('Complete', 'complete');
}

function handleRenderEvent(event = {}) {
  if (typeof event === 'string') {
    appendLog(event);
    return;
  }
  if (event.event === 'local-error') {
    const message = event.error || 'The action could not finish.';
    appendLog(`ERROR: ${message}`);
    app.chatting = false;
    if (app.rendering) setRendering(false, 'Render stopped.');
    $('chat-error').textContent = message;
    $('render-error').textContent = message;
    $('ask-deepseek').disabled = false;
    $('chat-status').textContent = '';
    setStatus('Needs attention', 'bad');
    return;
  }
  if (event.event === 'local-chat') {
    app.chatting = false;
    if (typeof event.message === 'string' && event.message.trim()) {
      app.chat.push({
        role: 'assistant', content: event.message.trim(),
        sources: Array.isArray(event.sources) ? event.sources : [],
      });
    }
    const operations = event.proposal?.operations;
    const applicable = event.canApply === true
      && Array.isArray(operations) && operations.length > 0;
    showProposal(applicable ? event.proposal : null);
    renderChat();
    $('ask-deepseek').disabled = false;
    $('chat-status').textContent = '';
    setStatus('Ready');
    return;
  }
  if (event.event === 'local-result') {
    app.transcript = typeof event.transcript === 'string' ? event.transcript : '';
    showResult(event.output || '');
    return;
  }
  if (event.event === 'local-progress') {
    appendLog(event.log || event.line || event.message || event.stage || 'Working...');
    if (!app.rendering && event.message) $('chat-status').textContent = event.message;
  }
  if (event.event === 'local-progress' && event.stage === 'canceled') {
    setRendering(false, 'Render canceled.');
    setStatus('Canceled');
    return;
  }
  if (event.progress !== undefined || event.percent !== undefined) {
    setProgress(event.progress ?? event.percent, event.message);
  }
  const status = String(event.status || event.phase || '').toLowerCase();
  const path = normalizePath(event.resultPath || event.outputPath || event.path || '');
  if (path && ['complete', 'completed', 'done', 'success', 'finished'].includes(status)) {
    showResult(path);
  } else if (path && !status) {
    showResult(path);
  }
}

function renderRequest() {
  return {
    videos: [...app.videos], outputDir: app.outputDir,
    projectType: $('project-type').value, script: $('script').value.trim(),
  };
}

async function addPickedVideos(promise) {
  $('render-error').textContent = '';
  try {
    const picked = normalizePaths(await promise);
    app.videos = [...new Set([...app.videos, ...picked])];
    renderVideos();
  } catch (error) {
    $('render-error').textContent = asError(error);
  }
}

$('select-videos').addEventListener('click', () =>
  addPickedVideos(window.helper.pickVideos()));
$('drop-zone').addEventListener('keydown', (event) => {
  if ((event.key === 'Enter' || event.key === ' ') && event.target === $('drop-zone')) {
    event.preventDefault();
    $('select-videos').click();
  }
});
for (const name of ['dragenter', 'dragover']) {
  $('drop-zone').addEventListener(name, (event) => {
    event.preventDefault();
    event.stopPropagation();
    $('drop-zone').classList.add('dragging');
  });
}
for (const name of ['dragleave', 'drop']) {
  $('drop-zone').addEventListener(name, (event) => {
    event.preventDefault();
    event.stopPropagation();
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
  renderVideos();
});

$('select-output').addEventListener('click', async () => {
  $('render-error').textContent = '';
  try {
    const picked = normalizePath(await window.helper.pickOutput());
    if (picked) {
      app.outputDir = picked;
      $('output-folder').value = picked;
    }
  } catch (error) {
    $('render-error').textContent = asError(error);
  }
});

$('ask-deepseek').addEventListener('click', async () => {
  const text = $('chat-prompt').value.trim();
  if (!text || app.chatting) return;
  $('chat-error').textContent = '';
  $('ask-deepseek').disabled = true;
  $('chat-status').textContent = 'DeepSeek is reading the editing context...';
  app.chatting = true;
  app.chat.push({ role: 'user', content: text });
  $('chat-prompt').value = '';
  renderChat();
  appendLog(`Chat: ${app.videos.length} attached video(s); preparing DeepSeek V4 context.`);
  setStatus('Thinking', 'on');
  try {
    await window.helper.chatLocal({
      text,
      history: boundedChatHistory(app.chat.slice(0, -1)),
      projectType: $('project-type').value,
      transcript: (app.transcript || $('script').value.trim()).slice(0, 20000),
      videoCount: app.videos.length,
      ...(app.videos.length ? { videoPaths: [...app.videos] } : {}),
      resultPath: app.resultPath || undefined,
      research: $('live-research').checked,
    });
  } catch (error) {
    app.chatting = false;
    appendLog(`ERROR: ${asError(error)}`);
    $('chat-error').textContent = asError(error);
    $('ask-deepseek').disabled = false;
    $('chat-status').textContent = '';
    setStatus('Needs attention', 'bad');
  }
});

$('chat-prompt').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('ask-deepseek').click();
  }
});

$('apply-changes').addEventListener('click', async () => {
  $('chat-error').textContent = '';
  $('render-error').textContent = '';
  if (!app.proposal) return;
  if (!app.videos.length) {
    $('render-error').textContent = 'Attach at least one video before rendering.';
    $('drop-zone').focus();
    return;
  }
  if (!app.outputDir) {
    $('render-error').textContent = 'Choose where to save the finished video before rendering.';
    document.querySelector('.edit-options').open = true;
    $('select-output').focus();
    return;
  }
  $('apply-changes').disabled = true;
  $('log').textContent = 'Starting local render...\n';
  setProgress(1, 'Starting the local edit...');
  setRendering(true);
  try {
    const request = renderRequest();
    await window.helper.applyLocal({
      ...request, proposal: app.proposal, resultPath: app.resultPath || undefined,
    });
    showProposal(null);
  } catch (error) {
    appendLog(`ERROR: ${asError(error)}`);
    setRendering(false, 'Render stopped.');
    $('render-error').textContent = asError(error);
  } finally {
    if (!app.rendering) $('apply-changes').disabled = false;
  }
});

$('cancel').addEventListener('click', async () => {
  $('cancel').disabled = true;
  try {
    await window.helper.cancelLocal();
    setRendering(false, 'Render canceled.');
    setStatus('Canceled');
  } catch (error) {
    $('render-error').textContent = asError(error);
  } finally {
    $('cancel').disabled = false;
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
    renderProviderStates(state || Object.fromEntries(
      Object.keys(settings).map((key) => [key, true])));
    $('settings-status').textContent = 'Saved and reused automatically.';
  } catch (error) {
    $('settings-error').textContent = asError(error);
    $('settings-status').textContent = '';
  } finally {
    $('save-settings').disabled = false;
  }
});

document.querySelectorAll('[data-open]').forEach((button) => {
  button.addEventListener('click', () => window.helper.open(button.dataset.open));
});
$('notices').addEventListener('click', () => window.helper.notices());
window.helper.onState(renderState);
window.helper.onLog(appendLog);
window.helper.onRender(handleRenderEvent);

async function boot() {
  renderVideos();
  renderChat();
  const state = await window.helper.state();
  renderState(state || {});
}

boot().catch((error) => {
  setStatus('Needs attention', 'bad');
  $('render-error').textContent = asError(error);
});
