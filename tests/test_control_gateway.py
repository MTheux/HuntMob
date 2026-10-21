"""Exercise the Docker bridge boundary without Docker or mobile devices."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import unittest

from huntmob.ui import HuntMobHandler


GATEWAY_FILE = Path(__file__).resolve().parents[1] / "deploy" / "control-gateway.py"


class QuietHuntMob(HuntMobHandler):
    def log_message(self, *_args):
        pass


class EchoWorker(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        body = (self.headers.get("X-HuntMob-Worker-Secret", "") + "|" + self.path).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ControlGatewayTests(unittest.TestCase):
    def setUp(self):
        self.servers = []
        self.threads = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=3)

    def serve(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append(server)
        self.threads.append(thread)
        return server

    def test_native_worker_rejects_direct_requests_without_bridge_secret(self):
        worker = self.serve(QuietHuntMob)
        worker.worker_secret = "a" * 48
        connection = http.client.HTTPConnection("127.0.0.1", worker.server_port, timeout=3)
        connection.request("GET", "/api/client/ping")
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", worker.server_port, timeout=3)
        connection.request("GET", "/api/client/ping", headers={"X-HuntMob-Worker-Secret": "a" * 48})
        self.assertEqual(connection.getresponse().status, 200)
        connection.close()

    def test_gateway_overwrites_browser_supplied_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            secret_file = Path(temporary) / "secret"
            secret_file.write_text("b" * 48)
            previous = os.environ.get("HUNTMOB_GATEWAY_SECRET_PATH")
            os.environ["HUNTMOB_GATEWAY_SECRET_PATH"] = str(secret_file)
            try:
                spec = importlib.util.spec_from_file_location("huntmob_control_gateway_test", GATEWAY_FILE)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finally:
                if previous is None:
                    os.environ.pop("HUNTMOB_GATEWAY_SECRET_PATH", None)
                else:
                    os.environ["HUNTMOB_GATEWAY_SECRET_PATH"] = previous
            worker = self.serve(EchoWorker)
            module.Gateway.worker_host = "127.0.0.1"
            module.Gateway.worker_port = worker.server_port
            gateway = self.serve(module.Gateway)
            connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=3)
            connection.request("GET", "/api/check?x=1", headers={
                "Host": "127.0.0.1:8090", "X-HuntMob-Worker-Secret": "attacker-value"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"b" * 48 + b"|/api/check?x=1")
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=3)
            connection.request("GET", "/api/check", headers={"Host": "untrusted.example"})
            self.assertEqual(connection.getresponse().status, 403)
            connection.close()


if __name__ == "__main__":
    unittest.main()
