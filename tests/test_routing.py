import unittest

from huntmob.contracts import Platform
from huntmob.routing import select_runtime


class RuntimeRoutingTests(unittest.TestCase):
    def test_ios_on_windows_routes_to_remote_mac(self):
        plan = select_runtime(Platform.IOS, controller_os="windows")
        self.assertEqual(plan.provider, "apple-simulator-worker")

    def test_android_routes_to_owned_huntmob_runtime(self):
        plan = select_runtime(Platform.ANDROID, controller_os="linux")
        self.assertEqual(plan.provider, "huntmob-runtime")
        self.assertEqual(plan.confidence, "theoretical")
        self.assertEqual(plan.execution_location, "local")

    def test_privileged_ios_routes_to_corellium(self):
        plan = select_runtime(
            Platform.IOS, controller_os="linux", privileged_ios=True
        )
        self.assertEqual(plan.provider, "corellium")

    def test_physical_ios_routes_to_real_device(self):
        plan = select_runtime(
            Platform.IOS, controller_os="darwin", physical_hardware=True
        )
        self.assertEqual(plan.provider, "real-device-cloud")


if __name__ == "__main__":
    unittest.main()
