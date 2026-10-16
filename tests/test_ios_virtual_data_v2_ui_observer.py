"""Public fixtures only. No SDK compilation, VM, images or Keychain access."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import stage_ios_virtual_data_v2_ui_observer as observer


def completed_log(rows=True):
    values = ['HuntMob:ui-proc stock-init-start', 'HuntMob:ui-proc stock-init-exit=0 signal=0',
              'HuntMob:ui-proc observer-spawned pid=42', observer.BEGIN]
    if rows:
        values += ['HuntMob:ui-proc sample=0 service=backboardd pid=50 state=3',
                   'HuntMob:ui-proc sample=23 service=SpringBoard pid=51 state=3']
    return '\n'.join(values + [observer.END, 'Early boot complete. Continuing system boot.'])


def stock_fixture():
    def tlv(tag, blob):
        assert len(blob) < 128
        return bytes((tag, len(blob))) + blob
    entry = b's' * 20 + b'\x02\x00'
    payload = struct.pack('<I', 1) + b'o' * 16 + struct.pack('<I', 2) + entry * 2
    return tlv(0x30, tlv(0x16, b'IM4P') + tlv(0x16, b'rtsc') + tlv(0x16, b'stock') + tlv(4, payload)), entry


class UIObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_frozen_source_pins_are_exact(self):
        observer.source_pins()
        self.assertEqual(len(observer.PINS), 5)

    def test_complete_sampler_does_not_validate_ui_or_absence_crash(self):
        result = observer.classify_result(completed_log())
        self.assertTrue(result['sampler_completed'])
        self.assertEqual(result['sample_snapshots_reported'], 24)
        self.assertEqual(result['process_row_count'], 2)
        self.assertFalse(result['ready'])
        self.assertFalse(result['native_ready'])
        self.assertFalse(result['full_boot_validated'])
        self.assertFalse(result['springboard_validated'])
        self.assertFalse(result['ipa_execution_validated'])
        self.assertTrue(result['process_presence_is_not_ui_or_missing_process_crash_proof'])

    def test_completed_zero_process_rows_is_metadata_not_missing_process_crash_proof(self):
        result = observer.classify_result(completed_log(rows=False))
        self.assertTrue(result['sampler_completed'])
        self.assertEqual(result['process_row_count'], 0)
        self.assertFalse(result['springboard_validated'])

    def test_spawn_log_can_race_sampler_begin_without_false_failure(self):
        log = completed_log().replace('HuntMob:ui-proc observer-spawned pid=42\n', '')
        log = log.replace(observer.BEGIN, observer.BEGIN + '\nHuntMob:ui-proc observer-spawned pid=42')
        self.assertTrue(observer.classify_result(log)['sampler_completed'])

    def test_known_diagnostic_failure_is_incomplete_but_stock_restorable(self):
        for label in ['wrapper-post-init-guard-failed', 'observer-spawn-failed', 'observer-group-failed']:
            log = '\n'.join(['HuntMob:ui-proc stock-init-start', 'HuntMob:ui-proc stock-init-exit=0 signal=0',
                             'HuntMob:ui-proc ' + label, 'Early boot complete. Continuing system boot.'])
            result = observer.classify_result(log)
            self.assertFalse(result['sampler_completed'])
            self.assertIsNone(result['sample_snapshots_reported'])
            self.assertEqual(result['diagnostic_failure_labels'], [label])
            self.assertFalse(result['native_ready'])
        log = completed_log().replace(observer.END, 'HuntMob:ui-proc failed')
        self.assertFalse(observer.classify_result(log)['sampler_completed'])

    def test_unknown_failure_missing_end_or_malformed_payload_refused(self):
        candidates = [completed_log().replace(observer.END, ''),
                      completed_log() + '\nHuntMob:ui-proc unknown secret=do-not-copy',
                      completed_log() + '\nHuntMob:ui-proc sample=0 service=Unknown pid=1 state=3',
                      completed_log().replace('state=3', 'state=8'),
                      completed_log().replace('pid=51', 'pid=9999999999'),
                      completed_log().replace('sample=23', 'sample=24')]
        for candidate in candidates:
            with self.subTest(candidate=candidates.index(candidate)), self.assertRaises(ValueError):
                observer.classify_result(candidate)

    def test_duplicate_out_of_order_or_outside_window_rows_refused(self):
        good = completed_log()
        row = 'HuntMob:ui-proc sample=0 service=backboardd pid=50 state=3'
        candidates = [good.replace(observer.END, row + '\n' + observer.END),
                      good.replace('sample=0', 'sample=23').replace('sample=23 service=SpringBoard', 'sample=0 service=SpringBoard'),
                      row + '\n' + good, good + '\n' + row]
        for candidate in candidates:
            with self.assertRaises(ValueError):
                observer.classify_result(candidate)

    def test_failed_stock_init_panic_checkpoint_and_provisioning_never_restored_automatically(self):
        good = completed_log()
        candidates = [good.replace('stock-init-exit=0 signal=0', 'stock-init-exit=1 signal=0'),
                      good.replace('stock-init-exit=0 signal=0', 'stock-init-exit=-1 signal=9'),
                      good + '\npanic(cpu', good + '\nBoot task failed: keybag',
                      good + '\nHuntMob: provisioning checkpoint ready;',
                      good + '\nfresh MKBCreateSystem', good + '\nClassD initialization',
                      good.replace('Early boot complete. Continuing system boot.', '')]
        for candidate in candidates:
            with self.assertRaises(ValueError):
                observer.classify_result(candidate)

    def test_trustcache_adds_only_two_hashes_and_preserves_stock_entries(self):
        base, entry = stock_fixture()
        hashes = ['1' * 40, '2' * 40]
        with patch.object(observer, 'BASE_TC_SHA', hashlib.sha256(base).hexdigest()):
            result = observer.trustcache_transition(base, hashes, observer.VM_UUID)
            count, = struct.unpack_from('<I', result, 20)
            self.assertEqual(count, 3)
            actual = [result[24+i*22:46+i*22] for i in range(count)]
            self.assertEqual(actual, sorted([entry] + [bytes.fromhex(h)+b'\x02\x00' for h in hashes]))
            for invalid in ([hashes[0]], [hashes[0], hashes[0]], ['s' * 40, hashes[0]], [entry[:20].hex(), hashes[0]]):
                with self.assertRaises(ValueError):
                    observer.trustcache_transition(base, invalid, observer.VM_UUID)
            with self.assertRaises(ValueError):
                observer.trustcache_transition(base[:-1], hashes, observer.VM_UUID)

    def test_shared_lock_prevents_concurrent_operation_and_removes_only_own_lock(self):
        with patch.object(observer.contract, 'validate_manifest') as validate:
            with observer.owned_lock(self.root, {}):
                self.assertTrue((self.root/'.data-v2-launch.lock').exists())
                with self.assertRaises(FileExistsError):
                    with observer.owned_lock(self.root, {}):
                        self.fail('concurrent lock accepted')
            self.assertFalse((self.root/'.data-v2-launch.lock').exists())
            self.assertEqual(validate.call_count, 1)

    def test_replaced_lock_is_preserved_for_manual_review(self):
        path = self.root/'.data-v2-launch.lock'
        with self.assertRaises(ValueError), patch.object(observer.contract, 'validate_manifest'):
            with observer.owned_lock(self.root, {}):
                other = self.root/'other'; other.write_bytes(b'other-owner')
                os.replace(other, path)
        self.assertEqual(path.read_bytes(), b'other-owner')

    def scan_fixture(self):
        sizes = {name: 32 for name in observer.profile.SIZES}
        manifest = {'engine_binding': {'public-fixture': True}, 'backings': {}}
        record = {'schema': 'huntmob.virtual-sep-data-storage-probe-scan.v1', 'state': 'completed-readonly-scan',
                  'vm_uuid': observer.VM_UUID, 'data_profile': observer.contract.PROFILE,
                  'engine_binding': manifest['engine_binding'], 'total_bytes_scanned': sum(sizes.values()),
                  'total_matches': 0, 'public_probe_absent': True, 'global_source_identity_unchanged': True,
                  'host_backings_not_attached_before_after': True, 'historical_finding_status': 'OPEN',
                  'scoped_native_cold_read': {'validated': True}, 'backings': {}}
        for key in ['root_accessed', 'keychain_accessed', 'vm_started', 'backings_written', 'Data_mounted_or_unlocked',
                    'cryptography_validated_by_scan', 'ready', 'native_ready']:
            record[key] = False
        for name, size in sizes.items():
            (self.root/name).write_bytes(b'Z'*size)
            ident = observer.reader.path_identity(self.root/name)
            manifest['backings'][name] = {k: ident[k] for k in ['device', 'inode', 'bytes', 'links']}
            record['backings'][name] = {'identity_before': ident, 'identity_after': ident, 'bytes_scanned': size,
                'matches': {key: {'count': 0, 'offsets': [], 'offsets_truncated': False} for key in ['ascii_hex64', 'decoded32']}}
        directory = self.root/observer.SCAN; directory.mkdir()
        path = directory/'receipt.json'; path.write_text(json.dumps(record))
        return sizes, manifest, record, path

    def check_scan(self, sizes, manifest, path, current):
        with patch.object(observer.profile, 'SIZES', sizes), patch.object(observer, 'SCAN_SHA', hashlib.sha256(path.read_bytes()).hexdigest()):
            return observer.checked_scan(self.root, manifest, current)

    def test_install_requires_fresh_all_nine_but_consume_allows_expected_native_writes(self):
        sizes, manifest, _, path = self.scan_fixture()
        self.check_scan(sizes, manifest, path, True)
        first = self.root/next(iter(sizes))
        first.write_bytes(b'Q'*32)
        with self.assertRaises(ValueError):
            self.check_scan(sizes, manifest, path, True)
        self.check_scan(sizes, manifest, path, False)

    def test_historical_scan_still_rejects_alias_partial_extent_match_or_engine_drift(self):
        sizes, manifest, record, path = self.scan_fixture()
        mutations = []
        value = copy.deepcopy(record); value['backings'].pop(next(iter(sizes))); mutations.append(value)
        value = copy.deepcopy(record); value['backings'][next(iter(sizes))]['bytes_scanned'] -= 1; mutations.append(value)
        value = copy.deepcopy(record); value['backings'][next(iter(sizes))]['matches']['decoded32']['count'] = 1; mutations.append(value)
        value = copy.deepcopy(record); value['engine_binding'] = {}; mutations.append(value)
        value = copy.deepcopy(record); value['backings'][next(iter(sizes))]['identity_after']['inode'] += 1; mutations.append(value)
        for value in mutations:
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                self.check_scan(sizes, manifest, path, False)

    def test_modified_scan_digest_rejected_before_layout_or_any_mutation(self):
        sizes, manifest, _, path = self.scan_fixture()
        with patch.object(observer.profile, 'SIZES', sizes), patch.object(observer, 'SCAN_SHA', '0'*64):
            with self.assertRaises(ValueError):
                observer.checked_scan(self.root, manifest, True)

    def observation_fixture(self, log=None):
        directory = self.root/'data-v2-observation-20261015-200000'; directory.mkdir()
        log = completed_log() if log is None else log
        trace = ('apple_sep_virtual_operation command=0x201 keydisable=0x0 iterations=1 accepted=1\n'
                 'pci_nvme_apple_ans_complete sqid=1 cid=1 opcode=0x01 status=0x0000\n')
        (directory/'boot.log').write_text(log); (directory/'trace.log').write_text(trace)
        manifest = {'engine_binding': {'public-test': True},
                    'data_profile_sha256': observer.contract.canonical_hash(observer.contract.PROFILE)}
        proof = {'schema': 'huntmob.virtual-sep-data-observation.v2', 'vm_uuid': observer.VM_UUID,
                 'engine_binding': manifest['engine_binding'], 'data_profile': observer.contract.PROFILE,
                 'data_profile_sha256': manifest['data_profile_sha256'], 'ui_process_observer_requested': True,
                 'normal_boot_requested': False, 'sep_profile': 'serving', 'headless_refresh_hz_requested': 10,
                 'headless_refresh_does_not_validate_ui': True, 'headless_refresh_accepted_count': 20,
                 'seconds': 240, 'elapsed_seconds': 240.01, 'stop_reason': 'bounded-observation-ended',
                 'stock_early_boot_marker_observed': True, 'qmp_quit_requested': True, 'qmp_quit_accepted': True,
                 'exit_code': 0, 'aess_command_count': 1}
        for key in ('panic_observed', 'own_checkpoint_unexpected', 'checkpoint_observed',
                    'virtual_mpe_memory_fault_observed', 'mpe_rejected_revocation_observed', 'ready', 'native_ready',
                    'full_boot_validated', 'springboard_validated', 'ipa_execution_validated', 'auxiliary_bootstrap_requested',
                    'effaceable_ramdisk_requested', 'effaceable_observer_requested', 'cold_class_c_read_requested',
                    'post_keybag_class_c_read_requested', 'factorydata_seed_requested', 'update_volume_bootstrap_requested'):
            proof[key] = False
        for key in ('aess_rejected_command_count', 'nvme_error_completion_count', 'protected_io_rejection_count',
                    'protected_gate_rejection_count'):
            proof[key] = 0
        for name in ('boot.log', 'trace.log'):
            proof[name+'_sha256'] = hashlib.sha256((directory/name).read_bytes()).hexdigest()
        path = directory/'observation.json'; path.write_text(json.dumps(proof))
        return manifest, {'observation': str(directory)}, proof, path

    def test_consumed_native_evidence_requires_hashes_exact240_and_real_trace_counts(self):
        manifest, record, proof, path = self.observation_fixture()
        result = observer.consumed_observation(self.root, manifest, record)
        self.assertTrue(result['sampler_completed'])
        self.assertFalse(result['ready'])
        for key, value in [('seconds', 120), ('elapsed_seconds', 119), ('qmp_quit_accepted', False),
                           ('springboard_validated', True), ('factorydata_seed_requested', True),
                           ('aess_command_count', 0), ('normal_boot_requested', True)]:
            changed = dict(proof); changed[key] = value; path.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                observer.consumed_observation(self.root, manifest, record)
        path.write_text(json.dumps(proof))
        trace = path.parent/'trace.log'
        trace.write_text(trace.read_text().replace('status=0x0000', 'status=0x4002'))
        proof['trace.log_sha256'] = hashlib.sha256(trace.read_bytes()).hexdigest(); path.write_text(json.dumps(proof))
        with self.assertRaises(ValueError):
            observer.consumed_observation(self.root, manifest, record)

    def test_consumed_known_incomplete_diagnostic_can_restore_without_readiness(self):
        log = '\n'.join(['HuntMob:ui-proc stock-init-start', 'HuntMob:ui-proc stock-init-exit=0 signal=0',
                         'HuntMob:ui-proc observer-spawn-failed', 'Early boot complete. Continuing system boot.'])
        manifest, record, _, _ = self.observation_fixture(log)
        result = observer.consumed_observation(self.root, manifest, record)
        self.assertFalse(result['sampler_completed'])
        self.assertFalse(result['ready'])
        self.assertEqual(result['result'], 'diagnostic-incomplete-stock-restorable')

    def test_only_exact_first_receipt_can_omit_full_boot_false(self):
        manifest, record, proof, path = self.observation_fixture()
        del proof['full_boot_validated']
        path.write_text(json.dumps(proof))
        with self.assertRaises(ValueError):
            observer.consumed_observation(self.root, manifest, record)
        directory = path.parent.with_name('data-v2-observation-20261015-183446')
        path.parent.rename(directory)
        path = directory/'observation.json'
        record['observation'] = str(directory)
        real_stable_blob = observer.reader.stable_blob
        exact_sha = '13770ec679cfe6b5aa8c5fe76bbb9fab4267b4890255e702f6c14f40ec3f5c6a'

        def fixture_digest(value, limit):
            blob, digest, identity = real_stable_blob(value, limit)
            return blob, exact_sha if value == path else digest, identity

        # The public fixture substitutes only the immutable receipt digest;
        # log hashes, trace counters and all remaining checks still execute.
        with patch.object(observer.reader, 'stable_blob', side_effect=fixture_digest):
            result = observer.consumed_observation(self.root, manifest, record)
            self.assertFalse(result['full_boot_validated'])
            self.assertFalse(result['ready'])
            self.assertFalse(result['native_ready'])
            self.assertFalse(result['springboard_validated'])
            self.assertFalse(result['ipa_execution_validated'])
            for key in ('full_boot_validated', 'ready', 'native_ready', 'springboard_validated', 'ipa_execution_validated'):
                changed = dict(proof); changed[key] = True; path.write_text(json.dumps(changed))
                with self.subTest(true=key), self.assertRaises(ValueError):
                    observer.consumed_observation(self.root, manifest, record)
            for key in ('ready', 'native_ready', 'springboard_validated', 'ipa_execution_validated', 'panic_observed'):
                changed = dict(proof); del changed[key]; path.write_text(json.dumps(changed))
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    observer.consumed_observation(self.root, manifest, record)
            path.write_text(json.dumps(proof))
        # Exact observation name alone, with an unbound digest, stays rejected.
        with self.assertRaises(ValueError):
            observer.consumed_observation(self.root, manifest, record)

    def test_changed_native_log_provenance_rejected(self):
        manifest, record, _, path = self.observation_fixture()
        (path.parent/'boot.log').write_text('changed public fixture')
        with self.assertRaises(ValueError):
            observer.consumed_observation(self.root, manifest, record)

    def test_validate_for_boot_refuses_backing_drift_after_install_even_with_historical_scan(self):
        sizes, _, _, _ = self.scan_fixture()
        record = {'schema': observer.SCHEMA, 'profile': observer.contract.PROFILE, 'vm_uuid': observer.VM_UUID,
                  'data_uuid': observer.DATA_UUID, 'state': 'installed', 'source_sha256': observer.PINS,
                  'engine_binding': {}, 'identity_binding': {key: None for key in observer.IDENTITY_KEYS},
                  'host_data_mounted': False, 'sampler_metadata_only': True, 'headless_refresh_hz_required': 10,
                  'observation_seconds_required': 240, 'evidence': {'public': True},
                  'stock_keybag_same_inode_moved': True, 'original_stock_program_bytes_preserved': True,
                  'owned_device_detached': True, 'existing_six_volumes_preserved': True}
        with patch.object(observer.profile, 'SIZES', sizes):
            record['post_install_backings'] = observer.file_snapshots(self.root)
            (self.root/next(iter(sizes))).write_bytes(b'X'*32)
            manifest = {'vm_uuid': observer.VM_UUID, 'engine_binding': {}, observer.RECORD: record}
            with patch.object(observer, 'evidence', return_value={'public': True}), self.assertRaises(ValueError):
                observer.validate_for_boot(self.root, manifest)

    def test_only_wrapper_compile_suppresses_commoncrypto_deprecation(self):
        from types import SimpleNamespace
        calls = []
        def fake_run(args, **kwargs):
            calls.append(args)
            if args[:4] == ['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']:
                return SimpleNamespace(stdout=b'/public/iPhoneOS.sdk')
            if args[:4] == ['xcrun', '--sdk', 'iphoneos', 'clang']:
                Path(args[args.index('-o')+1]).write_bytes(b'public-signed-code-fixture')
            if args[:2] == ['codesign', '-d']:
                return SimpleNamespace(stdout=observer.plistlib.dumps(observer.WRAPPER_ENTITLEMENTS))
            return SimpleNamespace(stdout=b'')
        with patch.object(observer.stage, 'run', side_effect=fake_run):
            observer.compile_helpers(self.root/'build', observer.VM_UUID)
        compiles = [args for args in calls if args[:4] == ['xcrun', '--sdk', 'iphoneos', 'clang']]
        self.assertEqual(len(compiles), 2)
        self.assertNotIn('-Wno-deprecated-declarations', compiles[0])
        self.assertIn('-Wno-deprecated-declarations', compiles[1])
        for args in compiles:
            self.assertIn('-Wall', args); self.assertIn('-Wextra', args); self.assertIn('-Werror', args)

    def test_default_plan_reads_no_cohort_engine_or_guest(self):
        stream = io.StringIO()
        with patch.object(sys, 'argv', ['stager', '--vm-uuid', observer.VM_UUID]), redirect_stdout(stream):
            with patch.object(observer.contract, 'validate_manifest', side_effect=AssertionError('cohort read')):
                with patch.object(observer, 'install', side_effect=AssertionError('installed')):
                    observer.main()
        result = json.loads(stream.getvalue())
        self.assertEqual(result['state'], 'plan-only')
        self.assertFalse(result['ready'])
        self.assertFalse(result['host_data_mounted'])

    def test_apply_requires_authorized_lab_before_install(self):
        with patch.object(sys, 'argv', ['stager', '--vm-uuid', observer.VM_UUID, '--apply']):
            with patch.object(observer, 'install', side_effect=AssertionError('installed')):
                with self.assertRaises(ValueError):
                    observer.main()


if __name__ == '__main__':
    unittest.main()
