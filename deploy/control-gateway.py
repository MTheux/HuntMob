"""Loopback Docker gateway for a HuntMob worker running on the native host."""

from http.client import HTTPConnection, HTTPException
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
from urllib.parse import urlsplit


HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "expect",
}
MAX_UPLOAD = 512 * 1024 * 1024
SECRET = Path(os.environ.get("HUNTMOB_GATEWAY_SECRET_PATH", "/run/secrets/worker_secret")).read_text(encoding="ascii").strip()
if not 32 <= len(SECRET) <= 256:
    raise SystemExit("Invalid worker bridge secret")


class Gateway(SimpleHTTPRequestHandler):
    worker_host = "host.docker.internal"
    worker_port = 8092

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="/app/web", **kwargs)

    def log_message(self, *_args):
        # Requests can contain client evidence; do not log paths or headers.
        pass

    def _allowed_host(self):
        hosts = self.headers.get_all("Host") or []
        return len(hosts) == 1 and hosts[0] in {"127.0.0.1:8090", "localhost:8090"}

    def _handle(self):
        if not self._allowed_host():
            self.send_error(403, "Invalid host")
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            self._proxy()
        elif self.command in {"GET", "HEAD"}:
            if self.command == "HEAD":
                super().do_HEAD()
            else:
                super().do_GET()
        else:
            self.send_error(404)

    def _proxy(self):
        if self.command not in {"GET", "HEAD", "POST"}:
            self.send_error(405)
            return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(400, "Chunked uploads are unavailable")
            return
        lengths = self.headers.get_all("Content-Length") or []
        try:
            if len(lengths) > 1 or (self.command == "POST" and len(lengths) != 1):
                raise ValueError
            length = int(lengths[0]) if lengths else 0
            if not 0 <= length <= MAX_UPLOAD:
                raise ValueError
        except ValueError:
            self.send_error(413, "Invalid upload size")
            return
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1:
            self.send_error(403, "Invalid origin")
            return
        origin = origins[0] if origins else None
        if origin and origin not in {"http://127.0.0.1:8090", "http://localhost:8090"}:
            self.send_error(403, "Invalid origin")
            return
        upstream = HTTPConnection(self.worker_host, self.worker_port, timeout=240)
        replied = False
        try:
            upstream.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            upstream.putheader("Host", f"{self.worker_host}:{self.worker_port}")
            upstream.putheader("X-HuntMob-Worker-Secret", SECRET)
            for key, value in self.headers.items():
                if key.lower() not in HOP_HEADERS | {"host", "content-length", "x-huntmob-worker-secret"}:
                    upstream.putheader(key, value)
            if self.command == "POST":
                upstream.putheader("Content-Length", str(length))
            upstream.endheaders()
            remaining = length if self.command == "POST" else 0
            while remaining:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    raise OSError("Incomplete upload")
                upstream.send(chunk)
                remaining -= len(chunk)
            response = upstream.getresponse()
            self.send_response(response.status)
            replied = True
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                while True:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (OSError, HTTPException):
            if not replied:
                self.send_error(502, "Native HuntMob worker unavailable")
            self.close_connection = True
        finally:
            upstream.close()

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def do_POST(self):
        self._handle()


if __name__ == "__main__":
    with ThreadingHTTPServer(("0.0.0.0", 8090), Gateway) as server:
        server.serve_forever()
