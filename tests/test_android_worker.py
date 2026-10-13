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

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run")
    def test_touch_coordinates_are_mapped_to_guest_display(self, run, _status):
        run.side_effect = [subprocess.CompletedProcess([], 0, "Physical size: 1080x1920", ""), subprocess.CompletedProcess([], 0, "", "")]
        result = AndroidWorker(self.sdk).device_input({"action": "tap", "x": 0.5, "y": 0.25})
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.args[0][-3:], ("tap", "540", "480"))

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    def test_text_input_rejects_shell_metacharacters(self, _status):
        self.assertFalse(AndroidWorker(self.sdk).device_input({"action": "text", "text": "$(id)"})["ok"])

    @patch.object(AndroidWorker, "status", return_value={"state": "offline"})
    def test_screenshot_fails_closed_when_device_is_offline(self, _status):
        self.assertEqual(AndroidWorker(self.sdk).screenshot(), b"")

    def test_file_browser_rejects_invalid_package(self):
        result = AndroidWorker(self.sdk).app_files("bad;package")
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run")
    def test_installed_apps_returns_only_parsed_package_ids(self, run, _status):
        run.return_value = subprocess.CompletedProcess([], 0, "package:/data/app/base.apk=br.com.test.app\ninvalid\n", "")
        result = AndroidWorker(self.sdk).installed_apps()
        self.assertTrue(result["ok"])
        self.assertEqual(result["apps"][0]["package_id"], "br.com.test.app")

    def test_proxy_rejects_privileged_port(self):
        result = AndroidWorker(self.sdk).configure_proxy(80)
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])

    def test_reverse_rejects_invalid_package(self):
        result = AndroidWorker(self.sdk).prepare_reverse("bad;package")
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
