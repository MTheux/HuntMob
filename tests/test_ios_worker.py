import json
import plistlib
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from huntmob import ios_worker

class IosWorkerTests(unittest.TestCase):
    def test_missing_saved_simulator_is_never_silently_replaced(self):
        info={'ready':True,'state':'off','lab':{'udid':'saved-device'},'device':None,'runtimes':[{'id':'ios'}]}
        with patch('huntmob.ios_worker.inventory',return_value=info),patch('huntmob.ios_worker.sim') as command,patch('huntmob.ios_worker.private_json') as save:
            with self.assertRaisesRegex(ValueError,'nenhum novo dispositivo'):
                ios_worker.start()
            command.assert_not_called();save.assert_not_called()

    def test_retaking_saved_lab_boots_same_uuid_without_creating_another(self):
        record={'udid':'saved-device','name':'HuntMob iOS Lab','runtime':'ios'}
        info={'ready':True,'state':'off','lab':record,'device':{'udid':'saved-device'},'runtimes':[{'id':'ios'}]}
        with patch('huntmob.ios_worker.inventory',return_value=info),patch('huntmob.ios_worker.ensure_companion'),patch('huntmob.ios_worker.sim',return_value=subprocess.CompletedProcess([],0,'','')) as command:
            self.assertEqual(ios_worker.start()['lab']['udid'],'saved-device')
            self.assertEqual([call.args for call in command.call_args_list],[('boot','saved-device'),('bootstatus','saved-device','-b')])

    def test_continuous_touch_rejects_stale_device_and_invalid_input_before_bridge(self):
        with patch('huntmob.ios_worker.saved',return_value={'udid':'selected'}),patch('huntmob.ios_worker.subprocess.Popen') as process:
            for payload in ({'udid':'old','phase':'down','x':.5,'y':.5},
                            {'udid':'selected','phase':'invalid','x':.5,'y':.5},
                            {'udid':'selected','phase':'down','x':float('nan'),'y':.5},
                            {'udid':'selected','phase':'move','x':.5,'y':2}):
                with self.assertRaises(ValueError):
                    ios_worker.input_action({'action':'touch',**payload})
            process.assert_not_called()

    def test_jailbreak_request_cannot_create_a_simulator(self):
        with patch('huntmob.ios_worker.sim') as command:
            with self.assertRaisesRegex(ValueError,'jailbreak'):
                ios_worker.new_lab('runtime','model','jailbreak')
            command.assert_not_called()

    def test_incompatible_model_preserves_current_lab(self):
        catalog={'runtimes':[{'id':'com.apple.CoreSimulator.SimRuntime.iOS-27-0'}],
                 'models':[{'id':'iphone7','minimum':655360,'maximum':1048575}]}
        with patch('huntmob.ios_worker.lab_catalog',return_value=catalog),patch('huntmob.ios_worker.sim') as command:
            with self.assertRaisesRegex(ValueError,'incompatível'):
                ios_worker.new_lab(catalog['runtimes'][0]['id'],'iphone7')
            command.assert_not_called()

    def test_ios_gps_validates_bounds_without_contacting_device(self):
        with patch('huntmob.ios_worker.owned',return_value={'udid':'owned'}),patch('huntmob.ios_worker.sim') as command:
            with self.assertRaises(ValueError):
                ios_worker.device_control({'action':'location','latitude':91,'longitude':0})
            command.assert_not_called()

    def test_ios_battery_is_explicitly_status_bar_only(self):
        with patch('huntmob.ios_worker.owned',return_value={'udid':'owned'}),patch('huntmob.ios_worker.sim',return_value=subprocess.CompletedProcess([],0,'','')) as command:
            result=ios_worker.device_control({'action':'battery','level':42})
            self.assertTrue(result['ok'])
            self.assertIn('não modifica',result['reason'])
            self.assertEqual(command.call_args.args,('status_bar','owned','override','--batteryLevel','42'))
    def test_video_batch_discards_stale_frames_and_preserves_partial_frame(self):
        frames=[b'\xff\xd8'+bytes([i])+b'\xff\xd9' for i in range(100)]
        buffer=bytearray(b'header'+b''.join(frames)+b'\xff\xd8partial')
        self.assertEqual(ios_worker.latest_jpeg(buffer),frames[-1])
        self.assertEqual(buffer,b'\xff\xd8partial')
        buffer.extend(b'\xff\xd9')
        self.assertEqual(ios_worker.latest_jpeg(buffer),b'\xff\xd8partial\xff\xd9')
        self.assertEqual(buffer,b'')

    def test_video_marker_split_across_pipe_reads(self):
        buffer=bytearray(b'header\xff')
        self.assertIsNone(ios_worker.latest_jpeg(buffer))
        buffer.extend(b'\xd8owned\xff')
        self.assertIsNone(ios_worker.latest_jpeg(buffer))
        buffer.extend(b'\xd9')
        self.assertEqual(ios_worker.latest_jpeg(buffer),b'\xff\xd8owned\xff\xd9')

    def test_renamed_ipa_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'app.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('Payload/App.app/Info.plist',b'data')
            with patch('huntmob.ios_worker.install_app') as install:
                with self.assertRaisesRegex(ValueError,'estrutura de IPA'):ios_worker.install_zip(archive)
                install.assert_not_called()

    def test_invalid_zip_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'app.zip';archive.write_bytes(b'not a zip')
            with self.assertRaisesRegex(ValueError,'ZIP válido'):ios_worker.install_zip(archive)

    def test_simulator_unavailable_off_macos(self):
        with patch('huntmob.ios_worker.platform.system',return_value='Windows'):
            self.assertFalse(ios_worker.inventory()['ready'])

    def test_inventory_never_adopts_unrelated_simulator(self):
        runtimes={'runtimes':[{'isAvailable':True,'platform':'iOS','identifier':'ios','name':'iOS test'}]}
        devices={'devices':{'ios':[{'udid':'x','name':'User iPhone','state':'Booted'}]}}
        with patch('huntmob.ios_worker.platform.system',return_value='Darwin'),patch('huntmob.ios_worker.saved',return_value={'udid':'x'}),patch('huntmob.ios_worker.sim',side_effect=[subprocess.CompletedProcess([],0,json.dumps(runtimes),''),subprocess.CompletedProcess([],0,json.dumps(devices),'')]):
            self.assertEqual(ios_worker.inventory()['state'],'off')

    def test_zip_traversal_is_rejected_before_extraction_or_install(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'app.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside','data')
            with patch('huntmob.ios_worker.install_app') as install:
                with self.assertRaises(ValueError):ios_worker.install_zip(archive)
                install.assert_not_called()
            self.assertFalse((Path(directory)/'outside').exists())

    def test_zip_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'app.zip';item=zipfile.ZipInfo('App.app/link');item.external_attr=(0o120777<<16)
            with zipfile.ZipFile(archive,'w') as z:z.writestr(item,'/outside')
            with self.assertRaises(ValueError):ios_worker.install_zip(archive)

    def test_device_binary_is_not_misrepresented_as_simulator_app(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Path(directory);(app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.lab.app','CFBundleExecutable':'App'}));(app/'App').write_bytes(b'fake')
            with patch('huntmob.ios_worker._run',return_value=subprocess.CompletedProcess([],0,'platform IOS','')):
                with self.assertRaisesRegex(ValueError,'não é de Simulator'):ios_worker.app_metadata(app)

    def test_invalid_touch_is_rejected_before_input_process(self):
        with patch('huntmob.ios_worker.saved',return_value={'udid':'owned'}),patch('huntmob.ios_worker.subprocess.Popen') as process:
            for value in [float('nan'),float('inf'),-1,2]:
                with self.assertRaises(ValueError):ios_worker.input_action({'action':'tap','x':value,'y':0})
            process.assert_not_called()

    def test_capture_uses_private_file_instead_of_stdout_dash(self):
        image=b'\x89PNG\r\n\x1a\nowned-image'
        def screenshot(*args,**kwargs):
            self.assertNotEqual(args[-1],'-')
            Path(args[-1]).write_bytes(image)
            return subprocess.CompletedProcess([],0,'','')
        with patch('huntmob.ios_worker.owned',return_value={'udid':'owned'}),patch('huntmob.ios_worker.sim',side_effect=screenshot):
            record,result=ios_worker.capture_image()
        self.assertEqual(result,image)
        self.assertEqual(record['udid'],'owned')
