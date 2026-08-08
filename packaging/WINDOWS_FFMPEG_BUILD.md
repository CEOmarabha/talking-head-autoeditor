# Windows FFmpeg Source Build

This build replaces the downloaded BtbN runtime with `ffmpeg.exe` and
`ffprobe.exe` compiled from pinned source. It produces a matching
corresponding-source bundle for the repository commit used by the Helper
release.

The tracked contracts are:

- `packaging/windows-ffmpeg-sources.lock.json`
- `packaging/windows-ffmpeg-capabilities.json`
- `packaging/build_windows_ffmpeg.sh`
- `packaging/verify_windows_ffmpeg.py`

The verifier contains the accepted SHA-256 for both JSON contracts. Any pin,
field, ordering, or line-ending change fails until the contract and verifier
are reviewed together.

## Build Boundary

Run the build from a clean checkout at an exact 40-character commit:

```bash
packaging/build_windows_ffmpeg.sh \
  --output-dir "$RUNNER_TEMP/windows-ffmpeg" \
  --repository-commit "$GITHUB_SHA"
```

The outer script downloads four immutable HTTPS archives and creates the x264
archive from the exact official Git object. It verifies archive byte counts,
SHA-256 values, Git commits, and Git trees before compilation.

Compilation runs with networking disabled in this digest-pinned image:

```text
docker.io/mstorsjo/llvm-mingw:20260616@sha256:a6371b0e370e2e9839a147a8a23195ed986772f99ebf43123e31dbe20bfe2146
```

The container builds NASM 3.01, static zlib, static x264, FFmpeg, and FFprobe.
It binds the pinned FFmpeg make rules and configured `.exe` suffix before
running `make -j2 ffmpeg.exe ffprobe.exe`.
The output directory contains:

```text
ffmpeg.exe
ffprobe.exe
windows-ffmpeg-corresponding-source.tar
windows-ffmpeg-corresponding-source.manifest.json
```

The build refuses source files that differ from the named repository commit.
It also refuses extra source-cache files, archive drift, a mutable container
reference, DLL payloads, nonzero PE timestamps, missing PE hardening flags, or
imports from x264, zlib, pthread, GCC, C++, Clang, or unwind runtime DLLs.

## Windows Capability Receipt

Move each clean build output to a Windows x64 runner. Create a receipt by
executing the produced programs on Windows:

```powershell
python packaging/verify_windows_ffmpeg.py create-receipt `
  --ffmpeg artifacts\ffmpeg.exe `
  --ffprobe artifacts\ffprobe.exe `
  --source-bundle artifacts\windows-ffmpeg-corresponding-source.tar `
  --source-manifest artifacts\windows-ffmpeg-corresponding-source.manifest.json `
  --repository-commit $env:GITHUB_SHA `
  --repo-root . `
  --output artifacts\windows-ffmpeg-build-receipt.json
```

The receipt binds the raw and Authenticode-normalized hash of both executables,
PE imports and hardening fields, the full parsed codec, encoder, decoder,
filter, format, protocol, and device inventories, the exact build
configuration, both tracked contract hashes, the source bundle, its manifest,
and the repository commit and tree. Runtime smoke checks exercise lavfi,
float PCM output, wrapped-frame video to the null muxer, libx264 and AAC in
MP4, and FFprobe stream inspection.

Recompute the receipt before accepting an artifact:

```powershell
python packaging/verify_windows_ffmpeg.py verify-receipt `
  --receipt artifacts\windows-ffmpeg-build-receipt.json `
  --ffmpeg artifacts\ffmpeg.exe `
  --ffprobe artifacts\ffprobe.exe `
  --source-bundle artifacts\windows-ffmpeg-corresponding-source.tar `
  --source-manifest artifacts\windows-ffmpeg-corresponding-source.manifest.json `
  --repository-commit $env:GITHUB_SHA `
  --repo-root .
```

## Dual Clean-Build Gate

Run the source build twice in separate fresh jobs. Run the Windows receipt step
for each output. The accepted pair must compare byte for byte:

```bash
python packaging/verify_windows_ffmpeg.py compare-receipts \
  --first first/windows-ffmpeg-build-receipt.json \
  --second second/windows-ffmpeg-build-receipt.json
```

This comparison covers both unsigned executables, the corresponding-source
bundle, its manifest, the canonical receipt, and all recorded inventories.
The workflow uploads one accepted runtime, source bundle, manifest, and receipt
only after this comparison passes. Signing and Helper staging start after that
gate.

## Required Runtime Contract

The network protocol set is exactly `file` and `pipe` for input and output.
HTTP, HTTPS, TCP, UDP, RTMP, and every other protocol fail the gate. The
capability JSON records every required encoder, decoder, filter, demuxer, and
muxer. A missing item fails receipt creation.

The executable license expression is `GPL-2.0-or-later` because libx264 is
enabled. The source bundle uses the repository's deterministic source-bundle
format and includes every pinned upstream archive plus the exact AutoEditor
repository tree and build scripts.
