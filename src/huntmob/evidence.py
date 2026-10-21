"""Local screenshot evidence with immutable hashes and owner-only storage."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

EVIDENCE_ID = re.compile(r"^ev_[a-f0-9]{32}$")
FAILURE_ID = re.compile(r"^fail_[a-f0-9]{32}\.json$")
MAX_SCREENSHOT_BYTES = 32 * 1024 * 1024
CAPTURE_SLOTS = threading.BoundedSemaphore(2)


def _private_atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
            output.write(json.dumps(value, ensure_ascii=False, sort_keys=True).encode())
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class EvidenceStore:
    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".huntmob/evidence"

    def capture(self, image: bytes, *, serial: str, selected_package: str = "", lab_id: str = "") -> dict:
        if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > MAX_SCREENSHOT_BYTES:
            raise ValueError("Screenshot unavailable or invalid PNG")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        if not CAPTURE_SLOTS.acquire(blocking=False):
            self._failure("capture_capacity_exceeded", lab_id=lab_id)
            raise ValueError("Screenshot capture capacity exceeded")
        identifier = "ev_" + uuid4().hex
        folder = self.root / identifier
        staging = self.root / ("." + identifier + "." + uuid4().hex + ".tmp")
        record = {
            "id": identifier, "kind": "screenshot", "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "serial": serial, "selected_package": selected_package, "lab_id": lab_id,
            "sha256": hashlib.sha256(image).hexdigest(), "size": len(image),
            "filename": "screenshot.png", "status": "captured",
            "finding_status": "not_assessed",
        }
        try:
            staging.mkdir(mode=0o700)
            for name, content in (("screenshot.png", image), ("record.json", json.dumps(record).encode())):
                with os.fdopen(os.open(staging / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
            staging.replace(folder)
        except OSError:
            self._failure("atomic_publish_failed", lab_id=lab_id, evidence_id=identifier)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            CAPTURE_SLOTS.release()
        return record

    def _failure(self, reason_code: str, *, lab_id: str = "", evidence_id: str = "") -> dict:
        receipt = {"id": "fail_" + uuid4().hex, "version": 1, "kind": "screenshot_failure",
                   "created_at": datetime.now(timezone.utc).isoformat(), "status": "failed",
                   "reason_code": reason_code, "lab_id": lab_id, "evidence_id": evidence_id}
        _private_atomic_json(self.root / "failures" / (receipt["id"] + ".json"), receipt)
        return receipt

    def failures(self) -> list[dict]:
        result = []
        folder = self.root / "failures"
        if folder.exists():
            for path in folder.glob("fail_*.json"):
                try:
                    if path.is_symlink() or not FAILURE_ID.fullmatch(path.name):
                        raise ValueError("Invalid failure receipt")
                    value = json.loads(path.read_text())
                    if value.get("id") + ".json" != path.name or value.get("status") != "failed":
                        raise ValueError("Invalid failure receipt")
                    result.append(value)
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

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
        return {"records": sorted(records, key=lambda item: item["created_at"], reverse=True), "invalid_count": invalid,
                "failure_receipts": self.failures()}

    def export(self, identifier: str) -> bytes:
        record, image = self.read(identifier)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("record.json", json.dumps(record, indent=2))
            archive.writestr("screenshot.png", image)
        return output.getvalue()
