import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from huntmob.android_worker import AndroidWorker,AndroidSdk
from huntmob.lab_sessions import create_play_lab
class StoreTests(unittest.TestCase):
 def worker(self,mode):return AndroidWorker(AndroidSdk(Path('/sdk'),Path('/sdk/emulator'),Path('/sdk/adb'),Path('/sdk/avdmanager'),Path('/sdk/sdkmanager')),avd_name='huntmob_lab_00000000000000000000000000000000',root_mode=mode,android_api=35)
 def test_root_never_opens_store(self):
  with patch('huntmob.android_worker._run') as run:
   self.assertFalse(self.worker('root').open_play_store()['ok']);run.assert_not_called()
 def test_invalid_package_not_sent_to_device(self):
  with patch('huntmob.android_worker._run') as run:
   self.assertFalse(self.worker('stock').open_play_store('--help')['ok']);run.assert_not_called()
 def test_missing_store_is_explicit(self):
  with patch.object(AndroidWorker,'status',return_value={'state':'device','properties':{'sys.boot_completed':'1'}}),patch('huntmob.android_worker._run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
   self.assertFalse(self.worker('stock').open_play_store()['ok']);self.assertEqual(run.call_count,1)
 def test_store_opens_fixed_market_target_with_no_credentials(self):
  with patch.object(AndroidWorker,'status',return_value={'state':'device','properties':{'sys.boot_completed':'1'}}),patch('huntmob.android_worker._run',side_effect=[subprocess.CompletedProcess([],0,'package:/store.apk',''),subprocess.CompletedProcess([],0,'Status: ok','')]) as run:
   self.assertTrue(self.worker('stock').open_play_store('com.huntmob.lab')['ok'])
   self.assertIn('market://details?id=com.huntmob.lab',run.call_args.args[0]);self.assertIn('com.android.vending',run.call_args.args[0])

class PlayLabTests(unittest.TestCase):
 def setUp(self):
  # Unit tests must not read or depend on the operator's real active lab.
  self.current_patch=patch('huntmob.lab_sessions.current',return_value={})
  self.current_patch.start();self.addCleanup(self.current_patch.stop)
 def test_unsaved_active_lab_never_prepares_or_switches(self):
  with patch('huntmob.lab_sessions.current',return_value={'id':'huntmob_lab_'+'b'*32,'saved_at':None}),patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.lab_sessions.create_lab') as create:
   result=create_play_lab(MagicMock())
   self.assertEqual(result['error_code'],'unsaved_lab');factory.assert_not_called();create.assert_not_called()
 def test_invalid_request_never_prepares_or_switches_lab(self):
  worker=MagicMock()
  with patch('huntmob.lab_sessions.create_lab') as create,patch.object(AndroidWorker,'prepare_profile') as prepare:
   self.assertFalse(create_play_lab(worker,'--help')['ok'])
   self.assertFalse(create_play_lab(worker,android_api=True)['ok'])
   create.assert_not_called();prepare.assert_not_called()
 def test_preparation_failure_preserves_current_lab(self):
  with patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.lab_sessions.create_lab') as create:
   factory.return_value.prepare_profile.return_value={'ok':False,'reason':'license required'}
   result=create_play_lab(MagicMock())
   self.assertFalse(result['ok']);self.assertFalse(result['lab_created']);self.assertEqual(result['stage'],'prepare');create.assert_not_called()
 def test_boot_failure_never_opens_store(self):
  with patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.lab_sessions.create_lab',return_value={'ok':False,'reason':'boot failed'}):
   factory.return_value.prepare_profile.return_value={'ok':True}
   self.assertFalse(create_play_lab(MagicMock())['ok']);factory.return_value.open_play_store.assert_not_called()
 def test_selected_api_and_new_lab_identity_are_used_for_store(self):
  lab={'id':'huntmob_lab_'+'a'*32,'root_mode':'stock','android_api':34}
  with patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.lab_sessions.create_lab',return_value={'ok':True,'lab':lab}) as create:
   factory.return_value.prepare_profile.return_value={'ok':True}
   factory.return_value.open_play_store.return_value={'ok':True,'reason':'store open'}
   result=create_play_lab(MagicMock(),'com.example.app',android_api=34)
   self.assertTrue(result['ok']);self.assertFalse(result['app_installed']);self.assertTrue(result['lab_created'])
   self.assertEqual(create.call_args.kwargs,{'root_mode':'stock','android_api':34})
   self.assertEqual(factory.call_args.kwargs,{'avd_name':lab['id'],'root_mode':'stock','android_api':34})
   factory.return_value.open_play_store.assert_called_once_with('com.example.app')
 def test_store_timeout_retains_created_lab_for_resume(self):
  lab={'id':'huntmob_lab_'+'a'*32}
  with patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.lab_sessions.create_lab',return_value={'ok':True,'lab':lab}):
   factory.return_value.prepare_profile.return_value={'ok':True}
   factory.return_value.open_play_store.side_effect=subprocess.TimeoutExpired('adb',20)
   result=create_play_lab(MagicMock())
   self.assertFalse(result['ok']);self.assertTrue(result['lab_created']);self.assertEqual(result['lab'],lab)
