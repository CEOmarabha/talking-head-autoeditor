# Web Deployment

## Components

- `webapp/worker/`: Cloudflare Worker (site + API + queue). D1 + R2.
- `webapp/site/`: static SPA served by the Worker's assets binding.
- `webapp/render_worker/`: Python daemon; runs on the render host
  (v1: Omar's Mac) next to the verified engine.

## One-time setup (Omar)

```bash
cd webapp/worker
npx wrangler login                       # Omar's Cloudflare account
npx wrangler d1 create autoeditor-web    # paste id into wrangler.toml
npx wrangler d1 execute autoeditor-web --remote --file schema.sql
npx wrangler r2 bucket create autoeditor-media
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # x3
npx wrangler secret put KEY_WRAP_SECRET
npx wrangler secret put WORKER_TOKEN
npx wrangler secret put ADMIN_TOKEN
npx wrangler deploy                      # prints the workers.dev URL
```

Invite a friend:

```bash
curl -X POST https://<worker-url>/api/admin/invites \
  -H "Authorization: Bearer <ADMIN_TOKEN>" \
  -H "content-type: application/json" -d '{"note":"friend name"}'
```

## Render daemon (on the Mac)

```bash
cd talking-head-autoeditor
AUTOEDITOR_WEB_API=https://<worker-url> \
WORKER_TOKEN=<WORKER_TOKEN> \
KEY_WRAP_SECRET=<KEY_WRAP_SECRET> \
python3 webapp/render_worker/render_worker.py
```

Keep it alive with `launchd` or a `caffeinate -s` session. The daemon is
stateless; restart it any time. Jobs marked `running` when it dies stay
running in the DB; re-queue by setting status back to `queued` (admin
D1 query) or delete them.

## Local development / acceptance rig

```bash
cd webapp/worker
printf 'KEY_WRAP_SECRET=dev\nWORKER_TOKEN=dev\nADMIN_TOKEN=dev\n' > .dev.vars
npx wrangler d1 execute autoeditor-web --local --file schema.sql
npx wrangler dev --local --port 8787
# then run the daemon with AUTOEDITOR_WEB_API=http://127.0.0.1:8787
```

## Scale-out path (paid; ask Omar first)

Containerize the daemon (plain Python + ffmpeg + repo checkout + env
vars) and run N instances on RunPod/EC2 against the same Worker API. No
Worker changes required: the daemon protocol is pull-based and stateless.

## Rollback

The web layer is additive. To remove it: `npx wrangler delete
autoeditor-web`, delete the R2 bucket and D1 database (destroys user
media/state: export first), stop the daemon, and revert the single branch.
The desktop app and engine are untouched by any of this.
