import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from huntmob.dynamic_runtime import DynamicRuntime, connection_readiness, frida_compatibility, frida_server_ready, scope


class ConnectionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.lab={'id':'lab','package_id':'com.lab.fixture','apk_sha256':'a'*64,'root_mode':'stock'}
        self.worker=MagicMock();self.worker.avd_name='lab';self.worker.sdk.adb='adb';self.worker.serial='emulator-5556'
        self.worker.status.return_value={'state':'device','ownership_verified':True,'properties':{'ro.build.version.sdk':'35','ro.product.cpu.abi':'arm64-v8a'}}
        self.worker.root_status.return_value={'root_available':True}
        self.frida=MagicMock();self.frida.__version__='17.23.3'

    def check(self, *, pid='1234', ports='', code=0, current_values=None):
        def run(command,**kwargs):
            if 'pidof' in command:return subprocess.CompletedProcess(command,0 if pid else 1,pid,'')
            return subprocess.CompletedProcess(command,code,ports,'')
        with patch('huntmob.dynamic_runtime.current',side_effect=current_values) if current_values else patch('huntmob.dynamic_runtime.current',return_value=self.lab), \
             patch('huntmob.dynamic_runtime.AndroidWorker',return_value=self.worker), \
             patch('huntmob.dynamic_runtime._run',side_effect=run) as called, \
             patch.dict('sys.modules',{'frida':self.frida}):
            result=connection_readiness()
        self.frida.get_device_manager.assert_not_called()
        self.assertFalse(any('forward' in call.args[0] or 'root' in call.args[0] for call in called.call_args_list))
        return result

    def test_open_app_without_gadget_listener_is_blocked_before_attach(self):
        result=self.check(ports='State Recv-Q Send-Q Local Address:Port Peer Address:Port\nLISTEN 0 5 127.0.0.1:27043 0.0.0.0:*\n')
        self.assertFalse(result['ready']);self.assertEqual(result['error_code'],'gadget_not_listening')
        self.assertIn('Google Play',result['reason']);self.assertIn('27042',result['reason'])

    def test_closed_app_has_a_different_actionable_prerequisite(self):
        result=self.check(pid='');self.assertEqual(result['error_code'],'gadget_app_not_running')
        self.assertFalse(result['ready'])

    def test_listening_port_only_allows_attempt_and_never_claims_connected_session(self):
        result=self.check(ports='LISTEN 0 5 127.0.0.1:27042 0.0.0.0:*\n')
        self.assertTrue(result['ready']);self.assertIn('serão verificadas',result['reason'])

    def test_unreadable_port_inventory_does_not_claim_gadget_absent(self):
        result=self.check(code=1);self.assertEqual(result['error_code'],'gadget_check_unavailable')
        self.assertFalse(result['ready'])

    def test_aosp_server_uses_adb_privilege_without_requiring_magisk(self):
        self.lab['root_mode']='root';result=self.check()
        self.assertTrue(result['ready']);self.assertIn('Magisk para apps não é necessário',result['reason'])
        self.worker.root_status.return_value={'root_available':False}
        self.assertEqual(self.check()['error_code'],'adb_root_unavailable')

    def test_known_aosp_api30_incompatibility_is_reported_before_server_setup(self):
        self.lab['root_mode']='root';self.worker.status.return_value['properties']['ro.build.version.sdk']='30'
        self.assertEqual(self.check()['error_code'],'frida_android_sigchain_incompatible')
        self.worker.root_status.assert_not_called()

    def test_replaced_lab_during_checks_cannot_return_ready(self):
        result=self.check(ports='LISTEN 0 5 [::1]:27042 [::]:*\n',current_values=[self.lab,{**self.lab,'id':'other'}])
        self.assertFalse(result['ready']);self.assertEqual(result['error_code'],'lab_changed')

    def test_start_endpoint_also_enforces_preflight_without_a_new_session(self):
        runtime=DynamicRuntime();blocked={**self.lab,'lab_id':'lab','ok':True,'ready':False,'error_code':'gadget_not_listening','reason':'Gadget indisponível.'}
        with patch('huntmob.dynamic_runtime.scope',return_value=self.lab),patch('huntmob.dynamic_runtime.connection_readiness',return_value=blocked),patch.dict('sys.modules',{'frida':self.frida}):
            result=runtime.start({'package_id':self.lab['package_id'],'script_ids':['tls-observe']})
        self.assertFalse(result['ok']);self.assertTrue(result['blocked']);self.assertIsNone(runtime.receipt)
        self.frida.get_device_manager.assert_not_called()


class DynamicTests(unittest.TestCase):
    def test_known_api30_arm64_frida_crash_is_blocked(self):
        result = frida_compatibility(30, 'arm64-v8a', '17.23.3')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'frida_android_sigchain_incompatible')

    def test_other_frida_runtime_tuple_is_not_blocked(self):
        self.assertTrue(frida_compatibility(35, 'arm64-v8a', '17.23.3')['ok'])

    @patch('huntmob.dynamic_runtime._run')
    def test_frida_readiness_uses_protocol_instead_of_process_name(self, run):
        run.return_value.returncode=0
        device=MagicMock();frida=MagicMock()
        frida.get_device_manager.return_value.add_remote_device.return_value=device
        self.assertTrue(frida_server_ready(('adb','-s','emulator-5556'),frida))
        device.enumerate_processes.assert_called_once_with()
        self.assertEqual(run.call_args.args[0][-3:],('forward','tcp:27052','tcp:27042'))

    def test_cannot_instrument_an_unbound_package(self):
        with patch('huntmob.dynamic_runtime.current',return_value={'id':'lab','package_id':'com.lab.app','apk_sha256':'hash'}):
            with self.assertRaises(ValueError):scope('com.other.app')

    def test_event_schema_drops_passwords_buffers_and_unknown_keys(self):
        runtime=DynamicRuntime()
        with tempfile.TemporaryDirectory() as directory,patch('huntmob.dynamic_runtime.root',return_value=Path(directory)):
            (Path(directory)/'lab').mkdir()
            runtime.receipt={'id':'dyn_'+'a'*32,'lab_id':'lab'}
            runtime.record({'kind':'call','method':'init','password':'synthetic-secret','buffer':'synthetic-secret'})
            self.assertNotIn('synthetic-secret',json.dumps(runtime.events))
            self.assertEqual(runtime.events[0]['method'],'init')
            self.assertEqual((Path(directory)/'lab'/('dyn_'+'a'*32+'.jsonl')).stat().st_mode & 0o777,0o600)

    def test_other_lab_cannot_see_active_events(self):
        runtime=DynamicRuntime();runtime.receipt={'lab_id':'one','state':'running'}
        runtime.events=[{'kind':'call'}]
        with patch('huntmob.dynamic_runtime.current',return_value={'id':'two'}):
            self.assertEqual(runtime.snapshot()['events'],[])

    def test_stop_unloads_agent_and_detaches_without_killing_app(self):
        from unittest.mock import MagicMock
        runtime=DynamicRuntime();runtime.agent=MagicMock();runtime.session=MagicMock()
        agent,session=runtime.agent,runtime.session
        runtime.stop();agent.unload.assert_called_once();session.detach.assert_called_once()

    def test_stop_preserves_abnormal_detached_terminal_state(self):
        runtime=DynamicRuntime();runtime.receipt={'id':'dyn_one','lab_id':'lab','state':'detached'}
        with tempfile.TemporaryDirectory() as directory,patch('huntmob.dynamic_runtime.root',return_value=Path(directory)):
            (Path(directory)/'lab').mkdir()
            result=runtime.stop()
        self.assertEqual(result['state'],'detached')
        self.assertEqual(runtime.receipt['state'],'detached')

