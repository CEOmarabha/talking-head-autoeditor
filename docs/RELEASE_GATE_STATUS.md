# AutoEditor Helper release gate status

Status date: August 8, 2026. Source branch: `web-app`. The accepted runtime and
unsigned artifact source commit is
`3ad08be851adefbec15d4ceac307eca42758cfd4`. Later local commits harden the
release gates and record evidence without changing those accepted runtime
bytes.

This file separates completed local engineering checks from the checks that
need signing accounts, hosted infrastructure, or physical computers. A source
test pass is not approval to send an installer to friends.

## Passed locally

- The unrestricted Python safety suite passed 103 tests, including 24
  subtests. The web suite passed 31 tests.
- All five Desktop Helper test files passed. The Worker Miniflare suite passed
  all nine real D1/R2 route simulations.
- Desktop, Helper runtime, and Worker npm audits reported zero vulnerabilities
  at the configured audit level.
- Windows x64, Mac Apple Silicon, and Mac Intel dependency resolution succeeded
  against exact Python 3.12 locks. Every locked requirement has one target
  archive hash.
- `pip check` reported no broken requirements in the clean locked environment.
- Apple Silicon PyInstaller builds completed for both the editing engine and
  the website render daemon. Both outputs are native arm64 Mach-O executables.
- The frozen engine opened its real command line and reported the Omar Marabha
  builder credit.
- The frozen render daemon passed its installed-path smoke check for the
  engine, FFmpeg, FFprobe, both speech models, profiles, fonts, CA bundle,
  Node, HyperFrames, Remotion, and the rendering browser.
- The frozen render daemon completed real HyperFrames and Remotion renders.
- The website passed local two-user tests for job and media isolation, output
  path ownership, multipart resume, sign-in rate limiting, authenticated
  installer downloads, byte ranges, and security headers.
- The website and Helper were rendered and inspected at a 1440-pixel desktop
  width, a 390-pixel mobile width, and the native Electron Helper window.
  The Impeccable detector returned no anti-pattern findings after the final
  correction pass.
- Electron Builder accepted both the base Helper configuration and the Azure
  Artifact Signing configuration schema.
- The tagged build workflow now stops after signed candidates and their exact
  receipts are uploaded. It has no live-release credentials or `current.json`
  write. Live exposure is a separate owner-dispatched promotion bound to the
  accepted tag, commit, build run, run attempt, and all three receipts.
- A fresh unsigned Mac arm64 DMG was built from this commit. A fresh read-only
  mount passed `hdiutil` verification, recursive Finder-metadata rejection,
  strict code-seal verification, the exact 13-component manifest, the exact
  six generic profiles, the mounted engine self-test, a normal packaged UI
  screenshot, and the real packaged HyperFrames and Remotion smoke.
- The mounted DMG completed a commercial 9:16 edit in 83 seconds. QA, caption
  safe area, exact 1080x1920 delivery, full decode, and four source-sync probes
  at 0 ms all passed.
- All six generic profiles then executed from the same mounted DMG. Every
  profile matched its exact ID and SHA-256, passed QA and caption safety,
  delivered exact 9:16 or 16:9 geometry, survived full decode, and passed four
  source-sync probes. This is packaging and mechanical execution coverage. The
  shared synthetic fixture is not creative-quality evidence for real long,
  podcast, course, or Custom source material.
- Wrangler 4.120.0 applied both production migrations to a fresh local D1,
  built the deploy bundle with all expected bindings, and passed a live local
  two-user HTTP check for sessions, ownership, deletion, malformed-key
  non-echo, preset rejection, security headers, and installer authentication.

## Blocked before a friend release

- GitHub now has protected `main`, an active `helper-v*` tag ruleset, SHA-pinned
  GitHub-owned Actions only, and three reviewer-protected Helper environments
  restricted to the exact signing tags or `main`. Candidate-upload credentials
  are attached only to the two signing environments, and separate promotion
  credentials are attached only to the live-release environment. Repository
  Actions secrets remain empty. The required Windows and Apple signing
  credentials have not been created or attached.
- The separate private Cloudflare candidate and live-release buckets now exist
  with isolated API tokens. Production still runs the older Worker and has not
  received the current D1 migrations or required `RELEASES` binding.
- No Windows Authenticode-signed installer has been built and installed on a
  clean Windows 11 computer.
- No Apple Developer ID signed, notarized, and stapled Apple Silicon or Intel
  DMG has been built from this revision.
- No complete signed-candidate run has been downloaded and physically accepted,
  so the separate live-promotion workflow has not been authorized or run.
- The Intel Mac package has not been installed and exercised on real Intel Mac
  hardware.
- The private production Worker, D1 schema, R2 paths, invites, and two-user
  isolation flow have not been deployed and accepted from this revision.
- The six generic profiles, five exact DeepSeek operations, server-bound
  revision proposal, and six-item browser picker have not been accepted
  together from signed Windows and Mac artifacts.
- GPL-compliant corresponding-source delivery remains unresolved for the exact
  top-level FFmpeg, x264, x265, and linked build, plus
  the native media copies inside PyAV, Electron or Chromium, and the Remotion
  compositor. Notices and build receipts alone do not close this gate.
- Real full edits for Short, long talking head, Commercial, Podcast, Course,
  and Custom have not all been watched from beginning to end on the exact
  signed release artifacts. Long-to-clips is not a supported release type.
- Real account checks for DeepSeek, Pexels, Pixabay, ElevenLabs, and every
  Remotion license choice have not all been exercised on those signed
  artifacts.

## Release decision

Local source, unrestricted regression, Wrangler-local, and unsigned Apple
Silicon artifact gates now have current pass evidence. Friend distribution
remains blocked until every item above is closed against the exact signed
installers and production services.
Follow `OWNER_SIGNING_SETUP.md`, build signed candidates, then use the physical
acceptance and separate promotion sequence in `LAUNCH_CHECKLIST.md`. Do not
publish an unsigned artifact or promote a signed run that was not physically
accepted.
