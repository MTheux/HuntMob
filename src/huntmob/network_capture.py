"""Passive mitmproxy addon for the local HuntMob network inspector."""
import json
import os
import re
from pathlib import Path

STORE = Path.home() / ".huntmob/run/network.json"
SENSITIVE = re.compile(r"password|passwd|secret|token|authorization|cookie|api.?key", re.I)


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SENSITIVE.search(key) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def body(message):
    if not message:
        return ""
    if len(message.raw_content or b"") > 32768:
        return "[Body larger than 32 KB; preview omitted]"
    text = message.get_text(strict=False) or ""
    try:
        return json.dumps(redact(json.loads(text)), ensure_ascii=False, indent=2)
    except ValueError:
        # Arbitrary text may contain credentials: retain structured metadata only.
        return "[Non-JSON body omitted]" if text else ""


class NetworkCapture:
    def __init__(self):
        self.flows = []

    def response(self, flow):
        self.save(flow)

    def error(self, flow):
        self.save(flow)

    def save(self, flow):
        request, response = flow.request, flow.response
        agent = request.headers.get("user-agent", "").lower()
        if not any(marker in agent for marker in ("android", "okhttp", "dalvik", "apache-httpclient")) and request.host not in {"127.0.0.1", "localhost", "10.0.2.2"}:
            return
        from urllib.parse import urlsplit, parse_qsl, urlencode
        url = urlsplit(request.url)
        query = urlencode([(key, "[REDACTED]") for key, value in parse_qsl(url.query)])
        path = url.path + ("?" + query if query else "")
        ended = response.timestamp_end if response else None
        self.flows.append({
            "id": flow.id, "method": request.method, "host": request.host, "path": path,
            "status": response.status_code if response else None,
            "duration_ms": round((ended - request.timestamp_start) * 1000) if ended else None,
            "request": {"headers": redact(dict(request.headers)), "body": body(request)},
            "response": {"headers": redact(dict(response.headers)) if response else {}, "body": body(response)},
        })
        self.flows = self.flows[-500:]
        STORE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STORE.with_suffix(".tmp")
        temporary.write_text(json.dumps({"flows": self.flows}, ensure_ascii=False), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, STORE)


addons = [NetworkCapture()]
