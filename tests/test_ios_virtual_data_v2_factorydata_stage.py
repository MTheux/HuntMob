import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_factorydata as seed


def seed_log():
    lines = ["HuntMob: invoking stock Data Protection verifier",
             "HuntMob: FactoryData command stage=mount-hardware exit=0 signal=0",
             "HuntMob: FactoryData Hardware UUID exact matched"]
    lines += ["HuntMob: FactoryData directory index=" + str(n) + " created=1 metadata_valid=1" for n in range(1, 6)]
    lines += ["HuntMob: FactoryData metadata verified directories=5 mode=0755 uid=0 gid=0",
              "HuntMob: FactoryData command stage=unmount-hardware exit=0 signal=0",
              "HuntMob: FactoryData Hardware unmounted", seed.STOP_MARKER]
    return "\n".join(lines)


class FactoryDataStageTests(unittest.TestCase):
    def test_five_new_metadata_only_directories_remain_not_native_ready(self):
        value = seed.classify_result(seed_log())
        self.assertEqual(value["directory_count"], 5)
        self.assertEqual(value["mode"], "0755")
        self.assertFalse(value["native_ready"])
        self.assertFalse(value["ready"])

    def test_partial_existing_or_wrong_mode_ownership_refused(self):
        log = seed_log()
        for before, after in (("index=5 created=1 metadata_valid=1", "index=5 created=0 metadata_valid=1"),
                              ("index=3 created=1 metadata_valid=1", "index=3 created=1 metadata_valid=0"),
                              ("mode=0755", "mode=0700"), ("uid=0", "uid=501"), ("gid=0", "gid=20"),
                              ("directories=5", "directories=4"), (seed.STOP_MARKER, "")):
            with self.subTest(after=after), self.assertRaises(ValueError):
                seed.classify_result(log.replace(before, after))

    def test_failure_keybag_data_or_incomplete_unmount_refused(self):
        for line in ("HuntMob: FactoryData failure stage=metadata-or-sync index=1 errno=5",
                     "HuntMob: post-keybag stock-init-start", "HuntMob: ClassD initialization status=0",
                     "HuntMob: cold Class C unlocked-since-boot before=1"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                seed.classify_result(seed_log() + "\n" + line)
        for replacement in ("unmount-hardware exit=1 signal=0", "unmount-hardware exit=0 signal=9"):
            with self.assertRaises(ValueError):
                seed.classify_result(seed_log().replace("unmount-hardware exit=0 signal=0", replacement))

    def test_hardware_identity_and_unmount_order_cannot_be_rearranged(self):
        lines = seed_log().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        with self.assertRaises(ValueError):
            seed.classify_result("\n".join(lines))
        lines = seed_log().splitlines()
        lines[-2], lines[-3] = lines[-3], lines[-2]
        with self.assertRaises(ValueError):
            seed.classify_result("\n".join(lines))

    def test_source_pins_are_frozen_and_match(self):
        for name, expected in seed.PINS.items():
            self.assertEqual(hashlib.sha256((seed.stage.PROVISIONING / name).read_bytes()).hexdigest(), expected)

    def test_changed_inspection_blocks_before_staging_or_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(seed.inspection, "baseline", return_value={}), \
                 mock.patch.object(seed.post, "verify_hash", side_effect=ValueError("Changed readonly receipt")):
                with self.assertRaisesRegex(ValueError, "Changed readonly"):
                    seed.preparation_evidence(Path(directory), {})

    def test_wrong_restore_bytes_or_marker_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "old-helper"
            artifact.write_bytes(b"replacement-bytes")
            with self.assertRaises(ValueError):
                seed.post.verify_hash(artifact, seed.OLD_COLD_SHA)

    def test_default_cli_noops_and_does_not_mount_or_start_guest(self):
        result = subprocess.run([sys.executable, seed.__file__, "--vm-uuid", seed.post.VM_UUID], check=True, capture_output=True)
        value = json.loads(result.stdout)
        self.assertTrue(value["read_only"])
        self.assertFalse(value["root_accessed"])
        self.assertFalse(value["host_data_mounted"])
        self.assertTrue(value["hardware_only_directory_seed"])

    def test_post_keybag_retry_is_once_only_and_requires_complete_original_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            manifest = {"vm_uuid": seed.post.VM_UUID, "post_keybag_v2": {"schema": seed.post.SCHEMA,
                "profile": seed.contract.PROFILE, "vm_uuid": seed.post.VM_UUID, "data_uuid": seed.post.DATA_UUID,
                "state": "launch-requested", "observation": str(target / seed.inspection.BASELINE)},
                "factorydata_seed_v2": {"schema": seed.SCHEMA, "profile": seed.contract.PROFILE,
                    "vm_uuid": seed.post.VM_UUID, "source_sha256": seed.PINS, "state": "observed-original-restored",
                    "original_helper_restored": True, "original_trustcache_restored": True,
                    "own_prepare_marker_removed": True, "owned_device_detached": True},
                "virtual_staging": {"trustcache_sha256": seed.OLD_TC_SHA,
                    "helper_sha256": {"huntmob-prepare-userdata": seed.OLD_COLD_SHA}}}
            seed.checked_rearm_state(target, manifest)
            for key in ("original_helper_restored", "original_trustcache_restored", "own_prepare_marker_removed", "owned_device_detached"):
                manifest["factorydata_seed_v2"][key] = False
                with self.subTest(key=key), self.assertRaises(ValueError):
                    seed.checked_rearm_state(target, manifest)
                manifest["factorydata_seed_v2"][key] = True
            manifest["post_keybag_v2"]["factorydata_seed_rearmed"] = {"previous": "already-used"}
            with self.assertRaises(ValueError):
                seed.checked_rearm_state(target, manifest)
            del manifest["post_keybag_v2"]["factorydata_seed_rearmed"]
            manifest["virtual_staging"]["trustcache_sha256"] = "wrong-prior-trustcache"
            with self.assertRaises(ValueError):
                seed.checked_rearm_state(target, manifest)


if __name__ == "__main__":
    unittest.main()
