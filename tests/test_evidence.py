import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from huntmob.evidence import EvidenceStore


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = EvidenceStore(Path(self.directory.name) / 'evidence')
        self.png = b'\x89PNG\r\n\x1a\ncontrolled-test-fixture'

    def test_capture_and_export_preserve_bytes_and_hash(self):
        record = self.store.capture(self.png, serial='emulator-5556')
        self.assertEqual(record['sha256'], hashlib.sha256(self.png).hexdigest())
        self.assertEqual(self.store.inventory()['records'], [record])
        with zipfile.ZipFile(io.BytesIO(self.store.export(record['id']))) as archive:
            self.assertEqual(archive.read('screenshot.png'), self.png)
            self.assertEqual(json.loads(archive.read('record.json'))['finding_status'], 'not_assessed')
        if os.name != 'nt':
            self.assertEqual((self.store.root / record['id'] / 'screenshot.png').stat().st_mode & 0o777, 0o600)

    def test_tampered_evidence_cannot_be_exported(self):
        record = self.store.capture(self.png, serial='emulator-5556')
        (self.store.root / record['id'] / 'screenshot.png').write_bytes(b'tampered')
        self.assertEqual(self.store.inventory()['invalid_count'], 1)
        self.assertEqual(self.store.inventory()['records'], [])
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.store.export(record['id'])

    def test_missing_screenshot_does_not_create_evidence(self):
        with self.assertRaises(ValueError):
            self.store.capture(b'', serial='emulator-5556')
        self.assertEqual(self.store.inventory()['records'], [])

    def test_identifiers_cannot_escape_store(self):
        with self.assertRaises(ValueError):
            self.store.export('../../file')
