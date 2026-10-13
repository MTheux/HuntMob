"""Deterministic runtime routing for local and remote mobile labs."""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass
from typing import Dict

from .contracts import Platform


@dataclass(frozen=True)
class RuntimePlan:
    platform: str
    controller_os: str
    provider: str
    execution_location: str
    transport: str
    confidence: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def select_runtime(
    target: Platform,
    *,
    controller_os: str | None = None,
    privileged_ios: bool = False,
    physical_hardware: bool = False,
) -> RuntimePlan:
    """Choose a supported lab topology without provisioning anything."""
    host = (controller_os or platform.system()).lower()
    if target is Platform.ANDROID:
        return RuntimePlan(
            target.value,
            host,
            "genymotion",
            "local" if host in {"darwin", "windows", "linux"} else "remote-worker",
            "local-api" if host in {"darwin", "windows", "linux"} else "vpn+https",
            "confirmed",
            "Genymotion is the primary Android runtime adapter.",
        )
    if physical_hardware:
        return RuntimePlan(
            target.value,
            host,
            "real-device-cloud",
            "remote-provider",
            "https+wss",
            "confirmed",
            "Physical camera, biometrics and device-specific behavior require real hardware.",
        )
    if privileged_ios:
        return RuntimePlan(
            target.value,
            host,
            "corellium",
            "remote-or-appliance",
            "vpn+https+wss",
            "confirmed",
            "Privileged iOS security analysis requires a purpose-built security runtime.",
        )
    if host == "darwin":
        return RuntimePlan(
            target.value,
            host,
            "apple-simulator",
            "local-mac",
            "local-api",
            "confirmed",
            "Apple Simulator is available through Xcode on macOS.",
        )
    return RuntimePlan(
        target.value,
        host,
        "apple-simulator-worker",
        "remote-mac",
        "tailscale-or-vpn+https+wss",
        "confirmed",
        "Windows and Linux act as controllers; the iOS runtime executes on an authorized Mac worker.",
    )
