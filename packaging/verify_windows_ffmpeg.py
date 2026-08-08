#!/usr/bin/env python3
"""Validate the pinned Windows FFmpeg build, receipt, and source linkage."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit


SOURCE_LOCK_SCHEMA = "autoeditor-windows-ffmpeg-sources/v2"
CAPABILITIES_SCHEMA = "autoeditor-windows-ffmpeg-capabilities/v1"
RECEIPT_SCHEMA = "autoeditor-windows-ffmpeg-build/v3"
BUNDLE_LOCK_SCHEMA = "autoeditor-native-media-sources/v1"
EXPECTED_SOURCE_LOCK_SHA256 = (
    "e0aa5a65142d0d9c70fe6cdad7e147662b038f1f6a39d733c64c1a1d25407cd8"
)
EXPECTED_CAPABILITIES_SHA256 = (
    "dc070e461ab436c0ebe0e9b18ecabcc32f84a2086bf91565001267f925195f0e"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
SAFE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*\Z")
MOVING_REF_RE = re.compile(
    r"(?:^|[/?#&=._-])(?:latest|nightly|snapshot|main|master|head|trunk|"
    r"develop|development|branches?)(?:$|[/?#&=._-])",
    re.IGNORECASE,
)
ROOT_SOURCE_FIELDS = {
    "license_expression", "link_closure", "schema", "source_date_epoch",
    "sources", "target", "toolchain",
}
LINK_CLOSURE_FIELDS = {"evidence", "status"}
SOURCE_FIELDS = {
    "archive", "archive_bytes", "archive_sha256", "build", "fetch",
    "git_ref", "id", "license", "patches", "role", "version",
}
GIT_REF_FIELDS = {"commit", "kind", "object", "tree"}
HTTPS_FETCH_FIELDS = {"method", "url"}
GIT_FETCH_FIELDS = {
    "archive_prefix", "compression", "method", "url",
}
CAPABILITY_ROOT_FIELDS = {
    "build", "forbidden", "license_expression", "required", "schema",
    "runtime_notices", "target", "version_marker",
}
CAPABILITY_BUILD_FIELDS = {
    "configure_args", "container_image", "environment", "make",
    "link_evidence", "source_lock_sha256", "strip",
}
LINK_EVIDENCE_CONTRACT_FIELDS = {"closure_status", "formats", "programs"}
CAPABILITY_REQUIRED_FIELDS = {
    "decoders", "demuxers", "encoders", "filters", "input_devices",
    "muxers", "output_devices", "programs", "protocols",
}
CAPABILITY_FORBIDDEN_FIELDS = {
    "buildconf_tokens", "pe_import_patterns", "protocols",
}
RECEIPT_FIELDS = {
    "build", "inventory", "license_expression", "link_evidence", "outputs",
    "runtime_notices", "schema", "runtime_smoke", "source", "target",
}
RUNTIME_NOTICE_CONTRACT_FIELDS = {
    "archive_member", "filename", "license_expression", "source_id",
}
RUNTIME_NOTICE_RECEIPT_FIELDS = RUNTIME_NOTICE_CONTRACT_FIELDS | {"bytes", "sha256"}
RECEIPT_SOURCE_FIELDS = {
    "bundle_bytes", "bundle_lock_sha256", "bundle_manifest_bytes",
    "bundle_manifest_sha256", "bundle_sha256", "primary_lock_sha256",
    "repository_commit", "repository_tree",
}
RECEIPT_BUILD_FIELDS = {
    "capabilities_sha256", "configure_args", "container_image",
    "environment", "link_evidence", "make", "source_date_epoch", "strip",
}
LINK_EVIDENCE_RECEIPT_FIELDS = {"closure_status", "programs"}
LINK_EVIDENCE_PROGRAM_FIELDS = {"lld_map", "reproducer", "verbose"}
LINK_EVIDENCE_FILE_FIELDS = {"bytes", "filename", "sha256"}
LINK_EVIDENCE_REPRODUCER_FIELDS = {
    "bytes", "filename", "members", "sha256",
}
LINK_EVIDENCE_MEMBER_FIELDS = {"bytes", "path", "sha256"}
RECEIPT_OUTPUT_FIELDS = {
    "authenticode_content_bytes", "authenticode_content_sha256",
    "buildconf_sha256", "bytes", "filename", "pe", "sha256",
    "version", "version_sha256",
}
RECEIPT_PE_FIELDS = {
    "certificate_bytes", "characteristics", "coff_timestamp",
    "dll_characteristics", "imports", "machine",
}
INVENTORY_FIELDS = {
    "codecs", "command_output_sha256", "decoders", "demuxers", "encoders",
    "filters", "input_devices", "muxers", "output_devices", "protocols",
}
COMMAND_HASH_FIELDS = {
    "buildconf", "codecs", "decoders", "devices", "encoders", "filters",
    "formats", "protocols",
}
RUNTIME_SMOKE_FIELDS = {"checks", "status"}
RUNTIME_SMOKE_CHECKS = [
    "f32le-audio",
    "ffprobe-mp4",
    "lavfi-input",
    "libx264-aac-mp4",
    "wrapped-avframe-null-video",
]
EXPECTED_RUNTIME_NOTICES = [
    {
        "archive_member": (
            "FFmpeg-9b6c8969e05b4f0b29f0f85cd501be6b3e582e6b/COPYING.GPLv2"
        ),
        "filename": "FFmpeg-COPYING.GPLv2",
        "license_expression": "GPL-2.0-or-later",
        "source_id": "ffmpeg",
    },
    {
        "archive_member": (
            "llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1/"
            "LICENSE.TXT"
        ),
        "filename": "LLVM-LICENSE.TXT",
        "license_expression": "Apache-2.0 WITH LLVM-exception",
        "source_id": "llvm-project",
    },
    {
        "archive_member": (
            "llvm-project-ca7933e47d3a3451d81e72ac174dcb5aa28b59d1/"
            "compiler-rt/LICENSE.TXT"
        ),
        "filename": "LLVM-compiler-rt-LICENSE.TXT",
        "license_expression": "Apache-2.0 WITH LLVM-exception",
        "source_id": "llvm-project",
    },
    {
        "archive_member": (
            "mingw-w64-c28e9555bb8800c53449f42a465ad9a5676fce88/"
            "COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt"
        ),
        "filename": "MinGW-w64-runtime-NOTICES.txt",
        "license_expression": "LicenseRef-MinGW-w64-runtime",
        "source_id": "mingw-w64",
    },
    {
        "archive_member": (
            "x264-0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee/COPYING"
        ),
        "filename": "x264-COPYING",
        "license_expression": "GPL-2.0-or-later",
        "source_id": "x264",
    },
    {
        "archive_member": (
            "zlib-e3dc0a85b7032e98380dec011bc8f2c2ee0d8fca/LICENSE"
        ),
        "filename": "zlib-LICENSE",
        "license_expression": "Zlib",
        "source_id": "zlib",
    },
]
EXPECTED_LINK_EVIDENCE_CONTRACT = {
    "closure_status": "input-classification-unverified",
    "formats": ["lld-map", "lld-reproducer", "lld-verbose"],
    "programs": ["ffmpeg", "ffprobe"],
}
LINK_EVIDENCE_FILES = {
    "ffmpeg": {
        "lld_map": "ffmpeg-lld.map",
        "reproducer": "ffmpeg-reproduce.tar",
        "verbose": "ffmpeg-link.verbose.txt",
    },
    "ffprobe": {
        "lld_map": "ffprobe-lld.map",
        "reproducer": "ffprobe-reproduce.tar",
        "verbose": "ffprobe-link.verbose.txt",
    },
}


class WindowsFFmpegError(ValueError):
    """The Windows FFmpeg artifact does not satisfy its release contract."""


@dataclass(frozen=True)
class LoadedContract:
    path: Path
    canonical: bytes
    sha256: str

    def parsed(self) -> dict[str, Any]:
        """Return a fresh object so callers cannot mutate trusted state."""
        return json.loads(self.canonical)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise WindowsFFmpegError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest(), size


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WindowsFFmpegError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json(raw: bytes, label: str) -> dict[str, Any]:
    if b"\r" in raw:
        raise WindowsFFmpegError(f"{label} must use LF line endings")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WindowsFFmpegError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise WindowsFFmpegError(f"{label} root must be an object")
    return value


def _read_regular_file(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise WindowsFFmpegError(f"{label} must be a regular file, not a symlink")
        return path.read_bytes()
    except WindowsFFmpegError:
        raise
    except OSError as exc:
        raise WindowsFFmpegError(f"cannot read {label} {path}: {exc}") from exc


def _require_regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise WindowsFFmpegError(f"cannot inspect {label} {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise WindowsFFmpegError(f"{label} must be a regular file, not a symlink")
    return metadata


def runtime_notice_receipts(
    license_dir: Path,
    source_bundle: Path,
    source_lock: LoadedContract,
    capabilities: LoadedContract,
) -> list[dict[str, Any]]:
    try:
        metadata = license_dir.lstat()
    except OSError as exc:
        raise WindowsFFmpegError(
            f"cannot inspect Windows FFmpeg license directory {license_dir}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise WindowsFFmpegError(
            "Windows FFmpeg license directory must be a directory, not a symlink"
        )
    try:
        members = list(license_dir.iterdir())
    except OSError as exc:
        raise WindowsFFmpegError(
            f"cannot enumerate Windows FFmpeg license directory {license_dir}: {exc}"
        ) from exc
    notices = capabilities.parsed()["runtime_notices"]
    actual = {member.name for member in members}
    expected = {notice["filename"] for notice in notices}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise WindowsFFmpegError(
            "Windows FFmpeg license set drifted (" + "; ".join(details) + ")"
        )
    sources = {source["id"]: source for source in source_lock.parsed()["sources"]}
    try:
        with tarfile.open(source_bundle, mode="r:") as outer:
            outer_members = outer.getmembers()
            receipts = []
            for notice in notices:
                source = sources[notice["source_id"]]
                outer_name = (
                    "autoeditor-corresponding-source/upstream/" + source["archive"]
                )
                matches = [member for member in outer_members if member.name == outer_name]
                if len(matches) != 1 or not matches[0].isfile():
                    raise WindowsFFmpegError(
                        f"source bundle lacks one regular archive for {notice['source_id']}"
                    )
                outer_handle = outer.extractfile(matches[0])
                if outer_handle is None:
                    raise WindowsFFmpegError(
                        f"cannot read source archive for {notice['source_id']}"
                    )
                archive_raw = outer_handle.read()
                if sha256_bytes(archive_raw) != source["archive_sha256"]:
                    raise WindowsFFmpegError(
                        f"source archive for {notice['source_id']} differs from the source lock"
                    )
                with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:*") as inner:
                    inner_matches = [
                        member for member in inner.getmembers()
                        if member.name == notice["archive_member"]
                    ]
                    if len(inner_matches) != 1 or not inner_matches[0].isfile():
                        raise WindowsFFmpegError(
                            f"source archive lacks one regular {notice['archive_member']}"
                        )
                    inner_handle = inner.extractfile(inner_matches[0])
                    if inner_handle is None:
                        raise WindowsFFmpegError(
                            f"cannot read source notice {notice['archive_member']}"
                        )
                    expected_raw = inner_handle.read()
                filename = notice["filename"]
                actual_raw = _read_regular_file(
                    license_dir / filename,
                    f"Windows FFmpeg runtime notice {filename}",
                )
                if not actual_raw or actual_raw != expected_raw:
                    raise WindowsFFmpegError(
                        f"Windows FFmpeg runtime notice {filename} differs from its source archive"
                    )
                receipts.append({
                    **notice,
                    "bytes": len(actual_raw),
                    "sha256": sha256_bytes(actual_raw),
                })
            return receipts
    except WindowsFFmpegError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise WindowsFFmpegError(f"cannot verify Windows FFmpeg runtime notices: {exc}") from exc


def _link_evidence_text(path: Path, label: str) -> tuple[bytes, str]:
    raw = _read_regular_file(path, label)
    if not raw or b"\0" in raw or b"\r" in raw:
        raise WindowsFFmpegError(f"{label} must be nonempty LF-only text")
    try:
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WindowsFFmpegError(f"{label} must be UTF-8 text") from exc


def _link_evidence_file_receipt(path: Path, expected_name: str) -> dict[str, Any]:
    if path.name != expected_name:
        raise WindowsFFmpegError(
            f"link evidence filename drifted: expected {expected_name}, found {path.name}"
        )
    metadata = _require_regular_file(path, f"link evidence {expected_name}")
    if metadata.st_size <= 0:
        raise WindowsFFmpegError(f"link evidence {expected_name} is empty")
    digest, size = sha256_file(path)
    return {"bytes": size, "filename": expected_name, "sha256": digest}


def _safe_link_member_path(name: str, expected_root: str) -> None:
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        raise WindowsFFmpegError(f"LLD reproducer member path is unsafe: {name!r}")
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise WindowsFFmpegError(f"LLD reproducer member path is unsafe: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or path.parts[0] != expected_root:
        raise WindowsFFmpegError(
            f"LLD reproducer member is outside {expected_root}: {name}"
        )


def _lld_reproducer_receipt(path: Path, program: str) -> dict[str, Any]:
    expected_name = LINK_EVIDENCE_FILES[program]["reproducer"]
    base = _link_evidence_file_receipt(path, expected_name)
    expected_root = Path(expected_name).stem
    members = []
    seen_names: set[str] = set()
    seen_casefold: set[str] = set()
    response_raw = None
    response_name = f"{expected_root}/response.txt"
    try:
        with tarfile.open(path, mode="r:") as archive:
            for member in archive.getmembers():
                _safe_link_member_path(member.name, expected_root)
                folded = member.name.casefold()
                if member.name in seen_names or folded in seen_casefold:
                    raise WindowsFFmpegError(
                        f"LLD reproducer contains duplicate member {member.name}"
                    )
                seen_names.add(member.name)
                seen_casefold.add(folded)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise WindowsFFmpegError(
                        f"LLD reproducer member is not a regular file: {member.name}"
                    )
                handle = archive.extractfile(member)
                if handle is None:
                    raise WindowsFFmpegError(
                        f"cannot read LLD reproducer member {member.name}"
                    )
                raw = handle.read()
                if len(raw) != member.size:
                    raise WindowsFFmpegError(
                        f"LLD reproducer member size drifted: {member.name}"
                    )
                if member.name == response_name:
                    response_raw = raw
                members.append({
                    "bytes": len(raw),
                    "path": member.name,
                    "sha256": sha256_bytes(raw),
                })
    except WindowsFFmpegError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise WindowsFFmpegError(f"cannot inspect LLD reproducer {path}: {exc}") from exc
    if response_raw is None:
        raise WindowsFFmpegError(
            f"LLD reproducer lacks its exact response file {response_name}"
        )
    if not any(PurePosixPath(item["path"]).suffix.casefold() in {".a", ".lib"} for item in members):
        raise WindowsFFmpegError("LLD reproducer records no static or import archive")
    if not any(PurePosixPath(item["path"]).suffix.casefold() in {".o", ".obj"} for item in members):
        raise WindowsFFmpegError("LLD reproducer records no object input")
    if b"\0" in response_raw or b"\r" in response_raw:
        raise WindowsFFmpegError("LLD reproducer response must be LF-only text")
    try:
        response_text = response_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WindowsFFmpegError("LLD reproducer response must be UTF-8") from exc
    response_lower = response_text.casefold()
    if "reproduce" in response_lower:
        raise WindowsFFmpegError("LLD reproducer response recursively records reproduce output")
    if "lldmap:" not in response_lower or "verbose" not in response_lower:
        raise WindowsFFmpegError("LLD reproducer response lacks map or verbose evidence flags")
    if f"{program}_g.exe" not in response_lower:
        raise WindowsFFmpegError(
            f"LLD reproducer response is not bound to {program}_g.exe"
        )
    members.sort(key=lambda item: item["path"].encode("utf-8"))
    return {**base, "members": members}


def link_evidence_receipt(
    evidence_dir: Path,
    capabilities: LoadedContract,
) -> dict[str, Any]:
    try:
        metadata = evidence_dir.lstat()
    except OSError as exc:
        raise WindowsFFmpegError(
            f"cannot inspect Windows FFmpeg link evidence directory {evidence_dir}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise WindowsFFmpegError(
            "Windows FFmpeg link evidence path must be a directory, not a symlink"
        )
    expected_names = {
        filename
        for program_files in LINK_EVIDENCE_FILES.values()
        for filename in program_files.values()
    }
    try:
        actual_names = {item.name for item in evidence_dir.iterdir()}
    except OSError as exc:
        raise WindowsFFmpegError(
            f"cannot enumerate Windows FFmpeg link evidence directory: {exc}"
        ) from exc
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise WindowsFFmpegError(
            f"Windows FFmpeg link evidence set drifted (missing {missing}; extra {extra})"
        )

    programs = {}
    for program in capabilities.parsed()["build"]["link_evidence"]["programs"]:
        names = LINK_EVIDENCE_FILES[program]
        map_path = evidence_dir / names["lld_map"]
        map_raw, map_text = _link_evidence_text(
            map_path, f"{program} LLD map"
        )
        map_lines = map_text.splitlines()
        if (
            not map_lines
            or map_lines[0] != "Address  Size     Align Out     In      Symbol"
            or not any(" .text" in line for line in map_lines[1:])
        ):
            raise WindowsFFmpegError(f"{program} LLD map has an invalid structure")

        verbose_path = evidence_dir / names["verbose"]
        verbose_raw, verbose_text = _link_evidence_text(
            verbose_path, f"{program} LLD verbose log"
        )
        verbose_lower = verbose_text.casefold()
        if (
            f"{program}_g.exe" not in verbose_lower
            or not any(marker in verbose_lower for marker in ("--map=", "lldmap:"))
            or not any(marker in verbose_lower for marker in ("--verbose", "-verbose"))
            or not any(marker in verbose_lower for marker in ("--reproduce=", "-reproduce:"))
        ):
            raise WindowsFFmpegError(
                f"{program} LLD verbose log lacks the actual evidence-bearing link command"
            )
        programs[program] = {
            "lld_map": {
                "bytes": len(map_raw),
                "filename": names["lld_map"],
                "sha256": sha256_bytes(map_raw),
            },
            "reproducer": _lld_reproducer_receipt(
                evidence_dir / names["reproducer"], program
            ),
            "verbose": {
                "bytes": len(verbose_raw),
                "filename": names["verbose"],
                "sha256": sha256_bytes(verbose_raw),
            },
        }
    contract = capabilities.parsed()["build"]["link_evidence"]
    return {
        "closure_status": contract["closure_status"],
        "programs": programs,
    }


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise WindowsFFmpegError(
            f"{label} fields are invalid ({'; '.join(details)})"
        )


def _trimmed_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WindowsFFmpegError(f"{label} must be a non-empty trimmed string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise WindowsFFmpegError(f"{label} contains control characters")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WindowsFFmpegError(f"{label} must be a positive integer")
    return value


def _string_list(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
    sorted_required: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        expectation = "an array" if allow_empty else "a non-empty array"
        raise WindowsFFmpegError(f"{label} must be {expectation}")
    result = [_trimmed_string(item, f"{label} entry") for item in value]
    if len(result) != len(set(result)):
        raise WindowsFFmpegError(f"{label} contains duplicate entries")
    if sorted_required and result != sorted(result):
        raise WindowsFFmpegError(f"{label} must be sorted")
    return result


def _https_url(value: Any, label: str, *, exact_revision_in_path: bool) -> str:
    url = _trimmed_string(value, label)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise WindowsFFmpegError(
            f"{label} must be an HTTPS URL without credentials, query, or fragment"
        )
    if exact_revision_in_path and MOVING_REF_RE.search(parsed.path):
        raise WindowsFFmpegError(f"{label} may not use a moving reference")
    return url


def _validate_target(value: Any, *, include_machine: bool, label: str) -> None:
    if not isinstance(value, dict):
        raise WindowsFFmpegError(f"{label} must be an object")
    expected_fields = {"arch", "os", "triple"}
    if include_machine:
        expected_fields.add("machine")
    _exact_fields(value, expected_fields, label)
    expected = {
        "arch": "x64",
        "os": "windows",
        "triple": "x86_64-w64-mingw32",
    }
    if include_machine:
        expected["machine"] = "AMD64"
    if value != expected:
        raise WindowsFFmpegError(f"{label} is not the pinned Windows x64 target")


def _validate_source_lock(value: dict[str, Any]) -> None:
    _exact_fields(value, ROOT_SOURCE_FIELDS, "source lock")
    if value["schema"] != SOURCE_LOCK_SCHEMA:
        raise WindowsFFmpegError(f"source lock schema must be {SOURCE_LOCK_SCHEMA}")
    if value["license_expression"] != "GPL-2.0-or-later":
        raise WindowsFFmpegError("source lock license expression drifted")
    if value["source_date_epoch"] != 1785458830:
        raise WindowsFFmpegError("source lock SOURCE_DATE_EPOCH drifted")
    _validate_target(value["target"], include_machine=False, label="source lock target")

    link_closure = value["link_closure"]
    if not isinstance(link_closure, dict):
        raise WindowsFFmpegError("source lock link_closure must be an object")
    _exact_fields(link_closure, LINK_CLOSURE_FIELDS, "source lock link_closure")
    if link_closure != {
        "evidence": ["lld-map", "lld-reproducer", "lld-verbose"],
        "status": "input-classification-unverified",
    }:
        raise WindowsFFmpegError(
            "source lock link closure must remain unverified until every actual link input is classified"
        )

    toolchain = value["toolchain"]
    if not isinstance(toolchain, dict):
        raise WindowsFFmpegError("source lock toolchain must be an object")
    _exact_fields(toolchain, {"image", "image_digest", "source_id"}, "toolchain")
    if toolchain != {
        "image": "docker.io/mstorsjo/llvm-mingw:20260616",
        "image_digest": (
            "sha256:a6371b0e370e2e9839a147a8a23195ed986772f99ebf43123e31dbe20bfe2146"
        ),
        "source_id": "llvm-mingw",
    }:
        raise WindowsFFmpegError("source lock toolchain drifted")

    sources = value["sources"]
    if not isinstance(sources, list) or len(sources) != 7:
        raise WindowsFFmpegError("source lock must contain exactly seven sources")
    expected_ids = [
        "ffmpeg", "llvm-mingw", "llvm-project", "mingw-w64", "nasm",
        "x264", "zlib",
    ]
    actual_ids = []
    archives = set()
    urls = set()
    for index, source in enumerate(sources):
        label = f"source[{index}]"
        if not isinstance(source, dict):
            raise WindowsFFmpegError(f"{label} must be an object")
        _exact_fields(source, SOURCE_FIELDS, label)
        source_id = _trimmed_string(source["id"], f"{label}.id")
        if not SAFE_ID_RE.fullmatch(source_id):
            raise WindowsFFmpegError(f"{label}.id contains invalid characters")
        actual_ids.append(source_id)
        _trimmed_string(source["version"], f"{label}.version")
        _trimmed_string(source["role"], f"{label}.role")
        archive = _trimmed_string(source["archive"], f"{label}.archive")
        if Path(archive).name != archive or "\\" in archive:
            raise WindowsFFmpegError(f"{label}.archive must be a portable filename")
        if archive.casefold() in archives:
            raise WindowsFFmpegError(f"duplicate source archive: {archive}")
        archives.add(archive.casefold())
        _positive_int(source["archive_bytes"], f"{label}.archive_bytes")
        digest = _trimmed_string(source["archive_sha256"], f"{label}.archive_sha256")
        if not SHA256_RE.fullmatch(digest):
            raise WindowsFFmpegError(f"{label}.archive_sha256 is invalid")
        _string_list(source["license"], f"{label}.license")
        _string_list(source["build"], f"{label}.build")
        if source["patches"] != ["none"]:
            raise WindowsFFmpegError(f"{label}.patches must explicitly be ['none']")

        git_ref = source["git_ref"]
        if not isinstance(git_ref, dict):
            raise WindowsFFmpegError(f"{label}.git_ref must be an object")
        _exact_fields(git_ref, GIT_REF_FIELDS, f"{label}.git_ref")
        for field in ("object", "commit", "tree"):
            if not GIT_SHA1_RE.fullmatch(str(git_ref[field])):
                raise WindowsFFmpegError(f"{label}.git_ref.{field} is invalid")
        if git_ref["kind"] not in {"commit", "annotated-tag"}:
            raise WindowsFFmpegError(f"{label}.git_ref.kind is invalid")
        if git_ref["kind"] == "commit" and git_ref["object"] != git_ref["commit"]:
            raise WindowsFFmpegError(f"{label} commit object does not match its commit")

        fetch = source["fetch"]
        if not isinstance(fetch, dict):
            raise WindowsFFmpegError(f"{label}.fetch must be an object")
        if fetch.get("method") == "https-archive":
            _exact_fields(fetch, HTTPS_FETCH_FIELDS, f"{label}.fetch")
            url = _https_url(fetch["url"], f"{label}.fetch.url", exact_revision_in_path=True)
        elif fetch.get("method") == "git-archive":
            _exact_fields(fetch, GIT_FETCH_FIELDS, f"{label}.fetch")
            url = _https_url(fetch["url"], f"{label}.fetch.url", exact_revision_in_path=False)
            if fetch["compression"] != "gzip-9-no-name":
                raise WindowsFFmpegError(f"{label}.fetch.compression drifted")
            prefix = _trimmed_string(fetch["archive_prefix"], f"{label}.fetch.archive_prefix")
            if not prefix.endswith("/") or prefix.startswith("/") or ".." in prefix.split("/"):
                raise WindowsFFmpegError(f"{label}.fetch.archive_prefix is unsafe")
        else:
            raise WindowsFFmpegError(f"{label}.fetch.method is not allowed")
        if url in urls:
            raise WindowsFFmpegError(f"duplicate source URL: {url}")
        urls.add(url)
    if actual_ids != expected_ids:
        raise WindowsFFmpegError(
            "source lock IDs must be exactly: " + ", ".join(expected_ids)
        )


def _validate_capabilities(value: dict[str, Any]) -> None:
    _exact_fields(value, CAPABILITY_ROOT_FIELDS, "capability contract")
    if value["schema"] != CAPABILITIES_SCHEMA:
        raise WindowsFFmpegError(
            f"capability contract schema must be {CAPABILITIES_SCHEMA}"
        )
    if value["license_expression"] != "GPL-2.0-or-later":
        raise WindowsFFmpegError("capability license expression drifted")
    notices = value["runtime_notices"]
    if not isinstance(notices, list):
        raise WindowsFFmpegError("capability runtime_notices must be an array")
    for index, notice in enumerate(notices):
        if not isinstance(notice, dict):
            raise WindowsFFmpegError(
                f"capability runtime_notices[{index}] must be an object"
            )
        _exact_fields(
            notice,
            RUNTIME_NOTICE_CONTRACT_FIELDS,
            f"capability runtime_notices[{index}]",
        )
        for field in RUNTIME_NOTICE_CONTRACT_FIELDS:
            _trimmed_string(notice[field], f"runtime_notices[{index}].{field}")
    if notices != EXPECTED_RUNTIME_NOTICES:
        raise WindowsFFmpegError("capability runtime notice contract drifted")
    _trimmed_string(value["version_marker"], "version_marker")
    _validate_target(value["target"], include_machine=True, label="capability target")

    build = value["build"]
    if not isinstance(build, dict):
        raise WindowsFFmpegError("capability build must be an object")
    _exact_fields(build, CAPABILITY_BUILD_FIELDS, "capability build")
    lock_digest = _trimmed_string(build["source_lock_sha256"], "source_lock_sha256")
    if lock_digest != EXPECTED_SOURCE_LOCK_SHA256:
        raise WindowsFFmpegError("capability source lock digest drifted")
    expected_image = (
        "docker.io/mstorsjo/llvm-mingw:20260616@"
        "sha256:a6371b0e370e2e9839a147a8a23195ed986772f99ebf43123e31dbe20bfe2146"
    )
    if build["container_image"] != expected_image:
        raise WindowsFFmpegError("capability container image is not digest-pinned")
    configure_args = _string_list(build["configure_args"], "configure_args")
    if len(configure_args) != len(set(configure_args)):
        raise WindowsFFmpegError("configure_args contains duplicates")
    required_configure = {
        "--disable-network", "--disable-protocols", "--enable-protocol=file",
        "--enable-protocol=pipe", "--disable-shared", "--enable-static",
        "--enable-gpl", "--enable-libx264", "--enable-zlib",
        "--disable-pthreads",
    }
    missing = sorted(required_configure - set(configure_args))
    if missing:
        raise WindowsFFmpegError("configure_args missing: " + ", ".join(missing))
    environment = build["environment"]
    if not isinstance(environment, dict):
        raise WindowsFFmpegError("build.environment must be an object")
    _exact_fields(
        environment,
        {
            "COMMON_CFLAGS", "COMMON_LDFLAGS", "LC_ALL", "NASMENV", "PATH_PREFIX",
            "PREFIX", "SOURCE_DATE_EPOCH", "TARGET", "TZ", "ZERO_AR_DATE",
        },
        "build.environment",
    )
    if environment["SOURCE_DATE_EPOCH"] != "1785458830":
        raise WindowsFFmpegError("build SOURCE_DATE_EPOCH drifted")
    if environment["LC_ALL"] != "C" or environment["TZ"] != "UTC":
        raise WindowsFFmpegError("build locale or timezone drifted")
    if environment["NASMENV"] != "--reproducible":
        raise WindowsFFmpegError("NASM reproducible-output mode drifted")
    link_evidence = build["link_evidence"]
    if not isinstance(link_evidence, dict):
        raise WindowsFFmpegError("build.link_evidence must be an object")
    _exact_fields(
        link_evidence,
        LINK_EVIDENCE_CONTRACT_FIELDS,
        "build.link_evidence",
    )
    if link_evidence != EXPECTED_LINK_EVIDENCE_CONTRACT:
        raise WindowsFFmpegError(
            "build.link_evidence must remain fail-closed until actual link inputs are classified"
        )
    make = build["make"]
    if not isinstance(make, dict):
        raise WindowsFFmpegError("build.make must be an object")
    _exact_fields(make, {"jobs", "targets"}, "build.make")
    if make != {"jobs": 2, "targets": ["ffmpeg.exe", "ffprobe.exe"]}:
        raise WindowsFFmpegError("build.make drifted")
    strip = build["strip"]
    if not isinstance(strip, dict):
        raise WindowsFFmpegError("build.strip must be an object")
    _exact_fields(strip, {"arguments", "program"}, "build.strip")
    if strip != {
        "arguments": ["--strip-all"],
        "program": "x86_64-w64-mingw32-strip",
    }:
        raise WindowsFFmpegError("build.strip drifted")

    required = value["required"]
    if not isinstance(required, dict):
        raise WindowsFFmpegError("required capabilities must be an object")
    _exact_fields(required, CAPABILITY_REQUIRED_FIELDS, "required capabilities")
    for field in (
        "decoders", "demuxers", "encoders", "filters", "input_devices",
        "muxers", "programs",
    ):
        _string_list(required[field], f"required.{field}")
    _string_list(
        required["output_devices"], "required.output_devices", allow_empty=True
    )
    if required["input_devices"] != ["lavfi"] or required["output_devices"] != []:
        raise WindowsFFmpegError(
            "required devices must be exactly lavfi input and no output devices"
        )
    protocols = required["protocols"]
    if not isinstance(protocols, dict):
        raise WindowsFFmpegError("required.protocols must be an object")
    _exact_fields(protocols, {"input", "output"}, "required.protocols")
    if protocols != {"input": ["file", "pipe"], "output": ["file", "pipe"]}:
        raise WindowsFFmpegError("required protocols must be exactly file and pipe")

    forbidden = value["forbidden"]
    if not isinstance(forbidden, dict):
        raise WindowsFFmpegError("forbidden capabilities must be an object")
    _exact_fields(forbidden, CAPABILITY_FORBIDDEN_FIELDS, "forbidden capabilities")
    for field in CAPABILITY_FORBIDDEN_FIELDS:
        _string_list(forbidden[field], f"forbidden.{field}")
    for pattern in forbidden["pe_import_patterns"]:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise WindowsFFmpegError(f"invalid PE import pattern {pattern}: {exc}") from exc
    if set(required["protocols"]["input"] + required["protocols"]["output"]) & set(forbidden["protocols"]):
        raise WindowsFFmpegError("a required protocol is also forbidden")


def _load_contract(
    path: Path,
    label: str,
    expected_sha256: str,
    validator,
) -> LoadedContract:
    raw = _read_regular_file(path, label)
    value = _parse_json(raw, label)
    validator(value)
    canonical = canonical_json(value)
    if raw != canonical:
        raise WindowsFFmpegError(f"{label} must be canonical sorted JSON")
    digest = sha256_bytes(raw)
    if digest != expected_sha256:
        raise WindowsFFmpegError(
            f"{label} digest drifted: expected {expected_sha256}, found {digest}"
        )
    return LoadedContract(path=path, canonical=raw, sha256=digest)


def load_source_lock(path: Path) -> LoadedContract:
    return _load_contract(
        path, "Windows FFmpeg source lock", EXPECTED_SOURCE_LOCK_SHA256,
        _validate_source_lock,
    )


def load_capabilities(path: Path) -> LoadedContract:
    return _load_contract(
        path, "Windows FFmpeg capability contract", EXPECTED_CAPABILITIES_SHA256,
        _validate_capabilities,
    )


def load_contracts(
    source_lock_path: Path,
    capabilities_path: Path,
) -> tuple[LoadedContract, LoadedContract]:
    source_lock = load_source_lock(source_lock_path)
    capabilities = load_capabilities(capabilities_path)
    source = source_lock.parsed()
    capability = capabilities.parsed()
    if capability["build"]["source_lock_sha256"] != source_lock.sha256:
        raise WindowsFFmpegError("capability contract is not linked to the source lock")
    if capability["license_expression"] != source["license_expression"]:
        raise WindowsFFmpegError("source and capability license expressions differ")
    if capability["build"]["environment"]["SOURCE_DATE_EPOCH"] != str(source["source_date_epoch"]):
        raise WindowsFFmpegError("source and capability SOURCE_DATE_EPOCH values differ")
    image = source["toolchain"]["image"] + "@" + source["toolchain"]["image_digest"]
    if capability["build"]["container_image"] != image:
        raise WindowsFFmpegError("source and capability container images differ")
    return source_lock, capabilities


def bundle_lock_value(source_lock: LoadedContract) -> dict[str, Any]:
    sources = []
    for source in source_lock.parsed()["sources"]:
        sources.append({
            "archive": source["archive"],
            "build": source["build"],
            "id": source["id"],
            "license": source["license"],
            "patches": source["patches"],
            "sha256": source["archive_sha256"],
            "source_url": source["fetch"]["url"],
            "version": source["version"],
        })
    return {
        "provenance_status": "complete",
        "schema": BUNDLE_LOCK_SCHEMA,
        "sources": sources,
    }


def _source_archive_member_bytes(
    archive_path: Path,
    member_name: str,
    label: str,
) -> bytes:
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            matches = [
                member for member in archive.getmembers()
                if member.name == member_name
            ]
            if len(matches) != 1 or not matches[0].isfile():
                raise WindowsFFmpegError(
                    f"{label} lacks one regular {member_name}"
                )
            handle = archive.extractfile(matches[0])
            if handle is None:
                raise WindowsFFmpegError(f"cannot read {label} member {member_name}")
            return handle.read()
    except WindowsFFmpegError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise WindowsFFmpegError(f"cannot inspect {label}: {exc}") from exc


def _verify_toolchain_source_pins(source_lock: LoadedContract, cache: Path) -> None:
    sources = {item["id"]: item for item in source_lock.parsed()["sources"]}
    required_ids = {"llvm-mingw", "llvm-project", "mingw-w64"}
    if not required_ids.issubset(sources):
        return
    wrapper = sources["llvm-mingw"]
    wrapper_archive = cache / wrapper["archive"]
    wrapper_root = Path(wrapper["archive"]).name.removesuffix(".tar.gz")
    expected = {
        "build-llvm.sh": ("LLVM_VERSION", sources["llvm-project"]["version"]),
        "build-mingw-w64.sh": (
            "MINGW_W64_VERSION",
            sources["mingw-w64"]["git_ref"]["commit"],
        ),
    }
    for filename, (variable, expected_value) in expected.items():
        raw = _source_archive_member_bytes(
            wrapper_archive,
            f"{wrapper_root}/{filename}",
            "pinned llvm-mingw source archive",
        )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WindowsFFmpegError(
                f"llvm-mingw {filename} must be UTF-8"
            ) from exc
        pattern = re.compile(
            rf"^: \$\{{{re.escape(variable)}:=([^}}]+)\}}$",
            re.MULTILINE,
        )
        values = pattern.findall(text)
        if values != [expected_value]:
            raise WindowsFFmpegError(
                f"llvm-mingw {filename} does not bind {variable} to {expected_value}"
            )


def verify_source_cache(source_lock: LoadedContract, cache: Path) -> None:
    if not cache.is_dir():
        raise WindowsFFmpegError(f"source cache is missing: {cache}")
    expected_names = set()
    for source in source_lock.parsed()["sources"]:
        archive = cache / source["archive"]
        if archive.is_symlink() or not archive.is_file():
            raise WindowsFFmpegError(f"source archive is missing or not regular: {archive}")
        digest, size = sha256_file(archive)
        if size != source["archive_bytes"] or digest != source["archive_sha256"]:
            raise WindowsFFmpegError(
                f"source archive drifted for {source['id']}: expected "
                f"{source['archive_bytes']} bytes and {source['archive_sha256']}, "
                f"found {size} bytes and {digest}"
            )
        expected_names.add(source["archive"])
    actual_names = {item.name for item in cache.iterdir() if item.is_file()}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise WindowsFFmpegError(
            f"source cache member set drifted (missing {missing}; extra {extra})"
        )
    _verify_toolchain_source_pins(source_lock, cache)


def _rva_to_offset(
    rva: int,
    sections: list[tuple[int, int, int, int]],
    data_size: int,
) -> int:
    for virtual_address, virtual_size, raw_offset, raw_size in sections:
        extent = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + extent:
            offset = raw_offset + (rva - virtual_address)
            if offset >= data_size or offset >= raw_offset + raw_size:
                break
            return offset
    raise WindowsFFmpegError(f"PE RVA 0x{rva:x} does not map to file data")


def _c_string(data: bytes, offset: int, label: str) -> str:
    if offset < 0 or offset >= len(data):
        raise WindowsFFmpegError(f"{label} points outside the PE file")
    end = data.find(b"\0", offset, min(len(data), offset + 512))
    if end < 0:
        raise WindowsFFmpegError(f"{label} is not NUL terminated")
    try:
        value = data[offset:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise WindowsFFmpegError(f"{label} is not ASCII") from exc
    if not value:
        raise WindowsFFmpegError(f"{label} is empty")
    return value


def _directory_imports(
    data: bytes,
    directory_rva: int,
    directory_size: int,
    sections: list[tuple[int, int, int, int]],
    *,
    delay: bool,
) -> list[str]:
    if not directory_rva and not directory_size:
        return []
    if not directory_rva or not directory_size:
        raise WindowsFFmpegError("PE import directory is incomplete")
    offset = _rva_to_offset(directory_rva, sections, len(data))
    descriptor_size = 32 if delay else 20
    maximum = min(directory_size // descriptor_size + 1, 4096)
    imports = []
    for index in range(maximum):
        start = offset + index * descriptor_size
        end = start + descriptor_size
        if end > len(data):
            raise WindowsFFmpegError("PE import descriptor table is truncated")
        descriptor = data[start:end]
        if descriptor == b"\0" * descriptor_size:
            return imports
        name_rva = struct.unpack_from("<I", descriptor, 4 if delay else 12)[0]
        if not name_rva:
            raise WindowsFFmpegError("PE import descriptor has no DLL name")
        name_offset = _rva_to_offset(name_rva, sections, len(data))
        imports.append(_c_string(data, name_offset, "PE import name").casefold())
    raise WindowsFFmpegError("PE import descriptor table has no terminator")


def inspect_pe(path: Path, forbidden_patterns: Iterable[str]) -> dict[str, Any]:
    raw = _read_regular_file(path, "Windows executable")
    if len(raw) < 64 or raw[:2] != b"MZ":
        raise WindowsFFmpegError(f"{path} is not a PE executable")
    pe_offset = struct.unpack_from("<I", raw, 0x3C)[0]
    if pe_offset < 64 or pe_offset + 24 > len(raw) or raw[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise WindowsFFmpegError(f"{path} has an invalid PE header")
    coff = pe_offset + 4
    machine, section_count, timestamp = struct.unpack_from("<HHI", raw, coff)
    optional_size, characteristics = struct.unpack_from("<HH", raw, coff + 16)
    optional = pe_offset + 24
    if optional_size < 152 or optional + optional_size > len(raw):
        raise WindowsFFmpegError(f"{path} has an invalid optional header")
    if struct.unpack_from("<H", raw, optional)[0] != 0x20B or machine != 0x8664:
        raise WindowsFFmpegError(f"{path} is not an AMD64 PE32+ executable")
    dll_characteristics = struct.unpack_from("<H", raw, optional + 70)[0]
    directory_count = struct.unpack_from("<I", raw, optional + 108)[0]
    if directory_count < 14:
        raise WindowsFFmpegError(f"{path} lacks required PE data directories")
    directories = [
        struct.unpack_from("<II", raw, optional + 112 + index * 8)
        for index in range(min(directory_count, 16))
    ]
    security_offset, security_size = directories[4]
    if bool(security_offset) != bool(security_size):
        raise WindowsFFmpegError(f"{path} has an incomplete certificate table")
    if security_size:
        if security_offset % 8 or security_size < 8 or security_offset + security_size != len(raw):
            raise WindowsFFmpegError(f"{path} has an invalid certificate table")
        certificate_length, revision, certificate_type = struct.unpack_from(
            "<IHH", raw, security_offset
        )
        if (
            certificate_length < 8
            or certificate_length > security_size
            or revision not in {0x0100, 0x0200}
            or certificate_type != 0x0002
        ):
            raise WindowsFFmpegError(f"{path} has an invalid WIN_CERTIFICATE")
        content_end = security_offset
    else:
        content_end = len(raw)

    section_table = optional + optional_size
    if section_count <= 0 or section_count > 96 or section_table + section_count * 40 > len(raw):
        raise WindowsFFmpegError(f"{path} has an invalid PE section table")
    sections = []
    for index in range(section_count):
        start = section_table + index * 40
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", raw, start + 8
        )
        if raw_size and (raw_offset < section_table or raw_offset + raw_size > content_end):
            raise WindowsFFmpegError(f"{path} has an invalid PE section range")
        sections.append((virtual_address, virtual_size, raw_offset, raw_size))

    imports = _directory_imports(raw, *directories[1], sections, delay=False)
    imports.extend(_directory_imports(raw, *directories[13], sections, delay=True))
    imports = sorted(set(imports))
    for imported in imports:
        for pattern in forbidden_patterns:
            if re.fullmatch(pattern, imported, re.IGNORECASE):
                raise WindowsFFmpegError(
                    f"{path.name} imports forbidden runtime DLL {imported}"
                )
    if timestamp != 0:
        raise WindowsFFmpegError(f"{path.name} has a nonzero COFF timestamp")
    if characteristics & 0x0002 == 0 or characteristics & 0x2000:
        raise WindowsFFmpegError(f"{path.name} is not a PE executable image")
    if characteristics & 0x0020 == 0:
        raise WindowsFFmpegError(f"{path.name} is not large-address aware")
    required_dll_characteristics = 0x0020 | 0x0040 | 0x0100
    if dll_characteristics & required_dll_characteristics != required_dll_characteristics:
        raise WindowsFFmpegError(
            f"{path.name} lacks high-entropy VA, dynamic base, or NX compatibility"
        )

    normalized = bytearray(raw[:content_end])
    checksum_offset = optional + 64
    security_entry_offset = optional + 112 + 4 * 8
    normalized[checksum_offset:checksum_offset + 4] = b"\0" * 4
    normalized[security_entry_offset:security_entry_offset + 8] = b"\0" * 8
    canonical_size = (len(normalized) + 7) & ~7
    normalized.extend(b"\0" * (canonical_size - len(normalized)))
    return {
        "authenticode_content_bytes": canonical_size,
        "authenticode_content_sha256": sha256_bytes(bytes(normalized)),
        "bytes": len(raw),
        "certificate_bytes": security_size,
        "characteristics": characteristics,
        "coff_timestamp": timestamp,
        "dll_characteristics": dll_characteristics,
        "imports": imports,
        "machine": "AMD64",
        "sha256": sha256_bytes(raw),
    }


def _normalized_output(raw: str) -> str:
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def _run(executable: Path, arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            env={**os.environ, "LC_ALL": "C"},
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise WindowsFFmpegError(
            f"{executable.name} {' '.join(arguments)} timed out"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise WindowsFFmpegError(f"cannot execute {executable}: {exc}") from exc
    if result.returncode != 0:
        detail = _normalized_output(result.stderr or result.stdout).strip()
        raise WindowsFFmpegError(
            f"{executable.name} {' '.join(arguments)} failed: {detail}"
        )
    output = result.stdout if result.stdout else result.stderr
    return _normalized_output(output)


def _buildconf(output: str) -> list[str]:
    marker = "configuration:"
    terminal_diagnostic = "Exiting with exit code 0"
    position = output.find(marker)
    if position < 0:
        raise WindowsFFmpegError("FFmpeg buildconf output lacks configuration")
    arguments = []
    started = False
    finished = False
    for raw_line in output[position + len(marker):].splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if finished:
            raise WindowsFFmpegError("FFmpeg buildconf contains invalid arguments")
        if line == terminal_diagnostic:
            if not started:
                raise WindowsFFmpegError("FFmpeg buildconf contains invalid arguments")
            finished = True
            continue
        try:
            values = shlex.split(line)
        except ValueError as exc:
            raise WindowsFFmpegError(f"cannot parse FFmpeg buildconf: {exc}") from exc
        if values and all(value.startswith("--") for value in values):
            arguments.extend(values)
            started = True
            continue
        raise WindowsFFmpegError("FFmpeg buildconf contains invalid arguments")
    if not arguments:
        raise WindowsFFmpegError("FFmpeg buildconf contains invalid arguments")
    return arguments


def _named_inventory(output: str, flags: int, label: str) -> list[str]:
    names = set()
    pattern = re.compile(rf"^\s*[A-Z.]{{{flags}}}\s+([A-Za-z0-9_]+)(?:\s|$)")
    for line in output.splitlines():
        match = pattern.match(line)
        if match:
            names.add(match.group(1))
    if not names:
        raise WindowsFFmpegError(f"FFmpeg {label} inventory is empty")
    return sorted(names)


def _format_inventory(output: str) -> tuple[list[str], list[str]]:
    demuxers = set()
    muxers = set()
    pattern = re.compile(r"^\s*([D ])([E ])\s+([A-Za-z0-9_,]+)(?:\s|$)")
    for line in output.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        aliases = match.group(3).split(",")
        if match.group(1) == "D":
            demuxers.update(aliases)
        if match.group(2) == "E":
            muxers.update(aliases)
    if not demuxers or not muxers:
        raise WindowsFFmpegError("FFmpeg format inventory is incomplete")
    return sorted(demuxers), sorted(muxers)


def _device_inventory(output: str) -> tuple[list[str], list[str]]:
    inputs = set()
    outputs = set()
    pattern = re.compile(r"^\s*([D ])([E ])\s+([A-Za-z0-9_,]+)(?:\s|$)")
    for line in output.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        aliases = match.group(3).split(",")
        if match.group(1) == "D":
            inputs.update(aliases)
        if match.group(2) == "E":
            outputs.update(aliases)
    if not inputs:
        raise WindowsFFmpegError("FFmpeg input device inventory is empty")
    return sorted(inputs), sorted(outputs)


def _protocol_inventory(output: str) -> dict[str, list[str]]:
    current = None
    result = {"input": set(), "output": set()}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == "Input:":
            current = "input"
        elif line == "Output:":
            current = "output"
        elif current and re.fullmatch(r"[A-Za-z0-9_+-]+", line):
            result[current].add(line)
    if not result["input"] or not result["output"]:
        raise WindowsFFmpegError("FFmpeg protocol inventory is incomplete")
    return {key: sorted(values) for key, values in result.items()}


def collect_inventory(ffmpeg: Path, capabilities: LoadedContract) -> tuple[dict[str, Any], dict[str, str]]:
    arguments = {
        "buildconf": ["-hide_banner", "-buildconf"],
        "codecs": ["-hide_banner", "-codecs"],
        "decoders": ["-hide_banner", "-decoders"],
        "devices": ["-hide_banner", "-devices"],
        "encoders": ["-hide_banner", "-encoders"],
        "filters": ["-hide_banner", "-filters"],
        "formats": ["-hide_banner", "-formats"],
        "protocols": ["-hide_banner", "-protocols"],
    }
    outputs = {name: _run(ffmpeg, args) for name, args in arguments.items()}
    demuxers, muxers = _format_inventory(outputs["formats"])
    input_devices, output_devices = _device_inventory(outputs["devices"])
    inventory = {
        "codecs": _named_inventory(outputs["codecs"], 6, "codec"),
        "command_output_sha256": {
            name: sha256_bytes(output.encode("utf-8"))
            for name, output in sorted(outputs.items())
        },
        "decoders": _named_inventory(outputs["decoders"], 6, "decoder"),
        "demuxers": demuxers,
        "encoders": _named_inventory(outputs["encoders"], 6, "encoder"),
        "filters": _named_inventory(outputs["filters"], 2, "filter"),
        "input_devices": input_devices,
        "muxers": muxers,
        "output_devices": output_devices,
        "protocols": _protocol_inventory(outputs["protocols"]),
    }
    verify_inventory(inventory, _buildconf(outputs["buildconf"]), capabilities)
    return inventory, outputs


def verify_inventory(
    inventory: dict[str, Any],
    buildconf: list[str],
    capabilities: LoadedContract,
) -> None:
    contract = capabilities.parsed()
    expected_args = contract["build"]["configure_args"]
    if buildconf != expected_args:
        raise WindowsFFmpegError("FFmpeg buildconf differs from the pinned configure arguments")
    for forbidden in contract["forbidden"]["buildconf_tokens"]:
        if forbidden in buildconf:
            raise WindowsFFmpegError(f"FFmpeg buildconf enables forbidden option {forbidden}")
    required = contract["required"]
    for field in (
        "decoders", "demuxers", "encoders", "filters", "input_devices",
        "muxers",
    ):
        missing = sorted(set(required[field]) - set(inventory[field]))
        if missing:
            raise WindowsFFmpegError(
                f"FFmpeg is missing required {field}: {', '.join(missing)}"
            )
    if inventory["input_devices"] != required["input_devices"]:
        raise WindowsFFmpegError(
            "FFmpeg input devices must be exactly lavfi"
        )
    if inventory["output_devices"] != required["output_devices"]:
        raise WindowsFFmpegError(
            "FFmpeg output device inventory must be empty"
        )
    if inventory["protocols"] != required["protocols"]:
        raise WindowsFFmpegError(
            "FFmpeg protocols must be exactly file and pipe for input and output"
        )
    found_protocols = set(inventory["protocols"]["input"] + inventory["protocols"]["output"])
    forbidden_protocols = sorted(found_protocols & set(contract["forbidden"]["protocols"]))
    if forbidden_protocols:
        raise WindowsFFmpegError(
            "FFmpeg exposes forbidden protocols: " + ", ".join(forbidden_protocols)
        )


def run_runtime_smoke(ffmpeg: Path, ffprobe: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="autoeditor-windows-ffmpeg-smoke-") as raw:
        root = Path(raw)
        f32le = root / "audio.f32le"
        mp4 = root / "h264-aac.mp4"
        _run(ffmpeg, [
            "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            "sine=frequency=1000:sample_rate=16000:duration=0.125",
            "-ac", "1", "-c:a", "pcm_f32le", "-f", "f32le", str(f32le),
        ])
        f32le_metadata = _require_regular_file(f32le, "f32le smoke output")
        if f32le_metadata.st_size <= 0 or f32le_metadata.st_size % 4:
            raise WindowsFFmpegError("f32le smoke output has an invalid byte count")

        _run(ffmpeg, [
            "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            "testsrc2=size=64x64:rate=10:duration=0.2",
            "-c:v", "wrapped_avframe", "-f", "null", "-",
        ])
        _run(ffmpeg, [
            "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            "testsrc2=size=128x72:rate=10:duration=0.5",
            "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", str(mp4),
        ])
        mp4_metadata = _require_regular_file(mp4, "H.264/AAC smoke output")
        if mp4_metadata.st_size <= 0:
            raise WindowsFFmpegError("H.264/AAC smoke output is empty")
        probe_output = _run(ffprobe, [
            "-v", "error", "-show_entries", "stream=codec_name,codec_type",
            "-of", "json", str(mp4),
        ])
        try:
            probe = json.loads(probe_output)
        except json.JSONDecodeError as exc:
            raise WindowsFFmpegError("ffprobe smoke output is not JSON") from exc
        streams = probe.get("streams") if isinstance(probe, dict) else None
        if not isinstance(streams, list):
            raise WindowsFFmpegError("ffprobe smoke output has no stream inventory")
        found = {
            (stream.get("codec_type"), stream.get("codec_name"))
            for stream in streams if isinstance(stream, dict)
        }
        required = {("video", "h264"), ("audio", "aac")}
        if not required.issubset(found):
            raise WindowsFFmpegError(
                "ffprobe smoke output lacks H.264 video or AAC audio"
            )
    return {"checks": list(RUNTIME_SMOKE_CHECKS), "status": "passed"}


def verify_configure_help(
    help_text: str,
    capabilities: LoadedContract,
) -> dict[str, str]:
    """Bind every configure argument to an option advertised by FFmpeg."""
    advertised = set()
    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--"):
            continue
        token = stripped.split(None, 1)[0].split("=", 1)[0]
        if re.fullmatch(r"--[a-z0-9][a-z0-9-]*", token):
            advertised.add(token)
    if "--help" not in advertised or "--disable-static" not in advertised:
        raise WindowsFFmpegError("configure help does not look like pinned FFmpeg help")

    bindings = {}
    for argument in capabilities.parsed()["build"]["configure_args"]:
        option = argument.split("=", 1)[0]
        advertised_option = option
        if advertised_option not in advertised:
            if option.startswith("--enable-"):
                inverse = "--disable-" + option.removeprefix("--enable-")
            elif option.startswith("--disable-"):
                inverse = "--enable-" + option.removeprefix("--disable-")
            else:
                inverse = ""
            if inverse not in advertised:
                raise WindowsFFmpegError(
                    f"configure argument is not advertised by pinned FFmpeg: {option}"
                )
            advertised_option = inverse
        bindings[option] = advertised_option
    return bindings


def verify_makefile_contract(
    makefile_text: str,
    tools_makefile_text: str,
    config_mak_text: str,
    capabilities: LoadedContract,
) -> None:
    main_rule = (
        "$(PROGS): %$(PROGSSUF)$(EXESUF): "
        "%$(PROGSSUF)_g$(EXESUF)"
    )
    required_tool_rules = {
        "AVPROGS-$(CONFIG_FFMPEG)   += ffmpeg",
        "AVPROGS-$(CONFIG_FFPROBE)  += ffprobe",
        "AVPROGS     := $(AVPROGS-yes:%=%$(PROGSSUF)$(EXESUF))",
    }
    if main_rule not in makefile_text.splitlines():
        raise WindowsFFmpegError(
            "pinned FFmpeg Makefile lacks the executable suffix target rule"
        )
    tool_lines = set(tools_makefile_text.splitlines())
    missing_tool_rules = sorted(required_tool_rules - tool_lines)
    if missing_tool_rules:
        raise WindowsFFmpegError(
            "pinned FFmpeg tools Makefile drifted: "
            + ", ".join(missing_tool_rules)
        )

    config = {}
    for line in config_mak_text.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in {"CONFIG_FFMPEG", "CONFIG_FFPROBE", "EXESUF", "PROGSSUF"}:
            if key in config:
                raise WindowsFFmpegError(f"duplicate FFmpeg config.mak key: {key}")
            config[key] = value
    expected_config = {
        "CONFIG_FFMPEG": "yes",
        "CONFIG_FFPROBE": "yes",
        "EXESUF": ".exe",
        "PROGSSUF": "",
    }
    if config != expected_config:
        raise WindowsFFmpegError(
            "FFmpeg config.mak does not produce ffmpeg.exe and ffprobe.exe"
        )
    targets = capabilities.parsed()["build"]["make"]["targets"]
    if targets != ["ffmpeg.exe", "ffprobe.exe"]:
        raise WindowsFFmpegError("pinned make targets must name both Windows executables")


def _load_source_bundle_module(repo_root: Path):
    script = repo_root / "packaging" / "source_bundle.py"
    spec = importlib.util.spec_from_file_location("autoeditor_source_bundle_windows", script)
    if spec is None or spec.loader is None:
        raise WindowsFFmpegError(f"cannot load source bundle verifier: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as exc:
        raise WindowsFFmpegError(f"cannot load source bundle verifier: {exc}") from exc
    return module


def verify_bundle_linkage(
    source_lock: LoadedContract,
    bundle: Path,
    manifest_path: Path,
    repository_commit: str,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not GIT_SHA1_RE.fullmatch(repository_commit):
        raise WindowsFFmpegError("repository commit must be an exact 40-character SHA-1")
    bundle_metadata = _require_regular_file(bundle, "corresponding-source bundle")
    manifest_metadata = _require_regular_file(
        manifest_path, "corresponding-source manifest"
    )
    module = _load_source_bundle_module(repo_root)
    try:
        manifest = module.verify_bundle(bundle, manifest_path)
    except module.SourceBundleError as exc:
        raise WindowsFFmpegError(f"corresponding-source bundle failed: {exc}") from exc
    derived = bundle_lock_value(source_lock)
    derived_bytes = canonical_json(derived)
    expected_sources = [
        {
            "archive": f"{module.UPSTREAM_PREFIX}/{item['archive']}",
            "id": item["id"],
            "sha256": item["sha256"],
            "source_url": item["source_url"],
            "version": item["version"],
        }
        for item in derived["sources"]
    ]
    if manifest["lock"]["sha256"] != sha256_bytes(derived_bytes):
        raise WindowsFFmpegError("source bundle is not linked to the Windows source lock")
    if manifest["sources"] != expected_sources:
        raise WindowsFFmpegError("source bundle source inventory differs from the Windows source lock")
    if manifest["repository"]["commit"] != repository_commit:
        raise WindowsFFmpegError("source bundle repository commit drifted")
    receipt = {
        "bundle_bytes": bundle_metadata.st_size,
        "bundle_lock_sha256": manifest["lock"]["sha256"],
        "bundle_manifest_bytes": manifest_metadata.st_size,
        "bundle_manifest_sha256": sha256_file(manifest_path)[0],
        "bundle_sha256": sha256_file(bundle)[0],
        "primary_lock_sha256": source_lock.sha256,
        "repository_commit": repository_commit,
        "repository_tree": manifest["repository"]["tree"],
    }
    return manifest, receipt


def _output_receipt(
    path: Path,
    expected_name: str,
    forbidden_patterns: list[str],
    version_marker: str,
) -> tuple[dict[str, Any], str, str]:
    if path.name.casefold() != expected_name.casefold():
        raise WindowsFFmpegError(f"expected {expected_name}, found {path.name}")
    pe = inspect_pe(path, forbidden_patterns)
    if pe["certificate_bytes"] != 0:
        raise WindowsFFmpegError(f"{path.name} must be unsigned before reproducibility comparison")
    version = _run(path, ["-hide_banner", "-version"])
    buildconf_output = _run(path, ["-hide_banner", "-buildconf"])
    if version_marker not in version:
        raise WindowsFFmpegError(f"{path.name} lacks the pinned AutoEditor version marker")
    receipt = {
        "authenticode_content_bytes": pe["authenticode_content_bytes"],
        "authenticode_content_sha256": pe["authenticode_content_sha256"],
        "buildconf_sha256": sha256_bytes(buildconf_output.encode("utf-8")),
        "bytes": pe["bytes"],
        "filename": expected_name,
        "pe": {
            "certificate_bytes": pe["certificate_bytes"],
            "characteristics": pe["characteristics"],
            "coff_timestamp": pe["coff_timestamp"],
            "dll_characteristics": pe["dll_characteristics"],
            "imports": pe["imports"],
            "machine": pe["machine"],
        },
        "sha256": pe["sha256"],
        "version": version.splitlines()[0],
        "version_sha256": sha256_bytes(version.encode("utf-8")),
    }
    return receipt, version, buildconf_output


def create_receipt(
    *,
    source_lock_path: Path,
    capabilities_path: Path,
    ffmpeg: Path,
    ffprobe: Path,
    license_dir: Path,
    link_evidence_dir: Path,
    source_bundle: Path,
    source_manifest: Path,
    repository_commit: str,
    repo_root: Path,
) -> dict[str, Any]:
    source_lock, capabilities = load_contracts(source_lock_path, capabilities_path)
    _, source_receipt = verify_bundle_linkage(
        source_lock, source_bundle, source_manifest, repository_commit, repo_root
    )
    contract = capabilities.parsed()
    forbidden_patterns = contract["forbidden"]["pe_import_patterns"]
    ffmpeg_receipt, _, ffmpeg_buildconf = _output_receipt(
        ffmpeg, "ffmpeg.exe", forbidden_patterns, contract["version_marker"]
    )
    ffprobe_receipt, _, ffprobe_buildconf = _output_receipt(
        ffprobe, "ffprobe.exe", forbidden_patterns, contract["version_marker"]
    )
    expected_args = contract["build"]["configure_args"]
    if _buildconf(ffmpeg_buildconf) != expected_args or _buildconf(ffprobe_buildconf) != expected_args:
        raise WindowsFFmpegError("FFmpeg and FFprobe buildconf values differ from the contract")
    inventory, _ = collect_inventory(ffmpeg, capabilities)
    runtime_smoke = run_runtime_smoke(ffmpeg, ffprobe)
    receipt = {
        "build": {
            "capabilities_sha256": capabilities.sha256,
            "configure_args": contract["build"]["configure_args"],
            "container_image": contract["build"]["container_image"],
            "environment": contract["build"]["environment"],
            "link_evidence": contract["build"]["link_evidence"],
            "make": contract["build"]["make"],
            "source_date_epoch": int(contract["build"]["environment"]["SOURCE_DATE_EPOCH"]),
            "strip": contract["build"]["strip"],
        },
        "inventory": inventory,
        "license_expression": contract["license_expression"],
        "link_evidence": link_evidence_receipt(
            link_evidence_dir,
            capabilities,
        ),
        "outputs": {
            "ffmpeg": ffmpeg_receipt,
            "ffprobe": ffprobe_receipt,
        },
        "runtime_notices": runtime_notice_receipts(
            license_dir,
            source_bundle,
            source_lock,
            capabilities,
        ),
        "runtime_smoke": runtime_smoke,
        "schema": RECEIPT_SCHEMA,
        "source": source_receipt,
        "target": contract["target"],
    }
    validate_receipt_shape(receipt)
    validate_receipt_against_contracts(receipt, source_lock, capabilities)
    return receipt


def _sorted_receipt_list(value: Any, label: str) -> None:
    _string_list(value, label, sorted_required=True)


def _validate_link_evidence_shape(value: Any) -> None:
    if not isinstance(value, dict):
        raise WindowsFFmpegError("receipt link_evidence must be an object")
    _exact_fields(value, LINK_EVIDENCE_RECEIPT_FIELDS, "receipt link_evidence")
    if value["closure_status"] != "input-classification-unverified":
        raise WindowsFFmpegError(
            "receipt link evidence may not claim verified closure without classified inputs"
        )
    programs = value["programs"]
    if not isinstance(programs, dict):
        raise WindowsFFmpegError("receipt link_evidence.programs must be an object")
    _exact_fields(programs, set(LINK_EVIDENCE_FILES), "receipt link_evidence.programs")
    for program, names in LINK_EVIDENCE_FILES.items():
        record = programs[program]
        if not isinstance(record, dict):
            raise WindowsFFmpegError(f"receipt link evidence {program} must be an object")
        _exact_fields(
            record,
            LINK_EVIDENCE_PROGRAM_FIELDS,
            f"receipt link evidence {program}",
        )
        for field in ("lld_map", "verbose"):
            file_record = record[field]
            if not isinstance(file_record, dict):
                raise WindowsFFmpegError(
                    f"receipt link evidence {program}.{field} must be an object"
                )
            _exact_fields(
                file_record,
                LINK_EVIDENCE_FILE_FIELDS,
                f"receipt link evidence {program}.{field}",
            )
            if file_record["filename"] != names[field]:
                raise WindowsFFmpegError(
                    f"receipt link evidence {program}.{field} filename drifted"
                )
            _positive_int(
                file_record["bytes"],
                f"receipt link evidence {program}.{field}.bytes",
            )
            if not SHA256_RE.fullmatch(str(file_record["sha256"])):
                raise WindowsFFmpegError(
                    f"receipt link evidence {program}.{field}.sha256 is invalid"
                )

        reproducer = record["reproducer"]
        if not isinstance(reproducer, dict):
            raise WindowsFFmpegError(
                f"receipt link evidence {program}.reproducer must be an object"
            )
        _exact_fields(
            reproducer,
            LINK_EVIDENCE_REPRODUCER_FIELDS,
            f"receipt link evidence {program}.reproducer",
        )
        if reproducer["filename"] != names["reproducer"]:
            raise WindowsFFmpegError(
                f"receipt link evidence {program}.reproducer filename drifted"
            )
        _positive_int(
            reproducer["bytes"],
            f"receipt link evidence {program}.reproducer.bytes",
        )
        if not SHA256_RE.fullmatch(str(reproducer["sha256"])):
            raise WindowsFFmpegError(
                f"receipt link evidence {program}.reproducer.sha256 is invalid"
            )
        members = reproducer["members"]
        if not isinstance(members, list) or not members:
            raise WindowsFFmpegError(
                f"receipt link evidence {program}.reproducer.members must be nonempty"
            )
        paths = []
        expected_root = Path(names["reproducer"]).stem
        for index, member in enumerate(members):
            label = f"receipt link evidence {program}.reproducer.members[{index}]"
            if not isinstance(member, dict):
                raise WindowsFFmpegError(f"{label} must be an object")
            _exact_fields(member, LINK_EVIDENCE_MEMBER_FIELDS, label)
            path = _trimmed_string(member["path"], f"{label}.path")
            _safe_link_member_path(path, expected_root)
            _positive_int(member["bytes"], f"{label}.bytes")
            if not SHA256_RE.fullmatch(str(member["sha256"])):
                raise WindowsFFmpegError(f"{label}.sha256 is invalid")
            paths.append(path)
        if paths != sorted(paths, key=lambda item: item.encode("utf-8")):
            raise WindowsFFmpegError(
                f"receipt link evidence {program} reproducer members are not sorted"
            )
        if len(paths) != len(set(paths)) or len(paths) != len({item.casefold() for item in paths}):
            raise WindowsFFmpegError(
                f"receipt link evidence {program} reproducer members are duplicated"
            )
        response_name = f"{expected_root}/response.txt"
        if response_name not in paths:
            raise WindowsFFmpegError(
                f"receipt link evidence {program} lacks {response_name}"
            )
        suffixes = {PurePosixPath(path).suffix.casefold() for path in paths}
        if not suffixes.intersection({".a", ".lib"}) or not suffixes.intersection({".o", ".obj"}):
            raise WindowsFFmpegError(
                f"receipt link evidence {program} lacks archive or object inputs"
            )


def validate_receipt_shape(receipt: dict[str, Any]) -> None:
    _exact_fields(receipt, RECEIPT_FIELDS, "build receipt")
    if receipt["schema"] != RECEIPT_SCHEMA:
        raise WindowsFFmpegError(f"build receipt schema must be {RECEIPT_SCHEMA}")
    if receipt["license_expression"] != "GPL-2.0-or-later":
        raise WindowsFFmpegError("build receipt license expression drifted")
    notices = receipt["runtime_notices"]
    if not isinstance(notices, list) or len(notices) != len(EXPECTED_RUNTIME_NOTICES):
        raise WindowsFFmpegError("build receipt runtime_notices are incomplete")
    for index, record in enumerate(notices):
        if not isinstance(record, dict):
            raise WindowsFFmpegError(
                f"build receipt runtime_notices[{index}] must be an object"
            )
        _exact_fields(
            record,
            RUNTIME_NOTICE_RECEIPT_FIELDS,
            f"build receipt runtime_notices[{index}]",
        )
        for field in RUNTIME_NOTICE_CONTRACT_FIELDS:
            _trimmed_string(record[field], f"runtime_notices[{index}].{field}")
        _positive_int(record["bytes"], f"runtime_notices[{index}].bytes")
        if not SHA256_RE.fullmatch(str(record["sha256"])):
            raise WindowsFFmpegError(
                f"build receipt runtime_notices[{index}].sha256 is invalid"
            )
    _validate_link_evidence_shape(receipt["link_evidence"])
    _validate_target(receipt["target"], include_machine=True, label="receipt target")
    source = receipt["source"]
    if not isinstance(source, dict):
        raise WindowsFFmpegError("receipt source must be an object")
    _exact_fields(source, RECEIPT_SOURCE_FIELDS, "receipt source")
    for field in (
        "bundle_lock_sha256", "bundle_manifest_sha256", "bundle_sha256",
        "primary_lock_sha256",
    ):
        if not SHA256_RE.fullmatch(str(source[field])):
            raise WindowsFFmpegError(f"receipt source.{field} is invalid")
    for field in ("repository_commit", "repository_tree"):
        if not GIT_SHA1_RE.fullmatch(str(source[field])):
            raise WindowsFFmpegError(f"receipt source.{field} is invalid")
    _positive_int(source["bundle_bytes"], "receipt source.bundle_bytes")
    _positive_int(source["bundle_manifest_bytes"], "receipt source.bundle_manifest_bytes")

    build = receipt["build"]
    if not isinstance(build, dict):
        raise WindowsFFmpegError("receipt build must be an object")
    _exact_fields(build, RECEIPT_BUILD_FIELDS, "receipt build")
    if not SHA256_RE.fullmatch(str(build["capabilities_sha256"])):
        raise WindowsFFmpegError("receipt build.capabilities_sha256 is invalid")
    _string_list(build["configure_args"], "receipt build.configure_args")
    _trimmed_string(build["container_image"], "receipt build.container_image")
    _positive_int(build["source_date_epoch"], "receipt build.source_date_epoch")
    environment = build["environment"]
    if not isinstance(environment, dict):
        raise WindowsFFmpegError("receipt build.environment must be an object")
    _exact_fields(
        environment,
        {
            "COMMON_CFLAGS", "COMMON_LDFLAGS", "LC_ALL", "NASMENV", "PATH_PREFIX",
            "PREFIX", "SOURCE_DATE_EPOCH", "TARGET", "TZ", "ZERO_AR_DATE",
        },
        "receipt build.environment",
    )
    for field, value in environment.items():
        _trimmed_string(value, f"receipt build.environment.{field}")
    if build["link_evidence"] != EXPECTED_LINK_EVIDENCE_CONTRACT:
        raise WindowsFFmpegError("receipt build.link_evidence contract drifted")
    make = build["make"]
    if not isinstance(make, dict):
        raise WindowsFFmpegError("receipt build.make must be an object")
    _exact_fields(make, {"jobs", "targets"}, "receipt build.make")
    _positive_int(make["jobs"], "receipt build.make.jobs")
    _string_list(make["targets"], "receipt build.make.targets")
    strip = build["strip"]
    if not isinstance(strip, dict):
        raise WindowsFFmpegError("receipt build.strip must be an object")
    _exact_fields(strip, {"arguments", "program"}, "receipt build.strip")
    _string_list(strip["arguments"], "receipt build.strip.arguments")
    _trimmed_string(strip["program"], "receipt build.strip.program")

    outputs = receipt["outputs"]
    if not isinstance(outputs, dict):
        raise WindowsFFmpegError("receipt outputs must be an object")
    _exact_fields(outputs, {"ffmpeg", "ffprobe"}, "receipt outputs")
    for name, expected_filename in (("ffmpeg", "ffmpeg.exe"), ("ffprobe", "ffprobe.exe")):
        output = outputs[name]
        if not isinstance(output, dict):
            raise WindowsFFmpegError(f"receipt output {name} must be an object")
        _exact_fields(output, RECEIPT_OUTPUT_FIELDS, f"receipt output {name}")
        if output["filename"] != expected_filename:
            raise WindowsFFmpegError(f"receipt output {name} filename drifted")
        for field in (
            "authenticode_content_sha256", "buildconf_sha256", "sha256",
            "version_sha256",
        ):
            if not SHA256_RE.fullmatch(str(output[field])):
                raise WindowsFFmpegError(f"receipt output {name}.{field} is invalid")
        _positive_int(output["bytes"], f"receipt output {name}.bytes")
        _positive_int(
            output["authenticode_content_bytes"],
            f"receipt output {name}.authenticode_content_bytes",
        )
        _trimmed_string(output["version"], f"receipt output {name}.version")
        pe = output["pe"]
        if not isinstance(pe, dict):
            raise WindowsFFmpegError(f"receipt output {name}.pe must be an object")
        _exact_fields(pe, RECEIPT_PE_FIELDS, f"receipt output {name}.pe")
        if pe["machine"] != "AMD64" or pe["coff_timestamp"] != 0 or pe["certificate_bytes"] != 0:
            raise WindowsFFmpegError(f"receipt output {name} PE identity drifted")
        _sorted_receipt_list(pe["imports"], f"receipt output {name}.pe.imports")
        for field in ("characteristics", "dll_characteristics"):
            _positive_int(pe[field], f"receipt output {name}.pe.{field}")

    inventory = receipt["inventory"]
    if not isinstance(inventory, dict):
        raise WindowsFFmpegError("receipt inventory must be an object")
    _exact_fields(inventory, INVENTORY_FIELDS, "receipt inventory")
    for field in (
        "codecs", "decoders", "demuxers", "encoders", "filters",
        "input_devices", "muxers",
    ):
        _sorted_receipt_list(inventory[field], f"receipt inventory.{field}")
    _string_list(
        inventory["output_devices"],
        "receipt inventory.output_devices",
        allow_empty=True,
        sorted_required=True,
    )
    protocols = inventory["protocols"]
    if not isinstance(protocols, dict):
        raise WindowsFFmpegError("receipt inventory.protocols must be an object")
    _exact_fields(protocols, {"input", "output"}, "receipt inventory.protocols")
    _sorted_receipt_list(protocols["input"], "receipt inventory.protocols.input")
    _sorted_receipt_list(protocols["output"], "receipt inventory.protocols.output")
    hashes = inventory["command_output_sha256"]
    if not isinstance(hashes, dict):
        raise WindowsFFmpegError("receipt command hashes must be an object")
    _exact_fields(hashes, COMMAND_HASH_FIELDS, "receipt command hashes")
    for field, digest in hashes.items():
        if not SHA256_RE.fullmatch(str(digest)):
            raise WindowsFFmpegError(f"receipt command hash {field} is invalid")
    runtime_smoke = receipt["runtime_smoke"]
    if not isinstance(runtime_smoke, dict):
        raise WindowsFFmpegError("receipt runtime_smoke must be an object")
    _exact_fields(runtime_smoke, RUNTIME_SMOKE_FIELDS, "receipt runtime_smoke")
    if runtime_smoke != {"checks": RUNTIME_SMOKE_CHECKS, "status": "passed"}:
        raise WindowsFFmpegError("receipt runtime smoke checks are incomplete")


def validate_receipt_against_contracts(
    receipt: dict[str, Any],
    source_lock: LoadedContract,
    capabilities: LoadedContract,
) -> None:
    source_contract = source_lock.parsed()
    capability_contract = capabilities.parsed()
    if receipt["source"]["primary_lock_sha256"] != source_lock.sha256:
        raise WindowsFFmpegError("build receipt is not linked to the pinned source lock")
    expected_bundle_lock_sha256 = sha256_bytes(
        canonical_json(bundle_lock_value(source_lock))
    )
    if receipt["source"]["bundle_lock_sha256"] != expected_bundle_lock_sha256:
        raise WindowsFFmpegError("build receipt is not linked to the derived source-bundle lock")
    expected_build = {
        "capabilities_sha256": capabilities.sha256,
        "configure_args": capability_contract["build"]["configure_args"],
        "container_image": capability_contract["build"]["container_image"],
        "environment": capability_contract["build"]["environment"],
        "link_evidence": capability_contract["build"]["link_evidence"],
        "make": capability_contract["build"]["make"],
        "source_date_epoch": source_contract["source_date_epoch"],
        "strip": capability_contract["build"]["strip"],
    }
    if receipt["build"] != expected_build:
        raise WindowsFFmpegError("build receipt build inputs differ from the pinned contract")
    if receipt["target"] != capability_contract["target"]:
        raise WindowsFFmpegError("build receipt target differs from the pinned contract")
    if receipt["license_expression"] != source_contract["license_expression"]:
        raise WindowsFFmpegError("build receipt license differs from the pinned contract")
    if receipt["link_evidence"]["closure_status"] != source_contract["link_closure"]["status"]:
        raise WindowsFFmpegError(
            "build receipt link closure status differs from the fail-closed source contract"
        )
    if set(receipt["link_evidence"]["programs"]) != set(
        capability_contract["build"]["link_evidence"]["programs"]
    ):
        raise WindowsFFmpegError(
            "build receipt link evidence program set differs from the pinned contract"
        )
    notice_contracts = [
        {field: notice[field] for field in RUNTIME_NOTICE_CONTRACT_FIELDS}
        for notice in receipt["runtime_notices"]
    ]
    if notice_contracts != capability_contract["runtime_notices"]:
        raise WindowsFFmpegError(
            "build receipt runtime notices differ from the pinned contract"
        )
    if receipt["runtime_smoke"] != {
        "checks": RUNTIME_SMOKE_CHECKS,
        "status": "passed",
    }:
        raise WindowsFFmpegError("build receipt runtime smoke result drifted")
    verify_inventory(
        receipt["inventory"], receipt["build"]["configure_args"], capabilities
    )
    patterns = capability_contract["forbidden"]["pe_import_patterns"]
    marker = capability_contract["version_marker"]
    for output_name, output in receipt["outputs"].items():
        if marker not in output["version"]:
            raise WindowsFFmpegError(
                f"receipt output {output_name} lacks the pinned version marker"
            )
        pe = output["pe"]
        if pe["characteristics"] & 0x0022 != 0x0022:
            raise WindowsFFmpegError(
                f"receipt output {output_name} lacks PE executable hardening"
            )
        if pe["dll_characteristics"] & 0x0160 != 0x0160:
            raise WindowsFFmpegError(
                f"receipt output {output_name} lacks PE DLL hardening"
            )
        for imported in pe["imports"]:
            if any(re.fullmatch(pattern, imported, re.IGNORECASE) for pattern in patterns):
                raise WindowsFFmpegError(
                    f"receipt output {output_name} records forbidden import {imported}"
                )


def load_receipt(path: Path) -> LoadedContract:
    raw = _read_regular_file(path, "Windows FFmpeg build receipt")
    value = _parse_json(raw, "Windows FFmpeg build receipt")
    validate_receipt_shape(value)
    if raw != canonical_json(value):
        raise WindowsFFmpegError("Windows FFmpeg build receipt must be canonical sorted JSON")
    return LoadedContract(path=path, canonical=raw, sha256=sha256_bytes(raw))


def _default_paths() -> tuple[Path, Path, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    return (
        repo_root,
        repo_root / "packaging" / "windows-ffmpeg-sources.lock.json",
        repo_root / "packaging" / "windows-ffmpeg-capabilities.json",
    )


def _add_contract_paths(parser: argparse.ArgumentParser, defaults: tuple[Path, Path, Path]) -> None:
    _, lock, capabilities = defaults
    parser.add_argument("--source-lock", type=Path, default=lock)
    parser.add_argument("--capabilities", type=Path, default=capabilities)


def _add_artifact_paths(parser: argparse.ArgumentParser, defaults: tuple[Path, Path, Path]) -> None:
    repo_root, _, _ = defaults
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--license-dir", type=Path, required=True)
    parser.add_argument("--link-evidence-dir", type=Path, required=True)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--repo-root", type=Path, default=repo_root)


def _parser() -> argparse.ArgumentParser:
    defaults = _default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    contracts = commands.add_parser("contracts", help="validate pinned build contracts")
    _add_contract_paths(contracts, defaults)

    bundle_lock = commands.add_parser(
        "materialize-bundle-lock", help="write the source-bundle-compatible lock"
    )
    _add_contract_paths(bundle_lock, defaults)
    bundle_lock.add_argument("--output", type=Path, required=True)

    cache = commands.add_parser("verify-source-cache", help="verify every source archive")
    _add_contract_paths(cache, defaults)
    cache.add_argument("--cache", type=Path, required=True)

    fetch_plan = commands.add_parser("emit-fetch-plan", help="emit a tab-separated fetch plan")
    _add_contract_paths(fetch_plan, defaults)

    image = commands.add_parser("container-image", help="print the digest-pinned image")
    _add_contract_paths(image, defaults)

    configure = commands.add_parser("emit-configure-args", help="emit pinned configure arguments")
    _add_contract_paths(configure, defaults)
    configure.add_argument("--nul", action="store_true")

    configure_help = commands.add_parser(
        "verify-configure-help",
        help="bind every configure argument to pinned FFmpeg configure help",
    )
    _add_contract_paths(configure_help, defaults)
    configure_help.add_argument("--configure-help", type=Path, required=True)

    makefile = commands.add_parser(
        "verify-makefile",
        help="bind Windows executable targets to pinned FFmpeg make rules",
    )
    _add_contract_paths(makefile, defaults)
    makefile.add_argument("--makefile", type=Path, required=True)
    makefile.add_argument("--tools-makefile", type=Path, required=True)
    makefile.add_argument("--config-mak", type=Path, required=True)

    pe = commands.add_parser("verify-pe", help="check unsigned PE structure and imports")
    _add_contract_paths(pe, defaults)
    pe.add_argument("--ffmpeg", type=Path, required=True)
    pe.add_argument("--ffprobe", type=Path, required=True)

    link_evidence = commands.add_parser(
        "verify-link-evidence",
        help="verify exact LLD map, verbose, and reproducer evidence",
    )
    _add_contract_paths(link_evidence, defaults)
    link_evidence.add_argument("--link-evidence-dir", type=Path, required=True)

    create = commands.add_parser("create-receipt", help="create a canonical build receipt")
    _add_contract_paths(create, defaults)
    _add_artifact_paths(create, defaults)
    create.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify-receipt", help="recompute and verify a build receipt")
    _add_contract_paths(verify, defaults)
    _add_artifact_paths(verify, defaults)
    verify.add_argument("--receipt", type=Path, required=True)

    compare = commands.add_parser("compare-receipts", help="require two clean builds to match")
    _add_contract_paths(compare, defaults)
    compare.add_argument("--first", type=Path, required=True)
    compare.add_argument("--second", type=Path, required=True)

    promotable = commands.add_parser(
        "assert-promotable",
        help="fail unless link input classification has verified full source closure",
    )
    _add_contract_paths(promotable, defaults)
    promotable.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "compare-receipts":
            source_lock, capabilities = load_contracts(
                args.source_lock, args.capabilities
            )
            first = load_receipt(args.first)
            second = load_receipt(args.second)
            validate_receipt_against_contracts(
                first.parsed(), source_lock, capabilities
            )
            validate_receipt_against_contracts(
                second.parsed(), source_lock, capabilities
            )
            if first.canonical != second.canonical:
                raise WindowsFFmpegError(
                    "clean build receipts differ; unsigned executables or source bundles are not reproducible"
                )
            print(f"Windows FFmpeg dual-build receipt verified: {first.sha256}")
            return

        source_lock, capabilities = load_contracts(args.source_lock, args.capabilities)
        if args.command == "contracts":
            print(
                "Windows FFmpeg contracts verified: "
                f"source={source_lock.sha256} capabilities={capabilities.sha256}"
            )
        elif args.command == "materialize-bundle-lock":
            output = args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(canonical_json(bundle_lock_value(source_lock)))
            print(f"source-bundle lock written: {output}")
        elif args.command == "verify-source-cache":
            verify_source_cache(source_lock, args.cache)
            print(
                "Windows FFmpeg source cache verified: "
                f"{len(source_lock.parsed()['sources'])} archives"
            )
        elif args.command == "emit-fetch-plan":
            for source in source_lock.parsed()["sources"]:
                fetch = source["fetch"]
                fields = [
                    source["id"], fetch["method"], source["archive"],
                    fetch["url"], source["archive_sha256"],
                    str(source["archive_bytes"]), source["git_ref"]["object"],
                    source["git_ref"]["commit"], source["git_ref"]["tree"],
                    fetch.get("archive_prefix", "-"),
                ]
                print("\t".join(fields))
        elif args.command == "container-image":
            print(capabilities.parsed()["build"]["container_image"])
        elif args.command == "emit-configure-args":
            separator = "\0" if args.nul else "\n"
            sys.stdout.write(separator.join(capabilities.parsed()["build"]["configure_args"]))
            sys.stdout.write(separator)
        elif args.command == "verify-configure-help":
            help_text = _read_regular_file(
                args.configure_help, "FFmpeg configure help"
            ).decode("utf-8")
            verify_configure_help(help_text, capabilities)
            print(
                "FFmpeg configure help verified: "
                f"{len(capabilities.parsed()['build']['configure_args'])} "
                "pinned arguments"
            )
        elif args.command == "verify-makefile":
            makefile_text = _read_regular_file(
                args.makefile, "FFmpeg Makefile"
            ).decode("utf-8")
            tools_makefile_text = _read_regular_file(
                args.tools_makefile, "FFmpeg tools Makefile"
            ).decode("utf-8")
            config_mak_text = _read_regular_file(
                args.config_mak, "FFmpeg config.mak"
            ).decode("utf-8")
            verify_makefile_contract(
                makefile_text, tools_makefile_text, config_mak_text,
                capabilities,
            )
            print("FFmpeg Windows make targets verified: ffmpeg.exe ffprobe.exe")
        elif args.command == "verify-pe":
            patterns = capabilities.parsed()["forbidden"]["pe_import_patterns"]
            for path, name in ((args.ffmpeg, "ffmpeg.exe"), (args.ffprobe, "ffprobe.exe")):
                if path.name.casefold() != name:
                    raise WindowsFFmpegError(f"expected {name}, found {path.name}")
                pe = inspect_pe(path, patterns)
                if pe["certificate_bytes"]:
                    raise WindowsFFmpegError(f"{path.name} must be unsigned")
            print("Windows FFmpeg PE artifacts verified")
        elif args.command == "verify-link-evidence":
            evidence = link_evidence_receipt(args.link_evidence_dir, capabilities)
            member_count = sum(
                len(program["reproducer"]["members"])
                for program in evidence["programs"].values()
            )
            print(
                "Windows FFmpeg LLD link evidence verified: "
                f"{member_count} recorded reproducer members; closure remains unverified"
            )
        elif args.command == "assert-promotable":
            receipt = load_receipt(args.receipt)
            validate_receipt_against_contracts(
                receipt.parsed(), source_lock, capabilities
            )
            status = receipt.parsed()["link_evidence"]["closure_status"]
            if status != "verified":
                raise WindowsFFmpegError(
                    "Windows FFmpeg is not promotable: actual LLD link inputs remain unclassified"
                )
            print("Windows FFmpeg link source closure is verified for promotion")
        elif args.command in {"create-receipt", "verify-receipt"}:
            receipt = create_receipt(
                source_lock_path=args.source_lock,
                capabilities_path=args.capabilities,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
                license_dir=args.license_dir,
                link_evidence_dir=args.link_evidence_dir,
                source_bundle=args.source_bundle,
                source_manifest=args.source_manifest,
                repository_commit=args.repository_commit,
                repo_root=args.repo_root,
            )
            raw = canonical_json(receipt)
            if args.command == "create-receipt":
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(raw)
                print(f"Windows FFmpeg build receipt written: {sha256_bytes(raw)}")
            else:
                recorded = load_receipt(args.receipt)
                if recorded.canonical != raw:
                    raise WindowsFFmpegError("Windows FFmpeg build receipt differs from the artifacts")
                print(f"Windows FFmpeg build receipt verified: {recorded.sha256}")
    except WindowsFFmpegError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
