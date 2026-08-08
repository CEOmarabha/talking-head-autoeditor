#!/usr/bin/env python3
"""Create and verify the immutable input closure for an llvm-mingw link."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import struct
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import verify_windows_ffmpeg as windows_verifier


SCHEMA = "autoeditor-windows-ffmpeg-linkage/v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PROGRAMS = {"ffmpeg": "ffmpeg_g.exe", "ffprobe": "ffprobe_g.exe"}
FFMPEG_SOURCE_ROOT = (
    "build/autoeditor-media/sources/"
    "FFmpeg-9b6c8969e05b4f0b29f0f85cd501be6b3e582e6b/"
)
BUILD_ONLY_SOURCE_IDS = {"llvm-mingw", "nasm"}
EXPECTED_CODE_SOURCE_IDS = {
    "ffmpeg", "llvm-project", "mingw-w64", "x264", "zlib",
}
MAP_INPUT_RE = re.compile(
    r"^[0-9A-Fa-f]{8,16} [0-9A-Fa-f]{8,16}\s+\d+\s{9}(.+):\(([^()]*)\)$"
)
VERBOSE_MEMBER_RE = re.compile(
    r"\b(?P<event>Loaded|Reading)\s+(?P<archive>[^\s()]+)"
    r"\((?P<member>[^()]+)\)(?:\s+for\s+(?P<reason>.+))?$"
)
ARCHIVE_MAGIC = b"!<arch>\n"
COFF_AMD64 = 0x8664
COFF_SYMBOL_BYTES = 18
COFF_STORAGE_EXTERNAL = 2
COFF_STORAGE_WEAK_EXTERNAL = 105


class LinkageError(ValueError):
    """The captured link does not satisfy the closed-input contract."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_regular(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise LinkageError(f"cannot inspect {label} {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise LinkageError(f"{label} must be a regular file, not a symlink")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LinkageError(f"cannot read {label} {path}: {exc}") from exc


def _decode_text(raw: bytes, label: str) -> str:
    if b"\r" in raw:
        raise LinkageError(f"{label} must use LF line endings")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LinkageError(f"{label} must be UTF-8: {exc}") from exc


def _safe_tar_name(name: str) -> PurePosixPath:
    if "\\" in name:
        raise LinkageError(f"reproducer member uses a backslash: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise LinkageError(f"unsafe reproducer member path: {name}")
    return path


def _origin_for(path: str) -> tuple[str, str]:
    name = PurePosixPath(path).name
    if path.startswith(FFMPEG_SOURCE_ROOT):
        if name.endswith(".a"):
            return "ffmpeg", "project-static-archive"
        if name.endswith((".o", ".obj", ".res")):
            return "ffmpeg", "project-object"
        raise LinkageError(f"undeclared FFmpeg link input: {path}")
    if path == "build/autoeditor-media/prefix/lib/libx264.a":
        return "x264", "project-static-archive"
    if path == "build/autoeditor-media/prefix/lib/libz.a":
        return "zlib", "project-static-archive"
    if path.startswith("build/autoeditor-media/prefix/"):
        raise LinkageError(f"undeclared prefix link input: {path}")
    if path.startswith("opt/llvm-mingw/lib/clang/22/lib/windows/"):
        if not name.endswith(".a"):
            raise LinkageError(f"undeclared compiler runtime link input: {path}")
        return "llvm-project", "toolchain-runtime-static-archive"
    if path.startswith("opt/llvm-mingw/lib/clang/"):
        raise LinkageError(f"undeclared compiler runtime link input: {path}")
    if path.startswith("opt/llvm-mingw/x86_64-w64-mingw32/lib/"):
        if name.startswith(("libunwind", "libc++", "libcxx")):
            if not name.endswith(".a"):
                raise LinkageError(f"undeclared LLVM runtime link input: {path}")
            return "llvm-project", "toolchain-runtime-static-archive"
        if re.fullmatch(r"(?:dll)?crt(?:begin|end|2u?|1u?)\.o", name, re.IGNORECASE):
            return "mingw-w64", "toolchain-startup-object"
        if name.endswith(".a"):
            return "mingw-w64", "toolchain-static-or-import-archive"
        raise LinkageError(f"undeclared MinGW link input: {path}")
    raise LinkageError(f"link input is outside every allowed source root: {path}")


def _decimal_field(raw: bytes, label: str) -> int:
    value = raw.strip()
    if not value or not value.isdigit():
        raise LinkageError(f"invalid archive {label}")
    return int(value)


def _archive_members(
    raw: bytes, archive_path: str
) -> dict[str, list[dict[str, Any]]]:
    """Return exact members from a regular ar archive, excluding its index."""
    if not raw.startswith(ARCHIVE_MAGIC):
        raise LinkageError(f"selected input is not a regular ar archive: {archive_path}")
    offset = len(ARCHIVE_MAGIC)
    records: list[tuple[bytes, bytes]] = []
    string_table: bytes | None = None
    while offset < len(raw):
        if offset + 60 > len(raw):
            raise LinkageError(f"truncated archive header: {archive_path}")
        header = raw[offset:offset + 60]
        if header[58:60] != b"`\n":
            raise LinkageError(f"invalid archive header marker: {archive_path}")
        size = _decimal_field(header[48:58], f"member size in {archive_path}")
        data_start = offset + 60
        data_end = data_start + size
        if data_end > len(raw):
            raise LinkageError(f"truncated archive member: {archive_path}")
        raw_name = header[:16].rstrip(b" ")
        data = raw[data_start:data_end]
        if raw_name == b"//":
            if string_table is not None:
                raise LinkageError(f"duplicate archive string table: {archive_path}")
            string_table = data
        elif raw_name not in {b"/", b"/SYM64/"}:
            records.append((raw_name, data))
        offset = data_end + (size & 1)
    if offset != len(raw):
        raise LinkageError(f"invalid archive padding: {archive_path}")

    members: dict[str, list[dict[str, Any]]] = {}
    for ordinal, (raw_name, data) in enumerate(records):
        if raw_name.startswith(b"#1/"):
            name_size = _decimal_field(raw_name[3:], f"BSD name size in {archive_path}")
            if name_size > len(data):
                raise LinkageError(f"truncated BSD archive name: {archive_path}")
            name_bytes = data[:name_size].rstrip(b"\0")
            data = data[name_size:]
        elif raw_name.startswith(b"/") and raw_name[1:].isdigit():
            if string_table is None:
                raise LinkageError(f"archive member lacks string table: {archive_path}")
            name_offset = int(raw_name[1:])
            if name_offset >= len(string_table):
                raise LinkageError(f"archive string offset is invalid: {archive_path}")
            name_end = string_table.find(b"/\n", name_offset)
            if name_end < 0:
                name_end = string_table.find(b"\0", name_offset)
            if name_end < 0:
                raise LinkageError(f"unterminated archive member name: {archive_path}")
            name_bytes = string_table[name_offset:name_end]
        else:
            name_bytes = raw_name[:-1] if raw_name.endswith(b"/") else raw_name
        try:
            name = name_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LinkageError(f"archive member name is not UTF-8: {archive_path}") from exc
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise LinkageError(f"unsafe archive member name in {archive_path}: {name!r}")
        members.setdefault(name, []).append({"ordinal": ordinal, "raw": data})
    if not members:
        raise LinkageError(f"selected archive contains no object members: {archive_path}")
    return members


def _short_import_dll(raw: bytes, label: str) -> str | None:
    if len(raw) < 20:
        return None
    sig1, sig2, version, machine, _timestamp, size, _hint, _type = struct.unpack_from(
        "<HHHHIIHH", raw
    )
    if (sig1, sig2) != (0, 0xFFFF):
        return None
    if version != 0 or machine != COFF_AMD64:
        raise LinkageError(f"unsupported anonymous COFF member: {label}")
    if size <= 2 or 20 + size != len(raw):
        raise LinkageError(f"invalid short-import member size: {label}")
    strings = raw[20:]
    first_end = strings.find(b"\0")
    second_end = strings.find(b"\0", first_end + 1)
    if first_end <= 0 or second_end <= first_end + 1:
        raise LinkageError(f"invalid short-import strings: {label}")
    try:
        dll = strings[first_end + 1:second_end].decode("ascii").casefold()
    except UnicodeDecodeError as exc:
        raise LinkageError(f"short-import DLL is not ASCII: {label}") from exc
    if not re.fullmatch(r"[a-z0-9_.-]+\.dll", dll):
        raise LinkageError(f"short-import DLL name is invalid: {label}")
    return dll


def _short_import_symbol(raw: bytes, label: str) -> str | None:
    imported_dll = _short_import_dll(raw, label)
    if imported_dll is None:
        return None
    symbol_raw = raw[20:raw.find(b"\0", 20)]
    try:
        symbol = symbol_raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise LinkageError(f"short-import symbol is not ASCII: {label}") from exc
    if not symbol or any(ord(character) < 33 or ord(character) > 126 for character in symbol):
        raise LinkageError(f"short-import symbol is invalid: {label}")
    return symbol


def _coff_symbol_name(
    entry: bytes,
    string_table: bytes,
    string_table_size: int,
    label: str,
) -> str:
    zeroes, offset = struct.unpack_from("<II", entry)
    if zeroes:
        raw_name = entry[:8].split(b"\0", 1)[0]
    else:
        if offset < 4 or offset >= string_table_size:
            raise LinkageError(f"COFF symbol string offset is invalid: {label}")
        end = string_table.find(b"\0", offset, string_table_size)
        if end < 0:
            raise LinkageError(f"COFF symbol string is unterminated: {label}")
        raw_name = string_table[offset:end]
    try:
        name = raw_name.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LinkageError(f"COFF symbol name is not UTF-8: {label}") from exc
    if not name:
        raise LinkageError(f"COFF symbol name is invalid: {label}")
    return name


def _coff_resolution_symbols(raw: bytes, label: str) -> set[str]:
    """Return defined externals and weak aliases used by LLD archive selection."""
    if len(raw) < 20 or struct.unpack_from("<H", raw)[0] != COFF_AMD64:
        raise LinkageError(f"selected member is not AMD64 COFF: {label}")
    (
        _machine,
        _section_count,
        _timestamp,
        symbol_table_offset,
        symbol_count,
        optional_header_bytes,
        _characteristics,
    ) = struct.unpack_from("<HHIIIHH", raw)
    if optional_header_bytes != 0:
        raise LinkageError(f"COFF object unexpectedly has an optional header: {label}")
    symbol_table_end = symbol_table_offset + symbol_count * COFF_SYMBOL_BYTES
    if (
        symbol_table_offset < 20
        or symbol_count <= 0
        or symbol_table_end + 4 > len(raw)
    ):
        raise LinkageError(f"COFF symbol table is invalid: {label}")
    string_table = raw[symbol_table_end:]
    string_table_size = struct.unpack_from("<I", string_table)[0]
    if string_table_size < 4 or string_table_size > len(string_table):
        raise LinkageError(f"COFF string table is invalid: {label}")

    symbols: set[str] = set()
    index = 0
    while index < symbol_count:
        start = symbol_table_offset + index * COFF_SYMBOL_BYTES
        entry = raw[start:start + COFF_SYMBOL_BYTES]
        if len(entry) != COFF_SYMBOL_BYTES:
            raise LinkageError(f"COFF symbol table is truncated: {label}")
        section_number = struct.unpack_from("<h", entry, 12)[0]
        storage_class = entry[16]
        auxiliary_count = entry[17]
        if index + auxiliary_count >= symbol_count:
            raise LinkageError(f"COFF auxiliary symbol count is invalid: {label}")
        if (
            (storage_class == COFF_STORAGE_EXTERNAL and section_number != 0)
            or storage_class == COFF_STORAGE_WEAK_EXTERNAL
        ):
            symbols.add(
                _coff_symbol_name(
                    entry, string_table, string_table_size, label
                )
            )
        index += 1 + auxiliary_count
    if not symbols:
        raise LinkageError(f"selected COFF member has no resolution symbols: {label}")
    return symbols


def _reason_match_rank(symbols: set[str], reason: str) -> int | None:
    dllimport_prefix = "__declspec(dllimport) "
    if reason.startswith(dllimport_prefix):
        target = "__imp_" + reason.removeprefix(dllimport_prefix)
        return 0 if target in symbols else None
    if reason in symbols:
        return 0
    if any(
        symbol == "_" + reason or reason == "_" + symbol
        for symbol in symbols
    ):
        return 1
    return None


def _code_member_format(raw: bytes, label: str) -> str:
    imported_dll = _short_import_dll(raw, label)
    if imported_dll is not None:
        return "short-import"
    if len(raw) >= 20 and struct.unpack_from("<H", raw)[0] == COFF_AMD64:
        section_count = struct.unpack_from("<H", raw, 2)[0]
        optional_header_bytes = struct.unpack_from("<H", raw, 16)[0]
        section_table_offset = 20 + optional_header_bytes
        section_table_end = section_table_offset + section_count * 40
        if section_count <= 0 or section_table_end > len(raw):
            raise LinkageError(f"COFF section table is invalid: {label}")
        section_names = [
            raw[offset:offset + 8].split(b"\0", 1)[0]
            for offset in range(section_table_offset, section_table_end, 40)
        ]
        if section_names == [b".drectve"]:
            return "coff-directive"
        return "coff-object"
    if raw.startswith((b"BC\xc0\xde", b"\xde\xc0\x17\x0b")):
        return "llvm-bitcode"
    raise LinkageError(f"selected archive member has unknown format: {label}")


def _reproducer_manifest(
    path: Path, program: str
) -> tuple[dict[str, Any], dict[str, str], dict[str, bytes]]:
    raw = _read_regular(path, "LLD reproducer")
    try:
        archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    except tarfile.TarError as exc:
        raise LinkageError(f"cannot parse LLD reproducer: {exc}") from exc
    with archive:
        members = archive.getmembers()
        if not members:
            raise LinkageError("LLD reproducer is empty")
        seen: set[str] = set()
        roots: set[str] = set()
        payloads: dict[str, bytes] = {}
        for member in members:
            member_path = _safe_tar_name(member.name)
            if member.name in seen:
                raise LinkageError(f"duplicate reproducer member: {member.name}")
            seen.add(member.name)
            roots.add(member_path.parts[0])
            if not member.isfile():
                raise LinkageError(f"reproducer member must be regular: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise LinkageError(f"cannot read reproducer member: {member.name}")
            data = handle.read()
            if len(data) != member.size:
                raise LinkageError(f"truncated reproducer member: {member.name}")
            relative = PurePosixPath(*member_path.parts[1:]).as_posix()
            if not relative or relative in payloads:
                raise LinkageError(f"invalid reproducer relative member: {member.name}")
            payloads[relative] = data
        if len(roots) != 1:
            raise LinkageError("LLD reproducer must have exactly one top-level directory")

    response = payloads.pop("response.txt", None)
    if response is None:
        raise LinkageError("LLD reproducer lacks response.txt")
    response_text = _decode_text(response, "LLD reproducer response")
    if PROGRAMS[program] not in response_text:
        raise LinkageError(f"LLD response is not for {PROGRAMS[program]}")
    response_folded = response_text.casefold()
    if any(token not in response_folded for token in ("lldmap", "verbose", "threads:1")):
        raise LinkageError("LLD response lacks lldmap, verbose, or single-thread capture flags")
    if not payloads:
        raise LinkageError("LLD reproducer contains no link inputs")

    inputs = []
    basename_paths: dict[str, list[str]] = {}
    for member_path, data in sorted(payloads.items()):
        origin, input_class = _origin_for(member_path)
        name = PurePosixPath(member_path).name
        basename_paths.setdefault(name, []).append(member_path)
        inputs.append({
            "bytes": len(data),
            "class": input_class,
            "origin": origin,
            "path": member_path,
            "sha256": sha256_bytes(data),
        })
    collisions = {name: paths for name, paths in basename_paths.items() if len(paths) != 1}
    if collisions:
        raise LinkageError(
            "reproducer input basenames are ambiguous: "
            + ", ".join(f"{name}={paths}" for name, paths in sorted(collisions.items()))
        )
    return (
        {
            "bytes": len(raw),
            "inputs": inputs,
            "response_bytes": len(response),
            "response_sha256": sha256_bytes(response),
            "sha256": sha256_bytes(raw),
        },
        {name: paths[0] for name, paths in basename_paths.items()},
        payloads,
    )


def _map_receipt(
    path: Path,
    input_payloads: dict[str, bytes],
    selections: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = _read_regular(path, "LLD map")
    text = _decode_text(raw, "LLD map")
    if not text.startswith("Address  Size     Align Out     In      Symbol\n"):
        raise LinkageError("LLD map header drifted")
    direct_inputs = [name for name in input_payloads if not name.endswith(".a")]
    selected_code_keys = {
        (selection["archive"], selection["member"])
        for selection in selections
        if selection["selected_code_members"]
    }
    resolutions: dict[tuple[str, tuple[str, ...], str], dict[str, Any]] = {}
    live_section_count = 0
    for line in text.splitlines()[1:]:
        match = MAP_INPUT_RE.fullmatch(line)
        if not match:
            continue
        displayed = match.group(1)
        normalized = displayed.replace("\\", "/").lstrip("/")
        candidates: list[tuple[str, str, str]] = []
        archive_form = re.fullmatch(r"(.+)\(([^()]+)\)", normalized)
        if archive_form:
            archive_name = PurePosixPath(archive_form.group(1)).name
            member_name = archive_form.group(2)
            for selection in selections:
                if (
                    PurePosixPath(selection["archive"]).name == archive_name
                    and selection["member"] == member_name
                    and selection["selected_code_members"]
                ):
                    candidates.append(("archive-member", selection["archive"], member_name))
        else:
            displayed_name = PurePosixPath(normalized).name
            for input_path in direct_inputs:
                if (
                    input_path == normalized
                    or input_path.endswith("/" + normalized)
                    or PurePosixPath(input_path).name == displayed_name
                ):
                    candidates.append(("direct-input", input_path, ""))
            for selection in selections:
                if (
                    selection["member"] == displayed_name
                    and selection["selected_code_members"]
                ):
                    candidates.append(
                        ("archive-member", selection["archive"], selection["member"])
                    )
        candidates = sorted(set(candidates))
        if not candidates:
            raise LinkageError(f"LLD map input is absent from reproducer/verbose: {displayed}")
        kinds = {candidate[0] for candidate in candidates}
        if len(kinds) != 1 or ("direct-input" in kinds and len(candidates) != 1):
            raise LinkageError(f"LLD map input mixes ambiguous origins: {displayed}={candidates}")
        if "direct-input" in kinds:
            key = ("direct-input", (candidates[0][1],), "")
            candidate_archives: list[str] = []
            direct_path: str | None = candidates[0][1]
        else:
            member_names = {candidate[2] for candidate in candidates}
            if len(member_names) != 1:
                raise LinkageError(f"LLD map member candidates drifted: {displayed}")
            candidate_archives = sorted({candidate[1] for candidate in candidates})
            key = ("archive-member", tuple(candidate_archives), candidates[0][2])
            direct_path = None
        resolution = resolutions.setdefault(
            key,
            {
                "archive": candidate_archives[0] if len(candidate_archives) == 1 else None,
                "candidate_archives": candidate_archives,
                "display_names": set(),
                "kind": key[0],
                "live_section_count": 0,
                "member": key[2] if key[0] == "archive-member" else None,
                "path": direct_path,
                "resolution_scope": (
                    "exact" if key[0] == "direct-input" or len(candidate_archives) == 1
                    else "conservative-same-name-closure"
                ),
            },
        )
        resolution["display_names"].add(displayed)
        resolution["live_section_count"] += 1
        live_section_count += 1
    if live_section_count == 0:
        raise LinkageError("LLD map contains no live input sections")
    live_inputs = []
    for resolution in resolutions.values():
        resolution["display_names"] = sorted(resolution["display_names"])
        live_inputs.append(resolution)
    live_inputs.sort(
        key=lambda item: (
            item["kind"], item["path"] or "\n".join(item["candidate_archives"]),
            item["member"] or "",
        )
    )
    covered_direct_inputs = {
        item["path"] for item in live_inputs if item["kind"] == "direct-input"
    }
    if covered_direct_inputs != set(direct_inputs):
        raise LinkageError(
            "LLD map does not cover every direct code input "
            f"(missing {sorted(set(direct_inputs) - covered_direct_inputs)})"
        )
    covered_code_keys = {
        (archive, item["member"])
        for item in live_inputs
        if item["kind"] == "archive-member"
        for archive in item["candidate_archives"]
    }
    if covered_code_keys != selected_code_keys:
        raise LinkageError(
            "LLD map does not cover every exact verbose-selected code member "
            f"(missing {sorted(selected_code_keys - covered_code_keys)})"
        )
    return {
        "bytes": len(raw),
        "covered_archive_member_groups": len(covered_code_keys),
        "covered_direct_inputs": len(covered_direct_inputs),
        "live_inputs": live_inputs,
        "live_section_count": live_section_count,
        "sha256": sha256_bytes(raw),
    }


def _verbose_receipt(
    path: Path,
    basename_paths: dict[str, str],
    input_payloads: dict[str, bytes],
    pe_imports: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _read_regular(path, "LLD verbose log")
    text = _decode_text(raw, "LLD verbose log")
    selections: dict[tuple[str, str], dict[str, Any]] = {}
    read_inputs: dict[str, str] = {}
    for line in text.splitlines():
        match = VERBOSE_MEMBER_RE.search(line)
        if match:
            archive_name = PurePosixPath(match.group("archive")).name
            archive_path = basename_paths.get(archive_name)
            if archive_path is None:
                raise LinkageError(
                    f"verbose log selected an archive absent from reproducer: {archive_name}"
                )
            event = match.group("event").casefold()
            reason = match.group("reason")
            if event == "loaded" and not reason:
                raise LinkageError("verbose Loaded event lacks its resolution reason")
            if event == "reading" and reason:
                raise LinkageError("verbose Reading event unexpectedly has a resolution reason")
            events = selections.setdefault(
                (archive_path, match.group("member")),
                {"loaded_reasons": [], "reading": 0},
            )
            if event == "loaded":
                events["loaded_reasons"].append(reason)
            else:
                events["reading"] += 1
            continue
        event_match = re.search(r"\b(?P<event>Loaded|Reading)\s+(?P<input>.+)$", line)
        if not event_match:
            continue
        if event_match.group("event") != "Reading":
            raise LinkageError(f"unparsed verbose Loaded event: {line}")
        displayed = event_match.group("input")
        normalized = displayed.replace("\\", "/").lstrip("/")
        _safe_tar_name(normalized)
        candidates = sorted(
            input_path
            for input_path in input_payloads
            if input_path == normalized or input_path.endswith("/" + normalized)
        )
        if len(candidates) != 1:
            raise LinkageError(
                f"verbose Reading input does not resolve exactly: {displayed}={candidates}"
            )
        input_path = candidates[0]
        if input_path in read_inputs:
            raise LinkageError(f"verbose Reading input is duplicated: {input_path}")
        read_inputs[input_path] = displayed
    if set(read_inputs) != set(input_payloads):
        raise LinkageError(
            "verbose log does not read every reproducer input "
            f"(missing {sorted(set(input_payloads) - set(read_inputs))})"
        )
    if not selections:
        raise LinkageError("LLD verbose log contains no selected archive members")
    records = []
    archive_members: dict[str, dict[str, list[dict[str, Any]]]] = {}
    selected_imports: set[str] = set()
    for (archive_path, member), events in sorted(selections.items()):
        origin, input_class = _origin_for(archive_path)
        members = archive_members.get(archive_path)
        if members is None:
            members = _archive_members(input_payloads[archive_path], archive_path)
            archive_members[archive_path] = members
        member_candidates = members.get(member)
        if member_candidates is None:
            raise LinkageError(
                f"verbose-selected member is absent from archive: {archive_path}({member})"
            )
        label = f"{archive_path}({member})"
        loaded_reasons = events["loaded_reasons"]
        reading_count = events["reading"]
        if len(loaded_reasons) > reading_count:
            raise LinkageError(f"archive event counts are impossible: {label}")
        candidates: list[dict[str, Any]] = []
        resolution_candidates: list[tuple[dict[str, Any], set[str]]] = []
        candidate_imports: set[str] = set()
        for member_record in member_candidates:
            member_raw = member_record["raw"]
            ordinal = member_record["ordinal"]
            member_label = f"{label}#{ordinal}"
            member_format = _code_member_format(member_raw, label)
            imported_dll = _short_import_dll(member_raw, member_label)
            imported_symbol = _short_import_symbol(member_raw, member_label)
            if member_format == "short-import":
                if (
                    origin != "mingw-w64"
                    or imported_dll is None
                    or imported_symbol is None
                ):
                    raise LinkageError(f"short-import candidate origin mismatch: {label}")
                candidate_imports.add(imported_dll)
                symbols = {imported_symbol}
            else:
                if imported_symbol is not None:
                    raise LinkageError(f"code-bearing member has an import symbol: {label}")
                symbols = _coff_resolution_symbols(member_raw, member_label)
            candidate = {
                "bytes": len(member_raw),
                "format": member_format,
                "imported_dll": imported_dll,
                "imported_symbol": imported_symbol,
                "member_ordinal": ordinal,
                "sha256": sha256_bytes(member_raw),
            }
            candidates.append(candidate)
            resolution_candidates.append((candidate, symbols))
        candidates.sort(key=lambda item: item["member_ordinal"])

        selected_loaded: list[dict[str, Any]] = []
        selected_ordinals: set[int] = set()
        for reason in loaded_reasons:
            ranked: list[tuple[int, dict[str, Any]]] = []
            for candidate, symbols in resolution_candidates:
                rank = _reason_match_rank(symbols, reason)
                if rank is not None:
                    ranked.append((rank, candidate))
            if not ranked:
                raise LinkageError(
                    f"Loaded reason does not resolve to an archive member: {label} for {reason}"
                )
            best_rank = min(rank for rank, _candidate in ranked)
            best = [candidate for rank, candidate in ranked if rank == best_rank]
            if len(best) != 1:
                raise LinkageError(
                    f"Loaded reason resolves ambiguously: {label} for {reason}"
                )
            candidate = best[0]
            ordinal = candidate["member_ordinal"]
            if ordinal in selected_ordinals:
                raise LinkageError(
                    f"archive member was Loaded more than once: {label}#{ordinal}"
                )
            selected_ordinals.add(ordinal)
            selected_loaded.append({
                "bytes": candidate["bytes"],
                "format": candidate["format"],
                "imported_dll": candidate["imported_dll"],
                "loaded_reason": reason,
                "member_ordinal": ordinal,
                "sha256": candidate["sha256"],
            })
        selected_loaded.sort(
            key=lambda item: (item["member_ordinal"], item["loaded_reason"])
        )
        selected_code = [
            item for item in selected_loaded if item["format"] == "coff-object"
        ]
        selected_directives = [
            item for item in selected_loaded if item["format"] == "coff-directive"
        ]
        selected_loaded_imports = [
            item for item in selected_loaded if item["format"] == "short-import"
        ]
        selected_import_count = (
            reading_count - len(selected_code) - len(selected_directives)
        )
        import_candidate_count = sum(
            candidate["format"] == "short-import" for candidate in candidates
        )
        if selected_import_count > import_candidate_count:
            raise LinkageError(f"short-import event count exceeds candidates: {label}")
        if not selected_loaded and selected_import_count == 0:
            raise LinkageError(f"archive selection count is zero: {label}")
        if selected_import_count:
            if len(candidate_imports) != 1:
                raise LinkageError(f"short-import DLL candidates are ambiguous: {label}")
            imported_dll = next(iter(candidate_imports))
            if any(
                item["imported_dll"] != imported_dll
                for item in selected_loaded_imports
            ):
                raise LinkageError(f"Loaded short-import DLL drifted: {label}")
            selected_imports.update(candidate_imports)
        elif selected_loaded_imports:
            raise LinkageError(f"Loaded short import was not counted as an import: {label}")
        import_scope = (
            "exact"
            if selected_import_count == import_candidate_count
            else "actual-pe-import-conservative"
        )
        records.append({
            "archive": archive_path,
            "archive_class": input_class,
            "candidates": candidates,
            "event_counts": {
                "loaded": len(loaded_reasons),
                "reading": reading_count,
            },
            "import_candidate_scope": import_scope,
            "member": member,
            "origin": origin,
            "selected_code_members": selected_code,
            "selected_directive_members": selected_directives,
            "selected_import_member_count": selected_import_count,
            "selected_loaded_import_members": selected_loaded_imports,
        })
    if selected_imports != set(pe_imports):
        raise LinkageError(
            "short-import DLL set differs from PE imports "
            f"(link {sorted(selected_imports)}; PE {pe_imports})"
        )
    return (
        {
            "bytes": len(raw),
            "read_inputs": [
                {"display_name": read_inputs[input_path], "path": input_path}
                for input_path in sorted(read_inputs)
            ],
            "selected_archive_members": records,
            "sha256": sha256_bytes(raw),
            "system_imports": sorted(selected_imports),
        },
        records,
    )


def _source_catalog(source_lock: Path) -> list[dict[str, Any]]:
    try:
        loaded = windows_verifier.load_source_lock(source_lock)
    except windows_verifier.WindowsFFmpegError as exc:
        raise LinkageError(f"source lock verification failed: {exc}") from exc
    catalog = [
        {
            "archive": source["archive"],
            "archive_bytes": source["archive_bytes"],
            "archive_sha256": source["archive_sha256"],
            "id": source["id"],
            "role": source["role"],
            "version": source["version"],
        }
        for source in loaded.parsed()["sources"]
    ]
    if [source["id"] for source in catalog] != sorted(
        EXPECTED_CODE_SOURCE_IDS | BUILD_ONLY_SOURCE_IDS
    ):
        raise LinkageError("source catalog IDs drifted")
    return catalog


def _bind_reproducer_sources(
    reproducer: dict[str, Any],
    sources: list[dict[str, Any]],
) -> None:
    by_id = {source["id"]: source for source in sources}
    for item in reproducer["inputs"]:
        source = by_id.get(item["origin"])
        if source is None:
            raise LinkageError(
                f"reproducer input origin lacks a pinned source: {item['origin']}"
            )
        item["source_archive"] = source["archive"]
        item["source_archive_sha256"] = source["archive_sha256"]


def _closure_receipt(
    reproducer: dict[str, Any],
    selections: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    reproducer_source_ids = sorted({
        item["origin"] for item in reproducer["inputs"]
    })
    code_source_ids = {
        item["origin"]
        for item in reproducer["inputs"]
        if not item["path"].endswith(".a")
    }
    code_source_ids.update(
        item["origin"] for item in selections if item["selected_code_members"]
    )
    import_source_ids = {
        item["origin"]
        for item in selections
        if item["selected_import_member_count"]
    }
    source_ids = {source["id"] for source in sources}
    if code_source_ids != EXPECTED_CODE_SOURCE_IDS:
        raise LinkageError(
            "code-bearing link sources are incomplete: "
            f"expected {sorted(EXPECTED_CODE_SOURCE_IDS)}, found {sorted(code_source_ids)}"
        )
    if import_source_ids != {"mingw-w64"}:
        raise LinkageError(
            "import-library source must be exactly mingw-w64: "
            f"found {sorted(import_source_ids)}"
        )
    if (
        set(reproducer_source_ids) != EXPECTED_CODE_SOURCE_IDS
        or source_ids != EXPECTED_CODE_SOURCE_IDS | BUILD_ONLY_SOURCE_IDS
    ):
        raise LinkageError("reproducer/source catalog coverage drifted")
    return {
        "build_only_source_ids": sorted(BUILD_ONLY_SOURCE_IDS),
        "code_source_ids": sorted(code_source_ids),
        "import_source_ids": sorted(import_source_ids),
        "mapping": "exact-reproducer-input-and-archive-member-sha256",
        "reproducer_input_count": len(reproducer["inputs"]),
        "reproducer_source_ids": reproducer_source_ids,
        "selected_code_member_count": sum(
            len(item["selected_code_members"]) for item in selections
        ),
        "selected_directive_member_count": sum(
            len(item["selected_directive_members"]) for item in selections
        ),
        "selected_import_member_count": sum(
            item["selected_import_member_count"] for item in selections
        ),
        "status": "verified",
    }


def create_receipt(
    *,
    program: str,
    reproduce: Path,
    lld_map: Path,
    verbose_log: Path,
    unstripped_executable: Path,
    source_lock: Path = Path(__file__).with_name("windows-ffmpeg-sources.lock.json"),
) -> dict[str, Any]:
    if program not in PROGRAMS:
        raise LinkageError(f"unsupported program: {program}")
    executable = _read_regular(unstripped_executable, "unstripped executable")
    try:
        pe = windows_verifier.inspect_pe(unstripped_executable, ())
    except windows_verifier.WindowsFFmpegError as exc:
        raise LinkageError(f"unstripped executable PE verification failed: {exc}") from exc
    if pe["sha256"] != sha256_bytes(executable):
        raise LinkageError("unstripped executable changed during PE inspection")
    repro_receipt, basename_paths, input_payloads = _reproducer_manifest(
        reproduce, program
    )
    sources = _source_catalog(source_lock)
    _bind_reproducer_sources(repro_receipt, sources)
    verbose_receipt, selections = _verbose_receipt(
        verbose_log, basename_paths, input_payloads, pe["imports"]
    )
    receipt = {
        "closure": _closure_receipt(
            repro_receipt, selections, sources
        ),
        "lld_map": _map_receipt(lld_map, input_payloads, selections),
        "program": program,
        "reproducer": repro_receipt,
        "schema": SCHEMA,
        "sources": sources,
        "unstripped_executable": {
            "bytes": len(executable),
            "filename": PROGRAMS[program],
            "imports": pe["imports"],
            "sha256": sha256_bytes(executable),
        },
        "verbose_log": verbose_receipt,
    }
    validate_receipt(receipt)
    return receipt


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise LinkageError(f"{label} fields drifted")


def _sha(value: Any, label: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise LinkageError(f"{label} is not a SHA-256 digest")


def _positive_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LinkageError(f"{label} is invalid")


def _nonnegative_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LinkageError(f"{label} is invalid")


def _sorted_strings(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise LinkageError(f"{label} must be sorted unique strings")
    return value


def validate_receipt(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise LinkageError("linkage receipt must be an object")
    _exact_fields(
        value,
        {
            "closure", "lld_map", "program", "reproducer", "schema",
            "sources", "unstripped_executable", "verbose_log",
        },
        "linkage receipt",
    )
    if value["schema"] != SCHEMA or value["program"] not in PROGRAMS:
        raise LinkageError("linkage receipt identity drifted")
    executable = value["unstripped_executable"]
    if not isinstance(executable, dict):
        raise LinkageError("unstripped executable receipt must be an object")
    _exact_fields(
        executable,
        {"bytes", "filename", "imports", "sha256"},
        "unstripped executable",
    )
    if executable["filename"] != PROGRAMS[value["program"]]:
        raise LinkageError("unstripped executable filename drifted")
    _positive_int(executable["bytes"], "unstripped executable byte count")
    _sha(executable["sha256"], "unstripped executable hash")
    imports = _sorted_strings(executable["imports"], "PE imports")
    if any(item != item.casefold() or not item.endswith(".dll") for item in imports):
        raise LinkageError("PE imports are not normalized DLL names")

    sources = value["sources"]
    if not isinstance(sources, list) or len(sources) != 7:
        raise LinkageError("linkage source catalog must contain seven sources")
    if any(not isinstance(source, dict) for source in sources):
        raise LinkageError("linkage source catalog entry must be an object")
    source_ids: list[str] = []
    sources_by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        _exact_fields(
            source,
            {"archive", "archive_bytes", "archive_sha256", "id", "role", "version"},
            "linkage source catalog entry",
        )
        for field in ("archive", "id", "role", "version"):
            if (
                not isinstance(source[field], str)
                or not source[field]
                or source[field] != source[field].strip()
            ):
                raise LinkageError(f"linkage source {field} is invalid")
        if Path(source["archive"]).name != source["archive"] or "\\" in source["archive"]:
            raise LinkageError("linkage source archive name is invalid")
        _positive_int(source["archive_bytes"], "linkage source archive bytes")
        _sha(source["archive_sha256"], "linkage source archive hash")
        source_ids.append(source["id"])
        if source["id"] in sources_by_id:
            raise LinkageError("duplicate linkage source ID")
        sources_by_id[source["id"]] = source
    expected_source_ids = sorted(EXPECTED_CODE_SOURCE_IDS | BUILD_ONLY_SOURCE_IDS)
    if source_ids != expected_source_ids:
        raise LinkageError("linkage source catalog IDs drifted")

    lld_map = value["lld_map"]
    reproducer = value["reproducer"]
    verbose = value["verbose_log"]
    for label, section, fields in (
        (
            "lld_map",
            lld_map,
            {
                "bytes", "covered_archive_member_groups",
                "covered_direct_inputs", "live_inputs", "live_section_count",
                "sha256",
            },
        ),
        (
            "reproducer",
            reproducer,
            {"bytes", "inputs", "response_bytes", "response_sha256", "sha256"},
        ),
        (
            "verbose_log",
            verbose,
            {
                "bytes", "read_inputs", "selected_archive_members", "sha256",
                "system_imports",
            },
        ),
    ):
        if not isinstance(section, dict):
            raise LinkageError(f"{label} receipt must be an object")
        _exact_fields(section, fields, label)
        _positive_int(section["bytes"], f"{label}.bytes")
        _sha(section["sha256"], f"{label}.sha256")

    _positive_int(reproducer["response_bytes"], "reproducer.response_bytes")
    _sha(reproducer["response_sha256"], "reproducer.response_sha256")
    inputs = reproducer["inputs"]
    if not isinstance(inputs, list) or not inputs:
        raise LinkageError("reproducer inputs are empty")
    if any(not isinstance(item, dict) for item in inputs):
        raise LinkageError("reproducer input must be an object")
    for item in inputs:
        _exact_fields(
            item,
            {
                "bytes", "class", "origin", "path", "sha256",
                "source_archive", "source_archive_sha256",
            },
            "reproducer input",
        )
        if not isinstance(item["path"], str):
            raise LinkageError("reproducer input path must be a string")
    if inputs != sorted(inputs, key=lambda item: item["path"]):
        raise LinkageError("reproducer inputs are not sorted")
    input_paths: set[str] = set()
    reproducer_source_ids: set[str] = set()
    code_source_ids: set[str] = set()
    for item in inputs:
        _safe_tar_name(item["path"])
        expected_origin, expected_class = _origin_for(item["path"])
        if (item["origin"], item["class"]) != (expected_origin, expected_class):
            raise LinkageError("reproducer input origin/class drifted")
        source = sources_by_id.get(item["origin"])
        if source is None or (
            item["source_archive"], item["source_archive_sha256"]
        ) != (source["archive"], source["archive_sha256"]):
            raise LinkageError("reproducer input source archive mapping drifted")
        _positive_int(item["bytes"], "reproducer input bytes")
        _sha(item["sha256"], "reproducer input hash")
        if item["path"] in input_paths:
            raise LinkageError("duplicate reproducer input path")
        input_paths.add(item["path"])
        reproducer_source_ids.add(item["origin"])
        if not item["path"].endswith(".a"):
            code_source_ids.add(item["origin"])

    read_inputs = verbose["read_inputs"]
    if not isinstance(read_inputs, list) or not read_inputs:
        raise LinkageError("verbose read inputs are empty")
    if any(not isinstance(item, dict) for item in read_inputs):
        raise LinkageError("verbose read input must be an object")
    for item in read_inputs:
        _exact_fields(item, {"display_name", "path"}, "verbose read input")
        if (
            not isinstance(item["display_name"], str)
            or not item["display_name"]
            or not isinstance(item["path"], str)
            or item["path"] not in input_paths
        ):
            raise LinkageError("verbose read input identity drifted")
        normalized_display = item["display_name"].replace("\\", "/").lstrip("/")
        _safe_tar_name(normalized_display)
        if not (
            item["path"] == normalized_display
            or item["path"].endswith("/" + normalized_display)
        ):
            raise LinkageError("verbose read input display mapping drifted")
    if read_inputs != sorted(read_inputs, key=lambda item: item["path"]):
        raise LinkageError("verbose read inputs are not sorted")
    read_input_paths = [item["path"] for item in read_inputs]
    if len(read_input_paths) != len(set(read_input_paths)) or set(read_input_paths) != input_paths:
        raise LinkageError("verbose read inputs do not cover the reproducer")

    selections = verbose["selected_archive_members"]
    if not isinstance(selections, list) or not selections:
        raise LinkageError("verbose selected archive members are empty")
    if any(not isinstance(item, dict) for item in selections):
        raise LinkageError("verbose archive member must be an object")
    for item in selections:
        _exact_fields(
            item,
            {
                "archive", "archive_class", "candidates", "event_counts",
                "import_candidate_scope", "member", "origin",
                "selected_code_members", "selected_directive_members",
                "selected_import_member_count", "selected_loaded_import_members",
            },
            "verbose archive member",
        )
        if not isinstance(item["archive"], str) or not isinstance(item["member"], str):
            raise LinkageError("verbose archive/member name must be a string")
    if selections != sorted(selections, key=lambda item: (item["archive"], item["member"])):
        raise LinkageError("verbose archive members are not sorted")
    selected_keys: set[tuple[str, str]] = set()
    selected_code_keys: set[tuple[str, str]] = set()
    selected_imports: set[str] = set()
    selected_code_member_count = 0
    selected_directive_member_count = 0
    selected_import_member_count = 0
    import_source_ids: set[str] = set()
    for item in selections:
        if item["archive"] not in input_paths or not item["archive"].endswith(".a"):
            raise LinkageError("verbose archive is absent from reproducer inputs")
        expected_origin, expected_class = _origin_for(item["archive"])
        if (item["origin"], item["archive_class"]) != (expected_origin, expected_class):
            raise LinkageError("verbose archive origin/class drifted")
        if (
            not isinstance(item["member"], str)
            or not item["member"]
            or "/" in item["member"]
            or "\\" in item["member"]
        ):
            raise LinkageError("verbose archive member name is invalid")
        if not isinstance(item["event_counts"], dict):
            raise LinkageError("verbose archive event counts must be an object")
        _exact_fields(item["event_counts"], {"loaded", "reading"}, "archive event counts")
        loaded = item["event_counts"]["loaded"]
        reading = item["event_counts"]["reading"]
        _nonnegative_int(loaded, "archive loaded count")
        _nonnegative_int(reading, "archive reading count")
        _nonnegative_int(item["selected_import_member_count"], "selected import member count")
        if reading <= 0 or loaded > reading:
            raise LinkageError("archive event count classification drifted")
        candidates = item["candidates"]
        if not isinstance(candidates, list) or not candidates:
            raise LinkageError("archive member candidates are empty")
        if any(not isinstance(candidate, dict) for candidate in candidates):
            raise LinkageError("archive member candidate must be an object")
        for candidate in candidates:
            _exact_fields(
                candidate,
                {
                    "bytes", "format", "imported_dll", "imported_symbol",
                    "member_ordinal", "sha256",
                },
                "archive member candidate",
            )
        if candidates != sorted(candidates, key=lambda candidate: candidate["member_ordinal"]):
            raise LinkageError("archive member candidates are not sorted")
        candidate_ordinals: set[int] = set()
        candidate_by_ordinal: dict[int, dict[str, Any]] = {}
        import_candidates = 0
        candidate_imports: set[str] = set()
        for candidate in candidates:
            _positive_int(candidate["bytes"], "archive member candidate bytes")
            _sha(candidate["sha256"], "archive member candidate hash")
            _nonnegative_int(candidate["member_ordinal"], "archive member ordinal")
            if candidate["member_ordinal"] in candidate_ordinals:
                raise LinkageError("duplicate archive member ordinal")
            candidate_ordinals.add(candidate["member_ordinal"])
            candidate_by_ordinal[candidate["member_ordinal"]] = candidate
            if candidate["format"] == "short-import":
                if (
                    not isinstance(candidate["imported_dll"], str)
                    or candidate["imported_dll"] != candidate["imported_dll"].casefold()
                    or not candidate["imported_dll"].endswith(".dll")
                    or not isinstance(candidate["imported_symbol"], str)
                    or not candidate["imported_symbol"]
                ):
                    raise LinkageError("short-import candidate identity drifted")
                import_candidates += 1
                candidate_imports.add(candidate["imported_dll"])
            elif candidate["format"] in {"coff-directive", "coff-object"}:
                if (
                    candidate["imported_dll"] is not None
                    or candidate["imported_symbol"] is not None
                ):
                    raise LinkageError("code-bearing candidate has an imported DLL")
            else:
                raise LinkageError("unknown archive member candidate format")

        def validate_selected(
            selected: Any,
            *,
            expected_format: str,
            label: str,
        ) -> list[dict[str, Any]]:
            if not isinstance(selected, list):
                raise LinkageError(f"{label} must be an array")
            if any(not isinstance(entry, dict) for entry in selected):
                raise LinkageError(f"{label} entry must be an object")
            for entry in selected:
                _exact_fields(
                    entry,
                    {
                        "bytes", "format", "imported_dll", "loaded_reason",
                        "member_ordinal", "sha256",
                    },
                    label,
                )
            expected_sort = sorted(
                selected,
                key=lambda entry: (entry["member_ordinal"], entry["loaded_reason"]),
            )
            if selected != expected_sort:
                raise LinkageError(f"{label} is not sorted")
            seen_ordinals: set[int] = set()
            for entry in selected:
                _positive_int(entry["bytes"], f"{label} bytes")
                _nonnegative_int(entry["member_ordinal"], f"{label} ordinal")
                _sha(entry["sha256"], f"{label} hash")
                if (
                    not isinstance(entry["loaded_reason"], str)
                    or not entry["loaded_reason"]
                    or entry["loaded_reason"] != entry["loaded_reason"].strip()
                ):
                    raise LinkageError(f"{label} reason is invalid")
                candidate = candidate_by_ordinal.get(entry["member_ordinal"])
                if candidate is None or (
                    entry["bytes"], entry["format"], entry["imported_dll"],
                    entry["sha256"],
                ) != (
                    candidate["bytes"], candidate["format"],
                    candidate["imported_dll"], candidate["sha256"],
                ):
                    raise LinkageError(f"{label} does not identify an exact candidate")
                if entry["format"] != expected_format:
                    raise LinkageError(f"{label} format drifted")
                if entry["member_ordinal"] in seen_ordinals:
                    raise LinkageError(f"{label} repeats an archive member")
                seen_ordinals.add(entry["member_ordinal"])
            return selected

        selected_code = validate_selected(
            item["selected_code_members"],
            expected_format="coff-object",
            label="selected code member",
        )
        selected_loaded_imports = validate_selected(
            item["selected_loaded_import_members"],
            expected_format="short-import",
            label="selected loaded import member",
        )
        selected_directives = validate_selected(
            item["selected_directive_members"],
            expected_format="coff-directive",
            label="selected directive member",
        )
        selected_sets = [
            {entry["member_ordinal"] for entry in selected}
            for selected in (selected_code, selected_directives, selected_loaded_imports)
        ]
        if any(
            selected_sets[left] & selected_sets[right]
            for left in range(len(selected_sets))
            for right in range(left + 1, len(selected_sets))
        ):
            raise LinkageError("code, directive, and import selections overlap")
        if (
            loaded
            != len(selected_code) + len(selected_directives) + len(selected_loaded_imports)
            or reading - len(selected_code) - len(selected_directives)
            != item["selected_import_member_count"]
        ):
            raise LinkageError("archive event count exact classification drifted")
        if item["selected_import_member_count"] > import_candidates:
            raise LinkageError("archive selection count exceeds candidates")
        selected_code_member_count += len(selected_code)
        selected_directive_member_count += len(selected_directives)
        selected_import_member_count += item["selected_import_member_count"]
        if selected_code:
            code_source_ids.add(item["origin"])
        if item["selected_import_member_count"]:
            if len(candidate_imports) != 1 or not candidate_imports.issubset(imports):
                raise LinkageError("selected short-import candidates are ambiguous")
            selected_imports.update(candidate_imports)
            import_source_ids.add(item["origin"])
        expected_scope = (
            "exact"
            if item["selected_import_member_count"] == import_candidates
            else "actual-pe-import-conservative"
        )
        if item["import_candidate_scope"] != expected_scope:
            raise LinkageError("archive member import candidate scope drifted")
        key = (item["archive"], item["member"])
        if key in selected_keys:
            raise LinkageError("duplicate verbose archive member")
        selected_keys.add(key)
        if selected_code:
            selected_code_keys.add(key)

    system_imports = _sorted_strings(verbose["system_imports"], "system imports")
    if system_imports != imports or system_imports != sorted(selected_imports):
        raise LinkageError("system import closure differs from PE imports")

    _positive_int(lld_map["live_section_count"], "lld_map.live_section_count")
    _positive_int(
        lld_map["covered_archive_member_groups"],
        "lld_map.covered_archive_member_groups",
    )
    _positive_int(lld_map["covered_direct_inputs"], "lld_map.covered_direct_inputs")
    live_inputs = lld_map["live_inputs"]
    if not isinstance(live_inputs, list) or not live_inputs:
        raise LinkageError("LLD map live inputs are empty")
    if any(not isinstance(item, dict) for item in live_inputs):
        raise LinkageError("LLD map live input must be an object")
    for item in live_inputs:
        _exact_fields(
            item,
            {
                "archive", "candidate_archives", "display_names", "kind",
                "live_section_count", "member", "path", "resolution_scope",
            },
            "LLD map live input",
        )
        if (
            not isinstance(item["kind"], str)
            or not isinstance(item["resolution_scope"], str)
            or not isinstance(item["candidate_archives"], list)
            or any(not isinstance(value, str) for value in item["candidate_archives"])
            or not isinstance(item["path"], (str, type(None)))
            or not isinstance(item["archive"], (str, type(None)))
            or not isinstance(item["member"], (str, type(None)))
        ):
            raise LinkageError("LLD map live input identity is invalid")
    expected_live_sort = sorted(
        live_inputs,
        key=lambda item: (
            item["kind"], item["path"] or "\n".join(item["candidate_archives"]),
            item["member"] or "",
        ),
    )
    if live_inputs != expected_live_sort:
        raise LinkageError("LLD map live inputs are not sorted")
    live_sections = 0
    for item in live_inputs:
        _sorted_strings(item["display_names"], "LLD map display names")
        candidate_archives = _sorted_strings(
            item["candidate_archives"], "LLD map candidate archives"
        )
        _positive_int(item["live_section_count"], "LLD map input section count")
        live_sections += item["live_section_count"]
        if item["kind"] == "direct-input":
            if (
                item["path"] not in input_paths
                or item["path"].endswith(".a")
                or item["archive"] is not None
                or item["member"] is not None
                or candidate_archives
                or item["resolution_scope"] != "exact"
            ):
                raise LinkageError("LLD map direct input is invalid")
        elif item["kind"] == "archive-member":
            if (
                not candidate_archives
                or any(
                    (archive, item["member"]) not in selected_code_keys
                    for archive in candidate_archives
                )
                or item["path"] is not None
                or item["archive"]
                != (candidate_archives[0] if len(candidate_archives) == 1 else None)
                or item["resolution_scope"]
                != (
                    "exact"
                    if len(candidate_archives) == 1
                    else "conservative-same-name-closure"
                )
            ):
                raise LinkageError("LLD map archive member is invalid")
        else:
            raise LinkageError("unknown LLD map input kind")
    if live_sections != lld_map["live_section_count"]:
        raise LinkageError("LLD map live section count drifted")
    covered_direct_inputs = {
        item["path"] for item in live_inputs if item["kind"] == "direct-input"
    }
    expected_direct_inputs = {
        item["path"] for item in inputs if not item["path"].endswith(".a")
    }
    covered_code_keys = {
        (archive, item["member"])
        for item in live_inputs
        if item["kind"] == "archive-member"
        for archive in item["candidate_archives"]
    }
    if (
        covered_direct_inputs != expected_direct_inputs
        or covered_code_keys != selected_code_keys
        or lld_map["covered_direct_inputs"] != len(covered_direct_inputs)
        or lld_map["covered_archive_member_groups"] != len(covered_code_keys)
    ):
        raise LinkageError("LLD map code coverage drifted")

    closure = value["closure"]
    if not isinstance(closure, dict):
        raise LinkageError("link closure receipt must be an object")
    _exact_fields(
        closure,
        {
            "build_only_source_ids", "code_source_ids", "import_source_ids",
            "mapping", "reproducer_input_count", "reproducer_source_ids",
            "selected_code_member_count", "selected_directive_member_count",
            "selected_import_member_count", "status",
        },
        "link closure receipt",
    )
    for field in (
        "build_only_source_ids", "code_source_ids", "import_source_ids",
        "reproducer_source_ids",
    ):
        _sorted_strings(closure[field], f"link closure {field}")
    if (
        reproducer_source_ids != EXPECTED_CODE_SOURCE_IDS
        or code_source_ids != EXPECTED_CODE_SOURCE_IDS
        or import_source_ids != {"mingw-w64"}
    ):
        raise LinkageError("verified link source closure is incomplete")
    build_only_source_ids = set(sources_by_id) - reproducer_source_ids
    if closure != {
        "build_only_source_ids": sorted(build_only_source_ids),
        "code_source_ids": sorted(code_source_ids),
        "import_source_ids": sorted(import_source_ids),
        "mapping": "exact-reproducer-input-and-archive-member-sha256",
        "reproducer_input_count": len(inputs),
        "reproducer_source_ids": sorted(reproducer_source_ids),
        "selected_code_member_count": selected_code_member_count,
        "selected_directive_member_count": selected_directive_member_count,
        "selected_import_member_count": selected_import_member_count,
        "status": "verified",
    }:
        raise LinkageError("verified link closure receipt drifted")


def load_receipt(path: Path) -> dict[str, Any]:
    raw = _read_regular(path, "linkage receipt")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LinkageError(f"cannot parse linkage receipt: {exc}") from exc
    validate_receipt(value)
    if raw != canonical_json(value):
        raise LinkageError("linkage receipt must be canonical sorted JSON")
    return value


def _write_new_receipt(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise LinkageError("refusing to replace an existing linkage receipt") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "verify"):
        child = commands.add_parser(command)
        child.add_argument(
            "--source-lock",
            type=Path,
            default=Path(__file__).with_name("windows-ffmpeg-sources.lock.json"),
        )
        child.add_argument("--program", choices=sorted(PROGRAMS), required=True)
        child.add_argument("--reproduce", type=Path, required=True)
        child.add_argument("--lld-map", type=Path, required=True)
        child.add_argument("--verbose-log", type=Path, required=True)
        child.add_argument("--unstripped-executable", type=Path, required=True)
        child.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        computed = create_receipt(
            program=args.program,
            reproduce=args.reproduce,
            lld_map=args.lld_map,
            verbose_log=args.verbose_log,
            unstripped_executable=args.unstripped_executable,
            source_lock=args.source_lock,
        )
        raw = canonical_json(computed)
        if args.command == "create":
            _write_new_receipt(args.receipt, raw)
            print(f"Windows FFmpeg linkage receipt written: {sha256_bytes(raw)}")
        else:
            recorded = load_receipt(args.receipt)
            if canonical_json(recorded) != raw:
                raise LinkageError("linkage receipt differs from captured link inputs")
            print(f"Windows FFmpeg linkage receipt verified: {sha256_bytes(raw)}")
        return 0
    except (LinkageError, OSError) as exc:
        print(f"Windows FFmpeg linkage verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
