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


SCHEMA = "autoeditor-windows-ffmpeg-linkage/v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PROGRAMS = {"ffmpeg": "ffmpeg_g.exe", "ffprobe": "ffprobe_g.exe"}
MAP_INPUT_RE = re.compile(
    r"^[0-9A-Fa-f]{8,16} [0-9A-Fa-f]{8,16}\s+\d+\s{9}(.+):\(([^()]*)\)$"
)
VERBOSE_MEMBER_RE = re.compile(
    r"\b(?P<event>Loaded|Reading)\s+(?P<archive>[^\s()]+)"
    r"\((?P<member>[^()]+)\)(?:\s+for\s+.*)?$"
)
ARCHIVE_MAGIC = b"!<arch>\n"
COFF_AMD64 = 0x8664


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
    if path.startswith("build/autoeditor-media/sources/FFmpeg-"):
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
    if path.startswith("opt/llvm-mingw/lib/clang/"):
        if not name.endswith(".a"):
            raise LinkageError(f"undeclared compiler runtime link input: {path}")
        return "llvm-project", "toolchain-runtime-static-archive"
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


def _archive_members(raw: bytes, archive_path: str) -> dict[str, list[bytes]]:
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

    members: dict[str, list[bytes]] = {}
    for raw_name, data in records:
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
        members.setdefault(name, []).append(data)
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


def _code_member_format(raw: bytes, label: str) -> str:
    imported_dll = _short_import_dll(raw, label)
    if imported_dll is not None:
        return "short-import"
    if len(raw) >= 2 and struct.unpack_from("<H", raw)[0] == COFF_AMD64:
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
                if selection["member"] == displayed_name:
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
    return {
        "bytes": len(raw),
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
    selections: dict[tuple[str, str], dict[str, int]] = {}
    for line in text.splitlines():
        match = VERBOSE_MEMBER_RE.search(line)
        if not match:
            continue
        archive_name = PurePosixPath(match.group("archive")).name
        archive_path = basename_paths.get(archive_name)
        if archive_path is None:
            raise LinkageError(
                f"verbose log selected an archive absent from reproducer: {archive_name}"
            )
        event = match.group("event").casefold()
        counts = selections.setdefault(
            (archive_path, match.group("member")), {"loaded": 0, "reading": 0}
        )
        counts[event] += 1
    if not selections:
        raise LinkageError("LLD verbose log contains no selected archive members")
    records = []
    archive_members: dict[str, dict[str, list[bytes]]] = {}
    selected_imports: set[str] = set()
    for (archive_path, member), event_counts in sorted(selections.items()):
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
        if event_counts["loaded"] > event_counts["reading"]:
            raise LinkageError(f"archive event counts are impossible: {label}")
        selected_code_count = event_counts["loaded"]
        selected_import_count = event_counts["reading"] - event_counts["loaded"]
        candidates = []
        code_candidate_count = 0
        import_candidate_count = 0
        candidate_imports: set[str] = set()
        for member_raw in member_candidates:
            member_format = _code_member_format(member_raw, label)
            imported_dll = _short_import_dll(member_raw, label)
            if member_format == "short-import":
                if origin != "mingw-w64" or imported_dll is None:
                    raise LinkageError(f"short-import candidate origin mismatch: {label}")
                import_candidate_count += 1
                candidate_imports.add(imported_dll)
            else:
                code_candidate_count += 1
            candidates.append({
                "bytes": len(member_raw),
                "format": member_format,
                "imported_dll": imported_dll,
                "sha256": sha256_bytes(member_raw),
            })
        candidates.sort(key=lambda item: (item["format"], item["sha256"]))
        if selected_code_count > code_candidate_count:
            raise LinkageError(f"code-bearing archive event count exceeds candidates: {label}")
        if selected_import_count > import_candidate_count:
            raise LinkageError(f"short-import event count exceeds candidates: {label}")
        if selected_code_count == 0 and selected_import_count == 0:
            raise LinkageError(f"archive selection count is zero: {label}")
        if selected_import_count:
            if len(candidate_imports) != 1:
                raise LinkageError(f"short-import DLL candidates are ambiguous: {label}")
            selected_imports.update(candidate_imports)
        scope = (
            "exact"
            if selected_code_count == code_candidate_count
            and selected_import_count == import_candidate_count
            else "conservative-same-name-closure"
        )
        records.append({
            "archive": archive_path,
            "archive_class": input_class,
            "candidate_scope": scope,
            "candidates": candidates,
            "event_counts": event_counts,
            "member": member,
            "origin": origin,
            "selected_code_member_count": selected_code_count,
            "selected_import_member_count": selected_import_count,
        })
    if selected_imports != set(pe_imports):
        raise LinkageError(
            "short-import DLL set differs from PE imports "
            f"(link {sorted(selected_imports)}; PE {pe_imports})"
        )
    return (
        {
            "bytes": len(raw),
            "selected_archive_members": records,
            "sha256": sha256_bytes(raw),
            "system_imports": sorted(selected_imports),
        },
        records,
    )


def create_receipt(
    *,
    program: str,
    reproduce: Path,
    lld_map: Path,
    verbose_log: Path,
    unstripped_executable: Path,
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
    verbose_receipt, selections = _verbose_receipt(
        verbose_log, basename_paths, input_payloads, pe["imports"]
    )
    receipt = {
        "lld_map": _map_receipt(lld_map, input_payloads, selections),
        "program": program,
        "reproducer": repro_receipt,
        "schema": SCHEMA,
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
        {"lld_map", "program", "reproducer", "schema", "unstripped_executable", "verbose_log"},
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

    lld_map = value["lld_map"]
    reproducer = value["reproducer"]
    verbose = value["verbose_log"]
    for label, section, fields in (
        (
            "lld_map",
            lld_map,
            {"bytes", "live_inputs", "live_section_count", "sha256"},
        ),
        (
            "reproducer",
            reproducer,
            {"bytes", "inputs", "response_bytes", "response_sha256", "sha256"},
        ),
        (
            "verbose_log",
            verbose,
            {"bytes", "selected_archive_members", "sha256", "system_imports"},
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
        _exact_fields(item, {"bytes", "class", "origin", "path", "sha256"}, "reproducer input")
        if not isinstance(item["path"], str):
            raise LinkageError("reproducer input path must be a string")
    if inputs != sorted(inputs, key=lambda item: item["path"]):
        raise LinkageError("reproducer inputs are not sorted")
    input_paths: set[str] = set()
    for item in inputs:
        _safe_tar_name(item["path"])
        expected_origin, expected_class = _origin_for(item["path"])
        if (item["origin"], item["class"]) != (expected_origin, expected_class):
            raise LinkageError("reproducer input origin/class drifted")
        _positive_int(item["bytes"], "reproducer input bytes")
        _sha(item["sha256"], "reproducer input hash")
        if item["path"] in input_paths:
            raise LinkageError("duplicate reproducer input path")
        input_paths.add(item["path"])

    selections = verbose["selected_archive_members"]
    if not isinstance(selections, list) or not selections:
        raise LinkageError("verbose selected archive members are empty")
    if any(not isinstance(item, dict) for item in selections):
        raise LinkageError("verbose archive member must be an object")
    for item in selections:
        _exact_fields(
            item,
            {
                "archive", "archive_class", "candidate_scope", "candidates",
                "event_counts", "member", "origin", "selected_code_member_count",
                "selected_import_member_count",
            },
            "verbose archive member",
        )
        if not isinstance(item["archive"], str) or not isinstance(item["member"], str):
            raise LinkageError("verbose archive/member name must be a string")
    if selections != sorted(selections, key=lambda item: (item["archive"], item["member"])):
        raise LinkageError("verbose archive members are not sorted")
    selected_keys: set[tuple[str, str]] = set()
    selected_imports: set[str] = set()
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
        _nonnegative_int(item["selected_code_member_count"], "selected code member count")
        _nonnegative_int(item["selected_import_member_count"], "selected import member count")
        if (
            loaded != item["selected_code_member_count"]
            or reading - loaded != item["selected_import_member_count"]
            or reading <= 0
        ):
            raise LinkageError("archive event count classification drifted")
        candidates = item["candidates"]
        if not isinstance(candidates, list) or not candidates:
            raise LinkageError("archive member candidates are empty")
        if any(not isinstance(candidate, dict) for candidate in candidates):
            raise LinkageError("archive member candidate must be an object")
        for candidate in candidates:
            _exact_fields(
                candidate, {"bytes", "format", "imported_dll", "sha256"},
                "archive member candidate",
            )
        if candidates != sorted(candidates, key=lambda candidate: (candidate["format"], candidate["sha256"])):
            raise LinkageError("archive member candidates are not sorted")
        code_candidates = 0
        import_candidates = 0
        candidate_imports: set[str] = set()
        for candidate in candidates:
            _positive_int(candidate["bytes"], "archive member candidate bytes")
            _sha(candidate["sha256"], "archive member candidate hash")
            if candidate["format"] == "short-import":
                if (
                    not isinstance(candidate["imported_dll"], str)
                    or candidate["imported_dll"] != candidate["imported_dll"].casefold()
                    or not candidate["imported_dll"].endswith(".dll")
                ):
                    raise LinkageError("short-import candidate DLL drifted")
                import_candidates += 1
                candidate_imports.add(candidate["imported_dll"])
            elif candidate["format"] in {"coff-object", "llvm-bitcode"}:
                if candidate["imported_dll"] is not None:
                    raise LinkageError("code-bearing candidate has an imported DLL")
                code_candidates += 1
            else:
                raise LinkageError("unknown archive member candidate format")
        if (
            item["selected_code_member_count"] > code_candidates
            or item["selected_import_member_count"] > import_candidates
        ):
            raise LinkageError("archive selection count exceeds candidates")
        if item["selected_import_member_count"]:
            if len(candidate_imports) != 1 or not candidate_imports.issubset(imports):
                raise LinkageError("selected short-import candidates are ambiguous")
            selected_imports.update(candidate_imports)
        expected_scope = (
            "exact"
            if item["selected_code_member_count"] == code_candidates
            and item["selected_import_member_count"] == import_candidates
            else "conservative-same-name-closure"
        )
        if item["candidate_scope"] != expected_scope:
            raise LinkageError("archive member candidate scope drifted")
        key = (item["archive"], item["member"])
        if key in selected_keys:
            raise LinkageError("duplicate verbose archive member")
        selected_keys.add(key)

    system_imports = _sorted_strings(verbose["system_imports"], "system imports")
    if system_imports != imports or system_imports != sorted(selected_imports):
        raise LinkageError("system import closure differs from PE imports")

    _positive_int(lld_map["live_section_count"], "lld_map.live_section_count")
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
                    (archive, item["member"]) not in selected_keys
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
