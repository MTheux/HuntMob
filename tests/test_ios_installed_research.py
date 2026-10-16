import importlib.util
import sys
import tempfile
import socket
import threading
import json
import unittest
from pathlib import Path
from unittest.mock import patch


scripts = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location('installed_research', scripts / 'boot_ios_installed_research.py')
installed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installed)


class InstalledResearchTests(unittest.TestCase):
    def test_qmp_shutdown_handles_events_before_acknowledgements(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'owned.sock';requests=[]
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path));server.listen(1);server.settimeout(3)
                def respond():
                    client,_=server.accept()
                    with client:
                        client.settimeout(3);stream=client.makefile('rwb')
                        stream.write(b'{"QMP":{"version":{}}}\n');stream.flush()
                        for expected in ['qmp_capabilities','quit']:
                            command=json.loads(stream.readline())['execute'];requests.append(command)
                            stream.write(b'{"event":"STOP"}\n{"return":{}}\n');stream.flush()
                thread=threading.Thread(target=respond);thread.start()
                self.assertTrue(installed.quit_owned_vm(path))
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(requests,['qmp_capabilities','quit'])

    def test_missing_qmp_socket_cannot_claim_clean_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(installed.quit_owned_vm(Path(directory)/'absent.sock'))

    def test_sep_alive_does_not_establish_complete_boot(self):
        result=installed.boot_observations('SEP/OS is alive\nHuntMob: invoking stock Data Protection verifier\nBoot task failed: data-protection\npanic(cpu 5 caller ...)',False)
        self.assertTrue(result['sep_os_alive_observed'])
        self.assertEqual(result['validation_status'],'failed-data-protection')
        self.assertFalse(result['springboard_validated'])
        self.assertFalse(result['ipa_execution_validated'])

    def test_nonce_request_without_completion_is_incomplete(self):
        result=installed.boot_observations('SEP/OS is alive\nHuntMob: stock normal SEP nonce initialization',True)
        self.assertFalse(result['normal_nonce_init_completed_observed'])
        self.assertEqual(result['validation_status'],'observation-time-limit')

    def test_persistent_provisioning_rejects_hardlinked_source_disks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent=root/'ios-vms/native-20261013-215607';parent.mkdir(parents=True)
            target=root/'ios-vms/native-test-restore-preload';target.mkdir()
            for name in [f'namespace-{n}.raw' for n in range(1,8)]+['sep-nvram.raw','sep-ssc.raw']:
                (parent/name).write_bytes(b'original');(target/name).write_bytes(b'clone')
            receipt={'parent_clone':str(parent)}
            with patch.object(installed,'RESEARCH',root):
                installed.validate_provisioning_clone(target,receipt,'restore-preload')
                (target/'namespace-1.raw').unlink()
                import os
                os.link(parent/'namespace-1.raw',target/'namespace-1.raw')
                with self.assertRaisesRegex(SystemExit,'backing file'):
                    installed.validate_provisioning_clone(target,receipt,'restore-preload')
                self.assertEqual((parent/'namespace-1.raw').read_bytes(),b'original')

    def test_debugger_run_length_and_escape_decoding(self):
        self.assertEqual(installed.decode_rsp(b'0* '), '0000')
        self.assertEqual(installed.decode_rsp(b'}\x03'), '#')
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            installed.decode_rsp(b'0*')
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            installed.decode_rsp(b'* ')

    def test_disk_boot_selects_serving_firmware_without_changing_other_options(self):
        restore = installed.RESEARCH / 'firmware/sep-firmware.n104.RELEASE.new.img4'
        machine = f't8030,sep-fw={restore},kaslr-off=true'
        with patch.object(installed, 'digest', return_value=installed.NORMAL_SEP_SHA):
            result = installed.normal_sep_machine(machine)
        self.assertEqual(result, f't8030,sep-fw={installed.RESEARCH}/firmware/sep-firmware.n104.serving.img4,kaslr-off=true')

    def test_unverified_serving_firmware_blocks_boot(self):
        with patch.object(installed, 'digest', return_value='different'):
            with self.assertRaisesRegex(SystemExit, 'Pinned serving'):
                installed.normal_sep_machine('t8030')

    def test_encrypted_lab_profile_is_explicit_and_pinned(self):
        filename, expected = installed.SEP_PROFILES['encrypted-lab']
        restore = installed.RESEARCH / 'firmware/sep-firmware.n104.RELEASE.new.img4'
        with patch.object(installed, 'digest', return_value=expected):
            result = installed.normal_sep_machine(f't8030,sep-fw={restore}', 'encrypted-lab')
        self.assertEqual(result, f't8030,sep-fw={installed.RESEARCH}/firmware/{filename}')
        with patch.object(installed, 'digest', return_value=installed.NORMAL_SEP_SHA):
            with self.assertRaisesRegex(SystemExit, 'Pinned serving'):
                installed.normal_sep_machine(f't8030,sep-fw={restore}', 'encrypted-lab')

    def test_unexpected_launch_configuration_blocks_boot(self):
        with patch.object(installed, 'digest', return_value=installed.NORMAL_SEP_SHA):
            with self.assertRaisesRegex(SystemExit, 'Unexpected SEP'):
                installed.normal_sep_machine('t8030,sep-fw=unverified')
