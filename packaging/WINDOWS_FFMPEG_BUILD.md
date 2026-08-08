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

The outer script downloads seven immutable, commit-addressed HTTPS archives.
It verifies archive byte counts and SHA-256 values before compilation. The
source lock separately records the audited Git commits and trees.

The toolchain source set now includes the llvm-mingw wrapper source, LLVM
`llvmorg-22.1.8` at commit
`ca7933e47d3a3451d81e72ac174dcb5aa28b59d1`, and mingw-w64 at commit
`c28e9555bb8800c53449f42a465ad9a5676fce88`. The verifier reads the exact
llvm-mingw build scripts from their pinned archive and checks that those two
revisions are the revisions named by the wrapper.

Compilation runs with networking disabled in this digest-pinned image:

```text
docker.io/mstorsjo/llvm-mingw:20260616@sha256:a6371b0e370e2e9839a147a8a23195ed986772f99ebf43123e31dbe20bfe2146
```

The container builds NASM 3.01, static zlib, static x264, FFmpeg, and FFprobe.
Before NASM is compiled, `patch_nasm_coff_timestamp.py` verifies the exact
upstream `output/outcoff.c` bytes and changes only the Win32/Win64 COFF header
timestamp to zero. The normal `.file` auxiliary record and all other NASM
output semantics remain intact. This removes the sole 172-object difference
observed between the two hosted clean builds without using NASM's broader
`--reproducible` mode.
It binds the pinned FFmpeg make rules and configured `.exe` suffix before
running `make -j2 ffmpeg.exe ffprobe.exe`. Each final program link is repeated
with one LLD thread and evidence flags. The MinGW LLD driver translates
`--Map=...` to the COFF `/lldmap` form. It also receives `--verbose` and
`--reproduce=...` for the same link invocation.
The output directory contains:

```text
ffmpeg.exe
ffprobe.exe
licenses/FFmpeg-COPYING.GPLv2
licenses/LLVM-LICENSE.TXT
licenses/LLVM-compiler-rt-LICENSE.TXT
licenses/MinGW-w64-runtime-NOTICES.txt
licenses/x264-COPYING
licenses/zlib-LICENSE
link-evidence/ffmpeg-lld.map
link-evidence/ffmpeg-link.verbose.txt
link-evidence/ffmpeg-reproduce.tar
link-evidence/ffprobe-lld.map
link-evidence/ffprobe-link.verbose.txt
link-evidence/ffprobe-reproduce.tar
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
  --license-dir artifacts\licenses `
  --link-evidence-dir artifacts\link-evidence `
  --source-bundle artifacts\windows-ffmpeg-corresponding-source.tar `
  --source-manifest artifacts\windows-ffmpeg-corresponding-source.manifest.json `
  --repository-commit $env:GITHUB_SHA `
  --repo-root . `
  --output artifacts\windows-ffmpeg-build-receipt.json
```

The receipt binds the raw and Authenticode-normalized hash of both executables,
the exact standalone FFmpeg, LLVM, MinGW-w64, x264, and zlib license texts,
PE imports and hardening fields, the full parsed codec, encoder, decoder,
filter, format, protocol, and device inventories, the exact build
configuration, both tracked contract hashes, the source bundle, its manifest,
the repository commit and tree, and canonical receipts for every regular file
inside both LLD reproducer archives. Runtime smoke checks exercise lavfi,
float PCM output, wrapped-frame video to the null muxer, libx264 and AAC in
MP4, and FFprobe stream inspection.

Recompute the receipt before accepting an artifact:

```powershell
python packaging/verify_windows_ffmpeg.py verify-receipt `
  --receipt artifacts\windows-ffmpeg-build-receipt.json `
  --ffmpeg artifacts\ffmpeg.exe `
  --ffprobe artifacts\ffprobe.exe `
  --license-dir artifacts\licenses `
  --link-evidence-dir artifacts\link-evidence `
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
The workflow uploads one reproducible evidence candidate, source bundle,
manifest, and receipt after this comparison passes. It does not upload an
accepted or promotable runtime while link input classification is unverified.

## Link-Closure Hold

The current source lock and receipt state is
`input-classification-unverified`. This is intentional. The LLD map, verbose
log, and reproducer tar collect the actual link inputs for each executable,
but this patch does not classify every archive, object, startup file, or import
library against its source archive. The deterministic source bundle is complete
for the seven declared archives. That statement is limited to the declared
archive set and is not a claim that every code-bearing link input has been
mapped to source.

Helper staging, signing, release promotion, and distribution must call the
promotion gate and must stop while this status is present:

```bash
python packaging/verify_windows_ffmpeg.py assert-promotable \
  --receipt windows-ffmpeg-build-receipt.json
```

The command currently fails by design. Change the status only after a hosted
build has produced both reproducer archives and every actual input has an exact
classification and source mapping. A source archive being present in the
bundle is not enough by itself.

The verified classification contract must have one record for every
code-bearing input shown by the LLD map and reproducer. Each record needs the
program, reproducer member path, byte count, SHA-256, classification, source
ID, and source archive member when the input came from an archive. The allowed
classifications are `project-static`, `toolchain-runtime-static`,
`startup-object`, and `system-import`. A `system-import` record is allowed only
when the imported DLL also appears in that executable's PE import receipt.
Unknown records, duplicate records, unmatched map inputs, and code-bearing
records without a pinned source ID must keep the status unverified.

## Required Runtime Contract

The network protocol set is exactly `file` and `pipe` for input and output.
HTTP, HTTPS, TCP, UDP, RTMP, and every other protocol fail the gate. The
capability JSON records every required encoder, decoder, filter, demuxer, and
muxer. A missing item fails receipt creation.

The executable license expression is `GPL-2.0-or-later` because libx264 is
enabled. The source bundle uses the repository's deterministic source-bundle
format and includes all seven declared upstream archives plus the exact
AutoEditor repository tree and build scripts. The link-closure hold above stays
in force until the actual hosted LLD inputs have been classified.
