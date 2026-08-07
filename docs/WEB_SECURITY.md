# Web Security Model

## Trust boundaries

1. Browser (untrusted user input, trusted user identity via session).
2. Cloudflare Worker (trusted logic; holds KEY_WRAP_SECRET, WORKER_TOKEN,
   ADMIN_TOKEN as Worker secrets).
3. D1 (data at rest; contains DeepSeek keys ONLY as AES-GCM ciphertext).
4. R2 (private media; no public access; all reads flow through
   authenticated Worker routes).
5. Friend Helper and render engine (the friend’s signed local app; holds only
   that friend’s personal Helper token and connected provider keys in the OS
   keystore).
6. Optional global owner render host (holds KEY_WRAP_SECRET only when the
   owner intentionally runs the global daemon).
7. DeepSeek API (receives the user's own key over TLS, as designed).

## DeepSeek key lifecycle (threat model)

- Entry: browser -> HTTPS -> `PUT /api/me/key`. The Worker immediately
  AES-256-GCM encrypts (key = SHA-256(KEY_WRAP_SECRET), fresh 12-byte IV)
  and stores ciphertext+IV on the user row. The plaintext is request-scoped
  and never logged (the Worker's catch-all logs only error name + message,
  never request bodies).
- At rest: ciphertext in D1. A D1 dump alone cannot recover keys without
  the Worker secret.
- Dispatch: a personal Helper token can claim only that user’s jobs. The
  Worker unwraps that user’s key and returns the plaintext over HTTPS for that
  one claimed job. It does not return the stored ciphertext fields to a
  personal Helper. The optional global owner daemon receives ciphertext and
  unwraps it locally with KEY_WRAP_SECRET.
- Use: the daemon passes the key to the engine child through the process
  environment. `AUTOEDITOR_PACKAGED=1` guarantees the engine reads the
  environment only and writes no key dotfiles. The engine never prints its
  environment. The in-process key reference is dropped when the job ends.
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
  crossover. Personal daemon tokens recheck job ownership on progress and
  completion, media routes enforce the user prefix, output keys must match the
  claimed job’s user and project, and revision IDs come from the server-created
  job payload. The admin API is separate as well.
- Sign-in attempts are limited per hashed client address in D1. The stored
  rate-limit key does not contain the raw address.

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

- Session revocation is delete-on-signout only; no admin "kill session"
  UI yet (delete the D1 row manually if needed).
- A compromised Worker can still direct a local engine to process malicious
  input within that user’s job scope. The Helper therefore accepts Setup codes
  only from the production AutoEditor host and keeps the engine non-agentic.
