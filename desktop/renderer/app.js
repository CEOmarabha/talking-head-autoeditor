/* One-screen flow: profile -> clips -> script -> extras -> Edit Reel. */
const $ = (id) => document.getElementById(id);
const state = {
  profile: null, clips: [], music: null, broll: [], outDir: null,
  joinedInput: null, workDir: null, running: false,
};

const PHASES = [
  [/phase 1/i, 8, 'Preparing your footage'],
  [/phase 2(?!B)/i, 22, 'Cutting silence and flubbed takes'],
  [/phase 2B/i, 32, 'Second cleanup pass'],
  [/phase 3/i, 45, 'Transcribing your words'],
  [/phase 4p/i, 58, 'Planning the edit (AI director)'],
  [/caption|band/i, 70, 'Building captions'],
  [/render|phase 6/i, 82, 'Rendering the master'],
  [/QA|gate|sync|integrity/i, 93, 'Running quality checks'],
];

async function init() {
  const s = await window.api.state();
  document.title = s.product.name;
  $('app-name').textContent = s.product.name;
  $('tagline').textContent = s.product.tagline +
    '  ·  v' + s.version;
  const box = $('profiles');
  box.innerHTML = '';
  s.profiles.forEach((p) => {
    const d = document.createElement('div');
    d.className = 'profile';
    d.innerHTML = `<b>${p.display_name}</b>` +
      `<span class="muted">${p.description}</span>`;
    d.onclick = () => {
      state.profile = p.id;
      [...box.children].forEach((c) => c.classList.remove('sel'));
      d.classList.add('sel');
      refresh();
    };
    box.appendChild(d);
  });
  if (s.profiles.length === 1) box.children[0].click();
  if (!s.hasKey) showSettings(true);
  else $('main').classList.remove('hidden');
}

function showSettings(firstRun) {
  $('settings').classList.remove('hidden');
  if (firstRun) {
    $('settings-msg').textContent =
      'Welcome! Paste your DeepSeek API key once to get started.';
    $('main').classList.add('hidden');
  }
}

function refresh() {
  $('edit-btn').disabled =
    !(state.profile && state.clips.length && !state.running);
}

function renderClips() {
  const ul = $('clip-list');
  ul.innerHTML = '';
  state.clips.forEach((c, i) => {
    const li = document.createElement('li');
    li.innerHTML = `${c.split(/[\\/]/).pop()}<span data-i="${i}">✕</span>`;
    li.querySelector('span').onclick = (e) => {
      state.clips.splice(+e.target.dataset.i, 1);
      state.joinedInput = null; // joined file is stale now
      renderClips(); refresh();
    };
    ul.appendChild(li);
  });
  refresh();
}

// ---- wiring
$('settings-btn').onclick = () => showSettings(false);
$('outdir-btn').onclick = async () => {
  const d = await window.api.pickOutdir();
  if (d) { state.outDir = d; $('outdir-input').value = d; }
};
$('settings-save').onclick = async () => {
  const key = $('key-input').value.trim();
  if (key) {
    const r = await window.api.saveKey(key);
    if (!r.ok) { $('settings-msg').textContent = r.error; return; }
    $('key-input').value = '';
  }
  $('settings-msg').textContent = 'Saved.';
  $('settings').classList.add('hidden');
  $('main').classList.remove('hidden');
};

const dz = $('dropzone');
dz.onclick = async () => {
  const f = await window.api.pickFiles('video');
  if (f.length) { state.clips.push(...f); state.joinedInput = null; }
  renderClips();
};
dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('hover'); };
dz.ondragleave = () => dz.classList.remove('hover');
dz.ondrop = (e) => {
  e.preventDefault(); dz.classList.remove('hover');
  const files = [...e.dataTransfer.files]
    .filter((f) => /\.(mp4|mov|m4v|mkv|webm)$/i.test(f.name))
    .map((f) => f.path);
  if (files.length) { state.clips.push(...files); state.joinedInput = null; }
  renderClips();
};

$('transcribe-btn').onclick = async () => {
  if (!state.clips.length) {
    $('transcribe-status').textContent = 'Add clips first.'; return;
  }
  $('transcribe-status').textContent =
    'Listening to your clips… (first run downloads the speech model)';
  $('transcribe-btn').disabled = true;
  const r = await window.api.transcribe({ clips: state.clips });
  $('transcribe-btn').disabled = false;
  if (r.ok) {
    $('script-box').value = r.text;
    state.joinedInput = r.joinedInput;
    state.workDir = r.workDir;
    $('transcribe-status').textContent =
      `${r.words} words. Fix anything it misheard, then edit.`;
  } else {
    $('transcribe-status').textContent = r.error;
  }
};

$('music-btn').onclick = async () => {
  const f = await window.api.pickFiles('music');
  if (f.length) { state.music = f[0];
    $('music-name').textContent = f[0].split(/[\\/]/).pop(); }
};
$('broll-btn').onclick = async () => {
  const f = await window.api.pickFiles('video');
  if (f.length) { state.broll = f;
    $('broll-name').textContent = `${f.length} clip(s)`; }
};

window.api.onLog((line) => {
  const log = $('log');
  log.textContent += line + '\n';
  log.scrollTop = log.scrollHeight;
  for (const [re, pct, label] of PHASES) {
    if (re.test(line)) {
      $('bar-fill').style.width = pct + '%';
      $('phase-label').textContent = label;
    }
  }
});

$('edit-btn').onclick = async () => {
  const script = $('script-box').value.trim();
  if (!script) {
    $('transcribe-status').textContent =
      'Add a script or generate the transcript first: quality checks ' +
      'need the text you performed.';
    return;
  }
  state.running = true; refresh();
  $('progress').classList.remove('hidden');
  $('result').classList.add('hidden');
  $('log').textContent = '';
  $('bar-fill').style.width = '2%';
  const r = await window.api.edit({
    clips: state.clips, joinedInput: state.joinedInput,
    workDir: state.workDir, profile: state.profile,
    script, music: state.music, broll: state.broll, outDir: state.outDir,
  });
  state.running = false; refresh();
  $('progress').classList.add('hidden');
  $('result').classList.remove('hidden');
  const title = $('result-title');
  if (r.ok && r.qa_pass) {
    $('bar-fill').style.width = '100%';
    title.textContent = 'Done. Your reel passed every check.';
    title.className = 'ok';
    $('result-detail').textContent =
      'Sync, speech, captions, and rendering all verified. ' +
      `Finished in ${Math.round((r.seconds || 0) / 60)} min.`;
    const out = Object.values(r.outputs || {})[0];
    $('reveal-btn').onclick = () => window.api.reveal(out);
  } else if (r.ok) {
    title.textContent = 'Needs Review';
    title.className = 'warn';
    $('result-detail').textContent =
      'The edit finished but a quality check failed, so this is NOT ' +
      'marked upload-ready. Open the folder to watch it and see ' +
      'QA_REPORT.json.';
    $('reveal-btn').onclick = () => window.api.openPath(r.outdir);
  } else {
    title.textContent = 'The edit could not finish';
    title.className = 'warn';
    $('result-detail').textContent = r.error || 'See the log above.';
    $('reveal-btn').onclick = () => {};
  }
};

$('cancel-btn').onclick = async () => {
  await window.api.cancel();
  state.running = false; refresh();
  $('progress').classList.add('hidden');
};
$('again-btn').onclick = () => {
  $('result').classList.add('hidden');
  state.clips = []; state.joinedInput = null; state.music = null;
  state.broll = [];
  renderClips();
  $('script-box').value = ''; $('music-name').textContent = '';
  $('broll-name').textContent = '';
};

init();
