"""Curated Frida catalog and fail-closed job planning contracts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Sequence

from .contracts import EngagementGate


PACKAGE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")


@dataclass(frozen=True)
class FridaScript:
    script_id: str
    title: str
    platforms: tuple[str, ...]
    category: str
    mode: str
    risk: str
    description: str
    source: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


CATALOG = (
    FridaScript("tls-observe", "TLS pinning diagnostics", ("android", "ios"), "network", "observe", "low", "Records trust and pinning checks without changing return values.", "huntmob"),
    FridaScript("tls-lab-override", "TLS trust override", ("android", "ios"), "network", "modify", "high", "Lab-only trust override for an explicitly authorized package.", "curated-upstream"),
    FridaScript("biometric-monitor", "Biometric API monitor", ("android", "ios"), "biometric", "observe", "low", "Records biometric prompts, outcomes and lockout paths.", "huntmob"),
    FridaScript("biometric-fixture", "Biometric result fixture", ("android", "ios"), "biometric", "modify", "medium", "Injects approved, rejected or cancelled outcomes in the lab.", "huntmob"),
    FridaScript("root-detection-observe", "Root and jailbreak checks", ("android", "ios"), "integrity", "observe", "low", "Maps integrity checks performed by the selected application.", "huntmob"),
    FridaScript("webview-observe", "WebView navigation trace", ("android",), "webview", "observe", "low", "Records WebView URL loads and bridge registration.", "huntmob"),
    FridaScript("crypto-observe", "Crypto API trace", ("android", "ios"), "crypto", "observe", "medium", "Records algorithm and key-use metadata with secret values redacted.", "huntmob"),
    FridaScript("file-observe", "Application file I/O", ("android", "ios"), "storage", "observe", "low", "Records application-scoped file access paths.", "huntmob"),
)


def validate_package_id(package_id: str) -> str:
    package = package_id.strip()
    if not PACKAGE_PATTERN.fullmatch(package):
        raise ValueError("invalid Android package or iOS bundle identifier")
    return package


def build_frida_job(
    gate: EngagementGate,
    package_id: str,
    script_ids: Sequence[str],
    *,
    catalog: Iterable[FridaScript] = CATALOG,
) -> Dict[str, object]:
    package = validate_package_id(package_id)
    if package != gate.package_id:
        raise ValueError("package does not match the authorized engagement")
    decision = gate.authorize("frida.execute")
    if not decision["ok"]:
        return {"ok": False, "blocked": True, "reasons": decision["reasons"]}
    indexed = {script.script_id: script for script in catalog}
    if not script_ids:
        raise ValueError("at least one script is required")
    unknown = sorted(set(script_ids) - indexed.keys())
    if unknown:
        raise ValueError(f"unknown scripts: {', '.join(unknown)}")
    selected: List[FridaScript] = [indexed[script_id] for script_id in script_ids]
    incompatible = [item.script_id for item in selected if gate.platform.value not in item.platforms]
    if incompatible:
        raise ValueError(f"scripts incompatible with {gate.platform.value}: {', '.join(incompatible)}")
    return {
        "ok": True,
        "blocked": False,
        "engagement_id": gate.engagement_id,
        "platform": gate.platform.value,
        "package_id": package,
        "scripts": [item.to_dict() for item in selected],
        "execution": "worker-only",
        "raw_shell": False,
        "receipt_required": True,
    }
