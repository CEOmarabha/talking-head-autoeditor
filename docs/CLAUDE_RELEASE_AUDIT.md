# AutoEditor: Independent Deep Release Audit

Reviewer: Claude (Cowork), independent final review per
`docs/CLAUDE_DEEP_RELEASE_REVIEW_PROMPT.md`.
Repository: `/Users/ceomarabha/Desktop/talking-head-autoeditor`
Branch: `web-app`   HEAD at audit start: `bb8fbf2` ("Build verified private
AutoEditor release pipeline")   Upstream: none tracked.
Worktree: clean except untracked `.cache/`, `docs/RELEASE_V2_1.md`,
`docs/examples/V2_1_REGRESSION_PROOFS.md` (left untouched, as instructed).
Audit date: 2026-08-07.

This is a historical snapshot of `bb8fbf2`. The generic six-profile and
five-operation revision contract was added later. Use
`docs/RELEASE_GATE_STATUS.md` for current status and rerun every affected gate
before release.

Method: four independent specialist reviewers (web/worker security; engine +
DeepSeek gating; packaging/supply-chain/licensing; friend-experience +
accessibility) plus direct execution evidence. No prior doc, test name, or
completion claim was trusted; each claim was reconciled with the live code and
a real artifact or local behavior. No push, deploy, tag, publish, PR, account,
or secret change was performed.

--------------------------------------------------------------------------
## Top-line decision

RELEASE IS BLOCKED for friend distribution. This matches, and does not
overturn, the honest status in `docs/RELEASE_GATE_STATUS.md`. The engineering
core is sound; the blocks are the things no source test can close: a real
signed Windows installer and a notarized/stapled macOS DMG, built from this
revision and run on real machines, plus an unresolved GPL corresponding-source
obligation. Nothing in this audit may be read as "signed", "notarized",
"friend ready", "secure", "private", or "production ready" for the artifact,
because the exact signed deliverable was never built or accepted here.

What DID pass, with evidence, is the source layer: tests, the fail-closed QA
and speech-protection invariants, dependency-lock integrity, npm audit, secret
hygiene, and the account/isolation logic. Details below.

--------------------------------------------------------------------------
## What I verified passed (evidence)

- Python safety + web contract tests: `93 passed, 17 subtests` via
  `python3 -m pytest tests/ webapp/tests/` in a clean container with the
  engine deps installed. (Gate doc says "78 Python + 15 web"; the current
  tree totals 93 across both suites; the count grew, claim not overstated.)
- Desktop Helper tests: all four files pass individually via `node --test`
  (`clip-catalog`, `helper-setup`, `platform-contracts`, `process-tree`).
- Engine/DeepSeek gating invariants CONFIRMED by reading the real code paths
  (see `autoeditor/pipeline.py` delivery/quarantine/promote logic and the
  final gates): delivery is quarantine-first (`quarantine_outputs` renames to
  `*.UNVERIFIED` before any gate), `qa["pass"]` is an AND across all gates,
  `promote_outputs` runs only on pass, failure exits 2 with `needs_review`,
  and every gate function defaults to `{"ok": False}` on missing data. The AI
  cannot bypass speech or QA gates.
- Historical Py/JS proposal parity was confirmed at `bb8fbf2`. That allowlist
  is superseded. The current release must separately prove parity for the five
  executable generic operations, server-bound proposal delivery, and rejection
  of speech, duration, clip-splitting, and other unmapped requests.
- Prompt-injection safety confirmed: transcript/filenames reach DeepSeek
  prompts, but deterministic validation AFTER the model prevents the model
  from widening its own permissions or exfiltrating the key (key never enters
  a prompt; lives only in the Authorization header / child env).
- Dependency locks: `packaging/requirements-{windows-x64,mac-arm64,mac-x64}
  .txt`: every package version-pinned with exactly one platform-correct
  `--hash`; no manylinux wheels in the mac locks; per-platform hash
  differences verified against PyPI (e.g. `ctranslate2 4.8.1`). Claim
  CONFIRMED.
- npm audit: 0 vulnerabilities at the configured level across
  `desktop/`, `packaging/helper-runtime/`, `templates/remotion-viz/`,
  `webapp/worker/` lockfiles (reviewer ran it live).
- Secret scan: CLEAN. Full-tree scan for `sk-`, `Bearer`, `AKIA`, PEM
  private keys, `ghp_`, `AIza`, Slack tokens, and literal key/token/secret
  assignments found only test fixtures and placeholders; `wrangler.toml`
  holds a D1 `database_id` (a resource id, not a credential).
- Worker security claims: two-user isolation, output-path ownership,
  multipart resume, sign-in rate limiting, authenticated installer downloads,
  and byte ranges are all backed by real code. Correction: "two-user tests"
  are static source-string assertions in `webapp/tests/test_web.py`, not a
  runtime two-user harness (the code is correctly scoped; the test wording is
  overstated). Security headers were site-only before this audit (fixed
  below).
- Attribution PASS: "Omar Marabha / @CEOmarabha" appears tastefully in the
  website footer, Helper footer, `desktop/package.json`, the helper
  electron-builder metadata, and engine result metadata, not watermarked on
  user videos. Guarded by tests.

--------------------------------------------------------------------------
## Defects found and FIXED in this audit (with proof)

All fixes are in `webapp/worker/src/index.js`, the site, the helper, and CI,
and preserve the fail-closed QA/speech protections. Post-fix: worker parses,
93 tests still pass, and three fixes are behaviorally verified locally.

1. [MED] API/media/installer responses lacked security headers (only static
   HTML got them). Media keys embed `u/<userId>/<projectId>/...`, so a missing
   `referrer-policy` could leak user paths via `Referer`, and missing HSTS
   left an SSL-strip window on the API.
   Fix: added `BASE_SECURITY_HEADERS` (`nosniff`, `referrer-policy:
   no-referrer`, HSTS) to the `j()` helper so every API response carries them,
   and added `referrer-policy`/HSTS to the media stream responses.
   Proof: `curl -D- /api/me` now returns `Strict-Transport-Security`,
   `referrer-policy: no-referrer`, `x-content-type-options: nosniff`.

2. [LOW-MED] No rate limit on the DeepSeek-spending endpoints (`/me/key`,
   `/assistant`, `/chat`); only `/auth/signin` was capped.
   Fix: per-user `withinRateLimit` buckets on `/me/key` (20 / 10 min),
   `/assistant` and `/chat` (40 / 5 min).
   Proof: hammering `/me/key` returned twenty `422`s then `429` exactly at the
   configured limit.

3. [LOW] Revision approval was not atomic (double-click/replay → duplicate
   render): a `SELECT status` check then an unconditional `UPDATE`.
   Fix: `UPDATE revisions SET status='approved' WHERE id=? AND
   status='proposed'` and enqueue only when `changes === 1`.

4. [LOW] Invite claim race: two concurrent signups on one invite could both
   see `used_by NULL` and both create accounts.
   Fix: claim the invite atomically first (`UPDATE invites SET used_by=? WHERE
   code=? AND used_by IS NULL`, check `changes===1`) before creating the user.
   Proof: sequential reuse correctly logs into the existing account (invite is
   the account password by design); the atomic guard closes the concurrent
   window.

5. [LOW] Upload part handler skipped the size check when `Content-Length` was
   omitted, and neither part nor complete guarded `status='uploading'`.
   Fix: require `Content-Length` (411 if absent), reject parts against a
   non-`uploading` upload (409), make `/complete` idempotent and its status
   flip atomic.

6. [LOW] 206 media responses omitted `Content-Length` (minor seek/correctness
   nit). Fix: set `content-length` on both 206 and 200 media branches.

7. [HIGH, friend-path] `webapp/deploy.sh` still built and uploaded the OLD
   Python/terminal Helper (`helper.zip` of a Python source tree whose
   launchers run `brew install`, `winget install`, `pip install`) to
   production R2. It is currently unreachable from the site (no Worker route),
   but it violates the "one signed installer, no dev tools, no terminal" bar
   and was one shared object away from reaching a friend.
   Fix: rewrote `deploy.sh` to publish the Worker only, with an explicit note
   that the Helper is the SIGNED installer built by
   `.github/workflows/helper-release.yml`; relocated `helper_dist/`,
   `build_helper_zip.sh`, and `render_worker/install_helper.sh` into
   `webapp/_legacy_terminal_helper_DO_NOT_SHIP/` with a README. Owner action:
   if `dist/helper.zip` already exists in R2, delete it.

8. [LOW, a11y] Site Setup-code and OTP inputs lacked programmatic labels;
   Helper status/detail/checks weren't announced to assistive tech.
   Fix: added `aria-label` to `#cc-value`, `#otp-secret`, `#otp-code`;
   `role="status" aria-live="polite"` to the site project status and the
   Helper status/detail/checks regions.

9. [MED, desktop product] `desktop/electron-builder.yml` shipped GPL
   FFmpeg/x264 with zero license notices (the Helper config already ships
   `licenses/`).
   Fix: added `staging/licenses -> licenses` to the desktop extraResources and
   a `release.yml` staging step that copies `packaging/THIRD_PARTY_NOTICES.md`
   and `LICENSE` into `desktop/staging/licenses/`. This closes the notices
   gap; it does NOT close the GPL corresponding-source obligation (owner/legal
   (see below).

--------------------------------------------------------------------------
## Confirmed defects NOT fixed here (documented for the owner)

These are in the separate desktop/PSE product CI (`.github/workflows/
release.yml`), a different deliverable from the friend Helper. They are real
and should be fixed before that product ships, but are lower priority for the
Helper release and require external SHA/checksum lookups and CI runs I cannot
reproduce or test offline. The friend Helper workflow
(`helper-release.yml`) is already hardened and does NOT share these defects.

- [HIGH] `release.yml` Windows FFmpeg from a mutable `.../releases/latest/...`
  URL with no checksum (line ~45/149). A moving dependency must fail closed.
  Fix pattern: mirror `helper-release.yml` (pin the asset + sha256 compare).
- [HIGH] `release.yml` macOS FFmpeg via unpinned `brew install ffmpeg`
  (line ~121), no version guard. Fix: pin the version and fail on drift, as
  `helper-release.yml` does.
- [MED] `release.yml` Montserrat font from the `master` branch, no checksum
  (line ~157). Fix: pin to a commit SHA (helper workflow already does).
- [MED] `release.yml` + `ci.yml` GitHub Actions pinned to floating tags
  (`@v4`/`@v5`/`@v6`). Fix: pin to full commit SHAs.
- [MED] `packaging/engine.spec` swallows `collect_all` failures with
  `except Exception: pass`, and CI validates the frozen engine only with
  `--help`. A silently-missing backend (onnxruntime/av/ctranslate2 data) would
  pass the gate and fail on a user machine. Fix: stop swallowing, or add a
  real transcribe smoke test to the build.

Non-blocking hardening note: the web render path uploads a QA-failed artifact
to a clean R2 `.../{rev}.mp4` key and relies on `qa_pass=0`/`needs review` (the
on-disk `*.UNVERIFIED` quarantine does not survive into R2; consider an
`_UNVERIFIED` key). At this audit commit, revision application was a default
rerender. The later generic contract supersedes that path and requires fresh
Worker, daemon, browser, and signed-artifact verification.

--------------------------------------------------------------------------
## Licensing / legal (separated from code defects)

Genuine legal uncertainty requiring Omar/counsel, correctly listed as BLOCKED
in `RELEASE_GATE_STATUS.md`; this is not a false claim:

- FFmpeg + x264 (GPL-2.0): bundling in a distributed installer triggers a
  corresponding-source obligation. `THIRD_PARTY_NOTICES.md` is inventory-only
  and self-admits this is open. Notices (now shipped for both products) do NOT
  satisfy corresponding-source. macOS builds capture no source archive (brew);
  the Windows helper records only a download URL. Owner must establish a valid
  written-offer / source-mirror process for the EXACT bundled build.
  Source: GNU GPL-2.0 §3; FFmpeg legal/licensing docs.
- Remotion 4.x: free license is limited to individuals/small orgs; CI renders
  with `--license-key=free-license`. Eligibility for Marabha must be
  confirmed. Source: Remotion licensing terms.
- PyInstaller (GPL-2.0 + bootloader exception): OK to distribute the frozen
  app. Fonts (Montserrat/Work Sans, OFL-1.1), certifi (MPL-2.0), GSAP,
  Chromium/Node/Electron: notices present and adequate.

--------------------------------------------------------------------------
## Sources (accessed 2026-08-07)

- Microsoft SmartScreen / unwanted-app protection:
  https://support.microsoft.com/windows/protect-your-pc-from-potentially-unwanted-applications-c7668a25-174e-3b78-0191-faf0607f7a6e
- Apple notarization:
  https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution
- Cloudflare R2 Workers multipart:
  https://developers.cloudflare.com/r2/api/workers/workers-multipart-usage/
- PydanticAI DeepSeek v4 tool-choice issue (architecture rationale):
  https://github.com/pydantic/pydantic-ai/issues/5193
- GNU GPL-2.0 (corresponding source): https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
- Remotion licensing: https://www.remotion.dev/docs/license
- 1Password onboarding pattern (UI ledger reference):
  https://support.1password.com/getting-started-mac/

--------------------------------------------------------------------------
## Shortest ordered list of what only Omar can still do

1. Configure signing secrets per `docs/OWNER_SIGNING_SETUP.md` (Apple
   Developer ID + notarization; Windows Authenticode / Azure Trusted
   Signing). This BLOCKED gate needs accounts or certificates.
2. Build the SIGNED Windows `.exe` and NOTARIZED+STAPLED macOS DMGs from this
   revision via `helper-release.yml`.
3. On a clean Windows 11 machine and a real Mac (Apple Silicon + Intel):
   install, run, edit a real video start-to-finish for each project type,
   request a DeepSeek revision, quit, reopen, update, uninstall, and verify
   signatures/notarization. Record pass/fail.
4. Resolve the GPL corresponding-source offer for the exact bundled FFmpeg/
   x264, and confirm Remotion license eligibility.
5. Deploy the production Worker from this revision and run the two-user
   isolation acceptance live; delete any stale `dist/helper.zip` from R2.
6. (Desktop product, if shipping) fix the five `release.yml`/`engine.spec`
   supply-chain items above.

Do not publish an unsigned artifact. A friend release is not "ready" until
items 1 to 4 are closed against the exact signed installers.
