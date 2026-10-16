"""Public tiny-file tests only. Never touches Keychain, host disks or a VM."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_data_v2 as prepare
import boot_ios_virtual_data_v2 as boot

VM_ID = "9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"


def binding():
    sources = {"crypto/huntmob-virtual-sep.c": "a" * 64}
    return {"binary_sha256": "b" * 64, "build_receipt_sha256": "c" * 64,
            "data_v2_patch_sha256": "d" * 64, "reviewed_source_sha256": sources,
            "reviewed_sources_sha256": contract.canonical_hash(sources)}


class DataV2Guards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="huntmob-data-v2-public-")
        self.root = Path(self.temporary.name)
        self.patches = [patch.object(contract, "VM_ROOT", self.root),
                        patch.object(prepare.preparation, "VM_ROOT", self.root),
                        patch.object(prepare.preparation, "SIZES", {f"namespace-{n}.raw": 16 for n in range(1, 8)} |
                                     {"sep-nvram.raw": 16, "sep-ssc.raw": 16})]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def fresh(self):
        with patch.object(prepare.preparation, "check_parent"), \
             patch.object(prepare.preparation.shutil, "disk_usage", return_value=Mock(free=32 * 1024**3)), \
             patch.object(contract, "engine_binding", return_value=binding()), \
             patch.object(prepare.preparation, "validate_sources", return_value={}):
            value = prepare.create(VM_ID, "b" * 64)
        return contract.target_for(VM_ID), value

    def test_plan_creates_nothing_or_executes_no_process(self):
        for module in (prepare, boot):
            with self.subTest(module=module.__name__), \
                 patch("sys.argv", [module.__file__, "--vm-uuid", VM_ID]), \
                 patch.object(boot.subprocess, "run", side_effect=AssertionError("no process")), \
                 patch.object(boot.subprocess, "Popen", side_effect=AssertionError("no VM")), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                module.main()
                result = json.loads(output.getvalue())
                self.assertTrue(result["read_only"])
                self.assertFalse(result["root_accessed"])
                self.assertFalse(result["vm_started"])
                self.assertFalse(result["native_ready"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_apply_requires_authorized_flag_before_mutation(self):
        for module in (prepare, boot):
            with self.subTest(module=module.__name__), patch("sys.argv", [module.__file__, "--vm-uuid", VM_ID, "--apply"]):
                with self.assertRaisesRegex(ValueError, "requires"):
                    module.main()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_post_keybag_mode_cannot_mix_with_a_provisioning_or_early_probe(self):
        for other in ("effaceable_ramdisk", "auxiliary_bootstrap", "effaceable_observer", "cold_class_c_read",
                      "factorydata_seed", "update_volume_bootstrap", "normal_boot", "ui_process_observer"):
            with self.subTest(other=other), \
                 patch.object(contract, "validate_manifest", side_effect=AssertionError("no manifest access")), \
                 patch.object(boot.legacy, "root_pipe", side_effect=AssertionError("no Keychain access")), \
                 self.assertRaisesRegex(ValueError, "mutually exclusive"):
                boot.validate_boot(self.root, create_root=False, sep_profile="serving",
                                   post_keybag_class_c_read=True, **{other: True})

    def test_factorydata_seed_cannot_share_a_boot_with_any_other_provisioning_mode(self):
        for other in ("effaceable_ramdisk", "auxiliary_bootstrap", "effaceable_observer", "cold_class_c_read",
                      "post_keybag_class_c_read", "update_volume_bootstrap", "normal_boot", "ui_process_observer"):
            with self.subTest(other=other), \
                 patch.object(contract, "validate_manifest", side_effect=AssertionError("no backing access")), \
                 self.assertRaisesRegex(ValueError, "mutually exclusive"):
                boot.validate_boot(self.root, create_root=False, sep_profile="serving",
                                   factorydata_seed=True, **{other: True})

    def test_update_bootstrap_cannot_share_a_boot_with_any_other_mode(self):
        for other in ("effaceable_ramdisk", "auxiliary_bootstrap", "effaceable_observer", "cold_class_c_read",
                      "post_keybag_class_c_read", "factorydata_seed", "normal_boot", "ui_process_observer"):
            with self.subTest(other=other), \
                 patch.object(contract, "validate_manifest", side_effect=AssertionError("no backing access")), \
                 self.assertRaisesRegex(ValueError, "mutually exclusive"):
                boot.validate_boot(self.root, create_root=False, sep_profile="serving",
                                   update_volume_bootstrap=True, **{other: True})

    def test_normal_boot_cannot_mix_with_an_initializer_or_probe(self):
        for other in ("effaceable_ramdisk", "auxiliary_bootstrap", "effaceable_observer", "cold_class_c_read",
                      "post_keybag_class_c_read", "factorydata_seed", "update_volume_bootstrap", "ui_process_observer"):
            with self.subTest(other=other), \
                 patch.object(contract, "validate_manifest", side_effect=AssertionError("no backing access")), \
                 self.assertRaisesRegex(ValueError, "mutually exclusive"):
                boot.validate_boot(self.root, create_root=False, sep_profile="serving",
                                   normal_boot=True, **{other: True})

    def test_ui_process_observer_requires_an_independent_exact_bounded_boot(self):
        for other in ("effaceable_ramdisk", "auxiliary_bootstrap", "effaceable_observer", "cold_class_c_read",
                      "post_keybag_class_c_read", "factorydata_seed", "update_volume_bootstrap", "normal_boot"):
            with self.subTest(other=other), \
                 patch.object(contract, "validate_manifest", side_effect=AssertionError("no backing access")), \
                 self.assertRaisesRegex(ValueError, "mutually exclusive"):
                boot.validate_boot(self.root, create_root=False, sep_profile="serving",
                                   ui_process_observer=True, **{other: True})
        with patch.object(boot.legacy, "root_pipe", side_effect=AssertionError("no Keychain")):
            for seconds, hz in ((180, 10), (240, 0), (241, 10)):
                with self.subTest(seconds=seconds, hz=hz), self.assertRaises(ValueError):
                    boot.boot(self.root, seconds, False, "serving", ui_process_observer=True, headless_refresh_hz=hz)

    def test_post_keybag_plan_is_explicit_and_does_not_launch_or_attach(self):
        with patch("sys.argv", [boot.__file__, "--vm-uuid", VM_ID, "--sep-profile", "serving",
                                "--post-keybag-class-c-read"]), \
             patch.object(boot.subprocess, "Popen", side_effect=AssertionError("no VM")), \
             patch.object(boot.legacy, "root_pipe", side_effect=AssertionError("no Keychain")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            boot.main()
        result = json.loads(output.getvalue())
        self.assertTrue(result["post_keybag_class_c_read_requested"])
        self.assertFalse(result["cold_class_c_read_requested"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["native_ready"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fresh_files_are_separate_zeroed_identity_and_unpromoted(self):
        target, value = self.fresh()
        self.assertTrue(target.name.startswith("virtual-sep-data-v2-"))
        self.assertEqual(value["schema"], contract.SCHEMA)
        self.assertEqual(value["identity_schema"], contract.IDENTITY_SCHEMA)
        self.assertEqual(value["data_profile"], contract.PROFILE)
        self.assertEqual(value["keychain_account"], VM_ID)
        self.assertFalse(value["root_provisioned"])
        self.assertFalse(value["native_ready"])
        self.assertEqual(len(value["backings"]), 9)
        self.assertEqual(len({v["inode"] for v in value["backings"].values()}), 9)
        for name in value["backings"]:
            self.assertEqual((target / name).read_bytes(), bytes(16))
        with self.assertRaises(ValueError):
            contract.require_new_identity(VM_ID)

    def test_existing_v1_uuid_and_root_account_never_reused(self):
        old = self.root / ("virtual-sep-v1-" + VM_ID)
        old.mkdir()
        with self.assertRaisesRegex(ValueError, "already belongs"):
            contract.require_new_identity(VM_ID)
        old.rmdir()
        old = self.root / "other-public-name"
        old.mkdir()
        (old / "virtual-profile.json").write_text(json.dumps({"keychain_account": VM_ID}))
        with self.assertRaisesRegex(ValueError, "already used"):
            contract.require_new_identity(VM_ID)

    def test_wrong_schema_format_kdf_and_engine_fingerprint_are_refused(self):
        target, baseline = self.fresh()
        for key, value in (("schema", contract.IDENTITY_SCHEMA), ("kdf_id", "unknown"),
                           ("data_profile_sha256", "f" * 64), ("ready", True), ("native_ready", True)):
            modified = copy.deepcopy(baseline)
            modified[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                contract.validate_manifest(target, modified)
        modified = copy.deepcopy(baseline)
        modified["data_profile"]["formats"] = ["0x0001b140"]
        with self.assertRaises(ValueError):
            contract.validate_manifest(target, modified)
        modified = copy.deepcopy(baseline)
        modified["engine_binding"]["reviewed_source_sha256"]["crypto/huntmob-virtual-sep.c"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "source map"):
            contract.validate_manifest(target, modified)

    def test_backing_hardlink_symlink_resize_and_active_qmp_are_refused(self):
        target, value = self.fresh()
        selected = target / "sep-nvram.raw"
        selected.write_bytes(bytes(17))
        with self.assertRaisesRegex(ValueError, "geometry"):
            contract.validate_manifest(target, value)
        selected.write_bytes(bytes(16))
        selected.unlink()
        selected.symlink_to(target / "sep-ssc.raw")
        with self.assertRaises(ValueError):
            contract.validate_manifest(target, value)
        selected.unlink()
        os.link(target / "sep-ssc.raw", selected)
        with self.assertRaises(ValueError):
            contract.validate_manifest(target, value)

    def test_duplicate_json_and_symlink_manifest_are_refused(self):
        path = self.root / "metadata.json"
        path.write_text('{"schema":"a","schema":"b"}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            contract.read_metadata(path)
        alias = self.root / "alias.json"
        alias.symlink_to(path)
        with self.assertRaises(ValueError):
            contract.read_metadata(alias)

    def test_short_socket_launch_lock_blocks_host_adapters_until_resolved(self):
        target, value = self.fresh()
        path = target / ".data-v2-launch.lock"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with self.assertRaisesRegex(ValueError, "launch is active"):
                contract.validate_manifest(target, value)
            contract.validate_manifest(target, value, owned_launch_lock=fd)
            other = self.root / "other-lock"
            other.write_bytes(b"public fixture")
            other_fd = os.open(other, os.O_RDONLY)
            try:
                with self.assertRaisesRegex(ValueError, "exclusive lock"):
                    contract.validate_manifest(target, value, owned_launch_lock=other_fd)
            finally:
                os.close(other_fd)
        finally:
            os.close(fd)
            path.unlink()
        contract.validate_manifest(target, value)

    def test_stale_engine_is_never_rebound(self):
        target, value = self.fresh()
        changed = binding()
        changed["binary_sha256"] = "f" * 64
        with patch.object(contract, "engine_binding", return_value=changed), \
             self.assertRaisesRegex(ValueError, "silently rebind"):
            contract.verify_engine(value)

    def test_restore_refuses_any_provisioned_identity_before_host_or_filesystem_access(self):
        target, value = self.fresh()
        value["root_provisioned"] = True
        with patch.object(prepare.preparation, "image_inventory", side_effect=AssertionError("no host access")), \
             self.assertRaisesRegex(ValueError, "never-booted"):
            prepare.restore(target, value)

    def test_launch_gates_fail_before_keychain_for_incomplete_staging_and_auxiliary(self):
        target, value = self.fresh()
        with patch.object(contract, "verify_engine", return_value=self.root / "public-engine"), \
             patch.object(boot.legacy, "root_pipe", side_effect=AssertionError("no keychain")):
            with self.assertRaisesRegex(ValueError, "host staging"):
                boot.validate_boot(target, create_root=True, sep_profile="restore")
            value.update(restore_completed=True, owned_device_detached=True, v2_staging_complete=True,
                         host_staging_complete=True, stock_files_staged=True, private_artifact_absence_checked=True,
                         mnt2_empty_directory_verified=True,
                         virtual_staging={"phase": "restore-checkpoint", "stock_verifier_preserved": True,
                                          "stock_seputil_unchanged": True})
            with patch.object(contract, "validate_manifest", return_value=value):
                with self.assertRaisesRegex(ValueError, "auxiliary APFS"):
                    boot.validate_boot(target, create_root=True, sep_profile="restore")
                with self.assertRaisesRegex(ValueError, "bootstrap adapter"):
                    boot.validate_boot(target, create_root=True, sep_profile="restore", auxiliary_bootstrap=True)

    def test_machine_property_exact_v2_and_uuid_without_secret_bytes(self):
        target, _ = self.fresh()
        generic = ["public-engine", "-M", "t8030,usb-conn-addr=" + str(target / "usb.sock"),
                   "-qmp", "unix:" + str(target / "qmp.sock") + ",server=on,wait=off",
                   "-initrd", "public-ramdisk", "-snapshot"]
        with patch.object(boot, "command", return_value=generic), \
             patch.object(boot, "normal_sep_machine", side_effect=lambda machine, profile: machine + ",sep=" + profile):
            launch = boot.launch_command("public-engine", target, {}, VM_ID, "restore", False, Path("/tmp/hm-v2-public"))
        machine = launch[launch.index("-M") + 1]
        self.assertIn(",huntmob-virtual-data-profile=v2", machine)
        self.assertIn(",huntmob-virtual-sep-vm-id=" + VM_ID, machine)
        self.assertIn(",sep=restore-preload", machine)
        self.assertNotIn("-snapshot", launch)
        self.assertNotIn("-initrd", launch)
        self.assertNotIn("-object", launch)
        self.assertEqual(launch[launch.index("-qmp") + 1], "unix:/tmp/hm-v2-public/qmp.sock,server=on,wait=off")
        self.assertIn("usb-conn-addr=/tmp/hm-v2-public/usb.sock", machine)

    def boot_public_fixture(self, *, qmp=True, fault=False, revoke=False, exit_code=0, drain_events=""):
        target, value = self.fresh()
        value["virtual_staging"] = {"phase": "restore-checkpoint"}
        events = ""
        if fault:
            events += "apple_sep_virtual_mpe_memory_event action=fault region=2 bytes=0\n"
        if revoke:
            events += "apple_sep_virtual_mpe_control action=revoked reg=0x414 value=0x1 accepted=0\n"
        class PublicProcess:
            returncode = None
            def __init__(self, argv, **kwargs):
                self.directory = kwargs["cwd"]
                kwargs["stdout"].write(b"HuntMob: provisioning checkpoint ready; virtual v1 stock SEP restore prepared\n")
                kwargs["stdout"].flush()
                (kwargs["cwd"] / "trace.log").write_text(events)
            def poll(self):
                return self.returncode
            def wait(self, timeout):
                if drain_events:
                    with (self.directory / "trace.log").open("a") as trace:
                        trace.write(drain_events)
                self.returncode = exit_code
            def terminate(self):
                self.returncode = -15
            def kill(self):
                self.returncode = -9
        def public_pipe(vm_id, create_root):
            read_fd, write_fd = os.pipe()
            os.write(write_fd, b"PUBLIC-FIXTURE-ROOT".ljust(32, b"!"))
            os.close(write_fd)
            return read_fd, {"created": True, "delivered": True}
        with patch.object(boot, "validate_boot", return_value=(value, Path("public-engine"), {})), \
             patch.object(boot, "launch_command", return_value=["public-engine"]), \
             patch.object(boot.resource, "setrlimit"), \
             patch.object(boot.legacy, "root_pipe", side_effect=public_pipe), \
             patch.object(boot.subprocess, "Popen", PublicProcess), \
             patch.object(boot, "quit_owned_vm", return_value=qmp):
            run_dir, receipt = boot.boot(target, 10, True, "restore")
        self.assertFalse((target / ".data-v2-launch.lock").exists())
        return receipt, contract.read_metadata(target / "virtual-profile.json")

    def test_checkpoint_requires_accepted_qmp_flush_and_clean_exit(self):
        receipt, manifest = self.boot_public_fixture(qmp=False)
        self.assertFalse(receipt["checkpoint_observed"])
        self.assertNotIn("restore_checkpoint_observed", manifest)

    def test_mpe_fault_stops_before_a_checkpoint_can_be_promoted(self):
        receipt, manifest = self.boot_public_fixture(fault=True)
        self.assertEqual(receipt["stop_reason"], "virtual-mpe-contract-rejected")
        self.assertFalse(receipt["checkpoint_observed"])
        self.assertNotIn("restore_checkpoint_observed", manifest)

    def test_mpe_revoke_stops_before_a_checkpoint_can_be_promoted(self):
        receipt, _ = self.boot_public_fixture(revoke=True)
        self.assertEqual(receipt["stop_reason"], "virtual-mpe-contract-rejected")
        self.assertFalse(receipt["checkpoint_observed"])

    def test_normal_accepted_flush_can_record_only_the_restore_checkpoint(self):
        receipt, manifest = self.boot_public_fixture()
        self.assertTrue(receipt["checkpoint_observed"])
        self.assertTrue(manifest["restore_checkpoint_observed"])
        self.assertFalse(receipt["ready"])
        self.assertFalse(receipt["native_ready"])

    def test_signal_exit_does_not_record_a_successful_checkpoint(self):
        receipt, manifest = self.boot_public_fixture(exit_code=-15)
        self.assertFalse(receipt["checkpoint_observed"])
        self.assertNotIn("restore_checkpoint_observed", manifest)

    def test_rejection_during_final_drain_cannot_record_checkpoint(self):
        receipt, manifest = self.boot_public_fixture(drain_events=
            "pci_nvme_apple_ans_complete sqid=1 cid=7 opcode=0x01 status=0x4002\n"
            "apple_sep_virtual_mpe_control action=revoked reg=0x414 value=0x1 accepted=0\n")
        self.assertEqual(receipt["nvme_error_completion_count"], 1)
        self.assertTrue(receipt["mpe_rejected_revocation_observed"])
        self.assertFalse(receipt["checkpoint_observed"])
        self.assertNotIn("restore_checkpoint_observed", manifest)
        self.assertTrue(receipt["private_socket_directory_removed"])

    def test_private_socket_cleanup_never_removes_unexpected_files(self):
        directory = self.root / "owned-sockets"
        directory.mkdir(mode=0o700)
        info = directory.lstat()
        identity = (info.st_dev, info.st_ino, info.st_uid)
        unexpected = directory / "qmp.sock"
        unexpected.write_bytes(b"PUBLIC-SENTINEL")
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            boot.cleanup_short_sockets(directory, identity)
        self.assertEqual(unexpected.read_bytes(), b"PUBLIC-SENTINEL")

    def test_protected_rejection_metadata_is_retained_without_payload(self):
        result = boot.storage_failure_observations(
            "pci_nvme_apple_ans_protected_gate sqid=1 cid=7 stage=protected-gate result=context-stale\n"
            "pci_nvme_apple_ans_protected_io_rejected sqid=1 cid=7 opcode=0x01 mode=1 unsupported crypto; I/O rejected\n")
        self.assertEqual(result["protected_gate_rejection_count"], 1)
        self.assertEqual(result["protected_io_rejection_count"], 1)
        self.assertNotIn("payload", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
