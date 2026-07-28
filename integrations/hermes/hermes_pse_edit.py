#!/usr/bin/env python3
"""Live entry point for the canonical tested talking-head auto-editor."""

from __future__ import annotations

import os
import sys
from pathlib import Path


POINTER = (
    Path.home()
    / "cinematic-autopilot"
    / "tools"
    / ".talking-head-autoeditor-root"
)
if os.environ.get("AUTOEDITOR_REPO"):
    CANONICAL_ROOT = Path(os.environ["AUTOEDITOR_REPO"])
elif POINTER.exists():
    CANONICAL_ROOT = Path(POINTER.read_text().strip())
else:
    CANONICAL_ROOT = Path.home() / "Desktop" / "talking-head-autoeditor"
CANONICAL_ROOT = CANONICAL_ROOT.expanduser().resolve()

if not (CANONICAL_ROOT / "autoeditor" / "pipeline.py").exists():
    raise RuntimeError(
        "canonical talking-head-autoeditor checkout is missing at "
        f"{CANONICAL_ROOT}. Run make install from the repository or set "
        "AUTOEDITOR_REPO."
    )
if str(CANONICAL_ROOT) not in sys.path:
    sys.path.insert(0, str(CANONICAL_ROOT))

from autoeditor.pipeline import main  # noqa: E402


if __name__ == "__main__":
    main()
