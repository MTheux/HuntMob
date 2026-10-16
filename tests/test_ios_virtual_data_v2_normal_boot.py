import copy
import hashlib
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_normal_boot as normal


class NormalBootRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name)
        self.manifest = {"vm_uuid": normal.post.VM_UUID, "engine_binding": {}, "backings": {}}
        self.scan = {"schema": "huntmob.virtual-sep-data-storage-probe-scan.v1", "vm_uuid": normal.post.VM_UUID,
            "engine_binding": {}, "data_profile": normal.contract.PROFILE, "state": "completed-readonly-scan", "total_matches": 0,
            "public_probe_absent": True, "global_source_identity_unchanged": True, "host_backings_not_attached_before_after": True,
            "Data_mounted_or_unlocked": False, "backings_written": False, "root_accessed": False, "keychain_accessed": False, "vm_started": False,
            "scoped_native_cold_read": {"observation": str(self.target / normal.OBSERVATION), "observation_sha256": normal.OBSERVATION_SHA,
                "boot_log_sha256": normal.BOOT_LOG_SHA, "trace_log_sha256": normal.TRACE_LOG_SHA, "result": "afu-read-match", "validated": True},
            "backings": {}, "total_bytes_scanned": sum(normal.profile.SIZES.values())}
        for index, (name, size) in enumerate(normal.profile.SIZES.items()):
            fingerprint = {"device": 2, "inode": index + 100, "bytes": size, "links": 1}
            self.manifest["backings"][name] = fingerprint
            identity = {**fingerprint, "mtime_ns": 1, "ctime_ns": 1}
            self.scan["backings"][name] = {"identity_before": dict(identity), "identity_after": dict(identity), "bytes_scanned": size,
                "matches": {kind: {"count": 0, "offsets": [], "offsets_truncated": False} for kind in ("ascii_hex64", "decoded32")}}

    def verify_scan(self, current_identity=True, changed=None, scan_mode="initial"):
        def lstat(path):
            entry = self.scan["backings"][path.name]["identity_after"]
            return SimpleNamespace(st_dev=entry["device"], st_ino=entry["inode"], st_size=entry["bytes"], st_nlink=1,
                st_mtime_ns=2 if path.name == changed else 1, st_ctime_ns=1)
        with mock.patch.object(normal.post, "verify_hash"), mock.patch.object(normal.contract, "read_metadata", return_value=self.scan), \
             mock.patch.object(Path, "lstat", lstat):
            return normal.verified_scan(self.target, self.manifest, current_identity, scan_mode=scan_mode)

    def test_actual_scoped_read_and_full_nine_extent_absence_required(self):
        value = self.verify_scan()
        self.assertEqual(value["total_matches"], 0)
        self.assertTrue(value["scoped_native_cold_read_validated"])

    def test_plaintext_absence_alone_partial_scan_or_hit_does_not_authorize_normal_staging(self):
        self.scan["scoped_native_cold_read"]["validated"] = False
        with self.assertRaises(ValueError):
            self.verify_scan()
        self.scan["scoped_native_cold_read"]["validated"] = True
        entry = self.scan["backings"].pop("namespace-7.raw")
        with self.assertRaises(ValueError):
            self.verify_scan()
        self.scan["backings"]["namespace-7.raw"] = entry
        entry["matches"]["decoded32"]["count"] = 1
        with self.assertRaises(ValueError):
            self.verify_scan()

    def test_backing_drift_blocks_before_stage_and_only_known_system_changes_allowed_after(self):
        with self.assertRaises(ValueError):
            self.verify_scan(changed="namespace-1.raw")
        self.verify_scan(current_identity=False, changed="namespace-1.raw")
        with self.assertRaises(ValueError):
            self.verify_scan(current_identity=False, changed="sep-nvram.raw")

    def test_stock_tc_restoration_is_original_im4p_not_rebuilt_deduplicated_cache(self):
        def tlv(tag, data):
            return bytes((tag, len(data))) + data
        stock = b"s" * 20 + b"\x02\x00"
        hashes = [str(n) * 40 for n in (1, 2, 3)]
        # The original stock payload deliberately contains a duplicate; its
        # exact bytes/UUID/order must survive restoration.
        payload = struct.pack("<I", 1) + b"o" * 16 + struct.pack("<I", 2) + stock * 2
        fields = tlv(0x16, b"IM4P") + tlv(0x16, b"rtsc") + tlv(0x16, b"stock") + tlv(4, payload)
        original = tlv(0x30, fields)
        own = [bytes.fromhex(value) + b"\x02\x00" for value in hashes]
        old = struct.pack("<I", 1) + b"v" * 16 + struct.pack("<I", 4) + stock + b"".join(own)
        with mock.patch.object(normal, "BASE_TC_SHA", hashlib.sha256(original).hexdigest()):
            self.assertEqual(normal.stock_tc_transition(old, original, hashes), original)
            with self.assertRaises(ValueError):
                normal.stock_tc_transition(old, original, hashes[:2] + ["4" * 40])
            extra = old[:20] + struct.pack("<I", 5) + old[24:] + b"x" * 20 + b"\x02\x00"
            with self.assertRaises(ValueError):
                normal.stock_tc_transition(extra, original, hashes)

    def test_any_own_restore_marker_including_dangling_alias_blocks_stock_stage(self):
        libexec = self.target / "usr/libexec"
        libexec.mkdir(parents=True)
        normal.require_absent_markers(self.target)
        for relative in normal.FORBIDDEN_MARKERS:
            marker = self.target / relative
            marker.write_bytes(b"own-marker")
            with self.assertRaises(ValueError):
                normal.require_absent_markers(self.target)
            marker.unlink()
            marker.symlink_to("/missing")
            with self.assertRaises(ValueError):
                normal.require_absent_markers(self.target)
            marker.unlink()

    def test_springboard_text_alone_never_claims_full_boot_ui_or_ipa(self):
        value = normal.classify_result("launchd started SpringBoard")
        self.assertFalse(value["full_boot_validated"])
        self.assertFalse(value["springboard_validated"])
        self.assertFalse(value["ipa_execution_validated"])
        self.assertFalse(value["native_ready"])
        self.assertFalse(normal.classify_result("")["normal_boot_log_observed"])
        with self.assertRaises(ValueError):
            normal.classify_result("HuntMob: post-keybag stock-init-start")
        with self.assertRaises(ValueError):
            normal.classify_result("HuntMob: provisioning checkpoint ready;")
        value = normal.classify_result("Early boot complete. Continuing system boot.\npanic(cpu")
        self.assertTrue(value["stock_early_boot_marker_observed"])
        self.assertFalse(value["full_boot_validated"])

    def test_default_cli_remains_noop_after_scoped_crypto_success(self):
        result = subprocess.run([sys.executable, normal.__file__, "--vm-uuid", normal.post.VM_UUID], check=True, capture_output=True)
        value = json.loads(result.stdout)
        self.assertTrue(value["read_only"])
        self.assertFalse(value["root_accessed"])
        self.assertFalse(value["host_data_mounted"])
        self.assertFalse(value["springboard_validated"])

    def test_public_stock_rename_preserves_inode_and_wrong_inode_or_mode_refused(self):
        original = self.target / "original-stock"
        shim = self.target / "owned-shim"
        original.write_bytes(b"public-stock-fixture")
        original.chmod(0o755)
        shim.write_bytes(b"owned-shim-fixture")
        before = original.lstat()
        os.replace(original, shim)
        normal.require_stock_inode_preserved(before, shim.lstat())
        replacement = self.target / "replacement"
        replacement.write_bytes(b"public-stock-fixture")
        replacement.chmod(0o755)
        with self.assertRaises(ValueError):
            normal.require_stock_inode_preserved(before, replacement.lstat())
        shim.chmod(0o777)
        with self.assertRaises(ValueError):
            normal.require_stock_inode_preserved(before, shim.lstat())

    def test_atomic_shared_lock_rejects_a_real_concurrent_contender(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def holder():
            try:
                with normal.exclusive_staging_lock(self.target) as fd:
                    self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
                    entered.set()
                    self.assertTrue(release.wait(2))
            except BaseException as error:
                errors.append(error)
                entered.set()
        worker = threading.Thread(target=holder)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertFalse(errors)
            with self.assertRaises(FileExistsError):
                with normal.exclusive_staging_lock(self.target):
                    self.fail("A concurrent staging/launch lock must never enter")
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertFalse((self.target / ".data-v2-launch.lock").exists())

    def test_install_holds_owned_descriptor_through_validation_and_work_then_closes_it(self):
        captured = []
        manifest = {"vm_uuid": normal.post.VM_UUID}
        def validation(target, *, owned_launch_lock):
            captured.append(owned_launch_lock)
            path = target / ".data-v2-launch.lock"
            self.assertEqual(path.lstat().st_ino, os.fstat(owned_launch_lock).st_ino)
            return manifest
        def work(target, value, fd):
            self.assertIs(value, manifest)
            self.assertEqual(fd, captured[0])
            with self.assertRaises(FileExistsError):
                os.open(target / ".data-v2-launch.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            return {"public-test": "completed"}
        with mock.patch.object(normal.contract, "target_for", return_value=self.target), \
             mock.patch.object(normal.contract, "validate_manifest", side_effect=validation), \
             mock.patch.object(normal, "_install_owned", side_effect=work):
            self.assertEqual(normal.install(normal.post.VM_UUID), {"public-test": "completed"})
        self.assertFalse((self.target / ".data-v2-launch.lock").exists())
        with self.assertRaises(OSError):
            os.fstat(captured[0])

    def test_existing_lock_or_alias_prevents_any_manifest_or_staging_work(self):
        lock = self.target / ".data-v2-launch.lock"
        victim = self.target / "public-existing"
        victim.write_bytes(b"leave-existing-file-unchanged")
        with mock.patch.object(normal.contract, "target_for", return_value=self.target), \
             mock.patch.object(normal.contract, "validate_manifest") as validation, \
             mock.patch.object(normal, "_install_owned") as work:
            lock.write_bytes(b"existing-launch")
            with self.assertRaises(FileExistsError):
                normal.install(normal.post.VM_UUID)
            self.assertEqual(lock.read_bytes(), b"existing-launch")
            lock.unlink()
            lock.symlink_to(victim)
            with self.assertRaises(FileExistsError):
                normal.install(normal.post.VM_UUID)
            validation.assert_not_called()
            work.assert_not_called()
        self.assertEqual(victim.read_bytes(), b"leave-existing-file-unchanged")

    def test_exception_cleanup_removes_only_own_inode_and_preserves_replacements(self):
        lock = self.target / ".data-v2-launch.lock"
        with self.assertRaisesRegex(RuntimeError, "public-staging-failure"):
            with normal.exclusive_staging_lock(self.target):
                raise RuntimeError("public-staging-failure")
        self.assertFalse(lock.exists())
        with normal.exclusive_staging_lock(self.target) as fd:
            original_inode = os.fstat(fd).st_ino
            lock.unlink()
            lock.write_bytes(b"replacement-owner")
            self.assertNotEqual(lock.lstat().st_ino, original_inode)
        self.assertEqual(lock.read_bytes(), b"replacement-owner")
        lock.unlink()
        victim = self.target / "public-victim"
        victim.write_bytes(b"preserve")
        with normal.exclusive_staging_lock(self.target):
            lock.unlink()
            lock.symlink_to(victim)
        self.assertTrue(lock.is_symlink())
        self.assertEqual(victim.read_bytes(), b"preserve")

    def test_preparation_accepts_only_descriptor_validated_by_shared_contract(self):
        with normal.exclusive_staging_lock(self.target) as fd:
            with self.assertRaisesRegex(ValueError, "launch is active"):
                normal.preparation_evidence(self.target, {})
            with mock.patch.object(normal.contract, "validate_manifest", side_effect=ValueError("ownership-check-rejected")) as validation:
                with self.assertRaisesRegex(ValueError, "ownership-check-rejected"):
                    normal.preparation_evidence(self.target, {}, owned_launch_lock=fd)
                validation.assert_called_once_with(self.target, {}, owned_launch_lock=fd)


    def refresh_fixture(self):
        self.manifest["normal_boot_v2"] = {"schema": normal.SCHEMA, "profile": normal.contract.PROFILE,
            "vm_uuid": normal.post.VM_UUID, "data_uuid": normal.post.DATA_UUID, "update_uuid": normal.UPDATE_UUID,
            "engine_binding": {}, "observation": str(self.target / normal.FIRST_NORMAL), "state": "launch-requested"}
        proof = {"schema": "huntmob.virtual-sep-data-observation.v2", "vm_uuid": normal.post.VM_UUID,
            "engine_binding": {}, "data_profile": normal.contract.PROFILE, "normal_boot_requested": True,
            "stop_reason": "bounded-observation-ended", "normal_boot_log_observed": True,
            "stock_early_boot_marker_observed": True, "panic_observed": False, "qmp_quit_requested": True,
            "qmp_quit_accepted": True, "exit_code": 0, "checkpoint_observed": False, "aess_command_count": 22143,
            "boot.log_sha256": normal.FIRST_NORMAL_BOOT_SHA, "trace.log_sha256": normal.FIRST_NORMAL_TRACE_SHA,
            "virtual_mpe_memory_fault_observed": False, "mpe_rejected_revocation_observed": False,
            "command": ["public-engine", "-display", "none"]}
        for key in ("aess_rejected_command_count", "nvme_error_completion_count", "protected_io_rejection_count", "protected_gate_rejection_count"):
            proof[key] = 0
        return proof

    def test_refresh_requires_exact_clean_stopped_normal_boot_and_hashes(self):
        proof = self.refresh_fixture()
        log = "Early boot complete. Continuing system boot."
        with mock.patch.object(normal.contract, "read_metadata", side_effect=lambda path: proof), \
             mock.patch.object(normal.post, "verify_hash") as verify, \
             mock.patch.object(Path, "read_text", return_value=log), \
             mock.patch.object(normal, "verified_scan", return_value={"current": "all-nine"}) as scan:
            evidence = normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=True)
            self.assertEqual(evidence["headless_refresh_hz_required"], 10)
            self.assertFalse(evidence["ready"])
            scan.assert_called_once_with(self.target, self.manifest, True, scan_mode="refresh-current")
            self.assertEqual([call.args[1] for call in verify.call_args_list],
                [normal.FIRST_NORMAL_SHA, normal.FIRST_NORMAL_BOOT_SHA, normal.FIRST_NORMAL_TRACE_SHA])
            for key, bad in (("exit_code", 1), ("panic_observed", True), ("normal_boot_requested", False),
                    ("qmp_quit_accepted", False), ("aess_rejected_command_count", 1), ("nvme_error_completion_count", 1),
                    ("boot.log_sha256", "changed"), ("checkpoint_observed", True),
                    ("virtual_mpe_memory_fault_observed", True), ("command", ["engine", "-display", "cocoa"])):
                original = proof[key]
                proof[key] = bad
                with self.subTest(key=key), self.assertRaises(ValueError):
                    normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=True)
                proof[key] = original
            verify.side_effect = ValueError("pinned-hash-mismatch")
            with self.assertRaisesRegex(ValueError, "pinned-hash-mismatch"):
                normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=True)

    def test_refresh_single_use_intent_and_planned_launch_must_match_exactly(self):
        proof = self.refresh_fixture()
        intent = self.target / "data-v2-normal-headless-refresh-intent.json"
        record = self.manifest["normal_boot_v2"]
        with mock.patch.object(normal.contract, "read_metadata", side_effect=lambda path: proof), \
             mock.patch.object(normal.post, "verify_hash"), \
             mock.patch.object(Path, "read_text", return_value="Early boot complete. Continuing system boot."), \
             mock.patch.object(normal, "verified_scan", return_value={"current": "all-nine"}):
            evidence = normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=True)
            intent.symlink_to(self.target / "absent")
            with self.assertRaisesRegex(ValueError, "only once"):
                normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=True)
            intent.unlink()
            record.update(state="planned", headless_refresh_hz_required=10, headless_refresh_rearmed=evidence)
            with mock.patch.object(normal.contract, "read_metadata", side_effect=lambda path: evidence if path == intent else proof):
                self.assertEqual(normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=False), evidence)
                record["headless_refresh_hz_required"] = 9
                with self.assertRaises(ValueError):
                    normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=False)
                record["headless_refresh_hz_required"] = 10
                record["headless_refresh_rearmed"] = {**evidence, "maximum_retries": 2}
                with self.assertRaises(ValueError):
                    normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=False)
            record["state"] = "launch-requested"
            with self.assertRaisesRegex(ValueError, "only once"):
                normal.headless_refresh_evidence(self.target, self.manifest, for_rearm=True)

    def test_refresh_current_scan_checks_all_nine_and_historical_exception_requires_new_chain(self):
        for name in self.scan["backings"]:
            with self.subTest(backing=name), self.assertRaises(ValueError):
                self.verify_scan(current_identity=False, changed=name, scan_mode="refresh-current")
        with mock.patch.object(normal, "headless_refresh_evidence", side_effect=ValueError("chain-not-validated")) as gate:
            with self.assertRaisesRegex(ValueError, "chain-not-validated"):
                self.verify_scan(current_identity=False, changed="sep-nvram.raw", scan_mode="historical-after-normal")
            gate.assert_called_once_with(self.target, self.manifest, for_rearm=False)
        with mock.patch.object(normal, "headless_refresh_evidence") as gate:
            original = self.verify_scan(current_identity=False, changed="sep-nvram.raw", scan_mode="historical-after-normal")
            self.assertEqual(original["receipt"], normal.SCAN)
            self.assertEqual(original["receipt_sha256"], normal.SCAN_SHA)
            gate.assert_called_once()

    def test_rearm_preserves_history_under_shared_lock_and_only_publishes_single_plan(self):
        self.refresh_fixture()
        original = {"raw_scan": {"receipt": normal.SCAN, "receipt_sha256": normal.SCAN_SHA, "total_matches": 0,
                    "scoped_native_cold_read_validated": True}, "original-history": "immutable"}
        record = self.manifest["normal_boot_v2"]
        record.update(evidence=copy.deepcopy(original), identity_binding={key: None for key in
            ("keychain_service", "keychain_account", "crypto_provider_source_sha256", "kdf_id")})
        for key in ("stock_keybag_same_inode_restored", "stock_data_protection_restored", "all_owned_helpers_removed_from_trustcache",
                "own_restore_preparation_markers_absent", "owned_device_detached", "existing_six_volumes_preserved"):
            record[key] = True
        self.manifest["virtual_staging"] = {"helper_sha256": {"init_data_protection": normal.stage.STOCK_SHA},
            "trustcache_sha256": normal.BASE_TC_SHA}
        evidence = {"public-test": "all-exact-chain-verified"}
        historical = {**original, "raw_scan": {"receipt": normal.REFRESH_SCAN}}
        order = []
        def validation(target, *, owned_launch_lock):
            self.assertEqual(os.fstat(owned_launch_lock).st_ino, (target / ".data-v2-launch.lock").lstat().st_ino)
            return self.manifest
        def durable(path, value):
            order.append("intent")
            self.assertTrue((self.target / ".data-v2-launch.lock").is_file())
            self.assertEqual(value, evidence)
        def publish(target, manifest):
            order.append("manifest")
            self.assertEqual(order, ["artifacts", "intent", "manifest"])
            self.assertEqual(record["state"], "planned")
            self.assertEqual(record["headless_refresh_hz_required"], 10)
            self.assertEqual(record["evidence"], original)
        with mock.patch.object(normal.contract, "target_for", return_value=self.target), \
             mock.patch.object(normal.contract, "validate_manifest", side_effect=validation), \
             mock.patch.object(normal.contract, "verify_engine"), \
             mock.patch.object(normal, "headless_refresh_evidence", return_value=evidence), \
             mock.patch.object(normal, "preparation_evidence", return_value=historical), \
             mock.patch.object(normal, "verify_stock_restore_artifacts", side_effect=lambda *args: order.append("artifacts")), \
             mock.patch.object(normal.post, "durable_intent", side_effect=durable), \
             mock.patch.object(normal.profile, "write_manifest", side_effect=publish), \
             mock.patch.object(normal.stage, "attach_backing") as attach, \
             mock.patch.object(normal.stage, "run") as run:
            self.assertEqual(normal.rearm_headless_refresh(normal.post.VM_UUID), evidence)
            attach.assert_not_called()
            run.assert_not_called()
        self.assertFalse((self.target / ".data-v2-launch.lock").exists())

    def test_rearm_cli_is_noop_without_apply(self):
        result = subprocess.run([sys.executable, normal.__file__, "--vm-uuid", normal.post.VM_UUID,
            "--action", "rearm-headless-refresh"], check=True, capture_output=True)
        value = json.loads(result.stdout)
        self.assertTrue(value["read_only"])
        self.assertFalse(value["host_data_mounted"])
        self.assertFalse(value["springboard_validated"])


if __name__ == "__main__":
    unittest.main()
