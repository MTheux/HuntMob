import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huntmob import ios_worker as ios

OLD='11111111-2222-3333-4444-555555555555'
NEW='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
RUNTIME='com.apple.CoreSimulator.SimRuntime.iOS-26-0'
MODEL='com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro'


class IdentityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        change=patch.object(ios,'folder',return_value=self.folder);change.start();self.addCleanup(change.stop)
        self.previous={'udid':OLD,'name':'HuntMob iOS Lab previous','runtime':RUNTIME,'model':MODEL,'package_id':'com.lab.app','engagement':'test'}
        self.info={'ready':True,'state':'on','lab':self.previous,'device':{'udid':OLD}}
        self.catalog={'runtimes':[{'id':RUNTIME}],'models':[{'id':MODEL,'minimum':0,'maximum':4294967295}]}
        ios.private_json(self.folder/'current.json',self.previous)

    def test_reset_creates_clean_uuid_and_archives_exact_previous_lab(self):
        with patch.object(ios,'inventory',return_value=self.info),patch.object(ios,'lab_catalog',return_value=self.catalog),patch.object(ios,'sim',return_value=subprocess.CompletedProcess([],0,NEW+'\n','')) as command,patch.object(ios,'shutdown',return_value={'ok':True}) as stop,patch.object(ios,'start',side_effect=lambda:{'ok':True,'lab':ios.saved()}):
            result=ios.reset_identity(OLD)
        current=ios.saved()
        self.assertEqual(current['udid'],NEW);self.assertEqual(current['previous_udid'],OLD)
        self.assertEqual((current['runtime'],current['model'],current['engagement']),(RUNTIME,MODEL,'test'))
        self.assertNotIn('package_id',current)
        self.assertEqual(json.loads((self.folder/('lab-'+OLD+'.json')).read_text()),self.previous)
        self.assertTrue(result['ok']);self.assertEqual(command.call_args.args[0],'create');stop.assert_called_once()

    def test_stale_invalid_or_missing_identity_cannot_create_or_stop(self):
        with patch.object(ios,'inventory',return_value=self.info),patch.object(ios,'new_lab') as create,patch.object(ios,'shutdown') as stop:
            for identifier in (NEW,'../../current',None):
                with self.assertRaises(ValueError):ios.reset_identity(identifier)
            create.assert_not_called();stop.assert_not_called()

    def test_reset_closes_only_capture_owned_by_selected_identity(self):
        from huntmob import ios_proxy
        for target,should_stop in ((OLD,True),(NEW,False)):
            with patch.object(ios,'inventory',return_value=self.info),patch.object(ios,'new_lab',return_value={'ok':True}),patch.object(ios_proxy,'TARGET',target),patch.object(ios_proxy,'stop') as stop:
                ios.reset_identity(OLD)
                self.assertEqual(stop.called,should_stop)

    def test_shutdown_failure_keeps_previous_selection(self):
        with patch.object(ios,'inventory',return_value=self.info),patch.object(ios,'lab_catalog',return_value=self.catalog),patch.object(ios,'sim',return_value=subprocess.CompletedProcess([],0,NEW+'\n','')),patch.object(ios,'shutdown',return_value={'ok':False}),patch.object(ios,'start') as start:
            with self.assertRaises(ValueError):ios.reset_identity(OLD)
            start.assert_not_called()
        self.assertEqual(ios.saved(),self.previous)

    def test_create_failure_never_stops_or_replaces_previous_lab(self):
        with patch.object(ios,'inventory',return_value=self.info),patch.object(ios,'lab_catalog',return_value=self.catalog),patch.object(ios,'sim',return_value=subprocess.CompletedProcess([],1,'','failed')),patch.object(ios,'shutdown') as stop,patch.object(ios,'start') as start:
            with self.assertRaises(ValueError):ios.reset_identity(OLD)
            stop.assert_not_called();start.assert_not_called()
        self.assertEqual(ios.saved(),self.previous)

    def test_boot_failure_leaves_both_labs_and_restore_pointer_available(self):
        with patch.object(ios,'inventory',return_value=self.info),patch.object(ios,'lab_catalog',return_value=self.catalog),patch.object(ios,'sim',return_value=subprocess.CompletedProcess([],0,NEW+'\n','')),patch.object(ios,'shutdown',return_value={'ok':True}),patch.object(ios,'start',side_effect=ValueError('boot failed')):
            with self.assertRaises(ValueError):ios.reset_identity(OLD)
        self.assertEqual(ios.saved()['previous_udid'],OLD)
        self.assertTrue((self.folder/('lab-'+OLD+'.json')).exists())
        self.assertTrue((self.folder/('lab-'+NEW+'.json')).exists())

    def test_restore_verifies_saved_predecessor_before_switching(self):
        active={**self.previous,'udid':NEW,'name':'HuntMob iOS Lab new','previous_udid':OLD}
        ios.private_json(self.folder/'current.json',active)
        ios.private_json(self.folder/('lab-'+OLD+'.json'),self.previous)
        info={**self.info,'lab':active,'device':{'udid':NEW}}
        devices={'devices':{'ios':[{'udid':OLD,'name':self.previous['name']}]}}
        with patch.object(ios,'inventory',return_value=info),patch.object(ios,'sim',return_value=subprocess.CompletedProcess([],0,json.dumps(devices),'')),patch.object(ios,'shutdown',return_value={'ok':True}),patch.object(ios,'start',return_value={'ok':True}):
            ios.restore_previous_identity(NEW)
        self.assertEqual(ios.saved(),self.previous)
        self.assertEqual(json.loads((self.folder/('lab-'+NEW+'.json')).read_text()),active)

    def test_restore_refuses_unrelated_device_or_unsafe_archive_path(self):
        for previous in (OLD,'../../other'):
            active={**self.previous,'udid':NEW,'previous_udid':previous}
            ios.private_json(self.folder/'current.json',active)
            ios.private_json(self.folder/('lab-'+OLD+'.json'),self.previous)
            with patch.object(ios,'inventory',return_value={**self.info,'lab':active}),patch.object(ios,'sim',return_value=subprocess.CompletedProcess([],0,'{"devices":{}}','')),patch.object(ios,'shutdown') as stop:
                with self.assertRaises(ValueError):ios.restore_previous_identity(NEW)
                stop.assert_not_called()
            self.assertEqual(ios.saved(),active)
