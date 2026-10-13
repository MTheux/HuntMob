"""Deterministic, provider-independent HuntMob device provisioning plans."""

from __future__ import annotations

import platform
import re
from dataclasses import asdict, dataclass
from typing import Dict, Tuple


SAFE_NAME = re.compile(r"^[a-z][a-z0-9-]{2,31}$")


@dataclass(frozen=True)
class DeviceRecipe:
    name: str
    api: int
    architecture: str
    cpu: int = 4
    memory_mb: int = 4096
    data_gb: int = 16
    camera: bool = True
    biometrics: bool = True

    def validate(self) -> Tuple[str, ...]:
        errors = []
        if not SAFE_NAME.fullmatch(self.name):
            errors.append("name must match ^[a-z][a-z0-9-]{2,31}$")
        if self.api < 33:
            errors.append("API 33 or newer is required for the HuntMob biometric HAL")
        if self.architecture not in {"arm64", "x86_64"}:
            errors.append("architecture must be arm64 or x86_64")
        if not 1 <= self.cpu <= 16:
            errors.append("cpu must be between 1 and 16")
        if not 2048 <= self.memory_mb <= 16384:
            errors.append("memory_mb must be between 2048 and 16384")
        if not 4 <= self.data_gb <= 128:
            errors.append("data_gb must be between 4 and 128")
        return tuple(errors)


def provision_plan(recipe: DeviceRecipe, host_os: str | None = None) -> Dict[str, object]:
    """Create a plan only; this never starts a VM or container."""
    errors = recipe.validate()
    host = (host_os or platform.system()).lower()
    if errors:
        return {"ok": False, "blocked": True, "errors": list(errors)}
    dockerized = host == "linux"
    accelerator = {"linux": "kvm", "darwin": "hvf", "windows": "whpx"}.get(host)
    if accelerator is None:
        return {"ok": False, "blocked": True, "errors": ["unsupported worker OS"]}
    return {
        "ok": True,
        "blocked": False,
        "recipe": asdict(recipe),
        "execution": "docker-worker" if dockerized else "native-worker",
        "accelerator": accelerator,
        "lifecycle": [
            "validate-recipe",
            "resolve-signed-aosp-base",
            "create-copy-on-write-data-overlay",
            "write-instance-config",
            "allocate-private-network-and-ports",
            "boot-qemu",
            "wait-for-adb-and-boot-complete",
            "attach-display-and-fixture-services",
            "emit-ready-receipt",
        ],
        "storage": {
            "base": "read-only content-addressed AOSP image",
            "data": "per-instance copy-on-write overlay",
            "snapshots": "per-engagement immutable lineage",
        },
        "docker": {
            "supported": dockerized,
            "required_devices": ["/dev/kvm"] if dockerized else [],
            "published_services": ["worker-api", "webrtc", "adb-loopback"],
            "note": (
                "Docker packages the Linux worker; KVM still performs virtualization"
                if dockerized
                else "Use a native worker so HVF/WHPX remains hardware accelerated"
            ),
        },
    }
