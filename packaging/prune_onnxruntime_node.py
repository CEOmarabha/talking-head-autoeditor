#!/usr/bin/env python3
"""Keep only the audited target ONNX Runtime native payload.

The creative Node runtime is installed from one cross-platform npm package.
Shipping every architecture is unnecessary and caused the Windows NSIS
extractor to silently omit five ARM64 files. This gate recognizes the exact
1.21.1 package, builds a separate target-only replacement, validates it, and
commits the package plus receipt as one rollback-safe directory swap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence


PACKAGE_NAME = "onnxruntime-node"
PACKAGE_VERSION = "1.21.1"
PACKAGE_RELATIVE_ROOT = Path(
    "creative-runtime/node_modules/onnxruntime-node"
)
NATIVE_RELATIVE_ROOT = Path("bin/napi-v3")
LOCK_PACKAGE_KEY = "node_modules/onnxruntime-node"
RECEIPT_RELATIVE_PATH = Path("ONNXRUNTIME_NODE_TARGET_PRUNE.json")

EXPECTED_LOCK_ENTRY = {
    "dependencies": {
        "global-agent": "^3.0.0",
        "onnxruntime-common": "1.21.1",
        "tar": "^7.0.1",
    },
    "hasInstallScript": True,
    "integrity": (
        "sha512-YThL/YYeGAeytecOvRcTKUORTIE2f8/iSo/JZgHFawWrV4zOY7fWLEaNuscg"
        "jmY5C5/VE/Wr7tm+ucSsc/AysQ=="
    ),
    "license": "MIT",
    "os": ["win32", "darwin", "linux"],
    "resolved": (
        "https://registry.npmjs.org/onnxruntime-node/-/"
        "onnxruntime-node-1.21.1.tgz"
    ),
    "version": PACKAGE_VERSION,
}

EXPECTED_PACKAGE_FIELDS = {
    "name": PACKAGE_NAME,
    "version": PACKAGE_VERSION,
    "license": "MIT",
    "os": ["win32", "darwin", "linux"],
}

EXPECTED_NATIVE_INVENTORY = {
    "darwin/arm64/libonnxruntime.1.21.1.dylib": (
        "2ea5e7f4202bfa9e0cfe4822576d8a7bb71e430a57c84decb7c4830dea4337ef"
    ),
    "darwin/arm64/onnxruntime_binding.node": (
        "d748eb499784a400e4c4ee5932e61a79d5cbb6fde26382fe3fb62aeeda3a9dd4"
    ),
    "darwin/x64/libonnxruntime.1.21.1.dylib": (
        "f5044fa26473f312af7222b9c85410a72488848b3667b1cfaf8f92d271a81990"
    ),
    "darwin/x64/onnxruntime_binding.node": (
        "f1263de9f95174584f0f035adbe530790d7914f81a06e50f3494e70c344c34b4"
    ),
    "linux/arm64/libonnxruntime.so.1": (
        "2dba27b484f8171f9fd39182230b4ace5f85401114d65a53c767ee924284806b"
    ),
    "linux/arm64/libonnxruntime.so.1.21.1": (
        "2dba27b484f8171f9fd39182230b4ace5f85401114d65a53c767ee924284806b"
    ),
    "linux/arm64/onnxruntime_binding.node": (
        "c1af123e973aa95b71df207e79a0ce63def9b2b8a0e6f384a8c4455c64d5b1a8"
    ),
    "linux/x64/libonnxruntime.so.1": (
        "3d03e6de8f828ae7432e67764ab4c02d4c9d4804db1b46ad60484c46188bb144"
    ),
    "linux/x64/libonnxruntime.so.1.21.1": (
        "3d03e6de8f828ae7432e67764ab4c02d4c9d4804db1b46ad60484c46188bb144"
    ),
    "linux/x64/libonnxruntime_providers_shared.so": (
        "950dbbe7c7a6f73b7f574c0e2308417e1e90e1f73b6472d799e25b47c6fdee82"
    ),
    "linux/x64/onnxruntime_binding.node": (
        "61278544b4668a50a481b8a451cbd8f7627e2006b2b54cd9a96438dff24b67da"
    ),
    "win32/arm64/DirectML.dll": (
        "77b0db83ff903f2323f5caf538499d75af6038bbea23b7959f7d232d9a4ab9d4"
    ),
    "win32/arm64/onnxruntime.dll": (
        "705d445a93d59db8f3ac540e9c94d9498a7399bca90047fc9ca18cc87f6c0af2"
    ),
    "win32/arm64/onnxruntime_binding.node": (
        "401a1a66a9f01237c7b60340554ed3e65a8cd88402f72260fa0c14d348491de9"
    ),
    "win32/x64/DirectML.dll": (
        "9c9e6d822561c6c41b90e6994b3e8857cf1d66dbfb1e0c4c799c7c89b4e92da1"
    ),
    "win32/x64/onnxruntime.dll": (
        "253cdf35f87692394205b01d8b6430f7926479bde557200f98d08193e8160a82"
    ),
    "win32/x64/onnxruntime_binding.node": (
        "9f3026a462fb77d9f5866680209dd683ee51f6fbf8967da7770e154c395f73ef"
    ),
}

EXPECTED_NON_NATIVE_INVENTORY = {
    "README.md": (
        "af669632f39c72a94af7a2458008431eded908e387fbe2e68bbc017c7fd882ad"
    ),
    "dist/backend.d.ts": (
        "23e65ad2c30827e0f2bfe2aadc2987b76d4619ae5e25aad36674ce618ed3df6d"
    ),
    "dist/backend.js": (
        "35e464b195c0e9d32c6c789664f83e6104b2eacb19cbe342c7fa7da0b163db41"
    ),
    "dist/backend.js.map": (
        "b9b11e5c46b363dc59f2a92f66df149f35f037cc02b8e185744ae518f3bf48cc"
    ),
    "dist/binding.d.ts": (
        "8fe5ebfaa425be61ef36bb81e98dec3edfa2ce0b2f6f4abb307d6d6fe488ea3e"
    ),
    "dist/binding.js": (
        "266a182fa5802f8f76c93979663eb572e0164577f4f59bd70bbb92c4accb83aa"
    ),
    "dist/binding.js.map": (
        "14b26a6f25aad873ea2fdd65b835fc08339dc3b075a700db53ae10b2e057337b"
    ),
    "dist/index.d.ts": (
        "d2498ae6d465fecfa80a535e99ad9bbabcfafac73f6b420f29651ec9d50b98fa"
    ),
    "dist/index.js": (
        "019eb02133b94b1f7fdf2d89eb93b590ce1288d271f7b280647fb3978e6391fa"
    ),
    "dist/index.js.map": (
        "73f55f1aa74f8179fa8891e532eb543b556726c3c90a4c2a3abb0b50af9919f0"
    ),
    "dist/version.d.ts": (
        "41559ce4d89dfbedc1be80155877382b0e0ddc8b717715d2d35c5ab38f2fc8f1"
    ),
    "dist/version.js": (
        "a289425452989ce1922578e4d54fbaff2dca6f48a98368c59b7eea3ea9cf605c"
    ),
    "dist/version.js.map": (
        "dc33a306cd858dd8d4b11566d33c13db607eaa2587ed6f7c06809513f3dab50e"
    ),
    "lib/backend.ts": (
        "ba13f22bb188b8ff2665136f40bc946906eff6dee9f4cf630cd393a68e6d9a04"
    ),
    "lib/binding.ts": (
        "7fc011e9e0a30aa5d3ba7faece8e16604eca7da9666c00d51b857a68907de398"
    ),
    "lib/index.ts": (
        "1e68f9c33ff0c9759b50f9c9d43a87665f8b47a6f9d74b2b3d6e4fbccbd26e48"
    ),
    "lib/version.ts": (
        "7af4f40988b2cb966449221a257b1138eacb603564a340b14039d0d45c03b6cb"
    ),
    "package.json": (
        "eced9c8f8f02b855d2c2b8fa60982c0d67c5d90b141505d1c0b92a8aa09e37d9"
    ),
    "script/build.js": (
        "72b38dfb3da5a091db3ac33cdfa67cb9872d7fcf293fb10cae6c287d5727341a"
    ),
    "script/build.ts": (
        "aa02bf6d0afabdb7230a40fb3101b13b263210dd4684741f9fdcc7d96ac74f5e"
    ),
    "script/install.js": (
        "987860df3f7ef9ad76d94fdb32590fd18de56da6d1b980a99965df5a0507b09d"
    ),
    "script/prepack.js": (
        "ffe3017a9df3bf21f45d70e7610aae7b9423b2b86889acff6afbee50d5c07295"
    ),
    "script/prepack.ts": (
        "ff251557aaffa1fac06b63172178c260aaff0c358905a4117a4d05a36f5b20d4"
    ),
}

EXPECTED_PACKAGE_INVENTORY = {
    **EXPECTED_NON_NATIVE_INVENTORY,
    **{
        f"{NATIVE_RELATIVE_ROOT.as_posix()}/{relative}": digest
        for relative, digest in EXPECTED_NATIVE_INVENTORY.items()
    },
}

TARGET_DIRECTORIES = {
    ("mac", "arm64"): "darwin/arm64",
    ("mac", "x64"): "darwin/x64",
    ("windows", "x64"): "win32/x64",
}


class GateError(RuntimeError):
    """The staged package does not match the audited pruning policy."""


@dataclass(frozen=True)
class Policy:
    package_name: str
    package_version: str
    package_relative_root: Path
    native_relative_root: Path
    lock_package_key: str
    lock_entry: Mapping[str, object]
    package_fields: Mapping[str, object]
    inventory: Mapping[str, str]
    package_inventory: Mapping[str, str]
    targets: Mapping[tuple[str, str], str]


PRODUCTION_POLICY = Policy(
    package_name=PACKAGE_NAME,
    package_version=PACKAGE_VERSION,
    package_relative_root=PACKAGE_RELATIVE_ROOT,
    native_relative_root=NATIVE_RELATIVE_ROOT,
    lock_package_key=LOCK_PACKAGE_KEY,
    lock_entry=EXPECTED_LOCK_ENTRY,
    package_fields=EXPECTED_PACKAGE_FIELDS,
    inventory=EXPECTED_NATIVE_INVENTORY,
    package_inventory=EXPECTED_PACKAGE_INVENTORY,
    targets=TARGET_DIRECTORIES,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GateError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read {label}: {path}: {exc}") from exc


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


def _require_plain_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise GateError(f"{label} is unavailable: {path}: {exc}") from exc
    if path.is_symlink() or _is_junction(path) or not stat.S_ISDIR(metadata.st_mode):
        raise GateError(f"{label} must be a plain directory: {path}")
    return path.resolve(strict=True)


def _reject_linked_ancestors(stage_root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(stage_root)
    except ValueError as exc:
        raise GateError("ONNX Runtime package escaped the staging root") from exc
    current = stage_root
    for component in relative.parts:
        current = current / component
        if current.is_symlink() or _is_junction(current):
            raise GateError(f"ONNX Runtime path contains a link: {current}")


def _expected_directories(files: Mapping[str, str]) -> set[str]:
    directories: set[str] = set()
    for relative in files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _inventory(root: Path) -> tuple[dict[str, str], set[str]]:
    files: dict[str, str] = {}
    directories: set[str] = set()
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directory_names:
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            metadata = candidate.lstat()
            if (
                candidate.is_symlink()
                or _is_junction(candidate)
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                raise GateError(f"native inventory contains linked directory: {relative}")
            directories.add(relative)
        for name in file_names:
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            metadata = candidate.lstat()
            if (
                candidate.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
            ):
                raise GateError(f"native inventory contains linked file: {relative}")
            files[relative] = _sha256(candidate)
    return files, directories


def _compare_inventory(
    observed_files: Mapping[str, str],
    observed_directories: set[str],
    expected_files: Mapping[str, str],
    label: str,
) -> None:
    expected_names = set(expected_files)
    observed_names = set(observed_files)
    missing = sorted(expected_names - observed_names)
    unexpected = sorted(observed_names - expected_names)
    changed = sorted(
        name
        for name in expected_names & observed_names
        if expected_files[name] != observed_files[name]
    )
    expected_directories = _expected_directories(expected_files)
    missing_directories = sorted(expected_directories - observed_directories)
    unexpected_directories = sorted(observed_directories - expected_directories)
    if missing or unexpected or changed or missing_directories or unexpected_directories:
        details = []
        for name, values in (
            ("missing", missing),
            ("unexpected", unexpected),
            ("changed", changed),
            ("missing-directories", missing_directories),
            ("unexpected-directories", unexpected_directories),
        ):
            if values:
                details.append(name + "=" + ",".join(values))
        raise GateError(f"{label} inventory drift: " + "; ".join(details))


def _verify_lock(lock_path: Path, policy: Policy) -> None:
    document = _load_json(lock_path, "creative runtime lock")
    if not isinstance(document, dict):
        raise GateError("creative runtime lock must be an object")
    packages = document.get("packages")
    if not isinstance(packages, dict):
        raise GateError("creative runtime lock has no packages object")
    if packages.get(policy.lock_package_key) != policy.lock_entry:
        raise GateError("onnxruntime-node npm lock entry drift")


def _verify_package_metadata(package_root: Path, policy: Policy) -> None:
    document = _load_json(package_root / "package.json", "onnxruntime-node metadata")
    if not isinstance(document, dict):
        raise GateError("onnxruntime-node metadata must be an object")
    actual = {name: document.get(name) for name in policy.package_fields}
    if actual != policy.package_fields:
        raise GateError("onnxruntime-node package metadata drift")


def _inventory_digest(inventory: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_digest in sorted(inventory.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_digest))
    return digest.hexdigest()


def _target_package_inventory(
    policy: Policy,
    expected_native: Mapping[str, str],
) -> dict[str, str]:
    native_prefix = policy.native_relative_root.as_posix() + "/"
    target = {
        relative: digest
        for relative, digest in policy.package_inventory.items()
        if not relative.startswith(native_prefix)
    }
    target.update(
        {
            native_prefix + relative: digest
            for relative, digest in expected_native.items()
        }
    )
    return target


def _copy_target_package(
    source: Path,
    destination: Path,
    native_relative_root: Path,
    keep_directory: str,
) -> None:
    native_parts = PurePosixPath(native_relative_root.as_posix()).parts
    keep_parts = PurePosixPath(keep_directory).parts
    if len(keep_parts) != 2:
        raise GateError("target ONNX Runtime directory must have two components")

    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory)
        relative = current.relative_to(source)
        parts = PurePosixPath(relative.as_posix()).parts
        if parts == native_parts:
            return set(names) - {keep_parts[0]}
        if parts == native_parts + (keep_parts[0],):
            return set(names) - {keep_parts[1]}
        return set()

    try:
        shutil.copytree(
            source,
            destination,
            symlinks=True,
            copy_function=shutil.copy2,
            ignore=ignore,
        )
    except OSError as exc:
        raise GateError(f"cannot build target-only ONNX Runtime package: {exc}") from exc


def _directory_identity(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    if path.is_symlink() or _is_junction(path) or not stat.S_ISDIR(metadata.st_mode):
        raise GateError(f"transaction directory drifted: {path}")
    return metadata.st_dev, metadata.st_ino


class _DirectoryRenamer:
    def __init__(self, package_parent: Path, transaction: Path):
        self.package_parent = package_parent
        self.transaction = transaction
        self.package_identity = _directory_identity(package_parent)
        self.transaction_identity = _directory_identity(transaction)
        self.package_fd: int | None = None
        self.transaction_fd: int | None = None
        if os.rename in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                self.package_fd = os.open(package_parent, flags)
                self.transaction_fd = os.open(transaction, flags)
            except OSError:
                self.close()
                raise

    def close(self) -> None:
        for descriptor in (self.package_fd, self.transaction_fd):
            if descriptor is not None:
                os.close(descriptor)
        self.package_fd = None
        self.transaction_fd = None

    def _verify_fallback_parents(self) -> None:
        if _directory_identity(self.package_parent) != self.package_identity:
            raise GateError("ONNX Runtime package parent raced")
        if _directory_identity(self.transaction) != self.transaction_identity:
            raise GateError("ONNX Runtime transaction directory raced")

    def to_transaction(self, source_name: str, destination_name: str) -> None:
        if self.package_fd is not None and self.transaction_fd is not None:
            os.rename(
                source_name,
                destination_name,
                src_dir_fd=self.package_fd,
                dst_dir_fd=self.transaction_fd,
            )
            return
        self._verify_fallback_parents()
        os.rename(
            self.package_parent / source_name,
            self.transaction / destination_name,
        )

    def to_package(self, source_name: str, destination_name: str) -> None:
        if self.package_fd is not None and self.transaction_fd is not None:
            os.rename(
                source_name,
                destination_name,
                src_dir_fd=self.transaction_fd,
                dst_dir_fd=self.package_fd,
            )
            return
        self._verify_fallback_parents()
        os.rename(
            self.transaction / source_name,
            self.package_parent / destination_name,
        )


def _write_receipt(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise GateError(f"cannot write ONNX Runtime pruning receipt: {exc}") from exc


def run_gate(
    stage_root: Path,
    lock_path: Path,
    transaction_parent: Path,
    target_os: str,
    target_arch: str,
    policy: Policy = PRODUCTION_POLICY,
) -> dict[str, object]:
    target_key = (target_os, target_arch)
    if target_key not in policy.targets:
        raise GateError(f"unsupported ONNX Runtime target: {target_os}/{target_arch}")
    stage_root = _require_plain_directory(stage_root, "staging root")
    transaction_parent = _require_plain_directory(
        transaction_parent,
        "ONNX Runtime transaction parent",
    )
    try:
        transaction_parent.relative_to(stage_root)
    except ValueError:
        pass
    else:
        raise GateError("ONNX Runtime transaction parent must be outside staging")
    package_root = stage_root / policy.package_relative_root
    native_root = package_root / policy.native_relative_root
    _reject_linked_ancestors(stage_root, native_root)
    package_root = _require_plain_directory(package_root, "onnxruntime-node package")
    native_root = _require_plain_directory(native_root, "onnxruntime-node native root")
    if package_root.stat().st_dev != transaction_parent.stat().st_dev:
        raise GateError("ONNX Runtime transaction parent is on another filesystem")
    _verify_lock(lock_path.resolve(strict=True), policy)
    _verify_package_metadata(package_root, policy)

    published_package, published_package_directories = _inventory(package_root)
    _compare_inventory(
        published_package,
        published_package_directories,
        policy.package_inventory,
        "published onnxruntime-node package",
    )
    before, before_directories = _inventory(native_root)
    _compare_inventory(
        before,
        before_directories,
        policy.inventory,
        "published onnxruntime-node native",
    )
    keep_prefix = policy.targets[target_key] + "/"
    expected_after = {
        relative: digest
        for relative, digest in policy.inventory.items()
        if relative.startswith(keep_prefix)
    }
    if not expected_after:
        raise GateError("target ONNX Runtime inventory is empty")

    remove = {
        relative: digest
        for relative, digest in policy.inventory.items()
        if relative not in expected_after
    }
    expected_target_package = _target_package_inventory(policy, expected_after)
    transaction = Path(
        tempfile.mkdtemp(
            prefix=f"autoeditor-onnx-{target_os}-{target_arch}-",
            dir=transaction_parent,
        )
    )
    replacement = transaction / "target-package"
    backup_name = "published-package"
    failed_name = "failed-target-package"
    _copy_target_package(
        package_root,
        replacement,
        policy.native_relative_root,
        policy.targets[target_key],
    )
    _verify_package_metadata(replacement, policy)
    replacement_files, replacement_directories = _inventory(replacement)
    _compare_inventory(
        replacement_files,
        replacement_directories,
        expected_target_package,
        "prepared target-only onnxruntime-node package",
    )
    replacement_native = replacement / policy.native_relative_root
    after, after_directories = _inventory(replacement_native)
    _compare_inventory(
        after,
        after_directories,
        expected_after,
        "prepared target-only onnxruntime-node native",
    )
    payload: dict[str, object] = {
        "schema": "autoeditor-onnxruntime-node-target-prune/v2",
        "target": {"os": target_os, "arch": target_arch},
        "package": {
            "name": policy.package_name,
            "version": policy.package_version,
            "integrity": policy.lock_entry.get("integrity"),
            "inventorySha256Before": _inventory_digest(before),
            "inventorySha256After": _inventory_digest(after),
        },
        "kept": [
            {"path": relative, "sha256": digest}
            for relative, digest in sorted(expected_after.items())
        ],
        "removed": [
            {"path": relative, "sha256": digest}
            for relative, digest in sorted(remove.items())
        ],
    }
    receipt_path = replacement / RECEIPT_RELATIVE_PATH
    _write_receipt(receipt_path, payload)
    expected_committed_package = dict(expected_target_package)
    expected_committed_package[RECEIPT_RELATIVE_PATH.as_posix()] = _sha256(
        receipt_path
    )
    prepared_files, prepared_directories = _inventory(replacement)
    _compare_inventory(
        prepared_files,
        prepared_directories,
        expected_committed_package,
        "receipted target-only onnxruntime-node package",
    )

    renamer = _DirectoryRenamer(package_root.parent, transaction)
    original_moved = False
    replacement_moved = False
    try:
        renamer.to_transaction(package_root.name, backup_name)
        original_moved = True
        renamer.to_package(replacement.name, package_root.name)
        replacement_moved = True
        final_package, final_package_directories = _inventory(package_root)
        _compare_inventory(
            final_package,
            final_package_directories,
            expected_committed_package,
            "committed target-only onnxruntime-node package",
        )
        _verify_package_metadata(package_root, policy)
        if (package_root / RECEIPT_RELATIVE_PATH).read_bytes() != (
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"):
            raise GateError("committed ONNX Runtime pruning receipt drifted")
    except Exception as exc:
        rollback_errors: list[str] = []
        if replacement_moved:
            try:
                renamer.to_transaction(package_root.name, failed_name)
                replacement_moved = False
            except Exception as rollback_exc:
                rollback_errors.append(f"cannot move replacement aside: {rollback_exc}")
        if original_moved:
            try:
                renamer.to_package(backup_name, package_root.name)
                original_moved = False
            except Exception as rollback_exc:
                rollback_errors.append(f"cannot restore published package: {rollback_exc}")
        if not rollback_errors:
            try:
                restored, restored_directories = _inventory(package_root)
                _compare_inventory(
                    restored,
                    restored_directories,
                    policy.package_inventory,
                    "restored published onnxruntime-node package",
                )
            except Exception as rollback_exc:
                rollback_errors.append(f"restored package verification failed: {rollback_exc}")
        if rollback_errors:
            raise GateError(
                "ONNX Runtime transaction failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        if isinstance(exc, GateError):
            raise
        raise GateError(f"ONNX Runtime transaction failed: {exc}") from exc
    finally:
        renamer.close()
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prune exact non-target ONNX Runtime native files"
    )
    parser.add_argument("--stage-root", required=True, type=Path)
    parser.add_argument("--package-lock", required=True, type=Path)
    parser.add_argument("--transaction-parent", required=True, type=Path)
    parser.add_argument("--target-os", required=True, choices=("mac", "windows"))
    parser.add_argument("--target-arch", required=True, choices=("arm64", "x64"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_gate(
            stage_root=args.stage_root,
            lock_path=args.package_lock,
            transaction_parent=args.transaction_parent,
            target_os=args.target_os,
            target_arch=args.target_arch,
        )
    except (GateError, OSError) as exc:
        print(f"ONNX Runtime target pruning failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
