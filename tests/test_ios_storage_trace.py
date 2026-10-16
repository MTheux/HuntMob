import importlib.util
import sys
import tempfile
import unittest
import hashlib
import json
import subprocess
from unittest.mock import patch
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('ios_storage_trace', SCRIPTS / 'trace_ios_storage_research.py')
trace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trace)


class StorageTraceTests(unittest.TestCase):
    def test_context_requests_do_not_validate_derivation_or_handoff(self):
        result = trace.trace_summary(
            'apple_sep_derivation_readiness phase=program-request role=wrapping validated=0\n'
            'apple_sep_derivation_readiness phase=unsupported-derive role=wrapping validated=0\n'
            'apple_sep_derivation_readiness phase=program-request role=authentication validated=0\n'
            'apple_sep_derivation_readiness phase=unsupported-derive role=authentication validated=0\n'
            'apple_sep_derivation_readiness phase=latch-request role=wrapping validated=0\n'
            'apple_sep_derivation_readiness phase=latch-request role=subkey validated=0\n')
        self.assertEqual(result['sep_context_readiness_requests'], {
            'program-request:wrapping': 1, 'unsupported-derive:wrapping': 1,
            'program-request:authentication': 1, 'unsupported-derive:authentication': 1,
            'latch-request:wrapping': 1, 'latch-request:subkey': 1})
        self.assertEqual(result['sep_context_untrusted_readiness_records'], 0)
        self.assertFalse(result['sep_context_derivation_validated'])
        self.assertFalse(result['ready'])

    def test_context_trace_rejects_claimed_validation_and_noncanonical_fields(self):
        result = trace.trace_summary(
            'apple_sep_derivation_readiness phase=latch-request role=wrapping validated=1\n'
            'apple_sep_derivation_readiness phase=DO_NOT_EXPORT role=wrapping validated=0\n'
            'apple_sep_derivation_readiness phase=latch-request role=DO_NOT_EXPORT validated=0\n'
            'apple_sep_derivation_readiness phase=latch-request role=wrapping validated=0 input=DO_NOT_EXPORT\n'
            'apple_sep_derivation_readiness phase=latch-request role=wrapping validated=00\n')
        self.assertEqual(result['sep_context_readiness_requests'], {})
        self.assertEqual(result['sep_context_untrusted_readiness_records'], 5)
        self.assertNotIn('DO_NOT_EXPORT', str(result))
        self.assertFalse(result['sep_context_derivation_validated'])
        self.assertFalse(result['data_protection_validated'])

    def test_added_untracked_codec_change_invalidates_compiled_candidate(self):
        import build_ios_research_engine as builder
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            (source / 'crypto').mkdir(parents=True)
            subprocess.run(['git', 'init', '-q'], cwd=source, check=True, capture_output=True)
            codec = source / 'crypto/apple-ans-wrapped.c'
            codec.write_text('reviewed codec\n')
            component = root / 'patches'
            component.mkdir()
            (component / 'fixture.patch').write_text(
                'diff --git a/crypto/apple-ans-wrapped.c b/crypto/apple-ans-wrapped.c\n')
            (component / 'upstream.json').write_text(json.dumps({'revision': 'fixture'}))
            (root / 'build').mkdir()
            binary = root / 'build/qemu-system-aarch64'
            binary.write_bytes(b'not executed')
            with patch.object(builder, 'COMPONENT', component), \
                 patch.object(trace, 'COMPONENT', component), \
                 patch.object(trace, 'PATCHES', ('fixture.patch',)), \
                 patch.object(trace, 'require_data_protection'):
                receipt = {
                    'state': 'compiled', 'ready': False, 'purpose': 'storage-protocol-research',
                    'revision': 'fixture', 'data_protection_source_enabled': True,
                    'patch_sha256': {'fixture.patch': trace.digest(component / 'fixture.patch')},
                    'binary_sha256': trace.digest(binary),
                    'reviewed_source_sha256': builder.reviewed_sources(source, ('fixture.patch',)),
                    'source_diff_sha256': hashlib.sha256(b'').hexdigest(),
                }
                (root / 'build-receipt.json').write_text(json.dumps(receipt))
                # An added file is absent from a normal git diff; the explicit
                # source map must still detect its post-build modification.
                codec.write_text('unreviewed modified codec\n')
                self.assertEqual(subprocess.check_output(['git', 'diff', '--binary'], cwd=source), b'')
                with self.assertRaisesRegex(ValueError, 'Reviewed source changed'):
                    trace.validate_candidate(root)

    def test_ap_aes_and_keyline_metadata_never_export_unknown_payloads(self):
        result = trace.trace_summary(
            'apple_aes_key_mode mode=software-wrapped disabled=0\n'
            'apple_aes_key_mode mode=DO_NOT_EXPORT disabled=0\n'
            'apple_aes_key_mode mode=software-wrapped-secret disabled=0\n'
            'apple_aes_data_rejected reason=disabled-key\n'
            'apple_aes_cipher_result result=0\n'
            'apple_aes_process_command op 0x1\n'
            'apple_sep_keyline_request operation=send active=1\n'
            'apple_sep_keyline_request operation=DO_NOT_EXPORT active=1\n'
            'apple_sep_key_control_category category=seed\n'
            'apple_sep_key_control_category category=wrapping-select\n'
            'apple_sep_key_control_category category=DO_NOT_EXPORT\n')
        self.assertEqual(result['ap_aes_key_modes'], {'software-wrapped:disabled=0': 1})
        self.assertEqual(result['ap_aes_rejections'], {'disabled-key': 1})
        self.assertEqual(result['ap_aes_cipher_results'], {'0': 1})
        self.assertEqual(result['ap_aes_opcodes'], {'0x1': 1})
        self.assertEqual(result['sep_keyline_requests'], {'send:active=1': 1})
        self.assertEqual(result['sep_key_control_categories'], {'seed': 1, 'wrapping-select': 1})
        self.assertNotIn('DO_NOT_EXPORT', str(result))
        self.assertFalse(result['data_protection_validated'])

    def test_successful_dma_completion_cannot_validate_crypto(self):
        result = trace.trace_summary(
            '42@1.2:pci_nvme_apple_ans_submit sqid=1 cid=3 opcode=0x01 nsid=1\n'
            '42@1.3:pci_nvme_apple_ans_complete sqid=1 cid=3 opcode=0x01 status=0x0000\n')
        self.assertEqual(result['submission_opcodes'], {'io:0x01': 1})
        self.assertEqual(result['completion_statuses'], {'0x0000': 1})
        self.assertFalse(result['ready'])
        self.assertFalse(result['data_protection_validated'])

    def test_stub_markers_and_sep_transfers_are_distinct_from_crypto(self):
        result = trace.trace_summary(
            'pci_nvme_apple_ans_admin_unimplemented sqid=0 cid=4 opcode=0xd8\n'
            'apple_sep_key_transfer_unimplemented endpoint=0x14 size=4\n')
        self.assertEqual(result['unimplemented_admin_opcodes'], {'0xd8': 1})
        self.assertEqual(result['sep_transfer_endpoints'], {'0x14': 1})
        self.assertFalse(result['data_protection_validated'])

    def test_unknown_or_raw_lines_cannot_leak_into_report(self):
        result = trace.trace_summary('private-log-value=DO_NOT_EXPORT\n')
        self.assertNotIn('DO_NOT_EXPORT', str(result))
        self.assertFalse(result['ready'])

    def test_sep_approximation_and_backing_errors_are_metadata_not_validation(self):
        result = trace.trace_summary(
            'apple_sep_aess_uid_wrap_approximation upstream CBC UID-wrap approximation called\n'
            'apple_sep_aess_operation operation=uid-wrap\n'
            'apple_sep_aess_complete invalid_parameters=1\n'
            'apple_sep_ssc_command operation=0x06\n'
            'apple_sep_ssc_backing_io operation=0x06 write=0 bytes=64 result=-5\n')
        self.assertEqual(result['aess_operation_categories'], {'uid-wrap': 1})
        self.assertEqual(result['aess_invalid_parameter_completions'], 1)
        self.assertEqual(result['ssc_backing_return_codes'], {'-5': 1})
        self.assertEqual(result['ssc_backing_operations'], {'0x06:read': 1})
        self.assertFalse(result['data_protection_validated'])

    def test_protected_io_rejection_never_claims_encryption_implemented(self):
        result = trace.trace_summary(
            'pci_nvme_apple_ans_protected_io_rejected sqid=1 cid=5 opcode=0x01 mode=1 unsupported crypto; I/O rejected\n'
            'pci_nvme_apple_ans_protected_io_rejected sqid=1 cid=6 opcode=0x02 mode=2 unsupported crypto; I/O rejected\n')
        self.assertEqual(result['protected_io_rejected_modes'], {'1': 1, '2': 1})
        self.assertFalse(result['ready'])
        self.assertFalse(result['data_protection_validated'])

    def test_arbitrary_prepared_clone_cannot_be_booted(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with self.assertRaisesRegex(ValueError, 'outside'):
                trace.prepared_clone(folder)
            self.assertEqual(list(folder.iterdir()), [])

    def test_nonobject_or_oversized_receipts_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt'
            path.write_text('[]')
            with self.assertRaises(ValueError):
                trace.read_json(path)
            path.write_bytes(b'x' * 65537)
            with self.assertRaises(ValueError):
                trace.read_json(path)

    def test_existing_lab_cannot_be_used_as_trace_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / 'owned'
            checkpoint.mkdir()
            with self.assertRaisesRegex(ValueError, 'owned synthetic'):
                trace.clone_checkpoint(checkpoint, checkpoint)
            self.assertEqual(list(checkpoint.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
