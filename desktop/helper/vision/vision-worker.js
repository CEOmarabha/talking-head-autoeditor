import {
  env,
  AutoProcessor,
  AutoModelForVision2Seq,
  LogitsProcessor,
  LogitsProcessorList,
  load_image,
} from './transformers.web.min.js';

const MODEL_ID = 'HuggingFaceTB/SmolVLM2-256M-Video-Instruct';
const MODEL_REVISION = '067788b187b95ebe7b2e040b3e4299e342e5b8fd';
const MODEL_PACK_LOCK_SHA256 =
  'adc37855602e89d80260fbb8768aa2b87fb4b928f34d9765a4e6c267f554a1fa';
const MODEL_PACK_TREE_SHA256 =
  '5ab9f376a07e111ed08957c6db3847e4531b55589f6dbfe3fdb35619171bbc21';
const WORKER_RUNTIME_SCHEMA_VERSION =
  'autoeditor-local-vision-worker-runtime/v1';
const MAX_IMAGES = 8;
const MAX_IMAGE_CHARS = 3 * 1024 * 1024;
const ATOMIC_CHOICE_CANDIDATES = Object.freeze(['A', 'B', 'U']);
const ATOMIC_CHOICE_TOKEN_IDS = Object.freeze([49, 50, 69]);
let runtimePromise = null;
let blockedNetworkRequests = 0;

const platformFetch = globalThis.fetch.bind(globalThis);
env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = 'autoeditor-vision://model/';
env.useBrowserCache = false;
env.useFSCache = false;
env.useCustomCache = false;
env.fetch = (input, init) => {
  const raw = typeof input === 'string' || input instanceof URL
    ? String(input) : String(input?.url || '');
  let url;
  try { url = new URL(raw, self.location.href); }
  catch (_) { throw new Error('local vision rejected an invalid resource URL'); }
  if (!['autoeditor-vision:', 'data:', 'blob:'].includes(url.protocol)) {
    blockedNetworkRequests += 1;
    throw new Error('local vision blocked a non-local resource request');
  }
  return platformFetch(input, init);
};
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
        line: 'Loading the bundled verified local vision model...' });
      let webgpu = false;
      try {
        const adapter = await navigator.gpu?.requestAdapter();
        webgpu = !!adapter;
      } catch (_) { /* WASM fallback remains local */ }
      const processor = await AutoProcessor.from_pretrained(MODEL_ID, {
        revision: MODEL_REVISION, local_files_only: true, progress_callback,
      });
      if (webgpu) {
        try {
          const model = await AutoModelForVision2Seq.from_pretrained(MODEL_ID, {
            revision: MODEL_REVISION, dtype: 'q4', device: 'webgpu',
            local_files_only: true, progress_callback,
          });
          return { processor, model, device: 'webgpu', dtype: 'q4' };
        } catch (error) {
          self.postMessage({ id, status: 'progress',
            line: 'WebGPU was unavailable for this model. Continuing locally with WASM...' });
        }
      }
      const model = await AutoModelForVision2Seq.from_pretrained(MODEL_ID, {
        revision: MODEL_REVISION, dtype: 'q4', device: 'wasm',
        local_files_only: true, progress_callback,
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

function runtimeEvidence(device, dtype) {
  if (blockedNetworkRequests !== 0) {
    throw new Error('local vision attempted to access a non-local resource');
  }
  return {
    schema_version: WORKER_RUNTIME_SCHEMA_VERSION,
    model_id: MODEL_ID,
    model_revision: MODEL_REVISION,
    model_dtype: dtype,
    model_pack_lock_sha256: MODEL_PACK_LOCK_SHA256,
    model_pack_tree_sha256: MODEL_PACK_TREE_SHA256,
    backend: device,
    remote_requests: 0,
  };
}

class AtomicChoiceLogitsProcessor extends LogitsProcessor {
  constructor(candidateTokenIds, eosTokenId) {
    super();
    this.candidateTokenIds = candidateTokenIds;
    this.eosTokenId = eosTokenId;
    this.relativeLogitsMilli = null;
    this.selectedTokenId = null;
  }

  _call(inputIds, batchedLogits) {
    for (let row = 0; row < inputIds.length; row += 1) {
      const logits = batchedLogits[row].data;
      let allowed;
      if (this.relativeLogitsMilli === null) {
        const observed = this.candidateTokenIds.map((token) => Number(logits[token]));
        if (row !== 0 || observed.some((value) => !Number.isFinite(value))) {
          throw new Error('local vision atomic choice logits are invalid');
        }
        const maximum = Math.max(...observed);
        this.relativeLogitsMilli = observed.map((value) =>
          Math.max(-1_000_000_000, Math.min(0,
            Math.round((value - maximum) * 1000))));
        this.selectedTokenId = this.candidateTokenIds[observed.indexOf(maximum)];
        allowed = new Set(this.candidateTokenIds);
      } else {
        const lastToken = Number(inputIds[row].at(-1));
        if (row !== 0 || lastToken !== this.selectedTokenId) {
          throw new Error('local vision atomic choice prefix drifted');
        }
        allowed = new Set([this.eosTokenId]);
      }
      for (let token = 0; token < logits.length; token += 1) {
        if (!allowed.has(token)) logits[token] = -Infinity;
      }
    }
    return batchedLogits;
  }
}

function exactAtomicChoiceCandidates(processor) {
  const eosTokenId = Number(processor.tokenizer?.eos_token_id);
  if (!Number.isSafeInteger(eosTokenId) || eosTokenId < 0) {
    throw new Error('local vision choice EOS token is invalid');
  }
  const candidateTokenIds = ATOMIC_CHOICE_CANDIDATES.map((choice) => {
    const tokens = processor.tokenizer.encode(choice, { add_special_tokens: false });
    if (!Array.isArray(tokens) || tokens.length !== 1 || tokens.some((token) =>
      !Number.isSafeInteger(Number(token)) || Number(token) < 0)) {
      throw new Error('local vision atomic choice tokenization is invalid');
    }
    return Number(tokens[0]);
  });
  if (new Set(candidateTokenIds).size !== ATOMIC_CHOICE_CANDIDATES.length ||
      candidateTokenIds.some((token, index) =>
        token !== ATOMIC_CHOICE_TOKEN_IDS[index]) ||
      candidateTokenIds.some((token, index) =>
        processor.tokenizer.decode([token], { skip_special_tokens: true }).trim() !==
          ATOMIC_CHOICE_CANDIDATES[index])) {
    throw new Error('local vision atomic choice tokens are not exact');
  }
  return { candidateTokenIds, eosTokenId };
}

function exactObject(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
}

function exactAtomicChoicePrompt(context) {
  let value;
  try { value = JSON.parse(typeof context === 'string' ? context : ''); }
  catch (_) { throw new Error('local vision atomic prompt is invalid'); }
  if (!exactObject(value, ['candidate_token_ids', 'candidates', 'prompt']) ||
      !Array.isArray(value.candidates) || value.candidates.length !== 3 ||
      value.candidates.some((candidate, index) =>
        candidate !== ATOMIC_CHOICE_CANDIDATES[index]) ||
      !exactObject(value.candidate_token_ids, ['A', 'B', 'U']) ||
      ATOMIC_CHOICE_CANDIDATES.some((candidate, index) =>
        !Array.isArray(value.candidate_token_ids[candidate]) ||
        value.candidate_token_ids[candidate].length !== 1 ||
        value.candidate_token_ids[candidate][0] !== ATOMIC_CHOICE_TOKEN_IDS[index]) ||
      typeof value.prompt !== 'string' || !value.prompt.trim() ||
      value.prompt.length > 2000 ||
      !value.prompt.includes('Return exactly one token') ||
      !value.prompt.includes('A, B, or U')) {
    throw new Error('local vision atomic prompt is invalid');
  }
  return `${value.prompt.trim()}\nANSWER:`;
}

function exactGeneratedAtomicChoice(output, atomicProcessor) {
  const rows = typeof output?.tolist === 'function' ? output.tolist() : output;
  if (!Array.isArray(rows) || rows.length !== 1 || !Array.isArray(rows[0]) ||
      !atomicProcessor.candidateTokenIds.includes(
        atomicProcessor.selectedTokenId)) {
    throw new Error('local vision atomic choice output is invalid');
  }
  const tokens = rows[0].map(Number);
  if (tokens.at(-1) !== atomicProcessor.eosTokenId ||
      tokens.at(-2) !== atomicProcessor.selectedTokenId) {
    throw new Error('local vision atomic choice output drifted');
  }
  return ATOMIC_CHOICE_CANDIDATES[atomicProcessor.candidateTokenIds.indexOf(
    atomicProcessor.selectedTokenId)];
}

function atomicChoiceResult(choice, processor) {
  if (!ATOMIC_CHOICE_CANDIDATES.includes(choice) ||
      !Array.isArray(processor.relativeLogitsMilli) ||
      processor.relativeLogitsMilli.length !== ATOMIC_CHOICE_CANDIDATES.length ||
      processor.relativeLogitsMilli.some((value) =>
        !Number.isSafeInteger(value) || value > 0 || value < -1_000_000_000)) {
    throw new Error('local vision atomic choice evidence is invalid');
  }
  const maximum = Math.max(...processor.relativeLogitsMilli);
  const weights = processor.relativeLogitsMilli.map((value) =>
    Math.exp((value - maximum) / 1000));
  const total = weights.reduce((sum, value) => sum + value, 0);
  if (!Number.isFinite(total) || total <= 0) {
    throw new Error('local vision atomic choice scores are invalid');
  }
  const rawPpm = weights.map((value) => value / total * 1_000_000);
  const scoresPpm = rawPpm.map(Math.floor);
  let remainder = 1_000_000 - scoresPpm.reduce((sum, value) => sum + value, 0);
  const order = rawPpm.map((value, index) => ({
    index, fraction: value - Math.floor(value),
  })).sort((left, right) => right.fraction - left.fraction || left.index - right.index);
  for (let index = 0; index < remainder; index += 1) {
    scoresPpm[order[index].index] += 1;
  }
  const selectedIndex = ATOMIC_CHOICE_CANDIDATES.indexOf(choice);
  const selectedScore = scoresPpm[selectedIndex];
  if (scoresPpm.some((score, index) =>
    index !== selectedIndex && score >= selectedScore)) {
    throw new Error('local vision atomic choice label is not uniquely highest');
  }
  return JSON.stringify({
    label: choice,
    scores_ppm: Object.fromEntries(ATOMIC_CHOICE_CANDIDATES.map(
      (candidate, index) => [candidate, scoresPpm[index]])),
  });
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
  const atomicChoiceMode = mode === 'artifact-assertion';
  if (atomicChoiceMode && (images.length < 1 || images.length > 3)) {
    throw new Error('local vision atomic choice requires one to three images');
  }
  const messages = [{ role: 'user', content: [
    ...frames.map(() => ({ type: 'image' })),
    { type: 'text', text: atomicChoiceMode ? exactAtomicChoicePrompt(context) :
      mode === 'artifact-quality' ? artifactPrompt(context) : [
      'These are chronological frames sampled from one attached video.',
      'Describe only visibly supported people, actions, objects, setting, products,',
      'readable on-screen text, camera framing, composition, and meaningful changes.',
      'Note uncertainty. Do not invent names or dialogue. Return one concise factual',
      'production report for a video editor.',
    ].join(' ') },
  ] }];
  const prompt = processor.apply_chat_template(messages, { add_generation_prompt: true });
  const inputs = await processor(prompt, frames, { do_image_splitting: false });
  let output;
  let atomicProcessor = null;
  if (atomicChoiceMode) {
    const { candidateTokenIds, eosTokenId } = exactAtomicChoiceCandidates(processor);
    const processorList = new LogitsProcessorList();
    atomicProcessor = new AtomicChoiceLogitsProcessor(candidateTokenIds, eosTokenId);
    processorList.push(atomicProcessor);
    output = await model.generate({
      ...inputs, do_sample: false, max_new_tokens: 2,
      logits_processor: processorList,
    });
  } else {
    output = await model.generate({
      ...inputs, do_sample: false, repetition_penalty: 1.05,
      max_new_tokens: mode === 'artifact-quality' ? 420 : 220,
    });
  }
  let result;
  if (atomicChoiceMode) {
    const choice = exactGeneratedAtomicChoice(output, atomicProcessor);
    result = atomicChoiceResult(choice, atomicProcessor);
  } else {
    const decoded = processor.batch_decode(output, { skip_special_tokens: true });
    result = cleanResult(decoded.at(-1));
  }
  if (!result) throw new Error('local vision model returned no description');
  return { result, runtime: runtimeEvidence(device, dtype) };
}

self.addEventListener('message', async (event) => {
  const id = event.data?.id;
  if (!Number.isSafeInteger(id) || id < 1) return;
  try {
    const completed = await describe(
      id, event.data.images, event.data.mode, event.data.context);
    self.postMessage({ id, status: 'complete', ...completed });
  } catch (error) {
    self.postMessage({ id, status: 'error',
      error: String(error?.message || error).slice(0, 1000) });
  }
});
