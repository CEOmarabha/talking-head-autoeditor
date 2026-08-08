"""Frozen entry point for the website render Helper.

The Electron shell supplies every runtime path and the user-scoped token via
the child environment. No API key or setup code is written by this process.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def revision_contract_check() -> bool:
    """Prove the frozen daemon contains the executable revision contract."""
    from webapp.render_worker.project_types import (
        ALLOWED_OPS,
        GENERIC_PROFILE_IDS,
        PROJECT_TYPES,
        revision_engine_args,
    )

    expected_ops = {
        "set_edit_style",
        "set_aspect_ratio",
        "set_caption_mode",
        "set_visual_mode",
        "set_edit_profile",
    }
    expected_profiles = (
        "generic_short",
        "generic_long",
        "generic_commercial",
        "generic_podcast",
        "generic_course",
        "generic_custom",
    )
    supported_projects = {
        name for name, contract in PROJECT_TYPES.items()
        if contract.get("supported")
    }
    mapped = revision_engine_args("custom", None, {
        "operations": [
            {"op": "set_edit_style", "style": "short"},
            {"op": "set_aspect_ratio", "aspect": "9x16"},
            {"op": "set_caption_mode", "mode": "sidecar"},
            {"op": "set_visual_mode", "mode": "baseline"},
            {"op": "set_edit_profile", "profile_id": "generic_commercial"},
        ],
    })
    return (
        set(ALLOWED_OPS) == expected_ops
        and tuple(GENERIC_PROFILE_IDS) == expected_profiles
        and supported_projects == {
            "short", "long", "commercial", "podcast", "course", "custom",
        }
        and PROJECT_TYPES.get("clips", {}).get("supported") is False
        and mapped == [
            "--style", "short", "--aspects", "9x16",
            "--profile", "generic_commercial", "--no-burn", "--no-premium",
        ]
    )


def smoke_test() -> int:
    required = {
        "engine": os.environ.get("AUTOEDITOR_ENGINE", ""),
        "ffmpeg": os.environ.get("AUTOEDITOR_FFMPEG", ""),
        "ffprobe": os.environ.get("AUTOEDITOR_FFPROBE", ""),
        "small_model": os.environ.get("AUTOEDITOR_WHISPER_SMALL", ""),
        "medium_model": os.environ.get("AUTOEDITOR_WHISPER_MEDIUM", ""),
        "profiles": os.environ.get("AUTOEDITOR_PROFILES_DIR", ""),
        "fonts": os.environ.get("AUTOEDITOR_BUNDLED_FONTS", ""),
        "ca_bundle": os.environ.get("SSL_CERT_FILE", ""),
        "node": os.environ.get("AUTOEDITOR_NODE", ""),
        "hyperframes_cli": os.environ.get("AUTOEDITOR_HYPERFRAMES_CLI", ""),
        "hyperframes_project": os.environ.get(
            "AUTOEDITOR_HYPERFRAMES_PROJECT", ""),
        "remotion_cli": os.environ.get("AUTOEDITOR_REMOTION_CLI", ""),
        "remotion_project": os.environ.get("AUTOEDITOR_REMOTION_PROJECT", ""),
        "browser": os.environ.get("AUTOEDITOR_BROWSER", ""),
    }
    checks = {name: bool(value) and Path(value).exists()
              for name, value in required.items()}
    try:
        checks["typed_deepseek_revision_contract"] = revision_contract_check()
    except Exception:
        checks["typed_deepseek_revision_contract"] = False
    print(json.dumps({"event": "helper-daemon-smoke", "checks": checks}))
    return 0 if all(checks.values()) else 1


def creative_smoke_test() -> int:
    """Render tiny real assets through the installed creative stack."""
    from autoeditor import premium

    with tempfile.TemporaryDirectory(prefix="autoeditor-creative-smoke-") as raw:
        work = Path(raw)
        premium.BROLL_CACHE = work
        hf_ok = premium._hf_render_graphic(
            "keyword", {"text": "READY"}, 1.2, 320, 568,
            work / "hyperframes-sequence",
        )
        remotion_required = os.environ.get("AUTOEDITOR_REQUIRE_REMOTION") == "1"
        remotion_ok = True
        if remotion_required:
            remotion_ok = bool(premium._remotion_viz(
                {"template": "flow", "title": "READY", "items": ["ONE", "TWO"]},
                2.5, 320, 568,
            ))
        checks = {"hyperframes_render": hf_ok, "remotion_render": remotion_ok}
        print(json.dumps({"event": "helper-creative-smoke", "checks": checks}))
        return 0 if all(checks.values()) else 1


def main() -> None:
    if os.environ.get("AUTOEDITOR_HELPER_SMOKE_TEST") == "1":
        raise SystemExit(smoke_test())
    if os.environ.get("AUTOEDITOR_CREATIVE_SMOKE_TEST") == "1":
        raise SystemExit(creative_smoke_test())
    from webapp.render_worker.render_worker import main as run
    run()


if __name__ == "__main__":
    main()
