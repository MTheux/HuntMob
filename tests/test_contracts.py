import unittest

from huntmob.contracts import EngagementGate, Platform


class EngagementGateTests(unittest.TestCase):
    def test_active_action_fails_closed_without_approval(self):
        gate = EngagementGate(
            engagement_id="lab-1",
            platform=Platform.ANDROID,
            package_id="com.example.lab",
            authorized=True,
            allowed_actions=["install"],
        )
        self.assertTrue(gate.authorize("install")["blocked"])

    def test_inventory_can_run_when_authorized_and_allowlisted(self):
        gate = EngagementGate(
            engagement_id="lab-1",
            platform=Platform.IOS,
            package_id="com.example.lab",
            authorized=True,
            allowed_actions=["inventory"],
        )
        self.assertTrue(gate.authorize("inventory")["ok"])

    def test_unknown_action_is_blocked(self):
        gate = EngagementGate("lab-1", Platform.ANDROID, "com.example.lab", True, True, [])
        self.assertTrue(gate.authorize("shell")["blocked"])


if __name__ == "__main__":
    unittest.main()

