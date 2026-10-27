import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from huntmob import deep_dast, deep_preparation, reverse_workspace

OWNER='huntmob_lab_'+'a'*32
CHILD='huntmob_lab_'+'b'*32
SHA='c'*64
PACKAGE='com.lab.app'


class DeepTargetTests(unittest.TestCase):
    def context(self, sha=SHA):
        return {'id':CHILD, 'workspace_id':OWNER, 'package_id':PACKAGE, 'apk_sha256':sha, 'engagement':'lab-only'}

    def gates(self, evidence_sha=SHA, receipt_state='stopped', receipt_job='dyn_one'):
        lab=self.context()
        report={'lab_id':CHILD,'package_id':PACKAGE,'apk_sha256':SHA,'job_id':'dyn_one','source_sha256':'d'*64,'session_state':'stopped','summary':{'observed_monitors':1,'network_requests':0}}
        record={'package_id':PACKAGE,'sha256':SHA,'run_id':'e'*32}
        evidence={'evidence_id':'ev_test','subject':{'digest':{'sha256':evidence_sha}}}
        with patch('huntmob.deep_dast.dynamic_runtime.target_context',return_value=lab), \
             patch('huntmob.deep_dast.native_dast.latest',return_value=report) as latest, \
             patch('huntmob.deep_dast.dynamic_runtime.runtime_for') as runtime, \
             patch('huntmob.deep_dast.reverse_workspace.latest',return_value=record) as static, \
             patch('huntmob.deep_dast.reverse_engines.jobs',return_value={'jobs':[{'state':'complete','evidence':evidence}]}), \
             patch('huntmob.deep_dast.reverse_engines.model_status',return_value={'model_connected':True}):
            runtime.return_value.snapshot.return_value={'receipt':{'id':receipt_job,'state':receipt_state}}
            result=deep_dast.prerequisites(OWNER,CHILD)
            latest.assert_called_once_with(lab)
            static.assert_called_once_with(PACKAGE,OWNER)
            return result

    def test_child_report_reuses_only_same_hash_static_owner_evidence(self):
        result=self.gates()
        self.assertTrue(result['ready']);self.assertEqual(result['device_id'],CHILD)
        self.assertEqual(result['rea_workspace_id'],OWNER)

    def test_wrong_hash_rea_and_old_session_do_not_pass(self):
        for args, gate in (({'evidence_sha':'f'*64},'rea-evidence'),({'receipt_job':'dyn_new'},'dynamic-evidence'),({'receipt_state':'running'},'dynamic-evidence')):
            result=self.gates(**args)
            self.assertFalse(next(item for item in result['gates'] if item['id']==gate)['passed'])

    def test_engagement_change_is_scoped_and_rejects_stale_apk(self):
        payload={'workspace_id':OWNER,'device_id':CHILD,'package_id':PACKAGE,'apk_sha256':SHA,'engagement':'authorized-test'}
        with patch('huntmob.deep_preparation.dynamic_runtime.scope',return_value=self.context()),patch('huntmob.deep_preparation.lab_sessions.current',return_value={'id':OWNER}),patch('huntmob.deep_preparation.lab_sessions.save') as save:
            deep_preparation.register_engagement(payload)
            self.assertEqual(save.call_args.args[0]['id'],OWNER)
            with self.assertRaises(ValueError):deep_preparation.register_engagement({**payload,'apk_sha256':'f'*64})
            self.assertEqual(save.call_count,1)

    def test_preparation_preserves_existing_full_reverse_run(self):
        record={'run_id':'e'*32,'files':['sources/App.java'],'sha256':SHA}
        with patch('huntmob.deep_preparation.reverse_workspace.latest',return_value=record),patch('huntmob.deep_preparation.reverse_engines.bound'),patch('huntmob.deep_preparation.dynamic_runtime.target_worker') as worker:
            self.assertEqual(deep_preparation._ensure_apk(self.context(),OWNER,CHILD),record)
            worker.assert_not_called()

    def test_reverse_storage_is_private_under_permissive_umask_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory,patch('pathlib.Path.home',return_value=Path(directory)):
            destination=reverse_workspace.prepare_workspace(PACKAGE,OWNER)
            for path in (destination,destination.parent,destination.parent.parent):
                self.assertEqual(path.stat().st_mode&0o777,0o700)
            destination.rmdir();destination.symlink_to(Path(directory),target_is_directory=True)
            with self.assertRaises(ValueError):reverse_workspace.prepare_workspace(PACKAGE,OWNER)
