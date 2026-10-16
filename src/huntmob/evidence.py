"""Local screenshot evidence with immutable hashes and owner-only storage."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

EVIDENCE_ID = re.compile(r"^ev_[a-f0-9]{32}$")


class EvidenceStore:
    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".huntmob/evidence"

    def capture(self, image: bytes, *, serial: str, selected_package: str = "", lab_id: str = "") -> dict:
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Screenshot unavailable or invalid PNG")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        identifier = "ev_" + uuid4().hex
        folder = self.root / identifier
        folder.mkdir(mode=0o700)
        record = {
            "id": identifier, "kind": "screenshot", "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "serial": serial, "selected_package": selected_package, "lab_id": lab_id,
            "sha256": hashlib.sha256(image).hexdigest(), "size": len(image),
            "filename": "screenshot.png", "status": "captured",
            "finding_status": "not_assessed",
        }
        try:
            for name, content in (("screenshot.png", image), ("record.json", json.dumps(record).encode())):
                with os.fdopen(os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                    output.write(content)
        except OSError:
            # Incomplete records are excluded from inventory.
            raise
        return record

    def read(self, identifier: str) -> tuple[dict, bytes]:
        if not EVIDENCE_ID.fullmatch(identifier):
            raise ValueError("Invalid evidence identifier")
        folder = self.root / identifier
        if folder.is_symlink():
            raise ValueError("Invalid evidence directory")
        metadata, artifact = folder / "record.json", folder / "screenshot.png"
        if metadata.is_symlink() or artifact.is_symlink():
            raise ValueError("Invalid evidence artifact")
        record = json.loads(metadata.read_text())
        image = artifact.read_bytes()
        if record.get("id") != identifier or hashlib.sha256(image).hexdigest() != record.get("sha256"):
            raise ValueError("Evidence integrity check failed")
        return record, image

    def inventory(self) -> dict:
        records, invalid = [], 0
        if self.root.exists():
            for folder in self.root.glob("ev_*"):
                try:
                    record, _ = self.read(folder.name)
                    records.append(record)
                except (OSError, ValueError, TypeError):
                    invalid += 1
        return {"records": sorted(records, key=lambda item: item["created_at"], reverse=True), "invalid_count": invalid}

    def export(self, identifier: str) -> bytes:
        record, image = self.read(identifier)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("record.json", json.dumps(record, indent=2))
            archive.writestr("screenshot.png", image)
        return output.getvalue()
