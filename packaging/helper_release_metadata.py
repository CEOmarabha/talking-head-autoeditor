#!/usr/bin/env python3
"""Create and validate small receipts for immutable Helper installers."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


SCHEMA = "autoeditor-helper-candidate/v2"
RELEASE_SCHEMA = "autoeditor-helper-release/v2"
GITHUB_ASSETS_SCHEMA = "autoeditor-helper-github-assets/v1"
TAG_PATTERN = re.compile(
    r"^helper-v(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\."
    r"(?P<patch>[0-9]+)(?P<suffix>[.-][A-Za-z0-9.-]+)?$"
)
MAX_COPY_OBJECT_BYTES = 5 * 1024 * 1024 * 1024
MAX_NSIS_WEB_PACKAGE_BYTES = 4_294_967_295
WINDOWS_RUNTIME_PACKAGE = (
    "AutoEditor-Helper-Windows.nsis.7z",
    "application/x-7z-compressed",
)
PLATFORMS = {
    ("windows", "x64"): (
        "windows-x64", "AutoEditor-Helper.exe",
        "AutoEditor-Helper-Windows.exe",
        "application/vnd.microsoft.portable-executable",
    ),
    ("mac", "arm64"): (
        "mac-arm64", "AutoEditor-Helper.dmg",
        "AutoEditor-Helper-Mac-Apple-Silicon.dmg",
        "application/x-apple-diskimage",
    ),
    ("mac", "x64"): (
        "mac-x64", "AutoEditor-Helper.dmg",
        "AutoEditor-Helper-Mac-Intel.dmg",
        "application/x-apple-diskimage",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_tag(tag: str) -> re.Match[str]:
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise SystemExit(f"invalid Helper release tag: {tag}")
    return match


def write_candidate(args: argparse.Namespace) -> None:
    valid_tag(args.tag)
    tag_version = args.tag.removeprefix("helper-v")
    platform = PLATFORMS.get((args.target_os, args.arch))
    if not platform:
        raise SystemExit(f"unsupported target: {args.target_os}-{args.arch}")
    platform_id, stored_name, download_name, content_type = platform
    if not args.file.is_file() or args.file.stat().st_size <= 0:
        raise SystemExit(f"installer is missing or empty: {args.file}")
    if args.file.stat().st_size > MAX_COPY_OBJECT_BYTES:
        raise SystemExit("installer exceeds the 5 GiB server-side copy limit")
    try:
        runtime = json.loads(args.runtime_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid runtime manifest: {exc}") from exc
    if runtime.get("target") != {"os": args.target_os, "arch": args.arch}:
        raise SystemExit("runtime manifest target does not match installer target")
    if runtime.get("version") != tag_version:
        raise SystemExit("runtime manifest version does not match release tag")
    if not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        raise SystemExit("source commit must be the exact 40-character Git SHA")
    if not re.fullmatch(r"[1-9][0-9]*", args.run_id) or not re.fullmatch(
            r"[1-9][0-9]*", args.run_attempt):
        raise SystemExit("GitHub run id and attempt must be positive integers")
    expected_verification = (
        ("verified", "not-applicable") if args.target_os == "windows"
        else ("verified", "verified")
    )
    if (args.signing_status, args.notarization_status) != expected_verification:
        raise SystemExit("tagged candidate lacks required signing verification")
    installer_sha = sha256(args.file)
    key = (f"dist/helper/objects/{installer_sha}/{platform_id}/"
           f"{stored_name}")
    runtime_package = None
    if args.target_os == "windows":
        if args.runtime_package is None:
            raise SystemExit("Windows candidate requires one .nsis.7z runtime package")
        if not args.runtime_package.name.endswith(".nsis.7z"):
            raise SystemExit("Windows runtime package must end in .nsis.7z")
        if not args.runtime_package.is_file() or \
                args.runtime_package.stat().st_size <= 0:
            raise SystemExit(
                f"Windows runtime package is missing or empty: {args.runtime_package}"
            )
        package_bytes = args.runtime_package.stat().st_size
        if package_bytes >= MAX_NSIS_WEB_PACKAGE_BYTES:
            raise SystemExit(
                "Windows runtime package must be smaller than 4294967295 bytes"
            )
        package_sha = sha256(args.runtime_package)
        package_name, package_content_type = WINDOWS_RUNTIME_PACKAGE
        runtime_package = {
            "key": (f"dist/helper/objects/{package_sha}/{platform_id}/"
                    f"{package_name}"),
            "filename": package_name,
            "content_type": package_content_type,
            "bytes": package_bytes,
            "sha256": package_sha,
        }
    elif args.runtime_package is not None:
        raise SystemExit("macOS candidates must not include a Windows runtime package")
    receipt = {
        "schema": SCHEMA,
        "tag": args.tag,
        "platform": platform_id,
        "key": key,
        "filename": stored_name,
        "download_name": download_name,
        "content_type": content_type,
        "bytes": args.file.stat().st_size,
        "sha256": installer_sha,
        "source": {
            "commit": args.commit,
            "run_id": args.run_id,
            "run_attempt": args.run_attempt,
        },
        "verification": {
            "signing": args.signing_status,
            "notarization": args.notarization_status,
        },
        "runtime_manifest": {
            "filename": f"runtime-manifest-{platform_id}.json",
            "sha256": sha256(args.runtime_manifest),
        },
    }
    if runtime_package is not None:
        receipt["runtime_package"] = runtime_package
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_receipt(path: Path, tag: str) -> dict:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid candidate receipt {path}: {exc}") from exc
    if receipt.get("schema") != SCHEMA or receipt.get("tag") != tag:
        raise SystemExit(f"wrong schema or tag in candidate receipt: {path}")
    platform_id = receipt.get("platform")
    expected = next(
        (item for item in PLATFORMS.values() if item[0] == platform_id), None
    )
    if not expected:
        raise SystemExit(f"unknown platform in candidate receipt: {path}")
    _, stored_name, download_name, content_type = expected
    digest_value = str(receipt.get("sha256", ""))
    expected_key = (f"dist/helper/objects/{digest_value}/{platform_id}/"
                    f"{stored_name}")
    exact = {
        "key": expected_key,
        "filename": stored_name,
        "download_name": download_name,
        "content_type": content_type,
    }
    for field, value in exact.items():
        if receipt.get(field) != value:
            raise SystemExit(f"invalid {field} in candidate receipt: {path}")
    if not isinstance(receipt.get("bytes"), int) or receipt["bytes"] <= 0:
        raise SystemExit(f"invalid byte count in candidate receipt: {path}")
    if not re.fullmatch(r"[a-f0-9]{64}", digest_value):
        raise SystemExit(f"invalid digest in candidate receipt: {path}")
    runtime = receipt.get("runtime_manifest")
    expected_runtime_name = f"runtime-manifest-{platform_id}.json"
    if not isinstance(runtime, dict) or \
            runtime.get("filename") != expected_runtime_name or not re.fullmatch(
                r"[a-f0-9]{64}", str(runtime.get("sha256", ""))
            ):
        raise SystemExit(f"invalid runtime manifest receipt: {path}")
    package = receipt.get("runtime_package")
    if platform_id == "windows-x64":
        package_name, package_content_type = WINDOWS_RUNTIME_PACKAGE
        if not isinstance(package, dict):
            raise SystemExit(f"missing Windows runtime package receipt: {path}")
        package_digest = str(package.get("sha256", ""))
        package_exact = {
            "key": (f"dist/helper/objects/{package_digest}/{platform_id}/"
                    f"{package_name}"),
            "filename": package_name,
            "content_type": package_content_type,
        }
        for field, value in package_exact.items():
            if package.get(field) != value:
                raise SystemExit(
                    f"invalid runtime package {field} in candidate receipt: {path}"
                )
        package_bytes = package.get("bytes")
        if not isinstance(package_bytes, int) or package_bytes <= 0 or \
                package_bytes >= MAX_NSIS_WEB_PACKAGE_BYTES:
            raise SystemExit(f"invalid runtime package byte count: {path}")
        if not re.fullmatch(r"[a-f0-9]{64}", package_digest):
            raise SystemExit(f"invalid runtime package digest: {path}")
    elif "runtime_package" in receipt:
        raise SystemExit(f"macOS receipt includes a Windows runtime package: {path}")
    source = receipt.get("source")
    if not isinstance(source, dict) or not re.fullmatch(
            r"[a-f0-9]{40}", str(source.get("commit", ""))) or not re.fullmatch(
                r"[1-9][0-9]*", str(source.get("run_id", ""))) or not re.fullmatch(
                    r"[1-9][0-9]*", str(source.get("run_attempt", ""))):
        raise SystemExit(f"invalid source provenance in candidate receipt: {path}")
    verification = receipt.get("verification")
    expected_verification = {
        "signing": "verified",
        "notarization": "not-applicable" if platform_id == "windows-x64"
        else "verified",
    }
    if verification != expected_verification:
        raise SystemExit(f"unverified signing receipt: {path}")
    return receipt


def verify_head(args: argparse.Namespace) -> None:
    receipt = load_receipt(args.receipt, args.tag)
    try:
        head = json.loads(args.head.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid R2 HEAD response: {exc}") from exc
    selected = receipt if args.object == "installer" \
        else receipt.get("runtime_package")
    if not isinstance(selected, dict):
        raise SystemExit(
            f"candidate has no {args.object} object to verify"
        )
    metadata = head.get("Metadata") or {}
    if head.get("ContentLength") != selected["bytes"]:
        raise SystemExit("R2 object size does not match candidate receipt")
    if metadata.get("sha256") != selected["sha256"]:
        raise SystemExit("R2 object digest metadata does not match candidate receipt")


def assemble_release(args: argparse.Namespace) -> None:
    tag_match = valid_tag(args.tag)
    paths = sorted(args.receipts.rglob("candidate-*.json"))
    receipts = [load_receipt(path, args.tag) for path in paths]
    runtime_paths = []
    for path, receipt in zip(paths, receipts):
        runtime = path.with_name(receipt["runtime_manifest"]["filename"])
        if not runtime.is_file() or \
                sha256(runtime) != receipt["runtime_manifest"]["sha256"]:
            raise SystemExit(f"runtime manifest does not match receipt: {path}")
        runtime_paths.append(runtime)
    discovered_runtime_paths = set(
        args.receipts.rglob("runtime-manifest-*.json")
    )
    expected_runtime_paths = set(runtime_paths)
    if discovered_runtime_paths != expected_runtime_paths:
        unexpected = sorted(discovered_runtime_paths - expected_runtime_paths)
        missing = sorted(expected_runtime_paths - discovered_runtime_paths)
        details = []
        if unexpected:
            details.append("unexpected: " + ", ".join(map(str, unexpected)))
        if missing:
            details.append("missing: " + ", ".join(map(str, missing)))
        raise SystemExit(
            "release contains an unreferenced or missing runtime manifest"
            + (f" ({'; '.join(details)})" if details else "")
        )
    by_platform = {receipt["platform"]: receipt for receipt in receipts}
    expected_platforms = {item[0] for item in PLATFORMS.values()}
    if len(receipts) != len(expected_platforms) or \
            set(by_platform) != expected_platforms:
        raise SystemExit("release needs exactly one receipt for every platform")
    source_receipts = {
        json.dumps(receipt["source"], sort_keys=True) for receipt in receipts
    }
    if len(source_receipts) != 1:
        raise SystemExit("platform receipts came from different workflow runs")
    source = receipts[0]["source"]
    expected_source = {
        "commit": args.commit,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
    }
    if source != expected_source:
        raise SystemExit("platform receipt provenance does not match this workflow")
    args.output.mkdir(parents=True, exist_ok=True)
    github_assets = []
    for receipt_path, runtime_path in zip(paths, runtime_paths):
        github_assets.extend((
            {
                "kind": "candidate-receipt",
                "path": str(receipt_path),
                "sha256": sha256(receipt_path),
            },
            {
                "kind": "runtime-manifest",
                "path": str(runtime_path),
                "sha256": sha256(runtime_path),
            },
        ))
    (args.output / "github-assets.json").write_text(json.dumps({
        "schema": GITHUB_ASSETS_SCHEMA,
        "assets": github_assets,
    }, indent=2, sort_keys=True) + "\n")
    checksum_lines = []
    for receipt in sorted(receipts, key=lambda item: item["platform"]):
        checksum_lines.append(
            f"{receipt['sha256']}  {receipt['download_name']}"
        )
        checksum_lines.append(
            f"{receipt['runtime_manifest']['sha256']}  "
            f"{receipt['runtime_manifest']['filename']}"
        )
        if receipt["platform"] == "windows-x64":
            package = receipt["runtime_package"]
            checksum_lines.append(
                f"{package['sha256']}  {package['filename']}"
            )
    checksums = args.output / "SHA256SUMS.txt"
    checksums.write_text("\n".join(checksum_lines) + "\n")
    checksum_sha = sha256(checksums)
    checksum_key = f"dist/helper/checksums/{checksum_sha}/SHA256SUMS.txt"
    pointer = {
        "schema": RELEASE_SCHEMA,
        "tag": args.tag,
        "version": args.tag.removeprefix("helper-v"),
        "source": source,
        "checksums": {
            "key": checksum_key,
            "sha256": checksum_sha,
            "bytes": checksums.stat().st_size,
        },
        "platforms": {},
        "verification": {
            receipt["platform"]: receipt["verification"]
            for receipt in receipts
        },
    }
    for receipt in receipts:
        platform_entry = {
            "key": receipt["key"],
            "sha256": receipt["sha256"],
            "bytes": receipt["bytes"],
        }
        if receipt["platform"] == "windows-x64":
            platform_entry["runtime_package"] = dict(
                receipt["runtime_package"]
            )
        pointer["platforms"][receipt["platform"]] = platform_entry
    (args.output / "current.json").write_text(
        json.dumps(pointer, indent=2, sort_keys=True) + "\n"
    )


def emit_github_assets(args: argparse.Namespace) -> None:
    try:
        plan = json.loads(args.plan.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid GitHub asset plan: {exc}") from exc
    assets = plan.get("assets") if isinstance(plan, dict) else None
    if not isinstance(plan, dict) or \
            plan.get("schema") != GITHUB_ASSETS_SCHEMA or \
            not isinstance(assets, list):
        raise SystemExit("GitHub asset plan has the wrong schema")
    if len(assets) != len(PLATFORMS) * 2:
        raise SystemExit("GitHub asset plan must contain exactly six assets")
    expected_kinds = {
        "candidate-receipt": len(PLATFORMS),
        "runtime-manifest": len(PLATFORMS),
    }
    actual_kinds = {kind: 0 for kind in expected_kinds}
    resolved = []
    names = set()
    for item in assets:
        if not isinstance(item, dict) or set(item) != {"kind", "path", "sha256"}:
            raise SystemExit("invalid entry in GitHub asset plan")
        kind = item["kind"]
        if kind not in actual_kinds:
            raise SystemExit("invalid asset kind in GitHub asset plan")
        path = Path(item["path"])
        digest = item["sha256"]
        if not path.is_file() or not re.fullmatch(r"[a-f0-9]{64}", digest) or \
                sha256(path) != digest:
            raise SystemExit(f"GitHub asset no longer matches its plan: {path}")
        if path.name in names:
            raise SystemExit(f"duplicate GitHub asset name: {path.name}")
        names.add(path.name)
        actual_kinds[kind] += 1
        resolved.append(path)
    if actual_kinds != expected_kinds:
        raise SystemExit("GitHub asset plan does not contain three assets of each kind")
    for path in resolved:
        sys.stdout.buffer.write(str(path).encode() + b"\0")


def version_parts(tag: str) -> tuple[tuple[int, int, int], list[str] | None]:
    match = valid_tag(tag)
    core = tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
    suffix = match.group("suffix")
    return core, suffix[1:].split(".") if suffix else None


def compare_versions(left: str, right: str) -> int:
    left_core, left_pre = version_parts(left)
    right_core, right_pre = version_parts(right)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_pre is None or right_pre is None:
        if left_pre is right_pre:
            return 0
        return 1 if left_pre is None else -1
    for left_item, right_item in zip(left_pre, right_pre):
        if left_item == right_item:
            continue
        left_numeric, right_numeric = left_item.isdigit(), right_item.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_item) > int(right_item) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_item > right_item else -1
    if len(left_pre) == len(right_pre):
        return 0
    return 1 if len(left_pre) > len(right_pre) else -1


def guard_promotion(args: argparse.Namespace) -> None:
    candidate = json.loads(args.candidate.read_text())
    if candidate.get("schema") != RELEASE_SCHEMA:
        raise SystemExit("candidate pointer has the wrong schema")
    valid_tag(candidate.get("tag", ""))
    if not args.current.exists() or not args.current.read_text().strip():
        print("promotion allowed: no current release")
        return
    current = json.loads(args.current.read_text())
    if current.get("schema") != RELEASE_SCHEMA:
        raise SystemExit("current pointer has the wrong schema")
    valid_tag(current.get("tag", ""))
    ordering = compare_versions(candidate["tag"], current["tag"])
    if ordering < 0:
        raise SystemExit(
            f"release downgrade blocked: {candidate['tag']} < {current['tag']}"
        )
    same_release = all(
        candidate.get(field) == current.get(field)
        for field in (
            "tag", "version", "source", "checksums", "platforms",
            "verification",
        )
    )
    if ordering == 0 and not same_release:
        raise SystemExit(
            "release version already exists with different provenance or "
            "installer receipts"
        )
    print("promotion allowed")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("candidate")
    candidate.add_argument("--file", type=Path, required=True)
    candidate.add_argument("--runtime-manifest", type=Path, required=True)
    candidate.add_argument("--runtime-package", type=Path)
    candidate.add_argument("--target-os", required=True)
    candidate.add_argument("--arch", required=True)
    candidate.add_argument("--tag", required=True)
    candidate.add_argument("--commit", required=True)
    candidate.add_argument("--run-id", required=True)
    candidate.add_argument("--run-attempt", required=True)
    candidate.add_argument("--signing-status", required=True)
    candidate.add_argument("--notarization-status", required=True)
    candidate.add_argument("--output", type=Path, required=True)
    candidate.set_defaults(run=write_candidate)
    head = commands.add_parser("verify-head")
    head.add_argument("--receipt", type=Path, required=True)
    head.add_argument("--head", type=Path, required=True)
    head.add_argument("--tag", required=True)
    head.add_argument(
        "--object", choices=("installer", "runtime-package"),
        default="installer",
    )
    head.set_defaults(run=verify_head)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--receipts", type=Path, required=True)
    assemble.add_argument("--tag", required=True)
    assemble.add_argument("--commit", required=True)
    assemble.add_argument("--run-id", required=True)
    assemble.add_argument("--run-attempt", required=True)
    assemble.add_argument("--output", type=Path, required=True)
    assemble.set_defaults(run=assemble_release)
    github_assets = commands.add_parser("github-assets")
    github_assets.add_argument("--plan", type=Path, required=True)
    github_assets.set_defaults(run=emit_github_assets)
    guard = commands.add_parser("guard")
    guard.add_argument("--candidate", type=Path, required=True)
    guard.add_argument("--current", type=Path, required=True)
    guard.set_defaults(run=guard_promotion)
    return root


def main() -> None:
    args = parser().parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
