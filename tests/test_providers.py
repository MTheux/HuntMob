import json
import subprocess
import unittest
from unittest.mock import patch

from huntmob.providers import (AndroidBiometricProbe, AppleSimulatorProvider,
                               GenymotionProvider, HuntMobRuntimeProvider,
                               InfernoResearchProvider)


def completed(command, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class ProviderTests(unittest.TestCase):
    @patch("huntmob.providers.AndroidWorker")
    def test_owned_runtime_fails_closed_without_runtime(self, worker_class):
        worker_class.return_value.sdk = None
        worker_class.return_value.prerequisites.return_value = {"ready": False, "reason": "runtime missing"}
        status = HuntMobRuntimeProvider().probe()
        self.assertEqual(status.provider, "huntmob-runtime")
        self.assertFalse(status.ready)
        self.assertIn("runtime missing", status.limitations)
    @patch.object(GenymotionProvider, "executable")
    def test_genymotion_probe_is_inventory_only(self, executable):
        executable.exists.return_value = True
        commands = []

        def runner(command):
            commands.append(tuple(command))
            if "version" in command:
                return completed(command, "Version : 3.10.0")
            return completed(command, json.dumps({"instances": []}))

        status = GenymotionProvider().probe(runner)
        self.assertTrue(status.ready)
        self.assertEqual(status.instances, 0)
        self.assertFalse(any("start" in command for command in commands))

    def test_genymotion_parses_current_instances_shape(self):
        provider = GenymotionProvider()
        with patch.object(provider, "executable") as executable:
            executable.exists.return_value = True
            status = provider.probe(
                lambda command: completed(
                    command,
                    "Version : 3.10.0" if "version" in command else '{"instances":[{"name":"Lab"}]}',
                )
            )
        self.assertEqual(status.instances, 1)

    def test_biometrics_fail_closed_below_android_13(self):
        result = AndroidBiometricProbe().probe("127.0.0.1:6555", 30)
        self.assertFalse(result["supported"])
        self.assertIn("Android 13", result["reason"])

    @patch("huntmob.providers.platform.system", return_value="Darwin")
    def test_apple_simulator_requires_installed_runtime(self, _system):
        status = AppleSimulatorProvider().probe(
            lambda command: completed(command, '{"runtimes": []}')
        )
        self.assertFalse(status.ready)
        self.assertIn("no iOS Simulator runtime", status.error)

    def test_inferno_is_detected_without_being_promoted_to_ready_runtime(self):
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / "component"
            component.mkdir()
            binary = root / "qemu-system-aarch64"
            binary.write_bytes(b"pinned inferno")
            revision = "a" * 40
            (component / "upstream.json").write_text(json.dumps({"revision": revision}))
            (root / "build-receipt.json").write_text(json.dumps({
                "state": "compiled", "revision": revision, "binary": str(binary),
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            }))
            provider = InfernoResearchProvider()
            with patch.object(provider, "root", root), patch.object(provider, "component", component):
                status = provider.probe(lambda command: completed(
                    command,
                    "QEMU ChefKiss Inferno\n" if "--version" in command else "t8030 Apple T8030\n",
                ))
        self.assertTrue(status.installed)
        self.assertFalse(status.ready)
        self.assertEqual(status.kind, "research-engine")
        self.assertIn("research-only; not an Apple Simulator replacement", status.limitations)

    def test_inferno_rejects_receipt_with_changed_binary(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / "component"
            component.mkdir()
            binary = root / "qemu-system-aarch64"
            binary.write_bytes(b"changed")
            revision = "b" * 40
            (component / "upstream.json").write_text(json.dumps({"revision": revision}))
            (root / "build-receipt.json").write_text(json.dumps({
                "state": "compiled", "revision": revision, "binary": str(binary),
                "binary_sha256": "0" * 64,
            }))
            provider = InfernoResearchProvider()
            with patch.object(provider, "root", root), patch.object(provider, "component", component):
                status = provider.probe(lambda command: completed(command))
        self.assertFalse(status.installed)
        self.assertFalse(status.ready)
        self.assertIn("integrity", status.error)

    def test_inferno_uses_windows_local_app_data_receipt(self):
        provider = InfernoResearchProvider()
        with patch("huntmob.providers.platform.system", return_value="Windows"), \
                patch.dict("huntmob.providers.os.environ", {"LOCALAPPDATA": "C:/Local"}, clear=True):
            self.assertEqual(
                provider.receipt_root(),
                __import__("pathlib").Path("C:/Local/HuntMob/research/ios-engine"),
            )


if __name__ == "__main__":
    unittest.main()
