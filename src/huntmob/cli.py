"""Command-line entrypoint for HuntMob."""

from __future__ import annotations

import argparse
import json

from .discovery import runtime_status
from .providers import provider_catalog
from .contracts import Platform
from .routing import select_runtime
from .capabilities import capability_catalog
from .ui import serve
from .runtime_provisioning import DeviceRecipe, provision_plan
from .android_worker import AndroidWorker
from .bootstrap import bootstrap_android


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
    ui = commands.add_parser("ui", help="serve the HuntMob workbench")
    ui.add_argument("--bind", default="127.0.0.1")
    ui.add_argument("--port", default=8090, type=int)
    ui.add_argument("--authorized-remote", action="store_true")
    runtime_plan = commands.add_parser(
        "runtime-plan", help="plan an owned HuntMob Android device without creating it"
    )
    runtime_plan.add_argument("name")
    runtime_plan.add_argument("--api", type=int, default=35)
    runtime_plan.add_argument("--arch", choices=("arm64", "x86_64"), default="arm64")
    runtime_plan.add_argument("--worker-os", choices=("darwin", "windows", "linux"))
    android = commands.add_parser("android", help="manage the owned headless Android worker")
    android.add_argument("action", choices=("status", "create", "start", "stop"))
    android.add_argument("--authorized", action="store_true")
    android.add_argument("--approve", action="store_true")
    bootstrap = commands.add_parser("bootstrap", help="prepare a platform-appropriate HuntMob worker")
    bootstrap.add_argument("--install", action="store_true", help="install missing Android runtime packages when SDK tools already exist")
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
    if args.command == "ui":
        serve(args.bind, args.port, authorized_remote=args.authorized_remote)
        return 0
    if args.command == "runtime-plan":
        result = provision_plan(
            DeviceRecipe(args.name, args.api, args.arch), args.worker_os
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 2
    if args.command == "android":
        worker = AndroidWorker()
        if args.action == "status":
            result = worker.status()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if not args.authorized or not args.approve:
            print(json.dumps({"ok": False, "blocked": True, "reason": "--authorized and --approve are required"}, indent=2))
            return 2
        result = getattr(worker, args.action)()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.command == "bootstrap":
        result = bootstrap_android(install=args.install)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

