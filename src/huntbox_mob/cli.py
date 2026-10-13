"""Command-line entrypoint for HuntBox Mob."""

from __future__ import annotations

import argparse
import json

from .discovery import runtime_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="huntbox-mob")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="inspect local runtime prerequisites")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "status":
        result = runtime_status()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

