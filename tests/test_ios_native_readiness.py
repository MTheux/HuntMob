import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from huntmob import ios_native_readiness as readiness


class NativeReadinessTests(unittest.TestCase):
    def scoped_snapshot(self, *, tamper=False, promote=False, missing=False, inconsistent=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = {'vm_uuid': '9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4', 'engine_binding': {'binary_sha256': 'a' * 64}}
            cold = {**shared, 'schema': 'huntmob.ios-own-data-v2-native-cold-read.v1',
                    'data_profile': {'id': 'huntmob.virtual-data.v2', 'hardware_equivalent': False},
                    'persistent_ClassC_probe_read_validated': True, 'same_existing_probe_class': 3,
                    'existing_probe_bytes': 64, 'AFU_before_after': [1, 1],
                    'native_stock_keybag_init_exit': 0, 'native_stock_keybag_init_signal': 0,
                    'metadata_valid': True, 'read_complete': True, 'digest_match': True,
                    'native_ready': False, 'historical_plaintext_finding': 'open'}
            boot = {**shared, 'schema': 'huntmob.ios.own-data-v2.normal-boot.v1',
                    'binary_sha256': 'a' * 64, 'data_profile': dict(cold['data_profile']),
                    'stock_early_boot_marker_observed': True, 'panic_observed': False,
                    'own_checkpoint_unexpected': False, 'qmp_quit_accepted': True, 'exit_code': 0,
                    'ready': promote, 'native_ready': False, 'springboard_validated': False, 'ipa_execution_validated': False}
            if inconsistent == 'missing-engine':
                cold.pop('engine_binding'); boot.pop('engine_binding')
            elif inconsistent == 'promoted-cold':
                cold['ready'] = True
            elif inconsistent == 'foreign-profile':
                boot['data_profile']['hardware_equivalent'] = True
            evidence = {}
            for name, value in (('native-cold-read', cold), ('normal-boot', boot)):
                path = root / ('ios-own-data-v2-' + name + '-v1-2026-10-15.json')
                data = json.dumps(value).encode(); path.write_bytes(data)
                evidence[path.name] = hashlib.sha256(data).hexdigest()
            if tamper:
                path.write_text('{}')
            if missing:
                path.unlink()
            # A prior failure stays on disk and cannot override later scoped evidence.
            (root / 'ios-native-runtime-status-v1-2026-10-15.json').write_text(json.dumps(
                {'version': 1, 'date': '2026-10-15', 'data_protection_disabled': False,
                 'current_blocker': 'sep-ans-context-derivation-unvalidated'}))
            (root / 'ios-native-runtime-status-v2-2026-10-15.json').write_text(json.dumps(
                {'version': 2, 'date': '2026-10-15', 'data_protection_disabled': False,
                 'evidence_sha256': evidence, 'ready': True, 'reason': 'PRIVATE_LOG'}))
            with patch.object(readiness, 'REPORTS', root):
                return readiness.snapshot()

    def test_scoped_probe_and_early_boot_advance_without_claiming_full_protection_or_ui(self):
        result = self.scoped_snapshot()
        self.assertFalse(result['ready'])
        self.assertFalse(result['data_protection_complete_validated'])
        self.assertEqual(result['stages'][2]['state'], 'observed')
        self.assertIn('Class C', result['stages'][2]['label'])
        self.assertEqual(result['stages'][3]['state'], 'blocked')
        self.assertEqual(result['stages'][4]['state'], 'pending')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_changed_or_missing_scoped_evidence_cannot_advance_progress(self):
        for options in ({'tamper': True}, {'missing': True}, {'promote': True}):
            result = self.scoped_snapshot(**options)
            self.assertFalse(result['ready'])
            self.assertEqual(result['state'], 'unavailable')
            self.assertTrue(all(stage['state'] == 'pending' for stage in result['stages']))

    def test_inconsistent_receipts_cannot_advance_milestones_even_with_matching_file_hashes(self):
        for case in ('missing-engine', 'promoted-cold', 'foreign-profile'):
            result = self.scoped_snapshot(inconsistent=case)
            self.assertFalse(result['ready'])
            self.assertEqual(result['state'], 'unavailable')

    def snapshot(self, report):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'ios-native-runtime-status-v1-2026-10-14.json').write_text(json.dumps(report))
            with patch.object(readiness,'REPORTS',root):
                return readiness.snapshot()

    def test_research_receipt_cannot_advertise_usable_runtime(self):
        result=self.snapshot({'version':1,'date':'2026-10-14','data_protection_disabled':False,
            'stock_verifier_invoked':True,'sep_restore_os_alive_observed':True,
            'ready':True,'springboard_validated':True,'ipa_execution_validated':True,
            'reason':'PRIVATE_LOG','command':['PRIVATE_COMMAND']})
        self.assertFalse(result['ready'])
        self.assertEqual(result['state'],'blocked')
        self.assertEqual(result['stages'][1]['state'],'observed')
        self.assertEqual(result['stages'][2]['state'],'blocked')
        self.assertEqual(result['stages'][3]['state'],'pending')
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_disabled_or_unknown_protection_is_not_accepted_as_evidence(self):
        for flag in [True,None,'false']:
            result=self.snapshot({'version':1,'date':'2026-10-14','data_protection_disabled':flag})
            self.assertEqual(result['state'],'unavailable')
            self.assertIsNone(result['last_validation'])

    def test_plaintext_storage_failure_overrides_claimed_protection_success(self):
        result=self.snapshot({'version':1,'date':'2026-10-14','data_protection_disabled':False,
            'current_blocker':'persisted-probe-plaintext-storage',
            'data_protection_functional_validated':True,'ready':True})
        self.assertFalse(result['ready'])
        self.assertEqual(result['stages'][2]['state'],'blocked')
        self.assertIn('falhou',result['summary'])

    def test_no_report_has_no_observed_milestones(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(readiness,'REPORTS',Path(directory)):
            result=readiness.snapshot()
        self.assertTrue(all(stage['state']=='pending' for stage in result['stages']))

    def test_context_lifecycle_tests_cannot_promote_native_derivation(self):
        result=self.snapshot({'version':1,'date':'2026-10-15','data_protection_disabled':False,
            'current_blocker':'sep-ans-context-derivation-unvalidated',
            'synthetic_context_lifecycle_validated':True,'ready':True,
            'springboard_validated':True,'ipa_execution_validated':True})
        self.assertIn('SEP/ANS',result['summary'])
        self.assertEqual(result['last_validation'],'15/10/2026')
        self.assertFalse(result['ready'])
        self.assertEqual(result['stages'][2]['state'],'blocked')
        self.assertEqual(result['stages'][3]['state'],'pending')
        self.assertEqual(result['stages'][4]['state'],'pending')

    def test_malformed_report_is_a_visible_unavailable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'ios-native-runtime-status-v1-2026-10-14.json').write_text('{broken')
            with patch.object(readiness,'REPORTS',root):result=readiness.snapshot()
        self.assertFalse(result['ready'])
        self.assertEqual(result['state'],'unavailable')
