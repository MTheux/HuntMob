import unittest
from huntmob.network_capture import redact


class CaptureTests(unittest.TestCase):
    def test_credentials_are_redacted_recursively(self):
        value = {"Authorization": "secret", "Cookie": "session", "items": [{"password": "secret", "count": 3}]}
        result = redact(value)
        self.assertEqual(result["Authorization"], "[REDACTED]")
        self.assertEqual(result["Cookie"], "[REDACTED]")
        self.assertEqual(result["items"][0], {"password": "[REDACTED]", "count": 3})
