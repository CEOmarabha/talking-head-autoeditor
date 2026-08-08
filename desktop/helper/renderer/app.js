const $ = (id) => document.getElementById(id);
let running = false;

const labels = {
  daemon: 'Helper engine', engine: 'Editing engine', ffmpeg: 'FFmpeg',
  ffprobe: 'FFprobe', smallModel: 'Speech model', mediumModel: 'QA speech model',
  profiles: 'Editing profiles', fonts: 'Fonts', caBundle: 'Secure connections',
  notices: 'License notices', keystore: 'OS keystore', disk: '20 GB free space',
  codecs: 'H.264 and AAC codecs', filters: 'Required video filters',
  node: 'Built-in Node runtime', hyperframes: 'HyperFrames',
  remotion: 'Remotion', browser: 'Built-in rendering browser',
};

function selected(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value || '';
}

function syncChoices() {
  $('pexels-connect').classList.toggle('hidden', selected('pexels-mode') === 'skip');
  $('pixabay-connect').classList.toggle('hidden', selected('pixabay-mode') === 'skip');
  $('eleven-connect').classList.toggle('hidden', selected('eleven-mode') === 'skip');
  $('remotion-paid').classList.toggle('hidden', selected('remotion-mode') !== 'paid');
}

function renderCapabilities(value) {
  const root = $('capabilities');
  if (!value) { root.innerHTML = ''; return; }
  const names = {
    hyperframes: 'HyperFrames graphics', remotion: 'Remotion diagrams',
    pexels: 'Pexels footage', pixabay: 'Pixabay footage',
    elevenlabs: 'ElevenLabs sound effects',
  };
  root.innerHTML = '<b>Available for edits</b>';
  for (const [key, label] of Object.entries(names)) {
    const row = document.createElement('div');
    row.className = value[key] ? 'available' : 'unavailable';
    row.textContent = `${value[key] ? 'Available' : 'Skipped'}: ${label}`;
    root.appendChild(row);
  }
}

function renderChecks(preflight) {
  const root = $('checks'); root.innerHTML = '';
  for (const [name, ok] of Object.entries(preflight.checks || {})) {
    const item = document.createElement('div');
    item.className = `check ${ok ? 'ok' : 'bad'}`;
    item.textContent = `${ok ? '✓' : '✕'} ${labels[name] || name}`;
    root.appendChild(item);
  }
}

function renderState(state) {
  running = !!state.running;
  const configured = state.configured !== false;
  $('status').textContent = running ? 'Running' : (state.error
    ? 'Stopped' : (configured ? 'Ready' : 'Setup needed'));
  $('status').className = `pill ${running ? 'on' : (state.error ? 'bad' : '')}`;
  $('headline').textContent = running ? 'Helper is running' : 'Helper is stopped';
  $('detail').textContent = state.error || (running
    ? 'Leave this app open while AutoEditor makes your video.'
    : 'Start it whenever you want to make a video.');
  $('start').disabled = running; $('stop').disabled = !running;
  if (state.preflight) renderChecks(state.preflight);
  renderCapabilities(state.capabilities || null);
}

async function boot() {
  const state = await window.helper.state();
  $('setup').classList.toggle('hidden', state.configured);
  $('ready').classList.toggle('hidden', !state.configured);
  renderState(state);
}

$('save').onclick = async () => {
  $('setup-error').textContent = '';
  $('save').disabled = true;
  $('checking').classList.remove('hidden');
  try {
    const result = await window.helper.save({
      setupCode: $('code').value,
      pexelsMode: selected('pexels-mode'), pexelsKey: $('pexels-key').value,
      pixabayMode: selected('pixabay-mode'), pixabayKey: $('pixabay-key').value,
      elevenMode: selected('eleven-mode'), elevenKey: $('eleven-key').value,
      remotionMode: selected('remotion-mode'), remotionKey: $('remotion-key').value,
    });
    renderChecks(result.preflight);
    $('pexels-key').value = ''; $('pixabay-key').value = '';
    $('eleven-key').value = '';
    $('remotion-key').value = '';
    $('setup').classList.add('hidden'); $('ready').classList.remove('hidden');
    await window.helper.start();
  } catch (error) { $('setup-error').textContent = error.message || String(error); }
  finally { $('save').disabled = false; $('checking').classList.add('hidden'); }
};
$('start').onclick = async () => {
  try { await window.helper.start(); } catch (error) { renderState({ error: error.message }); }
};
$('stop').onclick = () => window.helper.stop();
$('reset').onclick = async () => { await window.helper.reset(); $('code').value = ''; boot(); };
$('notices').onclick = () => window.helper.notices();
document.querySelectorAll('input[type="radio"]').forEach((radio) => {
  radio.addEventListener('change', syncChoices);
});
document.querySelectorAll('[data-open]').forEach((button) => {
  button.addEventListener('click', () => window.helper.open(button.dataset.open));
});
window.helper.onState(renderState);
window.helper.onLog((line) => {
  $('log').textContent = ($('log').textContent + line).slice(-12000);
  $('log').scrollTop = $('log').scrollHeight;
});
syncChoices();
boot().catch((error) => renderState({ error: error.message }));
