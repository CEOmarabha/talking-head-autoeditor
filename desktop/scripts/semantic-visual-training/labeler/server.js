'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { LABEL_RECORD_SCHEMA } = require('../contract');
const { sha256File } = require('../labels');

function argument(name, fallback = '') {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || '') : fallback;
}

function fail(message) {
  throw new Error(message);
}

function workspaceRoot() {
  const root = path.resolve(argument('--workspace',
    path.join(process.cwd(), '.semantic-visual-work')));
  if (!path.isAbsolute(root) || root.includes('\0')) fail('workspace is invalid');
  fs.mkdirSync(path.join(root, 'inbox'), { recursive: true });
  fs.mkdirSync(path.join(root, 'labels'), { recursive: true });
  fs.mkdirSync(path.join(root, 'annotations'), { recursive: true });
  return root;
}

function listInbox(root) {
  const inbox = path.join(root, 'inbox');
  return fs.readdirSync(inbox).filter((name) =>
    /\.(jpe?g|png|webp)$/i.test(name)).map((name) => {
    const file = path.join(inbox, name);
    const hashed = sha256File(file);
    return {
      relative_path: `inbox/${name}`,
      file,
      sha256: hashed.sha256,
      size_bytes: hashed.bytes,
    };
  });
}

function saveAnnotation(root, payload) {
  if (!payload || typeof payload !== 'object') fail('payload is invalid');
  if (!payload.asset?.sha256 || !payload.annotator_id || !payload.assertion_class) {
    fail('annotation is incomplete');
  }
  fs.mkdirSync(path.join(root, 'annotations'), { recursive: true });
  const stamp = crypto.randomBytes(8).toString('hex');
  const record = {
    schema_version: LABEL_RECORD_SCHEMA,
    recorded_at: new Date().toISOString(),
    annotator_id: String(payload.annotator_id),
    role: payload.role === 'adjudicator' ? 'adjudicator' : 'annotator',
    assertion_class: payload.assertion_class,
    split: payload.split,
    source_id: payload.source_id,
    template_id: payload.template_id,
    label: payload.label,
    assertion: payload.assertion,
    asset: payload.asset,
    gold_complete: false,
    note: 'This is a raw annotation. A gold label record is written only after the required annotators and distinct adjudicator are present.',
  };
  const file = path.join(root, 'annotations', `${payload.asset.sha256}.${stamp}.json`);
  fs.writeFileSync(file, `${JSON.stringify(record, null, 2)}\n`, { flag: 'wx' });
  return record;
}

function main() {
  const root = workspaceRoot();
  const html = fs.readFileSync(path.join(__dirname, 'index.html'));
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1');
    if (request.method === 'GET' && url.pathname === '/') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      response.end(html);
      return;
    }
    if (request.method === 'GET' && url.pathname === '/api/next') {
      const inbox = listInbox(root);
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({
        asset: inbox[0] || null,
        preview: inbox[0] ? `/asset/${inbox[0].sha256}` : '',
        remaining: inbox.length,
      }));
      return;
    }
    if (request.method === 'GET' && url.pathname.startsWith('/asset/')) {
      const wanted = url.pathname.slice('/asset/'.length);
      const asset = listInbox(root).find((item) => item.sha256 === wanted);
      if (!asset) {
        response.writeHead(404);
        response.end('missing');
        return;
      }
      response.writeHead(200, { 'content-type': 'image/jpeg' });
      response.end(fs.readFileSync(asset.file));
      return;
    }
    if (request.method === 'POST' && url.pathname === '/api/label') {
      const chunks = [];
      request.on('data', (chunk) => chunks.push(chunk));
      request.on('end', () => {
        try {
          const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          const record = saveAnnotation(root, payload);
          response.writeHead(200, { 'content-type': 'application/json' });
          response.end(JSON.stringify({
            message: `saved ${record.role} annotation; gold record is not fabricated`,
            record,
          }));
        } catch (error) {
          response.writeHead(400, { 'content-type': 'application/json' });
          response.end(JSON.stringify({ message: error.message }));
        }
      });
      return;
    }
    response.writeHead(404);
    response.end('not found');
  });
  server.listen(8765, '127.0.0.1', () => {
    process.stdout.write('semantic visual labeler on http://127.0.0.1:8765\n');
  });
}

if (require.main === module) main();

module.exports = { listInbox, saveAnnotation };
