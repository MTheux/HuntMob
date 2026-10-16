import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_ios_virtual_data_v2_boot as inspection


class SystemBootInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.mount = Path(self.temporary.name) / "System"
        self.mount.mkdir()
        self.output = Path(self.temporary.name) / "output"
        self.output.mkdir()

    def test_only_fixed_public_system_paths_can_be_copied(self):
        for path in ("mnt2/keybags/systembag.kb", "private/var/keybags/systembag.kb", "../Data/file", "/sbin/launchd"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                inspection.copy_public_file(self.mount, self.output, path, 1024)

    def test_public_binary_copy_is_hash_bound_and_non_executable(self):
        (self.mount / "sbin").mkdir()
        data = b"public-mach-o-fixture"
        (self.mount / "sbin/launchd").write_bytes(data)
        record, size = inspection.copy_public_file(self.mount, self.output, "sbin/launchd", 1024)
        self.assertEqual(size, len(data))
        self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
        destination = self.output / record["artifact"]
        self.assertEqual(destination.read_bytes(), data)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_missing_is_reported_and_size_budget_is_enforced(self):
        record, size = inspection.copy_public_file(self.mount, self.output, "sbin/launchd", 0)
        self.assertFalse(record["present"])
        self.assertEqual(size, 0)
        (self.mount / "sbin").mkdir()
        (self.mount / "sbin/launchd").write_bytes(b"oversized")
        with self.assertRaises(ValueError):
            inspection.copy_public_file(self.mount, self.output, "sbin/launchd", 1)

    def test_symlink_file_or_parent_is_never_followed(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "launchd").write_bytes(b"do-not-follow")
        (self.mount / "sbin").symlink_to(outside)
        with self.assertRaises(ValueError):
            inspection.copy_public_file(self.mount, self.output, "sbin/launchd", 1024)
        (self.mount / "sbin").unlink()
        (self.mount / "sbin").mkdir()
        (self.mount / "sbin/launchd").symlink_to(outside / "launchd")
        with self.assertRaises(ValueError):
            inspection.copy_public_file(self.mount, self.output, "sbin/launchd", 1024)

    def test_directory_inventory_reads_names_and_types_only(self):
        directory = self.mount / "private/etc"
        directory.mkdir(parents=True)
        (directory / "example.conf").write_bytes(b"not-read-by-inventory")
        (directory / "alias").symlink_to("example.conf")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("No directory contents allowed")):
            record = inspection.directory_names(self.mount, "private/etc")
        self.assertFalse(record["contents_read"])
        self.assertEqual(record["entries"], [{"name": "alias", "type": "symlink"}, {"name": "example.conf", "type": "file"}])

    def test_optional_utility_leaf_symlink_is_recorded_without_following(self):
        (self.mount / "sbin").mkdir()
        (self.mount / "sbin/mount_apfs").symlink_to("/private/Data/never-follow")
        record, size = inspection.copy_public_file(self.mount, self.output, "sbin/mount_apfs", 1024)
        self.assertEqual(size, 0)
        self.assertTrue(record["present"])
        self.assertFalse(record["copied"])
        self.assertFalse(record["symlink_followed"])
        self.assertEqual(record["status"], "optional-leaf-symlink-skipped")
        self.assertFalse((self.output / "public-system").exists())

    def test_optional_utility_still_rejects_any_symlink_parent(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "mount_apfs").write_bytes(b"must-not-follow")
        (self.mount / "sbin").symlink_to(outside)
        with self.assertRaises(ValueError):
            inspection.copy_public_file(self.mount, self.output, "sbin/mount_apfs", 1024)

    def test_actual_readonly_vfs_required_after_exact_mount_binding(self):
        with mock.patch.object(inspection.cold, "validate_system_mount") as validation, \
             mock.patch.object(inspection.os, "statvfs", return_value=SimpleNamespace(f_flag=0)):
            with self.assertRaises(ValueError):
                inspection.checked_readonly_system(self.mount, "/dev/disk99s1", {})
            validation.assert_called_once()
        with mock.patch.object(inspection.cold, "validate_system_mount"), \
             mock.patch.object(inspection.os, "statvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            inspection.checked_readonly_system(self.mount, "/dev/disk99s1", {})

    def test_default_cli_does_not_require_or_attach_a_real_cohort(self):
        result = subprocess.run([sys.executable, inspection.__file__, "--vm-uuid", "2a31ad9c-aab5-4816-a69a-6f4e9ece162a"],
                                check=True, capture_output=True)
        plan = json.loads(result.stdout)
        self.assertTrue(plan["read_only"])
        self.assertFalse(plan["host_attachment_performed"])
        self.assertFalse(plan["host_mount_performed"])
        self.assertFalse(plan["root_accessed"])

    def test_each_success_is_persisted_before_a_later_extraction_fails(self):
        target = Path(self.temporary.name) / "cohort"
        target.mkdir()
        (target / "virtual-profile.json").write_text("public-metadata-fixture")
        data_uuid = "6CBC240D-0C5B-4E26-A078-1D3C02181D3E"
        manifest = {"vm_uuid": "fixture", "root_provisioned": True, "data_profile_sha256": "profilehash",
            "engine_binding": {}, "backings": {"namespace-1.raw": {}}, "cold_read_v2": {
                "schema": inspection.cold.SCHEMA, "vm_uuid": "fixture", "profile": inspection.contract.PROFILE,
                "state": "installed", "data_uuid": data_uuid, "host_data_uuid": data_uuid,
                "host_data_encrypted": True, "host_data_locked": True}}
        calls = []
        def extract(mount, output, relative, remaining):
            calls.append(relative)
            if len(calls) == 1:
                return {"present": True, "artifact": "public-system/sbin/launchd", "sha256": "bound"}, 8
            on_disk = json.loads((output / "receipt.json").read_text())
            self.assertEqual(on_disk["files"]["sbin/launchd"]["sha256"], "bound")
            self.assertEqual(on_disk["bytes_copied"], 8)
            raise ValueError("Later critical source rejected")
        with mock.patch.object(inspection.contract, "target_for", return_value=target), \
             mock.patch.object(inspection.contract, "validate_manifest", return_value=manifest), \
             mock.patch.object(inspection.contract, "verify_engine"), \
             mock.patch.object(inspection.stage, "attach_backing", return_value=("/dev/disk99", set())), \
             mock.patch.object(inspection.stage, "run"), mock.patch.object(inspection, "owned_container", return_value={}), \
             mock.patch.object(inspection.cold, "checked_layout", return_value="/dev/disk100s1"), \
             mock.patch.object(inspection, "checked_readonly_system"), \
             mock.patch.object(inspection.profile, "verify_attachment"), \
             mock.patch.object(inspection.profile, "image_inventory", return_value=[]), \
             mock.patch.object(inspection, "copy_public_file", side_effect=extract):
            with self.assertRaisesRegex(ValueError, "Later critical"):
                inspection.inspect("fixture")
        receipts = list(target.glob("data-v2-system-boot-inspection-*/receipt.json"))
        self.assertEqual(len(receipts), 1)
        final = json.loads(receipts[0].read_text())
        self.assertEqual(final["state"], "inspection-failed")
        self.assertTrue(final["system_unmounted"])
        self.assertTrue(final["owned_device_detached"])


if __name__ == "__main__":
    unittest.main()
