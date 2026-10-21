import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from huntmob import workspace_devices as devices
from huntmob.android_worker import AndroidWorker
from huntmob.codec_relay import CodecRelay

PARENT = 'huntmob_lab_' + 'a' * 32
CHILD = 'huntmob_lab_' + 'b' * 32
OTHER = 'huntmob_lab_' + 'c' * 32


class WorkspaceDevicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        change = patch.object(devices, 'root', return_value=self.folder / 'devices')
        change.start(); self.addCleanup(change.stop)
        self.record = {'id': CHILD, 'workspace_id': PARENT, 'port': 5558, 'root_mode': 'stock', 'android_api': 35, 'created_at': 'now'}

    def test_saved_device_is_scoped_and_rejects_arbitrary_serials(self):
        devices._save(self.record)
        self.assertEqual(devices.owned(PARENT, CHILD), self.record)
        for parent, child in [(OTHER, CHILD), (PARENT, 'emulator-5556'), ('../../x', CHILD)]:
            with self.assertRaises(ValueError): devices.owned(parent, child)
        self.assertEqual(devices.worker(self.record).serial, 'emulator-5558')
        self.assertEqual(devices.worker(self.record).port, '5558')

    def test_invalid_ports_cannot_retarget_primary(self):
        for port in [5556, 5559, True, '5558', 5682]:
            with self.assertRaises(ValueError): AndroidWorker(port=port)

    def test_allocator_skips_saved_and_external_device_ports(self):
        devices._save(self.record)
        sdk = SimpleNamespace(adb='adb')
        with patch.object(devices, '_run', return_value=subprocess.CompletedProcess([], 0, 'emulator-5560\tdevice\n', '')):
            self.assertGreaterEqual(devices._available_port(sdk), 5562)

    def test_changed_workspace_never_creates_or_stops_device(self):
        with patch.object(devices, 'current', return_value={'id': OTHER}), patch.object(devices, 'AndroidWorker') as factory:
            self.assertFalse(devices.create(PARENT)['ok']); factory.assert_not_called()

    def test_creation_uses_fresh_data_same_config_without_switching_current(self):
        primary = Mock(architecture='arm64-v8a')
        primary.status.return_value = {'ownership_verified': True}
        target = Mock()
        target.create.return_value = target.start.return_value = {'ok': True}
        target.root_status.return_value={'verified':True,'root_available':False}
        source = {'id': PARENT, 'root_mode': 'stock', 'android_api': 34}
        with patch.object(devices, 'current', return_value=source), patch.object(devices, 'AndroidWorker', return_value=primary), patch.object(devices, 'worker', return_value=target), patch.object(devices, '_available_port', return_value=5562), patch.object(devices, 'configure_graphics'), patch.object(devices, '_copy_display') as copy:
            result = devices.create(PARENT)
        self.assertTrue(result['ok'])
        record = result['device']
        self.assertEqual((record['root_mode'], record['android_api'], record['port'], record['data_mode']), ('stock', 34, 5562, 'clean'))
        primary.stop.assert_not_called(); primary.destroy.assert_not_called()
        self.assertFalse((self.folder / 'devices/current.json').exists())
        copy.assert_called_once_with(PARENT, record['id'])

    def test_wrong_workspace_actions_never_reach_worker(self):
        devices._save(self.record)
        with patch.object(devices, 'worker') as worker:
            result = devices.action({'workspace_id': OTHER, 'device_id': CHILD, 'action': 'stop'})
        self.assertFalse(result['ok']); worker.assert_not_called()

    def test_video_channels_have_distinct_forwards_and_immutable_owners(self):
        devices._save(self.record)
        one = devices.relay(self.record)
        second = {**self.record, 'id': OTHER, 'port': 5560}
        devices._save(second)
        two = devices.relay(second)
        self.assertNotEqual(one.forward_port, two.forward_port)
        self.assertFalse(one.owner_check(OTHER)); self.assertTrue(one.owner_check(CHILD))
        devices.RELAYS.clear()

    def test_direct_input_uses_verified_channel_without_running_adb_for_every_move(self):
        devices._save(self.record)
        target = Mock(sdk=SimpleNamespace(adb='adb'), serial='emulator-5558', avd_name=CHILD)
        channel = Mock(target=('adb', 'emulator-5558', CHILD))
        channel.input.return_value = {'ok': True}
        with patch.object(devices, 'worker', return_value=target), patch.object(devices, 'relay', return_value=channel):
            result = devices.action({'workspace_id': PARENT, 'device_id': CHILD, 'action': 'input', 'input': {'action': 'touch', 'phase': 'down', 'x': .2, 'y': .4}})
        self.assertTrue(result['ok']); target.status.assert_not_called()
        channel.input.assert_called_once()

    def test_persisted_device_with_invalid_port_is_not_accepted(self):
        devices._save({**self.record, 'port': 5556})
        self.assertEqual(devices.records(), [])

    def test_root_override_is_independent_of_stock_primary(self):
        primary=Mock(architecture='arm64-v8a');primary.status.return_value={'ownership_verified':True}
        target=Mock();target.prepare_profile.return_value=target.create.return_value=target.start.return_value={'ok':True}
        target.root_status.return_value={'verified':True,'root_available':True}
        source={'id':PARENT,'root_mode':'stock','android_api':35}
        with patch.object(devices,'current',return_value=source),patch.object(devices,'AndroidWorker',return_value=primary),patch.object(devices,'worker',return_value=target),patch.object(devices,'_available_port',return_value=5562),patch.object(devices,'configure_graphics'),patch.object(devices,'_copy_display'):
            result=devices.create(PARENT,root_mode='root')
        self.assertTrue(result['ok']);self.assertEqual(result['device']['root_mode'],'root')
        self.assertEqual(source['root_mode'],'stock');primary.stop.assert_not_called();target.prepare_profile.assert_called_once_with('root')

    def test_invalid_root_profile_is_rejected_before_worker_or_session_changes(self):
        with patch.object(devices,'worker') as worker,patch.object(devices,'_save') as save:
            self.assertFalse(devices.create(PARENT,root_mode='invalid')['ok'])
        worker.assert_not_called();save.assert_not_called()

    def test_companion_relay_ignores_current_selection_but_never_another_owner(self):
        relay = CodecRelay(owner_check=lambda identifier: identifier == CHILD, forward_port=33558)
        relay.target = ('adb', 'emulator-5558', CHILD); relay.control = Mock()
        with patch('huntmob.codec_relay.current', return_value={'id': PARENT}):
            self.assertTrue(relay.input({'action': 'home'})['ok'])
        relay.target = ('adb', 'emulator-5558', OTHER)
        self.assertFalse(relay.input({'action': 'home'})['ok'])

    def test_stale_generation_is_rejected_before_input(self):
        devices._save(self.record)
        target = Mock(sdk=SimpleNamespace(adb='adb'), serial='emulator-5558', avd_name=CHILD)
        channel = Mock(target=('adb', 'emulator-5558', CHILD))
        channel.snapshot.return_value = {'generation': 3}
        with patch.object(devices, 'worker', return_value=target), patch.object(devices, 'relay', return_value=channel):
            result = devices.action({'workspace_id': PARENT, 'device_id': CHILD, 'action': 'input',
                                     'session_generation': 2, 'input': {'action': 'home'}})
        self.assertFalse(result['ok'])
        self.assertTrue(result['stale_session'])
        channel.input.assert_not_called()

    def test_snapshot_isolates_discovery_failure_and_exposes_contract(self):
        devices._save(self.record)
        good = {**self.record, 'id': OTHER, 'port': 5560, 'created_at': 'later'}
        devices._save(good)
        good_worker = Mock()
        good_worker.status.return_value = {'state': 'device', 'ownership_verified': True,
                                           'properties': {'sys.boot_completed': '1'}}
        good_relay = Mock()
        good_relay.snapshot.return_value = {'state': 'idle', 'transport': 'h264-webcodecs',
                                            'generation': 7, 'frames': 0, 'input_ready': False}

        def choose(record):
            if record['id'] == CHILD:
                raise OSError('private worker detail')
            return good_worker

        with patch.object(devices, 'worker', side_effect=choose), patch.object(devices, 'relay', return_value=good_relay), \
             patch.object(devices, 'current', return_value={}):
            result = devices.snapshot(PARENT)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['devices']), 2)
        self.assertEqual(result['contract']['schema'], 'huntmob.device-inventory/v1')
        self.assertEqual(result['contract']['discovery_errors'][0]['reason'], 'device_discovery_failed')
        self.assertNotIn('private worker detail', json.dumps(result))
        normalized = next(item for item in result['contract']['devices'] if item['identity']['device_id'] == OTHER)
        self.assertEqual(normalized['channels']['stream']['status'], 'idle')
        self.assertEqual(normalized['channels']['stream']['generation'], 7)
        self.assertTrue(normalized['capabilities']['security']['frida'])
