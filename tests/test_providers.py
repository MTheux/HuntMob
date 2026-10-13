import json
import subprocess
import unittest
from unittest.mock import patch

from huntmob.providers import AndroidBiometricProbe, AppleSimulatorProvider, GenymotionProvider, HuntMobRuntimeProvider


def completed(command, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class ProviderTests(unittest.TestCase):
    @patch("huntmob.providers.shutil.which", return_value=None)
    def test_owned_runtime_fails_closed_without_qemu_and_adb(self, _which):
        status = HuntMobRuntimeProvider().probe()
        self.assertEqual(status.provider, "huntmob-runtime")
        self.assertFalse(status.ready)
        self.assertIn("QEMU", status.limitations)
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


if __name__ == "__main__":
    unittest.main()
