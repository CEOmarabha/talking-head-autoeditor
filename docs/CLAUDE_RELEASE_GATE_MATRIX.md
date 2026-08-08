# AutoEditor: Release Gate Matrix

Companion to `docs/CLAUDE_RELEASE_AUDIT.md`. One row per release gate.
Status vocabulary (per `docs/CLAUDE_DEEP_RELEASE_REVIEW_PROMPT.md`):

- **PASS**: direct, current evidence in this audit (a command output or an
  inspected artifact). A source test is never accepted as artifact acceptance.
- **FAIL**: evidence shows the gate is not met.
- **BLOCKED**: cannot be closed without a named certificate, secret, account,
  hardware, artifact, or permission that only Omar controls.
- **NOT RUN**: not exercised in this audit and not blocked; owner must run it.

Branch `web-app`, HEAD `bb8fbf2` at audit start. Audit date 2026-08-07.
Reviewer: Claude (Cowork), independent final review.

This matrix is a historical snapshot of `bb8fbf2`. The later generic
six-profile and five-operation revision contract supersedes affected source
rows. Current release status lives in `docs/RELEASE_GATE_STATUS.md`.

--------------------------------------------------------------------------

## A. Source, tests, and engine invariants

| # | Gate | Status | Command / artifact | Result | Remaining owner action |
|---|------|--------|--------------------|--------|------------------------|
| A1 | Python safety + web contract tests | PASS | `python3 -m pytest tests/ webapp/tests/` | 93 passed, 17 subtests, clean container w/ engine deps | none |
| A2 | Desktop Helper unit tests | PASS | `node --test` per file (clip-catalog, helper-setup, platform-contracts, process-tree) | all four pass individually (aggregate runner quirk only) | none |
| A3 | Fail-closed QA gate (AND across gates, exit 2 on fail) | PASS | read `autoeditor/pipeline.py` gate/promote/quarantine paths | `qa["pass"]` is AND; each gate defaults `{"ok": False}`; promote only on pass | none |
| A4 | Quarantine-before-gates delivery | PASS | read `quarantine_outputs`/`promote_outputs` | outputs renamed `*.UNVERIFIED` before any gate; promoted only on full pass | none |
| A5 | DeepSeek cannot bypass speech/QA gates | PASS | read gate ordering + deterministic post-model validation | model output validated AFTER generation; cannot widen permissions | none |
| A6 | Current Py/JS edit-proposal parity and proposal binding | NOT RUN | generic contract added after this audit | old allowlist result is superseded; current five-op parity and server-bound proposal were not tested here | rerun against current Worker, daemon, and browser |
| A7 | Prompt-injection safety (transcript/filenames → DeepSeek) | PASS | trace key handling + post-model validation | key never enters a prompt (header/child-env only); deterministic validation blocks widening/exfil | none |
| A8 | API key redaction in logs/results | PASS | reviewer grep of log/result emitters | key not logged or echoed in result metadata | none |

## B. Web / Worker security (fixed + verified in this audit)

| # | Gate | Status | Command / artifact | Result | Remaining owner action |
|---|------|--------|--------------------|--------|------------------------|
| B1 | Security headers on API/media/installer responses | PASS | `curl -D- /api/me` against local `wrangler dev` after fix | HSTS + `referrer-policy: no-referrer` + `nosniff` now present (added to `j()` and media) | deploy this revision so headers reach prod |
| B2 | Rate limiting on DeepSeek-spend endpoints | PASS | hammer `/me/key` locally after fix | 20×422 then 429 at limit; `/assistant`+`/chat` capped 40/5min | deploy this revision |
| B3 | Atomic invite claim (concurrent signup race) | PASS | sequential reuse test + conditional `UPDATE ... WHERE used_by IS NULL` | reuse logs into same account (by design); atomic guard closes concurrent window | deploy this revision |
| B4 | Atomic revision approval (double-click/replay) | PASS (code) | read `UPDATE revisions SET status='approved' WHERE id=? AND status='proposed'`, enqueue on `changes===1` | duplicate-render window closed | deploy; re-confirm live |
| B5 | Upload part/complete guards (size, status, idempotency) | PASS (code) | read Content-Length 411 guard, `status='uploading'` 409 guard, atomic complete | over-read + double-complete windows closed | deploy; re-confirm live |
| B6 | Two-user isolation / output-path ownership | PASS (code) | read scoping + `webapp/tests/test_web.py` | code correctly scopes by `u/<userId>/...`; NOTE: tests are static string assertions, not a runtime two-user harness | run live two-user acceptance post-deploy (B12) |
| B7 | Sign-in rate limiting | PASS (code) | read `/auth/signin` `withinRateLimit` | capped | deploy |
| B8 | Authenticated installer downloads + byte ranges | PASS (code) | read range + auth on media/installer routes | 206/200 both set content-length after fix; auth enforced | deploy |
| B9 | Legacy Python/terminal helper removed from deploy path | PASS | rewrote `webapp/deploy.sh` (Worker-only); relocated helper_dist/build_helper_zip/install_helper → `_legacy_terminal_helper_DO_NOT_SHIP/` | friend can no longer receive a Python source tree via deploy | if `dist/helper.zip` exists in R2, delete it |
| B10 | Accessibility labels (site + Helper) | PASS | added `aria-label` (#cc-value/#otp-secret/#otp-code) + `role=status aria-live` regions | assistive-tech gaps closed | none |
| B11 | Live Worker deployed from THIS revision | NOT RUN | `npx wrangler deploy` (owner-run; AI keystrokes into Terminal are blocked) | not deployed in audit | owner deploys this revision |
| B12 | Live two-user isolation acceptance | NOT RUN | manual two-account run against deployed Worker | not exercised live | run after B11 |

## C. Supply chain / packaging

| # | Gate | Status | Command / artifact | Result | Remaining owner action |
|---|------|--------|--------------------|--------|------------------------|
| C1 | Python dependency locks pinned + hashed, per-platform | PASS | inspect `packaging/requirements-{windows-x64,mac-arm64,mac-x64}.txt` | every pkg version-pinned, one platform-correct `--hash`; no manylinux wheels in mac locks | none |
| C2 | npm audit across all lockfiles | PASS | `npm audit` in desktop/, packaging/helper-runtime/, templates/remotion-viz/, webapp/worker/ | 0 vulnerabilities at configured level | none |
| C3 | Secret scan (full tree) | PASS | grep sk-/Bearer/AKIA/PEM/ghp_/AIza/Slack/assignments | only fixtures/placeholders; `wrangler.toml` D1 id is a resource id, not a credential | none |
| C4 | Friend Helper CI hardened (`helper-release.yml`) | PASS | read workflow | SHA-pinned actions, hashed pip locks, checksummed FFmpeg | none |
| C5 | Desktop product CI FFmpeg (Windows) checksummed/pinned | FAIL | `release.yml` ~L45/149 mutable `releases/latest` URL, no checksum | moving dependency does not fail closed | mirror helper workflow: pin asset + sha256 |
| C6 | Desktop product CI FFmpeg (macOS) pinned | FAIL | `release.yml` ~L121 unpinned `brew install ffmpeg` | no version guard | pin version, fail on drift |
| C7 | Desktop product CI font integrity | FAIL | `release.yml` ~L157 Montserrat from `master`, no checksum | mutable font source | pin to commit SHA |
| C8 | GitHub Actions pinned to commit SHAs | FAIL | `release.yml` + `ci.yml` use `@v4/@v5/@v6` floating tags | supply-chain drift risk | pin to full commit SHAs |
| C9 | Frozen-engine completeness validated (not just `--help`) | FAIL | `packaging/engine.spec` `except Exception: pass`; CI validates with `--help` | a silently-missing backend passes gate, fails on user machine | stop swallowing, or add real transcribe smoke test |

## D. Signed artifacts / installer acceptance (the release-blocking gates)

| # | Gate | Status | Command / artifact | Result | Remaining owner action |
|---|------|--------|--------------------|--------|------------------------|
| D1 | Signing secrets configured | BLOCKED | per `docs/OWNER_SIGNING_SETUP.md` | missing: Apple Developer ID + notarization creds; Windows Authenticode / Azure Trusted Signing cert | create accounts/certs, set secrets |
| D2 | Signed Windows `.exe` built from this revision | BLOCKED | `helper-release.yml` artifact | no signing cert → no signed installer produced/inspected here | build after D1 |
| D3 | Notarized + stapled macOS DMG (arm64 + x64) built | BLOCKED | `helper-release.yml` artifact | no Apple creds → no notarized DMG produced/inspected here | build after D1 |
| D4 | Windows install/run/upgrade/uninstall on clean Win 11 | BLOCKED | run signed `.exe` on real hardware | requires D2 + a clean Windows machine | run full lifecycle, record pass/fail |
| D5 | macOS Gatekeeper/quarantine/mount/relaunch on real Mac | BLOCKED | run notarized DMG on Apple Silicon + Intel | requires D3 + real Macs | run full lifecycle incl. offline relaunch |
| D6 | End-to-end edit per project type on signed build | BLOCKED | edit a real video start-to-finish, request a DeepSeek revision | requires D2/D3 artifacts | run for each project type |
| D7 | Signature/notarization verification on the exact artifact | BLOCKED | `signtool verify` / `spctl -a -vv` / `stapler validate` | no artifact to verify | verify against shipped installers |

## E. Licensing / legal

| # | Gate | Status | Command / artifact | Result | Remaining owner action |
|---|------|--------|--------------------|--------|------------------------|
| E1 | GPL third-party NOTICES shipped with binaries | PASS | `electron-builder.yml` (helper) + fix adding `staging/licenses -> licenses` to desktop + `release.yml` staging step | both products now bundle notices | none (notices only) |
| E2 | GPL corresponding-source obligation (FFmpeg/x264) | BLOCKED | GPL-2.0 §3; `THIRD_PARTY_NOTICES.md` self-admits open | notices ≠ corresponding source; mac captures no source archive, Windows records only a URL | establish written-offer/source-mirror for the EXACT bundled build (owner/counsel) |
| E3 | Remotion license eligibility | BLOCKED | CI renders `--license-key=free-license` | free license limited to individuals/small orgs; Marabha eligibility unconfirmed | confirm eligibility or buy a license |
| E4 | PyInstaller / fonts / certifi / Electron notices adequate | PASS | inspect `THIRD_PARTY_NOTICES.md` | PyInstaller (GPL + bootloader exception) OK; Montserrat/Work Sans OFL-1.1, certifi MPL-2.0 present | none |

--------------------------------------------------------------------------

## Release decision (from the matrix)

**BLOCKED for friend distribution.** Every source, engine, and web-security
gate that can be closed here is PASS (A1 to A8, B1 to B10, C1 to C4, E1, E4). The
release is held by two independent walls that no source test can close:

1. **Signed-artifact acceptance (D1 to D7, BLOCKED)**: no signing certificates,
   so no signed Windows `.exe` and no notarized macOS DMG were ever built,
   installed, or verified. This is the primary block.
2. **Legal (E2 corresponding-source, E3 Remotion, BLOCKED)**: decisions only
   Omar/counsel can make.

Deployment gates B11 and B12 are NOT RUN (owner deploys this revision, then runs
live two-user acceptance). Desktop-product supply-chain gates C5 to C9 are FAIL
but scoped to the separate desktop/PSE product, not the friend Helper.

Shortest ordered owner actions: (1) configure signing secrets (D1); (2) build
signed Win `.exe` + notarized Mac DMGs from this revision (D2 and D3); (3) run the
full install/edit/upgrade/uninstall lifecycle on real Windows + Mac hardware
and verify signatures (D4 to D7); (4) resolve GPL corresponding-source + Remotion
eligibility (E2 and E3); (5) deploy this Worker revision and run live two-user
acceptance (B11 and B12); (6) if shipping the desktop product, fix C5 to C9.

Do not publish an unsigned artifact. A friend release is not "ready" until
D1 to D7 and E2 and E3 are closed against the exact signed installers.

--------------------------------------------------------------------------

## Addendum 2026-08-07: real Mac acceptance run (unsigned DMG at c697aa3)

Omar ran the first real-hardware Mac acceptance against an unsigned 2.2 GB
`AutoEditor Helper` DMG. The editing core passed (engine + web tests, locked
deps, frozen arm64 engine/daemon, bundled FFmpeg/Whisper/Node/HyperFrames/
Remotion/Chrome, real HyperFrames and Remotion MP4 renders, DMG built and
mounted, setup window usable). The installer itself FAILED acceptance. New
gate rows, with the fixes committed after the run:

| # | Gate | Status at run | Fix in this commit | Remaining owner action |
|---|------|---------------|--------------------|------------------------|
| F1 | Packed app contains creative runtime node_modules | FAIL: electron-builder pruned node_modules from extraResources; HyperFrames + Remotion missing in the DMG | explicit `creative-runtime/node_modules` file set in `electron-builder.helper.yml`; CI gate "Verify the packed app ships the complete creative runtime" inspects the PACKED app; contract test locks both | rebuild, confirm gate passes |
| F2 | Packaged Helper smoke test | FAIL: downstream of F1 (preflight checks hyperframesCli/remotionCli existence) | resolved by F1; smoke unchanged (it caught the defect correctly) | re-run on rebuilt DMG |
| F3 | Signature survives packaging (no post-seal Finder metadata) | FAIL: Finder metadata attached after sealing broke `codesign --strict` | plain DMG (no background/volume icon); staging stripped of `.DS_Store`/`._*`/xattrs before sealing; CI now verifies the app from a fresh DMG mount incl. FinderInfo xattr check | re-run; verify from the mounted DMG, not a Finder-browsed folder |
| F4 | Mac CI calls the correct app executable | FAIL: hardcoded binary name was wrong | both workflows resolve `CFBundleExecutable` from the bundle's Info.plist | none |
| F5 | FFmpeg pin accepts Homebrew bottle revisions | FAIL: guard rejected `8.1.2_1` (a rebuild of the same 8.1.2 source) | regex accepts `8.1.2(_N)?`, still rejects real version moves | none |
| F6 | Real app icon | FAIL: default Electron icon | `desktop/build/icon.{icns,ico,png}` added and wired into both products | replace with final brand art whenever desired |
| F7 | Developer ID signing + notarization | BLOCKED (unchanged, = D1 to D3) | n/a | configure signing secrets |
| F8 | Worker transaction fixes present | STALE FINDING: the report flagged them unresolved, but HEAD `c697aa3` contains all of them (atomic invite claim, atomic revision approval, atomic upload complete, rate limits, security headers; verified by line inspection on the device repo) | none needed | re-test against a Worker deployed from HEAD, not an older checkout |

Order to green: rebuild the Mac DMG from this commit, repeat the mounted-DMG
smoke + signature + launch + real-edit test, then build Windows, then the MSI
friend-workflow walkthrough. The failed DMG at
`work/mac-acceptance-c697aa3/` is evidence only. Never distribute it.

--------------------------------------------------------------------------

## Addendum 2026-08-08: current local result at 3ad08be

This addendum supersedes the historical A6, C5 to C9, and F1 to F6 states. It
does not change signed, production, provider, or legal blocks.

| Gate | Current status | Direct evidence |
|------|----------------|-----------------|
| Current five-operation revision contract and proposal binding | PASS | Python safety, web, and nine-test Worker Miniflare suites passed; Worker claim payload carries the canonical approved proposal |
| Desktop Windows FFmpeg pin, Mac FFmpeg guard, font pin, Action SHA pins, frozen-engine completeness | PASS | current workflow and platform contracts passed; frozen engine self-test passed from the mounted artifact |
| Creative runtime present in packed app | PASS | mounted manifest verified HyperFrames 0.7.99, Remotion 4.0.507, Node 22.23.2, and Chrome 152.0.7928.2 |
| Packaged Helper creative smoke | PASS | all six desktop-smoke booleans true; real HyperFrames and Remotion renders completed |
| Finder metadata and strict code seal | PASS for unsigned arm64 | fresh read-only mount had no FinderInfo or ResourceFork; `codesign --deep --strict` passed with the expected ad hoc signature |
| Correct executable and product icon | PASS | normal mounted Electron renderer launched and produced a decoded 1440x4624 UI screenshot with the shipped branding |
| Mounted real edit | PASS for unsigned arm64 Commercial | 83-second 9:16 edit passed QA, caption safety, exact geometry, full decode, and four 0 ms source-sync probes |
| Six generic profiles packaged and executable | PASS mechanically | all six exact profile hashes rendered from the mounted DMG, passed QA/full decode, and delivered exact 9:16 or 16:9 geometry |
| Wrangler migration and bundle path | PASS locally | both migrations applied through Wrangler 4.120.0, dry-run bundle contained all bindings, and live local two-user HTTP checks passed |

The six-profile run uses one synthetic fixture. It proves packaged execution,
not representative creative quality for long talking head, podcast, course, or
both Custom auto branches. Developer ID, notarization, Authenticode, signed
physical acceptance, production Cloudflare, real accounts, GPL corresponding
source, and Remotion eligibility remain blocked exactly as stated in
`RELEASE_GATE_STATUS.md`.
