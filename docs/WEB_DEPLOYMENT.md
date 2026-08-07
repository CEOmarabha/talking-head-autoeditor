# Web Deployment (friends render on their own PCs)

Architecture: a serverless Cloudflare Worker is the website + API + job
queue (Cloudflare keeps it up 24/7, $0, zero uptime work for Omar). Each
friend runs a tiny Helper on their OWN computer that renders only their own
jobs. Nothing runs on Omar's machine.

## What is already provisioned (done in this session)

- D1 database `autoeditor-web` (id `28a0100d-7996-4d8d-b979-180086527c08`),
  full schema applied.
- R2 bucket `autoeditor-media` (private).
- Worker `autoeditor-web` created with D1 (`DB`) + R2 (`MEDIA`) bindings.
- Secrets set (encrypted, persist across deploys): `KEY_WRAP_SECRET`,
  `WORKER_TOKEN`, `ADMIN_TOKEN`.

The live URL is https://autoeditor-web.<your-subdomain>.workers.dev — right
now it still serves the placeholder page because the real Worker code has
not been uploaded yet. That is the one remaining deploy step.

## Step 1 — upload the real Worker code (one command, from Omar's Mac)

The dashboard code-paste and the raw API are both blocked by Cloudflare's
WAF for a script this size, so use wrangler (it uploads natively):

```bash
cd talking-head-autoeditor/webapp/worker
npx wrangler deploy
```

`wrangler.toml` already points at the live D1 id and R2 bucket, and the
three secrets are already set, so this single command publishes the real
site with everything wired. Re-run it any time you change the code.

Verify: open the URL; you should see the AutoEditor sign-in screen (not
"Hello World").

## Step 2 — invite a friend and mint their connect code

```bash
BASE=https://autoeditor-web.<your-subdomain>.workers.dev
ADMIN=<ADMIN_TOKEN>          # the value you set as the secret

# 1) invite (they use this once to make their account)
curl -X POST $BASE/api/admin/invites -H "authorization: Bearer $ADMIN" \
  -H 'content-type: application/json' -d '{"note":"Alex"}'
#   -> {"code":"abc123..."}   send this to the friend

# 2) after they have signed in once, mint their personal connect code
#    (renders ONLY their jobs; use their exact display name)
curl -X POST $BASE/api/admin/daemon-tokens -H "authorization: Bearer $ADMIN" \
  -H 'content-type: application/json' -d '{"user_name":"Alex"}'
#   -> {"token":"..."}        send this to the friend as their connect code
```

## Step 3 — the friend sets up their Helper (once, on their PC)

Send them `docs/FRIEND_WEB_GUIDE.md`. In short: install FFmpeg + Python,
run `webapp/render_worker/install_helper.sh`, then launch
`friend_helper.py`, paste the site address + their connect code. It renders
their jobs whenever it's open; they close it when done. Their PC is the only
machine that has to be on, and only while they want a video made.

## Local development / acceptance rig (unchanged)

```bash
cd webapp/worker
printf 'KEY_WRAP_SECRET=dev\nWORKER_TOKEN=dev\nADMIN_TOKEN=dev\n' > .dev.vars
npx wrangler d1 execute autoeditor-web --local --file schema.sql
npx wrangler dev --local --port 8787
# run the helper against it with AUTOEDITOR_WEB_API=http://127.0.0.1:8787
```

## Rollback

`npx wrangler delete autoeditor-web`, then delete the R2 bucket and D1
database in the dashboard (export first — this destroys user media/state).
The desktop app and engine are untouched.
