import {
  env,
  AutoProcessor,
  AutoModelForVision2Seq,
  load_image,
} from './transformers.web.min.js';

const MODEL_ID = 'HuggingFaceTB/SmolVLM2-256M-Video-Instruct';
const MODEL_REVISION = '067788b187b95ebe7b2e040b3e4299e342e5b8fd';
const MAX_IMAGES = 8;
const MAX_IMAGE_CHARS = 3 * 1024 * 1024;
let runtimePromise = null;

env.allowRemoteModels = true;
env.allowLocalModels = false;
env.backends.onnx.wasm.wasmPaths = 'autoeditor-vision://runtime/';
env.backends.onnx.wasm.numThreads = 1;

function progressReporter(id) {
  const seen = new Map();
  return (event) => {
    if (!event || event.status !== 'progress' || !Number.isFinite(event.progress)) return;
    const percent = Math.max(0, Math.min(100, Math.floor(event.progress / 10) * 10));
    const file = String(event.file || 'vision model').slice(0, 120);
    if (seen.get(file) === percent) return;
    seen.set(file, percent);
    if (percent === 0 || percent === 100 || percent % 20 === 0) {
      self.postMessage({ id, status: 'progress',
        line: `Local vision model: ${file} ${percent}%` });
    }
  };
}

async function getRuntime(id) {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      const progress_callback = progressReporter(id);
      self.postMessage({ id, status: 'progress',
        line: 'Loading the free local vision model. The first use downloads it once...' });
      let webgpu = false;
      try {
        const adapter = await navigator.gpu?.requestAdapter();
        webgpu = !!adapter;
      } catch (_) { /* WASM fallback remains local */ }
      const processor = await AutoProcessor.from_pretrained(MODEL_ID, {
        revision: MODEL_REVISION, progress_callback,
      });
      if (webgpu) {
        try {
          const model = await AutoModelForVision2Seq.from_pretrained(MODEL_ID, {
            revision: MODEL_REVISION, dtype: 'q4', device: 'webgpu', progress_callback,
          });
          return { processor, model, device: 'webgpu', dtype: 'q4' };
        } catch (error) {
          self.postMessage({ id, status: 'progress',
            line: 'WebGPU was unavailable for this model. Continuing locally with WASM...' });
        }
      }
      const model = await AutoModelForVision2Seq.from_pretrained(MODEL_ID, {
        revision: MODEL_REVISION, dtype: 'q4', device: 'wasm', progress_callback,
      });
      return { processor, model, device: 'wasm', dtype: 'q4' };
    })().catch((error) => {
      runtimePromise = null;
      throw error;
    });
  }
  return runtimePromise;
}

function cleanResult(value) {
  let text = String(value || '').replace(/\0/g, '').trim();
  const marker = text.lastIndexOf('Assistant:');
  if (marker >= 0) text = text.slice(marker + 'Assistant:'.length).trim();
  return text.slice(0, 5000);
}

function artifactPrompt(context) {
  const value = typeof context === 'string' ? context.slice(0, 8000) : '';
  return value || [
    'You are the final visual quality-control gate for a professionally edited video.',
    'The frames cover the entire finished artifact in chronological order.',
    'Reject unreadable or face-obscuring captions, unsafe framing, weak contrast,',
    'bad crops, accidental transitions, unfinished graphics, continuity defects,',
    'or an amateur and visually repetitive result. Return strict JSON with schema',
    'autoeditor-artifact-review/v1, boolean pass, score 0-100, checks containing',
    'captions, framing, visualVariety, graphics, transitions, productionDesign,',
    'and a specific issues array. pass can be true only at score 92+ with all checks true.',
    'Return JSON only.',
  ].join(' ');
}

async function describe(id, images, mode = '', context = '') {
  if (!Array.isArray(images) || images.length < 1 || images.length > MAX_IMAGES ||
      images.some((image) => typeof image !== 'string' ||
        !image.startsWith('data:image/jpeg;base64,') || image.length > MAX_IMAGE_CHARS)) {
    throw new Error('local vision frames were invalid');
  }
  const { processor, model, device, dtype } = await getRuntime(id);
  self.postMessage({ id, status: 'progress',
    line: `Watching ${images.length} representative frames locally with ${device}/${dtype}...` });
  const frames = await Promise.all(images.map((image) => load_image(image)));
  const messages = [{ role: 'user', content: [
    ...frames.map(() => ({ type: 'image' })),
    { type: 'text', text: mode === 'artifact-quality' ? artifactPrompt(context) : [
      'These are chronological frames sampled from one attached video.',
      'Describe only visibly supported people, actions, objects, setting, products,',
      'readable on-screen text, camera framing, composition, and meaningful changes.',
      'Note uncertainty. Do not invent names or dialogue. Return one concise factual',
      'production report for a video editor.',
    ].join(' ') },
  ] }];
  const prompt = processor.apply_chat_template(messages, { add_generation_prompt: true });
  const inputs = await processor(prompt, frames, { do_image_splitting: false });
  const output = await model.generate({
    ...inputs, do_sample: false, repetition_penalty: 1.05,
    max_new_tokens: mode === 'artifact-quality' ? 420 : 220,
  });
  const decoded = processor.batch_decode(output, { skip_special_tokens: true });
  const result = cleanResult(decoded.at(-1));
  if (!result) throw new Error('local vision model returned no description');
  return result;
}

self.addEventListener('message', async (event) => {
  const id = event.data?.id;
  if (!Number.isSafeInteger(id) || id < 1) return;
  try {
    const result = await describe(
      id, event.data.images, event.data.mode, event.data.context);
    self.postMessage({ id, status: 'complete', result });
  } catch (error) {
    self.postMessage({ id, status: 'error',
      error: String(error?.message || error).slice(0, 1000) });
  }
});
