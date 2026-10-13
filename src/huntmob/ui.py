"""Loopback-first server for the HuntMob web workbench."""

from __future__ import annotations

import json
import secrets
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type
from urllib.parse import parse_qs, urlparse

from .providers import huntmob_runtime
from .android_worker import AndroidWorker


LOOPBACKS = {"127.0.0.1", "::1", "localhost"}
SESSION_TOKEN = secrets.token_urlsafe(32)


def validate_bind(host: str, authorized_remote: bool) -> None:
    if host not in LOOPBACKS and not authorized_remote:
        raise ValueError("remote UI binding requires --authorized-remote")


def web_root() -> Path:
    root = Path(__file__).resolve().parents[2] / "web"
    if not (root / "index.html").is_file():
        raise FileNotFoundError("HuntMob web assets were not found")
    return root


class HuntMobHandler(SimpleHTTPRequestHandler):
    """Static workbench plus read-only, same-origin runtime discovery."""

    def __init__(self, *args, directory: str | None = None, **kwargs) -> None:
        super().__init__(*args, directory=directory or str(web_root()), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP API name
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/api/runtime":
            payload = huntmob_runtime()
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/session":
            body = json.dumps({"csrf_token": SESSION_TOKEN}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/device/screenshot":
            body = AndroidWorker().screenshot()
            if not body:
                self.send_error(503, "Android device is not ready")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/device/files":
            package_id = parse_qs(parsed.query).get("package", [""])[0]
            payload = AndroidWorker().app_files(package_id)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if payload.get("ok") else 409)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - inherited HTTP API name
        route = urlparse(self.path).path
        if route != "/api/device/action":
            self.send_error(404)
            return
        if self.headers.get("X-HuntMob-CSRF") != SESSION_TOKEN:
            self.send_error(403, "invalid session token")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "invalid JSON request")
            return
        if not payload.get("authorized") or not payload.get("approved"):
            result = {"ok": False, "blocked": True, "reason": "authorization and explicit approval are required"}
            status = 403
        else:
            worker = AndroidWorker()
            actions = {"start": worker.start, "stop": worker.stop, "reboot": worker.reboot, "destroy": worker.destroy}
            action = actions.get(str(payload.get("action", "")))
            if action is None:
                result, status = {"ok": False, "reason": "unknown device action"}, 400
            else:
                result = action()
                status = 200 if result.get("ok") else 409
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(
    host: str = "127.0.0.1",
    port: int = 8090,
    *,
    authorized_remote: bool = False,
    server_class: Type[ThreadingHTTPServer] = ThreadingHTTPServer,
) -> None:
    validate_bind(host, authorized_remote)
    handler = lambda *args, **kwargs: HuntMobHandler(  # noqa: E731
        *args, directory=str(web_root()), **kwargs
    )
    with server_class((host, port), handler) as server:
        print(f"HuntMob UI: http://{host}:{port}")
        server.serve_forever()
