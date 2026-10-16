import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_effaceable as e
import ios_virtual_data_v2_contract as c


class EffaceablePrewriteRetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name)
        self.build = self.target / e.ORIGINAL_BUILD
        self.build.mkdir()
        self.image = self.build / "RestoreRamDisk.raw"
        with self.image.open("wb") as stream:
            stream.truncate(e.SOURCE_BYTES)
        self.mount = self.build / "mount"
        for directory in ("usr/libexec", "usr/bin", "System/Library/LaunchDaemons"):
            (self.mount / directory).mkdir(parents=True, exist_ok=True)
        (self.target / "data-v2-effaceable-intent.json").write_text("{}")
        for name in e.PINS:
            (self.build / name).write_text("public-source-fixture")
        self.source = self.target / "public-source"
        self.source.write_text("public-source")
        self.manifest = {"vm_uuid": "new", "effaceable_ramdisk_v2": {"schema": e.SCHEMA,
            "vm_uuid": "new", "profile": c.PROFILE, "state": "preparing", "prepared": False,
            "source_sha256": e.PINS, "public_original_sha256": e.SOURCE_SHA}}

    def evidence(self):
        inventory = [{"image-path": str(self.image), "system-entities": [{"dev-entry": "/dev/disk99"}]}]
        def digest(path):
            if path.name in e.PINS:
                return e.PINS[path.name]
            if path.name == "nvmefwupdater":
                return e.UTILITY_SHA
            return e.SOURCE_SHA
        with mock.patch.object(e, "SOURCE", self.source), mock.patch.object(e, "fresh_ns6"), \
             mock.patch.object(e, "verify_ramdisk_attachment"), mock.patch.object(e.profile, "image_inventory", return_value=inventory), \
             mock.patch.object(e.stage, "digest", side_effect=digest):
            return e.prewrite_cleanup_evidence(self.target, self.manifest)

    def test_only_unmodified_preparing_copy_can_clean(self):
        value = self.evidence()
        self.assertEqual(value["device"], "/dev/disk99")
        self.assertFalse(value["root_recreated"])
        self.assertEqual(value["preparing_record_sha256"], c.canonical_hash(self.manifest["effaceable_ramdisk_v2"]))

    def test_any_guest_mutation_blocks_cleanup(self):
        for relative in ("usr/libexec/huntmob-initialize-effaceable", "usr/libexec/huntmob-virtual-sep-v1",
                         "System/Library/LaunchDaemons/com.huntmob.effaceable-init.plist"):
            path = self.mount / relative
            path.write_text("installed")
            with self.assertRaises(ValueError):
                self.evidence()
            path.unlink()
        path = self.build / "com.apple.restored_external.plist.original"
        path.write_text("saved-before-mutation")
        with self.assertRaises(ValueError):
            self.evidence()

    def test_launch_or_previous_cleanup_blocks_retry(self):
        for filename in (".data-v2-launch.lock", "data-v2-effaceable-cleanup-intent.json"):
            path = self.target / filename
            path.write_text("exists")
            with self.assertRaises(ValueError):
                self.evidence()
            path.unlink()
        self.manifest["effaceable_ramdisk_v2"]["observation"] = "guest-was-requested"
        with self.assertRaises(ValueError):
            self.evidence()


if __name__ == "__main__":
    unittest.main()
