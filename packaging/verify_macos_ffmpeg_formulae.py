#!/usr/bin/env python3
"""Fail closed when the Homebrew FFmpeg dependency closure drifts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


SYSTEM_PREFIXES = ("/System/", "/usr/lib/")


class FormulaInventoryError(RuntimeError):
    """The installed media runtime does not match its audited inventory."""


@dataclass(frozen=True)
class BottleRecord:
    formula: str
    version: str
    bottle_tag: str
    bottle_rebuild: int
    bottle_sha256: str


def formula_version_from_cellar(path: Path, cellar: Path) -> tuple[str, str]:
    resolved = path.resolve()
    root = cellar.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise FormulaInventoryError(
            f"non-system dependency is outside Homebrew Cellar: {resolved}"
        ) from exc
    if len(relative.parts) < 2:
        raise FormulaInventoryError(
            f"cannot identify formula and version from Cellar path: {resolved}"
        )
    return relative.parts[0], relative.parts[1]


def read_inventory(path: Path) -> dict[str, BottleRecord]:
    inventory: dict[str, BottleRecord] = {}
    for number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 5:
            raise FormulaInventoryError(
                f"{path}:{number}: expected '<formula> <version> "
                "<bottle-tag> <bottle-rebuild> <bottle-sha256>'"
            )
        formula, version, bottle_tag, rebuild_text, bottle_sha256 = fields
        if formula in inventory:
            raise FormulaInventoryError(
                f"{path}:{number}: duplicate formula {formula}"
            )
        try:
            bottle_rebuild = int(rebuild_text)
        except ValueError as exc:
            raise FormulaInventoryError(
                f"{path}:{number}: bottle rebuild must be an integer"
            ) from exc
        if bottle_rebuild < 0:
            raise FormulaInventoryError(
                f"{path}:{number}: bottle rebuild cannot be negative"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", bottle_sha256):
            raise FormulaInventoryError(
                f"{path}:{number}: invalid bottle SHA-256"
            )
        inventory[formula] = BottleRecord(
            formula, version, bottle_tag, bottle_rebuild, bottle_sha256
        )
    if not inventory:
        raise FormulaInventoryError(f"formula inventory is empty: {path}")
    return inventory


def compare_inventories(
    actual: dict[str, str], expected: dict[str, BottleRecord]
) -> None:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(
        formula for formula in set(actual) & set(expected)
        if actual[formula] != expected[formula].version
    )
    problems = []
    if missing:
        problems.append("missing formulae: " + ", ".join(missing))
    if extra:
        problems.append("unexpected formulae: " + ", ".join(extra))
    if changed:
        problems.append("version changes: " + ", ".join(
            f"{formula} expected {expected[formula].version}, "
            f"found {actual[formula]}"
            for formula in changed
        ))
    if problems:
        raise FormulaInventoryError(
            "Homebrew FFmpeg formula closure drifted; " + "; ".join(problems)
        )


def otool_dependencies(binary: Path) -> list[Path]:
    result = subprocess.run(
        ["otool", "-L", str(binary)], check=True, capture_output=True,
        text=True,
    )
    found = []
    for line in result.stdout.splitlines()[1:]:
        match = re.match(r"\s*(\S+)\s+\(", line)
        if not match:
            continue
        value = match.group(1)
        if value.startswith(SYSTEM_PREFIXES) or value.startswith("@"):
            continue
        dependency = Path(value)
        if not dependency.is_absolute() or not dependency.exists():
            raise FormulaInventoryError(
                f"unresolved non-system dependency in {binary}: {value}"
            )
        found.append(dependency.resolve())
    return found


def discover_formulae(
    ffmpeg: Path, ffprobe: Path, cellar: Path
) -> dict[str, str]:
    queue = [ffmpeg.resolve(), ffprobe.resolve()]
    visited: set[Path] = set()
    inventory: dict[str, str] = {}
    while queue:
        binary = queue.pop(0).resolve()
        if binary in visited:
            continue
        visited.add(binary)
        formula, version = formula_version_from_cellar(binary, cellar)
        prior = inventory.get(formula)
        if prior is not None and prior != version:
            raise FormulaInventoryError(
                f"multiple versions of {formula} are linked: {prior}, {version}"
            )
        inventory[formula] = version
        queue.extend(otool_dependencies(binary))
    return inventory


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bottle_archive(path: Path, record: BottleRecord) -> None:
    rebuild = (
        f".{record.bottle_rebuild}" if record.bottle_rebuild else ""
    )
    expected_suffix = (
        f"--{record.formula}--{record.version}.{record.bottle_tag}"
        f".bottle{rebuild}.tar.gz"
    )
    if not path.name.endswith(expected_suffix):
        raise FormulaInventoryError(
            f"unexpected bottle filename for {record.formula}: {path.name}; "
            f"expected suffix {expected_suffix}"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != record.bottle_sha256:
        raise FormulaInventoryError(
            f"bottle SHA-256 drifted for {record.formula}: expected "
            f"{record.bottle_sha256}, found {actual_sha256}"
        )


def verify_cached_bottles(
    inventory: dict[str, BottleRecord], brew: str
) -> None:
    for formula, record in inventory.items():
        result = subprocess.run(
            [brew, "--cache", formula], check=True, capture_output=True,
            text=True,
        )
        cache_lines = [line.strip() for line in result.stdout.splitlines()
                       if line.strip()]
        if len(cache_lines) != 1:
            raise FormulaInventoryError(
                f"cannot resolve one cached bottle for {formula}"
            )
        archive = Path(cache_lines[0])
        if not archive.is_file():
            raise FormulaInventoryError(
                f"verified bottle archive is missing for {formula}: {archive}"
            )
        verify_bottle_archive(archive, record)


def verify_install_receipts(
    inventory: dict[str, BottleRecord], brew: str, expected_arch: str
) -> None:
    receipt_arch = "x86_64" if expected_arch == "x64" else "arm64"
    for formula, record in inventory.items():
        result = subprocess.run(
            [brew, "--prefix", formula], check=True, capture_output=True,
            text=True,
        )
        prefix = Path(result.stdout.strip()).resolve()
        found_formula, found_version = formula_version_from_cellar(
            prefix, Path(subprocess.run(
                [brew, "--cellar"], check=True, capture_output=True,
                text=True,
            ).stdout.strip()),
        )
        if (found_formula, found_version) != (formula, record.version):
            raise FormulaInventoryError(
                f"installed prefix drifted for {formula}: "
                f"{found_formula} {found_version}"
            )
        receipt_path = prefix / "INSTALL_RECEIPT.json"
        try:
            receipt = json.loads(receipt_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise FormulaInventoryError(
                f"invalid install receipt for {formula}: {receipt_path}"
            ) from exc
        if receipt.get("built_as_bottle") is not True or \
                receipt.get("poured_from_bottle") is not True:
            raise FormulaInventoryError(
                f"{formula} was not installed from a Homebrew bottle"
            )
        if receipt.get("arch") != receipt_arch:
            raise FormulaInventoryError(
                f"{formula} receipt arch is {receipt.get('arch')}, "
                f"expected {receipt_arch}"
            )


def write_inventory(
    path: Path, inventory: dict[str, BottleRecord]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        f"{record.formula} {record.version} {record.bottle_tag} "
        f"{record.bottle_rebuild} {record.bottle_sha256}\n"
        for record in (inventory[formula] for formula in sorted(inventory))
    ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--cellar", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-arch", choices=("arm64", "x64"),
                        required=True)
    parser.add_argument("--brew", default="brew")
    args = parser.parse_args()

    for executable in (args.ffmpeg, args.ffprobe):
        if not executable.is_file():
            raise FormulaInventoryError(f"missing executable: {executable}")
    actual = discover_formulae(args.ffmpeg, args.ffprobe, args.cellar)
    expected = read_inventory(args.expected)
    compare_inventories(actual, expected)
    verify_cached_bottles(expected, args.brew)
    verify_install_receipts(expected, args.brew, args.expected_arch)
    write_inventory(args.output, expected)
    print(
        f"verified {len(actual)} exact Homebrew formula versions "
        f"against {args.expected}"
    )


if __name__ == "__main__":
    main()
