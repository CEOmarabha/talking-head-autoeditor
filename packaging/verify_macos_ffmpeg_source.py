#!/usr/bin/env python3
"""Verify the source and Homebrew recipe closure for macOS FFmpeg bottles."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit


LOCK_SCHEMA = "autoeditor-macos-homebrew-ffmpeg-sources/v1"
BUNDLE_LOCK_SCHEMA = "autoeditor-native-media-sources/v1"
EVIDENCE_SCHEMA = "autoeditor-macos-homebrew-ffmpeg-source-evidence/v1"
EXPECTED_LOCK_SHA256 = (
    "eac1198ce317c623116a3ca5872b6e08813a68928c658a19889e4df182bb2ffb"
)
EXPECTED_FORMULAE = (
    "dav1d",
    "ffmpeg",
    "lame",
    "libvmaf",
    "libvpx",
    "mpg123",
    "openssl@3",
    "opus",
    "svt-av1",
    "x264",
    "x265",
)
EXPECTED_DEPENDENCY_EXCEPTIONS = (
    "ca-certificates",
    "cmake",
    "gcc",
    "meson",
    "nasm",
    "ninja",
    "pkgconf",
    "sdl2-compat",
    "sdl3",
    "vim",
    "yasm",
)
EXPECTED_SYSTEM_LIBRARIES = (
    "apple-frameworks",
    "bzip2",
    "libxml2",
    "macos-runtime",
    "ncurses",
)
EXPECTED_LICENSES = {
    "dav1d": "BSD-2-Clause",
    "ffmpeg": "GPL-3.0-or-later",
    "lame": "LGPL-2.0-or-later",
    "libvmaf": "BSD-2-Clause-Patent",
    "libvpx": "BSD-3-Clause",
    "mpg123": "LGPL-2.1-only",
    "openssl@3": "Apache-2.0",
    "opus": "BSD-3-Clause",
    "svt-av1": "BSD-3-Clause",
    "x264": "GPL-2.0-or-later",
    "x265": "GPL-2.0-or-later",
}
EXPECTED_OPENSSL_PATCHES = (
    "9061e9381306a053908177aca8509c262015cdf3",
    "2e2438b494e7f661be5212e4732f7fab86bf6303",
    "ea598f5dd23f1d64d8952e20fcf95d9f3a21d654",
    "cffb97915813aeeef58ee9a0d33c05d3d45e1fe6",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._+-]*\Z")
MOVING_REF_RE = re.compile(
    r"(?:^|[/?#&=._-])(?:latest|nightly|snapshot|main|master|head|trunk|"
    r"develop|development|branches?)(?:$|[/?#&=._-])",
    re.IGNORECASE,
)
ROOT_FIELDS = {
    "dependency_exceptions",
    "formulae",
    "inventories",
    "provenance_status",
    "schema",
    "system_libraries",
}
FORMULA_FIELDS = {
    "bottles",
    "formula",
    "license",
    "name",
    "package_version",
    "patches",
    "source",
    "source_version_commit",
}
BOTTLE_FIELDS = {"bottle_rebuild", "bottle_sha256", "bottle_tag"}
FORMULA_SOURCE_FIELDS = {
    "archive",
    "bottle_commit",
    "bytes",
    "git_blob_sha1",
    "path",
    "sha256",
    "source_url",
}
UPSTREAM_SOURCE_FIELDS = {
    "archive",
    "bytes",
    "license_file",
    "sha256",
    "source_url",
    "version",
}
PATCH_FIELDS = {"archive", "bytes", "commit", "sha256", "source_url"}
INVENTORY_FIELDS = {"arch", "bytes", "path", "sha256"}
EXCEPTION_FIELDS = {"classification", "name", "reason"}
SYSTEM_LIBRARY_FIELDS = {
    "id",
    "load_paths",
    "provided_by",
    "reason",
    "source_required",
}


class MacSourceError(ValueError):
    """The macOS source provenance contract failed closed."""


@dataclass(frozen=True)
class BottleRecord:
    formula: str
    version: str
    bottle_tag: str
    bottle_rebuild: int
    bottle_sha256: str


@dataclass(frozen=True)
class CacheItem:
    archive: str
    bytes: int
    item_id: str
    kind: str
    license: str
    sha256: str
    source_url: str
    version: str


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise MacSourceError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _parse_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MacSourceError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise MacSourceError(f"{label} root must be an object")
    return value


def _read_regular(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MacSourceError(f"cannot read {label}: {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MacSourceError(f"{label} must be a regular file, not a symlink: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MacSourceError(f"cannot read {label}: {path}: {exc}") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise MacSourceError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest(), size


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise MacSourceError(f"{label} is missing fields: {', '.join(missing)}")
    if extra:
        raise MacSourceError(f"{label} has unknown fields: {', '.join(extra)}")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise MacSourceError(f"{label} must be a non-empty trimmed string")
    return value


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MacSourceError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MacSourceError(f"{label} must be a non-negative integer")
    return value


def _safe_archive(value: object, label: str) -> str:
    name = _string(value, label)
    if (
        "/" in name
        or "\\" in name
        or name in {".", ".."}
        or not SAFE_NAME_RE.fullmatch(name)
        or MOVING_REF_RE.search(name)
    ):
        raise MacSourceError(f"{label} must be an immutable portable file name")
    return name


def _https_url(value: object, label: str, required_revision: str | None = None) -> str:
    url = _string(value, label)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise MacSourceError(f"{label} must be an HTTPS URL without credentials or fragments")
    decoded = unquote(parsed.path)
    if MOVING_REF_RE.search(decoded + ("?" + parsed.query if parsed.query else "")):
        raise MacSourceError(f"{label} may not use a moving reference")
    if required_revision is not None and required_revision not in decoded:
        raise MacSourceError(f"{label} does not contain its exact revision")
    return url


def _source_id(formula: str) -> str:
    return "openssl-3" if formula == "openssl@3" else formula


def _validate_lock_value(value: dict[str, Any]) -> dict[str, Any]:
    _exact_fields(value, ROOT_FIELDS, "source lock")
    if value["schema"] != LOCK_SCHEMA:
        raise MacSourceError(f"source lock schema must be {LOCK_SCHEMA}")
    if value["provenance_status"] != "complete":
        raise MacSourceError("source lock provenance_status must be complete")

    inventories = value["inventories"]
    if not isinstance(inventories, dict) or set(inventories) != {"arm64", "x64"}:
        raise MacSourceError("source lock inventories must be exactly arm64 and x64")
    for arch, record in inventories.items():
        if not isinstance(record, dict):
            raise MacSourceError(f"inventory {arch} must be an object")
        _exact_fields(record, INVENTORY_FIELDS, f"inventory {arch}")
        if record["arch"] != arch:
            raise MacSourceError(f"inventory {arch} arch drifted")
        if record["path"] != f"packaging/macos-ffmpeg-formulae-{arch}.txt":
            raise MacSourceError(f"inventory {arch} path drifted")
        _positive_int(record["bytes"], f"inventory {arch}.bytes")
        if not SHA256_RE.fullmatch(str(record["sha256"])):
            raise MacSourceError(f"inventory {arch}.sha256 is invalid")

    formulae = value["formulae"]
    if not isinstance(formulae, list):
        raise MacSourceError("source lock formulae must be an array")
    names = [item.get("name") if isinstance(item, dict) else None for item in formulae]
    if tuple(names) != EXPECTED_FORMULAE:
        raise MacSourceError("formulae must be the exact audited ordered closure")
    archives: set[str] = set()
    urls: set[str] = set()
    for index, record in enumerate(formulae):
        label = f"formulae[{index}]"
        if not isinstance(record, dict):
            raise MacSourceError(f"{label} must be an object")
        _exact_fields(record, FORMULA_FIELDS, label)
        name = _string(record["name"], f"{label}.name")
        package_version = _string(record["package_version"], f"{label}.package_version")
        if record["license"] != EXPECTED_LICENSES[name]:
            raise MacSourceError(f"{name} license drifted")
        source_version_commit = _string(
            record["source_version_commit"], f"{label}.source_version_commit"
        )
        if not SHA1_RE.fullmatch(source_version_commit):
            raise MacSourceError(f"{name} source_version_commit is invalid")

        bottles = record["bottles"]
        if not isinstance(bottles, dict) or set(bottles) != {"arm64", "x64"}:
            raise MacSourceError(f"{name} bottles must be exactly arm64 and x64")
        for arch, bottle in bottles.items():
            if not isinstance(bottle, dict):
                raise MacSourceError(f"{name} {arch} bottle must be an object")
            _exact_fields(bottle, BOTTLE_FIELDS, f"{name} {arch} bottle")
            _nonnegative_int(bottle["bottle_rebuild"], f"{name} {arch} rebuild")
            if not SHA256_RE.fullmatch(str(bottle["bottle_sha256"])):
                raise MacSourceError(f"{name} {arch} bottle SHA-256 is invalid")
            _string(bottle["bottle_tag"], f"{name} {arch} bottle tag")

        formula = record["formula"]
        if not isinstance(formula, dict):
            raise MacSourceError(f"{name} formula source must be an object")
        _exact_fields(formula, FORMULA_SOURCE_FIELDS, f"{name} formula source")
        bottle_commit = _string(formula["bottle_commit"], f"{name} bottle_commit")
        if not SHA1_RE.fullmatch(bottle_commit):
            raise MacSourceError(f"{name} bottle_commit is invalid")
        expected_path = formula["path"]
        if not isinstance(expected_path, str) or not expected_path.endswith(f"/{name}.rb"):
            raise MacSourceError(f"{name} formula path drifted")
        if not SHA1_RE.fullmatch(str(formula["git_blob_sha1"])):
            raise MacSourceError(f"{name} formula Git blob is invalid")
        formula_archive = _safe_archive(formula["archive"], f"{name} formula archive")
        _positive_int(formula["bytes"], f"{name} formula bytes")
        if not SHA256_RE.fullmatch(str(formula["sha256"])):
            raise MacSourceError(f"{name} formula SHA-256 is invalid")
        formula_url = _https_url(
            formula["source_url"], f"{name} formula URL", bottle_commit
        )
        expected_url = (
            f"https://raw.githubusercontent.com/Homebrew/homebrew-core/"
            f"{bottle_commit}/{expected_path}"
        )
        if formula_url != expected_url:
            raise MacSourceError(f"{name} formula URL is not its exact Homebrew raw path")

        source = record["source"]
        if not isinstance(source, dict):
            raise MacSourceError(f"{name} upstream source must be an object")
        _exact_fields(source, UPSTREAM_SOURCE_FIELDS, f"{name} upstream source")
        source_archive = _safe_archive(source["archive"], f"{name} source archive")
        _positive_int(source["bytes"], f"{name} source bytes")
        if not SHA256_RE.fullmatch(str(source["sha256"])):
            raise MacSourceError(f"{name} source SHA-256 is invalid")
        _https_url(source["source_url"], f"{name} source URL")
        _safe_archive(source["license_file"], f"{name} source license file")
        _string(source["version"], f"{name} source version")
        if name != "ffmpeg" and name != "x264" and source["version"] != package_version:
            raise MacSourceError(f"{name} source and package versions differ")

        patches = record["patches"]
        if not isinstance(patches, list):
            raise MacSourceError(f"{name} patches must be an array")
        patch_commits: list[str] = []
        for patch_index, patch in enumerate(patches):
            patch_label = f"{name} patch[{patch_index}]"
            if not isinstance(patch, dict):
                raise MacSourceError(f"{patch_label} must be an object")
            _exact_fields(patch, PATCH_FIELDS, patch_label)
            commit = _string(patch["commit"], f"{patch_label}.commit")
            if not SHA1_RE.fullmatch(commit):
                raise MacSourceError(f"{patch_label}.commit is invalid")
            patch_commits.append(commit)
            patch_archive = _safe_archive(patch["archive"], f"{patch_label}.archive")
            _positive_int(patch["bytes"], f"{patch_label}.bytes")
            if not SHA256_RE.fullmatch(str(patch["sha256"])):
                raise MacSourceError(f"{patch_label}.sha256 is invalid")
            patch_url = _https_url(patch["source_url"], f"{patch_label}.source_url", commit)
            if not patch_url.startswith("https://github.com/openssl/openssl/commit/"):
                raise MacSourceError(f"{patch_label} URL is outside the pinned OpenSSL history")
            for item in (patch_archive,):
                if item in archives:
                    raise MacSourceError(f"duplicate cache archive: {item}")
                archives.add(item)
            if patch_url in urls:
                raise MacSourceError(f"duplicate cache URL: {patch_url}")
            urls.add(patch_url)
        expected_patch_commits = EXPECTED_OPENSSL_PATCHES if name == "openssl@3" else ()
        if tuple(patch_commits) != expected_patch_commits:
            raise MacSourceError(f"{name} exact patch closure drifted")

        for item in (formula_archive, source_archive):
            if item in archives:
                raise MacSourceError(f"duplicate cache archive: {item}")
            archives.add(item)
        for item in (formula_url, source["source_url"]):
            if item in urls:
                raise MacSourceError(f"duplicate cache URL: {item}")
            urls.add(item)

    mpg123 = formulae[5]
    if (
        mpg123["package_version"] != "1.33.6"
        or mpg123["source_version_commit"]
        != "63a0c10d3a5f115bc28bb858cce57ef4b1eebf20"
        or mpg123["formula"]["bottle_commit"]
        != "b854b7b20bd2a4fced247b67cf803be58aacf71c"
        or mpg123["source"]["sha256"]
        != "929a7c18ba662b8927aed4de229ad9ae8ab2b4806dd0f30b90113eb1b4e2195a"
    ):
        raise MacSourceError("mpg123 must remain on the audited 1.33.6 history")
    if formulae[4]["formula"]["bottle_commit"] != (
        "30e8b07eb9becf25653cf858b95b81a8fa1820fc"
    ):
        raise MacSourceError("libvpx must remain on its Yasm bottle-producing formula")
    if "b35605ace3ddf7c1a5d67a2eb553f034aef41d55" not in formulae[9]["source"]["source_url"]:
        raise MacSourceError("x264 source URL must name the exact r3222 commit")

    exceptions = value["dependency_exceptions"]
    if not isinstance(exceptions, list):
        raise MacSourceError("dependency_exceptions must be an array")
    exception_names: list[str] = []
    for index, item in enumerate(exceptions):
        if not isinstance(item, dict):
            raise MacSourceError(f"dependency_exceptions[{index}] must be an object")
        _exact_fields(item, EXCEPTION_FIELDS, f"dependency_exceptions[{index}]")
        exception_names.append(_string(item["name"], f"dependency exception {index} name"))
        _string(item["classification"], f"dependency exception {index} classification")
        _string(item["reason"], f"dependency exception {index} reason")
    if tuple(exception_names) != EXPECTED_DEPENDENCY_EXCEPTIONS:
        raise MacSourceError("dependency exceptions drifted")

    system_libraries = value["system_libraries"]
    if not isinstance(system_libraries, list):
        raise MacSourceError("system_libraries must be an array")
    library_ids: list[str] = []
    load_paths: set[str] = set()
    for index, item in enumerate(system_libraries):
        if not isinstance(item, dict):
            raise MacSourceError(f"system_libraries[{index}] must be an object")
        _exact_fields(item, SYSTEM_LIBRARY_FIELDS, f"system_libraries[{index}]")
        library_ids.append(_string(item["id"], f"system library {index} id"))
        if item["provided_by"] != "macOS" or item["source_required"] is not False:
            raise MacSourceError("system exception must be supplied by macOS without bundled source")
        _string(item["reason"], f"system library {index} reason")
        paths = item["load_paths"]
        if not isinstance(paths, list) or not paths:
            raise MacSourceError(f"system library {item['id']} must have load paths")
        for path in paths:
            path = _string(path, f"system library {item['id']} load path")
            if not path.startswith(("/System/Library/", "/usr/lib/")):
                raise MacSourceError(f"system exception is outside macOS system roots: {path}")
            if path in load_paths:
                raise MacSourceError(f"duplicate system load path: {path}")
            load_paths.add(path)
    if tuple(library_ids) != EXPECTED_SYSTEM_LIBRARIES:
        raise MacSourceError("system library exceptions drifted")
    return value


def load_lock(path: Path, *, require_pinned_digest: bool = True) -> dict[str, Any]:
    raw = _read_regular(path, "macOS FFmpeg source lock")
    value = _parse_json_bytes(raw, "macOS FFmpeg source lock")
    _validate_lock_value(value)
    if raw != canonical_json(value):
        raise MacSourceError("macOS FFmpeg source lock is not canonical JSON")
    digest = _sha256(raw)
    if require_pinned_digest and digest != EXPECTED_LOCK_SHA256:
        raise MacSourceError(
            f"macOS FFmpeg source lock digest drifted: expected {EXPECTED_LOCK_SHA256}, got {digest}"
        )
    return value


def read_inventory(path: Path) -> dict[str, BottleRecord]:
    raw = _read_regular(path, "formula inventory")
    records: dict[str, BottleRecord] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise MacSourceError(f"formula inventory is not UTF-8: {path}") from exc
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 5:
            raise MacSourceError(f"{path}:{line_number}: expected five fields")
        formula, version, tag, rebuild_text, digest = fields
        if formula in records:
            raise MacSourceError(f"{path}:{line_number}: duplicate formula {formula}")
        try:
            rebuild = int(rebuild_text)
        except ValueError as exc:
            raise MacSourceError(f"{path}:{line_number}: invalid rebuild") from exc
        if rebuild < 0 or not SHA256_RE.fullmatch(digest):
            raise MacSourceError(f"{path}:{line_number}: invalid bottle record")
        records[formula] = BottleRecord(formula, version, tag, rebuild, digest)
    if tuple(records) != EXPECTED_FORMULAE:
        raise MacSourceError(f"{path} is not the exact audited formula closure")
    return records


def verify_inventories(lock: dict[str, Any], repo_root: Path) -> None:
    formulae = {record["name"]: record for record in lock["formulae"]}
    for arch in ("arm64", "x64"):
        contract = lock["inventories"][arch]
        path = repo_root / contract["path"]
        raw = _read_regular(path, f"{arch} formula inventory")
        if len(raw) != contract["bytes"] or _sha256(raw) != contract["sha256"]:
            raise MacSourceError(f"{arch} formula inventory digest or size drifted")
        records = read_inventory(path)
        for name, bottle in records.items():
            formula = formulae[name]
            expected = formula["bottles"][arch]
            if (
                bottle.version != formula["package_version"]
                or bottle.bottle_tag != expected["bottle_tag"]
                or bottle.bottle_rebuild != expected["bottle_rebuild"]
                or bottle.bottle_sha256 != expected["bottle_sha256"]
            ):
                raise MacSourceError(f"{arch} inventory differs from the source lock for {name}")


def cache_items(lock: dict[str, Any]) -> list[CacheItem]:
    items: list[CacheItem] = []
    for record in lock["formulae"]:
        source_id = _source_id(record["name"])
        source = record["source"]
        items.append(CacheItem(
            source["archive"],
            source["bytes"],
            source_id,
            "upstream-source",
            record["license"],
            source["sha256"],
            source["source_url"],
            source["version"],
        ))
        formula = record["formula"]
        items.append(CacheItem(
            formula["archive"],
            formula["bytes"],
            f"homebrew-formula-{source_id}",
            "homebrew-formula",
            record["license"],
            formula["sha256"],
            formula["source_url"],
            formula["bottle_commit"],
        ))
        for patch in record["patches"]:
            items.append(CacheItem(
                patch["archive"],
                patch["bytes"],
                f"openssl-patch-{patch['commit']}",
                "formula-patch",
                record["license"],
                patch["sha256"],
                patch["source_url"],
                patch["commit"],
            ))
    return sorted(items, key=lambda item: item.item_id.encode("utf-8"))


def bundle_lock_value(lock: dict[str, Any], arch: str) -> dict[str, Any]:
    if arch not in {"arm64", "x64"}:
        raise MacSourceError(f"unsupported architecture: {arch}")
    inventory_path = lock["inventories"][arch]["path"]
    formulae = {record["name"]: record for record in lock["formulae"]}
    sources = []
    for item in cache_items(lock):
        patches = ["none"]
        if item.kind == "upstream-source":
            formula_name = "openssl@3" if item.item_id == "openssl-3" else item.item_id
            formula = formulae[formula_name]
            patches = [patch["archive"] for patch in formula["patches"]] or ["none"]
        sources.append({
            "archive": item.archive,
            "build": [
                inventory_path,
                "packaging/verify_macos_ffmpeg_source.py",
            ],
            "id": item.item_id,
            "license": [
                item.license,
                "Homebrew formula definition" if item.kind == "homebrew-formula"
                else "Homebrew-applied patch" if item.kind == "formula-patch"
                else formulae[
                    "openssl@3" if item.item_id == "openssl-3" else item.item_id
                ]["source"]["license_file"],
            ],
            "patches": patches,
            "sha256": item.sha256,
            "source_url": item.source_url,
            "version": item.version,
        })
    return {
        "provenance_status": "complete",
        "schema": BUNDLE_LOCK_SCHEMA,
        "sources": sources,
    }


def _load_source_bundle_module(repo_root: Path):
    script = repo_root / "packaging" / "source_bundle.py"
    spec = importlib.util.spec_from_file_location("autoeditor_source_bundle_macos", script)
    if spec is None or spec.loader is None:
        raise MacSourceError(f"cannot load source bundle module: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as exc:
        raise MacSourceError(f"cannot load source bundle module: {exc}") from exc
    return module


def verify_contracts(lock_path: Path, repo_root: Path) -> dict[str, Any]:
    lock = load_lock(lock_path)
    verify_inventories(lock, repo_root)
    module = _load_source_bundle_module(repo_root)
    for arch in ("arm64", "x64"):
        try:
            derived = module.validate_lock(bundle_lock_value(lock, arch))
        except module.SourceBundleError as exc:
            raise MacSourceError(f"{arch} bundle lock is incompatible: {exc}") from exc
        if canonical_json(derived) != canonical_json(bundle_lock_value(lock, arch)):
            raise MacSourceError(f"{arch} bundle lock is not canonical")
    return lock


def _formula_without_bottle(raw: bytes, name: str) -> tuple[bytes, bytes]:
    lines = raw.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line == b"  bottle do\n"]
    if len(starts) != 1:
        raise MacSourceError(f"{name} formula must contain exactly one canonical bottle block")
    start = starts[0]
    end = None
    for index in range(start + 1, len(lines)):
        if lines[index] == b"  end\n":
            end = index
            break
    if end is None:
        raise MacSourceError(f"{name} formula bottle block is unterminated")
    block = b"".join(lines[start:end + 1])
    tail = end + 1
    if tail < len(lines) and lines[tail] == b"\n":
        tail += 1
    return b"".join(lines[:start] + lines[tail:]), block


def _parse_formula_bytes(raw: bytes, record: dict[str, Any]) -> tuple[bytes, str]:
    name = record["name"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MacSourceError(f"{name} formula is not UTF-8") from exc
    without_bottle, bottle_block_raw = _formula_without_bottle(raw, name)
    bottle_block = bottle_block_raw.decode("utf-8")
    source = record["source"]
    prefix = text.split("  bottle do\n", 1)[0]
    license_match = re.search(r'^  license "([^"]+)"$', prefix, re.MULTILINE)
    if license_match is None or license_match.group(1) != record["license"]:
        raise MacSourceError(f"{name} formula license differs from the source lock")
    if name == "x264":
        expected_revision = "b35605ace3ddf7c1a5d67a2eb553f034aef41d55"
        if (
            'url "https://code.videolan.org/videolan/x264.git",' not in prefix
            or f'revision: "{expected_revision}"' not in prefix
            or f'version "{record["package_version"]}"' not in prefix
        ):
            raise MacSourceError("x264 formula source revision drifted")
        stable_version = record["package_version"]
    else:
        url_match = re.search(r'^  url "([^"]+)"$', prefix, re.MULTILINE)
        sha_match = re.search(r'^  sha256 "([0-9a-f]{64})"$', prefix, re.MULTILINE)
        if url_match is None or url_match.group(1) != source["source_url"]:
            raise MacSourceError(f"{name} formula upstream URL differs from the source lock")
        if sha_match is None or sha_match.group(1) != source["sha256"]:
            raise MacSourceError(f"{name} formula upstream SHA-256 differs from the source lock")
        stable_version = source["version"]
    revision_match = re.search(r"^  revision ([0-9]+)$", prefix, re.MULTILINE)
    revision = int(revision_match.group(1)) if revision_match else 0
    expected_package = f"{stable_version}_{revision}" if revision else stable_version
    if expected_package != record["package_version"]:
        raise MacSourceError(f"{name} formula version/revision differs from the source lock")
    for arch in ("arm64", "x64"):
        bottle = record["bottles"][arch]
        tag = re.escape(bottle["bottle_tag"])
        matches = re.findall(rf"\b{tag}:\s+\"([0-9a-f]{{64}})\"", bottle_block)
        if matches != [bottle["bottle_sha256"]]:
            raise MacSourceError(f"{name} {arch} formula bottle hash drifted")
    rebuilds = re.findall(r"^    rebuild ([0-9]+)$", bottle_block, re.MULTILINE)
    expected_rebuild = record["bottles"]["arm64"]["bottle_rebuild"]
    if record["bottles"]["x64"]["bottle_rebuild"] != expected_rebuild:
        raise MacSourceError(f"{name} bottle rebuild differs across architectures")
    if rebuilds != ([str(expected_rebuild)] if expected_rebuild else []):
        raise MacSourceError(f"{name} formula bottle rebuild drifted")
    patch_matches = re.findall(
        r'  patch do\n    url "([^"]+)"\n    sha256 "([0-9a-f]{64})"\n  end',
        text,
    )
    expected_patches = [
        (patch["source_url"], patch["sha256"]) for patch in record["patches"]
    ]
    if patch_matches != expected_patches:
        raise MacSourceError(f"{name} formula patch closure drifted")
    return without_bottle, stable_version


def _verify_source_license(path: Path, license_file: str, name: str) -> None:
    try:
        with tarfile.open(path, mode="r:*") as archive:
            matches = [
                member for member in archive.getmembers()
                if (
                    member.isfile()
                    and len(PurePosixPath(member.name).parts) == 2
                    and PurePosixPath(member.name).name == license_file
                )
            ]
    except (OSError, tarfile.TarError) as exc:
        raise MacSourceError(f"cannot inspect {name} source archive: {exc}") from exc
    if len(matches) != 1:
        raise MacSourceError(
            f"{name} source archive must contain exactly one {license_file}, found {len(matches)}"
        )


def verify_cache(lock: dict[str, Any], source_cache: Path) -> dict[str, bytes]:
    try:
        metadata = source_cache.lstat()
    except OSError as exc:
        raise MacSourceError(f"source cache is missing: {source_cache}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MacSourceError("source cache must be a real directory, not a symlink")
    items = cache_items(lock)
    expected = {item.archive for item in items}
    try:
        actual = {entry.name for entry in source_cache.iterdir()}
    except OSError as exc:
        raise MacSourceError(f"cannot list source cache: {exc}") from exc
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise MacSourceError("source cache inventory drifted; " + "; ".join(details))
    raw_files: dict[str, bytes] = {}
    formulae_by_archive = {
        record["formula"]["archive"]: record for record in lock["formulae"]
    }
    sources_by_archive = {
        record["source"]["archive"]: record for record in lock["formulae"]
    }
    for item in items:
        path = source_cache / item.archive
        raw = _read_regular(path, f"source cache item {item.archive}")
        if len(raw) != item.bytes or _sha256(raw) != item.sha256:
            raise MacSourceError(f"source cache digest or size mismatch: {item.archive}")
        raw_files[item.archive] = raw
        if item.archive in formulae_by_archive:
            _parse_formula_bytes(raw, formulae_by_archive[item.archive])
        elif item.archive in sources_by_archive:
            record = sources_by_archive[item.archive]
            _verify_source_license(path, record["source"]["license_file"], record["name"])
    return raw_files


def _download_item(item: CacheItem, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise MacSourceError(f"refusing to replace existing cache item: {destination}")
    request = urllib.request.Request(
        item.source_url,
        headers={"User-Agent": "AutoEditor-source-closure/1"},
    )
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{item.archive}.", suffix=".tmp", dir=destination.parent, delete=False
    )
    temporary = Path(handle.name)
    digest = hashlib.sha256()
    size = 0
    try:
        with handle:
            with urllib.request.urlopen(request, timeout=120) as response:
                final_url = response.geturl()
                if urlsplit(final_url).scheme != "https":
                    raise MacSourceError(f"cache fetch redirected away from HTTPS: {item.archive}")
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size != item.bytes or digest.hexdigest() != item.sha256:
            raise MacSourceError(f"downloaded bytes do not match the lock: {item.archive}")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def fetch_cache(lock: dict[str, Any], source_cache: Path) -> None:
    source_cache.mkdir(parents=True, exist_ok=True)
    if source_cache.is_symlink() or not source_cache.is_dir():
        raise MacSourceError("source cache must be a real directory")
    for item in cache_items(lock):
        destination = source_cache / item.archive
        if destination.exists():
            digest, size = _sha256_file(destination)
            if destination.is_symlink() or digest != item.sha256 or size != item.bytes:
                raise MacSourceError(f"existing cache item differs from the lock: {item.archive}")
            continue
        _download_item(item, destination)
    verify_cache(lock, source_cache)


def _find_bottle(bottle_cache: Path, record: dict[str, Any], arch: str) -> Path:
    bottle = record["bottles"][arch]
    rebuild = f".{bottle['bottle_rebuild']}" if bottle["bottle_rebuild"] else ""
    suffix = (
        f"--{record['name']}--{record['package_version']}."
        f"{bottle['bottle_tag']}.bottle{rebuild}.tar.gz"
    )
    try:
        matches = [
            path for path in bottle_cache.rglob("*")
            if path.name.endswith(suffix) and path.is_file() and not path.is_symlink()
        ]
    except OSError as exc:
        raise MacSourceError(f"cannot scan bottle cache: {exc}") from exc
    if len(matches) != 1:
        raise MacSourceError(f"expected one exact bottle for {record['name']}, found {len(matches)}")
    return matches[0]


def _embedded_formula(bottle: Path, record: dict[str, Any]) -> bytes:
    member_name = (
        f"{record['name']}/{record['package_version']}/.brew/{record['name']}.rb"
    )
    try:
        with tarfile.open(bottle, mode="r:gz") as archive:
            matches = [member for member in archive.getmembers() if member.name == member_name]
            if len(matches) != 1 or not matches[0].isfile():
                raise MacSourceError(
                    f"{record['name']} bottle lacks one exact embedded formula: {member_name}"
                )
            handle = archive.extractfile(matches[0])
            if handle is None:
                raise MacSourceError(f"cannot read embedded formula from {bottle}")
            return handle.read()
    except (OSError, tarfile.TarError) as exc:
        raise MacSourceError(f"cannot inspect bottle {bottle}: {exc}") from exc


def _runtime_exception_names(lock: dict[str, Any]) -> set[str]:
    return {
        item["name"] for item in lock["dependency_exceptions"]
        if "runtime" in item["classification"]
    }


def _verify_install_receipt(
    receipt_path: Path,
    record: dict[str, Any],
    arch: str,
    lock: dict[str, Any],
    stable_version: str,
) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(receipt_path, f"{record['name']} install receipt")
    receipt = _parse_json_bytes(raw, f"{record['name']} install receipt")
    expected_arch = "x86_64" if arch == "x64" else "arm64"
    if receipt.get("built_as_bottle") is not True or receipt.get("poured_from_bottle") is not True:
        raise MacSourceError(f"{record['name']} was not installed from a bottle")
    if receipt.get("arch") != expected_arch or receipt.get("compiler") != "clang":
        raise MacSourceError(f"{record['name']} install receipt architecture/compiler drifted")
    if receipt.get("used_options") != [] or receipt.get("unused_options") != []:
        raise MacSourceError(f"{record['name']} bottle must use the default formula options")
    built_on = receipt.get("built_on")
    expected_built_fields = {"clt", "cpu_family", "os", "os_version", "preferred_perl", "xcode"}
    if not isinstance(built_on, dict) or set(built_on) != expected_built_fields:
        raise MacSourceError(f"{record['name']} build metadata fields drifted")
    if built_on.get("os") != "Macintosh" or not str(built_on.get("os_version", "")).startswith("macOS "):
        raise MacSourceError(f"{record['name']} bottle was not built on macOS")
    for field in expected_built_fields:
        _string(built_on[field], f"{record['name']} built_on.{field}")
    source = receipt.get("source")
    if not isinstance(source, dict) or source.get("spec") != "stable" or source.get("tap") != "homebrew/core":
        raise MacSourceError(f"{record['name']} receipt source metadata drifted")
    versions = source.get("versions")
    if not isinstance(versions, dict) or versions.get("stable") != stable_version:
        raise MacSourceError(f"{record['name']} receipt stable version drifted")
    dependencies = receipt.get("runtime_dependencies")
    if not isinstance(dependencies, list):
        raise MacSourceError(f"{record['name']} runtime_dependencies must be an array")
    formulae = {item["name"]: item for item in lock["formulae"]}
    allowed_exceptions = _runtime_exception_names(lock)
    seen: set[str] = set()
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            raise MacSourceError(f"{record['name']} runtime dependency {index} is invalid")
        required = {
            "bottle_rebuild", "declared_directly", "full_name", "pkg_version",
            "revision", "version",
        }
        if set(dependency) != required:
            raise MacSourceError(f"{record['name']} runtime dependency fields drifted")
        name = _string(dependency["full_name"], "runtime dependency name")
        if name in seen:
            raise MacSourceError(f"{record['name']} has duplicate runtime dependency {name}")
        seen.add(name)
        if not isinstance(dependency["declared_directly"], bool):
            raise MacSourceError(f"{record['name']} runtime dependency directness is invalid")
        _nonnegative_int(dependency["revision"], f"{name} revision")
        _nonnegative_int(dependency["bottle_rebuild"], f"{name} bottle rebuild")
        if name in formulae:
            expected = formulae[name]
            if (
                dependency["version"] != expected["package_version"].split("_", 1)[0]
                or dependency["pkg_version"] != expected["package_version"]
                or dependency["bottle_rebuild"]
                != expected["bottles"][arch]["bottle_rebuild"]
            ):
                raise MacSourceError(f"{record['name']} receipt dependency {name} drifted")
        elif name in allowed_exceptions:
            _string(dependency["version"], f"{name} version")
            _string(dependency["pkg_version"], f"{name} package version")
        else:
            raise MacSourceError(f"{record['name']} has an unclassified runtime dependency: {name}")
    if record["name"] == "ffmpeg":
        expected_closure = set(EXPECTED_FORMULAE) - {"ffmpeg"}
        if not expected_closure.issubset(seen):
            missing = sorted(expected_closure - seen)
            raise MacSourceError("ffmpeg receipt is missing source-covered dependencies: " + ", ".join(missing))
    return receipt, raw


def verify_environment(
    lock: dict[str, Any],
    repo_root: Path,
    arch: str,
    source_cache: Path,
    bottle_cache: Path,
    cellar: Path,
) -> dict[str, Any]:
    if arch not in {"arm64", "x64"}:
        raise MacSourceError(f"unsupported architecture: {arch}")
    verify_inventories(lock, repo_root)
    source_raw = verify_cache(lock, source_cache)
    results: dict[str, Any] = {}
    for record in lock["formulae"]:
        formula_raw = source_raw[record["formula"]["archive"]]
        without_bottle, stable_version = _parse_formula_bytes(formula_raw, record)
        bottle = _find_bottle(bottle_cache, record, arch)
        bottle_sha256, bottle_bytes = _sha256_file(bottle)
        expected_bottle = record["bottles"][arch]
        if bottle_sha256 != expected_bottle["bottle_sha256"]:
            raise MacSourceError(f"{record['name']} bottle SHA-256 drifted")
        if _embedded_formula(bottle, record) != without_bottle:
            raise MacSourceError(
                f"{record['name']} bottle embedded formula differs from the exact Homebrew revision"
            )
        receipt_path = cellar / record["name"] / record["package_version"] / "INSTALL_RECEIPT.json"
        receipt, receipt_raw = _verify_install_receipt(
            receipt_path, record, arch, lock, stable_version
        )
        results[record["name"]] = {
            "bottle": {
                "bytes": bottle_bytes,
                "filename": bottle.name,
                "sha256": bottle_sha256,
            },
            "build_metadata": receipt["built_on"],
            "formula_sha256": record["formula"]["sha256"],
            "install_receipt_sha256": _sha256(receipt_raw),
            "source_sha256": record["source"]["sha256"],
        }
    return {
        "arch": arch,
        "formulae": results,
        "inventory_sha256": lock["inventories"][arch]["sha256"],
        "primary_lock_sha256": EXPECTED_LOCK_SHA256,
        "schema": EVIDENCE_SCHEMA,
    }


def verify_bundle(
    lock: dict[str, Any],
    arch: str,
    archive: Path,
    manifest_path: Path,
    repository_commit: str,
    repo_root: Path,
) -> dict[str, Any]:
    if not SHA1_RE.fullmatch(repository_commit):
        raise MacSourceError("repository commit must be an exact 40-character SHA-1")
    module = _load_source_bundle_module(repo_root)
    try:
        manifest = module.verify_bundle(archive, manifest_path)
    except module.SourceBundleError as exc:
        raise MacSourceError(f"corresponding-source bundle failed: {exc}") from exc
    derived = bundle_lock_value(lock, arch)
    if manifest["lock"]["sha256"] != _sha256(canonical_json(derived)):
        raise MacSourceError("bundle is not linked to the macOS source lock and architecture")
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
    if manifest["sources"] != expected_sources:
        raise MacSourceError("bundle source inventory differs from the macOS source lock")
    if manifest["repository"]["commit"] != repository_commit:
        raise MacSourceError("bundle repository commit drifted")
    return manifest


def _write_new(path: Path, raw: bytes, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except OSError as exc:
        raise MacSourceError(f"refusing to overwrite {label}: {path}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    default_lock = Path(__file__).with_name("macos-ffmpeg-sources.lock.json")
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    contracts = commands.add_parser("contracts")
    contracts.add_argument("--lock", type=Path, default=default_lock)
    contracts.add_argument("--repo-root", type=Path, default=default_root)

    bundle_lock = commands.add_parser("write-bundle-lock")
    bundle_lock.add_argument("--lock", type=Path, default=default_lock)
    bundle_lock.add_argument("--arch", choices=("arm64", "x64"), required=True)
    bundle_lock.add_argument("--output", type=Path, required=True)

    fetch = commands.add_parser("fetch-cache")
    fetch.add_argument("--lock", type=Path, default=default_lock)
    fetch.add_argument("--source-cache", type=Path, required=True)

    cache = commands.add_parser("verify-cache")
    cache.add_argument("--lock", type=Path, default=default_lock)
    cache.add_argument("--source-cache", type=Path, required=True)

    environment = commands.add_parser("verify-environment")
    environment.add_argument("--lock", type=Path, default=default_lock)
    environment.add_argument("--repo-root", type=Path, default=default_root)
    environment.add_argument("--arch", choices=("arm64", "x64"), required=True)
    environment.add_argument("--source-cache", type=Path, required=True)
    environment.add_argument("--bottle-cache", type=Path, required=True)
    environment.add_argument("--cellar", type=Path, required=True)
    environment.add_argument("--output", type=Path, required=True)

    bundle = commands.add_parser("verify-bundle")
    bundle.add_argument("--lock", type=Path, default=default_lock)
    bundle.add_argument("--arch", choices=("arm64", "x64"), required=True)
    bundle.add_argument("--archive", type=Path, required=True)
    bundle.add_argument("--manifest", type=Path, required=True)
    bundle.add_argument("--repository-commit", required=True)
    bundle.add_argument("--repo-root", type=Path, default=default_root)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "contracts":
            lock = verify_contracts(args.lock, args.repo_root)
            print(f"verified {len(lock['formulae'])} macOS Homebrew source contracts")
        elif args.command == "write-bundle-lock":
            lock = load_lock(args.lock)
            value = bundle_lock_value(lock, args.arch)
            _write_new(args.output, canonical_json(value), "bundle lock")
            print(f"wrote {args.arch} bundle lock with {len(value['sources'])} inputs")
        elif args.command == "fetch-cache":
            lock = load_lock(args.lock)
            fetch_cache(lock, args.source_cache)
            print(f"fetched and verified {len(cache_items(lock))} exact source inputs")
        elif args.command == "verify-cache":
            lock = load_lock(args.lock)
            verify_cache(lock, args.source_cache)
            print(f"verified {len(cache_items(lock))} exact source inputs")
        elif args.command == "verify-environment":
            lock = load_lock(args.lock)
            evidence = verify_environment(
                lock,
                args.repo_root,
                args.arch,
                args.source_cache,
                args.bottle_cache,
                args.cellar,
            )
            _write_new(args.output, canonical_json(evidence), "source evidence receipt")
            print(f"verified {len(evidence['formulae'])} {args.arch} Homebrew bottles")
        else:
            lock = load_lock(args.lock)
            manifest = verify_bundle(
                lock,
                args.arch,
                args.archive,
                args.manifest,
                args.repository_commit,
                args.repo_root,
            )
            print(f"verified {args.arch} source bundle with {len(manifest['sources'])} inputs")
    except (MacSourceError, OSError, urllib.error.URLError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
