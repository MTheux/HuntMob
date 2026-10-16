import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from huntmob.dynamic_runtime import DynamicRuntime, scope


class DynamicTests(unittest.TestCase):
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

