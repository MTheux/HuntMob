import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from huntmob.android_worker import AndroidSdk, AndroidWorker


class ReverseResultTests(unittest.TestCase):
    def result(self, code, produce=True, timeout=False, stderr='', many_files=False):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            sdk = AndroidSdk(home, home/'emulator', home/'adb', home/'avdmanager', home/'sdkmanager')
            def run(command, **kwargs):
                if command[-3:-1] == ('pm', 'path'):
                    return subprocess.CompletedProcess(command, 0, 'package:/data/app/base.apk\n', '')
                if 'pull' in command:
                    Path(command[-1]).write_bytes(b'controlled APK fixture')
                    return subprocess.CompletedProcess(command, 0, '', '')
                if timeout:
                    raise subprocess.TimeoutExpired(command, 300)
                if produce:
                    out = Path(command[2]);out.mkdir(parents=True)
                    (out/'Example.java').write_text('class Example {}')
                    if many_files:
                        for index in range(5001):
                            (out/f'Class{index}.java').touch()
                return subprocess.CompletedProcess(command, code, 'ERROR - finished with errors, count: 2' if code else '', stderr)
            with patch('huntmob.android_worker.Path.home', return_value=home), patch('huntmob.android_worker.EmbeddedAnalysis') as engine, patch('huntmob.android_worker._run', side_effect=run), patch.object(AndroidWorker, 'status', return_value={'state':'device'}):
                engine.return_value.status.return_value = {'ready': True}
                engine.return_value.command.side_effect = lambda apk, out: ('/managed/java', '--output-dir', str(out), str(apk))
                engine.return_value.environment.return_value = {}
                return AndroidWorker(sdk).prepare_reverse('com.test.app')

    def test_saved_output_with_exit_three_is_partial(self):
        result = self.result(3)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['errors_count'], 2)
        self.assertIn('Example.java', result['files'])
        self.assertTrue(result['sha256'])

    def test_exit_one_remains_failure_even_with_output(self):
        self.assertFalse(self.result(1)['ok'])

    def test_out_of_memory_reports_resource_failure(self):
        result = self.result(1, stderr='java.lang.OutOfMemoryError: Java heap space')
        self.assertFalse(result['ok'])
        self.assertIn('Memória insuficiente', result['reason'])

    def test_large_partial_run_skips_expensive_second_pass(self):
        result = self.result(3, many_files=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['fallback_status'], 'skipped_large_analysis')

    def test_exit_three_without_output_is_failure(self):
        self.assertFalse(self.result(3, produce=False)['ok'])

    def test_exit_zero_without_output_is_failure(self):
        self.assertFalse(self.result(0, produce=False)['ok'])

    def test_success_is_complete(self):
        self.assertEqual(self.result(0)['status'], 'complete')

    def test_timeout_returns_actionable_failure(self):
        result = self.result(0, timeout=True)
        self.assertFalse(result['ok'])
        self.assertIn('5 minutos', result['reason'])
