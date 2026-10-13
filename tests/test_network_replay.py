import json
import unittest
from unittest.mock import patch
from huntmob.network_replay import replay


class ReplayTests(unittest.TestCase):
    @patch("pathlib.Path.read_text")
    def test_external_destination_is_blocked(self, read):
        read.return_value = json.dumps({"flows": [{"id": "flow", "host": "example.com", "port": 443}]})
        result = replay({"flow_id": "flow"})
        self.assertFalse(result["ok"])
        self.assertIn("loopback", result["reason"])

    @patch("pathlib.Path.read_text")
    def test_redacted_credentials_are_not_replayed(self, read):
        read.return_value = json.dumps({"flows": [{"id": "flow", "host": "127.0.0.1", "port": 8090}]})
        result = replay({"flow_id": "flow", "method": "GET", "path": "/", "headers": {"Authorization": "[REDACTED]"}})
        self.assertFalse(result["ok"])
        self.assertIn("redigidos", result["reason"])
