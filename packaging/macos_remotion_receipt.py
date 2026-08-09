#!/usr/bin/env python3
"""Create and verify exact macOS Remotion compositor producer receipts.

The contract authenticates the exact npm lock entry and pinned npm tarball for
``@remotion/compositor-darwin-{arm64,x64}@4.0.507``.  It then compares the
whole installed package in the final ``.app`` against that source.  Data files
must remain byte-identical.  Mach-O files may differ only by their embedded
code signature: each signed input must pass exact ``/usr/bin/codesign`` strict
verification, then its terminal signature geometry is normalized in memory.
Architecture, Mach-O kind, UUID, and every other pre-signature byte must match.

Directory-descriptor traversal and no-follow opens make missing, extra,
symlinked, hard-linked, case-drifted, or concurrently replaced package files
fail closed.  The canonical receipt records both source and final raw hashes,
the normalized native hashes, the authenticated lockfile hash, and a digest of
the complete source manifest.  This is a technical provenance contract, not a
licensing determination.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterator


SCHEMA = "autoeditor-macos-remotion-producer/v1"
SOURCE_MANIFEST_SCHEMA = "autoeditor-remotion-npm-source/v1"
COMPONENT = "remotion"
VERSION = "4.0.507"
PACKAGE_ROOT_PREFIX = (
    "Contents/Resources/creative-runtime/node_modules/@remotion"
)
LOCKFILE_LOGICAL_PATH = "packaging/helper-runtime/package-lock.json"
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_TARBALL_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 96 * 1024 * 1024
MAX_MACHO_COMMAND_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
CODESIGN_PATH = "/usr/bin/codesign"

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
UUID_RE = re.compile(
    r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\Z"
)

CPU_TYPES = {
    "arm64": 0x0100000C,
    "x64": 0x01000007,
}
PLATFORMS = {
    "arm64": "mac-arm64",
    "x64": "mac-x64",
}
MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe": "<",
    b"\xfe\xed\xfa\xcf": ">",
}
MH_EXECUTE = 0x2
MH_DYLIB = 0x6
MH_BUNDLE = 0x8
LC_UUID = 0x1B
LC_CODE_SIGNATURE = 0x1D
LC_SEGMENT_64 = 0x19

NATIVE_FILES = frozenset({
    "ffmpeg",
    "ffprobe",
    "libavcodec.dylib",
    "libavdevice.dylib",
    "libavfilter.dylib",
    "libavformat.dylib",
    "libavutil.dylib",
    "libswresample.dylib",
    "libswscale.dylib",
    "remotion",
})
EXECUTABLE_FILES = frozenset({"ffmpeg", "ffprobe", "remotion"})
DATA_FILES = frozenset({
    "README.md", "index.d.ts", "index.js", "index.mjs", "package.json",
})
EXPECTED_FILES = NATIVE_FILES | DATA_FILES


class MacRemotionReceiptError(ValueError):
    """The source, final package, or producer receipt failed closed."""


@dataclass(frozen=True)
class ArchContract:
    architecture: str
    platform: str
    package_name: str
    lock_key: str
    resolved: str
    integrity: str
    tarball_sha256: str
    tarball_bytes: int
    lineage_id: str


@dataclass(frozen=True)
class SourceFilePin:
    byte_count: int
    sha256: str
    mode: int
    kind: str
    normalized_bytes: int | None = None
    normalized_sha256: str | None = None
    macho_uuid: str | None = None
    normalized_linkedit_vmsize: int | None = None


@dataclass(frozen=True)
class MachMetadata:
    architecture: str
    kind: str
    macho_uuid: str | None
    command_count: int
    command_bytes: int
    has_code_signature: bool
    linkedit_vm_address: int
    linkedit_vm_size: int
    linkedit_file_offset: int
    linkedit_file_size: int
    linkedit_vmsize_offset: int
    code_signature_command_offset: int | None
    code_signature_offset: int | None
    code_signature_size: int | None


@dataclass(frozen=True)
class FileObservation:
    path: str
    byte_count: int
    sha256: str
    mode: int
    raw: bytes
    architecture: str | None = None
    kind: str = "data"
    macho_uuid: str | None = None
    normalized_bytes: int | None = None
    normalized_sha256: str | None = None
    normalized_linkedit_vmsize: int | None = None


@dataclass(frozen=True)
class FileClaim:
    """One exact native-file producer claim for allowlist generation."""

    path: str
    bytes: int
    sha256: str
    architecture: str
    kind: str
    lineage_id: str
    source_manifest_sha256: str
    source_path: str
    source_bytes: int
    source_sha256: str
    normalized_bytes: int
    normalized_sha256: str
    normalized_linkedit_vmsize: int
    mode: str


ARCH_CONTRACTS: Mapping[str, ArchContract] = MappingProxyType({
    "arm64": ArchContract(
        architecture="arm64",
        platform="mac-arm64",
        package_name="@remotion/compositor-darwin-arm64",
        lock_key="node_modules/@remotion/compositor-darwin-arm64",
        resolved=(
            "https://registry.npmjs.org/@remotion/compositor-darwin-arm64/-/"
            "compositor-darwin-arm64-4.0.507.tgz"
        ),
        integrity=(
            "sha512-MNvUNS33X3YCwalX+LbGcYXXxkWnOspX2vB7agzkHE/"
            "IKSFAG58sF9iXyp+rn6lJmCjBcaUxO7paJFxfAzjwEw=="
        ),
        tarball_sha256=(
            "657b2f944ebb850b316fae97fcf7e1a1b62ced8e5421ba0ca3d5c7930bf2960a"
        ),
        tarball_bytes=8_442_638,
        lineage_id="npm:@remotion/compositor-darwin-arm64@4.0.507",
    ),
    "x64": ArchContract(
        architecture="x64",
        platform="mac-x64",
        package_name="@remotion/compositor-darwin-x64",
        lock_key="node_modules/@remotion/compositor-darwin-x64",
        resolved=(
            "https://registry.npmjs.org/@remotion/compositor-darwin-x64/-/"
            "compositor-darwin-x64-4.0.507.tgz"
        ),
        integrity=(
            "sha512-oz8Wjq42oKZwhTc2N20tBMXx7Ts3K5T+cQH6oo5PEyFgrpx1j5Lm2AQT"
            "sunlgiMhOda20Vff0ZLeiXVUR+xtuA=="
        ),
        tarball_sha256=(
            "b834141ad1e5f3ea7cb9cffd6e96de4df4a32470f9db08b78fb35d05b124f25e"
        ),
        tarball_bytes=9_632_985,
        lineage_id="npm:@remotion/compositor-darwin-x64@4.0.507",
    ),
})


def _pin(
    byte_count: int,
    sha256: str,
    mode: int,
    kind: str,
    normalized_bytes: int | None = None,
    normalized_sha256: str | None = None,
    macho_uuid: str | None = None,
    normalized_linkedit_vmsize: int | None = None,
) -> SourceFilePin:
    return SourceFilePin(
        byte_count, sha256, mode, kind, normalized_bytes,
        normalized_sha256, macho_uuid, normalized_linkedit_vmsize,
    )


PINNED_SOURCE_FILES: Mapping[str, Mapping[str, SourceFilePin]] = (
    MappingProxyType({
        "arm64": MappingProxyType({
            "README.md": _pin(156, "f163a3c334ce9e293ccb8c0d7f5cbdf3ab81a0adfed5e20ac4fbd66bfe1b7d9b", 0o644, "data"),
            "ffmpeg": _pin(304696, "899fceb537d0e7609433aa644830cfc8ddcef4b97077c5e2150b43505928c5e9", 0o755, "executable", 302200, "d7e8b8bcc50f6a31829143a7639cd96630acfd100202a5c9f33529b93cc69eee", "1C8501DD-055E-3619-8628-12E789E318DA", 49152),
            "ffprobe": _pin(168520, "3ad991fd4ca0556195e88686b57af91e0518a9ac8abfb3d0d10b85a6fa168527", 0o755, "executable", 167088, "961d24c4d81b34e52b951d2f43d293b417f39a12c1c769ab3cc000222315f7a6", "7123B343-5CCD-3705-A5CF-AB0518F16C70", 32768),
            "index.d.ts": _pin(26, "32d05b74efe9deaffef9116eb9838fc6a7e4a7ba908e1142daf152bf60a22aca", 0o644, "data"),
            "index.js": _pin(25, "439eed71b21d9e5ad1223983ad7f60a286e24661905f2d918b6ff92430fe6964", 0o644, "data"),
            "index.mjs": _pin(132, "bcd507a747b4d5cdcaf0fcf4da0cab5736a88ab7a6e3abb337db1c81c836140e", 0o644, "data"),
            "libavcodec.dylib": _pin(13454816, "6175fee33ee11d610b00ce2e4841489b21245a21de009e7a9b9b7dd2b31aa113", 0o755, "dylib", 13350360, "84cb3df2cfc2147b2c64243fe984c6118a62271e00b5ebc1cf3cf01d7c61e31d", "9012E928-43B3-306F-9559-BE39F04010FF", 98304),
            "libavdevice.dylib": _pin(81872, "e6ca27cd57e8a3e19018ee82aa6ffe74c860032118ea1d85f1cba5b82cf25627", 0o755, "dylib", 81104, "20864829f7a959d26e82907197f1fd0752f44870183d07d98448f09db44932ea", "3671E6EA-6563-30FD-AEE0-DE3541380831", 16384),
            "libavfilter.dylib": _pin(510304, "d40071fa15228cddab3defa3e1063af57f0b358a53b61dca90db3b4938f91dfd", 0o755, "dylib", 506200, "e098fcb56d4cfced59575408531e02bef7625496b155df1c4fb07acc4108a742", "DAFEA53F-0BE1-3D08-8466-993ECC8AFC8F", 32768),
            "libavformat.dylib": _pin(967328, "3b8c8a9441c789b13d3b1af4cd401bb40ad1cde8c6f874da99ed5688846261ca", 0o755, "dylib", 959672, "92f9ca54dcbf35c02d1c940b7c40e14ee4d35d26d8714663148db6d1cc84c7ea", "7A040704-E10C-3F99-A258-2D681FB84455", 65536),
            "libavutil.dylib": _pin(542896, "84989619c29d4a92703da2ee8fc51418a91e7e64cb70993bd6cab006ea36478e", 0o755, "dylib", 538536, "861b3f4e1a634c777b67b8b1dc37416604c0009b8810531c612f9e1d67ffcca3", "944C1BB7-86A7-3B62-AEED-B7A5163A55B4", 49152),
            "libswresample.dylib": _pin(86992, "6d6e19ca4f8fa95392e68f59a120ae19bbe7dc3e3ee895900bab7ede5ec25206", 0o755, "dylib", 86160, "fabc5444a722493310f4ae5ea591c75f2999c0ce5ee4b26653a4c055ed0a4a84", "ECAD1064-B4BA-3395-A31E-2C4B1D630E57", 16384),
            "libswscale.dylib": _pin(369536, "51d63f757c117b430a20213a0c4bf397b06ee34be1c58dd213de8b0b646418d5", 0o755, "dylib", 366528, "0c7bda7054453d1f1ba089a23eb6a515870eb0879e25aeab1b0dbc97d1b8b4b3", "0B47118B-1EE9-36FD-B4C9-88AE06B0BAAB", 16384),
            "package.json": _pin(506, "32e5c7e91c987ff824f36d1fdd7b691151f92abc62378e708490f381a4e50237", 0o644, "data"),
            "remotion": _pin(1212672, "4e129fef9e26bfcec7fcb4667e5bde7b6abc9dee515fd2cf18bcc28409f7e066", 0o755, "executable", 1203112, "73315f7433945b7055b7c3540aa3c2622adda988facecd97de0784228613f108", "05026C2D-25EA-300F-B886-98C38B13E3C5", 163840),
        }),
        "x64": MappingProxyType({
            "README.md": _pin(144, "09c1865b586d03ea6c08ca602c2d0fca5e9dcefa0332eeff30f1bfd4cd4ef209", 0o644, "data"),
            "ffmpeg": _pin(301864, "4a14d5ceddb1d601f15fca2f52f2f41dd253b57b9e3572aeb770fb0c06529ee5", 0o755, "executable", 301864, "4a14d5ceddb1d601f15fca2f52f2f41dd253b57b9e3572aeb770fb0c06529ee5", "881369F0-8880-33ED-ABD5-EF809008F53F", 49152),
            "ffprobe": _pin(150528, "1aafe77f2c5b0d34e263ff8c940b4ccfbcb26716ad99bed8bb190f18073df041", 0o755, "executable", 150528, "1aafe77f2c5b0d34e263ff8c940b4ccfbcb26716ad99bed8bb190f18073df041", "D69EF737-FDAA-35D7-95E2-6510C4858DAC", 32768),
            "index.d.ts": _pin(26, "32d05b74efe9deaffef9116eb9838fc6a7e4a7ba908e1142daf152bf60a22aca", 0o644, "data"),
            "index.js": _pin(25, "439eed71b21d9e5ad1223983ad7f60a286e24661905f2d918b6ff92430fe6964", 0o644, "data"),
            "index.mjs": _pin(132, "bcd507a747b4d5cdcaf0fcf4da0cab5736a88ab7a6e3abb337db1c81c836140e", 0o644, "data"),
            "libavcodec.dylib": _pin(20296008, "c5632ffe2601ae43df86e1c9b4d362d02ca5eeece2fbd8b3f34f2fa280d2c062", 0o755, "dylib", 20296008, "c5632ffe2601ae43df86e1c9b4d362d02ca5eeece2fbd8b3f34f2fa280d2c062", "7A528FBA-D673-3DC1-893B-321A4103B168", 131072),
            "libavdevice.dylib": _pin(60600, "ab2101916b5de4ec7db31e3818e06b4b8b5e37fdcd716a886ae7a2c67899a3ad", 0o755, "dylib", 60600, "ab2101916b5de4ec7db31e3818e06b4b8b5e37fdcd716a886ae7a2c67899a3ad", "E6905A62-53E5-30B4-A817-CA5D979662A8", 16384),
            "libavfilter.dylib": _pin(965776, "593e5b1623c80d28ab367d36a1096ddd6a1ac30bbe270b19e6bbe8f8bb32f7ed", 0o755, "dylib", 965776, "593e5b1623c80d28ab367d36a1096ddd6a1ac30bbe270b19e6bbe8f8bb32f7ed", "E7B8BE2D-58FB-3FE4-9B76-4E83BDC056A5", 32768),
            "libavformat.dylib": _pin(1015432, "094311e17a170edec1fb45e5231bb7289bede0cac1d6d932ff7c623d29d066bf", 0o755, "dylib", 1015432, "094311e17a170edec1fb45e5231bb7289bede0cac1d6d932ff7c623d29d066bf", "DBDF1C13-1731-3D07-A083-77641EF65786", 65536),
            "libavutil.dylib": _pin(661344, "9f9d4b89506e9fc6344c6d2b17f09e2509a70a8627bcec3ecb7479ca5db9bd87", 0o755, "dylib", 661344, "9f9d4b89506e9fc6344c6d2b17f09e2509a70a8627bcec3ecb7479ca5db9bd87", "2E438996-044B-374D-93A3-D99B6197DD17", 49152),
            "libswresample.dylib": _pin(99024, "f0cf5934bbf638129b64753f0abd1e62b1ed5137f6740b1c8d0391f6e454fab9", 0o755, "dylib", 99024, "f0cf5934bbf638129b64753f0abd1e62b1ed5137f6740b1c8d0391f6e454fab9", "0F133F1B-6574-3D31-AD23-303F6C4792B6", 16384),
            "libswscale.dylib": _pin(548008, "aec83026916fb3fb88d74c5180f5e8b95a6c6afe6e64ccff546edf40ea8b6d0a", 0o755, "dylib", 548008, "aec83026916fb3fb88d74c5180f5e8b95a6c6afe6e64ccff546edf40ea8b6d0a", "766F225B-427B-3E26-816B-3284722D4A50", 16384),
            "package.json": _pin(490, "ecdc1fc239e275123f5496a1d1f44e42cb5b94225af2f9e84e10c1fd81f7cbae", 0o644, "data"),
            "remotion": _pin(1202160, "6b5c4d78ce8184ff5770e22b648ec0438f66bcfa174c084762d88ccb56360fa6", 0o755, "executable", 1202160, "6b5c4d78ce8184ff5770e22b648ec0438f66bcfa174c084762d88ccb56360fa6", "7A5450E7-E1BA-3C5D-A63D-DD480E0763D3", 155648),
        }),
    })
)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _contract(expected_arch: str) -> ArchContract:
    contract = ARCH_CONTRACTS.get(expected_arch)
    if contract is None:
        raise MacRemotionReceiptError(
            f"unsupported Mac Remotion architecture: {expected_arch}"
        )
    return contract


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise MacRemotionReceiptError(f"invalid SHA256 for {label}")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise MacRemotionReceiptError(f"{label} must be a positive integer")
    return value


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise MacRemotionReceiptError(
            f"{label} keys must be exactly: {', '.join(sorted(expected))}"
        )
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise MacRemotionReceiptError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _parse_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise MacRemotionReceiptError(f"{label} has an invalid byte count")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except MacRemotionReceiptError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MacRemotionReceiptError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise MacRemotionReceiptError(f"{label} root must be an object")
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
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode))


def _directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise MacRemotionReceiptError(
            "secure POSIX directory-handle APIs are unavailable"
        )
    return (
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _validate_names(names: list[str], label: str) -> None:
    logical: dict[str, str] = {}
    for name in names:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or "\x00" in name
            or unicodedata.normalize("NFC", name) != name
            or any(ord(character) < 32 or ord(character) == 127 for character in name)
        ):
            raise MacRemotionReceiptError(f"invalid path name in {label}: {name!r}")
        folded = name.casefold()
        prior = logical.get(folded)
        if prior is not None and prior != name:
            raise MacRemotionReceiptError(
                f"case-colliding path names in {label}: {prior}, {name}"
            )
        logical[folded] = name


def _safe_package_relative(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise MacRemotionReceiptError(f"{label} path must be a string")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or pure.as_posix() != value
        or len(pure.parts) != 1
        or value not in EXPECTED_FILES
        or unicodedata.normalize("NFC", value) != value
    ):
        raise MacRemotionReceiptError(f"invalid {label} path: {value!r}")
    return value


def _read_regular_path(
    path: Path,
    label: str,
    *,
    max_bytes: int,
) -> tuple[bytes, int, str]:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise MacRemotionReceiptError(
                f"{label} must be a regular file, not a symlink"
            )
        if before.st_nlink != 1 or before.st_size <= 0 or before.st_size > max_bytes:
            raise MacRemotionReceiptError(
                f"{label} must have one link and a valid byte count"
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise MacRemotionReceiptError(f"{label} changed while opening")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(READ_CHUNK_BYTES, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise MacRemotionReceiptError(f"{label} is too large")
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
        ):
            raise MacRemotionReceiptError(f"{label} changed while reading")
        raw = b"".join(chunks)
        if len(raw) != opened.st_size:
            raise MacRemotionReceiptError(f"{label} read was truncated")
        return raw, len(raw), hashlib.sha256(raw).hexdigest()
    except MacRemotionReceiptError:
        raise
    except OSError as exc:
        raise MacRemotionReceiptError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_regular_at(
    directory_fd: int,
    name: str,
    label: str,
) -> tuple[bytes, int]:
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise MacRemotionReceiptError(
                f"{label} must be a regular file, not a symlink"
            )
        if (
            before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > MAX_MEMBER_BYTES
        ):
            raise MacRemotionReceiptError(
                f"{label} must have one link and a valid byte count"
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise MacRemotionReceiptError(f"{label} changed while opening")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(READ_CHUNK_BYTES, MAX_MEMBER_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_MEMBER_BYTES:
                raise MacRemotionReceiptError(f"{label} is too large")
        after_handle = os.fstat(descriptor)
        after_name = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_name)
        ):
            raise MacRemotionReceiptError(f"{label} changed while reading")
        raw = b"".join(chunks)
        if len(raw) != opened.st_size:
            raise MacRemotionReceiptError(f"{label} read was truncated")
        return raw, stat.S_IMODE(opened.st_mode)
    except MacRemotionReceiptError:
        raise
    except OSError as exc:
        raise MacRemotionReceiptError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _held_package_directory(app_root: Path, arch: str) -> Iterator[int]:
    contract = _contract(arch)
    relative = PurePosixPath(PACKAGE_ROOT_PREFIX) / contract.package_name.split("/")[1]
    descriptors: list[int] = []
    opened_stats: list[os.stat_result] = []
    try:
        before_root = app_root.lstat()
        if stat.S_ISLNK(before_root.st_mode) or not stat.S_ISDIR(before_root.st_mode):
            raise MacRemotionReceiptError(
                "final app root must be a real directory, not a symlink"
            )
        root_fd = os.open(app_root, _directory_flags())
        descriptors.append(root_fd)
        opened_root = os.fstat(root_fd)
        if _directory_identity(before_root) != _directory_identity(opened_root):
            raise MacRemotionReceiptError("final app root changed while opening")
        opened_stats.append(opened_root)

        current_fd = root_fd
        for segment in relative.parts:
            names = os.listdir(current_fd)
            _validate_names(names, f"parent of {segment}")
            if segment not in names:
                raise MacRemotionReceiptError(
                    f"missing exact final package path segment: {segment}"
                )
            before = os.stat(segment, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise MacRemotionReceiptError(
                    f"final package path segment is not a real directory: {segment}"
                )
            child_fd = os.open(segment, _directory_flags(), dir_fd=current_fd)
            opened = os.fstat(child_fd)
            if _directory_identity(before) != _directory_identity(opened):
                os.close(child_fd)
                raise MacRemotionReceiptError(
                    f"final package path changed while opening: {segment}"
                )
            descriptors.append(child_fd)
            opened_stats.append(opened)
            current_fd = child_fd
        yield current_fd
        for descriptor, opened in zip(descriptors, opened_stats):
            if _directory_identity(os.fstat(descriptor)) != _directory_identity(opened):
                raise MacRemotionReceiptError(
                    "final package directory changed while scanning"
                )
        if _directory_identity(app_root.lstat()) != _directory_identity(opened_root):
            raise MacRemotionReceiptError("final app root changed while scanning")
    except MacRemotionReceiptError:
        raise
    except OSError as exc:
        raise MacRemotionReceiptError(
            f"cannot traverse final Remotion package: {exc}"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _round_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _parse_macho(
    raw: bytes,
    label: str,
    *,
    allow_stripped_signed_vmsize: bool = False,
    require_uuid: bool = True,
    allow_exact_vmsize: bool = False,
) -> MachMetadata:
    if len(raw) < 32:
        raise MacRemotionReceiptError(f"truncated Mach-O file: {label}")
    endian = MACHO_MAGICS.get(raw[:4])
    if endian is None:
        raise MacRemotionReceiptError(
            f"native Remotion file is not a thin 64-bit Mach-O: {label}"
        )
    cpu_type, _, file_type, command_count, command_bytes = struct.unpack_from(
        f"{endian}IIIII", raw, 4
    )
    architectures = {
        value: name for name, value in CPU_TYPES.items()
    }
    architecture = architectures.get(cpu_type)
    if architecture is None:
        raise MacRemotionReceiptError(f"unsupported Mach-O CPU type: {label}")
    kind = {
        MH_EXECUTE: "executable",
        MH_DYLIB: "dylib",
        MH_BUNDLE: "bundle",
    }.get(file_type)
    if kind is None:
        raise MacRemotionReceiptError(f"unsupported Mach-O kind: {label}")
    if (
        command_count <= 0
        or command_count > 65_535
        or command_bytes < command_count * 8
        or command_bytes > MAX_MACHO_COMMAND_BYTES
        or 32 + command_bytes > len(raw)
    ):
        raise MacRemotionReceiptError(f"invalid Mach-O command bounds: {label}")
    cursor = 32
    command_end = 32 + command_bytes
    uuids: list[str] = []
    code_signatures: list[tuple[int, int, int]] = []
    linkedit_segments: list[tuple[int, int, int, int, int]] = []
    for _ in range(command_count):
        if cursor + 8 > command_end:
            raise MacRemotionReceiptError(f"truncated Mach-O command: {label}")
        command, command_size = struct.unpack_from(f"{endian}II", raw, cursor)
        if command_size < 8 or command_size > command_end - cursor:
            raise MacRemotionReceiptError(f"invalid Mach-O command: {label}")
        if command == LC_UUID:
            if command_size != 24:
                raise MacRemotionReceiptError(f"invalid Mach-O UUID command: {label}")
            uuids.append(str(uuid.UUID(bytes=raw[cursor + 8:cursor + 24])).upper())
        elif command == LC_SEGMENT_64:
            if command_size < 72:
                raise MacRemotionReceiptError(
                    f"truncated Mach-O segment command: {label}"
                )
            segment_name = raw[cursor + 8:cursor + 24].split(b"\0", 1)[0]
            if segment_name == b"__LINKEDIT":
                vm_address, vm_size, file_offset, file_size = struct.unpack_from(
                    f"{endian}QQQQ", raw, cursor + 24
                )
                linkedit_segments.append((
                    vm_address,
                    vm_size,
                    file_offset,
                    file_size,
                    cursor + 32,
                ))
        elif command == LC_CODE_SIGNATURE:
            if command_size != 16:
                raise MacRemotionReceiptError(
                    f"invalid Mach-O code-signature command: {label}"
                )
            data_offset, data_size = struct.unpack_from(
                f"{endian}II", raw, cursor + 8
            )
            if (
                data_size <= 0
                or data_offset < command_end
                or data_offset > len(raw)
                or data_size > len(raw) - data_offset
            ):
                raise MacRemotionReceiptError(
                    f"invalid Mach-O code-signature bounds: {label}"
                )
            code_signatures.append((cursor, data_offset, data_size))
        cursor += command_size
    if (
        cursor != command_end
        or len(uuids) > 1
        or (require_uuid and len(uuids) != 1)
    ):
        raise MacRemotionReceiptError(
            f"Mach-O file must have exactly one UUID: {label}"
        )
    if len(code_signatures) > 1:
        raise MacRemotionReceiptError(
            f"Mach-O file has multiple code signatures: {label}"
        )
    if len(linkedit_segments) != 1:
        raise MacRemotionReceiptError(
            f"Mach-O file must have one terminal __LINKEDIT segment: {label}"
        )
    vm_address, vm_size, file_offset, file_size, vmsize_offset = (
        linkedit_segments[0]
    )
    if (
        file_size <= 0
        or file_offset < command_end
        or file_offset > len(raw)
        or file_size > len(raw) - file_offset
        or file_offset + file_size != len(raw)
        or vm_size < file_size
        or vm_size > file_size + MAX_MACHO_COMMAND_BYTES
    ):
        raise MacRemotionReceiptError(
            f"invalid terminal Mach-O __LINKEDIT bounds: {label}"
        )
    signature_offset: int | None = None
    signature_size: int | None = None
    signature_command_offset: int | None = None
    if code_signatures:
        signature_command_offset, signature_offset, signature_size = (
            code_signatures[0]
        )
        if signature_command_offset + 16 != command_end:
            raise MacRemotionReceiptError(
                f"Mach-O LC_CODE_SIGNATURE is not the terminal load command: {label}"
            )
        signed_vmsizes = {_round_up(file_size, 16 * 1024)}
        if allow_exact_vmsize:
            signed_vmsizes.update({file_size, _round_up(file_size, 4 * 1024)})
        if (
            signature_offset % 16
            or signature_offset < file_offset
            or signature_offset + signature_size != len(raw)
            or signature_offset + signature_size > file_offset + file_size
            or vm_size not in signed_vmsizes
        ):
            raise MacRemotionReceiptError(
                f"code signature is not the exact terminal __LINKEDIT suffix: {label}"
            )
    elif not allow_stripped_signed_vmsize:
        canonical_sizes = {
            _round_up(file_size, 4 * 1024),
            _round_up(file_size, 16 * 1024),
        }
        if allow_exact_vmsize:
            canonical_sizes.add(file_size)
        if vm_size not in canonical_sizes:
            raise MacRemotionReceiptError(
                f"unsigned Mach-O has noncanonical __LINKEDIT vmsize: {label}"
            )
    return MachMetadata(
        architecture=architecture,
        kind=kind,
        macho_uuid=uuids[0] if uuids else None,
        command_count=command_count,
        command_bytes=command_bytes,
        has_code_signature=bool(code_signatures),
        linkedit_vm_address=vm_address,
        linkedit_vm_size=vm_size,
        linkedit_file_offset=file_offset,
        linkedit_file_size=file_size,
        linkedit_vmsize_offset=vmsize_offset,
        code_signature_command_offset=signature_command_offset,
        code_signature_offset=signature_offset,
        code_signature_size=signature_size,
    )


def _canonicalize_signed_macho(
    raw: bytes,
    metadata: MachMetadata,
    label: str,
    expected_linkedit_vmsize: int | None = None,
    expected_normalized_bytes: int | None = None,
    *,
    require_uuid: bool = True,
    general_codesign_layout: bool = False,
) -> bytes:
    signature_command_offset = metadata.code_signature_command_offset
    signature_offset = metadata.code_signature_offset
    signature_size = metadata.code_signature_size
    if (
        signature_command_offset is None
        or signature_offset is None
        or signature_size is None
        or metadata.command_count <= 1
        or metadata.command_bytes < 16
        or signature_command_offset + 16 != 32 + metadata.command_bytes
        or signature_offset + signature_size != len(raw)
    ):
        raise MacRemotionReceiptError(
            f"signed Mach-O lacks exact terminal signature geometry: {label}"
        )

    canonical_end = signature_offset
    if expected_normalized_bytes is not None:
        if (
            type(expected_normalized_bytes) is not int
            or expected_normalized_bytes <= metadata.linkedit_file_offset
            or expected_normalized_bytes > signature_offset
            or _round_up(expected_normalized_bytes, 16) != signature_offset
        ):
            raise MacRemotionReceiptError(
                f"pinned unsigned Mach-O extent does not bind the signature: {label}"
            )
        if any(raw[expected_normalized_bytes:signature_offset]):
            raise MacRemotionReceiptError(
                f"non-zero code-signature alignment padding is forbidden: {label}"
            )
        canonical_end = expected_normalized_bytes

    canonical_linkedit_size = canonical_end - metadata.linkedit_file_offset
    canonical_sizes = {
        _round_up(canonical_linkedit_size, 4 * 1024),
        _round_up(canonical_linkedit_size, 16 * 1024),
    }
    if general_codesign_layout:
        canonical_sizes.add(canonical_linkedit_size)
    target_vmsize = expected_linkedit_vmsize
    if target_vmsize is None:
        if general_codesign_layout:
            target_vmsize = canonical_linkedit_size
        else:
            target_vmsize = (
                _round_up(canonical_linkedit_size, 16 * 1024)
                if metadata.architecture == "arm64"
                else min(canonical_sizes)
            )
    if target_vmsize not in canonical_sizes:
        raise MacRemotionReceiptError(
            f"source __LINKEDIT vmsize is not canonical for {label}"
        )

    endian = MACHO_MAGICS[raw[:4]]
    normalized_buffer = bytearray(raw[:canonical_end])
    struct.pack_into(
        f"{endian}II",
        normalized_buffer,
        16,
        metadata.command_count - 1,
        metadata.command_bytes - 16,
    )
    normalized_buffer[
        signature_command_offset:signature_command_offset + 16
    ] = b"\0" * 16
    struct.pack_into(
        f"{endian}Q",
        normalized_buffer,
        metadata.linkedit_vmsize_offset,
        target_vmsize,
    )
    struct.pack_into(
        f"{endian}Q",
        normalized_buffer,
        metadata.linkedit_vmsize_offset + 16,
        canonical_linkedit_size,
    )
    normalized = bytes(normalized_buffer)
    normalized_metadata = _parse_macho(
        normalized,
        f"normalized {label}",
        require_uuid=require_uuid,
        allow_exact_vmsize=general_codesign_layout,
    )
    if (
        normalized_metadata.architecture != metadata.architecture
        or normalized_metadata.kind != metadata.kind
        or normalized_metadata.macho_uuid != metadata.macho_uuid
        or normalized_metadata.command_count != metadata.command_count - 1
        or normalized_metadata.command_bytes != metadata.command_bytes - 16
        or normalized_metadata.has_code_signature
        or normalized_metadata.linkedit_vm_address != metadata.linkedit_vm_address
        or normalized_metadata.linkedit_vm_size != target_vmsize
        or normalized_metadata.linkedit_file_offset != metadata.linkedit_file_offset
        or normalized_metadata.linkedit_file_size != canonical_linkedit_size
    ):
        raise MacRemotionReceiptError(
            f"code-signature normalization changed Mach-O identity: {label}"
        )
    return normalized


def _normalize_macho_bytes(
    raw: bytes,
    label: str,
    expected_linkedit_vmsize: int | None = None,
    *,
    expected_normalized_bytes: int | None = None,
    max_bytes: int = MAX_MEMBER_BYTES,
    require_uuid: bool = True,
    general_codesign_layout: bool = False,
) -> bytes:
    if len(raw) <= 0 or len(raw) > max_bytes:
        raise MacRemotionReceiptError(
            f"invalid byte count for Mach-O normalization: {label}"
        )
    metadata = _parse_macho(
        raw,
        label,
        require_uuid=require_uuid,
        allow_exact_vmsize=general_codesign_layout,
    )
    if not metadata.has_code_signature:
        if general_codesign_layout:
            normalized_buffer = bytearray(raw)
            struct.pack_into(
                f"{MACHO_MAGICS[raw[:4]]}Q",
                normalized_buffer,
                metadata.linkedit_vmsize_offset,
                metadata.linkedit_file_size,
            )
            normalized = bytes(normalized_buffer)
            _parse_macho(
                normalized,
                f"normalized unsigned {label}",
                require_uuid=require_uuid,
                allow_exact_vmsize=True,
            )
            return normalized
        if (
            expected_linkedit_vmsize is not None
            and metadata.linkedit_vm_size != expected_linkedit_vmsize
        ):
            raise MacRemotionReceiptError(
                f"unsigned Mach-O __LINKEDIT vmsize differs from source: {label}"
            )
        return raw
    codesign = Path(CODESIGN_PATH)
    try:
        tool_stat = codesign.lstat()
    except OSError as exc:
        raise MacRemotionReceiptError(
            f"cannot inspect exact codesign tool {CODESIGN_PATH}: {exc}"
        ) from exc
    if stat.S_ISLNK(tool_stat.st_mode) or not stat.S_ISREG(tool_stat.st_mode):
        raise MacRemotionReceiptError(
            f"exact codesign tool is not a regular file: {CODESIGN_PATH}"
        )
    with tempfile.TemporaryDirectory(
        prefix="autoeditor-remotion-normalize-", dir="/private/tmp"
    ) as temp:
        directory = Path(temp)
        temporary = directory / "native"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o700,
        )
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise MacRemotionReceiptError(
                        f"short temporary Mach-O write: {label}"
                    )
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            verified = subprocess.run(
                [CODESIGN_PATH, "--verify", "--strict", str(temporary)],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            )
            if verified.returncode != 0:
                detail = (verified.stderr or verified.stdout).strip()
                raise MacRemotionReceiptError(
                    f"strict codesign verification failed for {label}: {detail}"
                )
        except MacRemotionReceiptError:
            raise
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MacRemotionReceiptError(
                f"cannot verify Mach-O code signature for {label}: {exc}"
            ) from exc
    return _canonicalize_signed_macho(
        raw,
        metadata,
        label,
        expected_linkedit_vmsize,
        expected_normalized_bytes,
        require_uuid=require_uuid,
        general_codesign_layout=general_codesign_layout,
    )


def _validate_file_mode(path: str, mode: int, label: str) -> None:
    if type(mode) is not int or mode < 0 or mode > 0o777:
        raise MacRemotionReceiptError(f"invalid file mode for {label}: {path}")
    if mode & 0o002:
        raise MacRemotionReceiptError(
            f"world-writable file mode is forbidden for {label}: {path}"
        )
    if path in NATIVE_FILES and mode & 0o111 != 0o111:
        raise MacRemotionReceiptError(
            f"native file is not executable for {label}: {path}"
        )
    if path in DATA_FILES and mode & 0o111:
        raise MacRemotionReceiptError(
            f"data file is unexpectedly executable for {label}: {path}"
        )


def _observe_bytes(path: str, raw: bytes, mode: int, arch: str) -> FileObservation:
    if len(raw) <= 0 or len(raw) > MAX_MEMBER_BYTES:
        raise MacRemotionReceiptError(f"invalid byte count for package file: {path}")
    _validate_file_mode(path, mode, "Remotion package")
    digest = hashlib.sha256(raw).hexdigest()
    if path not in NATIVE_FILES:
        return FileObservation(path, len(raw), digest, mode, raw)
    metadata = _parse_macho(raw, path)
    expected_kind = "executable" if path in EXECUTABLE_FILES else "dylib"
    if metadata.architecture != arch or metadata.kind != expected_kind:
        raise MacRemotionReceiptError(
            f"Mach-O architecture or kind drift for package file: {path}"
        )
    pin = PINNED_SOURCE_FILES[arch].get(path)
    expected_vmsize = (
        pin.normalized_linkedit_vmsize if pin is not None else None
    )
    expected_normalized_bytes = pin.normalized_bytes if pin is not None else None
    normalized = _normalize_macho_bytes(
        raw,
        path,
        expected_vmsize,
        expected_normalized_bytes=expected_normalized_bytes,
    )
    normalized_metadata = _parse_macho(normalized, f"normalized {path}")
    return FileObservation(
        path=path,
        byte_count=len(raw),
        sha256=digest,
        mode=mode,
        raw=raw,
        architecture=metadata.architecture,
        kind=metadata.kind,
        macho_uuid=metadata.macho_uuid,
        normalized_bytes=len(normalized),
        normalized_sha256=hashlib.sha256(normalized).hexdigest(),
        normalized_linkedit_vmsize=normalized_metadata.linkedit_vm_size,
    )


def _read_source_tarball(tarball: Path, arch: str) -> dict[str, FileObservation]:
    contract = _contract(arch)
    raw, byte_count, digest = _read_regular_path(
        tarball, "Remotion npm tarball", max_bytes=MAX_TARBALL_BYTES
    )
    if byte_count != contract.tarball_bytes or digest != contract.tarball_sha256:
        raise MacRemotionReceiptError(
            "Remotion npm tarball does not match the pinned byte count and SHA256"
        )
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            members = archive.getmembers()
            member_names = [member.name for member in members]
            expected_names = {f"package/{name}" for name in EXPECTED_FILES}
            if len(member_names) != len(set(member_names)):
                raise MacRemotionReceiptError(
                    "Remotion npm tarball has duplicate member paths"
                )
            if set(member_names) != expected_names:
                missing = sorted(expected_names - set(member_names))
                extra = sorted(set(member_names) - expected_names)
                detail = []
                if missing:
                    detail.append("missing " + ", ".join(missing))
                if extra:
                    detail.append("extra " + ", ".join(extra))
                raise MacRemotionReceiptError(
                    "Remotion npm tarball inventory drifted (" + "; ".join(detail) + ")"
                )
            relative_names = [name.removeprefix("package/") for name in member_names]
            _validate_names(relative_names, "Remotion npm tarball")
            observations: dict[str, FileObservation] = {}
            total = 0
            for member in members:
                pure = PurePosixPath(member.name)
                if (
                    pure.is_absolute()
                    or pure.as_posix() != member.name
                    or len(pure.parts) != 2
                    or pure.parts[0] != "package"
                ):
                    raise MacRemotionReceiptError(
                        f"invalid Remotion npm tarball path: {member.name!r}"
                    )
                relative = _safe_package_relative(pure.parts[1], "tarball member")
                if not member.isreg() or member.linkname:
                    raise MacRemotionReceiptError(
                        f"Remotion npm tarball member is not a regular file: {member.name}"
                    )
                if member.size <= 0 or member.size > MAX_MEMBER_BYTES:
                    raise MacRemotionReceiptError(
                        f"invalid Remotion npm tarball member size: {member.name}"
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise MacRemotionReceiptError(
                        f"cannot read Remotion npm tarball member: {member.name}"
                    )
                member_raw = extracted.read(member.size + 1)
                if len(member_raw) != member.size:
                    raise MacRemotionReceiptError(
                        f"truncated Remotion npm tarball member: {member.name}"
                    )
                total += len(member_raw)
                if total > MAX_PACKAGE_BYTES:
                    raise MacRemotionReceiptError("Remotion npm package is too large")
                observations[relative] = _observe_bytes(
                    relative, member_raw, member.mode & 0o777, arch
                )
    except MacRemotionReceiptError:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise MacRemotionReceiptError(
            f"cannot decode pinned Remotion npm tarball: {exc}"
        ) from exc
    _validate_source_observations(observations, arch)
    return observations


def _validate_source_observations(
    observations: Mapping[str, FileObservation], arch: str
) -> None:
    pins = PINNED_SOURCE_FILES[arch]
    if set(observations) != set(EXPECTED_FILES) or set(pins) != set(EXPECTED_FILES):
        raise MacRemotionReceiptError("pinned Remotion source inventory is incomplete")
    for path in sorted(EXPECTED_FILES):
        observed = observations[path]
        pin = pins[path]
        if (
            observed.byte_count != pin.byte_count
            or observed.sha256 != pin.sha256
            or observed.mode != pin.mode
            or observed.kind != pin.kind
        ):
            raise MacRemotionReceiptError(
                f"pinned Remotion source file drifted: {path}"
            )
        if path in NATIVE_FILES and (
            observed.architecture != arch
            or observed.normalized_bytes != pin.normalized_bytes
            or observed.normalized_sha256 != pin.normalized_sha256
            or observed.macho_uuid != pin.macho_uuid
            or observed.normalized_linkedit_vmsize
            != pin.normalized_linkedit_vmsize
        ):
            raise MacRemotionReceiptError(
                f"pinned Remotion native source identity drifted: {path}"
            )


def _scan_final_package(app_root: Path, arch: str) -> dict[str, FileObservation]:
    observations: dict[str, FileObservation] = {}
    with _held_package_directory(app_root, arch) as package_fd:
        before_names = os.listdir(package_fd)
        _validate_names(before_names, "final Remotion package")
        if len(before_names) != len(set(before_names)) or set(before_names) != EXPECTED_FILES:
            missing = sorted(EXPECTED_FILES - set(before_names))
            extra = sorted(set(before_names) - EXPECTED_FILES)
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("extra " + ", ".join(extra))
            raise MacRemotionReceiptError(
                "final Remotion package inventory drifted (" + "; ".join(detail) + ")"
            )
        total = 0
        for name in sorted(EXPECTED_FILES):
            raw, mode = _read_regular_at(package_fd, name, f"final Remotion file {name}")
            total += len(raw)
            if total > MAX_PACKAGE_BYTES:
                raise MacRemotionReceiptError("final Remotion package is too large")
            observations[name] = _observe_bytes(name, raw, mode, arch)
        after_names = os.listdir(package_fd)
        _validate_names(after_names, "final Remotion package")
        if before_names != after_names:
            raise MacRemotionReceiptError(
                "final Remotion package changed while scanning"
            )
    return observations


def _validate_lockfile(
    package_lock: Path,
    expected_sha256: str,
    arch: str,
) -> tuple[bytes, str]:
    contract = _contract(arch)
    expected = _sha256(expected_sha256, "package-lock input")
    raw, _, actual = _read_regular_path(
        package_lock, "creative-runtime package-lock", max_bytes=MAX_JSON_BYTES
    )
    if actual != expected:
        raise MacRemotionReceiptError(
            "creative-runtime package-lock raw SHA256 differs from the authenticated input"
        )
    payload = _parse_json_bytes(raw, "creative-runtime package-lock")
    packages = payload.get("packages")
    if not isinstance(packages, dict):
        raise MacRemotionReceiptError("package-lock packages must be an object")
    entry = _exact_keys(
        packages.get(contract.lock_key),
        {"cpu", "integrity", "optional", "os", "resolved", "version"},
        f"package-lock entry {contract.lock_key}",
    )
    expected_entry = {
        "cpu": [arch],
        "integrity": contract.integrity,
        "optional": True,
        "os": ["darwin"],
        "resolved": contract.resolved,
        "version": VERSION,
    }
    if entry != expected_entry:
        raise MacRemotionReceiptError(
            f"package-lock entry is not the exact pinned {contract.package_name}@{VERSION} record"
        )
    renderer = packages.get("node_modules/@remotion/renderer")
    if not isinstance(renderer, dict):
        raise MacRemotionReceiptError(
            "package-lock lacks @remotion/renderer dependency metadata"
        )
    optional = renderer.get("optionalDependencies")
    if not isinstance(optional, dict) or optional.get(contract.package_name) != VERSION:
        raise MacRemotionReceiptError(
            "package-lock renderer does not bind the pinned macOS package"
        )
    return raw, actual


def _source_file_object(observation: FileObservation) -> dict[str, Any]:
    base: dict[str, Any] = {
        "bytes": observation.byte_count,
        "kind": observation.kind,
        "mode": format(observation.mode, "04o"),
        "sha256": observation.sha256,
    }
    if observation.path in NATIVE_FILES:
        base.update({
            "architecture": observation.architecture,
            "macho_uuid": observation.macho_uuid,
            "normalized_bytes": observation.normalized_bytes,
            "normalized_linkedit_vmsize": (
                observation.normalized_linkedit_vmsize
            ),
            "normalized_sha256": observation.normalized_sha256,
        })
    return base


def _source_manifest(
    lock_raw: bytes,
    lock_sha256: str,
    source_files: Mapping[str, FileObservation],
    arch: str,
) -> dict[str, Any]:
    contract = _contract(arch)
    files = {
        path: _source_file_object(source_files[path])
        for path in sorted(EXPECTED_FILES)
    }
    return {
        "files": files,
        "inventory": {
            "file_count": len(files),
            "native_file_count": len(NATIVE_FILES),
            "sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
            "total_bytes": sum(entry["bytes"] for entry in files.values()),
        },
        "package": {
            "integrity": contract.integrity,
            "name": contract.package_name,
            "resolved": contract.resolved,
            "tarball_bytes": contract.tarball_bytes,
            "tarball_sha256": contract.tarball_sha256,
            "version": VERSION,
        },
        "package_lock": {
            "bytes": len(lock_raw),
            "path": LOCKFILE_LOGICAL_PATH,
            "sha256": lock_sha256,
        },
        "schema": SOURCE_MANIFEST_SCHEMA,
    }


def _assert_final_matches_source(
    final_files: Mapping[str, FileObservation],
    source_files: Mapping[str, FileObservation],
) -> None:
    if set(final_files) != set(source_files) or set(final_files) != EXPECTED_FILES:
        raise MacRemotionReceiptError(
            "final and source Remotion inventories do not match"
        )
    for path in sorted(EXPECTED_FILES):
        final = final_files[path]
        source = source_files[path]
        if final.mode != source.mode:
            raise MacRemotionReceiptError(
                f"final Remotion file mode differs from npm source: {path}"
            )
        if path in DATA_FILES:
            if final.byte_count != source.byte_count or final.sha256 != source.sha256:
                raise MacRemotionReceiptError(
                    f"final Remotion data file differs from npm source: {path}"
                )
            continue
        if (
            final.architecture != source.architecture
            or final.kind != source.kind
            or final.macho_uuid != source.macho_uuid
            or final.normalized_bytes != source.normalized_bytes
            or final.normalized_sha256 != source.normalized_sha256
        ):
            raise MacRemotionReceiptError(
                f"final Remotion Mach-O differs beyond its code signature: {path}"
            )


def _final_file_object(
    final: FileObservation,
    source: FileObservation,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "bytes": final.byte_count,
        "kind": final.kind,
        "mode": format(final.mode, "04o"),
        "package_path": final.path,
        "sha256": final.sha256,
        "source_bytes": source.byte_count,
        "source_mode": format(source.mode, "04o"),
        "source_sha256": source.sha256,
    }
    if final.path in NATIVE_FILES:
        base.update({
            "architecture": final.architecture,
            "macho_uuid": final.macho_uuid,
            "normalized_bytes": final.normalized_bytes,
            "normalized_linkedit_vmsize": (
                final.normalized_linkedit_vmsize
            ),
            "normalized_sha256": final.normalized_sha256,
            "source_normalized_bytes": source.normalized_bytes,
            "source_normalized_linkedit_vmsize": (
                source.normalized_linkedit_vmsize
            ),
            "source_normalized_sha256": source.normalized_sha256,
        })
    return base


def _final_app_path(package_path: str, arch: str) -> str:
    contract = _contract(arch)
    return f"{PACKAGE_ROOT_PREFIX}/{contract.package_name.split('/')[1]}/{package_path}"


def generate_receipt(
    app_root: Path,
    package_lock: Path,
    expected_package_lock_sha256: str,
    tarball: Path,
    expected_arch: str,
) -> tuple[dict[str, Any], bytes]:
    """Generate canonical receipt bytes from pinned source and the final app."""
    arch = _contract(expected_arch).architecture
    lock_raw, lock_sha = _validate_lockfile(
        package_lock, expected_package_lock_sha256, arch
    )
    source_files = _read_source_tarball(tarball, arch)
    final_files = _scan_final_package(app_root, arch)
    _assert_final_matches_source(final_files, source_files)

    lock_raw_after, lock_sha_after = _validate_lockfile(
        package_lock, expected_package_lock_sha256, arch
    )
    source_files_after = _read_source_tarball(tarball, arch)
    final_files_after = _scan_final_package(app_root, arch)
    if (
        lock_raw_after != lock_raw
        or lock_sha_after != lock_sha
        or source_files_after != source_files
        or final_files_after != final_files
    ):
        raise MacRemotionReceiptError(
            "Mac Remotion producer inputs changed while generating the receipt"
        )

    source_manifest = _source_manifest(lock_raw, lock_sha, source_files, arch)
    source_manifest_sha = hashlib.sha256(
        canonical_json_bytes(source_manifest)
    ).hexdigest()
    files = {
        _final_app_path(path, arch): _final_file_object(
            final_files[path], source_files[path]
        )
        for path in sorted(EXPECTED_FILES)
    }
    contract = _contract(arch)
    payload = {
        "component": COMPONENT,
        "files": files,
        "lineage_id": contract.lineage_id,
        "package_inventory": {
            "file_count": len(files),
            "native_file_count": len(NATIVE_FILES),
            "sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
            "total_bytes": sum(entry["bytes"] for entry in files.values()),
        },
        "package_root": (
            f"{PACKAGE_ROOT_PREFIX}/{contract.package_name.split('/')[1]}"
        ),
        "platform": contract.platform,
        "schema": SCHEMA,
        "source_manifest": source_manifest,
        "source_manifest_sha256": source_manifest_sha,
    }
    raw = canonical_json_bytes(payload)
    validate_receipt(payload, raw, arch)
    return payload, raw


def _validate_inventory(
    inventory: Any,
    files: Mapping[str, Any],
    label: str,
) -> None:
    value = _exact_keys(
        inventory,
        {"file_count", "native_file_count", "sha256", "total_bytes"},
        label,
    )
    if _positive_int(value["file_count"], f"{label} file count") != len(files):
        raise MacRemotionReceiptError(f"{label} file count drifted")
    if (
        _positive_int(value["native_file_count"], f"{label} native file count")
        != len(NATIVE_FILES)
    ):
        raise MacRemotionReceiptError(f"{label} native file count drifted")
    total = sum(_positive_int(item["bytes"], f"{label} file bytes") for item in files.values())
    if _positive_int(value["total_bytes"], f"{label} total bytes") != total:
        raise MacRemotionReceiptError(f"{label} total bytes drifted")
    expected_digest = hashlib.sha256(canonical_json_bytes(files)).hexdigest()
    if _sha256(value["sha256"], label) != expected_digest:
        raise MacRemotionReceiptError(f"{label} digest drifted")


def _validate_source_manifest(value: Any, arch: str) -> dict[str, Any]:
    contract = _contract(arch)
    manifest = _exact_keys(
        value,
        {"files", "inventory", "package", "package_lock", "schema"},
        "Remotion source manifest",
    )
    if manifest["schema"] != SOURCE_MANIFEST_SCHEMA:
        raise MacRemotionReceiptError("Remotion source manifest has wrong schema")
    package = _exact_keys(
        manifest["package"],
        {"integrity", "name", "resolved", "tarball_bytes", "tarball_sha256", "version"},
        "Remotion source package",
    )
    expected_package = {
        "integrity": contract.integrity,
        "name": contract.package_name,
        "resolved": contract.resolved,
        "tarball_bytes": contract.tarball_bytes,
        "tarball_sha256": contract.tarball_sha256,
        "version": VERSION,
    }
    if package != expected_package:
        raise MacRemotionReceiptError("Remotion source package pins drifted")
    lock = _exact_keys(
        manifest["package_lock"], {"bytes", "path", "sha256"},
        "Remotion source package-lock",
    )
    if lock["path"] != LOCKFILE_LOGICAL_PATH:
        raise MacRemotionReceiptError("Remotion source package-lock path drifted")
    _positive_int(lock["bytes"], "Remotion source package-lock bytes")
    _sha256(lock["sha256"], "Remotion source package-lock")

    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != EXPECTED_FILES:
        raise MacRemotionReceiptError("Remotion source manifest paths drifted")
    pins = PINNED_SOURCE_FILES[arch]
    for path in sorted(EXPECTED_FILES):
        pin = pins[path]
        entry = files[path]
        expected_keys = {"bytes", "kind", "mode", "sha256"}
        if path in NATIVE_FILES:
            expected_keys |= {
                "architecture", "macho_uuid", "normalized_bytes",
                "normalized_linkedit_vmsize", "normalized_sha256",
            }
        entry = _exact_keys(entry, expected_keys, f"Remotion source file {path}")
        if (
            entry["bytes"] != pin.byte_count
            or entry["sha256"] != pin.sha256
            or entry["mode"] != format(pin.mode, "04o")
            or entry["kind"] != pin.kind
        ):
            raise MacRemotionReceiptError(f"Remotion source file pin drifted: {path}")
        if path in NATIVE_FILES and (
            entry["architecture"] != arch
            or entry["macho_uuid"] != pin.macho_uuid
            or entry["normalized_bytes"] != pin.normalized_bytes
            or entry["normalized_sha256"] != pin.normalized_sha256
            or entry["normalized_linkedit_vmsize"]
            != pin.normalized_linkedit_vmsize
        ):
            raise MacRemotionReceiptError(
                f"Remotion source native identity drifted: {path}"
            )
    _validate_inventory(manifest["inventory"], files, "source inventory")
    return manifest


def validate_receipt(
    payload: Mapping[str, Any],
    raw: bytes,
    expected_arch: str,
) -> dict[str, Any]:
    """Validate canonical structure and every exact per-path producer claim."""
    arch = _contract(expected_arch).architecture
    parsed = _parse_json_bytes(raw, "Mac Remotion producer receipt")
    if not isinstance(payload, Mapping) or dict(payload) != parsed:
        raise MacRemotionReceiptError(
            "Mac Remotion receipt payload differs from its raw JSON"
        )
    if canonical_json_bytes(parsed) != raw:
        raise MacRemotionReceiptError(
            "Mac Remotion producer receipt is not canonical JSON"
        )
    root = _exact_keys(
        parsed,
        {
            "component", "files", "lineage_id", "package_inventory",
            "package_root", "platform", "schema", "source_manifest",
            "source_manifest_sha256",
        },
        "Mac Remotion producer receipt",
    )
    contract = _contract(arch)
    expected_root = f"{PACKAGE_ROOT_PREFIX}/{contract.package_name.split('/')[1]}"
    if (
        root["schema"] != SCHEMA
        or root["component"] != COMPONENT
        or root["platform"] != contract.platform
        or root["lineage_id"] != contract.lineage_id
        or root["package_root"] != expected_root
    ):
        raise MacRemotionReceiptError("Mac Remotion receipt identity drifted")
    source_manifest = _validate_source_manifest(root["source_manifest"], arch)
    source_digest = hashlib.sha256(canonical_json_bytes(source_manifest)).hexdigest()
    if _sha256(root["source_manifest_sha256"], "source manifest") != source_digest:
        raise MacRemotionReceiptError("Mac Remotion source manifest digest drifted")

    files = root["files"]
    expected_paths = {_final_app_path(path, arch) for path in EXPECTED_FILES}
    if not isinstance(files, dict) or set(files) != expected_paths:
        raise MacRemotionReceiptError("Mac Remotion final receipt paths drifted")
    for relative in sorted(EXPECTED_FILES):
        final_path = _final_app_path(relative, arch)
        source = source_manifest["files"][relative]
        expected_keys = {
            "bytes", "kind", "mode", "package_path", "sha256",
            "source_bytes", "source_mode", "source_sha256",
        }
        if relative in NATIVE_FILES:
            expected_keys |= {
                "architecture", "macho_uuid", "normalized_bytes",
                "normalized_linkedit_vmsize", "normalized_sha256",
                "source_normalized_bytes",
                "source_normalized_linkedit_vmsize",
                "source_normalized_sha256",
            }
        entry = _exact_keys(files[final_path], expected_keys, f"final claim {final_path}")
        if (
            entry["package_path"] != relative
            or entry["kind"] != source["kind"]
            or entry["mode"] != source["mode"]
            or entry["source_mode"] != source["mode"]
        ):
            raise MacRemotionReceiptError(f"Mac Remotion final path metadata drifted: {final_path}")
        _positive_int(entry["bytes"], f"final byte count {final_path}")
        _sha256(entry["sha256"], f"final file {final_path}")
        if entry["source_bytes"] != source["bytes"] or entry["source_sha256"] != source["sha256"]:
            raise MacRemotionReceiptError(f"Mac Remotion source binding drifted: {final_path}")
        if relative in DATA_FILES:
            if entry["bytes"] != source["bytes"] or entry["sha256"] != source["sha256"]:
                raise MacRemotionReceiptError(f"Mac Remotion data claim differs from source: {final_path}")
        else:
            if (
                entry["architecture"] != arch
                or entry["macho_uuid"] != source["macho_uuid"]
                or entry["normalized_bytes"] != source["normalized_bytes"]
                or entry["normalized_linkedit_vmsize"]
                != source["normalized_linkedit_vmsize"]
                or entry["normalized_sha256"] != source["normalized_sha256"]
                or entry["source_normalized_bytes"] != source["normalized_bytes"]
                or entry["source_normalized_linkedit_vmsize"]
                != source["normalized_linkedit_vmsize"]
                or entry["source_normalized_sha256"] != source["normalized_sha256"]
            ):
                raise MacRemotionReceiptError(f"Mac Remotion normalized claim drifted: {final_path}")
    _validate_inventory(root["package_inventory"], files, "final package inventory")
    return parsed


def claims_from_receipt(
    payload: Mapping[str, Any],
    raw: bytes,
    expected_arch: str,
) -> Mapping[str, FileClaim]:
    """Return exact app-relative native claims for allowlist generation."""
    arch = _contract(expected_arch).architecture
    validated = validate_receipt(payload, raw, arch)
    lineage = validated["lineage_id"]
    source_manifest_sha = validated["source_manifest_sha256"]
    claims: dict[str, FileClaim] = {}
    for relative in sorted(NATIVE_FILES):
        path = _final_app_path(relative, arch)
        entry = validated["files"][path]
        claims[path] = FileClaim(
            path=path,
            bytes=entry["bytes"],
            sha256=entry["sha256"],
            architecture=entry["architecture"],
            kind=entry["kind"],
            lineage_id=lineage,
            source_manifest_sha256=source_manifest_sha,
            source_path=entry["package_path"],
            source_bytes=entry["source_bytes"],
            source_sha256=entry["source_sha256"],
            normalized_bytes=entry["normalized_bytes"],
            normalized_sha256=entry["normalized_sha256"],
            normalized_linkedit_vmsize=(
                entry["normalized_linkedit_vmsize"]
            ),
            mode=entry["mode"],
        )
    return MappingProxyType(claims)


def verify_app(
    app_root: Path,
    payload: Mapping[str, Any],
    raw: bytes,
    expected_arch: str,
) -> Mapping[str, FileClaim]:
    """Verify the final installed package against a canonical receipt."""
    arch = _contract(expected_arch).architecture
    validated = validate_receipt(payload, raw, arch)
    first = _scan_final_package(app_root, arch)
    second = _scan_final_package(app_root, arch)
    if first != second:
        raise MacRemotionReceiptError(
            "final Remotion package changed during receipt verification"
        )
    source_files = validated["source_manifest"]["files"]
    for relative in sorted(EXPECTED_FILES):
        observation = first[relative]
        expected = validated["files"][_final_app_path(relative, arch)]
        if relative in DATA_FILES:
            actual = {
                "bytes": observation.byte_count,
                "kind": observation.kind,
                "mode": format(observation.mode, "04o"),
                "package_path": relative,
                "sha256": observation.sha256,
                "source_bytes": source_files[relative]["bytes"],
                "source_mode": source_files[relative]["mode"],
                "source_sha256": source_files[relative]["sha256"],
            }
        else:
            actual = {
                "architecture": observation.architecture,
                "bytes": observation.byte_count,
                "kind": observation.kind,
                "macho_uuid": observation.macho_uuid,
                "mode": format(observation.mode, "04o"),
                "normalized_bytes": observation.normalized_bytes,
                "normalized_linkedit_vmsize": (
                    observation.normalized_linkedit_vmsize
                ),
                "normalized_sha256": observation.normalized_sha256,
                "package_path": relative,
                "sha256": observation.sha256,
                "source_bytes": source_files[relative]["bytes"],
                "source_mode": source_files[relative]["mode"],
                "source_normalized_bytes": source_files[relative]["normalized_bytes"],
                "source_normalized_linkedit_vmsize": (
                    source_files[relative]["normalized_linkedit_vmsize"]
                ),
                "source_normalized_sha256": source_files[relative]["normalized_sha256"],
                "source_sha256": source_files[relative]["sha256"],
            }
        if actual != expected:
            raise MacRemotionReceiptError(
                f"final Remotion package differs from receipt: {relative}"
            )
    return claims_from_receipt(validated, raw, arch)


def load_authenticated_receipt(
    path: Path,
    expected_sha256: str,
    expected_arch: str,
) -> tuple[dict[str, Any], bytes]:
    expected = _sha256(expected_sha256, "Mac Remotion receipt input")
    raw, _, actual = _read_regular_path(
        path, "Mac Remotion producer receipt", max_bytes=MAX_JSON_BYTES
    )
    if actual != expected:
        raise MacRemotionReceiptError(
            "Mac Remotion receipt raw SHA256 differs from the authenticated input"
        )
    payload = _parse_json_bytes(raw, "Mac Remotion producer receipt")
    return validate_receipt(payload, raw, expected_arch), raw


@contextmanager
def _held_writable_directory(path: Path) -> Iterator[int]:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise MacRemotionReceiptError(
                "receipt output parent must be a real directory"
            )
        descriptor = os.open(path, _directory_flags())
        opened = os.fstat(descriptor)
        if _directory_object_identity(before) != _directory_object_identity(opened):
            raise MacRemotionReceiptError(
                "receipt output directory changed while opening"
            )
        yield descriptor
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _directory_object_identity(after_handle)
            != _directory_object_identity(opened)
            or _directory_object_identity(after_path)
            != _directory_object_identity(opened)
        ):
            raise MacRemotionReceiptError(
                "receipt output directory changed while writing"
            )
    except MacRemotionReceiptError:
        raise
    except OSError as exc:
        raise MacRemotionReceiptError(
            f"cannot open receipt output directory: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def write_new_receipt(path: Path, raw: bytes) -> None:
    payload = _parse_json_bytes(raw, "Mac Remotion producer receipt")
    platform = payload.get("platform")
    arch = next(
        (name for name, candidate in PLATFORMS.items() if candidate == platform),
        None,
    )
    if arch is None:
        raise MacRemotionReceiptError("Mac Remotion receipt has unsupported platform")
    validate_receipt(payload, raw, arch)
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_names([path.name], "receipt output")
    with _held_writable_directory(path.parent) as parent_fd:
        descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path.name, flags, 0o644, dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise MacRemotionReceiptError("short Mac Remotion receipt write")
                view = view[written:]
            os.fsync(descriptor)
            final = os.fstat(descriptor)
            linked = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(final.st_mode)
                or final.st_nlink != 1
                or final.st_size != len(raw)
                or _stat_identity(final) != _stat_identity(linked)
                or _stat_identity(opened)[:4] != _stat_identity(final)[:4]
            ):
                raise MacRemotionReceiptError("invalid written Mac Remotion receipt")
        except MacRemotionReceiptError:
            raise
        except OSError as exc:
            raise MacRemotionReceiptError(
                f"cannot create Mac Remotion receipt: {exc}"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--app-root", type=Path, required=True)
    generate.add_argument("--package-lock", type=Path, required=True)
    generate.add_argument("--package-lock-sha256", required=True)
    generate.add_argument("--tarball", type=Path, required=True)
    generate.add_argument("--expected-arch", choices=sorted(ARCH_CONTRACTS), required=True)
    generate.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--app-root", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--receipt-sha256", required=True)
    verify.add_argument("--expected-arch", choices=sorted(ARCH_CONTRACTS), required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "generate":
            _, raw = generate_receipt(
                args.app_root,
                args.package_lock,
                args.package_lock_sha256,
                args.tarball,
                args.expected_arch,
            )
            write_new_receipt(args.output, raw)
            print(hashlib.sha256(raw).hexdigest())
        else:
            payload, raw = load_authenticated_receipt(
                args.receipt, args.receipt_sha256, args.expected_arch
            )
            verify_app(args.app_root, payload, raw, args.expected_arch)
            print(args.receipt_sha256)
    except MacRemotionReceiptError as exc:
        print(f"macOS Remotion receipt error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
