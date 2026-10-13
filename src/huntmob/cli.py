"""Command-line entrypoint for HuntMob."""

from __future__ import annotations

import argparse
import json

from .discovery import runtime_status
from .providers import provider_catalog
from .contracts import Platform
from .routing import select_runtime
from .capabilities import capability_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="huntmob")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="inspect local runtime prerequisites")
    commands.add_parser("providers", help="inspect local and optional runtime providers")
    commands.add_parser("capabilities", help="show the provider-neutral lab contract")
    plan = commands.add_parser("plan", help="select a runtime without provisioning it")
    plan.add_argument("platform", choices=("android", "ios"))
    plan.add_argument("--controller-os", choices=("darwin", "windows", "linux"))
    plan.add_argument("--privileged-ios", action="store_true")
    plan.add_argument("--physical-hardware", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "status":
        result = runtime_status()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 2
    if args.command == "providers":
        print(json.dumps(provider_catalog(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "capabilities":
        print(json.dumps(capability_catalog(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "plan":
        result = select_runtime(
            Platform(args.platform),
            controller_os=args.controller_os,
            privileged_ios=args.privileged_ios,
            physical_hardware=args.physical_hardware,
        )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

