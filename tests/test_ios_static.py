import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from huntmob.ios_static import inspect_ipa

class IpaInspectionTests(unittest.TestCase):
    def archive(self, entries):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/'app.ipa'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, content in entries:
                archive.writestr(name, content)
        return path

    def test_binary_plist_metadata_without_sensitive_values(self):
        path = self.archive([('Payload/Lab.app/Info.plist', plistlib.dumps({'CFBundleIdentifier':'com.huntmob.lab', 'NSCameraUsageDescription':'private explanation', 'API_KEY':'private value', 'CFBundleURLTypes':[{'CFBundleURLSchemes':['lab']}], 'NSAppTransportSecurity':{'NSAllowsArbitraryLoads':True}}, fmt=plistlib.FMT_BINARY))])
        result = inspect_ipa(path)
        self.assertEqual(result['url_schemes'], ['lab'])
        self.assertEqual(result['permission_keys'], ['NSCameraUsageDescription'])
        self.assertTrue(result['ats']['allows_arbitrary_loads'])
        self.assertNotIn('private', str(result))
        self.assertEqual(len(result['sha256']), 64)

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            inspect_ipa(self.archive([('../bad', b'')]))

    def test_missing_app_rejected(self):
        with self.assertRaises(ValueError):
            inspect_ipa(self.archive([('Info.plist', b'')]))

    def test_ambiguous_app_rejected(self):
        with self.assertRaises(ValueError):
            inspect_ipa(self.archive([(f'Payload/{name}.app/Info.plist', plistlib.dumps({})) for name in ['One','Two']]))
