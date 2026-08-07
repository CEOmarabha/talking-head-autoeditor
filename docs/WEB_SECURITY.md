# Web Security Model

## Trust boundaries

1. Browser (untrusted user input, trusted user identity via session).
2. Cloudflare Worker (trusted logic; holds KEY_WRAP_SECRET, WORKER_TOKEN,
   ADMIN_TOKEN as Worker secrets).
3. D1 (data at rest; contains DeepSeek keys ONLY as AES-GCM ciphertext).
4. R2 (private media; no public access; all reads flow through
   authenticated Worker routes).
5. Render host (Omar's Mac; holds KEY_WRAP_SECRET in env; the only place
   plaintext DeepSeek keys ever exist, in process memory, per job).
6. DeepSeek API (receives the user's own key over TLS, as designed).

## DeepSeek key lifecycle (threat model)

- Entry: browser -> HTTPS -> `PUT /api/me/key`. The Worker immediately
  AES-256-GCM encrypts (key = SHA-256(KEY_WRAP_SECRET), fresh 12-byte IV)
  and stores ciphertext+IV on the user row. The plaintext is request-scoped
  and never logged (the Worker's catch-all logs only error name + message,
  never request bodies).
- At rest: ciphertext in D1. A D1 dump alone cannot recover keys without
  the Worker secret.
- Dispatch: the render daemon authenticates with WORKER_TOKEN and receives
  ciphertext only. Job rows, queue payloads, progress logs, revisions,
  chat, R2 keys, and URLs never contain key fields (enforced by schema:
  keys live only on `users.key_ct/key_iv`; verified by the acceptance
  sweep, which greps logs, every D1 row, and R2 blobs for the plaintext).
- Use: the daemon decrypts in memory, passes the key to the engine child
  via env. `AUTOEDITOR_PACKAGED=1` guarantees the engine reads env only
  and writes no dotfiles. The engine never prints env. The reference is
  dropped when the job ends.
- No third-party queue ever sees key material: the only queue is our own
  D1 table, and it carries no key fields at all.
- Compromise scenarios: Worker secret alone -> can decrypt only if D1 is
  also compromised (same blast radius as the Worker itself). Render host
  compromise -> keys for jobs processed while compromised are exposed:
  same blast radius as the machine that renders the videos. Browser
  compromise -> that user's own key only.

## Authentication and isolation

- Invite-only: accounts exist only through single-use codes minted by the
  admin bearer token. Sessions are 30-day httpOnly Secure SameSite=Lax
  cookies; tokens are 52 random hex chars.
- Every project/upload/revision/media query is scoped by `user_id` from
  the session, and R2 media paths embed the owner id
  (`u/<user>/<project>/...`) with a server-side prefix check on every
  read. Verified in acceptance: cross-account project read 404, media 403,
  signed-out 401.
- The daemon API is a separate bearer-token surface with no session
  crossover; the admin API likewise.

## Media

- R2 bucket is private. Browser access streams through
  `GET /api/media/<key>` with per-user prefix enforcement (equivalent to
  short-lived signed URLs, with the advantage that authorization is
  re-checked on every request rather than while a signed URL lives).
- Uploads are multipart through the Worker; part state persists in D1 so
  an interrupted upload resumes instead of silently losing the project.

## DeepSeek as untrusted planner

- Chat requests become typed proposals validated deterministically against
  `ALLOWED_OPS` (bounded params, max 8 ops, whole-proposal rejection on
  any unknown op: no partial application).
- Speech-affecting, duration-affecting, licensing, and spend ops carry
  `approval: true` and require an explicit user OK in the UI before an
  apply job can exist. Visual-only ops auto-apply.
- The engine's fail-closed QA gates remain authoritative: a render that
  fails any required gate is delivered as Needs Review, never as final
  (verified in acceptance: blank-frame fixture correctly quarantined).

## Resource acquisition (v1 boundary)

v1 permits only the engine's licensed-API asset path (Pexels/Pixabay)
with per-asset receipts (source URL, license, hash, project). There is no
repo cloning, package installation, or arbitrary download surface exposed
to friends. The full Resource Broker (sandboxed repo evaluation,
capability approval flow) is specified for a later phase and requires a
paid sandbox decision plus Omar's per-capability approval; Hermes remains
an admin-only sidecar.

## Known gaps (tracked, not hidden)

- No rate limiting on auth endpoints yet (invite codes are high-entropy;
  add Cloudflare rate rules before widening the invite list).
- Session revocation is delete-on-signout only; no admin "kill session"
  UI yet (delete the D1 row manually if needed).
- The render daemon trusts Worker-supplied R2 keys; a compromised Worker
  could direct it to overwrite other users' outputs. Same blast radius as
  the Worker itself.
