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
