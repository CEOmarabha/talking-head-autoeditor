#!/usr/bin/env python3
"""Fail closed before pruning Remotion 4.0.507's stale Windows DLLs.

The published Windows compositor contains an active FFmpeg 7.1 runtime and an
unreferenced FFmpeg 6.1 runtime left by an upstream packaging mistake.  This
gate recognizes one exact npm payload, verifies its lock entry and PE imports,
and only then unlinks the seven known-stale DLLs by exact name and digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


PACKAGE_NAME = "@remotion/compositor-win32-x64-msvc"
PACKAGE_VERSION = "4.0.507"
PACKAGE_RELATIVE_ROOT = Path(
    "creative-runtime/node_modules/@remotion/compositor-win32-x64-msvc"
)
LOCK_PACKAGE_KEY = "node_modules/@remotion/compositor-win32-x64-msvc"
PACKAGE_RESOLVED = (
    "https://registry.npmjs.org/@remotion/compositor-win32-x64-msvc/-/"
    "compositor-win32-x64-msvc-4.0.507.tgz"
)
PACKAGE_INTEGRITY = (
    "sha512-FCkZDLcPBCO2WO/MyrtMB5tpsIuqqkc7E1nY2lfY6WmRX2quGfykcsz4S9inYx/"
    "G+XybKVTgplqnyLtt9wyFnw=="
)
PACKAGE_TARBALL_SHA256 = (
    "f0e006a1b84d7ac3caf6970ea6cfa4c0419371db230a2bd593996e86db197749"
)

EXPECTED_LOCK_ENTRY = {
    "cpu": ["x64"],
    "integrity": PACKAGE_INTEGRITY,
    "optional": True,
    "os": ["win32"],
    "resolved": PACKAGE_RESOLVED,
    "version": PACKAGE_VERSION,
}

EXPECTED_PACKAGE_JSON = {
    "repository": {
        "url": (
            "https://github.com/remotion-dev/remotion/tree/main/"
            "packages/compositor-win32-x64-msvc"
        )
    },
    "version": PACKAGE_VERSION,
    "name": PACKAGE_NAME,
    "os": ["win32"],
    "cpu": ["x64"],
    "exports": {
        ".": {
            "types": "./index.d.ts",
            "require": "./index.js",
            "import": "./index.mjs",
        },
        "./package.json": "./package.json",
    },
    "publishConfig": {"access": "public"},
}

# SHA-256 of every file extracted from the exact npm tarball above.  Checking
# the whole inventory prevents a changed package from borrowing the seven
# stale-file hashes and passing this narrowly authorized deletion gate.
EXPECTED_INVENTORY = {
    "README.md": "a7852a7bb8740348d8aecddd308fa222698de2ccd0f8bf57c1eb8d6afadb63db",
    "avcodec-60.dll": "b65d252925037d170803a16cdab1391acb3a9179cd5f93e47f31eefbce535f5d",
    "avcodec-61.dll": "f20de600c7a762768705821be4d7c7ec27524bd8f338659937785d7df0650914",
    "avdevice-60.dll": "bb17bd3d39856f6c8940e86bc7336ab09151f17cac4a52eb0c5679ea3c171d46",
    "avdevice-61.dll": "b83c1035e74bd590bbb60387421a8f9428b69cee531199d6e5d38000979a0b75",
    "avfilter-10.dll": "856f2dc37b14f42e526be3ec378d420d4c6714ec1c191bc60c51de48040bc30b",
    "avfilter-9.dll": "ddeb084f55d2f5c9d3d33d0b5b238d3d66ab83744a853daada3bd6b1d0f765ba",
    "avformat-60.dll": "0694f8549b8d56125150dfacc70d0f27ab199a1179055b43b7c386a381106a52",
    "avformat-61.dll": "d143e11641ec99b82787306aa9921348b10cacbe55ffbf4d9439f1b15fbe76a7",
    "avutil-58.dll": "71d5c71fab96ab66f0826a310418e010f796dc1c88d5c48d233cad080c5f0c40",
    "avutil-59.dll": "3cbe1a3eaf12996de9915e3c9ad7f7f349912b3557208a470d926ecd34b39597",
    "ffmpeg.exe": "cec8044dabd562f06fc4a6ed1cd59b8289680f542ef4ccf07d1924c5b340bc68",
    "ffprobe.exe": "3c7c023ed30f7034daa099f617ddf70dec87492dfb2bfb5000ece5a8768b0769",
    "index.d.ts": "32d05b74efe9deaffef9116eb9838fc6a7e4a7ba908e1142daf152bf60a22aca",
    "index.js": "439eed71b21d9e5ad1223983ad7f60a286e24661905f2d918b6ff92430fe6964",
    "index.mjs": "bcd507a747b4d5cdcaf0fcf4da0cab5736a88ab7a6e3abb337db1c81c836140e",
    "libgcc_s_seh-1.dll": "22f5d5bafd409871d8041686e55e3af1939d60f37cb1a48e7a4785136d0e9870",
    "libssp-0.dll": "647dbde6fe577e2d8710f96510556c2405a42a4f10fc30e4e10521ce036584b4",
    "libstdc++-6.dll": "65b141802009fd5e12c9ff1cc7c561f1be0607b5ec641971b313d8269e353606",
    "libvpx-1.dll": "e7da5d371cd3607cfe8d9819da040e2761074ad1c58ddcd7f8f47a9ebc088f0f",
    "libwinpthread-1.dll": "e814c9ce497ccb9a79ab4180e0cffaafa987e33a1b7474f12f70cecb1e868705",
    "msvcr100.dll": "e8684453d54a1bf9b9ed4b9d32c0e01da034debcd91fc35b2fd66d11b760845b",
    "package.json": "1d9591d2064df7c3ed75999946ac06f0c08bb8d39c4d57b2aa8b87e5f30fc0a2",
    "remotion.exe": "de75acfdb58f54ecbf66b6f90abd61688ba758ed56a1fd8c5277df32a3a60da1",
    "swresample-4.dll": "31f08bd1b0996ec52a96b9dac6786289559f6b29902cc2ec455fdb7bd35f4ec0",
    "swresample-5.dll": "e6f1c1196d0cb9ecac3801056a9d43533a56a7c9e7977eda9817aec6be011c21",
    "swscale-7.dll": "1f96a24e81da9fe32d35d3db9780fcdd4048d5c62b0cb2795cf7c95975f40326",
    "swscale-8.dll": "4b97a9efb593bd217d105dfc6e62c5c7fd61b3db57fb072751cd6030aecef860",
    "zlib1.dll": "fb23ab0f7f3def5a6af4653b2c70b5e3a42b5ae329d1c71ad986ba85ea439cf1",
}

STALE_FILES = {
    "avcodec-60.dll": EXPECTED_INVENTORY["avcodec-60.dll"],
    "avdevice-60.dll": EXPECTED_INVENTORY["avdevice-60.dll"],
    "avfilter-9.dll": EXPECTED_INVENTORY["avfilter-9.dll"],
    "avformat-60.dll": EXPECTED_INVENTORY["avformat-60.dll"],
    "avutil-58.dll": EXPECTED_INVENTORY["avutil-58.dll"],
    "swresample-4.dll": EXPECTED_INVENTORY["swresample-4.dll"],
    "swscale-7.dll": EXPECTED_INVENTORY["swscale-7.dll"],
}

EXPECTED_IMPORTS = {
    "remotion.exe": frozenset(
        {
            "api-ms-win-core-synch-l1-2-0.dll",
            "api-ms-win-crt-environment-l1-1-0.dll",
            "api-ms-win-crt-heap-l1-1-0.dll",
            "api-ms-win-crt-math-l1-1-0.dll",
            "api-ms-win-crt-private-l1-1-0.dll",
            "api-ms-win-crt-runtime-l1-1-0.dll",
            "api-ms-win-crt-stdio-l1-1-0.dll",
            "api-ms-win-crt-string-l1-1-0.dll",
            "api-ms-win-crt-time-l1-1-0.dll",
            "avcodec-61.dll",
            "avdevice-61.dll",
            "avfilter-10.dll",
            "avformat-61.dll",
            "avutil-59.dll",
            "bcryptprimitives.dll",
            "kernel32.dll",
            "msvcrt.dll",
            "ntdll.dll",
            "pdh.dll",
            "swscale-8.dll",
        }
    ),
    "ffmpeg.exe": frozenset(
        {
            "avcodec-61.dll",
            "avdevice-61.dll",
            "avfilter-10.dll",
            "avformat-61.dll",
            "avutil-59.dll",
            "kernel32.dll",
            "libgcc_s_seh-1.dll",
            "libwinpthread-1.dll",
            "msvcrt.dll",
            "psapi.dll",
            "shell32.dll",
            "swresample-5.dll",
            "swscale-8.dll",
        }
    ),
    "ffprobe.exe": frozenset(
        {
            "avcodec-61.dll",
            "avdevice-61.dll",
            "avfilter-10.dll",
            "avformat-61.dll",
            "avutil-59.dll",
            "kernel32.dll",
            "libwinpthread-1.dll",
            "msvcrt.dll",
            "shell32.dll",
            "swresample-5.dll",
            "swscale-8.dll",
        }
    ),
}


class GateError(RuntimeError):
    """The staged native runtime does not match the sole deletion policy."""


@dataclass(frozen=True)
class Policy:
    package_name: str
    package_version: str
    package_relative_root: Path
    lock_package_key: str
    resolved: str
    integrity: str
    tarball_sha256: str
    lock_entry: Mapping[str, object]
    package_json: Mapping[str, object]
    inventory: Mapping[str, str]
    stale_files: Mapping[str, str]
    expected_imports: Mapping[str, frozenset[str]]


PRODUCTION_POLICY = Policy(
    package_name=PACKAGE_NAME,
    package_version=PACKAGE_VERSION,
    package_relative_root=PACKAGE_RELATIVE_ROOT,
    lock_package_key=LOCK_PACKAGE_KEY,
    resolved=PACKAGE_RESOLVED,
    integrity=PACKAGE_INTEGRITY,
    tarball_sha256=PACKAGE_TARBALL_SHA256,
    lock_entry=EXPECTED_LOCK_ENTRY,
    package_json=EXPECTED_PACKAGE_JSON,
    inventory=EXPECTED_INVENTORY,
    stale_files=STALE_FILES,
    expected_imports=EXPECTED_IMPORTS,
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
            path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read strict {label}: {exc}") from exc


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


def _require_contained_path(stage_root: Path, candidate: Path, label: str) -> Path:
    absolute = candidate if candidate.is_absolute() else Path.cwd() / candidate
    parent = absolute.parent.resolve(strict=True)
    resolved = parent / absolute.name
    try:
        resolved.relative_to(stage_root)
    except ValueError as exc:
        raise GateError(f"{label} must stay inside the staging root") from exc
    return resolved


def _reject_symlink_components(stage_root: Path, package_root: Path) -> None:
    try:
        relative = package_root.relative_to(stage_root)
    except ValueError as exc:
        raise GateError("Remotion package escaped the staging root") from exc
    current = stage_root
    for component in relative.parts:
        current = current / component
        if current.is_symlink() or _is_junction(current):
            raise GateError(f"Remotion package path contains a link: {current}")


def _inventory(root: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directory_names:
            candidate = base / name
            metadata = candidate.lstat()
            if (
                candidate.is_symlink()
                or _is_junction(candidate)
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                raise GateError(f"package contains linked or special directory: {candidate}")
        for name in file_names:
            candidate = base / name
            relative = candidate.relative_to(root).as_posix()
            metadata = candidate.lstat()
            if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise GateError(f"package contains linked or special file: {relative}")
            if metadata.st_nlink != 1:
                raise GateError(f"package file has unexpected hard links: {relative}")
            inventory[relative] = _sha256(candidate)
    return inventory


def _inventory_digest(inventory: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_digest in sorted(inventory.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_digest))
    return digest.hexdigest()


def _compare_inventory(
    observed: Mapping[str, str], expected: Mapping[str, str], label: str
) -> None:
    observed_names = set(observed)
    expected_names = set(expected)
    missing = sorted(expected_names - observed_names)
    unexpected = sorted(observed_names - expected_names)
    changed = sorted(
        name
        for name in observed_names & expected_names
        if observed[name] != expected[name]
    )
    if missing or unexpected or changed:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        if changed:
            details.append("changed=" + ",".join(changed))
        raise GateError(f"{label} inventory drift: {'; '.join(details)}")


def _verify_lock(lock_path: Path, policy: Policy) -> None:
    document = _load_json(lock_path, "npm package lock")
    if not isinstance(document, dict):
        raise GateError("npm package lock must be a JSON object")
    packages = document.get("packages")
    if not isinstance(packages, dict):
        raise GateError("npm package lock has no packages object")
    entry = packages.get(policy.lock_package_key)
    if entry != dict(policy.lock_entry):
        raise GateError(
            f"npm lock entry drift for {policy.package_name} {policy.package_version}"
        )


def _verify_package_metadata(package_root: Path, policy: Policy) -> None:
    document = _load_json(package_root / "package.json", "package metadata")
    if document != dict(policy.package_json):
        raise GateError(
            f"package metadata drift for {policy.package_name} {policy.package_version}"
        )


def _read_at(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise GateError(f"truncated PE while reading {label}")
    return data[offset : offset + size]


def _unpack_from(fmt: str, data: bytes, offset: int, label: str) -> tuple[int, ...]:
    size = struct.calcsize(fmt)
    _read_at(data, offset, size, label)
    return struct.unpack_from(fmt, data, offset)


@dataclass(frozen=True)
class _PeLayout:
    data: bytes
    image_base: int
    size_of_headers: int
    sections: tuple[tuple[int, int, int, int], ...]
    directories: tuple[tuple[int, int], ...]

    def rva_offset(self, rva: int, size: int, label: str) -> int:
        if rva < self.size_of_headers:
            _read_at(self.data, rva, size, label)
            return rva
        for virtual_address, virtual_size, raw_offset, raw_size in self.sections:
            extent = max(virtual_size, raw_size)
            if virtual_address <= rva < virtual_address + extent:
                delta = rva - virtual_address
                if delta + size > raw_size:
                    raise GateError(f"PE RVA points outside raw section data: {label}")
                offset = raw_offset + delta
                _read_at(self.data, offset, size, label)
                return offset
        raise GateError(f"PE RVA is not mapped by any section: {label}")

    def c_string(self, rva: int, label: str) -> str:
        offset = self.rva_offset(rva, 1, label)
        end = min(len(self.data), offset + 512)
        terminator = self.data.find(b"\0", offset, end)
        if terminator < 0:
            raise GateError(f"unterminated PE string: {label}")
        raw = self.data[offset:terminator]
        try:
            value = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise GateError(f"non-ASCII PE import name: {label}") from exc
        allowed = (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        )
        if not value or any(ch not in allowed for ch in value):
            raise GateError(f"invalid PE import name: {value!r}")
        return value.lower()


def _pe_layout(path: Path) -> _PeLayout:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GateError(f"cannot read PE executable {path.name}: {exc}") from exc
    if len(data) < 64 or data[:2] != b"MZ":
        raise GateError(f"{path.name} is not a complete DOS/PE image")
    (pe_offset,) = _unpack_from("<I", data, 0x3C, "DOS PE offset")
    if _read_at(data, pe_offset, 4, "PE signature") != b"PE\0\0":
        raise GateError(f"{path.name} has no PE signature")
    coff = pe_offset + 4
    machine, section_count = _unpack_from("<HH", data, coff, "COFF header")
    if machine != 0x8664:
        raise GateError(f"{path.name} is not Windows x64 PE (machine=0x{machine:04x})")
    if not 1 <= section_count <= 96:
        raise GateError(f"{path.name} has an invalid PE section count")
    (optional_size,) = _unpack_from("<H", data, coff + 16, "optional-header size")
    optional = coff + 20
    if optional_size < 240:
        raise GateError(f"{path.name} has a truncated PE32+ optional header")
    (magic,) = _unpack_from("<H", data, optional, "optional-header magic")
    if magic != 0x20B:
        raise GateError(f"{path.name} is not a PE32+ executable")
    (image_base,) = _unpack_from("<Q", data, optional + 24, "image base")
    (size_of_headers,) = _unpack_from("<I", data, optional + 60, "header size")
    (directory_count,) = _unpack_from("<I", data, optional + 108, "directory count")
    if directory_count < 2 or directory_count > 16:
        raise GateError(f"{path.name} has an invalid PE directory count")
    directory_offset = optional + 112
    if directory_offset + directory_count * 8 > optional + optional_size:
        raise GateError(f"{path.name} data directories escape the optional header")
    directories = tuple(
        _unpack_from(
            "<II", data, directory_offset + index * 8, f"data directory {index}"
        )
        for index in range(directory_count)
    )
    section_offset = optional + optional_size
    sections = []
    for index in range(section_count):
        entry = section_offset + index * 40
        _read_at(data, entry, 40, f"section header {index}")
        virtual_size, virtual_address, raw_size, raw_offset = _unpack_from(
            "<IIII", data, entry + 8, f"section header {index}"
        )
        if raw_size:
            _read_at(data, raw_offset, raw_size, f"section data {index}")
        sections.append((virtual_address, virtual_size, raw_offset, raw_size))
    return _PeLayout(
        data=data,
        image_base=image_base,
        size_of_headers=size_of_headers,
        sections=tuple(sections),
        directories=directories,
    )


def _descriptor_imports(
    layout: _PeLayout,
    directory_index: int,
    descriptor_size: int,
    name_field_offset: int,
    label: str,
    delay_addresses: bool = False,
) -> set[str]:
    if directory_index >= len(layout.directories):
        return set()
    directory_rva, directory_size = layout.directories[directory_index]
    if directory_rva == 0 and directory_size == 0:
        return set()
    if directory_rva == 0 or directory_size < descriptor_size:
        raise GateError(f"invalid {label} directory")
    imports: set[str] = set()
    terminated = False
    for index in range(directory_size // descriptor_size):
        descriptor_rva = directory_rva + index * descriptor_size
        descriptor_offset = layout.rva_offset(
            descriptor_rva, descriptor_size, f"{label} descriptor {index}"
        )
        descriptor = _read_at(
            layout.data, descriptor_offset, descriptor_size, f"{label} descriptor {index}"
        )
        if descriptor == b"\0" * descriptor_size:
            terminated = True
            break
        (name_address,) = _unpack_from(
            "<I",
            layout.data,
            descriptor_offset + name_field_offset,
            f"{label} name RVA",
        )
        if delay_addresses:
            (attributes,) = _unpack_from(
                "<I", layout.data, descriptor_offset, f"{label} attributes"
            )
            if attributes & ~1:
                raise GateError(f"unsupported {label} attributes")
            if not attributes & 1:
                if name_address < layout.image_base:
                    raise GateError(f"invalid {label} virtual address")
                name_address -= layout.image_base
        imports.add(layout.c_string(name_address, f"{label} import name"))
    if not terminated:
        raise GateError(f"unterminated {label} directory")
    return imports


def pe_imports(path: Path) -> frozenset[str]:
    layout = _pe_layout(path)
    imports = _descriptor_imports(layout, 1, 20, 12, "import")
    imports.update(
        _descriptor_imports(layout, 13, 32, 4, "delay-import", delay_addresses=True)
    )
    if not imports:
        raise GateError(f"{path.name} has no parseable PE imports")
    return frozenset(imports)


def _verify_pe_imports(package_root: Path, policy: Policy) -> dict[str, list[str]]:
    stale_names = {name.lower() for name in policy.stale_files}
    observed: dict[str, list[str]] = {}
    for executable, expected in policy.expected_imports.items():
        imports = pe_imports(package_root / executable)
        forbidden = sorted(imports & stale_names)
        if forbidden:
            raise GateError(
                f"{executable} imports stale FFmpeg runtime: {', '.join(forbidden)}"
            )
        if imports != expected:
            missing = sorted(expected - imports)
            unexpected = sorted(imports - expected)
            raise GateError(
                f"{executable} PE import drift: missing={missing}; unexpected={unexpected}"
            )
        observed[executable] = sorted(imports)
    return observed


def _stray_stale_paths(
    stage_root: Path, package_root: Path | None, policy: Policy
) -> list[str]:
    stale_names = {name.lower() for name in policy.stale_files}
    found = []
    for directory, directory_names, file_names in os.walk(
        stage_root, followlinks=False
    ):
        base = Path(directory)
        directory_names[:] = [
            name
            for name in directory_names
            if not (base / name).is_symlink() and not _is_junction(base / name)
        ]
        for name in file_names:
            if name.lower() not in stale_names:
                continue
            candidate = base / name
            if package_root is not None:
                try:
                    candidate.relative_to(package_root)
                    continue
                except ValueError:
                    pass
            found.append(candidate.relative_to(stage_root).as_posix())
    return sorted(found)


def _write_receipt(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise GateError(f"cannot write pruning receipt: {exc}") from exc


def run_gate(
    stage_root: Path,
    lock_path: Path,
    receipt_path: Path,
    require_package: bool,
    policy: Policy = PRODUCTION_POLICY,
) -> dict[str, object]:
    stage_root = _require_plain_directory(stage_root, "staging root")
    receipt_path = _require_contained_path(stage_root, receipt_path, "receipt")
    package_root = stage_root / policy.package_relative_root

    if not package_root.exists():
        stray = _stray_stale_paths(stage_root, None, policy)
        if stray:
            raise GateError(
                "stale Remotion FFmpeg DLLs exist outside the canonical package: "
                + ", ".join(stray)
            )
        if require_package:
            raise GateError(
                f"required {policy.package_name} {policy.package_version} is missing"
            )
        payload: dict[str, object] = {
            "schema": "autoeditor-remotion-windows-runtime-prune/v1",
            "status": "package-not-present",
            "target": {"os": "windows", "arch": "x64"},
            "package": {
                "name": policy.package_name,
                "version": policy.package_version,
            },
            "removed": [],
        }
        _write_receipt(receipt_path, payload)
        return payload

    _reject_symlink_components(stage_root, package_root)
    package_root = _require_plain_directory(package_root, "Remotion package")
    stray = _stray_stale_paths(stage_root, package_root, policy)
    if stray:
        raise GateError(
            "stale Remotion FFmpeg DLLs exist outside the canonical package: "
            + ", ".join(stray)
        )

    _verify_lock(lock_path.resolve(strict=True), policy)
    _verify_package_metadata(package_root, policy)
    before = _inventory(package_root)
    _compare_inventory(before, policy.inventory, "published Remotion package")
    imports = _verify_pe_imports(package_root, policy)

    identities: dict[str, tuple[int, int, int, int]] = {}
    for relative, expected_digest in policy.stale_files.items():
        candidate = package_root / relative
        metadata = candidate.lstat()
        if (
            candidate.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise GateError(f"stale deletion target is not a sole regular file: {relative}")
        if _sha256(candidate) != expected_digest:
            raise GateError(f"stale deletion target changed before pruning: {relative}")
        identities[relative] = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )

    # No unlink happens before every package, digest, and PE-import check above.
    for relative, expected_digest in policy.stale_files.items():
        candidate = package_root / relative
        metadata = candidate.lstat()
        current_identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        if current_identity != identities[relative] or _sha256(candidate) != expected_digest:
            raise GateError(f"stale deletion target raced validation: {relative}")
        candidate.unlink()

    after = _inventory(package_root)
    expected_after = {
        relative: digest
        for relative, digest in policy.inventory.items()
        if relative not in policy.stale_files
    }
    _compare_inventory(after, expected_after, "pruned Remotion package")
    if len(before) - len(after) != len(policy.stale_files):
        raise GateError("pruning did not remove exactly the authorized stale files")

    payload = {
        "schema": "autoeditor-remotion-windows-runtime-prune/v1",
        "status": "pruned",
        "target": {"os": "windows", "arch": "x64"},
        "package": {
            "name": policy.package_name,
            "version": policy.package_version,
            "resolved": policy.resolved,
            "integrity": policy.integrity,
            "tarballSha256": policy.tarball_sha256,
            "inventorySha256Before": _inventory_digest(before),
            "inventorySha256After": _inventory_digest(after),
        },
        "activeFfmpegGeneration": "7.1",
        "staleFfmpegGeneration": "6.1",
        "activePeImports": imports,
        "removed": [
            {"path": relative, "sha256": digest}
            for relative, digest in policy.stale_files.items()
        ],
    }
    _write_receipt(receipt_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and prune the exact stale FFmpeg 6.1 files from the "
            "Windows Remotion 4.0.507 compositor"
        )
    )
    parser.add_argument("--stage-root", required=True, type=Path)
    parser.add_argument("--package-lock", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument(
        "--require-package",
        action="store_true",
        help="fail if the canonical Windows compositor package is absent",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_gate(
            stage_root=args.stage_root,
            lock_path=args.package_lock,
            receipt_path=args.receipt,
            require_package=args.require_package,
        )
    except (GateError, OSError) as exc:
        print(f"Remotion Windows runtime gate failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
