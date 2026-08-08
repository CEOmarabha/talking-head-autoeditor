# Private AutoEditor website deployment

This is the owner runbook. Friends never run these commands. Their flow is
only: open the private website, sign in, download one signed installer, paste
one Setup code, connect or skip accounts, and make a video.

## Architecture

- One Cloudflare Worker serves the website and authenticated API.
- D1 stores invite, account, project, queue, chat, and QA state.
- Private `autoeditor-media` R2 stores user uploads and outputs.
- Separate candidate and live-release R2 buckets keep CI credentials away from
  friends' footage and make installer promotion all-or-none.
- Each friend’s signed AutoEditor Helper pulls only that friend’s jobs and
  renders on that friend’s computer.
- DeepSeek chat runs through the Worker. Video editing remains a deterministic
  local pipeline, not a terminal agent or arbitrary code runner.

Footage is hosted for transfer, not for rendering. The browser uploads source
media to private R2, the friend’s Helper downloads it and renders locally, and
the Helper uploads the output and QA receipt back to private R2. Temporary work
files and provider caches also exist on the friend’s computer. Project deletion
must remove the R2 project objects. No automatic retention period is claimed
until one is implemented and accepted.

## Generic edit contract

The friend product exposes six executable types and bundled profiles:

| Browser type | Engine profile | Engine grammar and delivery |
| --- | --- | --- |
| Short / Reel | `generic_short` | short, 9:16 |
| Long Talking Head | `generic_long` | long, 16:9 |
| Commercial / Ad | `generic_commercial` | commercial contract, short, 9:16 |
| Podcast / Interview | `generic_podcast` | podcast contract, long, 16:9 |
| Course / Lesson | `generic_course` | course contract, long, 16:9 |
| Custom | `generic_custom` | automatic grammar and delivery |

Long-to-clips is outside this release because the engine cannot select moments
and emit several independently gated outputs. PSE remains a separate product
channel and is not one of the friend profiles.

The Worker, render daemon, browser, and packaged profiles must agree on these
five revision operations:

- `set_edit_style`: `auto`, `short`, or `long`.
- `set_aspect_ratio`: `auto`, `9x16`, or `16x9`.
- `set_caption_mode`: `burned` or `sidecar`.
- `set_visual_mode`: `full` or `baseline`. Baseline maps only to the engine’s
  complete `--no-premium` mode.
- `set_edit_profile`: one of the six generic profile IDs above.

The claimed revision job must carry the server-stored approved proposal. The
daemon revalidates that proposal and fails the job when it is absent, changed,
or unsupported. Speech deletion, duration targeting, multi-clip output,
specific asset replacement, caption scaling, grading, and granular punch-in
or b-roll controls are not revision operations in this release.

The repository expects these resources. Their names do not prove that the
production deployment or release gates passed:

- Worker: `autoeditor-web`
- D1: `autoeditor-web`, id `28a0100d-7996-4d8d-b979-180086527c08`
- User media R2: `autoeditor-media`
- Expiring release candidates R2: `autoeditor-release-candidates`
- Live installers R2: `autoeditor-releases`
- Production Helper host allowlist:
  `autoeditor-web.mromarmarabha.workers.dev`

Do not change the production hostname without updating and releasing the
Helper allowlist in `desktop/helper/lib/setup-code.js`.

## Required Cloudflare secrets

The Worker requires:

- `KEY_WRAP_SECRET`: long random secret used to wrap stored DeepSeek keys.
- `WORKER_TOKEN`: long random token for the optional owner-wide daemon.
- `ADMIN_TOKEN`: long random token for owner-only invite creation.

Do not put their values in this repository. Confirm the names exist with
`npx wrangler secret list`. If one is absent, add it interactively with
`npx wrangler secret put NAME`. Rotating `KEY_WRAP_SECRET` without first
re-encrypting stored DeepSeek keys makes existing keys unreadable.

Friends create and fund their own DeepSeek accounts, then enter their own API
keys on the website. DeepSeek is required. Pexels, Pixabay, and ElevenLabs are
connected or explicitly skipped in the local Helper, and those provider keys
stay in the operating system keystore. HyperFrames is bundled locally.
Remotion requires a confirmed applicable free license or a paid public license
key. Account creation instructions belong in `FRIEND_SETUP.md`; friends never
receive the owner secrets above.

## Safe deployment order

This task does not deploy automatically. Before any production change:

1. Export or back up D1 data needed for rollback.
2. From `webapp/worker`, install the exact locked dependency with `npm ci`.
3. Run `npm audit --audit-level=high`.
4. Run the local schema and API acceptance tests.
5. Confirm `autoeditor-releases` exists before deploying. The Worker has a
   required `RELEASES` binding and intentionally has no fallback to the user
   media bucket or old fixed installer keys. Run
   `npx wrangler r2 bucket lock list autoeditor-releases` and confirm
   indefinite locks cover `dist/helper/objects/` and
   `dist/helper/checksums/`, but not `dist/helper/current.json`.
6. Before the migration, check for duplicate account names or revision numbers.
   The new unique indexes intentionally stop instead of choosing which duplicate
   record to keep:

   ```bash
   npx wrangler d1 execute autoeditor-web --remote \
     --command "SELECT name, COUNT(*) AS n FROM users GROUP BY name HAVING n > 1"
   npx wrangler d1 execute autoeditor-web --remote \
     --command "SELECT project_id, num, COUNT(*) AS n FROM revisions GROUP BY project_id, num HAVING n > 1"
   ```

   Resolve any returned rows deliberately before continuing.
7. Apply the ordered D1 migrations. `0001_initial_schema.sql` adopts an
   existing pre-migration database without recreating its tables, then
   `0002_claim_leases_and_render_uploads.sql` adds the lease and upload state:

   ```bash
   npx wrangler d1 migrations list autoeditor-web --remote
   npx wrangler d1 migrations apply autoeditor-web --remote
   ```

   Confirm `render_uploads`, `idx_users_name`,
   `idx_revisions_project_num`, and `idx_jobs_one_active_render` exist. The
   upgrade deliberately fails old running jobs and retires duplicate queued
   renders because they cannot be resumed safely under the new token protocol.
8. Build without publishing:

   ```bash
   npx wrangler deploy --dry-run
   ```

9. Deploy only after the owner approves the production change:

   ```bash
   npx wrangler deploy
   ```

10. Open `https://autoeditor-web.mromarmarabha.workers.dev`, confirm the real
   sign-in page loads, then run the two-account isolation test in
   `LAUNCH_CHECKLIST.md`.

## Invite one friend

Only Omar creates the first invite code. Keep `ADMIN_TOKEN` in a local shell
variable or password manager, never in command history, screenshots, or chat.

```bash
curl -X POST \
  https://autoeditor-web.mromarmarabha.workers.dev/api/admin/invites \
  -H "authorization: Bearer $AUTOEDITOR_ADMIN_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"note":"Friend name"}'
```

Send only the returned invite code and website URL to that friend. After the
friend signs in, the dashboard creates that account’s personal Setup code
automatically. The owner does not mint or send a separate daemon token.

An invite code remains that account’s fallback password. The friend can enable
6-digit authenticator codes under Sign-in settings. Never put multiple friends
on the same invite or Helper Setup code.

## Local API acceptance rig

Keep local state outside the repository:

```bash
STATE_DIR=/tmp/autoeditor-wrangler-state
npx wrangler d1 migrations apply autoeditor-web --local \
  --persist-to "$STATE_DIR"
npx wrangler dev --local --port 8787 --persist-to "$STATE_DIR" \
  --var KEY_WRAP_SECRET:dev-wrap-secret \
  --var WORKER_TOKEN:dev-worker-token \
  --var ADMIN_TOKEN:dev-admin-token
```

The local site may issue a Setup code for `http://127.0.0.1:8787`; the Helper
allows that address only for development. A production Setup code must use the
allowlisted HTTPS host.

## Installer publishing

Do not upload installers by hand. A `helper-v*` tag builds, verifies, signs, and
notarizes all three platform candidates. Those jobs can write only to the
expiring candidate bucket and upload seven-day signed-candidate artifacts for
physical acceptance. The tagged workflow stops there. It cannot write the live
bucket or `dist/helper/current.json`.

After the exact signed Windows, Apple Silicon, and Intel candidates from one run
pass physical acceptance, Omar manually runs **Promote accepted AutoEditor
Helper release** with that tag, run ID, full commit SHA, and the explicit
acceptance checkbox. The protected workflow proves the source run and tag,
requires all three receipts to bind the same run attempt, rejects downgrades or
same-version provenance changes, and stream-hashes each candidate before and
after its content-addressed copy. It prepares and rereads the metadata-only
GitHub release, then conditionally updates `dist/helper/current.json` last. The
Worker refuses every installer route if any one of the three pointed-to objects
is missing or fails its receipt. The live object and checksum prefixes are also
protected by the indefinite bucket lock rules in `r2-release-locks.json`; the
pointer is intentionally unlocked.

## Rollback

- Worker code: redeploy the last accepted commit.
- D1: restore the exported data only after checking schema compatibility.
- Installer: restore the previously accepted `dist/helper/current.json`.
  Content-addressed installers and checksums remain immutable in the live
  bucket. Never hand-edit the pointer or mix platform receipts.
- Do not delete the Worker, D1 database, or R2 bucket as a normal rollback.
  Deleting them destroys account state or user media.
