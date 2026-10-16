"""Pure staging guards; no attached device or Apple firmware is needed."""
import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("virtual_stage_under_test", ROOT / "scripts/stage_ios_virtual_profile.py")
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


def tlv(tag, value):
    if len(value) < 128:
        length = bytes([len(value)])
    else:
        length = b"\x82" + len(value).to_bytes(2, "big")
    return bytes([tag]) + length + value


class VirtualStagingGuards(unittest.TestCase):
    def stock(self):
        entry = bytes(range(20)) + b"\x02\x00"
        data = struct.pack("<I", 1) + bytes(16) + struct.pack("<I", 1) + entry
        return tlv(0x30, tlv(0x16, b"IM4P") + tlv(0x16, b"rtsc") + tlv(0x16, b"1") + tlv(4, data)), entry

    def test_trustcache_keeps_stock_and_adds_only_owned_hash(self):
        stock, entry = self.stock()
        result = stage.merged_trustcache(stock, ["ab" * 20], "52c79047-1d89-4a97-bf6b-cc2d6b9d742c")
        self.assertEqual(struct.unpack_from("<I", result)[0], 1)
        self.assertEqual(struct.unpack_from("<I", result, 20)[0], 2)
        self.assertEqual(len(result), 24 + 2 * 22)
        self.assertIn(entry, [result[24:46], result[46:68]])
        self.assertIn(bytes.fromhex("ab" * 20) + b"\x02\x00", result)
        with self.assertRaises(ValueError):
            stage.merged_trustcache(stock, ["not a cdhash"], "52c79047-1d89-4a97-bf6b-cc2d6b9d742c")

    def test_trustcache_rejects_extra_data(self):
        stock, _ = self.stock()
        with self.assertRaises(ValueError):
            stage.trustcache_entries(stock + b"extra")

    def test_exact_five_service_changes(self):
        daemons = {"/System/Library/LaunchDaemons/" + label + ".plist": {"Label": label}
                   for label in stage.SERVICES}
        daemons["other"] = {"Label": "com.huntmob.untouched", "Disabled": False}
        result = stage.disable_services({"LaunchDaemons": daemons})
        self.assertFalse(result["LaunchDaemons"]["other"]["Disabled"])
        self.assertEqual(sum(entry.get("Disabled") is True for entry in daemons.values()), 5)
        with self.assertRaises(ValueError):
            stage.disable_services({"LaunchDaemons": {"other": daemons["other"]}})

    def test_symlink_parent_cannot_escape_guest_root(self):
        with tempfile.TemporaryDirectory(prefix="huntmob-stage-guard-") as directory:
            root = Path(directory)
            (root / "usr").symlink_to("/usr")
            with self.assertRaises(ValueError):
                stage.safe_path(root, "usr/libexec/owned-helper")

    def test_data_volume_and_foreign_physical_store_rejected(self):
        system = {"DeviceIdentifier": "disk10s1", "Roles": ["System"], "Encryption": False}
        owned = {"PhysicalStores": [{"DeviceIdentifier": "disk9s1"}], "Volumes": [system]}
        with mock.patch.object(stage.profile, "run_plist", return_value={"Containers": [owned]}):
            self.assertEqual(stage.owned_system("/dev/disk9"), "/dev/disk10s1")
        with mock.patch.object(stage.profile, "run_plist", return_value={"Containers": [{
            **owned, "Volumes": [system, {"Roles": ["Data"]}]}]}):
            with self.assertRaises(ValueError):
                stage.owned_system("/dev/disk9")
        with mock.patch.object(stage.profile, "run_plist", return_value={"Containers": [{
            **owned, "PhysicalStores": [{"DeviceIdentifier": "disk90s1"}]}]}):
            with self.assertRaises(ValueError):
                stage.owned_system("/dev/disk9")


if __name__ == "__main__":
    unittest.main()
