-- Apply once before deploying the claim-token Worker.
ALTER TABLE projects ADD COLUMN delete_token TEXT;
ALTER TABLE projects ADD COLUMN delete_lease_expires_at INTEGER;

ALTER TABLE jobs ADD COLUMN claim_token TEXT;
ALTER TABLE jobs ADD COLUMN lease_expires_at INTEGER;
ALTER TABLE jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN render_slot INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN completion_request_hash TEXT;
ALTER TABLE jobs ADD COLUMN completion_receipt_json TEXT;

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
  status TEXT NOT NULL DEFAULT 'uploading',
  completion_token TEXT,
  completion_lease_expires_at INTEGER,
  r2_etag TEXT,
  created_at INTEGER NOT NULL,
  completed_at INTEGER,
  PRIMARY KEY (job_id, claim_token)
);

-- Existing active jobs predate leases and cannot be safely resumed. Mark them
-- failed so every post-migration render begins with a fresh, tokened claim.
UPDATE jobs
SET status = 'failed', error = 'release upgrade requires a fresh render',
    finished_at = CAST(strftime('%s','now') AS INTEGER) * 1000
WHERE status = 'running' OR status LIKE 'finishing:%';

UPDATE jobs
SET render_slot = 1
WHERE status = 'queued'
  AND kind IN ('transcribe','make','revision_apply')
  AND id = (
    SELECT oldest.id FROM jobs AS oldest
    WHERE oldest.project_id = jobs.project_id
      AND oldest.status = 'queued'
      AND oldest.kind IN ('transcribe','make','revision_apply')
    ORDER BY oldest.created_at, oldest.id LIMIT 1
  );

UPDATE jobs
SET status = 'cancelled', error = 'duplicate render removed during upgrade',
    finished_at = CAST(strftime('%s','now') AS INTEGER) * 1000
WHERE status = 'queued'
  AND kind IN ('transcribe','make','revision_apply')
  AND render_slot = 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active_render
  ON jobs(project_id) WHERE render_slot = 1;
CREATE INDEX IF NOT EXISTS idx_jobs_claim
  ON jobs(id, claim_token, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_render_uploads_job
  ON render_uploads(job_id, claim_token, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name
  ON users(name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_revisions_project_num
  ON revisions(project_id, num);
