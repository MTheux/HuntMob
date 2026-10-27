import http.client
from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from huntmob.operator_auth import OperatorSession, COOKIE, local_key, write_access_url
from huntmob.ui import HuntMobHandler, trusted_origins
from huntmob.device_mcp import WorkerClient


class OperatorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.operator = OperatorSession('a' * 64)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), HuntMobHandler)
        self.server.operator_session = self.operator
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path='/api/session', method='GET', headers=None, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_guest_cannot_mint_csrf_or_read_evidence_with_forged_loopback_host(self):
        headers = {'Host': f'127.0.0.1:{self.server.server_port}'}
        for path in ('/api/session', '/api/evidence', '/api/device/status'):
            status, _, body = self.request(path, headers=headers)
            self.assertEqual(status, 401)
            self.assertNotIn(b'csrf_token', body)
        self.assertEqual(self.request('/api/client/ping')[0], 200)

    def test_rebinding_and_foreign_origins_are_rejected_before_session_routing(self):
        value=self.operator.cookie();cookie = COOKIE + '=' + value
        for headers in ({'Host':'attacker.test','Cookie':cookie}, {'Origin':'https://attacker.test','Cookie':cookie}):
            self.assertEqual(self.request(headers=headers)[0], 403)

    def test_bootstrap_sets_private_cookie_and_then_allows_csrf(self):
        payload = json.dumps({'token': self.operator.bootstrap})
        status, headers, body = self.request('/api/auth/bootstrap', 'POST', {'Content-Type':'application/json'}, payload)
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Strict', cookie)
        proof=json.loads(body)['proof']
        status, _, body = self.request(headers={'Cookie': cookie.split(';')[0], 'X-HuntMob-Operator':proof})
        self.assertEqual(status, 200); self.assertIn('csrf_token', json.loads(body))

    def test_stolen_cookie_alone_is_insufficient_and_read_tickets_are_path_bound(self):
        cookie=self.operator.cookie()
        headers={'Cookie': COOKIE+'='+cookie}
        self.assertEqual(self.request(headers=headers)[0],401)
        path='/api/pentest/readiness?platform=other'
        ticket=self.operator.ticket(path,cookie)
        self.assertEqual(self.request('/api/session?_operator_ticket='+ticket,headers=headers)[0],401)
        self.assertEqual(self.request('/api/evidence?_operator_ticket='+ticket,headers=headers)[0],401)
        headers['X-HuntMob-Operator']=self.operator.proof(cookie)
        self.assertEqual(self.request(headers=headers)[0],200)

    def test_invalid_bootstrap_tampered_and_expired_cookies_fail(self):
        self.assertEqual(self.request('/api/auth/bootstrap', 'POST', {}, json.dumps({'token':'x'}))[0], 401)
        cookie = self.operator.cookie()
        for value in (cookie + 'x', str(int(time.time())-1)+'.'+cookie.split('.')[1]):
            self.assertEqual(self.request(headers={'Cookie':COOKIE+'='+value})[0], 401)

    def test_second_tab_bootstrap_preserves_existing_tab_proof(self):
        cookie=self.operator.cookie();proof=self.operator.proof(cookie)
        with patch('huntmob.operator_auth.time.time',return_value=time.time()+60):
            self.assertEqual(self.operator.cookie(),cookie)
            self.assertEqual(self.operator.proof(self.operator.cookie()),proof)

    def test_local_stdio_client_bootstraps_from_private_file_without_exporting_secret(self):
        with tempfile.TemporaryDirectory() as directory, patch('pathlib.Path.home', return_value=Path(directory)):
            write_access_url(self.operator, f'http://127.0.0.1:{self.server.server_port}')
            client = WorkerClient(self.server.server_port, 'huntmob_lab_'+'a'*32)
            result = client.request('/api/session')
            self.assertIn('csrf_token', result)

    def test_access_files_are_private_and_origin_configuration_is_exact(self):
        with tempfile.TemporaryDirectory() as directory, patch('pathlib.Path.home', return_value=Path(directory)):
            key = local_key()
            self.assertEqual(local_key(), key)
            path = write_access_url(OperatorSession(key), 'http://127.0.0.1:8090')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for value in ('https://host.test/path', 'https://user:secret@host.test', 'https://host.test/?token=x'):
            with self.assertRaises(ValueError): trusted_origins([value])
