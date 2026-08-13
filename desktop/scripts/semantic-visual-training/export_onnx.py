"""Export a trained candidate only after development-split training exists."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    checkpoint = Path(args.checkpoint)
    if not checkpoint.exists():
        print("export blocked: trained checkpoint is absent", file=sys.stderr)
        return 2
    print(
        "export blocked: attach the pinned Transformers.js/ONNX exporter "
        f"after a real development-split checkpoint exists at {checkpoint}",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
