"""Read-only runtime provider probes used by the HuntMob control plane."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence

from .android_worker import AndroidWorker


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    platform: str
    kind: str
    installed: bool
    ready: bool
    version: str = ""
    instances: int = 0
    limitations: tuple[str, ...] = ()
    error: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class HuntMobRuntimeProvider:
    """Probe only independently installed components for the HuntMob runtime."""

    def probe(self) -> ProviderStatus:
        worker = AndroidWorker()
        prerequisites = worker.prerequisites()
        ready = bool(prerequisites.get("ready"))
        missing = () if ready else (str(prerequisites.get("reason", "Android Emulator and AOSP image are required")),)
        return ProviderStatus(
            "huntmob-runtime",
            "android",
            "owned-local-worker",
            worker.sdk is not None,
            ready,
            "clean-room-v0",
            1 if worker.status().get("state") == "device" else 0,
            missing,
            "" if ready else "HuntMob runtime dependencies are incomplete",
        )


def huntmob_runtime() -> Dict[str, object]:
    worker = AndroidWorker()
    prerequisites = worker.prerequisites()
    worker_status = worker.status()
    online = worker_status.get("state") == "device" and worker_status.get("properties", {}).get("sys.boot_completed") == "1"
    props = worker_status.get("properties", {})
    devices = []
    if online:
        devices.append({
            "uuid": worker.avd_name,
            "name": "HuntMob API 35",
            "state": "on",
            "adb_serial": worker.serial,
            "android_version": props.get("ro.build.version.release", "unknown"),
            "api": int(props.get("ro.build.version.sdk", "0") or 0),
            "architecture": props.get("ro.product.cpu.abi", "unknown"),
            "biometrics": {
                "provider": "huntmob-runtime", "supported": True,
                "transport": "android-emulator-console",
                "reason": "Owned Android Emulator fixture channel",
            },
        })
    return {
        "provider": "huntmob-runtime",
        "state": "online" if online else ("worker-ready" if prerequisites.get("ready") else "build-required"),
        "ready": bool(prerequisites.get("ready")),
        "devices": devices,
        "components": {
            "hypervisor": "qemu with HVF/KVM/WHPX",
            "guest": "HuntMob AOSP image",
            "device_bridge": "ADB",
            "display": "WebRTC worker stream",
            "biometrics": "HuntMob virtual biometric HAL",
            "camera": "HuntMob virtual camera HAL",
        },
        "limitations": [] if prerequisites.get("ready") else [prerequisites.get("reason", "runtime dependencies incomplete")],
        "reference_only": ["genymotion"],
    }


class GenymotionProvider:
    """Probe Genymotion Desktop without starting or changing a device."""

    executable = Path("/Applications/Genymotion.app/Contents/MacOS/gmtool")

    def probe(self, runner: CommandRunner = _run) -> ProviderStatus:
        if not self.executable.exists():
            return ProviderStatus("genymotion", "android", "local", False, False)
        version_result = runner((str(self.executable), "version"))
        list_result = runner(
            (str(self.executable), "--format", "json", "admin", "list")
        )
        version = version_result.stdout.strip().replace("\n", "; ")
        error = (version_result.stderr or list_result.stderr).strip()
        instances = 0
        if list_result.returncode == 0:
            try:
                inventory = json.loads(list_result.stdout)
                instances = len(inventory.get("instances", inventory.get("devices", [])))
            except (json.JSONDecodeError, AttributeError, TypeError):
                error = "gmtool returned invalid device inventory JSON"
        return ProviderStatus(
            "genymotion",
            "android",
            "local",
            True,
            version_result.returncode == 0 and list_result.returncode == 0,
            version,
            instances,
            ("Android only", "device creation requires an explicit approval gate"),
            error,
        )

    def inventory(self, runner: CommandRunner = _run) -> List[Dict[str, object]]:
        """Return the real gmtool inventory without starting or changing a VM."""
        if not self.executable.exists():
            return []
        result = runner((str(self.executable), "--format", "json", "admin", "list"))
        if result.returncode != 0:
            return []
        try:
            payload = json.loads(result.stdout)
            instances = payload.get("instances", payload.get("devices", []))
            return list(instances) if isinstance(instances, list) else list(instances.values())
        except (json.JSONDecodeError, AttributeError, TypeError):
            return []


class AndroidBiometricProbe:
    """Read-only Android biometric capability probe.

    Genymotion exposes biometric outcomes through its own widget. HuntMob only
    enables those controls when Android advertises a fingerprint implementation;
    it never reports a fixture as injected when the guest cannot receive it.
    """

    adb = Path(
        "/Applications/Genymotion.app/Contents/MacOS/player.app/Contents/MacOS/tools/adb"
    )
    scenarios = (
        "recognized",
        "unrecognized",
        "dirty",
        "partial",
        "insufficient",
        "too-fast",
    )

    def probe(
        self, serial: str, android_api: int, runner: CommandRunner = _run
    ) -> Dict[str, object]:
        result: Dict[str, object] = {
            "provider": "genymotion",
            "serial": serial,
            "android_api": android_api,
            "supported": False,
            "transport": "genymotion-widget",
            "scenarios": list(self.scenarios),
            "automatic_recognition": True,
            "reason": "",
        }
        if not serial or not self.adb.exists():
            result["reason"] = "ADB serial or Genymotion ADB is unavailable"
            return result
        if android_api < 33:
            result["reason"] = "Genymotion biometrics requires Android 13 (API 33) or newer"
            return result
        feature = runner(
            (str(self.adb), "-s", serial, "shell", "pm", "list", "features")
        )
        if feature.returncode != 0:
            result["reason"] = "Android device is not reachable through ADB"
            return result
        has_fingerprint = "android.hardware.fingerprint" in feature.stdout
        result["supported"] = has_fingerprint
        result["reason"] = (
            "Use the Genymotion Biometrics widget to inject the selected sensor outcome"
            if has_fingerprint
            else "Android image does not advertise a fingerprint implementation"
        )
        return result


def genymotion_runtime(runner: CommandRunner = _run) -> Dict[str, object]:
    """Describe installed Genymotion devices and their real biometric readiness."""
    devices: List[Dict[str, object]] = []
    biometric_probe = AndroidBiometricProbe()
    for instance in GenymotionProvider().inventory(runner):
        recipe = instance.get("recipe", {}) if isinstance(instance, dict) else {}
        osimage = recipe.get("osimage", {}) if isinstance(recipe, dict) else {}
        api_text = str(osimage.get("api_version", "0"))
        api = int(api_text) if api_text.isdigit() else 0
        serial = str(instance.get("adb_serial", ""))
        devices.append(
            {
                "uuid": instance.get("uuid", ""),
                "name": instance.get("name", "Unknown device"),
                "state": instance.get("state", "unknown"),
                "adb_serial": serial,
                "android_version": osimage.get("android_version", "unknown"),
                "api": api,
                "architecture": osimage.get("architecture", "unknown"),
                "biometrics": biometric_probe.probe(serial, api, runner),
            }
        )
    return {"provider": "genymotion", "devices": devices}


class AppleSimulatorProvider:
    """Probe Apple Simulator runtimes through the supported simctl interface."""

    def probe(self, runner: CommandRunner = _run) -> ProviderStatus:
        if platform.system() != "Darwin":
            return ProviderStatus("apple-simulator", "ios", "local", False, False)
        result = runner(("xcrun", "simctl", "list", "runtimes", "--json"))
        runtimes: List[object] = []
        error = result.stderr.strip()
        if result.returncode == 0:
            try:
                runtimes = json.loads(result.stdout).get("runtimes", [])
            except (json.JSONDecodeError, AttributeError, TypeError):
                error = "simctl returned invalid runtime inventory JSON"
        return ProviderStatus(
            "apple-simulator",
            "ios",
            "local",
            True,
            result.returncode == 0 and bool(runtimes),
            instances=len(runtimes),
            limitations=(
                "requires a Simulator-compatible app build",
                "does not reproduce every physical-device hardware feature",
            ),
            error=error or ("no iOS Simulator runtime installed" if not runtimes else ""),
        )


def provider_catalog(runner: CommandRunner = _run) -> Dict[str, object]:
    local = [
        HuntMobRuntimeProvider().probe().to_dict(),
        AppleSimulatorProvider().probe(runner).to_dict(),
    ]
    remote = [
        {
            "provider": "corellium",
            "platform": "android,ios",
            "kind": "remote-security-lab",
            "configured": False,
            "purpose": "advanced virtual-device security research",
        },
        {
            "provider": "browserstack",
            "platform": "android,ios",
            "kind": "remote-real-device-cloud",
            "configured": False,
            "purpose": "hardware and compatibility validation",
        },
        {
            "provider": "sauce-labs",
            "platform": "android,ios",
            "kind": "remote-real-device-cloud",
            "configured": False,
            "purpose": "hardware and compatibility validation",
        },
    ]
    return {
        "mode": "read-only-discovery",
        "local": local,
        "remote": remote,
        "network_requests": 0,
        "device_contacted": False,
        "reference_probes": ["genymotion-clean-room-behavior"],
    }
