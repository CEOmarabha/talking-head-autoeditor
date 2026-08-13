'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..', 'scripts', 'vision-capability-electron');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const main = fs.readFileSync(path.join(root, manifest.main), 'utf8');
const preload = fs.readFileSync(path.join(root, 'preload.js'), 'utf8');
const renderer = fs.readFileSync(path.join(root, 'renderer.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const { writeStdoutSync } = require(path.join(root, 'safe-output'));

new vm.Script(main, { filename: 'vision-capability-electron/main.js' });
new vm.Script(preload, { filename: 'vision-capability-electron/preload.js' });
new vm.Script(renderer, { filename: 'vision-capability-electron/renderer.js' });

assert.equal(manifest.private, true);
assert.ok(main.includes('createVisionProtocolHandler'));
assert.ok(main.includes('createVisualQualityFixtures'));
assert.ok(main.includes('runVisualQualityRuntimeProbe'));
assert.ok(main.includes("urls: ['http://*/*', 'https://*/*']"));
assert.ok(main.includes('remoteRequests += 1'));
assert.ok(main.includes('remoteRequests !== 0'));
assert.ok(main.includes("new Set(iterations.map(({ result_sha256 })"));
assert.ok(main.includes('defective_captions_false'));
assert.ok(main.includes('defective_production_design_false'));
assert.ok(main.includes('positive_targets_exact'));
assert.ok(main.includes('defective_targets_exact'));
assert.ok(main.includes('semanticEvidenceProjection'));
assert.ok(main.includes('semantic_evidence: first.semantic_evidence'));
assert.ok(main.includes('writeStdoutSync(bytes)'));
assert.ok(!main.includes('process.stdout.write'));
assert.ok(main.includes('function authoritativeOutputPath()'));
assert.match(main,
  /failureOutputPath = authoritativeOutputPath\(\);\s*const configuration = options\(\);/,
  'an --output path must be bound before later configuration can throw');
assert.match(main,
  /if \(file\) \{\s*fs\.writeFileSync\(file, bytes,[\s\S]*?\s+return;\s*\}/,
  'an authoritative output file must not also depend on a supervisor stdout pipe');
assert.ok(!main.includes('mock'));
assert.ok(!main.includes('fake'));
assert.ok(!main.includes('AUTOEDITOR_VISION_RESULT'));
assert.ok(renderer.includes('../../helper/vision/vision-worker.bundle.js'));
assert.ok(renderer.includes("mode: 'artifact-assertion'"));
assert.ok(renderer.includes('context: JSON.stringify(request.model_request)'));
assert.ok(renderer.includes('validModelRequest(request.model_request)'));
assert.ok(main.includes('requestChoice'));
assert.ok(main.includes('mode, model_request: modelRequest'));
assert.ok(main.includes("crypto.createHash('sha256').update(bytes).digest('hex')"));
assert.ok(main.includes('readJpeg(framePath, frameSha256)'));
assert.ok(renderer.includes('window.autoeditorVisionProbe.result(value)'));
assert.ok(preload.includes('contextBridge.exposeInMainWorld'));
assert.ok(html.includes("connect-src autoeditor-vision: data: blob:"));
assert.ok(html.includes("script-src 'self' 'wasm-unsafe-eval'"));

const chunks = [];
assert.equal(writeStdoutSync(Buffer.from('receipt'), {
  descriptor: 7,
  writeSync(fd, bytes, offset, length) {
    assert.equal(fd, 7);
    const written = Math.min(length, 3);
    chunks.push(bytes.subarray(offset, offset + written));
    return written;
  },
}), true);
assert.equal(Buffer.concat(chunks).toString('utf8'), 'receipt');
for (const code of ['EPIPE', 'EBADF', 'EOF', 'ERR_STREAM_DESTROYED']) {
  assert.equal(writeStdoutSync(Buffer.from('receipt'), {
    descriptor: 7,
    writeSync() {
      const error = new Error(`closed ${code}`);
      error.code = code;
      throw error;
    },
  }), false, `${code} is a closed delivery channel, not a crash`);
}
assert.throws(() => writeStdoutSync(Buffer.from('receipt'), {
  descriptor: 7,
  writeSync() {
    const error = new Error('unexpected output failure');
    error.code = 'EIO';
    throw error;
  },
}), /unexpected output failure/);
assert.equal(writeStdoutSync(Buffer.from('receipt'), {
  descriptor: -1,
  writeSync() { throw new Error('invalid fd must not be used'); },
}), false);
assert.equal(writeStdoutSync(Buffer.from('receipt'), {
  descriptor: Number.NaN,
  writeSync() { throw new Error('missing fd must not be used'); },
}), false);

console.log('visual-quality Electron harness source contracts passed');
