import unittest
from unittest.mock import patch

from huntmob.bootstrap import bootstrap_android


class BootstrapTests(unittest.TestCase):
    @patch("huntmob.bootstrap.AndroidSdk.discover", return_value=None)
    @patch("huntmob.bootstrap.platform.system", return_value="Darwin")
    def test_mac_without_sdk_returns_one_command(self, _system, _discover):
        result = bootstrap_android()
        self.assertFalse(result["ok"])
        self.assertIn("brew install", result["next"])

    @patch("huntmob.bootstrap.AndroidSdk.discover", return_value=None)
    @patch("platform.machine", return_value="x86_64")
    @patch("huntmob.bootstrap.platform.system", return_value="Linux")
    def test_linux_uses_available_native_sdk_without_unpublished_image(self, _system, _machine, _sdk):
        result = bootstrap_android()
        self.assertEqual(result["mode"], "native")
        self.assertIn("/dev/kvm", result["next"])


if __name__ == "__main__":
    unittest.main()
