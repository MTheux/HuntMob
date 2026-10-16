import json
import subprocess
import unittest
from unittest.mock import Mock,patch
from huntmob import ios_workspace as workspace
from huntmob import workspace_devices

UDID='11111111-2222-3333-4444-555555555555'
PARENT='huntmob_lab_'+'a'*32
RECORD={'id':'huntmob_lab_'+'b'*32,'udid':UDID,'workspace_id':PARENT,'name':'HuntMob iOS Workspace owned','platform':'ios','runtime':'com.apple.CoreSimulator.SimRuntime.iOS-26-0'}

class IosWorkspaceTests(unittest.TestCase):
    def test_state_requires_exact_saved_name_and_uuid(self):
        for name,expected in [(RECORD['name'],True),('Other user phone',False)]:
            response={'devices':{'ios':[{'udid':UDID,'name':name,'state':'Booted'}]}}
            with patch.object(workspace.ios,'sim',return_value=subprocess.CompletedProcess([],0,json.dumps(response),'')):
                self.assertEqual(workspace.IosDevice(RECORD).status()['ownership_verified'],expected)

    def test_start_uses_saved_uuid_and_does_not_change_primary_ios(self):
        device=workspace.IosDevice(RECORD)
        with patch.object(device,'status',return_value={'ownership_verified':True,'state':'offline'}),patch.object(workspace.ios,'sim',return_value=subprocess.CompletedProcess([],0,'','')) as sim,patch.object(workspace.ios,'ensure_companion') as bridge,patch.object(workspace.ios,'private_json') as save:
            self.assertTrue(device.start()['ok'])
        sim.assert_any_call('boot',UDID);sim.assert_any_call('bootstatus',UDID,'-b',timeout=180)
        bridge.assert_called_once_with(RECORD,primary=False);save.assert_not_called()

    def test_bad_input_cannot_start_bridge_or_touch_another_phone(self):
        device=workspace.IosDevice(RECORD)
        with patch.object(workspace.subprocess,'Popen') as popen:
            for payload in [{'action':'shell'},{'action':'touch','phase':'down','x':float('nan'),'y':0},{'action':'touch','phase':'wrong','x':0,'y':0}]:
                with self.assertRaises(ValueError):device.input(payload)
            popen.assert_not_called()

    def test_incompatible_model_never_creates_simulator(self):
        catalog={'runtimes':[{'id':RECORD['runtime']}],'models':[{'id':'old-model','minimum':0,'maximum':16*65536}]}
        with patch.object(workspace.ios,'lab_catalog',return_value=catalog),patch.object(workspace.ios,'sim') as sim:
            with self.assertRaises(ValueError):workspace.create_record(PARENT,RECORD['runtime'],'old-model')
            sim.assert_not_called()

    def test_new_ios_does_not_call_primary_shutdown_or_write_current(self):
        catalog={'runtimes':[{'id':RECORD['runtime']}],'models':[{'id':'model','minimum':0,'maximum':4294967295}]}
        with patch.object(workspace.ios,'lab_catalog',return_value=catalog),patch.object(workspace.ios,'sim',return_value=subprocess.CompletedProcess([],0,UDID+'\n','')) as sim,patch.object(workspace.ios,'shutdown') as stop,patch.object(workspace.ios,'private_json') as save:
            record=workspace.create_record(PARENT,RECORD['runtime'],'model')
        self.assertEqual(record['platform'],'ios');self.assertEqual(record['udid'],UDID)
        self.assertEqual(record['workspace_id'],PARENT);stop.assert_not_called();save.assert_not_called()
