# AutoEditor Helper third-party notices

This file is an inventory, not legal advice. The exact payload hashes and
sizes are recorded beside this file in `runtime-manifest.json`.

## Bundled runtimes and libraries

- Electron 43.3.0, MIT License.
- Node.js 22, MIT License and bundled third-party notices.
- Python 3.12, Python Software Foundation License.
- PyInstaller, GPL-2.0-or-later with its bootloader exception.
- FFmpeg, a GPL build because AutoEditor requires libx264. Source and build
  information must ship with each release. See https://ffmpeg.org/legal.html.
  Before any third-party handoff, the publisher must confirm a GPL-compliant
  corresponding-source delivery method for the exact FFmpeg, x264, and linked
  GPL components with counsel or the binary provider. For installer downloads,
  this means equivalent source access alongside the installer.
- x264, GPL-2.0-or-later.
- Native media code also ships inside the Electron or Chromium runtime and
  Remotion compositor. The release source review must account for each
  embedded FFmpeg-derived copy, its exact build configuration, and every
  linked copyleft codec. Supplying source only for the top-level `ffmpeg`
  executable is not treated as a complete corresponding-source gate.
- PyAV remains a build-environment dependency of faster-whisper, but is
  excluded from the frozen engine. AutoEditor decodes speech audio through
  the same manifest-bound FFmpeg executable used by the editing pipeline, so
  no PyAV FFmpeg libraries are distributed.
- The low-speech cutter is AutoEditor project code built on the bundled
  FFmpeg. The `auto-editor` 29.3.1 PyPI launcher and its separately downloaded
  WyattBlue native executable are not included. This avoids a first-run
  network download and removes that external runtime from the distributed
  payload.
- faster-whisper 1.2.1, MIT License.
- CTranslate2 4.8.1, MIT License.
- Hugging Face faster-whisper small and medium model files, MIT License.
- HyperFrames 0.7.99, Apache License 2.0.
- Remotion 4.0.507, Remotion License. Individuals and organizations of up to
  three people qualify for the free license. Other collaborations and
  organizations require the applicable paid license. See
  https://www.remotion.dev/docs/license/pricing.
- React and React DOM 19.0.0, MIT License.
- GSAP 3.15.0, GSAP Standard no-charge license. See
  https://gsap.com/community/standard-license/.
- Chrome Headless Shell 152.0.7928.2, Chromium project licenses and notices.
- certifi CA bundle, Mozilla Public License 2.0.
- Pillow, HPND License.
- NumPy, BSD-3-Clause License.
- cryptography, Apache-2.0 or BSD-3-Clause dual license.
- Montserrat and Work Sans fonts, SIL Open Font License 1.1.

Complete Python and npm dependency trees are frozen in the release build and
recorded by their lock files and runtime manifest. Original license files from
the packaged dependencies must remain in the installer payload.

## Network services and downloaded media

- DeepSeek is the required editing and revision model. Every friend uses their
  own account and API key. DeepSeek terms and pricing apply.
- Pexels is an account-backed stock source. It can be skipped during setup, in
  which case AutoEditor does not request or download Pexels media. Pexels API
  guidelines require a prominent provider link and impose rate limits. Pexels
  content restrictions, model and property releases, and prohibited uses still
  apply to the person publishing a finished video.
- Pixabay is an account-backed stock source. It can be skipped during setup, in
  which case AutoEditor does not request or download Pixabay media. Pixabay
  requires API responses to be cached for 24 hours and prohibits systematic
  mass downloads. Content restrictions and third-party rights still apply.
- ElevenLabs is an account-backed generated sound-effects source. It can be
  skipped during setup, in which case AutoEditor does not send sound-effect
  prompts to ElevenLabs. When connected, ElevenLabs credits, plan limits, and
  terms apply. Friends should use a restricted API key with a small credit
  limit and Sound Effects access only.

Every resolved stock event records its provider, source page, contributor when
available, license URL, downloaded asset hash, and measured duration in the
edit receipt. Stock media is composited into a new edit and is never exposed as
a standalone stock download.
