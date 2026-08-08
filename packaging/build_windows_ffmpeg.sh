#!/usr/bin/env bash
set -euo pipefail

umask 022

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
VERIFIER="$SCRIPT_DIR/verify_windows_ffmpeg.py"
LINKAGE_VERIFIER="$SCRIPT_DIR/windows_ffmpeg_link_receipt.py"
SOURCE_LOCK="$SCRIPT_DIR/windows-ffmpeg-sources.lock.json"
CAPABILITIES="$SCRIPT_DIR/windows-ffmpeg-capabilities.json"

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

require_empty_output() {
  local output=$1
  [[ ! -L "$output" ]] || fail "Output path must not be a symlink: $output"
  if [[ -e "$output" && ! -d "$output" ]]; then
    fail "Output path exists and is not a directory: $output"
  fi
  mkdir -p "$output"
  if find "$output" -mindepth 1 -print -quit | grep -q .; then
    fail "Output directory must be empty: $output"
  fi
}

extract_source() {
  local archive=$1
  local destination=$2
  case "$archive" in
    *.tar.gz) tar --no-same-owner --no-same-permissions -xzf "$archive" -C "$destination" ;;
    *.tar.xz) tar --no-same-owner --no-same-permissions -xJf "$archive" -C "$destination" ;;
    *) fail "Unsupported source archive: $archive" ;;
  esac
}

inside_container() {
  [[ "${AUTOEDITOR_WINDOWS_FFMPEG_CONTAINER:-}" == "1" ]] || \
    fail "The internal build may run only in the pinned container"
  [[ "$(pwd -P)" == "/build/autoeditor-media" ]] || \
    fail "The internal build directory must be /build/autoeditor-media"
  [[ -d /source-cache && -d /artifact && -d /repository ]] || \
    fail "The internal build mounts are incomplete"

  python3 /repository/packaging/verify_windows_ffmpeg.py contracts \
    --source-lock /repository/packaging/windows-ffmpeg-sources.lock.json \
    --capabilities /repository/packaging/windows-ffmpeg-capabilities.json
  python3 /repository/packaging/verify_windows_ffmpeg.py verify-source-cache \
    --source-lock /repository/packaging/windows-ffmpeg-sources.lock.json \
    --capabilities /repository/packaging/windows-ffmpeg-capabilities.json \
    --cache /source-cache

  export TARGET=x86_64-w64-mingw32
  export PREFIX=/build/autoeditor-media/prefix
  export SOURCE_DATE_EPOCH=1785458830
  export ZERO_AR_DATE=1
  export TZ=UTC
  export LC_ALL=C
  export COMMON_CFLAGS='-O2 -pipe -fstack-protector-strong -D_FORTIFY_SOURCE=2 -ffile-prefix-map=/build/autoeditor-media=/usr/src/autoeditor-media -fdebug-prefix-map=/build/autoeditor-media=/usr/src/autoeditor-media'
  export COMMON_LDFLAGS='-Wl,--nxcompat,--dynamicbase,--high-entropy-va,--no-insert-timestamp'
  export PATH="/opt/nasm-3.01/bin:$PATH"
  export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  export PKG_CONFIG_PATH=

  [[ -z "$(find . -mindepth 1 -print -quit)" ]] || \
    fail "/build/autoeditor-media must start empty"
  mkdir -p sources "$PREFIX" /opt/nasm-3.01/bin
  extract_source \
    /source-cache/ffmpeg-9b6c8969e05b4f0b29f0f85cd501be6b3e582e6b.tar.gz \
    sources
  extract_source \
    /source-cache/nasm-3.01.tar.xz \
    sources
  extract_source \
    /source-cache/x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee.tar.gz \
    sources
  extract_source \
    /source-cache/zlib-e3dc0a85b7032e98380dec011bc8f2c2ee0d8fca.tar.gz \
    sources
  tar --no-same-owner --no-same-permissions -xzf \
    /source-cache/llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1.tar.gz \
    -C sources \
    llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1/LICENSE.TXT \
    llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1/compiler-rt/LICENSE.TXT
  tar --no-same-owner --no-same-permissions -xzf \
    /source-cache/mingw-w64-c28e9555bb8800c53449f42a465ad9a5676fce88.tar.gz \
    -C sources \
    mingw-w64-c28e9555bb8800c53449f42a465ad9a5676fce88/COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt

  python3 /repository/packaging/patch_nasm_coff_timestamp.py apply \
    --source-root sources/nasm-3.01
  python3 /repository/packaging/patch_nasm_coff_timestamp.py verify \
    --source-root sources/nasm-3.01

  find sources -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +

  pushd sources/nasm-3.01 >/dev/null
  ./configure --prefix=/opt/nasm-3.01
  make -j2 nasm
  install -m 0755 nasm /opt/nasm-3.01/bin/nasm
  popd >/dev/null
  [[ "$(nasm -v)" == NASM\ version\ 3.01* ]] || \
    fail "The source-built NASM version drifted"

  pushd sources/zlib-e3dc0a85b7032e98380dec011bc8f2c2ee0d8fca >/dev/null
  CHOST="$TARGET" \
    CC="$TARGET-clang" \
    AR="$TARGET-ar" \
    RANLIB="$TARGET-ranlib" \
    CFLAGS="$COMMON_CFLAGS" \
    ./configure --static --prefix="$PREFIX"
  make -j2 libz.a
  make install
  popd >/dev/null
  [[ -f "$PREFIX/lib/libz.a" ]] || fail "The static zlib archive was not installed"

  pushd sources/x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee >/dev/null
  ./configure \
    --host="$TARGET" \
    --cross-prefix="$TARGET-" \
    --prefix="$PREFIX" \
    --enable-static \
    --disable-cli \
    --disable-opencl \
    --extra-cflags="$COMMON_CFLAGS" \
    --extra-ldflags="$COMMON_LDFLAGS"
  make -j2 lib-static
  make install-lib-static
  popd >/dev/null
  [[ -f "$PREFIX/lib/libx264.a" ]] || fail "The static x264 archive was not installed"

  mapfile -d '' -t CONFIGURE_ARGS < <(
    python3 /repository/packaging/verify_windows_ffmpeg.py emit-configure-args \
      --source-lock /repository/packaging/windows-ffmpeg-sources.lock.json \
      --capabilities /repository/packaging/windows-ffmpeg-capabilities.json \
      --nul
  )
  pushd sources/FFmpeg-9b6c8969e05b4f0b29f0f85cd501be6b3e582e6b >/dev/null
  ./configure --help > /build/autoeditor-media/ffmpeg-configure-help.txt
  python3 /repository/packaging/verify_windows_ffmpeg.py verify-configure-help \
    --source-lock /repository/packaging/windows-ffmpeg-sources.lock.json \
    --capabilities /repository/packaging/windows-ffmpeg-capabilities.json \
    --configure-help /build/autoeditor-media/ffmpeg-configure-help.txt
  if ! ./configure "${CONFIGURE_ARGS[@]}"; then
    if [[ -f ffbuild/config.log ]]; then
      printf '%s\n' "FFmpeg configure failed; final config.log section follows" >&2
      tail -n 300 ffbuild/config.log >&2
    fi
    fail "FFmpeg configure rejected the pinned source build"
  fi
  python3 /repository/packaging/verify_windows_ffmpeg.py verify-makefile \
    --source-lock /repository/packaging/windows-ffmpeg-sources.lock.json \
    --capabilities /repository/packaging/windows-ffmpeg-capabilities.json \
    --makefile Makefile \
    --tools-makefile fftools/Makefile \
    --config-mak ffbuild/config.mak
  make -j2 ffmpeg.exe ffprobe.exe
  rm -f -- ffmpeg.exe ffmpeg_g.exe ffprobe.exe ffprobe_g.exe
  mkdir -p /artifact/link-evidence /artifact/linkage
  local program
  for program in ffmpeg ffprobe; do
    local link_flags
    link_flags="-Wl,--Map=/artifact/link-evidence/${program}-lld.map,--verbose,--threads=1,--reproduce=/artifact/link-evidence/${program}-reproduce.tar"
    make -j1 "$program.exe" "LDFLAGS-$program=$link_flags" 2>&1 | \
      tee "/artifact/link-evidence/${program}-link.verbose.txt"
    [[ -f "$program.exe" && -f "${program}_g.exe" ]] || \
      fail "The captured $program link did not create both executables"
    install -m 0755 "${program}_g.exe" "/artifact/linkage/${program}_g.exe"
    python3 /repository/packaging/windows_ffmpeg_link_receipt.py create \
      --program "$program" \
      --reproduce "/artifact/link-evidence/${program}-reproduce.tar" \
      --lld-map "/artifact/link-evidence/${program}-lld.map" \
      --verbose-log "/artifact/link-evidence/${program}-link.verbose.txt" \
      --unstripped-executable "/artifact/linkage/${program}_g.exe" \
      --receipt "/artifact/linkage/$program-linkage-receipt.json"
    python3 /repository/packaging/windows_ffmpeg_link_receipt.py verify \
      --program "$program" \
      --reproduce "/artifact/link-evidence/${program}-reproduce.tar" \
      --lld-map "/artifact/link-evidence/${program}-lld.map" \
      --verbose-log "/artifact/link-evidence/${program}-link.verbose.txt" \
      --unstripped-executable "/artifact/linkage/${program}_g.exe" \
      --receipt "/artifact/linkage/$program-linkage-receipt.json"
  done
  python3 /repository/packaging/verify_windows_ffmpeg.py verify-link-evidence \
    --source-lock /repository/packaging/windows-ffmpeg-sources.lock.json \
    --capabilities /repository/packaging/windows-ffmpeg-capabilities.json \
    --link-evidence-dir /artifact/link-evidence
  "$TARGET-strip" --strip-all ffmpeg.exe ffprobe.exe
  install -m 0755 ffmpeg.exe /artifact/ffmpeg.exe
  install -m 0755 ffprobe.exe /artifact/ffprobe.exe
  popd >/dev/null

  mkdir -p /artifact/licenses
  install -m 0644 \
    sources/FFmpeg-9b6c8969e05b4f0b29f0f85cd501be6b3e582e6b/COPYING.GPLv2 \
    /artifact/licenses/FFmpeg-COPYING.GPLv2
  install -m 0644 \
    sources/llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1/LICENSE.TXT \
    /artifact/licenses/LLVM-LICENSE.TXT
  install -m 0644 \
    sources/llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1/compiler-rt/LICENSE.TXT \
    /artifact/licenses/LLVM-compiler-rt-LICENSE.TXT
  install -m 0644 \
    sources/mingw-w64-c28e9555bb8800c53449f42a465ad9a5676fce88/COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt \
    /artifact/licenses/MinGW-w64-runtime-NOTICES.txt
  install -m 0644 \
    sources/x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee/COPYING \
    /artifact/licenses/x264-COPYING
  install -m 0644 \
    sources/zlib-e3dc0a85b7032e98380dec011bc8f2c2ee0d8fca/LICENSE \
    /artifact/licenses/zlib-LICENSE
  touch -d "@$SOURCE_DATE_EPOCH" \
    /artifact/ffmpeg.exe /artifact/ffprobe.exe \
    /artifact/licenses/* /artifact/link-evidence/*
  find /artifact/linkage -type f -exec touch -d "@$SOURCE_DATE_EPOCH" {} +
  if find /artifact -maxdepth 1 -type f -iname '*.dll' -print -quit | grep -q .; then
    fail "The Windows FFmpeg artifact unexpectedly contains a DLL"
  fi
}

outer_build() {
  local output_dir=
  local repository_commit=
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --output-dir)
        [[ $# -ge 2 ]] || fail "--output-dir requires a value"
        output_dir=$2
        shift 2
        ;;
      --repository-commit)
        [[ $# -ge 2 ]] || fail "--repository-commit requires a value"
        repository_commit=$2
        shift 2
        ;;
      *) fail "Unknown argument: $1" ;;
    esac
  done
  [[ -n "$output_dir" && -n "$repository_commit" ]] || \
    fail "Usage: $0 --output-dir PATH --repository-commit 40_HEX_SHA"
  [[ "$repository_commit" =~ ^[0-9a-f]{40}$ ]] || \
    fail "--repository-commit must be an exact 40-character SHA-1"
  command -v curl >/dev/null || fail "curl is required"
  command -v docker >/dev/null || fail "Docker is required"
  command -v git >/dev/null || fail "Git is required"
  command -v python3 >/dev/null || fail "Python 3 is required"

  output_dir=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$output_dir")
  require_empty_output "$output_dir"
  python3 "$VERIFIER" contracts \
    --source-lock "$SOURCE_LOCK" \
    --capabilities "$CAPABILITIES"
  [[ "$(git -C "$REPO_ROOT" rev-parse "$repository_commit^{commit}")" == \
      "$repository_commit" ]] || fail "Repository commit did not resolve exactly"
  local tracked
  for tracked in \
    packaging/windows-ffmpeg-sources.lock.json \
    packaging/windows-ffmpeg-capabilities.json \
    packaging/build_windows_ffmpeg.sh \
    packaging/patch_nasm_coff_timestamp.py \
    packaging/verify_windows_ffmpeg.py \
    packaging/windows_ffmpeg_link_receipt.py \
    packaging/WINDOWS_FFMPEG_BUILD.md \
    packaging/source_bundle.py; do
    git -C "$REPO_ROOT" cat-file -e "$repository_commit:$tracked" || \
      fail "$tracked is absent from repository commit $repository_commit"
    git -C "$REPO_ROOT" diff --quiet "$repository_commit" -- "$tracked" || \
      fail "$tracked differs from repository commit $repository_commit"
  done

  local build_work
  local temporary_root
  temporary_root=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' \
    "${TMPDIR:-/tmp}")
  build_work=$(mktemp -d "$temporary_root/autoeditor-windows-ffmpeg.XXXXXX")
  case "$build_work" in
    "$temporary_root"/autoeditor-windows-ffmpeg.*) ;;
    *) fail "Temporary directory was not created under the expected prefix" ;;
  esac
  AUTOEDITOR_WINDOWS_FFMPEG_CLEANUP=$build_work
  AUTOEDITOR_WINDOWS_FFMPEG_CLEANUP_ROOT=$temporary_root
  cleanup_windows_ffmpeg_build() {
    case "$AUTOEDITOR_WINDOWS_FFMPEG_CLEANUP" in
      "$AUTOEDITOR_WINDOWS_FFMPEG_CLEANUP_ROOT"/autoeditor-windows-ffmpeg.*)
        rm -rf -- "$AUTOEDITOR_WINDOWS_FFMPEG_CLEANUP"
        ;;
      *)
        printf '%s\n' "Refusing unexpected cleanup target" >&2
        ;;
    esac
  }
  trap cleanup_windows_ffmpeg_build EXIT
  local source_cache="$build_work/source-cache"
  local container_work="$build_work/container"
  local nasm_prefix="$build_work/nasm-prefix"
  mkdir -p "$source_cache" "$container_work" "$nasm_prefix"

  while IFS=$'\t' read -r source_id method archive url expected_sha \
      expected_bytes object_id commit_id tree_id archive_prefix; do
    local destination="$source_cache/$archive"
    if [[ "$method" == "https-archive" ]]; then
      curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
        --silent --show-error "$url" -o "$destination"
    else
      fail "Unsupported fetch method for $source_id: $method"
    fi
    local actual_record
    actual_record=$(python3 - "$destination" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
raw = path.read_bytes()
print(f"{hashlib.sha256(raw).hexdigest()} {len(raw)}")
PY
)
    [[ "$actual_record" == "$expected_sha $expected_bytes" ]] || \
      fail "$source_id archive digest or byte count drifted"
  done < <(
    python3 "$VERIFIER" emit-fetch-plan \
      --source-lock "$SOURCE_LOCK" \
      --capabilities "$CAPABILITIES"
  )
  python3 "$VERIFIER" verify-source-cache \
    --source-lock "$SOURCE_LOCK" \
    --capabilities "$CAPABILITIES" \
    --cache "$source_cache"

  local bundle_lock="$build_work/source-bundle.lock.json"
  python3 "$VERIFIER" materialize-bundle-lock \
    --source-lock "$SOURCE_LOCK" \
    --capabilities "$CAPABILITIES" \
    --output "$bundle_lock"
  python3 "$SCRIPT_DIR/source_bundle.py" build \
    --lock "$bundle_lock" \
    --source-cache "$source_cache" \
    --repository "$REPO_ROOT" \
    --repository-commit "$repository_commit" \
    --output-tar "$output_dir/windows-ffmpeg-corresponding-source.tar" \
    --output-manifest "$output_dir/windows-ffmpeg-corresponding-source.manifest.json"
  python3 "$SCRIPT_DIR/source_bundle.py" verify \
    --archive "$output_dir/windows-ffmpeg-corresponding-source.tar" \
    --manifest "$output_dir/windows-ffmpeg-corresponding-source.manifest.json"

  local container_image
  container_image=$(python3 "$VERIFIER" container-image \
    --source-lock "$SOURCE_LOCK" \
    --capabilities "$CAPABILITIES")
  docker pull "$container_image"
  docker image inspect "$container_image" >/dev/null
  docker run --rm --network=none \
    --user "$(id -u):$(id -g)" \
    --env AUTOEDITOR_WINDOWS_FFMPEG_CONTAINER=1 \
    --volume "$REPO_ROOT:/repository:ro" \
    --volume "$source_cache:/source-cache:ro" \
    --volume "$container_work:/build/autoeditor-media" \
    --volume "$nasm_prefix:/opt/nasm-3.01" \
    --volume "$output_dir:/artifact" \
    --workdir /build/autoeditor-media \
    --entrypoint /bin/bash \
    "$container_image" \
    /repository/packaging/build_windows_ffmpeg.sh --inside-container

  python3 "$VERIFIER" verify-pe \
    --source-lock "$SOURCE_LOCK" \
    --capabilities "$CAPABILITIES" \
    --ffmpeg "$output_dir/ffmpeg.exe" \
    --ffprobe "$output_dir/ffprobe.exe"
  local program
  for program in ffmpeg ffprobe; do
    python3 "$LINKAGE_VERIFIER" verify \
      --program "$program" \
      --reproduce "$output_dir/link-evidence/${program}-reproduce.tar" \
      --lld-map "$output_dir/link-evidence/${program}-lld.map" \
      --verbose-log "$output_dir/link-evidence/${program}-link.verbose.txt" \
      --unstripped-executable "$output_dir/linkage/${program}_g.exe" \
      --receipt "$output_dir/linkage/$program-linkage-receipt.json"
  done
  printf '%s\n' "Windows FFmpeg source build completed: $output_dir"
}

if [[ "${1:-}" == "--inside-container" ]]; then
  [[ $# -eq 1 ]] || fail "--inside-container takes no other arguments"
  inside_container
else
  outer_build "$@"
fi
