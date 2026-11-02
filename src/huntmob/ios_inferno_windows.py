"""Read-only readiness probe for an experimental Inferno Windows worker."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Mapping


def _regular_executable(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def snapshot(*, system: str | None = None, machine: str | None = None,
             environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Describe host prerequisites without installing packages or booting firmware."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    environ = dict(os.environ if environ is None else environ)
    result: dict[str, object] = {
        "provider": "inferno",
        "platform": "ios",
        "host": "windows",
        "state": "unavailable",
        "build_supported": False,
        "engine_compiled": False,
        "runtime_validated": False,
        "springboard_validated": False,
        "ipa_execution_validated": False,
        "network_requests": 0,
        "firmware_included": False,
        "modes": [],
        "limitations": [
            "Experimental research worker; not an Apple Simulator replacement.",
            "Apple firmware must be supplied and licensed by the operator.",
            "A compiled engine does not prove T8030 boot, SpringBoard, or IPA execution.",
        ],
    }
    if system != "Windows":
        result["reason"] = "This probe is only for a native Windows worker."
        return result
    if machine not in {"amd64", "x86_64", "arm64", "aarch64"}:
        result["reason"] = "Inferno Windows worker requires a 64-bit host."
        return result

    modes: list[dict[str, object]] = []
    roots = []
    if environ.get("MSYS2_ROOT"):
        roots.append(Path(environ["MSYS2_ROOT"]))
    roots.extend((Path("C:/msys64"), Path("C:/tools/msys64")))
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        bash = root / "usr/bin/bash.exe"
        if _regular_executable(bash):
            modes.append({"id": "native-msys2", "ready": True,
                          "shell": str(bash), "root": str(root)})
            break

    wsl = shutil.which("wsl.exe", path=environ.get("PATH"))
    if wsl:
        modes.append({"id": "wsl2", "ready": True, "command": wsl,
                      "experimental_apfs_preparation": True})

    local = environ.get("LOCALAPPDATA")
    if local:
        result["workspace"] = str(Path(local) / "HuntMob/research/Inferno")
        result["receipt"] = str(Path(local) / "HuntMob/research/ios-engine/build-receipt.json")
    result["modes"] = modes
    result["build_supported"] = bool(modes)
    result["state"] = "build-required" if modes else "toolchain-required"
    result["reason"] = (
        "Windows toolchain detected; compile and probe the pinned engine before boot validation."
        if modes else
        "Install an approved MSYS2 or WSL2 toolchain, then rerun this read-only probe."
    )
    return result
