"""Owned Android worker backed by the official Android Emulator and ADB."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence


SDK_CANDIDATES = (
    Path("/opt/homebrew/share/android-commandlinetools"),
    Path.home() / "Library/Android/sdk",
    Path.home() / "Android/Sdk",
    Path(os.environ.get("LOCALAPPDATA", "C:/__missing__")) / "Android/Sdk",
)


def _run(command: Sequence[str], timeout: int = 30, input_text: str | None = None):
    return subprocess.run(
        command, input=input_text, capture_output=True, text=True,
        timeout=timeout, check=False,
    )


@dataclass(frozen=True)
class AndroidSdk:
    root: Path
    emulator: Path
    adb: Path
    avdmanager: Path
    sdkmanager: Path

    @classmethod
    def discover(cls) -> "AndroidSdk | None":
        roots = []
        for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]).expanduser())
        roots.extend(SDK_CANDIDATES)
        for root in roots:
            emulator = root / ("emulator/emulator.exe" if platform.system() == "Windows" else "emulator/emulator")
            adb = root / ("platform-tools/adb.exe" if platform.system() == "Windows" else "platform-tools/adb")
            bin_dir = root / "cmdline-tools/latest/bin"
            suffix = ".bat" if platform.system() == "Windows" else ""
            avdmanager = bin_dir / f"avdmanager{suffix}"
            sdkmanager = bin_dir / f"sdkmanager{suffix}"
            if adb.exists() and avdmanager.exists() and sdkmanager.exists():
                return cls(root, emulator, adb, avdmanager, sdkmanager)
        return None


class AndroidWorker:
    avd_name = "huntmob_api35_arm64"
    package = "system-images;android-35;default;arm64-v8a"
    serial = "emulator-5556"
    port = "5556"

    def __init__(self, sdk: AndroidSdk | None = None) -> None:
        self.sdk = sdk or AndroidSdk.discover()

    def prerequisites(self) -> Dict[str, object]:
        if not self.sdk:
            return {"ready": False, "reason": "Android SDK command-line tools not found"}
        image = self.sdk.root / "system-images/android-35/default/arm64-v8a/system.img"
        return {
            "ready": self.sdk.emulator.exists() and image.exists(),
            "sdk_root": str(self.sdk.root),
            "emulator": str(self.sdk.emulator),
            "image": str(image),
            "accelerator": {"Darwin": "hvf", "Linux": "kvm", "Windows": "whpx"}.get(platform.system(), "unknown"),
        }

    def create(self) -> Dict[str, object]:
        prerequisites = self.prerequisites()
        if not prerequisites["ready"]:
            return {"ok": False, "blocked": True, "reason": prerequisites.get("reason", "runtime packages missing")}
        listed = _run((str(self.sdk.emulator), "-list-avds"))
        if self.avd_name in listed.stdout.splitlines():
            return {"ok": True, "created": False, "avd": self.avd_name}
        result = _run(
            (str(self.sdk.avdmanager), "create", "avd", "--force", "--name", self.avd_name,
             "--package", self.package, "--device", "medium_phone"),
            timeout=120, input_text="no\n",
        )
        return {"ok": result.returncode == 0, "created": result.returncode == 0, "avd": self.avd_name, "error": result.stderr.strip()}

    def status(self) -> Dict[str, object]:
        if not self.sdk:
            return {"state": "unavailable", "serial": self.serial}
        result = _run((str(self.sdk.adb), "devices"))
        state = "offline"
        for line in result.stdout.splitlines():
            if line.startswith(f"{self.serial}\t"):
                state = line.split("\t", 1)[1].strip()
        payload: Dict[str, object] = {"state": state, "serial": self.serial, "avd": self.avd_name}
        if state == "device":
            props = {}
            for key in ("ro.build.version.release", "ro.build.version.sdk", "ro.product.cpu.abi", "sys.boot_completed"):
                value = _run((str(self.sdk.adb), "-s", self.serial, "shell", "getprop", key)).stdout.strip()
                props[key] = value
            payload["properties"] = props
        return payload

    def start(self, timeout: int = 180) -> Dict[str, object]:
        existing = self.status()
        if existing["state"] == "device" and existing.get("properties", {}).get("sys.boot_completed") == "1":
            return {"ok": True, "started": False, **existing}
        created = self.create()
        if not created["ok"]:
            return created
        log_dir = Path.home() / ".huntmob/logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = (log_dir / "android-worker.log").open("a", encoding="utf-8")
        command = (
            str(self.sdk.emulator), f"@{self.avd_name}", "-no-window", "-no-audio",
            "-no-boot-anim", "-gpu", "auto", "-port", self.port, "-no-snapshot-save",
        )
        subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.status()
            if current["state"] == "device" and current.get("properties", {}).get("sys.boot_completed") == "1":
                return {"ok": True, "started": True, **current}
            time.sleep(2)
        return {"ok": False, "blocked": True, "reason": "Android boot timed out", **self.status()}

    def stop(self) -> Dict[str, object]:
        if not self.sdk:
            return {"ok": False, "reason": "Android SDK unavailable"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "emu", "kill"))
        return {"ok": result.returncode == 0, "state": "stopping", "error": result.stderr.strip()}

    def install_and_launch(self, apk: Path, package_id: str) -> Dict[str, object]:
        if not apk.is_file() or apk.suffix.lower() != ".apk":
            return {"ok": False, "blocked": True, "reason": "an existing APK is required"}
        if self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        install = _run((str(self.sdk.adb), "-s", self.serial, "install", "-r", str(apk)), timeout=180)
        if install.returncode != 0:
            return {"ok": False, "blocked": True, "reason": "APK installation failed", "error": install.stderr.strip()}
        launch = _run((str(self.sdk.adb), "-s", self.serial, "shell", "monkey", "-p", package_id, "-c", "android.intent.category.LAUNCHER", "1"))
        return {"ok": launch.returncode == 0, "package_id": package_id, "installed": True, "launched": launch.returncode == 0}

    def screenshot(self) -> bytes:
        if not self.sdk or self.status()["state"] != "device":
            return b""
        result = subprocess.run(
            (str(self.sdk.adb), "-s", self.serial, "exec-out", "screencap", "-p"),
            capture_output=True, timeout=15, check=False,
        )
        return result.stdout if result.returncode == 0 and result.stdout.startswith(b"\x89PNG") else b""
