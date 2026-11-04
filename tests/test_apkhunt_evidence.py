import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from huntmob import apkhunt_evidence
from huntmob.ui import HuntMobHandler, SESSION_TOKEN


class ApkhuntEvidenceTests(unittest.TestCase):
    LAB = {"id": "lab_one", "package_id": "com.lab.app", "apk_sha256": "a" * 64}

    def report(self, **metadata):
        return json.dumps({
            "scan_metadata": {"apk_sha256": "a" * 64, "package_name": "com.lab.app",
                              "coverage_status": "partial", "source_files_scanned": 42, **metadata},
            "findings": [{"id": "MSTG-TEST", "rule_title": "Review WebView", "severity": "Medium",
                          "masvs": "MASVS-PLATFORM", "cwe": "CWE-749", "file": "src/Main.java",
                          "line": 18, "code": "SECRET_NEVER_PERSIST", "desc": "PRIVATE_NEVER_PERSIST"}],
            "secrets_snapshot": {"token": "SECRET_NEVER_PERSIST"},
        }).encode()

    def test_import_keeps_only_bounded_static_metadata(self):
        with tempfile.TemporaryDirectory() as directory, patch('huntmob.apkhunt_evidence.root', return_value=Path(directory)):
            snapshot = apkhunt_evidence.save(self.report(), self.LAB)
            stored = apkhunt_evidence.latest(self.LAB)
        self.assertEqual(snapshot['total_static_leads'], 1)
        self.assertEqual(stored['leads'][0]['status'], 'static_lead_needs_runtime_validation')
        self.assertEqual(stored['coverage_status'], 'partial')
        self.assertNotIn('SECRET_NEVER_PERSIST', json.dumps(stored))
        self.assertNotIn('PRIVATE_NEVER_PERSIST', json.dumps(stored))

    def test_rejects_other_apk_or_package(self):
        for metadata in ({'apk_sha256': 'b' * 64}, {'package_name': 'com.other.app'}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                apkhunt_evidence.normalize(self.report(**metadata), self.LAB)

    def test_previous_import_is_hidden_after_apk_change(self):
        with tempfile.TemporaryDirectory() as directory, patch('huntmob.apkhunt_evidence.root', return_value=Path(directory)):
            apkhunt_evidence.save(self.report(), self.LAB)
            self.assertIsNone(apkhunt_evidence.latest({**self.LAB, 'apk_sha256': 'b' * 64}))

    def test_rejects_missing_identity_and_oversized_input(self):
        with self.assertRaises(ValueError):
            apkhunt_evidence.normalize(json.dumps({'scan_metadata': {}, 'findings': []}).encode(), self.LAB)
        with self.assertRaises(ValueError):
            apkhunt_evidence.normalize(b' ' * (apkhunt_evidence.MAX_REPORT_BYTES + 1), self.LAB)

    def test_http_import_requires_csrf_approval_and_matching_apk(self):
        class QuietHandler(HuntMobHandler):
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}/api/dynamic/apkhunt'
        headers = {'Content-Type': 'application/json', 'X-HuntMob-Workspace': self.LAB['id'],
                   'X-HuntMob-Device': self.LAB['id'], 'X-HuntMob-Package': self.LAB['package_id']}
        try:
            with tempfile.TemporaryDirectory() as directory, \
                    patch('huntmob.apkhunt_evidence.root', return_value=Path(directory)), \
                    patch('huntmob.dynamic_runtime.scope', return_value=self.LAB), \
                    patch('huntmob.dynamic_runtime.target_context', return_value=self.LAB):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base, data=self.report(), headers=headers), timeout=3)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                headers['X-HuntMob-CSRF'] = SESSION_TOKEN
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base, data=self.report(), headers=headers), timeout=3)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                headers['X-HuntMob-Approved'] = 'true'
                with urlopen(Request(base, data=self.report(), headers=headers), timeout=3) as response:
                    self.assertEqual(json.load(response)['report']['total_static_leads'], 1)
                with urlopen(base, timeout=3) as response:
                    self.assertEqual(json.load(response)['report']['package_id'], self.LAB['package_id'])
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base, data=self.report(apk_sha256='b' * 64), headers=headers), timeout=3)
                self.assertEqual(error.exception.code, 409)
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
