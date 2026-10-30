import io
import unittest
import zipfile

from huntmob.protection_scan import scan_protections


def _apk(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in names:
            archive.writestr(name, b'\x00')
    buffer.seek(0)
    return buffer


class ProtectionScanTests(unittest.TestCase):
    def test_detects_dexguard_and_rootbeer_from_native_libs(self):
        result = scan_protections(_apk([
            'AndroidManifest.xml', 'classes.dex',
            'lib/arm64-v8a/libdexguard.so', 'lib/arm64-v8a/libtoolChecker.so',
        ]))
        self.assertTrue(result['ok'])
        names = {p['name'] for p in result['protections']}
        self.assertIn('DexGuard', names)
        self.assertIn('RootBeer', names)
        dexguard = next(p for p in result['protections'] if p['name'] == 'DexGuard')
        self.assertIn('lib/arm64-v8a/libdexguard.so', dexguard['evidence'])

    def test_clean_apk_reports_no_known_protection(self):
        result = scan_protections(_apk(['AndroidManifest.xml', 'classes.dex', 'resources.arsc']))
        self.assertTrue(result['ok'])
        self.assertEqual(result['protections'], [])
        self.assertRegex(result['summary'], r'[Nn]enhuma')

    def test_matching_is_case_insensitive(self):
        result = scan_protections(_apk(['lib/armeabi-v7a/libHSTSecurity.so']))
        self.assertIn('HST Security', {p['name'] for p in result['protections']})

    def test_unreadable_input_fails_closed_without_raising(self):
        result = scan_protections(io.BytesIO(b'this is not a zip'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['protections'], [])


class ReverseEngineProtectionsWiringTests(unittest.TestCase):
    WS = 'huntmob_lab_' + 'c' * 32
    PKG = 'br.com.exemplo.app'

    def test_protections_scans_the_sha_bound_apk(self):
        from unittest.mock import patch
        from huntmob import reverse_engines
        apk = _apk(['AndroidManifest.xml', 'classes.dex', 'lib/arm64-v8a/libdexguard.so'])
        record = {'run_id': 'r1', 'sha256': 's1', 'files': ['AndroidManifest.xml']}
        with patch('huntmob.reverse_engines.lab_sessions.current', return_value={'id': self.WS, 'package_id': self.PKG}), \
             patch('huntmob.reverse_engines.reverse_workspace.latest', return_value=record), \
             patch('huntmob.reverse_engines.bound', return_value=(record, apk)):
            result = reverse_engines.protections(self.WS)
        self.assertTrue(result['ok'])
        self.assertTrue(result['prepared'])
        self.assertEqual(result['sha256'], 's1')
        self.assertIn('DexGuard', {p['name'] for p in result['protections']})

    def test_protections_unprepared_when_no_decompilation(self):
        from unittest.mock import patch
        from huntmob import reverse_engines
        with patch('huntmob.reverse_engines.lab_sessions.current', return_value={'id': self.WS, 'package_id': self.PKG}), \
             patch('huntmob.reverse_engines.reverse_workspace.latest', side_effect=KeyError('run')):
            result = reverse_engines.protections(self.WS)
        self.assertTrue(result['ok'])
        self.assertFalse(result['prepared'])
        self.assertEqual(result['protections'], [])

    def test_protections_rejects_a_changed_workspace(self):
        from unittest.mock import patch
        from huntmob import reverse_engines
        with patch('huntmob.reverse_engines.lab_sessions.current', return_value={'id': 'other', 'package_id': self.PKG}):
            with self.assertRaises(ValueError):
                reverse_engines.protections(self.WS)


if __name__ == '__main__':
    unittest.main()
