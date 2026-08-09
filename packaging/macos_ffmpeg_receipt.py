#!/usr/bin/env python3
"""Create and verify the exact final macOS FFmpeg bundle receipt.

The receipt is generated against the packed ``.app`` tree, after Electron
Builder has copied and signed the staged FFmpeg bundle.  It binds every Mach-O
byte to the resolved Homebrew Cellar source while normalizing only the exact
install-name rewrites, their header padding, and the terminal code-signature
blob.  The receipt also records each complete final file hash and the audited
bottle inventory for the target architecture.

The module intentionally owns only ``Contents/Resources/bin/{ffmpeg,ffprobe}``
and the audited files directly below ``Contents/Resources/lib``.  Directory
descriptors and no-follow opens are used throughout the final-tree scan so a
symlink, hard link, path replacement, case drift, or concurrent mutation fails
closed.  This is a technical provenance contract, not a legal determination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterator


SCHEMA = "autoeditor-macos-ffmpeg-bundle/v1"
COMPONENT = "main-ffmpeg"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_INVENTORY_BYTES = 1024 * 1024
MAX_MACHO_COMMAND_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
OTOOL_PATH = "/usr/bin/otool"
MACHO_WHOLE_DIGEST_DOMAIN = b"autoeditor-macos-ffmpeg-whole-macho/v1\0"

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MACHO_UUID_RE = re.compile(r"[0-9a-f]{32}\Z")
FORMULA_RE = re.compile(r"[a-z0-9][a-z0-9@+._-]{0,127}\Z")
VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+._-]{0,127}\Z")
BOTTLE_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+-]{0,127}\Z")
DYLIB_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+@._-]*\.dylib\Z")

MH_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 0x2
MH_DYLIB = 0x6
LC_SEGMENT_64 = 0x19
LC_UUID = 0x1B
LC_CODE_SIGNATURE = 0x1D
LC_LOAD_DYLIB = 0xC
LC_ID_DYLIB = 0xD
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_LAZY_LOAD_DYLIB = 0x20
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_TWOLEVEL_HINTS = 0x16
LC_SEGMENT_SPLIT_INFO = 0x1E
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_FUNCTION_STARTS = 0x26
LC_DATA_IN_CODE = 0x29
LC_DYLIB_CODE_SIGN_DRS = 0x2B
LC_ENCRYPTION_INFO_64 = 0x2C
LC_LINKER_OPTIMIZATION_HINT = 0x2E
LC_NOTE = 0x31
LC_DYLD_EXPORTS_TRIE = 0x80000033
LC_DYLD_CHAINED_FIXUPS = 0x80000034
LINKEDIT_DATA_COMMANDS = frozenset({
    LC_SEGMENT_SPLIT_INFO,
    LC_FUNCTION_STARTS,
    LC_DATA_IN_CODE,
    LC_DYLIB_CODE_SIGN_DRS,
    LC_LINKER_OPTIMIZATION_HINT,
    LC_DYLD_EXPORTS_TRIE,
    LC_DYLD_CHAINED_FIXUPS,
})
DYNAMIC_LIBRARY_LOAD_COMMANDS = frozenset({
    LC_LOAD_DYLIB,
    LC_LOAD_WEAK_DYLIB,
    LC_REEXPORT_DYLIB,
    LC_LAZY_LOAD_DYLIB,
    LC_LOAD_UPWARD_DYLIB,
})
VM_PROT_EXECUTE = 0x4
SECTION_64_BYTES = 80
SECTION_TYPE_MASK = 0xFF
ZERO_FILL_SECTION_TYPES = frozenset({0x1, 0xC, 0x12})
CPU_TYPES = {
    "arm64": 0x0100000C,
    "x64": 0x01000007,
}
MACHO_PAGE_BYTES = {
    # Exact native Homebrew pours of the pinned bottles use these
    # architecture-specific __LINKEDIT allocation granularities.
    CPU_TYPES["arm64"]: 16 * 1024,
    CPU_TYPES["x64"]: 4 * 1024,
}
# Exact __LINKEDIT allocations in the authenticated arm64_sequoia bottle for
# the pinned FFmpeg 8.1.2_1 formula. Homebrew's pour-time ad-hoc signer can
# shrink the terminal signature without shrinking these original allocations.
ARM64_FFMPEG_BOTTLE_LINKEDIT_VM_BYTES = MappingProxyType({
    "ffmpeg": 81_920,
    "ffprobe": 49_152,
    "libavcodec.62.28.102.dylib": 196_608,
    "libavdevice.62.3.102.dylib": 49_152,
    "libavfilter.11.14.102.dylib": 114_688,
    "libavformat.62.12.102.dylib": 114_688,
    "libavutil.60.26.102.dylib": 81_920,
    "libswresample.6.3.102.dylib": 32_768,
    "libswscale.9.5.102.dylib": 32_768,
})
# Exact unsigned bottle and bundled Intel __LINKEDIT allocations derived from
# the authenticated x64 Sonoma FFmpeg 8.1.2_1 bottle plus the production
# install-name rewrite and ad-hoc signing sequence. The bottle SHA-256 is
# fcc13fae2031e5adaa193bc1accb03e8127b9503d41ac29c07e3758e7a88ba88.
X64_FFMPEG_BOTTLE_LINKEDIT_VM_BYTES = MappingProxyType({
    "ffmpeg": frozenset({49_152, 81_920}),
    "ffprobe": frozenset({32_768, 49_152}),
    "libavcodec.62.28.102.dylib": frozenset({98_304, 212_992}),
    "libavdevice.62.3.102.dylib": frozenset({16_384, 49_152}),
    "libavfilter.11.14.102.dylib": frozenset({65_536, 114_688}),
    "libavformat.62.12.102.dylib": frozenset({81_920, 114_688}),
    "libavutil.60.26.102.dylib": frozenset({49_152, 81_920}),
    "libswresample.6.3.102.dylib": frozenset({16_384, 32_768}),
    "libswscale.9.5.102.dylib": frozenset({16_384, 49_152}),
})
# Exact allocation in the authenticated libvmaf 3.2.0 arm64_sequoia bottle
# whose archive SHA-256 is pinned as dbd548d2ba16092e9c88b81cd91d7cbd1ecec84b9bb31e9c196fe3f6658ee6b3.
ARM64_LIBVMAF_BOTTLE_LINKEDIT_VM_BYTES = MappingProxyType({
    "libvmaf.3.dylib": 81_920,
})
PACKAGING_DYLIB_TIMESTAMP = 0
PLATFORMS = {
    "arm64": "mac-arm64",
    "x64": "mac-x64",
}
LINEAGE_IDS = {
    "arm64": "homebrew:ffmpeg@8.1.2_1:mac-arm64",
    "x64": "homebrew:ffmpeg@8.1.2_1:mac-x64",
}
PINNED_FORMULA_INVENTORY_SHA256 = {
    "arm64": "7c0472395f88b33d515a4cdbadafc5be2c00773d895213c2e9eb29b732bfa71d",
    "x64": "68421d8e408a64dbc0f7e4db60f4eb9cf78f91c6ec4f2bacdcce91223ceac0fc",
}

EXECUTABLE_SOURCE_FORMULAE = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
}
SVT_AV1_FINAL_PATH = (
    "Contents/Resources/lib/libSvtAv1Enc.4.2.0.dylib"
)
LIBRARY_SOURCE_FORMULAE = {
    PurePosixPath(SVT_AV1_FINAL_PATH).name: "svt-av1",
    "libavcodec.62.28.102.dylib": "ffmpeg",
    "libavdevice.62.3.102.dylib": "ffmpeg",
    "libavfilter.11.14.102.dylib": "ffmpeg",
    "libavformat.62.12.102.dylib": "ffmpeg",
    "libavutil.60.26.102.dylib": "ffmpeg",
    "libcrypto.3.dylib": "openssl@3",
    "libdav1d.7.dylib": "dav1d",
    "libmp3lame.0.dylib": "lame",
    "libmpg123.0.dylib": "mpg123",
    "libopus.0.dylib": "opus",
    "libssl.3.dylib": "openssl@3",
    "libswresample.6.3.102.dylib": "ffmpeg",
    "libswscale.9.5.102.dylib": "ffmpeg",
    "libvmaf.3.dylib": "libvmaf",
    "libvpx.12.dylib": "libvpx",
    "libx264.165.dylib": "x264",
    "libx265.216.dylib": "x265",
}
EXPECTED_FINAL_PATHS = {
    **{
        f"Contents/Resources/bin/{name}": ("executable", formula)
        for name, formula in EXECUTABLE_SOURCE_FORMULAE.items()
    },
    **{
        f"Contents/Resources/lib/{name}": ("dylib", formula)
        for name, formula in LIBRARY_SOURCE_FORMULAE.items()
    },
}
POSIX_HANDLE_APIS_AVAILABLE = (
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.listdir in os.supports_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


class MacFFmpegReceiptError(ValueError):
    """The producer inputs, final app tree, or receipt failed closed."""


@dataclass(frozen=True)
class FormulaRecord:
    formula: str
    version: str
    bottle_tag: str
    bottle_rebuild: int
    bottle_sha256: str


@dataclass(frozen=True)
class BottleMemberRecord:
    bottle_sha256: str
    member_path: str
    byte_count: int
    sha256: str
    macho_whole_sha256: str


@dataclass(frozen=True)
class MachoIdentity:
    uuid: str
    content_sha256: str
    header: tuple[int, int, int, int, int, int]
    commands: tuple[bytes, ...]
    byte_count: int
    first_file_offset: int


@dataclass(frozen=True)
class FileObservation:
    path: str
    byte_count: int
    sha256: str
    architecture: str
    kind: str
    macho_uuid: str
    macho_content_sha256: str
    macho_load_commands_sha256: str
    macho_whole_sha256: str
    dependencies: tuple[str, ...]
    system_dependencies: tuple[str, ...]


@dataclass(frozen=True)
class SourceObservation:
    final_path: str
    formula: str
    formula_version: str
    cellar_path: str
    byte_count: int
    sha256: str
    macho_uuid: str
    macho_content_sha256: str
    macho_load_commands_sha256: str
    macho_whole_sha256: str
    dependencies: tuple[str, ...]
    system_dependencies: tuple[str, ...]


@dataclass(frozen=True)
class FileClaim:
    """One exact producer claim consumed by the native allowlist generator."""

    path: str
    bytes: int
    sha256: str
    architecture: str
    kind: str
    source_formula: str
    source_formula_version: str
    source_cellar_path: str
    source_bytes: int
    source_sha256: str
    macho_uuid: str
    macho_content_sha256: str
    macho_load_commands_sha256: str
    macho_whole_sha256: str
    source_macho_uuid: str
    source_macho_content_sha256: str
    source_macho_load_commands_sha256: str
    source_macho_whole_sha256: str
    dependencies: tuple[str, ...]
    system_dependencies: tuple[str, ...]
    formula_inventory_sha256: str


# These member observations were taken from the exact bottle archives whose
# SHA256 values are pinned in macos-ffmpeg-formulae-{arch}.txt. Homebrew may
# relocate and re-sign the poured Cellar file, so its raw member identity stays
# recorded while the poured file is bound to the audited normalized whole
# Mach-O identity.
PINNED_BOTTLE_MEMBERS: Mapping[str, Mapping[str, BottleMemberRecord]] = (
    MappingProxyType({
        "arm64": MappingProxyType({
            SVT_AV1_FINAL_PATH: BottleMemberRecord(
                bottle_sha256=(
                    "2e6f7cbf3ff42f59ca251f3c84d4ad5a3ecfd518340237a6f70a54a428de1676"
                ),
                member_path="svt-av1/4.2.0/lib/libSvtAv1Enc.4.2.0.dylib",
                byte_count=3_090_544,
                sha256=(
                    "72407e386bf6582771dd73ff51c6318201b7ad27a755d82efc64ea35db161d64"
                ),
                macho_whole_sha256=(
                    "87f9d30d9c820b29a9657631114d01064d279c16bda3556d48d7d8547895aebe"
                ),
            ),
        }),
        "x64": MappingProxyType({
            SVT_AV1_FINAL_PATH: BottleMemberRecord(
                bottle_sha256=(
                    "413ca9c3ca785dcebb9baae17b4b86a70f1c86e5881fa8af87f55ac7e5d8a5eb"
                ),
                member_path="svt-av1/4.2.0/lib/libSvtAv1Enc.4.2.0.dylib",
                byte_count=5_450_640,
                sha256=(
                    "b10c2dfc281d442691befb528090747f92a25ac12189b6689782cc259abdd4ad"
                ),
                macho_whole_sha256=(
                    "ec2ff23e2b0f841949b9ddcda1935e552fa77a3ae8be76f6b40d6da182f71da5"
                ),
            ),
        }),
    })
)


DependencyReader = Callable[[Path], Sequence[Path]]


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _expected_arch(value: str) -> str:
    if value not in CPU_TYPES:
        raise MacFFmpegReceiptError(
            f"unsupported Mac FFmpeg architecture: {value}"
        )
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise MacFFmpegReceiptError(f"invalid SHA256 for {label}")
    return value


def _macho_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not MACHO_UUID_RE.fullmatch(value):
        raise MacFFmpegReceiptError(f"invalid Mach-O UUID for {label}")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise MacFFmpegReceiptError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise MacFFmpegReceiptError(f"{label} must be a nonnegative integer")
    return value


def _exact_keys(
    value: Any,
    expected: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise MacFFmpegReceiptError(
            f"{label} keys must be exactly: {', '.join(sorted(expected))}"
        )
    return value


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MacFFmpegReceiptError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise MacFFmpegReceiptError(f"{label} has an invalid byte count")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MacFFmpegReceiptError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise MacFFmpegReceiptError(f"{label} root must be an object")
    return value


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_object_identity(value: os.stat_result) -> tuple[int, ...]:
    """Identity fields that remain stable when directory entries change."""
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
    )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


@contextmanager
def _held_directory_path(path: Path, label: str) -> Iterator[int]:
    if not POSIX_HANDLE_APIS_AVAILABLE:
        raise MacFFmpegReceiptError(
            "secure POSIX directory-handle APIs are unavailable"
        )
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise MacFFmpegReceiptError(
                f"{label} must be a real directory, not a symlink"
            )
        descriptor = os.open(path, _directory_flags())
        opened = os.fstat(descriptor)
        if _directory_identity(before) != _directory_identity(opened):
            raise MacFFmpegReceiptError(f"{label} changed while opening")
        yield descriptor
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _directory_identity(opened) != _directory_identity(after_handle)
            or _directory_identity(opened) != _directory_identity(after_path)
        ):
            raise MacFFmpegReceiptError(f"{label} changed while scanning")
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(f"cannot open {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _held_writable_directory_path(path: Path, label: str) -> Iterator[int]:
    """Hold one real directory while allowing entry creation within it."""
    if not POSIX_HANDLE_APIS_AVAILABLE:
        raise MacFFmpegReceiptError(
            "secure POSIX directory-handle APIs are unavailable"
        )
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise MacFFmpegReceiptError(
                f"{label} must be a real directory, not a symlink"
            )
        descriptor = os.open(path, _directory_flags())
        opened = os.fstat(descriptor)
        if (
            _directory_object_identity(before)
            != _directory_object_identity(opened)
        ):
            raise MacFFmpegReceiptError(f"{label} changed while opening")
        yield descriptor
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _directory_object_identity(opened)
            != _directory_object_identity(after_handle)
            or _directory_object_identity(opened)
            != _directory_object_identity(after_path)
        ):
            raise MacFFmpegReceiptError(f"{label} was replaced while writing")
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(f"cannot open {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _held_child_directory(
    parent_fd: int,
    name: str,
    label: str,
) -> Iterator[int]:
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise MacFFmpegReceiptError(
                f"{label} must be a real directory, not a symlink"
            )
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
        opened = os.fstat(descriptor)
        if _directory_identity(before) != _directory_identity(opened):
            raise MacFFmpegReceiptError(f"{label} changed while opening")
        yield descriptor
        after_handle = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _directory_identity(opened) != _directory_identity(after_handle)
            or _directory_identity(opened) != _directory_identity(after_path)
        ):
            raise MacFFmpegReceiptError(f"{label} changed while scanning")
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(f"cannot open {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_descriptor(
    descriptor: int,
    max_bytes: int | None = None,
) -> tuple[bytes, int, str]:
    digest = hashlib.sha256()
    prefix = bytearray()
    total = 0
    while True:
        chunk = os.read(descriptor, READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise MacFFmpegReceiptError("file exceeds its maximum byte count")
        digest.update(chunk)
        if len(prefix) < MAX_MACHO_COMMAND_BYTES:
            wanted = MAX_MACHO_COMMAND_BYTES - len(prefix)
            prefix.extend(chunk[:wanted])
    return bytes(prefix), total, digest.hexdigest()


def _read_regular_path(
    path: Path,
    label: str,
    *,
    max_bytes: int | None = None,
    reject_hardlinks: bool = True,
) -> tuple[bytes, int, str]:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise MacFFmpegReceiptError(
                f"{label} must be a regular file, not a symlink"
            )
        if reject_hardlinks and before.st_nlink != 1:
            raise MacFFmpegReceiptError(
                f"{label} must have exactly one filesystem link"
            )
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise MacFFmpegReceiptError(f"{label} changed while opening")
        prefix, byte_count, digest = _read_descriptor(descriptor, max_bytes)
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
            or byte_count != opened.st_size
        ):
            raise MacFFmpegReceiptError(f"{label} changed while reading")
        return prefix, byte_count, digest
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _observe_macho_path(
    path: Path,
    label: str,
    expected_arch: str,
    kind: str,
) -> tuple[int, str, MachoIdentity]:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise MacFFmpegReceiptError(
                f"{label} must be a regular file, not a symlink"
            )
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise MacFFmpegReceiptError(f"{label} changed while opening")
        prefix, byte_count, digest = _read_descriptor(descriptor)
        macho = _validate_macho(
            prefix,
            byte_count,
            expected_arch,
            kind,
            label,
            descriptor,
        )
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
            or byte_count != opened.st_size
        ):
            raise MacFFmpegReceiptError(f"{label} changed while reading")
        return byte_count, digest, macho
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _observe_file_at(
    directory_fd: int,
    name: str,
    relative: str,
    expected_arch: str,
    kind: str,
) -> FileObservation:
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise MacFFmpegReceiptError(
                f"final Mac FFmpeg path must be a regular file: {relative}"
            )
        if before.st_nlink != 1:
            raise MacFFmpegReceiptError(
                f"final Mac FFmpeg path must have one link: {relative}"
            )
        if kind == "executable" and not before.st_mode & 0o111:
            raise MacFFmpegReceiptError(
                f"final Mac FFmpeg executable lacks execute permission: {relative}"
            )
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise MacFFmpegReceiptError(
                f"final Mac FFmpeg path changed while opening: {relative}"
            )
        prefix, byte_count, digest = _read_descriptor(descriptor)
        after_handle = os.fstat(descriptor)
        after_path = os.stat(
            name, dir_fd=directory_fd, follow_symlinks=False
        )
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
            or byte_count != opened.st_size
        ):
            raise MacFFmpegReceiptError(
                f"final Mac FFmpeg path changed while reading: {relative}"
            )
        macho = _validate_macho(
            prefix, byte_count, expected_arch, kind, relative, descriptor
        )
        load_digest, dependencies, system_dependencies = (
            _macho_load_command_profile(
                macho,
                binary=Path(relative),
                final_path=relative,
                kind=kind,
            )
        )
        whole_digest = _macho_whole_sha256(
            macho,
            descriptor,
            binary=Path(relative),
            final_path=relative,
            kind=kind,
        )
        return FileObservation(
            relative,
            byte_count,
            digest,
            expected_arch,
            kind,
            macho.uuid,
            macho.content_sha256,
            load_digest,
            whole_digest,
            dependencies,
            system_dependencies,
        )
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(
            f"cannot read final Mac FFmpeg path {relative}: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_regular_at(
    directory_fd: int,
    name: str,
    label: str,
    *,
    max_bytes: int,
) -> bytes:
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise MacFFmpegReceiptError(
                f"{label} must be a regular file, not a symlink"
            )
        if before.st_nlink != 1:
            raise MacFFmpegReceiptError(
                f"{label} must have exactly one filesystem link"
            )
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise MacFFmpegReceiptError(f"{label} changed while opening")
        raw, byte_count, _ = _read_descriptor(descriptor, max_bytes)
        after_handle = os.fstat(descriptor)
        after_path = os.stat(
            name, dir_fd=directory_fd, follow_symlinks=False
        )
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
            or byte_count != opened.st_size
            or byte_count != len(raw)
        ):
            raise MacFFmpegReceiptError(f"{label} changed while reading")
        return raw
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _macho_name(raw: bytes, label: str) -> str:
    if len(raw) != 16:
        raise MacFFmpegReceiptError(f"invalid Mach-O name field: {label}")
    terminator = raw.find(b"\0")
    if terminator >= 0:
        if any(raw[terminator:]):
            raise MacFFmpegReceiptError(
                f"noncanonical Mach-O name padding: {label}"
            )
        raw = raw[:terminator]
    if not raw or any(value < 0x21 or value > 0x7E for value in raw):
        raise MacFFmpegReceiptError(f"invalid Mach-O name: {label}")
    return raw.decode("ascii")


def _hash_descriptor_range(
    descriptor: int,
    offset: int,
    byte_count: int,
    label: str,
) -> str:
    if not hasattr(os, "pread"):
        raise MacFFmpegReceiptError(
            "secure positioned Mach-O reads are unavailable"
        )
    digest = hashlib.sha256()
    consumed = 0
    while consumed < byte_count:
        wanted = min(READ_CHUNK_BYTES, byte_count - consumed)
        chunk = os.pread(descriptor, wanted, offset + consumed)
        if not chunk:
            raise MacFFmpegReceiptError(
                f"truncated Mach-O section content: {label}"
            )
        digest.update(chunk)
        consumed += len(chunk)
    return digest.hexdigest()


def _validate_macho(
    prefix: bytes,
    byte_count: int,
    expected_arch: str,
    kind: str,
    label: str,
    descriptor: int,
) -> MachoIdentity:
    if len(prefix) < 32 or byte_count < 32:
        raise MacFFmpegReceiptError(f"truncated Mach-O file: {label}")
    magic, cpu_type, subtype, file_type, commands, command_bytes, flags, reserved = (
        struct.unpack_from("<8I", prefix, 0)
    )
    if magic != MH_MAGIC_64:
        raise MacFFmpegReceiptError(
            f"{label} is not a thin little-endian 64-bit Mach-O"
        )
    if cpu_type != CPU_TYPES[expected_arch]:
        raise MacFFmpegReceiptError(
            f"{label} has the wrong Mach-O architecture"
        )
    expected_type = MH_EXECUTE if kind == "executable" else MH_DYLIB
    if file_type != expected_type:
        raise MacFFmpegReceiptError(
            f"{label} has the wrong Mach-O file type for {kind}"
        )
    if commands <= 0 or commands > 65_535:
        raise MacFFmpegReceiptError(f"{label} has invalid Mach-O commands")
    if (
        command_bytes < commands * 8
        or command_bytes > MAX_MACHO_COMMAND_BYTES - 32
        or command_bytes > byte_count - 32
        or len(prefix) < 32 + command_bytes
    ):
        raise MacFFmpegReceiptError(
            f"{label} has invalid Mach-O command bounds"
        )
    cursor = 32
    end = 32 + command_bytes
    executable_segment = False
    macho_uuid: str | None = None
    section_records: list[dict[str, Any]] = []
    section_names: set[tuple[str, str]] = set()
    file_backed_offsets: list[int] = []
    command_records: list[bytes] = []
    for _ in range(commands):
        if cursor + 8 > end:
            raise MacFFmpegReceiptError(
                f"{label} has a truncated Mach-O load command"
            )
        command, command_size = struct.unpack_from("<II", prefix, cursor)
        if command_size < 8 or command_size % 4 or cursor + command_size > end:
            raise MacFFmpegReceiptError(
                f"{label} has an invalid Mach-O load command"
            )
        command_records.append(prefix[cursor:cursor + command_size])
        if command == LC_SEGMENT_64:
            if command_size < 72:
                raise MacFFmpegReceiptError(
                    f"{label} has a truncated Mach-O segment"
                )
            (
                segment_name_raw,
                segment_vm_address,
                segment_vm_size,
                segment_file_offset,
                segment_file_size,
                maximum_protection,
                initial_protection,
                section_count,
                segment_flags,
            ) = struct.unpack_from("<16sQQQQIIII", prefix, cursor + 8)
            expected_command_size = 72 + section_count * SECTION_64_BYTES
            if command_size != expected_command_size:
                raise MacFFmpegReceiptError(
                    f"{label} has invalid Mach-O section command bounds"
                )
            if (
                segment_file_offset > byte_count
                or segment_file_size > byte_count - segment_file_offset
            ):
                raise MacFFmpegReceiptError(
                    f"{label} has an out-of-bounds Mach-O segment"
                )
            segment_name = _macho_name(
                segment_name_raw, f"{label} segment"
            )
            executable_segment = bool(
                executable_segment or initial_protection & VM_PROT_EXECUTE
            )
            section_cursor = cursor + 72
            for section_index in range(section_count):
                (
                    section_name_raw,
                    section_segment_raw,
                    section_address,
                    section_size,
                    section_offset,
                    _section_alignment,
                    _relocation_offset,
                    _relocation_count,
                    section_flags,
                    _reserved_1,
                    _reserved_2,
                    _reserved_3,
                ) = struct.unpack_from(
                    "<16s16sQQIIIIIIII", prefix, section_cursor
                )
                section_name = _macho_name(
                    section_name_raw,
                    f"{label} section {section_index}",
                )
                section_segment = _macho_name(
                    section_segment_raw,
                    f"{label} section {section_index} segment",
                )
                if section_segment != segment_name:
                    raise MacFFmpegReceiptError(
                        f"{label} has a section in the wrong Mach-O segment"
                    )
                identity = (segment_name, section_name)
                if identity in section_names:
                    raise MacFFmpegReceiptError(
                        f"{label} has duplicate Mach-O section names"
                    )
                section_names.add(identity)
                if (
                    section_address < segment_vm_address
                    or section_size
                    > segment_vm_size - (section_address - segment_vm_address)
                ):
                    raise MacFFmpegReceiptError(
                        f"{label} has an out-of-bounds Mach-O section address"
                    )
                section_type = section_flags & SECTION_TYPE_MASK
                if section_type in ZERO_FILL_SECTION_TYPES:
                    content_sha256 = hashlib.sha256(b"").hexdigest()
                else:
                    if (
                        section_offset < segment_file_offset
                        or section_offset > byte_count
                        or section_size > byte_count - section_offset
                        or section_size
                        > segment_file_size
                        - (section_offset - segment_file_offset)
                    ):
                        raise MacFFmpegReceiptError(
                            f"{label} has out-of-bounds Mach-O section content"
                        )
                    content_sha256 = _hash_descriptor_range(
                        descriptor,
                        section_offset,
                        section_size,
                        f"{label} {segment_name},{section_name}",
                    )
                    if section_size:
                        file_backed_offsets.append(section_offset)
                section_records.append({
                    "content_sha256": content_sha256,
                    "segment": segment_name,
                    "segment_flags": segment_flags,
                    "segment_initial_protection": initial_protection,
                    "segment_maximum_protection": maximum_protection,
                    "section": section_name,
                    "section_flags": section_flags,
                    "size": section_size,
                })
                section_cursor += SECTION_64_BYTES
        elif command == LC_UUID:
            if command_size != 24 or macho_uuid is not None:
                raise MacFFmpegReceiptError(
                    f"{label} has an invalid Mach-O UUID command"
                )
            macho_uuid = prefix[cursor + 8:cursor + 24].hex()
        cursor += command_size
    if (
        cursor != end
        or not executable_segment
        or macho_uuid is None
        or not section_records
        or not file_backed_offsets
    ):
        raise MacFFmpegReceiptError(
            f"{label} has an invalid executable Mach-O identity"
        )
    first_file_offset = min(file_backed_offsets)
    if first_file_offset < end:
        raise MacFFmpegReceiptError(
            f"{label} has file-backed Mach-O content inside its header"
        )
    section_records.sort(key=lambda item: (item["segment"], item["section"]))
    return MachoIdentity(
        uuid=macho_uuid,
        content_sha256=hashlib.sha256(
            canonical_json_bytes(section_records)
        ).hexdigest(),
        header=(magic, cpu_type, subtype, file_type, flags, reserved),
        commands=tuple(command_records),
        byte_count=byte_count,
        first_file_offset=first_file_offset,
    )


def _load_command_string(command: bytes, label: str) -> tuple[str, int, int, int]:
    if len(command) < 24:
        raise MacFFmpegReceiptError(f"truncated Mach-O dylib command: {label}")
    name_offset, timestamp, current_version, compatibility_version = (
        struct.unpack_from("<4I", command, 8)
    )
    if name_offset != 24 or name_offset >= len(command):
        raise MacFFmpegReceiptError(f"invalid Mach-O dylib name offset: {label}")
    terminator = command.find(b"\0", name_offset)
    if terminator < 0 or any(command[terminator + 1:]):
        raise MacFFmpegReceiptError(f"noncanonical Mach-O dylib name: {label}")
    try:
        value = command[name_offset:terminator].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MacFFmpegReceiptError(
            f"Mach-O dylib name is not UTF-8: {label}"
        ) from exc
    if (
        not value
        or unicodedata.normalize("NFC", value) != value
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            for character in value
        )
    ):
        raise MacFFmpegReceiptError(f"ambiguous Mach-O dylib name: {label}")
    return value, timestamp, current_version, compatibility_version


def _round_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _canonical_signed_linkedit_command(
    command_bytes: bytes,
    macho: MachoIdentity,
    signature: tuple[int, int, int],
    binary: Path,
) -> bytes:
    """Remove only exact, signature-backed __LINKEDIT geometry."""
    command, command_size = struct.unpack_from("<II", command_bytes)
    if command != LC_SEGMENT_64 or command_size < 72:
        raise MacFFmpegReceiptError(
            f"invalid signed __LINKEDIT command: {binary}"
        )
    segment_name = _macho_name(
        command_bytes[8:24], f"{binary} signed segment"
    )
    if segment_name != "__LINKEDIT":
        raise MacFFmpegReceiptError(
            f"signed segment is not __LINKEDIT: {binary}"
        )
    _vm_address, vm_size, file_offset, file_size = struct.unpack_from(
        "<4Q", command_bytes, 24
    )
    signature_offset, signature_size, _signature_index = signature
    page_bytes = MACHO_PAGE_BYTES.get(macho.header[1])
    if page_bytes is None:
        raise MacFFmpegReceiptError(
            f"unsupported signed Mach-O page size: {binary}"
        )
    rounded_file_size = _round_up(file_size, page_bytes)
    allowed_vm_sizes = {
        rounded_file_size,
        rounded_file_size + page_bytes,
    }
    authenticated_vm_sizes = frozenset()
    if macho.header[1] == CPU_TYPES["arm64"]:
        authenticated_vm_size = (
            ARM64_FFMPEG_BOTTLE_LINKEDIT_VM_BYTES.get(binary.name)
        )
        if authenticated_vm_size is None:
            authenticated_vm_size = (
                ARM64_LIBVMAF_BOTTLE_LINKEDIT_VM_BYTES.get(binary.name)
            )
        if authenticated_vm_size is not None:
            authenticated_vm_sizes = frozenset({authenticated_vm_size})
    elif macho.header[1] == CPU_TYPES["x64"]:
        authenticated_vm_sizes = (
            X64_FFMPEG_BOTTLE_LINKEDIT_VM_BYTES.get(
                binary.name, frozenset()
            )
        )
    allowed_vm_sizes.update(authenticated_vm_sizes)
    if (
        file_size <= 0
        or file_offset > signature_offset
        or signature_offset + signature_size != file_offset + file_size
        or vm_size < rounded_file_size
        or vm_size not in allowed_vm_sizes
    ):
        raise MacFFmpegReceiptError(
            f"noncanonical signed __LINKEDIT extent: {binary}"
        )
    unsigned_file_size = signature_offset - file_offset
    normalized = bytearray(command_bytes)
    struct.pack_into(
        "<Q", normalized, 32, _round_up(unsigned_file_size, page_bytes)
    )
    struct.pack_into("<Q", normalized, 48, unsigned_file_size)
    return bytes(normalized)


def _canonical_install_id(value: str, label: str) -> None:
    if value.startswith("/"):
        _canonical_absolute_otool_path(value, Path(label))
        return
    prefixes = ("@loader_path/", "@executable_path/", "@rpath/")
    prefix = next((item for item in prefixes if value.startswith(item)), None)
    if prefix is None:
        raise MacFFmpegReceiptError(
            f"unsupported Mach-O install ID in {label}: {value}"
        )
    remainder = value.removeprefix(prefix)
    parts = PurePosixPath(remainder).parts
    if (
        not remainder
        or remainder.startswith("/")
        or "//" in remainder
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(remainder).as_posix() != remainder
    ):
        raise MacFFmpegReceiptError(
            f"noncanonical Mach-O install ID in {label}: {value}"
        )


def _macho_load_command_profile(
    macho: MachoIdentity,
    *,
    binary: Path,
    final_path: str,
    kind: str,
    source_dependencies: Sequence[Path] | None = None,
    executable_directories: Sequence[Path] = (),
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Normalize only the bundle's exact dylib rewrites and code signature."""
    source_mode = source_dependencies is not None
    resolved_source_dependencies: tuple[Path, ...] = ()
    if source_dependencies is not None:
        try:
            resolved_source_dependencies = tuple(
                Path(item).resolve(strict=True) for item in source_dependencies
            )
        except OSError as exc:
            raise MacFFmpegReceiptError(
                f"unresolved source dependency from {binary}"
            ) from exc
        if len(resolved_source_dependencies) != len(
            set(resolved_source_dependencies)
        ):
            raise MacFFmpegReceiptError(
                f"duplicate source dependency from {binary}"
            )

    signature = _macho_signature_extent(macho, binary)

    records: list[dict[str, Any]] = [{
        "header": list(macho.header),
    }]
    dependencies: list[str] = []
    system_dependencies: list[str] = []
    parsed_source_dependencies: list[Path] = []
    install_ids = 0
    normalized_signature_segments = 0
    for index, command_bytes in enumerate(macho.commands):
        command, command_size = struct.unpack_from("<II", command_bytes)
        label = f"{binary} load command {index}"
        if command == LC_CODE_SIGNATURE:
            continue
        if command == LC_SEGMENT_64:
            normalized = bytearray(command_bytes)
            segment_name = _macho_name(
                command_bytes[8:24], f"{label} segment"
            )
            if segment_name == "__LINKEDIT" and signature is not None:
                normalized = bytearray(_canonical_signed_linkedit_command(
                    command_bytes,
                    macho,
                    signature,
                    binary,
                ))
                normalized_signature_segments += 1
            records.append({
                "command": command,
                "raw_sha256": hashlib.sha256(normalized).hexdigest(),
            })
            continue
        if command == LC_ID_DYLIB or command in DYNAMIC_LIBRARY_LOAD_COMMANDS:
            value, timestamp, current_version, compatibility_version = (
                _load_command_string(command_bytes, label)
            )
            record: dict[str, Any] = {
                "command": command,
                "compatibility_version": compatibility_version,
                "current_version": current_version,
            }
            if command == LC_ID_DYLIB:
                install_ids += 1
                _canonical_install_id(value, label)
                expected_id = (
                    f"@loader_path/{PurePosixPath(final_path).name}"
                )
                if not source_mode and (kind != "dylib" or value != expected_id):
                    raise MacFFmpegReceiptError(
                        f"final dylib install ID drifted for {final_path}: {value}"
                    )
                record["install_id"] = final_path
                record["timestamp"] = PACKAGING_DYLIB_TIMESTAMP
                records.append(record)
                continue

            if value.startswith("/"):
                dependency, is_system = _canonical_absolute_otool_path(
                    value, binary
                )
                if is_system:
                    system_dependencies.append(value)
                    record["system_dependency"] = value
                    record["timestamp"] = timestamp
                    records.append(record)
                    continue
                if not source_mode:
                    raise MacFFmpegReceiptError(
                        f"final non-system dependency is absolute in {final_path}: {value}"
                    )
                try:
                    resolved = dependency.resolve(strict=True)
                except OSError as exc:
                    raise MacFFmpegReceiptError(
                        f"unresolved non-system dependency in {binary}: {value}"
                    ) from exc
            elif source_mode:
                resolved = _resolve_at_dependency(
                    value, binary, executable_directories
                )
            else:
                prefix = (
                    "@executable_path/../lib/"
                    if kind == "executable"
                    else "@loader_path/"
                )
                if not value.startswith(prefix):
                    raise MacFFmpegReceiptError(
                        f"final dependency uses alternate loader syntax in {final_path}: {value}"
                    )
                dependency_name = value.removeprefix(prefix)
                target = f"Contents/Resources/lib/{dependency_name}"
                if (
                    not DYLIB_NAME_RE.fullmatch(dependency_name)
                    or EXPECTED_FINAL_PATHS.get(target, (None,))[0] != "dylib"
                ):
                    raise MacFFmpegReceiptError(
                        f"unresolved final dependency in {final_path}: {value}"
                    )
                dependencies.append(target)
                record["dependency"] = target
                record["timestamp"] = PACKAGING_DYLIB_TIMESTAMP
                records.append(record)
                continue

            parsed_source_dependencies.append(resolved)
            dependency_name = resolved.name
            target = f"Contents/Resources/lib/{dependency_name}"
            if EXPECTED_FINAL_PATHS.get(target, (None,))[0] != "dylib":
                raise MacFFmpegReceiptError(
                    f"source dependency is outside the audited graph: {resolved}"
                )
            dependencies.append(target)
            record["dependency"] = target
            record["timestamp"] = PACKAGING_DYLIB_TIMESTAMP
            records.append(record)
            continue

        records.append({
            "command": command,
            "raw_sha256": hashlib.sha256(command_bytes).hexdigest(),
        })

    expected_install_ids = 0 if kind == "executable" else 1
    if install_ids != expected_install_ids:
        raise MacFFmpegReceiptError(
            f"Mach-O install ID cardinality drifted for {final_path}"
        )
    if signature is not None and normalized_signature_segments != 1:
        raise MacFFmpegReceiptError(
            f"Mach-O code signature lacks one __LINKEDIT segment: {final_path}"
        )
    if source_mode and tuple(parsed_source_dependencies) != (
        resolved_source_dependencies
    ):
        raise MacFFmpegReceiptError(
            f"source dependency load commands differ from otool graph: {final_path}"
        )
    if len(dependencies) != len(set(dependencies)):
        raise MacFFmpegReceiptError(
            f"duplicate non-system dependency in {final_path}"
        )
    if len(system_dependencies) != len(set(system_dependencies)):
        raise MacFFmpegReceiptError(
            f"duplicate system dependency in {final_path}"
        )
    return (
        hashlib.sha256(canonical_json_bytes(records)).hexdigest(),
        tuple(dependencies),
        tuple(system_dependencies),
    )


def _macho_referenced_file_ranges(
    macho: MachoIdentity,
    binary: Path,
) -> tuple[tuple[int, int, str], ...]:
    ranges: list[tuple[int, int, str]] = []

    def add(offset: int, byte_count: int, label: str) -> None:
        if offset == 0 and byte_count == 0:
            return
        if (
            byte_count < 0
            or offset < 0
            or offset > macho.byte_count
            or byte_count > macho.byte_count - offset
        ):
            raise MacFFmpegReceiptError(
                f"invalid Mach-O referenced range for {binary}: {label}"
            )
        ranges.append((offset, byte_count, label))

    for index, command_bytes in enumerate(macho.commands):
        command, command_size = struct.unpack_from("<II", command_bytes)
        label = f"load command {index}"
        if command == LC_SYMTAB:
            if command_size != 24:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O symbol table command: {binary}"
                )
            symbol_offset, symbol_count, string_offset, string_size = (
                struct.unpack_from("<4I", command_bytes, 8)
            )
            add(symbol_offset, symbol_count * 16, f"{label} symbol table")
            add(string_offset, string_size, f"{label} string table")
        elif command == LC_DYSYMTAB:
            if command_size != 80:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O dynamic symbol table command: {binary}"
                )
            values = struct.unpack_from("<18I", command_bytes, 8)
            for offset_index, count_index, entry_size, name in (
                (6, 7, 8, "table of contents"),
                (8, 9, 56, "module table"),
                (10, 11, 4, "external references"),
                (12, 13, 4, "indirect symbols"),
                (14, 15, 8, "external relocations"),
                (16, 17, 8, "local relocations"),
            ):
                add(
                    values[offset_index],
                    values[count_index] * entry_size,
                    f"{label} {name}",
                )
        elif command in {LC_DYLD_INFO, LC_DYLD_INFO_ONLY}:
            if command_size != 48:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O dyld info command: {binary}"
                )
            values = struct.unpack_from("<10I", command_bytes, 8)
            for pair, name in enumerate(
                ("rebase", "bind", "weak bind", "lazy bind", "exports")
            ):
                add(
                    values[pair * 2],
                    values[pair * 2 + 1],
                    f"{label} {name}",
                )
        elif command in LINKEDIT_DATA_COMMANDS:
            if command_size != 16:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O linkedit data command: {binary}"
                )
            offset, byte_count = struct.unpack_from("<II", command_bytes, 8)
            add(offset, byte_count, label)
        elif command == LC_TWOLEVEL_HINTS:
            if command_size != 16:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O two-level hints command: {binary}"
                )
            offset, count = struct.unpack_from("<II", command_bytes, 8)
            add(offset, count * 4, label)
        elif command == LC_ENCRYPTION_INFO_64:
            if command_size != 24:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O encryption command: {binary}"
                )
            offset, byte_count = struct.unpack_from("<II", command_bytes, 8)
            add(offset, byte_count, label)
        elif command == LC_NOTE:
            if command_size != 40:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O note command: {binary}"
                )
            offset, byte_count = struct.unpack_from("<QQ", command_bytes, 24)
            add(offset, byte_count, label)
    return tuple(ranges)


def _macho_signature_extent(
    macho: MachoIdentity,
    binary: Path,
) -> tuple[int, int, int] | None:
    """Return one structurally terminal code-signature extent, if present."""
    signature: tuple[int, int, int] | None = None
    linkedit_matches = 0
    referenced_ranges = _macho_referenced_file_ranges(macho, binary)
    for index, command_bytes in enumerate(macho.commands):
        command, command_size = struct.unpack_from("<II", command_bytes)
        if command == LC_CODE_SIGNATURE:
            if command_size != 16 or signature is not None:
                raise MacFFmpegReceiptError(
                    f"invalid Mach-O code signature command: {binary}"
                )
            data_offset, data_size = struct.unpack_from(
                "<II", command_bytes, 8
            )
            if (
                data_size <= 0
                or data_offset < macho.first_file_offset
                or data_offset > macho.byte_count
                or data_size != macho.byte_count - data_offset
            ):
                raise MacFFmpegReceiptError(
                    f"code signature is not a terminal Mach-O blob: {binary}"
                )
            signature = (data_offset, data_size, index)

    if signature is None:
        return None

    signature_offset, signature_size, _ = signature
    for offset, byte_count, label in referenced_ranges:
        if byte_count > signature_offset - offset:
            raise MacFFmpegReceiptError(
                "code signature overlaps Mach-O referenced data "
                f"for {binary}: {label}"
            )
    for command_bytes in macho.commands:
        command, _ = struct.unpack_from("<II", command_bytes)
        if command != LC_SEGMENT_64:
            continue
        segment_name = _macho_name(
            command_bytes[8:24], f"{binary} segment"
        )
        segment_file_offset, segment_file_size = struct.unpack_from(
            "<QQ", command_bytes, 40
        )
        if segment_name == "__LINKEDIT":
            if (
                signature_offset < segment_file_offset
                or signature_offset + signature_size
                != segment_file_offset + segment_file_size
            ):
                raise MacFFmpegReceiptError(
                    f"code signature is not the final __LINKEDIT payload: {binary}"
                )
            linkedit_matches += 1

        section_count = struct.unpack_from("<I", command_bytes, 64)[0]
        section_cursor = 72
        for _ in range(section_count):
            section_size = struct.unpack_from(
                "<Q", command_bytes, section_cursor + 40
            )[0]
            section_offset = struct.unpack_from(
                "<I", command_bytes, section_cursor + 48
            )[0]
            section_flags = struct.unpack_from(
                "<I", command_bytes, section_cursor + 64
            )[0]
            if (
                section_size
                and (section_flags & SECTION_TYPE_MASK)
                not in ZERO_FILL_SECTION_TYPES
                and section_offset + section_size > signature_offset
            ):
                raise MacFFmpegReceiptError(
                    f"code signature overlaps Mach-O section data: {binary}"
                )
            section_cursor += SECTION_64_BYTES

    if linkedit_matches != 1:
        raise MacFFmpegReceiptError(
            f"Mach-O code signature lacks one terminal __LINKEDIT segment: {binary}"
        )
    return signature


def _canonical_dylib_command(command_bytes: bytes, target: str) -> bytes:
    command, _ = struct.unpack_from("<II", command_bytes)
    _, _timestamp, current_version, compatibility_version = (
        _load_command_string(command_bytes, target)
    )
    encoded_target = target.encode("utf-8") + b"\0"
    command_size = (24 + len(encoded_target) + 7) // 8 * 8
    return (
        struct.pack(
            "<6I",
            command,
            command_size,
            24,
            PACKAGING_DYLIB_TIMESTAMP,
            current_version,
            compatibility_version,
        )
        + encoded_target.ljust(command_size - 24, b"\0")
    )


def _canonical_dependency_target(
    command_bytes: bytes,
    *,
    binary: Path,
    final_path: str,
    kind: str,
    source_mode: bool,
    executable_directories: Sequence[Path],
) -> str | None:
    value, _, _, _ = _load_command_string(command_bytes, str(binary))
    if value.startswith("/"):
        dependency, is_system = _canonical_absolute_otool_path(value, binary)
        if is_system:
            return None
        if not source_mode:
            raise MacFFmpegReceiptError(
                f"final non-system dependency is absolute in {final_path}: {value}"
            )
        try:
            resolved = dependency.resolve(strict=True)
        except OSError as exc:
            raise MacFFmpegReceiptError(
                f"unresolved non-system dependency in {binary}: {value}"
            ) from exc
    elif source_mode:
        resolved = _resolve_at_dependency(
            value, binary, executable_directories
        )
    else:
        prefix = (
            "@executable_path/../lib/"
            if kind == "executable"
            else "@loader_path/"
        )
        if not value.startswith(prefix):
            raise MacFFmpegReceiptError(
                f"final dependency uses alternate loader syntax in {final_path}: {value}"
            )
        dependency_name = value.removeprefix(prefix)
        target = f"Contents/Resources/lib/{dependency_name}"
        if (
            not DYLIB_NAME_RE.fullmatch(dependency_name)
            or EXPECTED_FINAL_PATHS.get(target, (None,))[0] != "dylib"
        ):
            raise MacFFmpegReceiptError(
                f"unresolved final dependency in {final_path}: {value}"
            )
        return target

    target = f"Contents/Resources/lib/{resolved.name}"
    if EXPECTED_FINAL_PATHS.get(target, (None,))[0] != "dylib":
        raise MacFFmpegReceiptError(
            f"source dependency is outside the audited graph: {resolved}"
        )
    return target


def _descriptor_range_is_zero(
    descriptor: int,
    offset: int,
    byte_count: int,
    label: str,
) -> bool:
    consumed = 0
    while consumed < byte_count:
        wanted = min(READ_CHUNK_BYTES, byte_count - consumed)
        chunk = os.pread(descriptor, wanted, offset + consumed)
        if len(chunk) != wanted:
            raise MacFFmpegReceiptError(
                f"truncated Mach-O bytes while reading {label}"
            )
        if any(chunk):
            return False
        consumed += wanted
    return True


def _update_digest_from_descriptor(
    digest: Any,
    descriptor: int,
    offset: int,
    byte_count: int,
    label: str,
) -> None:
    consumed = 0
    while consumed < byte_count:
        wanted = min(READ_CHUNK_BYTES, byte_count - consumed)
        chunk = os.pread(descriptor, wanted, offset + consumed)
        if len(chunk) != wanted:
            raise MacFFmpegReceiptError(
                f"truncated Mach-O bytes while reading {label}"
            )
        digest.update(chunk)
        consumed += wanted


def _macho_whole_sha256(
    macho: MachoIdentity,
    descriptor: int,
    *,
    binary: Path,
    final_path: str,
    kind: str,
    source_dependencies: Sequence[Path] | None = None,
    executable_directories: Sequence[Path] = (),
) -> str:
    """Hash every Mach-O byte after only audited packaging normalization."""
    _macho_load_command_profile(
        macho,
        binary=binary,
        final_path=final_path,
        kind=kind,
        source_dependencies=source_dependencies,
        executable_directories=executable_directories,
    )
    source_mode = source_dependencies is not None
    signature = _macho_signature_extent(macho, binary)
    canonical_commands: list[bytes] = []
    for index, command_bytes in enumerate(macho.commands):
        command, _ = struct.unpack_from("<II", command_bytes)
        if command == LC_CODE_SIGNATURE:
            continue
        if command == LC_SEGMENT_64 and signature is not None:
            segment_name = _macho_name(
                command_bytes[8:24], f"{binary} load command {index} segment"
            )
            if segment_name == "__LINKEDIT":
                canonical_commands.append(
                    _canonical_signed_linkedit_command(
                        command_bytes,
                        macho,
                        signature,
                        binary,
                    )
                )
                continue
        if command == LC_ID_DYLIB:
            canonical_commands.append(
                _canonical_dylib_command(command_bytes, final_path)
            )
            continue
        if command in DYNAMIC_LIBRARY_LOAD_COMMANDS:
            target = _canonical_dependency_target(
                command_bytes,
                binary=binary,
                final_path=final_path,
                kind=kind,
                source_mode=source_mode,
                executable_directories=executable_directories,
            )
            if target is not None:
                canonical_commands.append(
                    _canonical_dylib_command(command_bytes, target)
                )
                continue
        canonical_commands.append(command_bytes)

    actual_command_end = 32 + sum(len(item) for item in macho.commands)
    if actual_command_end > macho.first_file_offset:
        raise MacFFmpegReceiptError(
            f"Mach-O commands overlap file content: {binary}"
        )
    if not _descriptor_range_is_zero(
        descriptor,
        actual_command_end,
        macho.first_file_offset - actual_command_end,
        f"{binary} header padding",
    ):
        raise MacFFmpegReceiptError(
            f"nonzero Mach-O header padding outside loader rewrites: {binary}"
        )

    canonical_command_bytes = b"".join(canonical_commands)
    canonical_header = struct.pack(
        "<8I",
        macho.header[0],
        macho.header[1],
        macho.header[2],
        macho.header[3],
        len(canonical_commands),
        len(canonical_command_bytes),
        macho.header[4],
        macho.header[5],
    )
    canonical_header_end = len(canonical_header) + len(
        canonical_command_bytes
    )
    if canonical_header_end > macho.first_file_offset:
        raise MacFFmpegReceiptError(
            f"canonical Mach-O commands overlap file content: {binary}"
        )

    unsigned_end = signature[0] if signature is not None else macho.byte_count
    if unsigned_end < macho.first_file_offset:
        raise MacFFmpegReceiptError(
            f"invalid unsigned Mach-O extent: {binary}"
        )
    digest = hashlib.sha256()
    digest.update(MACHO_WHOLE_DIGEST_DOMAIN)
    digest.update(struct.pack("<QQ", macho.first_file_offset, unsigned_end))
    digest.update(canonical_header)
    digest.update(canonical_command_bytes)
    zeroes = b"\0" * min(READ_CHUNK_BYTES, max(1, macho.first_file_offset))
    remaining_padding = macho.first_file_offset - canonical_header_end
    while remaining_padding:
        count = min(len(zeroes), remaining_padding)
        digest.update(zeroes[:count])
        remaining_padding -= count
    _update_digest_from_descriptor(
        digest,
        descriptor,
        macho.first_file_offset,
        unsigned_end - macho.first_file_offset,
        f"{binary} unsigned whole Mach-O",
    )
    return digest.hexdigest()


def _macho_whole_sha256_path(
    path: Path,
    label: str,
    expected_arch: str,
    kind: str,
    *,
    final_path: str,
    source_dependencies: Sequence[Path] | None = None,
    executable_directories: Sequence[Path] = (),
    expected_observation: tuple[int, str, MachoIdentity] | None = None,
) -> str:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise MacFFmpegReceiptError(
                f"{label} must be a regular file, not a symlink"
            )
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise MacFFmpegReceiptError(f"{label} changed while opening")
        prefix, byte_count, raw_sha256 = _read_descriptor(descriptor)
        macho = _validate_macho(
            prefix,
            byte_count,
            expected_arch,
            kind,
            label,
            descriptor,
        )
        if expected_observation is not None and (
            byte_count,
            raw_sha256,
            macho,
        ) != expected_observation:
            raise MacFFmpegReceiptError(
                f"{label} changed before whole Mach-O hashing"
            )
        whole_sha256 = _macho_whole_sha256(
            macho,
            descriptor,
            binary=path,
            final_path=final_path,
            kind=kind,
            source_dependencies=source_dependencies,
            executable_directories=executable_directories,
        )
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
            or byte_count != opened.st_size
        ):
            raise MacFFmpegReceiptError(f"{label} changed while reading")
        return whole_sha256
    except MacFFmpegReceiptError:
        raise
    except OSError as exc:
        raise MacFFmpegReceiptError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_names(names: list[str], label: str) -> None:
    folded: dict[str, str] = {}
    for name in names:
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\0" in name
            or unicodedata.normalize("NFC", name) != name
        ):
            raise MacFFmpegReceiptError(f"invalid path name in {label}: {name!r}")
        key = name.casefold()
        if key in folded and folded[key] != name:
            raise MacFFmpegReceiptError(
                f"case-colliding path names in {label}: {folded[key]}, {name}"
            )
        folded[key] = name


def scan_app_bundle(
    app_root: Path,
    expected_arch: str,
) -> dict[str, FileObservation]:
    """Inventory the exact final main FFmpeg paths in a packed app."""
    arch = _expected_arch(expected_arch)
    observations: dict[str, FileObservation] = {}
    with _held_directory_path(app_root, "packed Mac app root") as app_fd:
        with _held_child_directory(app_fd, "Contents", "app Contents") as contents_fd:
            with _held_child_directory(
                contents_fd, "Resources", "app Contents/Resources"
            ) as resources_fd:
                for directory, expected_names in (
                    ("bin", set(EXECUTABLE_SOURCE_FORMULAE)),
                    ("lib", set(LIBRARY_SOURCE_FORMULAE)),
                ):
                    with _held_child_directory(
                        resources_fd,
                        directory,
                        f"app Contents/Resources/{directory}",
                    ) as directory_fd:
                        names = os.listdir(directory_fd)
                        _validate_names(names, f"Contents/Resources/{directory}")
                        actual_names = set(names)
                        if actual_names != expected_names:
                            missing = sorted(expected_names - actual_names)
                            extra = sorted(actual_names - expected_names)
                            details = []
                            if missing:
                                details.append("missing: " + ", ".join(missing))
                            if extra:
                                details.append("extra: " + ", ".join(extra))
                            raise MacFFmpegReceiptError(
                                "final Mac FFmpeg bundle path set drifted in "
                                f"Contents/Resources/{directory}; "
                                + "; ".join(details)
                            )
                        for name in sorted(names):
                            if directory == "lib" and not DYLIB_NAME_RE.fullmatch(name):
                                raise MacFFmpegReceiptError(
                                    f"invalid dylib name in final bundle: {name}"
                                )
                            relative = f"Contents/Resources/{directory}/{name}"
                            kind = "executable" if directory == "bin" else "dylib"
                            observations[relative] = _observe_file_at(
                                directory_fd, name, relative, arch, kind
                            )
    if set(observations) != set(EXPECTED_FINAL_PATHS):
        raise MacFFmpegReceiptError(
            "final Mac FFmpeg observation set is incomplete"
        )
    return observations


def _formula_record_object(record: FormulaRecord) -> dict[str, Any]:
    return {
        "bottle_rebuild": record.bottle_rebuild,
        "bottle_sha256": record.bottle_sha256,
        "bottle_tag": record.bottle_tag,
        "formula": record.formula,
        "version": record.version,
    }


def _canonical_inventory_bytes(records: Sequence[FormulaRecord]) -> bytes:
    return "".join(
        f"{record.formula} {record.version} {record.bottle_tag} "
        f"{record.bottle_rebuild} {record.bottle_sha256}\n"
        for record in records
    ).encode("utf-8")


def _parse_formula_inventory(
    raw: bytes,
    expected_arch: str,
) -> tuple[FormulaRecord, ...]:
    arch = _expected_arch(expected_arch)
    if not raw or len(raw) > MAX_INVENTORY_BYTES:
        raise MacFFmpegReceiptError(
            "Mac FFmpeg formula inventory has an invalid byte count"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MacFFmpegReceiptError(
            "Mac FFmpeg formula inventory is not UTF-8"
        ) from exc
    if "\r" in text or not text.endswith("\n"):
        raise MacFFmpegReceiptError(
            "Mac FFmpeg formula inventory is not canonical LF text"
        )
    records: list[FormulaRecord] = []
    for number, line in enumerate(text.splitlines(), 1):
        fields = line.split(" ")
        if len(fields) != 5 or any(not field for field in fields):
            raise MacFFmpegReceiptError(
                f"formula inventory line {number} is not canonical"
            )
        formula, version, bottle_tag, rebuild_text, bottle_sha256 = fields
        if not FORMULA_RE.fullmatch(formula):
            raise MacFFmpegReceiptError(
                f"invalid formula name on inventory line {number}"
            )
        if not VERSION_RE.fullmatch(version):
            raise MacFFmpegReceiptError(
                f"invalid formula version on inventory line {number}"
            )
        if not BOTTLE_TAG_RE.fullmatch(bottle_tag):
            raise MacFFmpegReceiptError(
                f"invalid bottle tag on inventory line {number}"
            )
        if not re.fullmatch(r"0|[1-9][0-9]*", rebuild_text):
            raise MacFFmpegReceiptError(
                f"invalid bottle rebuild on inventory line {number}"
            )
        records.append(FormulaRecord(
            formula,
            version,
            bottle_tag,
            int(rebuild_text),
            _sha256(bottle_sha256, f"inventory line {number}"),
        ))
    if not records:
        raise MacFFmpegReceiptError("Mac FFmpeg formula inventory is empty")
    formulas = [record.formula for record in records]
    if formulas != sorted(formulas) or len(formulas) != len(set(formulas)):
        raise MacFFmpegReceiptError(
            "Mac FFmpeg formula inventory must be uniquely sorted"
        )
    if _canonical_inventory_bytes(records) != raw:
        raise MacFFmpegReceiptError(
            "Mac FFmpeg formula inventory bytes are not canonical"
        )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PINNED_FORMULA_INVENTORY_SHA256[arch]:
        raise MacFFmpegReceiptError(
            f"Mac FFmpeg {arch} formula inventory differs from the audited pin"
        )
    return tuple(records)


def read_formula_inventory(
    path: Path,
    expected_arch: str,
) -> tuple[tuple[FormulaRecord, ...], bytes]:
    raw, byte_count, _ = _read_regular_path(
        path,
        "Mac FFmpeg formula inventory",
        max_bytes=MAX_INVENTORY_BYTES,
    )
    if byte_count != len(raw):
        raise MacFFmpegReceiptError(
            "formula inventory exceeded the secure read prefix"
        )
    return _parse_formula_inventory(raw, expected_arch), raw


def read_embedded_formula_inventory(
    app_root: Path,
    expected_arch: str,
) -> tuple[tuple[FormulaRecord, ...], bytes]:
    """Read the exact formula inventory shipped inside the packed app."""
    arch = _expected_arch(expected_arch)
    with _held_directory_path(app_root, "packed Mac app root") as app_fd:
        with _held_child_directory(app_fd, "Contents", "app Contents") as contents_fd:
            with _held_child_directory(
                contents_fd, "Resources", "app Contents/Resources"
            ) as resources_fd:
                with _held_child_directory(
                    resources_fd,
                    "licenses",
                    "app Contents/Resources/licenses",
                ) as licenses_fd:
                    raw = _read_regular_at(
                        licenses_fd,
                        "FFMPEG_FORMULAE.txt",
                        "embedded Mac FFmpeg formula inventory",
                        max_bytes=MAX_INVENTORY_BYTES,
                    )
    return _parse_formula_inventory(raw, arch), raw


def _run_otool(mode: str, binary: Path) -> str:
    try:
        result = subprocess.run(
            [OTOOL_PATH, mode, str(binary)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MacFFmpegReceiptError(
            f"cannot inspect Homebrew dependency graph for {binary}"
        ) from exc
    return result.stdout


def _otool_install_id(binary: Path) -> str | None:
    lines = _run_otool("-D", binary).splitlines()
    if not lines or lines[0] != f"{binary}:":
        raise MacFFmpegReceiptError(
            f"unexpected otool install-ID output for {binary}"
        )
    identifiers = [line.strip() for line in lines[1:] if line.strip()]
    if len(identifiers) > 1:
        raise MacFFmpegReceiptError(
            f"multiple Mach-O install IDs reported for {binary}"
        )
    if identifiers and ("\0" in identifiers[0] or "\n" in identifiers[0]):
        raise MacFFmpegReceiptError(
            f"invalid Mach-O install ID reported for {binary}"
        )
    return identifiers[0] if identifiers else None


def _canonical_absolute_otool_path(
    value: str,
    binary: Path,
) -> tuple[Path, bool]:
    if not value.startswith("/"):
        raise MacFFmpegReceiptError(
            f"non-system dependency is not absolute in {binary}: {value}"
        )
    if unicodedata.normalize("NFC", value) != value or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        for character in value
    ):
        raise MacFFmpegReceiptError(
            f"ambiguous absolute dependency path in {binary}: {value!r}"
        )
    raw_parts = value.split("/")
    if (
        raw_parts[0] != ""
        or not raw_parts[1:]
        or any(part in {"", ".", ".."} for part in raw_parts[1:])
    ):
        raise MacFFmpegReceiptError(
            f"noncanonical absolute dependency path in {binary}: {value!r}"
        )
    pure = PurePosixPath(value)
    if pure.as_posix() != value:
        raise MacFFmpegReceiptError(
            f"noncanonical absolute dependency path in {binary}: {value!r}"
        )
    parts = pure.parts
    is_system = (
        len(parts) >= 3 and parts[:3] == ("/", "usr", "lib")
    ) or (len(parts) >= 2 and parts[:2] == ("/", "System"))
    return Path(value), is_system


def _resolve_at_dependency(
    value: str,
    binary: Path,
    executable_directories: Sequence[Path],
) -> Path:
    if value.startswith("@loader_path/"):
        bases = (binary.parent,)
        remainder = value.removeprefix("@loader_path/")
    elif value.startswith("@executable_path/"):
        bases = tuple(dict.fromkeys(executable_directories))
        remainder = value.removeprefix("@executable_path/")
        if len(bases) != 1:
            raise MacFFmpegReceiptError(
                f"cannot uniquely resolve @executable_path load in {binary}: {value}"
            )
    elif value.startswith("@rpath/"):
        raise MacFFmpegReceiptError(
            f"unresolved @rpath load in {binary}: {value}"
        )
    else:
        raise MacFFmpegReceiptError(
            f"unsupported dynamic-loader path in {binary}: {value}"
        )
    if (
        not remainder
        or remainder.startswith("/")
        or "\0" in remainder
        or "//" in remainder
        or any(part in {"", ".", ".."} for part in PurePosixPath(remainder).parts)
    ):
        raise MacFFmpegReceiptError(
            f"invalid dynamic-loader path in {binary}: {value}"
        )
    candidate = bases[0] / Path(*PurePosixPath(remainder).parts)
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise MacFFmpegReceiptError(
            f"unresolved non-system dependency in {binary}: {value}"
        ) from exc


def _otool_dependencies(
    binary: Path,
    *,
    executable_directories: Sequence[Path] = (),
) -> Sequence[Path]:
    output = _run_otool("-L", binary)
    install_id = _otool_install_id(binary)
    lines = output.splitlines()
    if not lines or lines[0] != f"{binary}:":
        raise MacFFmpegReceiptError(
            f"unexpected otool dependency output for {binary}"
        )
    values: list[str] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*(.+?)\s+\([^\n]*\)", line)
        if not match:
            raise MacFFmpegReceiptError(
                f"unparseable otool dependency output for {binary}: {line!r}"
            )
        value = match.group(1)
        if "\0" in value:
            raise MacFFmpegReceiptError(
                f"invalid dependency path reported for {binary}"
            )
        values.append(value)
    if install_id is not None:
        if not values or values[0] != install_id:
            raise MacFFmpegReceiptError(
                f"Mach-O install ID is not the first otool entry for {binary}"
            )
        values = values[1:]

    dependencies: list[Path] = []
    for value in values:
        if value.startswith("@"):
            dependencies.append(_resolve_at_dependency(
                value, binary, executable_directories
            ))
            continue
        dependency, is_system = _canonical_absolute_otool_path(value, binary)
        if is_system:
            continue
        try:
            dependencies.append(dependency.resolve(strict=True))
        except OSError as exc:
            raise MacFFmpegReceiptError(
                f"unresolved non-system dependency in {binary}: {value}"
            ) from exc
    return dependencies


def _source_formula(
    path: Path,
    cellar: Path,
) -> tuple[str, str, str]:
    try:
        relative = path.relative_to(cellar)
    except ValueError as exc:
        raise MacFFmpegReceiptError(
            f"Homebrew source is outside the Cellar: {path}"
        ) from exc
    if len(relative.parts) != 4 or relative.parts[2] not in {"bin", "lib"}:
        raise MacFFmpegReceiptError(
            f"unexpected Homebrew Cellar source path: {relative.as_posix()}"
        )
    formula, version, _, name = relative.parts
    if (
        not FORMULA_RE.fullmatch(formula)
        or not VERSION_RE.fullmatch(version)
        or unicodedata.normalize("NFC", relative.as_posix())
        != relative.as_posix()
        or name in {"", ".", ".."}
    ):
        raise MacFFmpegReceiptError(
            f"invalid Homebrew Cellar source path: {relative.as_posix()}"
        )
    return formula, version, relative.as_posix()


def discover_source_graph(
    ffmpeg_source: Path,
    ffprobe_source: Path,
    cellar: Path,
    records: Sequence[FormulaRecord],
    expected_arch: str,
    *,
    dependency_reader: DependencyReader | None = None,
) -> dict[str, SourceObservation]:
    """Resolve the original Cellar file behind every final bundle path."""
    arch = _expected_arch(expected_arch)
    try:
        cellar_root = cellar.resolve(strict=True)
        roots = {
            "ffmpeg": ffmpeg_source.resolve(strict=True),
            "ffprobe": ffprobe_source.resolve(strict=True),
        }
    except OSError as exc:
        raise MacFFmpegReceiptError(
            "cannot resolve Homebrew FFmpeg source inputs"
        ) from exc
    executable_directories = tuple(sorted({
        root.parent for root in roots.values()
    }))
    if dependency_reader is None:
        def reader(path: Path) -> Sequence[Path]:
            return _otool_dependencies(
                path,
                executable_directories=executable_directories,
            )
    else:
        reader = dependency_reader
    record_map = {record.formula: record for record in records}
    bottle_members = PINNED_BOTTLE_MEMBERS[arch]
    queue = [roots["ffmpeg"], roots["ffprobe"]]
    visited: set[Path] = set()
    by_final_path: dict[str, SourceObservation] = {}
    while queue:
        source = queue.pop(0).resolve(strict=True)
        if source in visited:
            continue
        visited.add(source)
        if source == roots["ffmpeg"]:
            name = "ffmpeg"
            kind = "executable"
        elif source == roots["ffprobe"]:
            name = "ffprobe"
            kind = "executable"
        else:
            name = source.name
            kind = "dylib"
        if kind == "executable":
            final_path = f"Contents/Resources/bin/{name}"
        else:
            if not DYLIB_NAME_RE.fullmatch(name):
                raise MacFFmpegReceiptError(
                    f"unexpected non-dylib Homebrew dependency: {source}"
                )
            final_path = f"Contents/Resources/lib/{name}"
        expected = EXPECTED_FINAL_PATHS.get(final_path)
        if expected is None or expected[0] != kind:
            raise MacFFmpegReceiptError(
                f"Homebrew FFmpeg source graph has an unexpected path: {final_path}"
            )
        formula, version, cellar_path = _source_formula(source, cellar_root)
        if formula != expected[1]:
            raise MacFFmpegReceiptError(
                f"{final_path} came from {formula}, expected {expected[1]}"
            )
        record = record_map.get(formula)
        if record is None or record.version != version:
            raise MacFFmpegReceiptError(
                f"{final_path} is not bound to its audited formula version"
            )
        byte_count, digest, macho = _observe_macho_path(
            source,
            f"Homebrew source {cellar_path}",
            arch,
            kind,
        )
        try:
            dependencies = reader(source)
        except MacFFmpegReceiptError:
            raise
        except Exception as exc:
            raise MacFFmpegReceiptError(
                f"dependency reader failed for {source}: {exc}"
            ) from exc
        resolved_dependencies: list[Path] = []
        for dependency in dependencies:
            try:
                resolved_dependencies.append(
                    Path(dependency).resolve(strict=True)
                )
            except OSError as exc:
                raise MacFFmpegReceiptError(
                    f"unresolved source dependency from {source}: {dependency}"
                ) from exc
        load_digest, dependency_paths, system_dependencies = (
            _macho_load_command_profile(
                macho,
                binary=source,
                final_path=final_path,
                kind=kind,
                source_dependencies=resolved_dependencies,
                executable_directories=executable_directories,
            )
        )
        whole_digest = _macho_whole_sha256_path(
            source,
            f"Homebrew source {cellar_path}",
            arch,
            kind,
            final_path=final_path,
            source_dependencies=resolved_dependencies,
            executable_directories=executable_directories,
            expected_observation=(byte_count, digest, macho),
        )
        observation = SourceObservation(
            final_path,
            formula,
            version,
            cellar_path,
            byte_count,
            digest,
            macho.uuid,
            macho.content_sha256,
            load_digest,
            whole_digest,
            dependency_paths,
            system_dependencies,
        )
        bottle_member = bottle_members.get(final_path)
        if bottle_member is not None:
            if record.bottle_sha256 != bottle_member.bottle_sha256:
                raise MacFFmpegReceiptError(
                    f"audited bottle digest drifted for {final_path}"
                )
            if (
                cellar_path != bottle_member.member_path
                or byte_count != bottle_member.byte_count
                or whole_digest != bottle_member.macho_whole_sha256
            ):
                raise MacFFmpegReceiptError(
                    "Homebrew source differs from its authenticated bottle "
                    f"member: {final_path}"
                )
        prior = by_final_path.get(final_path)
        if prior is not None and prior != observation:
            raise MacFFmpegReceiptError(
                f"Homebrew dylib basename collision for {final_path}"
            )
        by_final_path[final_path] = observation
        queue.extend(resolved_dependencies)
    expected_paths = set(EXPECTED_FINAL_PATHS)
    if set(by_final_path) != expected_paths:
        missing = sorted(expected_paths - set(by_final_path))
        extra = sorted(set(by_final_path) - expected_paths)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("extra: " + ", ".join(extra))
        raise MacFFmpegReceiptError(
            "Homebrew FFmpeg source graph differs from the audited bundle; "
            + "; ".join(details)
        )
    reached_formulae = {item.formula for item in by_final_path.values()}
    expected_formulae = set(record_map)
    if reached_formulae != expected_formulae:
        raise MacFFmpegReceiptError(
            "Homebrew FFmpeg source graph formula closure differs from the "
            "audited inventory"
        )
    return by_final_path


def _inventory_from_record_objects(
    value: Any,
    expected_arch: str,
) -> tuple[tuple[FormulaRecord, ...], str]:
    container = _exact_keys(
        value, {"records", "sha256"}, "formula_inventory"
    )
    if not isinstance(container["records"], list):
        raise MacFFmpegReceiptError("formula inventory records must be a list")
    records: list[FormulaRecord] = []
    for index, item in enumerate(container["records"]):
        record = _exact_keys(
            item,
            {
                "bottle_rebuild",
                "bottle_sha256",
                "bottle_tag",
                "formula",
                "version",
            },
            f"formula inventory record {index}",
        )
        formula = record["formula"]
        version = record["version"]
        bottle_tag = record["bottle_tag"]
        if not isinstance(formula, str) or not FORMULA_RE.fullmatch(formula):
            raise MacFFmpegReceiptError("invalid receipt formula name")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise MacFFmpegReceiptError("invalid receipt formula version")
        if (
            not isinstance(bottle_tag, str)
            or not BOTTLE_TAG_RE.fullmatch(bottle_tag)
        ):
            raise MacFFmpegReceiptError("invalid receipt bottle tag")
        records.append(FormulaRecord(
            formula,
            version,
            bottle_tag,
            _nonnegative_int(record["bottle_rebuild"], "bottle rebuild"),
            _sha256(record["bottle_sha256"], "bottle archive"),
        ))
    raw_inventory = _canonical_inventory_bytes(records)
    parsed = _parse_formula_inventory(raw_inventory, expected_arch)
    digest = _sha256(container["sha256"], "formula inventory")
    if hashlib.sha256(raw_inventory).hexdigest() != digest:
        raise MacFFmpegReceiptError(
            "formula inventory record bytes do not match its SHA256"
        )
    return parsed, digest


def validate_receipt(
    payload: Mapping[str, Any],
    raw: bytes,
    expected_arch: str,
) -> dict[str, Any]:
    """Validate canonical structure and every per-path lineage claim."""
    arch = _expected_arch(expected_arch)
    parsed = _parse_json_bytes(raw, "Mac FFmpeg bundle receipt")
    if not isinstance(payload, Mapping) or dict(payload) != parsed:
        raise MacFFmpegReceiptError(
            "Mac FFmpeg receipt payload differs from its raw JSON"
        )
    if canonical_json_bytes(parsed) != raw:
        raise MacFFmpegReceiptError(
            "Mac FFmpeg bundle receipt is not canonical JSON"
        )
    root = _exact_keys(
        parsed,
        {
            "bundle_inventory",
            "component",
            "files",
            "formula_inventory",
            "lineage_id",
            "platform",
            "schema",
        },
        "Mac FFmpeg bundle receipt",
    )
    if root["schema"] != SCHEMA:
        raise MacFFmpegReceiptError("Mac FFmpeg bundle receipt has wrong schema")
    if root["component"] != COMPONENT:
        raise MacFFmpegReceiptError("Mac FFmpeg bundle receipt has wrong component")
    if root["platform"] != PLATFORMS[arch]:
        raise MacFFmpegReceiptError("Mac FFmpeg bundle receipt has wrong platform")
    if root["lineage_id"] != LINEAGE_IDS[arch]:
        raise MacFFmpegReceiptError("Mac FFmpeg bundle receipt has wrong lineage")
    records, inventory_digest = _inventory_from_record_objects(
        root["formula_inventory"], arch
    )
    record_map = {record.formula: record for record in records}

    files = root["files"]
    if not isinstance(files, dict) or set(files) != set(EXPECTED_FINAL_PATHS):
        raise MacFFmpegReceiptError(
            "Mac FFmpeg receipt paths differ from the audited final path set"
        )
    referenced_formulae: set[str] = set()

    def dependency_claims(value: Any, label: str) -> tuple[str, ...]:
        if (
            not isinstance(value, list)
            or any(
                not isinstance(item, str)
                or EXPECTED_FINAL_PATHS.get(item, (None,))[0] != "dylib"
                for item in value
            )
            or len(value) != len(set(value))
        ):
            raise MacFFmpegReceiptError(f"invalid dependency edges for {label}")
        return tuple(value)

    def system_claims(value: Any, label: str) -> tuple[str, ...]:
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ) or len(value) != len(set(value)):
            raise MacFFmpegReceiptError(f"invalid system loads for {label}")
        for item in value:
            _, is_system = _canonical_absolute_otool_path(item, Path(label))
            if not is_system:
                raise MacFFmpegReceiptError(
                    f"non-system path recorded as a system load for {label}"
                )
        return tuple(value)

    for relative in sorted(files):
        expected_kind, expected_formula = EXPECTED_FINAL_PATHS[relative]
        entry = _exact_keys(
            files[relative],
            {
                "architecture",
                "bytes",
                "dependencies",
                "kind",
                "macho_content_sha256",
                "macho_load_commands_sha256",
                "macho_whole_sha256",
                "macho_uuid",
                "sha256",
                "source",
                "system_dependencies",
            },
            f"Mac FFmpeg file claim {relative}",
        )
        if entry["architecture"] != arch:
            raise MacFFmpegReceiptError(
                f"Mac FFmpeg file claim has wrong architecture: {relative}"
            )
        if entry["kind"] != expected_kind:
            raise MacFFmpegReceiptError(
                f"Mac FFmpeg file claim has wrong kind: {relative}"
            )
        _positive_int(entry["bytes"], f"byte count for {relative}")
        _sha256(entry["sha256"], f"final file {relative}")
        final_uuid = _macho_uuid(entry["macho_uuid"], f"final file {relative}")
        final_content = _sha256(
            entry["macho_content_sha256"],
            f"final Mach-O content {relative}",
        )
        final_load_commands = _sha256(
            entry["macho_load_commands_sha256"],
            f"final Mach-O load commands {relative}",
        )
        final_whole = _sha256(
            entry["macho_whole_sha256"],
            f"final whole Mach-O {relative}",
        )
        final_dependencies = dependency_claims(
            entry["dependencies"], f"final file {relative}"
        )
        final_system = system_claims(
            entry["system_dependencies"], f"final file {relative}"
        )
        source = _exact_keys(
            entry["source"],
            {
                "bytes",
                "cellar_path",
                "dependencies",
                "formula",
                "formula_version",
                "macho_content_sha256",
                "macho_load_commands_sha256",
                "macho_whole_sha256",
                "macho_uuid",
                "sha256",
                "system_dependencies",
            },
            f"Mac FFmpeg source claim {relative}",
        )
        if source["formula"] != expected_formula:
            raise MacFFmpegReceiptError(
                f"Mac FFmpeg source formula is wrong for {relative}"
            )
        record = record_map.get(expected_formula)
        if record is None or source["formula_version"] != record.version:
            raise MacFFmpegReceiptError(
                f"Mac FFmpeg source version is wrong for {relative}"
            )
        source_path = source["cellar_path"]
        if not isinstance(source_path, str):
            raise MacFFmpegReceiptError(
                f"Mac FFmpeg source path is invalid for {relative}"
            )
        pure = PurePosixPath(source_path)
        final_name = PurePosixPath(relative).name
        expected_directory = "bin" if expected_kind == "executable" else "lib"
        if (
            pure.is_absolute()
            or pure.as_posix() != source_path
            or len(pure.parts) != 4
            or pure.parts
            != (expected_formula, record.version, expected_directory, final_name)
            or any(part in {"", ".", ".."} for part in pure.parts)
            or unicodedata.normalize("NFC", source_path) != source_path
        ):
            raise MacFFmpegReceiptError(
                f"Mac FFmpeg Cellar path is wrong for {relative}"
            )
        _positive_int(source["bytes"], f"source byte count for {relative}")
        _sha256(source["sha256"], f"source file for {relative}")
        source_uuid = _macho_uuid(
            source["macho_uuid"], f"source file {relative}"
        )
        source_content = _sha256(
            source["macho_content_sha256"],
            f"source Mach-O content {relative}",
        )
        source_load_commands = _sha256(
            source["macho_load_commands_sha256"],
            f"source Mach-O load commands {relative}",
        )
        source_whole = _sha256(
            source["macho_whole_sha256"],
            f"source whole Mach-O {relative}",
        )
        source_dependencies = dependency_claims(
            source["dependencies"], f"source file {relative}"
        )
        source_system = system_claims(
            source["system_dependencies"], f"source file {relative}"
        )
        if (
            final_uuid != source_uuid
            or final_content != source_content
            or final_load_commands != source_load_commands
            or final_whole != source_whole
            or final_dependencies != source_dependencies
            or final_system != source_system
        ):
            raise MacFFmpegReceiptError(
                f"Mac FFmpeg source and final Mach-O identity differ: {relative}"
            )
        referenced_formulae.add(expected_formula)
    if referenced_formulae != set(record_map):
        raise MacFFmpegReceiptError(
            "Mac FFmpeg receipt does not reference the exact formula closure"
        )

    bundle = _exact_keys(
        root["bundle_inventory"],
        {"file_count", "sha256", "total_bytes"},
        "bundle_inventory",
    )
    file_count = _positive_int(
        bundle["file_count"], "Mac FFmpeg bundle file count"
    )
    total_bytes = _positive_int(
        bundle["total_bytes"], "Mac FFmpeg bundle byte count"
    )
    if file_count != len(files):
        raise MacFFmpegReceiptError("Mac FFmpeg bundle file count drifted")
    expected_total = sum(entry["bytes"] for entry in files.values())
    if total_bytes != expected_total:
        raise MacFFmpegReceiptError("Mac FFmpeg bundle byte count drifted")
    files_digest = hashlib.sha256(canonical_json_bytes(files)).hexdigest()
    if _sha256(bundle["sha256"], "bundle inventory") != files_digest:
        raise MacFFmpegReceiptError("Mac FFmpeg bundle inventory digest drifted")
    if inventory_digest != PINNED_FORMULA_INVENTORY_SHA256[arch]:
        raise MacFFmpegReceiptError("Mac FFmpeg formula lineage digest drifted")
    return parsed


def claims_from_receipt(
    payload: Mapping[str, Any],
    raw: bytes,
    expected_arch: str,
) -> Mapping[str, FileClaim]:
    """Return exact app-relative claims for native allowlist generation."""
    validated = validate_receipt(payload, raw, expected_arch)
    inventory_digest = validated["formula_inventory"]["sha256"]
    claims: dict[str, FileClaim] = {}
    for relative, entry in validated["files"].items():
        source = entry["source"]
        claims[relative] = FileClaim(
            path=relative,
            bytes=entry["bytes"],
            sha256=entry["sha256"],
            architecture=entry["architecture"],
            kind=entry["kind"],
            source_formula=source["formula"],
            source_formula_version=source["formula_version"],
            source_cellar_path=source["cellar_path"],
            source_bytes=source["bytes"],
            source_sha256=source["sha256"],
            macho_uuid=entry["macho_uuid"],
            macho_content_sha256=entry["macho_content_sha256"],
            macho_load_commands_sha256=entry[
                "macho_load_commands_sha256"
            ],
            macho_whole_sha256=entry["macho_whole_sha256"],
            source_macho_uuid=source["macho_uuid"],
            source_macho_content_sha256=source["macho_content_sha256"],
            source_macho_load_commands_sha256=source[
                "macho_load_commands_sha256"
            ],
            source_macho_whole_sha256=source["macho_whole_sha256"],
            dependencies=tuple(entry["dependencies"]),
            system_dependencies=tuple(entry["system_dependencies"]),
            formula_inventory_sha256=inventory_digest,
        )
    return MappingProxyType(dict(sorted(claims.items())))


def generate_receipt(
    app_root: Path,
    ffmpeg_source: Path,
    ffprobe_source: Path,
    cellar: Path,
    formula_inventory: Path,
    expected_arch: str,
    *,
    dependency_reader: DependencyReader | None = None,
) -> tuple[dict[str, Any], bytes]:
    """Generate canonical receipt bytes from the final app and source graph."""
    arch = _expected_arch(expected_arch)
    records, inventory_raw = read_formula_inventory(formula_inventory, arch)
    embedded_records, embedded_inventory_raw = read_embedded_formula_inventory(
        app_root, arch
    )
    if (
        embedded_records != records
        or embedded_inventory_raw != inventory_raw
    ):
        raise MacFFmpegReceiptError(
            "packed app formula inventory differs from the authenticated input"
        )
    sources = discover_source_graph(
        ffmpeg_source,
        ffprobe_source,
        cellar,
        records,
        arch,
        dependency_reader=dependency_reader,
    )
    final_files = scan_app_bundle(app_root, arch)

    records_after, inventory_raw_after = read_formula_inventory(
        formula_inventory, arch
    )
    embedded_records_after, embedded_inventory_raw_after = (
        read_embedded_formula_inventory(app_root, arch)
    )
    sources_after = discover_source_graph(
        ffmpeg_source,
        ffprobe_source,
        cellar,
        records_after,
        arch,
        dependency_reader=dependency_reader,
    )
    final_files_after = scan_app_bundle(app_root, arch)
    if (
        records_after != records
        or inventory_raw_after != inventory_raw
        or embedded_records_after != embedded_records
        or embedded_inventory_raw_after != embedded_inventory_raw
        or sources_after != sources
        or final_files_after != final_files
    ):
        raise MacFFmpegReceiptError(
            "Mac FFmpeg producer inputs changed while generating the receipt"
        )

    files: dict[str, dict[str, Any]] = {}
    for relative in sorted(EXPECTED_FINAL_PATHS):
        final = final_files[relative]
        source = sources[relative]
        if final.macho_uuid != source.macho_uuid:
            raise MacFFmpegReceiptError(
                "final Mac FFmpeg Mach-O UUID does not match its Cellar "
                f"source: {relative}"
            )
        if final.macho_content_sha256 != source.macho_content_sha256:
            raise MacFFmpegReceiptError(
                "final Mac FFmpeg Mach-O section content does not match its "
                "Cellar "
                f"source: {relative}"
            )
        if final.dependencies != source.dependencies:
            raise MacFFmpegReceiptError(
                "final Mac FFmpeg dependency edges differ from the Cellar "
                f"source: {relative}"
            )
        if final.system_dependencies != source.system_dependencies:
            raise MacFFmpegReceiptError(
                "final Mac FFmpeg system loads differ from the Cellar "
                f"source: {relative}"
            )
        if (
            final.macho_load_commands_sha256
            != source.macho_load_commands_sha256
        ):
            raise MacFFmpegReceiptError(
                "final Mac FFmpeg load-command semantics differ from the "
                f"Cellar source: {relative}"
            )
        if final.macho_whole_sha256 != source.macho_whole_sha256:
            raise MacFFmpegReceiptError(
                "final Mac FFmpeg whole Mach-O identity differs from the "
                f"Cellar source: {relative}"
            )
        files[relative] = {
            "architecture": final.architecture,
            "bytes": final.byte_count,
            "dependencies": list(final.dependencies),
            "kind": final.kind,
            "macho_content_sha256": final.macho_content_sha256,
            "macho_load_commands_sha256": (
                final.macho_load_commands_sha256
            ),
            "macho_whole_sha256": final.macho_whole_sha256,
            "macho_uuid": final.macho_uuid,
            "sha256": final.sha256,
            "system_dependencies": list(final.system_dependencies),
            "source": {
                "bytes": source.byte_count,
                "cellar_path": source.cellar_path,
                "dependencies": list(source.dependencies),
                "formula": source.formula,
                "formula_version": source.formula_version,
                "macho_content_sha256": source.macho_content_sha256,
                "macho_load_commands_sha256": (
                    source.macho_load_commands_sha256
                ),
                "macho_whole_sha256": source.macho_whole_sha256,
                "macho_uuid": source.macho_uuid,
                "sha256": source.sha256,
                "system_dependencies": list(source.system_dependencies),
            },
        }
    payload = {
        "bundle_inventory": {
            "file_count": len(files),
            "sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
            "total_bytes": sum(entry["bytes"] for entry in files.values()),
        },
        "component": COMPONENT,
        "files": files,
        "formula_inventory": {
            "records": [_formula_record_object(record) for record in records],
            "sha256": hashlib.sha256(inventory_raw).hexdigest(),
        },
        "lineage_id": LINEAGE_IDS[arch],
        "platform": PLATFORMS[arch],
        "schema": SCHEMA,
    }
    raw = canonical_json_bytes(payload)
    validate_receipt(payload, raw, arch)
    return payload, raw


def verify_app(
    app_root: Path,
    payload: Mapping[str, Any],
    raw: bytes,
    expected_arch: str,
) -> Mapping[str, FileClaim]:
    """Verify that a final app is byte-identical to a canonical receipt."""
    arch = _expected_arch(expected_arch)
    validated = validate_receipt(payload, raw, arch)
    embedded_records, embedded_raw = read_embedded_formula_inventory(
        app_root, arch
    )
    expected_inventory = validated["formula_inventory"]
    if (
        [_formula_record_object(record) for record in embedded_records]
        != expected_inventory["records"]
        or hashlib.sha256(embedded_raw).hexdigest()
        != expected_inventory["sha256"]
    ):
        raise MacFFmpegReceiptError(
            "embedded Mac FFmpeg formula inventory differs from receipt"
        )
    first = scan_app_bundle(app_root, arch)
    second = scan_app_bundle(app_root, arch)
    if first != second:
        raise MacFFmpegReceiptError(
            "final Mac FFmpeg app tree changed during receipt verification"
        )
    for relative, observation in first.items():
        expected = validated["files"][relative]
        if (
            observation.byte_count != expected["bytes"]
            or observation.sha256 != expected["sha256"]
            or observation.architecture != expected["architecture"]
            or observation.kind != expected["kind"]
            or observation.macho_uuid != expected["macho_uuid"]
            or observation.macho_content_sha256
            != expected["macho_content_sha256"]
            or observation.macho_load_commands_sha256
            != expected["macho_load_commands_sha256"]
            or observation.macho_whole_sha256
            != expected["macho_whole_sha256"]
            or list(observation.dependencies) != expected["dependencies"]
            or list(observation.system_dependencies)
            != expected["system_dependencies"]
        ):
            raise MacFFmpegReceiptError(
                f"final Mac FFmpeg bytes differ from receipt: {relative}"
            )
    return claims_from_receipt(validated, raw, arch)


def load_authenticated_receipt(
    path: Path,
    expected_sha256: str,
    expected_arch: str,
) -> tuple[dict[str, Any], bytes]:
    expected = _sha256(expected_sha256, "Mac FFmpeg receipt input")
    raw, byte_count, actual = _read_regular_path(
        path,
        "Mac FFmpeg bundle receipt",
        max_bytes=MAX_JSON_BYTES,
    )
    if byte_count != len(raw):
        raise MacFFmpegReceiptError("Mac FFmpeg receipt read was truncated")
    if actual != expected:
        raise MacFFmpegReceiptError(
            "Mac FFmpeg receipt raw SHA256 differs from the authenticated input"
        )
    payload = _parse_json_bytes(raw, "Mac FFmpeg bundle receipt")
    return validate_receipt(payload, raw, expected_arch), raw


def write_new_receipt(path: Path, raw: bytes) -> None:
    payload = _parse_json_bytes(raw, "Mac FFmpeg bundle receipt")
    platform = payload.get("platform")
    architecture = next(
        (arch for arch, expected in PLATFORMS.items() if expected == platform),
        None,
    )
    if architecture is None:
        raise MacFFmpegReceiptError(
            "Mac FFmpeg bundle receipt has an unsupported platform"
        )
    validate_receipt(payload, raw, architecture)
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_names([path.name], "Mac FFmpeg receipt output")
    with _held_writable_directory_path(
        path.parent, "Mac FFmpeg receipt output directory"
    ) as parent_fd:
        descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(
                os, "O_CLOEXEC", 0
            )
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(
                path.name, flags, 0o644, dir_fd=parent_fd
            )
            opened = os.fstat(descriptor)
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise MacFFmpegReceiptError(
                        "short Mac FFmpeg receipt write"
                    )
                view = view[written:]
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            linked = os.stat(
                path.name, dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size != len(raw)
                or _stat_identity(metadata) != _stat_identity(linked)
                or _stat_identity(opened)[:4] != _stat_identity(metadata)[:4]
            ):
                raise MacFFmpegReceiptError(
                    "invalid written Mac FFmpeg receipt"
                )
        except MacFFmpegReceiptError:
            raise
        except OSError as exc:
            raise MacFFmpegReceiptError(
                f"cannot create Mac FFmpeg receipt: {exc}"
            ) from exc
        # Leave a failed create in place. POSIX has no unlink-by-file-
        # descriptor operation, so deleting by pathname here could remove an
        # attacker-supplied replacement after a rename race. A later create
        # fails closed under O_EXCL until the path is inspected by the caller.
        finally:
            if descriptor is not None:
                os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--app-root", type=Path, required=True)
    generate.add_argument("--ffmpeg-source", type=Path, required=True)
    generate.add_argument("--ffprobe-source", type=Path, required=True)
    generate.add_argument("--cellar", type=Path, required=True)
    generate.add_argument("--formula-inventory", type=Path, required=True)
    generate.add_argument(
        "--expected-arch", choices=sorted(CPU_TYPES), required=True
    )
    generate.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--app-root", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--receipt-sha256", required=True)
    verify.add_argument(
        "--expected-arch", choices=sorted(CPU_TYPES), required=True
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "generate":
            _, raw = generate_receipt(
                args.app_root,
                args.ffmpeg_source,
                args.ffprobe_source,
                args.cellar,
                args.formula_inventory,
                args.expected_arch,
            )
            write_new_receipt(args.output, raw)
            print(hashlib.sha256(raw).hexdigest())
        else:
            payload, raw = load_authenticated_receipt(
                args.receipt, args.receipt_sha256, args.expected_arch
            )
            claims = verify_app(
                args.app_root, payload, raw, args.expected_arch
            )
            print(
                f"verified {len(claims)} exact final Mac FFmpeg paths "
                f"for {args.expected_arch}"
            )
    except MacFFmpegReceiptError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
