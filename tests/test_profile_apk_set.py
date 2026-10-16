import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from huntmob import lab_sessions as labs
from huntmob.android_worker import AndroidWorker

A='huntmob_lab_'+'a'*32
B='huntmob_lab_'+'b'*32
class ProfileApkSetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(labs,'root',return_value=Path(self.temp.name));p.start();self.addCleanup(p.stop)
        labs.save({'id':A,'root_mode':'stock','android_api':35,'package_id':'com.test.app','apk_sha256':hashlib.sha256(b'base').hexdigest()})
        self.worker=Mock();self.worker.sdk.adb='adb';self.worker.serial='emulator-5556'
    def run_profile(self,listing,fail_pull=False,install_ok=True):
        def run(command,**kw):
            if 'path' in command:return SimpleNamespace(stdout=listing,returncode=0)
            Path(command[-1]).write_bytes(b'base' if command[-1].endswith('base.apk') else b'split')
            return SimpleNamespace(stdout='',returncode=1 if fail_pull else 0)
        with patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.android_worker._run',side_effect=run),patch.object(labs,'create_lab',return_value={'ok':True,'lab':{'id':B}}) as create,patch.object(labs,'resume_lab',return_value={'ok':True}) as resume:
            factory.return_value.prerequisites.return_value={'ready':True}
            factory.return_value.install_apk_set.return_value={'ok':install_ok,'installed':install_ok}
            result=labs.change_root_profile(self.worker,'root')
            return result,create,factory.return_value.install_apk_set,resume
    def test_complete_original_set_is_preserved_before_switch(self):
        result,create,install,resume=self.run_profile('package:/data/app/x/split_config.apk\npackage:/data/app/x/base.apk')
        self.assertTrue(result['ok']);self.assertEqual(len(install.call_args.args[0]),2)
        self.assertEqual(install.call_args.args[0][0].read_bytes(),b'base');create.assert_called_once();resume.assert_not_called()
    def test_missing_split_or_invalid_path_preserves_source(self):
        for listing,fail in [('package:/data/app/x/base.apk\npackage:/data/app/x/s.apk',True),('package:/etc/base.apk',False)]:
            result,create,install,resume=self.run_profile(listing,fail)
            self.assertFalse(result['ok']);create.assert_not_called();install.assert_not_called();self.worker.clear_proxy.assert_not_called()
    def test_install_failure_restores_source_profile(self):
        result,create,install,resume=self.run_profile('package:/data/app/x/base.apk\npackage:/data/app/x/s.apk',install_ok=False)
        self.assertTrue(result['source_restored']);self.assertEqual(resume.call_args.args[1],A)
    def test_install_multiple_keeps_original_files_and_no_signature_flags(self):
        paths=[Path(self.temp.name)/'base.apk',Path(self.temp.name)/'split.apk']
        for p in paths:p.write_bytes(b'apk')
        worker=AndroidWorker();worker.sdk=SimpleNamespace(adb='adb')
        with patch.object(worker,'status',return_value={'state':'device'}),patch('huntmob.android_worker._run',return_value=SimpleNamespace(stdout='Success',stderr='',returncode=0)) as run,patch.object(worker,'launch_app',return_value={'ok':True,'installed':True}):
            self.assertTrue(worker.install_apk_set(paths,'com.test.app')['ok'])
        self.assertEqual(run.call_args.args[0][3:5],('install-multiple','-r'))
