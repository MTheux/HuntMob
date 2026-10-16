import json
import unittest
from unittest.mock import patch
from huntmob.network_replay import replay


class ReplayTests(unittest.TestCase):
    @patch("pathlib.Path.read_text")
    def test_external_destination_is_blocked(self, read):
        read.return_value = json.dumps({"flows": [{"id": "flow", "host": "example.com", "port": 443}]})
        result = replay({"flow_id": "flow"})
        self.assertFalse(result["ok"])
        self.assertIn("loopback", result["reason"])

    @patch("pathlib.Path.read_text")
    def test_redacted_credentials_are_not_replayed(self, read):
        read.return_value = json.dumps({"flows": [{"id": "flow", "host": "127.0.0.1", "port": 8090}]})
        result = replay({"flow_id": "flow", "method": "GET", "path": "/", "headers": {"Authorization": "[REDACTED]"}})
        self.assertFalse(result["ok"])
        self.assertIn("redigidos", result["reason"])

    @patch('pathlib.Path.read_text')
    def test_encoded_redacted_form_is_not_sent(self, read):
        read.return_value=json.dumps({'flows':[{'id':'flow','host':'10.0.2.2','port':8888,'scheme':'http'}]})
        with patch('huntmob.network_replay.http.client.HTTPConnection') as connection:
            result=replay({'flow_id':'flow','method':'POST','path':'/login','body':'password=%5BREDACTED%5D'})
            self.assertFalse(result['ok'])
            self.assertIn('redigidos',result['reason'])
            connection.assert_not_called()

    @patch('pathlib.Path.read_text')
    def test_android_alias_sends_to_real_local_backend(self, read):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading
        seen=[]
        class Backend(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.path,self.rfile.read(int(self.headers['Content-Length']))))
                content=b'{"lab_validation":true}'
                self.send_response(200);self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Backend)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            read.return_value=json.dumps({'flows':[{'id':'flow','host':'10.0.2.2','port':server.server_port,'scheme':'http'}]})
            result=replay({'flow_id':'flow','method':'POST','path':'/login','headers':{'Content-Type':'application/x-www-form-urlencoded','Content-Length':'999'},'body':'username=synthetic&password=synthetic'})
            self.assertTrue(result['ok']);self.assertEqual(result['status'],200)
            self.assertEqual(seen,[('/login',b'username=synthetic&password=synthetic')])
        finally:server.shutdown();server.server_close();thread.join()

    @patch('pathlib.Path.read_text')
    def test_connection_failure_identifies_backend(self, read):
        read.return_value=json.dumps({'flows':[{'id':'flow','host':'10.0.2.2','port':8888,'scheme':'http'}]})
        with patch('huntmob.network_replay.http.client.HTTPConnection') as connection:
            connection.return_value.request.side_effect=ConnectionRefusedError()
            result=replay({'flow_id':'flow','method':'GET','path':'/'})
            self.assertFalse(result['ok']);self.assertIn('10.0.2.2:8888',result['reason'])
            connection.return_value.close.assert_called_once()
