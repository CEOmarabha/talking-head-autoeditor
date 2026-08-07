/** Private hosted AutoEditor: one Worker = site + API + queue.
 *
 * Security posture (full threat model in docs/WEB_SECURITY.md):
 *  - invite-only sessions, httpOnly cookies, per-user row scoping on every
 *    query;
 *  - DeepSeek keys AES-GCM wrapped immediately on receipt, ciphertext in
 *    D1, NEVER logged, never in job payloads/URLs, never returned by any
 *    endpoint (only a boolean hasKey);
 *  - the render daemon authenticates with WORKER_TOKEN and receives key
 *    ciphertext only; it decrypts with a KEK that exists only on the
 *    render host;
 *  - media is private in R2; all reads stream through authenticated
 *    routes; nothing is public.
 */

const JSONH = { 'content-type': 'application/json' };
const enc = new TextEncoder();

// ------------------------------------------------------------- helpers
const uid = () => crypto.randomUUID().replaceAll('-', '').slice(0, 20);
const now = () => Date.now();
function j(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status, headers: { ...JSONH, ...headers },
  });
}
function bad(msg, status = 400) { return j({ error: msg }, status); }

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
      if (p.startsWith('/api/')) return await api(req, env, url);
      return env.ASSETS.fetch(req);
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

  // ---------- auth
  if (p === '/auth/signin' && method === 'POST') {
    const { invite_code, name } = await req.json().catch(() => ({}));
    if (!invite_code || !name) return bad('invite code and name required');
    const inv = await env.DB.prepare(
      'SELECT * FROM invites WHERE code = ?').bind(invite_code).first();
    if (!inv) return bad('invalid invite code', 403);
    let user;
    if (inv.used_by) {
      user = await env.DB.prepare('SELECT * FROM users WHERE id = ?')
        .bind(inv.used_by).first();
      if (!user) return bad('invite orphaned; ask Omar', 403);
    } else {
      user = { id: uid(), name: String(name).slice(0, 60) };
      await env.DB.prepare(
        'INSERT INTO users (id, name, invite_code, created_at) ' +
        'VALUES (?, ?, ?, ?)')
        .bind(user.id, user.name, invite_code, now()).run();
      await env.DB.prepare(
        'UPDATE invites SET used_by = ? WHERE code = ?')
        .bind(user.id, invite_code).run();
    }
    const token = crypto.randomUUID().replaceAll('-', '') + uid();
    await env.DB.prepare(
      'INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)')
      .bind(token, user.id, now() + 1000 * 60 * 60 * 24 * 30).run();
    return j({ ok: true, name: user.name }, 200, {
      'set-cookie': `session=${token}; HttpOnly; Secure; SameSite=Lax; ` +
        'Path=/; Max-Age=2592000',
    });
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
    return j({ name: user.name, hasKey: user.hasKey });
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
  // This is the always-available lifeline — a friend can ask DeepSeek for
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
      'helping may not be technical. Help them with setup (installing the ' +
      'Helper app, FFmpeg, Python), using the site, understanding error ' +
      'messages, or anything else. Be concise, warm, and concrete. Give ' +
      'exact click-by-click or copy-paste steps and say which app to open ' +
      'on Windows (PowerShell) or Mac (Terminal) when relevant.' };
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
      'qa_pass,output_key IS NOT NULL AS has_output ' +
      'FROM revisions WHERE project_id = ? ORDER BY num')
      .bind(proj.id).all();
    const chat = await env.DB.prepare(
      'SELECT role,content,created_at FROM chat_messages ' +
      'WHERE project_id = ? ORDER BY created_at').bind(proj.id).all();
    return j({ ...proj, transcript: proj.transcript,
      uploads: uploads.results || [],
      revisions: revisions.results || [], chat: chat.results || [] });
  }

  // ---------- uploads: R2 multipart through the Worker (documented
  // pattern; parts survive refresh because uploadId+parts live in D1)
  if ((m = p.match(/^\/projects\/(\w+)\/uploads$/)) && method === 'POST') {
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    const { filename, size } = await req.json().catch(() => ({}));
    if (!filename) return bad('filename required');
    const id = uid();
    const key = `u/${user.userId}/${proj.id}/raw/${id}_` +
      filename.replace(/[^\w.-]/g, '_');
    const mp = await env.MEDIA.createMultipartUpload(key);
    await env.DB.prepare(
      'INSERT INTO uploads (id,project_id,r2_key,filename,size,' +
      'mp_upload_id,status,created_at) VALUES (?,?,?,?,?,?,?,?)')
      .bind(id, proj.id, key, filename, size || 0, mp.uploadId,
        'uploading', now()).run();
    await setStatus(env, proj.id, 'uploading');
    return j({ upload_id: id, part_size: 10 * 1024 * 1024 });
  }
  if ((m = p.match(/^\/uploads\/(\w+)\/part$/)) && method === 'PUT') {
    const up = await env.DB.prepare(
      'SELECT u.*, p.user_id FROM uploads u JOIN projects p ' +
      'ON p.id = u.project_id WHERE u.id = ?').bind(m[1]).first();
    if (!up || up.user_id !== user.userId) return bad('not found', 404);
    const partNum = parseInt(url.searchParams.get('n'), 10);
    if (!partNum || partNum < 1) return bad('part number required');
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
    const proj = await ownedProject(env, user, m[1]);
    if (!proj) return bad('not found', 404);
    if (!user.hasKey) return bad('add your DeepSeek key first', 428);
    const { text } = await req.json().catch(() => ({}));
    if (!text || !text.trim()) return bad('empty request');
    await env.DB.prepare(
      'INSERT INTO chat_messages (id,project_id,role,content,created_at) ' +
      'VALUES (?,?,?,?,?)')
      .bind(uid(), proj.id, 'user', text.slice(0, 2000), now()).run();
    const jobId = uid();
    await env.DB.prepare(
      'INSERT INTO jobs (id,project_id,user_id,kind,payload_json,' +
      'created_at) VALUES (?,?,?,?,?,?)')
      .bind(jobId, proj.id, user.userId, 'chat_proposal',
        JSON.stringify({ text: text.slice(0, 2000) }), now()).run();
    await setStatus(env, proj.id, 'planning');
    return j({ job_id: jobId });
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
      range: req.headers.get('range') || undefined });
    if (!obj) return bad('not found', 404);
    const headers = { 'content-type': 'video/mp4',
      'accept-ranges': 'bytes' };
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
    await env.DB.prepare(
      "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?")
      .bind(now(), job.id).run();
    const proj = await env.DB.prepare(
      'SELECT * FROM projects WHERE id = ?').bind(job.project_id).first();
    const uploads = await env.DB.prepare(
      "SELECT r2_key, filename FROM uploads WHERE project_id = ? " +
      "AND status = 'done' ORDER BY created_at").bind(job.project_id).all();
    const u = await env.DB.prepare(
      'SELECT key_ct, key_iv FROM users WHERE id = ?')
      .bind(job.user_id).first();
    const preset = proj.style_preset_id ? await env.DB.prepare(
      'SELECT name, params_json FROM style_presets WHERE id = ?')
      .bind(proj.style_preset_id).first() : null;
    // user-scoped helper: hand the user their OWN key over TLS (no KEK
    // distribution). Global daemon: ciphertext only + local KEK.
    let key_plain = null;
    if (scope.scope === 'user' && u && u.key_ct) {
      try { key_plain = await unwrapKey(env, u.key_ct, u.key_iv); }
      catch (_) { key_plain = null; }
    }
    return j({ job, project: proj, uploads: uploads.results || [],
      key_ct: u ? u.key_ct : null, key_iv: u ? u.key_iv : null,
      key_plain, preset });
  }
  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/progress$/))
      && method === 'POST') {
    const { line, status, detail } = await req.json().catch(() => ({}));
    const job = await env.DB.prepare('SELECT * FROM jobs WHERE id = ?')
      .bind(m[1]).first();
    if (!job) return bad('no job', 404);
    if (line) {
      const prog = JSON.parse(job.progress_json || '[]');
      prog.push(String(line).slice(0, 300));
      await env.DB.prepare(
        'UPDATE jobs SET progress_json = ? WHERE id = ?')
        .bind(JSON.stringify(prog.slice(-200)), job.id).run();
    }
    if (status) await setStatus(env, job.project_id, status, detail || '');
    return j({ ok: true });
  }
  if ((m = p.match(/^\/worker\/jobs\/(\w+)\/complete$/))
      && method === 'POST') {
    const body = await req.json().catch(() => ({}));
    const job = await env.DB.prepare('SELECT * FROM jobs WHERE id = ?')
      .bind(m[1]).first();
    if (!job) return bad('no job', 404);
    await env.DB.prepare(
      "UPDATE jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?")
      .bind(body.ok ? 'done' : 'failed', now(),
        body.error || null, job.id).run();
    if (job.kind === 'transcribe' && body.transcript) {
      await env.DB.prepare(
        'UPDATE projects SET transcript = ? WHERE id = ?')
        .bind(body.transcript, job.project_id).run();
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
    } else if (job.kind === 'chat_proposal' && body.proposal) {
      const count = await env.DB.prepare(
        'SELECT COUNT(*) AS n FROM revisions WHERE project_id = ?')
        .bind(job.project_id).first();
      const revId = uid();
      await env.DB.prepare(
        'INSERT INTO revisions (id,project_id,num,request_text,' +
        'proposal_json,needs_approval,status,created_at) ' +
        'VALUES (?,?,?,?,?,?,?,?)')
        .bind(revId, job.project_id, (count.n || 0) + 1,
          body.request_text || '', JSON.stringify(body.proposal),
          body.needs_approval ? 1 : 0,
          body.needs_approval ? 'proposed' : 'approved', now()).run();
      await env.DB.prepare(
        'INSERT INTO chat_messages (id,project_id,role,content,' +
        'created_at) VALUES (?,?,?,?,?)')
        .bind(uid(), job.project_id, 'assistant',
          body.summary || 'Proposal ready.', now()).run();
      if (body.needs_approval) {
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
      const revId = body.revision_id || uid();
      if (!body.revision_id) {
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
      return new Response(obj.body);
    }
    if (method === 'PUT') {
      await env.MEDIA.put(key, req.body);
      return j({ ok: true });
    }
  }
  return bad('no such endpoint', 404);
}
