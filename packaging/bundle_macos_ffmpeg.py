#!/usr/bin/env python3
"""Create a relocatable native macOS FFmpeg/FFprobe dependency bundle.

Homebrew bottles are architecture-native but link to Homebrew-owned dylibs.
This copies the complete non-system dependency graph beside the executables,
rewrites load commands to relative paths, and ad-hoc signs the staged files so
they can be smoke-tested before electron-builder applies the release identity.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path


SYSTEM_PREFIXES = ("/System/", "/usr/lib/")


def run(*args: str | Path, capture: bool = False) -> str:
    result = subprocess.run(
        [str(arg) for arg in args], check=True,
        capture_output=capture, text=True,
    )
    return result.stdout if capture else ""


def dependencies(binary: Path) -> list[tuple[str, Path]]:
    output = run("otool", "-L", binary, capture=True)
    found = []
    for line in output.splitlines()[1:]:
        match = re.match(r"\s*(\S+)\s+\(", line)
        if not match:
            continue
        value = match.group(1)
        if value.startswith(SYSTEM_PREFIXES) or value.startswith("@"):
            continue
        path = Path(value)
        if path.exists():
            found.append((value, path.resolve()))
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--lib-dir", type=Path, required=True)
    args = parser.parse_args()

    args.bin_dir.mkdir(parents=True, exist_ok=True)
    args.lib_dir.mkdir(parents=True, exist_ok=True)
    executables = []
    for source in (args.ffmpeg.resolve(), args.ffprobe.resolve()):
        target = args.bin_dir / source.name
        shutil.copy2(source, target)
        target.chmod(0o755)
        executables.append(target)

    originals: dict[Path, Path] = {}
    queue = [
        resolved
        for executable in executables
        for _, resolved in dependencies(executable)
    ]
    while queue:
        source = queue.pop(0).resolve()
        target = args.lib_dir / source.name
        prior = originals.get(target)
        if prior and prior != source:
            raise RuntimeError(
                f"dylib basename collision: {prior} and {source}"
            )
        if prior:
            continue
        originals[target] = source
        shutil.copy2(source, target)
        target.chmod(0o755)
        queue.extend(resolved for _, resolved in dependencies(target))

    original_to_target = {
        source: target for target, source in originals.items()
    }
    for target, source in originals.items():
        run("install_name_tool", "-id", f"@loader_path/{target.name}", target)
        for load_path, dependency in dependencies(source):
            bundled = original_to_target.get(dependency.resolve())
            if bundled:
                run(
                    "install_name_tool", "-change", load_path,
                    f"@loader_path/{bundled.name}", target,
                )
    for executable in executables:
        source = (
            args.ffmpeg.resolve()
            if executable.name == "ffmpeg" else args.ffprobe.resolve()
        )
        for load_path, dependency in dependencies(source):
            bundled = original_to_target.get(dependency.resolve())
            if bundled:
                run(
                    "install_name_tool", "-change", load_path,
                    f"@executable_path/../lib/{bundled.name}", executable,
                )

    for binary in [*originals, *executables]:
        run("codesign", "--force", "--sign", "-", binary)

    print(
        f"bundled {len(executables)} executables and "
        f"{len(originals)} dylibs for {os.uname().machine}"
    )


if __name__ == "__main__":
    main()
