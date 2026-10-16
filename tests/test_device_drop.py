import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from huntmob import device_drop


class DeviceDropTests(unittest.TestCase):
    def test_filename_cannot_escape_downloads(self):
        for value in ('..', '../other.txt', '%2e%2e%2fother.txt', 'a%5cb.txt', 'a%00b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                device_drop.safe_name(value)
        self.assertEqual(device_drop.safe_name('foto%20teste.png'), 'foto teste.png')

    def test_target_must_belong_to_current_workspace(self):
        with patch('huntmob.device_drop.current', return_value={'id': 'huntmob_lab_' + 'a'*32}):
            with self.assertRaisesRegex(ValueError, 'selecionado mudou'):
                device_drop.target('huntmob_lab_' + 'b'*32, 'huntmob_lab_' + 'b'*32)

    def test_regular_file_goes_to_selected_worker_without_install(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'upload.txt'
            source.write_text('fixture')
            worker = Mock()
            worker.sdk.adb = Path('/sdk/adb')
            worker.serial = 'emulator-5558'
            worker.avd_name = 'huntmob_lab_' + 'b'*32
            worker.status.return_value = {'state': 'device'}
            with patch('huntmob.device_drop._run', return_value=Mock(returncode=0, stderr='')) as run:
                result = device_drop.deliver(worker, source, 'foto teste.txt')
            self.assertTrue(result['ok'])
            self.assertEqual(result['kind'], 'file')
            commands = [call.args[0] for call in run.call_args_list]
            self.assertTrue(any(command[3] == 'push' and command[5].startswith('/sdcard/Download/HuntMob/') for command in commands))
            self.assertTrue(all('install' not in command for command in commands))
            self.assertTrue(all(command[2] == 'emulator-5558' for command in commands))

    def test_invalid_apk_stops_before_install(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'upload.apk'
            source.write_bytes(b'not-an-apk')
            worker = Mock()
            worker.sdk.root = Path('/sdk')
            worker.status.return_value = {'state': 'device'}
            with patch('pathlib.Path.glob', return_value=[Path('/sdk/build-tools/35/aapt')]), patch('huntmob.device_drop._run', return_value=Mock(returncode=1, stdout='')):
                result = device_drop.deliver(worker, source, 'app.apk')
            self.assertFalse(result['ok'])
            worker.install_and_launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
