#!/usr/bin/env python3
"""Create and verify the immutable input closure for an llvm-mingw link."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


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
SYSTEM_IMPORT_ARCHIVES = {
    "libadvapi32.a",
    "libbcrypt.a",
    "libkernel32.a",
    "libmsvcrt.a",
    "libole32.a",
    "libpsapi.a",
    "libshell32.a",
    "libuser32.a",
}


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
        return "ffmpeg", "project-static-code"
    if path == "build/autoeditor-media/prefix/lib/libx264.a":
        return "x264", "project-static-code"
    if path == "build/autoeditor-media/prefix/lib/libz.a":
        return "zlib", "project-static-code"
    if path.startswith("build/autoeditor-media/prefix/"):
        raise LinkageError(f"undeclared prefix link input: {path}")
    if path.startswith("opt/llvm-mingw/lib/clang/"):
        return "llvm-project", "toolchain-runtime-static"
    if path.startswith("opt/llvm-mingw/x86_64-w64-mingw32/lib/"):
        if name.startswith(("libunwind", "libc++", "libcxx")):
            return "llvm-project", "toolchain-runtime-static"
        if re.fullmatch(r"(?:dll)?crt(?:begin|end|2u?|1u?)\.o", name, re.IGNORECASE):
            return "mingw-w64", "toolchain-startup-object"
        if name.casefold() in SYSTEM_IMPORT_ARCHIVES:
            return "mingw-w64", "system-import-archive"
        return "mingw-w64", "toolchain-runtime-static"
    raise LinkageError(f"link input is outside every allowed source root: {path}")


def _reproducer_manifest(path: Path, program: str) -> tuple[dict[str, Any], dict[str, str]]:
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
    if "lldmap" not in response_text.casefold() or "verbose" not in response_text.casefold():
        raise LinkageError("LLD response lacks lldmap or verbose capture flags")
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
    return ({
        "bytes": len(raw),
        "inputs": inputs,
        "response_bytes": len(response),
        "response_sha256": sha256_bytes(response),
        "sha256": sha256_bytes(raw),
    }, {name: paths[0] for name, paths in basename_paths.items()})


def _map_receipt(path: Path) -> dict[str, Any]:
    raw = _read_regular(path, "LLD map")
    text = _decode_text(raw, "LLD map")
    if not text.startswith("Address  Size     Align Out     In      Symbol\n"):
        raise LinkageError("LLD map header drifted")
    map_inputs = []
    live_section_count = 0
    for line in text.splitlines()[1:]:
        match = MAP_INPUT_RE.fullmatch(line)
        if match:
            map_inputs.append(match.group(1))
            live_section_count += 1
    if live_section_count == 0:
        raise LinkageError("LLD map contains no live input sections")
    return {
        "bytes": len(raw),
        "input_files": sorted(set(map_inputs)),
        "live_section_count": live_section_count,
        "sha256": sha256_bytes(raw),
    }


def _verbose_receipt(path: Path, basename_paths: dict[str, str]) -> dict[str, Any]:
    raw = _read_regular(path, "LLD verbose log")
    text = _decode_text(raw, "LLD verbose log")
    selections: dict[tuple[str, str], set[str]] = {}
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
        selections.setdefault((archive_path, match.group("member")), set()).add(
            match.group("event").casefold()
        )
    if not selections:
        raise LinkageError("LLD verbose log contains no selected archive members")
    records = []
    for (archive_path, member), events in sorted(selections.items()):
        origin, input_class = _origin_for(archive_path)
        records.append({
            "archive": archive_path,
            "archive_class": input_class,
            "events": sorted(events),
            "member": member,
            "origin": origin,
        })
    return {
        "bytes": len(raw),
        "selected_archive_members": records,
        "sha256": sha256_bytes(raw),
    }


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
    if len(executable) < 2 or executable[:2] != b"MZ":
        raise LinkageError("unstripped executable is not a PE file")
    repro_receipt, basename_paths = _reproducer_manifest(reproduce, program)
    receipt = {
        "lld_map": _map_receipt(lld_map),
        "program": program,
        "reproducer": repro_receipt,
        "schema": SCHEMA,
        "unstripped_executable": {
            "bytes": len(executable),
            "filename": PROGRAMS[program],
            "sha256": sha256_bytes(executable),
        },
        "verbose_log": _verbose_receipt(verbose_log, basename_paths),
    }
    validate_receipt(receipt)
    return receipt


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise LinkageError(f"{label} fields drifted")


def _sha(value: Any, label: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise LinkageError(f"{label} is not a SHA-256 digest")


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
    _exact_fields(executable, {"bytes", "filename", "sha256"}, "unstripped executable")
    if executable["filename"] != PROGRAMS[value["program"]]:
        raise LinkageError("unstripped executable filename drifted")
    if not isinstance(executable["bytes"], int) or executable["bytes"] <= 0:
        raise LinkageError("unstripped executable byte count is invalid")
    _sha(executable["sha256"], "unstripped executable hash")
    for key in ("lld_map", "verbose_log", "reproducer"):
        section = value[key]
        if not isinstance(section, dict):
            raise LinkageError(f"{key} receipt must be an object")
        for field in ("bytes",):
            if not isinstance(section.get(field), int) or section[field] <= 0:
                raise LinkageError(f"{key}.{field} is invalid")
        _sha(section.get("sha256"), f"{key}.sha256")
    inputs = value["reproducer"].get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise LinkageError("reproducer inputs are empty")
    if inputs != sorted(inputs, key=lambda item: item.get("path", "")):
        raise LinkageError("reproducer inputs are not sorted")
    for item in inputs:
        if not isinstance(item, dict):
            raise LinkageError("reproducer input must be an object")
        _exact_fields(item, {"bytes", "class", "origin", "path", "sha256"}, "reproducer input")
        _origin_for(item["path"])
        _sha(item["sha256"], "reproducer input hash")
    selections = value["verbose_log"].get("selected_archive_members")
    if not isinstance(selections, list) or not selections:
        raise LinkageError("verbose selected archive members are empty")


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
            if args.receipt.exists() or args.receipt.is_symlink():
                raise LinkageError("refusing to replace an existing linkage receipt")
            args.receipt.write_bytes(raw)
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
