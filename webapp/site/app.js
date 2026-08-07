/* AutoEditor web client. Plain JS, no build step.
 * Windows Chrome/Edge first; resumable multipart uploads; poll-based
 * progress so a refresh never loses a project. */
const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const r = await fetch('/api' + path, {
    headers: { 'content-type': 'application/json' },
    credentials: 'same-origin', ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || r.status),
    { status: r.status });
  return data;
};

const TYPES = [
  ['short', 'Short / Reel', 'Vertical, fast, big captions'],
  ['long', 'Long Talking Head', 'YouTube-style lesson or talk'],
  ['commercial', 'Commercial / Ad', 'Tight, punchy, music-driven'],
  ['podcast', 'Podcast / Interview', 'Long-form conversation'],
  ['course', 'Course / Lesson', 'Structured teaching video'],
  ['clips', 'Turn Long Video Into Clips', 'Find the best moments'],
  ['custom', 'Custom', 'Tell the editor what you want'],
];
const state = { me: null, projectId: null, pollTimer: null };

// ------------------------------------------------------------ views
function show(id) {
  ['signin', 'keysetup', 'dash', 'proj'].forEach((v) =>
    $(v).classList.toggle('hidden', v !== id));
}

async function boot() {
  try {
    state.me = await api('/me');
    $('who').textContent = state.me.name;
    $('signout').classList.remove('hidden');
    // Hard gate: the ONLY thing you can do without a valid key is enter
    // one. The help chat (which needs the key) turns on the moment it's in.
    if (!state.me.hasKey) {
      $('help-fab').classList.add('hidden');
      return show('keysetup');
    }
    $('help-fab').classList.remove('hidden');
    await dash();
  } catch (_) { show('signin'); }
}

async function dash() {
  show('dash');
  loadHelperDownloads();
  // self-serve: connect code + OTP state
  api('/me/connect-code').then((r) => {
    $('cc-value').value = r.setup_code || r.connect_code;
  }).catch(() => {});
  $('otp-on').classList.toggle('hidden', !state.me.hasOtp);
  $('otp-off').classList.toggle('hidden', !!state.me.hasOtp);
  const t = $('types'); t.innerHTML = '';
  TYPES.forEach(([id, name, desc]) => {
    const d = document.createElement('div');
    d.className = 'type';
    d.tabIndex = 0;
    d.setAttribute('role', 'button');
    d.setAttribute('aria-label', `Start ${name}`);
    const title = document.createElement('b');
    title.textContent = name;
    const detail = document.createElement('span');
    detail.className = 'muted';
    detail.textContent = desc;
    d.append(title, detail);
    const startProject = async () => {
      const proj = await api('/projects', { method: 'POST',
        body: { type: id, title: name } });
      openProject(proj.id);
    };
    d.onclick = startProject;
    d.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        startProject();
      }
    };
    t.appendChild(d);
  });
  const list = await api('/projects');
  const ul = $('projects'); ul.replaceChildren();
  if (!list.length) {
    const empty = document.createElement('li');
    empty.className = 'muted';
    empty.textContent = 'Nothing yet. Pick a type above to start.';
    ul.appendChild(empty);
  }
  list.forEach((pr) => {
    const li = document.createElement('li');
    const link = document.createElement('a');
    link.href = '#'; link.textContent = pr.title;
    const badge = document.createElement('span');
    badge.className = 'badge'; badge.textContent = pr.status;
    li.append(link, document.createTextNode(' '), badge);
    link.onclick = (e) => {
      e.preventDefault(); openProject(pr.id);
    };
    ul.appendChild(li);
  });
}

async function loadHelperDownloads() {
  try {
    const response = await fetch('/download/helper/availability', {
      credentials: 'same-origin', cache: 'no-store',
    });
    const available = response.ok ? await response.json() : {};
    const mapping = [
      ['dl-win', '/download/helper/windows'],
      ['dl-mac-arm', '/download/helper/mac-arm64'],
      ['dl-mac-x64', '/download/helper/mac-x64'],
    ];
    let count = 0;
    for (const [id, route] of mapping) {
      const showLink = !!available[route];
      $(id).classList.toggle('hidden', !showLink);
      if (showLink) count += 1;
    }
    $('dl-wait').textContent = count
      ? '' : 'The signed installers are being prepared. Ask Omar for the release link.';
  } catch (_) {
    $('dl-wait').textContent = 'Could not check installers. Refresh this page or ask Omar.';
  }
}

// ------------------------------------------------------------ project
async function openProject(id) {
  state.projectId = id;
  show('proj');
  await renderProject();
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(renderProject, 3000);
}

const HUMAN_STATUS = {
  'empty': 'Waiting for footage', 'uploading': 'Uploading',
  'uploaded': 'Ready to make', 'queued': 'Waiting in queue',
  'transcribing': 'Transcribing', 'planning': 'Planning your edit',
  'transcript needs attention': 'Check the transcript',
  'gathering resources': 'Gathering footage and assets',
  'rendering preview': 'Rendering preview',
  'awaiting approval': 'Waiting for your OK',
  'applying revision': 'Applying your changes',
  'running final qa': 'Running quality checks',
  'ready': 'Ready', 'needs review': 'Needs review',
  'failed': 'Something went wrong', 'cancelled': 'Cancelled',
};

async function renderProject() {
  let pr;
  try { pr = await api('/projects/' + state.projectId); }
  catch (_) { return; }
  $('p-title').textContent = pr.title;
  $('p-status').textContent = HUMAN_STATUS[pr.status] || pr.status;
  $('p-detail').textContent = pr.status_detail || '';
  const ul = $('p-files'); ul.replaceChildren();
  pr.uploads.forEach((u) => {
    const li = document.createElement('li');
    li.textContent = `${u.filename} (${u.status})`;
    ul.appendChild(li);
  });
  if (pr.transcript && !$('p-script').value) {
    $('p-script').value = pr.transcript;
    $('p-scriptbox').open = true;
  }
  const applied = pr.revisions.filter((r) => r.status === 'applied'
    && r.has_output);
  if (applied.length) {
    const last = applied[applied.length - 1];
    $('p-result').classList.remove('hidden');
    const src = '/api/media/' + encodeURIComponent(lastOutputKey(pr, last));
    if ($('player').dataset.rev !== last.id) {
      $('player').src = src; $('player').dataset.rev = last.id;
      $('download').href = src;
      $('download').download = pr.title.replace(/\W+/g, '_') + '.mp4';
    }
    $('qa-line').textContent = last.qa_pass
      ? 'All quality checks passed.'
      : 'A quality check failed; watch before using (Needs Review).';
  }
  // chat + proposals
  const chat = $('chat'); chat.replaceChildren();
  pr.chat.forEach((c) => {
    const d = document.createElement('div');
    d.className = 'msg ' + c.role;
    d.textContent = c.content;
    chat.appendChild(d);
  });
  chat.scrollTop = chat.scrollHeight;
  const pending = pr.revisions.find((r) => r.status === 'proposed'
    && r.needs_approval);
  const box = $('proposal');
  if (pending) {
    box.classList.remove('hidden');
    const prop = JSON.parse(pending.proposal_json || '{}');
    box.replaceChildren();
    const title = document.createElement('b');
    title.textContent = 'Proposed changes (needs your OK):';
    const changes = document.createElement('ul');
    for (const operation of (prop.operations || [])) {
      const item = document.createElement('li');
      item.textContent = operation.human || operation.op || 'Edit';
      changes.appendChild(item);
    }
    const apply = document.createElement('button');
    apply.className = 'primary'; apply.textContent = 'Apply';
    const reject = document.createElement('button');
    reject.className = 'ghost'; reject.textContent = 'Reject';
    box.append(title, changes, apply, document.createTextNode(' '), reject);
    apply.onclick = () =>
      api(`/revisions/${pending.id}/approve`, { method: 'POST' })
        .then(renderProject);
    reject.onclick = () =>
      api(`/revisions/${pending.id}/reject`, { method: 'POST' })
        .then(renderProject);
  } else box.classList.add('hidden');
  const revs = $('revs'); revs.replaceChildren();
  pr.revisions.forEach((r) => {
    const li = document.createElement('li');
    li.textContent = `#${r.num} ${r.request_text || ''}: ${r.status}` +
      (r.qa_pass === 1 ? ' (QA pass)' :
        r.qa_pass === 0 && r.status === 'applied' ? ' (needs review)' : '');
    revs.appendChild(li);
  });
}
function lastOutputKey(pr, rev) {
  // output keys are conventional: u/<user>/<proj>/out/<rev>.mp4; the
  // media route enforces per-user scoping server-side regardless.
  return rev.output_key || '';
}

// ------------------------------------------------------------ uploads
async function uploadFile(file) {
  const meta = await api(`/projects/${state.projectId}/uploads`, {
    method: 'POST', body: { filename: file.name, size: file.size } });
  const partSize = meta.part_size;
  const uploaded = new Set(meta.uploaded_parts || []);
  const total = Math.ceil(file.size / partSize) || 1;
  for (let i = 0; i < total; i++) {
    if (uploaded.has(i + 1)) {
      $('up-progress').textContent =
        `Resuming ${file.name}: ${Math.round(((i + 1) / total) * 100)}%`;
      continue;
    }
    const blob = file.slice(i * partSize, (i + 1) * partSize);
    let ok = false, tries = 0;
    while (!ok && tries < 5) {
      tries += 1;
      try {
        const r = await fetch(
          `/api/uploads/${meta.upload_id}/part?n=${i + 1}`,
          { method: 'PUT', body: blob, credentials: 'same-origin' });
        ok = r.ok;
      } catch (_) { /* retry */ }
      if (!ok) await new Promise((res) => setTimeout(res, 1500 * tries));
    }
    if (!ok) { $('up-progress').textContent =
      'Upload interrupted. It will resume when you try again.'; return; }
    $('up-progress').textContent =
      `Uploading ${file.name}: ${Math.round(((i + 1) / total) * 100)}%`;
  }
  await api(`/uploads/${meta.upload_id}/complete`, { method: 'POST' });
  $('up-progress').textContent = `${file.name} uploaded.`;
  renderProject();
}

const dz = $('dropzone');
dz.onclick = () => {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = 'video/*'; inp.multiple = true;
  inp.onchange = () => [...inp.files].forEach(uploadFile);
  inp.click();
};
dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('hover'); };
dz.ondragleave = () => dz.classList.remove('hover');
dz.ondrop = (e) => {
  e.preventDefault(); dz.classList.remove('hover');
  [...e.dataTransfer.files].forEach(uploadFile);
};

// ------------------------------------------------------------ actions
$('make').onclick = async () => {
  try {
    await api(`/projects/${state.projectId}/make`, { method: 'POST',
      body: { script: $('p-script').value.trim() || null } });
    $('p-progresslog').classList.remove('hidden');
  } catch (e) { alert(e.message); }
};
$('chat-send').onclick = async () => {
  const text = $('chat-input').value.trim();
  if (!text) return;
  $('chat-input').value = '';
  // optimistic bubble so the back-and-forth feels instant
  const chatBox = $('chat');
  const mine = document.createElement('div');
  mine.className = 'msg user'; mine.textContent = text;
  chatBox.appendChild(mine);
  const thinking = document.createElement('div');
  thinking.className = 'msg assistant'; thinking.textContent = '…';
  chatBox.appendChild(thinking);
  chatBox.scrollTop = chatBox.scrollHeight;
  try {
    const r = await api(`/projects/${state.projectId}/chat`,
      { method: 'POST', body: { text } });
    thinking.textContent = r.reply || '…';
  } catch (e) { thinking.textContent = 'Sorry, ' + e.message; }
  renderProject();
};

// ---- self-serve settings
$('cc-copy').onclick = () => {
  $('cc-value').select();
  navigator.clipboard.writeText($('cc-value').value).catch(() => {});
};
$('otp-start').onclick = async () => {
  try {
    const r = await api('/me/otp/setup', { method: 'POST' });
    $('otp-secret').value = r.secret;
    $('otp-link').href = r.otpauth;
    $('otp-setup').classList.remove('hidden');
    $('otp-off').classList.add('hidden');
  } catch (e) { alert(e.message); }
};
$('otp-copy').onclick = () => {
  $('otp-secret').select();
  navigator.clipboard.writeText($('otp-secret').value).catch(() => {});
};
$('otp-verify').onclick = async () => {
  try {
    await api('/me/otp/verify', { method: 'POST',
      body: { code: $('otp-code').value.trim() } });
    $('otp-msg').textContent = 'Quick codes are on!';
    $('otp-setup').classList.add('hidden');
    $('otp-on').classList.remove('hidden');
    state.me.hasOtp = true;
  } catch (e) { $('otp-msg').textContent = e.message; }
};
$('chat-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('chat-send').click();
});
$('back').onclick = () => { clearInterval(state.pollTimer); dash(); };
$('delete-project').onclick = async () => {
  const confirmed = window.confirm(
    'Permanently delete this project, its uploaded footage, finished videos, and QA files?');
  if (!confirmed) return;
  try {
    await api('/projects/' + state.projectId, { method: 'DELETE' });
    clearInterval(state.pollTimer);
    state.projectId = null;
    await dash();
  } catch (error) { alert(error.message); }
};
$('si-go').onclick = async () => {
  try {
    await api('/auth/signin', { method: 'POST', body: {
      name: $('si-name').value.trim(), invite_code: $('si-code').value.trim(),
    } });
    boot();
  } catch (e) { $('si-msg').textContent = e.message; }
};
$('key-save').onclick = async () => {
  const btn = $('key-save');
  btn.disabled = true;
  $('key-msg').textContent = 'Checking your key with DeepSeek…';
  try {
    await api('/me/key', { method: 'PUT',
      body: { key: $('key-input').value.trim() } });
    $('key-input').value = '';
    $('key-msg').textContent = 'Unlocked!';
    boot();
  } catch (e) {
    $('key-msg').textContent = e.message;
  } finally { btn.disabled = false; }
};

// ---- built-in DeepSeek help chat (always available once key is valid)
const helpHistory = [];
function renderHelp() {
  const box = $('help-chat'); box.replaceChildren();
  helpHistory.forEach((m) => {
    const d = document.createElement('div');
    d.className = 'msg ' + m.role;
    d.textContent = m.content;
    box.appendChild(d);
  });
  box.scrollTop = box.scrollHeight;
}
$('help-fab').onclick = () => {
  $('help-panel').classList.remove('hidden');
  $('help-fab').classList.add('hidden');
  if (!helpHistory.length) {
    helpHistory.push({ role: 'assistant',
      content: "Hi! I'm your DeepSeek helper. Ask me anything, including setup, " +
        'an error you saw, or what to make. How can I help?' });
    renderHelp();
  }
  $('help-input').focus();
};
$('help-close').onclick = () => {
  $('help-panel').classList.add('hidden');
  $('help-fab').classList.remove('hidden');
};
$('help-send').onclick = async () => {
  const text = $('help-input').value.trim();
  if (!text) return;
  $('help-input').value = '';
  helpHistory.push({ role: 'user', content: text });
  renderHelp();
  helpHistory.push({ role: 'assistant', content: '…' });
  renderHelp();
  try {
    const r = await api('/assistant', { method: 'POST',
      body: { messages: helpHistory.filter((m) => m.content !== '…') } });
    helpHistory[helpHistory.length - 1] = { role: 'assistant',
      content: r.reply || '(no reply)' };
  } catch (e) {
    helpHistory[helpHistory.length - 1] = { role: 'assistant',
      content: 'Sorry, ' + e.message };
  }
  renderHelp();
};
$('help-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('help-send').click();
});
$('signout').onclick = async () => {
  await api('/auth/signout', { method: 'POST' });
  location.reload();
};

boot();
