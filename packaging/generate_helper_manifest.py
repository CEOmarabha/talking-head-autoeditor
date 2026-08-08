#!/usr/bin/env python3
"""Write a deterministic inventory for the exact Helper payload."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path


IGNORED_RECEIPT_NAMES = {".DS_Store", ".gitkeep"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_receipt(root: Path) -> dict:
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
        item_hash = file_sha256(path)
        item_size = path.stat().st_size
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(item_size).encode("ascii") + b"\0")
        digest.update(item_hash.encode("ascii") + b"\n")
        count += 1
        size += item_size
    return {"files": count, "bytes": size, "sha256": digest.hexdigest()}


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
        components[name] = directory_receipt(path)

    payload = {
        "schema": "autoeditor-helper-runtime/v1",
        "version": args.version,
        "target": {"os": args.target_os, "arch": args.target_arch},
        "builder": {
            "python": platform.python_version(),
            "system": platform.platform(),
        },
        "required_local_capabilities": [
            "frozen_python_engine", "ffmpeg", "ffprobe", "h264", "aac",
            "faster_whisper_small", "faster_whisper_medium", "node",
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
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
