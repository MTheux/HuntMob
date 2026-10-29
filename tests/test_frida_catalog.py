import unittest

from huntmob.contracts import EngagementGate, Platform
from huntmob.frida_catalog import CATALOG, build_frida_job, validate_package_id


class FridaCatalogTests(unittest.TestCase):
    def gate(self, **overrides):
        values = dict(
            engagement_id="eng-lab",
            platform=Platform.ANDROID,
            package_id="br.com.huntmob.demo",
            authorized=True,
            human_approved=True,
            allowed_actions=["frida.execute"],
        )
        values.update(overrides)
        return EngagementGate(**values)

    def test_valid_package_builds_worker_only_job(self):
        job = build_frida_job(self.gate(), "br.com.huntmob.demo", ["tls-observe"])
        self.assertTrue(job["ok"])
        self.assertEqual(job["execution"], "worker-only")
        self.assertFalse(job["raw_shell"])

    def test_package_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_package_id("br.com.demo; id")

    def test_cross_package_execution_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "authorized engagement"):
            build_frida_job(self.gate(), "br.com.other.app", ["tls-observe"])

    def test_active_script_requires_human_approval(self):
        job = build_frida_job(
            self.gate(human_approved=False),
            "br.com.huntmob.demo",
            ["tls-lab-override"],
        )
        self.assertTrue(job["blocked"])

    def test_curated_bypass_scripts_are_catalogued_as_modify_high(self):
        indexed = {script.script_id: script for script in CATALOG}
        curated = ["tls-unpin-multi", "root-jailbreak-bypass", "anti-frida-bypass", "rasp-bypass"]
        for script_id in curated:
            self.assertIn(script_id, indexed, script_id)
            self.assertEqual(indexed[script_id].mode, "modify", script_id)
            self.assertEqual(indexed[script_id].risk, "high", script_id)
        # o preset de RASP fica marcado como entrada do operador para plugar o script dele
        self.assertEqual(indexed["rasp-bypass"].source, "operator-preset")

    def test_curated_bypass_builds_under_approved_gate(self):
        job = build_frida_job(
            self.gate(),
            "br.com.huntmob.demo",
            ["tls-unpin-multi", "root-jailbreak-bypass"],
        )
        self.assertTrue(job["ok"])
        self.assertEqual({s["script_id"] for s in job["scripts"]}, {"tls-unpin-multi", "root-jailbreak-bypass"})


if __name__ == "__main__":
    unittest.main()
