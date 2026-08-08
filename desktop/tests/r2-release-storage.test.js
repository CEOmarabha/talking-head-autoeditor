'use strict';

const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Readable } = require('stream');
const { copy, put } = require('../scripts/r2-release-storage');

const sha256 = (body) => crypto.createHash('sha256').update(body).digest('hex');

function object(body, digest, etag = '"candidate-etag"') {
  return {
    Body: Readable.from([body]),
    ContentLength: body.length,
    Metadata: { sha256: digest },
    ETag: etag,
  };
}

function argv(bytes, digest) {
  process.argv = ['node', 'r2-release-storage.js', 'copy',
    '--source-bucket', 'candidate', '--destination-bucket', 'live',
    '--key', 'dist/helper/object.exe', '--bytes', String(bytes),
    '--sha256', digest];
}

function putArgv(file, digest, condition = ['--if-none-match', '*']) {
  process.argv = ['node', 'r2-release-storage.js', 'put',
    '--file', file, '--bucket', 'live', '--key', 'dist/helper/current.json',
    '--content-type', 'application/json', '--sha256', digest, ...condition];
}

function headRecord(body, digest) {
  return {
    ContentLength: body.length,
    Metadata: { sha256: digest },
    ETag: '"pointer-etag"',
  };
}

function pointerObject(body) {
  return {
    Body: {
      transformToByteArray: async () => body,
    },
  };
}

function conditionalFailure(status) {
  const error = new Error(`conditional write failed with ${status}`);
  error.$metadata = { httpStatusCode: status };
  return error;
}

async function readRequestBody(command) {
  const chunks = [];
  for await (const chunk of command.input.Body) chunks.push(chunk);
  return Buffer.concat(chunks);
}

(async () => {
  const originalArgv = process.argv;
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'r2-storage-test-'));
  const pointer = Buffer.from('{"version":"1.2.3"}\n');
  const pointerDigest = sha256(pointer);
  const pointerFile = path.join(tempDir, 'current.json');
  fs.writeFileSync(pointerFile, pointer);

  const trusted = Buffer.from('trusted-installer-bytes');
  const digest = sha256(trusted);
  const spoofed = Buffer.from('malware-installer-bytes');
  assert.strictEqual(spoofed.length, trusted.length);
  argv(trusted.length, digest);
  await assert.rejects(() => copy({
    send: async (command) => {
      if (command.constructor.name === 'GetObjectCommand') {
        return object(spoofed, digest);
      }
      throw new Error(`unexpected command ${command.constructor.name}`);
    },
  }), /streamed bytes do not match SHA-256 receipt/);

  let copied = false;
  let copyCondition = '';
  argv(trusted.length, digest);
  const result = await copy({
    send: async (command) => {
      const name = command.constructor.name;
      const input = command.input;
      if (name === 'GetObjectCommand' && input.Bucket === 'candidate') {
        return object(trusted, digest);
      }
      if (name === 'HeadObjectCommand' && input.Bucket === 'live') {
        if (!copied) {
          const error = new Error('missing');
          error.name = 'NoSuchKey';
          error.$metadata = { httpStatusCode: 404 };
          throw error;
        }
      }
      if (name === 'CopyObjectCommand') {
        copyCondition = input.CopySourceIfMatch;
        copied = true;
        return {};
      }
      if (name === 'GetObjectCommand' && input.Bucket === 'live' && copied) {
        return object(trusted, digest, '"live-etag"');
      }
      throw new Error(`unexpected command ${name}`);
    },
  });
  assert.strictEqual(copyCondition, '"candidate-etag"');
  assert.deepStrictEqual(result, { reused: false, bytes: trusted.length,
    sha256: digest });

  let putCalls = 0;
  putArgv(pointerFile, pointerDigest);
  const stored = await put({
    send: async (command) => {
      const name = command.constructor.name;
      if (name === 'PutObjectCommand') {
        putCalls += 1;
        assert.strictEqual(command.input.IfNoneMatch, '*');
        assert.strictEqual(command.input.IfMatch, undefined);
        assert.deepStrictEqual(command.input.Metadata, { sha256: pointerDigest });
        assert.deepStrictEqual(await readRequestBody(command), pointer);
        return {};
      }
      if (name === 'HeadObjectCommand') {
        return headRecord(pointer, pointerDigest);
      }
      throw new Error(`unexpected command ${name}`);
    },
  });
  assert.strictEqual(putCalls, 1);
  assert.deepStrictEqual(stored, {
    bytes: pointer.length,
    sha256: pointerDigest,
  });

  putArgv(pointerFile, pointerDigest, ['--if-match', '"previous-etag"']);
  const replaced = await put({
    send: async (command) => {
      const name = command.constructor.name;
      if (name === 'PutObjectCommand') {
        assert.strictEqual(command.input.IfMatch, '"previous-etag"');
        assert.strictEqual(command.input.IfNoneMatch, undefined);
        assert.deepStrictEqual(await readRequestBody(command), pointer);
        return {};
      }
      if (name === 'HeadObjectCommand') {
        return headRecord(pointer, pointerDigest);
      }
      throw new Error(`unexpected command ${name}`);
    },
  });
  assert.deepStrictEqual(replaced, {
    bytes: pointer.length,
    sha256: pointerDigest,
  });

  for (const status of [409, 412]) {
    putArgv(pointerFile, pointerDigest);
    const reused = await put({
      send: async (command) => {
        const name = command.constructor.name;
        if (name === 'PutObjectCommand') {
          await readRequestBody(command);
          throw conditionalFailure(status);
        }
        if (name === 'GetObjectCommand') return pointerObject(pointer);
        if (name === 'HeadObjectCommand') {
          return headRecord(pointer, pointerDigest);
        }
        throw new Error(`unexpected command ${name}`);
      },
    });
    assert.deepStrictEqual(reused, {
      reused: true,
      bytes: pointer.length,
      sha256: pointerDigest,
    });
  }

  const stalePointer = Buffer.from('{"version":"9.9.9"}\n');
  assert.strictEqual(stalePointer.length, pointer.length);
  for (const status of [409, 412]) {
    putArgv(pointerFile, pointerDigest);
    await assert.rejects(() => put({
      send: async (command) => {
        const name = command.constructor.name;
        if (name === 'PutObjectCommand') {
          await readRequestBody(command);
          throw conditionalFailure(status);
        }
        if (name === 'GetObjectCommand') return pointerObject(stalePointer);
        throw new Error(`unexpected command ${name}`);
      },
    }), /conditional pointer write blocked a stale release/);
  }

  putArgv(pointerFile, pointerDigest);
  await assert.rejects(() => put({
    send: async (command) => {
      const name = command.constructor.name;
      if (name === 'PutObjectCommand') {
        await readRequestBody(command);
        throw conditionalFailure(412);
      }
      if (name === 'GetObjectCommand') {
        const error = new Error('missing');
        error.name = 'NoSuchKey';
        error.$metadata = { httpStatusCode: 404 };
        throw error;
      }
      throw new Error(`unexpected command ${name}`);
    },
  }), /conditional pointer write lost and current object vanished/);

  putArgv(pointerFile, pointerDigest);
  await assert.rejects(() => put({
    send: async (command) => {
      const name = command.constructor.name;
      if (name === 'PutObjectCommand') {
        await readRequestBody(command);
        throw conditionalFailure(409);
      }
      if (name === 'GetObjectCommand') return pointerObject(pointer);
      if (name === 'HeadObjectCommand') {
        return headRecord(pointer, sha256(Buffer.from('wrong')));
      }
      throw new Error(`unexpected command ${name}`);
    },
  }), /idempotent conditional object size or sha256 metadata does not match/);

  process.argv = originalArgv;
  fs.rmSync(tempDir, { recursive: true, force: true });
  console.log('r2 release storage contracts ok');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
