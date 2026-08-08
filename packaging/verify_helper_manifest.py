#!/usr/bin/env python3
"""Verify installed Helper resources against their signed manifest."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


COMPONENTS = (
    "helper", "engine", "bin", "lib", "models", "profiles", "fonts",
    "certs", "node", "creative-runtime", "browser", "creative", "licenses",
)
REQUIRED_LOCAL_CAPABILITIES = {
    "frozen_python_engine", "ffmpeg", "ffprobe", "h264", "aac",
    "faster_whisper_small", "faster_whisper_medium",
    "in_process_low_speech_cutter", "typed_deepseek_revision_contract",
    "node", "hyperframes", "remotion",
    "chrome_headless_shell", "fonts", "certificate_bundle",
    "creator_profiles",
}


def _load_generator():
    source = Path(__file__).with_name("generate_helper_manifest.py")
    spec = importlib.util.spec_from_file_location("helper_manifest_generator", source)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load manifest generator: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--expected-manifest", type=Path, required=True)
    parser.add_argument("--target-os", required=True)
    parser.add_argument("--target-arch", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    manifest_path = args.resources / "runtime-manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        expected_bytes = args.expected_manifest.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read runtime manifest: {exc}") from exc
    if manifest_bytes != expected_bytes:
        raise SystemExit("packaged runtime manifest differs from the staged receipt")
    if manifest.get("schema") != "autoeditor-helper-runtime/v1":
        raise SystemExit("unsupported runtime manifest schema")
    if manifest.get("target") != {
            "os": args.target_os, "arch": args.target_arch}:
        raise SystemExit("runtime manifest target does not match this artifact")
    if manifest.get("version") != args.version:
        raise SystemExit("runtime manifest version does not match this artifact")
    capabilities = manifest.get("required_local_capabilities")
    if not isinstance(capabilities, list):
        raise SystemExit("runtime manifest has no local capability contract")
    missing_capabilities = sorted(
        REQUIRED_LOCAL_CAPABILITIES - set(capabilities)
    )
    if missing_capabilities:
        raise SystemExit(
            "runtime manifest is missing required local capabilities: "
            + ", ".join(missing_capabilities)
        )
    expected_components = manifest.get("components")
    if not isinstance(expected_components, dict):
        raise SystemExit("runtime manifest has no component receipts")

    generator = _load_generator()
    failures = []
    for name in COMPONENTS:
        root = args.resources / name
        expected = expected_components.get(name)
        if not root.is_dir():
            failures.append(f"{name}: component directory is missing")
            continue
        if not isinstance(expected, dict):
            failures.append(f"{name}: manifest receipt is missing")
            continue
        actual = generator.directory_receipt(root)
        if actual != expected:
            failures.append(
                f"{name}: expected {expected}, installed {actual}"
            )
    extras = sorted(set(expected_components) - set(COMPONENTS))
    if extras:
        failures.append(f"unexpected manifest components: {', '.join(extras)}")
    if failures:
        raise SystemExit("runtime manifest verification failed:\n" +
                         "\n".join(f"- {failure}" for failure in failures))
    print(f"runtime manifest verified: {len(COMPONENTS)} components")


if __name__ == "__main__":
    main()
