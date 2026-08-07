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

// ------------------------------------------------------------- helpers
const uid = () => crypto.randomUUID().replaceAll('-', '').slice(0, 20);
const now = () => Date.now();
function j(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status, headers: { ...JSONH, 'cache-control': 'no-store', ...headers },
  });
}
function bad(msg, status = 400) { return j({ error: msg }, status); }

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
    'WHERE id = ?').bind(status, detail, now(), projectId).run();
}

// ---------------------------------------------------------- edit contract
// Mirror of webapp/render_worker/project_types.py ALLOWED_OPS. DeepSeek is
// an untrusted planner: every proposal is validated deterministically here
// and anything outside this contract rejects the WHOLE proposal.
const ALLOWED_OPS = {
  faster_hook: { params: { factor: ['num', 1.0, 2.0] }, approval: false,
    human: (p) => `Tighten the opening (about ${p.factor}x faster pacing)` },
  remove_segment: { params: { start: ['num', 0, 36000],
    end: ['num', 0, 36000] }, approval: true,
    human: (p) => `Remove the section from ${p.start}s to ${p.end}s` },
  fewer_punchins: { params: {}, approval: false,
    human: () => 'Use fewer punch-ins' },
  more_punchins: { params: {}, approval: false,
    human: () => 'Use more punch-ins' },
  caption_scale: { params: { scale: ['num', 0.03, 0.09] }, approval: false,
    human: (p) => `Set caption size to ${p.scale} of frame height` },
  broll_density: { params: { level: ['choice', 'less', 'normal', 'more'] },
    approval: false, human: (p) => `Use ${p.level} b-roll` },
  cinematic_grade: { params: {}, approval: false,
    human: () => 'Apply a more cinematic look' },
  retarget_duration: { params: { seconds: ['num', 10, 3600] },
    approval: true,
    human: (p) => `Re-cut the video to about ${p.seconds} seconds` },
  split_into_clips: { params: { count: ['int', 1, 10] }, approval: true,
    human: (p) => `Create ${p.count} clips from this video` },
  acquire_asset: { params: { query: ['str', 1, 120],
    kind: ['choice', 'broll', 'music', 'sfx', 'image'] }, approval: true,
    human: (p) => `Find licensed ${p.kind}: "${p.query}"` },
};

function validateProposal(raw) {
  const errors = [];
  const opsIn = raw && raw.operations;
  if (!Array.isArray(opsIn) || !opsIn.length) {
    return { clean: null, needsApproval: false,
      errors: ['no operations'] };
  }
  if (opsIn.length > 8) {
    return { clean: null, needsApproval: false,
      errors: ['too many operations (max 8)'] };
  }
  const clean = []; let needsApproval = false;
  for (const op of opsIn) {
    const spec = op && ALLOWED_OPS[op.op];
    if (!spec) { errors.push(`unknown operation '${op && op.op}'`); continue; }
    const params = {}; let ok = true;
    for (const [pname, pspec] of Object.entries(spec.params)) {
      let val = op[pname];
      if (pspec[0] === 'choice') {
        if (!pspec.slice(1).includes(val)) {
          errors.push(`${op.op}.${pname} invalid`); ok = false;
        }
      } else if (pspec[0] === 'str') {
        val = String(val || '');
        if (val.length < pspec[1] || val.length > pspec[2]) {
          errors.push(`${op.op}.${pname} bad length`); ok = false;
        }
      } else {
        val = Number(val);
        if (!isFinite(val) || val < pspec[1] || val > pspec[2]) {
          errors.push(`${op.op}.${pname} out of range`); ok = false;
        }
        if (pspec[0] === 'int') val = Math.round(val);
      }
      params[pname] = val;
    }
    if (!ok) continue;
    if (op.op === 'remove_segment' && params.end <= params.start) {
      errors.push('remove_segment end before start'); continue;
    }
    clean.push({ op: op.op, ...params, human: spec.human(params) });
    needsApproval = needsApproval || spec.approval;
  }
  if (errors.length) return { clean: null, needsApproval: false, errors };
  return { clean: { operations: clean,
    summary: String(raw.summary || '').slice(0, 400) },
  needsApproval, errors: [] };
}

const PROJECT_TYPES = new Set(['short', 'long', 'commercial', 'podcast',
  'course', 'clips', 'custom']);
const PRESET_NAMES = new Set(['My Style', 'My Shorts Style',
  'My Long-Form Style', 'My Commercial Style', 'Custom Style']);

// ------------------------------------------------------------- router
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;
    try {
      const helperDownloads = {
        '/download/helper/windows': {
          key: 'dist/helper/windows/AutoEditor-Helper.exe',
          type: 'application/vnd.microsoft.portable-executable',
          name: 'AutoEditor-Helper-Windows.exe',
        },
        '/download/helper/mac-arm64': {
          key: 'dist/helper/mac-arm64/AutoEditor-Helper.dmg',
          type: 'application/x-apple-diskimage',
          name: 'AutoEditor-Helper-Mac-Apple-Silicon.dmg',
        },
        '/download/helper/mac-x64': {
          key: 'dist/helper/mac-x64/AutoEditor-Helper.dmg',
          type: 'application/x-apple-diskimage',
          name: 'AutoEditor-Helper-Mac-Intel.dmg',
        },
      };
      if (p === '/download/helper/availability') {
        if (!(await auth(req, env))) return bad('sign in first', 401);
        const entries = await Promise.all(Object.entries(helperDownloads)
          .map(async ([route, item]) => [route, !!(await env.MEDIA.head(item.key))]));
        return new Response(JSON.stringify(Object.fromEntries(entries)), {
          headers: { 'content-type': 'application/json; charset=utf-8',
            'cache-control': 'no-store' },
        });
      }
      if (helperDownloads[p]) {
        if (!(await auth(req, env))) return bad('sign in first', 401);
        const item = helperDownloads[p];
        const obj = await env.MEDIA.get(item.key, {
          range: req.headers,
        });
        if (!obj) return new Response('Installer is not uploaded yet', { status: 503 });
        const headers = {
          'content-type': item.type,
          'content-disposition': `attachment; filename="${item.name}"`,
          'cache-control': 'private, no-store',
          'accept-ranges': 'bytes',
          'x-content-type-options': 'nosniff',
        };
        if (obj.httpEtag) headers.etag = obj.httpEtag;
        if (obj.range) {
          headers['content-range'] =
            `bytes ${obj.range.offset}-${obj.range.offset + obj.range.length - 1}` +
            `/${obj.size}`;
          headers['content-length'] = String(obj.range.length);
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
      await env.DB.prepare(
        'INSERT INTO users (id, name, invite_code, created_at) ' +
        'VALUES (?, ?, ?, ?)')
        .bind(user.id, user.name, code, now()).run();
      await env.DB.prepare(
        'UPDATE invites SET used_by = ? WHERE code = ?')
        .bind(user.id, code).run();
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
      'or can skip Remotion diagrams. Give exact click-by-click guidance, ' +
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
    const id = uid();
    await env.DB.prepare(
      'INSERT INTO style_presets (id,user_id,name,params_json,created_at) ' +
      'VALUES (?,?,?,?,?)')
      .bind(id, user.userId, name, JSON.stringify(params || {}), now())
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
        'SELECT id FROM style_presets WHERE id = ? AND user_id = ?')
        .bind(style_preset_id, user.userId).first();
      if (!preset) return bad('style preset not found', 404);
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
      'SELECT id,filename,size,status FROM uploads WHERE project_id = ?')
      .bind(proj.id).all();
    const revisions = await env.DB.prepare(
      'SELECT id,num,request_text,proposal_json,needs_approval,status,' +
      'qa_pass,output_key,output_key IS NOT NULL AS has_output ' +
      'FROM revisions WHERE project_id = ? ORDER BY num')
      .bind(proj.id).all();
    const chat = await env.DB.prepare(
      'SELECT role,content,created_at FROM chat_messages ' +
      'WHERE project_id = ? ORDER BY created_at').bind(proj.id).all();
    return j({ ...proj, transcript: proj.transcript,
      uploads: uploads.results || [],
      revisions: revisions.results || [], chat: chat.results || [] });
  }
  if ((m = p.match(/^\/projects\/(\w+)$/)) && method === 'DELETE') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    const active = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM jobs WHERE project_id = ? AND status = 'running'")
      .bind(proj.id).first();
    if (active.n) return bad('wait for the current edit to finish before deleting', 409);

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

    for (const table of ['chat_messages', 'revisions', 'jobs', 'uploads']) {
      await env.DB.prepare(`DELETE FROM ${table} WHERE project_id = ?`)
        .bind(proj.id).run();
    }
    await env.DB.prepare('DELETE FROM projects WHERE id = ? AND user_id = ?')
      .bind(proj.id, user.userId).run();
    return j({ ok: true, cloud_files_deleted: deleted });
  }

  // ---------- uploads: R2 multipart through the Worker (documented
  // pattern; parts survive refresh because uploadId+parts live in D1)
  if ((m = p.match(/^\/projects\/(\w+)\/uploads$/)) && method === 'POST') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    const { filename, size } = await req.json().catch(() => ({}));
    if (!filename) return bad('filename required');
    const byteSize = Number(size);
    if (!Number.isSafeInteger(byteSize) || byteSize <= 0 ||
        byteSize > MAX_UPLOAD_BYTES) {
      return bad('video must be between 1 byte and 20 GB');
    }
    const prior = await env.DB.prepare(
      "SELECT id,parts_json FROM uploads WHERE project_id = ? " +
      "AND filename = ? AND size = ? AND status = 'uploading' " +
      'AND created_at > ? ORDER BY created_at DESC LIMIT 1')
      .bind(proj.id, String(filename).slice(0, 240), byteSize,
        now() - 6 * 24 * 60 * 60 * 1000).first();
    if (prior) {
      const parts = JSON.parse(prior.parts_json || '[]')
        .map((part) => part.partNumber).filter(Number.isInteger);
      return j({ upload_id: prior.id, part_size: UPLOAD_PART_SIZE,
        uploaded_parts: parts, resumed: true });
    }
    const id = uid();
    const key = `u/${user.userId}/${proj.id}/raw/${id}_` +
      String(filename).slice(0, 240).replace(/[^\w.-]/g, '_');
    const mp = await env.MEDIA.createMultipartUpload(key);
    await env.DB.prepare(
      'INSERT INTO uploads (id,project_id,r2_key,filename,size,' +
      'mp_upload_id,status,created_at) VALUES (?,?,?,?,?,?,?,?)')
      .bind(id, proj.id, key, String(filename).slice(0, 240), byteSize, mp.uploadId,
        'uploading', now()).run();
    await setStatus(env, proj.id, 'uploading');
    return j({ upload_id: id, part_size: UPLOAD_PART_SIZE,
      uploaded_parts: [], resumed: false });
  }
  if ((m = p.match(/^\/uploads\/(\w+)\/part$/)) && method === 'PUT') {
    const up = await env.DB.prepare(
      'SELECT u.*, p.user_id FROM uploads u JOIN projects p ' +
      'ON p.id = u.project_id WHERE u.id = ?').bind(m[1]).first();
    if (!up || up.user_id !== user.userId) return bad('not found', 404);
    const partNum = parseInt(url.searchParams.get('n'), 10);
    const totalParts = Math.ceil(up.size / UPLOAD_PART_SIZE);
    if (!partNum || partNum < 1 || partNum > totalParts) {
      return bad('part number out of range');
    }
    const expectedBytes = partNum === totalParts
      ? up.size - ((totalParts - 1) * UPLOAD_PART_SIZE) : UPLOAD_PART_SIZE;
    const lengthHeader = req.headers.get('content-length');
    const suppliedBytes = lengthHeader === null ? null : Number(lengthHeader);
    if (suppliedBytes !== null &&
        (!Number.isFinite(suppliedBytes) || suppliedBytes !== expectedBytes)) {
      return bad('upload part has the wrong size');
    }
    const mp = env.MEDIA.resumeMultipartUpload(up.r2_key, up.mp_upload_id);
    const part = await mp.uploadPart(partNum, req.body);
    const parts = JSON.parse(up.parts_json || '[]')
      .filter((x) => x.partNumber !== partNum);
    parts.push(part);
    await env.DB.prepare('UPDATE uploads SET parts_json = ? WHERE id = ?')
      .bind(JSON.stringify(parts), up.id).run();
    return j({ ok: true, part: partNum });
  }
  if ((m = p.match(/^\/uploads\/(\w+)\/complete$/)) && method === 'POST') {
    const up = await env.DB.prepare(
      'SELECT u.*, p.user_id FROM uploads u JOIN projects p ' +
      'ON p.id = u.project_id WHERE u.id = ?').bind(m[1]).first();
    if (!up || up.user_id !== user.userId) return bad('not found', 404);
    const parts = JSON.parse(up.parts_json || '[]')
      .sort((a, b) => a.partNumber - b.partNumber);
    const totalParts = Math.ceil(up.size / UPLOAD_PART_SIZE);
    if (parts.length !== totalParts ||
        parts.some((part, index) => part.partNumber !== index + 1)) {
      return bad('upload is missing one or more parts', 409);
    }
    const mp = env.MEDIA.resumeMultipartUpload(up.r2_key, up.mp_upload_id);
    await mp.complete(parts);
    await env.DB.prepare(
      "UPDATE uploads SET status = 'done' WHERE id = ?").bind(up.id).run();
    await setStatus(env, up.project_id, 'uploaded');
    return j({ ok: true });
  }

  // ---------- make it / chat / revisions -> jobs
  if ((m = p.match(/^\/projects\/(\w+)\/make$/)) && method === 'POST') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    if (!user.hasKey) return bad('add your DeepSeek key first', 428);
    const ready = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM uploads WHERE project_id = ? " +
      "AND status = 'done'").bind(proj.id).first();
    if (!ready.n) return bad('upload footage first', 428);
    const { script } = await req.json().catch(() => ({}));
    const jobId = uid();
    await env.DB.prepare(
      'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
      'created_at) VALUES (?,?,?,?,?,?)')
      .bind(jobId, proj.id, user.userId, 'make',
        JSON.stringify({ script: script || null }), now()).run();
    await setStatus(env, proj.id, 'queued');
    return j({ job_id: jobId });
  }

  if ((m = p.match(/^\/projects\/(\w+)\/chat$/)) && method === 'POST') {
    // Instant back-and-forth with DeepSeek, straight from the Worker: no
    // queue, no Helper needed. DeepSeek decides whether the message is
    // conversation (reply now) or an edit request (typed proposal that the
    // deterministic contract validates; sensitive ops wait for an OK).
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    if (!user.hasKey) return bad('add your DeepSeek key first', 428);
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
      .map(([k, v]) => [k, Object.fromEntries(Object.entries(v.params)
        .map(([pn, ps]) => [pn, ps.join(' ')]))]));
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
      const count = await env.DB.prepare(
        'SELECT COUNT(*) AS n FROM revisions WHERE project_id = ?')
        .bind(proj.id).first();
      const revId = uid();
      await env.DB.prepare(
        'INSERT INTO revisions (id,project_id,num,request_text,' +
        'proposal_json,needs_approval,status,created_at) ' +
        'VALUES (?,?,?,?,?,?,?,?)')
        .bind(revId, proj.id, (count.n || 0) + 1, userMsg,
          JSON.stringify(clean), needsApproval ? 1 : 0,
          needsApproval ? 'proposed' : 'approved', now()).run();
      const summary = clean.summary ||
        'Here\'s what I\'ll change.';
      await env.DB.prepare(
        'INSERT INTO chat_messages (id,project_id,role,content,' +
        'created_at) VALUES (?,?,?,?,?)')
        .bind(uid(), proj.id, 'assistant', summary, now()).run();
      if (needsApproval) {
        await setStatus(env, proj.id, 'awaiting approval');
        return j({ reply: summary, proposal: clean, revision_id: revId,
          needs_approval: true });
      }
      // visual-only: queue the apply render right away
      const jobId = uid();
      await env.DB.prepare(
        'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
        'created_at) VALUES (?,?,?,?,?,?)')
        .bind(jobId, proj.id, user.userId, 'revision_apply',
          JSON.stringify({ revision_id: revId }), now()).run();
      await setStatus(env, proj.id, 'applying revision');
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
      'SELECT r.*, p.user_id FROM revisions r JOIN projects p ' +
      'ON p.id = r.project_id WHERE r.id = ?').bind(m[1]).first();
    if (!rev || rev.user_id !== user.userId) return bad('not found', 404);
    if (rev.status !== 'proposed') return bad('already resolved');
    if (m[2] === 'reject') {
      await env.DB.prepare(
        "UPDATE revisions SET status = 'rejected' WHERE id = ?")
        .bind(rev.id).run();
      await setStatus(env, rev.project_id, 'ready');
      return j({ ok: true });
    }
    await env.DB.prepare(
      "UPDATE revisions SET status = 'approved' WHERE id = ?")
      .bind(rev.id).run();
    const jobId = uid();
    await env.DB.prepare(
      'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
      'created_at) VALUES (?,?,?,?,?,?)')
      .bind(jobId, rev.project_id, user.userId, 'revision_apply',
        JSON.stringify({ revision_id: rev.id }), now()).run();
    await setStatus(env, rev.project_id, 'applying revision');
    return j({ job_id: jobId });
  }

  // ---------- media reads: authenticated streaming, never public
  if ((m = p.match(/^\/media\/(.+)$/)) && method === 'GET') {
    const key = decodeURIComponent(m[1]);
    if (!key.startsWith(`u/${user.userId}/`)) return bad('forbidden', 403);
    const obj = await env.MEDIA.get(key, {
      range: req.headers });
    if (!obj) return bad('not found', 404);
    const headers = { 'content-type': 'video/mp4',
      'accept-ranges': 'bytes', 'cache-control': 'private, no-store',
      'x-content-type-options': 'nosniff' };
    if (obj.range) {
      headers['content-range'] =
        `bytes ${obj.range.offset}-${obj.range.offset + obj.range.length - 1}` +
        `/${obj.size}`;
      return new Response(obj.body, { status: 206, headers });
    }
    return new Response(obj.body, { headers });
  }

  return bad('no such endpoint', 404);
}

// ------------------------------------------------------------- daemon API
async function workerApi(req, env, p, method, scope) {
  let m;
  if (p === '/worker/next-job' && method === 'POST') {
    const job = scope.scope === 'user'
      ? await env.DB.prepare(
        "SELECT * FROM jobs WHERE status = 'queued' AND user_id = ? " +
        'ORDER BY created_at LIMIT 1').bind(scope.userId).first()
      : await env.DB.prepare(
        "SELECT * FROM jobs WHERE status = 'queued' " +
        'ORDER BY created_at LIMIT 1').first();
    if (!job) return j({ job: null });
    const claim = await env.DB.prepare(
      "UPDATE jobs SET status = 'running', started_at = ? " +
      "WHERE id = ? AND status = 'queued'")
      .bind(now(), job.id).run();
    if (!claim.meta || claim.meta.changes !== 1) return j({ job: null });
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
    return j({ job, project: proj, uploads: uploads.results || [],
      key_ct: scope.scope === 'global' && u ? u.key_ct : null,
      key_iv: scope.scope === 'global' && u ? u.key_iv : null,
      key_plain, preset });
  }
  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/progress$/))
      && method === 'POST') {
    const { line, status, detail } = await req.json().catch(() => ({}));
    const job = await env.DB.prepare('SELECT * FROM jobs WHERE id = ?')
      .bind(m[1]).first();
    if (!job) return bad('no job', 404);
    if (!workerOwnsJob(scope, job)) return bad('forbidden', 403);
    if (job.status !== 'running') return bad('job is not running', 409);
    if (line) {
      const prog = JSON.parse(job.progress_json || '[]');
      prog.push(String(line).slice(0, 300));
      await env.DB.prepare(
        'UPDATE jobs SET progress_json = ? WHERE id = ?')
        .bind(JSON.stringify(prog.slice(-200)), job.id).run();
    }
    const allowedStatuses = new Set([
      'transcribing', 'planning', 'gathering resources', 'rendering preview',
      'running final qa',
    ]);
    if (status && !allowedStatuses.has(status)) return bad('invalid status');
    if (status) {
      await setStatus(env, job.project_id, status,
        String(detail || '').slice(0, 300));
    }
    return j({ ok: true });
  }
  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/complete$/))
      && method === 'POST') {
    const body = await req.json().catch(() => ({}));
    const job = await env.DB.prepare('SELECT * FROM jobs WHERE id = ?')
      .bind(m[1]).first();
    if (!job) return bad('no job', 404);
    if (!workerOwnsJob(scope, job)) return bad('forbidden', 403);
    if (job.status !== 'running') return bad('job is not running', 409);
    if (!jobOwnsMediaKey(job, body.output_key) ||
        !jobOwnsMediaKey(job, body.qa_key)) {
      return bad('output path does not belong to this job', 403);
    }
    let safeProposal = null;
    let safeNeedsApproval = false;
    let targetRevisionId = null;
    if (job.kind === 'chat_proposal' &&
        body.proposal && (body.proposal.operations || []).length) {
      const checked = validateProposal(body.proposal);
      if (!checked.clean) return bad('unsafe edit proposal rejected', 422);
      safeProposal = checked.clean;
      safeNeedsApproval = checked.needsApproval;
    }
    if (job.kind === 'revision_apply' && body.ok) {
      let payload = {};
      try { payload = JSON.parse(job.payload_json || '{}'); } catch (_) { }
      const revision = await env.DB.prepare(
        'SELECT id FROM revisions WHERE id = ? AND project_id = ?')
        .bind(payload.revision_id || '', job.project_id).first();
      if (!revision) return bad('revision does not belong to this job', 409);
      targetRevisionId = revision.id;
    }
    await env.DB.prepare(
      "UPDATE jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?")
      .bind(body.ok ? 'done' : 'failed', now(),
        body.error ? String(body.error).slice(0, 300) : null, job.id).run();
    if (job.kind === 'transcribe' && body.transcript) {
      await env.DB.prepare(
        'UPDATE projects SET transcript = ? WHERE id = ?')
        .bind(String(body.transcript).slice(0, 250000), job.project_id).run();
      await setStatus(env, job.project_id, 'transcript needs attention');
    } else if (job.kind === 'chat_proposal'
        && !(body.proposal && (body.proposal.operations || []).length)) {
      // planner returned nothing usable: chat message only, no revision
      await env.DB.prepare(
        'INSERT INTO chat_messages (id,project_id,role,content,' +
        'created_at) VALUES (?,?,?,?,?)')
        .bind(uid(), job.project_id, 'assistant',
          body.summary || 'No change could be planned.', now()).run();
      await setStatus(env, job.project_id, 'ready');
    } else if (job.kind === 'chat_proposal' && safeProposal) {
      const count = await env.DB.prepare(
        'SELECT COUNT(*) AS n FROM revisions WHERE project_id = ?')
        .bind(job.project_id).first();
      const revId = uid();
      await env.DB.prepare(
        'INSERT INTO revisions (id,project_id,num,request_text,' +
        'proposal_json,needs_approval,status,created_at) ' +
        'VALUES (?,?,?,?,?,?,?,?)')
        .bind(revId, job.project_id, (count.n || 0) + 1,
          String(body.request_text || '').slice(0, 2000),
          JSON.stringify(safeProposal), safeNeedsApproval ? 1 : 0,
          safeNeedsApproval ? 'proposed' : 'approved', now()).run();
      await env.DB.prepare(
        'INSERT INTO chat_messages (id,project_id,role,content,' +
        'created_at) VALUES (?,?,?,?,?)')
        .bind(uid(), job.project_id, 'assistant',
          String(body.summary || 'Proposal ready.').slice(0, 2000), now()).run();
      if (safeNeedsApproval) {
        await setStatus(env, job.project_id, 'awaiting approval');
      } else {
        // auto-apply visual-only changes: queue the apply job now
        const jobId = uid();
        await env.DB.prepare(
          'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
          'created_at) VALUES (?,?,?,?,?,?)')
          .bind(jobId, job.project_id, job.user_id, 'revision_apply',
            JSON.stringify({ revision_id: revId }), now()).run();
        await setStatus(env, job.project_id, 'applying revision');
      }
    } else if ((job.kind === 'make' || job.kind === 'revision_apply')
        && body.ok) {
      let revId = uid();
      if (job.kind === 'revision_apply') {
        revId = targetRevisionId;
      } else {
        const count = await env.DB.prepare(
          'SELECT COUNT(*) AS n FROM revisions WHERE project_id = ?')
          .bind(job.project_id).first();
        await env.DB.prepare(
          'INSERT INTO revisions (id,project_id,num,request_text,status,' +
          'created_at) VALUES (?,?,?,?,?,?)')
          .bind(revId, job.project_id, (count.n || 0) + 1,
            'Initial edit', 'applied', now()).run();
      }
      await env.DB.prepare(
        "UPDATE revisions SET status = 'applied', output_key = ?, " +
        'qa_key = ?, qa_pass = ? WHERE id = ?')
        .bind(body.output_key || null, body.qa_key || null,
          body.qa_pass ? 1 : 0, revId).run();
      await setStatus(env, job.project_id,
        body.qa_pass ? 'ready' : 'needs review');
    } else if (!body.ok) {
      await setStatus(env, job.project_id, 'failed',
        (body.error || 'unknown error').slice(0, 300));
    }
    return j({ ok: true });
  }
  // R2 passthrough for the daemon (download raw, upload outputs)
  if ((m = p.match(/^\/worker\/media\/(.+)$/))) {
    const key = decodeURIComponent(m[1]);
    if (scope.scope === 'user' && !key.startsWith(`u/${scope.userId}/`)) {
      return bad('forbidden', 403);   // personal daemons touch own media only
    }
    if (method === 'GET') {
      const obj = await env.MEDIA.get(key);
      if (!obj) return bad('not found', 404);
      return new Response(obj.body, { headers: {
        'cache-control': 'private, no-store',
        'x-content-type-options': 'nosniff',
      } });
    }
    if (method === 'PUT') {
      await env.MEDIA.put(key, req.body);
      return j({ ok: true });
    }
  }
  return bad('no such endpoint', 404);
}
