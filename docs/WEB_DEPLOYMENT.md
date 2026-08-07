# Private AutoEditor website deployment

This is the owner runbook. Friends never run these commands. Their flow is
only: open the private website, sign in, download one signed installer, paste
one Setup code, connect or skip accounts, and make a video.

## Architecture

- One Cloudflare Worker serves the website and authenticated API.
- D1 stores invite, account, project, queue, chat, and QA state.
- Private R2 stores uploads, outputs, installer files, and checksums.
- Each friend’s signed AutoEditor Helper pulls only that friend’s jobs and
  renders on that friend’s computer.
- DeepSeek chat runs through the Worker. Video editing remains a deterministic
  local pipeline, not a terminal agent or arbitrary code runner.

The configured resources are:

- Worker: `autoeditor-web`
- D1: `autoeditor-web`, id `28a0100d-7996-4d8d-b979-180086527c08`
- R2: `autoeditor-media`
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

## Safe deployment order

This task does not deploy automatically. Before any production change:

1. Export or back up D1 data needed for rollback.
2. From `webapp/worker`, install the exact locked dependency with `npm ci`.
3. Run `npm audit --audit-level=high`.
4. Run the local schema and API acceptance tests.
5. Apply the idempotent schema to production:

   ```bash
   npx wrangler d1 execute autoeditor-web --remote --file schema.sql
   ```

   The current schema adds the server-side sign-in rate-limit table. Confirm
   the command reports that `rate_limits` exists before deploying code that
   calls it.
6. Build without publishing:

   ```bash
   npx wrangler deploy --dry-run
   ```

7. Deploy only after the owner approves the production change:

   ```bash
   npx wrangler deploy
   ```

8. Open `https://autoeditor-web.mromarmarabha.workers.dev`, confirm the real
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
npx wrangler d1 execute autoeditor-web --local \
  --persist-to "$STATE_DIR" --file schema.sql
npx wrangler dev --local --port 8787 --persist-to "$STATE_DIR" \
  --var KEY_WRAP_SECRET:dev-wrap-secret \
  --var WORKER_TOKEN:dev-worker-token \
  --var ADMIN_TOKEN:dev-admin-token
```

The local site may issue a Setup code for `http://127.0.0.1:8787`; the Helper
allows that address only for development. A production Setup code must use the
allowlisted HTTPS host.

## Installer publishing

Do not upload installers by hand. After all platform build, signing,
notarization, smoke, and physical acceptance gates pass, a `helper-v*` tag runs
the release workflow. The workflow uploads the signed Windows installer, both
notarized Mac DMGs, and `SHA256SUMS.txt` to fixed private R2 paths. It creates
the GitHub release only after the private upload succeeds.

## Rollback

- Worker code: redeploy the last accepted commit.
- D1: restore the exported data only after checking schema compatibility.
- Installer: restore all three accepted installer objects and the matching
  checksum file together. Never mix versions across Windows, Apple Silicon,
  and Intel.
- Do not delete the Worker, D1 database, or R2 bucket as a normal rollback.
  Deleting them destroys account state or user media.
