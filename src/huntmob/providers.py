"""Read-only runtime provider probes used by the HuntMob control plane."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence


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
                instances = len(json.loads(list_result.stdout).get("devices", {}))
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
        GenymotionProvider().probe(runner).to_dict(),
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
    }
