import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { Miniflare } from 'miniflare';

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const WORKER_DIR = resolve(TEST_DIR, '..');
const SCHEMA_PATH = resolve(WORKER_DIR, 'schema.sql');
const SCRIPT_PATH = resolve(WORKER_DIR, 'src/index.js');
const ORIGIN = 'https://autoeditor.test';
const GLOBAL_DAEMON_TOKEN = 'integration-global-daemon-token';
const ADMIN_TOKEN = 'integration-admin-token';
const KEY_WRAP_SECRET = 'integration-key-wrap-secret-not-for-production';

const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const multipartFingerprint = (size, hashes) =>
  sha256(`${size}:${hashes.join(':')}`);

function securityHeaders(response) {
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
  assert.equal(
    response.headers.get('strict-transport-security'),
    'max-age=31536000; includeSubDomains',
  );
}

async function json(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (error) {
    assert.fail(`expected JSON for HTTP ${response.status}, got: ${text}`,
      { cause: error });
  }
}

async function createHarness(t) {
  const suffix = randomUUID();
  const mf = new Miniflare({
    scriptPath: SCRIPT_PATH,
    modules: true,
    rootPath: WORKER_DIR,
    compatibilityDate: '2026-07-01',
    bindings: {
      KEY_WRAP_SECRET,
      WORKER_TOKEN: GLOBAL_DAEMON_TOKEN,
      ADMIN_TOKEN,
    },
    d1Databases: { DB: `integration-db-${suffix}` },
    r2Buckets: {
      MEDIA: `integration-media-${suffix}`,
      RELEASES: `integration-releases-${suffix}`,
    },
  });
  t.after(async () => mf.dispose());
  const db = await mf.getD1Database('DB');
  const media = await mf.getR2Bucket('MEDIA');
  const releases = await mf.getR2Bucket('RELEASES');
  // D1's exec endpoint rejects comment-only fragments before the first SQL
  // statement. Production migrations use Wrangler's parser; this harness
  // strips line comments before applying the same schema to Miniflare.
  const schema = (await readFile(SCHEMA_PATH, 'utf8'))
    .replace(/--[^\n]*/g, '')
    .split(';')
    .map((statement) => statement.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join(';\n') + ';';
  await db.exec(schema);

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.cookie) headers.set('cookie', `session=${options.cookie}`);
    if (options.daemonToken) {
      headers.set('authorization', `Bearer ${options.daemonToken}`);
    }
    let body = options.body;
    if (Object.hasOwn(options, 'json')) {
      body = JSON.stringify(options.json);
      headers.set('content-type', 'application/json');
    }
    return mf.dispatchFetch(`${ORIGIN}${path}`, {
      method: options.method || 'GET',
      headers,
      body,
    });
  }

  async function seedUser({
    id, name = id, session = `session-${id}`,
    daemon = `daemon-${id}`, hasKey = true,
  }) {
    const timestamp = Date.now();
    await db.prepare(
      'INSERT INTO users (id,name,invite_code,key_ct,key_iv,created_at) ' +
      'VALUES (?,?,?,?,?,?)',
    ).bind(id, name, `invite-${id}`, hasKey ? 'wrapped-key' : null,
      hasKey ? 'wrapped-iv' : null, timestamp).run();
    await db.prepare(
      'INSERT INTO sessions (token,user_id,expires_at) VALUES (?,?,?)',
    ).bind(session, id, timestamp + 60 * 60 * 1000).run();
    await db.prepare(
      'INSERT INTO daemon_tokens (token,user_id,note,created_at) ' +
      'VALUES (?,?,?,?)',
    ).bind(daemon, id, 'integration', timestamp).run();
    return { id, session, daemon };
  }

  async function seedProject({
    id, userId, status = 'uploaded', type = 'short', title = id,
    deleteToken = null,
  }) {
    const timestamp = Date.now();
    await db.prepare(
      'INSERT INTO projects (id,user_id,type,title,status,delete_token,' +
      'created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
    ).bind(id, userId, type, title, status, deleteToken,
      timestamp, timestamp).run();
    return id;
  }

  async function seedSource({
    id, projectId, userId, status = 'done', bytes = Buffer.from('source'),
  }) {
    const key = `u/${userId}/${projectId}/raw/${id}.mp4`;
    if (status === 'done') await media.put(key, bytes);
    await db.prepare(
      'INSERT INTO uploads (id,project_id,r2_key,filename,size,parts_json,' +
      'status,created_at) VALUES (?,?,?,?,?,?,?,?)',
    ).bind(id, projectId, key, `${id}.mp4`, bytes.length, '[]', status,
      Date.now()).run();
    return key;
  }

  async function seedJob({
    id, projectId, userId, kind = 'make', status = 'queued',
    payload = {}, claimToken = null, leaseExpiresAt = null,
    attemptCount = 0, renderSlot = 1,
  }) {
    await db.prepare(
      'INSERT INTO jobs (id,project_id,user_id,kind,status,payload_json,' +
      'claim_token,lease_expires_at,attempt_count,render_slot,created_at) ' +
      'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
    ).bind(id, projectId, userId, kind, status, JSON.stringify(payload),
      claimToken, leaseExpiresAt, attemptCount, renderSlot, Date.now()).run();
    return id;
  }

  async function row(sql, ...bindings) {
    return db.prepare(sql).bind(...bindings).first();
  }

  return {
    mf, db, media, releases, request, row,
    seedUser, seedProject, seedSource, seedJob,
  };
}

async function claimNext(harness, daemonToken = GLOBAL_DAEMON_TOKEN) {
  const response = await harness.request('/api/worker/next-job', {
    method: 'POST', daemonToken,
  });
  assert.equal(response.status, 200);
  return json(response);
}

test('claim tokens fence stale attempts and expired jobs are reclaimed',
  async (t) => {
    const h = await createHarness(t);
    const user = await h.seedUser({ id: 'user1' });
    await h.seedProject({ id: 'project1', userId: user.id });
    await h.seedJob({
      id: 'job1', projectId: 'project1', userId: user.id,
      kind: 'make',
    });

    const first = await claimNext(h);
    assert.equal(first.job.id, 'job1');
    assert.match(first.job.claim_token, /^[a-f0-9]{20}$/);
    assert.equal(first.job.attempt_count, 1);

    const abandonedBytes = Buffer.from('abandoned first render attempt');
    const abandonedHash = sha256(abandonedBytes);
    const firstUpload = await h.request('/api/worker/jobs/job1/output/start', {
      method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
      json: { claim_token: first.job.claim_token,
        size: abandonedBytes.length, content_sha256: abandonedHash,
        part_hashes: [abandonedHash] },
    });
    assert.equal(firstUpload.status, 200);

    const wrongProgress = await h.request('/api/worker/jobs/job1/progress', {
      method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
      json: { claim_token: '0'.repeat(20), line: 'wrong owner' },
    });
    assert.equal(wrongProgress.status, 409);

    await h.db.prepare(
      'UPDATE jobs SET lease_expires_at = ? WHERE id = ?',
    ).bind(Date.now() - 1000, 'job1').run();
    const second = await claimNext(h);
    assert.equal(second.job.id, 'job1');
    assert.notEqual(second.job.claim_token, first.job.claim_token);
    assert.equal(second.job.attempt_count, 2);
    const abandoned = await h.row(
      'SELECT status FROM render_uploads WHERE job_id = ? AND claim_token = ?',
      'job1', first.job.claim_token);
    assert.equal(abandoned.status, 'abandoned');

    const staleProgress = await h.request('/api/worker/jobs/job1/progress', {
      method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
      json: { claim_token: first.job.claim_token, line: 'stale owner' },
    });
    assert.equal(staleProgress.status, 409);
    const staleCompletion = await h.request('/api/worker/jobs/job1/complete', {
      method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
      json: { claim_token: first.job.claim_token, ok: false, error: 'stale' },
    });
    assert.equal(staleCompletion.status, 409);

    const heartbeat = await h.request('/api/worker/jobs/job1/progress', {
      method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
      json: { claim_token: second.job.claim_token, line: 'active owner' },
    });
    assert.equal(heartbeat.status, 200);
    const stored = await h.row('SELECT * FROM jobs WHERE id = ?', 'job1');
    assert.equal(stored.claim_token, second.job.claim_token);
    assert.equal(stored.status, 'running');
    assert.ok(stored.lease_expires_at > Date.now());
    assert.deepEqual(JSON.parse(stored.progress_json), ['active owner']);

    await h.db.prepare(
      'UPDATE jobs SET attempt_count = 3, lease_expires_at = ? WHERE id = ?',
    ).bind(Date.now() - 1000, 'job1').run();
    const exhausted = await claimNext(h);
    assert.equal(exhausted.job, null);
    const failed = await h.row('SELECT * FROM jobs WHERE id = ?', 'job1');
    assert.equal(failed.status, 'failed');
    assert.equal(failed.render_slot, 0);
    assert.equal(failed.claim_token, null);
    assert.equal(failed.error, 'claim retry limit reached');
    const failedProject = await h.row(
      'SELECT status FROM projects WHERE id = ?', 'project1');
    assert.equal(failedProject.status, 'failed');
  });

test('concurrent Make requests create exactly one active render', async (t) => {
  const h = await createHarness(t);
  const user = await h.seedUser({ id: 'maker' });
  await h.seedProject({ id: 'makeproject', userId: user.id });
  await h.seedSource({
    id: 'source1', projectId: 'makeproject', userId: user.id,
  });
  const make = () => h.request('/api/projects/makeproject/make', {
    method: 'POST', cookie: user.session, json: { script: 'Keep every word.' },
  });
  const responses = await Promise.all([make(), make()]);
  assert.deepEqual(responses.map((response) => response.status).sort(),
    [200, 409]);
  const count = await h.row(
    'SELECT COUNT(*) AS count FROM jobs WHERE project_id = ?', 'makeproject');
  assert.equal(count.count, 1);
  const active = await h.row(
    'SELECT COUNT(*) AS count FROM jobs WHERE project_id = ? AND render_slot = 1',
    'makeproject');
  assert.equal(active.count, 1);
  const project = await h.row(
    'SELECT status FROM projects WHERE id = ?', 'makeproject');
  assert.equal(project.status, 'queued');
});

test('revision approval binds the exact validated proposal and rejects old shapes',
  async (t) => {
    const h = await createHarness(t);
    const user = await h.seedUser({ id: 'revisionuser' });
    await h.seedProject({ id: 'revisionproject', userId: user.id });

    const submittedProposal = {
      operations: [
        { op: 'set_edit_style', style: 'short',
          human: 'untrusted model wording' },
        { op: 'set_caption_mode', mode: 'sidecar' },
      ],
      summary: 'Use a short edit with sidecar captions.',
    };
    const approvedProposal = {
      operations: [
        { op: 'set_edit_style', style: 'short',
          human: 'Use short edit pacing' },
        { op: 'set_caption_mode', mode: 'sidecar',
          human: 'Use sidecar captions' },
      ],
      summary: 'Use a short edit with sidecar captions.',
    };
    await h.db.prepare(
      'INSERT INTO revisions (id,project_id,num,request_text,proposal_json,' +
      'needs_approval,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
    ).bind('exactrevision', 'revisionproject', 1, 'Make it vertical.',
      JSON.stringify(submittedProposal), 1, 'proposed', Date.now()).run();

    const approval = await h.request('/api/revisions/exactrevision/approve', {
      method: 'POST', cookie: user.session,
    });
    assert.equal(approval.status, 200);
    assert.deepEqual(await json(approval), {
      job_id: 'revision_apply_exactrevision',
    });
    const storedRevision = await h.row(
      'SELECT status,proposal_json FROM revisions WHERE id = ?',
      'exactrevision');
    assert.equal(storedRevision.status, 'approved');
    assert.deepEqual(JSON.parse(storedRevision.proposal_json), approvedProposal);

    const claimed = await claimNext(h, user.daemon);
    assert.equal(claimed.job.id, 'revision_apply_exactrevision');
    assert.equal(claimed.job.kind, 'revision_apply');
    assert.deepEqual(JSON.parse(claimed.job.payload_json), {
      revision_id: 'exactrevision',
      proposal: approvedProposal,
    });

    const invalidProposals = [
      {
        id: 'oldrevision',
        proposal: { operations: [{ op: 'faster_hook', factor: 1.5 }] },
      },
      {
        id: 'duplicaterevision',
        proposal: { operations: [
          { op: 'set_visual_mode', mode: 'full' },
          { op: 'set_visual_mode', mode: 'baseline' },
        ] },
      },
      {
        id: 'extrafieldrevision',
        proposal: { operations: [
          { op: 'set_aspect_ratio', aspect: '9x16', seconds: 30 },
        ] },
      },
      {
        id: 'invalidchoicerevision',
        proposal: { operations: [
          { op: 'set_edit_profile', profile_id: 'ryan_duffy' },
        ] },
      },
    ];
    let num = 2;
    for (const invalid of invalidProposals) {
      await h.db.prepare(
        'INSERT INTO revisions (id,project_id,num,request_text,proposal_json,' +
        'needs_approval,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
      ).bind(invalid.id, 'revisionproject', num++, 'legacy proposal',
        JSON.stringify(invalid.proposal), 1, 'proposed', Date.now()).run();
      const rejected = await h.request(`/api/revisions/${invalid.id}/approve`, {
        method: 'POST', cookie: user.session,
      });
      assert.equal(rejected.status, 422, invalid.id);
      const revision = await h.row(
        'SELECT status FROM revisions WHERE id = ?', invalid.id);
      assert.equal(revision.status, 'proposed', invalid.id);
      assert.equal(await h.row(
        'SELECT id FROM jobs WHERE id = ?', `revision_apply_${invalid.id}`),
      null, invalid.id);
    }
  });

test('project types and style presets accept only executable engine choices',
  async (t) => {
    const h = await createHarness(t);
    const user = await h.seedUser({ id: 'presetuser' });

    const clips = await h.request('/api/projects', {
      method: 'POST', cookie: user.session,
      json: { type: 'clips', title: 'Unsupported clips' },
    });
    assert.equal(clips.status, 400);

    const extraParam = await h.request('/api/presets', {
      method: 'POST', cookie: user.session,
      json: { name: 'My Style', params: { broll_density: 'more' } },
    });
    assert.equal(extraParam.status, 422);
    const invalidChoice = await h.request('/api/presets', {
      method: 'POST', cookie: user.session,
      json: { name: 'My Style', params: { style: 'fast' } },
    });
    assert.equal(invalidChoice.status, 422);
    const invalidShape = await h.request('/api/presets', {
      method: 'POST', cookie: user.session,
      json: { name: 'My Style', params: ['short'] },
    });
    assert.equal(invalidShape.status, 422);

    const exactParams = {
      style: 'short',
      aspects: '9x16',
      caption_mode: 'burned',
      visual_mode: 'full',
      profile: 'generic_short',
    };
    const validPresetResponse = await h.request('/api/presets', {
      method: 'POST', cookie: user.session,
      json: { name: 'My Shorts Style', params: exactParams },
    });
    assert.equal(validPresetResponse.status, 200);
    const validPreset = await json(validPresetResponse);
    const stored = await h.row(
      'SELECT params_json FROM style_presets WHERE id = ?', validPreset.id);
    assert.deepEqual(JSON.parse(stored.params_json), exactParams);
    const project = await h.request('/api/projects', {
      method: 'POST', cookie: user.session,
      json: { type: 'short', title: 'Executable short',
        style_preset_id: validPreset.id },
    });
    assert.equal(project.status, 200);
  });

test('project deletion and daemon claiming cannot both win', async (t) => {
  const h = await createHarness(t);
  const user = await h.seedUser({ id: 'deleteuser' });
  await h.seedProject({ id: 'deleteproject', userId: user.id });
  await h.seedJob({
    id: 'deletejob', projectId: 'deleteproject', userId: user.id,
    kind: 'transcribe',
  });
  const [deletion, claim] = await Promise.all([
    h.request('/api/projects/deleteproject', {
      method: 'DELETE', cookie: user.session,
    }),
    h.request('/api/worker/next-job', {
      method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
    }),
  ]);
  const claimed = await json(claim);
  if (deletion.status === 200) {
    assert.equal(claimed.job, null);
    assert.equal(await h.row(
      'SELECT id FROM projects WHERE id = ?', 'deleteproject'), null);
    assert.equal(await h.row(
      'SELECT id FROM jobs WHERE id = ?', 'deletejob'), null);
  } else {
    assert.equal(deletion.status, 409);
    assert.equal(claimed.job.id, 'deletejob');
    const job = await h.row('SELECT status FROM jobs WHERE id = ?', 'deletejob');
    assert.equal(job.status, 'running');
    assert.ok(await h.row(
      'SELECT id FROM projects WHERE id = ?', 'deleteproject'));
  }
});

test('source multipart rejects checksum and fingerprint substitution',
  async (t) => {
    const h = await createHarness(t);
    const user = await h.seedUser({ id: 'uploader' });
    await h.seedProject({ id: 'uploadproject', userId: user.id, status: 'empty' });
    const bytes = Buffer.from('verified source bytes');
    const partHash = sha256(bytes);
    const correctFingerprint = multipartFingerprint(bytes.length, [partHash]);
    const wrongFingerprint = 'a'.repeat(64);

    const invalid = await h.request('/api/projects/uploadproject/uploads', {
      method: 'POST', cookie: user.session,
      json: { filename: 'clip.mp4', size: bytes.length,
        source_fingerprint: 'not-a-fingerprint' },
    });
    assert.equal(invalid.status, 400);

    const wrongStartResponse = await h.request(
      '/api/projects/uploadproject/uploads', {
        method: 'POST', cookie: user.session,
        json: { filename: 'clip.mp4', size: bytes.length,
          source_fingerprint: wrongFingerprint },
      });
    assert.equal(wrongStartResponse.status, 200);
    const wrongStart = await json(wrongStartResponse);

    const corrupt = Buffer.from(bytes);
    corrupt[0] ^= 0xff;
    const corruptPart = await h.request(
      `/api/uploads/${wrongStart.upload_id}/part?n=1`, {
        method: 'PUT', cookie: user.session, body: corrupt,
        headers: {
          'content-length': String(corrupt.length),
          'x-autoeditor-part-sha256': partHash,
        },
      });
    assert.equal(corruptPart.status, 422);

    const acceptedWrongPart = await h.request(
      `/api/uploads/${wrongStart.upload_id}/part?n=1`, {
        method: 'PUT', cookie: user.session, body: bytes,
        headers: {
          'content-length': String(bytes.length),
          'x-autoeditor-part-sha256': partHash,
        },
      });
    assert.equal(acceptedWrongPart.status, 200);
    const rejectedCompletion = await h.request(
      `/api/uploads/${wrongStart.upload_id}/complete`, {
        method: 'POST', cookie: user.session,
      });
    assert.equal(rejectedCompletion.status, 422);
    const rejectedRow = await h.row(
      'SELECT status FROM uploads WHERE id = ?', wrongStart.upload_id);
    assert.equal(rejectedRow.status, 'rejected');

    const correctStartResponse = await h.request(
      '/api/projects/uploadproject/uploads', {
        method: 'POST', cookie: user.session,
        json: { filename: 'clip.mp4', size: bytes.length,
          source_fingerprint: correctFingerprint },
      });
    const correctStart = await json(correctStartResponse);
    assert.equal(correctStart.resumed, false);
    assert.notEqual(correctStart.upload_id, wrongStart.upload_id);
    const resumedResponse = await h.request(
      '/api/projects/uploadproject/uploads', {
        method: 'POST', cookie: user.session,
        json: { filename: 'clip.mp4', size: bytes.length,
          source_fingerprint: correctFingerprint },
      });
    const resumed = await json(resumedResponse);
    assert.equal(resumed.resumed, true);
    assert.equal(resumed.upload_id, correctStart.upload_id);

    const part = await h.request(
      `/api/uploads/${correctStart.upload_id}/part?n=1`, {
        method: 'PUT', cookie: user.session, body: bytes,
        headers: {
          'content-length': String(bytes.length),
          'x-autoeditor-part-sha256': partHash,
        },
      });
    assert.equal(part.status, 200);
    const completed = await h.request(
      `/api/uploads/${correctStart.upload_id}/complete`, {
        method: 'POST', cookie: user.session,
      });
    assert.equal(completed.status, 200);
    const upload = await h.row(
      'SELECT * FROM uploads WHERE id = ?', correctStart.upload_id);
    assert.equal(upload.status, 'done');
    const stored = await h.media.get(upload.r2_key);
    assert.deepEqual(Buffer.from(await stored.arrayBuffer()), bytes);
    const project = await h.row(
      'SELECT status FROM projects WHERE id = ?', 'uploadproject');
    assert.equal(project.status, 'uploaded');
    const make = await h.request('/api/projects/uploadproject/make', {
      method: 'POST', cookie: user.session,
      json: { script: 'The rejected upload must not block this edit.' },
    });
    assert.equal(make.status, 200);
    const queued = await h.row(
      'SELECT COUNT(*) AS count FROM jobs WHERE project_id = ?',
      'uploadproject');
    assert.equal(queued.count, 1);
  });

test('render multipart, QA binding, completion, and exact replay are enforced',
  async (t) => {
    const h = await createHarness(t);
    const user = await h.seedUser({ id: 'renderer' });
    await h.seedProject({ id: 'renderproject', userId: user.id });
    await h.seedSource({
      id: 'render-source', projectId: 'renderproject', userId: user.id,
    });
    await h.seedJob({
      id: 'renderjob', projectId: 'renderproject', userId: user.id,
    });
    const claimed = await claimNext(h);
    const claimToken = claimed.job.claim_token;
    const outputBytes = Buffer.from('deterministic rendered mp4 bytes');
    const outputHash = sha256(outputBytes);

    const startedResponse = await h.request(
      '/api/worker/jobs/renderjob/output/start', {
        method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
        json: { claim_token: claimToken, size: outputBytes.length,
          content_sha256: outputHash, part_hashes: [outputHash] },
      });
    assert.equal(startedResponse.status, 200);
    const started = await json(startedResponse);
    assert.match(started.output_key,
      new RegExp(`^u/${user.id}/renderproject/out/renderjob/${claimToken}_`));

    const damaged = Buffer.from(outputBytes);
    damaged[0] ^= 0xff;
    const rejectedPart = await h.request(
      '/api/worker/jobs/renderjob/output/part?n=1', {
        method: 'PUT', daemonToken: GLOBAL_DAEMON_TOKEN, body: damaged,
        headers: {
          'content-length': String(damaged.length),
          'x-autoeditor-claim-token': claimToken,
          'x-autoeditor-part-sha256': outputHash,
        },
      });
    assert.equal(rejectedPart.status, 422);

    const acceptedPart = await h.request(
      '/api/worker/jobs/renderjob/output/part?n=1', {
        method: 'PUT', daemonToken: GLOBAL_DAEMON_TOKEN, body: outputBytes,
        headers: {
          'content-length': String(outputBytes.length),
          'x-autoeditor-claim-token': claimToken,
          'x-autoeditor-part-sha256': outputHash,
        },
      });
    assert.equal(acceptedPart.status, 200);

    const completedUploadResponse = await h.request(
      '/api/worker/jobs/renderjob/output/complete', {
        method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
        json: { claim_token: claimToken },
      });
    assert.equal(completedUploadResponse.status, 200);
    const completedUpload = await json(completedUploadResponse);
    assert.equal(completedUpload.output_key, started.output_key);
    assert.equal(completedUpload.qa_key, started.qa_key);
    assert.equal(completedUpload.content_sha256, outputHash);
    const uploadReplayResponse = await h.request(
      '/api/worker/jobs/renderjob/output/complete', {
        method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
        json: { claim_token: claimToken },
      });
    assert.equal(uploadReplayResponse.status, 200);
    assert.deepEqual(await json(uploadReplayResponse), completedUpload);

    const qa = {
      pass: true,
      checks: { speech_integrity: { ok: true } },
      release: { final: { sha256: outputHash } },
      _autoeditor: {
        claim_token: claimToken,
        output_key: started.output_key,
        output_content_sha256: outputHash,
        output_multipart_sha256: completedUpload.multipart_sha256,
        output_size: outputBytes.length,
      },
    };
    const qaBytes = Buffer.from(JSON.stringify(qa));
    const qaHash = sha256(qaBytes);
    const completionBody = JSON.stringify({
      claim_token: claimToken,
      ok: true,
      output_key: started.output_key,
      qa_key: started.qa_key,
    });
    const beforeQa = await h.request(
      '/api/worker/jobs/renderjob/complete', {
        method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
        body: completionBody,
        headers: { 'content-type': 'application/json' },
      });
    assert.equal(beforeQa.status, 422);
    const wrongQaBytes = Buffer.from('{"pass":false}');
    const wrongQa = await h.request('/api/worker/jobs/renderjob/qa', {
      method: 'PUT', daemonToken: GLOBAL_DAEMON_TOKEN, body: wrongQaBytes,
      headers: {
        'content-length': String(wrongQaBytes.length),
        'x-autoeditor-claim-token': claimToken,
        'x-autoeditor-sha256': 'b'.repeat(64),
      },
    });
    assert.equal(wrongQa.status, 422);
    const qaResponse = await h.request('/api/worker/jobs/renderjob/qa', {
      method: 'PUT', daemonToken: GLOBAL_DAEMON_TOKEN, body: qaBytes,
      headers: {
        'content-length': String(qaBytes.length),
        'x-autoeditor-claim-token': claimToken,
        'x-autoeditor-sha256': qaHash,
      },
    });
    assert.equal(qaResponse.status, 200);

    const complete = () => h.request(
      '/api/worker/jobs/renderjob/complete', {
        method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
        body: completionBody,
        headers: { 'content-type': 'application/json' },
      });

    await h.db.prepare(
      "CREATE TRIGGER force_completion_rollback " +
      "BEFORE UPDATE OF status ON projects WHEN NEW.status = 'ready' " +
      "BEGIN SELECT RAISE(ABORT, 'forced completion rollback'); END",
    ).run();
    const rolledBackCompletion = await complete();
    assert.equal(rolledBackCompletion.status, 503);
    const retryableJob = await h.row(
      'SELECT status,claim_token,render_slot FROM jobs WHERE id = ?',
      'renderjob');
    assert.equal(retryableJob.status, 'running');
    assert.equal(retryableJob.claim_token, claimToken);
    assert.equal(retryableJob.render_slot, 1);
    const rolledBackRevisions = await h.db.prepare(
      'SELECT id FROM revisions WHERE project_id = ?',
    ).bind('renderproject').all();
    assert.equal(rolledBackRevisions.results.length, 0);
    await h.db.exec('DROP TRIGGER force_completion_rollback;');

    const firstCompletion = await complete();
    assert.equal(firstCompletion.status, 200);
    const firstReceipt = await firstCompletion.text();
    const replayCompletion = await complete();
    assert.equal(replayCompletion.status, 409);
    assert.equal(await replayCompletion.text(), firstReceipt);

    const inexactReplay = await h.request(
      '/api/worker/jobs/renderjob/complete', {
        method: 'POST', daemonToken: GLOBAL_DAEMON_TOKEN,
        body: `${completionBody}\n`,
        headers: { 'content-type': 'application/json' },
      });
    assert.equal(inexactReplay.status, 409);
    assert.notEqual(await inexactReplay.text(), firstReceipt);

    const job = await h.row('SELECT * FROM jobs WHERE id = ?', 'renderjob');
    assert.equal(job.status, 'done');
    assert.equal(job.render_slot, 0);
    assert.equal(job.claim_token, null);
    assert.equal(job.completion_request_hash, sha256(completionBody));
    const revisions = await h.db.prepare(
      'SELECT * FROM revisions WHERE project_id = ?',
    ).bind('renderproject').all();
    assert.equal(revisions.results.length, 1);
    assert.equal(revisions.results[0].output_key, started.output_key);
    assert.equal(revisions.results[0].qa_pass, 1);
    const project = await h.row(
      'SELECT status FROM projects WHERE id = ?', 'renderproject');
    assert.equal(project.status, 'ready');
  });

test('browser and daemon routes enforce two-user ownership', async (t) => {
  const h = await createHarness(t);
  const owner = await h.seedUser({ id: 'owner' });
  const stranger = await h.seedUser({ id: 'stranger' });
  await h.seedProject({ id: 'privateproject', userId: owner.id });
  const mediaKey = await h.seedSource({
    id: 'private-source', projectId: 'privateproject', userId: owner.id,
  });
  await h.seedJob({
    id: 'privatejob', projectId: 'privateproject', userId: owner.id,
    kind: 'transcribe',
  });

  const projectRead = await h.request('/api/projects/privateproject', {
    cookie: stranger.session,
  });
  assert.equal(projectRead.status, 404);
  const projectDelete = await h.request('/api/projects/privateproject', {
    method: 'DELETE', cookie: stranger.session,
  });
  assert.equal(projectDelete.status, 404);
  const uploadStart = await h.request('/api/projects/privateproject/uploads', {
    method: 'POST', cookie: stranger.session,
    json: { filename: 'stolen.mp4', size: 10,
      source_fingerprint: 'a'.repeat(64) },
  });
  assert.equal(uploadStart.status, 404);
  const mediaRead = await h.request(`/api/media/${encodeURIComponent(mediaKey)}`, {
    cookie: stranger.session,
  });
  assert.equal(mediaRead.status, 403);

  const strangerClaim = await claimNext(h, stranger.daemon);
  assert.equal(strangerClaim.job, null);
  const ownerClaim = await claimNext(h, owner.daemon);
  assert.equal(ownerClaim.job.id, 'privatejob');
  const stolenProgress = await h.request(
    '/api/worker/jobs/privatejob/progress', {
      method: 'POST', daemonToken: stranger.daemon,
      json: { claim_token: ownerClaim.job.claim_token, line: 'stolen' },
    });
  assert.equal(stolenProgress.status, 409);
  const stolenCompletion = await h.request(
    '/api/worker/jobs/privatejob/complete', {
      method: 'POST', daemonToken: stranger.daemon,
      json: { claim_token: ownerClaim.job.claim_token, ok: false,
        error: 'stolen' },
    });
  assert.equal(stolenCompletion.status, 403);
  const ownerMedia = await h.request(
    `/api/worker/media/${encodeURIComponent(mediaKey)}`, {
      daemonToken: owner.daemon,
      headers: {
        'x-autoeditor-job-id': 'privatejob',
        'x-autoeditor-claim-token': ownerClaim.job.claim_token,
      },
    });
  assert.equal(ownerMedia.status, 200);
  assert.equal(await ownerMedia.text(), 'source');
});

test('public Helper runtime contract exposes only the fixed v2 contract',
  async (t) => {
    const h = await createHarness(t);
    const response = await h.request('/download/helper/runtime/contract');
    assert.equal(response.status, 200);
    securityHeaders(response);
    assert.equal(response.headers.get('content-type'), 'application/json');
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await json(response), {
      schema: 'autoeditor-helper-runtime-route/v2',
      release_schema: 'autoeditor-helper-release/v2',
      route: '/download/helper/runtime/windows-x64/{tag}/{commit}',
      max_package_bytes: 4_294_967_294,
    });

    const nearMiss = await h.request('/download/helper/runtime/contract/');
    assert.equal(nearMiss.status, 404);
    securityHeaders(nearMiss);
    assert.equal(nearMiss.headers.get('cache-control'), 'no-store');
  });

test('installer and immutable runtime routes enforce the live release receipt',
  async (t) => {
    const h = await createHarness(t);
    const user = await h.seedUser({ id: 'installeruser' });
    const tag = 'helper-v1.2.3';
    const commit = 'a'.repeat(40);
    const runtimePath =
      `/download/helper/runtime/windows-x64/${tag}/${commit}`;
    const releases = {
      'windows-x64': Buffer.from('windows-installer-bytes'),
      'mac-arm64': Buffer.from('mac-arm-installer-bytes'),
      'mac-x64': Buffer.from('mac-intel-installer-bytes'),
    };
    const filenames = {
      'windows-x64': 'AutoEditor-Helper.exe',
      'mac-arm64': 'AutoEditor-Helper.dmg',
      'mac-x64': 'AutoEditor-Helper.dmg',
    };
    const platforms = {};
    for (const [platform, bytes] of Object.entries(releases)) {
      const hash = sha256(bytes);
      const key = `dist/helper/objects/${hash}/${platform}/${filenames[platform]}`;
      await h.releases.put(key, bytes, {
        customMetadata: { sha256: hash },
      });
      platforms[platform] = { key, bytes: bytes.length, sha256: hash };
    }
    const runtimeBytes = Buffer.from('windows-nsis-web-runtime-package');
    const runtimeHash = sha256(runtimeBytes);
    const runtimePackage = {
      key: `dist/helper/objects/${runtimeHash}/windows-x64/` +
        'AutoEditor-Helper-Windows.nsis.7z',
      filename: 'AutoEditor-Helper-Windows.nsis.7z',
      content_type: 'application/x-7z-compressed',
      bytes: runtimeBytes.length,
      sha256: runtimeHash,
    };
    platforms['windows-x64'].runtime_package = runtimePackage;
    await h.releases.put(runtimePackage.key, runtimeBytes, {
      customMetadata: { sha256: runtimeHash },
    });

    const beforePromotion = await h.request(runtimePath);
    assert.equal(beforePromotion.status, 404);
    securityHeaders(beforePromotion);

    await h.releases.put('dist/helper/current.json', JSON.stringify({
      schema: 'autoeditor-helper-release/v2',
      tag,
      version: '1.2.3',
      source: { commit, run_id: '123', run_attempt: '1' },
      platforms,
    }));

    const unauthenticated = await h.request('/download/helper/availability');
    assert.equal(unauthenticated.status, 401);
    securityHeaders(unauthenticated);
    const unauthenticatedBinary = await h.request('/download/helper/windows');
    assert.equal(unauthenticatedBinary.status, 401);
    securityHeaders(unauthenticatedBinary);
    const unauthenticatedMac = await h.request('/download/helper/mac-arm64');
    assert.equal(unauthenticatedMac.status, 401);
    securityHeaders(unauthenticatedMac);
    const availability = await h.request('/download/helper/availability', {
      cookie: user.session,
    });
    assert.equal(availability.status, 200);
    securityHeaders(availability);
    assert.deepEqual(await json(availability), {
      '/download/helper/windows': true,
      '/download/helper/mac-arm64': true,
      '/download/helper/mac-x64': true,
    });

    const full = await h.request('/download/helper/windows', {
      cookie: user.session,
    });
    assert.equal(full.status, 200);
    securityHeaders(full);
    assert.equal(full.headers.get('accept-ranges'), 'bytes');
    assert.equal(full.headers.get('content-length'),
      String(releases['windows-x64'].length));
    assert.match(full.headers.get('content-disposition'),
      /AutoEditor-Helper-Windows\.exe/);
    assert.deepEqual(Buffer.from(await full.arrayBuffer()),
      releases['windows-x64']);

    const ranged = await h.request('/download/helper/windows', {
      cookie: user.session, headers: { range: 'bytes=2-7' },
    });
    assert.equal(ranged.status, 206);
    securityHeaders(ranged);
    assert.equal(ranged.headers.get('content-range'),
      `bytes 2-7/${releases['windows-x64'].length}`);
    assert.equal(ranged.headers.get('content-length'), '6');
    assert.deepEqual(Buffer.from(await ranged.arrayBuffer()),
      releases['windows-x64'].subarray(2, 8));

    const mac = await h.request('/download/helper/mac-arm64', {
      cookie: user.session,
    });
    assert.equal(mac.status, 200);
    securityHeaders(mac);
    assert.deepEqual(Buffer.from(await mac.arrayBuffer()),
      releases['mac-arm64']);

    const runtimeFull = await h.request(runtimePath);
    assert.equal(runtimeFull.status, 200);
    securityHeaders(runtimeFull);
    assert.equal(runtimeFull.headers.get('accept-ranges'), 'bytes');
    assert.equal(runtimeFull.headers.get('content-type'),
      'application/x-7z-compressed');
    assert.equal(runtimeFull.headers.get('cache-control'), 'no-store');
    assert.equal(runtimeFull.headers.get('content-length'),
      String(runtimeBytes.length));
    assert.deepEqual(Buffer.from(await runtimeFull.arrayBuffer()), runtimeBytes);

    const runtimeRange = await h.request(runtimePath, {
      headers: { range: 'bytes=4-11' },
    });
    assert.equal(runtimeRange.status, 206);
    securityHeaders(runtimeRange);
    assert.equal(runtimeRange.headers.get('content-range'),
      `bytes 4-11/${runtimeBytes.length}`);
    assert.equal(runtimeRange.headers.get('content-length'), '8');
    assert.deepEqual(Buffer.from(await runtimeRange.arrayBuffer()),
      runtimeBytes.subarray(4, 12));

    const openEndedRange = await h.request(runtimePath, {
      headers: { range: 'bytes=4-' },
    });
    assert.equal(openEndedRange.status, 206);
    securityHeaders(openEndedRange);
    assert.equal(openEndedRange.headers.get('content-range'),
      `bytes 4-${runtimeBytes.length - 1}/${runtimeBytes.length}`);
    assert.equal(openEndedRange.headers.get('content-length'),
      String(runtimeBytes.length - 4));
    assert.deepEqual(Buffer.from(await openEndedRange.arrayBuffer()),
      runtimeBytes.subarray(4));

    const suffixRange = await h.request(runtimePath, {
      headers: { range: 'bytes=-7' },
    });
    assert.equal(suffixRange.status, 206);
    securityHeaders(suffixRange);
    assert.equal(suffixRange.headers.get('content-range'),
      `bytes ${runtimeBytes.length - 7}-${runtimeBytes.length - 1}/` +
      `${runtimeBytes.length}`);
    assert.equal(suffixRange.headers.get('content-length'), '7');
    assert.deepEqual(Buffer.from(await suffixRange.arrayBuffer()),
      runtimeBytes.subarray(-7));

    const wrongTag = await h.request(
      `/download/helper/runtime/windows-x64/helper-v1.2.4/${commit}`,
    );
    assert.equal(wrongTag.status, 404);
    const wrongCommit = await h.request(
      `/download/helper/runtime/windows-x64/${tag}/${'b'.repeat(40)}`,
    );
    assert.equal(wrongCommit.status, 404);
    const tagOnly = await h.request(
      `/download/helper/runtime/windows-x64/${tag}`,
    );
    assert.equal(tagOnly.status, 404);

    await h.releases.delete(runtimePackage.key);
    const missingPackage = await h.request('/download/helper/availability', {
      cookie: user.session,
    });
    assert.equal(missingPackage.status, 200);
    assert.deepEqual(await json(missingPackage), {
      '/download/helper/windows': false,
      '/download/helper/mac-arm64': false,
      '/download/helper/mac-x64': false,
    });
    const missingRuntime = await h.request(runtimePath);
    assert.equal(missingRuntime.status, 404);

    await h.releases.put(
      runtimePackage.key, Buffer.concat([runtimeBytes, Buffer.from('x')]), {
        customMetadata: { sha256: runtimeHash },
      },
    );
    const wrongPackageSize = await h.request(
      '/download/helper/availability', { cookie: user.session },
    );
    assert.equal(wrongPackageSize.status, 200);
    assert.deepEqual(await json(wrongPackageSize), {
      '/download/helper/windows': false,
      '/download/helper/mac-arm64': false,
      '/download/helper/mac-x64': false,
    });

    await h.releases.put(runtimePackage.key, runtimeBytes, {
      customMetadata: { sha256: '0'.repeat(64) },
    });
    const tamperedPackage = await h.request('/download/helper/availability', {
      cookie: user.session,
    });
    assert.equal(tamperedPackage.status, 200);
    assert.deepEqual(await json(tamperedPackage), {
      '/download/helper/windows': false,
      '/download/helper/mac-arm64': false,
      '/download/helper/mac-x64': false,
    });
    const tamperedRuntime = await h.request(runtimePath);
    assert.equal(tamperedRuntime.status, 404);

    await h.releases.put(runtimePackage.key, runtimeBytes, {
      customMetadata: { sha256: runtimeHash },
    });

    const macArm = platforms['mac-arm64'];
    await h.releases.put(macArm.key, releases['mac-arm64'], {
      customMetadata: { sha256: '0'.repeat(64) },
    });
    const unavailable = await h.request('/download/helper/availability', {
      cookie: user.session,
    });
    assert.equal(unavailable.status, 200);
    assert.deepEqual(await json(unavailable), {
      '/download/helper/windows': false,
      '/download/helper/mac-arm64': false,
      '/download/helper/mac-x64': false,
    });
    const blocked = await h.request('/download/helper/windows', {
      cookie: user.session,
    });
    assert.equal(blocked.status, 503);
    securityHeaders(blocked);

    await h.releases.delete('dist/helper/current.json');
    const afterPointerRemoval = await h.request(runtimePath);
    assert.equal(afterPointerRemoval.status, 404);
    securityHeaders(afterPointerRemoval);
  });
