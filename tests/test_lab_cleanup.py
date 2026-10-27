import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from huntmob import lab_cleanup, lab_sessions
from huntmob.android_worker import AndroidSdk


class LabCleanupTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.home=Path(temp.name);self.labs=self.home/'labs';self.avds=self.home/'avd';self.avds.mkdir()
        self.devices=self.home/'workspace-devices';self.devices.mkdir()
        self.one='huntmob_lab_'+'a'*32;self.two='huntmob_lab_'+'b'*32
        for change in (patch.object(lab_sessions,'root',return_value=self.labs),
                       patch('huntmob.workspace_devices.root',return_value=self.devices),
                       patch('huntmob.workspace_devices.records',return_value=[]),
                       patch('huntmob.runtime_cleanup.cleanup_primary_session'),
                       patch.dict(os.environ,{'ANDROID_AVD_HOME':str(self.avds)})):
            change.start();self.addCleanup(change.stop)
        for identifier in (self.one,self.two):
            lab_sessions.save({'id':identifier,'saved_at':'2026-10-21','package_id':'com.lab.app'})
            (self.labs/identifier).mkdir();(self.labs/identifier/'network.json').write_text('{}')
            (self.avds/(identifier+'.avd')).mkdir()
            (self.avds/(identifier+'.ini')).write_text('path='+str(self.avds/(identifier+'.avd'))+'\n')
        self.worker=MagicMock(avd_name=self.two)
        self.worker.sdk=AndroidSdk(self.home,self.home/'emulator',self.home/'adb',self.home/'avdmanager',self.home/'sdkmanager')
        self.worker.status.return_value={'state':'offline','attached':False}

    def native(self, command, **kwargs):
        if 'delete' in command:
            directory=self.avds/(command[-1]+'.avd');settings=self.avds/(command[-1]+'.ini')
            if directory.exists():directory.rmdir()
            settings.unlink(missing_ok=True)
        return subprocess.CompletedProcess(command,0,'List of devices attached\n' if command[-1]=='devices' else '','')

    def delete(self, identifiers=None, **kwargs):
        return lab_cleanup.delete_saved_labs(self.worker,identifiers or [self.one],self.two,delete_data=True,**kwargs)

    def test_requires_separate_delete_confirmation_and_valid_selection(self):
        with patch.object(lab_cleanup,'_run') as run,patch.object(lab_sessions,'stop_saved_labs') as stop:
            for approval in (False,None,'true',1):
                self.assertFalse(lab_cleanup.delete_saved_labs(self.worker,[self.one],self.two,delete_data=approval)['ok'])
            for identifiers in ([],[self.one,self.one],['../outside'],['huntmob_lab_'+'c'*32]):
                self.assertFalse(lab_cleanup.delete_saved_labs(self.worker,identifiers,self.two,delete_data=True)['ok'])
            self.assertFalse(lab_cleanup.delete_saved_labs(self.worker,[self.one],self.one,delete_data=True)['ok'])
            run.assert_not_called();stop.assert_not_called()

    def test_deletes_only_selected_saved_lab_and_keeps_other_lab_and_evidence(self):
        evidence=self.home/'evidence';evidence.mkdir();(evidence/'capture.png').write_bytes(b'evidence')
        with patch.object(lab_cleanup,'_run',side_effect=self.native) as run:
            result=self.delete()
        self.assertEqual((result['deleted'],result['failed']),(1,0))
        self.assertFalse((self.labs/self.one).exists())
        self.assertEqual([item['id'] for item in lab_sessions.inventory()['labs']],[self.two])
        self.assertEqual(lab_sessions.current()['id'],self.two)
        self.assertTrue((self.labs/self.two/'network.json').exists())
        self.assertEqual((evidence/'capture.png').read_bytes(),b'evidence')
        deletes=[call.args[0] for call in run.call_args_list if 'delete' in call.args[0]]
        self.assertEqual([command[-1] for command in deletes],[self.one])
        self.worker.stop.assert_not_called()

    def test_deleting_current_lab_clears_current_pointer_without_selecting_another(self):
        with patch.object(lab_cleanup,'_run',side_effect=self.native):
            result=self.delete([self.two])
        self.assertEqual(result['deleted'],1)
        self.assertEqual(lab_sessions.current(),{})
        self.assertFalse((self.labs/'current.json').exists())
        self.assertEqual([item['id'] for item in lab_sessions.inventory()['labs']],[self.one])

    def test_deletion_does_not_require_stopping_unselected_android_on_shared_port(self):
        def native(command,**kwargs):
            if 'delete' in command:return self.native(command,**kwargs)
            output='List of devices attached\nemulator-5556\tdevice\n' if command[-1]=='devices' else self.two+'\nOK\n' if command[-3:]==('emu','avd','name') else ''
            return subprocess.CompletedProcess(command,0,output,'')
        with patch.object(lab_cleanup,'_run',side_effect=native):
            self.assertEqual(self.delete()['deleted'],1)
        self.worker.stop.assert_not_called()
        self.assertTrue((self.labs/(self.two+'.json')).exists())

    def test_rejects_external_symlink_or_avd_path_before_shutdown(self):
        external=self.home/'external';external.mkdir();(external/'keep').write_text('keep')
        (self.labs/self.one/'network.json').unlink();(self.labs/self.one).rmdir()
        (self.labs/self.one).symlink_to(external,target_is_directory=True)
        with patch.object(lab_cleanup,'_run') as run,patch.object(lab_sessions,'stop_saved_labs') as stop:
            self.assertFalse(self.delete()['ok'])
            run.assert_not_called();stop.assert_not_called()
        (self.labs/self.one).unlink();(self.labs/self.one).mkdir()
        (self.avds/(self.one+'.ini')).write_text('path='+str(external)+'\n')
        with patch.object(lab_cleanup,'_run') as run,patch.object(lab_sessions,'stop_saved_labs') as stop:
            self.assertFalse(self.delete()['ok'])
            run.assert_not_called();stop.assert_not_called()
        self.assertEqual((external/'keep').read_text(),'keep')

    def test_unidentified_emulator_or_selected_running_avd_is_never_deleted(self):
        for state in ('offline','device'):
            def native(command,**kwargs):
                output='List of devices attached\nemulator-5556\t'+state+'\n' if command[-1]=='devices' else self.one+'\nOK\n'
                return subprocess.CompletedProcess(command,0,output,'')
            with patch.object(lab_cleanup,'_run',side_effect=native) as run:
                result=self.delete()
            self.assertFalse(any('delete' in call.args[0] for call in run.call_args_list))
            self.assertTrue((self.labs/(self.one+'.json')).exists())
            self.assertEqual(result.get('deleted',0),0)

    def test_native_failure_keeps_saved_record_and_data_for_retry(self):
        def native(command,**kwargs):
            return subprocess.CompletedProcess(command,1,'','refused') if 'delete' in command else self.native(command,**kwargs)
        with patch.object(lab_cleanup,'_run',side_effect=native):
            result=self.delete()
        self.assertEqual((result['deleted'],result['failed']),(0,1))
        self.assertTrue((self.labs/(self.one+'.json')).exists())
        self.assertTrue((self.labs/self.one/'network.json').exists())

    def test_file_cleanup_failure_does_not_hide_pending_lab(self):
        with patch.object(lab_cleanup,'_run',side_effect=self.native),patch.object(lab_cleanup.shutil,'rmtree',side_effect=OSError('busy')):
            result=self.delete()
        self.assertEqual(result['failed'],1)
        self.assertIn(self.one,{item['id'] for item in lab_sessions.inventory()['labs']})

    def test_sdk_success_without_removed_files_is_not_reported_as_deleted(self):
        with patch.object(lab_cleanup,'_run',return_value=subprocess.CompletedProcess([],0,'List of devices attached\n','')):
            result=self.delete()
        self.assertEqual((result['deleted'],result['failed']),(0,1))
        self.assertTrue((self.labs/(self.one+'.json')).exists())

    def test_deletes_only_selected_ios_companion_and_registered_metadata(self):
        identifier='huntmob_lab_'+'c'*32;udid='11111111-2222-3333-4444-555555555555'
        record={'id':identifier,'workspace_id':self.one,'platform':'ios','name':'HuntMob iOS Workspace test','udid':udid}
        (self.devices/(identifier+'.json')).write_text(json.dumps(record))
        target=MagicMock();target.status.side_effect=[{'state':'device','ownership_verified':True},{'state':'offline','attached':False}];target.stop.return_value={'ok':True}
        device={'udid':udid,'name':record['name'],'state':'Shutdown'}
        devices=[device]
        def simulator(*args,**kwargs):
            if args[0]=='delete':devices.clear()
            return subprocess.CompletedProcess([],0,json.dumps({'devices':{'ios':devices}}),'')
        with patch('huntmob.workspace_devices.records',return_value=[record]),patch('huntmob.workspace_devices.worker',return_value=target),patch('huntmob.workspace_devices.relay'),patch('huntmob.workspace_devices.forget') as forget,patch('huntmob.ios_worker.sim',side_effect=simulator) as sim,patch.object(lab_cleanup,'_run',side_effect=self.native):
            result=self.delete()
        self.assertEqual(result['deleted'],1);target.stop.assert_called_once()
        sim.assert_any_call('delete',udid,timeout=30);forget.assert_called_once_with(record)
        self.assertFalse((self.devices/(identifier+'.json')).exists())

    def test_never_deletes_companion_identity_shared_with_unselected_workspace(self):
        identifier='huntmob_lab_'+'c'*32
        records=[{'id':identifier,'workspace_id':self.one},{'id':identifier,'workspace_id':self.two}]
        with patch('huntmob.workspace_devices.records',return_value=records),patch.object(lab_sessions,'stop_saved_labs') as stop,patch.object(lab_cleanup,'_run') as run:
            self.assertFalse(self.delete()['ok'])
            run.assert_not_called();stop.assert_not_called()
