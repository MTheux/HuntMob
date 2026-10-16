import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from huntmob import ios_xtool as x

UDID='00008110-0012345678901234'
DEVICE={'udid':UDID,'name':'Owned phone','connection':'USB'}

class XtoolTests(unittest.TestCase):
    def test_devices_is_usb_nonblocking_and_parses_real_udid(self):
        output=f'Owned phone [USB]: {UDID}\nSimulator [USB]: 00000000-0000-0000-0000-000000000001\n'
        with patch.object(x,'run',return_value=subprocess.CompletedProcess([],0,output,'')) as command:
            self.assertEqual(x.devices(),[DEVICE])
            command.assert_called_once_with(['devices','--usb','--no-wait'])

    def test_rejects_simulator_or_cli_option_before_device_query(self):
        with patch.object(x,'devices') as devices:
            for value in ['--network','00000000-0000-0000-0000-000000000001',None]:
                with self.assertRaises(ValueError):x.selected(value)
            devices.assert_not_called()

    def test_disconnected_device_never_runs_install(self):
        with patch.object(x,'devices',return_value=[]),patch.object(x,'run') as command:
            with self.assertRaises(ValueError):x.install(Path('/tmp/app.ipa'),UDID)
            command.assert_not_called()

    def test_install_does_not_guess_or_launch_resigned_bundle(self):
        with patch.object(x,'devices',return_value=[DEVICE]),patch.object(x,'inspect_ipa',return_value={'sha256':'a'*64,'bundle_id':'com.huntmob.fixture'}),patch.object(x,'run',return_value=subprocess.CompletedProcess([],0,'Success','')) as command,patch.object(x,'receipt',return_value={}) as receipt:
            self.assertTrue(x.install(Path('/tmp/app.ipa'),UDID)['ok'])
            self.assertEqual(command.call_args.args[0],['install','--usb','--udid',UDID,str(Path('/tmp/app.ipa').resolve())])
            self.assertFalse(receipt.call_args.kwargs['launch_verified'])
            command.assert_called_once()

    def test_failed_install_never_records_success_or_exposes_cli_output(self):
        with patch.object(x,'devices',return_value=[DEVICE]),patch.object(x,'inspect_ipa',return_value={'sha256':'a'*64,'bundle_id':'com.huntmob.fixture'}),patch.object(x,'run',return_value=subprocess.CompletedProcess([],1,'private output','private error')),patch.object(x,'receipt') as receipt:
            with self.assertRaises(ValueError) as error:x.install(Path('/tmp/app.ipa'),UDID)
            self.assertNotIn('private',str(error.exception));receipt.assert_not_called()

    def test_launch_rejects_flags_without_contacting_device(self):
        with patch.object(x,'devices') as devices:
            with self.assertRaises(ValueError):x.launch(UDID,'--help')
            devices.assert_not_called()

    def test_missing_xtool_is_explicit_and_has_no_devices(self):
        with patch.object(x.shutil,'which',return_value=None):
            status=x.status();self.assertFalse(status['available']);self.assertEqual(status['devices'],[])
