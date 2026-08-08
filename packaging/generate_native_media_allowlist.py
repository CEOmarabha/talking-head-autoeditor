#!/usr/bin/env python3
"""Generate a digest-bound allowlist from authenticated producer receipts.

This is a technical provenance gate. It does not make a licensing or legal
determination. Each accepted receipt is authenticated by a caller-supplied raw
SHA256 before its schema is interpreted. Native paths are discovered by the
held-handle scanner in ``native_media_receipt``. A path is emitted only when
one exact producer contract owns it.

The current repository has no exact producer contract for the transformed
macOS FFmpeg bundle, the installed macOS Remotion compositor, or native files
created by Electron Builder outside the staged Resources tree. Those paths are
rejected instead of accepting a generic claim manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_JSON_BYTES = 64 * 1024 * 1024
ELECTRON_CHROMIUM_SCHEMA = "autoeditor-electron-chromium-provenance/v1"
RUNTIME_BUILD_SCHEMA = "autoeditor-helper-runtime/v1"
WINDOWS_FFMPEG_BUILD_SCHEMA = "autoeditor-windows-ffmpeg-build/v4"
SOURCE_BUNDLE_SCHEMA = "autoeditor-corresponding-source-bundle/v1"


class AllowlistGenerationError(ValueError):
    """An input, producer claim, or final native tree failed closed."""


class MissingProducerContractError(AllowlistGenerationError):
    """The repository has no exact producer contract for a required path."""


@dataclass(frozen=True)
class AuthenticatedJson:
    path: Path
    payload: dict[str, Any]
    raw: bytes
    sha256: str


@dataclass(frozen=True)
class AuthenticatedFile:
    path: Path
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class ProducerOwner:
    component: str
    lineage_id: str
    source_manifest_sha256: str
    producer: str


@dataclass(frozen=True)
class ProducerClaim:
    owner: ProducerOwner
    sha256: str
    byte_count: int | None


@dataclass(frozen=True)
class GeneratorInputs:
    onnx_receipt: Path
    onnx_receipt_sha256: str
    electron_chromium_receipt: Path
    electron_chromium_receipt_sha256: str
    creative_runtime_lock: Path
    creative_runtime_lock_sha256: str
    runtime_build_manifest: Path
    runtime_build_manifest_sha256: str
    remotion_receipt: Path | None = None
    remotion_receipt_sha256: str | None = None
    windows_ffmpeg_build_receipt: Path | None = None
    windows_ffmpeg_build_receipt_sha256: str | None = None
    windows_ffmpeg_source_manifest: Path | None = None
    windows_ffmpeg_source_manifest_sha256: str | None = None
    windows_ffmpeg_source_lock: Path | None = None
    windows_ffmpeg_source_lock_sha256: str | None = None
    windows_ffmpeg_capabilities: Path | None = None
    windows_ffmpeg_capabilities_sha256: str | None = None
    windows_ffmpeg_source_bundle: Path | None = None
    windows_ffmpeg_source_bundle_sha256: str | None = None
    windows_ffmpeg_license_dir: Path | None = None
    windows_ffmpeg_link_evidence_dir: Path | None = None
    windows_ffmpeg_linkage_dir: Path | None = None
    windows_ffmpeg_repository_commit: str | None = None
    mac_normalization_receipt: Path | None = None
    mac_normalization_receipt_sha256: str | None = None


def _load_sibling(name: str):
    source = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(
        f"autoeditor_allowlist_{name}", source
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load required sibling module: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


native = _load_sibling("native_media_receipt")
normalizer = _load_sibling("normalize_pyinstaller_symlinks")
helper_manifest = _load_sibling("generate_helper_manifest")
source_bundle = _load_sibling("source_bundle")
try:
    windows_ffmpeg_verifier = _load_sibling("verify_windows_ffmpeg")
    windows_ffmpeg_verifier_error: Exception | None = None
except Exception as exc:
    windows_ffmpeg_verifier = None
    windows_ffmpeg_verifier_error = exc


def canonical_json_bytes(value: Any) -> bytes:
    return native.canonical_json_bytes(value)


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AllowlistGenerationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AllowlistGenerationError(f"invalid expected SHA256 for {label}")
    return value


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _read_authenticated_json(
    path: Path,
    expected_sha256: str,
    label: str,
) -> AuthenticatedJson:
    expected = _sha256(expected_sha256, label)
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise AllowlistGenerationError(
                f"{label} must be a regular file, not a symlink"
            )
        if before.st_nlink != 1:
            raise AllowlistGenerationError(
                f"{label} must have exactly one filesystem link"
            )
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            raise AllowlistGenerationError(f"{label} has an invalid byte count")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(
            os, "O_CLOEXEC", 0
        )
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise AllowlistGenerationError(f"{label} changed while opening")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                raise AllowlistGenerationError(f"{label} is too large")
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
        ):
            raise AllowlistGenerationError(f"{label} changed while reading")
        raw = b"".join(chunks)
    except AllowlistGenerationError:
        raise
    except OSError as exc:
        raise AllowlistGenerationError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise AllowlistGenerationError(
            f"{label} raw SHA256 mismatch: expected {expected}, found {actual}"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except AllowlistGenerationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AllowlistGenerationError(f"cannot decode {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AllowlistGenerationError(f"{label} root must be an object")
    return AuthenticatedJson(path, payload, raw, actual)


def _authenticate_regular_file(
    path: Path,
    expected_sha256: str,
    label: str,
) -> AuthenticatedFile:
    expected = _sha256(expected_sha256, label)
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise AllowlistGenerationError(
                f"{label} must be a regular file, not a symlink"
            )
        if before.st_nlink != 1 or before.st_size <= 0:
            raise AllowlistGenerationError(
                f"{label} must have one filesystem link and nonzero bytes"
            )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(
            os, "O_CLOEXEC", 0
        )
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            raise AllowlistGenerationError(f"{label} changed while opening")
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
        after_handle = os.fstat(descriptor)
        after_path = path.lstat()
        if (
            _stat_identity(opened) != _stat_identity(after_handle)
            or _stat_identity(opened) != _stat_identity(after_path)
        ):
            raise AllowlistGenerationError(f"{label} changed while reading")
    except AllowlistGenerationError:
        raise
    except OSError as exc:
        raise AllowlistGenerationError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    actual = digest.hexdigest()
    if actual != expected:
        raise AllowlistGenerationError(
            f"{label} raw SHA256 mismatch: expected {expected}, found {actual}"
        )
    return AuthenticatedFile(path, actual, byte_count)


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AllowlistGenerationError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("extra " + ", ".join(extra))
        raise AllowlistGenerationError(
            f"{label} has wrong fields ({'; '.join(detail)})"
        )
    return value


def _platform_target(platform: str) -> dict[str, str]:
    if platform == "windows-x64":
        return {"arch": "x64", "os": "windows"}
    if platform == "mac-arm64":
        return {"arch": "arm64", "os": "mac"}
    if platform == "mac-x64":
        return {"arch": "x64", "os": "mac"}
    raise AllowlistGenerationError(f"unsupported platform: {platform}")


ELECTRON_ARCHIVES = {
    "windows-x64": {
        "bytes": 144396349,
        "filename": "electron-v43.3.0-win32-x64.zip",
        "sha256": "18528bedc6a9b04bdc5efb7b803cbc3cb0e5ea6415d54046e23d464d89a00da9",
        "url": (
            "https://github.com/electron/electron/releases/download/v43.3.0/"
            "electron-v43.3.0-win32-x64.zip"
        ),
    },
    "mac-arm64": {
        "bytes": 122102881,
        "filename": "electron-v43.3.0-darwin-arm64.zip",
        "sha256": "ee939d1564d83d61032b3b3cb23af4e46005a4900c91f0695f7ed793f0ce6e83",
        "url": (
            "https://github.com/electron/electron/releases/download/v43.3.0/"
            "electron-v43.3.0-darwin-arm64.zip"
        ),
    },
    "mac-x64": {
        "bytes": 124293997,
        "filename": "electron-v43.3.0-darwin-x64.zip",
        "sha256": "7347bbd5fb529eea64f9c2d148bb1c19222d98946ff234ffe27953a1bbcb9dae",
        "url": (
            "https://github.com/electron/electron/releases/download/v43.3.0/"
            "electron-v43.3.0-darwin-x64.zip"
        ),
    },
}

CHROME_ARCHIVES = {
    "windows-x64": {
        "archive_root": "chrome-headless-shell-win64",
        "binary": "chrome-headless-shell.exe",
        "bytes": 120932410,
        "filename": "chrome-headless-shell-win64.zip",
        "sha256": "ec7d7cfbc9d97093c9269d6a26de78a3244a49f3112ff9616e2ccb5ac3afeb24",
        "stage_root": "chrome-headless-shell-win64",
        "url": (
            "https://storage.googleapis.com/chrome-for-testing-public/"
            "152.0.7928.2/win64/chrome-headless-shell-win64.zip"
        ),
    },
    "mac-arm64": {
        "archive_root": "chrome-headless-shell-mac-arm64",
        "binary": "chrome-headless-shell",
        "bytes": 99137906,
        "filename": "chrome-headless-shell-mac-arm64.zip",
        "sha256": "e4ca218c9cb2da2117cabd1ca4a2318a9a80efffbba242045be68d708ce3a5ed",
        "stage_root": "chrome-headless-shell-mac",
        "url": (
            "https://storage.googleapis.com/chrome-for-testing-public/"
            "152.0.7928.2/mac-arm64/chrome-headless-shell-mac-arm64.zip"
        ),
    },
    "mac-x64": {
        "archive_root": "chrome-headless-shell-mac-x64",
        "binary": "chrome-headless-shell",
        "bytes": 103765768,
        "filename": "chrome-headless-shell-mac-x64.zip",
        "sha256": "3b4e27aa52345a4177f0b69211ef3e70476cfab156f75d7c3dc11342ef488ae2",
        "stage_root": "chrome-headless-shell-mac",
        "url": (
            "https://storage.googleapis.com/chrome-for-testing-public/"
            "152.0.7928.2/mac-x64/chrome-headless-shell-mac-x64.zip"
        ),
    },
}


ELECTRON_SOURCE = {
    "commit": "1aa21d231aeaf5634880a6e60187256e9f2fd4f9",
    "deps_blob": "5edf5704707973a93c2af16c1ed3cf1b852b72d3",
    "repository": "https://github.com/electron/electron.git",
    "tag": "v43.3.0",
    "tag_object": "51209d845e68865d5cca5cfec3a645f1ff7df48c",
    "tree": "bae3a10ebeb1d9dfb845565e7bcf600322c1366b",
}
ELECTRON_CHROMIUM = {
    "commit": "69bf1c67cb894365d151bd020bb0171fd583633a",
    "repository": "https://chromium.googlesource.com/chromium/src.git",
    "tag": "150.0.7871.212",
    "version": "150.0.7871.212",
}
ELECTRON_NPM_PACKAGE = {
    "bytes": 194534,
    "filename": "electron-43.3.0.tgz",
    "integrity": (
        "sha512-nLlvu0WFjftWsSaTkV2B/c4NDuJBspTyXu8vKSQ6vLvFt8uG3NgN49LLKcXddwX0"
        "GqVvAQDhciWp+4xOdTdhew=="
    ),
    "members": {
        "package/LICENSE": {
            "bytes": 1096,
            "sha256": "5154e165bd6c2cc0cfbcd8916498c7abab0497923bafcd5cb07673fe8480087d",
        },
        "package/checksums.json": {
            "bytes": 8138,
            "sha256": "3cc7d8c0e3822e924b1c20ca300581a128c81f3ec846372063a8f7aa3625f1a9",
        },
        "package/package.json": {
            "bytes": 744,
            "sha256": "3d4cb058d752ffea804929bec188b02671de846c049128b31b5dd8e50e102c56",
        },
    },
    "resolved": "https://registry.npmjs.org/electron/-/electron-43.3.0.tgz",
    "sha256": "581b6b729df7582407aca4817e71078e815bb96de764185276a8fd15b5905399",
}
ELECTRON_NOTICES = {
    "windows": {
        "Electron-LICENSE.txt": {
            "archive_member": "LICENSE",
            "bytes": 1096,
            "output_filename": "Electron-LICENSE.txt",
            "sha256": "5154e165bd6c2cc0cfbcd8916498c7abab0497923bafcd5cb07673fe8480087d",
        },
        "Electron-LICENSES.chromium.html": {
            "archive_member": "LICENSES.chromium.html",
            "bytes": 20313957,
            "output_filename": "Electron-LICENSES.chromium.html",
            "sha256": "b911161e6594ec76b872498b423c54406168f2974e0d407a847f7de1e5ff94dd",
        },
    },
    "mac": {
        "Electron-LICENSE.txt": {
            "archive_member": "LICENSE",
            "bytes": 1096,
            "output_filename": "Electron-LICENSE.txt",
            "sha256": "5154e165bd6c2cc0cfbcd8916498c7abab0497923bafcd5cb07673fe8480087d",
        },
        "Electron-LICENSES.chromium.html": {
            "archive_member": "LICENSES.chromium.html",
            "bytes": 19956019,
            "output_filename": "Electron-LICENSES.chromium.html",
            "sha256": "4fc0507a046b9ecd0738b2dd64119b5ec8bc29ac0221b63edb693fd5fd497c87",
        },
    },
}
CHROME_NOTICES = {
    "windows": {
        "Chrome-Headless-Shell-ABOUT.txt": {
            "archive_member": "ABOUT",
            "bytes": 257,
            "output_filename": "Chrome-Headless-Shell-ABOUT.txt",
            "sha256": "122b32f3ee3f1e8d65c774f5257fc6cc2127b666148ced0ce2efa3ea57e1d93c",
        },
        "Chrome-Headless-Shell-LICENSE.txt": {
            "archive_member": "LICENSE.headless_shell",
            "bytes": 2126763,
            "output_filename": "Chrome-Headless-Shell-LICENSE.txt",
            "sha256": "b8e35b682081095c7082a84021aa612c740a62c479eccb8a9846838f5c82cd1f",
        },
    },
    "mac": {
        "Chrome-Headless-Shell-ABOUT.txt": {
            "archive_member": "ABOUT",
            "bytes": 248,
            "output_filename": "Chrome-Headless-Shell-ABOUT.txt",
            "sha256": "34d078ce3003087a8374e7c6156fda374769b8047d6ddaf419d66414aa48edfb",
        },
        "Chrome-Headless-Shell-LICENSE.txt": {
            "archive_member": "LICENSE.headless_shell",
            "bytes": 1855737,
            "output_filename": "Chrome-Headless-Shell-LICENSE.txt",
            "sha256": "fa3c4920c528c1cb14b4bfb480b1e8a71add17585b4776ce1f258cd14587b00b",
        },
    },
}
CHROME_SOURCE = {
    "commit": "8e122fd6ce1b7bb7bcef0fd0b2e96018ff110c4d",
    "repository": "https://chromium.googlesource.com/chromium/src.git",
    "tag": "152.0.7928.2",
}


def _expected_electron_chromium(platform: str) -> dict[str, Any]:
    target = _platform_target(platform)
    target_os = target["os"]
    return {
        "chrome_headless_shell": {
            "archive": CHROME_ARCHIVES[platform],
            "cft_revision": "1656291",
            "notices": CHROME_NOTICES[target_os],
            "source": CHROME_SOURCE,
            "version": native.CHROME_HEADLESS_SHELL_VERSION,
        },
        "electron": {
            "binary_archive": ELECTRON_ARCHIVES[platform],
            "chromium": ELECTRON_CHROMIUM,
            "notices": ELECTRON_NOTICES[target_os],
            "npm_package": ELECTRON_NPM_PACKAGE,
            "source": ELECTRON_SOURCE,
            "version": "43.3.0",
        },
        "product": "helper",
        "schema": ELECTRON_CHROMIUM_SCHEMA,
        "target": target,
    }


def _validate_electron_chromium(
    authenticated: AuthenticatedJson,
    platform: str,
) -> None:
    payload = _exact_keys(
        authenticated.payload,
        {"chrome_headless_shell", "electron", "product", "schema", "target"},
        "Electron and Chromium provenance receipt",
    )
    if payload["schema"] != ELECTRON_CHROMIUM_SCHEMA:
        raise AllowlistGenerationError(
            "Electron and Chromium provenance receipt has wrong schema"
        )
    if payload["product"] != "helper" or payload["target"] != _platform_target(
        platform
    ):
        raise AllowlistGenerationError(
            "Electron and Chromium provenance receipt has wrong product or target"
        )
    if authenticated.raw != (
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8"):
        raise AllowlistGenerationError(
            "Electron and Chromium provenance receipt is not canonical"
        )

    if payload != _expected_electron_chromium(platform):
        raise AllowlistGenerationError(
            "Electron 43.3.0 and Chrome 152.0.7928.2 provenance receipt drifted"
        )

    electron = _exact_keys(
        payload["electron"],
        {"binary_archive", "chromium", "notices", "npm_package", "source", "version"},
        "Electron provenance",
    )
    if electron["version"] != "43.3.0":
        raise AllowlistGenerationError("Electron version must be 43.3.0")
    if electron["binary_archive"] != ELECTRON_ARCHIVES[platform]:
        raise AllowlistGenerationError(
            "Electron 43.3.0 binary archive provenance drifted"
        )
    source = _exact_keys(
        electron["source"],
        {"commit", "deps_blob", "repository", "tag", "tag_object", "tree"},
        "Electron source provenance",
    )
    if source != ELECTRON_SOURCE:
        raise AllowlistGenerationError("Electron source provenance drifted")
    chromium = _exact_keys(
        electron["chromium"],
        {"commit", "repository", "tag", "version"},
        "Electron Chromium provenance",
    )
    if chromium != ELECTRON_CHROMIUM:
        raise AllowlistGenerationError("Electron Chromium provenance drifted")
    npm_package = _exact_keys(
        electron["npm_package"],
        {"bytes", "filename", "integrity", "members", "resolved", "sha256"},
        "Electron npm provenance",
    )
    if (
        npm_package["bytes"] != 194534
        or npm_package["filename"] != "electron-43.3.0.tgz"
        or npm_package["integrity"]
        != "sha512-nLlvu0WFjftWsSaTkV2B/c4NDuJBspTyXu8vKSQ6vLvFt8uG3NgN49LLKcXddwX0GqVvAQDhciWp+4xOdTdhew=="
        or npm_package["resolved"]
        != "https://registry.npmjs.org/electron/-/electron-43.3.0.tgz"
        or npm_package["sha256"]
        != "581b6b729df7582407aca4817e71078e815bb96de764185276a8fd15b5905399"
    ):
        raise AllowlistGenerationError("Electron npm provenance drifted")
    if not isinstance(electron["notices"], dict) or set(electron["notices"]) != {
        "Electron-LICENSE.txt",
        "Electron-LICENSES.chromium.html",
    }:
        raise AllowlistGenerationError("Electron notice provenance is incomplete")

    chrome = _exact_keys(
        payload["chrome_headless_shell"],
        {"archive", "cft_revision", "notices", "source", "version"},
        "Chrome Headless Shell provenance",
    )
    if (
        chrome["version"] != native.CHROME_HEADLESS_SHELL_VERSION
        or chrome["cft_revision"] != "1656291"
        or chrome["archive"] != CHROME_ARCHIVES[platform]
    ):
        raise AllowlistGenerationError("Chrome Headless Shell provenance drifted")
    if chrome["source"] != CHROME_SOURCE:
        raise AllowlistGenerationError("Chrome source provenance drifted")
    if not isinstance(chrome["notices"], dict) or set(chrome["notices"]) != {
        "Chrome-Headless-Shell-ABOUT.txt",
        "Chrome-Headless-Shell-LICENSE.txt",
    }:
        raise AllowlistGenerationError("Chrome notice provenance is incomplete")


HYPERFRAMES_INTEGRITY = (
    "sha512-wZHchPo048F6f2B2hvB/K9t1qF9Le3y1pPqC5k3xkty3w3d7AS40k3fraFC366xdzEzJll8kWpU18MH9xyArHQ=="
)
REMOTION_INTEGRITIES = {
    "windows-x64": (
        "node_modules/@remotion/compositor-win32-x64-msvc",
        native.REMOTION_PACKAGE_INTEGRITY,
    ),
    "mac-arm64": (
        "node_modules/@remotion/compositor-darwin-arm64",
        "sha512-MNvUNS33X3YCwalX+LbGcYXXxkWnOspX2vB7agzkHE/IKSFAG58sF9iXyp+rn6lJmCjBcaUxO7paJFxfAzjwEw==",
    ),
    "mac-x64": (
        "node_modules/@remotion/compositor-darwin-x64",
        "sha512-oz8Wjq42oKZwhTc2N20tBMXx7Ts3K5T+cQH6oo5PEyFgrpx1j5Lm2AQTsunlgiMhOda20Vff0ZLeiXVUR+xtuA==",
    ),
}


def _validate_creative_runtime_lock(
    authenticated: AuthenticatedJson,
    platform: str,
) -> None:
    lock = authenticated.payload
    if (
        lock.get("name") != "autoeditor-creative-runtime"
        or lock.get("version") != "0.1.0"
        or lock.get("lockfileVersion") != 3
        or lock.get("requires") is not True
    ):
        raise AllowlistGenerationError(
            "creative runtime package lock root identity drifted"
        )
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise AllowlistGenerationError("creative runtime package lock has no packages map")
    root = packages.get("")
    if not isinstance(root, dict) or root.get("dependencies") != {
        "@remotion/cli": "4.0.507",
        "gsap": "3.15.0",
        "hyperframes": "0.7.99",
        "react": "19.0.0",
        "react-dom": "19.0.0",
        "remotion": "4.0.507",
    }:
        raise AllowlistGenerationError("creative runtime root dependencies drifted")
    hyperframes = packages.get("node_modules/hyperframes")
    if not isinstance(hyperframes, dict) or any(
        hyperframes.get(field) != expected
        for field, expected in {
            "version": native.HYPERFRAMES_VERSION,
            "resolved": (
                "https://registry.npmjs.org/hyperframes/-/"
                "hyperframes-0.7.99.tgz"
            ),
            "integrity": HYPERFRAMES_INTEGRITY,
        }.items()
    ):
        raise AllowlistGenerationError("HyperFrames 0.7.99 package provenance drifted")
    remotion_key, remotion_integrity = REMOTION_INTEGRITIES[platform]
    remotion = packages.get(remotion_key)
    if not isinstance(remotion, dict) or any(
        remotion.get(field) != expected
        for field, expected in {
            "version": native.REMOTION_VERSION,
            "integrity": remotion_integrity,
        }.items()
    ):
        raise AllowlistGenerationError(
            f"Remotion 4.0.507 package provenance drifted for {platform}"
        )
    onnx = packages.get("node_modules/onnxruntime-node")
    if not isinstance(onnx, dict) or any(
        onnx.get(field) != expected
        for field, expected in {
            "version": native.ONNX_PACKAGE_VERSION,
            "integrity": native.ONNX_PACKAGE_INTEGRITY,
        }.items()
    ):
        raise AllowlistGenerationError("ONNX Runtime package provenance drifted")


RUNTIME_COMPONENTS = (
    "helper",
    "engine",
    "bin",
    "lib",
    "models",
    "profiles",
    "fonts",
    "certs",
    "node",
    "creative-runtime",
    "browser",
    "creative",
    "licenses",
)


def _resources_root(app_root: Path, platform: str) -> Path:
    return (
        app_root / "resources"
        if platform == "windows-x64"
        else app_root / "Contents" / "Resources"
    )


def _validate_runtime_build_manifest(
    authenticated: AuthenticatedJson,
    app_root: Path,
    platform: str,
) -> None:
    payload = _exact_keys(
        authenticated.payload,
        {
            "account_capabilities",
            "builder",
            "components",
            "receipt_algorithm",
            "required_local_capabilities",
            "schema",
            "target",
            "version",
        },
        "Helper runtime build manifest",
    )
    if payload["schema"] != RUNTIME_BUILD_SCHEMA:
        raise AllowlistGenerationError("Helper runtime build manifest has wrong schema")
    if authenticated.raw != (
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8"):
        raise AllowlistGenerationError(
            "Helper runtime build manifest is not canonical"
        )
    if payload["target"] != _platform_target(platform):
        raise AllowlistGenerationError("Helper runtime build manifest has wrong target")
    expected_algorithm = (
        "pe-authenticode-content-v1"
        if platform == "windows-x64"
        else "raw-sha256-v1"
    )
    if payload["receipt_algorithm"] != expected_algorithm:
        raise AllowlistGenerationError(
            "Helper runtime build manifest has wrong receipt algorithm"
        )
    components = payload["components"]
    if not isinstance(components, dict) or set(components) != set(RUNTIME_COMPONENTS):
        raise AllowlistGenerationError(
            "Helper runtime build manifest has wrong component set"
        )
    resources = _resources_root(app_root, platform)
    for name in RUNTIME_COMPONENTS:
        expected = _exact_keys(
            components[name], {"bytes", "files", "sha256"},
            f"Helper runtime component {name}",
        )
        if (
            type(expected["bytes"]) is not int
            or expected["bytes"] < 0
            or type(expected["files"]) is not int
            or expected["files"] < 0
            or not isinstance(expected["sha256"], str)
            or not SHA256_RE.fullmatch(expected["sha256"])
        ):
            raise AllowlistGenerationError(
                f"Helper runtime component {name} receipt is invalid"
            )
        component_root = resources / name
        if component_root.is_symlink():
            raise AllowlistGenerationError(
                f"Helper runtime component is a symlink: {name}"
            )
        try:
            if not component_root.is_dir():
                actual = helper_manifest.empty_directory_receipt()
            else:
                actual = helper_manifest.directory_receipt(
                    component_root,
                    normalize_windows_executables=platform == "windows-x64",
                )
        except helper_manifest.ManifestReceiptError as exc:
            raise AllowlistGenerationError(
                f"cannot verify Helper runtime component {name}: {exc}"
            ) from exc
        if actual != expected:
            raise AllowlistGenerationError(
                f"Helper runtime component {name} differs from its build manifest"
            )


def _validate_normalization(
    authenticated: AuthenticatedJson,
    app_root: Path,
    platform: str,
) -> dict[str, Any]:
    if platform not in {"mac-arm64", "mac-x64"}:
        raise AllowlistGenerationError(
            "PyInstaller normalization receipt is valid only for macOS"
        )
    try:
        payload = normalizer._validate_receipt_payload(
            authenticated.payload,
            authenticated.raw,
            _platform_target(platform)["arch"],
        )
    except normalizer.NormalizationError as exc:
        raise AllowlistGenerationError(
            f"invalid PyInstaller normalization receipt: {exc}"
        ) from exc
    embedded_relative = (
        "Contents/Resources/licenses/"
        + normalizer.RECEIPT_FILENAME
    )
    try:
        embedded = native._secure_read_relative_file(app_root, embedded_relative)
    except native.NativeMediaReceiptError as exc:
        raise AllowlistGenerationError(
            f"cannot authenticate embedded PyInstaller normalization receipt: {exc}"
        ) from exc
    if embedded != authenticated.raw:
        raise AllowlistGenerationError(
            "embedded PyInstaller normalization receipt differs from authenticated input"
        )
    try:
        verified = normalizer.verify_stage(
            _resources_root(app_root, platform),
            _platform_target(platform)["arch"],
        )
    except normalizer.NormalizationError as exc:
        raise AllowlistGenerationError(
            f"final PyInstaller runtime differs from normalization receipt: {exc}"
        ) from exc
    if verified != payload:
        raise AllowlistGenerationError(
            "verified PyInstaller normalization receipt changed during validation"
        )
    return payload


def _validate_source_manifest(
    authenticated: AuthenticatedJson,
) -> None:
    if authenticated.payload.get("schema") != SOURCE_BUNDLE_SCHEMA:
        raise AllowlistGenerationError("FFmpeg source manifest has wrong schema")
    try:
        source_bundle._validate_manifest(
            authenticated.payload, authenticated.raw
        )
    except source_bundle.SourceBundleError as exc:
        raise AllowlistGenerationError(
            f"invalid FFmpeg source manifest: {exc}"
        ) from exc


WINDOWS_FFMPEG_LINK_FILENAMES = {
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


def _raw_link_member_key(path: Any, expected_root: str, label: str) -> str:
    if not isinstance(path, str) or not path or path != path.strip():
        raise AllowlistGenerationError(f"{label} path is invalid")
    try:
        encoded = path.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise AllowlistGenerationError(f"{label} path is invalid") from exc
    if (
        len(encoded) > 4096
        or "\\" in path
        or any(unicodedata.category(character).startswith("C") for character in path)
        or unicodedata.normalize("NFC", path) != path
        or unicodedata.normalize("NFKC", path) != path
    ):
        raise AllowlistGenerationError(f"{label} path is invalid")
    raw_parts = path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise AllowlistGenerationError(f"{label} path is invalid")
    parsed = PurePosixPath(path)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or parsed.parts[0] != expected_root
        or tuple(parsed.parts) != tuple(raw_parts)
    ):
        raise AllowlistGenerationError(f"{label} path is invalid")
    return unicodedata.normalize("NFKC", path).casefold()


def _prevalidate_link_member_paths(payload: Mapping[str, Any]) -> None:
    try:
        programs = payload["link_evidence"]["programs"]
    except (KeyError, TypeError) as exc:
        raise AllowlistGenerationError(
            "Windows FFmpeg receipt lacks structured link evidence"
        ) from exc
    if not isinstance(programs, dict):
        raise AllowlistGenerationError(
            "Windows FFmpeg receipt link evidence programs must be an object"
        )
    for program in WINDOWS_FFMPEG_LINK_FILENAMES:
        try:
            members = programs[program]["reproducer"]["members"]
        except (KeyError, TypeError) as exc:
            raise AllowlistGenerationError(
                f"Windows FFmpeg {program} receipt lacks reproducer members"
            ) from exc
        if not isinstance(members, list) or not members:
            raise AllowlistGenerationError(
                f"Windows FFmpeg {program} reproducer members are empty"
            )
        expected_root = f"{program}-reproduce"
        logical_paths: set[str] = set()
        for index, member in enumerate(members):
            if not isinstance(member, dict) or "path" not in member:
                raise AllowlistGenerationError(
                    f"Windows FFmpeg {program} reproducer member {index} is invalid"
                )
            label = f"Windows FFmpeg {program} reproducer member {index}"
            logical = _raw_link_member_key(
                member["path"], expected_root, label
            )
            if logical in logical_paths:
                raise AllowlistGenerationError(
                    f"Windows FFmpeg {program} reproducer has a logical duplicate"
                )
            logical_paths.add(logical)


def _validate_windows_ffmpeg_build(
    authenticated: AuthenticatedJson,
    source_manifest: AuthenticatedJson,
    source_lock: AuthenticatedJson,
    capabilities: AuthenticatedJson,
    source_archive: AuthenticatedFile,
    *,
    app_root: Path,
    license_dir: Path,
    link_evidence_dir: Path,
    linkage_dir: Path,
    repository_commit: str,
) -> dict[str, Any]:
    _prevalidate_link_member_paths(authenticated.payload)
    verifier = windows_ffmpeg_verifier
    if verifier is None:
        detail = (
            f": {windows_ffmpeg_verifier_error}"
            if windows_ffmpeg_verifier_error is not None
            else ""
        )
        raise MissingProducerContractError(
            "exact shared verify_windows_ffmpeg.py v4 verifier is unavailable"
            + detail
        )
    required_api = (
        "RECEIPT_SCHEMA",
        "WindowsFFmpegError",
        "canonical_json",
        "create_receipt",
        "load_contracts",
        "load_receipt",
        "validate_receipt_against_contracts",
    )
    missing_api = [name for name in required_api if not hasattr(verifier, name)]
    if missing_api or verifier.RECEIPT_SCHEMA != WINDOWS_FFMPEG_BUILD_SCHEMA:
        raise MissingProducerContractError(
            "shared Windows FFmpeg verifier has an incompatible v4 API: "
            + ", ".join(missing_api or [str(verifier.RECEIPT_SCHEMA)])
        )
    try:
        pinned_source, pinned_capabilities = verifier.load_contracts(
            source_lock.path, capabilities.path
        )
        if (
            pinned_source.sha256 != source_lock.sha256
            or pinned_capabilities.sha256 != capabilities.sha256
        ):
            raise AllowlistGenerationError(
                "shared Windows FFmpeg contracts differ from authenticated inputs"
            )
        recorded = verifier.load_receipt(authenticated.path)
        if (
            recorded.canonical != authenticated.raw
            or recorded.sha256 != authenticated.sha256
        ):
            raise AllowlistGenerationError(
                "shared Windows FFmpeg receipt differs from authenticated input"
            )
        verifier.validate_receipt_against_contracts(
            recorded.parsed(), pinned_source, pinned_capabilities
        )
        recomputed = verifier.create_receipt(
            source_lock_path=source_lock.path,
            capabilities_path=capabilities.path,
            ffmpeg=app_root / "resources/bin/ffmpeg.exe",
            ffprobe=app_root / "resources/bin/ffprobe.exe",
            license_dir=license_dir,
            link_evidence_dir=link_evidence_dir,
            linkage_dir=linkage_dir,
            source_bundle=source_archive.path,
            source_manifest=source_manifest.path,
            repository_commit=repository_commit,
            repo_root=Path(__file__).resolve().parents[1],
        )
        recomputed_raw = verifier.canonical_json(recomputed)
    except AllowlistGenerationError:
        raise
    except Exception as exc:
        raise AllowlistGenerationError(
            f"shared Windows FFmpeg v4 verification failed: {exc}"
        ) from exc
    if recomputed_raw != authenticated.raw:
        raise AllowlistGenerationError(
            "Windows FFmpeg build receipt differs from the exact shared "
            "artifact verifier"
        )
    if recomputed.get("schema") != WINDOWS_FFMPEG_BUILD_SCHEMA:
        raise AllowlistGenerationError(
            "shared Windows FFmpeg verifier returned the wrong schema"
        )
    if recomputed.get("source", {}).get(
        "bundle_manifest_sha256"
    ) != source_manifest.sha256:
        raise AllowlistGenerationError(
            "Windows FFmpeg build receipt does not bind the authenticated "
            "source manifest"
        )
    if recomputed.get("link_evidence", {}).get(
        "closure_status"
    ) != "verified":
        raise AllowlistGenerationError(
            "Windows FFmpeg v4 link input closure is not verified for promotion"
        )
    return recomputed


def _embedded_receipt_matches(
    app_root: Path,
    relative: str,
    authenticated: AuthenticatedJson,
    label: str,
) -> None:
    try:
        embedded = native._secure_read_relative_file(app_root, relative)
    except native.NativeMediaReceiptError as exc:
        raise AllowlistGenerationError(
            f"cannot read embedded {label}: {exc}"
        ) from exc
    if embedded != authenticated.raw:
        raise AllowlistGenerationError(
            f"embedded {label} differs from authenticated input"
        )


MAC_HELPER_PRODUCT_NAME = "AutoEditor Helper"
MAC_ROOT_EXECUTABLE_NAME = "AutoEditor"
MAC_ELECTRON_SCAN_ROOTS = (
    "Contents/MacOS",
    (
        "Contents/Frameworks/Electron Framework.framework/Versions/A"
    ),
    "Contents/Frameworks/Mantle.framework/Versions/A",
    "Contents/Frameworks/ReactiveObjC.framework/Versions/A",
    "Contents/Frameworks/Squirrel.framework/Versions/A",
    (
        "Contents/Frameworks/AutoEditor Helper Helper.app/Contents/MacOS"
    ),
    (
        "Contents/Frameworks/AutoEditor Helper Helper (GPU).app/"
        "Contents/MacOS"
    ),
    (
        "Contents/Frameworks/AutoEditor Helper Helper (Plugin).app/"
        "Contents/MacOS"
    ),
    (
        "Contents/Frameworks/AutoEditor Helper Helper (Renderer).app/"
        "Contents/MacOS"
    ),
)
MAC_ELECTRON_NATIVE_PATHS = (
    f"Contents/MacOS/{MAC_ROOT_EXECUTABLE_NAME}",
    (
        "Contents/Frameworks/Electron Framework.framework/Versions/A/"
        "Electron Framework"
    ),
    (
        "Contents/Frameworks/Electron Framework.framework/Versions/A/"
        "Helpers/chrome_crashpad_handler"
    ),
    *(
        "Contents/Frameworks/Electron Framework.framework/Versions/A/"
        f"Libraries/{name}"
        for name in (
            "libEGL.dylib",
            "libGLESv2.dylib",
            "libffmpeg.dylib",
            "libvk_swiftshader.dylib",
        )
    ),
    "Contents/Frameworks/Mantle.framework/Versions/A/Mantle",
    (
        "Contents/Frameworks/ReactiveObjC.framework/Versions/A/ReactiveObjC"
    ),
    "Contents/Frameworks/Squirrel.framework/Versions/A/Squirrel",
    "Contents/Frameworks/Squirrel.framework/Versions/A/Resources/ShipIt",
    *(
        f"Contents/Frameworks/{MAC_HELPER_PRODUCT_NAME} Helper{suffix}.app/"
        f"Contents/MacOS/{MAC_HELPER_PRODUCT_NAME} Helper{suffix}"
        for suffix in ("", " (GPU)", " (Plugin)", " (Renderer)")
    ),
)
MAC_FRAMEWORK_LIBRARY_PATHS = frozenset({
    (
        "Contents/Frameworks/Electron Framework.framework/Versions/A/"
        "Electron Framework"
    ),
    "Contents/Frameworks/Mantle.framework/Versions/A/Mantle",
    (
        "Contents/Frameworks/ReactiveObjC.framework/Versions/A/ReactiveObjC"
    ),
    "Contents/Frameworks/Squirrel.framework/Versions/A/Squirrel",
})


def _scan_roots(platform: str) -> tuple[str, ...]:
    if platform == "windows-x64":
        return (".",)
    rules = native.PLATFORM_COMPONENT_RULES[platform]
    return tuple(sorted({
        "Contents/Resources/bin",
        "Contents/Resources/engine",
        "Contents/Resources/helper",
        "Contents/Resources/lib",
        *MAC_ELECTRON_SCAN_ROOTS,
        *rules["remotion"]["roots"],
        *rules["onnxruntime-node"]["roots"],
        *rules["browser"]["roots"],
    }))


def _validate_generator_scan_coverage(
    scan_roots: tuple[str, ...], platform: str
) -> None:
    native._validate_scan_coverage(scan_roots, platform)
    if platform == "windows-x64":
        return
    missing = [
        relative
        for relative in MAC_ELECTRON_NATIVE_PATHS
        if not any(
            native._root_covers_path(root, relative) for root in scan_roots
        )
    ]
    if missing:
        raise AllowlistGenerationError(
            "Mac scan roots do not cover the current Electron Builder native "
            "paths: " + ", ".join(missing)
        )


def _inventory_native_tree(
    app_root: Path,
    scan_roots: tuple[str, ...],
    platform: str,
) -> dict[str, Any]:
    original_roles = native._expected_binary_roles

    def exact_roles(relative: str, target: str) -> set[str]:
        if (
            target in {"mac-arm64", "mac-x64"}
            and relative in MAC_FRAMEWORK_LIBRARY_PATHS
        ):
            return {"library"}
        return original_roles(relative, target)

    native._expected_binary_roles = exact_roles
    try:
        observations = native._inventory_native_tree(
            app_root, scan_roots, platform
        )
    finally:
        native._expected_binary_roles = original_roles
    if platform in {"mac-arm64", "mac-x64"}:
        electron_paths = {
            relative
            for relative in observations
            if any(
                native._root_covers_path(root, relative)
                for root in MAC_ELECTRON_SCAN_ROOTS
            )
        }
        expected_paths = set(MAC_ELECTRON_NATIVE_PATHS)
        if electron_paths != expected_paths:
            missing = sorted(expected_paths - electron_paths)
            unexpected = sorted(electron_paths - expected_paths)
            details: list[str] = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unexpected:
                details.append("unexpected " + ", ".join(unexpected))
            raise AllowlistGenerationError(
                "Mac Electron native path set does not match the exact "
                "Electron Builder 26.15.3 contract: " + "; ".join(details)
            )
    return observations


def _unique_owner(
    relative: str,
    candidates: list[ProducerOwner],
) -> ProducerOwner:
    if not candidates:
        raise MissingProducerContractError(
            "no authenticated producer owns native path "
            f"{relative}; an exact final Electron app build manifest must "
            "enumerate each Electron Builder-created PE or Mach-O path with "
            "its final byte count and SHA256"
        )
    if len(candidates) != 1:
        producers = ", ".join(sorted(owner.producer for owner in candidates))
        raise AllowlistGenerationError(
            f"multiple authenticated producers own native path {relative}: "
            f"{producers}"
        )
    return candidates[0]


def _missing_inventory(relative: str, component: str) -> None:
    if component in {"electron", "supporting-native"}:
        raise MissingProducerContractError(
            "no authenticated producer owns native path "
            f"{relative}; an exact final Electron app build manifest must "
            "enumerate each Electron Builder-created PE or Mach-O path with "
            "its final byte count and SHA256"
        )
    if component == "browser":
        raise MissingProducerContractError(
            "native path lacks an authenticated per-path content claim: "
            f"{relative}; the Chrome extraction receipt must enumerate every "
            "final native path with its byte count and SHA256 and bind that "
            "inventory to the pinned Chrome/HyperFrames provenance"
        )
    if component in {"frozen-engine", "frozen-helper"}:
        raise MissingProducerContractError(
            "native path lacks an authenticated per-path content claim: "
            f"{relative}; the final frozen engine/helper manifest must "
            "enumerate every native path with its byte count and SHA256"
        )
    if component == "remotion":
        raise MissingProducerContractError(
            "native path lacks an authenticated per-path content claim: "
            f"{relative}; the canonical Remotion prune receipt must enumerate "
            "the complete final native inventory with per-path byte counts "
            "and SHA256 values"
        )
    raise MissingProducerContractError(
        "native path lacks an authenticated per-path content claim: "
        f"{relative} ({component})"
    )


def _component_owners(
    platform: str,
    *,
    onnx: AuthenticatedJson,
    electron: AuthenticatedJson,
    runtime: AuthenticatedJson,
    remotion: AuthenticatedJson | None,
    ffmpeg_source: AuthenticatedJson | None,
    normalization: AuthenticatedJson | None,
) -> dict[str, ProducerOwner]:
    contracts = native.PLATFORM_COMPONENT_RULES[platform]
    owners = {
        "onnxruntime-node": ProducerOwner(
            "onnxruntime-node",
            contracts["onnxruntime-node"]["lineage_id"],
            onnx.sha256,
            "ONNX Runtime v2 prune receipt",
        ),
        "browser": ProducerOwner(
            "browser",
            contracts["browser"]["lineage_id"],
            runtime.sha256,
            (
                "Helper runtime build manifest bound to the pinned "
                "Chrome/HyperFrames provenance receipt"
            ),
        ),
    }
    if platform == "windows-x64":
        if remotion is None or ffmpeg_source is None:
            raise AllowlistGenerationError(
                "Windows generation requires Remotion and FFmpeg producer receipts"
            )
        owners.update({
            "main-ffmpeg": ProducerOwner(
                "main-ffmpeg",
                contracts["main-ffmpeg"]["lineage_id"],
                ffmpeg_source.sha256,
                "Windows FFmpeg source-build receipt chain",
            ),
            "remotion": ProducerOwner(
                "remotion",
                contracts["remotion"]["lineage_id"],
                remotion.sha256,
                "Windows Remotion canonical prune receipt",
            ),
            "frozen-engine": ProducerOwner(
                "frozen-engine",
                contracts["frozen-engine"]["lineage_id"],
                runtime.sha256,
                "Helper runtime build manifest",
            ),
            "frozen-helper": ProducerOwner(
                "frozen-helper",
                contracts["frozen-helper"]["lineage_id"],
                runtime.sha256,
                "Helper runtime build manifest",
            ),
        })
    else:
        if normalization is None:
            raise AllowlistGenerationError(
                "macOS generation requires a PyInstaller normalization receipt"
            )
        owners.update({
            "frozen-engine": ProducerOwner(
                "frozen-engine",
                contracts["frozen-engine"]["lineage_id"],
                normalization.sha256,
                "PyInstaller normalization receipt",
            ),
            "frozen-helper": ProducerOwner(
                "frozen-helper",
                contracts["frozen-helper"]["lineage_id"],
                normalization.sha256,
                "PyInstaller normalization receipt",
            ),
        })
    return owners


def _require_pair(
    path: Path | None,
    digest: str | None,
    label: str,
) -> tuple[Path, str]:
    if path is None or digest is None:
        raise AllowlistGenerationError(
            f"{label} path and expected raw SHA256 are both required"
        )
    return path, digest


def _require_path(path: Path | None, label: str) -> Path:
    if path is None:
        raise AllowlistGenerationError(f"{label} is required")
    return path


def _require_text(value: str | None, label: str) -> str:
    if value is None or not value or value != value.strip():
        raise AllowlistGenerationError(f"{label} is required")
    return value


def _load_producers(
    app_root: Path,
    platform: str,
    inputs: GeneratorInputs,
) -> tuple[
    dict[str, ProducerOwner],
    dict[str, Any] | None,
    dict[str, ProducerClaim],
]:
    onnx = _read_authenticated_json(
        inputs.onnx_receipt,
        inputs.onnx_receipt_sha256,
        "ONNX Runtime v2 prune receipt",
    )
    try:
        native._validate_onnx_prune_receipt(
            onnx.raw, onnx.sha256, platform
        )
    except native.NativeMediaReceiptError as exc:
        raise AllowlistGenerationError(
            f"invalid ONNX Runtime v2 prune receipt: {exc}"
        ) from exc
    _embedded_receipt_matches(
        app_root,
        native._onnx_prune_receipt_path(platform),
        onnx,
        "ONNX Runtime v2 prune receipt",
    )

    electron = _read_authenticated_json(
        inputs.electron_chromium_receipt,
        inputs.electron_chromium_receipt_sha256,
        "Electron and Chromium provenance receipt",
    )
    _validate_electron_chromium(electron, platform)
    _embedded_receipt_matches(
        app_root,
        (
            "resources/licenses/ELECTRON_CHROMIUM_PROVENANCE.json"
            if platform == "windows-x64"
            else "Contents/Resources/licenses/ELECTRON_CHROMIUM_PROVENANCE.json"
        ),
        electron,
        "Electron and Chromium provenance receipt",
    )

    creative = _read_authenticated_json(
        inputs.creative_runtime_lock,
        inputs.creative_runtime_lock_sha256,
        "creative runtime package lock",
    )
    _validate_creative_runtime_lock(creative, platform)
    _embedded_receipt_matches(
        app_root,
        (
            "resources/licenses/creative-runtime-package-lock.json"
            if platform == "windows-x64"
            else "Contents/Resources/licenses/creative-runtime-package-lock.json"
        ),
        creative,
        "creative runtime package lock",
    )

    runtime = _read_authenticated_json(
        inputs.runtime_build_manifest,
        inputs.runtime_build_manifest_sha256,
        "Helper runtime build manifest",
    )
    _validate_runtime_build_manifest(runtime, app_root, platform)
    _embedded_receipt_matches(
        app_root,
        (
            "resources/runtime-manifest.json"
            if platform == "windows-x64"
            else "Contents/Resources/runtime-manifest.json"
        ),
        runtime,
        "Helper runtime build manifest",
    )

    if platform != "windows-x64":
        normalization_path, normalization_sha = _require_pair(
            inputs.mac_normalization_receipt,
            inputs.mac_normalization_receipt_sha256,
            "Mac PyInstaller normalization receipt",
        )
        normalization = _read_authenticated_json(
            normalization_path,
            normalization_sha,
            "Mac PyInstaller normalization receipt",
        )
        _validate_normalization(normalization, app_root, platform)
        raise MissingProducerContractError(
            "macOS native allowlist generation is closed until three exact "
            "producer contracts exist: (1) a Mac FFmpeg bundle receipt that "
            "enumerates every final Contents/Resources/bin and lib Mach-O "
            "with byte count and SHA256, (2) a canonical Mac Remotion "
            "post-install receipt that binds the complete target compositor "
            "inventory, and (3) a final Electron app build manifest that "
            "enumerates every Electron Builder-created Mach-O outside the "
            "staged Resources tree"
        )

    remotion_path, remotion_sha = _require_pair(
        inputs.remotion_receipt,
        inputs.remotion_receipt_sha256,
        "Windows Remotion prune receipt",
    )
    remotion = _read_authenticated_json(
        remotion_path, remotion_sha, "Windows Remotion prune receipt"
    )
    try:
        native._validate_remotion_prune_receipt(
            remotion.raw, remotion.sha256
        )
    except native.NativeMediaReceiptError as exc:
        raise AllowlistGenerationError(
            f"invalid Windows Remotion prune receipt: {exc}"
        ) from exc
    _embedded_receipt_matches(
        app_root,
        native.REMOTION_PRUNE_RECEIPT_PATH,
        remotion,
        "Windows Remotion prune receipt",
    )

    source_path, source_sha = _require_pair(
        inputs.windows_ffmpeg_source_manifest,
        inputs.windows_ffmpeg_source_manifest_sha256,
        "Windows FFmpeg source manifest",
    )
    source = _read_authenticated_json(
        source_path, source_sha, "Windows FFmpeg source manifest"
    )
    _validate_source_manifest(source)
    source_lock_path, source_lock_sha = _require_pair(
        inputs.windows_ffmpeg_source_lock,
        inputs.windows_ffmpeg_source_lock_sha256,
        "Windows FFmpeg source lock",
    )
    source_lock = _read_authenticated_json(
        source_lock_path, source_lock_sha, "Windows FFmpeg source lock"
    )
    capabilities_path, capabilities_sha = _require_pair(
        inputs.windows_ffmpeg_capabilities,
        inputs.windows_ffmpeg_capabilities_sha256,
        "Windows FFmpeg capability contract",
    )
    capabilities = _read_authenticated_json(
        capabilities_path,
        capabilities_sha,
        "Windows FFmpeg capability contract",
    )
    source_bundle_path, source_bundle_sha = _require_pair(
        inputs.windows_ffmpeg_source_bundle,
        inputs.windows_ffmpeg_source_bundle_sha256,
        "Windows FFmpeg corresponding-source bundle",
    )
    source_archive = _authenticate_regular_file(
        source_bundle_path,
        source_bundle_sha,
        "Windows FFmpeg corresponding-source bundle",
    )
    build_path, build_sha = _require_pair(
        inputs.windows_ffmpeg_build_receipt,
        inputs.windows_ffmpeg_build_receipt_sha256,
        "Windows FFmpeg build receipt",
    )
    build = _read_authenticated_json(
        build_path, build_sha, "Windows FFmpeg build receipt"
    )
    build_payload = _validate_windows_ffmpeg_build(
        build,
        source,
        source_lock,
        capabilities,
        source_archive,
        app_root=app_root,
        license_dir=_require_path(
            inputs.windows_ffmpeg_license_dir,
            "Windows FFmpeg runtime license directory",
        ),
        link_evidence_dir=_require_path(
            inputs.windows_ffmpeg_link_evidence_dir,
            "Windows FFmpeg link evidence directory",
        ),
        linkage_dir=_require_path(
            inputs.windows_ffmpeg_linkage_dir,
            "Windows FFmpeg linkage directory",
        ),
        repository_commit=_require_text(
            inputs.windows_ffmpeg_repository_commit,
            "Windows FFmpeg repository commit",
        ),
    )
    owners = _component_owners(
        platform,
        onnx=onnx,
        electron=electron,
        runtime=runtime,
        remotion=remotion,
        ffmpeg_source=source,
        normalization=None,
    )
    claims: dict[str, ProducerClaim] = {}
    onnx_root = native._onnx_package_root(platform)
    onnx_owner = owners["onnxruntime-node"]
    for relative, digest in native._expected_onnx_target_inventory(
        platform
    ).items():
        app_relative = f"{onnx_root}/bin/napi-v3/{relative}"
        claims[app_relative] = ProducerClaim(onnx_owner, digest, None)
    ffmpeg_owner = owners["main-ffmpeg"]
    for name in ("ffmpeg", "ffprobe"):
        output = build_payload["outputs"][name]
        claims[f"resources/bin/{name}.exe"] = ProducerClaim(
            ffmpeg_owner, output["sha256"], output["bytes"]
        )
    return owners, build_payload, claims


def _applicable_claims(
    claims: Mapping[str, ProducerClaim], platform: str
) -> dict[str, ProducerClaim]:
    roots = _scan_roots(platform)
    applicable: dict[str, ProducerClaim] = {}
    outside: list[str] = []
    try:
        native._assert_no_path_collisions(list(claims), "producer claim")
        for raw_path, claim in claims.items():
            relative = native._safe_relative_path(raw_path)
            if relative != raw_path:
                raise AllowlistGenerationError(
                    f"producer claim path is not canonical: {raw_path}"
                )
            if not any(
                native._root_covers_path(root, relative) for root in roots
            ):
                outside.append(relative)
                continue
            if not isinstance(claim, ProducerClaim):
                raise AllowlistGenerationError(
                    f"producer claim has an invalid record: {relative}"
                )
            _sha256(claim.sha256, f"producer claim {relative}")
            if claim.byte_count is not None and (
                type(claim.byte_count) is not int or claim.byte_count <= 0
            ):
                raise AllowlistGenerationError(
                    f"producer claim has an invalid byte count: {relative}"
                )
            applicable[relative] = claim
    except native.NativeMediaReceiptError as exc:
        raise AllowlistGenerationError(
            f"invalid authenticated producer claim set: {exc}"
        ) from exc
    if outside:
        raise AllowlistGenerationError(
            "authenticated native producer claims are outside the configured "
            "final scan roots: " + ", ".join(sorted(outside))
        )
    return applicable


def _validate_observations(
    observations: Mapping[str, Any],
    platform: str,
    owners: Mapping[str, ProducerOwner],
    claims: Mapping[str, ProducerClaim],
    ffmpeg_build: dict[str, Any] | None,
) -> dict[str, dict[str, str]]:
    native._validate_onnx_observed(observations, platform)
    applicable_claims = _applicable_claims(claims, platform)
    observed_paths = set(observations)
    claimed_paths = set(applicable_claims)
    unclaimed = sorted(observed_paths - claimed_paths)
    if unclaimed:
        relative = unclaimed[0]
        _missing_inventory(
            relative, native._component_for_path(relative, platform)
        )
    unobserved = sorted(claimed_paths - observed_paths)
    if unobserved:
        raise AllowlistGenerationError(
            "authenticated producer claim paths are missing from the final "
            "native scan: " + ", ".join(unobserved)
        )
    files: dict[str, dict[str, str]] = {}
    for relative in sorted(observations):
        component = native._component_for_path(relative, platform)
        candidates = []
        owner = owners.get(component)
        if owner is not None:
            candidates.append(owner)
        selected = _unique_owner(relative, candidates)
        claim = applicable_claims[relative]
        if claim.owner != selected:
            raise AllowlistGenerationError(
                "authenticated per-path claim has the wrong producer owner: "
                f"{relative}"
            )
        observed = observations[relative]
        if (
            observed.sha256 != claim.sha256
            or (
                claim.byte_count is not None
                and observed.byte_count != claim.byte_count
            )
        ):
            raise AllowlistGenerationError(
                "final native bytes differ from the authenticated per-path "
                f"producer inventory: {relative}"
            )
        files[relative] = {
            "component": selected.component,
            "lineage_id": selected.lineage_id,
            "source_manifest_sha256": selected.source_manifest_sha256,
        }

    native._validate_required_components(files, "generated allowlist")
    native._validate_component_contracts(files, platform, "generated allowlist")
    if platform == "windows-x64":
        if ffmpeg_build is None:
            raise AllowlistGenerationError("Windows FFmpeg build receipt is absent")
        outputs = ffmpeg_build["outputs"]
        for name, relative in (
            ("ffmpeg", "resources/bin/ffmpeg.exe"),
            ("ffprobe", "resources/bin/ffprobe.exe"),
        ):
            observed = observations.get(relative)
            if observed is None:
                raise AllowlistGenerationError(
                    f"Windows FFmpeg output is missing from final app: {relative}"
                )
            expected = outputs[name]
            if (
                observed.byte_count != expected["bytes"]
                or observed.sha256 != expected["sha256"]
            ):
                raise AllowlistGenerationError(
                    f"final Windows FFmpeg bytes differ from build receipt: {relative}"
                )
    return files


def generate_allowlist(
    app_root: Path,
    platform: str,
    inputs: GeneratorInputs,
) -> tuple[dict[str, Any], str]:
    native._platform_rule(platform)
    roots = _scan_roots(platform)
    _validate_generator_scan_coverage(roots, platform)
    owners, ffmpeg_build, claims = _load_producers(
        app_root, platform, inputs
    )
    try:
        first = _inventory_native_tree(app_root, roots, platform)
        second = _inventory_native_tree(app_root, roots, platform)
    except native.NativeMediaReceiptError as exc:
        raise AllowlistGenerationError(
            f"cannot discover final native media paths: {exc}"
        ) from exc
    if first != second:
        raise AllowlistGenerationError(
            "final native media tree changed while generating the allowlist"
        )
    owners_after, ffmpeg_build_after, claims_after = _load_producers(
        app_root, platform, inputs
    )
    if (
        owners_after != owners
        or ffmpeg_build_after != ffmpeg_build
        or claims_after != claims
    ):
        raise AllowlistGenerationError(
            "authenticated producer bindings changed while generating the "
            "allowlist"
        )
    files = _validate_observations(
        first, platform, owners, claims, ffmpeg_build
    )
    payload = {
        "files": files,
        "platform": platform,
        "scan_roots": list(roots),
        "schema": native.ALLOWLIST_SCHEMA,
    }
    raw = canonical_json_bytes(payload)
    return payload, hashlib.sha256(raw).hexdigest()


def _write_new(path: Path, raw: bytes, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(
            os, "O_CLOEXEC", 0
        )
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o644)
        created = True
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise AllowlistGenerationError(f"short write for {label}")
            view = view[written:]
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != len(raw)
        ):
            raise AllowlistGenerationError(f"invalid written {label}")
    except AllowlistGenerationError:
        raise
    except OSError as exc:
        raise AllowlistGenerationError(f"cannot write {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created and sys.exc_info()[0] is not None:
            try:
                path.unlink()
            except OSError:
                pass


def write_allowlist(
    output: Path,
    payload: dict[str, Any],
    expected_sha256: str,
) -> None:
    raw = canonical_json_bytes(payload)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != _sha256(expected_sha256, "generated allowlist"):
        raise AllowlistGenerationError("generated allowlist SHA256 drifted")
    _write_new(output, raw, "native media allowlist")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument(
        "--platform", choices=sorted(native.PLATFORM_RULES), required=True
    )
    parser.add_argument("--onnx-receipt", type=Path, required=True)
    parser.add_argument("--onnx-receipt-sha256", required=True)
    parser.add_argument(
        "--electron-chromium-receipt", type=Path, required=True
    )
    parser.add_argument("--electron-chromium-receipt-sha256", required=True)
    parser.add_argument("--creative-runtime-lock", type=Path, required=True)
    parser.add_argument("--creative-runtime-lock-sha256", required=True)
    parser.add_argument("--runtime-build-manifest", type=Path, required=True)
    parser.add_argument("--runtime-build-manifest-sha256", required=True)
    parser.add_argument("--remotion-receipt", type=Path)
    parser.add_argument("--remotion-receipt-sha256")
    parser.add_argument("--windows-ffmpeg-build-receipt", type=Path)
    parser.add_argument("--windows-ffmpeg-build-receipt-sha256")
    parser.add_argument("--windows-ffmpeg-source-manifest", type=Path)
    parser.add_argument("--windows-ffmpeg-source-manifest-sha256")
    parser.add_argument("--windows-ffmpeg-source-lock", type=Path)
    parser.add_argument("--windows-ffmpeg-source-lock-sha256")
    parser.add_argument("--windows-ffmpeg-capabilities", type=Path)
    parser.add_argument("--windows-ffmpeg-capabilities-sha256")
    parser.add_argument("--windows-ffmpeg-source-bundle", type=Path)
    parser.add_argument("--windows-ffmpeg-source-bundle-sha256")
    parser.add_argument("--windows-ffmpeg-license-dir", type=Path)
    parser.add_argument("--windows-ffmpeg-link-evidence-dir", type=Path)
    parser.add_argument("--windows-ffmpeg-linkage-dir", type=Path)
    parser.add_argument("--windows-ffmpeg-repository-commit")
    parser.add_argument("--mac-normalization-receipt", type=Path)
    parser.add_argument("--mac-normalization-receipt-sha256")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    inputs = GeneratorInputs(
        onnx_receipt=args.onnx_receipt,
        onnx_receipt_sha256=args.onnx_receipt_sha256,
        electron_chromium_receipt=args.electron_chromium_receipt,
        electron_chromium_receipt_sha256=(
            args.electron_chromium_receipt_sha256
        ),
        creative_runtime_lock=args.creative_runtime_lock,
        creative_runtime_lock_sha256=args.creative_runtime_lock_sha256,
        runtime_build_manifest=args.runtime_build_manifest,
        runtime_build_manifest_sha256=args.runtime_build_manifest_sha256,
        remotion_receipt=args.remotion_receipt,
        remotion_receipt_sha256=args.remotion_receipt_sha256,
        windows_ffmpeg_build_receipt=args.windows_ffmpeg_build_receipt,
        windows_ffmpeg_build_receipt_sha256=(
            args.windows_ffmpeg_build_receipt_sha256
        ),
        windows_ffmpeg_source_manifest=args.windows_ffmpeg_source_manifest,
        windows_ffmpeg_source_manifest_sha256=(
            args.windows_ffmpeg_source_manifest_sha256
        ),
        windows_ffmpeg_source_lock=args.windows_ffmpeg_source_lock,
        windows_ffmpeg_source_lock_sha256=(
            args.windows_ffmpeg_source_lock_sha256
        ),
        windows_ffmpeg_capabilities=args.windows_ffmpeg_capabilities,
        windows_ffmpeg_capabilities_sha256=(
            args.windows_ffmpeg_capabilities_sha256
        ),
        windows_ffmpeg_source_bundle=args.windows_ffmpeg_source_bundle,
        windows_ffmpeg_source_bundle_sha256=(
            args.windows_ffmpeg_source_bundle_sha256
        ),
        windows_ffmpeg_license_dir=args.windows_ffmpeg_license_dir,
        windows_ffmpeg_link_evidence_dir=(
            args.windows_ffmpeg_link_evidence_dir
        ),
        windows_ffmpeg_linkage_dir=args.windows_ffmpeg_linkage_dir,
        windows_ffmpeg_repository_commit=(
            args.windows_ffmpeg_repository_commit
        ),
        mac_normalization_receipt=args.mac_normalization_receipt,
        mac_normalization_receipt_sha256=(
            args.mac_normalization_receipt_sha256
        ),
    )
    try:
        payload, digest = generate_allowlist(
            args.app_root, args.platform, inputs
        )
        write_allowlist(args.output, payload, digest)
    except AllowlistGenerationError as exc:
        raise SystemExit(str(exc)) from exc
    print(digest)


if __name__ == "__main__":
    main()
