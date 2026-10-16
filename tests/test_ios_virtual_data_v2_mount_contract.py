import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_ios_virtual_data_v2_mount_contract as inspect_mount


class MountContractInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.mount = Path(self.temporary.name) / "Hardware"
        self.mount.mkdir()
        self.manifest = {"auxiliary_layout": {"system_uuid": "system", "created_volumes": [
            {"Roles": ["xART"], "APFSVolumeUUID": "xart"}, {"Roles": ["Hardware"], "APFSVolumeUUID": inspect_mount.HARDWARE_UUID},
            {"Roles": ["Preboot"], "APFSVolumeUUID": "preboot"}]}}
        self.container = {"ContainerReference": "disk100", "PhysicalStores": [{"DeviceIdentifier": "disk99s1"}], "Volumes": []}
        for index, name, identity, encrypted in ((1, "System", "system", False), (2, "Data", inspect_mount.post.DATA_UUID, True),
              (3, "xART", "xart", False), (4, "Hardware", inspect_mount.HARDWARE_UUID, False), (5, "Preboot", "preboot", False)):
            self.container["Volumes"].append({"Name": name, "Roles": [name], "APFSVolumeUUID": identity,
                "Encryption": encrypted, "Locked": name == "Data", "DeviceIdentifier": "disk100s" + str(index)})

    def test_only_exact_hardware_mount_metadata_exception_is_allowed(self):
        self.container["Volumes"][3]["MountPoint"] = str(self.mount)
        value = inspect_mount.hardware_from_layout(self.container, "/dev/disk99", self.manifest, self.mount)
        self.assertEqual(value, "/dev/disk100s4")
        self.assertEqual(self.container["Volumes"][3]["MountPoint"], str(self.mount))

    def test_data_unlocked_mounted_or_wrong_hardware_uuid_refused(self):
        for index, key, value in ((1, "Locked", False), (1, "MountPoint", "/Data"), (3, "APFSVolumeUUID", "foreign"),
                                  (3, "MountPoint", str(self.mount.parent))):
            container = copy.deepcopy(self.container)
            container["Volumes"][index][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                inspect_mount.hardware_from_layout(container, "/dev/disk99", self.manifest, self.mount)

    def test_hardware_inventory_is_metadata_only_and_locates_first_missing_component(self):
        (self.mount / "FactoryData").mkdir()
        (self.mount / "FactoryData/public-metadata-name").write_bytes(b"must-never-be-read")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("Hardware bytes must never be read")):
            metadata = inspect_mount.metadata_only(self.mount, "FactoryData", inspect_mount.HARDWARE_PATHS)
            missing = inspect_mount.metadata_only(self.mount, "FactoryData/System/Library", inspect_mount.HARDWARE_PATHS)
        self.assertFalse(metadata["file_contents_read"])
        self.assertEqual(metadata["directory_names"], [{"name": "public-metadata-name", "type": "file"}])
        self.assertEqual(missing["first_missing_component"], "FactoryData/System")

    def test_metadata_symlink_ancestor_is_reported_without_following(self):
        (self.mount / "FactoryData").symlink_to("/private/var")
        metadata = inspect_mount.metadata_only(self.mount, "FactoryData/System", inspect_mount.HARDWARE_PATHS)
        self.assertEqual(metadata["blocked_by_ancestor"], "FactoryData")
        self.assertEqual(metadata["ancestor_type"], "symlink")
        self.assertFalse(metadata["file_contents_read"])

    def test_metadata_allowlist_cannot_access_data_keybags_or_other_paths(self):
        for path in ("/private/var", "../Data", "keybags/systembag.kb", "FactoryData/secrets"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                inspect_mount.metadata_only(self.mount, path, inspect_mount.HARDWARE_PATHS)

    def test_public_mount_binary_only_is_copied_and_hash_bound(self):
        (self.mount / "sbin").mkdir()
        data = b"public-mount-mach-o-fixture"
        (self.mount / "sbin/mount").write_bytes(data)
        output = Path(self.temporary.name) / "output"
        output.mkdir()
        record = inspect_mount.copy_public_mount(self.mount, output)
        self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual((output / record["artifact"]).read_bytes(), data)
        self.assertEqual((output / record["artifact"]).stat().st_mode & 0o777, 0o600)

    def test_public_mount_symlink_is_never_followed(self):
        (self.mount / "sbin").mkdir()
        (self.mount / "sbin/mount").symlink_to("/private/var/arbitrary")
        with self.assertRaises(ValueError):
            inspect_mount.copy_public_mount(self.mount, Path(self.temporary.name) / "output")

    def test_default_cli_performs_no_attachment_or_mount(self):
        result = subprocess.run([sys.executable, inspect_mount.__file__, "--vm-uuid", inspect_mount.post.VM_UUID], check=True, capture_output=True)
        plan = json.loads(result.stdout)
        self.assertTrue(plan["read_only"])
        self.assertFalse(plan["host_mount_performed"])
        self.assertFalse(plan["hardware_file_contents_read"])
        self.assertEqual(plan["public_file_allowlist"], ["sbin/mount"])

    def test_hardware_vfs_requires_readonly_exact_device_and_uuid(self):
        device = "/dev/disk100s4"
        info = {"DeviceNode": device, "DeviceIdentifier": "disk100s4", "FilesystemType": "apfs",
                "APFSVolumeUUID": inspect_mount.HARDWARE_UUID}
        point = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_dev=42)
        block = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=42)
        def lstat(path):
            return block if str(path) == device else point
        with mock.patch.object(Path, "lstat", lstat), \
             mock.patch.object(inspect_mount.os, "statvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
             mock.patch.object(inspect_mount.profile, "run_plist", return_value=info):
            inspect_mount.validate_hardware_mount(self.mount, device)
            info["APFSVolumeUUID"] = "foreign"
            with self.assertRaises(ValueError):
                inspect_mount.validate_hardware_mount(self.mount, device)
            info["APFSVolumeUUID"] = inspect_mount.HARDWARE_UUID
            block.st_rdev = 99
            with self.assertRaises(ValueError):
                inspect_mount.validate_hardware_mount(self.mount, device)
        block.st_rdev = 42
        with mock.patch.object(Path, "lstat", lstat), \
             mock.patch.object(inspect_mount.os, "statvfs", return_value=SimpleNamespace(f_flag=0)):
            with self.assertRaises(ValueError):
                inspect_mount.validate_hardware_mount(self.mount, device)


if __name__ == "__main__":
    unittest.main()
