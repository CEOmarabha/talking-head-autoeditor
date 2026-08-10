#!/usr/bin/env python3
"""Bind final Electron native binaries to the pinned Electron 43.3.0 archive.

The receipt is produced from the final packed application, not from staging.
Windows permits only Electron Builder's deterministic resource edit and a
terminal Authenticode envelope. macOS permits only code-signature allocation
and the terminal ``__LINKEDIT`` page rounding implied by that allocation.
Everything else is compared byte-for-byte with the pinned archive member.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA = "autoeditor-electron-native-producer-receipt/v1"
ELECTRON_VERSION = "43.3.0"
SOURCE_LOCK_SCHEMA = "autoeditor-electron-chromium-provenance-lock/v1"
SOURCE_LOCK_SHA256 = (
    "4c24da63574cbcbad23f68e5d3f0eaedc19af099308471981b2b5e62c3b183d8"
)
PRODUCT_NAME = "AutoEditor Helper"
COPYRIGHT = "Copyright © 2026 Omar Marabha (@CEOmarabha)"
ICON_SHA256 = "0b0f706e96340f7b7f5dd60847e5778159c83e5383701f51f32ddf779d2fb6fd"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
VERSION_RE = re.compile(
    r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?:[.-][A-Za-z0-9.-]+)?\Z"
)
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_RECEIPT_BYTES = 16 * 1024 * 1024

ARCHIVE_RECORDS: dict[str, dict[str, Any]] = {
    "windows-x64": {
        "bytes": 144396349,
        "filename": "electron-v43.3.0-win32-x64.zip",
        "sha256": "18528bedc6a9b04bdc5efb7b803cbc3cb0e5ea6415d54046e23d464d89a00da9",
    },
    "mac-arm64": {
        "bytes": 122102881,
        "filename": "electron-v43.3.0-darwin-arm64.zip",
        "sha256": "ee939d1564d83d61032b3b3cb23af4e46005a4900c91f0695f7ed793f0ce6e83",
    },
    "mac-x64": {
        "bytes": 124293997,
        "filename": "electron-v43.3.0-darwin-x64.zip",
        "sha256": "7347bbd5fb529eea64f9c2d148bb1c19222d98946ff234ffe27953a1bbcb9dae",
    },
}

WINDOWS_NAMES = (
    "AutoEditor Helper.exe",
    "d3dcompiler_47.dll",
    "dxcompiler.dll",
    "dxil.dll",
    "ffmpeg.dll",
    "libEGL.dll",
    "libGLESv2.dll",
    "vk_swiftshader.dll",
    "vulkan-1.dll",
)
WINDOWS_ARCHIVE_NAMES = ("electron.exe", *WINDOWS_NAMES[1:])

MAC_MAPPINGS = (
    ("Electron.app/Contents/MacOS/Electron", "Contents/MacOS/AutoEditor"),
    (
        "Electron.app/Contents/Frameworks/Electron Framework.framework/"
        "Versions/A/Electron Framework",
        "Contents/Frameworks/Electron Framework.framework/Versions/A/"
        "Electron Framework",
    ),
    (
        "Electron.app/Contents/Frameworks/Electron Framework.framework/"
        "Versions/A/Helpers/chrome_crashpad_handler",
        "Contents/Frameworks/Electron Framework.framework/Versions/A/"
        "Helpers/chrome_crashpad_handler",
    ),
    *tuple(
        (
            "Electron.app/Contents/Frameworks/Electron Framework.framework/"
            f"Versions/A/Libraries/{name}",
            "Contents/Frameworks/Electron Framework.framework/Versions/A/"
            f"Libraries/{name}",
        )
        for name in (
            "libEGL.dylib",
            "libGLESv2.dylib",
            "libffmpeg.dylib",
            "libvk_swiftshader.dylib",
        )
    ),
    (
        "Electron.app/Contents/Frameworks/Mantle.framework/Versions/A/Mantle",
        "Contents/Frameworks/Mantle.framework/Versions/A/Mantle",
    ),
    (
        "Electron.app/Contents/Frameworks/ReactiveObjC.framework/Versions/A/"
        "ReactiveObjC",
        "Contents/Frameworks/ReactiveObjC.framework/Versions/A/ReactiveObjC",
    ),
    (
        "Electron.app/Contents/Frameworks/Squirrel.framework/Versions/A/"
        "Squirrel",
        "Contents/Frameworks/Squirrel.framework/Versions/A/Squirrel",
    ),
    (
        "Electron.app/Contents/Frameworks/Squirrel.framework/Versions/A/"
        "Resources/ShipIt",
        "Contents/Frameworks/Squirrel.framework/Versions/A/Resources/ShipIt",
    ),
    *tuple(
        (
            f"Electron.app/Contents/Frameworks/Electron Helper{suffix}.app/"
            f"Contents/MacOS/Electron Helper{suffix}",
            f"Contents/Frameworks/AutoEditor Helper Helper{suffix}.app/"
            f"Contents/MacOS/AutoEditor Helper Helper{suffix}",
        )
        for suffix in ("", " (GPU)", " (Plugin)", " (Renderer)")
    ),
)


class ElectronNativeReceiptError(ValueError):
    """The Electron archive, final app, or receipt failed closed."""


@dataclass(frozen=True)
class ElectronNativeClaim:
    path: str
    component: str
    sha256: str
    byte_count: int
    mode: int


@dataclass(frozen=True)
class _FileData:
    raw: bytes
    mode: int
    sha256: str


@dataclass(frozen=True)
class _Section:
    name: str
    header_offset: int
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_pointer: int
    reloc_pointer: int
    line_pointer: int
    relocation_count: int
    line_count: int
    characteristics: int


@dataclass(frozen=True)
class _PeImage:
    raw: bytes
    pe_offset: int
    optional_offset: int
    optional_size: int
    checksum_offset: int
    directory_offset: int
    size_of_headers: int
    section_alignment: int
    file_alignment: int
    sections: tuple[_Section, ...]
    directories: tuple[tuple[int, int], ...]
    certificate_offset: int
    certificate_bytes: int


@dataclass(frozen=True)
class _ResourceLeaf:
    path: tuple[str | int, ...]
    codepage: int
    data: bytes


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ElectronNativeReceiptError(f"invalid {label} SHA256")
    return value


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _read_regular(path: Path, label: str, maximum: int = MAX_FILE_BYTES) -> _FileData:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ElectronNativeReceiptError(f"{label} must be a regular file")
        if before.st_nlink != 1 or before.st_size <= 0 or before.st_size > maximum:
            raise ElectronNativeReceiptError(f"{label} has invalid filesystem metadata")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _identity(before) != _identity(opened):
            raise ElectronNativeReceiptError(f"{label} changed while opening")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ElectronNativeReceiptError(f"short read for {label}")
            chunks.append(chunk)
            remaining -= len(chunk)
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if _identity(opened) != _identity(after_handle) or _identity(opened) != _identity(after_path):
            raise ElectronNativeReceiptError(f"{label} changed while reading")
        raw = b"".join(chunks)
        return _FileData(raw, stat.S_IMODE(opened.st_mode), _sha256(raw))
    except ElectronNativeReceiptError:
        raise
    except OSError as exc:
        raise ElectronNativeReceiptError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ElectronNativeReceiptError(f"invalid receipt path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ElectronNativeReceiptError(f"unsafe receipt path: {value!r}")
    if str(path) != value:
        raise ElectronNativeReceiptError(f"non-canonical receipt path: {value!r}")
    return value


def _require_exact_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ElectronNativeReceiptError(f"{label} has wrong fields")
    return value


def _decode_json(raw: bytes, label: str) -> Any:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ElectronNativeReceiptError(f"invalid {label} JSON") from exc
    return value


def _load_json(raw: bytes, label: str) -> dict[str, Any]:
    value = _decode_json(raw, label)
    if not isinstance(value, dict):
        raise ElectronNativeReceiptError(f"{label} root must be an object")
    return value


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ElectronNativeReceiptError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mappings(target: str) -> tuple[tuple[str, str], ...]:
    if target == "windows-x64":
        return tuple(zip(WINDOWS_ARCHIVE_NAMES, WINDOWS_NAMES))
    if target in {"mac-arm64", "mac-x64"}:
        return MAC_MAPPINGS
    raise ElectronNativeReceiptError(f"unsupported Electron target: {target}")


def _component(path: str, target: str) -> str:
    if target == "windows-x64" and path == "ffmpeg.dll":
        return "electron"
    if target != "windows-x64" and path.endswith("/Libraries/libffmpeg.dylib"):
        return "electron"
    return "supporting-native"


def _load_source_lock(path: Path, target: str) -> tuple[dict[str, Any], _FileData]:
    data = _read_regular(path, "Electron source lock", MAX_RECEIPT_BYTES)
    if data.sha256 != SOURCE_LOCK_SHA256:
        raise ElectronNativeReceiptError("Electron source lock SHA256 drifted")
    payload = _load_json(data.raw, "Electron source lock")
    if payload.get("schema") != SOURCE_LOCK_SCHEMA or payload.get("provenance_status") != "complete":
        raise ElectronNativeReceiptError("Electron source lock is not complete v1 provenance")
    electron = payload.get("electron")
    if not isinstance(electron, dict) or electron.get("version") != ELECTRON_VERSION:
        raise ElectronNativeReceiptError("Electron source lock is not pinned to 43.3.0")
    archives = electron.get("archives")
    archive = archives.get(target) if isinstance(archives, dict) else None
    expected = ARCHIVE_RECORDS[target]
    expected_url = (
        "https://github.com/electron/electron/releases/download/v43.3.0/"
        + expected["filename"]
    )
    if (
        not isinstance(archive, dict)
        or {key: archive.get(key) for key in expected} != expected
        or archive.get("url") != expected_url
        or set(archive) != {*expected, "url"}
    ):
        raise ElectronNativeReceiptError("Electron archive record drifted from the exact target")
    return payload, data


def _load_configuration(
    config_path: Path,
    package_path: Path,
    icon_path: Path,
    version: str,
) -> dict[str, Any]:
    match = VERSION_RE.fullmatch(version)
    if match is None:
        raise ElectronNativeReceiptError("invalid configured Helper version")
    config_data = _read_regular(config_path, "Electron Builder Helper config", MAX_RECEIPT_BYTES)
    package_data = _read_regular(package_path, "desktop package manifest", MAX_RECEIPT_BYTES)
    icon_data = _read_regular(icon_path, "configured Windows icon", MAX_RECEIPT_BYTES)
    if icon_data.sha256 != ICON_SHA256:
        raise ElectronNativeReceiptError("configured Windows icon SHA256 drifted")
    try:
        import yaml

        config = yaml.safe_load(config_data.raw.decode("utf-8"))
    except Exception as exc:
        raise ElectronNativeReceiptError("cannot parse Electron Builder Helper config") from exc
    package = _load_json(package_data.raw, "desktop package manifest")
    if not isinstance(config, dict):
        raise ElectronNativeReceiptError("Electron Builder Helper config must be an object")
    win = config.get("win")
    if (
        config.get("productName") != PRODUCT_NAME
        or config.get("copyright") != COPYRIGHT
        or not isinstance(win, dict)
        or win.get("icon") != "build/icon.ico"
    ):
        raise ElectronNativeReceiptError("configured product, copyright, or Windows icon drifted")
    if (
        package.get("name") != "autoeditor-desktop"
        or package.get("version") != version
        or package.get("author") != "Omar Marabha"
        or package.get("devDependencies", {}).get("electron") != ELECTRON_VERSION
        or package.get("devDependencies", {}).get("electron-builder") != "26.15.3"
    ):
        raise ElectronNativeReceiptError("desktop package metadata drifted from the Helper build")
    return {
        "builder_config_sha256": config_data.sha256,
        "copyright": COPYRIGHT,
        "electron_builder": "26.15.3",
        "icon_bytes": len(icon_data.raw),
        "icon_sha256": icon_data.sha256,
        "package_manifest_sha256": package_data.sha256,
        "product_name": PRODUCT_NAME,
        "version": version,
        "version_quad": [
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            0,
        ],
    }


def _archive_members(path: Path, target: str) -> tuple[dict[str, _FileData], _FileData]:
    archive = _read_regular(path, "Electron binary archive", MAX_FILE_BYTES)
    expected = ARCHIVE_RECORDS[target]
    if path.name != expected["filename"] or len(archive.raw) != expected["bytes"] or archive.sha256 != expected["sha256"]:
        raise ElectronNativeReceiptError("Electron binary archive does not match the exact pinned record")
    wanted = {source for source, _ in _mappings(target)}
    result: dict[str, _FileData] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive.raw)) as bundle:
            seen: set[str] = set()
            for info in bundle.infolist():
                name = info.filename.rstrip("/")
                if name in seen:
                    raise ElectronNativeReceiptError(f"duplicate Electron archive member: {name}")
                seen.add(name)
                if name not in wanted:
                    continue
                if info.flag_bits & 1 or info.is_dir():
                    raise ElectronNativeReceiptError(f"invalid Electron archive member: {name}")
                mode = (info.external_attr >> 16) & 0o777
                raw = bundle.read(info)
                if not raw or len(raw) > MAX_FILE_BYTES:
                    raise ElectronNativeReceiptError(f"invalid Electron archive member bytes: {name}")
                result[name] = _FileData(raw, mode, _sha256(raw))
    except ElectronNativeReceiptError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ElectronNativeReceiptError(f"cannot read Electron binary archive: {exc}") from exc
    missing = sorted(wanted - set(result))
    if missing:
        raise ElectronNativeReceiptError("Electron archive is missing native members: " + ", ".join(missing))
    return result, archive


def _parse_pe(raw: bytes, label: str) -> _PeImage:
    if len(raw) < 0x100 or raw[:2] != b"MZ":
        raise ElectronNativeReceiptError(f"{label} is not PE")
    pe_offset = struct.unpack_from("<I", raw, 0x3C)[0]
    if pe_offset > len(raw) - 24 or raw[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ElectronNativeReceiptError(f"{label} has an invalid PE header")
    machine, count, _, _, _, optional_size, _ = struct.unpack_from("<HHIIIHH", raw, pe_offset + 4)
    if machine != 0x8664 or count == 0 or count > 96 or optional_size < 240:
        raise ElectronNativeReceiptError(f"{label} is not a bounded x64 PE32+ image")
    optional = pe_offset + 24
    if optional + optional_size > len(raw) or struct.unpack_from("<H", raw, optional)[0] != 0x20B:
        raise ElectronNativeReceiptError(f"{label} has an invalid PE32+ optional header")
    section_alignment = struct.unpack_from("<I", raw, optional + 32)[0]
    file_alignment = struct.unpack_from("<I", raw, optional + 36)[0]
    size_headers = struct.unpack_from("<I", raw, optional + 60)[0]
    directory_count = struct.unpack_from("<I", raw, optional + 108)[0]
    if directory_count != 16 or section_alignment == 0 or file_alignment == 0:
        raise ElectronNativeReceiptError(f"{label} has unsupported PE layout fields")
    directory_offset = optional + 112
    directories = tuple(struct.unpack_from("<II", raw, directory_offset + i * 8) for i in range(16))
    section_offset = optional + optional_size
    if section_offset + count * 40 > len(raw) or size_headers < section_offset + count * 40:
        raise ElectronNativeReceiptError(f"{label} has a truncated PE section table")
    sections: list[_Section] = []
    names: set[str] = set()
    ranges: list[tuple[int, int]] = []
    for index in range(count):
        offset = section_offset + index * 40
        name_raw = raw[offset : offset + 8].split(b"\0", 1)[0]
        try:
            name = name_raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ElectronNativeReceiptError(f"{label} has a non-ASCII section name") from exc
        if not name or name in names:
            raise ElectronNativeReceiptError(f"{label} has invalid duplicate PE sections")
        names.add(name)
        values = struct.unpack_from("<IIIIIIHHI", raw, offset + 8)
        section = _Section(name, offset, *values)
        if section.raw_size:
            end = section.raw_pointer + section.raw_size
            if section.raw_pointer < size_headers or end > len(raw):
                raise ElectronNativeReceiptError(f"{label} has invalid section bounds: {name}")
            ranges.append((section.raw_pointer, end))
        sections.append(section)
    for left, right in zip(sorted(ranges), sorted(ranges)[1:]):
        if left[1] > right[0]:
            raise ElectronNativeReceiptError(f"{label} has overlapping PE sections")
    certificate_offset, certificate_bytes = directories[4]
    if bool(certificate_offset) != bool(certificate_bytes):
        raise ElectronNativeReceiptError(f"{label} has a partial Authenticode directory")
    if certificate_offset and (
        certificate_offset % 8
        or certificate_offset < max(end for _, end in ranges)
        or certificate_offset + certificate_bytes != len(raw)
    ):
        raise ElectronNativeReceiptError(f"{label} has a non-terminal Authenticode envelope")
    if not certificate_offset and max(end for _, end in ranges) != len(raw):
        raise ElectronNativeReceiptError(f"{label} has an unowned PE overlay")
    return _PeImage(
        raw,
        pe_offset,
        optional,
        optional_size,
        optional + 64,
        directory_offset,
        size_headers,
        section_alignment,
        file_alignment,
        tuple(sections),
        directories,
        certificate_offset,
        certificate_bytes,
    )


def _normalized_pe(image: _PeImage) -> tuple[bytes, dict[str, Any]]:
    end = image.certificate_offset or len(image.raw)
    normalized = bytearray(image.raw[:end])
    struct.pack_into("<I", normalized, image.checksum_offset, 0)
    struct.pack_into("<II", normalized, image.directory_offset + 4 * 8, 0, 0)
    certificate = image.raw[image.certificate_offset:] if image.certificate_offset else b""
    return bytes(normalized), {
        "authenticode": "present" if certificate else "absent",
        "certificate_bytes": len(certificate),
        "certificate_sha256": _sha256(certificate) if certificate else None,
    }


def _section(image: _PeImage, name: str) -> _Section:
    matches = [section for section in image.sections if section.name == name]
    if len(matches) != 1:
        raise ElectronNativeReceiptError(f"PE image must contain exactly one {name} section")
    return matches[0]


def _rva_offset(image: _PeImage, rva: int, size: int, label: str) -> int:
    if size < 0:
        raise ElectronNativeReceiptError(f"invalid {label} size")
    if rva < image.size_of_headers and rva + size <= image.size_of_headers:
        return rva
    for section in image.sections:
        span = max(section.virtual_size, section.raw_size)
        if section.virtual_address <= rva and rva + size <= section.virtual_address + span:
            offset = section.raw_pointer + rva - section.virtual_address
            if offset + size <= section.raw_pointer + section.raw_size and offset + size <= len(image.raw):
                return offset
    raise ElectronNativeReceiptError(f"invalid {label} RVA")


def _c_string(raw: bytes, offset: int, label: str, maximum: int = 4096) -> str:
    end = raw.find(b"\0", offset, min(len(raw), offset + maximum))
    if end < 0:
        raise ElectronNativeReceiptError(f"unterminated {label}")
    try:
        return raw[offset:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ElectronNativeReceiptError(f"non-ASCII {label}") from exc


def _imports(image: _PeImage, directory_index: int, *, delay: bool) -> list[dict[str, Any]]:
    rva, size = image.directories[directory_index]
    if not rva and not size:
        return []
    descriptor_size = 32 if delay else 20
    base = _rva_offset(image, rva, size, "import directory")
    result: list[dict[str, Any]] = []
    cursor = base
    limit = base + size
    for _ in range(4096):
        if cursor + descriptor_size > len(image.raw):
            raise ElectronNativeReceiptError("truncated PE import descriptor")
        words = struct.unpack_from("<8I" if delay else "<5I", image.raw, cursor)
        if not any(words):
            break
        if delay:
            attributes, name_rva, _, _, int_rva, _, _, _ = words
            if not attributes & 1:
                raise ElectronNativeReceiptError("VA-based delay imports are not accepted")
        else:
            int_rva, _, _, name_rva, first_thunk = words
            int_rva = int_rva or first_thunk
        name_offset = _rva_offset(image, name_rva, 1, "import name")
        dll = _c_string(image.raw, name_offset, "import DLL")
        thunk_offset = _rva_offset(image, int_rva, 8, "import thunk")
        symbols: list[str] = []
        for index in range(65536):
            value = struct.unpack_from("<Q", image.raw, thunk_offset + index * 8)[0]
            if value == 0:
                break
            if value & (1 << 63):
                symbols.append(f"#{value & 0xffff}")
            else:
                hint_name = _rva_offset(image, value, 3, "import symbol")
                hint = struct.unpack_from("<H", image.raw, hint_name)[0]
                symbols.append(f"{hint}:{_c_string(image.raw, hint_name + 2, 'import symbol')}")
        else:
            raise ElectronNativeReceiptError("PE import thunk table is unbounded")
        result.append({"dll": dll, "symbols": symbols})
        cursor += descriptor_size
        if cursor > limit and not delay:
            raise ElectronNativeReceiptError("PE import directory exceeded its declared size")
    else:
        raise ElectronNativeReceiptError("PE import descriptor table is unbounded")
    return result


def _pe_profile(image: _PeImage, normalized: bytes) -> dict[str, Any]:
    sections = []
    for section in image.sections:
        data = normalized[section.raw_pointer : section.raw_pointer + section.raw_size]
        sections.append(
            {
                "characteristics": section.characteristics,
                "name": section.name,
                "raw_bytes": section.raw_size,
                "raw_pointer": section.raw_pointer,
                "raw_sha256": _sha256(data),
                "virtual_address": section.virtual_address,
                "virtual_bytes": section.virtual_size,
            }
        )
    header = normalized[: image.size_of_headers]
    return {
        "delay_imports": _imports(image, 13, delay=True),
        "header_bytes": image.size_of_headers,
        "header_sha256": _sha256(header),
        "imports": _imports(image, 1, delay=False),
        "sections": sections,
    }


def _resource_leaves(
    image: _PeImage,
    *,
    require_exact_extent: bool = False,
) -> dict[tuple[str | int, ...], _ResourceLeaf]:
    resource_rva, resource_size = image.directories[2]
    resource = _section(image, ".rsrc")
    if (
        resource_rva != resource.virtual_address
        or resource_size != resource.virtual_size
        or resource_size <= 0
        or resource_size > resource.raw_size
    ):
        raise ElectronNativeReceiptError("PE resource directory does not exactly own .rsrc")
    base = resource.raw_pointer
    limit = base + resource_size
    used: list[tuple[int, int]] = []
    active: set[int] = set()
    leaves: dict[tuple[str | int, ...], _ResourceLeaf] = {}

    def claim(start: int, size: int, label: str) -> None:
        if start < base or size < 0 or start + size > limit:
            raise ElectronNativeReceiptError(f"resource {label} is outside .rsrc")
        for left, right in used:
            if start < right and left < start + size:
                if start == left and start + size == right:
                    return
                raise ElectronNativeReceiptError(f"overlapping resource {label}")
        used.append((start, start + size))

    def entry_name(value: int) -> str | int:
        if not value & 0x80000000:
            return value
        offset = base + (value & 0x7FFFFFFF)
        if offset + 2 > limit:
            raise ElectronNativeReceiptError("truncated resource name")
        count = struct.unpack_from("<H", image.raw, offset)[0]
        size = 2 + count * 2
        claim(offset, size, "name")
        try:
            name = image.raw[offset + 2 : offset + size].decode("utf-16le")
        except UnicodeDecodeError as exc:
            raise ElectronNativeReceiptError("invalid UTF-16 resource name") from exc
        if not name or "\x00" in name:
            raise ElectronNativeReceiptError("invalid empty resource name")
        return name

    def walk(relative: int, path: tuple[str | int, ...]) -> None:
        if len(path) >= 3 or relative in active:
            raise ElectronNativeReceiptError("invalid recursive resource tree")
        active.add(relative)
        offset = base + relative
        if offset + 16 > limit:
            raise ElectronNativeReceiptError("truncated resource directory")
        characteristics, timestamp, major, minor, named, ids = struct.unpack_from(
            "<IIHHHH", image.raw, offset
        )
        if characteristics or timestamp or major or minor:
            raise ElectronNativeReceiptError("resource directory metadata must be deterministic zero")
        count = named + ids
        if count > 4096 or offset + 16 + count * 8 > limit:
            raise ElectronNativeReceiptError("resource directory entry count is invalid")
        claim(offset, 16 + count * 8, "directory")
        prior: tuple[int, str] | None = None
        for index in range(count):
            name_value, target = struct.unpack_from("<II", image.raw, offset + 16 + index * 8)
            key = entry_name(name_value)
            order = (0, key) if isinstance(key, str) else (1, f"{key:010d}")
            if prior is not None and order <= prior:
                raise ElectronNativeReceiptError("resource directory entries are not uniquely ordered")
            prior = order
            child_path = (*path, key)
            if target & 0x80000000:
                walk(target & 0x7FFFFFFF, child_path)
                continue
            if len(child_path) != 3:
                raise ElectronNativeReceiptError("resource data entry has wrong depth")
            data_entry = base + target
            claim(data_entry, 16, "data entry")
            data_rva, size, codepage, reserved = struct.unpack_from("<IIII", image.raw, data_entry)
            if reserved or size <= 0:
                raise ElectronNativeReceiptError("resource data entry is invalid")
            data_offset = _rva_offset(image, data_rva, size, "resource payload")
            claim(data_offset, size, "payload")
            if child_path in leaves:
                raise ElectronNativeReceiptError("duplicate resource leaf")
            leaves[child_path] = _ResourceLeaf(child_path, codepage, image.raw[data_offset : data_offset + size])
        active.remove(relative)

    walk(0, ())
    if not leaves:
        raise ElectronNativeReceiptError("PE resource tree is empty")
    if require_exact_extent and max(end for _, end in used) != limit:
        raise ElectronNativeReceiptError(
            "generated PE resource extent is not exactly owned"
        )
    covered = bytearray(resource.raw_size)
    for start, end in used:
        covered[start - base : end - base] = b"\1" * (end - start)
    raw_section = image.raw[base : base + resource.raw_size]
    for index, value in enumerate(raw_section):
        if covered[index] or value == 0:
            continue
        if index >= resource_size and value == b"PADDINGX"[(index - resource_size) % 8]:
            continue
        if value != 0:
            raise ElectronNativeReceiptError(
                f"PE .rsrc contains unowned nonzero byte at offset {index}"
            )
    return leaves


def _icon_payloads(raw: bytes) -> tuple[list[bytes], bytes]:
    if len(raw) < 6:
        raise ElectronNativeReceiptError("configured icon is truncated")
    reserved, kind, count = struct.unpack_from("<HHH", raw, 0)
    if reserved != 0 or kind != 1 or count <= 0 or count > 64 or 6 + count * 16 > len(raw):
        raise ElectronNativeReceiptError("configured icon has invalid ICO header")
    payloads: list[bytes] = []
    group = bytearray(struct.pack("<HHH", 0, 1, count))
    ranges: list[tuple[int, int]] = []
    for index in range(count):
        offset = 6 + index * 16
        width, height, colors, reserved_byte, planes, bits, size, data_offset = struct.unpack_from(
            "<BBBBHHII", raw, offset
        )
        if reserved_byte or size <= 0 or data_offset < 6 + count * 16 or data_offset + size > len(raw):
            raise ElectronNativeReceiptError("configured icon has invalid image bounds")
        ranges.append((data_offset, data_offset + size))
        payloads.append(raw[data_offset : data_offset + size])
        group.extend(
            struct.pack(
                "<BBBBHHIH",
                width,
                height,
                colors,
                0,
                planes or 1,
                bits,
                size,
                index + 1,
            )
        )
    for left, right in zip(sorted(ranges), sorted(ranges)[1:]):
        if left[1] > right[0]:
            raise ElectronNativeReceiptError("configured icon images overlap")
    return payloads, bytes(group)


def _align(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ElectronNativeReceiptError("non-power-of-two binary alignment")
    return (value + alignment - 1) & ~(alignment - 1)


def _serialized_resource_size(entries: Iterable[_ResourceLeaf]) -> int:
    """Reproduce pe-library 0.4.1's generated resource virtual size."""
    ordered = tuple(entries)
    if not ordered:
        raise ElectronNativeReceiptError("cannot serialize an empty PE resource tree")
    tree: dict[str | int, dict[str | int, set[str | int]]] = {}
    strings: set[str] = set()
    for entry in ordered:
        if len(entry.path) != 3 or not entry.data:
            raise ElectronNativeReceiptError("invalid resource leaf for serialization")
        resource_type, resource_id, language = entry.path
        languages = tree.setdefault(resource_type, {}).setdefault(resource_id, set())
        if language in languages:
            raise ElectronNativeReceiptError("duplicate resource leaf for serialization")
        languages.add(language)
        strings.update(part for part in entry.path if isinstance(part, str))

    size = 16 + 8 * len(tree)
    for ids in tree.values():
        size += 16 + 8 * len(ids)
        for languages in ids.values():
            size += 16 + 8 * len(languages)
    for value in strings:
        try:
            code_units = len(value.encode("utf-16le")) // 2
        except UnicodeEncodeError as exc:
            raise ElectronNativeReceiptError("invalid resource string for serialization") from exc
        size += 2 + min(code_units, 65535) * 2
    size = _align(size, 8) + 16 * len(ordered)
    for entry in ordered:
        size = _align(size, 8) + len(entry.data)
    return size


def _expected_resedit_rsrc_raw_size(
    *,
    source_raw_size: int,
    final_virtual_size: int,
    file_alignment: int,
    source_leaves: Mapping[tuple[str | int, ...], _ResourceLeaf],
    final_leaves: Mapping[tuple[str | int, ...], _ResourceLeaf],
) -> int:
    """Model Electron Builder's ASAR-integrity then icon/version resource passes."""
    if any(path[:2] == ("INTEGRITY", "ELECTRONASAR") for path in source_leaves):
        raise ElectronNativeReceiptError(
            "pinned archive unexpectedly has an Electron ASAR integrity resource"
        )
    integrity = [
        leaf
        for path, leaf in final_leaves.items()
        if path[:2] == ("INTEGRITY", "ELECTRONASAR")
    ]
    if len(integrity) != 1:
        raise ElectronNativeReceiptError(
            "final executable must have one Electron ASAR integrity resource"
        )
    first_pass_virtual_size = _serialized_resource_size(
        (*source_leaves.values(), integrity[0])
    )
    return max(
        source_raw_size,
        _align(first_pass_virtual_size, file_alignment),
        _align(final_virtual_size, file_alignment),
    )


def _version_node(raw: bytes, start: int, limit: int) -> tuple[dict[str, Any], int]:
    if start + 6 > limit:
        raise ElectronNativeReceiptError("truncated VERSIONINFO node")
    length, value_length, value_type = struct.unpack_from("<HHH", raw, start)
    end = start + length
    if length < 6 or end > limit:
        raise ElectronNativeReceiptError("invalid VERSIONINFO node length")
    cursor = start + 6
    key_end = cursor
    while key_end + 2 <= end and raw[key_end : key_end + 2] != b"\0\0":
        key_end += 2
    if key_end + 2 > end:
        raise ElectronNativeReceiptError("unterminated VERSIONINFO key")
    try:
        key = raw[cursor:key_end].decode("utf-16le")
    except UnicodeDecodeError as exc:
        raise ElectronNativeReceiptError("invalid VERSIONINFO key") from exc
    cursor = _align(key_end + 2, 4)
    value_bytes = value_length * 2 if value_type == 1 else value_length
    if cursor + value_bytes > end:
        raise ElectronNativeReceiptError("truncated VERSIONINFO value")
    value = raw[cursor : cursor + value_bytes]
    cursor = _align(cursor + value_bytes, 4)
    children: list[dict[str, Any]] = []
    while cursor < end:
        if raw[cursor:end].strip(b"\0") == b"":
            cursor = end
            break
        child, child_end = _version_node(raw, cursor, end)
        children.append(child)
        cursor = _align(child_end, 4)
    return {"key": key, "type": value_type, "value": value, "children": children}, end


def _resedit_file_version_quad(version: str) -> tuple[int, int, int, int]:
    """Reproduce resedit 1.7.2's numeric parsing of the FileVersion string."""
    values: list[int] = []
    for token in version.split(".")[:4]:
        value = int(token) if re.fullmatch(r"[0-9]+", token) else 0
        values.append(min(value, 65535))
    return tuple((values + [0, 0, 0, 0])[:4])  # type: ignore[return-value]


def _decode_version(
    raw: bytes,
) -> tuple[tuple[int, ...], tuple[int, ...], dict[str, str]]:
    root, end = _version_node(raw, 0, len(raw))
    if end != len(raw) or root["key"] != "VS_VERSION_INFO" or root["type"] != 0 or len(root["value"]) != 52:
        raise ElectronNativeReceiptError("invalid root VERSIONINFO record")
    fixed = struct.unpack("<13I", root["value"])
    if fixed[0:2] != (0xFEEF04BD, 0x10000):
        raise ElectronNativeReceiptError("invalid VS_FIXEDFILEINFO signature")
    quad = (
        fixed[2] >> 16,
        fixed[2] & 0xFFFF,
        fixed[3] >> 16,
        fixed[3] & 0xFFFF,
    )
    product_quad = (
        fixed[4] >> 16,
        fixed[4] & 0xFFFF,
        fixed[5] >> 16,
        fixed[5] & 0xFFFF,
    )
    if fixed[6:] != (0x3F, 0, 0x40004, 1, 0, 0, 0):
        raise ElectronNativeReceiptError("unexpected VS_FIXEDFILEINFO semantics")
    if len(root["children"]) != 2:
        raise ElectronNativeReceiptError("VERSIONINFO must contain StringFileInfo and VarFileInfo")
    string_file, var_file = root["children"]
    if string_file["key"] != "StringFileInfo" or string_file["value"] or len(string_file["children"]) != 1:
        raise ElectronNativeReceiptError("invalid StringFileInfo")
    table = string_file["children"][0]
    if table["key"].casefold() != "040904b0" or table["value"]:
        raise ElectronNativeReceiptError("VERSIONINFO language/codepage drifted")
    strings: dict[str, str] = {}
    for child in table["children"]:
        if child["type"] != 1 or child["children"] or child["key"] in strings:
            raise ElectronNativeReceiptError("invalid VERSIONINFO string entry")
        try:
            text = child["value"].decode("utf-16le")
        except UnicodeDecodeError as exc:
            raise ElectronNativeReceiptError("invalid VERSIONINFO string value") from exc
        if not text.endswith("\0") or "\0" in text[:-1]:
            raise ElectronNativeReceiptError("invalid VERSIONINFO string terminator")
        strings[child["key"]] = text[:-1]
    if var_file["key"] != "VarFileInfo" or var_file["value"] or len(var_file["children"]) != 1:
        raise ElectronNativeReceiptError("invalid VarFileInfo")
    translation = var_file["children"][0]
    if translation["key"] != "Translation" or translation["value"] != struct.pack("<HH", 1033, 1200) or translation["children"]:
        raise ElectronNativeReceiptError("VERSIONINFO translation drifted")
    return quad, product_quad, strings


def _asar_header_sha256(raw: bytes) -> str:
    if len(raw) < 16:
        raise ElectronNativeReceiptError("final Electron app.asar is truncated")
    size_pickle, header_pickle, header_payload, header_bytes = struct.unpack_from(
        "<IIII", raw, 0
    )
    if (
        size_pickle != 4
        or header_payload != header_bytes + 4
        or header_pickle != header_bytes + 8
        or 16 + header_bytes > len(raw)
    ):
        raise ElectronNativeReceiptError("final Electron app.asar has invalid header pickle")
    header = raw[16 : 16 + header_bytes]
    try:
        decoded = header.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ElectronNativeReceiptError("final Electron app.asar header is invalid JSON") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("files"), dict):
        raise ElectronNativeReceiptError("final Electron app.asar header has no file tree")
    return _sha256(header)


def _packed_asar_paths(app_root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    try:
        for directory, directory_names, file_names in os.walk(
            app_root, topdown=True, followlinks=False
        ):
            directory_names.sort()
            file_names.sort()
            base = Path(directory)
            for name in file_names:
                if not name.casefold().endswith(".asar"):
                    continue
                relative = (base / name).relative_to(app_root).as_posix()
                relative = _safe_relative(relative)
                folded = relative.casefold()
                if folded in seen:
                    raise ElectronNativeReceiptError(
                        f"packed Electron ASAR path collides by case: {relative}"
                    )
                seen.add(folded)
                paths.append(relative)
    except ElectronNativeReceiptError:
        raise
    except (OSError, ValueError) as exc:
        raise ElectronNativeReceiptError(
            f"cannot enumerate packed Electron ASAR files: {exc}"
        ) from exc
    return tuple(sorted(paths, key=str.casefold))


def _validate_asar_integrity(
    integrity: object, app_root: Path
) -> list[dict[str, Any]]:
    if not isinstance(integrity, list) or not integrity:
        raise ElectronNativeReceiptError("Electron ASAR integrity resource must be nonempty")
    entries: dict[str, dict[str, str]] = {}
    for entry in integrity:
        if not isinstance(entry, dict) or set(entry) != {"alg", "file", "value"}:
            raise ElectronNativeReceiptError("Electron ASAR integrity entry has wrong fields")
        raw_path = entry.get("file")
        if (
            not isinstance(raw_path, str)
            or not raw_path.startswith("resources\\")
            or "/" in raw_path
            or raw_path.endswith("\\")
            or "\\\\" in raw_path
        ):
            raise ElectronNativeReceiptError("Electron ASAR integrity path is not canonical")
        relative = _safe_relative(raw_path.replace("\\", "/"))
        if not relative.casefold().endswith(".asar"):
            raise ElectronNativeReceiptError("Electron ASAR integrity path is not an ASAR")
        folded = relative.casefold()
        if folded in entries:
            raise ElectronNativeReceiptError("Electron ASAR integrity has duplicate paths")
        if entry.get("alg") != "SHA256":
            raise ElectronNativeReceiptError("Electron ASAR integrity algorithm drifted")
        entries[folded] = {
            "file": relative,
            "value": _require_sha(entry.get("value"), "Electron ASAR header"),
        }

    packed_paths = _packed_asar_paths(app_root)
    if {path.casefold() for path in packed_paths} != set(entries):
        raise ElectronNativeReceiptError(
            "Electron ASAR integrity inventory does not match packed ASAR files"
        )
    profiles: list[dict[str, Any]] = []
    for relative in packed_paths:
        expected = entries[relative.casefold()]
        if expected["file"] != relative:
            raise ElectronNativeReceiptError("Electron ASAR integrity path case drifted")
        asar = _read_regular(
            app_root / PurePosixPath(relative),
            f"final Electron ASAR {relative}",
        )
        header_sha256 = _asar_header_sha256(asar.raw)
        if expected["value"] != header_sha256:
            raise ElectronNativeReceiptError(
                f"Electron ASAR integrity does not bind {relative}"
            )
        profiles.append(
            {
                "bytes": len(asar.raw),
                "header_sha256": header_sha256,
                "path": relative,
                "sha256": asar.sha256,
            }
        )
    return profiles


def _validate_windows_resources(
    source: _PeImage,
    final: _PeImage,
    icon_raw: bytes,
    configuration: Mapping[str, Any],
    app_root: Path,
    *,
    source_leaves: Mapping[tuple[str | int, ...], _ResourceLeaf] | None = None,
    final_leaves: Mapping[tuple[str | int, ...], _ResourceLeaf] | None = None,
) -> dict[str, Any]:
    source_leaves = (
        dict(source_leaves) if source_leaves is not None else _resource_leaves(source)
    )
    final_leaves = (
        dict(final_leaves)
        if final_leaves is not None
        else _resource_leaves(final, require_exact_extent=True)
    )
    retained = {
        path: leaf
        for path, leaf in source_leaves.items()
        if path[0] not in {3, 14, 16}
    }
    expected_paths = set(retained)
    icon_payloads, group_icon = _icon_payloads(icon_raw)
    expected_paths.update((3, index + 1, 1033) for index in range(len(icon_payloads)))
    expected_paths.update({(14, 1, 1033), (16, 1, 1033), ("INTEGRITY", "ELECTRONASAR", 1033)})
    if set(final_leaves) != expected_paths:
        missing = sorted(map(str, expected_paths - set(final_leaves)))
        unexpected = sorted(map(str, set(final_leaves) - expected_paths))
        raise ElectronNativeReceiptError(
            "final PE resource paths drifted"
            + ("; missing " + ", ".join(missing) if missing else "")
            + ("; unexpected " + ", ".join(unexpected) if unexpected else "")
        )
    for path, leaf in retained.items():
        actual = final_leaves[path]
        if actual.codepage != leaf.codepage or actual.data != leaf.data:
            raise ElectronNativeReceiptError(f"retained Electron resource changed: {path}")
    icon_hashes: list[str] = []
    for index, payload in enumerate(icon_payloads, 1):
        leaf = final_leaves[(3, index, 1033)]
        if leaf.codepage != 0 or leaf.data != payload:
            raise ElectronNativeReceiptError(f"configured icon image changed: {index}")
        icon_hashes.append(_sha256(payload))
    group_leaf = final_leaves[(14, 1, 1033)]
    if group_leaf.codepage != 0 or group_leaf.data != group_icon:
        raise ElectronNativeReceiptError("configured icon group changed")
    version_leaf = final_leaves[(16, 1, 1033)]
    if version_leaf.codepage != 1200:
        raise ElectronNativeReceiptError("VERSIONINFO codepage drifted")
    file_quad, product_quad, strings = _decode_version(version_leaf.data)
    expected_file_quad = _resedit_file_version_quad(configuration["version"])
    expected_product_quad = tuple(configuration["version_quad"])
    expected_strings = {
        # electron-builder 26.15.3 reads author.name, while this package uses
        # the accepted string author form. rcedit therefore retains the pinned
        # Electron executable's CompanyName instead of rewriting that field.
        "CompanyName": "GitHub, Inc.",
        "FileDescription": PRODUCT_NAME,
        "FileVersion": configuration["version"],
        "InternalName": PRODUCT_NAME,
        "LegalCopyright": COPYRIGHT,
        "OriginalFilename": "",
        "ProductName": PRODUCT_NAME,
        "ProductVersion": ".".join(map(str, expected_product_quad)),
        "SquirrelAwareVersion": "1",
    }
    if file_quad != expected_file_quad:
        raise ElectronNativeReceiptError(
            f"configured VERSIONINFO fixed file version quad drifted: "
            f"expected {expected_file_quad}, got {file_quad}"
        )
    if product_quad != expected_product_quad:
        raise ElectronNativeReceiptError(
            f"configured VERSIONINFO fixed product version quad drifted: "
            f"expected {expected_product_quad}, got {product_quad}"
        )
    missing_fields = sorted(set(expected_strings) - set(strings))
    if missing_fields:
        raise ElectronNativeReceiptError(
            f"configured VERSIONINFO field missing: {missing_fields[0]}"
        )
    unexpected_fields = sorted(set(strings) - set(expected_strings))
    if unexpected_fields:
        raise ElectronNativeReceiptError(
            f"configured VERSIONINFO field unexpected: {unexpected_fields[0]}"
        )
    for field, expected in expected_strings.items():
        if strings[field] != expected:
            raise ElectronNativeReceiptError(
                f"configured VERSIONINFO field drifted: {field}"
            )
    integrity_leaf = final_leaves[("INTEGRITY", "ELECTRONASAR", 1033)]
    if integrity_leaf.codepage != 1200:
        raise ElectronNativeReceiptError("Electron ASAR integrity codepage drifted")
    integrity = _decode_json(integrity_leaf.data, "Electron ASAR integrity resource")
    asar_profiles = _validate_asar_integrity(integrity, app_root)
    primary = next(
        (profile for profile in asar_profiles if profile["path"] == "resources/app.asar"),
        None,
    )
    if primary is None:
        raise ElectronNativeReceiptError("packed Electron app.asar is missing")
    return {
        "asar_bytes": primary["bytes"],
        "asar_header_sha256": primary["header_sha256"],
        "asar_sha256": primary["sha256"],
        "asars": asar_profiles,
        "icon_image_sha256": icon_hashes,
        "resource_paths": [list(path) for path in sorted(final_leaves, key=lambda p: tuple(str(x) for x in p))],
        "version_strings": strings,
    }


def _windows_root_transformation(
    source_raw: bytes,
    final_raw: bytes,
    icon_raw: bytes,
    configuration: Mapping[str, Any],
    app_root: Path,
) -> tuple[bytes, dict[str, Any]]:
    source_signed = _parse_pe(source_raw, "archive electron.exe")
    final_signed = _parse_pe(final_raw, "final AutoEditor Helper.exe")
    source_normalized, source_signature = _normalized_pe(source_signed)
    final_normalized, final_signature = _normalized_pe(final_signed)
    source = _parse_pe(source_normalized, "normalized archive electron.exe")
    final = _parse_pe(final_normalized, "normalized final AutoEditor Helper.exe")
    if source_signed.certificate_bytes:
        raise ElectronNativeReceiptError("pinned archive electron.exe unexpectedly has Authenticode")
    source_layout = (
        source.pe_offset,
        source.optional_offset,
        source.optional_size,
        source.size_of_headers,
        source.section_alignment,
        source.file_alignment,
    )
    final_layout = (
        final.pe_offset,
        final.optional_offset,
        final.optional_size,
        final.size_of_headers,
        final.section_alignment,
        final.file_alignment,
    )
    if final_layout != source_layout:
        raise ElectronNativeReceiptError("rcedit changed the core PE layout")
    source_names = [section.name for section in source.sections]
    final_names = [section.name for section in final.sections]
    if source_names != final_names or source_names.count(".rsrc") != 1 or source_names.count(".reloc") != 1:
        raise ElectronNativeReceiptError("rcedit changed the PE section identity or ordering")
    source_rsrc = _section(source, ".rsrc")
    final_rsrc = _section(final, ".rsrc")
    source_reloc = _section(source, ".reloc")
    final_reloc = _section(final, ".reloc")
    source_leaves = _resource_leaves(source)
    final_leaves = _resource_leaves(final, require_exact_extent=True)
    if (
        final_rsrc.virtual_address != source_rsrc.virtual_address
        or final_rsrc.raw_pointer != source_rsrc.raw_pointer
        or final_rsrc.reloc_pointer != source_rsrc.reloc_pointer
        or final_rsrc.line_pointer != source_rsrc.line_pointer
        or final_rsrc.relocation_count != source_rsrc.relocation_count
        or final_rsrc.line_count != source_rsrc.line_count
        or final_rsrc.characteristics != source_rsrc.characteristics
    ):
        raise ElectronNativeReceiptError("rcedit changed non-resource .rsrc layout fields")
    expected_rsrc_raw_size = _expected_resedit_rsrc_raw_size(
        source_raw_size=source_rsrc.raw_size,
        final_virtual_size=final_rsrc.virtual_size,
        file_alignment=final.file_alignment,
        source_leaves=source_leaves,
        final_leaves=final_leaves,
    )
    if final_rsrc.raw_size != expected_rsrc_raw_size:
        raise ElectronNativeReceiptError(
            "rcedit .rsrc raw allocation is not determined by generated resources"
        )
    raw_growth = final_rsrc.raw_size - source_rsrc.raw_size
    if len(final_normalized) != len(source_normalized) + raw_growth:
        raise ElectronNativeReceiptError(
            "rcedit executable byte growth is not the exact .rsrc raw growth"
        )
    if (
        final_reloc.virtual_size != source_reloc.virtual_size
        or final_reloc.raw_size != source_reloc.raw_size
        or final_reloc.reloc_pointer != source_reloc.reloc_pointer
        or final_reloc.line_pointer != source_reloc.line_pointer
        or final_reloc.relocation_count != source_reloc.relocation_count
        or final_reloc.line_count != source_reloc.line_count
        or final_reloc.characteristics != source_reloc.characteristics
    ):
        raise ElectronNativeReceiptError("rcedit changed non-address .reloc layout fields")
    if final_reloc.raw_pointer != source_reloc.raw_pointer + raw_growth:
        raise ElectronNativeReceiptError(
            "rcedit relocation raw address is not determined by .rsrc growth"
        )
    source_virtual_span = _align(source_rsrc.virtual_size, source.section_alignment)
    final_virtual_span = _align(final_rsrc.virtual_size, final.section_alignment)
    expected_reloc_virtual_address = (
        source_reloc.virtual_address + final_virtual_span - source_virtual_span
    )
    if (
        final_reloc.virtual_address != expected_reloc_virtual_address
        or final_reloc.virtual_address
        != _align(
            final_rsrc.virtual_address + final_rsrc.virtual_size,
            final.section_alignment,
        )
    ):
        raise ElectronNativeReceiptError("rcedit .reloc address is not determined by final .rsrc")
    expected_image_size = _align(
        final_reloc.virtual_address + final_reloc.virtual_size,
        final.section_alignment,
    )
    if struct.unpack_from("<I", final.raw, final.optional_offset + 56)[0] != expected_image_size:
        raise ElectronNativeReceiptError("rcedit SizeOfImage is not determined by final section layout")
    if final.directories[2] != (final_rsrc.virtual_address, final_rsrc.virtual_size):
        raise ElectronNativeReceiptError("rcedit resource directory does not match final .rsrc")
    if final.directories[5] != (final_reloc.virtual_address, source.directories[5][1]):
        raise ElectronNativeReceiptError("rcedit relocation directory is not the exact shifted source directory")

    derived_header_offsets = {
        final.optional_offset + 56,
        final.directory_offset + 2 * 8 + 4,
        final.directory_offset + 5 * 8,
        final_rsrc.header_offset + 8,
        final_rsrc.header_offset + 16,
        final_reloc.header_offset + 12,
        final_reloc.header_offset + 20,
    }
    reconstructed = bytearray(source.raw[: source_rsrc.raw_pointer])
    reconstructed.extend(
        final.raw[
            final_rsrc.raw_pointer : final_rsrc.raw_pointer + final_rsrc.raw_size
        ]
    )
    reconstructed.extend(
        source.raw[source_rsrc.raw_pointer + source_rsrc.raw_size :]
    )
    for offset in derived_header_offsets:
        reconstructed[offset : offset + 4] = final.raw[offset : offset + 4]
    if bytes(reconstructed) != final.raw:
        raise ElectronNativeReceiptError(
            "rcedit changed bytes outside the exact resource rewrite"
        )
    resource_profile = _validate_windows_resources(
        source,
        final,
        icon_raw,
        configuration,
        app_root,
        source_leaves=source_leaves,
        final_leaves=final_leaves,
    )
    source_imports = {
        "imports": _imports(source, 1, delay=False),
        "delay_imports": _imports(source, 13, delay=True),
    }
    final_imports = {
        "imports": _imports(final, 1, delay=False),
        "delay_imports": _imports(final, 13, delay=True),
    }
    if final_imports != source_imports:
        raise ElectronNativeReceiptError("rcedit changed the Electron import contract")
    return final_normalized, {
        "final_pe": _pe_profile(final, final_normalized),
        "resource_edit": resource_profile,
        "signature": final_signature,
        "source_pe": _pe_profile(source, source_normalized),
        "source_signature": source_signature,
        "transformation": "electron-builder-26.15.3-resedit-plus-terminal-authenticode",
    }


def _windows_identical_transformation(
    source_raw: bytes,
    final_raw: bytes,
    label: str,
) -> tuple[bytes, dict[str, Any]]:
    source_signed = _parse_pe(source_raw, f"archive {label}")
    final_signed = _parse_pe(final_raw, f"final {label}")
    source_normalized, source_signature = _normalized_pe(source_signed)
    final_normalized, final_signature = _normalized_pe(final_signed)
    if source_normalized != final_normalized:
        raise ElectronNativeReceiptError(f"final {label} differs from the pinned archive outside Authenticode")
    final_image = _parse_pe(final_normalized, f"normalized final {label}")
    return final_normalized, {
        "final_pe": _pe_profile(final_image, final_normalized),
        "signature": final_signature,
        "source_signature": source_signature,
        "transformation": "byte-identical-plus-terminal-authenticode",
    }


def _codesign_verify_standalone(raw: bytes, label: str) -> None:
    if sys.platform != "darwin" or not Path("/usr/bin/codesign").is_file():
        raise ElectronNativeReceiptError("strict macOS codesign verification requires macOS")
    with tempfile.TemporaryDirectory(prefix="autoeditor-electron-codesign-") as temporary:
        path = Path(temporary) / "binary"
        path.write_bytes(raw)
        path.chmod(0o755)
        completed = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ElectronNativeReceiptError(f"strict codesign verification failed for {label}: {detail}")


def _codesign_verify_app(app_root: Path) -> None:
    if sys.platform != "darwin" or not Path("/usr/bin/codesign").is_file():
        raise ElectronNativeReceiptError("strict macOS codesign verification requires macOS")
    completed = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ElectronNativeReceiptError(f"strict codesign verification failed for final app: {detail}")


def _macho_canonical(raw: bytes, target: str, label: str) -> tuple[bytes, dict[str, Any]]:
    if len(raw) < 32 or raw[:4] != b"\xcf\xfa\xed\xfe":
        raise ElectronNativeReceiptError(f"{label} is not a thin little-endian 64-bit Mach-O")
    cpu_type, cpu_subtype, file_type, command_count, command_bytes, flags, reserved = struct.unpack_from(
        "<IIIIIII", raw, 4
    )
    expected_cpu = 0x0100000C if target == "mac-arm64" else 0x01000007
    page_size = 0x4000 if target == "mac-arm64" else 0x1000
    if cpu_type != expected_cpu or command_count <= 0 or command_count > 4096 or command_bytes < command_count * 8:
        raise ElectronNativeReceiptError(f"{label} has invalid Mach-O header semantics")
    command_end = 32 + command_bytes
    if command_end > len(raw):
        raise ElectronNativeReceiptError(f"{label} has truncated Mach-O load commands")
    cursor = 32
    linkedit_offset: int | None = None
    linkedit: tuple[int, int, int, int] | None = None
    code_signature_offset: int | None = None
    code_signature: tuple[int, int] | None = None
    command_profile: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for index in range(command_count):
        command, size = struct.unpack_from("<II", raw, cursor)
        if size < 8 or size % 8 or cursor + size > command_end:
            raise ElectronNativeReceiptError(f"{label} has invalid Mach-O load command bounds")
        command_raw = raw[cursor : cursor + size]
        if command == 0x19:
            if size < 72:
                raise ElectronNativeReceiptError(f"{label} has truncated LC_SEGMENT_64")
            name = command_raw[8:24].split(b"\0", 1)[0].decode("ascii")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", command_raw, 24)
            maxprot, initprot, section_count, segment_flags = struct.unpack_from("<IIII", command_raw, 56)
            if size != 72 + section_count * 80 or fileoff + filesize > len(raw):
                raise ElectronNativeReceiptError(f"{label} has invalid Mach-O segment semantics")
            sections: list[dict[str, Any]] = []
            for section_index in range(section_count):
                offset = 72 + section_index * 80
                section_name = command_raw[offset : offset + 16].split(b"\0", 1)[0].decode("ascii")
                segment_name = command_raw[offset + 16 : offset + 32].split(b"\0", 1)[0].decode("ascii")
                address, section_bytes = struct.unpack_from("<QQ", command_raw, offset + 32)
                file_offset, alignment, reloc_offset, reloc_count, section_flags = struct.unpack_from(
                    "<IIIII", command_raw, offset + 48
                )
                if section_bytes and file_offset + section_bytes > len(raw):
                    raise ElectronNativeReceiptError(f"{label} has invalid Mach-O section bounds")
                sections.append(
                    {
                        "address": address,
                        "alignment": alignment,
                        "bytes": section_bytes,
                        "content_sha256": _sha256(raw[file_offset : file_offset + section_bytes]),
                        "file_offset": file_offset,
                        "flags": section_flags,
                        "name": section_name,
                        "relocation_count": reloc_count,
                        "relocation_offset": reloc_offset,
                        "segment": segment_name,
                    }
                )
            segment = {
                "file_bytes": filesize,
                "file_offset": fileoff,
                "flags": segment_flags,
                "init_protection": initprot,
                "max_protection": maxprot,
                "name": name,
                "sections": sections,
                "virtual_address": vmaddr,
                "virtual_bytes": vmsize,
            }
            segments.append(segment)
            if name == "__LINKEDIT":
                if linkedit is not None:
                    raise ElectronNativeReceiptError(f"{label} has duplicate __LINKEDIT segments")
                linkedit_offset = cursor
                linkedit = (vmaddr, vmsize, fileoff, filesize)
            elif linkedit is not None:
                raise ElectronNativeReceiptError(f"{label} has a segment after terminal __LINKEDIT")
        elif command == 0x1D:
            if size != 16 or index != command_count - 1 or code_signature is not None:
                raise ElectronNativeReceiptError(f"{label} must have one terminal LC_CODE_SIGNATURE")
            dataoff, datasize = struct.unpack_from("<II", command_raw, 8)
            code_signature_offset = cursor
            code_signature = (dataoff, datasize)
        command_profile.append({"command": command, "index": index, "raw_sha256": _sha256(command_raw), "size": size})
        cursor += size
    if cursor != command_end or linkedit is None or linkedit_offset is None or code_signature is None or code_signature_offset is None:
        raise ElectronNativeReceiptError(f"{label} lacks the exact signature normalization commands")
    vmaddr, vmsize, fileoff, filesize = linkedit
    dataoff, datasize = code_signature
    if dataoff + datasize != len(raw) or fileoff + filesize != len(raw) or dataoff < fileoff:
        raise ElectronNativeReceiptError(f"{label} code signature is not the terminal __LINKEDIT allocation")
    unsigned_linkedit_bytes = dataoff - fileoff
    canonical_vmsize = _align(unsigned_linkedit_bytes, page_size)
    canonical = bytearray(raw[:dataoff])
    struct.pack_into("<Q", canonical, linkedit_offset + 32, canonical_vmsize)
    struct.pack_into("<Q", canonical, linkedit_offset + 48, unsigned_linkedit_bytes)
    struct.pack_into("<I", canonical, code_signature_offset + 12, 0)
    profile = {
        "canonical_linkedit_bytes": unsigned_linkedit_bytes,
        "canonical_linkedit_virtual_bytes": canonical_vmsize,
        "code_signature_bytes": datasize,
        "code_signature_offset": dataoff,
        "code_signature_sha256": _sha256(raw[dataoff:]),
        "command_count": command_count,
        "commands_sha256": _sha256(raw[32:command_end]),
        "cpu_subtype": cpu_subtype,
        "cpu_type": cpu_type,
        "file_type": file_type,
        "flags": flags,
        "raw_linkedit_bytes": filesize,
        "raw_linkedit_virtual_bytes": vmsize,
        "reserved": reserved,
        "segments": segments,
    }
    return bytes(canonical), profile


def _unsigned_archive_macho_canonical(
    raw: bytes,
    target: str,
    label: str,
) -> tuple[bytes, dict[str, Any]]:
    """Canonicalize the authenticated unsigned Intel archive as codesign does."""
    if target != "mac-x64" or len(raw) < 32 or raw[:4] != b"\xcf\xfa\xed\xfe":
        raise ElectronNativeReceiptError(
            f"{label} is not the expected unsigned Intel Mach-O"
        )
    (
        cpu_type,
        _cpu_subtype,
        _file_type,
        command_count,
        command_bytes,
        _flags,
        _reserved,
    ) = struct.unpack_from("<IIIIIII", raw, 4)
    if (
        cpu_type != 0x01000007
        or command_count <= 0
        or command_count > 4096
        or command_bytes < command_count * 8
    ):
        raise ElectronNativeReceiptError(
            f"{label} has invalid unsigned Mach-O header semantics"
        )
    command_end = 32 + command_bytes
    if command_end + 16 > len(raw) or any(raw[command_end : command_end + 16]):
        raise ElectronNativeReceiptError(
            f"{label} lacks the exact zero command slot used by codesign"
        )
    cursor = 32
    linkedit_offset = None
    linkedit = None
    for _ in range(command_count):
        command, size = struct.unpack_from("<II", raw, cursor)
        if size < 8 or size % 8 or cursor + size > command_end:
            raise ElectronNativeReceiptError(
                f"{label} has invalid unsigned Mach-O command bounds"
            )
        if command == 0x1D:
            raise ElectronNativeReceiptError(
                f"{label} unexpectedly contains LC_CODE_SIGNATURE"
            )
        if command == 0x19:
            if size < 72:
                raise ElectronNativeReceiptError(
                    f"{label} has truncated unsigned LC_SEGMENT_64"
                )
            name = raw[cursor + 8 : cursor + 24].split(b"\0", 1)[0]
            if name == b"__LINKEDIT":
                if linkedit is not None:
                    raise ElectronNativeReceiptError(
                        f"{label} has duplicate unsigned __LINKEDIT segments"
                    )
                _vmaddr, vmsize, fileoff, filesize = struct.unpack_from(
                    "<QQQQ", raw, cursor + 24
                )
                linkedit_offset = cursor
                linkedit = (vmsize, fileoff, filesize)
        cursor += size
    if cursor != command_end or linkedit is None or linkedit_offset is None:
        raise ElectronNativeReceiptError(
            f"{label} lacks the unsigned __LINKEDIT segment"
        )
    vmsize, fileoff, filesize = linkedit
    page_size = 0x1000
    if (
        filesize <= 0
        or fileoff + filesize != len(raw)
        or vmsize % page_size
        or vmsize < _align(filesize, page_size)
    ):
        raise ElectronNativeReceiptError(
            f"{label} has noncanonical unsigned __LINKEDIT geometry"
        )

    signature_offset = _align(len(raw), 16)
    synthetic = bytearray(raw)
    synthetic.extend(b"\0" * (signature_offset - len(synthetic)))
    synthetic.extend(b"\0" * 16)
    struct.pack_into(
        "<II", synthetic, 16, command_count + 1, command_bytes + 16
    )
    struct.pack_into(
        "<IIII",
        synthetic,
        command_end,
        0x1D,
        16,
        signature_offset,
        16,
    )
    signed_linkedit_bytes = signature_offset + 16 - fileoff
    struct.pack_into(
        "<Q",
        synthetic,
        linkedit_offset + 32,
        _align(signed_linkedit_bytes, page_size),
    )
    struct.pack_into(
        "<Q", synthetic, linkedit_offset + 48, signed_linkedit_bytes
    )
    canonical, profile = _macho_canonical(
        bytes(synthetic), target, label
    )
    profile["archive_signature"] = "absent-authenticated-by-archive-sha256"
    profile["archive_unsigned_bytes"] = len(raw)
    return canonical, profile


def _mac_transformation(
    source_raw: bytes,
    final_raw: bytes,
    target: str,
    source_name: str,
    final_name: str,
) -> tuple[bytes, dict[str, Any]]:
    if target == "mac-x64":
        source_canonical, source_profile = (
            _unsigned_archive_macho_canonical(
                source_raw, target, f"archive {source_name}"
            )
        )
        transformation = (
            "authenticated-unsigned-archive-plus-codesign-allocation-"
            "and-terminal-linkedit-page-rounding"
        )
    else:
        _codesign_verify_standalone(source_raw, f"archive {source_name}")
        source_canonical, source_profile = _macho_canonical(
            source_raw, target, f"archive {source_name}"
        )
        transformation = (
            "codesign-allocation-plus-terminal-linkedit-page-rounding"
        )
    final_canonical, final_profile = _macho_canonical(final_raw, target, f"final {final_name}")
    if source_canonical != final_canonical:
        raise ElectronNativeReceiptError(
            f"final {final_name} differs from archive {source_name} outside signature allocation and terminal __LINKEDIT rounding"
        )
    return final_canonical, {
        "final_macho": final_profile,
        "source_macho": source_profile,
        "transformation": transformation,
    }


def _entry_payload(
    *,
    source_path: str,
    final_path: str,
    source: _FileData,
    final: _FileData,
    canonical: bytes,
    details: Mapping[str, Any],
    target: str,
) -> dict[str, Any]:
    return {
        "canonical_bytes": len(canonical),
        "canonical_sha256": _sha256(canonical),
        "component": _component(final_path, target),
        "final": {
            "bytes": len(final.raw),
            "mode": final.mode,
            "sha256": final.sha256,
        },
        "mapping": {
            "archive_path": source_path,
            "final_path": final_path,
        },
        "normalization": dict(details),
        "source": {
            "bytes": len(source.raw),
            "mode": source.mode,
            "sha256": source.sha256,
        },
    }


def create_receipt(
    *,
    app_root: Path,
    target: str,
    electron_archive: Path,
    source_lock: Path,
    builder_config: Path,
    package_json: Path,
    icon: Path,
    version: str,
) -> dict[str, Any]:
    mappings = _mappings(target)
    _, lock_data = _load_source_lock(source_lock, target)
    configuration = _load_configuration(
        builder_config,
        package_json,
        icon,
        version,
    )
    icon_data = _read_regular(icon, "configured Windows icon", MAX_RECEIPT_BYTES)
    archive_members, archive_data = _archive_members(electron_archive, target)
    try:
        root_stat = app_root.lstat()
    except OSError as exc:
        raise ElectronNativeReceiptError(f"cannot inspect final app root: {exc}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ElectronNativeReceiptError("final app root must be a real directory")
    if target != "windows-x64":
        _codesign_verify_app(app_root)
    files: dict[str, Any] = {}
    seen_casefold: set[str] = set()
    for source_path, final_path in mappings:
        _safe_relative(source_path)
        _safe_relative(final_path)
        folded = final_path.casefold()
        if folded in seen_casefold:
            raise ElectronNativeReceiptError("Electron final mapping has a case-insensitive collision")
        seen_casefold.add(folded)
        source = archive_members[source_path]
        final = _read_regular(app_root / Path(*PurePosixPath(final_path).parts), f"final Electron native file {final_path}")
        if target == "windows-x64":
            if final_path == "AutoEditor Helper.exe":
                canonical, details = _windows_root_transformation(
                    source.raw,
                    final.raw,
                    icon_data.raw,
                    configuration,
                    app_root,
                )
            else:
                canonical, details = _windows_identical_transformation(
                    source.raw,
                    final.raw,
                    final_path,
                )
        else:
            canonical, details = _mac_transformation(
                source.raw,
                final.raw,
                target,
                source_path,
                final_path,
            )
        files[final_path] = _entry_payload(
            source_path=source_path,
            final_path=final_path,
            source=source,
            final=final,
            canonical=canonical,
            details=details,
            target=target,
        )
    return {
        "archive": {
            "bytes": len(archive_data.raw),
            "filename": electron_archive.name,
            "sha256": archive_data.sha256,
        },
        "configuration": configuration,
        "electron_version": ELECTRON_VERSION,
        "files": files,
        "schema": SCHEMA,
        "source_lock_sha256": lock_data.sha256,
        "target": target,
    }


def _validate_receipt_shape(payload: object, target: str) -> dict[str, Any]:
    root = _require_exact_keys(
        payload,
        {
            "archive",
            "configuration",
            "electron_version",
            "files",
            "schema",
            "source_lock_sha256",
            "target",
        },
        "Electron native receipt",
    )
    if root["schema"] != SCHEMA or root["electron_version"] != ELECTRON_VERSION or root["target"] != target:
        raise ElectronNativeReceiptError("Electron native receipt identity drifted")
    if root["source_lock_sha256"] != SOURCE_LOCK_SHA256:
        raise ElectronNativeReceiptError("Electron native receipt source lock drifted")
    archive = _require_exact_keys(root["archive"], {"bytes", "filename", "sha256"}, "receipt archive")
    if archive != ARCHIVE_RECORDS[target]:
        raise ElectronNativeReceiptError("Electron native receipt archive drifted")
    configuration = _require_exact_keys(
        root["configuration"],
        {
            "builder_config_sha256",
            "copyright",
            "electron_builder",
            "icon_bytes",
            "icon_sha256",
            "package_manifest_sha256",
            "product_name",
            "version",
            "version_quad",
        },
        "receipt configuration",
    )
    for key in ("builder_config_sha256", "icon_sha256", "package_manifest_sha256"):
        _require_sha(configuration[key], f"receipt configuration {key}")
    if (
        configuration["product_name"] != PRODUCT_NAME
        or configuration["copyright"] != COPYRIGHT
        or configuration["electron_builder"] != "26.15.3"
        or configuration["icon_sha256"] != ICON_SHA256
        or type(configuration["icon_bytes"]) is not int
        or configuration["icon_bytes"] <= 0
        or VERSION_RE.fullmatch(configuration["version"]) is None
        or not isinstance(configuration["version_quad"], list)
        or len(configuration["version_quad"]) != 4
        or any(type(value) is not int or value < 0 or value > 65535 for value in configuration["version_quad"])
    ):
        raise ElectronNativeReceiptError("Electron native receipt configuration is invalid")
    files = root["files"]
    if not isinstance(files, dict):
        raise ElectronNativeReceiptError("Electron native receipt files must be a mapping")
    expected_mapping = {final: source for source, final in _mappings(target)}
    if set(files) != set(expected_mapping):
        raise ElectronNativeReceiptError("Electron native receipt path set drifted")
    for final_path, entry_value in files.items():
        _safe_relative(final_path)
        entry = _require_exact_keys(
            entry_value,
            {
                "canonical_bytes",
                "canonical_sha256",
                "component",
                "final",
                "mapping",
                "normalization",
                "source",
            },
            f"receipt file {final_path}",
        )
        if entry["component"] != _component(final_path, target):
            raise ElectronNativeReceiptError(f"receipt component drifted: {final_path}")
        mapping = _require_exact_keys(entry["mapping"], {"archive_path", "final_path"}, f"receipt mapping {final_path}")
        if mapping != {"archive_path": expected_mapping[final_path], "final_path": final_path}:
            raise ElectronNativeReceiptError(f"receipt mapping drifted: {final_path}")
        for side in ("source", "final"):
            record = _require_exact_keys(entry[side], {"bytes", "mode", "sha256"}, f"receipt {side} {final_path}")
            _require_sha(record["sha256"], f"receipt {side} {final_path}")
            if type(record["bytes"]) is not int or record["bytes"] <= 0 or type(record["mode"]) is not int or not 0 <= record["mode"] <= 0o777:
                raise ElectronNativeReceiptError(f"receipt {side} metadata is invalid: {final_path}")
        _require_sha(entry["canonical_sha256"], f"receipt canonical {final_path}")
        if type(entry["canonical_bytes"]) is not int or entry["canonical_bytes"] <= 0 or not isinstance(entry["normalization"], dict):
            raise ElectronNativeReceiptError(f"receipt normalization is invalid: {final_path}")
    return root


def load_authenticated_receipt(
    path: Path,
    expected_sha256: str,
    target: str,
) -> tuple[dict[str, Any], str]:
    expected = _require_sha(expected_sha256, "Electron native receipt")
    data = _read_regular(path, "Electron native receipt", MAX_RECEIPT_BYTES)
    if data.sha256 != expected:
        raise ElectronNativeReceiptError("Electron native receipt SHA256 mismatch")
    payload = _load_json(data.raw, "Electron native receipt")
    return _validate_receipt_shape(payload, target), data.sha256


def claims_from_receipt(payload: Mapping[str, Any], target: str) -> dict[str, ElectronNativeClaim]:
    validated = _validate_receipt_shape(dict(payload), target)
    claims: dict[str, ElectronNativeClaim] = {}
    for path, entry in validated["files"].items():
        final = entry["final"]
        claims[path] = ElectronNativeClaim(
            path,
            entry["component"],
            final["sha256"],
            final["bytes"],
            final["mode"],
        )
    return claims


def validate_claim_modes(app_root: Path, payload: Mapping[str, Any], target: str) -> None:
    """Bind receipt modes to the same final tree the allowlist will scan."""
    for path, claim in claims_from_receipt(payload, target).items():
        final_path = app_root / Path(*PurePosixPath(path).parts)
        try:
            metadata = final_path.lstat()
        except OSError as exc:
            raise ElectronNativeReceiptError(f"cannot inspect final Electron claim {path}: {exc}") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != claim.byte_count
            or stat.S_IMODE(metadata.st_mode) != claim.mode
        ):
            raise ElectronNativeReceiptError(f"final Electron claim metadata drifted: {path}")


def verify_receipt(
    *,
    receipt: Path,
    expected_receipt_sha256: str,
    app_root: Path,
    target: str,
    electron_archive: Path,
    source_lock: Path,
    builder_config: Path,
    package_json: Path,
    icon: Path,
    version: str,
) -> dict[str, Any]:
    payload, _ = load_authenticated_receipt(receipt, expected_receipt_sha256, target)
    expected = create_receipt(
        app_root=app_root,
        target=target,
        electron_archive=electron_archive,
        source_lock=source_lock,
        builder_config=builder_config,
        package_json=package_json,
        icon=icon,
        version=version,
    )
    if payload != expected:
        raise ElectronNativeReceiptError("final Electron native receipt no longer matches exact app bytes")
    return payload


def _write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o644)
        created = True
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ElectronNativeReceiptError("short write for Electron native receipt")
            view = view[written:]
        os.fsync(descriptor)
    except ElectronNativeReceiptError:
        raise
    except OSError as exc:
        raise ElectronNativeReceiptError(f"cannot write Electron native receipt: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created and sys.exc_info()[0] is not None:
            try:
                path.unlink()
            except OSError:
                pass


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--target", choices=sorted(ARCHIVE_RECORDS), required=True)
    parser.add_argument("--electron-archive", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--builder-config", type=Path, required=True)
    parser.add_argument("--package-json", type=Path, required=True)
    parser.add_argument("--icon", type=Path, required=True)
    parser.add_argument("--version", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    _common_arguments(create)
    create.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    _common_arguments(verify)
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--expected-receipt-sha256", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    common = {
        "app_root": args.app_root,
        "target": args.target,
        "electron_archive": args.electron_archive,
        "source_lock": args.source_lock,
        "builder_config": args.builder_config,
        "package_json": args.package_json,
        "icon": args.icon,
        "version": args.version,
    }
    try:
        if args.command == "create":
            payload = create_receipt(**common)
            raw = canonical_json_bytes(payload)
            _write_new(args.output, raw)
            digest = _sha256(raw)
        else:
            verify_receipt(
                receipt=args.receipt,
                expected_receipt_sha256=args.expected_receipt_sha256,
                **common,
            )
            digest = _require_sha(args.expected_receipt_sha256, "Electron native receipt")
    except ElectronNativeReceiptError as exc:
        raise SystemExit(str(exc)) from exc
    print(digest)


if __name__ == "__main__":
    main()
