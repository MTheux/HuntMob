import unittest
from unittest.mock import patch
from huntmob.lab_backend import ensure_backend


class LabBackendTests(unittest.TestCase):
    def test_other_apps_never_start_training_backend(self):
        with patch('huntmob.lab_backend.supported_lab',return_value=False),patch('huntmob.lab_backend.subprocess.Popen') as launch:
            self.assertFalse(ensure_backend()['ok'])
            launch.assert_not_called()

    def test_existing_listener_is_not_replaced(self):
        with patch('huntmob.lab_backend.supported_lab',return_value=True),patch('huntmob.lab_backend.listening',return_value=True),patch('huntmob.lab_backend.subprocess.Popen') as launch:
            result=ensure_backend()
            self.assertTrue(result['ok']);self.assertFalse(result['started'])
            launch.assert_not_called()
