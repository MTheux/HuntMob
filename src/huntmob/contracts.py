"""Shared contracts for mobile runtimes and REA analysis providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List


class Platform(str, Enum):
    ANDROID = "android"
    IOS = "ios"


@dataclass(frozen=True)
class EngagementGate:
    engagement_id: str
    platform: Platform
    package_id: str
    authorized: bool = False
    human_approved: bool = False
    allowed_actions: List[str] = field(default_factory=list)

    def authorize(self, action: str) -> Dict[str, object]:
        reasons = []
        if not self.engagement_id.strip():
            reasons.append("engagement_id is required")
        if not self.package_id.strip():
            reasons.append("package_id is required")
        if not self.authorized:
            reasons.append("engagement is not authorized")
        if action not in self.allowed_actions:
            reasons.append("action is outside the allowlist")
        if action not in {"status", "inventory"} and not self.human_approved:
            reasons.append("active action requires human approval")
        return {"ok": not reasons, "blocked": bool(reasons), "reasons": reasons}

