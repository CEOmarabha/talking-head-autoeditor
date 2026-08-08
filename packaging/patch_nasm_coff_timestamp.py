#!/usr/bin/env python3
"""Apply and verify AutoEditor's exact NASM 3.01 COFF timestamp patch."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys


UPSTREAM_SHA256 = "03111d2099272695ecfaa5150fff21f4afd551e43f99a1fffdca682b4141e345"
PATCHED_SHA256 = "743c7b78b666b9777124ac4dd701f13011004be012f2b2c272d71b1a33f8f26f"
SOURCE_PATH = Path("output/outcoff.c")
UPSTREAM_LINE = (
    b"    fwriteint32_t(posix_timestamp(), ofile); /* timestamp */\n"
)
PATCHED_LINE = (
    b"    fwriteint32_t(0, ofile);                 /* deterministic timestamp */\n"
)


class PatchError(RuntimeError):
    """Raised when the pinned source or patched result is not exact."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patched_bytes(raw: bytes) -> bytes:
    """Return the exact patched source after validating the replacement seam."""
    if b"\r" in raw:
        raise PatchError("NASM outcoff.c must use LF line endings")
    if raw.count(UPSTREAM_LINE) != 1:
        raise PatchError("NASM COFF timestamp source seam drifted")
    if PATCHED_LINE in raw:
        raise PatchError("NASM COFF timestamp source is already patched")
    return raw.replace(UPSTREAM_LINE, PATCHED_LINE, 1)


def _source_file(source_root: Path) -> Path:
    root = source_root.resolve(strict=True)
    path = root / SOURCE_PATH
    try:
        info = path.lstat()
    except OSError as exc:
        raise PatchError(f"cannot inspect {SOURCE_PATH}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PatchError(f"{SOURCE_PATH} must be a regular non-symlink file")
    try:
        path.resolve(strict=True).relative_to(root)
    except ValueError as exc:
        raise PatchError(
            f"{SOURCE_PATH} resolves outside the NASM source root"
        ) from exc
    return path


def apply_patch(source_root: Path) -> None:
    path = _source_file(source_root)
    raw = path.read_bytes()
    if _sha256(raw) != UPSTREAM_SHA256:
        raise PatchError("NASM 3.01 outcoff.c digest drifted before patching")
    patched = patched_bytes(raw)
    if _sha256(patched) != PATCHED_SHA256:
        raise PatchError("NASM COFF timestamp patched digest drifted")

    temporary = path.with_name(path.name + ".autoeditor-patch")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IMODE(path.stat().st_mode),
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(patched)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise PatchError(f"cannot apply NASM COFF timestamp patch: {exc}") from exc

    verify_patch(source_root)


def verify_patch(source_root: Path) -> None:
    path = _source_file(source_root)
    raw = path.read_bytes()
    if _sha256(raw) != PATCHED_SHA256:
        raise PatchError("NASM 3.01 outcoff.c patched digest drifted")
    if raw.count(PATCHED_LINE) != 1 or UPSTREAM_LINE in raw:
        raise PatchError("NASM COFF timestamp patch content drifted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("apply", "verify"))
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "apply":
            apply_patch(args.source_root)
        else:
            verify_patch(args.source_root)
    except (OSError, PatchError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
