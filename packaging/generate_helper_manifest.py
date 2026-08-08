#!/usr/bin/env python3
"""Write a deterministic inventory for the exact Helper payload."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import struct
from pathlib import Path


IGNORED_RECEIPT_NAMES = {".DS_Store", ".gitkeep"}


class ManifestReceiptError(ValueError):
    """A file cannot be represented by the release receipt contract."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_file_range(handle, digest, start: int, length: int) -> None:
    handle.seek(start)
    remaining = length
    while remaining:
        chunk = handle.read(min(1024 * 1024, remaining))
        if not chunk:
            raise ManifestReceiptError("PE file ended while hashing")
        digest.update(chunk)
        remaining -= len(chunk)


def pe_authenticode_content_receipt(path: Path) -> dict:
    """Hash executable content while excluding Authenticode mutations.

    Windows signing updates the PE checksum and certificate-table directory,
    then appends an aligned WIN_CERTIFICATE table. Those bytes are separately
    validated by Get-AuthenticodeSignature in the signed-artifact gates. This
    receipt keeps every executable byte outside that signature envelope bound
    to the unsigned runtime that passed the earlier acceptance job.
    """
    file_size = path.stat().st_size
    try:
        with path.open("rb") as handle:
            dos = handle.read(64)
            if len(dos) != 64 or dos[:2] != b"MZ":
                raise ManifestReceiptError(f"{path} is not a PE executable")
            pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
            if pe_offset < 64 or pe_offset + 24 > file_size:
                raise ManifestReceiptError(f"{path} has an invalid PE header offset")
            handle.seek(pe_offset)
            pe_header = handle.read(24)
            if len(pe_header) != 24 or pe_header[:4] != b"PE\0\0":
                raise ManifestReceiptError(f"{path} has no valid PE signature")
            optional_size = struct.unpack_from("<H", pe_header, 20)[0]
            optional_offset = pe_offset + 24
            if optional_size < 152 or optional_offset + optional_size > file_size:
                raise ManifestReceiptError(f"{path} has an invalid optional header")
            optional = handle.read(optional_size)
            magic = struct.unpack_from("<H", optional, 0)[0]
            if magic == 0x10B:  # PE32
                directory_count_offset = 92
                security_directory_offset = 128
            elif magic == 0x20B:  # PE32+
                directory_count_offset = 108
                security_directory_offset = 144
            else:
                raise ManifestReceiptError(f"{path} has an unsupported PE format")
            if optional_size < security_directory_offset + 8:
                raise ManifestReceiptError(f"{path} has no security directory slot")
            directory_count = struct.unpack_from(
                "<I", optional, directory_count_offset
            )[0]
            if directory_count <= 4:
                raise ManifestReceiptError(f"{path} has no security directory entry")
            certificate_offset, certificate_size = struct.unpack_from(
                "<II", optional, security_directory_offset
            )
            if bool(certificate_offset) != bool(certificate_size):
                raise ManifestReceiptError(
                    f"{path} has an incomplete certificate-table entry"
                )
            if certificate_size:
                if (
                    certificate_offset % 8
                    or certificate_size < 8
                    or certificate_offset < optional_offset + optional_size
                    or certificate_offset + certificate_size != file_size
                ):
                    raise ManifestReceiptError(
                        f"{path} has an invalid certificate-table range"
                    )
                handle.seek(certificate_offset)
                certificate_header = handle.read(8)
                if len(certificate_header) != 8:
                    raise ManifestReceiptError(
                        f"{path} has a truncated WIN_CERTIFICATE header"
                    )
                certificate_length, revision, certificate_type = (
                    struct.unpack("<IHH", certificate_header)
                )
                if (
                    certificate_length < 8
                    or certificate_length > certificate_size
                    or revision not in {0x0100, 0x0200}
                    or certificate_type != 0x0002
                ):
                    raise ManifestReceiptError(
                        f"{path} has an invalid WIN_CERTIFICATE header"
                    )
                content_end = certificate_offset
            else:
                content_end = file_size

            checksum_offset = optional_offset + 64
            security_entry_offset = optional_offset + security_directory_offset
            zero_ranges = ((checksum_offset, 4), (security_entry_offset, 8))
            digest = hashlib.sha256()
            cursor = 0
            for offset, length in zero_ranges:
                if offset < cursor or offset + length > content_end:
                    raise ManifestReceiptError(
                        f"{path} has invalid Authenticode normalization offsets"
                    )
                _hash_file_range(handle, digest, cursor, offset - cursor)
                digest.update(b"\0" * length)
                cursor = offset + length
            _hash_file_range(handle, digest, cursor, content_end - cursor)
            canonical_size = (content_end + 7) & ~7
            digest.update(b"\0" * (canonical_size - content_end))
    except OSError as exc:
        raise ManifestReceiptError(f"cannot read PE executable {path}: {exc}") from exc
    return {"bytes": canonical_size, "sha256": digest.hexdigest()}


def directory_receipt(
    root: Path, *, normalize_windows_executables: bool = False
) -> dict:
    digest = hashlib.sha256()
    count = size = 0
    files = (
        item for item in root.rglob("*")
        if item.is_file()
        and item.name not in IGNORED_RECEIPT_NAMES
        and not item.name.startswith("._")
    )
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if normalize_windows_executables and path.suffix.casefold() == ".exe":
            executable = pe_authenticode_content_receipt(path)
            item_hash = executable["sha256"]
            item_size = executable["bytes"]
        else:
            item_hash = file_sha256(path)
            item_size = path.stat().st_size
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(item_size).encode("ascii") + b"\0")
        digest.update(item_hash.encode("ascii") + b"\n")
        count += 1
        size += item_size
    return {"files": count, "bytes": size, "sha256": digest.hexdigest()}


def empty_directory_receipt() -> dict:
    """Return the only receipt that may represent an omitted empty directory."""
    return {
        "files": 0,
        "bytes": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-os", required=True)
    parser.add_argument("--target-arch", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    components = {}
    for name in (
        "helper", "engine", "bin", "lib", "models", "profiles", "fonts", "certs",
        "node", "creative-runtime", "browser", "creative", "licenses",
    ):
        path = args.stage / name
        if not path.exists():
            raise SystemExit(f"required staged component is missing: {path}")
        components[name] = directory_receipt(
            path,
            normalize_windows_executables=args.target_os == "windows",
        )

    payload = {
        "schema": "autoeditor-helper-runtime/v1",
        "version": args.version,
        "target": {"os": args.target_os, "arch": args.target_arch},
        "receipt_algorithm": (
            "pe-authenticode-content-v1"
            if args.target_os == "windows"
            else "raw-sha256-v1"
        ),
        "builder": {
            "python": platform.python_version(),
            "system": platform.platform(),
        },
        "required_local_capabilities": [
            "frozen_python_engine", "ffmpeg", "ffprobe", "h264", "aac",
            "faster_whisper_small", "faster_whisper_medium", "node",
            "python_utf8_mode",
            "in_process_low_speech_cutter",
            "typed_deepseek_revision_contract",
            "hyperframes", "remotion", "chrome_headless_shell", "fonts",
            "certificate_bundle", "creator_profiles",
        ],
        "account_capabilities": {
            "deepseek": "required for editing and revision chat",
            "pexels": "user may connect or explicitly skip stock footage",
            "pixabay": "user may connect or explicitly skip stock footage",
            "elevenlabs": "user may connect or explicitly skip generated sound effects",
            "remotion": "required: free-license eligibility or paid key",
        },
        "components": components,
    }
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
