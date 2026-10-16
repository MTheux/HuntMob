import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from huntmob.device_controls import execute

LAB = 'huntmob_lab_' + 'a' * 32


class DeviceControlTests(unittest.TestCase):
    def setUp(self):
        self.worker = SimpleNamespace(sdk=SimpleNamespace(adb=Path('/lab/adb')), serial='emulator-5556', avd_name=LAB, status=lambda: {'state':'device'})
        self.calls = []

    def run_command(self, command, **kwargs):
        self.calls.append(command)
        return subprocess.CompletedProcess(command, 0, LAB+'\nOK\n' if command[-2:] == ('avd','name') else 'OK\n', '')

    def run_control(self, payload, name=LAB):
        with patch('huntmob.device_controls.current',return_value={'id':name}), patch('huntmob.device_controls._run',side_effect=self.run_command):
            return execute(self.worker,payload)

    def test_gps_uses_longitude_before_latitude(self):
        result = self.run_control({'action':'location','latitude':-23,'longitude':-46})
        self.assertTrue(result['ok'])
        self.assertIn(('/lab/adb','-s','emulator-5556','emu','geo','fix','-46.0','-23.0'),self.calls)
        self.assertIn('location_enabled',result['readback'])

    def test_invalid_and_nonfinite_coordinates_do_not_reach_geo(self):
        for value in [91,float('nan'),float('inf'),'0; command']:
            self.calls.clear()
            self.assertFalse(self.run_control({'action':'location','latitude':value,'longitude':0})['ok'])
            self.assertFalse(any('geo' in call for call in self.calls))

    def test_unknown_network_profile_cannot_be_command_text(self):
        self.assertFalse(self.run_control({'action':'network','profile':'enable; reboot'})['ok'])
        self.assertFalse(any('svc' in call for call in self.calls))

    def test_offline_disables_both_radios_without_changing_proxy(self):
        self.assertTrue(self.run_control({'action':'network','profile':'offline'})['ok'])
        self.assertIn(('/lab/adb','-s','emulator-5556','shell','svc','wifi','disable'),self.calls)
        self.assertIn(('/lab/adb','-s','emulator-5556','shell','svc','data','disable'),self.calls)
        self.assertFalse(any('http_proxy' in call for call in self.calls))

    def test_wrong_lab_blocks_mutation(self):
        self.assertFalse(self.run_control({'action':'home'},name='huntmob_lab_'+'b'*32)['ok'])
        self.assertFalse(any('input' in call for call in self.calls))

    def test_emulator_console_rejection_is_failure(self):
        with patch('huntmob.device_controls.current',return_value={'id':LAB}), patch('huntmob.device_controls._run',side_effect=[subprocess.CompletedProcess([],0,LAB+'\nOK\n',''),subprocess.CompletedProcess([],0,'OK\n',''),subprocess.CompletedProcess([],0,'KO: invalid command','')]):
            self.assertFalse(execute(self.worker,{'action':'location','latitude':1,'longitude':1})['ok'])

    def test_restore_is_bounded_and_does_not_wipe_data(self):
        self.assertTrue(self.run_control({'action':'battery-reset'})['ok'])
        self.assertIn(('/lab/adb','-s','emulator-5556','shell','dumpsys','battery','reset'),self.calls)
        self.assertFalse(any('clear' in call for call in self.calls))

    def test_sensor_rejects_unbounded_or_nonfinite_vectors(self):
        for value in [21,float('nan'),float('inf')]:
            self.calls.clear()
            self.assertFalse(self.run_control({'action':'sensor','x':value,'y':0,'z':0})['ok'])
            self.assertFalse(any('sensor' in call for call in self.calls))

    def test_latency_profile_is_an_allowlist(self):
        self.assertTrue(self.run_control({'action':'network-shape','profile':'slow'})['ok'])
        self.assertIn(('/lab/adb','-s','emulator-5556','emu','network','speed','edge'),self.calls)
        self.calls.clear()
        self.assertFalse(self.run_control({'action':'network-shape','profile':'http://external'})['ok'])
        self.assertFalse(any('network' in call for call in self.calls))

    def test_root_toggle_uses_same_avd_and_reads_back_uid(self):
        ids = iter(['2000', '0', '0', '2000'])
        def run(command, **kwargs):
            self.calls.append(command)
            if command[-2:] == ('avd', 'name'): output = LAB+'\nOK\n'
            elif command[-2:] == ('id', '-u'): output = next(ids)+'\n'
            elif command[-2:] == ('getprop', 'ro.build.type'): output = 'userdebug\n'
            elif command[-2:] == ('getprop', 'ro.debuggable'): output = '1\n'
            else: output = 'restarting adbd\n'
            return subprocess.CompletedProcess(command, 0, output, '')
        with patch('huntmob.device_controls.current',return_value={'id':LAB}), patch('huntmob.device_controls._run',side_effect=run):
            on = execute(self.worker, {'action':'root-toggle','enabled':True,'expected_device_id':LAB})
            off = execute(self.worker, {'action':'root-toggle','enabled':False,'expected_device_id':LAB})
        self.assertTrue(on['ok']);self.assertTrue(on['root']['enabled'])
        self.assertTrue(off['ok']);self.assertFalse(off['root']['enabled'])
        self.assertIn(('/lab/adb','-s','emulator-5556','root'),self.calls)
        self.assertIn(('/lab/adb','-s','emulator-5556','unroot'),self.calls)
        self.assertFalse(any('emulator' in call[3:] or 'avdmanager' in call[0] for call in self.calls))

    def test_production_image_refuses_root_without_switch(self):
        def run(command, **kwargs):
            self.calls.append(command)
            value = LAB+'\nOK\n' if command[-2:] == ('avd','name') else '2000\n' if command[-2:] == ('id','-u') else 'user\n' if command[-2:] == ('getprop','ro.build.type') else '0\n'
            return subprocess.CompletedProcess(command,0,value,'')
        with patch('huntmob.device_controls.current',return_value={'id':LAB}), patch('huntmob.device_controls._run',side_effect=run):
            result=execute(self.worker,{'action':'root-toggle','enabled':True,'expected_device_id':LAB})
        self.assertFalse(result['ok']);self.assertFalse(result['root']['available'])
        self.assertFalse(any(call[-1] in {'root','unroot'} for call in self.calls))

    def test_root_action_rejects_wrong_device_and_nonboolean_state(self):
        self.assertFalse(self.run_control({'action':'root-toggle','enabled':True,'expected_device_id':'other'})['ok'])
        self.assertFalse(any(call[-1]=='root' for call in self.calls))
        self.calls.clear()
        self.assertFalse(self.run_control({'action':'root-toggle','enabled':'true'})['ok'])
        self.assertFalse(any(call[-1]=='root' for call in self.calls))

    def test_app_root_toggle_keeps_selected_avd_and_checks_observed_state(self):
        def run(command, **kwargs):
            self.calls.append(command)
            output = LAB+'\nOK\n' if command[-2:] == ('avd','name') else '0\n' if command[-2:] == ('id','-u') else 'userdebug\n' if command[-2:] == ('getprop','ro.build.type') else '1\n'
            return subprocess.CompletedProcess(command,0,output,'')
        states = [{'enabled':False,'available':True}, {'enabled':True,'available':True}]
        with patch('huntmob.device_controls.current',return_value={'id':LAB}), patch('huntmob.device_controls._run',side_effect=run), patch('huntmob.app_root.status',side_effect=states), patch('huntmob.app_root.enable',return_value=states[1]) as enabled:
            result=execute(self.worker,{'action':'app-root-toggle','enabled':True,'expected_device_id':LAB})
        self.assertTrue(result['ok'])
        self.assertTrue(result['root']['enabled'])
        enabled.assert_called_once()
        self.assertIn(('/lab/adb','-s','emulator-5556','emu','avd','name'),self.calls)

    def test_app_root_rejects_wrong_avd_before_setup(self):
        with patch('huntmob.device_controls.current',return_value={'id':LAB}), patch('huntmob.device_controls._run',side_effect=self.run_command), patch('huntmob.app_root.enable') as enabled:
            result=execute(self.worker,{'action':'app-root-toggle','enabled':True,'expected_device_id':'other'})
        self.assertFalse(result['ok'])
        enabled.assert_not_called()
