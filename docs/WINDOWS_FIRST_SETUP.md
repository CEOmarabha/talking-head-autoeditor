# Windows-first release acceptance

Friends receive one signed `AutoEditor-Helper-Windows.exe`. They do not install
Python, Node, FFmpeg, Whisper models, HyperFrames, Remotion, a browser runtime,
fonts, repositories, package managers, or command-line tools.

The tagged `helper-v*` workflow is required to fail unless Azure Artifact
Signing or the fallback Windows PFX credentials are completely configured. It
builds on Windows itself because PyInstaller is not a cross-compiler, installs
the finished `.exe` silently, runs the frozen daemon, performs real HyperFrames
and Remotion renders, checks the installed application signature, and
uninstalls it. The owner-only setup is in `OWNER_SIGNING_SETUP.md`.

## Required final physical Windows test

CI is necessary but does not replace this test on the installer Omar will
actually send:

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
7. In Chrome, create one Short, one long talking-head video, and one commercial
   edit from real footage. Run at least one DeepSeek revision on each.
8. Disconnect the internet during one large upload, reconnect, and verify the
   resumable upload finishes.
9. Download each MP4 and play it in Windows Media Player and a browser.
10. Delete one project and confirm its authenticated media URLs no longer
    return files.
11. Uninstall AutoEditor Helper from Windows Settings and confirm the program
    files are removed. User projects stay until deleted from the website.

Status is not Windows-ready until this physical-machine pass is recorded
against the exact signed installer. Passing source tests or a macOS build does
not satisfy it.
