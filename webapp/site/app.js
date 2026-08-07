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
    if (!state.me.hasKey) return show('keysetup');
    await dash();
  } catch (_) { show('signin'); }
}

async function dash() {
  show('dash');
  const t = $('types'); t.innerHTML = '';
  TYPES.forEach(([id, name, desc]) => {
    const d = document.createElement('div');
    d.className = 'type';
    d.innerHTML = `<b>${name}</b><span class="muted">${desc}</span>`;
    d.onclick = async () => {
      const proj = await api('/projects', { method: 'POST',
        body: { type: id, title: name } });
      openProject(proj.id);
    };
    t.appendChild(d);
  });
  const list = await api('/projects');
  const ul = $('projects'); ul.innerHTML = '';
  if (!list.length) ul.innerHTML =
    '<li class="muted">Nothing yet. Pick a type above to start.</li>';
  list.forEach((pr) => {
    const li = document.createElement('li');
    li.innerHTML = `<a href="#">${pr.title}</a> ` +
      `<span class="badge">${pr.status}</span>`;
    li.querySelector('a').onclick = (e) => {
      e.preventDefault(); openProject(pr.id);
    };
    ul.appendChild(li);
  });
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
  const ul = $('p-files'); ul.innerHTML = '';
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
  const chat = $('chat'); chat.innerHTML = '';
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
    box.innerHTML =
      `<b>Proposed changes (needs your OK):</b>` +
      `<ul>${(prop.operations || []).map((o) =>
        `<li>${o.human || o.op}</li>`).join('')}</ul>` +
      `<button class="primary" id="prop-ok">Apply</button> ` +
      `<button class="ghost" id="prop-no">Reject</button>`;
    $('prop-ok').onclick = () =>
      api(`/revisions/${pending.id}/approve`, { method: 'POST' })
        .then(renderProject);
    $('prop-no').onclick = () =>
      api(`/revisions/${pending.id}/reject`, { method: 'POST' })
        .then(renderProject);
  } else box.classList.add('hidden');
  const revs = $('revs'); revs.innerHTML = '';
  pr.revisions.forEach((r) => {
    const li = document.createElement('li');
    li.textContent = `#${r.num} ${r.request_text || ''} — ${r.status}` +
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
  const total = Math.ceil(file.size / partSize) || 1;
  for (let i = 0; i < total; i++) {
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
  try {
    await api(`/projects/${state.projectId}/chat`, { method: 'POST',
      body: { text } });
    renderProject();
  } catch (e) { alert(e.message); }
};
$('chat-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('chat-send').click();
});
$('back').onclick = () => { clearInterval(state.pollTimer); dash(); };
$('si-go').onclick = async () => {
  try {
    await api('/auth/signin', { method: 'POST', body: {
      name: $('si-name').value.trim(), invite_code: $('si-code').value.trim(),
    } });
    boot();
  } catch (e) { $('si-msg').textContent = e.message; }
};
$('key-save').onclick = async () => {
  try {
    await api('/me/key', { method: 'PUT',
      body: { key: $('key-input').value.trim() } });
    $('key-input').value = '';
    boot();
  } catch (e) { $('key-msg').textContent = e.message; }
};
$('signout').onclick = async () => {
  await api('/auth/signout', { method: 'POST' });
  location.reload();
};

boot();
