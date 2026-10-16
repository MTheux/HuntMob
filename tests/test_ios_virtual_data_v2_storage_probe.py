"""Public tiny-file tests only. Never opens a lab backing or invokes a VM."""
import hashlib
import io
from contextlib import redirect_stdout
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import verify_ios_virtual_data_v2_storage_probe as probe
import ios_virtual_data_v2_contract as contract
import stage_ios_virtual_data_v2_cold_read as cold


class StorageProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.canary = bytes(range(32)).hex()
        self.expected = hashlib.sha256(self.canary.encode()).hexdigest()
        self.patterns = probe.probe_patterns(self.canary, self.expected)

    def tearDown(self):
        self.temp.cleanup()

    def scan(self, payload, chunk=17, patterns=None):
        path = self.root / "public.raw"
        path.write_bytes(payload)
        with probe.open_stable(path, len(payload)) as (fd, identity):
            return probe.scan_file(fd, path, identity, patterns or self.patterns, chunk_bytes=chunk)

    def test_both_patterns_cross_tiny_chunk_boundaries_and_full_hash(self):
        ascii_probe = self.patterns['ascii_hex64']
        binary = self.patterns['decoded32']
        payload = b'prefix!' + ascii_probe + b'X' * 13 + binary + b'end'
        result = self.scan(payload)
        self.assertEqual(result['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result['bytes_scanned'], len(payload))
        self.assertEqual(result['matches']['ascii_hex64']['offsets'], [7])
        self.assertEqual(result['matches']['decoded32']['offsets'], [84])
        self.assertEqual(result['identity_before'], result['identity_after'])

    def test_different_length_patterns_are_not_double_counted_in_overlap(self):
        result = self.scan(b'abcabcabcabc', chunk=2, patterns={'short': b'abc', 'long': b'abcabc'})
        self.assertEqual(result['matches']['short']['offsets'], [0, 3, 6, 9])
        self.assertEqual(result['matches']['long']['offsets'], [0, 3, 6])

    def test_overlapping_matches_and_offsets_are_bounded_but_count_complete(self):
        result = self.scan(b'A' * 100, chunk=7, patterns={'overlap': b'AAA'})
        self.assertEqual(result['matches']['overlap']['count'], 98)
        self.assertEqual(len(result['matches']['overlap']['offsets']), probe.MAX_OFFSETS)
        self.assertTrue(result['matches']['overlap']['offsets_truncated'])

    def test_absence_does_not_generate_crypto_readiness(self):
        result = self.scan(b'public harmless fixture' * 23)
        self.assertEqual(sum(v['count'] for v in result['matches'].values()), 0)
        self.assertNotIn('native_ready', result)
        self.assertNotIn('cryptography_validated', result)

    def test_empty_file_is_fully_hashed(self):
        self.assertEqual(self.scan(b'')['sha256'], hashlib.sha256(b'').hexdigest())

    def test_symlink_and_hardlink_refused(self):
        path = self.root / 'regular'; path.write_bytes(b'public')
        link = self.root / 'symlink'; link.symlink_to(path)
        with self.assertRaises(ValueError):
            with probe.open_stable(link):
                self.fail('symlink accepted')
        hard = self.root / 'hard'; os.link(path, hard)
        for candidate in (path, hard):
            with self.assertRaises(ValueError):
                with probe.open_stable(candidate):
                    self.fail('hardlink accepted')

    def test_same_size_content_mutation_during_scan_refused(self):
        path = self.root / 'mutable'; path.write_bytes(b'Q' * 127)
        original_read = os.read
        changed = False
        def mutate(fd, amount):
            nonlocal changed
            result = original_read(fd, amount)
            if not changed:
                changed = True
                with path.open('r+b') as writer:
                    writer.write(b'R')
                    writer.flush()
                    os.fsync(writer.fileno())
            return result
        with self.assertRaises(ValueError):
            with probe.open_stable(path) as (fd, identity):
                with patch.object(probe.os, 'read', side_effect=mutate):
                    probe.scan_file(fd, path, identity, self.patterns, chunk_bytes=9)

    def test_path_replacement_with_same_bytes_refused(self):
        path = self.root / 'replace'; path.write_bytes(b'public')
        with self.assertRaises(ValueError):
            with probe.open_stable(path) as (fd, identity):
                replacement = self.root / 'replacement'; replacement.write_bytes(b'public')
                os.replace(replacement, path)
                probe.scan_file(fd, path, identity, self.patterns)

    def test_truncate_during_scan_refused(self):
        path = self.root / 'truncate'; path.write_bytes(b'Q' * 90)
        original_read = os.read
        changed = False
        def mutate(fd, amount):
            nonlocal changed
            result = original_read(fd, amount)
            if not changed:
                changed = True
                with path.open('r+b') as writer:
                    writer.truncate(10)
            return result
        with self.assertRaises(ValueError):
            with probe.open_stable(path) as (fd, identity):
                with patch.object(probe.os, 'read', side_effect=mutate):
                    probe.scan_file(fd, path, identity, self.patterns, chunk_bytes=9)

    def test_pattern_digest_mismatch_refused_without_echo(self):
        with self.assertRaises(ValueError) as raised:
            probe.probe_patterns(self.canary, '0' * 64)
        self.assertNotIn(self.canary, str(raised.exception))
        with self.assertRaises(ValueError):
            probe.probe_patterns('x' * 64, self.expected)

    def test_attached_backing_path_and_alias_refused(self):
        path = self.root / 'namespace-1.raw'; path.write_bytes(b'public')
        probe.require_no_attached_backings(self.root, [path.name], [])
        with self.assertRaises(ValueError):
            probe.require_no_attached_backings(self.root, [path.name], [{'image-path': str(path)}])
        alias = self.root / 'alias'; alias.symlink_to(path)
        with self.assertRaises(ValueError):
            probe.require_no_attached_backings(self.root, [path.name], [{'image-path': str(alias)}])
        with self.assertRaises(ValueError):
            probe.require_no_attached_backings(self.root, [path.name], [{}])

    def test_receipt_exclusive_and_no_symlink_output(self):
        path = self.root / 'receipt.json'
        probe.write_json_exclusive(path, {'public': True})
        with self.assertRaises(FileExistsError):
            probe.write_json_exclusive(path, {'public': False})
        self.assertEqual(json.loads(path.read_text()), {'public': True})
        alias = self.root / 'alias'; alias.symlink_to(path)
        with self.assertRaises(FileExistsError):
            probe.write_json_exclusive(alias, {})

    def test_default_plan_performs_no_cohort_engine_inventory_or_probe_read(self):
        arguments = ['scanner', '--vm-uuid', '00112233-4455-4677-8899-aabbccddeeff']
        output = io.StringIO()
        with patch.object(sys, 'argv', arguments), redirect_stdout(output):
            with patch.object(probe.contract, 'validate_manifest', side_effect=AssertionError('cohort accessed')):
                with patch.object(probe.contract, 'verify_engine', side_effect=AssertionError('engine accessed')):
                    with patch.object(probe.preparation, 'image_inventory', side_effect=AssertionError('inventory accessed')):
                        with patch.object(probe, 'checked_creation', side_effect=AssertionError('probe accessed')):
                            probe.main()
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['state'], 'plan-only')
        self.assertFalse(plan['heavy_read_performed'])
        self.assertEqual(plan['historical_finding_status'], 'OPEN')
        self.assertFalse(plan['native_ready'])

    def test_heavy_read_without_explicit_authorization_refused_before_cohort_access(self):
        arguments = ['scanner', '--vm-uuid', '00112233-4455-4677-8899-aabbccddeeff', '--apply']
        with patch.object(sys, 'argv', arguments), patch.object(probe, 'scan_cohort', side_effect=AssertionError('scan accessed')):
            with self.assertRaises(ValueError):
                probe.main()

    def tiny_cohort(self, change_first=False):
        names = {name: 91 for name in probe.preparation.SIZES}
        for name in names:
            (self.root/name).write_bytes(b'Z' * 91)
        manifest = {'engine_binding': {'public_test': True}}
        (self.root/'virtual-profile.json').write_text(json.dumps(manifest))
        original_scan = probe.scan_file
        first_name = next(iter(names))
        last_name = list(names)[-1]
        def maybe_mutate(fd, path, identity, patterns, **kwargs):
            result = original_scan(fd, path, identity, patterns, **kwargs)
            if change_first and path.name == last_name:
                with (self.root/first_name).open('r+b') as stream:
                    stream.write(b'Q')
                    stream.flush()
                    os.fsync(stream.fileno())
            return result
        with patch.object(probe.preparation, 'SIZES', names), patch.object(probe.contract, 'target_for', return_value=self.root):
            with patch.object(probe.contract, 'validate_manifest', return_value=manifest), patch.object(probe.contract, 'verify_engine'):
                with patch.object(probe.preparation, 'image_inventory', return_value=[]), patch.object(probe.resource, 'setrlimit'):
                    with patch.object(probe, 'checked_creation', return_value=(self.patterns, {}, {})):
                        with patch.object(probe, 'scoped_cold_read', return_value={'validated': False}):
                            with patch.object(probe, 'scan_file', side_effect=maybe_mutate):
                                return probe.scan_cohort('00112233-4455-4677-8899-aabbccddeeff')

    def test_entire_nine_tiny_file_pipeline_preserves_finding_and_removes_owned_lock(self):
        result = self.tiny_cohort()
        self.assertEqual(result['total_bytes_scanned'], 9 * 91)
        self.assertTrue(result['public_probe_absent'])
        self.assertFalse(result['native_ready'])
        self.assertFalse(result['cryptography_validated_by_scan'])
        self.assertEqual(result['historical_finding_status'], 'OPEN')
        receipt = json.loads(Path(result['receipt_path']).read_text())
        self.assertEqual(len(receipt['backings']), 9)
        self.assertNotIn(self.canary, json.dumps(receipt))
        self.assertFalse((self.root/'.data-v2-launch.lock').exists())

    def test_global_snapshot_detects_prior_backing_change_while_later_file_scanned(self):
        with self.assertRaises(ValueError):
            self.tiny_cohort(change_first=True)
        self.assertFalse((self.root/'.data-v2-launch.lock').exists())
        receipts = list(self.root.glob('data-v2-storage-scan-*/receipt.json'))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(receipt['state'], 'failed-readonly-scan')
        self.assertFalse(receipt['native_ready'])

    def creation_fixture(self):
        directory = self.root / 'data-v2-observation-20261015-160837'; directory.mkdir()
        vm_id = '00112233-4455-4677-8899-aabbccddeeff'
        manifest = {'vm_uuid': vm_id, 'data_profile_sha256': contract.canonical_hash(contract.PROFILE),
                    'engine_binding': {'public_test': True}}
        log = '\n'.join(['HuntMob: ClassD initialization status=0',
                         'HuntMob virtual v1: fresh MKBCreateSystem returned zero',
                         'HuntMob: provisioning checkpoint ready; virtual v1 fresh protected Data prepared',
                         'HuntMob virtual v1: Class C roundtrip; synthetic canary=' + self.canary]) + '\n'
        trace = ('pci_nvme_apple_ans_protected_gate sqid=1 cid=2 stage=sq-context result=accepted\n'
                 'pci_nvme_apple_ans_complete sqid=1 cid=2 opcode=0x01 status=0x0000\n')
        (directory/'boot.log').write_text(log); (directory/'trace.log').write_text(trace)
        proof = {'schema': 'huntmob.virtual-sep-data-observation.v2', 'vm_uuid': vm_id,
                 'data_profile': contract.PROFILE, 'data_profile_sha256': manifest['data_profile_sha256'],
                 'engine_binding': manifest['engine_binding'], 'sep_profile': 'serving',
                 'qmp_quit_requested': True, 'qmp_quit_accepted': True, 'exit_code': 0,
                 'checkpoint_observed': True, 'panic_observed': False,
                 'virtual_mpe_memory_fault_observed': False, 'mpe_rejected_revocation_observed': False,
                 'stock_data_protection_verifier_invoked': True, 'aess_command_count': 1}
        for key in ('aess_rejected_command_count', 'nvme_error_completion_count',
                    'protected_io_rejection_count', 'protected_gate_rejection_count'):
            proof[key] = 0
        for key in ('auxiliary_bootstrap_requested', 'effaceable_ramdisk_requested', 'effaceable_observer_requested'):
            proof[key] = False
        for name in ('boot.log', 'trace.log'):
            proof[name + '_sha256'] = hashlib.sha256((directory/name).read_bytes()).hexdigest()
        (directory/'observation.json').write_text(json.dumps(proof))
        evidence = cold.creation_evidence(self.root, manifest, directory.name)
        manifest['cold_read_v2'] = {'creation_evidence': evidence, 'expected_probe_sha256': self.expected}
        return manifest, directory

    def test_creation_reads_hashed_fixture_once_and_excludes_canary_from_provenance(self):
        manifest, directory = self.creation_fixture()
        patterns, evidence, _ = probe.checked_creation(self.root, manifest)
        self.assertEqual(patterns, self.patterns)
        self.assertNotIn(self.canary, json.dumps(evidence))
        self.assertEqual(probe.scoped_cold_read(self.root, manifest)['validated'], False)

    def test_changed_creation_log_and_forged_source_digest_refused(self):
        manifest, directory = self.creation_fixture()
        (directory/'boot.log').write_text('changed public fixture\n')
        with self.assertRaises(ValueError):
            probe.checked_creation(self.root, manifest)

    def test_validated_flag_without_observed_native_result_never_accepted(self):
        manifest, _ = self.creation_fixture()
        manifest['post_keybag_v2'] = {'state': 'installed', 'read_validated': True}
        self.assertFalse(probe.scoped_cold_read(self.root, manifest)['validated'])
        manifest['post_keybag_v2']['state'] = 'observed'
        with self.assertRaises(ValueError):
            probe.scoped_cold_read(self.root, manifest)


if __name__ == '__main__':
    unittest.main()
