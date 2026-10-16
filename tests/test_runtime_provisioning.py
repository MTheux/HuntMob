import unittest

from huntmob.runtime_provisioning import DeviceRecipe, provision_plan


class RuntimeProvisioningTests(unittest.TestCase):
    def test_linux_worker_runs_natively_with_optional_docker_and_kvm(self):
        plan = provision_plan(DeviceRecipe("pixel-lab", 35, "x86_64"), "linux")
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution"], "native-worker")
        self.assertTrue(plan['docker']['optional'])
        self.assertEqual(plan["accelerator"], "kvm")
        self.assertEqual(plan["docker"]["required_devices"], ["/dev/kvm"])

    def test_mac_worker_stays_native_for_hvf(self):
        plan = provision_plan(DeviceRecipe("pixel-lab", 35, "arm64"), "darwin")
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution"], "native-worker")
        self.assertEqual(plan["accelerator"], "hvf")
        self.assertFalse(plan["docker"]["supported"])

    def test_old_api_is_blocked_for_owned_biometric_hal(self):
        plan = provision_plan(DeviceRecipe("pixel-lab", 30, "arm64"), "linux")
        self.assertFalse(plan["ok"])
        self.assertIn("API 33", plan["errors"][0])


if __name__ == "__main__":
    unittest.main()
