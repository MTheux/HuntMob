import json
import subprocess
import unittest
from unittest.mock import patch

from huntmob.providers import AppleSimulatorProvider, GenymotionProvider


def completed(command, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class ProviderTests(unittest.TestCase):
    @patch.object(GenymotionProvider, "executable")
    def test_genymotion_probe_is_inventory_only(self, executable):
        executable.exists.return_value = True
        commands = []

        def runner(command):
            commands.append(tuple(command))
            if "version" in command:
                return completed(command, "Version : 3.10.0")
            return completed(command, json.dumps({"devices": {}}))

        status = GenymotionProvider().probe(runner)
        self.assertTrue(status.ready)
        self.assertEqual(status.instances, 0)
        self.assertFalse(any("start" in command for command in commands))

    @patch("huntmob.providers.platform.system", return_value="Darwin")
    def test_apple_simulator_requires_installed_runtime(self, _system):
        status = AppleSimulatorProvider().probe(
            lambda command: completed(command, '{"runtimes": []}')
        )
        self.assertFalse(status.ready)
        self.assertIn("no iOS Simulator runtime", status.error)


if __name__ == "__main__":
    unittest.main()
