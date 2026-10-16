import copy
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_auxiliary as auxiliary


class DataV2AuxiliaryTests(unittest.TestCase):
    def setUp(self):
        self.placeholder = {"Name": "HuntMobEmptyDataSlotV2", "Roles": ["Data"], "APFSVolumeUUID": "new-data",
                            "DeviceIdentifier": "disk21s2", "Encryption": False, "CapacityInUse": 20480}
        self.system = {"Name": "Stock", "Roles": ["System"], "APFSVolumeUUID": "system", "DeviceIdentifier": "disk21s1", "Encryption": False}
        self.container = {"ContainerReference": "disk21", "Volumes": [self.system, copy.deepcopy(self.placeholder)]}
        for index, name, role in ((3, "xART", "xART"), (4, "Hardware", "Hardware"), (5, "Preboot", "Preboot")):
            self.container["Volumes"].append({"Name": name, "Roles": [role], "APFSVolumeUUID": name,
                "DeviceIdentifier": "disk21s" + str(index), "Encryption": False})

    def test_exact_new_placeholder_and_guest_roles_accepted(self):
        self.assertEqual(auxiliary.layout(self.container, self.placeholder, True), self.system)

    def test_changed_placeholder_uuid_capacity_crypto_or_mount_rejected(self):
        for key, value in (("APFSVolumeUUID", "historical"), ("CapacityInUse", 24576),
                           ("Encryption", True), ("MountPoint", "/host/Data")):
            with self.subTest(key=key):
                container = copy.deepcopy(self.container)
                container["Volumes"][1][key] = value
                with self.assertRaises(ValueError):
                    auxiliary.layout(container, self.placeholder, True)

    def test_missing_auxiliary_or_wrong_slot_rejected(self):
        for change in (lambda c: c["Volumes"].pop(),
                       lambda c: c["Volumes"][2].update(DeviceIdentifier="disk21s6"),
                       lambda c: c["Volumes"][2].update(Roles=["Data"])):
            container = copy.deepcopy(self.container)
            change(container)
            with self.assertRaises(ValueError):
                auxiliary.layout(container, self.placeholder, True)

    def test_final_layout_requires_no_data(self):
        with self.assertRaises(ValueError):
            auxiliary.layout(self.container, auxiliary=True)
        del self.container["Volumes"][1]
        self.assertEqual(auxiliary.layout(self.container, auxiliary=True), self.system)

    def test_plan_is_read_only_without_existing_cohort(self):
        for script, arguments in (("stage_ios_virtual_data_v2_auxiliary.py", ["--action", "reserve-bootstrap"]),
                                  ("stage_ios_virtual_data_v2_effaceable.py", [])):
            result = subprocess.run([sys.executable, str(Path(auxiliary.__file__).with_name(script)),
                "--vm-uuid", "2a31ad9c-aab5-4816-a69a-6f4e9ece162a", *arguments], capture_output=True, check=True)
            self.assertIn(b'"read_only": true', result.stdout)
            self.assertIn(b'"root_accessed": false', result.stdout)


if __name__ == "__main__":
    unittest.main()
