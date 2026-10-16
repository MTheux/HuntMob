"""Passive mitmproxy addon for the local HuntMob network inspector."""
import json
import os
import re
from pathlib import Path

STORE = Path.home() / ".huntmob/run/network.json"
SENSITIVE = re.compile(r"password|passwd|pwd|secret|token|authorization|cookie|api.?key|username|email", re.I)
# Keep browser search/sign-in and their static assets usable without trusting
# the lab CA. Do not exempt googleapis.com: it may be the target app's backend.
GOOGLE_TLS_PASSTHROUGH = r"(?i)^(?:[a-z0-9-]+\.)*(?:google\.com|google\.com\.br|gstatic\.com|googleusercontent\.com):443$"


def preserve_google_tls(options):
    """Tunnel Google HTTPS unchanged; preserve any operator exclusions."""
    exclusions = list(options.ignore_hosts)
    if GOOGLE_TLS_PASSTHROUGH not in exclusions:
        options.update(ignore_hosts=exclusions + [GOOGLE_TLS_PASSTHROUGH])


def capture_cutoff(store):
    try:
        return float(store.with_suffix('.cleared').read_text())
    except (OSError, ValueError):
        return 0


def visible_snapshot(store):
    payload = json.loads(store.read_text()) if store.exists() else {'flows': []}
    cutoff = capture_cutoff(store)
    payload['flows'] = [item for item in payload.get('flows', []) if not cutoff or item.get('started_at', 0) > cutoff]
    return payload


def clear_capture(store):
    """Hide prior traffic in this lab; retain the disk snapshot for recovery."""
    import time
    import uuid
    marker = store.with_suffix('.cleared')
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(marker.name + '.' + uuid.uuid4().hex)
    temporary.write_text(str(time.time()))
    temporary.chmod(0o600)
    os.replace(temporary, marker)
    return {'ok': True}


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
    content_type = next((value for key, value in message.headers.items() if key.lower() == 'content-type'), '').lower()
    if 'application/x-www-form-urlencoded' in content_type:
        from urllib.parse import parse_qsl, urlencode
        fields = parse_qsl(text, keep_blank_values=True)
        return urlencode([(key, '[REDACTED]' if SENSITIVE.search(key) else value) for key, value in fields])
    try:
        return json.dumps(redact(json.loads(text)), ensure_ascii=False, indent=2)
    except ValueError:
        # Arbitrary text may contain credentials: retain structured metadata only.
        return "[Non-JSON body omitted]" if text else ""


class NetworkCapture:
    user_agent_markers = ('android','okhttp','dalvik','apache-httpclient')
    def __init__(self):
        self.flows = []
        self.lab_id = None

    def load(self, loader):
        # Also applied when mitmproxy reloads this addon in an existing session.
        from mitmproxy import ctx
        preserve_google_tls(ctx.options)

    def response(self, flow):
        self.save(flow)

    def error(self, flow):
        self.save(flow)

    def request(self, flow):
        flow.metadata['huntmob_lab_id'] = self.active_lab()
        flow.metadata['huntmob_original_host'] = flow.request.host
        flow.metadata['huntmob_original_headers'] = redact(dict(flow.request.headers))
        self.save(flow)
        # Android Emulator's host alias must resolve to host loopback upstream.
        # This maps only the fixed owned-lab alias, never arbitrary destinations.
        if flow.request.host == '10.0.2.2':
            flow.request.host = '127.0.0.1'

    def active_lab(self):
        try:
            identifier = json.loads((Path.home() / '.huntmob/labs/current.json').read_text()).get('id', '')
            return identifier if re.fullmatch(r'huntmob_lab_[a-f0-9]{32}', identifier) else ''
        except (OSError, ValueError, TypeError):
            return ''

    def save(self, flow):
        identifier = getattr(flow, 'metadata', {}).get('huntmob_lab_id', self.active_lab())
        store = Path.home() / '.huntmob/labs' / identifier / 'network.json' if identifier else STORE
        if self.lab_id != identifier:
            self.lab_id = identifier
            try:
                self.flows = json.loads(store.read_text()).get('flows', [])
            except (OSError, ValueError):
                self.flows = []
        request, response = flow.request, flow.response
        cutoff = capture_cutoff(store)
        if cutoff and request.timestamp_start <= cutoff:
            return
        agent = request.headers.get("user-agent", "").lower()
        if not any(marker in agent for marker in self.user_agent_markers) and request.host not in {"127.0.0.1", "localhost", "10.0.2.2"}:
            return
        from urllib.parse import urlsplit, parse_qsl, urlencode
        url = urlsplit(request.url)
        query = urlencode([(key, "[REDACTED]") for key, value in parse_qsl(url.query)])
        path = url.path + ("?" + query if query else "")
        ended = response.timestamp_end if response else None
        record = {
            "started_at": request.timestamp_start,
            "state": "error" if getattr(flow, "error", None) else "complete" if response else "pending",
            "id": flow.id, "method": request.method, "host": getattr(flow, "metadata", {}).get("huntmob_original_host", request.host), "path": path,
            "port": request.port, "scheme": request.scheme,
            "status": response.status_code if response else None,
            "duration_ms": round((ended - request.timestamp_start) * 1000) if ended else None,
            "request": {"headers": getattr(flow, "metadata", {}).get("huntmob_original_headers", redact(dict(request.headers))), "body": body(request)},
            "response": {"headers": redact(dict(response.headers)) if response else {}, "body": body(response)},
        }
        self.flows = [item for item in self.flows if item['id'] != flow.id and (not cutoff or item.get('started_at', 0) > cutoff)]
        self.flows.append(record)
        self.flows = self.flows[-500:]
        store.parent.mkdir(parents=True, exist_ok=True)
        temporary = store.with_suffix(".tmp")
        temporary.write_text(json.dumps({"flows": self.flows}, ensure_ascii=False), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, store)


addons = [NetworkCapture()]
