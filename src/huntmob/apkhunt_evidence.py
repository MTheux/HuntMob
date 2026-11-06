"""Import a bounded APKHunt JSON report as static leads for the selected APK.

APKHunt is a separate GPL-3.0 workbench. HuntMob consumes only its exported
JSON format; no APKHunt code, live API probing, or scanner process runs here.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

from .dynamic_runtime import private_json
from .lab_sessions import root

MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_FINDINGS = 200
SHA256 = re.compile(r"[a-f0-9]{64}")


def _path(lab):
    return root() / lab["id"] / "apkhunt-static.json"


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _relative_path(value):
    if not isinstance(value, str) or len(value) > 300 or "\\" in value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value:
        return ""
    return str(path)[:200]


def normalize(raw: bytes, lab: dict) -> dict:
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Relatório APKHunt vazio ou acima de 8 MB.")
    try:
        report = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Relatório APKHunt não é JSON válido.") from error
    if not isinstance(report, dict):
        raise ValueError("Relatório APKHunt inválido.")
    meta = report.get("scan_metadata")
    if not isinstance(meta, dict) or not isinstance(report.get("findings"), list):
        raise ValueError("Relatório APKHunt sem metadados ou achados.")
    digest = meta.get("apk_sha256")
    package = meta.get("package_name")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest.lower()):
        raise ValueError("Relatório APKHunt sem SHA256 do APK.")
    if digest.lower() != lab.get("apk_sha256") or package != lab.get("package_id"):
        raise ValueError("O relatório APKHunt não pertence ao APK selecionado.")
    findings = report["findings"]
    if len(findings) > 5000:
        raise ValueError("Relatório APKHunt excede o limite de achados.")
    leads = []
    for item in findings[:MAX_FINDINGS]:
        if not isinstance(item, dict):
            continue
        rule = _text(item.get("id") or item.get("rule_id"), 80)
        title = _text(item.get("rule_title"), 160)
        if not rule or not title:
            continue
        line = item.get("line")
        leads.append({
            "rule_id": rule,
            "title": title,
            "severity": item.get("severity") if item.get("severity") in {"Critical", "High", "Medium", "Low", "Info"} else "Unknown",
            "masvs": _text(item.get("masvs"), 80),
            "cwe": _text(item.get("cwe"), 32),
            "file": _relative_path(item.get("file")),
            "line": line if type(line) is int and 0 <= line <= 10_000_000 else None,
            "status": "static_lead_needs_runtime_validation",
        })
    coverage = meta.get("coverage_status")
    source_count = meta.get("source_files_scanned")
    return {
        "schema": "huntmob.apkhunt-static.v1",
        "engine": "APKHunt",
        "engine_kind": "external-static-report",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "lab_id": lab["id"],
        "package_id": package,
        "apk_sha256": digest.lower(),
        "coverage_status": _text(coverage, 80),
        "source_files_scanned": source_count if type(source_count) is int and source_count >= 0 else None,
        "total_static_leads": len(findings),
        "shown_static_leads": len(leads),
        "truncated": len(findings) > MAX_FINDINGS,
        "leads": leads,
        "finding_status": "not_validated",
        "limitations": ["Sinais estáticos não demonstram execução, alcance ou impacto.",
                        "Código, snippets, segredos, SBOM e rotas do relatório original não são armazenados pelo HuntMob."],
    }


def save(raw: bytes, lab: dict) -> dict:
    snapshot = normalize(raw, lab)
    private_json(_path(lab), snapshot)
    return snapshot


def latest(lab: dict) -> dict | None:
    if not lab.get("id") or not lab.get("package_id") or not lab.get("apk_sha256"):
        return None
    try:
        snapshot = json.loads(_path(lab).read_text())
    except (OSError, ValueError):
        return None
    if (snapshot.get("schema") != "huntmob.apkhunt-static.v1" or
            snapshot.get("lab_id") != lab["id"] or
            any(snapshot.get(key) != lab.get(key) for key in ("package_id", "apk_sha256"))):
        return None
    return snapshot
