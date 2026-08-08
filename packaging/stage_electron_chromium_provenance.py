#!/usr/bin/env python3
"""Stage hash-locked Electron and Chrome notices and provenance."""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterator


LOCK_SCHEMA = "autoeditor-electron-chromium-provenance-lock/v1"
RECEIPT_SCHEMA = "autoeditor-electron-chromium-provenance/v1"
RECEIPT_FILENAME = "ELECTRON_CHROMIUM_PROVENANCE.json"
TARGET_KEYS = {
    ("mac", "arm64"): "mac-arm64",
    ("mac", "x64"): "mac-x64",
    ("windows", "x64"): "windows-x64",
}
ELECTRON_NOTICE_NAMES = (
    "Electron-LICENSE.txt",
    "Electron-LICENSES.chromium.html",
    RECEIPT_FILENAME,
)
CHROME_NOTICE_NAMES = (
    "Chrome-Headless-Shell-ABOUT.txt",
    "Chrome-Headless-Shell-LICENSE.txt",
)


class ProvenanceError(ValueError):
    """The staged runtime does not match the checked-in provenance lock."""


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, *, canonical: bool = False) -> dict:
    try:
        raw = path.read_bytes()
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProvenanceError(f"JSON root must be an object: {path}")
    if canonical and raw != _canonical_json(value):
        raise ProvenanceError(f"JSON is not canonical: {path}")
    return value


def _require_keys(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ProvenanceError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise ProvenanceError(f"{label} fields are invalid: {'; '.join(detail)}")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProvenanceError(f"{label} must be a nonempty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ProvenanceError(f"{label} contains a control character")
    return value


def _require_sha256(value: object, label: str) -> str:
    text = _require_text(value, label)
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ProvenanceError(f"{label} must be a lowercase SHA-256")
    return text


def _require_git_oid(value: object, label: str) -> str:
    text = _require_text(value, label)
    if not re.fullmatch(r"[0-9a-f]{40}", text):
        raise ProvenanceError(f"{label} must be a full Git object ID")
    return text


def _require_bytes(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProvenanceError(f"{label} must be a positive integer")
    return value


def _require_url(value: object, label: str) -> str:
    text = _require_text(value, label)
    if not text.startswith("https://"):
        raise ProvenanceError(f"{label} must use HTTPS")
    if any(token in text.casefold() for token in ("/latest", "/heads/", "?")):
        raise ProvenanceError(f"{label} must be immutable")
    return text


def _validate_notice(value: object, label: str) -> dict:
    notice = _require_keys(
        value,
        {"archive_member", "bytes", "output_filename", "sha256"},
        label,
    )
    member = _require_text(notice["archive_member"], f"{label}.archive_member")
    output = _require_text(notice["output_filename"], f"{label}.output_filename")
    for path_value, path_label in ((member, "archive_member"), (output, "output")):
        path = PurePosixPath(path_value)
        if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
            raise ProvenanceError(f"{label}.{path_label} must be a basename")
    _require_bytes(notice["bytes"], f"{label}.bytes")
    _require_sha256(notice["sha256"], f"{label}.sha256")
    return notice


def _validate_archive(value: object, label: str, *, chrome: bool) -> dict:
    fields = {"bytes", "filename", "sha256", "url"}
    if chrome:
        fields.update({"archive_root", "binary", "stage_root"})
    archive = _require_keys(value, fields, label)
    filename = _require_text(archive["filename"], f"{label}.filename")
    if PurePosixPath(filename).name != filename or not filename.endswith(".zip"):
        raise ProvenanceError(f"{label}.filename must be a ZIP basename")
    _require_bytes(archive["bytes"], f"{label}.bytes")
    _require_sha256(archive["sha256"], f"{label}.sha256")
    url = _require_url(archive["url"], f"{label}.url")
    if not url.endswith("/" + filename):
        raise ProvenanceError(f"{label}.url does not end with its filename")
    if chrome:
        for field in ("archive_root", "binary", "stage_root"):
            text = _require_text(archive[field], f"{label}.{field}")
            if PurePosixPath(text).name != text:
                raise ProvenanceError(f"{label}.{field} must be a basename")
    return archive


def validate_lock(value: object) -> dict:
    lock = _require_keys(
        value,
        {"chrome_headless_shell", "electron", "provenance_status", "schema"},
        "lock",
    )
    if lock["schema"] != LOCK_SCHEMA:
        raise ProvenanceError(f"lock schema must be {LOCK_SCHEMA}")
    if lock["provenance_status"] != "complete":
        raise ProvenanceError("provenance_status must be complete")

    electron = _require_keys(
        lock["electron"],
        {"archives", "chromium", "notices", "npm_package", "source", "version"},
        "electron",
    )
    electron_version = _require_text(electron["version"], "electron.version")
    electron_archives = _require_keys(
        electron["archives"], set(TARGET_KEYS.values()), "electron.archives"
    )
    for target, archive_value in electron_archives.items():
        archive = _validate_archive(
            archive_value, f"electron.archives.{target}", chrome=False
        )
        if electron_version not in archive["filename"]:
            raise ProvenanceError(
                f"electron.archives.{target} does not name version {electron_version}"
            )

    npm_package = _require_keys(
        electron["npm_package"],
        {"bytes", "filename", "integrity", "members", "resolved", "sha256"},
        "electron.npm_package",
    )
    _require_bytes(npm_package["bytes"], "electron.npm_package.bytes")
    _require_sha256(npm_package["sha256"], "electron.npm_package.sha256")
    resolved = _require_url(npm_package["resolved"], "electron.npm_package.resolved")
    filename = _require_text(
        npm_package["filename"], "electron.npm_package.filename"
    )
    if not resolved.endswith("/" + filename) or electron_version not in filename:
        raise ProvenanceError("Electron npm package URL or filename has drifted")
    integrity = _require_text(
        npm_package["integrity"], "electron.npm_package.integrity"
    )
    if not re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", integrity):
        raise ProvenanceError("Electron npm package integrity must be SHA-512 SRI")
    npm_members = _require_keys(
        npm_package["members"],
        {"package/LICENSE", "package/checksums.json", "package/package.json"},
        "electron.npm_package.members",
    )
    for name, member in npm_members.items():
        record = _require_keys(member, {"bytes", "sha256"}, f"npm member {name}")
        _require_bytes(record["bytes"], f"npm member {name}.bytes")
        _require_sha256(record["sha256"], f"npm member {name}.sha256")

    source = _require_keys(
        electron["source"],
        {"commit", "deps_blob", "repository", "tag", "tag_object", "tree"},
        "electron.source",
    )
    _require_url(source["repository"], "electron.source.repository")
    if source["tag"] != f"v{electron_version}":
        raise ProvenanceError("Electron source tag does not match its version")
    for field in ("commit", "deps_blob", "tag_object", "tree"):
        _require_git_oid(source[field], f"electron.source.{field}")

    chromium = _require_keys(
        electron["chromium"],
        {"commit", "repository", "tag", "version"},
        "electron.chromium",
    )
    chromium_version = _require_text(
        chromium["version"], "electron.chromium.version"
    )
    if chromium["tag"] != chromium_version:
        raise ProvenanceError("Electron Chromium tag does not match its version")
    _require_url(chromium["repository"], "electron.chromium.repository")
    _require_git_oid(chromium["commit"], "electron.chromium.commit")

    notices = _require_keys(
        electron["notices"], {"chromium_licenses", "license"}, "electron.notices"
    )
    license_notice = _validate_notice(notices["license"], "electron.notices.license")
    if license_notice["output_filename"] != ELECTRON_NOTICE_NAMES[0]:
        raise ProvenanceError("Electron license output filename is invalid")
    platform_notices = _require_keys(
        notices["chromium_licenses"], {"mac", "windows"},
        "electron.notices.chromium_licenses",
    )
    for target_os, notice_value in platform_notices.items():
        notice = _validate_notice(
            notice_value, f"electron.notices.chromium_licenses.{target_os}"
        )
        if notice["output_filename"] != ELECTRON_NOTICE_NAMES[1]:
            raise ProvenanceError("Electron Chromium notice output filename is invalid")

    chrome = _require_keys(
        lock["chrome_headless_shell"],
        {"archives", "cft_revision", "notices", "source", "version", "version_output"},
        "chrome_headless_shell",
    )
    chrome_version = _require_text(chrome["version"], "chrome.version")
    revision = _require_text(chrome["cft_revision"], "chrome.cft_revision")
    if not revision.isascii() or not revision.isdecimal():
        raise ProvenanceError("Chrome for Testing revision must be decimal")
    if chrome["version_output"] != f"Google Chrome for Testing {chrome_version}":
        raise ProvenanceError("Chrome version output does not match its version")
    chrome_archives = _require_keys(
        chrome["archives"], set(TARGET_KEYS.values()), "chrome.archives"
    )
    for target, archive_value in chrome_archives.items():
        archive = _validate_archive(
            archive_value, f"chrome.archives.{target}", chrome=True
        )
        if chrome_version not in archive["url"]:
            raise ProvenanceError(
                f"chrome.archives.{target} URL does not name {chrome_version}"
            )
    chrome_source = _require_keys(
        chrome["source"], {"commit", "repository", "tag"}, "chrome.source"
    )
    if chrome_source["tag"] != chrome_version:
        raise ProvenanceError("Chrome source tag does not match its version")
    _require_url(chrome_source["repository"], "chrome.source.repository")
    _require_git_oid(chrome_source["commit"], "chrome.source.commit")
    chrome_notices = _require_keys(
        chrome["notices"], {"mac", "windows"}, "chrome.notices"
    )
    for target_os, notice_value in chrome_notices.items():
        pair = _require_keys(
            notice_value, {"about", "license"}, f"chrome.notices.{target_os}"
        )
        about = _validate_notice(pair["about"], f"chrome.notices.{target_os}.about")
        license_record = _validate_notice(
            pair["license"], f"chrome.notices.{target_os}.license"
        )
        if (
            about["output_filename"] != CHROME_NOTICE_NAMES[0]
            or license_record["output_filename"] != CHROME_NOTICE_NAMES[1]
        ):
            raise ProvenanceError("Chrome notice output filenames are invalid")
    return lock


def load_lock(path: Path) -> dict:
    return validate_lock(_read_json(path, canonical=True))


def required_notice_names(product: str) -> tuple[str, ...]:
    if product == "helper":
        return ELECTRON_NOTICE_NAMES + CHROME_NOTICE_NAMES
    if product == "pse":
        return ELECTRON_NOTICE_NAMES
    raise ProvenanceError(f"unsupported product: {product}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file(path: Path, record: dict, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ProvenanceError(f"cannot read {label}: {path}: {exc}") from exc
    if size != record["bytes"]:
        raise ProvenanceError(
            f"{label} size drifted: expected {record['bytes']}, found {size}"
        )
    actual = _sha256_file(path)
    if actual != record["sha256"]:
        raise ProvenanceError(
            f"{label} SHA-256 drifted: expected {record['sha256']}, found {actual}"
        )
    return path.read_bytes()


def _verify_bytes(data: bytes, record: dict, label: str) -> None:
    if len(data) != record["bytes"]:
        raise ProvenanceError(
            f"{label} size drifted: expected {record['bytes']}, found {len(data)}"
        )
    actual = hashlib.sha256(data).hexdigest()
    if actual != record["sha256"]:
        raise ProvenanceError(
            f"{label} SHA-256 drifted: expected {record['sha256']}, found {actual}"
        )


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "AutoEditor-release-provenance/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with destination.open("wb") as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
    except (OSError, urllib.error.URLError) as exc:
        raise ProvenanceError(f"download failed for {url}: {exc}") from exc


@contextlib.contextmanager
def _archive_path(
    supplied: Path | None, *, url: str, filename: str
) -> Iterator[Path]:
    if supplied is not None:
        yield supplied
        return
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / filename
        _download(url, path)
        yield path


def _tar_member_bytes(bundle: tarfile.TarFile, name: str) -> bytes:
    matches = [member for member in bundle.getmembers() if member.name == name]
    if len(matches) != 1 or not matches[0].isfile():
        raise ProvenanceError(f"Electron npm archive has no unique file {name}")
    handle = bundle.extractfile(matches[0])
    if handle is None:
        raise ProvenanceError(f"cannot read Electron npm archive member {name}")
    return handle.read()


def verify_npm_package(
    archive_path: Path,
    npm_record: dict,
    electron_archives: dict,
    version: str,
) -> None:
    _verify_file(archive_path, npm_record, "Electron npm package")
    sha512 = base64.b64encode(
        hashlib.sha512(archive_path.read_bytes()).digest()
    ).decode("ascii")
    if f"sha512-{sha512}" != npm_record["integrity"]:
        raise ProvenanceError("Electron npm package SHA-512 integrity drifted")
    try:
        with tarfile.open(archive_path, "r:gz") as bundle:
            members = {
                name: _tar_member_bytes(bundle, name)
                for name in npm_record["members"]
            }
    except (OSError, tarfile.TarError) as exc:
        raise ProvenanceError(f"Electron npm archive is invalid: {exc}") from exc
    for name, data in members.items():
        _verify_bytes(data, npm_record["members"][name], f"npm member {name}")
    package = json.loads(members["package/package.json"])
    if package.get("version") != version:
        raise ProvenanceError("Electron npm package version drifted")
    if package.get("license") != "MIT":
        raise ProvenanceError("Electron npm package license declaration drifted")
    if package.get("repository") != "https://github.com/electron/electron":
        raise ProvenanceError("Electron npm package repository drifted")
    checksums = json.loads(
        members["package/checksums.json"], object_pairs_hook=_reject_duplicate_keys
    )
    for target, archive in electron_archives.items():
        actual = checksums.get(archive["filename"])
        if actual != archive["sha256"]:
            raise ProvenanceError(
                f"Electron npm checksums drifted for {target}: "
                f"expected {archive['sha256']}, found {actual}"
            )


def verify_desktop_package_lock(path: Path, lock: dict) -> None:
    package_lock = _read_json(path)
    packages = package_lock.get("packages")
    if not isinstance(packages, dict):
        raise ProvenanceError("desktop package lock has no packages map")
    root = packages.get("")
    package = packages.get("node_modules/electron")
    if not isinstance(root, dict) or not isinstance(package, dict):
        raise ProvenanceError("desktop package lock has no exact Electron package")
    version = lock["electron"]["version"]
    npm_record = lock["electron"]["npm_package"]
    dev_dependencies = root.get("devDependencies")
    if not isinstance(dev_dependencies, dict) or dev_dependencies.get("electron") != version:
        raise ProvenanceError("desktop Electron dependency is not exact")
    expected = {
        "version": version,
        "resolved": npm_record["resolved"],
        "integrity": npm_record["integrity"],
    }
    actual = {field: package.get(field) for field in expected}
    if actual != expected:
        raise ProvenanceError(
            f"desktop Electron lock drifted: expected {expected}, found {actual}"
        )


def verify_installed_electron_package(electron_root: Path, lock: dict) -> bytes:
    electron = lock["electron"]
    package = _read_json(electron_root / "package.json")
    if package.get("version") != electron["version"]:
        raise ProvenanceError("installed Electron package version drifted")
    license_record = electron["notices"]["license"]
    package_license = _verify_file(
        electron_root / "LICENSE", license_record, "Electron package license"
    )
    checksums_record = electron["npm_package"]["members"][
        "package/checksums.json"
    ]
    checksums_bytes = _verify_file(
        electron_root / "checksums.json", checksums_record,
        "installed Electron checksums",
    )
    checksums = json.loads(
        checksums_bytes, object_pairs_hook=_reject_duplicate_keys
    )
    for target, archive in electron["archives"].items():
        if checksums.get(archive["filename"]) != archive["sha256"]:
            raise ProvenanceError(
                f"installed Electron checksums drifted for {target}"
            )
    return package_license


def _zip_member_bytes(bundle: zipfile.ZipFile, name: str, label: str) -> bytes:
    matches = [member for member in bundle.infolist() if member.filename == name]
    if len(matches) != 1 or matches[0].is_dir():
        raise ProvenanceError(f"{label} has no unique file {name}")
    return bundle.read(matches[0])


def verify_electron_archive(
    archive_path: Path,
    archive_record: dict,
    notice_records: dict,
    version: str,
) -> dict[str, bytes]:
    _verify_file(archive_path, archive_record, "Electron binary archive")
    try:
        with zipfile.ZipFile(archive_path) as bundle:
            version_bytes = _zip_member_bytes(bundle, "version", "Electron archive")
            if version_bytes != version.encode("ascii"):
                raise ProvenanceError("Electron archive version drifted")
            result = {}
            for record in notice_records:
                data = _zip_member_bytes(
                    bundle, record["archive_member"], "Electron archive"
                )
                _verify_bytes(
                    data, record,
                    f"Electron archive member {record['archive_member']}",
                )
                result[record["output_filename"]] = data
            return result
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProvenanceError(f"Electron binary archive is invalid: {exc}") from exc


def _safe_zip_members(bundle: zipfile.ZipFile, archive_root: str) -> list[zipfile.ZipInfo]:
    members = bundle.infolist()
    seen = set()
    casefolded = set()
    total_size = 0
    for member in members:
        name = member.filename
        if "\\" in name or "\0" in name:
            raise ProvenanceError(f"Chrome archive has an unsafe path: {name!r}")
        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or any(
            part in {"", ".", ".."} for part in path.parts
        ):
            raise ProvenanceError(f"Chrome archive has an unsafe path: {name!r}")
        if path.parts[0] != archive_root:
            raise ProvenanceError(f"Chrome archive escaped its root: {name!r}")
        normalized = path.as_posix().rstrip("/")
        if normalized in seen or normalized.casefold() in casefolded:
            raise ProvenanceError(f"Chrome archive has a duplicate path: {name!r}")
        seen.add(normalized)
        casefolded.add(normalized.casefold())
        if member.flag_bits & 0x1:
            raise ProvenanceError(f"Chrome archive has an encrypted member: {name!r}")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ProvenanceError(f"Chrome archive has a symlink: {name!r}")
        file_type = stat.S_IFMT(mode)
        if file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ProvenanceError(f"Chrome archive has a special file: {name!r}")
        if not member.is_dir():
            total_size += member.file_size
            if total_size > 2 * 1024 * 1024 * 1024:
                raise ProvenanceError("Chrome archive expands beyond 2 GiB")
    if not members:
        raise ProvenanceError("Chrome archive is empty")
    return members


def _extract_chrome(
    archive_path: Path,
    archive_record: dict,
    notice_records: dict,
    browser_dir: Path,
    version_output: str,
) -> tuple[Path, dict[str, bytes]]:
    _verify_file(archive_path, archive_record, "Chrome Headless Shell archive")
    browser_dir.mkdir(parents=True, exist_ok=True)
    destination = browser_dir / archive_record["stage_root"]
    if destination.exists():
        raise ProvenanceError(f"Chrome destination already exists: {destination}")
    try:
        with tempfile.TemporaryDirectory(dir=browser_dir) as temporary:
            extracted = Path(temporary) / archive_record["stage_root"]
            extracted.mkdir()
            with zipfile.ZipFile(archive_path) as bundle:
                members = _safe_zip_members(bundle, archive_record["archive_root"])
                for member in members:
                    relative_parts = PurePosixPath(member.filename).parts[1:]
                    if not relative_parts:
                        continue
                    output = extracted.joinpath(*relative_parts)
                    if member.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                        continue
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, output.open("wb") as target:
                        shutil.copyfileobj(source, target, 1024 * 1024)
                    mode = (member.external_attr >> 16) & 0o777
                    output.chmod(mode or 0o644)
            binary = extracted / archive_record["binary"]
            if not binary.is_file():
                raise ProvenanceError("Chrome archive is missing its expected binary")
            if os.name != "nt":
                binary.chmod(binary.stat().st_mode | 0o755)
            result = subprocess.run(
                [str(binary), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = f"{result.stdout}\n{result.stderr}".strip()
            if result.returncode != 0 or output != version_output:
                raise ProvenanceError(
                    f"Chrome binary version drifted: exit {result.returncode}, "
                    f"output {output!r}"
                )
            notices = {}
            for name, record in notice_records.items():
                data = _verify_file(
                    extracted / record["archive_member"], record,
                    f"Chrome {name} notice",
                )
                notices[record["output_filename"]] = data
            os.replace(extracted, destination)
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        raise ProvenanceError(f"cannot stage Chrome Headless Shell: {exc}") from exc
    return destination, notices


def expected_receipt(
    lock: dict, *, product: str, target_os: str, target_arch: str
) -> dict:
    try:
        target_key = TARGET_KEYS[(target_os, target_arch)]
    except KeyError as exc:
        raise ProvenanceError(
            f"unsupported release target: {target_os}-{target_arch}"
        ) from exc
    electron = lock["electron"]
    electron_notice_records = {
        electron["notices"]["license"]["output_filename"]:
            electron["notices"]["license"],
        electron["notices"]["chromium_licenses"][target_os]["output_filename"]:
            electron["notices"]["chromium_licenses"][target_os],
    }
    receipt = {
        "electron": {
            "binary_archive": electron["archives"][target_key],
            "chromium": electron["chromium"],
            "notices": electron_notice_records,
            "npm_package": electron["npm_package"],
            "source": electron["source"],
            "version": electron["version"],
        },
        "product": product,
        "schema": RECEIPT_SCHEMA,
        "target": {"arch": target_arch, "os": target_os},
    }
    if product == "helper":
        chrome = lock["chrome_headless_shell"]
        chrome_notice_records = {
            record["output_filename"]: record
            for record in chrome["notices"][target_os].values()
        }
        receipt["chrome_headless_shell"] = {
            "archive": chrome["archives"][target_key],
            "cft_revision": chrome["cft_revision"],
            "notices": chrome_notice_records,
            "source": chrome["source"],
            "version": chrome["version"],
        }
    elif product != "pse":
        raise ProvenanceError(f"unsupported product: {product}")
    return receipt


def verify_staged_notices(
    licenses: Path,
    lock: dict,
    *,
    product: str,
    target_os: str,
    target_arch: str,
) -> None:
    expected = expected_receipt(
        lock, product=product, target_os=target_os, target_arch=target_arch
    )
    receipt_path = licenses / RECEIPT_FILENAME
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError as exc:
        raise ProvenanceError(f"cannot read provenance receipt: {exc}") from exc
    expected_bytes = _canonical_json(expected)
    if receipt_bytes != expected_bytes:
        raise ProvenanceError("Electron and Chromium provenance receipt drifted")
    notice_records = dict(expected["electron"]["notices"])
    if product == "helper":
        notice_records.update(expected["chrome_headless_shell"]["notices"])
    for filename in required_notice_names(product):
        if filename == RECEIPT_FILENAME:
            continue
        record = notice_records.get(filename)
        if record is None:
            raise ProvenanceError(f"receipt has no record for {filename}")
        _verify_file(licenses / filename, record, filename)


def stage(
    *,
    lock_path: Path,
    desktop_package_lock: Path,
    electron_root: Path,
    licenses: Path,
    product: str,
    target_os: str,
    target_arch: str,
    browser_dir: Path | None,
    npm_package_archive: Path | None = None,
    electron_archive: Path | None = None,
    chrome_archive: Path | None = None,
) -> Path | None:
    lock = load_lock(lock_path)
    receipt = expected_receipt(
        lock, product=product, target_os=target_os, target_arch=target_arch
    )
    target_key = TARGET_KEYS[(target_os, target_arch)]
    verify_desktop_package_lock(desktop_package_lock, lock)
    npm_record = lock["electron"]["npm_package"]
    with _archive_path(
        npm_package_archive,
        url=npm_record["resolved"],
        filename=npm_record["filename"],
    ) as npm_path:
        verify_npm_package(
            npm_path,
            npm_record,
            lock["electron"]["archives"],
            lock["electron"]["version"],
        )
    package_license = verify_installed_electron_package(electron_root, lock)
    electron_archive_record = lock["electron"]["archives"][target_key]
    electron_notice_records = (
        lock["electron"]["notices"]["license"],
        lock["electron"]["notices"]["chromium_licenses"][target_os],
    )
    with _archive_path(
        electron_archive,
        url=electron_archive_record["url"],
        filename=electron_archive_record["filename"],
    ) as electron_path:
        notice_bytes = verify_electron_archive(
            electron_path,
            electron_archive_record,
            electron_notice_records,
            lock["electron"]["version"],
        )
    if notice_bytes[ELECTRON_NOTICE_NAMES[0]] != package_license:
        raise ProvenanceError("Electron package and binary licenses differ")
    staged_browser = None
    if product == "helper":
        if browser_dir is None:
            raise ProvenanceError("Helper staging requires --browser-dir")
        chrome_record = lock["chrome_headless_shell"]["archives"][target_key]
        with _archive_path(
            chrome_archive,
            url=chrome_record["url"],
            filename=chrome_record["filename"],
        ) as chrome_path:
            staged_browser, chrome_notices = _extract_chrome(
                chrome_path,
                chrome_record,
                lock["chrome_headless_shell"]["notices"][target_os],
                browser_dir,
                lock["chrome_headless_shell"]["version_output"],
            )
        notice_bytes.update(chrome_notices)
    elif browser_dir is not None or chrome_archive is not None:
        raise ProvenanceError("PSE staging may not add standalone Chrome")
    licenses.mkdir(parents=True, exist_ok=True)
    for filename, data in notice_bytes.items():
        (licenses / filename).write_bytes(data)
    (licenses / RECEIPT_FILENAME).write_bytes(_canonical_json(receipt))
    verify_staged_notices(
        licenses,
        lock,
        product=product,
        target_os=target_os,
        target_arch=target_arch,
    )
    return staged_browser


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lock", type=Path, required=True)
    common.add_argument("--licenses", type=Path, required=True)
    common.add_argument("--product", choices=("helper", "pse"), required=True)
    common.add_argument("--target-os", choices=("mac", "windows"), required=True)
    common.add_argument("--target-arch", choices=("arm64", "x64"), required=True)

    stage_parser = subparsers.add_parser("stage", parents=[common])
    stage_parser.add_argument("--desktop-package-lock", type=Path, required=True)
    stage_parser.add_argument("--electron-root", type=Path, required=True)
    stage_parser.add_argument("--browser-dir", type=Path)
    stage_parser.add_argument("--npm-package-archive", type=Path)
    stage_parser.add_argument("--electron-archive", type=Path)
    stage_parser.add_argument("--chrome-archive", type=Path)
    subparsers.add_parser("verify", parents=[common])
    args = parser.parse_args()
    try:
        if args.command == "stage":
            staged_browser = stage(
                lock_path=args.lock,
                desktop_package_lock=args.desktop_package_lock,
                electron_root=args.electron_root,
                licenses=args.licenses,
                product=args.product,
                target_os=args.target_os,
                target_arch=args.target_arch,
                browser_dir=args.browser_dir,
                npm_package_archive=args.npm_package_archive,
                electron_archive=args.electron_archive,
                chrome_archive=args.chrome_archive,
            )
            suffix = f" and browser {staged_browser}" if staged_browser else ""
            print(f"Electron and Chromium notices staged{suffix}")
        else:
            lock = load_lock(args.lock)
            verify_staged_notices(
                args.licenses,
                lock,
                product=args.product,
                target_os=args.target_os,
                target_arch=args.target_arch,
            )
            print("Electron and Chromium notices verified")
    except ProvenanceError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
