import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from huntmob.reverse_workspace import latest,preview,export,workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.patch=patch('huntmob.reverse_workspace.Path.home',return_value=self.home)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.package='com.test.app';self.avd='huntmob_lab_'+'a'*32;self.run='b'*32
        self.folder=workspace(self.package,self.avd)
        self.output=self.folder/'jadx-runs'/self.run
        (self.output/'sources').mkdir(parents=True)
        (self.output/'sources/Main.java').write_text('class Main { String name = "<script>"; }')
        (self.output/'certificate.bin').write_bytes(b'\x00\xff\x01')
        self.record={'package_id':self.package,'run_id':self.run,'files':['sources/Main.java','certificate.bin']}
        (self.folder/'analysis.json').write_text(json.dumps(self.record))

    def test_source_preview_is_plain_text(self):
        result=preview(self.package,self.avd,self.run,'sources/Main.java')
        self.assertEqual(result['format'],'text')
        self.assertIn('<script>',result['content'])

    def test_binary_preview_is_hex(self):
        result=preview(self.package,self.avd,self.run,'certificate.bin')
        self.assertEqual(result['format'],'hex')
        self.assertIn('00 ff 01',result['content'])

    def test_export_includes_all_recorded_files(self):
        with zipfile.ZipFile(io.BytesIO(export(self.package,self.avd,self.run))) as archive:
            self.assertEqual(set(archive.namelist()),{'analysis.json','sources/Main.java','certificate.bin'})

    def test_traversal_and_unknown_runs_are_blocked(self):
        for path in ('../../secret','/etc/passwd','not-recorded.java'):
            with self.assertRaises(ValueError):preview(self.package,self.avd,self.run,path)
        with self.assertRaises(ValueError):preview(self.package,self.avd,'c'*32,'sources/Main.java')

    def test_symlink_cannot_escape_workspace(self):
        secret=self.home/'outside.txt';secret.write_text('outside')
        path=self.output/'sources/Main.java';path.unlink();path.symlink_to(secret)
        with self.assertRaises(ValueError):preview(self.package,self.avd,self.run,'sources/Main.java')
