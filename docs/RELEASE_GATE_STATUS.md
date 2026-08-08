# AutoEditor Helper release gate status

Status date: August 7, 2026. Source branch: `web-app`.

This file separates completed local engineering checks from the checks that
need signing accounts, hosted infrastructure, or physical computers. A source
test pass is not approval to send an installer to friends.

## Passed locally

- The current clean-export Python safety, generic-profile, project-type, and
  revision checks have local pass evidence in Python 3.12. The localhost
  wall-clock timeout check still needs an unrestricted runner, so the exact
  complete suite must pass again in release CI.
- Desktop Helper tests passed.
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

These local results do not prove the generic profiles were bundled into a new
installer or that the Worker, browser, daemon, and signed artifacts carry the
same revision contract. Rebuild and retest the combined revision before using
these results for release acceptance.

## Blocked before a friend release

- No GitHub repository signing or Cloudflare publishing secrets are currently
  configured.
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
- GPL corresponding-source delivery or a valid written-offer process for the
  exact bundled FFmpeg, x264, and linked GPL build remains unresolved. Notices
  alone do not close this gate.
- Real full edits for Short, long talking head, Commercial, Podcast, Course,
  and Custom have not all been watched from beginning to end on the exact
  signed release artifacts. Long-to-clips is not a supported release type.
- Real account checks for DeepSeek, Pexels, Pixabay, ElevenLabs, and every
  Remotion license choice have not all been exercised on those signed
  artifacts.

## Release decision

Local source and Apple Silicon freeze checks have substantial pass evidence,
with the current unrestricted full-suite and combined-artifact rerun still due.
Friend distribution remains blocked until every item above is closed against
the exact signed installers.
Follow `OWNER_SIGNING_SETUP.md`, build signed candidates, then use the physical
acceptance and separate promotion sequence in `LAUNCH_CHECKLIST.md`. Do not
publish an unsigned artifact or promote a signed run that was not physically
accepted.
