import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from huntmob.android_worker import AndroidSdk, AndroidWorker


class AndroidWorkerTests(unittest.TestCase):
    def setUp(self):
        self.sdk = AndroidSdk(Path("/sdk"), Path("/sdk/emulator/emulator"), Path("/sdk/adb"), Path("/sdk/avdmanager"), Path("/sdk/sdkmanager"))

    @patch("huntmob.android_worker._run")
    def test_online_status_reads_owned_emulator(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "List of devices attached\nemulator-5556\tdevice\n", ""),
            *[subprocess.CompletedProcess([], 0, value, "") for value in ("15\n", "35\n", "arm64-v8a\n", "1\n")],
        ]
        status = AndroidWorker(self.sdk).status()
        self.assertEqual(status["state"], "device")
        self.assertEqual(status["properties"]["sys.boot_completed"], "1")

    def test_missing_apk_fails_closed(self):
        result = AndroidWorker(self.sdk).install_and_launch(Path("/missing.apk"), "br.com.test.app")
        self.assertFalse(result["ok"])

    @patch.object(AndroidWorker, "status", return_value={"state": "offline"})
    def test_screenshot_fails_closed_when_device_is_offline(self, _status):
        self.assertEqual(AndroidWorker(self.sdk).screenshot(), b"")

    def test_file_browser_rejects_invalid_package(self):
        result = AndroidWorker(self.sdk).app_files("bad;package")
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])

    @patch.object(AndroidWorker, "status", return_value={"state": "offline"})
    @patch("huntmob.android_worker._run")
    def test_destroy_targets_only_fixed_avd(self, run, _status):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        result = AndroidWorker(self.sdk).destroy()
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "huntmob_api35_arm64")


if __name__ == "__main__":
    unittest.main()
