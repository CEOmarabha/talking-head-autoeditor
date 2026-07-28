#!/usr/bin/env python3
"""Run one bounded, credentialed DeepSeek V4 creative-contract fixture."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoeditor import premium, providers


FIXTURE_TEXT = """\
Your brain decides what matters before your mouth explains it.
Today I am breaking down three signals: superiority, autonomy, and certainty.
Superiority means you carry value without begging for comparison.
Autonomy means your choices remain yours under pressure.
Certainty means your direction stays clear when the room gets noisy.
First, notice where you ask for permission that nobody required.
Second, remove the explanation you added to calm somebody else.
Third, make the clean decision and let your behavior carry it.
Here is the test.
You quote a project at twelve point five percent above your old rate.
The client pauses.
State the number, stop talking, and let the other person respond.
Use all three signals on the next choice that makes you explain yourself.
"""


def fixture() -> tuple[list[dict], float]:
    tokens = FIXTURE_TEXT.split()
    words = [
        {
            "w": token,
            "s": round(index * 0.42, 3),
            "e": round(index * 0.42 + 0.26, 3),
            "p": 0.99,
        }
        for index, token in enumerate(tokens)
    ]
    return words, float(words[-1]["e"]) + 0.8


def run_live(run_id: str) -> int:
    providers.load_dotenv()
    if not providers.llm_available("deepseek"):
        print(json.dumps({
            "run": run_id,
            "result": "FAIL",
            "reason": "DEEPSEEK_API_KEY is not configured",
        }))
        return 2

    words, duration = fixture()
    edl = premium.deepseek_edl(words, [], duration, style="long")

    if not edl:
        print(json.dumps({
            "run": run_id,
            "result": "FAIL",
            "reason": "director and critic did not produce a valid plan",
        }))
        return 1

    receipt = edl["production_receipt"]
    contract = edl["contract"]
    result = {
        "run": run_id,
        "result": "PASS" if contract["score"] == 100 else "FAIL",
        "model": receipt["model"],
        "reasoning_effort": receipt["reasoning_effort"],
        "score": contract["score"],
        "director_passed": receipt["director_contract_passed"],
        "critic_passed": receipt["critic_contract_passed"],
        "critic_rounds": receipt["critic_rounds_used"],
        "punch_ins": len(edl["punch_ins"]),
        "broll": len(edl["broll"]),
        "graphics": len(edl["graphics"]),
        "validated_plan_sha256": receipt["validated_plan_sha256"],
        "fixture_words": len(words),
        "fixture_duration_seconds": round(duration, 3),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        return run_live(args.run_id)

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--run-id",
        args.run_id,
    ]
    worker = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        output, _ = worker.communicate(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        worker.kill()
        output, _ = worker.communicate()
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        print(json.dumps({
            "run": args.run_id,
            "result": "FAIL",
            "reason": (
                f"DeepSeek smoke worker exceeded {args.timeout} seconds"
            ),
        }))
        return 1

    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    return int(worker.returncode or 0)


if __name__ == "__main__":
    sys.exit(main())
