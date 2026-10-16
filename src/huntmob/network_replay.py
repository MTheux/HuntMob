from .lab_sessions import network_store
"""User-triggered replay against a captured loopback lab destination."""
import http.client
import json
import re
import time
from pathlib import Path

from .network_capture import redact, visible_snapshot
from urllib.parse import unquote_plus


def replay(payload):
    try:
        flows = visible_snapshot(network_store())["flows"]
        original = next(flow for flow in flows if flow["id"] == payload.get("flow_id"))
    except (OSError, ValueError, KeyError, StopIteration):
        return {"ok": False, "reason": "Selecione uma requisição capturada válida."}
    if original["host"] not in {"127.0.0.1", "localhost", "::1", "10.0.2.2"}:
        return {"ok": False, "reason": "Send disponível para destinos loopback do laboratório nesta versão."}
    method = str(payload.get("method", ""))
    path = str(payload.get("path", ""))
    body = str(payload.get("body", ""))
    headers = payload.get("headers", {})
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} or not path.startswith("/") or path.startswith("//") or any(ord(char) < 32 for char in path):
        return {"ok": False, "reason": "Método ou caminho inválido."}
    if not isinstance(headers, dict) or len(headers) > 100 or len(body.encode()) > 32768:
        return {"ok": False, "reason": "Request excede os limites do laboratório."}
    if "[REDACTED]" in unquote_plus(body + path + json.dumps(headers)):
        return {"ok": False, "reason": "Substitua os campos redigidos antes de enviar."}
    safe_headers = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", key) or not isinstance(value, str) or any(ord(char) < 32 for char in value):
            return {"ok": False, "reason": "Header inválido."}
        if key.lower() not in {"host", "content-length", "connection", "transfer-encoding", "proxy-authorization"}:
            safe_headers[key] = value
    if "port" not in original:
        return {"ok": False, "reason": "Registro antigo sem porta. Capture novamente antes de enviar."}
    try:
        port = int(original["port"])
        if not 1 <= port <= 65535 or original.get("scheme", "http") not in {"http", "https"}:
            raise ValueError()
    except (TypeError, ValueError):
        return {"ok": False, "reason": "Porta ou protocolo de destino inválido."}
    if port in {8080, 8081}:
        return {"ok": False, "reason": "Replay para portas do proxy não é permitido."}
    if original['host'] in {'10.0.2.2', '127.0.0.1', 'localhost'} and port == 8888:
        from .lab_backend import supported_lab, ensure_backend
        if supported_lab():
            backend = ensure_backend()
            if not backend.get('ok'):
                return {'ok': False, 'reason': backend['reason'], 'error_code': 'backend_unavailable'}
    connection_type = http.client.HTTPSConnection if original.get("scheme") == "https" else http.client.HTTPConnection
    connection = connection_type("::1" if original["host"] == "::1" else "127.0.0.1", port, timeout=10)
    started = time.monotonic()
    try:
        connection.request(method, path, body=body.encode() if body else None, headers=safe_headers)
        response = connection.getresponse()
        content = response.read(32769)
        preview = content[:32768].decode("utf-8", errors="replace")
        try:
            preview = json.dumps(redact(json.loads(preview)), ensure_ascii=False, indent=2)
        except ValueError:
            preview = "[Non-JSON response body omitted]" if preview else ""
        return {"ok": True, "status": response.status, "duration_ms": round((time.monotonic() - started) * 1000), "headers": redact(dict(response.getheaders())), "body": preview, "truncated": len(content) > 32768}
    except (OSError, http.client.HTTPException) as error:
        return {"ok": False, "error_code": "connection_failed", "reason": f"Backend {original['host']}:{port} indisponível ou sem resposta ({type(error).__name__}). Verifique o serviço local; nenhuma resposta HTTP foi recebida."}
    finally:
        connection.close()
