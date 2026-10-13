"""Read-only discovery of local mobile analysis capabilities."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Iterable


APPLICATION_ROOTS = (Path("/Applications"), Path.home() / "Applications")


def _first_existing(paths: Iterable[Path]) -> str:
    return str(next((path for path in paths if path.exists()), ""))


def runtime_status() -> Dict[str, object]:
    genymotion = _first_existing(root / "Genymotion.app" for root in APPLICATION_ROOTS)
    simulator = _first_existing(
        root / "Xcode.app/Contents/Developer/Applications/Simulator.app"
        for root in APPLICATION_ROOTS
    )
    tools = {
        name: shutil.which(name) or ""
        for name in ("adb", "xcrun", "frida-ps", "jadx", "apktool")
    }
    return {
        "ok": bool(genymotion and tools["adb"]),
        "mode": "read-only-discovery",
        "android": {"genymotion": genymotion, "adb": tools["adb"]},
        "ios": {"simulator": simulator, "xcrun": tools["xcrun"]},
        "analysis": {
            "frida": tools["frida-ps"],
            "jadx": tools["jadx"],
            "apktool": tools["apktool"],
        },
        "network_requests": 0,
        "device_contacted": False,
    }

