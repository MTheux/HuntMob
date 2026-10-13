"""Loopback-first server for the HuntMob web workbench."""

from __future__ import annotations

import json
import secrets
import tempfile
import shutil
import subprocess
import threading
import select
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type
from urllib.parse import parse_qs, urlparse

from .providers import huntmob_runtime
from .android_worker import AndroidWorker
from .network_replay import replay


LOOPBACKS = {"127.0.0.1", "::1", "localhost"}
SESSION_TOKEN = secrets.token_urlsafe(32)
VIDEO_SLOTS = threading.BoundedSemaphore(2)


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
        if route == "/api/network":
            store = Path.home() / ".huntmob/run/network.json"
            try:
                payload = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {"flows": []}
            except (OSError, ValueError):
                payload = {"flows": [], "error": "Capture snapshot unavailable"}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/device/stream":
            worker = AndroidWorker()
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg or not worker.sdk or worker.status()["state"] != "device":
                self.send_error(503, "video stream unavailable")
                return
            if not VIDEO_SLOTS.acquire(blocking=False):
                self.send_error(503, "video stream capacity reached")
                return
            recorder = decoder = None
            try:
                seed = subprocess.run(
                    (ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-vf", "scale=540:1200", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"),
                    input=worker.screenshot(), capture_output=True, timeout=15,
                ).stdout
                recorder = subprocess.Popen(
                    (str(worker.sdk.adb), "-s", worker.serial, "exec-out", "screenrecord",
                     "--output-format=h264", "--size", "540x1200", "--bit-rate", "2000000", "--time-limit", "0", "-"),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                decoder = subprocess.Popen(
                    (ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "+genpts", "-flags", "low_delay",
                     "-probesize", "32", "-analyzeduration", "0", "-f", "h264", "-i", "pipe:0",
                     "-q:v", "5", "-flush_packets", "1", "-f", "mpjpeg", "-boundary_tag", "huntmob", "pipe:1"),
                    stdin=recorder.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                recorder.stdout.close()
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=huntmob")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if seed:
                    first_frame = b"--huntmob\r\nContent-type: image/jpeg\r\nContent-length: " + str(len(seed)).encode() + b"\r\n\r\n" + seed + b"\r\n"
                    self.wfile.write(first_frame + first_frame)
                    self.wfile.flush()
                while True:
                    readable, _, _ = select.select([decoder.stdout, self.connection], [], [], 1)
                    if self.connection in readable and not self.connection.recv(1, socket.MSG_PEEK):
                        break
                    if decoder.stdout not in readable:
                        continue
                    chunk = decoder.stdout.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                for process in (decoder, recorder):
                    if process is not None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                VIDEO_SLOTS.release()
            return
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
        if route == "/api/device/apps":
            payload = AndroidWorker().installed_apps()
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if payload.get("ok") else 409)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/proxy":
            query = parse_qs(parsed.query)
            try:
                port = int(query.get("port", ["8080"])[0])
            except ValueError:
                port = 0
            payload = AndroidWorker().proxy_status(port)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - inherited HTTP API name
        route = urlparse(self.path).path
        if route not in {"/api/device/action", "/api/proxy", "/api/reverse", "/api/device/upload", "/api/device/input", "/api/network/send"}:
            self.send_error(404)
            return
        if self.headers.get("X-HuntMob-CSRF") != SESSION_TOKEN:
            self.send_error(403, "invalid session token")
            return
        if route == "/api/device/upload":
            if self.headers.get("X-HuntMob-Approved") != "true":
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 512 * 1024 * 1024:
                    raise ValueError()
                with tempfile.TemporaryDirectory(prefix="huntmob-upload-") as folder:
                    apk = Path(folder) / "app.apk"
                    with apk.open("wb") as output:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError()
                            output.write(chunk)
                            remaining -= len(chunk)
                    result = AndroidWorker().upload_and_launch(apk, legacy_sdk=self.headers.get("X-HuntMob-Legacy-SDK") == "true")
            except (ValueError, TimeoutError):
                result = {"ok": False, "reason": "invalid upload or Android operation timed out"}
            body = json.dumps(result).encode()
            self.send_response(200 if result.get("ok") else 409)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            if route == "/api/network/send":
                result = replay(payload)
                status = 200 if result.get("ok") else 409
            elif route == "/api/device/input":
                result = worker.device_input(payload)
                status = 200 if result.get("ok") else 409
            elif route == "/api/reverse":
                result = worker.prepare_reverse(str(payload.get("package_id", "")))
                status = 200 if result.get("ok") else 409
            elif route == "/api/proxy":
                proxy_action = str(payload.get("action", ""))
                if proxy_action == "configure":
                    try:
                        port = int(payload.get("port", 8080))
                    except (TypeError, ValueError):
                        port = 0
                    result = worker.configure_proxy(port)
                elif proxy_action == "start-managed":
                    try:
                        port = int(payload.get("port", 8080))
                    except (TypeError, ValueError):
                        port = 0
                    result = worker.start_managed_proxy(port)
                elif proxy_action == "clear":
                    result = worker.clear_proxy()
                else:
                    result = {"ok": False, "reason": "unknown proxy action"}
                status = 200 if result.get("ok") else 409
            else:
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
