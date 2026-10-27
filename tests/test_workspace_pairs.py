import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from huntmob import workspace_pairs as pairs, workspace_devices as devices, dynamic_runtime as dynamic

SOURCE = 'huntmob_lab_' + 'a' * 32
CHILD = 'huntmob_lab_' + 'b' * 32
LAB = {'id': SOURCE, 'package_id': 'com.lab.fixture', 'apk_sha256': 'a' * 64, 'root_mode': 'stock', 'android_api': 30}
CHILD_RECORD = {'id': CHILD, 'workspace_id': SOURCE, 'platform': 'android', 'port': 5558, 'root_mode': 'root', 'android_api': 35,
                'package_id': LAB['package_id'], 'apk_sha256': LAB['apk_sha256'], 'created_at': 'now',
                'link': {'kind': 'root-companion', 'source_id': SOURCE, 'state': 'ready'}}


class PairTests(unittest.TestCase):
    def worker(self, serial):
        device = MagicMock(serial=serial, sdk=SimpleNamespace(adb='adb'))
        device.status.return_value = {'ownership_verified': True, 'state': 'device', 'properties': {'sys.boot_completed': '1'}}
        return device

    def test_apk_paths_reject_untrusted_paths_and_duplicate_base(self):
        device = self.worker('emulator-5556')
        for output in ('package:/sdcard/base.apk', 'package:/data/app/a/../base.apk', 'package:/data/app/a/$(whoami)/base.apk',
                       'package:/data/app/a/base.apk\npackage:/data/app/b/base.apk', 'package:/data/app/a/split.apk'):
            with self.subTest(output=output), patch.object(pairs, '_run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                with self.assertRaises(ValueError): pairs.apk_paths(device, LAB['package_id'])

    def test_split_set_keeps_original_bytes_and_never_launches_app(self):
        source, target = self.worker('emulator-5556'), self.worker('emulator-5558')
        contents = {'base.apk': b'original-base', 'split.apk': b'original-split'}
        def run(command, **kwargs):
            tail = command[3:]
            output = ''
            if tail[:3] == ('shell', 'pm', 'path'): output = '\n'.join('package:/data/app/pkg/' + name for name in reversed(contents))
            elif tail[:2] == ('shell', 'stat'): output = str(len(contents[Path(tail[-1]).name]))
            elif tail[0] == 'pull': Path(tail[2]).write_bytes(contents[Path(tail[1]).name])
            elif tail[:2] == ('shell', 'sha256sum'): output = hashlib.sha256(contents[Path(tail[-1]).name]).hexdigest()
            elif tail[0] == 'install-multiple':
                self.assertEqual(command[2], target.serial)
                self.assertEqual([Path(p).read_bytes() for p in tail[3:]], list(contents.values()))
                output = 'Success'
            else: self.fail('Unexpected native action: ' + str(tail))
            return subprocess.CompletedProcess(command, 0, output, '')
        with patch.object(pairs, '_run', side_effect=run):
            receipt = pairs.copy_app(source, target, LAB['package_id'], hashlib.sha256(contents['base.apk']).hexdigest())
        self.assertEqual(receipt['state'], 'verified'); self.assertEqual(len(receipt['files']), 2)
        source.launch_app.assert_not_called(); target.launch_app.assert_not_called()

    def test_base_hash_mismatch_blocks_install(self):
        source, target = self.worker('emulator-5556'), self.worker('emulator-5558')
        def run(command, **kwargs):
            if 'stat' in command: return subprocess.CompletedProcess(command, 0, '4', '')
            Path(command[-1]).write_bytes(b'base')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(pairs, 'apk_paths', return_value=['/data/app/pkg/base.apk']), patch.object(pairs, '_run', side_effect=run) as calls, patch.object(pairs, 'remote_digest', return_value=hashlib.sha256(b'base').hexdigest()):
            with self.assertRaises(ValueError): pairs.copy_app(source, target, LAB['package_id'], '0' * 64)
        self.assertFalse(any('install' in call.args[0] for call in calls.call_args_list))

    def test_foreign_workspace_is_rejected_before_native_discovery(self):
        with patch.object(pairs, 'current', return_value=LAB), patch.object(pairs, 'AndroidWorker') as worker:
            with self.assertRaises(ValueError): pairs.checked_source(CHILD)
        worker.assert_not_called()

    def test_repeated_create_reuses_running_job(self):
        with patch.object(pairs, 'checked_source', return_value=(LAB, self.worker('emulator-5556'))), patch.object(devices, 'records', return_value=[CHILD_RECORD]), patch.object(pairs, 'JOBS', {CHILD}), patch.object(pairs.threading, 'Thread') as thread:
            result = pairs.start(SOURCE, 'all')
        self.assertEqual(result['device']['id'], CHILD); thread.assert_not_called()

    def test_invalid_sync_scope_never_mutates(self):
        with patch.object(pairs, 'checked_source') as checked:
            with self.assertRaises(ValueError): pairs.start(SOURCE, 'private-data')
        checked.assert_not_called()

    def test_network_without_private_wifi_does_not_start_listener(self):
        source, target = self.worker('emulator-5556'), self.worker('emulator-5558')
        with patch.object(pairs, 'checked_source', return_value=(LAB, source)), patch.object(devices, 'owned', return_value=CHILD_RECORD), patch.object(devices, 'worker', return_value=target), patch.object(pairs, '_run', return_value=subprocess.CompletedProcess([], 0, 'inet 8.8.8.8/24', '')), patch.object(pairs.subprocess, 'Popen') as popen:
            self.assertEqual(pairs.network_check(CHILD_RECORD)['state'], 'pending')
        popen.assert_not_called()

    def test_service_bridge_rolls_back_only_its_forward_when_access_port_is_busy(self):
        source, target = self.worker('emulator-5556'), self.worker('emulator-5558')
        with patch.object(pairs, 'checked_source', return_value=(LAB, source)), patch.object(devices, 'owned', return_value=CHILD_RECORD), patch.object(devices, 'worker', return_value=target), patch.object(pairs, '_run', side_effect=[subprocess.CompletedProcess([], 0, '', ''), subprocess.CompletedProcess([], 1, '', ''), subprocess.CompletedProcess([], 0, '', '')]) as run:
            with self.assertRaises(ValueError): pairs.service_bridge(SOURCE, CHILD)
        self.assertEqual(run.call_args_list[0].args[0][-4:], ('forward', '--no-rebind', 'tcp:40558', 'tcp:9000'))
        self.assertEqual(run.call_args_list[-1].args[0][-3:], ('forward', '--remove', 'tcp:40558'))

    def test_service_port_validation_precedes_native_actions(self):
        with patch.object(devices, 'owned') as owned:
            for value in (22, 65536, '9000', True):
                with self.assertRaises(ValueError): pairs.service_bridge(SOURCE, CHILD, value)
        owned.assert_not_called()

    def test_bridge_cleanup_preserves_other_mappings(self):
        source, target = self.worker('emulator-5556'), self.worker('emulator-5558')
        record = {**CHILD_RECORD, 'link': {**CHILD_RECORD['link'], 'service': {'enabled': True, 'service_port': 9000, 'access_port': 19000}}}
        with patch.object(pairs, '_run', return_value=subprocess.CompletedProcess([], 0, 'emulator-5560 tcp:40558 tcp:9100', '')) as run, patch.object(pairs, 'update'):
            pairs.release_bridge(record, source, target)
        self.assertFalse(any('--remove' in call.args[0] for call in run.call_args_list))


class CompanionRuntimeTests(unittest.TestCase):
    def test_workspace_cleanup_stops_only_its_own_companion_sessions(self):
        ours, other = MagicMock(), MagicMock()
        with patch.object(dynamic, 'RUNTIMES', {(SOURCE, CHILD): ours, (CHILD, SOURCE): other}):
            dynamic.stop_workspace(SOURCE)
        ours.stop.assert_called_once_with(); other.stop.assert_not_called()

    def test_target_is_bound_to_owned_child_and_distinct_forward(self):
        with patch.object(dynamic, 'current', return_value=LAB), patch.object(devices, 'owned', return_value=CHILD_RECORD):
            one = dynamic.runtime_for(SOURCE, CHILD)
            two = dynamic.runtime_for(SOURCE, SOURCE)
            self.assertIsNot(one, two); self.assertEqual(one.forward_port, 34558)
            self.assertEqual(one.context()['id'], CHILD)
        with patch.object(dynamic, 'current', return_value={**LAB, 'id': CHILD}):
            with self.assertRaises(ValueError): one.context()

    def test_changed_original_hash_invalidates_companion_selection(self):
        with patch.object(dynamic, 'current', return_value={**LAB, 'apk_sha256': 'c' * 64}), patch.object(devices, 'owned', return_value=CHILD_RECORD):
            self.assertIsNone(dynamic.target_context(SOURCE, CHILD)['package_id'])
            with self.assertRaises(ValueError): dynamic.scope(LAB['package_id'], SOURCE, CHILD)

    def test_child_export_excludes_primary_proxy_and_primary_screenshots(self):
        runtime = dynamic.DynamicRuntime(SOURCE, CHILD, 34558)
        runtime.receipt = {'id': 'dyn_' + 'd' * 32, 'lab_id': CHILD, 'started_at': '2026-01-01', 'state': 'stopped'}
        with patch.object(dynamic, 'current', return_value=LAB), patch.object(devices, 'owned', return_value=CHILD_RECORD), patch('huntmob.lab_sessions.network_store') as network, patch('huntmob.evidence.EvidenceStore') as evidence:
            evidence.return_value.inventory.return_value = {'records': [{'lab_id': SOURCE, 'created_at': '2026-05-01'}, {'lab_id': CHILD, 'created_at': '2026-05-01'}]}
            exported = json.loads(runtime.export())
        network.assert_not_called(); self.assertEqual(exported['network'], [])
        self.assertEqual([item['lab_id'] for item in exported['screenshots']], [CHILD])
