import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from huntmob.analysis_core import EmbeddedAnalysis
from scripts.build_analysis_bundle import relative


class EmbeddedCoreTests(unittest.TestCase):
    def bundle(self, folder):
        root = Path(folder)
        core = EmbeddedAnalysis(root)
        executable = 'java/bin/java.exe' if core.target.startswith('windows-') else 'java/bin/java'
        files = {}
        for name in ('engine.jar', executable):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'controlled runtime fixture')
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (root/'bundle.json').write_text(json.dumps({'schema':1,'target':core.target,'files':files,'java_executable':executable,'engine_version':'1.5.5','java_version':'21'}))
        return core

    def test_missing_bundle_does_not_use_system_installation(self):
        with tempfile.TemporaryDirectory() as folder, patch('shutil.which', side_effect=AssertionError('PATH lookup forbidden')):
            self.assertFalse(EmbeddedAnalysis(Path(folder)).status()['ready'])

    def test_embedded_paths_are_used_even_with_missing_external_java(self):
        with tempfile.TemporaryDirectory() as folder:
            core = self.bundle(folder)
            self.assertTrue(core.status()['ready'])
            command = core.command(Path('app.apk'),Path('out'))
            self.assertTrue(command[0].startswith(folder))
            self.assertIn('-Xmx2048m', command)
            self.assertIn('jadx.cli.JadxCLI', command)
            with patch.dict('os.environ', {'PATH':'','JAVA_HOME':'/missing','JAVA_TOOL_OPTIONS':'-javaagent:unapproved'}):
                environment=core.environment()
                self.assertEqual(environment['JAVA_HOME'],str(core.root/'java'))
                self.assertNotIn('JAVA_TOOL_OPTIONS',environment)

    def test_tampered_binary_blocks_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            core = self.bundle(folder)
            (core.root/'engine.jar').write_bytes(b'tampered')
            self.assertFalse(core.status()['ready'])
            with self.assertRaises(RuntimeError):core.command(Path('app.apk'),Path('out'))

    def test_archive_paths_cannot_escape_release(self):
        for name in ('../escape','/absolute','C:/windows','a\\b'):
            with self.assertRaises(ValueError):relative(name)
