import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_effaceable as effaceable


class DataV2RamdiskOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.image = Path(self.temporary.name) / "copy.raw"
        self.image.write_bytes(b"public-fixture")
        self.identity = effaceable.profile.fingerprint(self.image)
        self.mount = Path(self.temporary.name) / "mount"
        self.inventory = [{"image-path": str(self.image), "system-entities": [{"dev-entry": "/dev/disk99", "mount-point": str(self.mount)}]}]
        self.info = {"DeviceNode": "/dev/disk99", "DeviceIdentifier": "disk99", "Whole": True,
            "TotalSize": effaceable.SOURCE_BYTES, "VirtualOrPhysical": "Virtual", "BusProtocol": "Disk Image",
            "Internal": False, "Mounted": True, "MountPoint": str(self.mount), "FilesystemType": "hfs"}

    def verify(self, before=None):
        with mock.patch.object(effaceable.profile, "image_inventory", return_value=self.inventory), \
             mock.patch.object(effaceable, "mount_device_matches", return_value=True), \
             mock.patch.object(effaceable.profile, "run_plist", return_value=self.info):
            effaceable.verify_ramdisk_attachment(self.image, self.identity, "/dev/disk99", before or set(), self.mount)

    def test_new_owned_ramdisk_accepts(self):
        self.verify()

    def test_mounted_key_omitted_accepts_only_with_actual_device_binding(self):
        del self.info["Mounted"]
        self.verify()
        with mock.patch.object(effaceable.profile, "image_inventory", return_value=self.inventory), \
             mock.patch.object(effaceable.profile, "run_plist", return_value=self.info), \
             mock.patch.object(effaceable, "mount_device_matches", return_value=False):
            with self.assertRaises(ValueError):
                effaceable.verify_ramdisk_attachment(self.image, self.identity, "/dev/disk99", set(), self.mount)

    def test_inventory_mount_contradiction_rejected(self):
        self.inventory[0]["system-entities"][0]["mount-point"] = "/foreign"
        with self.assertRaises(ValueError):
            self.verify()

    def test_existing_device_or_wrong_inventory_refused(self):
        with self.assertRaises(ValueError):
            self.verify({"/dev/disk99"})
        self.inventory[0]["image-path"] = str(self.image.with_name("foreign.raw"))
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.verify()

    def test_wrong_size_mount_or_physical_device_refused(self):
        for key, value in (("TotalSize", 4096), ("MountPoint", "/foreign"), ("VirtualOrPhysical", "Physical"),
                           ("Internal", True), ("Whole", False), ("Mounted", False)):
            with self.subTest(key=key):
                old = self.info[key]
                self.info[key] = value
                with self.assertRaises(ValueError):
                    self.verify()
                self.info[key] = old

    def test_replaced_image_inode_refused(self):
        replacement = self.image.with_name("replacement")
        replacement.write_bytes(b"public-fixture")
        replacement.replace(self.image)
        with self.assertRaises(ValueError):
            self.verify()


if __name__ == "__main__":
    unittest.main()
