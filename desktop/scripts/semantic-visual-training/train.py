"""Parameter-efficient training entry that refuses qualification labels.

This script does not invent a model, download weights, or tune against the
sealed qualification split. It only starts when a development-only corpus and
sufficient local hardware are present.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--split-report", required=True)
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    inventory = _load(Path(args.inventory))
    split_report = _load(Path(args.split_report))
    assessment = inventory.get("assessment") or {}
    if assessment.get("can_parameter_efficient_train") is not True:
        reasons = assessment.get("blocking_reasons") or ["hardware floor not met"]
        print("training blocked: " + "; ".join(reasons), file=sys.stderr)
        return 2
    if split_report.get("disjoint") is not True:
        print("training blocked: development and qualification splits overlap", file=sys.stderr)
        return 3
    if int(split_report.get("qualification_count") or 0) > 0:
        print(
            "training blocked: qualification records are visible; "
            "copy only the development split into the trainer workspace",
            file=sys.stderr,
        )
        return 4
    if int(split_report.get("development_count") or 0) < 1:
        print("training blocked: no development labels exist", file=sys.stderr)
        return 5
    if not (workspace / "labels").exists():
        print("training blocked: workspace has no labels directory", file=sys.stderr)
        return 6
    print(
        "training is allowed only after a real PEFT trainer is attached; "
        "no weights were written in this run",
        file=sys.stderr,
    )
    return 7


if __name__ == "__main__":
    raise SystemExit(main())
