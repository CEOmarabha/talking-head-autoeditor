'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const {
  MODEL_FILES,
  MODEL_ID,
  MODEL_PACK_LOCK_SHA256,
  MODEL_PACK_RUNTIME_TOTAL_BYTES,
  MODEL_PACK_RUNTIME_TREE_SHA256,
  MODEL_PACK_TOTAL_BYTES,
  MODEL_PACK_TREE_SHA256,
  MODEL_PROTOCOL_ORIGIN,
  MODEL_REVISION,
  VISION_RUNTIME_LOCK_SHA256,
  VisionModelPackError,
  createVisionModelProtocolHandler,
  createVisionProtocolHandler,
  sourceVisionModelPackPath,
  validateVisionModelPack,
  validateVisionRuntimeAssets,
  visionModelRuntimeBindings,
} = require('../helper/lib/vision-model-pack');
const {
  stableFileMeasurement,
} = require('../helper/lib/runtime-capability-preflight');

const repoRoot = path.resolve(__dirname, '..', '..');
const packRoot = sourceVisionModelPackPath(repoRoot);
const pack = validateVisionModelPack(packRoot);

assert.equal(pack.lockSha256, MODEL_PACK_LOCK_SHA256);
assert.equal(pack.treeSha256, MODEL_PACK_TREE_SHA256);
assert.equal(pack.totalBytes, MODEL_PACK_TOTAL_BYTES);
assert.equal(pack.files.length, 9);
assert.equal(MODEL_FILES.reduce((total, item) => total + item.bytes, 0),
  MODEL_PACK_TOTAL_BYTES);
assert.match(MODEL_REVISION, /^[0-9a-f]{40}$/);

const bindings = visionModelRuntimeBindings(packRoot);
assert.equal(bindings.length, 1);
assert.equal(bindings[0].name, 'vision-model-pack-tree');
assert.equal(bindings[0].path, packRoot);
assert.ok(bindings.every(({ path: file }) => path.isAbsolute(file)));

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'vision-model-pack-test-'));
try {
  fs.writeFileSync(path.join(temporary, 'model-pack.lock.json'),
    fs.readFileSync(path.join(packRoot, 'model-pack.lock.json')));
  fs.appendFileSync(path.join(temporary, 'model-pack.lock.json'), ' ');
  assert.throws(() => validateVisionModelPack(temporary),
    (error) => error instanceof VisionModelPackError &&
      /lock identity drifted/.test(error.message));
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}

(async () => {
  const runtimeTree = await stableFileMeasurement(bindings[0].path);
  assert.deepEqual(runtimeTree, {
    sha256: MODEL_PACK_RUNTIME_TREE_SHA256,
    size_bytes: MODEL_PACK_RUNTIME_TOTAL_BYTES,
  });

  const visionRoot = path.join(repoRoot, 'desktop', 'helper', 'vision');
  const runtimeAssets = validateVisionRuntimeAssets(visionRoot);
  assert.equal(runtimeAssets.lockSha256, VISION_RUNTIME_LOCK_SHA256);
  assert.equal(runtimeAssets.files.size, 7);
  const runtimeLock = JSON.parse(fs.readFileSync(path.join(
    visionRoot, 'vision-runtime.lock.json'), 'utf8'));
  assert.equal(runtimeLock.schema, 'autoeditor-local-vision-runtime/v2');
  assert.deepEqual(runtimeLock.model_pack, {
    directory: path.basename(packRoot),
    file_count: MODEL_FILES.length,
    lock_sha256: MODEL_PACK_LOCK_SHA256,
    model_total_bytes: MODEL_PACK_TOTAL_BYTES,
    model_tree_sha256: MODEL_PACK_TREE_SHA256,
    runtime_total_bytes: MODEL_PACK_RUNTIME_TOTAL_BYTES,
    runtime_tree_sha256: MODEL_PACK_RUNTIME_TREE_SHA256,
    schema_version: 'autoeditor-local-vision-model-pack/v1',
  });
  const fileSha256 = (file) => crypto.createHash('sha256')
    .update(fs.readFileSync(file)).digest('hex');
  assert.equal(fileSha256(path.join(visionRoot, runtimeLock.vision_worker.entry)),
    runtimeLock.vision_worker.entry_sha256);
  assert.equal(fileSha256(path.join(visionRoot, runtimeLock.vision_worker.bundle)),
    runtimeLock.vision_worker.bundle_sha256);

  const workerSource = fs.readFileSync(path.join(
    visionRoot, runtimeLock.vision_worker.entry), 'utf8');
  const executableWorker = workerSource.replace(
    /^import\s*\{[\s\S]*?\}\s*from\s*'\.\/transformers\.web\.min\.js';\s*/,
    '',
  );
  const messages = [];
  const loads = [];
  const bridge = {};
  const processor = async () => ({ input_ids: { dims: [1, 5] } });
  processor.tokenizer = {
    eos_token_id: 49279,
    encode: (value) => value === 'YES' ? [13465] : [10921],
    decode: (tokens) => tokens[0] === 13465 ? 'YES' : 'NO',
  };
  processor.apply_chat_template = () => 'prompt';
  processor.batch_decode = () => ['{"schema":"autoeditor-artifact-review/v2"}'];
  const env = { backends: { onnx: { wasm: {} } } };
  vm.runInNewContext(executableWorker, {
    env,
    AutoProcessor: { from_pretrained: async (id, options) => {
      loads.push({ type: 'processor', id, options });
      return processor;
    } },
    AutoModelForVision2Seq: { from_pretrained: async (id, options) => {
      loads.push({ type: 'model', id, options });
      return { generate: async () => [] };
    } },
    LogitsProcessor: class {},
    LogitsProcessorList: class extends Array {
      push(value) { return super.push(value); }
    },
    load_image: async () => ({}),
    fetch: async (input) => ({ input }),
    navigator: {},
    self: {
      location: { href: 'file:///worker.js' },
      addEventListener: (name, callback) => { bridge[name] = callback; },
      postMessage: (message) => messages.push(message),
    },
    URL,
  });
  assert.equal(env.allowRemoteModels, false);
  assert.equal(env.allowLocalModels, true);
  assert.equal(env.localModelPath, MODEL_PROTOCOL_ORIGIN);
  assert.equal(env.useBrowserCache, false);
  await bridge.message({ data: {
    id: 7,
    images: ['data:image/jpeg;base64,AA=='],
    mode: 'artifact-quality',
    context: 'Return the production artifact review JSON.',
  } });
  assert.deepEqual(loads.map(({ type }) => type), ['processor', 'model']);
  assert.ok(loads.every(({ id, options }) => id === MODEL_ID &&
    options.revision === MODEL_REVISION && options.local_files_only === true));
  const complete = messages.find((message) => message.status === 'complete');
  assert.equal(complete.result, '{"schema":"autoeditor-artifact-review/v2"}');
  assert.deepEqual(Object.keys(complete.runtime).sort(), [
    'backend', 'model_dtype', 'model_id', 'model_pack_lock_sha256',
    'model_pack_tree_sha256', 'model_revision', 'remote_requests',
    'schema_version',
  ]);
  assert.equal(complete.runtime.schema_version,
    'autoeditor-local-vision-worker-runtime/v1');
  assert.equal(complete.runtime.model_pack_lock_sha256, MODEL_PACK_LOCK_SHA256);
  assert.equal(complete.runtime.model_pack_tree_sha256, MODEL_PACK_TREE_SHA256);
  assert.equal(complete.runtime.backend, 'wasm');
  assert.equal(complete.runtime.remote_requests, 0);
  messages.length = 0;
  processor.batch_decode = () => ['Assistant: YES'];
  await bridge.message({ data: {
    id: 8,
    images: ['data:image/jpeg;base64,AA=='],
    mode: 'artifact-quality-choice',
    context: 'Is the title fully visible and readable?',
  } });
  const choice = messages.find((message) => message.status === 'complete');
  assert.equal(choice.result, 'YES');
  assert.throws(() => env.fetch('https://huggingface.co/model.bin'),
    /blocked a non-local resource request/);

  const combined = createVisionProtocolHandler({
    modelPackRoot: packRoot, runtimeRoot: visionRoot,
  });
  const runtimeScript = await combined(new Request(
    'autoeditor-vision://runtime/ort-wasm-simd-threaded.mjs',
  ));
  assert.equal(runtimeScript.status, 200);
  assert.equal(runtimeScript.headers.get('content-type'), 'text/javascript');
  assert.equal((await runtimeScript.arrayBuffer()).byteLength,
    runtimeAssets.files.get('ort-wasm-simd-threaded.mjs').bytes);
  assert.equal((await combined(new Request(
    'autoeditor-vision://runtime/vision-worker.js',
  ))).status, 404);
  assert.equal((await combined(new Request(
    'https://huggingface.co/model.bin',
  ))).status, 404);

  const handler = createVisionModelProtocolHandler({ modelPackRoot: packRoot });
  const configFile = MODEL_FILES.find((item) => item.path === 'config.json');
  const config = await handler(new Request(
    `${MODEL_PROTOCOL_ORIGIN}${MODEL_ID}/config.json`,
  ));
  assert.equal(config.status, 200);
  assert.equal(config.headers.get('cache-control'), 'no-store');
  assert.equal(config.headers.get('content-length'), String(configFile.bytes));
  const configBytes = Buffer.from(await config.arrayBuffer());
  assert.equal(configBytes.length, configFile.bytes);
  assert.equal(crypto.createHash('sha256').update(configBytes).digest('hex'),
    configFile.sha256);
  assert.equal(JSON.parse(configBytes).model_type, 'smolvlm');

  const embed = MODEL_FILES.find((item) => item.path === 'onnx/embed_tokens_q4.onnx');
  const range = await handler(new Request(
    `${MODEL_PROTOCOL_ORIGIN}${MODEL_ID}/${embed.path}`,
    { headers: { Range: 'bytes=0-0' } },
  ));
  assert.equal(range.status, 206);
  assert.equal(range.headers.get('content-range'), `bytes 0-0/${embed.bytes}`);
  assert.equal((await range.arrayBuffer()).byteLength, 1);

  const unsupportedRange = await handler(new Request(
    `${MODEL_PROTOCOL_ORIGIN}${MODEL_ID}/${embed.path}`,
    { headers: { Range: 'bytes=1-2' } },
  ));
  assert.equal(unsupportedRange.status, 416);
  assert.equal((await handler(new Request(
    `${MODEL_PROTOCOL_ORIGIN}${MODEL_ID}/missing.json`,
  ))).status, 404);
  assert.equal((await handler(new Request(
    `${MODEL_PROTOCOL_ORIGIN}${MODEL_ID}/config.json?remote=true`,
  ))).status, 404);
  assert.equal((await handler(new Request(
    `https://huggingface.co/${MODEL_ID}/resolve/${MODEL_REVISION}/config.json`,
  ))).status, 404);
  console.log('local vision model-pack tests passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
