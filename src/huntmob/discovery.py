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
        for name in ("adb", "xcrun", "frida-ps", "apktool")
    }
    from .android_worker import AndroidWorker
    android=AndroidWorker().prerequisites()
    return {
        "ok": bool(android.get('ready')),
        "mode": "read-only-discovery",
        "android": {"genymotion": genymotion, "adb": tools["adb"],"worker":android},
        "ios": {"simulator": simulator, "xcrun": tools["xcrun"]},
        "analysis": {
            "frida": tools["frida-ps"],
            "embedded_analysis": __import__("huntmob.analysis_core", fromlist=["EmbeddedAnalysis"]).EmbeddedAnalysis().status(),
            "apktool": tools["apktool"],
        },
        "network_requests": 0,
        "device_contacted": False,
    }

