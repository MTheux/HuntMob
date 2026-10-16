import socket
import unittest
from unittest.mock import patch
from huntmob import ios_proxy, ios_worker

RECORD={'udid':'00000000-0000-0000-0000-000000000001','package_id':'com.huntmob.ios.lab','binary_sha256':'a'*64}

class IosProxyTests(unittest.TestCase):
    def test_ios_store_never_uses_android_namespace(self):
        self.assertEqual(ios_proxy.store(RECORD).parent.name,'ios_00000000000000000000000000000001')

    def test_occupied_listener_is_not_adopted(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            with patch.object(ios_proxy,'PORT',listener.getsockname()[1]), patch.object(ios_proxy,'PROCESS',None), patch.object(ios_worker,'owned',return_value=RECORD), patch.object(ios_proxy.shutil,'which',return_value='mitmdump'), patch.object(ios_proxy.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(ValueError,'ocupada'):
                    ios_proxy.start()
                launch.assert_not_called()

    def test_capture_of_previous_device_is_not_current(self):
        with patch.object(ios_worker,'saved',return_value=RECORD), patch.object(ios_proxy,'TARGET','other'), patch.object(ios_proxy,'PROCESS') as process, patch.object(ios_proxy,'store') as path:
            process.poll.return_value=None
            path.return_value.exists.return_value=False
            self.assertFalse(ios_proxy.status()['active'])

    def test_invalid_biometric_event_never_reaches_device(self):
        with patch.object(ios_worker,'owned',return_value=RECORD), patch.object(ios_worker,'sim') as command:
            with self.assertRaises(ValueError):
                ios_worker.device_control({'action':'biometric','kind':'face','mode':'arbitrary'})
            command.assert_not_called()
