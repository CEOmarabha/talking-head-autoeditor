#!/usr/bin/env node
'use strict';

const fs = require('fs');
const crypto = require('crypto');
const {
  CopyObjectCommand,
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} = require('@aws-sdk/client-s3');
const { Upload } = require('@aws-sdk/lib-storage');

function option(name, required = true) {
  const index = process.argv.indexOf(`--${name}`);
  const value = index >= 0 ? process.argv[index + 1] : '';
  if (required && !value) throw new Error(`missing --${name}`);
  return value;
}

function client() {
  const account = process.env.R2_ACCOUNT_ID;
  if (!account) throw new Error('R2_ACCOUNT_ID is required');
  return new S3Client({
    region: 'auto',
    endpoint: `https://${account}.r2.cloudflarestorage.com`,
    forcePathStyle: true,
  });
}

async function digest(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

async function digestBody(body) {
  const hash = crypto.createHash('sha256');
  let bytes = 0;
  for await (const chunk of body) {
    hash.update(chunk);
    bytes += chunk.length;
  }
  return { bytes, sha256: hash.digest('hex') };
}

async function head(s3, bucket, key) {
  try {
    const result = await s3.send(new HeadObjectCommand({
      Bucket: bucket, Key: key,
    }));
    return {
      exists: true,
      bytes: Number(result.ContentLength),
      sha256: result.Metadata?.sha256 || '',
      etag: result.ETag || '',
    };
  } catch (error) {
    const status = error?.$metadata?.httpStatusCode;
    if (status === 404 || error?.name === 'NotFound' ||
        error?.name === 'NoSuchKey') {
      return { exists: false };
    }
    throw error;
  }
}

function verify(record, bytes, sha256, label) {
  if (!record.exists || record.bytes !== Number(bytes) ||
      record.sha256 !== sha256) {
    throw new Error(`${label} size or sha256 metadata does not match`);
  }
}

async function verifyRemoteContent(s3, bucket, key, bytes, sha256, label) {
  const result = await s3.send(new GetObjectCommand({
    Bucket: bucket,
    Key: key,
  }));
  const expectedBytes = Number(bytes);
  if (Number(result.ContentLength) !== expectedBytes ||
      result.Metadata?.sha256 !== sha256 || !result.ETag) {
    throw new Error(`${label} receipt metadata does not match`);
  }
  const actual = await digestBody(result.Body);
  if (actual.bytes !== expectedBytes || actual.sha256 !== sha256) {
    throw new Error(`${label} streamed bytes do not match SHA-256 receipt`);
  }
  return { etag: result.ETag };
}

async function upload(s3) {
  const file = option('file');
  const bucket = option('bucket');
  const key = option('key');
  const contentType = option('content-type');
  const expectedSha = option('sha256');
  const bytes = fs.statSync(file).size;
  const actualSha = await digest(file);
  if (actualSha !== expectedSha) throw new Error('local sha256 does not match receipt');
  const existing = await head(s3, bucket, key);
  if (existing.exists) {
    verify(existing, bytes, expectedSha, 'existing content-addressed object');
    return { reused: true, bytes, sha256: expectedSha };
  }
  const transfer = new Upload({
    client: s3,
    params: {
      Bucket: bucket,
      Key: key,
      Body: fs.createReadStream(file),
      ContentType: contentType,
      Metadata: { sha256: expectedSha },
    },
    queueSize: 4,
    partSize: 64 * 1024 * 1024,
    leavePartsOnError: false,
  });
  await transfer.done();
  verify(await head(s3, bucket, key), bytes, expectedSha, 'uploaded object');
  return { reused: false, bytes, sha256: expectedSha };
}

async function copy(s3) {
  const sourceBucket = option('source-bucket');
  const destinationBucket = option('destination-bucket');
  const key = option('key');
  const bytes = Number(option('bytes'));
  const sha256 = option('sha256');
  // Candidate metadata is self-declared. Hash the remote bytes and bind the
  // copy to the exact ETag that was read so an overwrite cannot race in.
  const source = await verifyRemoteContent(
    s3, sourceBucket, key, bytes, sha256, 'candidate object');
  const existing = await head(s3, destinationBucket, key);
  if (existing.exists) {
    verify(existing, bytes, sha256, 'existing release object');
    await verifyRemoteContent(
      s3, destinationBucket, key, bytes, sha256, 'existing release object');
    return { reused: true, bytes, sha256 };
  }
  await s3.send(new CopyObjectCommand({
    Bucket: destinationBucket,
    Key: key,
    CopySource: `${sourceBucket}/${key}`,
    CopySourceIfMatch: source.etag,
    MetadataDirective: 'COPY',
  }));
  await verifyRemoteContent(
    s3, destinationBucket, key, bytes, sha256, 'promoted release object');
  return { reused: false, bytes, sha256 };
}

async function put(s3) {
  const file = option('file');
  const bucket = option('bucket');
  const key = option('key');
  const contentType = option('content-type');
  const expectedSha = option('sha256', false);
  const ifMatch = option('if-match', false);
  const ifNoneMatch = option('if-none-match', false);
  if (ifMatch && ifNoneMatch) throw new Error('choose one conditional write mode');
  const bytes = fs.statSync(file).size;
  const actualSha = await digest(file);
  if (expectedSha && actualSha !== expectedSha) {
    throw new Error('local sha256 does not match receipt');
  }
  const storedSha = expectedSha || actualSha;
  const request = {
    Bucket: bucket,
    Key: key,
    Body: fs.createReadStream(file),
    ContentType: contentType,
    Metadata: { sha256: storedSha },
  };
  if (ifMatch) request.IfMatch = ifMatch;
  if (ifNoneMatch) request.IfNoneMatch = ifNoneMatch;
  try {
    await s3.send(new PutObjectCommand(request));
  } catch (error) {
    if (![409, 412].includes(error?.$metadata?.httpStatusCode)) throw error;
    // A retried workflow may lose the condition race to the exact same
    // pointer. Only byte-identical content is an idempotent success.
    let current;
    try {
      current = await s3.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
    } catch (_) {
      throw new Error('conditional pointer write lost and current object vanished');
    }
    const currentBody = await current.Body.transformToByteArray();
    const localBody = fs.readFileSync(file);
    if (!Buffer.from(currentBody).equals(localBody)) {
      throw new Error('conditional pointer write blocked a stale release');
    }
    verify(await head(s3, bucket, key), bytes, storedSha,
      'idempotent conditional object');
    return { reused: true, bytes, sha256: storedSha };
  }
  verify(await head(s3, bucket, key), bytes, storedSha, 'stored object');
  return { bytes, sha256: storedSha };
}

async function get(s3) {
  const bucket = option('bucket');
  const key = option('key');
  const etagOutput = option('etag-output', false);
  try {
    const result = await s3.send(new GetObjectCommand({
      Bucket: bucket, Key: key,
    }));
    if (etagOutput) fs.writeFileSync(etagOutput, result.ETag || '');
    process.stdout.write(await result.Body.transformToString());
    return null;
  } catch (error) {
    const status = error?.$metadata?.httpStatusCode;
    if (status === 404 || error?.name === 'NoSuchKey') process.exit(4);
    throw error;
  }
}

async function main() {
  const command = process.argv[2];
  const s3 = client();
  let result;
  if (command === 'upload') result = await upload(s3);
  else if (command === 'copy') result = await copy(s3);
  else if (command === 'put') result = await put(s3);
  else if (command === 'get') result = await get(s3);
  else throw new Error(`unknown command: ${command}`);
  if (result) console.log(JSON.stringify(result));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`R2 release operation failed: ${error.message}`);
    process.exit(1);
  });
}

module.exports = { copy, digestBody, put, verifyRemoteContent };
