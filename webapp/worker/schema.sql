-- D1 schema for the private hosted AutoEditor.
CREATE TABLE IF NOT EXISTS invites (
  code TEXT PRIMARY KEY,
  note TEXT DEFAULT '',
  used_by TEXT,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,     -- unique (enforced in app code at signup)
  invite_code TEXT NOT NULL,
  key_ct TEXT,            -- AES-GCM ciphertext of DeepSeek key (b64)
  key_iv TEXT,            -- b64 IV; NEVER return either field over the API
  totp_secret TEXT,       -- active OTP secret (base32), NULL = OTP off
  totp_pending TEXT,      -- secret awaiting first verification
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS daemon_tokens (
  token TEXT PRIMARY KEY,
  user_id TEXT,           -- NULL = global daemon; else that user's Helper
  note TEXT DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS style_presets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,      -- "My Style", "My Shorts Style", ...
  params_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  type TEXT NOT NULL,      -- short|long|commercial|podcast|course|clips|custom
  title TEXT NOT NULL,
  style_preset_id TEXT,
  status TEXT NOT NULL DEFAULT 'empty',
  status_detail TEXT DEFAULT '',
  transcript TEXT,
  delete_token TEXT,      -- non-NULL while destructive cleanup owns project
  delete_lease_expires_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  r2_key TEXT NOT NULL,
  filename TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0,
  mp_upload_id TEXT,       -- R2 multipart id while in flight
  parts_json TEXT DEFAULT '[]',
  -- uploading|interrupted|completing:<started_ms>:<lease_token>|done
  status TEXT NOT NULL DEFAULT 'uploading',
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,      -- transcribe|make|chat_proposal|revision_apply
  -- queued|running|finishing:<claim>|done|failed|cancelled
  status TEXT NOT NULL DEFAULT 'queued',
  payload_json TEXT NOT NULL DEFAULT '{}',   -- NO key material, ever
  progress_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  created_at INTEGER NOT NULL,
  started_at INTEGER,
  claim_token TEXT,                      -- exact daemon attempt owner
  lease_expires_at INTEGER,              -- heartbeat-controlled claim expiry
  attempt_count INTEGER NOT NULL DEFAULT 0,
  render_slot INTEGER NOT NULL DEFAULT 0,-- one queued/running render/project
  completion_request_hash TEXT,          -- exact committed HTTP body receipt
  completion_receipt_json TEXT,
  finished_at INTEGER
);
CREATE TABLE IF NOT EXISTS render_uploads (
  job_id TEXT NOT NULL,
  claim_token TEXT NOT NULL,
  r2_key TEXT NOT NULL,
  qa_key TEXT NOT NULL,
  mp_upload_id TEXT NOT NULL,
  size INTEGER NOT NULL,
  content_sha256 TEXT NOT NULL,
  multipart_sha256 TEXT NOT NULL,
  expected_parts_json TEXT NOT NULL,
  uploaded_parts_json TEXT NOT NULL DEFAULT '[]',
  -- uploading|completing|done
  status TEXT NOT NULL DEFAULT 'uploading',
  completion_token TEXT,
  completion_lease_expires_at INTEGER,
  r2_etag TEXT,
  created_at INTEGER NOT NULL,
  completed_at INTEGER,
  PRIMARY KEY (job_id, claim_token)
);
CREATE TABLE IF NOT EXISTS revisions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  num INTEGER NOT NULL,
  request_text TEXT NOT NULL DEFAULT '',
  proposal_json TEXT,      -- typed edit proposal awaiting approval
  needs_approval INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'proposed',
  -- proposed|approved|rejected|applied|superseded
  output_key TEXT,         -- R2 key of rendered mp4
  qa_key TEXT,             -- R2 key of QA_REPORT.json
  qa_pass INTEGER,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  role TEXT NOT NULL,      -- user|assistant|system
  content TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limits (
  bucket_key TEXT PRIMARY KEY,
  window_start INTEGER NOT NULL,
  count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name ON users(name);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active_render
  ON jobs(project_id) WHERE render_slot = 1;
CREATE INDEX IF NOT EXISTS idx_jobs_claim
  ON jobs(id, claim_token, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_render_uploads_job
  ON render_uploads(job_id, claim_token, status);
CREATE INDEX IF NOT EXISTS idx_uploads_project ON uploads(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_revisions_project_num
  ON revisions(project_id, num);
CREATE INDEX IF NOT EXISTS idx_revisions_project ON revisions(project_id);
