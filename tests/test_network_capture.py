import unittest
from huntmob.network_capture import redact


class CaptureTests(unittest.TestCase):
    def test_google_tls_exclusions_are_bounded_and_keep_app_backends(self):
        import re
        from huntmob.network_capture import GOOGLE_TLS_PASSTHROUGH
        for host in ('www.google.com:443', 'accounts.google.com:443', 'www.google.com.br:443', 'ssl.gstatic.com:443', 'lh3.googleusercontent.com:443'):
            with self.subTest(host=host):
                self.assertIsNotNone(re.fullmatch(GOOGLE_TLS_PASSTHROUGH, host))
        for host in ('google.com.evil.test:443', 'evilgoogle.com:443', 'api.googleapis.com:443', '10.0.2.2:8888', 'google.com:80'):
            with self.subTest(host=host):
                self.assertIsNone(re.fullmatch(GOOGLE_TLS_PASSTHROUGH, host))

    def test_google_passthrough_preserves_custom_exclusions_and_is_idempotent(self):
        from huntmob.network_capture import GOOGLE_TLS_PASSTHROUGH, preserve_google_tls
        class Options:
            ignore_hosts = ['^owned.example:443$']
            def update(self, **values):
                self.ignore_hosts = values['ignore_hosts']
        options = Options()
        preserve_google_tls(options)
        preserve_google_tls(options)
        self.assertEqual(options.ignore_hosts, ['^owned.example:443$', GOOGLE_TLS_PASSTHROUGH])

    def test_credentials_are_redacted_recursively(self):
        value = {"Authorization": "secret", "Cookie": "session", "items": [{"password": "secret", "count": 3}]}
        result = redact(value)
        self.assertEqual(result["Authorization"], "[REDACTED]")
        self.assertEqual(result["Cookie"], "[REDACTED]")
        self.assertEqual(result["items"][0], {"password": "[REDACTED]", "count": 3})

class FormCaptureTests(unittest.TestCase):
    def test_login_form_preserves_field_names_but_redacts_credentials(self):
        from types import SimpleNamespace
        from huntmob.network_capture import body
        from urllib.parse import parse_qsl
        message=SimpleNamespace(raw_content=b'username=lab-user&password=lab-pass&mode=test',headers={'Content-Type':'application/x-www-form-urlencoded'},get_text=lambda **kwargs:'username=lab-user&password=lab-pass&mode=test')
        self.assertEqual(dict(parse_qsl(body(message))),{'username':'[REDACTED]','password':'[REDACTED]','mode':'test'})

    def test_request_appears_before_response_and_is_updated(self):
        import tempfile,json
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from huntmob.network_capture import NetworkCapture
        with tempfile.TemporaryDirectory() as directory, patch('huntmob.network_capture.Path.home',return_value=Path(directory)), patch('huntmob.network_capture.STORE',Path(directory)/'network.json'):
            request=SimpleNamespace(headers={'User-Agent':'Android','Content-Type':'application/json'},url='http://127.0.0.1/login',host='127.0.0.1',port=80,scheme='http',method='POST',timestamp_start=1,raw_content=b'{}',get_text=lambda **kwargs:'{}')
            flow=SimpleNamespace(id='controlled',request=request,response=None,metadata={})
            capture=NetworkCapture();capture.request(flow)
            self.assertEqual(len(capture.flows),1)
            self.assertIsNone(capture.flows[0]['status'])
            flow.response=SimpleNamespace(headers={},raw_content=b'{}',get_text=lambda **kwargs:'{}',timestamp_end=2,status_code=200)
            capture.response(flow)
            self.assertEqual(len(capture.flows),1)
            self.assertEqual(capture.flows[0]['status'],200)

    def test_android_host_alias_rewrites_upstream_but_preserves_evidence(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from huntmob.network_capture import NetworkCapture
        with tempfile.TemporaryDirectory() as directory, patch('huntmob.network_capture.Path.home',return_value=Path(directory)), patch('huntmob.network_capture.STORE',Path(directory)/'network.json'):
            request=SimpleNamespace(headers={'User-Agent':'Android','Host':'10.0.2.2:8888'},url='http://10.0.2.2:8888/login',host='10.0.2.2',port=8888,scheme='http',method='POST',timestamp_start=1,raw_content=b'',get_text=lambda **kwargs:'')
            flow=SimpleNamespace(id='local-login',request=request,response=None,metadata={})
            capture=NetworkCapture();capture.request(flow)
            self.assertEqual(request.host,'127.0.0.1')
            capture.error(flow)
            self.assertEqual(capture.flows[0]['host'],'10.0.2.2')
            self.assertEqual(capture.flows[0]['request']['headers']['Host'],'10.0.2.2:8888')

class ClearCaptureTests(unittest.TestCase):
    def test_clear_hides_old_and_late_responses_but_accepts_new_traffic(self):
        import tempfile,json,time
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from huntmob.network_capture import NetworkCapture,clear_capture,visible_snapshot
        with tempfile.TemporaryDirectory() as directory, patch('huntmob.network_capture.Path.home',return_value=Path(directory)), patch('huntmob.network_capture.STORE',Path(directory)/'network.json'):
            store=Path(directory)/'network.json'
            request=SimpleNamespace(headers={'User-Agent':'Android'},url='http://127.0.0.1/login',host='127.0.0.1',port=80,scheme='http',method='POST',timestamp_start=time.time()-1,raw_content=b'',get_text=lambda **kwargs:'')
            flow=SimpleNamespace(id='old',request=request,response=None,metadata={})
            capture=NetworkCapture();capture.request(flow)
            clear_capture(store)
            self.assertEqual(visible_snapshot(store)['flows'],[])
            capture.error(flow)
            self.assertEqual(visible_snapshot(store)['flows'],[])
            request.timestamp_start=time.time()+1;flow.id='new'
            capture.request(flow)
            self.assertEqual([x['id'] for x in visible_snapshot(store)['flows']],['new'])
            self.assertEqual(visible_snapshot(store)['flows'][0]['state'],'pending')
