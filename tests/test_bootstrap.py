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

    @patch("huntmob.bootstrap.platform.system", return_value="Linux")
    def test_linux_routes_to_docker_kvm(self, _system):
        result = bootstrap_android()
        self.assertEqual(result["mode"], "docker-kvm")
        self.assertIn("/dev/kvm", result["next"])


if __name__ == "__main__":
    unittest.main()
