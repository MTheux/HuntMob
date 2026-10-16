import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('virtual_boot', SCRIPTS / 'boot_ios_virtual_profile.py')
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)


class VirtualBootTests(unittest.TestCase):
    def test_late_aess_failure_is_retained_after_metadata_bound(self):
        trace=('apple_sep_virtual_operation command=0x202 keydisable=0xb iterations=0 accepted=1\n'*300+
               'apple_sep_virtual_operation command=0x206 keydisable=0xb iterations=0 accepted=0\n')
        result=boot.virtual_memory_observations(trace)
        self.assertEqual(result['aess_command_count'],301)
        self.assertEqual(result['aess_rejected_command_count'],1)
        self.assertEqual(len(result['aess_commands']),256)
        self.assertEqual(result['aess_commands'][-1],{'command':0x206,'accepted':False})

    def test_memory_counters_and_jump_requests_remain_observations(self):
        result = boot.virtual_memory_observations(
            'apple_sep_virtual_mpe_memory_event action=written region=1 bytes=1048576\n'
            'apple_sep_virtual_mpe_memory_event action=written region=1 bytes=2097152\n'
            'apple_sep_virtual_mpe_memory_event action=initialized region=1 bytes=4096\n'
            'apple_sep_virtual_mpe_memory_event action=boot-jump-request region=1 bytes=0\n'
            'apple_sep_virtual_mpe_memory_event action=fault region=2 bytes=0\n')
        self.assertEqual(result['virtual_mpe_last_written_byte_counters'], {'1': 2097152})
        self.assertEqual(result['virtual_mpe_initialized_region_bytes'], {'1': 4096})
        self.assertTrue(result['virtual_mpe_memory_fault_observed'])
        self.assertTrue(result['virtual_mpe_boot_jump_requested'])
        self.assertFalse(result['virtual_mpe_guest_memory_validated'])

    def test_command_receipt_does_not_promote_control_ack_to_runtime_validation(self):
        result = boot.virtual_memory_observations(
            'apple_sep_virtual_operation command=0x211 keydisable=0x0 iterations=0 accepted=1\n'
            'apple_sep_virtual_operation command=0x251 keydisable=0x0 iterations=0 accepted=0\n'
            'apple_sep_virtual_mpe_control action=control reg=0x414 value=0x1 accepted=1\n'
            'apple_sep_virtual_mpe_control action=control reg=0x434 value=0x1 accepted=0\n')
        self.assertEqual(result['aess_commands'], [{'command': 0x211, 'accepted': True},
                                                   {'command': 0x251, 'accepted': False}])
        self.assertEqual(result['virtual_mpe_seal_commands_accepted'], [0])
        self.assertFalse(result['virtual_mpe_guest_memory_validated'])
        self.assertFalse(result['apple_mpe_equivalence'])

    def test_metadata_parser_never_copies_unrecognized_payloads(self):
        result = boot.virtual_memory_observations(
            'apple_sep_virtual_operation command=0x211 keydisable=0x0 iterations=0 accepted=1 payload=fixture\n'
            'apple_sep_virtual_mpe_control action=control reg=0x414 value=0x1 accepted=1\n' * 300)
        self.assertEqual(result['aess_commands'], [])
        self.assertEqual(len(result['virtual_mpe_controls']), 256)
        self.assertNotIn('fixture', json.dumps(result))

    def test_missing_identity_never_reads_keychain(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(boot, 'root_pipe') as delivery:
                with self.assertRaises(ValueError):
                    boot.validate(Path(root) / 'absent')
                delivery.assert_not_called()

    def test_symlink_profile_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'target'
            target.mkdir()
            link = Path(root) / 'alias'
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                boot.validate(link)

    def test_identity_cannot_be_rebound_to_different_path(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)
            (target / 'virtual-profile.json').write_text(json.dumps({
                'vm_uuid': '52c79047-1d89-4a97-bf6b-cc2d6b9d742c'}))
            with self.assertRaisesRegex(ValueError, 'identity do not match'):
                boot.validate(target)

    def test_keychain_delivery_uses_dedicated_pipe_not_secret_argument(self):
        from types import SimpleNamespace
        seen = []
        def invoke(command, **kwargs):
            seen.extend(command)
            fd = kwargs['pass_fds'][0]
            self.assertEqual(os.fstat(fd).st_mode & 0o170000, 0o010000)
            # Public fixture bytes only: test code may read these, launcher may not.
            os.write(fd, b'public fixture'.ljust(32, b'!'))
            return SimpleNamespace(returncode=0, stdout=b'{"status":"ok","delivered":true}', stderr=b'')
        with patch.object(boot.subprocess, 'run', side_effect=invoke):
            fd, status = boot.root_pipe('52c79047-1d89-4a97-bf6b-cc2d6b9d742c', True)
            try:
                self.assertEqual(len(os.read(fd, 33)), 32)
            finally:
                os.close(fd)
        self.assertIn('--create', seen)
        self.assertNotIn('public fixture', ' '.join(seen))
        self.assertTrue(status['delivered'])

    def test_lookup_failure_returns_no_pipe_for_emulator(self):
        from types import SimpleNamespace
        with patch.object(boot.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout=b'{"status":"missing","delivered":false}', stderr=b'')):
            with self.assertRaisesRegex(ValueError, 'refused'):
                boot.root_pipe('52c79047-1d89-4a97-bf6b-cc2d6b9d742c', False)


if __name__ == '__main__':
    unittest.main()
