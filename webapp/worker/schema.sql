-- D1 schema for the private hosted AutoEditor.
CREATE TABLE IF NOT EXISTS invites (
  code TEXT PRIMARY KEY,
  note TEXT DEFAULT '',
  used_by TEXT,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  invite_code TEXT NOT NULL,
  key_ct TEXT,            -- AES-GCM ciphertext of DeepSeek key (b64)
  key_iv TEXT,            -- b64 IV; NEVER return either field over the API
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
  status TEXT NOT NULL DEFAULT 'uploading',  -- uploading|interrupted|done
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,      -- transcribe|make|chat_proposal|revision_apply
  status TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|failed|cancelled
  payload_json TEXT NOT NULL DEFAULT '{}',   -- NO key material, ever
  progress_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  created_at INTEGER NOT NULL,
  started_at INTEGER,
  finished_at INTEGER
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
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_uploads_project ON uploads(project_id);
CREATE INDEX IF NOT EXISTS idx_revisions_project ON revisions(project_id);
