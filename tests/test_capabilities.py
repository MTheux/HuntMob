import unittest

from huntmob.capabilities import capability_catalog


class CapabilityContractTests(unittest.TestCase):
    def test_every_provider_exposes_rea_evidence_contract(self):
        profiles = capability_catalog()
        self.assertTrue(profiles)
        for profile in profiles:
            self.assertIn("rea-static", profile["capabilities"])
            self.assertIn("rea-dynamic-evidence", profile["capabilities"])

    def test_apple_simulator_is_not_marked_privileged(self):
        profile = next(
            item for item in capability_catalog()
            if item["provider"] == "apple-simulator-worker"
        )
        self.assertFalse(profile["privileged"])
        self.assertNotIn("frida", profile["capabilities"])

    def test_owned_runtime_is_android_only(self):
        profile = next(
            item for item in capability_catalog()
            if item["provider"] == "huntmob-runtime"
        )
        self.assertEqual(profile["platform"], "android")
        self.assertTrue(any("Clean-room" in note for note in profile["notes"]))


if __name__ == "__main__":
    unittest.main()
