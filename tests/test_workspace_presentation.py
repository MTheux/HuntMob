import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from huntmob import workspace_devices as devices

P='huntmob_lab_'+'a'*32
C='huntmob_lab_'+'b'*32
X='huntmob_lab_'+'c'*32
class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        for name,value in [('root',Path(self.temp.name)/'devices'),('current',{'id':P})]:
            p=patch.object(devices,name,return_value=value);p.start();self.addCleanup(p.stop)
        devices._save({'id':C,'workspace_id':P,'port':5558,'root_mode':'root','android_api':35,'created_at':'now'})
    def test_names_and_positions_merge_and_preserve_native_identity(self):
        devices.update_presentation(P,[{'device_id':C,'label':'Lab pentest','position':{'x':24,'y':90}}])
        result=devices.update_presentation(P,[{'device_id':C,'position':{'x':100,'y':90}}])
        self.assertEqual(result['presentation']['devices'][C]['label'],'Lab pentest')
        self.assertEqual(devices.owned(P,C)['port'],5558)
        file=Path(self.temp.name)/'workspace-layout'/(P+'.json')
        self.assertEqual(file.stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(file.read_text())['version'],2)
    def test_invalid_batch_never_writes_partial_layout(self):
        for item in [{'device_id':X,'label':'x'},{'device_id':C,'position':{'x':float('nan'),'y':0}},{'device_id':C,'label':'x\ny'},{'device_id':C,'label':'x','serial':'elsewhere'}]:
            with self.assertRaises(ValueError):devices.update_presentation(P,[{'device_id':P,'label':'valid'},item])
            self.assertEqual(devices.presentation(P)['version'],0)
    def test_stop_prevalidates_every_member_before_native_actions(self):
        with patch.object(devices,'worker') as worker,patch.object(devices,'AndroidWorker') as primary:
            with self.assertRaises(ValueError):devices.stop_many(P,[C,X])
            worker.assert_not_called();primary.assert_not_called()
    def test_batch_shutdown_keeps_failures_separate_and_records_untouched(self):
        target=Mock();target.stop.return_value={'ok':True};target.status.return_value={'state':'offline','attached':False}
        with patch.object(devices,'worker',return_value=target),patch.object(devices,'relay'):
            result=devices.stop_many(P,[C])
        self.assertTrue(result['all_stopped']);self.assertEqual(result['results'][0]['device_id'],C)
        self.assertEqual(devices.owned(P,C)['port'],5558)
        target.stop.return_value={'ok':False,'reason':'busy'}
        with patch.object(devices,'worker',return_value=target),patch.object(devices,'relay'):
            result=devices.stop_many(P,[C])
        self.assertFalse(result['all_stopped']);self.assertEqual(result['results'][0]['reason'],'busy')
    def test_resume_enforces_active_limit_without_replacing_saved_identity(self):
        target=Mock();target.status.return_value={'state':'offline'}
        records=[{'id':value,'workspace_id':P} for value in [C,X,'huntmob_lab_'+'d'*32]]
        other=Mock();other.status.return_value={'state':'device'}
        with patch.object(devices,'owned',return_value={'id':C,'workspace_id':P}),patch.object(devices,'worker',side_effect=[target,other,other,other]),patch.object(devices,'records',return_value=records):
            result=devices.action({'action':'start','workspace_id':P,'device_id':C})
        self.assertFalse(result['ok']);target.start.assert_not_called()
