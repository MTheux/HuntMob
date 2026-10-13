"""App-first laboratory jobs for the owned HuntMob Android runtime."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple


PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


class ArtifactSource(str, Enum):
    UPLOAD = "upload"
    FIREBASE = "firebase"
    SIGNED_URL = "signed-url"
    PLAY_MANUAL = "play-manual"


@dataclass(frozen=True)
class LabRequest:
    engagement_id: str
    package_id: str
    source: ArtifactSource
    artifact_path: str = ""
    firebase_release: str = ""
    signed_url_ref: str = ""
    android_api: int = 35
    architecture: str = "arm64"
    authorized: bool = False
    human_approved: bool = False

    def validate(self) -> Tuple[str, ...]:
        errors = []
        if not self.engagement_id.strip():
            errors.append("engagement_id is required")
        if not PACKAGE.fullmatch(self.package_id):
            errors.append("valid package_id is required")
        if not self.authorized:
            errors.append("engagement authorization is required")
        if not self.human_approved:
            errors.append("human approval is required")
        if self.source is ArtifactSource.UPLOAD and not self.artifact_path:
            errors.append("artifact_path is required for upload")
        if self.source is ArtifactSource.FIREBASE and not self.firebase_release:
            errors.append("firebase_release is required")
        if self.source is ArtifactSource.SIGNED_URL and not self.signed_url_ref:
            errors.append("server-side signed URL reference is required")
        if self.android_api < 33:
            errors.append("Android API 33 or newer is required")
        return tuple(errors)


def _local_artifact(path_text: str) -> Optional[Dict[str, object]]:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".apk", ".aab"}:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "kind": path.suffix.lower()[1:],
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def plan_lab(request: LabRequest) -> Dict[str, object]:
    """Validate and plan a lab. No download, VM boot or installation happens here."""
    errors = list(request.validate())
    artifact = None
    if request.source is ArtifactSource.UPLOAD and request.artifact_path:
        artifact = _local_artifact(request.artifact_path)
        if artifact is None:
            errors.append("uploaded artifact must be an existing APK or AAB")
    if errors:
        return {"ok": False, "blocked": True, "errors": errors}
    return {
        "ok": True,
        "blocked": False,
        "request": {
            "engagement_id": request.engagement_id,
            "package_id": request.package_id,
            "source": request.source.value,
            "android_api": request.android_api,
            "architecture": request.architecture,
        },
        "artifact": artifact,
        "states": [
            "queued",
            "acquiring-artifact",
            "hashing-and-package-validation",
            "selecting-compatible-image",
            "provisioning-headless-device",
            "waiting-for-boot-complete",
            "installing-artifact",
            "launching-authorized-package",
            "attaching-rea-frida-proxy",
            "ready",
        ],
        "headless": True,
        "display_on_demand": "webrtc",
        "secrets": "server-side-only",
    }
