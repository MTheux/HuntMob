import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_update_volume as update


def append_log():
    return "\n".join(["HuntMob: invoking stock Data Protection verifier",
        "HuntMob: Update append preflight existing_slots=5 slot6_absent=1 slot7_absent=1",
        "HuntMob: Update append stock-newfs-start role=192 append_only=1",
        "HuntMob: Update append stock-newfs-exit=0 signal=0",
        "HuntMob: Update append slot6 ready existing_slots_preserved=5 slot7_absent=1", update.STOP_MARKER])


class UpdateVolumeStageTests(unittest.TestCase):
    def setUp(self):
        self.uuid = "51D74C2E-89CE-4F9F-8F9B-E1E32AB61425"
        self.manifest = {"auxiliary_layout": {"system_uuid": "system", "created_volumes": [
            {"Roles": ["xART"], "APFSVolumeUUID": "xart"}, {"Roles": ["Hardware"], "APFSVolumeUUID": "hardware"},
            {"Roles": ["Preboot"], "APFSVolumeUUID": "preboot"}]}}
        self.container = {"ContainerReference": "disk100", "PhysicalStores": [{"DeviceIdentifier": "disk99s1"}], "Volumes": []}
        for index, name, identity, encrypted in ((1, "System", "system", False), (2, "Data", update.post.DATA_UUID, True),
                (3, "xART", "xart", False), (4, "Hardware", "hardware", False), (5, "Preboot", "preboot", False),
                (6, "Update", self.uuid, False)):
            self.container["Volumes"].append({"Name": name, "Roles": [name], "APFSVolumeUUID": identity,
                "Encryption": encrypted, "Locked": name == "Data", "DeviceIdentifier": "disk100s" + str(index)})

    def test_exact_single_update_exception_keeps_global_five_guard_strict(self):
        system, added = update.checked_updated_layout(self.container, "/dev/disk99", self.manifest)
        self.assertEqual(system, "/dev/disk100s1")
        self.assertEqual(added["APFSVolumeUUID"], self.uuid)
        self.assertEqual(len(self.container["Volumes"]), 6)
        with self.assertRaises(ValueError):
            update.cold.checked_layout(self.container, "/dev/disk99", self.manifest, update.post.DATA_UUID)

    def test_user_role_wrong_slot_duplicate_uuid_or_extra_volume_refused(self):
        for field, value in (("Roles", ["User"]), ("Name", "Other"), ("Encryption", True),
                              ("DeviceIdentifier", "disk100s7"), ("APFSVolumeUUID", update.post.DATA_UUID), ("MountPoint", "/Update")):
            container = copy.deepcopy(self.container)
            container["Volumes"][-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                update.checked_updated_layout(container, "/dev/disk99", self.manifest)
        container = copy.deepcopy(self.container)
        container["Volumes"].append({"DeviceIdentifier": "disk100s7"})
        with self.assertRaises(ValueError):
            update.checked_updated_layout(container, "/dev/disk99", self.manifest)
        with self.assertRaises(ValueError):
            update.checked_updated_layout(self.container, "/dev/disk99", self.manifest, "different-bound-uuid")

    def test_existing_data_identity_crypto_lock_or_mount_cannot_change(self):
        for field, value in (("APFSVolumeUUID", self.uuid), ("Encryption", False), ("Locked", False), ("MountPoint", "/Data")):
            container = copy.deepcopy(self.container)
            container["Volumes"][1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                update.checked_updated_layout(container, "/dev/disk99", self.manifest)

    def test_stock_exit_zero_still_requires_host_metadata_and_remains_not_ready(self):
        value = update.classify_result(append_log())
        self.assertTrue(value["host_update_metadata_validation_required"])
        self.assertEqual(value["new_role_number"], 192)
        self.assertFalse(value["native_ready"])

    def test_failed_repeated_wrong_role_partial_or_keybag_result_refused(self):
        for before, after in (("stock-newfs-exit=0", "stock-newfs-exit=1"), ("role=192", "role=2"),
                              ("slot7_absent=1", "slot7_absent=0"), ("existing_slots_preserved=5", "existing_slots_preserved=4"),
                              (update.STOP_MARKER, "")):
            with self.subTest(after=after), self.assertRaises(ValueError):
                update.classify_result(append_log().replace(before, after))
        for line in ("HuntMob: Update append stock-newfs-exit=0 signal=0", "HuntMob: post-keybag stock-init-start",
                     "HuntMob: Update append failure stage=single-new-slot errno=22"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                update.classify_result(append_log() + "\n" + line)

    def test_sources_pin_role_p_and_actual_bundle_program(self):
        for name, sha in update.PINS.items():
            self.assertEqual(hashlib.sha256((update.stage.PROVISIONING / name).read_bytes()).hexdigest(), sha)
        header = (update.stage.PROVISIONING / "append_update_policy_v2.h").read_text()
        self.assertIn('"role=p"', header)
        self.assertIn('"/System/Library/Filesystems/apfs.fs/newfs_apfs"', header)

    def test_boot_revalidates_frozen_evidence_after_temporary_staging_without_fake_old_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            build = target / "data-v2-update-volume"
            build.mkdir()
            (build / "original-VirtualTrustCache").write_bytes(b"public-prior-tc-fixture")
            expected = b"public-updated-tc-fixture"
            tc_sha = hashlib.sha256(expected).hexdigest()
            manifest = {"vm_uuid": update.post.VM_UUID, "engine_binding": {}, "virtual_staging": {
                "helper_sha256": {"huntmob-prepare-userdata": "new-helper-sha"}, "trustcache_sha256": tc_sha},
                "update_volume_v2": {"schema": update.SCHEMA, "profile": update.contract.PROFILE,
                    "vm_uuid": update.post.VM_UUID, "data_uuid": update.post.DATA_UUID, "state": "installed", "source_sha256": update.PINS,
                    "engine_binding": {}, "existing_five_preserved_before_guest": True, "host_data_mounted": False,
                    "helper_sha256": "new-helper-sha", "trustcache_sha256": tc_sha, "evidence": {"pinned": True}, "helper_cdhash": "1" * 40}}
            with mock.patch.object(update, "verify_frozen_evidence") as frozen, \
                 mock.patch.object(update, "preparation_evidence", side_effect=AssertionError("Do not fabricate old staging")), \
                 mock.patch.object(update, "require_sources"), mock.patch.object(update.post, "verify_hash"), \
                 mock.patch.object(update.post, "add_only_shim_tc", return_value=expected):
                update.validate_for_boot(target, manifest)
            frozen.assert_called_once_with(target, {"pinned": True})

    def test_cli_defaults_to_noop(self):
        result = subprocess.run([sys.executable, update.__file__, "--vm-uuid", update.post.VM_UUID], check=True, capture_output=True)
        value = json.loads(result.stdout)
        self.assertTrue(value["read_only"])
        self.assertFalse(value["host_data_mounted"])
        self.assertEqual(value["new_role_number"], 192)

    def test_separate_update_retry_preserves_factory_history_and_refuses_replay_or_partial_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            history = {"previous_receipt_sha256": update.inspection.BASELINE_SHA, "maximum_retries": 1}
            manifest = {"vm_uuid": update.post.VM_UUID, "engine_binding": {}, "post_keybag_v2": {
                "schema": update.post.SCHEMA, "profile": update.contract.PROFILE, "vm_uuid": update.post.VM_UUID,
                "data_uuid": update.post.DATA_UUID, "state": "launch-requested",
                "observation": str(target / update.inspection.POST_FACTORY_BASELINE), "factorydata_seed_rearmed": history},
                "update_volume_v2": {"schema": update.SCHEMA, "profile": update.contract.PROFILE, "vm_uuid": update.post.VM_UUID,
                    "data_uuid": update.post.DATA_UUID, "engine_binding": {}, "source_sha256": update.PINS,
                    "state": "observed-original-restored", "original_helper_restored": True, "original_trustcache_restored": True,
                    "own_prepare_marker_removed": True, "owned_device_detached": True, "existing_five_uuid_unchanged": True,
                    "existing_five_uuid_by_slot": {str(i): "old-uuid-" + str(i) for i in range(1, 6)},
                    "created_update": {"Name": "Update", "Roles": ["Update"], "Encryption": False,
                        "APFSVolumeUUID": self.uuid, "DeviceIdentifier": "disk100s6"}},
                "virtual_staging": {"trustcache_sha256": update.factory.OLD_TC_SHA,
                    "helper_sha256": {"huntmob-prepare-userdata": update.factory.OLD_COLD_SHA}}}
            post_record, _ = update.checked_rearm_state(target, manifest)
            self.assertIs(post_record["factorydata_seed_rearmed"], history)
            for field in ("original_helper_restored", "original_trustcache_restored", "own_prepare_marker_removed", "existing_five_uuid_unchanged"):
                manifest["update_volume_v2"][field] = False
                with self.subTest(field=field), self.assertRaises(ValueError):
                    update.checked_rearm_state(target, manifest)
                manifest["update_volume_v2"][field] = True
            post_record["update_volume_rearmed"] = {"already-used": True}
            with self.assertRaises(ValueError):
                update.checked_rearm_state(target, manifest)


if __name__ == "__main__":
    unittest.main()
