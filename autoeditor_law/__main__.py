"""Command-line verifier for AutoEditor project archives."""

from __future__ import annotations

import argparse
import json

from .contracts import ContractError, verify_archive


def main() -> int:
    parser = argparse.ArgumentParser(prog="autoeditor-law")
    subcommands = parser.add_subparsers(dest="command", required=True)
    verify = subcommands.add_parser(
        "verify-archive", help="verify a closed project archive"
    )
    verify.add_argument("archive")
    args = parser.parse_args()
    try:
        result = verify_archive(args.archive)
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result.as_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
