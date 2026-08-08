#!/usr/bin/env python3
"""Build and verify deterministic, offline corresponding-source bundles."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import posixpath
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Callable, Iterable
from urllib.parse import parse_qsl, unquote, urlsplit


LOCK_SCHEMA = "autoeditor-native-media-sources/v1"
MANIFEST_SCHEMA = "autoeditor-corresponding-source-bundle/v1"
BUNDLE_ROOT = "autoeditor-corresponding-source"
LOCK_MEMBER = f"{BUNDLE_ROOT}/LOCK.json"
MANIFEST_MEMBER = f"{BUNDLE_ROOT}/MANIFEST.json"
REPOSITORY_PREFIX = f"{BUNDLE_ROOT}/repository"
UPSTREAM_PREFIX = f"{BUNDLE_ROOT}/upstream"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._+-]*\Z")
VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*\Z")
MOVING_REFERENCE_PATTERN = re.compile(
    r"(?:^|[./?#&=_-])(latest|nightly|snapshot|main|master|head|trunk|"
    r"develop|development|branch|branches)(?:$|[./?#&=_-])",
    re.IGNORECASE,
)
LOCK_FIELDS = {"schema", "provenance_status", "sources"}
SOURCE_FIELDS = {
    "id", "version", "archive", "source_url", "sha256",
    "license", "build", "patches",
}
MANIFEST_FIELDS = {
    "schema", "archive_format", "root", "normalization", "lock",
    "repository", "sources", "entries",
}
MANIFEST_SOURCE_FIELDS = {
    "id", "version", "archive", "source_url", "sha256",
}
REPOSITORY_FIELDS = {
    "commit", "commit_object", "object_format", "path", "tree",
}
ENTRY_FIELDS = {"path", "type", "mode", "size", "sha256"}
SYMLINK_ENTRY_FIELDS = ENTRY_FIELDS | {"link_target"}
NORMALIZATION = {
    "file_mode": "0644",
    "executable_mode": "0755",
    "symlink_mode": "0777",
    "gid": 0,
    "gname": "",
    "mtime": 0,
    "order": "utf8-bytewise-path",
    "uid": 0,
    "uname": "",
}
GIT_OBJECT_FORMATS = {"sha1": 40, "sha256": 64}
MAX_COMMIT_OBJECT_BYTES = 16 * 1024 * 1024


class SourceBundleError(ValueError):
    """The source lock or bundle violates the release contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceBundleError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[dict, bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceBundleError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceBundleError(f"JSON root must be an object: {path}")
    return value, raw


def _parse_json_bytes(raw: bytes, label: str) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceBundleError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceBundleError(f"{label} root must be an object")
    return value


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_exact_fields(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise SourceBundleError(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise SourceBundleError(f"{label} has unknown fields: {', '.join(unknown)}")


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SourceBundleError(f"{label} must be a non-empty trimmed string")
    if "\x00" in value:
        raise SourceBundleError(f"{label} contains a NUL byte")
    return value


def _require_string_entries(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SourceBundleError(f"{label} must have at least one entry")
    result = [_require_string(item, f"{label} entry") for item in value]
    if len(set(result)) != len(result):
        raise SourceBundleError(f"{label} contains duplicate entries")
    return result


def _validate_https_url(value: object, label: str) -> str:
    url = _require_string(value, label)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SourceBundleError(f"{label} must be an HTTPS URL without credentials or fragments")
    decoded_path = unquote(parsed.path)
    moving_text = decoded_path
    moving_text += "?" + "&".join(f"{key}={item}" for key, item in parse_qsl(parsed.query))
    if "/refs/heads/" in decoded_path.casefold() or "/branches/" in decoded_path.casefold():
        raise SourceBundleError(f"{label} may not reference a branch")
    if any(key.casefold() in {"branch", "head"} for key, _ in parse_qsl(parsed.query)):
        raise SourceBundleError(f"{label} may not reference a branch")
    if MOVING_REFERENCE_PATTERN.search(moving_text):
        raise SourceBundleError(f"{label} may not use a moving reference")
    return url


def _validate_version(value: object, label: str) -> str:
    version = _require_string(value, label)
    if not VERSION_PATTERN.fullmatch(version):
        raise SourceBundleError(f"{label} must be an exact version without spaces or slashes")
    if MOVING_REFERENCE_PATTERN.search(version):
        raise SourceBundleError(f"{label} may not use a moving reference")
    return version


def _validate_member_path(value: object, label: str, *, basename_only: bool = False) -> str:
    path = _require_string(value, label)
    if (
        path.startswith("/")
        or "\\" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        raise SourceBundleError(f"{label} must be a portable relative POSIX path")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SourceBundleError(f"{label} contains an unsafe path segment")
    if basename_only and len(parts) != 1:
        raise SourceBundleError(f"{label} must be a file name, not a path")
    return path


def validate_lock(value: dict) -> dict:
    """Validate and return a normalized native-media source lock."""
    _require_exact_fields(value, LOCK_FIELDS, "source lock")
    if value["schema"] != LOCK_SCHEMA:
        raise SourceBundleError(f"source lock schema must be {LOCK_SCHEMA}")
    if value["provenance_status"] != "complete":
        raise SourceBundleError("source lock provenance_status must be complete")
    raw_sources = value["sources"]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise SourceBundleError("source lock sources must have at least one entry")

    sources = []
    seen_ids: set[str] = set()
    seen_archives: set[str] = set()
    seen_urls: set[str] = set()
    for index, raw in enumerate(raw_sources):
        label = f"source[{index}]"
        if not isinstance(raw, dict):
            raise SourceBundleError(f"{label} must be an object")
        _require_exact_fields(raw, SOURCE_FIELDS, label)
        source_id = _require_string(raw["id"], f"{label}.id")
        if not IDENTIFIER_PATTERN.fullmatch(source_id):
            raise SourceBundleError(f"{label}.id has invalid characters")
        version = _validate_version(raw["version"], f"{label}.version")
        archive = _validate_member_path(
            raw["archive"], f"{label}.archive", basename_only=True
        )
        if MOVING_REFERENCE_PATTERN.search(archive):
            raise SourceBundleError(f"{label}.archive may not use a moving reference")
        source_url = _validate_https_url(raw["source_url"], f"{label}.source_url")
        sha256 = _require_string(raw["sha256"], f"{label}.sha256")
        if not SHA256_PATTERN.fullmatch(sha256):
            raise SourceBundleError(f"{label}.sha256 must be 64 lowercase hex characters")
        license_entries = _require_string_entries(raw["license"], f"{label}.license")
        build_entries = _require_string_entries(raw["build"], f"{label}.build")
        patch_entries = _require_string_entries(raw["patches"], f"{label}.patches")

        for item, seen, duplicate_label in (
            (source_id, seen_ids, "id"),
            (archive.casefold(), seen_archives, "archive"),
            (source_url, seen_urls, "source_url"),
        ):
            if item in seen:
                raise SourceBundleError(f"duplicate source {duplicate_label}: {item}")
            seen.add(item)
        sources.append({
            "archive": archive,
            "build": build_entries,
            "id": source_id,
            "license": license_entries,
            "patches": patch_entries,
            "sha256": sha256,
            "source_url": source_url,
            "version": version,
        })

    return {
        "provenance_status": "complete",
        "schema": LOCK_SCHEMA,
        "sources": sorted(sources, key=lambda item: item["id"].encode("utf-8")),
    }


def load_lock(path: Path) -> dict:
    value, _ = _read_json(path)
    return validate_lock(value)


def _sha256_stream(handle: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _sha256_and_git_blob(
    handle: BinaryIO, expected_size: int, object_format: str
) -> tuple[str, int, str]:
    sha256 = hashlib.sha256()
    git_digest = hashlib.new(object_format)
    git_digest.update(f"blob {expected_size}\0".encode("ascii"))
    size = 0
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        sha256.update(chunk)
        git_digest.update(chunk)
        size += len(chunk)
    return sha256.hexdigest(), size, git_digest.hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    try:
        with path.open("rb") as handle:
            return _sha256_stream(handle)
    except OSError as exc:
        raise SourceBundleError(f"cannot read source archive {path}: {exc}") from exc


def _git(repository: Path, arguments: list[str]) -> bytes:
    environment = os.environ.copy()
    environment.update({
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode("utf-8", "replace").strip()
        raise SourceBundleError(f"local git command failed: {detail or exc}") from exc
    return result.stdout


def _git_object_digest(object_type: str, data: bytes, object_format: str) -> str:
    if object_format not in GIT_OBJECT_FORMATS:
        raise SourceBundleError(f"unsupported Git object format: {object_format}")
    digest = hashlib.new(object_format)
    digest.update(f"{object_type} {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _repository_object_format(repository: Path, commit: str) -> str:
    try:
        object_format = _git(
            repository, ["rev-parse", "--show-object-format"]
        ).decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SourceBundleError("git returned a non-ASCII object format") from exc
    expected_length = GIT_OBJECT_FORMATS.get(object_format)
    if expected_length is None or len(commit) != expected_length:
        raise SourceBundleError("repository commit and Git object format differ")
    return object_format


def _commit_tree(commit_object: bytes, object_format: str) -> str:
    if not commit_object or len(commit_object) > MAX_COMMIT_OBJECT_BYTES:
        raise SourceBundleError("Git commit object has an invalid size")
    first_line = commit_object.split(b"\n", 1)[0]
    prefix = b"tree "
    if not first_line.startswith(prefix):
        raise SourceBundleError("Git commit object has no root tree header")
    try:
        tree = first_line.removeprefix(prefix).decode("ascii")
    except UnicodeDecodeError as exc:
        raise SourceBundleError("Git commit tree identifier is not ASCII") from exc
    expected_length = GIT_OBJECT_FORMATS[object_format]
    if not re.fullmatch(rf"[0-9a-f]{{{expected_length}}}", tree):
        raise SourceBundleError("Git commit tree identifier is invalid")
    return tree


def _resolve_commit(repository: Path, commit: str) -> str:
    if not COMMIT_PATTERN.fullmatch(commit):
        raise SourceBundleError("repository commit must be an explicit full 40- or 64-character hex commit")
    resolved = _git(repository, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
    try:
        value = resolved.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SourceBundleError("git returned a non-ASCII commit identifier") from exc
    if value != commit:
        raise SourceBundleError("repository commit did not resolve to the exact supplied identifier")
    return value


def _safe_repository_path(raw: bytes) -> str:
    try:
        path = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceBundleError("repository contains a non-UTF-8 path") from exc
    return _validate_member_path(path, "repository path")


def _safe_symlink_target(path: str, target_bytes: bytes) -> str:
    try:
        target = target_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceBundleError(f"repository symlink target is not UTF-8: {path}") from exc
    if (
        not target
        or target.startswith("/")
        or "\\" in target
        or re.match(r"^[A-Za-z]:", target) is not None
        or any(ord(character) < 32 or ord(character) == 127 for character in target)
    ):
        raise SourceBundleError(f"repository symlink target is unsafe: {path}")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    if resolved == ".." or resolved.startswith("../"):
        raise SourceBundleError(f"repository symlink escapes the repository: {path}")
    return target


@dataclass(frozen=True)
class BundleEntry:
    path: str
    entry_type: str
    mode: int
    size: int
    sha256: str
    opener: Callable[[], BinaryIO] | None = None
    link_target: str | None = None
    git_oid: str | None = None

    def manifest_value(self) -> dict:
        value = {
            "mode": f"{self.mode:04o}",
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "type": self.entry_type,
        }
        if self.entry_type == "symlink":
            value["link_target"] = self.link_target
        return value


def _bytes_entry(path: str, data: bytes, mode: int = 0o644) -> BundleEntry:
    return BundleEntry(
        path=path,
        entry_type="file",
        mode=mode,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        opener=lambda data=data: io.BytesIO(data),
    )


def _repository_entries(
    repository: Path, commit: str, object_format: str
) -> list[BundleEntry]:
    records = _git(repository, ["ls-tree", "-rz", "--full-tree", commit]).split(b"\0")
    entries = []
    seen_paths: set[str] = set()
    for record in records:
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_bytes, object_type, object_id = metadata.split(b" ", 2)
            mode = mode_bytes.decode("ascii")
            object_kind = object_type.decode("ascii")
            oid = object_id.decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceBundleError("git returned an invalid tree record") from exc
        path = _safe_repository_path(raw_path)
        if path in seen_paths:
            raise SourceBundleError(f"repository contains a duplicate path: {path}")
        seen_paths.add(path)
        if object_kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise SourceBundleError(
                f"repository entry cannot be represented completely: {mode} {object_kind} {path}"
            )
        data = _git(repository, ["cat-file", "blob", oid])
        actual_oid = _git_object_digest("blob", data, object_format)
        if actual_oid != oid:
            raise SourceBundleError(
                f"repository blob content does not match its object ID: {path}"
            )
        member_path = f"{REPOSITORY_PREFIX}/{path}"
        if mode == "120000":
            target = _safe_symlink_target(path, data)
            entries.append(BundleEntry(
                path=member_path,
                entry_type="symlink",
                mode=0o777,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                link_target=target,
                git_oid=actual_oid,
            ))
        else:
            entry = _bytes_entry(
                member_path,
                data,
                0o755 if mode == "100755" else 0o644,
            )
            entries.append(replace(entry, git_oid=actual_oid))
    if not entries:
        raise SourceBundleError("repository commit contains no source files")
    return entries


def _git_tree_digest(
    records: Iterable[tuple[str, str, str]], object_format: str
) -> str:
    root: dict[str, object] = {}
    for path, mode, oid in records:
        path = _validate_member_path(path, "repository tree path")
        if mode not in {"100644", "100755", "120000"}:
            raise SourceBundleError(f"repository tree mode is invalid: {path}")
        expected_length = GIT_OBJECT_FORMATS.get(object_format)
        if expected_length is None or not re.fullmatch(
            rf"[0-9a-f]{{{expected_length}}}", oid
        ):
            raise SourceBundleError(f"repository blob object ID is invalid: {path}")
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            existing = node.get(part)
            if existing is None:
                child: dict[str, object] = {}
                node[part] = child
                node = child
            elif isinstance(existing, dict):
                node = existing
            else:
                raise SourceBundleError(
                    f"repository path conflicts with a file: {path}"
                )
        leaf = parts[-1]
        if leaf in node:
            raise SourceBundleError(f"duplicate repository tree path: {path}")
        node[leaf] = (mode, oid)

    if not root:
        raise SourceBundleError("repository tree contains no source files")

    def digest_tree(node: dict[str, object]) -> str:
        encoded_entries: list[tuple[bytes, bytes]] = []
        for name, value in node.items():
            name_bytes = name.encode("utf-8")
            if isinstance(value, dict):
                mode = "40000"
                oid = digest_tree(value)
                sort_key = name_bytes + b"/"
            else:
                mode, oid = value
                sort_key = name_bytes + b"\0"
            record = mode.encode("ascii") + b" " + name_bytes + b"\0"
            record += bytes.fromhex(oid)
            encoded_entries.append((sort_key, record))
        body = b"".join(
            record for _, record in sorted(encoded_entries, key=lambda item: item[0])
        )
        return _git_object_digest("tree", body, object_format)

    return digest_tree(root)


def _repository_manifest(
    repository: Path,
    commit: str,
    object_format: str,
    entries: list[BundleEntry],
) -> dict:
    commit_object = _git(repository, ["cat-file", "commit", commit])
    if _git_object_digest("commit", commit_object, object_format) != commit:
        raise SourceBundleError("repository commit content does not match its object ID")
    commit_tree = _commit_tree(commit_object, object_format)
    records = []
    for entry in entries:
        if not entry.path.startswith(f"{REPOSITORY_PREFIX}/") or not entry.git_oid:
            raise SourceBundleError("repository entry lacks Git provenance")
        relative = entry.path.removeprefix(f"{REPOSITORY_PREFIX}/")
        mode = (
            "120000" if entry.entry_type == "symlink"
            else "100755" if entry.mode == 0o755
            else "100644"
        )
        records.append((relative, mode, entry.git_oid))
    reconstructed_tree = _git_tree_digest(records, object_format)
    if reconstructed_tree != commit_tree:
        raise SourceBundleError(
            "repository source files do not reconstruct the claimed commit tree"
        )
    return {
        "commit": commit,
        "commit_object": base64.b64encode(commit_object).decode("ascii"),
        "object_format": object_format,
        "path": f"{REPOSITORY_PREFIX}/",
        "tree": commit_tree,
    }


def _sort_entries(entries: Iterable[BundleEntry]) -> list[BundleEntry]:
    ordered = sorted(entries, key=lambda item: item.path.encode("utf-8"))
    paths = [entry.path for entry in ordered]
    if len(paths) != len(set(paths)):
        raise SourceBundleError("bundle contains duplicate member paths")
    return ordered


def _write_tar(path: Path, entries: Iterable[BundleEntry]) -> None:
    try:
        with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
            for entry in _sort_entries(entries):
                info = tarfile.TarInfo(entry.path)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                info.mode = entry.mode
                if entry.entry_type == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = entry.link_target or ""
                    info.size = 0
                    archive.addfile(info)
                else:
                    if entry.opener is None:
                        raise SourceBundleError(f"bundle entry has no content source: {entry.path}")
                    info.type = tarfile.REGTYPE
                    info.size = entry.size
                    with entry.opener() as handle:
                        archive.addfile(info, handle)
    except (OSError, tarfile.TarError, ValueError) as exc:
        if isinstance(exc, SourceBundleError):
            raise
        raise SourceBundleError(f"cannot write deterministic tar archive: {exc}") from exc


def _manifest_sources(lock: dict) -> list[dict]:
    return [
        {
            "archive": f"{UPSTREAM_PREFIX}/{source['archive']}",
            "id": source["id"],
            "sha256": source["sha256"],
            "source_url": source["source_url"],
            "version": source["version"],
        }
        for source in lock["sources"]
    ]


def _build_manifest(
    lock: dict,
    lock_bytes: bytes,
    repository: dict,
    entries: list[BundleEntry],
) -> dict:
    return {
        "archive_format": "tar-ustar",
        "entries": [entry.manifest_value() for entry in _sort_entries(entries)],
        "lock": {"path": LOCK_MEMBER, "sha256": hashlib.sha256(lock_bytes).hexdigest()},
        "normalization": NORMALIZATION,
        "repository": repository,
        "root": f"{BUNDLE_ROOT}/",
        "schema": MANIFEST_SCHEMA,
        "sources": _manifest_sources(lock),
    }


def _temporary_output(parent: Path, suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix=".autoeditor-source-", suffix=suffix, dir=parent, delete=False
    )
    path = Path(handle.name)
    handle.close()
    return path


def build_bundle(
    *,
    lock_path: Path,
    source_cache: Path,
    repository: Path,
    repository_commit: str,
    output_tar: Path,
    output_manifest: Path,
) -> dict:
    """Build a deterministic bundle from local, hash-locked inputs only."""
    if output_tar.resolve() == output_manifest.resolve():
        raise SourceBundleError("tar and manifest outputs must be different paths")
    if not source_cache.is_dir():
        raise SourceBundleError("an existing explicit source cache directory is required")
    if not repository.is_dir():
        raise SourceBundleError("an existing local git repository directory is required")
    lock = load_lock(lock_path)
    commit = _resolve_commit(repository, repository_commit)
    object_format = _repository_object_format(repository, commit)
    lock_bytes = _canonical_json(lock)
    entries: list[BundleEntry] = [_bytes_entry(LOCK_MEMBER, lock_bytes)]

    for source in lock["sources"]:
        archive_path = source_cache / source["archive"]
        if archive_path.is_symlink() or not archive_path.is_file():
            raise SourceBundleError(f"required source archive is missing from cache: {archive_path}")
        actual_sha256, size = _sha256_file(archive_path)
        if actual_sha256 != source["sha256"]:
            raise SourceBundleError(
                f"source archive hash mismatch for {source['id']}: "
                f"expected {source['sha256']}, got {actual_sha256}"
            )
        entries.append(BundleEntry(
            path=f"{UPSTREAM_PREFIX}/{source['archive']}",
            entry_type="file",
            mode=0o644,
            size=size,
            sha256=actual_sha256,
            opener=lambda archive_path=archive_path: archive_path.open("rb"),
        ))

    repository_entries = _repository_entries(repository, commit, object_format)
    repository_receipt = _repository_manifest(
        repository, commit, object_format, repository_entries
    )
    entries.extend(repository_entries)
    entries = _sort_entries(entries)
    manifest = _build_manifest(lock, lock_bytes, repository_receipt, entries)
    manifest_bytes = _canonical_json(manifest)
    tar_entries = entries + [_bytes_entry(MANIFEST_MEMBER, manifest_bytes)]

    output_tar.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary_tar = _temporary_output(output_tar.parent, ".tar")
    temporary_manifest = _temporary_output(output_manifest.parent, ".json")
    try:
        _write_tar(temporary_tar, tar_entries)
        temporary_manifest.write_bytes(manifest_bytes)
        verify_bundle(temporary_tar, temporary_manifest)
        os.replace(temporary_tar, output_tar)
        os.replace(temporary_manifest, output_manifest)
    except Exception:
        temporary_tar.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        raise
    return manifest


def _validate_manifest(value: dict, raw: bytes) -> dict:
    _require_exact_fields(value, MANIFEST_FIELDS, "bundle manifest")
    if raw != _canonical_json(value):
        raise SourceBundleError("bundle manifest is not canonical JSON")
    if value["schema"] != MANIFEST_SCHEMA:
        raise SourceBundleError(f"bundle manifest schema must be {MANIFEST_SCHEMA}")
    if value["archive_format"] != "tar-ustar" or value["root"] != f"{BUNDLE_ROOT}/":
        raise SourceBundleError("bundle manifest archive contract is unsupported")
    if value["normalization"] != NORMALIZATION:
        raise SourceBundleError("bundle manifest normalization contract differs")

    lock = value["lock"]
    repository = value["repository"]
    if not isinstance(lock, dict):
        raise SourceBundleError("bundle manifest lock must be an object")
    if not isinstance(repository, dict):
        raise SourceBundleError("bundle manifest repository must be an object")
    _require_exact_fields(lock, {"path", "sha256"}, "bundle manifest lock")
    _require_exact_fields(repository, REPOSITORY_FIELDS, "bundle manifest repository")
    if lock["path"] != LOCK_MEMBER or not SHA256_PATTERN.fullmatch(str(lock["sha256"])):
        raise SourceBundleError("bundle manifest lock receipt is invalid")
    commit = str(repository["commit"])
    object_format = repository["object_format"]
    expected_length = GIT_OBJECT_FORMATS.get(object_format)
    tree = str(repository["tree"])
    if (
        repository["path"] != f"{REPOSITORY_PREFIX}/"
        or expected_length is None
        or not re.fullmatch(rf"[0-9a-f]{{{expected_length}}}", commit)
        or not re.fullmatch(rf"[0-9a-f]{{{expected_length}}}", tree)
    ):
        raise SourceBundleError("bundle manifest repository receipt is invalid")
    commit_object_text = _require_string(
        repository["commit_object"], "bundle manifest repository.commit_object"
    )
    try:
        commit_object = base64.b64decode(commit_object_text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SourceBundleError("bundle manifest commit object is not valid base64") from exc
    if _git_object_digest("commit", commit_object, object_format) != commit:
        raise SourceBundleError("bundle manifest commit object hash is invalid")
    if _commit_tree(commit_object, object_format) != tree:
        raise SourceBundleError("bundle manifest commit object names a different tree")

    sources = value["sources"]
    if not isinstance(sources, list) or not sources:
        raise SourceBundleError("bundle manifest sources must have entries")
    source_ids: set[str] = set()
    source_archives: set[str] = set()
    for index, source in enumerate(sources):
        label = f"bundle manifest source[{index}]"
        if not isinstance(source, dict):
            raise SourceBundleError(f"{label} must be an object")
        _require_exact_fields(source, MANIFEST_SOURCE_FIELDS, label)
        source_id = _require_string(source["id"], f"{label}.id")
        archive = _validate_member_path(source["archive"], f"{label}.archive")
        if not archive.startswith(f"{UPSTREAM_PREFIX}/"):
            raise SourceBundleError(f"{label}.archive is outside the upstream prefix")
        if source_id in source_ids or archive in source_archives:
            raise SourceBundleError("bundle manifest contains duplicate sources")
        source_ids.add(source_id)
        source_archives.add(archive)
        if not IDENTIFIER_PATTERN.fullmatch(source_id):
            raise SourceBundleError(f"{label}.id has invalid characters")
        _validate_version(source["version"], f"{label}.version")
        _validate_https_url(source["source_url"], f"{label}.source_url")
        if not SHA256_PATTERN.fullmatch(str(source["sha256"])):
            raise SourceBundleError(f"{label}.sha256 is invalid")
    if sources != sorted(sources, key=lambda item: item["id"].encode("utf-8")):
        raise SourceBundleError("bundle manifest sources are not deterministically ordered")

    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise SourceBundleError("bundle manifest entries must have entries")
    entry_paths: set[str] = set()
    entries = []
    for index, entry in enumerate(raw_entries):
        label = f"bundle manifest entry[{index}]"
        if not isinstance(entry, dict):
            raise SourceBundleError(f"{label} must be an object")
        entry_type = entry.get("type")
        _require_exact_fields(
            entry,
            SYMLINK_ENTRY_FIELDS if entry_type == "symlink" else ENTRY_FIELDS,
            label,
        )
        if entry_type not in {"file", "symlink"}:
            raise SourceBundleError(f"{label}.type is invalid")
        path = _validate_member_path(entry["path"], f"{label}.path")
        if not path.startswith(f"{BUNDLE_ROOT}/") or path == MANIFEST_MEMBER:
            raise SourceBundleError(f"{label}.path is outside the bundle contract")
        if path != LOCK_MEMBER and not (
            path.startswith(f"{UPSTREAM_PREFIX}/")
            or path.startswith(f"{REPOSITORY_PREFIX}/")
        ):
            raise SourceBundleError(f"{label}.path is outside the known bundle sections")
        if path in entry_paths:
            raise SourceBundleError(f"duplicate bundle manifest entry: {path}")
        entry_paths.add(path)
        expected_mode = "0777" if entry_type == "symlink" else None
        mode = _require_string(entry["mode"], f"{label}.mode")
        if expected_mode is not None and mode != expected_mode:
            raise SourceBundleError(f"{label}.mode is invalid")
        if entry_type == "file" and mode not in {"0644", "0755"}:
            raise SourceBundleError(f"{label}.mode is invalid")
        if isinstance(entry["size"], bool) or not isinstance(entry["size"], int) or entry["size"] < 0:
            raise SourceBundleError(f"{label}.size is invalid")
        if not SHA256_PATTERN.fullmatch(str(entry["sha256"])):
            raise SourceBundleError(f"{label}.sha256 is invalid")
        if entry_type == "symlink":
            target = _require_string(entry["link_target"], f"{label}.link_target")
            if not path.startswith(f"{REPOSITORY_PREFIX}/"):
                raise SourceBundleError(f"{label} symlink is outside repository source")
            repository_path = path.removeprefix(f"{REPOSITORY_PREFIX}/")
            _safe_symlink_target(repository_path, target.encode("utf-8"))
            target_bytes = target.encode("utf-8")
            if len(target_bytes) != entry["size"] or hashlib.sha256(target_bytes).hexdigest() != entry["sha256"]:
                raise SourceBundleError(f"{label} symlink receipt is invalid")
        entries.append(entry)
    if raw_entries != sorted(raw_entries, key=lambda item: item["path"].encode("utf-8")):
        raise SourceBundleError("bundle manifest entries are not deterministically ordered")
    if LOCK_MEMBER not in entry_paths:
        raise SourceBundleError("bundle manifest does not include its source lock")
    by_path = {entry["path"]: entry for entry in entries}
    if by_path[LOCK_MEMBER]["type"] != "file" or by_path[LOCK_MEMBER]["mode"] != "0644":
        raise SourceBundleError("bundle source lock metadata is invalid")
    if not any(path.startswith(f"{REPOSITORY_PREFIX}/") for path in entry_paths):
        raise SourceBundleError("bundle manifest does not include repository source")
    if source_archives != {path for path in entry_paths if path.startswith(f"{UPSTREAM_PREFIX}/")}:
        raise SourceBundleError("bundle manifest upstream source set differs from its entries")
    if any(
        by_path[path]["type"] != "file" or by_path[path]["mode"] != "0644"
        for path in source_archives
    ):
        raise SourceBundleError("bundle upstream source metadata is invalid")
    for source in sources:
        if by_path[source["archive"]]["sha256"] != source["sha256"]:
            raise SourceBundleError(
                f"bundle upstream source hash differs from its lock: {source['id']}"
            )
    return value


def _verify_tar_padding(path: Path, members: list[tarfile.TarInfo]) -> None:
    content_end = 0
    for member in members:
        data_size = member.size if member.isreg() else 0
        content_end = max(content_end, member.offset_data + ((data_size + 511) // 512) * 512)
    expected_minimum = content_end + 1024
    expected_size = ((expected_minimum + tarfile.RECORDSIZE - 1) // tarfile.RECORDSIZE) * tarfile.RECORDSIZE
    if path.stat().st_size != expected_size:
        raise SourceBundleError("tar archive has non-deterministic length or trailing data")
    with path.open("rb") as handle:
        handle.seek(content_end)
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if any(chunk):
                raise SourceBundleError("tar archive padding is not normalized")


def verify_bundle(archive_path: Path, manifest_path: Path) -> dict:
    """Verify every bundle member and the embedded JSON manifest."""
    manifest, manifest_bytes = _read_json(manifest_path)
    manifest = _validate_manifest(manifest, manifest_bytes)
    expected_entries = {entry["path"]: entry for entry in manifest["entries"]}
    expected_paths = set(expected_entries) | {MANIFEST_MEMBER}
    object_format = manifest["repository"]["object_format"]
    repository_records: list[tuple[str, str, str]] = []
    try:
        with tarfile.open(archive_path, "r:") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)):
                raise SourceBundleError("tar archive contains duplicate member paths")
            if names != sorted(names, key=lambda item: item.encode("utf-8")):
                raise SourceBundleError("tar archive members are not deterministically ordered")
            if set(names) != expected_paths:
                raise SourceBundleError("tar archive member set differs from the manifest")
            for member in members:
                if (
                    member.uid != 0
                    or member.gid != 0
                    or member.uname != ""
                    or member.gname != ""
                    or member.mtime != 0
                    or member.pax_headers
                ):
                    raise SourceBundleError(f"tar member metadata is not normalized: {member.name}")
                if member.name == MANIFEST_MEMBER:
                    if not member.isreg() or member.mode != 0o644:
                        raise SourceBundleError("embedded manifest metadata is invalid")
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise SourceBundleError("embedded manifest cannot be read")
                    embedded = handle.read()
                    embedded_sha256 = hashlib.sha256(embedded).hexdigest()
                    sidecar_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
                    if embedded_sha256 != sidecar_sha256:
                        raise SourceBundleError("embedded manifest hash mismatch")
                    if embedded != manifest_bytes:
                        raise SourceBundleError("embedded manifest differs from the sidecar manifest")
                    continue

                expected = expected_entries[member.name]
                if expected["type"] == "symlink":
                    if not member.issym() or member.mode != 0o777 or member.linkname != expected["link_target"]:
                        raise SourceBundleError(f"symlink metadata mismatch: {member.name}")
                    actual_bytes = member.linkname.encode("utf-8")
                    actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()
                    actual_size = len(actual_bytes)
                    git_oid = _git_object_digest(
                        "blob", actual_bytes, object_format
                    )
                else:
                    if not member.isreg() or member.mode != int(expected["mode"], 8):
                        raise SourceBundleError(f"file metadata mismatch: {member.name}")
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise SourceBundleError(f"tar member cannot be read: {member.name}")
                    if member.name.startswith(f"{REPOSITORY_PREFIX}/"):
                        actual_sha256, actual_size, git_oid = _sha256_and_git_blob(
                            handle, member.size, object_format
                        )
                    else:
                        actual_sha256, actual_size = _sha256_stream(handle)
                        git_oid = None
                if actual_size != expected["size"] or actual_sha256 != expected["sha256"]:
                    raise SourceBundleError(f"tar member hash mismatch: {member.name}")
                if member.name.startswith(f"{REPOSITORY_PREFIX}/"):
                    relative = member.name.removeprefix(f"{REPOSITORY_PREFIX}/")
                    mode = (
                        "120000" if expected["type"] == "symlink"
                        else "100755" if expected["mode"] == "0755"
                        else "100644"
                    )
                    if git_oid is None:
                        raise SourceBundleError(
                            f"repository member has no Git object receipt: {member.name}"
                        )
                    repository_records.append((relative, mode, git_oid))
            _verify_tar_padding(archive_path, members)
    except (OSError, tarfile.TarError) as exc:
        raise SourceBundleError(f"cannot verify tar archive: {exc}") from exc

    lock_member = expected_entries[LOCK_MEMBER]
    if lock_member["sha256"] != manifest["lock"]["sha256"]:
        raise SourceBundleError("source lock hash differs between manifest receipts")
    try:
        with tarfile.open(archive_path, "r:") as archive:
            handle = archive.extractfile(LOCK_MEMBER)
            if handle is None:
                raise SourceBundleError("embedded source lock cannot be read")
            lock_bytes = handle.read()
    except (OSError, tarfile.TarError) as exc:
        raise SourceBundleError(f"cannot read embedded source lock: {exc}") from exc
    if hashlib.sha256(lock_bytes).hexdigest() != manifest["lock"]["sha256"]:
        raise SourceBundleError("embedded source lock hash mismatch")
    lock = validate_lock(_parse_json_bytes(lock_bytes, "embedded source lock"))
    if lock_bytes != _canonical_json(lock):
        raise SourceBundleError("embedded source lock is not canonical JSON")
    if manifest["sources"] != _manifest_sources(lock):
        raise SourceBundleError("bundle manifest sources differ from the embedded source lock")
    if _git_tree_digest(repository_records, object_format) != manifest["repository"]["tree"]:
        raise SourceBundleError(
            "bundle repository files do not reconstruct the claimed Git tree"
        )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate a source lock")
    validate.add_argument("--lock", type=Path, required=True)

    build = commands.add_parser("build", help="build from an explicit offline source cache")
    build.add_argument("--lock", type=Path, required=True)
    build.add_argument("--source-cache", type=Path, required=True)
    build.add_argument("--repository", type=Path, required=True)
    build.add_argument("--repository-commit", required=True)
    build.add_argument("--output-tar", type=Path, required=True)
    build.add_argument("--output-manifest", type=Path, required=True)

    verify = commands.add_parser("verify", help="verify a bundle and sidecar manifest")
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "validate":
            lock = load_lock(args.lock)
            print(f"source lock verified: {len(lock['sources'])} archives")
        elif args.command == "build":
            manifest = build_bundle(
                lock_path=args.lock,
                source_cache=args.source_cache,
                repository=args.repository,
                repository_commit=args.repository_commit,
                output_tar=args.output_tar,
                output_manifest=args.output_manifest,
            )
            print(f"source bundle built: {len(manifest['entries'])} entries")
        else:
            manifest = verify_bundle(args.archive, args.manifest)
            print(f"source bundle verified: {len(manifest['entries'])} entries")
    except SourceBundleError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
