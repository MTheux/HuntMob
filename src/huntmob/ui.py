"""Loopback-first server for the HuntMob web workbench."""

from __future__ import annotations

import json
from datetime import datetime, timezone
import secrets
import tempfile
import shutil
import subprocess
import threading
import select
import socket
import signal
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type
from urllib.parse import unquote, parse_qs, urlparse

from .providers import huntmob_runtime
from .android_worker import AndroidWorker
from .network_replay import replay
from .device_controls import execute as device_control
from .codec_relay import CODEC_RELAY
from . import ios_worker, ios_static, ios_native_readiness
from .ios_identity import simulator_identity
from .dynamic_runtime import DYNAMIC
from . import native_dast
from .network_capture import clear_capture, visible_snapshot
from .evidence import EvidenceStore
from .screen_relay import SCREEN_RELAY
from .analysis_core import EmbeddedAnalysis
from . import reverse_workspace
from . import reverse_engines
from .lab_sessions import inventory as lab_inventory, create_lab, create_play_lab, resume_lab, network_store, current as current_lab, change_root_profile
from .android_worker import PACKAGE_ID
from . import workspace_devices


LOOPBACKS = {"127.0.0.1", "::1", "localhost"}
SESSION_TOKEN = secrets.token_urlsafe(32)
VIDEO_SLOTS = threading.BoundedSemaphore(2)


def validate_bind(host: str, authorized_remote: bool) -> None:
    if host not in LOOPBACKS and not authorized_remote:
        raise ValueError("remote UI binding requires --authorized-remote")


def web_root() -> Path:
    root = Path(__file__).resolve().parents[2] / "web"
    if not (root / "index.html").is_file():
        root = Path(__file__).parent / "_web"
    if not (root / "index.html").is_file():
        raise FileNotFoundError("HuntMob web assets were not found")
    return root


class HuntMobHandler(SimpleHTTPRequestHandler):
    """Static workbench plus read-only, same-origin runtime discovery."""

    def __init__(self, *args, directory: str | None = None, **kwargs) -> None:
        super().__init__(*args, directory=directory or str(web_root()), **kwargs)

    def log_message(self, format: str, *args) -> None:
        # A detached worker can outlive the chat/terminal reading stderr.
        # Losing that log sink must not interrupt an HTTP response.
        try:
            super().log_message(format, *args)
        except (OSError, ValueError):
            pass

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP API name
        parsed = urlparse(self.path)
        route = parsed.path
        if route == '/api/ios/runtime-catalog':
            from .ios_runtimes import catalog
            self.workspace_json(catalog())
            return
        if route in {'/api/workspace/devices', '/api/workspace/agent', '/api/workspace/device/video', '/api/workspace/device/screenshot'}:
            self.workspace_get(route, parse_qs(parsed.query))
            return
        if route == '/api/client/ping':
            body=b'{"ok":true,"version":1}'
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        if route == '/api/reverse/engines':
            self.workspace_json(reverse_engines.status())
            return
        if route == '/api/reverse/target':
            try: self.workspace_json(reverse_engines.target(parse_qs(parsed.query).get('workspace', [''])[0]))
            except (OSError, ValueError, KeyError, TypeError): self.workspace_json({'ok': False, 'reason': 'Workspace selecionado mudou.'}, 409)
            return
        if route in {'/api/reverse/inspections', '/api/reverse/companion', '/api/reverse/companion.zip'}:
            query = parse_qs(parsed.query)
            try:
                args = [query.get(key, [''])[0] for key in ('package', 'workspace', 'run', 'sha256')]
                if route.endswith('.zip'):
                    body = reverse_engines.export_handoff(*args)
                    self.send_response(200); self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Disposition', 'attachment; filename="huntmob-companion.zip"')
                    self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body)
                else:
                    self.workspace_json(reverse_engines.handoff(*args) if route.endswith('/companion') else reverse_engines.jobs(*args))
            except (OSError, ValueError, KeyError, TypeError):
                self.workspace_json({'ok': False, 'reason': 'Contexto indisponível. Confira app, execução, SHA256 e evidências REA.'}, 409)
            return
        if route in {'/api/reverse/workspace', '/api/reverse/file', '/api/reverse/export'}:
            query = parse_qs(parsed.query)
            package = query.get('package', [''])[0]
            run_id = query.get('run', [''])[0]
            try:
                avd = AndroidWorker().avd_name
                if route == '/api/reverse/workspace':
                    payload = reverse_workspace.latest(package, avd)
                elif route == '/api/reverse/file':
                    payload = reverse_workspace.preview(package, avd, run_id, query.get('path', [''])[0])
                else:
                    payload = None
                body = json.dumps(payload).encode() if payload is not None else reverse_workspace.export(package, avd, run_id)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if payload is not None else 'application/zip')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                if payload is None:
                    self.send_header('Content-Disposition', f'attachment; filename="huntmob-{package}-{run_id}.zip"')
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError, TypeError):
                self.send_error(404, 'Recorded analysis or file unavailable')
            return
        if route == "/api/analysis/status":
            body = json.dumps(EmbeddedAnalysis().status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/labs":
            body = json.dumps(lab_inventory()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/evidence" or route.startswith("/api/evidence/export/"):
            try:
                if route == "/api/evidence":
                    body = json.dumps(EvidenceStore().inventory()).encode()
                    content_type = "application/json"
                else:
                    identifier = route.removeprefix("/api/evidence/export/")
                    body = EvidenceStore().export(identifier)
                    content_type = "application/zip"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                if content_type == "application/zip":
                    self.send_header("Content-Disposition", f'attachment; filename="huntmob-evidence-v1-{identifier}.zip"')
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError, TypeError):
                self.send_error(409, "Evidence unavailable or integrity check failed")
            return
        if route == "/api/network":
            store = network_store()
            try:
                payload = visible_snapshot(store)
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
        if route == '/api/viewer/downloads' or route.startswith('/api/viewer/download/'):
            from . import viewer_downloads
            try:
                if route == '/api/viewer/downloads':
                    body=json.dumps(viewer_downloads.catalog()).encode()
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                else:
                    path=viewer_downloads.artifact(route.removeprefix('/api/viewer/download/'))
                    size=path.stat().st_size
                    item=next(i for i in viewer_downloads.catalog()['artifacts'] if i['filename']==path.name)
                    etag='"'+item['sha256']+'"'
                    if self.headers.get('If-None-Match')==etag:
                        self.send_response(304);self.send_header('ETag',etag);self.end_headers();return
                    requested=self.headers.get('Range') if self.headers.get('If-Range',etag)==etag else None
                    try:start,end,partial=viewer_downloads.byte_range(requested,size)
                    except ValueError:
                        self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
                    self.send_response(206 if partial else 200);self.send_header('Content-Type','application/zip');self.send_header('Content-Disposition','attachment; filename="'+path.name+'"');self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('ETag',etag);self.send_header('Cache-Control','private, max-age=3600')
                    if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    with path.open('rb') as source:
                        source.seek(start);remaining=end-start+1
                        while remaining:
                            chunk=source.read(min(1024*1024,remaining))
                            if not chunk:break
                            self.wfile.write(chunk);remaining-=len(chunk)
            except (OSError,ValueError):self.send_error(404,'Viewer artifact unavailable')
            return
        if route == '/api/remote/status':
            body=json.dumps({'active':False,'command':'huntmob remote'}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        if route == '/api/ios/xtool/status':
            from . import ios_xtool
            body=json.dumps(ios_xtool.status()).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        if route == '/api/ios/status':
            payload = ios_worker.inventory()
            payload['virtual_runtime'] = ios_native_readiness.snapshot()
            payload['identity'] = simulator_identity(payload.get('lab', {}))
            body = json.dumps(payload).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        if route == '/api/ios/catalog':
            try: payload=ios_worker.lab_catalog()
            except (OSError,ValueError,subprocess.TimeoutExpired): payload={'ok':False,'runtimes':[],'models':[],'reason':'Catálogo iOS indisponível.'}
            body=json.dumps(payload).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        if route == '/api/ios/proxy/status':
            from . import ios_proxy
            try: payload=ios_proxy.status()
            except (OSError,ValueError): payload={'ok':False,'active':False,'flows':[],'reason':'Estado da captura iOS indisponível.'}
            body=json.dumps(payload).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        if route == '/api/ios/video-status':
            body=json.dumps(ios_worker.IOS_RELAY.snapshot()).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        if route == '/api/ios/stream':
            try:
                record = ios_worker.owned()
                relay = ios_worker.IOS_RELAY
                sequence, frame = relay.get_frame(str(ios_worker.client_path()), record['udid'], '')
                self.send_response(200); self.send_header('Content-Type','multipart/x-mixed-replace; boundary=huntmob'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.connection.settimeout(3)
                while True:
                    self.wfile.write(b'--huntmob\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(frame)).encode()+b'\r\n\r\n'+frame+b'\r\n'); self.wfile.flush()
                    sequence, frame = relay.get_frame(str(ios_worker.client_path()),record['udid'],'',after=sequence,timeout=1)
            except (OSError,ValueError,RuntimeError,TimeoutError): self.close_connection = True
            return
        if route == '/api/device/video-status':
            body = json.dumps(CODEC_RELAY.snapshot()).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        if route == '/api/device/video':
            worker = AndroidWorker()
            if worker.status().get('state') != 'device':
                self.send_error(503,'Android offline'); return
            try:
                sequence, packets = CODEC_RELAY.get_packets(worker)
                if not packets: raise TimeoutError('Video not ready')
                self.send_response(200); self.send_header('Content-Type','application/octet-stream'); self.send_header('Cache-Control','no-store'); self.send_header('Connection','close'); self.end_headers()
                self.connection.settimeout(3); self.wfile.write(b'h264')
                while True:
                    if not packets: self.wfile.write(b'\0' * 12)
                    for packet in packets: self.wfile.write(packet)
                    self.wfile.flush()
                    sequence, packets = CODEC_RELAY.get_packets(worker,after=sequence,timeout=1)
            except (OSError,ValueError,RuntimeError,TimeoutError):
                self.close_connection = True
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
            try:
                sequence, frame = SCREEN_RELAY.get_frame(str(worker.sdk.adb), worker.serial, ffmpeg)
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=huntmob")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.connection.settimeout(3)
                while True:
                    packet = b"--huntmob\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
                    self.wfile.write(packet)
                    self.wfile.flush()
                    # Slow viewers receive the newest frame, never an old queue.
                    sequence, frame = SCREEN_RELAY.get_frame(str(worker.sdk.adb), worker.serial, ffmpeg, after=sequence, timeout=1)
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError, RuntimeError):
                self.close_connection = True
            finally:
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
        if route in {'/api/dynamic/status', '/api/dynamic/export', '/api/dynamic/report', '/api/dynamic/report.json', '/api/dynamic/report.html'}:
            try:
                if route == '/api/dynamic/status':
                    body = json.dumps(DYNAMIC.snapshot()).encode()
                elif route.startswith('/api/dynamic/report'):
                    report = native_dast.latest()
                    if report is None: raise ValueError('Native report unavailable')
                    body = native_dast.render_html(report) if route.endswith('.html') else json.dumps(report, ensure_ascii=False).encode()
                else:
                    body = DYNAMIC.export()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8' if route.endswith('.html') else 'application/json')
                self.send_header('Cache-Control', 'no-store')
                if route not in {'/api/dynamic/status', '/api/dynamic/report'}:
                    import hashlib
                    kind = 'native-dast-report' if '/report' in route else 'dynamic'
                    extension = 'html' if route.endswith('.html') else 'json'
                    self.send_header('Content-Disposition', f'attachment; filename="huntmob-{kind}-v1-{datetime.now(timezone.utc).date().isoformat()}.{extension}"')
                    self.send_header('X-HuntMob-SHA256', hashlib.sha256(body).hexdigest())
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
            except (OSError, ValueError, KeyError):
                self.send_error(409, 'Dynamic evidence unavailable')
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

    def workspace_get(self, route, query):
        workspace_id = query.get('workspace', [''])[0]
        try:
            workspace_devices._name(workspace_id)
            if route == '/api/workspace/devices':
                result = workspace_devices.snapshot(workspace_id)
                self.workspace_json(result)
                return
            if route == '/api/workspace/agent':
                import sys
                config = {'mcpServers': {'huntmob-devices': {'command': sys.executable,
                          'args': ['-m', 'huntmob.device_mcp', '--port', str(self.server.server_port), '--workspace', workspace_id],
                          'env': {'PYTHONPATH': str(Path(__file__).resolve().parents[1])}}}}
                self.workspace_json({'ok': True, 'config': config, 'workspace_id': workspace_id})
                return
            device_id = query.get('device', [''])[0]
            if device_id == workspace_id and current_lab().get('id') == workspace_id and route.endswith('/screenshot'):
                worker = AndroidWorker()
            else:
                record = workspace_devices.owned(workspace_id, device_id)
                worker = workspace_devices.worker(record)
            if worker.status().get('ownership_verified') is not True:
                raise ValueError('Aparelho offline ou identidade ADB divergente.')
            if route.endswith('/screenshot'):
                body = worker.screenshot()
                if not body.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('Captura indisponível.')
                self.send_response(200); self.send_header('Content-Type', 'image/png'); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            relay = workspace_devices.relay(record)
            if record.get('platform')=='ios':
                self.workspace_ios_stream(worker,relay)
                return
            sequence, packets = relay.get_packets(worker)
            if not packets:
                raise ValueError('Vídeo ainda não disponível.')
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
            self.workspace_json({'ok': False, 'reason': 'Aparelho indisponível ou fora deste workspace.'}, 409)
            return
        try:
            self.send_response(200); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Cache-Control', 'no-store'); self.send_header('Connection', 'close'); self.end_headers()
            self.connection.settimeout(3); self.wfile.write(b'h264')
            while True:
                if not packets: self.wfile.write(b'\0' * 12)
                for packet in packets: self.wfile.write(packet)
                self.wfile.flush()
                sequence, packets = relay.get_packets(worker, after=sequence, timeout=1)
        except (OSError, ValueError, RuntimeError, TimeoutError):
            self.close_connection = True

    def workspace_ios_stream(self, worker, relay):
        try:
            sequence,frame=relay.get_frame(str(ios_worker.client_path()),worker.serial,'')
        except (OSError, ValueError, RuntimeError, TimeoutError):
            self.workspace_json({'ok':False,'reason':'Vídeo iOS ainda indisponível.'},409)
            return
        try:
            self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=huntmob');self.send_header('Cache-Control','no-store');self.end_headers();self.connection.settimeout(3)
            while True:
                self.wfile.write(b'--huntmob\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(frame)).encode()+b'\r\n\r\n'+frame+b'\r\n');self.wfile.flush()
                sequence,frame=relay.get_frame(str(ios_worker.client_path()),worker.serial,'',after=sequence,timeout=1)
        except (OSError,ValueError,RuntimeError,TimeoutError):self.close_connection=True

    def workspace_json(self, result, status=200):
        body = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - inherited HTTP API name
        route = urlparse(self.path).path
        if route not in {"/api/reverse/model-review", "/api/reverse/review", "/api/reverse/inspect", "/api/workspace/device/action", "/api/ios/xtool/install", "/api/ios/analyze", "/api/ios/action", "/api/ios/upload", "/api/device/direct-input", "/api/device/control", "/api/device/action", "/api/proxy", "/api/reverse", "/api/device/upload", "/api/device/drop", "/api/device/input", "/api/network/send", "/api/network/clear", "/api/dynamic", "/api/evidence/capture"}:
            self.send_error(404)
            return
        if self.headers.get("X-HuntMob-CSRF") != SESSION_TOKEN:
            body=json.dumps({'ok':False,'error_code':'csrf_session_changed','executed':False,'reason':'Sessão do servidor mudou; renove a conexão antes de repetir.'}).encode()
            self.send_response(403);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        if route == '/api/device/drop':
            if self.headers.get('X-HuntMob-Approved') != 'true':
                self.workspace_json({'ok': False, 'reason': 'Autorização explícita necessária.'}, 403)
                return
            try:
                from . import device_drop
                name = device_drop.safe_name(self.headers.get('X-HuntMob-Filename', ''))
                workspace_id = self.headers.get('X-HuntMob-Workspace', '')
                device_id = self.headers.get('X-HuntMob-Device', '')
                device_drop.target(workspace_id, device_id)
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 512 * 1024 * 1024:
                    raise ValueError('Arquivo deve ter até 512 MB.')
                with tempfile.TemporaryDirectory(prefix='huntmob-drop-') as folder:
                    path = Path(folder) / ('upload' + Path(name).suffix.lower())
                    with path.open('wb') as output:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError('Upload interrompido.')
                            output.write(chunk)
                            remaining -= len(chunk)
                    worker = device_drop.target(workspace_id, device_id)
                    result = device_drop.deliver(worker, path, name, primary=device_id == workspace_id)
            except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as error:
                result = {'ok': False, 'reason': str(error) if isinstance(error, ValueError) else 'Envio ao Android não concluído.'}
            self.workspace_json(result, 200 if result.get('ok') else 409)
            return
        if route in {'/api/ios/upload', '/api/ios/analyze', '/api/ios/xtool/install'}:
            if self.headers.get('X-HuntMob-Approved') != 'true':
                self.send_error(403); return
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 512*1024*1024: raise ValueError('ZIP deve ter até 512 MB.')
                with tempfile.TemporaryDirectory(prefix='huntmob-ios-upload-') as directory:
                    path = Path(directory)/'app.zip'
                    with path.open('wb') as target:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(remaining,1024*1024))
                            if not chunk: raise ValueError('Upload interrompido.')
                            target.write(chunk); remaining -= len(chunk)
                    if route == '/api/ios/xtool/install':
                        from . import ios_xtool
                        result=ios_xtool.install(path,self.headers.get('X-HuntMob-Device',''))
                    else:
                        result = ios_static.inspect_ipa(path) if route == '/api/ios/analyze' else ios_worker.install_zip(path)
            except (OSError, ValueError, subprocess.TimeoutExpired, __import__('zipfile').BadZipFile) as error:
                result = {'ok':False,'reason':str(error) if isinstance(error,ValueError) else 'Build iOS não instalado; confira ZIP e Simulator.'}
            body = json.dumps(result).encode(); self.send_response(200 if result.get('ok') else 409); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
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
                    result = AndroidWorker().upload_and_launch(apk, legacy_sdk=self.headers.get("X-HuntMob-Legacy-SDK") == "true", new_lab=self.headers.get("X-HuntMob-New-Lab") == "true", root_mode=self.headers.get("X-HuntMob-Root-Mode", "root"), android_api=int(self.headers.get('X-HuntMob-Android-API','35')), engagement=unquote(self.headers.get('X-HuntMob-Engagement','')))
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
            if not isinstance(payload, dict):
                raise ValueError('JSON object required')
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "invalid JSON request")
            return
        if not payload.get("authorized") or not payload.get("approved"):
            result = {"ok": False, "blocked": True, "reason": "authorization and explicit approval are required"}
            status = 403
        else:
            worker = AndroidWorker()
            if route == '/api/workspace/device/action':
                result = workspace_devices.action(payload)
                status = 200 if result.get('ok') else 409
            elif route == '/api/ios/action':
                try:
                    action = payload.get('action')
                    if action == 'start': result = ios_worker.start()
                    elif action == 'install-runtime':
                        from .ios_runtimes import install
                        result=install(payload.get('version'))
                    elif action == 'new-lab': result=ios_worker.new_lab(payload.get('runtime'),payload.get('model'),payload.get('access','stock'), payload.get('engagement',''))
                    elif action == 'device-control': result=ios_worker.device_control({**payload,'action':payload.get('control')})
                    elif action == 'frida-inspect':
                        from .ios_instrumentation import inspect_native
                        try: result=inspect_native()
                        except Exception as error:
                            result={'ok':False,'reason':str(error) if isinstance(error,ValueError) else 'Frida recusou a conexão ao app do Simulator.','error_type':type(error).__name__}
                    elif action in {'proxy-start','proxy-stop','proxy-clear'}:
                        from . import ios_proxy
                        result={'proxy-start':ios_proxy.start,'proxy-stop':ios_proxy.stop,'proxy-clear':ios_proxy.clear}[action]()
                    elif action == 'xtool-launch':
                        from . import ios_xtool
                        result=ios_xtool.launch(payload.get('udid'),payload.get('bundle_id'))
                    elif action == 'fixture': result = ios_worker.fixture()
                    elif action == 'stop': result = ios_worker.shutdown()
                    elif action == 'capture':
                        record, image = ios_worker.capture_image()
                        result = {'ok':True,'record':EvidenceStore().capture(image,serial=record['udid'],selected_package=record.get('package_id',''),lab_id='ios_'+record['udid'])}
                    else: result = ios_worker.input_action(payload)
                except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
                    result = {'ok':False,'reason':str(error) if isinstance(error,ValueError) else 'Operação iOS não concluída.'}
                status = 200 if result.get('ok') else 409
            elif route == "/api/evidence/capture":
                package = payload.get("package_id", "")
                if not isinstance(package, str) or (package and not PACKAGE_ID.fullmatch(package)):
                    result, status = {"ok": False, "reason": "Invalid selected package"}, 400
                else:
                    try:
                        record = EvidenceStore().capture(worker.screenshot(), serial=worker.serial, selected_package=package, lab_id=current_lab().get("id", ""))
                        result, status = {"ok": True, "record": record}, 200
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        result, status = {"ok": False, "reason": "Screenshot could not be saved; check device and local storage"}, 409
            elif route == '/api/dynamic':
                try:
                    action = payload.get('action')
                    if action == 'prepare': result = DYNAMIC.prepare()
                    elif action == 'start':
                        result = DYNAMIC.start(payload)
                        if result.get('ok') and payload.get('include_proxy'):
                            result['proxy'] = worker.start_managed_proxy()
                    elif action == 'stop':
                        result = DYNAMIC.stop()
                        if DYNAMIC.snapshot().get('receipt'):
                            result['report'] = native_dast.generate(DYNAMIC)
                    elif action == 'analyze':
                        result = {'ok': True, 'report': native_dast.generate(DYNAMIC)}
                    elif action == 'capture':
                        from .dynamic_runtime import scope
                        lab = scope(payload.get('package_id'))
                        record = EvidenceStore().capture(worker.screenshot(), serial=worker.serial, selected_package=lab['package_id'], lab_id=lab['id'])
                        result = {'ok': True, 'record': record}
                    else: result = {'ok': False, 'reason': 'Operação DAST desconhecida.'}
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    result = {'ok': False, 'reason': 'Operação DAST não concluída. Verifique app selecionado, device e armazenamento local.'}
                status = 200 if result.get('ok') else 409
            elif route == "/api/network/clear":
                result, status = clear_capture(network_store()), 200
            elif route == "/api/network/send":
                result = replay(payload)
                status = 200 if result.get("ok") else 409
            elif route == '/api/device/direct-input':
                result = CODEC_RELAY.input(payload)
                status = 200 if result.get('ok') else 409
            elif route == "/api/device/control":
                result = device_control(worker, payload)
                status = 200 if result.get('ok') else 409
            elif route == "/api/device/input":
                result = worker.device_input(payload)
                status = 200 if result.get("ok") else 409
            elif route == '/api/reverse/inspect':
                try: result = reverse_engines.start(payload)
                except (OSError, ValueError, KeyError, TypeError):
                    result = {'ok': False, 'reason': 'Inspeção não iniciada. Confira seleção do app, execução, SHA256, seletores e configuração do REA.'}
                status = 200 if result.get('ok') else 409
            elif route == '/api/reverse/review':
                try: result = reverse_engines.record_review(payload)
                except (OSError, ValueError, KeyError, TypeError):
                    result = {'ok': False, 'reason': 'Avaliação não registrada. Confira identidade, formato e Evidence IDs desta execução.'}
                status = 200 if result.get('ok') else 409
            elif route == '/api/reverse/model-review':
                try: result = reverse_engines.start_model_review(payload)
                except (OSError, ValueError, KeyError, TypeError):
                    result = {'ok': False, 'reason': 'Modelo local não iniciado. Confira Ollama, evidências REA e identidade do APK selecionado.'}
                status = 200 if result.get('ok') else 409
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
                elif proxy_action == "open-cert-settings":
                    result = worker.open_certificate_settings()
                else:
                    result = {"ok": False, "reason": "unknown proxy action"}
                status = 200 if result.get("ok") else 409
            else:
                actions = {"select-target": lambda: worker.select_target(payload.get("package_id")), "open-play-store": lambda: worker.open_play_store(payload.get("package_id", "")), "start": worker.start, "stop": worker.stop, "reboot": worker.reboot, "destroy": worker.destroy, "prepare-root-profile": lambda: worker.prepare_profile(payload.get("root_mode")), "root-profile": lambda: change_root_profile(worker, payload.get("root_mode"), expected_lab_id=payload.get("lab_id")), "new-lab": lambda: create_lab(worker, root_mode=payload.get("root_mode", "root"), android_api=payload.get("android_api",35), engagement=payload.get("engagement","")), "resume": lambda: resume_lab(worker, payload.get("lab_id"))}
                actions['new-play-lab'] = lambda: create_play_lab(worker, payload.get('package_id', ''), android_api=payload.get('android_api', 35))
                action = actions.get(str(payload.get("action", "")))
                if action is None:
                    result, status = {"ok": False, "reason": "unknown device action"}, 400
                else:
                    try:
                        result = action()
                        status = 200 if result.get("ok") else 409
                    except (ValueError, TypeError):
                        result, status = {'ok':False,'reason':'Parâmetros da operação inválidos; confira app, perfil e engagement.'}, 400
                    except (OSError, subprocess.TimeoutExpired):
                        result, status = {'ok':False,'reason':'Worker não concluiu a operação. Atualize o estado antes de repetir.'}, 409
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
        old_handler = None
        if threading.current_thread() is threading.main_thread():
            def terminate(signum, frame):
                raise KeyboardInterrupt
            old_handler = signal.signal(signal.SIGTERM, terminate)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            from . import ios_proxy
            ios_proxy.stop()
            CODEC_RELAY.shutdown()
            workspace_devices.shutdown()
            reverse_engines.shutdown()
            ios_worker.IOS_RELAY.shutdown()
            ios_worker.close_input_bridge()
            DYNAMIC.stop()
            SCREEN_RELAY.shutdown()
            if old_handler is not None:
                signal.signal(signal.SIGTERM, old_handler)
