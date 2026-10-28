import subprocess
import unittest

from huntmob import doctor
from huntmob.doctor import ToolStatus


class DoctorTests(unittest.TestCase):
    def test_check_tools_reports_missing_without_raising(self):
        statuses = doctor.check_tools(which=lambda name: None, run=lambda *a, **k: None)
        self.assertTrue(statuses)  # cobre todas as ferramentas
        self.assertTrue(all(not s.found and s.path is None for s in statuses))

    def test_check_tools_parses_version(self):
        def which(name):
            return '/usr/bin/adb' if name == 'adb' else None

        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, 'Android Debug Bridge version 1.0.41\n', '')

        statuses = {s.name: s for s in doctor.check_tools(which=which, run=run)}
        self.assertTrue(statuses['adb'].found)
        self.assertEqual(statuses['adb'].version, '1.0.41')
        self.assertEqual(statuses['adb'].path, '/usr/bin/adb')
        self.assertFalse(statuses['emulator'].found)

    def test_exit_code_nonzero_when_required_missing(self):
        statuses = [
            ToolStatus('adb', False, None, None, False, None, True),
            ToolStatus('jadx', True, '/j', '1.4', True, None, False),
        ]
        self.assertEqual(doctor.exit_code(statuses), 1)

    def test_exit_code_zero_when_all_required_present(self):
        statuses = [
            ToolStatus('adb', True, '/a', '1.0.41', True, None, True),
            ToolStatus('jadx', False, None, None, False, None, False),
        ]
        self.assertEqual(doctor.exit_code(statuses), 0)


if __name__ == '__main__':
    unittest.main()
