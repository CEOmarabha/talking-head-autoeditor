#!/usr/bin/env python3
"""Normalize validated in-tree PyInstaller file symlinks on macOS.

Only the ``engine`` and ``helper`` directories below one prepared Helper stage
are mutable. Every source path is inspected through held directory descriptors
with no-follow opens. A symlink is accepted only when its complete, acyclic
chain resolves to a single-link regular file inside the same frozen runtime.
The replacement trees contain regular files only. One canonical receipt binds
the source inventory, each resolved link, and the complete final inventory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "autoeditor-pyinstaller-symlink-normalization/v1"
RECEIPT_DIRECTORY = "licenses"
RECEIPT_FILENAME = "PYINSTALLER_SYMLINK_NORMALIZATION.json"
RUNTIME_NAMES = ("engine", "helper")
REQUIRED_EXECUTABLES = {
    "engine": "autoeditor-engine",
    "helper": "autoeditor-helper-daemon",
}
TARGET_ARCHES = ("arm64", "x64")
SHA256_RE = re.compile(r"[a-f0-9]{64}")
MAX_LINK_DEPTH = 40
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
SPECIAL_PERMISSION_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX
HELD_FD_APIS_AVAILABLE = (
    all(
        function in os.supports_dir_fd
        for function in (
            os.open,
            os.stat,
            os.readlink,
            os.rename,
            os.mkdir,
            os.unlink,
            os.rmdir,
        )
    )
    and os.listdir in os.supports_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


class NormalizationError(RuntimeError):
    """The staged frozen runtime violated the normalization contract."""


@dataclass(frozen=True)
class _TreePlan:
    root_mode: int
    source_entries: tuple[dict[str, Any], ...]
    directories: tuple[dict[str, Any], ...]
    files: tuple[dict[str, Any], ...]
    normalized_links: tuple[dict[str, Any], ...]


def canonical_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("extra " + ", ".join(extra))
    raise NormalizationError(
        f"{label} has wrong fields ({'; '.join(details)})"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise NormalizationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise NormalizationError(
            "PyInstaller symlink normalization is supported only on macOS"
        )
    if not HELD_FD_APIS_AVAILABLE:
        raise NormalizationError(
            "held-FD no-follow filesystem operations are unavailable"
        )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _read_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _write_flags() -> int:
    return (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _path_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)


def _mode(value: os.stat_result, label: str) -> int:
    result = stat.S_IMODE(value.st_mode)
    if result & SPECIAL_PERMISSION_BITS:
        raise NormalizationError(
            f"special permission bits are forbidden in frozen runtime: {label}"
        )
    return result


def _safe_name(value: str, label: str = "path component") -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\0" in value
        or unicodedata.normalize("NFC", value) != value
        or len(value.encode("utf-8")) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise NormalizationError(f"unsafe {label}: {value!r}")
    return value


def _safe_relative(value: Any, label: str = "path") -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise NormalizationError(f"unsafe {label}: {value!r}")
    parts = value.split("/")
    for part in parts:
        _safe_name(part, label)
    return "/".join(parts)


def _sorted_names(directory_fd: int, label: str) -> list[str]:
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise NormalizationError(f"cannot list held directory {label}: {exc}") from exc
    normalized: dict[str, str] = {}
    for name in names:
        _safe_name(name)
        folded = unicodedata.normalize("NFC", name).casefold()
        previous = normalized.get(folded)
        if previous is not None:
            raise NormalizationError(
                f"casefold collision in frozen runtime: {previous} and {name}"
            )
        normalized[folded] = name
    return sorted(names, key=lambda name: (name.casefold(), name))


def _open_directory_at(
    parent_fd: int, name: str, display: str
) -> tuple[int, os.stat_result]:
    _safe_name(name)
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode):
            raise NormalizationError(f"directory symlink is forbidden: {display}")
        if not stat.S_ISDIR(before.st_mode):
            raise NormalizationError(f"required directory is not plain: {display}")
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
        opened = os.fstat(descriptor)
        if _path_identity(before) != _path_identity(opened):
            os.close(descriptor)
            raise NormalizationError(
                f"directory changed while opening: {display}"
            )
        return descriptor, opened
    except NormalizationError:
        raise
    except OSError as exc:
        raise NormalizationError(f"cannot open held directory {display}: {exc}") from exc


def _open_stage_parent(stage_root: Path) -> tuple[int, str]:
    parts = list(stage_root.parts)
    if stage_root.is_absolute():
        current = os.open("/", _directory_flags())
        parts = parts[1:]
    else:
        current = os.open(".", _directory_flags())
    parts = [part for part in parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        os.close(current)
        raise NormalizationError(
            "stage root must name a child path without parent traversal"
        )
    for component in parts[:-1]:
        next_fd, _ = _open_directory_at(current, component, component)
        os.close(current)
        current = next_fd
    return current, _safe_name(parts[-1], "stage root")


def _open_relative_directory(root_fd: int, parts: list[str]) -> int:
    current = os.dup(root_fd)
    try:
        for component in parts:
            next_fd, _ = _open_directory_at(
                current, component, "/".join(parts)
            )
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def _normalize_link_target(parent: list[str], target: str) -> list[str]:
    if (
        not isinstance(target, str)
        or not target
        or target.startswith("/")
        or "\0" in target
    ):
        raise NormalizationError(
            f"symlink target must be a nonempty relative path: {target!r}"
        )
    result = list(parent)
    for component in target.split("/"):
        if component == ".":
            continue
        if component == "..":
            if not result:
                raise NormalizationError(
                    f"symlink target escapes its frozen runtime: {target}"
                )
            result.pop()
            continue
        _safe_name(component, "symlink target component")
        result.append(component)
    if not result:
        raise NormalizationError(
            f"symlink target resolves to the runtime directory: {target}"
        )
    return result


def _readlink_stable(
    parent_fd: int,
    name: str,
    before: os.stat_result,
    display: str,
) -> str:
    if before.st_nlink != 1:
        raise NormalizationError(
            f"symlink must have exactly one filesystem link: {display}"
        )
    try:
        target = os.readlink(name, dir_fd=parent_fd)
        after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise NormalizationError(f"cannot read symlink {display}: {exc}") from exc
    if _identity(before) != _identity(after):
        raise NormalizationError(f"symlink changed while reading: {display}")
    return target


def _open_resolved_regular(
    runtime_fd: int,
    link_parent: list[str],
    first_target: str,
    display: str,
) -> tuple[int, os.stat_result, str]:
    parts = _normalize_link_target(link_parent, first_target)
    seen: set[str] = set()
    for _ in range(MAX_LINK_DEPTH):
        relative = "/".join(parts)
        if relative in seen:
            raise NormalizationError(f"symlink cycle in frozen runtime: {display}")
        seen.add(relative)
        parent_fd = _open_relative_directory(runtime_fd, parts[:-1])
        try:
            name = parts[-1]
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                target = _readlink_stable(parent_fd, name, before, relative)
                parts = _normalize_link_target(parts[:-1], target)
                continue
            if not stat.S_ISREG(before.st_mode):
                raise NormalizationError(
                    f"symlink target is not a regular file: {relative}"
                )
            if before.st_nlink != 1:
                raise NormalizationError(
                    f"symlink target must have exactly one filesystem link: "
                    f"{relative}"
                )
            descriptor = os.open(name, _read_flags(), dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            if _identity(before) != _identity(opened):
                os.close(descriptor)
                raise NormalizationError(
                    f"symlink target changed while opening: {relative}"
                )
            return descriptor, opened, relative
        except NormalizationError:
            raise
        except OSError as exc:
            raise NormalizationError(
                f"cannot resolve symlink target {display}: {exc}"
            ) from exc
        finally:
            os.close(parent_fd)
    raise NormalizationError(f"symlink chain is too deep: {display}")


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise NormalizationError("short write while building normalized runtime")
        view = view[written:]


def _copy_or_hash_regular(
    source_fd: int,
    opened: os.stat_result,
    display: str,
    destination_parent_fd: int | None,
    destination_name: str | None,
) -> dict[str, Any]:
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        raise NormalizationError(
            f"source file must be a single-link regular file: {display}"
        )
    permission = _mode(opened, display)
    destination_fd: int | None = None
    try:
        if destination_parent_fd is not None:
            if destination_name is None:
                raise NormalizationError("internal destination name is missing")
            destination_fd = os.open(
                destination_name,
                _write_flags(),
                0o600,
                dir_fd=destination_parent_fd,
            )
        os.lseek(source_fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
            if destination_fd is not None:
                _write_all(destination_fd, chunk)
        after = os.fstat(source_fd)
        if _identity(opened) != _identity(after) or byte_count != opened.st_size:
            raise NormalizationError(
                f"source file changed while reading: {display}"
            )
        if destination_fd is not None:
            os.fchmod(destination_fd, permission)
            os.fsync(destination_fd)
            copied = os.fstat(destination_fd)
            if (
                not stat.S_ISREG(copied.st_mode)
                or copied.st_nlink != 1
                or copied.st_size != byte_count
                or stat.S_IMODE(copied.st_mode) != permission
            ):
                raise NormalizationError(
                    f"normalized file metadata drifted: {display}"
                )
        return {
            "bytes": byte_count,
            "mode": permission,
            "sha256": digest.hexdigest(),
        }
    except NormalizationError:
        raise
    except OSError as exc:
        raise NormalizationError(
            f"cannot copy frozen runtime file {display}: {exc}"
        ) from exc
    finally:
        if destination_fd is not None:
            os.close(destination_fd)


def _walk_source(
    directory_fd: int,
    runtime_fd: int,
    destination_fd: int | None,
    prefix: list[str],
    *,
    normalize_links: bool,
    source_entries: list[dict[str, Any]],
    directories: list[dict[str, Any]],
    files: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> None:
    directory_before = os.fstat(directory_fd)
    for name in _sorted_names(directory_fd, "/".join(prefix) or "."):
        relative_parts = [*prefix, name]
        relative = "/".join(relative_parts)
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(before.st_mode):
            child_mode = _mode(before, relative)
            child_fd, opened = _open_directory_at(
                directory_fd, name, relative
            )
            destination_child_fd: int | None = None
            try:
                if destination_fd is not None:
                    os.mkdir(name, 0o700, dir_fd=destination_fd)
                    destination_child_fd, _ = _open_directory_at(
                        destination_fd, name, relative
                    )
                    os.fchmod(destination_child_fd, child_mode)
                source_entries.append({
                    "kind": "directory",
                    "mode": child_mode,
                    "path": relative,
                })
                directories.append({"mode": child_mode, "path": relative})
                _walk_source(
                    child_fd,
                    runtime_fd,
                    destination_child_fd,
                    relative_parts,
                    normalize_links=normalize_links,
                    source_entries=source_entries,
                    directories=directories,
                    files=files,
                    links=links,
                )
                child_after = os.fstat(child_fd)
                path_after = os.stat(
                    name, dir_fd=directory_fd, follow_symlinks=False
                )
                if (
                    _identity(opened) != _identity(child_after)
                    or _identity(opened) != _identity(path_after)
                ):
                    raise NormalizationError(
                        f"source directory changed while scanning: {relative}"
                    )
            finally:
                if destination_child_fd is not None:
                    os.close(destination_child_fd)
                os.close(child_fd)
            continue
        if stat.S_ISLNK(before.st_mode):
            if not normalize_links:
                raise NormalizationError(
                    f"symlink remains in normalized runtime: {relative}"
                )
            target = _readlink_stable(
                directory_fd, name, before, relative
            )
            target_fd: int | None = None
            try:
                target_fd, target_stat, resolved = _open_resolved_regular(
                    runtime_fd, prefix, target, relative
                )
                metadata = _copy_or_hash_regular(
                    target_fd,
                    target_stat,
                    relative,
                    destination_fd,
                    name if destination_fd is not None else None,
                )
            finally:
                if target_fd is not None:
                    os.close(target_fd)
            path_after = os.stat(
                name, dir_fd=directory_fd, follow_symlinks=False
            )
            if _identity(before) != _identity(path_after):
                raise NormalizationError(
                    f"symlink changed while normalizing: {relative}"
                )
            source_entry = {
                **metadata,
                "kind": "symlink",
                "path": relative,
                "resolved_path": resolved,
                "target": target,
            }
            source_entries.append(source_entry)
            final_entry = {**metadata, "path": relative}
            files.append(final_entry)
            links.append({
                **final_entry,
                "resolved_path": resolved,
                "target": target,
            })
            continue
        if not stat.S_ISREG(before.st_mode):
            raise NormalizationError(
                f"special file is forbidden in frozen runtime: {relative}"
            )
        if before.st_nlink != 1:
            raise NormalizationError(
                f"file must have exactly one filesystem link: {relative}"
            )
        source_fd: int | None = None
        try:
            source_fd = os.open(name, _read_flags(), dir_fd=directory_fd)
            opened = os.fstat(source_fd)
            if _identity(before) != _identity(opened):
                raise NormalizationError(
                    f"source file changed while opening: {relative}"
                )
            metadata = _copy_or_hash_regular(
                source_fd,
                opened,
                relative,
                destination_fd,
                name if destination_fd is not None else None,
            )
        except NormalizationError:
            raise
        except OSError as exc:
            raise NormalizationError(
                f"cannot open frozen runtime file {relative}: {exc}"
            ) from exc
        finally:
            if source_fd is not None:
                os.close(source_fd)
        path_after = os.stat(
            name, dir_fd=directory_fd, follow_symlinks=False
        )
        if _identity(before) != _identity(path_after):
            raise NormalizationError(
                f"source file changed while scanning: {relative}"
            )
        source_entries.append({**metadata, "kind": "file", "path": relative})
        files.append({**metadata, "path": relative})
    directory_after = os.fstat(directory_fd)
    if _identity(directory_before) != _identity(directory_after):
        raise NormalizationError(
            f"source directory changed while scanning: {'/'.join(prefix) or '.'}"
        )


def _plan_tree(
    runtime_fd: int,
    destination_fd: int | None,
    *,
    normalize_links: bool,
) -> _TreePlan:
    root_before = os.fstat(runtime_fd)
    if not stat.S_ISDIR(root_before.st_mode):
        raise NormalizationError("frozen runtime root is not a directory")
    root_mode = _mode(root_before, ".")
    if destination_fd is not None:
        os.fchmod(destination_fd, root_mode)
    source_entries: list[dict[str, Any]] = []
    directories: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    _walk_source(
        runtime_fd,
        runtime_fd,
        destination_fd,
        [],
        normalize_links=normalize_links,
        source_entries=source_entries,
        directories=directories,
        files=files,
        links=links,
    )
    root_after = os.fstat(runtime_fd)
    if _identity(root_before) != _identity(root_after):
        raise NormalizationError("frozen runtime root changed while scanning")
    key = lambda entry: entry["path"]
    return _TreePlan(
        root_mode=root_mode,
        source_entries=tuple(sorted(source_entries, key=key)),
        directories=tuple(sorted(directories, key=key)),
        files=tuple(sorted(files, key=key)),
        normalized_links=tuple(sorted(links, key=key)),
    )


def _source_inventory_sha256(plan: _TreePlan) -> str:
    return _source_inventory_sha256_from_entries(
        plan.root_mode, list(plan.source_entries)
    )


def _source_inventory_sha256_from_entries(
    root_mode: int,
    entries: list[dict[str, Any]],
) -> str:
    payload = {
        "entries": sorted(entries, key=lambda entry: entry["path"]),
        "root_mode": root_mode,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _runtime_payload(plan: _TreePlan) -> dict[str, Any]:
    return {
        "directories": list(plan.directories),
        "files": list(plan.files),
        "normalized_links": list(plan.normalized_links),
        "root_mode": plan.root_mode,
        "source_inventory_sha256": _source_inventory_sha256(plan),
    }


def _require_runtime_executable(runtime_name: str, plan: _TreePlan) -> None:
    required = REQUIRED_EXECUTABLES[runtime_name]
    entry = next(
        (item for item in plan.files if item["path"] == required), None
    )
    if entry is None or not entry["mode"] & 0o111:
        raise NormalizationError(
            f"{runtime_name} is missing required executable {required}"
        )


def _expected_payload(
    target_arch: str, plans: Mapping[str, _TreePlan]
) -> dict[str, Any]:
    if target_arch not in TARGET_ARCHES:
        raise NormalizationError(f"unsupported Mac target architecture: {target_arch}")
    if set(plans) != set(RUNTIME_NAMES):
        raise NormalizationError("normalization plans must cover engine and helper")
    return {
        "roots": list(RUNTIME_NAMES),
        "runtimes": {
            name: _runtime_payload(plans[name]) for name in RUNTIME_NAMES
        },
        "schema": SCHEMA,
        "target": {"arch": target_arch, "os": "mac"},
    }


def _validate_mode(value: Any, label: str) -> int:
    if type(value) is not int or value < 0 or value > 0o777:
        raise NormalizationError(f"invalid mode in {label}")
    return value


def _validate_sorted_entries(
    entries: Any,
    fields: set[str],
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise NormalizationError(f"{label} must be an array")
    paths: list[str] = []
    result: list[dict[str, Any]] = []
    folded: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise NormalizationError(f"{label} entry must be an object")
        _exact_keys(entry, fields, f"{label} entry")
        path = _safe_relative(entry["path"], f"{label} path")
        key = path.casefold()
        if key in folded:
            raise NormalizationError(
                f"duplicate or casefold-colliding {label} path: {path}"
            )
        folded[key] = path
        paths.append(path)
        result.append(entry)
    if paths != sorted(paths):
        raise NormalizationError(f"{label} paths are not sorted")
    return result


def _validate_receipt_payload(
    payload: Any,
    raw: bytes,
    target_arch: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NormalizationError("normalization receipt must be an object")
    _exact_keys(payload, {"roots", "runtimes", "schema", "target"}, "receipt")
    if payload["schema"] != SCHEMA:
        raise NormalizationError("normalization receipt has wrong schema")
    if payload["target"] != {"arch": target_arch, "os": "mac"}:
        raise NormalizationError("normalization receipt has wrong target")
    if payload["roots"] != list(RUNTIME_NAMES):
        raise NormalizationError("normalization receipt has wrong runtime roots")
    runtimes = payload["runtimes"]
    if not isinstance(runtimes, dict) or set(runtimes) != set(RUNTIME_NAMES):
        raise NormalizationError(
            "normalization receipt must contain only engine and helper"
        )
    for runtime_name in RUNTIME_NAMES:
        runtime = runtimes[runtime_name]
        if not isinstance(runtime, dict):
            raise NormalizationError(f"receipt {runtime_name} must be an object")
        _exact_keys(
            runtime,
            {
                "directories",
                "files",
                "normalized_links",
                "root_mode",
                "source_inventory_sha256",
            },
            f"receipt {runtime_name}",
        )
        _validate_mode(runtime["root_mode"], f"receipt {runtime_name}")
        source_digest = runtime["source_inventory_sha256"]
        if not isinstance(source_digest, str) or not SHA256_RE.fullmatch(
            source_digest
        ):
            raise NormalizationError(
                f"invalid source inventory digest for {runtime_name}"
            )
        directories = _validate_sorted_entries(
            runtime["directories"], {"mode", "path"}, f"{runtime_name} directories"
        )
        files = _validate_sorted_entries(
            runtime["files"],
            {"bytes", "mode", "path", "sha256"},
            f"{runtime_name} files",
        )
        links = _validate_sorted_entries(
            runtime["normalized_links"],
            {"bytes", "mode", "path", "resolved_path", "sha256", "target"},
            f"{runtime_name} normalized links",
        )
        directory_paths = {entry["path"] for entry in directories}
        file_by_path = {entry["path"]: entry for entry in files}
        if directory_paths & set(file_by_path):
            raise NormalizationError(
                f"receipt {runtime_name} reuses a file and directory path"
            )
        for entry in directories:
            _validate_mode(entry["mode"], f"{runtime_name} directory")
        for entry in files:
            _validate_mode(entry["mode"], f"{runtime_name} file")
            if type(entry["bytes"]) is not int or entry["bytes"] < 0:
                raise NormalizationError(
                    f"invalid file size in receipt {runtime_name}"
                )
            if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(
                entry["sha256"]
            ):
                raise NormalizationError(
                    f"invalid file digest in receipt {runtime_name}"
                )
        for entry in links:
            path = entry["path"]
            final = file_by_path.get(path)
            comparable = {
                key: entry[key] for key in ("bytes", "mode", "path", "sha256")
            }
            if final != comparable:
                raise NormalizationError(
                    f"normalized link does not match final file: {runtime_name}/{path}"
                )
            target = entry["target"]
            resolved = _safe_relative(
                entry["resolved_path"], "resolved symlink target"
            )
            parent = path.split("/")[:-1]
            # The original one-hop target may itself have been a symlink.  The
            # normalizer records both that safe first hop and the final regular
            # file reached by the fully validated chain.  Once normalization
            # has replaced every link, only the final path still exists as a
            # semantic target, so revalidate the first hop's containment here
            # without incorrectly requiring it to equal the final path.
            first_hop = "/".join(_normalize_link_target(parent, target))
            for target_label, target_path in (
                ("first hop", first_hop),
                ("resolved target", resolved),
            ):
                target_entry = file_by_path.get(target_path)
                if target_entry is None:
                    raise NormalizationError(
                        f"normalized link {target_label} is absent from final "
                        f"inventory: {runtime_name}/{path}"
                    )
                if any(
                    target_entry[key] != entry[key]
                    for key in ("bytes", "mode", "sha256")
                ):
                    raise NormalizationError(
                        f"normalized link {target_label} does not match copied "
                        f"bytes: {runtime_name}/{path}"
                    )
        link_by_path = {entry["path"]: entry for entry in links}
        reconstructed_source_entries = [
            {**entry, "kind": "directory"} for entry in directories
        ]
        for entry in files:
            link = link_by_path.get(entry["path"])
            if link is None:
                reconstructed_source_entries.append({**entry, "kind": "file"})
            else:
                reconstructed_source_entries.append(
                    {**link, "kind": "symlink"}
                )
        reconstructed_digest = _source_inventory_sha256_from_entries(
            runtime["root_mode"], reconstructed_source_entries
        )
        if source_digest != reconstructed_digest:
            raise NormalizationError(
                f"source inventory digest does not match reconstructed "
                f"{runtime_name} inventory"
            )
        required = REQUIRED_EXECUTABLES[runtime_name]
        required_entry = file_by_path.get(required)
        if required_entry is None or not required_entry["mode"] & 0o111:
            raise NormalizationError(
                f"receipt {runtime_name} is missing required executable "
                f"{required}"
            )
    if raw != canonical_json_bytes(payload):
        raise NormalizationError("normalization receipt is not canonical")
    return payload


def _read_receipt(licenses_fd: int, target_arch: str) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        before = os.stat(
            RECEIPT_FILENAME,
            dir_fd=licenses_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise NormalizationError(
                "normalization receipt must be a single-link regular file"
            )
        if before.st_size <= 0 or before.st_size > MAX_RECEIPT_BYTES:
            raise NormalizationError("normalization receipt has invalid size")
        descriptor = os.open(RECEIPT_FILENAME, _read_flags(), dir_fd=licenses_fd)
        opened = os.fstat(descriptor)
        if _identity(before) != _identity(opened):
            raise NormalizationError(
                "normalization receipt changed while opening"
            )
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RECEIPT_BYTES:
                raise NormalizationError("normalization receipt is too large")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(
            RECEIPT_FILENAME,
            dir_fd=licenses_fd,
            follow_symlinks=False,
        )
        if _identity(opened) != _identity(after) or _identity(opened) != _identity(
            path_after
        ):
            raise NormalizationError(
                "normalization receipt changed while reading"
            )
        raw = b"".join(chunks)
    except NormalizationError:
        raise
    except OSError as exc:
        raise NormalizationError(f"cannot read normalization receipt: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except NormalizationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizationError(
            f"cannot decode normalization receipt: {exc}"
        ) from exc
    return _validate_receipt_payload(payload, raw, target_arch)


def _write_receipt(licenses_fd: int, payload: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(payload)
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            RECEIPT_FILENAME,
            _write_flags(),
            0o600,
            dir_fd=licenses_fd,
        )
        created = True
        _write_all(descriptor, data)
        os.fchmod(descriptor, 0o644)
        os.fsync(descriptor)
        written = os.fstat(descriptor)
        if (
            not stat.S_ISREG(written.st_mode)
            or written.st_nlink != 1
            or written.st_size != len(data)
        ):
            raise NormalizationError("normalization receipt write drifted")
    except NormalizationError:
        raise
    except OSError as exc:
        raise NormalizationError(f"cannot write normalization receipt: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created and sys.exc_info()[0] is not None:
            try:
                os.unlink(RECEIPT_FILENAME, dir_fd=licenses_fd)
            except OSError:
                pass


def _entry_exists(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise NormalizationError(f"cannot inspect transaction entry {name}: {exc}") from exc


def _delete_entry(parent_fd: int, name: str) -> None:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISDIR(before.st_mode):
        child_fd, opened = _open_directory_at(parent_fd, name, name)
        try:
            for child in _sorted_names(child_fd, name):
                _delete_entry(child_fd, child)
            after = os.fstat(child_fd)
            if _path_identity(opened) != _path_identity(after):
                raise NormalizationError(
                    f"transaction directory changed during cleanup: {name}"
                )
        finally:
            os.close(child_fd)
        os.rmdir(name, dir_fd=parent_fd)
        return
    os.unlink(name, dir_fd=parent_fd)


def _create_transaction(parent_fd: int) -> tuple[str, int]:
    for _ in range(32):
        name = ".autoeditor-pyinstaller-normalize-" + secrets.token_hex(12)
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            descriptor, _ = _open_directory_at(parent_fd, name, name)
            return name, descriptor
        except FileExistsError:
            continue
        except OSError as exc:
            raise NormalizationError(
                f"cannot create normalization transaction: {exc}"
            ) from exc
    raise NormalizationError("cannot allocate a unique normalization transaction")


def _verify_open_stage(
    stage_fd: int,
    licenses_fd: int,
    target_arch: str,
) -> dict[str, Any]:
    payload = _read_receipt(licenses_fd, target_arch)
    for runtime_name in RUNTIME_NAMES:
        runtime_fd, _ = _open_directory_at(
            stage_fd, runtime_name, runtime_name
        )
        try:
            observed = _plan_tree(
                runtime_fd, None, normalize_links=False
            )
        finally:
            os.close(runtime_fd)
        runtime = payload["runtimes"][runtime_name]
        if (
            observed.root_mode != runtime["root_mode"]
            or list(observed.directories) != runtime["directories"]
            or list(observed.files) != runtime["files"]
            or observed.normalized_links
        ):
            raise NormalizationError(
                f"normalized {runtime_name} inventory does not match receipt"
            )
    return payload


def _open_stage(
    stage_root: Path,
) -> tuple[int, int, str, os.stat_result, int, os.stat_result]:
    parent_fd, stage_name = _open_stage_parent(stage_root)
    stage_fd: int | None = None
    try:
        stage_fd, stage_stat = _open_directory_at(
            parent_fd, stage_name, os.fspath(stage_root)
        )
        licenses_fd, licenses_stat = _open_directory_at(
            stage_fd, RECEIPT_DIRECTORY, RECEIPT_DIRECTORY
        )
        return (
            parent_fd,
            stage_fd,
            stage_name,
            stage_stat,
            licenses_fd,
            licenses_stat,
        )
    except BaseException:
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(parent_fd)
        raise


def _verify_stage_identity(
    parent_fd: int,
    stage_fd: int,
    stage_name: str,
    opened: os.stat_result,
) -> None:
    current = os.fstat(stage_fd)
    path_current = os.stat(
        stage_name, dir_fd=parent_fd, follow_symlinks=False
    )
    if (
        _path_identity(opened) != _path_identity(current)
        or _path_identity(opened) != _path_identity(path_current)
    ):
        raise NormalizationError("stage root changed during normalization")


def _verify_licenses_identity(
    stage_fd: int,
    licenses_fd: int,
    opened: os.stat_result,
) -> None:
    current = os.fstat(licenses_fd)
    path_current = os.stat(
        RECEIPT_DIRECTORY,
        dir_fd=stage_fd,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISDIR(path_current.st_mode)
        or _path_identity(opened) != _path_identity(current)
        or _path_identity(opened) != _path_identity(path_current)
    ):
        raise NormalizationError(
            "licenses directory changed during normalization"
        )


def verify_stage(stage_root: Path, target_arch: str) -> dict[str, Any]:
    _require_macos()
    try:
        (
            parent_fd,
            stage_fd,
            stage_name,
            stage_stat,
            licenses_fd,
            licenses_stat,
        ) = _open_stage(stage_root)
    except NormalizationError:
        raise
    except OSError as exc:
        raise NormalizationError(f"cannot open prepared Mac stage: {exc}") from exc
    try:
        try:
            payload = _verify_open_stage(stage_fd, licenses_fd, target_arch)
            _verify_licenses_identity(
                stage_fd, licenses_fd, licenses_stat
            )
            _verify_stage_identity(
                parent_fd, stage_fd, stage_name, stage_stat
            )
            return payload
        except NormalizationError:
            raise
        except OSError as exc:
            raise NormalizationError(
                f"cannot verify normalized Mac stage: {exc}"
            ) from exc
    finally:
        os.close(licenses_fd)
        os.close(stage_fd)
        os.close(parent_fd)


def normalize_stage(stage_root: Path, target_arch: str) -> dict[str, Any]:
    _require_macos()
    if target_arch not in TARGET_ARCHES:
        raise NormalizationError(f"unsupported Mac target architecture: {target_arch}")
    try:
        (
            parent_fd,
            stage_fd,
            stage_name,
            stage_stat,
            licenses_fd,
            licenses_stat,
        ) = _open_stage(stage_root)
    except NormalizationError:
        raise
    except OSError as exc:
        raise NormalizationError(f"cannot open prepared Mac stage: {exc}") from exc
    transaction_name: str | None = None
    transaction_fd: int | None = None
    swapped: list[str] = []
    receipt_created = False
    committed = False
    runtime_stats: dict[str, os.stat_result] = {}
    try:
        if _entry_exists(licenses_fd, RECEIPT_FILENAME):
            raise NormalizationError(
                "normalization receipt already exists; use --verify-only"
            )
        transaction_name, transaction_fd = _create_transaction(parent_fd)
        if os.fstat(parent_fd).st_dev != os.fstat(transaction_fd).st_dev:
            raise NormalizationError(
                "normalization transaction is on another filesystem"
            )
        plans: dict[str, _TreePlan] = {}
        for runtime_name in RUNTIME_NAMES:
            runtime_fd, runtime_stat = _open_directory_at(
                stage_fd, runtime_name, runtime_name
            )
            runtime_stats[runtime_name] = runtime_stat
            replacement_name = f"replacement-{runtime_name}"
            os.mkdir(replacement_name, 0o700, dir_fd=transaction_fd)
            replacement_fd, _ = _open_directory_at(
                transaction_fd, replacement_name, replacement_name
            )
            try:
                copied = _plan_tree(
                    runtime_fd, replacement_fd, normalize_links=True
                )
                _require_runtime_executable(runtime_name, copied)
                rescanned = _plan_tree(
                    runtime_fd, None, normalize_links=True
                )
                if copied != rescanned:
                    raise NormalizationError(
                        f"source {runtime_name} changed across normalization scans"
                    )
                final = _plan_tree(
                    replacement_fd, None, normalize_links=False
                )
                if (
                    final.root_mode != copied.root_mode
                    or final.directories != copied.directories
                    or final.files != copied.files
                    or final.normalized_links
                ):
                    raise NormalizationError(
                        f"prepared normalized {runtime_name} inventory drifted"
                    )
                plans[runtime_name] = copied
            finally:
                os.close(replacement_fd)
                os.close(runtime_fd)

        payload = _expected_payload(target_arch, plans)
        _verify_licenses_identity(stage_fd, licenses_fd, licenses_stat)
        for runtime_name in RUNTIME_NAMES:
            current = os.stat(
                runtime_name,
                dir_fd=stage_fd,
                follow_symlinks=False,
            )
            if _identity(current) != _identity(runtime_stats[runtime_name]):
                raise NormalizationError(
                    f"source {runtime_name} changed before commit"
                )
            backup_name = f"original-{runtime_name}"
            replacement_name = f"replacement-{runtime_name}"
            os.rename(
                runtime_name,
                backup_name,
                src_dir_fd=stage_fd,
                dst_dir_fd=transaction_fd,
            )
            try:
                os.rename(
                    replacement_name,
                    runtime_name,
                    src_dir_fd=transaction_fd,
                    dst_dir_fd=stage_fd,
                )
            except BaseException:
                os.rename(
                    backup_name,
                    runtime_name,
                    src_dir_fd=transaction_fd,
                    dst_dir_fd=stage_fd,
                )
                raise
            swapped.append(runtime_name)

        _write_receipt(licenses_fd, payload)
        receipt_created = True
        verified = _verify_open_stage(stage_fd, licenses_fd, target_arch)
        if verified != payload:
            raise NormalizationError("normalization receipt verification drifted")
        _verify_licenses_identity(stage_fd, licenses_fd, licenses_stat)
        _verify_stage_identity(
            parent_fd, stage_fd, stage_name, stage_stat
        )
        # This is the irreversible commit boundary.  The normalized runtime
        # trees and their fixed receipt have been independently reopened and
        # verified through held directories.  Everything below only deletes
        # private backups; a cleanup failure must never undo the valid stage.
        committed = True
        for runtime_name in RUNTIME_NAMES:
            _delete_entry(transaction_fd, f"original-{runtime_name}")
        return payload
    except BaseException as exc:
        if committed:
            if isinstance(exc, (NormalizationError, OSError)):
                raise NormalizationError(
                    "normalization committed and verified, but backup cleanup "
                    f"failed: {exc}"
                ) from exc
            raise
        rollback_errors: list[str] = []
        if receipt_created:
            try:
                os.unlink(RECEIPT_FILENAME, dir_fd=licenses_fd)
            except OSError as rollback_exc:
                rollback_errors.append(
                    f"cannot remove failed receipt: {rollback_exc}"
                )
        if transaction_fd is not None:
            for runtime_name in reversed(swapped):
                try:
                    failed_name = f"failed-{runtime_name}"
                    os.rename(
                        runtime_name,
                        failed_name,
                        src_dir_fd=stage_fd,
                        dst_dir_fd=transaction_fd,
                    )
                    os.rename(
                        f"original-{runtime_name}",
                        runtime_name,
                        src_dir_fd=transaction_fd,
                        dst_dir_fd=stage_fd,
                    )
                except OSError as rollback_exc:
                    rollback_errors.append(
                        f"cannot restore {runtime_name}: {rollback_exc}"
                    )
        if rollback_errors:
            raise NormalizationError(
                f"{exc}; rollback failed: {'; '.join(rollback_errors)}"
            ) from exc
        if isinstance(exc, NormalizationError):
            raise
        if isinstance(exc, OSError):
            raise NormalizationError(
                f"cannot normalize prepared Mac stage: {exc}"
            ) from exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        if transaction_fd is not None:
            try:
                for entry in _sorted_names(transaction_fd, "transaction"):
                    _delete_entry(transaction_fd, entry)
            except BaseException as exc:
                cleanup_error = exc
            os.close(transaction_fd)
        if transaction_name is not None:
            try:
                os.rmdir(transaction_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        os.close(licenses_fd)
        os.close(stage_fd)
        os.close(parent_fd)
        if cleanup_error is not None and sys.exc_info()[0] is None:
            if committed:
                raise NormalizationError(
                    "normalization committed and verified, but transaction "
                    f"cleanup failed: {cleanup_error}"
                ) from cleanup_error
            raise cleanup_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize validated in-tree PyInstaller file symlinks in the "
            "Mac Helper engine and helper runtimes"
        )
    )
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--target-arch", choices=TARGET_ARCHES, required=True)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify the fixed receipt and regular-file runtime trees",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.verify_only:
            payload = verify_stage(args.stage_root, args.target_arch)
        else:
            payload = normalize_stage(args.stage_root, args.target_arch)
    except NormalizationError as exc:
        raise SystemExit(str(exc)) from exc
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    print(f"PyInstaller normalization receipt SHA256: {digest}")


if __name__ == "__main__":
    main()
