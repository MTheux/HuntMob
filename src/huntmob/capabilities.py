"""Provider-neutral capability contract for HuntMob mobile laboratories."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, Iterable, List


class Capability(str, Enum):
    POWER = "power"
    DISPLAY = "display"
    APPS = "apps"
    FILES = "files"
    CONSOLE = "console"
    FRIDA = "frida"
    NETWORK_CAPTURE = "network-capture"
    SENSORS = "sensors"
    SNAPSHOTS = "snapshots"
    PORT_FORWARDING = "port-forwarding"
    REA_STATIC = "rea-static"
    REA_DYNAMIC_EVIDENCE = "rea-dynamic-evidence"


@dataclass(frozen=True)
class CapabilityProfile:
    provider: str
    platform: str
    capabilities: tuple[Capability, ...]
    privileged: bool
    execution: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["capabilities"] = [item.value for item in self.capabilities]
        return payload


COMMON = (
    Capability.POWER,
    Capability.DISPLAY,
    Capability.APPS,
    Capability.CONSOLE,
    Capability.NETWORK_CAPTURE,
    Capability.SENSORS,
    Capability.SNAPSHOTS,
    Capability.PORT_FORWARDING,
    Capability.REA_STATIC,
    Capability.REA_DYNAMIC_EVIDENCE,
)


PROFILES = (
    CapabilityProfile(
        "huntmob-runtime",
        "android",
        COMMON + (Capability.FILES, Capability.FRIDA),
        True,
        "owned-local-or-remote-worker",
        (
            "Clean-room runtime over QEMU and a HuntMob-controlled AOSP image.",
            "Frida requires an explicitly prepared authorized lab image.",
        ),
    ),
    CapabilityProfile(
        "apple-simulator-worker",
        "ios",
        COMMON,
        False,
        "local-mac-or-remote-mac",
        ("Simulator build required.", "Not equivalent to a jailbroken device."),
    ),
    CapabilityProfile(
        "corellium",
        "android,ios",
        COMMON + (Capability.FILES, Capability.FRIDA),
        True,
        "remote-or-appliance",
        ("Optional commercial provider adapter; API credentials stay server-side.",),
    ),
)


def capability_catalog(profiles: Iterable[CapabilityProfile] = PROFILES) -> List[Dict[str, object]]:
    return [profile.to_dict() for profile in profiles]
