# Paste this entire prompt into Claude Code

You are the final independent release reviewer for AutoEditor. Work directly in
this canonical repository:

`/Users/ceomarabha/Desktop/talking-head-autoeditor`

The active branch should be `web-app`. Confirm the exact path, branch, HEAD,
worktree status, and upstream before doing anything. Stop if you opened a
different project. Preserve every unrelated user change. Do not edit or stage
`.cache/`, `docs/RELEASE_V2_1.md`, or
`docs/examples/V2_1_REGRESSION_PROOFS.md`. Do not push, deploy, tag, publish,
open a pull request, buy anything, create accounts, rotate secrets, or change
GitHub, Cloudflare, Microsoft, Apple, DeepSeek, Pexels, Pixabay, ElevenLabs, or
Remotion configuration without Omar's explicit approval in that same session.

Your job is to perform a wider and deeper adversarial review, fix every
confirmed in-scope source defect you can safely fix, rerun the relevant checks,
and give an evidence-backed release decision. Do not trust the existing docs,
test names, comments, prior summaries, or passing workflow text. Reconcile each
claim with the active code path and a real artifact or live local behavior.

Read these before reviewing:

1. `AGENTS.md` and every applicable child instruction.
2. `docs/RELEASE_GATE_STATUS.md`.
3. `docs/LAUNCH_CHECKLIST.md`.
4. `docs/OWNER_SIGNING_SETUP.md`.
5. `docs/WEB_SECURITY.md` and `docs/WEB_DEPLOYMENT.md`.
6. `docs/FRIEND_SETUP.md` and `docs/WINDOWS_FIRST_SETUP.md`.
7. `docs/HELPER_UI_REFERENCE_LEDGER.md`.
8. Omar's global human writing and website design standards referenced by the
   repository instructions.

Use parallel specialist agents if available, with one final reviewer merging
the evidence. Cover at least these independent tracks:

- Windows installer, Authenticode, Azure Artifact Signing, NSIS install,
  uninstall, upgrades, Windows Defender and SmartScreen behavior, path quoting,
  non-admin users, long paths, spaces and Unicode usernames, 125 and 150
  percent display scaling, sleep and resume, shutdown, and process cleanup.
- Apple Silicon and Intel packaging, universal assumptions, minimum macOS 12,
  hardened runtime, entitlements, Developer ID, notarization, stapling,
  Gatekeeper, DMG mounting, upgrades, uninstall, quarantine attributes, and
  offline relaunch.
- Frozen Python and native dependency completeness on all three targets,
  including PyInstaller hidden imports, CTranslate2, ONNX Runtime, PyAV,
  cryptography, certifi, model files, CPU support, DLL and dylib search paths,
  temporary directories, working-directory assumptions, and subprocess paths.
- Bundled FFmpeg, FFprobe, Node, Chrome Headless Shell, HyperFrames, Remotion,
  GSAP, React, fonts, speech models, profiles, CA certificates, runtime
  manifest, checksums, license files, SBOM, and reproducible dependency locks.
- Actual video behavior for Short or Reel, long talking head, Commercial or Ad,
  Podcast or Interview, Course or Lesson, and Custom. Confirm their packaged
  profiles are `generic_short`, `generic_long`, `generic_commercial`,
  `generic_podcast`, `generic_course`, and `generic_custom`. Confirm
  long-to-clips is absent because multiple independently gated outputs are not
  implemented. Inspect speech cuts, source-time alignment, portrait and landscape,
  variable frame rate, missing audio, unusual codecs, large files, captions,
  punch-ins, B-roll, stock attribution, graphics, HyperFrames, Remotion,
  generated sound effects, loudness, aspect output, QA quarantine, and failure
  recovery. Never mark a mode accepted from configuration alone.
- DeepSeek key validation, model selection, planning receipts, revision chat,
  and deterministic proposal validation. Prove the five executable operations
  map exactly to edit style, aspect ratio, caption mode, full or baseline
  visuals, and one of the six generic profiles. Prove speech deletion, duration
  targeting, clip splitting, specific asset replacement, caption scaling,
  grading, and granular punch-in or b-roll requests are rejected before render.
  Verify the claimed job carries the server-stored approved proposal and a
  default rerender cannot be recorded as the requested change. Cover retries,
  timeouts, malformed model responses, prompt injection from transcript or
  filenames, cost controls, key redaction, and the rule that DeepSeek cannot
  bypass speech or QA gates.
- Cloudflare Worker, D1, R2, invitation and session security, CSRF and cookie
  behavior, rate limiting, user and project authorization, style preset
  ownership, queue claiming, replay and race conditions, output paths,
  multipart upload resume, file size and part validation, byte ranges, media
  deletion, installer privacy, CSP, CORS, cache headers, logs, backup,
  migration rollback, data retention, and two-account isolation.
- Trace the full media path: browser to private R2, R2 to the friend’s local
  Helper, local render and temporary files, then output and QA back to R2.
  Confirm the friend guide does not describe local rendering as local-only
  storage or claim an automatic retention period that is not implemented.
- Supply-chain review of exact Python hashes, npm locks, GitHub Action SHA pins,
  mutable downloads, FFmpeg provenance, model revisions, Chrome version,
  external URLs, update behavior, secret scopes, build permissions, artifact
  checksums, and release ordering. A moving dependency must fail closed.
- Licensing review for the exact distribution shape, including FFmpeg and
  x264 GPL corresponding source, PyInstaller exception, Remotion eligibility,
  HyperFrames, GSAP, Chromium, Node, Python dependencies, Work Sans,
  Montserrat, Whisper models, Pexels, Pixabay, ElevenLabs, and stock-media
  downstream rights. Separate legal uncertainty from a code defect. Use
  current official terms and primary documentation.
- Friend experience from a low-tech user's perspective. The friend should
  receive one signed `.exe` on Windows or one notarized `.dmg` on Mac. They
  must never install Python, Node, Git, FFmpeg, Homebrew, Chocolatey, a repo,
  a terminal tool, or a browser renderer. Walk every account creation and Skip
  branch. Confirm the instructions match the actual screens and error states.
- Product design and accessibility. Apply the installed Impeccable skill and
  Omar's reference-first standard. Render the real website and Helper at wide
  desktop, a normal Windows laptop, 390-pixel mobile, and Windows high-DPI
  sizes. Reject generic AI dashboard styling, decorative glass, blobs, bento
  filler, fake metrics, weak type, repeated cards, and unclear hierarchy.
  Check keyboard-only use, focus, labels, zoom, contrast, reduced motion,
  long copy, narrow windows, loading, empty, success, failure, disabled,
  offline, and permission-limited states. Preserve the coal, warm ivory, and
  aged-brass editorial production-console direction unless evidence proves a
  usability problem.
- Omar attribution. Confirm the website, Helper, package metadata, CLI or QA
  receipts, and appropriate product surfaces credit `Omar Marabha` and
  `@CEOmarabha`. Keep it tasteful and visible. Do not watermark or cover the
  user's finished video unless Omar separately asks for that.

Research current official documentation for every platform-sensitive claim.
Use primary sources for technical, security, signing, pricing, and licensing
facts. You may use GitHub issues, Reddit, and X to find real setup friction and
failure reports, but treat them as leads and reproduce or verify the issue
before changing code. Record every source URL and access date. Never install a
new dependency or tool merely because a post recommends it. Audit Hermes and
other agent harness ideas only as owner tooling. Friends must not receive an
arbitrary shell agent or a system that can download and execute repos on their
computer.

Required execution evidence:

1. Install each target-specific Python lock with `--require-hashes` in clean
   Python 3.12 environments or prove target wheel resolution without silently
   using the host platform. Run `pip check`.
2. Run every Python, web, desktop, and Worker test plus all npm audits.
3. Run syntax, configuration schema, workflow YAML, lock integrity, secret
   scan, and dependency-drift checks.
4. Build both PyInstaller programs from the clean lock. Run the frozen engine
   CLI, frozen Helper path smoke test, and frozen real HyperFrames plus Remotion
   smoke render.
5. Run the Worker against a clean isolated local D1 and R2 state with two
   users. Exercise both successful and hostile cross-user requests.
6. Render and inspect the website and Helper. Save screenshots and console
   output as evidence outside generated source folders.
7. If signed artifacts and suitable machines are available, install, run,
   revise a real video, quit, reopen, update, uninstall, verify signatures, and
   watch the output. If they are unavailable, record the gate as blocked. Never
   substitute a source test for artifact acceptance.
8. Inspect the exact artifact contents, hashes, signatures, notarization,
   licenses, runtime manifest, model files, DLLs or dylibs, and absence of
   secrets.

For every finding, provide severity, exact file and line, reproduction, user
impact, root cause, fix, and proof after the fix. Do not produce a speculative
wall of warnings. Label every gate PASS, FAIL, BLOCKED, or NOT RUN. PASS requires
direct current evidence. BLOCKED must name the missing certificate, secret,
hardware, account, artifact, or permission.

Create or update these local files:

- `docs/CLAUDE_RELEASE_AUDIT.md`, detailed findings, fixes, sources, and
  evidence.
- `docs/CLAUDE_RELEASE_GATE_MATRIX.md`, one row per release gate with status,
  command or artifact, result, and remaining owner action.

Use focused source edits for confirmed defects. Preserve the fail-closed QA and
speech protections. After fixes, run the full applicable suite again. Do not
say “release ready,” “friend ready,” “secure,” “private,” “signed,” or
“production ready” unless the exact deliverable friends will receive passed
the matching gate. Finish with a direct release decision and the shortest
ordered list of actions Omar must still take.
