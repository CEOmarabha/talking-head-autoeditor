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

function asError(error) {
  return error?.message || String(error || 'Something went wrong.');
}

function fileName(path) {
  return String(path || '').split(/[\\/]/).filter(Boolean).pop() || String(path || 'Video');
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
  $('video-empty').classList.toggle('hidden', hasVideos);
  $('video-list-wrap').classList.toggle('hidden', !hasVideos);
  $('video-count').textContent = `${app.videos.length} ${app.videos.length === 1 ? 'video' : 'videos'} selected`;
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
}

function renderProviderStates(state) {
  ['deepseek', 'pexels', 'pixabay', 'eleven', 'remotion'].forEach((name) => {
    const saved = providerSaved(state, name)
      || (name === 'eleven' && providerSaved(state, 'elevenLabs'));
    const target = $(`${name}-saved`);
    target.textContent = saved ? 'Saved on this computer' : '';
    target.classList.toggle('visible', saved);
  });
}

function renderState(state = {}) {
  const videos = normalizePaths(state.videos || state.videoPaths || state.selectedVideos || []);
  if (videos.length) {
    app.videos = videos;
    renderVideos();
  }

  const outputDir = normalizePath(state.outputDir || state.outputFolder || '');
  if (outputDir) {
    app.outputDir = outputDir;
    $('output-folder').value = outputDir;
  }

  if (state.projectType && $(`project-type`)) $('project-type').value = state.projectType;
  if (typeof state.script === 'string' && !$('script').value) $('script').value = state.script;
  renderProviderStates(state);

  const resultPath = normalizePath(state.resultPath || state.latestResult || '');
  if (resultPath) showResult(resultPath);

  if (state.error) {
    setStatus('Needs attention', 'bad');
    $('render-error').textContent = state.error;
  } else if (!app.rendering) {
    setStatus('Ready');
  }
}

function setRendering(value, message = '') {
  app.rendering = value;
  $('render').disabled = value;
  $('select-videos').disabled = value;
  $('select-output').disabled = value;
  $('cancel').classList.toggle('hidden', !value);
  $('progress-section').classList.toggle('hidden', !value && !$('log').textContent.trim());
  if (message) $('progress-message').textContent = message;
  setStatus(value ? 'Rendering' : 'Ready', value ? 'on' : '');
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
  const suffix = text.endsWith('\n') ? '' : '\n';
  $('log').textContent = ($('log').textContent + text + suffix).slice(-16000);
  $('log').scrollTop = $('log').scrollHeight;
}

function showResult(path) {
  if (!path) return;
  app.resultPath = path;
  $('result-path').textContent = path;
  $('result-path').title = path;
  $('result-section').classList.remove('hidden');
  $('chat-section').classList.remove('hidden');
  setProgress(100, 'Finished and saved on this computer.');
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
    if (app.chatting) {
      app.chatting = false;
      $('chat-error').textContent = message;
      $('ask-deepseek').disabled = false;
      $('chat-status').textContent = '';
    } else {
      setRendering(false, 'Render stopped.');
      setStatus('Needs attention', 'bad');
      $('render-error').textContent = message;
    }
    return;
  }
  if (event.event === 'local-chat') {
    app.chatting = false;
    if (typeof event.message === 'string' && event.message.trim()) {
      app.chat.push({ role: 'assistant', content: event.message.trim() });
      renderChat();
    }
    const operations = event.proposal?.operations;
    showProposal(event.canApply === true && Array.isArray(operations) && operations.length
      ? event.proposal
      : null);
    $('ask-deepseek').disabled = false;
    $('chat-status').textContent = '';
    return;
  }
  if (event.event === 'local-result') {
    app.transcript = typeof event.transcript === 'string' ? event.transcript : '';
    showResult(event.output || '');
    return;
  }
  if (event.event === 'local-progress' && event.stage === 'canceled') {
    setRendering(false, 'Render canceled.');
    setStatus('Canceled');
    return;
  }

  appendLog(event.log || event.message || event.line || event.stage || '');
  if (event.progress !== undefined || event.percent !== undefined) {
    setProgress(event.progress ?? event.percent, event.message);
  }

  const status = String(event.status || event.phase || '').toLowerCase();
  const path = normalizePath(event.resultPath || event.outputPath || event.path || '');
  if (path && ['complete', 'completed', 'done', 'success', 'finished'].includes(status)) {
    showResult(path);
    return;
  }
  if (path && !status) showResult(path);

  if (['rendering', 'running', 'working', 'started', 'queued'].includes(status)) {
    setRendering(true, event.message || 'Rendering your video on this computer...');
  } else if (['cancelled', 'canceled'].includes(status)) {
    setRendering(false, 'Render canceled.');
    setStatus('Canceled');
  } else if (['error', 'failed', 'failure'].includes(status)) {
    setRendering(false, 'Render stopped.');
    setStatus('Needs attention', 'bad');
    $('render-error').textContent = event.error || event.message || 'The render could not finish. Try again.';
  }
}

function renderChat() {
  $('chat-transcript').replaceChildren();
  if (!app.chat.length) {
    const empty = document.createElement('p');
    empty.id = 'chat-empty';
    empty.className = 'chat-empty';
    empty.textContent = 'Ask DeepSeek what you want to improve in this edit.';
    $('chat-transcript').appendChild(empty);
    return;
  }

  app.chat.forEach((message) => {
    const row = document.createElement('div');
    const role = document.createElement('span');
    const content = document.createElement('p');
    row.className = `chat-message ${message.role === 'user' ? 'user' : 'assistant'}`;
    role.textContent = message.role === 'user' ? 'You' : 'DeepSeek';
    content.textContent = message.content;
    row.append(role, content);
    $('chat-transcript').appendChild(row);
  });
  $('chat-transcript').scrollTop = $('chat-transcript').scrollHeight;
}

function formatProposal(value) {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); }
  catch { return String(value); }
}

function showProposal(proposal) {
  app.proposal = proposal;
  $('proposal-text').textContent = formatProposal(proposal);
  $('proposal').classList.toggle('hidden', !proposal);
}

function renderRequest() {
  return {
    videos: [...app.videos],
    outputDir: app.outputDir,
    projectType: $('project-type').value,
    script: $('script').value.trim(),
  };
}

$('select-videos').addEventListener('click', async () => {
  $('render-error').textContent = '';
  try {
    const picked = normalizePaths(await window.helper.pickVideos());
    app.videos = [...new Set([...app.videos, ...picked])];
    renderVideos();
  } catch (error) {
    $('render-error').textContent = asError(error);
  }
});

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

$('render').addEventListener('click', async () => {
  $('render-error').textContent = '';
  if (!app.videos.length) {
    $('render-error').textContent = 'Select at least one video.';
    return;
  }
  if (!app.outputDir) {
    $('render-error').textContent = 'Choose an output folder.';
    return;
  }

  app.proposal = null;
  $('proposal').classList.add('hidden');
  $('result-section').classList.add('hidden');
  $('progress-section').classList.remove('hidden');
  $('log').textContent = '';
  setProgress(0, 'Preparing your edit on this computer...');
  setRendering(true);

  try {
    const result = await window.helper.renderLocal(renderRequest());
    handleRenderEvent(result || { status: 'started' });
  } catch (error) {
    handleRenderEvent({ status: 'error', error: asError(error) });
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

function openCurrentResult() {
  if (app.resultPath) window.helper.openResult(app.resultPath);
}

$('open-result').addEventListener('click', openCurrentResult);
$('result-path').addEventListener('click', openCurrentResult);

$('ask-deepseek').addEventListener('click', async () => {
  const text = $('chat-prompt').value.trim();
  if (!text) return;

  $('chat-error').textContent = '';
  $('ask-deepseek').disabled = true;
  $('chat-status').textContent = 'DeepSeek is reviewing your edit...';
  app.chatting = true;
  app.chat.push({ role: 'user', content: text });
  $('chat-prompt').value = '';
  renderChat();

  try {
    await window.helper.chatLocal({
      text,
      history: app.chat.slice(0, -1).slice(-12),
      projectType: $('project-type').value,
      transcript: app.transcript || $('script').value.trim(),
    });
  } catch (error) {
    app.chatting = false;
    $('chat-error').textContent = asError(error);
    $('ask-deepseek').disabled = false;
    $('chat-status').textContent = '';
  }
});

$('chat-prompt').addEventListener('keydown', (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') $('ask-deepseek').click();
});

$('apply-changes').addEventListener('click', async () => {
  if (!app.proposal) return;
  $('chat-error').textContent = '';
  $('apply-changes').disabled = true;
  $('progress-section').classList.remove('hidden');
  setProgress(0, 'Applying approved changes on this computer...');
  setRendering(true);
  try {
    const request = renderRequest();
    const result = await window.helper.applyLocal({
      proposal: app.proposal,
      videos: request.videos,
      outputDir: request.outputDir,
      projectType: request.projectType,
      script: request.script,
      resultPath: app.resultPath,
    });
    $('proposal').classList.add('hidden');
    app.proposal = null;
    handleRenderEvent(result || { status: 'started' });
  } catch (error) {
    setRendering(false);
    $('chat-error').textContent = asError(error);
  } finally {
    $('apply-changes').disabled = false;
  }
});

$('save-settings').addEventListener('click', async () => {
  const fields = {
    deepseekApiKey: $('deepseek-key'),
    pexelsApiKey: $('pexels-key'),
    pixabayApiKey: $('pixabay-key'),
    elevenLabsApiKey: $('eleven-key'),
    remotionKey: $('remotion-key'),
  };
  const settings = {};
  Object.entries(fields).forEach(([name, input]) => {
    const value = input.value.trim();
    if (value) settings[name] = value;
  });

  $('settings-error').textContent = '';
  if (!Object.keys(settings).length) {
    $('settings-error').textContent = 'Paste at least one key to save.';
    return;
  }

  $('save-settings').disabled = true;
  $('settings-status').textContent = 'Encrypting and saving on this computer...';
  try {
    const state = await window.helper.saveSettings(settings);
    Object.values(fields).forEach((input) => { input.value = ''; });
    renderProviderStates(state || Object.fromEntries(Object.keys(settings).map((key) => [key, true])));
    $('settings-status').textContent = 'Saved on this computer.';
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
