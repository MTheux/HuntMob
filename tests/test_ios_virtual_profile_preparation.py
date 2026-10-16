"""Destructive-operation guards, using metadata doubles and tiny owned files."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_ios_virtual_profile.py"
SPEC = importlib.util.spec_from_file_location("virtual_profile_preparation_under_test", SCRIPT)
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


class ProfilePreparationGuards(unittest.TestCase):
    def info(self, device="/dev/disk90", size=16):
        return {"DeviceNode": device, "DeviceIdentifier": device.removeprefix("/dev/"),
                "Whole": True, "VirtualOrPhysical": "Virtual", "BusProtocol": "Disk Image",
                "Internal": False, "Mounted": False, "TotalSize": size, "DeviceBlockSize": 4096}

    def test_asr_rejects_partition_and_nondevice(self):
        for value in ("/dev/disk0s1", "/dev/rdisk0", "/tmp/image", "/dev/disk1;echo bad", "disk1"):
            with self.assertRaises(ValueError):
                profile.asr_command(value)
        command = profile.asr_command("/dev/disk90")
        self.assertEqual(command[command.index("--source") + 1], str(profile.SOURCE))
        self.assertEqual(command[command.index("--target") + 1], "/dev/disk90")
        self.assertIn("--erase", command)
        self.assertNotIn("--noverify", command)

    def test_whole_virtual_disk_image_required(self):
        baseline = self.info(size=profile.SIZES["namespace-1.raw"])
        profile.validate_virtual_info(baseline, "/dev/disk90")
        for field, value in (("Whole", False), ("VirtualOrPhysical", "Physical"),
                             ("BusProtocol", "PCI"), ("Internal", True),
                             ("Mounted", True), ("TotalSize", 1),
                             ("DeviceBlockSize", 512),
                             ("DeviceNode", "/dev/disk1"), ("MountPoint", "/Volumes/user")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                profile.validate_virtual_info({**baseline, field: value}, "/dev/disk90")

    def test_macos_27_metadata_aliases_require_consistency(self):
        baseline = self.info(size=profile.SIZES["namespace-1.raw"])
        modern = {key: value for key, value in baseline.items() if key not in ("Whole", "TotalSize")}
        modern.update(WholeDisk=True, Size=profile.SIZES["namespace-1.raw"])
        profile.validate_virtual_info(modern, "/dev/disk90")
        with self.assertRaises(ValueError):
            profile.validate_virtual_info({**modern, "Whole": False}, "/dev/disk90")
        with self.assertRaises(ValueError):
            profile.validate_virtual_info({**modern, "TotalSize": 1}, "/dev/disk90")

    def test_attachment_requires_new_device_and_exact_backing(self):
        with tempfile.TemporaryDirectory(prefix="huntmob-prep-guard-") as directory:
            image = Path(directory) / "namespace-1.raw"
            image.write_bytes(bytes(16))
            inventory = [{"image-path": image.as_uri(),
                          "system-entities": [{"dev-entry": "/dev/disk90"}]}]
            with mock.patch.dict(profile.SIZES, {"namespace-1.raw": 16}), \
                 mock.patch.object(profile, "image_inventory", return_value=inventory), \
                 mock.patch.object(profile, "run_plist", return_value=self.info()):
                identity = profile.fingerprint(image)
                profile.verify_attachment(image, identity, "/dev/disk90", set())
                with self.assertRaises(ValueError):
                    profile.verify_attachment(image, identity, "/dev/disk90", {"/dev/disk90"})
                with self.assertRaises(ValueError):
                    profile.verify_attachment(image, identity, "/dev/disk91", set())
                wrong = [{"image-path": str(Path(directory) / "other.raw"),
                          "system-entities": [{"dev-entry": "/dev/disk90"}]}]
                with mock.patch.object(profile, "image_inventory", return_value=wrong):
                    with self.assertRaises(ValueError):
                        profile.verify_attachment(image, identity, "/dev/disk90", set())

    def test_source_symlink_and_hardlink_refused(self):
        with tempfile.TemporaryDirectory(prefix="huntmob-prep-source-") as directory:
            original = Path(directory) / "public-os"
            original.write_bytes(b"public fixture")
            actual, record = profile.digest(original)
            self.assertEqual(actual, hashlib.sha256(b"public fixture").hexdigest())
            self.assertIn("mtime_ns", record)
            alias = original.with_name("alias")
            alias.symlink_to(original)
            with self.assertRaises(ValueError):
                profile.digest(alias)
            alias.unlink()
            os.link(original, alias)
            with self.assertRaises(ValueError):
                profile.digest(original)

    def test_create_only_new_files_never_overwrites(self):
        with tempfile.TemporaryDirectory(prefix="huntmob-prep-files-") as directory:
            target = Path(directory) / "new-profile"
            tiny = {name: 16 for name in profile.SIZES}
            with mock.patch.object(profile, "check_parent"), \
                 mock.patch.object(profile.shutil, "disk_usage", return_value=mock.Mock(free=profile.MIN_START_FREE)), \
                 mock.patch.dict(profile.SIZES, tiny, clear=True):
                manifest = profile.create_cohort(target, "public-fixture-uuid", {})
                self.assertFalse(manifest["root_provisioned"])
                self.assertFalse(manifest["ready"])
                self.assertEqual(len(manifest["backings"]), 9)
                for name in tiny:
                    self.assertEqual((target / name).read_bytes(), bytes(16))
                    self.assertEqual((target / name).stat().st_nlink, 1)
                with self.assertRaises(ValueError):
                    profile.create_cohort(target, "public-fixture-uuid", {})

    def test_default_plan_executes_nothing(self):
        with tempfile.TemporaryDirectory(prefix="huntmob-prep-plan-") as directory:
            output = io.StringIO()
            arguments = [str(SCRIPT), "--vm-uuid", "d550c662-a0d4-49d5-a102-811c89e02030"]
            with mock.patch.object(profile, "VM_ROOT", Path(directory)), \
                 mock.patch.object(profile, "check_parent"), \
                 mock.patch.object(profile, "create_cohort") as create, \
                 mock.patch.object(profile.subprocess, "run", side_effect=AssertionError("must not execute")), \
                 mock.patch("sys.argv", arguments), contextlib.redirect_stdout(output):
                profile.main()
                create.assert_not_called()
            receipt = json.loads(output.getvalue())
            self.assertTrue(receipt["read_only"])
            self.assertFalse(receipt["source_hash_validation_performed"])
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
