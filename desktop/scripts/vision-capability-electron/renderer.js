'use strict';

let worker = null;
let activeId = null;

function stop() {
  try { worker?.terminate(); } catch (_) { /* best effort */ }
  worker = null;
  activeId = null;
}

function localWorker() {
  if (worker) return worker;
  const target = new URL(
    '../../helper/vision/vision-worker.bundle.js', window.location.href);
  const current = new Worker(target, { name: 'autoeditor-vision-capability' });
  worker = current;
  current.addEventListener('message', (event) => {
    const value = event.data;
    if (current !== worker || !value || typeof value !== 'object' ||
        value.id !== activeId) return;
    if (value.status === 'progress') return;
    activeId = null;
    window.autoeditorVisionProbe.result(value);
  });
  current.addEventListener('error', () => {
    if (current !== worker || activeId === null) return;
    const id = activeId;
    stop();
    window.autoeditorVisionProbe.result({
      id, status: 'error', error: 'local vision worker execution failed',
    });
  });
  return current;
}

function validModelRequest(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join('\0') !==
        'candidate_token_ids\0candidates\0prompt' ||
      !Array.isArray(value.candidates) ||
      value.candidates.join('\0') !== 'A\0B\0U' ||
      typeof value.prompt !== 'string' || value.prompt.length < 1 ||
      value.prompt.length > 4000 || !value.candidate_token_ids ||
      typeof value.candidate_token_ids !== 'object' ||
      Array.isArray(value.candidate_token_ids) ||
      Object.keys(value.candidate_token_ids).sort().join('\0') !== 'A\0B\0U') {
    return false;
  }
  return ['A', 'B', 'U'].every((label) => {
    const ids = value.candidate_token_ids[label];
    return Array.isArray(ids) && ids.length === 1 &&
      Number.isSafeInteger(ids[0]) && ids[0] >= 0 && ids[0] <= 0x7fffffff;
  });
}

window.autoeditorVisionProbe.onRequest((request) => {
  const id = request?.id;
  if (!Number.isSafeInteger(id) || id < 1 || !Array.isArray(request.images) ||
      request.images.length < 1 || request.images.length > 8 ||
      request.images.some((image) => typeof image !== 'string' ||
        !image.startsWith('data:image/jpeg;base64,')) ||
      request.mode !== 'artifact-assertion' ||
      !validModelRequest(request.model_request)) return;
  if (activeId !== null) {
    window.autoeditorVisionProbe.result({
      id, status: 'error', error: 'local vision worker is already active',
    });
    return;
  }
  activeId = id;
  try {
    localWorker().postMessage({
      id,
      images: request.images,
      mode: 'artifact-assertion',
      context: JSON.stringify(request.model_request),
    });
  } catch (_) {
    stop();
    window.autoeditorVisionProbe.result({
      id, status: 'error', error: 'local vision worker request failed',
    });
  }
});
