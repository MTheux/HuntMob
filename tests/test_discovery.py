import unittest
from unittest.mock import patch

from huntbox_mob.discovery import runtime_status


class DiscoveryTests(unittest.TestCase):
    @patch("huntbox_mob.discovery.shutil.which")
    def test_status_is_read_only(self, which):
        which.side_effect = lambda name: f"/tools/{name}" if name == "adb" else None
        result = runtime_status()
        self.assertEqual(result["network_requests"], 0)
        self.assertFalse(result["device_contacted"])


if __name__ == "__main__":
    unittest.main()

