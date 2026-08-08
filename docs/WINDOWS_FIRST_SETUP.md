# Windows-first release acceptance

Friends receive one signed `AutoEditor-Helper-Windows.exe`. They do not install
Python, Node, FFmpeg, Whisper models, HyperFrames, Remotion, a browser runtime,
fonts, repositories, package managers, or command-line tools.

Windows is tested first because it is the primary friend platform. The Mac
Helper must ship the same six generic edit profiles, five DeepSeek revision
controls, account checks, local render path, cloud transfer path, and QA gates.
Mac parity is a separate physical acceptance requirement, not an inference
from a passing Windows build.

The tagged `helper-v*` workflow is required to fail unless Azure Artifact
Signing or the fallback Windows PFX credentials are completely configured. It
builds on Windows itself because PyInstaller is not a cross-compiler, installs
the finished `.exe` silently, runs the frozen daemon, performs real HyperFrames
and Remotion renders, checks the installed application signature, and
uninstalls it. It then uploads a seven-day signed candidate for physical
acceptance and stops. The tag cannot change live friend downloads. The
owner-only setup is in `OWNER_SIGNING_SETUP.md`.

## Required final physical Windows test

CI is necessary but does not replace this test on the installer Omar will
actually send. Download `signed-candidate-helper-windows-x64` from the same
successful tagged Actions run as both Mac candidates. Extract it, open its
candidate receipt, then run `Get-FileHash` in PowerShell and confirm the
installer SHA-256 exactly matches the receipt before testing. Record the tag,
full commit SHA, run ID, and run attempt.

1. Use a normal 64-bit Windows 11 account with no Python, Node, FFmpeg, Git,
   Visual Studio, or development tools installed.
2. Download the `.exe` from the same website link a friend receives.
3. Confirm Microsoft Defender and SmartScreen show the expected verified
   publisher. Any unknown-publisher warning fails the signed release.
4. Install from Downloads and confirm desktop and Start menu shortcuts.
5. Open the Helper, paste a real Setup code, and connect real DeepSeek, Pexels,
   Pixabay, and ElevenLabs accounts. Also exercise the Skip path for each
   account-backed resource.
6. Confirm every built-in runtime check passes and the real HyperFrames and
   Remotion samples render.
7. In Chrome, create one real edit for each supported type: Short, long talking
   head, Commercial, Podcast, Course, and Custom. Confirm their packaged
   profiles are `generic_short`, `generic_long`, `generic_commercial`,
   `generic_podcast`, `generic_course`, and `generic_custom`.
8. Disconnect the internet during one large upload, reconnect, and verify the
   resumable upload finishes.
9. Across those projects, apply every executable DeepSeek control at least
   once: edit pacing, aspect ratio, caption mode, full or baseline visuals, and
   generic profile selection. Confirm a request to remove speech, retarget
   duration, or split the upload is rejected before rendering.
10. Download each MP4 and play it in Windows Media Player and a browser.
11. Delete one project and confirm its authenticated media URLs no longer
    return files.
12. Uninstall AutoEditor Helper from Windows Settings and confirm the program
    files are removed. User projects stay until deleted from the website.

Status is not Windows-ready until this physical-machine pass is recorded
against the exact signed installer. Passing source tests or a macOS build does
not satisfy it. Completing this checklist authorizes only the Windows candidate.
Do not run the separate live-promotion workflow until both Mac candidates from
the same run pass too.

## Required Mac parity test

Repeat the same account, six-type, five-revision-control, upload-resume,
download, deletion, relaunch, and uninstall checks on the exact notarized Mac
DMG. Run Apple Silicon on real Apple Silicon hardware. Keep Intel marked
untested until the Intel DMG is exercised on a real Intel Mac. A Windows pass
does not close either Mac gate.
