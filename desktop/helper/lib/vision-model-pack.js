'use strict';

// Closed local-only binding for the exact SmolVLM model used by the production
// artifact-review worker. The browser cache is never part of this trust path.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { Readable, Transform } = require('node:stream');

const MODEL_PACK_SCHEMA_VERSION = 'autoeditor-local-vision-model-pack/v1';
const MODEL_ID = 'HuggingFaceTB/SmolVLM2-256M-Video-Instruct';
const MODEL_REVISION = '067788b187b95ebe7b2e040b3e4299e342e5b8fd';
const MODEL_DTYPE = 'q4';
const MODEL_PACK_DIRECTORY = 'smolvlm2-067788b187b95ebe';
const MODEL_PACK_LOCK_FILE = 'model-pack.lock.json';
const MODEL_PACK_LOCK_SHA256 =
  'adc37855602e89d80260fbb8768aa2b87fb4b928f34d9765a4e6c267f554a1fa';
const MODEL_PACK_TREE_SHA256 =
  '5ab9f376a07e111ed08957c6db3847e4531b55589f6dbfe3fdb35619171bbc21';
const MODEL_PACK_TOTAL_BYTES = 267802713;
// runtime-capability-preflight hashes the complete directory, including the
// canonical lock file, as name\0size\0sha256\n records. Keep that executable
// binding separate from the model-only tree recorded inside the lock.
const MODEL_PACK_RUNTIME_TREE_SHA256 =
  'caad861f0486e619a6fe0ee4c96e57c39be2c7e1a9fdfe0a9dd9d25fcda56ad3';
const MODEL_PACK_RUNTIME_TOTAL_BYTES = 267806161;
const MODEL_PROTOCOL_ORIGIN = 'autoeditor-vision://model/';
const VISION_RUNTIME_LOCK_SHA256 =
  'ae5ce046c8250a18032576aefc8e935c88909c7daecea32d6f15f015b17461f0';
const SHA256 = /^[0-9a-f]{64}$/;
const VISION_RUNTIME_TYPES = Object.freeze({
  'ort-wasm-simd-threaded.asyncify.mjs': 'text/javascript',
  'ort-wasm-simd-threaded.asyncify.wasm': 'application/wasm',
  'ort-wasm-simd-threaded.mjs': 'text/javascript',
  'ort-wasm-simd-threaded.wasm': 'application/wasm',
});

const MODEL_FILES = Object.freeze([
  Object.freeze({
    name: 'vision-model-config', path: 'config.json', bytes: 3812,
    sha256: '756cb7d37d7659c9d5a71c563f9d2530f9dd674ab7e909d8d0dd5b1a2d3e8317',
  }),
  Object.freeze({
    name: 'vision-model-generation-config', path: 'generation_config.json',
    bytes: 136,
    sha256: '34835060c9f0f74d1acb456cc72ca32746d3843d9eb5f578f9cbffac1d2eb840',
  }),
  Object.freeze({
    name: 'vision-model-decoder-q4', path: 'onnx/decoder_model_merged_q4.onnx',
    bytes: 86894835,
    sha256: 'ce4021b8e2242cbd4caac06b259e1b15e085c6a4b900af40f1e0abec7a6c6df2',
  }),
  Object.freeze({
    name: 'vision-model-embed-q4', path: 'onnx/embed_tokens_q4.onnx',
    bytes: 113541438,
    sha256: '64f62db97ca38a44b5ed8a225b75dbede2d069c9afc76696d63b89300d5edcd2',
  }),
  Object.freeze({
    name: 'vision-model-encoder-q4', path: 'onnx/vision_encoder_q4.onnx',
    bytes: 63784944,
    sha256: '253d225bf96b6203118d16e57bb2890c2dc542dd989d484cb9541dc4d4ae719b',
  }),
  Object.freeze({
    name: 'vision-model-preprocessor-config', path: 'preprocessor_config.json',
    bytes: 599,
    sha256: '149e315d9410368e5491455bb06e0f763426e9e56cca731c13b24404a29b6374',
  }),
  Object.freeze({
    name: 'vision-model-processor-config', path: 'processor_config.json',
    bytes: 67,
    sha256: 'f3ad45028447b3562b4752be0d5916d6806c1ef589091a469608dcf0faa1737c',
  }),
  Object.freeze({
    name: 'vision-model-tokenizer', path: 'tokenizer.json', bytes: 3548256,
    sha256: '5ece781dc8d2b2f3e2f289ca0ae50b17cfc27dd27bfe7971bb8241e0b964331a',
  }),
  Object.freeze({
    name: 'vision-model-tokenizer-config', path: 'tokenizer_config.json',
    bytes: 28626,
    sha256: 'dd9ce2ab89a3dd881bd9378f1a79b943a064b9275a7e1706d5b7b47b68977913',
  }),
]);
class VisionModelPackError extends Error {
  constructor(message) {
    super(message);
    this.name = 'VisionModelPackError';
  }
}

function fail(message) {
  throw new VisionModelPackError(message);
}

function exactKeys(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join('\0') !== [...keys].sort().join('\0')) {
    fail(`${label} has invalid keys`);
  }
  return value;
}

function sha256Buffer(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function pathInside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative !== '' && !relative.startsWith(`..${path.sep}`) &&
    relative !== '..' && !path.isAbsolute(relative);
}

function stableFileIdentity(file, expectedBytes = null) {
  let descriptor;
  try { descriptor = fs.openSync(file, 'r'); }
  catch (_) { fail('vision model-pack file is unavailable'); }
  try {
    const before = fs.fstatSync(descriptor);
    if (!before.isFile() || before.size < 1 ||
        (expectedBytes !== null && before.size !== expectedBytes)) {
      fail('vision model-pack file has an invalid size');
    }
    const digest = crypto.createHash('sha256');
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    let offset = 0;
    while (offset < before.size) {
      const count = fs.readSync(
        descriptor, buffer, 0, Math.min(buffer.length, before.size - offset), offset,
      );
      if (count < 1) fail('vision model-pack file ended while measured');
      digest.update(buffer.subarray(0, count));
      offset += count;
    }
    const after = fs.fstatSync(descriptor);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs ||
        before.dev !== after.dev || before.ino !== after.ino) {
      fail('vision model-pack file changed while measured');
    }
    return { bytes: before.size, sha256: digest.digest('hex'), stat: before };
  } finally {
    fs.closeSync(descriptor);
  }
}

function sourceVisionModelPackPath(repoRoot) {
  return path.join(
    repoRoot, 'packaging', 'vision-model-packs', MODEL_PACK_DIRECTORY,
  );
}

function installedVisionModelPackPath(runtimeRoot) {
  return path.join(runtimeRoot, 'models', 'vision', MODEL_PACK_DIRECTORY);
}

function visionModelRuntimeBindings(modelPackRoot) {
  if (typeof modelPackRoot !== 'string' || !path.isAbsolute(modelPackRoot)) {
    fail('vision model-pack root is invalid');
  }
  return Object.freeze([Object.freeze({
    name: 'vision-model-pack-tree',
    path: modelPackRoot,
  })]);
}

function modelPackInventory(root) {
  const files = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) fail('vision model pack contains a symbolic link');
      if (entry.isDirectory()) visit(target);
      else if (entry.isFile()) files.push(path.relative(root, target).split(path.sep).join('/'));
      else fail('vision model pack contains an unsupported entry');
    }
  };
  visit(root);
  return files.sort();
}

function validateVisionModelPack(modelPackRoot) {
  if (typeof modelPackRoot !== 'string' || !path.isAbsolute(modelPackRoot) ||
      modelPackRoot.includes('\0')) fail('vision model-pack root is invalid');
  let root;
  try { root = fs.realpathSync.native(modelPackRoot); }
  catch (_) { fail('vision model pack is unavailable'); }
  const lockPath = path.join(root, MODEL_PACK_LOCK_FILE);
  let lockBytes;
  try { lockBytes = fs.readFileSync(lockPath); }
  catch (_) { fail('vision model-pack lock is unavailable'); }
  if (lockBytes.length < 2 || lockBytes.length > 32 * 1024 ||
      sha256Buffer(lockBytes) !== MODEL_PACK_LOCK_SHA256) {
    fail('vision model-pack lock identity drifted');
  }
  let lock;
  try { lock = JSON.parse(lockBytes); }
  catch (_) { fail('vision model-pack lock is invalid'); }
  exactKeys(lock, [
    'files', 'model', 'schema_version', 'total_bytes', 'tree_sha256',
  ], 'vision model-pack lock');
  exactKeys(lock.model, ['dtype', 'id', 'license', 'revision'], 'vision model');
  if (lock.schema_version !== MODEL_PACK_SCHEMA_VERSION ||
      lock.model.id !== MODEL_ID || lock.model.revision !== MODEL_REVISION ||
      lock.model.dtype !== MODEL_DTYPE || lock.model.license !== 'Apache-2.0' ||
      lock.total_bytes !== MODEL_PACK_TOTAL_BYTES ||
      lock.tree_sha256 !== MODEL_PACK_TREE_SHA256 ||
      !Array.isArray(lock.files) || lock.files.length !== MODEL_FILES.length) {
    fail('vision model-pack lock contract drifted');
  }
  const expectedInventory = [
    MODEL_PACK_LOCK_FILE,
    ...MODEL_FILES.map((item) => `${MODEL_ID}/${item.path}`),
  ].sort();
  if (modelPackInventory(root).join('\0') !== expectedInventory.join('\0')) {
    fail('vision model-pack inventory drifted');
  }
  const repository = path.join(root, ...MODEL_ID.split('/'));
  const validated = [];
  for (const [index, expected] of MODEL_FILES.entries()) {
    const item = exactKeys(lock.files[index], [
      'bytes', 'path', 'sha256', 'source_etag', 'source_url',
    ], `vision model-pack file ${index}`);
    if (item.path !== expected.path || item.bytes !== expected.bytes ||
        item.sha256 !== expected.sha256 || !SHA256.test(item.sha256) ||
        item.source_url !== `https://huggingface.co/${MODEL_ID}/resolve/${
          MODEL_REVISION}/${item.path}` ||
        typeof item.source_etag !== 'string' || !item.source_etag) {
      fail(`vision model-pack file lock drifted for ${expected.path}`);
    }
    const candidate = path.join(repository, ...item.path.split('/'));
    let real;
    try { real = fs.realpathSync.native(candidate); }
    catch (_) { fail(`vision model-pack file is missing for ${expected.path}`); }
    if (!pathInside(root, real) || fs.lstatSync(candidate).isSymbolicLink()) {
      fail(`vision model-pack path escaped for ${expected.path}`);
    }
    const measured = stableFileIdentity(real, expected.bytes);
    if (measured.sha256 !== expected.sha256) {
      fail(`vision model-pack file identity drifted for ${expected.path}`);
    }
    validated.push(Object.freeze({ ...expected, real }));
  }
  return Object.freeze({
    root,
    lockSha256: MODEL_PACK_LOCK_SHA256,
    treeSha256: MODEL_PACK_TREE_SHA256,
    totalBytes: MODEL_PACK_TOTAL_BYTES,
    files: Object.freeze(validated),
  });
}

function headers(contentType, length, extra = {}) {
  return {
    'Access-Control-Allow-Origin': '*',
    'Accept-Ranges': 'bytes',
    'Cache-Control': 'no-store',
    'Content-Length': String(length),
    'Content-Type': contentType,
    'Cross-Origin-Resource-Policy': 'cross-origin',
    ...extra,
  };
}

function notFound() {
  return new Response('Not found', {
    status: 404, headers: { 'Cache-Control': 'no-store' },
  });
}

function oneByteResponse(file, expected) {
  let descriptor;
  try { descriptor = fs.openSync(file, 'r'); }
  catch (_) { return notFound(); }
  try {
    const before = fs.fstatSync(descriptor);
    const byte = Buffer.alloc(1);
    if (before.size !== expected.bytes || fs.readSync(descriptor, byte, 0, 1, 0) !== 1) {
      return notFound();
    }
    const after = fs.fstatSync(descriptor);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs ||
        before.dev !== after.dev || before.ino !== after.ino) return notFound();
    return new Response(byte, { status: 206, headers: headers(
      expected.path.endsWith('.json') ? 'application/json' : 'application/octet-stream',
      1, { 'Content-Range': `bytes 0-0/${expected.bytes}` },
    ) });
  } finally {
    fs.closeSync(descriptor);
  }
}

function verifiedFileStream(file, expected) {
  const descriptor = fs.openSync(file, 'r');
  const before = fs.fstatSync(descriptor);
  if (!before.isFile() || before.size !== expected.bytes) {
    fs.closeSync(descriptor);
    fail('vision model file changed before protocol delivery');
  }
  const source = fs.createReadStream(file, { fd: descriptor, autoClose: false });
  const digest = crypto.createHash('sha256');
  let count = 0;
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    try { fs.closeSync(descriptor); } catch (_) { /* already closed */ }
  };
  const verifier = new Transform({
    transform(chunk, _encoding, callback) {
      count += chunk.length;
      digest.update(chunk);
      callback(null, chunk);
    },
    flush(callback) {
      try {
        const after = fs.fstatSync(descriptor);
        if (count !== expected.bytes || digest.digest('hex') !== expected.sha256 ||
            before.size !== after.size || before.mtimeMs !== after.mtimeMs ||
            before.dev !== after.dev || before.ino !== after.ino) {
          throw new VisionModelPackError('vision model changed during protocol delivery');
        }
        close();
        callback();
      } catch (error) {
        close();
        callback(error);
      }
    },
  });
  source.once('error', close);
  verifier.once('close', () => {
    source.destroy();
    close();
  });
  source.pipe(verifier);
  return Readable.toWeb(verifier);
}

function createVisionModelProtocolHandler({ modelPackRoot } = {}) {
  const pack = validateVisionModelPack(modelPackRoot);
  const byPath = new Map(pack.files.map((item) => [
    `${MODEL_ID}/${item.path}`, item,
  ]));
  return async function visionModelProtocolHandler(request) {
    try {
      const url = new URL(request.url);
      const relative = url.pathname.replace(/^\//, '');
      const expected = byPath.get(relative);
      if (request.method !== 'GET' || url.protocol !== 'autoeditor-vision:' ||
          url.hostname !== 'model' || url.search || url.hash || !expected ||
          relative.includes('\\') || relative.includes('%')) return notFound();
      const range = request.headers?.get?.('range') || '';
      if (range && range !== 'bytes=0-0') {
        return new Response('Unsupported range', {
          status: 416,
          headers: { 'Content-Range': `bytes */${expected.bytes}` },
        });
      }
      if (range === 'bytes=0-0') return oneByteResponse(expected.real, expected);
      const type = expected.path.endsWith('.json')
        ? 'application/json' : 'application/octet-stream';
      return new Response(verifiedFileStream(expected.real, expected), {
        headers: headers(type, expected.bytes),
      });
    } catch (_) {
      return notFound();
    }
  };
}

function validateVisionRuntimeAssets(runtimeRoot) {
  if (typeof runtimeRoot !== 'string' || !path.isAbsolute(runtimeRoot) ||
      runtimeRoot.includes('\0')) fail('vision runtime root is invalid');
  let root;
  try { root = fs.realpathSync.native(runtimeRoot); }
  catch (_) { fail('vision runtime is unavailable'); }
  const lockPath = path.join(root, 'vision-runtime.lock.json');
  let lockBytes;
  try { lockBytes = fs.readFileSync(lockPath); }
  catch (_) { fail('vision runtime lock is unavailable'); }
  if (sha256Buffer(lockBytes) !== VISION_RUNTIME_LOCK_SHA256) {
    fail('vision runtime lock identity drifted');
  }
  let lock;
  try { lock = JSON.parse(lockBytes); }
  catch (_) { fail('vision runtime lock is invalid'); }
  exactKeys(lock, [
    'model', 'model_pack', 'onnxruntime_web', 'schema', 'transformers_js',
    'vision_worker',
  ], 'vision runtime lock');
  exactKeys(lock.model, [
    'dtype', 'id', 'license', 'revision',
  ], 'vision runtime model');
  exactKeys(lock.model_pack, [
    'directory', 'file_count', 'lock_sha256', 'model_total_bytes',
    'model_tree_sha256', 'runtime_total_bytes', 'runtime_tree_sha256',
    'schema_version',
  ], 'vision runtime model pack');
  exactKeys(lock.onnxruntime_web, [
    'commit', 'files', 'license', 'version',
  ], 'vision ONNX runtime');
  exactKeys(lock.transformers_js, [
    'file', 'license', 'sha256', 'version',
  ], 'vision Transformers runtime');
  exactKeys(lock.vision_worker, [
    'builder', 'bundle', 'bundle_sha256', 'entry', 'entry_sha256',
  ], 'vision worker runtime');
  if (lock.schema !== 'autoeditor-local-vision-runtime/v2' ||
      lock.model.id !== MODEL_ID || lock.model.revision !== MODEL_REVISION ||
      lock.model.dtype !== MODEL_DTYPE || lock.model.license !== 'Apache-2.0' ||
      lock.model_pack.directory !== MODEL_PACK_DIRECTORY ||
      lock.model_pack.file_count !== MODEL_FILES.length ||
      lock.model_pack.lock_sha256 !== MODEL_PACK_LOCK_SHA256 ||
      lock.model_pack.model_tree_sha256 !== MODEL_PACK_TREE_SHA256 ||
      lock.model_pack.model_total_bytes !== MODEL_PACK_TOTAL_BYTES ||
      lock.model_pack.runtime_tree_sha256 !== MODEL_PACK_RUNTIME_TREE_SHA256 ||
      lock.model_pack.runtime_total_bytes !== MODEL_PACK_RUNTIME_TOTAL_BYTES ||
      lock.model_pack.schema_version !== MODEL_PACK_SCHEMA_VERSION ||
      lock.transformers_js.file !== 'transformers.web.min.js' ||
      lock.transformers_js.license !== 'Apache-2.0' ||
      lock.transformers_js.version !== '4.2.0' ||
      lock.vision_worker.entry !== 'vision-worker.js' ||
      lock.vision_worker.bundle !== 'vision-worker.bundle.js' ||
      lock.vision_worker.builder !== 'esbuild 0.28.1' ||
      lock.onnxruntime_web.license !== 'MIT' ||
      !lock.onnxruntime_web.files ||
      Object.keys(lock.onnxruntime_web.files).sort().join('\0') !==
        Object.keys(VISION_RUNTIME_TYPES).sort().join('\0')) {
    fail('vision runtime lock contract drifted');
  }
  const files = [
    [lock.transformers_js.file, lock.transformers_js.sha256],
    [lock.vision_worker.entry, lock.vision_worker.entry_sha256],
    [lock.vision_worker.bundle, lock.vision_worker.bundle_sha256],
    ...Object.entries(lock.onnxruntime_web.files),
  ];
  const validated = new Map();
  for (const [name, expectedSha256] of files) {
    if (typeof name !== 'string' || !name || name.includes('/') ||
        name.includes('\\') || !SHA256.test(expectedSha256 || '')) {
      fail('vision runtime file lock is invalid');
    }
    const candidate = path.join(root, name);
    let real;
    try { real = fs.realpathSync.native(candidate); }
    catch (_) { fail(`vision runtime file is missing for ${name}`); }
    if (!pathInside(root, real) || fs.lstatSync(candidate).isSymbolicLink()) {
      fail(`vision runtime path escaped for ${name}`);
    }
    const measured = stableFileIdentity(real);
    if (measured.bytes > 32 * 1024 * 1024 ||
        measured.sha256 !== expectedSha256) {
      fail(`vision runtime file identity drifted for ${name}`);
    }
    validated.set(name, Object.freeze({
      path: name, real, bytes: measured.bytes, sha256: measured.sha256,
    }));
  }
  return Object.freeze({ root, lockSha256: VISION_RUNTIME_LOCK_SHA256,
    files: validated });
}

function createVisionProtocolHandler({ modelPackRoot, runtimeRoot } = {}) {
  const model = createVisionModelProtocolHandler({ modelPackRoot });
  const runtime = validateVisionRuntimeAssets(runtimeRoot);
  return async function visionProtocolHandler(request) {
    try {
      const url = new URL(request.url);
      if (url.protocol !== 'autoeditor-vision:') return notFound();
      if (url.hostname === 'model') return model(request);
      const relative = url.pathname.replace(/^\//, '');
      const asset = runtime.files.get(relative);
      const type = VISION_RUNTIME_TYPES[relative];
      if (url.hostname !== 'runtime' || request.method !== 'GET' ||
          url.search || url.hash || !asset || !type || relative.includes('%')) {
        return notFound();
      }
      return new Response(verifiedFileStream(asset.real, asset), {
        headers: headers(type, asset.bytes),
      });
    } catch (_) {
      return notFound();
    }
  };
}

module.exports = Object.freeze({
  MODEL_DTYPE,
  MODEL_FILES,
  MODEL_ID,
  MODEL_PACK_DIRECTORY,
  MODEL_PACK_LOCK_FILE,
  MODEL_PACK_LOCK_SHA256,
  MODEL_PACK_RUNTIME_TOTAL_BYTES,
  MODEL_PACK_RUNTIME_TREE_SHA256,
  MODEL_PACK_SCHEMA_VERSION,
  MODEL_PACK_TOTAL_BYTES,
  MODEL_PACK_TREE_SHA256,
  MODEL_PROTOCOL_ORIGIN,
  MODEL_REVISION,
  VISION_RUNTIME_LOCK_SHA256,
  VISION_RUNTIME_TYPES,
  VisionModelPackError,
  createVisionModelProtocolHandler,
  createVisionProtocolHandler,
  installedVisionModelPackPath,
  sourceVisionModelPackPath,
  validateVisionModelPack,
  validateVisionRuntimeAssets,
  visionModelRuntimeBindings,
});
