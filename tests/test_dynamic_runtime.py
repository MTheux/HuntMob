import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from huntmob.dynamic_runtime import DynamicRuntime, frida_compatibility, frida_server_ready, scope


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

