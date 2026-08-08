/** Private hosted AutoEditor: one Worker = site + API + queue.
 *
 * Security posture (full threat model in docs/WEB_SECURITY.md):
 *  - invite-only sessions, httpOnly cookies, per-user row scoping on every
 *    query;
 *  - DeepSeek keys AES-GCM wrapped immediately on receipt, ciphertext in
 *    D1, NEVER logged, and never stored in job payloads or URLs;
 *  - each personal Helper authenticates with its own user-scoped token and
 *    receives only that user's plaintext key over TLS for a claimed job;
 *    the optional global owner daemon receives ciphertext and holds the KEK;
 *  - media is private in R2; all reads stream through authenticated
 *    routes; nothing is public.
 */

const JSONH = { 'content-type': 'application/json' };
const enc = new TextEncoder();
const UPLOAD_PART_SIZE = 10 * 1024 * 1024;
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024;
const UPLOAD_COMPLETION_LEASE_MS = 2 * 60 * 1000;
const JOB_LEASE_MS = 2 * 60 * 1000;
const JOB_MAX_ATTEMPTS = 3;
const DELETE_LEASE_MS = 30 * 60 * 1000;
const OUTPUT_PART_SIZE = 64 * 1024 * 1024;
const MAX_OUTPUT_PARTS = 8192;
const MAX_OUTPUT_BYTES = OUTPUT_PART_SIZE * MAX_OUTPUT_PARTS;
const OUTPUT_COMPLETION_LEASE_MS = 2 * 60 * 1000;
const MAX_QA_BYTES = 4 * 1024 * 1024;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;

// ------------------------------------------------------------- helpers
const uid = () => crypto.randomUUID().replaceAll('-', '').slice(0, 20);
const now = () => Date.now();
async function sha256Hex(value) {
  const bytes = value instanceof ArrayBuffer ? value
    : ArrayBuffer.isView(value)
      ? value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength)
      : enc.encode(value);
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');
}
async function streamSha256Hex(stream) {
  const digestStream = new crypto.DigestStream('SHA-256');
  await stream.pipeTo(digestStream);
  return [...new Uint8Array(await digestStream.digest)]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');
}
function checksumHex(value) {
  if (typeof value === 'string') return value.toLowerCase();
  if (value instanceof ArrayBuffer) {
    return [...new Uint8Array(value)]
      .map((byte) => byte.toString(16).padStart(2, '0')).join('');
  }
  if (ArrayBuffer.isView(value)) {
    return [...new Uint8Array(value.buffer, value.byteOffset, value.byteLength)]
      .map((byte) => byte.toString(16).padStart(2, '0')).join('');
  }
  return '';
}
// Baseline hardening applied to EVERY worker response (API, media,
// installer), not just static assets. secureSiteResponse adds the full
// site CSP on top of this for HTML.
const BASE_SECURITY_HEADERS = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'no-referrer',
  'strict-transport-security': 'max-age=31536000; includeSubDomains',
};
function j(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status, headers: { ...JSONH, 'cache-control': 'no-store',
      ...BASE_SECURITY_HEADERS, ...headers },
  });
}
function bad(msg, status = 400) { return j({ error: msg }, status); }

function exactJson(jsonText, status = 200) {
  return new Response(jsonText, { status, headers: {
    ...JSONH, 'cache-control': 'no-store', ...BASE_SECURITY_HEADERS,
  } });
}

function secureSiteResponse(response) {
  const headers = new Headers(response.headers);
  headers.set('content-security-policy', "default-src 'self'; " +
    "script-src 'self'; style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; " +
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
  headers.set('x-content-type-options', 'nosniff');
  headers.set('referrer-policy', 'no-referrer');
  headers.set('permissions-policy',
    'camera=(), microphone=(), geolocation=(), payment=()');
  headers.set('cross-origin-opener-policy', 'same-origin');
  headers.set('strict-transport-security', 'max-age=31536000; includeSubDomains');
  return new Response(response.body, { status: response.status,
    statusText: response.statusText, headers });
}

async function wrapKey(env, plaintext) {
  const material = await crypto.subtle.importKey(
    'raw', await crypto.subtle.digest('SHA-256',
      enc.encode(env.KEY_WRAP_SECRET)),
    'AES-GCM', false, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv },
    material, enc.encode(plaintext));
  const b64 = (b) => btoa(String.fromCharCode(...new Uint8Array(b)));
  return { ct: b64(ct), iv: b64(iv.buffer) };
}

// ------------------------------------------------------------- TOTP (OTP)
const B32A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
function b32encode(bytes) {
  let bits = 0, val = 0, out = '';
  for (const b of bytes) {
    val = (val << 8) | b; bits += 8;
    while (bits >= 5) { out += B32A[(val >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits) out += B32A[(val << (5 - bits)) & 31];
  return out;
}
function b32decode(s) {
  let bits = 0, val = 0; const out = [];
  for (const c of s.replace(/=+$/, '').toUpperCase()) {
    const i = B32A.indexOf(c);
    if (i < 0) continue;
    val = (val << 5) | i; bits += 5;
    if (bits >= 8) { out.push((val >>> (bits - 8)) & 255); bits -= 8; }
  }
  return new Uint8Array(out);
}
async function totpAt(secretB32, counter) {
  const key = await crypto.subtle.importKey('raw', b32decode(secretB32),
    { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']);
  const buf = new ArrayBuffer(8);
  new DataView(buf).setUint32(4, counter);
  const h = new Uint8Array(await crypto.subtle.sign('HMAC', key, buf));
  const o = h[19] & 15;
  const code = (((h[o] & 127) << 24) | (h[o + 1] << 16) |
    (h[o + 2] << 8) | h[o + 3]) % 1e6;
  return String(code).padStart(6, '0');
}
async function verifyTotp(secretB32, code) {
  const c = Math.floor(Date.now() / 30000);
  for (const d of [-1, 0, 1]) {
    if (await totpAt(secretB32, c + d) === String(code).trim()) return true;
  }
  return false;
}

async function withinRateLimit(env, req, bucket, limit, windowMs) {
  const ip = req.headers.get('cf-connecting-ip') || 'unknown';
  const fingerprint = await crypto.subtle.digest('SHA-256',
    enc.encode(`${bucket}|${ip}|${env.KEY_WRAP_SECRET}`));
  const key = [...new Uint8Array(fingerprint)]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');
  const timestamp = now();
  const cutoff = timestamp - windowMs;
  const row = await env.DB.prepare(
    'INSERT INTO rate_limits (bucket_key,window_start,count) VALUES (?,?,1) ' +
    'ON CONFLICT(bucket_key) DO UPDATE SET ' +
    'count = CASE WHEN window_start < ? THEN 1 ELSE count + 1 END, ' +
    'window_start = CASE WHEN window_start < ? THEN ? ELSE window_start END ' +
    'RETURNING count')
    .bind(key, timestamp, cutoff, cutoff, timestamp).first();
  return !!row && row.count <= limit;
}

async function sessionFor(env, userId, name) {
  const token = crypto.randomUUID().replaceAll('-', '') + uid();
  await env.DB.prepare(
    'INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)')
    .bind(token, userId, now() + 1000 * 60 * 60 * 24 * 30).run();
  return j({ ok: true, name }, 200, {
    'set-cookie': `session=${token}; HttpOnly; Secure; SameSite=Lax; ` +
      'Path=/; Max-Age=2592000',
  });
}

async function deepseekChat(key, messages, opts = {}) {
  // Direct OpenAI-shaped call to DeepSeek, matching the engine's provider.
  const r = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json',
      authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model: opts.model || 'deepseek-v4-flash',
      messages,
      max_tokens: opts.max_tokens || 700,
    }),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => '');
    return { ok: false, status: r.status, body: body.slice(0, 300) };
  }
  const data = await r.json().catch(() => ({}));
  const text = data?.choices?.[0]?.message?.content || '';
  return { ok: true, text };
}

async function validateDeepseekKey(key) {
  // A tiny real call proves the key works before we ever store it.
  const res = await deepseekChat(key,
    [{ role: 'user', content: 'reply with the single word: ok' }],
    { max_tokens: 5 });
  return res.ok;
}

async function unwrapKey(env, ctB64, ivB64) {
  // Used ONLY to hand a user's own key to that user's own authenticated
  // helper daemon over TLS (scope 'user'). The shared KEK never leaves
  // Worker secrets; friends' machines never see other users' keys.
  const material = await crypto.subtle.importKey(
    'raw', await crypto.subtle.digest('SHA-256',
      enc.encode(env.KEY_WRAP_SECRET)),
    'AES-GCM', false, ['decrypt']);
  const un64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const pt = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: un64(ivB64) }, material, un64(ctB64));
  return new TextDecoder().decode(pt);
}

async function auth(req, env) {
  const cookie = req.headers.get('cookie') || '';
  const m = cookie.match(/session=([a-zA-Z0-9_-]+)/);
  if (!m) return null;
  const s = await env.DB.prepare(
    'SELECT s.token, s.expires_at, u.id, u.name, ' +
    '(u.key_ct IS NOT NULL) AS has_key ' +
    'FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?')
    .bind(m[1]).first();
  if (!s || s.expires_at < now()) return null;
  return { userId: s.id, name: s.name, hasKey: !!s.has_key };
}

async function workerAuth(req, env) {
  // Returns {scope:'global'} for Omar's daemon, {scope:'user', userId} for
  // a friend's personal daemon (only pulls THAT user's jobs), or null.
  const h = req.headers.get('authorization') || '';
  if (!h.startsWith('Bearer ')) return null;
  const tok = h.slice(7);
  if (tok === env.WORKER_TOKEN) return { scope: 'global' };
  const row = await env.DB.prepare(
    'SELECT user_id FROM daemon_tokens WHERE token = ?').bind(tok).first();
  if (!row) return null;
  return row.user_id ? { scope: 'user', userId: row.user_id }
    : { scope: 'global' };
}

function workerOwnsJob(scope, job) {
  return !!job && (scope.scope === 'global' || job.user_id === scope.userId);
}

function jobOwnsMediaKey(job, key) {
  return !key || key.startsWith(`u/${job.user_id}/${job.project_id}/`);
}

function claimTokenFrom(req, body = null) {
  return String((body && body.claim_token) ||
    req.headers.get('x-autoeditor-claim-token') || '');
}

function renderTag(job) {
  if (job.kind !== 'revision_apply') return job.id;
  try {
    return String(JSON.parse(job.payload_json || '{}').revision_id || job.id);
  } catch (_) { return job.id; }
}

function expectedRenderKeys(job, claimToken, multipartHash = '') {
  const suffix = multipartHash ? `_${multipartHash.slice(0, 16)}` : '';
  const root = `u/${job.user_id}/${job.project_id}/out/` +
    `${renderTag(job)}/${claimToken}${suffix}`;
  return { outputKey: `${root}.mp4`, qaKey: `${root}_QA.json` };
}

async function multipartFingerprint(size, partHashes) {
  return sha256Hex(`${size}:${partHashes.join(':')}`);
}

function completionReceipt(jobId, requestHash) {
  // Alphabetical property order matches the daemon's canonical JSON bytes.
  return JSON.stringify({ committed: true,
    completion_request_hash: requestHash, job_id: jobId, ok: true });
}

async function claimedJob(env, scope, jobId, claimToken,
    { allowExpired = false } = {}) {
  if (!claimToken) return null;
  const job = await env.DB.prepare('SELECT * FROM jobs WHERE id = ?')
    .bind(jobId).first();
  if (!workerOwnsJob(scope, job) || job.status !== 'running' ||
      job.claim_token !== claimToken) return null;
  if (!allowExpired && Number(job.lease_expires_at || 0) < now()) return null;
  return job;
}

function adminAuth(req, env) {
  const h = req.headers.get('authorization') || '';
  return h === `Bearer ${env.ADMIN_TOKEN}`;
}

async function ownedProject(env, user, projectId) {
  return await env.DB.prepare(
    'SELECT * FROM projects WHERE id = ? AND user_id = ?')
    .bind(projectId, user.userId).first();
}

async function setStatus(env, projectId, status, detail = '') {
  await env.DB.prepare(
    'UPDATE projects SET status = ?, status_detail = ?, updated_at = ? ' +
    'WHERE id = ? AND delete_token IS NULL')
    .bind(status, detail, now(), projectId).run();
}

function completionLease(status) {
  const match = String(status || '').match(
    /^completing:(\d+):([a-f0-9]{20})$/);
  if (!match) return null;
  return { startedAt: Number(match[1]), token: match[2] };
}

function newCompletionLease() {
  return `completing:${now()}:${uid()}`;
}

function uploadState(value) {
  let parsed;
  try { parsed = JSON.parse(value || '[]'); } catch (_) { parsed = []; }
  if (Array.isArray(parsed)) return { fingerprint: '', parts: parsed };
  if (!parsed || !Array.isArray(parsed.parts)) {
    return { fingerprint: '', parts: [] };
  }
  return { fingerprint: String(parsed.fingerprint || ''),
    parts: parsed.parts };
}

async function completedObjectExists(env, upload) {
  const object = await env.MEDIA.head(upload.r2_key);
  return !!object && Number(object.size) === Number(upload.size);
}

async function markUploadDone(env, upload, expectedStatus) {
  const finishedAt = now();
  const results = await env.DB.batch([
    env.DB.prepare(
      "UPDATE uploads SET status = 'done' WHERE id = ? AND status = ?")
      .bind(upload.id, expectedStatus),
    env.DB.prepare(
      "UPDATE projects SET status = 'uploaded', status_detail = '', " +
      'updated_at = ? WHERE id = ? AND EXISTS (' +
      "SELECT 1 FROM uploads WHERE id = ? AND status = 'done') " +
      'AND NOT EXISTS (SELECT 1 FROM uploads WHERE project_id = ? ' +
      "AND status NOT IN ('done','rejected'))")
      .bind(finishedAt, upload.project_id, upload.id, upload.project_id),
  ]);
  return !!(results[0].meta && results[0].meta.changes === 1);
}

// ---------------------------------------------------------- edit contract
// Mirror of webapp/render_worker/project_types.py ALLOWED_OPS. DeepSeek is
// an untrusted planner: every proposal is validated deterministically here
// and anything outside this contract rejects the WHOLE proposal.
const ALLOWED_OPS = {
  set_edit_style: {
    params: { style: ['auto', 'short', 'long'] }, approval: false,
    human: (p) => `Use ${p.style} edit pacing`,
  },
  set_aspect_ratio: {
    params: { aspect: ['auto', '9x16', '16x9'] }, approval: false,
    human: (p) => `Deliver in ${p.aspect}`,
  },
  set_caption_mode: {
    params: { mode: ['burned', 'sidecar'] }, approval: false,
    human: (p) => `Use ${p.mode} captions`,
  },
  set_visual_mode: {
    params: { mode: ['full', 'baseline'] }, approval: false,
    human: (p) => `Use the ${p.mode} visual treatment`,
  },
  set_edit_profile: {
    params: { profile_id: ['generic_short', 'generic_long',
      'generic_commercial', 'generic_podcast', 'generic_course',
      'generic_custom'] },
    approval: false,
    human: (p) => `Use the ${p.profile_id} edit profile`,
  },
};

function validateProposal(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { clean: null, needsApproval: false,
      errors: ['proposal must be an object'] };
  }
  const errors = [];
  const opsIn = raw.operations;
  if (!Array.isArray(opsIn) || !opsIn.length) {
    return { clean: null, needsApproval: false,
      errors: ['proposal has no operations list'] };
  }
  if (opsIn.length > 8) {
    return { clean: null, needsApproval: false,
      errors: ['too many operations in one proposal (max 8)'] };
  }
  const clean = []; let needsApproval = false;
  const seen = new Set();
  for (const [index, op] of opsIn.entries()) {
    if (!op || typeof op !== 'object' || Array.isArray(op) ||
        !Object.hasOwn(op, 'op')) {
      errors.push(`operation ${index} is malformed`);
      continue;
    }
    const name = op.op;
    const spec = Object.hasOwn(ALLOWED_OPS, name) ? ALLOWED_OPS[name] : null;
    if (!spec) {
      errors.push(`operation '${name}' is not in the executable contract`);
      continue;
    }
    if (seen.has(name)) {
      errors.push(`operation '${name}' appears more than once`);
      continue;
    }
    seen.add(name);
    const allowedFields = new Set(['op', 'human',
      ...Object.keys(spec.params)]);
    const extraFields = Object.keys(op)
      .filter((field) => !allowedFields.has(field)).sort();
    if (extraFields.length) {
      errors.push(`operation '${name}' has unsupported field(s): ` +
        extraFields.join(', '));
      continue;
    }
    const params = {}; let ok = true;
    for (const [pname, choices] of Object.entries(spec.params)) {
      const val = op[pname];
      if (!choices.includes(val)) {
        errors.push(`${name}.${pname} must be one of ` +
          JSON.stringify(choices));
        ok = false;
      } else {
        params[pname] = val;
      }
    }
    if (!ok) continue;
    clean.push({ op: name, ...params, human: spec.human(params) });
    needsApproval = needsApproval || spec.approval;
  }
  if (errors.length) return { clean: null, needsApproval: false, errors };
  return { clean: { operations: clean,
    summary: String(raw.summary || '').slice(0, 400) },
  needsApproval, errors: [] };
}

const PROJECT_TYPES = new Set(['short', 'long', 'commercial', 'podcast',
  'course', 'custom']);
const PRESET_NAMES = new Set(['My Style', 'My Shorts Style',
  'My Long-Form Style', 'My Commercial Style', 'Custom Style']);
const PRESET_CHOICES = {
  style: ['auto', 'short', 'long'],
  aspects: ['auto', '9x16', '16x9'],
  caption_mode: ['burned', 'sidecar'],
  visual_mode: ['full', 'baseline'],
  profile: ['generic_short', 'generic_long', 'generic_commercial',
    'generic_podcast', 'generic_course', 'generic_custom'],
};

function validatePresetParams(raw) {
  const params = raw == null ? {} : raw;
  if (typeof params !== 'object' || Array.isArray(params)) {
    return { clean: null, errors: ['preset parameters must be an object'] };
  }
  const unknown = Object.keys(params)
    .filter((name) => !Object.hasOwn(PRESET_CHOICES, name)).sort();
  if (unknown.length) {
    return { clean: null, errors: ['unsupported preset parameter(s): ' +
      unknown.join(', ')] };
  }
  const clean = {};
  const errors = [];
  for (const [name, value] of Object.entries(params)) {
    const choices = PRESET_CHOICES[name];
    if (!choices.includes(value)) {
      errors.push(`preset ${name} must be one of: ${choices.join(', ')}`);
    } else {
      clean[name] = value;
    }
  }
  return errors.length ? { clean: null, errors } : { clean, errors: [] };
}

const HELPER_DOWNLOAD_ROUTES = {
  '/download/helper/windows': {
    platform: 'windows-x64',
    filename: 'AutoEditor-Helper.exe',
    type: 'application/vnd.microsoft.portable-executable',
    name: 'AutoEditor-Helper-Windows.exe',
  },
  '/download/helper/mac-arm64': {
    platform: 'mac-arm64',
    filename: 'AutoEditor-Helper.dmg',
    type: 'application/x-apple-diskimage',
    name: 'AutoEditor-Helper-Mac-Apple-Silicon.dmg',
  },
  '/download/helper/mac-x64': {
    platform: 'mac-x64',
    filename: 'AutoEditor-Helper.dmg',
    type: 'application/x-apple-diskimage',
    name: 'AutoEditor-Helper-Mac-Intel.dmg',
  },
};

const HELPER_RELEASE_SCHEMA = 'autoeditor-helper-release/v2';
const HELPER_TAG_PATTERN =
  /^helper-v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.-]+)?$/;
const HELPER_RUNTIME_ROUTE_PATTERN = new RegExp(
  '^/download/helper/runtime/windows-x64/' +
  '(helper-v[0-9]+\\.[0-9]+\\.[0-9]+(?:[.-][A-Za-z0-9.-]+)?)/' +
  '([a-f0-9]{40})$',
);
const MAX_NSIS_WEB_PACKAGE_BYTES = 4_294_967_295;
const HELPER_RUNTIME_CONTRACT = Object.freeze({
  schema: 'autoeditor-helper-runtime-route/v2',
  release_schema: HELPER_RELEASE_SCHEMA,
  route: '/download/helper/runtime/windows-x64/{tag}/{commit}',
  max_package_bytes: MAX_NSIS_WEB_PACKAGE_BYTES - 1,
});
const WINDOWS_RUNTIME_PACKAGE = {
  filename: 'AutoEditor-Helper-Windows.nsis.7z',
  type: 'application/x-7z-compressed',
};

async function helperRelease(env) {
  const pointer = await env.RELEASES.get('dist/helper/current.json');
  if (!pointer) return null;
  let release;
  try { release = JSON.parse(await pointer.text()); } catch (_) { release = null; }
  if (!release || release.schema !== HELPER_RELEASE_SCHEMA ||
      !HELPER_TAG_PATTERN.test(release.tag) ||
      release.version !== release.tag.slice('helper-v'.length) ||
      !release.source ||
      !/^[a-f0-9]{40}$/.test(release.source.commit) ||
      typeof release.platforms !== 'object' ||
      Array.isArray(release.platforms)) {
    throw new Error('invalid helper release pointer');
  }
  const downloads = Object.fromEntries(Object.entries(HELPER_DOWNLOAD_ROUTES)
    .map(([route, item]) => {
      const selected = release.platforms[item.platform];
      const expected = `dist/helper/objects/${selected?.sha256}/` +
        `${item.platform}/${item.filename}`;
      if (!selected || selected.key !== expected ||
          !/^[a-f0-9]{64}$/.test(selected.sha256) ||
          !Number.isSafeInteger(selected.bytes) || selected.bytes <= 0) {
        throw new Error(`invalid helper release entry: ${item.platform}`);
      }
      if (item.platform !== 'windows-x64' &&
          Object.hasOwn(selected, 'runtime_package')) {
        throw new Error(`invalid helper release entry: ${item.platform}`);
      }
      return [route, { ...item, key: selected.key, bytes: selected.bytes,
        sha256: selected.sha256 }];
    }));
  const runtime = release.platforms['windows-x64'].runtime_package;
  const expectedRuntimeKey = `dist/helper/objects/${runtime?.sha256}/` +
    `windows-x64/${WINDOWS_RUNTIME_PACKAGE.filename}`;
  if (!runtime || runtime.key !== expectedRuntimeKey ||
      runtime.filename !== WINDOWS_RUNTIME_PACKAGE.filename ||
      runtime.content_type !== WINDOWS_RUNTIME_PACKAGE.type ||
      !/^[a-f0-9]{64}$/.test(runtime.sha256) ||
      !Number.isSafeInteger(runtime.bytes) || runtime.bytes <= 0 ||
      runtime.bytes >= MAX_NSIS_WEB_PACKAGE_BYTES) {
    throw new Error('invalid Windows runtime package release entry');
  }
  return {
    tag: release.tag,
    commit: release.source.commit,
    downloads,
    runtimePackage: {
      key: runtime.key,
      bytes: runtime.bytes,
      sha256: runtime.sha256,
      filename: runtime.filename,
      type: runtime.content_type,
    },
  };
}

function releaseObjectMatches(object, item) {
  return !!object && Number(object.size) === item.bytes &&
    object.customMetadata?.sha256 === item.sha256;
}

function normalizedR2Range(object) {
  const range = object?.range;
  if (!range) return null;
  let offset;
  let length;
  if (range.suffix !== undefined) {
    length = Math.min(range.suffix, object.size);
    offset = object.size - length;
  } else {
    offset = range.offset ?? 0;
    length = range.length ?? object.size - offset;
  }
  return { offset, length };
}

async function verifiedHelperRelease(env) {
  let release;
  try { release = await helperRelease(env); } catch (_) { return null; }
  if (!release) return null;
  const releaseObjects = [
    ...Object.values(release.downloads), release.runtimePackage,
  ];
  const verified = await Promise.all(releaseObjects
    .map(async (item) => releaseObjectMatches(
      await env.RELEASES.head(item.key), item)));
  return verified.every(Boolean) ? release : null;
}

// ------------------------------------------------------------- router
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;
    try {
      if (p === '/download/helper/runtime/contract') {
        return j(HELPER_RUNTIME_CONTRACT);
      }
      if (p.startsWith('/download/helper/runtime/')) {
        const route = HELPER_RUNTIME_ROUTE_PATTERN.exec(p);
        if (!route) return new Response('Not found', { status: 404,
          headers: { 'cache-control': 'no-store',
            ...BASE_SECURITY_HEADERS } });
        const release = await verifiedHelperRelease(env);
        if (!release || route[1] !== release.tag ||
            route[2] !== release.commit) {
          return new Response('Not found', { status: 404,
            headers: { 'cache-control': 'no-store',
              ...BASE_SECURITY_HEADERS } });
        }
        const item = release.runtimePackage;
        const rangeRequested = req.headers.has('range');
        const obj = rangeRequested
          ? await env.RELEASES.get(item.key, { range: req.headers })
          : await env.RELEASES.get(item.key);
        if (!releaseObjectMatches(obj, item)) {
          return new Response('Not found', { status: 404,
            headers: { 'cache-control': 'no-store',
              ...BASE_SECURITY_HEADERS } });
        }
        const headers = {
          'content-type': item.type,
          'content-disposition': `attachment; filename="${item.filename}"`,
          // The path is immutable, but the live pointer is the authorization
          // boundary. Do not let a cache keep serving it after promotion.
          'cache-control': 'no-store',
          'accept-ranges': 'bytes',
          ...BASE_SECURITY_HEADERS,
        };
        if (obj.httpEtag) headers.etag = obj.httpEtag;
        const servedRange = rangeRequested ? normalizedR2Range(obj) : null;
        if (servedRange) {
          headers['content-range'] =
            `bytes ${servedRange.offset}-` +
            `${servedRange.offset + servedRange.length - 1}` +
            `/${obj.size}`;
          headers['content-length'] = String(servedRange.length);
          return new Response(obj.body, { status: 206, headers });
        }
        headers['content-length'] = String(obj.size);
        return new Response(obj.body, { headers });
      }
      if (p === '/download/helper/availability') {
        if (!(await auth(req, env))) return bad('sign in first', 401);
        const release = await verifiedHelperRelease(env);
        const entries = Object.keys(HELPER_DOWNLOAD_ROUTES)
          .map((route) => [route, !!release]);
        return new Response(JSON.stringify(Object.fromEntries(entries)), {
          headers: { 'content-type': 'application/json; charset=utf-8',
            'cache-control': 'no-store', ...BASE_SECURITY_HEADERS },
        });
      }
      if (HELPER_DOWNLOAD_ROUTES[p]) {
        if (!(await auth(req, env))) return bad('sign in first', 401);
        const release = await verifiedHelperRelease(env);
        if (!release) {
          return new Response('Installer is not uploaded yet', { status: 503,
            headers: { 'cache-control': 'no-store',
              ...BASE_SECURITY_HEADERS } });
        }
        const item = release.downloads[p];
        const rangeRequested = req.headers.has('range');
        const obj = rangeRequested
          ? await env.RELEASES.get(item.key, { range: req.headers })
          : await env.RELEASES.get(item.key);
        if (!releaseObjectMatches(obj, item)) {
          return new Response('Installer failed its release receipt', {
            status: 503, headers: { 'cache-control': 'no-store',
              ...BASE_SECURITY_HEADERS },
          });
        }
        const headers = {
          'content-type': item.type,
          'content-disposition': `attachment; filename="${item.name}"`,
          'cache-control': 'private, no-store',
          'accept-ranges': 'bytes',
          'x-content-type-options': 'nosniff',
          ...BASE_SECURITY_HEADERS,
        };
        if (obj.httpEtag) headers.etag = obj.httpEtag;
        const servedRange = rangeRequested ? normalizedR2Range(obj) : null;
        if (servedRange) {
          headers['content-range'] =
            `bytes ${servedRange.offset}-` +
            `${servedRange.offset + servedRange.length - 1}` +
            `/${obj.size}`;
          headers['content-length'] = String(servedRange.length);
          return new Response(obj.body, { status: 206, headers });
        }
        headers['content-length'] = String(obj.size);
        return new Response(obj.body, { headers });
      }
      if (p.startsWith('/api/')) return await api(req, env, url);
      return secureSiteResponse(await env.ASSETS.fetch(req));
    } catch (e) {
      // never leak internals (or key material) into browser errors
      console.log('unhandled', e.name, e.message.slice(0, 200));
      return bad('internal error', 500);
    }
  },
};

async function api(req, env, url) {
  const p = url.pathname.replace(/^\/api/, '');
  const method = req.method;

  // ---------- admin: invites (Omar only, bearer token)
  if (p === '/admin/invites' && method === 'POST') {
    if (!adminAuth(req, env)) return bad('forbidden', 403);
    const { note } = await req.json().catch(() => ({}));
    const code = uid().slice(0, 10);
    await env.DB.prepare(
      'INSERT INTO invites (code, note, created_at) VALUES (?, ?, ?)')
      .bind(code, note || '', now()).run();
    return j({ code });
  }

  if (p === '/admin/daemon-tokens' && method === 'POST') {
    if (!adminAuth(req, env)) return bad('forbidden', 403);
    const { user_name, note } = await req.json().catch(() => ({}));
    let userId = null;
    if (user_name) {
      const u = await env.DB.prepare(
        'SELECT id FROM users WHERE name = ?').bind(user_name).first();
      if (!u) return bad('no such user');
      userId = u.id;
    }
    const token = crypto.randomUUID().replaceAll('-', '') + uid();
    await env.DB.prepare(
      'INSERT INTO daemon_tokens (token,user_id,note,created_at) ' +
      'VALUES (?,?,?,?)').bind(token, userId, note || '', now()).run();
    return j({ token, scoped_to: user_name || 'ALL USERS (global)' });
  }

  // ---------- auth: name + code. The code is either the invite code
  // (works forever as the account password) or, if the user set up OTP,
  // the current 6-digit code from their authenticator app.
  if (p === '/auth/signin' && method === 'POST') {
    if (!(await withinRateLimit(env, req, 'signin', 15, 10 * 60 * 1000))) {
      return bad('too many sign-in attempts; wait 10 minutes and try again', 429);
    }
    const { invite_code, name } = await req.json().catch(() => ({}));
    const code = String(invite_code || '').trim();
    const who = String(name || '').trim().slice(0, 60);
    if (!code || !who) return bad('name and code required');

    // 6-digit path: OTP login by name
    if (/^\d{6}$/.test(code)) {
      const candidates = (await env.DB.prepare(
        'SELECT id, name, totp_secret FROM users WHERE name = ? ' +
        'AND totp_secret IS NOT NULL').bind(who).all()).results || [];
      if (candidates.length !== 1) {
        return bad(candidates.length
          ? 'more than one account has that name; use your invite code'
          : 'no one-time codes set up for that name; use your invite code',
        403);
      }
      if (!(await verifyTotp(candidates[0].totp_secret, code))) {
        return bad('that code is wrong or expired; codes change every ' +
          '30 seconds', 403);
      }
      return sessionFor(env, candidates[0].id, candidates[0].name);
    }

    // invite-code path
    const inv = await env.DB.prepare(
      'SELECT * FROM invites WHERE code = ?').bind(code).first();
    if (!inv) return bad('invalid invite code', 403);
    let user;
    if (inv.used_by) {
      user = await env.DB.prepare('SELECT * FROM users WHERE id = ?')
        .bind(inv.used_by).first();
      if (!user) return bad('invite orphaned; ask Omar', 403);
    } else {
      // new account: names must be unique so OTP-by-name stays unambiguous
      const taken = await env.DB.prepare(
        'SELECT id FROM users WHERE name = ?').bind(who).first();
      if (taken) {
        return bad('that name is taken; add a last initial or pick ' +
          'another', 409);
      }
      user = { id: uid(), name: who };
      // D1 batch() is one transaction. A failed user insert rolls the invite
      // claim back, and the INSERT ... SELECT can only create the exact user
      // that won the NULL -> id claim.
      let signup;
      try {
        signup = await env.DB.batch([
          env.DB.prepare(
            'UPDATE invites SET used_by = ? WHERE code = ? ' +
            'AND used_by IS NULL').bind(user.id, code),
          env.DB.prepare(
            'INSERT INTO users (id, name, invite_code, created_at) ' +
            'SELECT ?, ?, ?, ? WHERE EXISTS (' +
            'SELECT 1 FROM invites WHERE code = ? AND used_by = ?)')
            .bind(user.id, user.name, code, now(), code, user.id),
        ]);
      } catch (_) {
        // The unique name index is the final concurrency guard. Re-read only
        // to return the friend a useful error; the batch already rolled back.
        const nameOwner = await env.DB.prepare(
          'SELECT id FROM users WHERE name = ?').bind(who).first();
        if (nameOwner) {
          return bad('that name is taken; add a last initial or pick ' +
            'another', 409);
        }
        const latestInvite = await env.DB.prepare(
          'SELECT used_by FROM invites WHERE code = ?').bind(code).first();
        if (latestInvite && latestInvite.used_by) {
          return bad('that invite was just used; ask Omar for another', 403);
        }
        return bad('could not create the account; try again', 503);
      }
      const claimed = signup[0]?.meta?.changes === 1;
      const created = signup[1]?.meta?.changes === 1;
      if (!claimed || !created) {
        return bad('that invite was just used; ask Omar for another', 403);
      }
    }
    return sessionFor(env, user.id, user.name);
  }
  if (p === '/auth/signout' && method === 'POST') {
    const user = await auth(req, env);
    if (user) {
      const m = (req.headers.get('cookie') || '')
        .match(/session=([a-zA-Z0-9_-]+)/);
      if (m) await env.DB.prepare('DELETE FROM sessions WHERE token = ?')
        .bind(m[1]).run();
    }
    return j({ ok: true }, 200,
      { 'set-cookie': 'session=; Max-Age=0; Path=/' });
  }

  // ---------- worker (render daemon) routes, bearer-token scoped
  if (p.startsWith('/worker/')) {
    const scope = await workerAuth(req, env);
    if (!scope) return bad('forbidden', 403);
    return workerApi(req, env, p, method, scope);
  }

  // ---------- everything below requires a signed-in user
  const user = await auth(req, env);
  if (!user) return bad('sign in required', 401);

  if (p === '/me' && method === 'GET') {
    const row = await env.DB.prepare(
      'SELECT (totp_secret IS NOT NULL) AS has_otp FROM users WHERE id = ?')
      .bind(user.userId).first();
    return j({ name: user.name, hasKey: user.hasKey,
      hasOtp: !!(row && row.has_otp) });
  }
  if (p === '/me/key' && method === 'PUT') {
    // each attempt fires a live DeepSeek call; cap per-user brute force
    if (!(await withinRateLimit(env, req, `key:${user.userId}`, 20,
        10 * 60 * 1000))) {
      return bad('too many key attempts; wait a few minutes', 429);
    }
    const { key } = await req.json().catch(() => ({}));
    if (!key || key.length < 20) return bad('that does not look like a key');
    // Validate against DeepSeek before storing: nothing works until the
    // key is real, and a bad key is rejected here with a clear message.
    const valid = await validateDeepseekKey(key.trim());
    if (!valid) {
      return bad('That key did not work with DeepSeek. Double-check you ' +
        'copied the whole key from platform.deepseek.com and that your ' +
        'DeepSeek account has credit.', 422);
    }
    const { ct, iv } = await wrapKey(env, key.trim());
    await env.DB.prepare(
      'UPDATE users SET key_ct = ?, key_iv = ? WHERE id = ?')
      .bind(ct, iv, user.userId).run();
    return j({ ok: true }); // the key itself is never echoed anywhere
  }

  // ---------- help chat: talk to DeepSeek directly (needs a valid key).
  // This is the always-available lifeline. A friend can ask DeepSeek for
  // help with setup or anything else the moment their key is in.
  if (p === '/assistant' && method === 'POST') {
    if (!user.hasKey) return bad('add your DeepSeek key first', 428);
    if (!(await withinRateLimit(env, req, `assist:${user.userId}`, 40,
        5 * 60 * 1000))) {
      return bad('slow down a moment and try again', 429);
    }
    const { messages } = await req.json().catch(() => ({}));
    if (!Array.isArray(messages) || !messages.length) {
      return bad('nothing to send');
    }
    const row = await env.DB.prepare(
      'SELECT key_ct, key_iv FROM users WHERE id = ?')
      .bind(user.userId).first();
    let key;
    try { key = await unwrapKey(env, row.key_ct, row.key_iv); }
    catch (_) { return bad('your stored key could not be unlocked; ' +
      're-enter it in Settings', 409); }
    const sys = { role: 'system', content:
      'You are the friendly built-in helper inside AutoEditor, a website ' +
      'that turns raw footage into finished videos. The person you are ' +
      'helping may not be technical. Friends install one signed AutoEditor ' +
      'Helper EXE on Windows or notarized DMG on Mac. Never tell them to ' +
      'install Python, Node, FFmpeg, models, HyperFrames, Remotion, repos, ' +
      'package managers, or to open a terminal. Those are bundled. DeepSeek ' +
      'is required. Pexels and Pixabay can be connected with their own API ' +
      'keys or skipped, which removes that stock source. ElevenLabs can be ' +
      'connected for generated sound effects or skipped, which leaves only ' +
      'the built-in sound effects. Tell them to restrict an ElevenLabs key ' +
      'to Sound Effects and set a small credit limit. HyperFrames needs ' +
      'no account. Remotion is free without signup for individuals and ' +
      'organizations of up to three people; larger groups need a public ' +
      'rm_pub_ license key from the Remotion dashboard ' +
      'or must enter a paid Remotion key. Remotion and HyperFrames are required. ' +
      'Give exact click-by-click guidance, ' +
      'explain the consequence of every Skip choice, and never ask them to ' +
      'paste a secret into chat.' };
    const trimmed = messages
      .filter((m) => m && typeof m.content === 'string' &&
        (m.role === 'user' || m.role === 'assistant'))
      .slice(-12)
      .map((m) => ({ role: m.role, content: m.content.slice(0, 4000) }));
    const res = await deepseekChat(key, [sys, ...trimmed],
      { model: 'deepseek-v4-flash', max_tokens: 800 });
    key = null;
    if (!res.ok) {
      return bad('DeepSeek did not respond (your key may be out of ' +
        'credit). Try again in a moment.', 502);
    }
    return j({ reply: res.text });
  }

  // ---------- self-serve Helper connect code (auto-minted per account)
  if (p === '/me/connect-code' && method === 'GET') {
    let row = await env.DB.prepare(
      'SELECT token FROM daemon_tokens WHERE user_id = ?')
      .bind(user.userId).first();
    if (!row) {
      const token = crypto.randomUUID().replaceAll('-', '') + uid();
      await env.DB.prepare(
        'INSERT INTO daemon_tokens (token,user_id,note,created_at) ' +
        'VALUES (?,?,?,?)')
        .bind(token, user.userId, 'self-serve', now()).run();
      row = { token };
    }
    const origin = new URL(req.url).origin;
    // one-paste setup code = base64url("site|connectcode")
    const setup = btoa(`${origin}|${row.token}`)
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return j({ connect_code: row.token, site: origin, setup_code: setup });
  }

  // ---------- optional OTP setup (their choice, tied to their account)
  if (p === '/me/otp/setup' && method === 'POST') {
    const secret = b32encode(crypto.getRandomValues(new Uint8Array(20)));
    await env.DB.prepare(
      'UPDATE users SET totp_pending = ? WHERE id = ?')
      .bind(secret, user.userId).run();
    const label = encodeURIComponent(`AutoEditor:${user.name}`);
    return j({ secret,
      otpauth: `otpauth://totp/${label}?secret=${secret}` +
        '&issuer=AutoEditor' });
  }
  if (p === '/me/otp/verify' && method === 'POST') {
    const { code } = await req.json().catch(() => ({}));
    const row = await env.DB.prepare(
      'SELECT totp_pending FROM users WHERE id = ?')
      .bind(user.userId).first();
    if (!row || !row.totp_pending) return bad('start OTP setup first');
    if (!(await verifyTotp(row.totp_pending, code || ''))) {
      return bad('that code is wrong or expired; try the newest one', 403);
    }
    await env.DB.prepare(
      'UPDATE users SET totp_secret = totp_pending, totp_pending = NULL ' +
      'WHERE id = ?').bind(user.userId).run();
    return j({ ok: true });
  }

  // ---------- style presets
  if (p === '/presets' && method === 'GET') {
    const r = await env.DB.prepare(
      'SELECT id, name, params_json FROM style_presets WHERE user_id = ?')
      .bind(user.userId).all();
    return j(r.results || []);
  }
  if (p === '/presets' && method === 'POST') {
    const { name, params } = await req.json().catch(() => ({}));
    if (!PRESET_NAMES.has(name)) return bad('unknown preset name');
    const validated = validatePresetParams(params);
    if (!validated.clean) return bad(validated.errors.join('; '), 422);
    const id = uid();
    await env.DB.prepare(
      'INSERT INTO style_presets (id,user_id,name,params_json,created_at) ' +
      'VALUES (?,?,?,?,?)')
      .bind(id, user.userId, name, JSON.stringify(validated.clean), now())
      .run();
    return j({ id });
  }

  // ---------- projects
  if (p === '/projects' && method === 'POST') {
    const { type, title, style_preset_id } =
      await req.json().catch(() => ({}));
    if (!PROJECT_TYPES.has(type)) return bad('unknown project type');
    if (style_preset_id) {
      const preset = await env.DB.prepare(
        'SELECT id, params_json FROM style_presets WHERE id = ? AND user_id = ?')
        .bind(style_preset_id, user.userId).first();
      if (!preset) return bad('style preset not found', 404);
      let params;
      try { params = JSON.parse(preset.params_json); }
      catch (_) { return bad('style preset parameters are invalid', 422); }
      const validated = validatePresetParams(params);
      if (!validated.clean) return bad(validated.errors.join('; '), 422);
    }
    const id = uid();
    await env.DB.prepare(
      'INSERT INTO projects (id,user_id,type,title,style_preset_id,' +
      'status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)')
      .bind(id, user.userId, type, String(title || 'Untitled').slice(0, 80),
        style_preset_id || null, 'empty', now(), now()).run();
    return j({ id });
  }
  if (p === '/projects' && method === 'GET') {
    const r = await env.DB.prepare(
      'SELECT id,type,title,status,status_detail,updated_at ' +
      'FROM projects WHERE user_id = ? ORDER BY updated_at DESC')
      .bind(user.userId).all();
    return j(r.results || []);
  }

  let m;
  if ((m = p.match(/^\/projects\/(\w+)$/)) && method === 'GET') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    const uploads = await env.DB.prepare(
      "SELECT id,filename,size,status FROM uploads WHERE project_id = ? " +
      "AND status != 'rejected'")
      .bind(proj.id).all();
    const revisions = await env.DB.prepare(
      'SELECT id,num,request_text,proposal_json,needs_approval,status,' +
      'qa_pass,output_key,output_key IS NOT NULL AS has_output ' +
      'FROM revisions WHERE project_id = ? ORDER BY num')
      .bind(proj.id).all();
    const chat = await env.DB.prepare(
      'SELECT role,content,created_at FROM chat_messages ' +
      'WHERE project_id = ? ORDER BY created_at').bind(proj.id).all();
    const active = await env.DB.prepare(
      'SELECT EXISTS(SELECT 1 FROM jobs WHERE project_id = ? ' +
      'AND render_slot = 1) AS active').bind(proj.id).first();
    return j({ ...proj, transcript: proj.transcript,
      uploads: uploads.results || [],
      revisions: revisions.results || [], chat: chat.results || [],
      render_active: !!active?.active });
  }
  if ((m = p.match(/^\/projects\/(\w+)$/)) && method === 'DELETE') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    const timestamp = now();
    const deleteToken = uid();
    const claimed = await env.DB.prepare(
      "UPDATE projects SET status = 'deleting', status_detail = '', " +
      'delete_token = ?, delete_lease_expires_at = ?, updated_at = ? ' +
      'WHERE id = ? AND user_id = ? AND ' +
      '(delete_token IS NULL OR delete_lease_expires_at < ?) AND ' +
      'NOT EXISTS (SELECT 1 FROM jobs WHERE project_id = ? AND (' +
      "status = 'running' OR status LIKE 'finishing:%'))")
      .bind(deleteToken, timestamp + DELETE_LEASE_MS, timestamp,
        proj.id, user.userId, timestamp, proj.id).run();
    if (claimed.meta?.changes !== 1) {
      return bad('wait for the current edit or deletion to finish', 409);
    }
    await env.DB.prepare(
      "UPDATE jobs SET status = 'cancelled', render_slot = 0, " +
      "error = 'project deleted before rendering', finished_at = ? " +
      "WHERE project_id = ? AND status = 'queued'")
      .bind(timestamp, proj.id).run();

    const incomplete = await env.DB.prepare(
      "SELECT r2_key,mp_upload_id FROM uploads WHERE project_id = ? " +
      "AND status != 'done'").bind(proj.id).all();
    for (const upload of (incomplete.results || [])) {
      if (!upload.mp_upload_id) continue;
      try {
        await env.MEDIA.resumeMultipartUpload(
          upload.r2_key, upload.mp_upload_id).abort();
      } catch (_) { /* expired or already completed */ }
    }
    const renderUploads = await env.DB.prepare(
      'SELECT r.r2_key,r.mp_upload_id FROM render_uploads r JOIN jobs j ' +
      "ON j.id = r.job_id WHERE j.project_id = ? AND r.status != 'done'")
      .bind(proj.id).all();
    for (const upload of (renderUploads.results || [])) {
      try {
        await env.MEDIA.resumeMultipartUpload(
          upload.r2_key, upload.mp_upload_id).abort();
      } catch (_) { /* expired or already completed */ }
    }

    const prefix = `u/${user.userId}/${proj.id}/`;
    let cursor;
    let deleted = 0;
    do {
      const listed = await env.MEDIA.list({ prefix, cursor, limit: 1000 });
      const keys = listed.objects.map((object) => object.key);
      if (keys.length) {
        await env.MEDIA.delete(keys);
        deleted += keys.length;
      }
      cursor = listed.truncated ? listed.cursor : undefined;
    } while (cursor);

    let removed;
    try {
      removed = await env.DB.batch([
        env.DB.prepare(
          'DELETE FROM render_uploads WHERE job_id IN (' +
          'SELECT id FROM jobs WHERE project_id = ?)').bind(proj.id),
        ...['chat_messages', 'revisions', 'jobs', 'uploads'].map((table) =>
          env.DB.prepare(`DELETE FROM ${table} WHERE project_id = ?`)
            .bind(proj.id)),
        env.DB.prepare(
          'DELETE FROM projects WHERE id = ? AND user_id = ? ' +
          'AND delete_token = ?')
          .bind(proj.id, user.userId, deleteToken),
      ]);
    } catch (_) {
      return bad('cloud files were removed but project cleanup must be retried', 503);
    }
    if (removed[removed.length - 1]?.meta?.changes !== 1) {
      return bad('project deletion lost its cleanup claim', 409);
    }
    return j({ ok: true, cloud_files_deleted: deleted });
  }

  // ---------- uploads: R2 multipart through the Worker (documented
  // pattern; parts survive refresh because uploadId+parts live in D1)
  if ((m = p.match(/^\/projects\/(\w+)\/uploads$/)) && method === 'POST') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    if (proj.delete_token) return bad('this project is being deleted', 409);
    const { filename, size, source_fingerprint: sourceFingerprint } =
      await req.json().catch(() => ({}));
    if (!filename) return bad('filename required');
    const byteSize = Number(size);
    if (!Number.isSafeInteger(byteSize) || byteSize <= 0 ||
        byteSize > MAX_UPLOAD_BYTES) {
      return bad('video must be between 1 byte and 20 GB');
    }
    if (!SHA256_PATTERN.test(String(sourceFingerprint || ''))) {
      return bad('the local file fingerprint is missing or invalid');
    }
    const priorRows = await env.DB.prepare(
      "SELECT id,parts_json FROM uploads WHERE project_id = ? " +
      "AND filename = ? AND size = ? AND " +
      "(status = 'uploading' OR status LIKE 'completing:%') " +
      'AND created_at > ? ORDER BY created_at DESC LIMIT 10')
      .bind(proj.id, String(filename).slice(0, 240), byteSize,
        now() - 6 * 24 * 60 * 60 * 1000).all();
    const prior = (priorRows.results || []).find((row) =>
      uploadState(row.parts_json).fingerprint === sourceFingerprint);
    if (prior) {
      const parts = uploadState(prior.parts_json).parts
        .map((part) => part.partNumber).filter(Number.isInteger);
      return j({ upload_id: prior.id, part_size: UPLOAD_PART_SIZE,
        uploaded_parts: parts, resumed: true });
    }
    const id = uid();
    const key = `u/${user.userId}/${proj.id}/raw/${id}_` +
      `${sourceFingerprint.slice(0, 16)}_` +
      String(filename).slice(0, 220).replace(/[^\w.-]/g, '_');
    const mp = await env.MEDIA.createMultipartUpload(key);
    await env.DB.prepare(
      'INSERT INTO uploads (id,project_id,r2_key,filename,size,' +
      'mp_upload_id,parts_json,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)')
      .bind(id, proj.id, key, String(filename).slice(0, 240), byteSize, mp.uploadId,
        JSON.stringify({ fingerprint: sourceFingerprint, parts: [] }),
        'uploading', now()).run();
    await setStatus(env, proj.id, 'uploading');
    return j({ upload_id: id, part_size: UPLOAD_PART_SIZE,
      uploaded_parts: [], resumed: false });
  }
  if ((m = p.match(/^\/uploads\/(\w+)\/part$/)) && method === 'PUT') {
    const up = await env.DB.prepare(
      'SELECT u.*, p.user_id, p.delete_token FROM uploads u JOIN projects p ' +
      'ON p.id = u.project_id WHERE u.id = ?').bind(m[1]).first();
    if (!up || up.user_id !== user.userId) return bad('not found', 404);
    if (up.delete_token) return bad('this project is being deleted', 409);
    if (up.status !== 'uploading') {
      return bad('this upload is being finished or is already finished', 409);
    }
    const partNum = parseInt(url.searchParams.get('n'), 10);
    const totalParts = Math.ceil(up.size / UPLOAD_PART_SIZE);
    if (!partNum || partNum < 1 || partNum > totalParts) {
      return bad('part number out of range');
    }
    const expectedBytes = partNum === totalParts
      ? up.size - ((totalParts - 1) * UPLOAD_PART_SIZE) : UPLOAD_PART_SIZE;
    const lengthHeader = req.headers.get('content-length');
    // require a declared length and enforce the exact expected part size —
    // a missing Content-Length must not skip the check.
    if (lengthHeader === null) {
      return bad('missing content-length on upload part', 411);
    }
    const suppliedBytes = Number(lengthHeader);
    if (!Number.isFinite(suppliedBytes) || suppliedBytes !== expectedBytes) {
      return bad('upload part has the wrong size');
    }
    const suppliedHash = req.headers.get('x-autoeditor-part-sha256') || '';
    if (!SHA256_PATTERN.test(suppliedHash)) {
      return bad('upload part is missing its SHA-256 receipt');
    }
    const partBytes = await req.arrayBuffer();
    if (partBytes.byteLength !== expectedBytes ||
        await sha256Hex(partBytes) !== suppliedHash) {
      return bad('upload part failed its SHA-256 receipt', 422);
    }
    const mp = env.MEDIA.resumeMultipartUpload(up.r2_key, up.mp_upload_id);
    const part = await mp.uploadPart(partNum, partBytes);
    const state = uploadState(up.parts_json);
    const parts = state.parts
      .filter((x) => x.partNumber !== partNum);
    parts.push({ partNumber: part.partNumber, etag: part.etag,
      sha256: suppliedHash });
    const saved = await env.DB.prepare(
      "UPDATE uploads SET parts_json = ? WHERE id = ? AND status = 'uploading'")
      .bind(JSON.stringify({ fingerprint: state.fingerprint, parts }),
        up.id).run();
    if (!saved.meta || saved.meta.changes !== 1) {
      return bad('this upload started finishing; retry the file', 409);
    }
    return j({ ok: true, part: partNum });
  }
  if ((m = p.match(/^\/uploads\/(\w+)\/complete$/)) && method === 'POST') {
    let up = await env.DB.prepare(
      'SELECT u.*, p.user_id, p.delete_token FROM uploads u JOIN projects p ' +
      'ON p.id = u.project_id WHERE u.id = ?').bind(m[1]).first();
    if (!up || up.user_id !== user.userId) return bad('not found', 404);
    if (up.delete_token) return bad('this project is being deleted', 409);
    if (up.status === 'done') {
      return j({ ok: true, already: true });
    }
    const state = uploadState(up.parts_json);
    const parts = state.parts
      .sort((a, b) => a.partNumber - b.partNumber);
    const totalParts = Math.ceil(up.size / UPLOAD_PART_SIZE);
    let priorLease = completionLease(up.status);
    if (priorLease && await completedObjectExists(env, up)) {
      await markUploadDone(env, up, up.status);
      return j({ ok: true, recovered: true });
    }
    if (up.status === 'uploading') {
      if (parts.length !== totalParts ||
          parts.some((part, index) => part.partNumber !== index + 1 ||
            !SHA256_PATTERN.test(String(part.sha256 || '')))) {
        return bad('upload is missing one or more parts', 409);
      }
      const recomputed = await multipartFingerprint(
        Number(up.size), parts.map((part) => part.sha256));
      if (recomputed !== state.fingerprint) {
        // Fence this multipart upload before aborting it. A part request that
        // raced with completion can no longer write its receipt back once the
        // status changes. Retain a terminal rejected row for later storage
        // cleanup without letting it block a correctly selected replacement.
        const invalidated = await env.DB.prepare(
          'UPDATE uploads SET status = ? WHERE id = ? AND status = ?')
          .bind('rejected', up.id, up.status).run();
        if (invalidated.meta?.changes !== 1) {
          return bad('this upload changed while it was being checked', 409);
        }
        try {
          await env.MEDIA.resumeMultipartUpload(
            up.r2_key, up.mp_upload_id).abort();
        } catch (_) { /* already expired or concurrently terminated */ }
        // Keep the terminal row and multipart id for later project cleanup.
        // Even if this status refresh fails, rejected is already non-pending
        // and a replacement upload can proceed safely.
        await env.DB.prepare(
          "UPDATE projects SET status = CASE WHEN EXISTS (SELECT 1 FROM uploads " +
          "WHERE project_id = ? AND status = 'done') THEN 'uploaded' " +
          "ELSE 'empty' END, status_detail = '', updated_at = ? " +
          'WHERE id = ? AND delete_token IS NULL AND NOT EXISTS (' +
          'SELECT 1 FROM uploads WHERE project_id = ? ' +
          "AND status NOT IN ('done','rejected'))")
          .bind(up.project_id, now(), up.project_id, up.project_id).run();
        return bad('the uploaded parts do not match the selected file', 422);
      }
    } else if (!priorLease) {
      return bad('this upload cannot be completed from its current state', 409);
    } else if (now() - priorLease.startedAt < UPLOAD_COMPLETION_LEASE_MS) {
      return bad('this upload is still being finished; try again shortly', 409);
    }

    // Claim completion before touching R2. Concurrent requests either see a
    // fresh lease and wait, or take over a stale lease after a crashed Worker.
    const lease = newCompletionLease();
    const claimed = await env.DB.prepare(
      'UPDATE uploads SET status = ? WHERE id = ? AND status = ?')
      .bind(lease, up.id, up.status).run();
    if (!claimed.meta || claimed.meta.changes !== 1) {
      return bad('this upload is already being finished; try again shortly', 409);
    }
    up = { ...up, status: lease };
    const mp = env.MEDIA.resumeMultipartUpload(up.r2_key, up.mp_upload_id);
    try {
      await mp.complete(parts.map((part) => ({
        partNumber: part.partNumber, etag: part.etag,
      })));
    } catch (_) {
      // complete() can succeed while its response is lost. R2 object reads are
      // strongly consistent, so HEAD decides whether to finalize D1 or make
      // this upload immediately retryable.
      if (!(await completedObjectExists(env, up))) {
        await env.DB.prepare(
          "UPDATE uploads SET status = 'uploading' WHERE id = ? " +
          'AND status = ?').bind(up.id, lease).run();
        return bad('could not finish the upload; try again', 503);
      }
    }
    await markUploadDone(env, up, lease);
    return j({ ok: true });
  }

  // ---------- make it / chat / revisions -> jobs
  if ((m = p.match(/^\/projects\/(\w+)\/make$/)) && method === 'POST') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    if (proj.delete_token) return bad('this project is being deleted', 409);
    if (!user.hasKey) return bad('add your DeepSeek key first', 428);
    const ready = await env.DB.prepare(
      'SELECT COUNT(*) AS total, ' +
      "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done, " +
      "SUM(CASE WHEN status NOT IN ('done','rejected') THEN 1 ELSE 0 END) " +
      'AS pending ' +
      'FROM uploads WHERE project_id = ?').bind(proj.id).first();
    if (!ready.total || !ready.done) return bad('upload footage first', 428);
    if (ready.pending) {
      return bad('wait for every selected clip to finish uploading', 409);
    }
    const { script } = await req.json().catch(() => ({}));
    const jobId = uid();
    const createdAt = now();
    try {
      const queued = await env.DB.batch([
        env.DB.prepare(
          'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
          'render_slot,created_at) SELECT ?,?,?,?,?,1,? FROM projects ' +
          'WHERE id = ? AND user_id = ? AND delete_token IS NULL')
          .bind(jobId, proj.id, user.userId, 'make',
            JSON.stringify({ script: script || null }), createdAt,
            proj.id, user.userId),
        env.DB.prepare(
          "UPDATE projects SET status = 'queued', status_detail = '', " +
          'updated_at = ? WHERE id = ? AND EXISTS (' +
          'SELECT 1 FROM jobs WHERE id = ? AND render_slot = 1)')
          .bind(createdAt, proj.id, jobId),
      ]);
      if (queued[0]?.meta?.changes !== 1) {
        return bad('this project cannot start another edit', 409);
      }
    } catch (_) {
      return bad('this project already has an edit in progress', 409);
    }
    return j({ job_id: jobId });
  }

  if ((m = p.match(/^\/projects\/(\w+)\/chat$/)) && method === 'POST') {
    // Instant back-and-forth with DeepSeek, straight from the Worker: no
    // queue, no Helper needed. DeepSeek decides whether the message is
    // conversation (reply now) or an edit request (typed proposal that the
    // deterministic contract validates; sensitive ops wait for an OK).
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    if (proj.delete_token) return bad('this project is being deleted', 409);
    if (!user.hasKey) return bad('add your DeepSeek key first', 428);
    if (!(await withinRateLimit(env, req, `chat:${user.userId}`, 40,
        5 * 60 * 1000))) {
      return bad('slow down a moment and try again', 429);
    }
    const { text } = await req.json().catch(() => ({}));
    if (!text || !text.trim()) return bad('empty request');
    const userMsg = text.slice(0, 2000);
    await env.DB.prepare(
      'INSERT INTO chat_messages (id,project_id,role,content,created_at) ' +
      'VALUES (?,?,?,?,?)')
      .bind(uid(), proj.id, 'user', userMsg, now()).run();

    const krow = await env.DB.prepare(
      'SELECT key_ct, key_iv FROM users WHERE id = ?')
      .bind(user.userId).first();
    let key;
    try { key = await unwrapKey(env, krow.key_ct, krow.key_iv); }
    catch (_) { return bad('your stored key could not be unlocked; ' +
      're-enter it in Settings', 409); }

    const history = ((await env.DB.prepare(
      'SELECT role, content FROM chat_messages WHERE project_id = ? ' +
      'ORDER BY created_at DESC LIMIT 10').bind(proj.id).all())
      .results || []).reverse();
    const revs = ((await env.DB.prepare(
      'SELECT num, request_text, status, qa_pass FROM revisions ' +
      'WHERE project_id = ? ORDER BY num').bind(proj.id).all())
      .results || []);
    const contract = Object.fromEntries(Object.entries(ALLOWED_OPS)
      .map(([name, spec]) => [name, spec.params]));
    const sys = { role: 'system', content:
      'You are the creative editing partner inside AutoEditor. You work ' +
      'WITH the person, back and forth, until their video is right. ' +
      `Project type: ${proj.type}. ` +
      `Transcript excerpt: ${(proj.transcript || '(none yet)')
        .slice(0, 1500)}. ` +
      `Revisions so far: ${JSON.stringify(revs).slice(0, 600)}. ` +
      'Respond with ONLY a JSON object, one of:\n' +
      '{"mode":"reply","text":"<conversational answer, advice, options, ' +
      'or clarifying question>"}\n' +
      '{"mode":"edit","summary":"<one sentence>","operations":[...]}\n' +
      'Use mode "edit" ONLY when they clearly asked for a change. Allowed ' +
      `operations (use ONLY these, max 8): ${JSON.stringify(contract)}. ` +
      'If their request needs an operation that does not exist, use mode ' +
      '"reply" to say what you CAN do instead. Be warm, specific, concise.' };
    const msgs = [sys, ...history.map((h) => ({ role: h.role === 'user'
      ? 'user' : 'assistant', content: h.content.slice(0, 1500) }))];
    const res = await deepseekChat(key, msgs,
      { model: 'deepseek-v4-pro', max_tokens: 900 });
    key = null;
    if (!res.ok) {
      return bad('DeepSeek did not respond (key out of credit?). Try ' +
        'again in a moment.', 502);
    }
    let parsed = null;
    try {
      parsed = JSON.parse(res.text.slice(res.text.indexOf('{'),
        res.text.lastIndexOf('}') + 1));
    } catch (_) { parsed = { mode: 'reply', text: res.text.slice(0, 1500) }; }

    if (parsed.mode === 'edit') {
      const { clean, needsApproval, errors } = validateProposal(parsed);
      if (!clean) {
        const msg = 'I couldn\'t turn that into a safe edit ' +
          `(${(errors || []).join('; ').slice(0, 150)}). Tell me more ` +
          'about what you want and we\'ll get there.';
        await env.DB.prepare(
          'INSERT INTO chat_messages (id,project_id,role,content,' +
          'created_at) VALUES (?,?,?,?,?)')
          .bind(uid(), proj.id, 'assistant', msg, now()).run();
        return j({ reply: msg });
      }
      const revId = uid();
      const createdAt = now();
      const revisionInsert = env.DB.prepare(
        'INSERT INTO revisions (id,project_id,num,request_text,' +
        'proposal_json,needs_approval,status,created_at) ' +
        'SELECT ?,?,(SELECT COALESCE(MAX(num),0)+1 FROM revisions ' +
        'WHERE project_id = ?),?,?,?,?,?')
        .bind(revId, proj.id, proj.id, userMsg,
          JSON.stringify(clean), needsApproval ? 1 : 0,
          needsApproval ? 'proposed' : 'approved', createdAt);
      const summary = clean.summary ||
        'Here\'s what I\'ll change.';
      const chatInsert = env.DB.prepare(
        'INSERT INTO chat_messages (id,project_id,role,content,' +
        'created_at) VALUES (?,?,?,?,?)')
        .bind(uid(), proj.id, 'assistant', summary, createdAt);
      if (needsApproval) {
        await env.DB.batch([
          revisionInsert,
          chatInsert,
          env.DB.prepare(
            "UPDATE projects SET status = 'awaiting approval', " +
            "status_detail = '', updated_at = ? WHERE id = ?")
            .bind(createdAt, proj.id),
        ]);
        return j({ reply: summary, proposal: clean, revision_id: revId,
          needs_approval: true });
      }
      // Visual-only proposals create the approved revision and its job in one
      // transaction. There is no approved-without-render state to recover.
      const jobId = `revision_apply_${revId}`;
      try {
        await env.DB.batch([
          revisionInsert,
          chatInsert,
          env.DB.prepare(
            'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
            'render_slot,created_at) SELECT ?,?,?,?,?,1,? FROM projects ' +
            'WHERE id = ? AND user_id = ? AND delete_token IS NULL')
            .bind(jobId, proj.id, user.userId, 'revision_apply',
              JSON.stringify({ revision_id: revId, proposal: clean }), createdAt,
              proj.id, user.userId),
          env.DB.prepare(
            "UPDATE projects SET status = 'applying revision', " +
            "status_detail = '', updated_at = ? WHERE id = ? AND EXISTS (" +
            'SELECT 1 FROM jobs WHERE id = ? AND render_slot = 1)')
            .bind(createdAt, proj.id, jobId),
        ]);
      } catch (_) {
        return bad('finish the current edit before applying another one', 409);
      }
      return j({ reply: summary + ' Applying it now. Keep your Helper ' +
        'open to render.', proposal: clean, revision_id: revId,
      needs_approval: false });
    }

    const replyText = String(parsed.text || 'Tell me more.').slice(0, 2000);
    await env.DB.prepare(
      'INSERT INTO chat_messages (id,project_id,role,content,created_at) ' +
      'VALUES (?,?,?,?,?)')
      .bind(uid(), proj.id, 'assistant', replyText, now()).run();
    return j({ reply: replyText });
  }

  if ((m = p.match(/^\/revisions\/(\w+)\/(approve|reject)$/))
      && method === 'POST') {
    const rev = await env.DB.prepare(
      'SELECT r.*, p.user_id, p.delete_token FROM revisions r JOIN projects p ' +
      'ON p.id = r.project_id WHERE r.id = ?').bind(m[1]).first();
    if (!rev || rev.user_id !== user.userId) return bad('not found', 404);
    if (rev.delete_token) return bad('this project is being deleted', 409);
    if (rev.status !== 'proposed') return bad('already resolved');
    if (m[2] === 'reject') {
      const rejected = await env.DB.batch([
        env.DB.prepare(
          "UPDATE revisions SET status = 'rejected' WHERE id = ? " +
          "AND status = 'proposed'").bind(rev.id),
        env.DB.prepare(
          "UPDATE projects SET status = 'ready', status_detail = '', " +
          'updated_at = ? WHERE id = ? AND NOT EXISTS (' +
          'SELECT 1 FROM jobs WHERE project_id = ? AND (' +
          "status IN ('queued','running') OR status LIKE 'finishing:%')) " +
          'AND NOT EXISTS (SELECT 1 FROM revisions WHERE project_id = ? ' +
          "AND status = 'proposed')")
          .bind(now(), rev.project_id, rev.project_id, rev.project_id),
      ]);
      if (rejected[0]?.meta?.changes !== 1) {
        return bad('already resolved');
      }
      return j({ ok: true });
    }
    // The deterministic job id makes a concurrent replay collide inside the
    // same D1 transaction. If the job insert fails, approval rolls back.
    let storedProposal;
    try { storedProposal = JSON.parse(rev.proposal_json || 'null'); }
    catch (_) { return bad('stored proposal is invalid; ask for a new edit', 422); }
    const validated = validateProposal(storedProposal);
    if (!validated.clean) {
      return bad('stored proposal is invalid; ask for a new edit', 422);
    }
    const approvedProposal = validated.clean;
    const jobId = `revision_apply_${rev.id}`;
    let approval;
    try {
      approval = await env.DB.batch([
        env.DB.prepare(
          "UPDATE revisions SET status = 'approved', proposal_json = ? " +
          "WHERE id = ? AND status = 'proposed'")
          .bind(JSON.stringify(approvedProposal), rev.id),
        env.DB.prepare(
          'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
          'render_slot,created_at) SELECT ?,?,?,?,?,1,? FROM revisions ' +
          'JOIN projects ON projects.id = revisions.project_id ' +
          'WHERE revisions.id = ? AND revisions.status = \'approved\' ' +
          'AND projects.delete_token IS NULL')
          .bind(jobId, rev.project_id, user.userId, 'revision_apply',
            JSON.stringify({ revision_id: rev.id,
              proposal: approvedProposal }), now(), rev.id),
        env.DB.prepare(
          "UPDATE projects SET status = 'applying revision', " +
          "status_detail = '', updated_at = ? WHERE id = ? AND EXISTS (" +
          'SELECT 1 FROM jobs WHERE id = ?)')
          .bind(now(), rev.project_id, jobId),
      ]);
    } catch (_) {
      const current = await env.DB.prepare(
        'SELECT status FROM revisions WHERE id = ?').bind(rev.id).first();
      if (current && current.status !== 'proposed') {
        return bad('already resolved');
      }
      return bad('could not queue this revision; try again', 503);
    }
    if (approval[0]?.meta?.changes !== 1 ||
        approval[1]?.meta?.changes !== 1) return bad('already resolved');
    return j({ job_id: jobId });
  }

  // ---------- media reads: authenticated streaming, never public
  if ((m = p.match(/^\/media\/(.+)$/)) && method === 'GET') {
    const key = decodeURIComponent(m[1]);
    if (!key.startsWith(`u/${user.userId}/`)) return bad('forbidden', 403);
    const rangeRequested = req.headers.has('range');
    const obj = rangeRequested
      ? await env.MEDIA.get(key, { range: req.headers })
      : await env.MEDIA.get(key);
    if (!obj) return bad('not found', 404);
    const headers = { 'content-type': 'video/mp4',
      'accept-ranges': 'bytes', 'cache-control': 'private, no-store',
      // media keys embed u/<userId>/<projectId>/... — no-referrer stops
      // those paths leaking via the Referer header off-site.
      'referrer-policy': 'no-referrer',
      'strict-transport-security': 'max-age=31536000; includeSubDomains',
      'x-content-type-options': 'nosniff' };
    if (rangeRequested && obj.range) {
      headers['content-range'] =
        `bytes ${obj.range.offset}-${obj.range.offset + obj.range.length - 1}` +
        `/${obj.size}`;
      headers['content-length'] = String(obj.range.length);
      return new Response(obj.body, { status: 206, headers });
    }
    headers['content-length'] = String(obj.size);
    return new Response(obj.body, { headers });
  }

  return bad('no such endpoint', 404);
}

// ------------------------------------------------------------- daemon API
async function verifiedRenderResult(env, job, body, revisionId) {
  const claimToken = String(body.claim_token || '');
  const upload = await env.DB.prepare(
    'SELECT * FROM render_uploads WHERE job_id = ? AND claim_token = ? ' +
    "AND status = 'done'").bind(job.id, claimToken).first();
  if (!upload || body.output_key !== upload.r2_key ||
      body.qa_key !== upload.qa_key) {
    throw new Error('render artifact paths do not match this claim');
  }
  const expected = expectedRenderKeys(job, claimToken,
    upload.multipart_sha256);
  if (upload.r2_key !== expected.outputKey || upload.qa_key !== expected.qaKey) {
    throw new Error('render receipt is not bound to this job attempt');
  }
  if (job.kind === 'revision_apply' && renderTag(job) !== revisionId) {
    throw new Error('render receipt is not bound to this revision');
  }
  const [output, qaObject] = await Promise.all([
    env.MEDIA.head(upload.r2_key),
    env.MEDIA.get(upload.qa_key),
  ]);
  const qaHash = qaObject?.customMetadata?.sha256 || '';
  if (!output || Number(output.size) !== Number(upload.size) ||
      output.customMetadata?.claim_token !== claimToken ||
      output.customMetadata?.multipart_sha256 !== upload.multipart_sha256 ||
      output.customMetadata?.content_sha256 !== upload.content_sha256 ||
      (upload.r2_etag && output.etag !== upload.r2_etag) || !qaObject ||
      Number(qaObject.size) <= 0 || Number(qaObject.size) > MAX_QA_BYTES ||
      !SHA256_PATTERN.test(qaHash) ||
      checksumHex(qaObject.checksums?.sha256) !== qaHash ||
      qaObject.customMetadata?.claim_token !== claimToken ||
      qaObject.customMetadata?.multipart_sha256 !== upload.multipart_sha256) {
    throw new Error('render output or QA receipt is missing');
  }
  const qaBytes = await qaObject.arrayBuffer();
  if (await sha256Hex(qaBytes) !== qaHash) {
    throw new Error('QA receipt bytes do not match their SHA-256 receipt');
  }
  let report;
  try { report = JSON.parse(new TextDecoder().decode(qaBytes)); }
  catch (_) { throw new Error('QA receipt is not valid JSON'); }
  const release = report && typeof report.release === 'object'
    ? Object.values(report.release) : [];
  const binding = report?._autoeditor;
  if (typeof report?.pass !== 'boolean' ||
      !report.checks || typeof report.checks !== 'object' ||
      !release.some((item) => item &&
        item.sha256 === upload.content_sha256) ||
      !binding || binding.claim_token !== claimToken ||
      binding.output_key !== upload.r2_key ||
      binding.output_content_sha256 !== upload.content_sha256 ||
      binding.output_multipart_sha256 !== upload.multipart_sha256 ||
      Number(binding.output_size) !== Number(upload.size)) {
    throw new Error('QA receipt is not bound to the rendered MP4');
  }
  return { outputKey: body.output_key, qaKey: body.qa_key,
    qaPass: report.pass };
}

async function completeWorkerJob(env, scope, jobId, body, requestHash) {
  const job = await env.DB.prepare('SELECT * FROM jobs WHERE id = ?')
    .bind(jobId).first();
  if (!job) return bad('no job', 404);
  if (!workerOwnsJob(scope, job)) return bad('forbidden', 403);
  if ((job.status === 'done' || job.status === 'failed') &&
      job.completion_request_hash === requestHash &&
      job.completion_receipt_json) {
    return exactJson(job.completion_receipt_json, 409);
  }
  const claimToken = String(body.claim_token || '');
  if (job.status !== 'running' || !claimToken ||
      job.claim_token !== claimToken ||
      Number(job.lease_expires_at || 0) < now()) {
    return bad('job claim is not active', 409);
  }

  const succeeded = body.ok === true;
  let safeProposal = null;
  let safeNeedsApproval = false;
  let targetRevisionId = null;
  if (job.kind === 'chat_proposal' && succeeded &&
      body.proposal && (body.proposal.operations || []).length) {
    const checked = validateProposal(body.proposal);
    if (!checked.clean) return bad('unsafe edit proposal rejected', 422);
    safeProposal = checked.clean;
    safeNeedsApproval = checked.needsApproval;
  }
  if (job.kind === 'revision_apply' && succeeded) {
    let payload = {};
    try { payload = JSON.parse(job.payload_json || '{}'); } catch (_) { }
    const revision = await env.DB.prepare(
      'SELECT id FROM revisions WHERE id = ? AND project_id = ?')
      .bind(payload.revision_id || '', job.project_id).first();
    if (!revision) return bad('revision does not belong to this job', 409);
    targetRevisionId = revision.id;
  }
  if (!['transcribe', 'chat_proposal', 'make', 'revision_apply']
    .includes(job.kind)) return bad('unknown job kind', 409);

  let render = null;
  if (succeeded && (job.kind === 'make' || job.kind === 'revision_apply')) {
    try {
      render = await verifiedRenderResult(
        env, job, body, targetRevisionId);
    } catch (_) {
      return bad('render output failed its QA receipt', 422);
    }
  } else if (!jobOwnsMediaKey(job, body.output_key) ||
      !jobOwnsMediaKey(job, body.qa_key)) {
    return bad('output path does not belong to this job', 403);
  }

  const lease = `finishing:${claimToken}:${uid()}`;
  const timestamp = now();
  const receipt = completionReceipt(job.id, requestHash);
  const statements = [env.DB.prepare(
    "UPDATE jobs SET status = ? WHERE id = ? AND status = 'running' " +
    'AND claim_token = ? AND lease_expires_at >= ?')
    .bind(lease, job.id, claimToken, timestamp)];
  const required = [];
  const add = (statement) => {
    required.push(statements.length);
    statements.push(statement);
  };
  const guard = 'EXISTS (SELECT 1 FROM jobs WHERE id = ? AND status = ?)';

  if (!succeeded) {
    add(env.DB.prepare(
      "UPDATE projects SET status = 'failed', status_detail = ?, " +
      'updated_at = ? WHERE id = ? AND ' + guard)
      .bind(String(body.error || 'unknown error').slice(0, 300), timestamp,
        job.project_id, job.id, lease));
  } else if (job.kind === 'transcribe') {
    add(env.DB.prepare(
      "UPDATE projects SET transcript = ?, status = 'transcript needs attention', " +
      "status_detail = '', updated_at = ? WHERE id = ? AND " + guard)
      .bind(String(body.transcript || '').slice(0, 250000), timestamp,
        job.project_id, job.id, lease));
  } else if (job.kind === 'chat_proposal' && !safeProposal) {
    add(env.DB.prepare(
      'INSERT INTO chat_messages (id,project_id,role,content,created_at) ' +
      'SELECT ?,?,?,?,? WHERE ' + guard)
      .bind(uid(), job.project_id, 'assistant',
        String(body.summary || 'No change could be planned.').slice(0, 2000),
        timestamp, job.id, lease));
    add(env.DB.prepare(
      "UPDATE projects SET status = 'ready', status_detail = '', " +
      'updated_at = ? WHERE id = ? AND ' + guard)
      .bind(timestamp, job.project_id, job.id, lease));
  } else if (job.kind === 'chat_proposal') {
    const revId = uid();
    const revisionStatus = safeNeedsApproval ? 'proposed' : 'approved';
    add(env.DB.prepare(
      'INSERT INTO revisions (id,project_id,num,request_text,proposal_json,' +
      'needs_approval,status,created_at) SELECT ?,?,(' +
      'SELECT COALESCE(MAX(num),0)+1 FROM revisions WHERE project_id = ?),' +
      '?,?,?,?,? WHERE ' + guard)
      .bind(revId, job.project_id, job.project_id,
        String(body.request_text || '').slice(0, 2000),
        JSON.stringify(safeProposal), safeNeedsApproval ? 1 : 0,
        revisionStatus, timestamp, job.id, lease));
    add(env.DB.prepare(
      'INSERT INTO chat_messages (id,project_id,role,content,created_at) ' +
      'SELECT ?,?,?,?,? WHERE ' + guard)
      .bind(uid(), job.project_id, 'assistant',
        String(body.summary || 'Proposal ready.').slice(0, 2000),
        timestamp, job.id, lease));
    if (safeNeedsApproval) {
      add(env.DB.prepare(
        "UPDATE projects SET status = 'awaiting approval', status_detail = '', " +
        'updated_at = ? WHERE id = ? AND ' + guard)
        .bind(timestamp, job.project_id, job.id, lease));
    } else {
      const applyJobId = `revision_apply_${revId}`;
      add(env.DB.prepare(
        'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
        'render_slot,created_at) SELECT ?,?,?,?,?,1,? WHERE ' + guard)
        .bind(applyJobId, job.project_id, job.user_id, 'revision_apply',
          JSON.stringify({ revision_id: revId, proposal: safeProposal }),
          timestamp, job.id, lease));
      add(env.DB.prepare(
        "UPDATE projects SET status = 'applying revision', status_detail = '', " +
        'updated_at = ? WHERE id = ? AND ' + guard)
        .bind(timestamp, job.project_id, job.id, lease));
    }
  } else {
    const revId = job.kind === 'revision_apply' ? targetRevisionId : uid();
    if (job.kind === 'make') {
      add(env.DB.prepare(
        'INSERT INTO revisions (id,project_id,num,request_text,status,created_at) ' +
        'SELECT ?,?,(SELECT COALESCE(MAX(num),0)+1 FROM revisions ' +
        'WHERE project_id = ?),?,?,? WHERE ' + guard)
        .bind(revId, job.project_id, job.project_id, 'Initial edit',
          'applied', timestamp, job.id, lease));
    }
    add(env.DB.prepare(
      "UPDATE revisions SET status = 'applied', output_key = ?, qa_key = ?, " +
      'qa_pass = ? WHERE id = ? AND project_id = ? AND ' + guard)
      .bind(render.outputKey, render.qaKey, render.qaPass ? 1 : 0,
        revId, job.project_id, job.id, lease));
    add(env.DB.prepare(
      "UPDATE projects SET status = ?, status_detail = '', updated_at = ? " +
      'WHERE id = ? AND ' + guard)
      .bind(render.qaPass ? 'ready' : 'needs review', timestamp,
        job.project_id, job.id, lease));
  }

  const finalIndex = statements.length;
  statements.push(env.DB.prepare(
    'UPDATE jobs SET status = ?, finished_at = ?, error = ?, ' +
    'claim_token = NULL, lease_expires_at = NULL, render_slot = 0, ' +
    'completion_request_hash = ?, completion_receipt_json = ? ' +
    'WHERE id = ? AND status = ?')
    .bind(succeeded ? 'done' : 'failed', timestamp,
      succeeded ? null : String(body.error || 'unknown error').slice(0, 300),
      requestHash, receipt, job.id, lease));
  let results;
  try { results = await env.DB.batch(statements); }
  catch (_) { return bad('could not record job completion; retry', 503); }
  if (results[0]?.meta?.changes !== 1) {
    return bad('job is not running', 409);
  }
  if (results[finalIndex]?.meta?.changes !== 1 ||
      required.some((index) => results[index]?.meta?.changes !== 1)) {
    // All statements ran in one D1 transaction. This path is defensive; the
    // guarded rows are required to exist while a running job owns the project.
    return bad('job completion did not record every required effect', 503);
  }
  return exactJson(receipt);
}

async function workerApi(req, env, p, method, scope) {
  let m;
  if (p === '/worker/next-job' && method === 'POST') {
    const timestamp = now();
    // Expired attempts at the retry cap are terminal. Releasing render_slot
    // is what makes a deliberate user retry possible without overlapping the
    // abandoned daemon attempt.
    await env.DB.batch([
      env.DB.prepare(
        "UPDATE projects SET status = 'failed', " +
        "status_detail = 'Helper lost the job three times; start it again', " +
        'updated_at = ? WHERE EXISTS (SELECT 1 FROM jobs WHERE ' +
        "jobs.project_id = projects.id AND jobs.status = 'running' " +
        'AND jobs.lease_expires_at < ? AND jobs.attempt_count >= ?)')
        .bind(timestamp, timestamp, JOB_MAX_ATTEMPTS),
      env.DB.prepare(
        "UPDATE jobs SET status = 'failed', render_slot = 0, " +
        "error = 'claim retry limit reached', finished_at = ?, " +
        'claim_token = NULL, lease_expires_at = NULL ' +
        "WHERE status = 'running' AND lease_expires_at < ? " +
        'AND attempt_count >= ?')
        .bind(timestamp, timestamp, JOB_MAX_ATTEMPTS),
    ]);
    const job = scope.scope === 'user'
      ? await env.DB.prepare(
        'SELECT j.* FROM jobs j JOIN projects p ON p.id = j.project_id ' +
        "WHERE (j.status = 'queued' OR (j.status = 'running' AND " +
        'j.lease_expires_at < ?)) AND j.attempt_count < ? AND ' +
        'p.delete_token IS NULL AND j.user_id = ? ' +
        "ORDER BY CASE j.status WHEN 'queued' THEN 0 ELSE 1 END, j.created_at " +
        'LIMIT 1').bind(timestamp, JOB_MAX_ATTEMPTS, scope.userId).first()
      : await env.DB.prepare(
        'SELECT j.* FROM jobs j JOIN projects p ON p.id = j.project_id ' +
        "WHERE (j.status = 'queued' OR (j.status = 'running' AND " +
        'j.lease_expires_at < ?)) AND j.attempt_count < ? ' +
        'AND p.delete_token IS NULL ' +
        "ORDER BY CASE j.status WHEN 'queued' THEN 0 ELSE 1 END, j.created_at " +
        'LIMIT 1').bind(timestamp, JOB_MAX_ATTEMPTS).first();
    if (!job) return j({ job: null });
    const claimToken = uid();
    const leaseExpiresAt = timestamp + JOB_LEASE_MS;
    const claim = await env.DB.prepare(
      "UPDATE jobs SET status = 'running', started_at = COALESCE(started_at, ?), " +
      'claim_token = ?, lease_expires_at = ?, attempt_count = attempt_count + 1 ' +
      'WHERE id = ? AND status = ? AND COALESCE(claim_token,\'\') = ? ' +
      'AND COALESCE(lease_expires_at,0) = ? AND attempt_count = ? ' +
      'AND attempt_count < ? AND EXISTS (SELECT 1 FROM projects ' +
      'WHERE projects.id = jobs.project_id AND delete_token IS NULL)')
      .bind(timestamp, claimToken, leaseExpiresAt, job.id, job.status,
        job.claim_token || '', Number(job.lease_expires_at || 0),
        Number(job.attempt_count || 0), JOB_MAX_ATTEMPTS).run();
    if (!claim.meta || claim.meta.changes !== 1) return j({ job: null });
    const claimedJobRow = await env.DB.prepare('SELECT * FROM jobs WHERE id = ?')
      .bind(job.id).first();
    const abandoned = await env.DB.prepare(
      'SELECT * FROM render_uploads WHERE job_id = ? AND claim_token != ? ' +
      "AND status IN ('uploading','completing')")
      .bind(job.id, claimToken).all();
    for (const upload of (abandoned.results || [])) {
      try {
        await env.MEDIA.resumeMultipartUpload(
          upload.r2_key, upload.mp_upload_id).abort();
      } catch (_) { /* already expired or completed */ }
      await env.DB.prepare(
        "UPDATE render_uploads SET status = 'abandoned' " +
        'WHERE job_id = ? AND claim_token = ? AND status != \'done\'')
        .bind(job.id, upload.claim_token).run();
    }
    const proj = await env.DB.prepare(
      'SELECT * FROM projects WHERE id = ?').bind(job.project_id).first();
    const uploads = await env.DB.prepare(
      "SELECT r2_key, filename FROM uploads WHERE project_id = ? " +
      "AND status = 'done' ORDER BY created_at").bind(job.project_id).all();
    const u = await env.DB.prepare(
      'SELECT key_ct, key_iv FROM users WHERE id = ?')
      .bind(job.user_id).first();
    const preset = proj.style_preset_id ? await env.DB.prepare(
      'SELECT name, params_json FROM style_presets WHERE id = ? AND user_id = ?')
      .bind(proj.style_preset_id, job.user_id).first() : null;
    // user-scoped helper: hand the user their OWN key over TLS (no KEK
    // distribution). Global daemon: ciphertext only + local KEK.
    let key_plain = null;
    if (scope.scope === 'user' && u && u.key_ct) {
      try { key_plain = await unwrapKey(env, u.key_ct, u.key_iv); }
      catch (_) { key_plain = null; }
    }
    return j({ job: claimedJobRow, project: proj, uploads: uploads.results || [],
      key_ct: scope.scope === 'global' && u ? u.key_ct : null,
      key_iv: scope.scope === 'global' && u ? u.key_iv : null,
      key_plain, preset });
  }
  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/progress$/))
      && method === 'POST') {
    const body = await req.json().catch(() => ({}));
    const { line, status, detail } = body;
    const claimToken = claimTokenFrom(req, body);
    const job = await claimedJob(env, scope, m[1], claimToken);
    if (!job) return bad('job claim is not active', 409);
    const prog = JSON.parse(job.progress_json || '[]');
    if (line) prog.push(String(line).slice(0, 300));
    const timestamp = now();
    const heartbeat = line
      ? await env.DB.prepare(
        'UPDATE jobs SET progress_json = ?, lease_expires_at = ? WHERE id = ? ' +
        "AND status = 'running' AND claim_token = ? AND lease_expires_at >= ?")
        .bind(JSON.stringify(prog.slice(-200)), timestamp + JOB_LEASE_MS,
          job.id, claimToken, timestamp).run()
      : await env.DB.prepare(
        'UPDATE jobs SET lease_expires_at = ? WHERE id = ? ' +
        "AND status = 'running' AND claim_token = ? AND lease_expires_at >= ?")
        .bind(timestamp + JOB_LEASE_MS, job.id, claimToken, timestamp).run();
    if (heartbeat.meta?.changes !== 1) return bad('job claim is not active', 409);
    const allowedStatuses = new Set([
      'transcribing', 'planning', 'gathering resources', 'rendering preview',
      'running final qa',
    ]);
    if (status && !allowedStatuses.has(status)) return bad('invalid status');
    if (status) {
      await env.DB.prepare(
        'UPDATE projects SET status = ?, status_detail = ?, updated_at = ? ' +
        'WHERE id = ? AND delete_token IS NULL AND EXISTS (' +
        'SELECT 1 FROM jobs WHERE id = ? AND status = \'running\' ' +
        'AND claim_token = ?)')
        .bind(status, String(detail || '').slice(0, 300), timestamp,
          job.project_id, job.id, claimToken).run();
    }
    return j({ ok: true });
  }
  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/complete$/))
      && method === 'POST') {
    const requestBytes = await req.arrayBuffer();
    const requestHash = await sha256Hex(requestBytes);
    let body;
    try { body = JSON.parse(new TextDecoder().decode(requestBytes)); }
    catch (_) { return bad('completion receipt is not valid JSON'); }
    return completeWorkerJob(env, scope, m[1], body, requestHash);
  }

  // Large render outputs use claim-bound R2 multipart uploads. Every part is
  // independently hashed, the ordered part receipt is fixed before upload,
  // and the completed R2 stream is hashed again before D1 records success.
  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/output\/start$/)) &&
      method === 'POST') {
    const body = await req.json().catch(() => ({}));
    const claimToken = claimTokenFrom(req, body);
    const job = await claimedJob(env, scope, m[1], claimToken);
    if (!job) return bad('job claim is not active', 409);
    if (!['make', 'revision_apply'].includes(job.kind)) {
      return bad('this job does not create a video', 409);
    }
    const size = Number(body.size);
    const contentHash = String(body.content_sha256 || '');
    const partHashes = body.part_hashes;
    const partCount = Math.ceil(size / OUTPUT_PART_SIZE);
    if (!Number.isSafeInteger(size) || size <= 0 || size > MAX_OUTPUT_BYTES ||
        !Number.isInteger(partCount) || partCount < 1 ||
        partCount > MAX_OUTPUT_PARTS || !SHA256_PATTERN.test(contentHash) ||
        !Array.isArray(partHashes) || partHashes.length !== partCount ||
        partHashes.some((hash) => !SHA256_PATTERN.test(String(hash)))) {
      return bad('render upload receipt is invalid');
    }
    const multipartHash = await multipartFingerprint(size, partHashes);
    const keys = expectedRenderKeys(job, claimToken, multipartHash);
    const existing = await env.DB.prepare(
      'SELECT * FROM render_uploads WHERE job_id = ? AND claim_token = ?')
      .bind(job.id, claimToken).first();
    if (existing) {
      if (Number(existing.size) !== size ||
          existing.content_sha256 !== contentHash ||
          existing.multipart_sha256 !== multipartHash ||
          existing.r2_key !== keys.outputKey) {
        return bad('this claim already started a different output', 409);
      }
      let uploaded = [];
      try { uploaded = JSON.parse(existing.uploaded_parts_json || '[]'); }
      catch (_) { uploaded = []; }
      return j({ output_key: existing.r2_key, qa_key: existing.qa_key,
        part_size: OUTPUT_PART_SIZE,
        uploaded_parts: uploaded.map((part) => part.partNumber),
        status: existing.status, resumed: true });
    }
    const mp = await env.MEDIA.createMultipartUpload(keys.outputKey, {
      customMetadata: { claim_token: claimToken,
        content_sha256: contentHash, multipart_sha256: multipartHash,
        job_id: job.id },
      httpMetadata: { contentType: 'video/mp4' },
    });
    let inserted;
    try {
      inserted = await env.DB.prepare(
        'INSERT INTO render_uploads (job_id,claim_token,r2_key,qa_key,' +
        'mp_upload_id,size,content_sha256,multipart_sha256,' +
        'expected_parts_json,uploaded_parts_json,status,created_at) ' +
        "SELECT ?,?,?,?,?,?,?,?,?,?,'uploading',? WHERE EXISTS (" +
        'SELECT 1 FROM jobs WHERE id = ? AND status = \'running\' ' +
        'AND claim_token = ? AND lease_expires_at >= ?)')
        .bind(job.id, claimToken, keys.outputKey, keys.qaKey, mp.uploadId,
          size, contentHash, multipartHash, JSON.stringify(partHashes), '[]',
          now(), job.id, claimToken, now()).run();
    } catch (_) { inserted = null; }
    if (inserted?.meta?.changes !== 1) {
      try { await mp.abort(); } catch (_) { }
      return bad('job claim expired before output upload started', 409);
    }
    return j({ output_key: keys.outputKey, qa_key: keys.qaKey,
      part_size: OUTPUT_PART_SIZE, uploaded_parts: [],
      status: 'uploading', resumed: false });
  }

  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/output\/part$/)) &&
      method === 'PUT') {
    const claimToken = claimTokenFrom(req);
    const job = await claimedJob(env, scope, m[1], claimToken);
    if (!job) return bad('job claim is not active', 409);
    const upload = await env.DB.prepare(
      'SELECT * FROM render_uploads WHERE job_id = ? AND claim_token = ?')
      .bind(job.id, claimToken).first();
    if (!upload || upload.status !== 'uploading') {
      return bad('render upload is not accepting parts', 409);
    }
    let expectedHashes;
    try { expectedHashes = JSON.parse(upload.expected_parts_json); }
    catch (_) { return bad('render upload receipt is damaged', 500); }
    const partNumber = Number(new URL(req.url).searchParams.get('n'));
    if (!Number.isInteger(partNumber) || partNumber < 1 ||
        partNumber > expectedHashes.length) return bad('part number out of range');
    const expectedBytes = partNumber === expectedHashes.length
      ? Number(upload.size) - ((expectedHashes.length - 1) * OUTPUT_PART_SIZE)
      : OUTPUT_PART_SIZE;
    const declaredBytes = Number(req.headers.get('content-length'));
    const declaredHash = req.headers.get('x-autoeditor-part-sha256') || '';
    if (!Number.isSafeInteger(declaredBytes) || declaredBytes !== expectedBytes) {
      return bad('render part has the wrong size', 400);
    }
    if (declaredHash !== expectedHashes[partNumber - 1]) {
      return bad('render part does not match the fixed receipt', 422);
    }
    const bytes = await req.arrayBuffer();
    if (bytes.byteLength !== expectedBytes ||
        await sha256Hex(bytes) !== declaredHash) {
      return bad('render part failed its SHA-256 receipt', 422);
    }
    const mp = env.MEDIA.resumeMultipartUpload(
      upload.r2_key, upload.mp_upload_id);
    const uploadedPart = await mp.uploadPart(partNumber, bytes);
    let uploaded;
    try { uploaded = JSON.parse(upload.uploaded_parts_json || '[]'); }
    catch (_) { uploaded = []; }
    uploaded = uploaded.filter((part) => part.partNumber !== partNumber);
    uploaded.push({ partNumber, etag: uploadedPart.etag,
      sha256: declaredHash });
    const saved = await env.DB.prepare(
      'UPDATE render_uploads SET uploaded_parts_json = ? WHERE job_id = ? ' +
      "AND claim_token = ? AND status = 'uploading'")
      .bind(JSON.stringify(uploaded), job.id, claimToken).run();
    if (saved.meta?.changes !== 1) {
      return bad('render upload stopped accepting parts', 409);
    }
    return j({ ok: true, part: partNumber });
  }

  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/output\/complete$/)) &&
      method === 'POST') {
    const body = await req.json().catch(() => ({}));
    const claimToken = claimTokenFrom(req, body);
    const job = await claimedJob(env, scope, m[1], claimToken);
    if (!job) return bad('job claim is not active', 409);
    let upload = await env.DB.prepare(
      'SELECT * FROM render_uploads WHERE job_id = ? AND claim_token = ?')
      .bind(job.id, claimToken).first();
    if (!upload) return bad('render upload was not started', 404);
    const receipt = () => ({ ok: true, output_key: upload.r2_key,
      qa_key: upload.qa_key, size: Number(upload.size),
      content_sha256: upload.content_sha256,
      multipart_sha256: upload.multipart_sha256,
      etag: upload.r2_etag || null });
    if (upload.status === 'done') {
      const object = await env.MEDIA.head(upload.r2_key);
      if (!object || Number(object.size) !== Number(upload.size) ||
          object.etag !== upload.r2_etag) {
        return bad('completed render is missing from storage', 503);
      }
      return j(receipt());
    }
    let expectedHashes, uploadedParts;
    try {
      expectedHashes = JSON.parse(upload.expected_parts_json);
      uploadedParts = JSON.parse(upload.uploaded_parts_json || '[]')
        .sort((a, b) => a.partNumber - b.partNumber);
    } catch (_) { return bad('render upload receipt is damaged', 500); }
    if (uploadedParts.length !== expectedHashes.length ||
        uploadedParts.some((part, index) =>
          part.partNumber !== index + 1 || part.sha256 !== expectedHashes[index])) {
      return bad('render upload is missing one or more parts', 409);
    }
    if (await multipartFingerprint(Number(upload.size), expectedHashes) !==
        upload.multipart_sha256) {
      return bad('render multipart receipt is invalid', 422);
    }
    const timestamp = now();
    if (upload.status === 'completing' &&
        Number(upload.completion_lease_expires_at || 0) >= timestamp) {
      return bad('render upload is still being finished', 409);
    }
    if (!['uploading', 'completing'].includes(upload.status)) {
      return bad('render upload cannot be completed', 409);
    }
    const completionToken = uid();
    const claimed = await env.DB.prepare(
      "UPDATE render_uploads SET status = 'completing', " +
      'completion_token = ?, completion_lease_expires_at = ? ' +
      'WHERE job_id = ? AND claim_token = ? AND status = ? ' +
      'AND COALESCE(completion_lease_expires_at,0) = ?')
      .bind(completionToken, timestamp + OUTPUT_COMPLETION_LEASE_MS,
        job.id, claimToken, upload.status,
        Number(upload.completion_lease_expires_at || 0)).run();
    if (claimed.meta?.changes !== 1) {
      return bad('render upload was claimed by another request', 409);
    }
    const mp = env.MEDIA.resumeMultipartUpload(
      upload.r2_key, upload.mp_upload_id);
    let object;
    try {
      object = await mp.complete(uploadedParts.map((part) => ({
        partNumber: part.partNumber, etag: part.etag,
      })));
    } catch (_) {
      object = await env.MEDIA.head(upload.r2_key);
      if (!object || Number(object.size) !== Number(upload.size)) {
        await env.DB.prepare(
          "UPDATE render_uploads SET status = 'uploading', " +
          'completion_token = NULL, completion_lease_expires_at = NULL ' +
          'WHERE job_id = ? AND claim_token = ? AND completion_token = ?')
          .bind(job.id, claimToken, completionToken).run();
        return bad('could not finish the render upload; retry', 503);
      }
    }
    const stored = await env.MEDIA.get(upload.r2_key);
    if (!stored || Number(stored.size) !== Number(upload.size)) {
      return bad('completed render could not be read back', 503);
    }
    const actualHash = await streamSha256Hex(stored.body);
    if (actualHash !== upload.content_sha256) {
      await env.MEDIA.delete(upload.r2_key);
      await env.DB.prepare(
        "UPDATE render_uploads SET status = 'corrupt', " +
        'completion_token = NULL, completion_lease_expires_at = NULL ' +
        'WHERE job_id = ? AND claim_token = ? AND completion_token = ?')
        .bind(job.id, claimToken, completionToken).run();
      return bad('completed render failed its full SHA-256 receipt', 422);
    }
    const etag = object.etag;
    const finished = await env.DB.prepare(
      "UPDATE render_uploads SET status = 'done', r2_etag = ?, " +
      'completed_at = ?, completion_lease_expires_at = NULL ' +
      'WHERE job_id = ? AND claim_token = ? AND completion_token = ?')
      .bind(etag, now(), job.id, claimToken, completionToken).run();
    if (finished.meta?.changes !== 1) {
      return bad('render storage receipt lost its completion claim', 409);
    }
    upload = { ...upload, status: 'done', r2_etag: etag };
    return j(receipt());
  }

  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/qa$/)) && method === 'PUT') {
    const claimToken = claimTokenFrom(req);
    const job = await claimedJob(env, scope, m[1], claimToken);
    if (!job) return bad('job claim is not active', 409);
    const upload = await env.DB.prepare(
      'SELECT * FROM render_uploads WHERE job_id = ? AND claim_token = ? ' +
      "AND status = 'done'").bind(job.id, claimToken).first();
    if (!upload) return bad('finish the render output before QA', 409);
    const declaredBytes = Number(req.headers.get('content-length'));
    const declaredHash = req.headers.get('x-autoeditor-sha256') || '';
    if (!Number.isSafeInteger(declaredBytes) || declaredBytes <= 0 ||
        declaredBytes > MAX_QA_BYTES || !SHA256_PATTERN.test(declaredHash)) {
      return bad('QA receipt size or SHA-256 is invalid');
    }
    const qaBytes = await req.arrayBuffer();
    if (qaBytes.byteLength !== declaredBytes ||
        await sha256Hex(qaBytes) !== declaredHash) {
      return bad('QA receipt failed its SHA-256 receipt', 422);
    }
    let report;
    try { report = JSON.parse(new TextDecoder().decode(qaBytes)); }
    catch (_) { return bad('QA receipt is not valid JSON', 422); }
    const binding = report?._autoeditor;
    const release = report && typeof report.release === 'object'
      ? Object.values(report.release) : [];
    if (typeof report?.pass !== 'boolean' || !report.checks ||
        typeof report.checks !== 'object' || !binding ||
        binding.claim_token !== claimToken ||
        binding.output_key !== upload.r2_key ||
        binding.output_content_sha256 !== upload.content_sha256 ||
        binding.output_multipart_sha256 !== upload.multipart_sha256 ||
        Number(binding.output_size) !== Number(upload.size) ||
        !release.some((item) => item &&
          item.sha256 === upload.content_sha256)) {
      return bad('QA receipt is not bound to this render claim', 422);
    }
    try {
      await env.MEDIA.put(upload.qa_key, qaBytes, {
        sha256: declaredHash,
        customMetadata: { sha256: declaredHash, claim_token: claimToken,
          multipart_sha256: upload.multipart_sha256, job_id: job.id },
        httpMetadata: { contentType: 'application/json' },
      });
    } catch (_) { return bad('QA receipt failed storage verification', 422); }
    return j({ ok: true, qa_key: upload.qa_key, sha256: declaredHash });
  }

  // R2 input passthrough for the daemon. A job claim can download only the
  // completed source rows for its own project.
  if ((m = p.match(/^\/worker\/media\/(.+)$/))) {
    const key = decodeURIComponent(m[1]);
    const jobId = req.headers.get('x-autoeditor-job-id') || '';
    const claimToken = claimTokenFrom(req);
    const job = await claimedJob(env, scope, jobId, claimToken);
    if (!job || !jobOwnsMediaKey(job, key)) {
      return bad('job claim is not active', 409);
    }
    if (method === 'GET') {
      const source = await env.DB.prepare(
        "SELECT 1 FROM uploads WHERE project_id = ? AND r2_key = ? " +
        "AND status = 'done'").bind(job.project_id, key).first();
      if (!source) return bad('source does not belong to this job', 403);
      const obj = await env.MEDIA.get(key);
      if (!obj) return bad('not found', 404);
      return new Response(obj.body, { headers: {
        'cache-control': 'private, no-store',
        'x-content-type-options': 'nosniff',
      } });
    }
    if (method === 'PUT') return bad('use the claim-bound output routes', 405);
  }
  return bad('no such endpoint', 404);
}
