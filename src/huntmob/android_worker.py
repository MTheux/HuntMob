"""Owned Android worker backed by the official Android Emulator and ADB."""

from __future__ import annotations

import os
import platform
import hashlib
import shutil
import subprocess
import time
import tempfile
import zipfile
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence


PACKAGE_ID = __import__("re").compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


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

    def reboot(self, timeout: int = 180) -> Dict[str, object]:
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "reboot"))
        if result.returncode != 0:
            return {"ok": False, "blocked": True, "reason": "reboot command failed"}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.status()
            if status["state"] == "device" and status.get("properties", {}).get("sys.boot_completed") == "1":
                return {"ok": True, "state": "device", "rebooted": True}
            time.sleep(2)
        return {"ok": False, "blocked": True, "reason": "reboot timed out"}

    def destroy(self, timeout: int = 45) -> Dict[str, object]:
        """Delete only the fixed HuntMob AVD after stopping its emulator."""
        if not self.sdk:
            return {"ok": False, "reason": "Android SDK unavailable"}
        if self.status()["state"] == "device":
            self.stop()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self.status()["state"] != "offline":
                time.sleep(1)
        result = _run((str(self.sdk.avdmanager), "delete", "avd", "--name", self.avd_name), timeout=60)
        deleted = result.returncode == 0 or "does not exist" in (result.stderr + result.stdout).lower()
        return {"ok": deleted, "state": "destroyed" if deleted else "error", "error": "" if deleted else result.stderr.strip()}

    def install_and_launch(self, apk: Path, package_id: str, *, legacy_sdk: bool = False) -> Dict[str, object]:
        if not PACKAGE_ID.fullmatch(package_id):
            return {"ok": False, "reason": "invalid package ID"}
        if not apk.is_file() or apk.suffix.lower() != ".apk":
            return {"ok": False, "blocked": True, "reason": "an existing APK is required"}
        if self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        flags = ("--bypass-low-target-sdk-block",) if legacy_sdk else ()
        install = _run((str(self.sdk.adb), "-s", self.serial, "install", "-r", *flags, str(apk)), timeout=180)
        if install.returncode != 0:
            details = (install.stderr + "\n" + install.stdout).strip()
            failure = __import__("re").search(r"Failure \[(.*?)\]", details, __import__("re").S)
            reason = failure[1] if failure else "APK installation failed"
            return {"ok": False, "blocked": True, "reason": reason, "error": details}
        resolved = _run((str(self.sdk.adb), "-s", self.serial, "shell", "cmd", "package", "resolve-activity", "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", package_id))
        component = next((line.strip() for line in reversed(resolved.stdout.splitlines()) if line.strip().startswith(package_id + "/")), "")
        if not component:
            return {"ok": False, "installed": True, "launched": False, "package_id": package_id, "reason": "APK installed but no launcher activity was found"}
        launch = _run((str(self.sdk.adb), "-s", self.serial, "shell", "am", "start", "-W", "-n", component))
        launched = launch.returncode == 0 and "Error:" not in launch.stdout + launch.stderr
        return {"ok": launched, "package_id": package_id, "installed": True, "launched": launched, "reason": "" if launched else (launch.stderr + launch.stdout).strip()}

    def upload_and_launch(self, apk: Path, *, legacy_sdk: bool = False) -> Dict[str, object]:
        if not self.sdk:
            return {"ok": False, "reason": "Android SDK unavailable"}
        candidates = sorted((self.sdk.root / "build-tools").glob("*/aapt*"))
        aapt = next((path for path in candidates if path.name in {"aapt", "aapt.exe"}), None)
        if not aapt:
            return {"ok": False, "reason": "Android build-tools (aapt) required to detect APK package"}
        metadata = _run((str(aapt), "dump", "badging", str(apk)))
        match = __import__("re").search(r"package: name='([^']+)'", metadata.stdout)
        if metadata.returncode or not match or not PACKAGE_ID.fullmatch(match[1]):
            return {"ok": False, "reason": "invalid APK or unreadable package metadata"}
        started = self.start()
        if not started.get("ok"):
            return started
        return self.install_and_launch(apk, match[1], legacy_sdk=legacy_sdk)

    def device_input(self, payload: dict) -> Dict[str, object]:
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "reason": "device is not online"}
        action = payload.get("action")
        if action == "back":
            command = ("keyevent", "4")
        elif action == "text":
            value = str(payload.get("text", ""))
            if not value or len(value) > 256 or not __import__("re").fullmatch(r"[A-Za-z0-9 @._+:/-]+", value):
                return {"ok": False, "reason": "Use ASCII text up to 256 characters"}
            command = ("text", value.replace(" ", "%s"))
        elif action in {"tap", "swipe"}:
            size = _run((str(self.sdk.adb), "-s", self.serial, "shell", "wm", "size")).stdout
            matches = __import__("re").findall(r"(\d+)x(\d+)", size)
            if not matches:
                return {"ok": False, "reason": "display size unavailable"}
            width, height = map(int, matches[-1])
            try:
                points = [float(payload[key]) for key in (("x", "y") if action == "tap" else ("x", "y", "end_x", "end_y"))]
                if not all(0 <= point <= 1 for point in points):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "reason": "invalid display coordinates"}
            coords = [str(min((width if index % 2 == 0 else height) - 1, int(point * (width if index % 2 == 0 else height)))) for index, point in enumerate(points)]
            command = (action, *coords, *(("300",) if action == "swipe" else ()))
        else:
            return {"ok": False, "reason": "unsupported input action"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "input", *command))
        return {"ok": result.returncode == 0}

    def screenshot(self) -> bytes:
        if not self.sdk or self.status()["state"] != "device":
            return b""
        result = subprocess.run(
            (str(self.sdk.adb), "-s", self.serial, "exec-out", "screencap", "-p"),
            capture_output=True, timeout=15, check=False,
        )
        return result.stdout if result.returncode == 0 and result.stdout.startswith(b"\x89PNG") else b""

    def app_files(self, package_id: str) -> Dict[str, object]:
        """List APK entries and the authorized app sandbox without changing it."""
        if not PACKAGE_ID.fullmatch(package_id):
            return {"ok": False, "blocked": True, "reason": "invalid package ID"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        installed = _run((str(self.sdk.adb), "-s", self.serial, "shell", "pm", "path", package_id))
        apk_paths = [line.removeprefix("package:").strip() for line in installed.stdout.splitlines() if line.startswith("package:")]
        if installed.returncode != 0 or not apk_paths:
            return {"ok": False, "blocked": True, "reason": "authorized package is not installed"}

        apk_entries: List[Dict[str, object]] = []
        with tempfile.TemporaryDirectory(prefix="huntmob-apk-") as directory:
            for index, remote in enumerate(apk_paths[:8]):
                local = Path(directory) / f"split-{index}.apk"
                pulled = _run((str(self.sdk.adb), "-s", self.serial, "pull", remote, str(local)), timeout=180)
                if pulled.returncode != 0 or not local.is_file():
                    continue
                try:
                    with zipfile.ZipFile(local) as archive:
                        for item in archive.infolist()[:5000]:
                            apk_entries.append({"path": item.filename, "size": item.file_size, "split": Path(remote).name})
                except zipfile.BadZipFile:
                    continue

        sandbox = _run(
            (str(self.sdk.adb), "-s", self.serial, "shell", "run-as", package_id,
             "find", ".", "-maxdepth", "5", "-print"), timeout=30,
        )
        sandbox_paths = [line.strip() for line in sandbox.stdout.splitlines() if line.strip()][:5000]
        sandbox_ready = sandbox.returncode == 0
        return {
            "ok": True,
            "package_id": package_id,
            "apk": {"paths": apk_paths, "entries": apk_entries, "truncated": len(apk_entries) >= 5000},
            "sandbox": {
                "root": f"/data/user/0/{package_id}",
                "alias": f"/data/data/{package_id}",
                "accessible": sandbox_ready,
                "mode": "run-as",
                "entries": sandbox_paths,
                "reason": "" if sandbox_ready else "run-as denied; a debuggable or explicitly prepared HuntMob lab build is required",
            },
        }

    def installed_apps(self) -> Dict[str, object]:
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online", "apps": []}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "pm", "list", "packages", "-3", "-f"))
        apps = []
        for line in result.stdout.splitlines():
            if not line.startswith("package:") or "=" not in line:
                continue
            apk_path, package_id = line.removeprefix("package:").rsplit("=", 1)
            if PACKAGE_ID.fullmatch(package_id):
                apps.append({"package_id": package_id, "apk_path": apk_path})
        return {"ok": result.returncode == 0, "apps": sorted(apps, key=lambda item: item["package_id"])}

    def proxy_status(self, port: int = 8080) -> Dict[str, object]:
        configured = ""
        if self.sdk and self.status()["state"] == "device":
            configured = _run((str(self.sdk.adb), "-s", self.serial, "shell", "settings", "get", "global", "http_proxy")).stdout.strip()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                listening = True
        except OSError:
            listening = False
        return {"configured": configured not in {"", ":0", "null"}, "device_proxy": configured, "listener": listening, "host_port": port}

    def configure_proxy(self, port: int = 8080) -> Dict[str, object]:
        if not 1024 <= port <= 65535:
            return {"ok": False, "blocked": True, "reason": "proxy port must be between 1024 and 65535"}
        status = self.proxy_status(port)
        if not status["listener"]:
            return {"ok": False, "blocked": True, "reason": f"no proxy listener is available on 127.0.0.1:{port}"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        route = f"10.0.2.2:{port}"
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "settings", "put", "global", "http_proxy", route))
        return {"ok": result.returncode == 0, "device_proxy": route, "listener": True}

    def clear_proxy(self) -> Dict[str, object]:
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "settings", "put", "global", "http_proxy", ":0"))
        return {"ok": result.returncode == 0, "device_proxy": ":0"}

    def start_managed_proxy(self, port: int = 8080) -> Dict[str, object]:
        """Start a local mitmweb listener and route only the owned emulator to it."""
        if not 1024 <= port <= 65534:
            return {"ok": False, "blocked": True, "reason": "proxy port must be between 1024 and 65534"}
        executable = shutil.which("mitmweb")
        if not executable:
            return {"ok": False, "blocked": True, "reason": "mitmweb is not installed"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        if not self.proxy_status(port)["listener"]:
            run_dir = Path.home() / ".huntmob" / "run"
            run_dir.mkdir(parents=True, exist_ok=True)
            log = (run_dir / "proxy.log").open("a", encoding="utf-8")
            command = (
                executable, "--listen-host", "0.0.0.0", "--listen-port", str(port),
                "-s", str(Path(__file__).with_name("network_capture.py")),
                "--web-host", "127.0.0.1", "--web-port", str(port + 1),
                "--set", "block_global=false",
            )
            subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and not self.proxy_status(port)["listener"]:
                time.sleep(0.25)
        configured = self.configure_proxy(port)
        if not configured.get("ok"):
            return configured
        return {
            **configured,
            "managed": True,
            "web_url": f"http://127.0.0.1:{port + 1}",
            "ca_path": str(Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"),
            "ca_installed": False,
        }

    def prepare_reverse(self, package_id: str) -> Dict[str, object]:
        """Pull an installed APK and decompile it into a package-scoped workspace."""
        if not PACKAGE_ID.fullmatch(package_id):
            return {"ok": False, "blocked": True, "reason": "invalid package ID"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        installed = _run((str(self.sdk.adb), "-s", self.serial, "shell", "pm", "path", package_id))
        apk_paths = [line.removeprefix("package:").strip() for line in installed.stdout.splitlines() if line.startswith("package:")]
        if installed.returncode != 0 or not apk_paths:
            return {"ok": False, "blocked": True, "reason": "authorized package is not installed"}
        jadx = shutil.which("jadx")
        if not jadx:
            return {"ok": False, "blocked": True, "reason": "jadx is not installed"}
        workspace = Path.home() / ".huntmob" / "workspaces" / package_id
        workspace.mkdir(parents=True, exist_ok=True)
        base_apk = workspace / "base.apk"
        pulled = _run((str(self.sdk.adb), "-s", self.serial, "pull", apk_paths[0], str(base_apk)), timeout=180)
        if pulled.returncode != 0 or not base_apk.is_file():
            return {"ok": False, "blocked": True, "reason": "APK pull failed"}
        output = workspace / "jadx"
        decoded = _run((jadx, "--output-dir", str(output), str(base_apk)), timeout=300)
        if decoded.returncode != 0:
            return {"ok": False, "blocked": True, "reason": "JADX analysis failed", "error": decoded.stderr[-1000:]}
        files = [str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()][:5000]
        digest = hashlib.sha256(base_apk.read_bytes()).hexdigest()
        return {"ok": True, "package_id": package_id, "sha256": digest, "workspace": str(workspace), "files": files, "truncated": len(files) >= 5000}
