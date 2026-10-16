import hashlib
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from huntmob import reverse_engines as engines
from huntmob import reverse_workspace


class ReverseEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.home_patch = patch('pathlib.Path.home', return_value=self.home); self.home_patch.start()
        self.package = 'br.com.huntmob.demo'; self.lab = 'huntmob_lab_' + 'a' * 32; self.run = 'b' * 32
        self.workspace = reverse_workspace.workspace(self.package, self.lab); self.workspace.mkdir(parents=True)
        self.apk = self.workspace / 'base.apk'; self.apk.write_bytes(b'controlled-apk-fixture')
        self.sha = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        self.record = {'package_id': self.package, 'run_id': self.run, 'sha256': self.sha, 'files': [], 'status': 'complete'}
        (self.workspace / 'analysis.json').write_text(json.dumps(self.record))
        self.selected = {'id': self.lab, 'package_id': self.package, 'apk_sha256': self.sha}
        self.selection = patch.object(engines.lab_sessions, 'current', return_value=self.selected); self.selection.start()
        skill = self.home / 'companion/SKILL.md'; skill.parent.mkdir(); skill.write_text('Controlled Companion fixture')
        self.skill_patch = patch.object(engines, 'companion_skill', return_value=skill); self.skill_patch.start()
        self.payload = {'package_id': self.package, 'workspace_id': self.lab, 'run_id': self.run, 'sha256': self.sha}

    def tearDown(self):
        self.skill_patch.stop(); self.selection.stop(); self.home_patch.stop(); self.temp.cleanup()

    def test_app_workspace_run_and_apk_digest_must_all_match(self):
        engines.bound(self.package, self.lab, self.run, self.sha)
        for args in [(self.package, 'huntmob_lab_'+'c'*32, self.run, self.sha), ('br.other.app', self.lab, self.run, self.sha), (self.package, self.lab, 'd'*32, self.sha)]:
            with self.assertRaises(ValueError): engines.bound(*args)
        self.apk.write_bytes(b'replaced')
        with self.assertRaises(ValueError): engines.bound(self.package, self.lab, self.run, self.sha)

    def test_command_is_allowlisted_and_cannot_inject_cli_flags(self):
        config = {'rea_cli': '/local/rea.mjs'}
        for payload in [{'operation': 'shell'}, {'operation': 'class', 'class_name': '--update'}, {'operation':'method','class_name':'App','method_name':'x','overload_index':True}]:
            with self.assertRaises(ValueError): engines.command(config, 'node', self.apk, payload)
        command = engines.command(config, 'node', self.apk, {'operation':'method','class_name':'App','method_name':'foo','overload_index':0})
        self.assertEqual(command[-4:], ['--overload-index','0','--format','json'])

    def wait_job(self):
        for _ in range(100):
            result = engines.jobs(self.package, self.lab, self.run, self.sha)['jobs'][0]
            if result['state'] != 'running': return result
            time.sleep(.01)
        self.fail('Job did not finish')

    def wait_model_job(self):
        for _ in range(100):
            result = engines.jobs(self.package, self.lab, self.run, self.sha)['model_jobs'][0]
            if result['state'] != 'running': return result
            time.sleep(.01)
        self.fail('Model job did not finish')

    def test_real_adapter_preserves_full_evidence_and_uses_private_snapshot(self):
        def execute(args, config):
            self.assertNotEqual(Path(args[3]), self.apk)
            self.assertEqual(Path(args[3]).read_bytes(), self.apk.read_bytes())
            return {'evidence_id':'ev_fixture','subject':{'digest':{'sha256':self.sha}},'normalized_result':{'manifest':'controlled'}}
        with patch.object(engines,'tooling',return_value=({'rea_cli':'/local/rea.mjs'},'node')), patch.object(engines,'execute',side_effect=execute):
            engines.start(self.payload); result=self.wait_job()
        self.assertEqual(result['state'],'complete'); self.assertIn('normalized_result',result['evidence'])

    def test_wrong_provider_artifact_is_never_marked_complete(self):
        with patch.object(engines,'tooling',return_value=({'rea_cli':'/local/rea.mjs'},'node')), patch.object(engines,'execute',return_value={'evidence_id':'ev_wrong','subject':{'digest':{'sha256':'c'*64}}}):
            engines.start(self.payload); result=self.wait_job()
        self.assertEqual(result['state'],'failed'); self.assertNotIn('evidence',result)

    def test_malformed_provider_digest_fails_job_and_releases_workspace(self):
        with patch.object(engines,'tooling',return_value=({'rea_cli':'/local/rea.mjs'},'node')), patch.object(engines,'execute',return_value={'evidence_id':'ev_malformed','subject':{'digest':'invalid'}}):
            engines.start(self.payload); result=self.wait_job()
        self.assertEqual(result['state'],'failed')
        self.assertNotIn('evidence',result)
        self.assertNotIn((self.lab,self.package,self.run),engines.BUSY)

    def test_storage_failure_does_not_leave_workspace_locked(self):
        with patch.object(engines,'tooling',return_value=({'rea_cli':'/local/rea.mjs'},'node')), patch.object(engines,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):engines.start(self.payload)
        self.assertNotIn((self.lab,self.package,self.run),engines.BUSY)

    def test_handoff_requires_evidence_and_does_not_claim_agent_execution(self):
        with self.assertRaises(ValueError): engines.handoff(self.package,self.lab,self.run,self.sha)
        engines.save(engines.folder(self.package,self.lab,self.run)/('c'*32+'.json'), {**self.payload,'state':'complete','created_at':'2026','evidence':{'evidence_id':'ev_fixture'}})
        data=engines.handoff(self.package,self.lab,self.run,self.sha)
        self.assertEqual(data['state'],'awaiting_agent'); self.assertEqual(data['sha256'],self.sha)
        with zipfile.ZipFile(io.BytesIO(engines.export_handoff(self.package,self.lab,self.run,self.sha))) as archive:
            self.assertIn('huntmob-context.json',archive.namelist())
            self.assertIn('rea-reconstruction-companion/SKILL.md',archive.namelist())
            self.assertNotIn('base.apk',archive.namelist())

    def test_restart_marks_unowned_running_job_interrupted(self):
        engines.save(engines.folder(self.package,self.lab,self.run)/('c'*32+'.json'), {**self.payload,'state':'running','created_at':'2026'})
        self.assertEqual(engines.jobs(self.package,self.lab,self.run,self.sha)['jobs'][0]['state'],'interrupted')

    def test_agent_review_requires_current_evidence_and_stays_unverified(self):
        engines.save(engines.folder(self.package,self.lab,self.run)/('c'*32+'.json'), {**self.payload,'state':'complete','created_at':'2026','evidence':{'evidence_id':'ev_current'}})
        report={'summary':'Static architecture review','observations':[{'text':'Declared component','evidence_id':'ev_other'}],'inferences':['Runtime behavior unknown'],'unknowns':['Backend not examined']}
        with self.assertRaises(ValueError):engines.record_review({**self.payload,'report':report})
        report['observations'][0]['evidence_id']='ev_current'
        result=engines.record_review({**self.payload,'report':report})
        self.assertEqual(result['status'],'needs_review');self.assertFalse(result['independently_verified'])
        self.assertEqual(len(engines.jobs(self.package,self.lab,self.run,self.sha)['reviews']),1)

    def test_local_model_review_cites_current_evidence_and_stays_unverified(self):
        engines.save(engines.folder(self.package,self.lab,self.run)/('c'*32+'.json'), {**self.payload,'state':'complete','created_at':'2026','evidence':{'evidence_id':'ev_current','normalized_result':{'manifest':'controlled'}}})
        answer={'summary':'Architecture only','observations':[{'text':'Manifest evidence','evidence_id':'ev_current'}],'inferences':[],'unknowns':['Runtime behavior']}
        response={'model':engines.MODEL_NAME,'done':True,'message':{'content':json.dumps(answer)}}
        with patch.object(engines,'model_status',return_value={'model_connected':True}),patch.object(engines,'_ollama',return_value=response) as ollama:
            engines.start_model_review(self.payload); job=self.wait_model_job()
        self.assertEqual(job['state'],'complete')
        review=engines.jobs(self.package,self.lab,self.run,self.sha)['reviews'][0]
        self.assertEqual((review['source'],review['model'],review['status']),('local-ollama',engines.MODEL_NAME,'needs_review'))
        self.assertFalse(review['independently_verified'])
        self.assertEqual(ollama.call_args.args[0],'/api/chat')
        self.assertNotIn('base.apk',json.dumps(ollama.call_args.args[1]))

    def test_local_model_rejects_uncited_observation(self):
        engines.save(engines.folder(self.package,self.lab,self.run)/('c'*32+'.json'), {**self.payload,'state':'complete','created_at':'2026','evidence':{'evidence_id':'ev_current'}})
        response={'model':engines.MODEL_NAME,'done':True,'message':{'content':json.dumps({'summary':'Claim','observations':[{'text':'Unsupported','evidence_id':'ev_other'}]})}}
        with patch.object(engines,'model_status',return_value={'model_connected':True}),patch.object(engines,'_ollama',return_value=response):
            engines.start_model_review(self.payload); job=self.wait_model_job()
        self.assertEqual(job['state'],'failed')
        self.assertEqual(engines.jobs(self.package,self.lab,self.run,self.sha)['reviews'],[])
        self.assertNotIn((self.lab,self.package,self.run),engines.MODEL_BUSY)
