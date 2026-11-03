"""The desktop launcher must not announce a stale operator-connect UI."""

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run-platform.py"
SPEC = importlib.util.spec_from_file_location("huntmob_run_platform", SCRIPT)
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)


class GatewayCheckoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "web").mkdir()
        self.script = self.root / "web" / "operator-session.js"
        self.script.write_bytes(b"const operatorRequired = () => new Error('remote only');")

    def check(self, status, served):
        responses = [io.BytesIO(json.dumps(status).encode()), io.BytesIO(served)]
        with patch.object(LAUNCHER, "ROOT", self.root), patch.object(
            LAUNCHER, "urlopen", side_effect=responses
        ):
            return LAUNCHER.gateway_matches_checkout()

    def test_current_local_gateway_matches_checkout(self):
        self.assertTrue(self.check(
            {"ok": True, "authenticated": True, "operator": False},
            self.script.read_bytes(),
        ))

    def test_old_image_or_operator_gate_cannot_be_announced_ready(self):
        local = {"ok": True, "authenticated": True, "operator": False}
        self.assertFalse(self.check(local, b"old operator connect screen"))
        self.assertFalse(self.check(
            {"ok": True, "authenticated": False, "operator": True},
            self.script.read_bytes(),
        ))

    def test_old_checkout_is_rejected_before_opening_browser(self):
        self.script.write_bytes(b"Abra o endere\xc3\xa7o privado gerado")
        with patch.object(LAUNCHER, "ROOT", self.root):
            with self.assertRaisesRegex(RuntimeError, "checkout ainda"):
                LAUNCHER.gateway_matches_checkout()


if __name__ == "__main__":
    unittest.main()
