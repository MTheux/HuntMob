import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from huntmob.android_worker import AndroidSdk, AndroidWorker


class AndroidWorkerTests(unittest.TestCase):
    def setUp(self):
        self.sdk = AndroidSdk(Path("/sdk"), Path("/sdk/emulator/emulator"), Path("/sdk/adb"), Path("/sdk/avdmanager"), Path("/sdk/sdkmanager"))

    def test_stop_waits_for_console_port_before_resume(self):
        from unittest.mock import MagicMock
        worker = AndroidWorker(self.sdk)
        online = {'state': 'device', 'attached': True, 'ownership_verified': True}
        offline = {'state': 'offline', 'attached': False}
        with patch.object(worker, 'status', side_effect=[online, offline, offline]), \
             patch('huntmob.android_worker._run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
             patch('huntmob.android_worker.socket.create_connection', side_effect=[MagicMock(), ConnectionRefusedError]), \
             patch('huntmob.android_worker.time.sleep'):
            self.assertEqual(worker.stop(), {'ok': True, 'state': 'stopped'})

    def test_arm64_catalog_covers_android_11_through_16(self):
        for api in range(30, 37):
            for mode, variant in (("root", "default"), ("stock", "google_apis_playstore")):
                with self.subTest(api=api, mode=mode), patch("huntmob.host_runtime.android_host", return_value={"supported": True, "architecture": "arm64-v8a"}):
                    worker = AndroidWorker(self.sdk, root_mode=mode, android_api=api)
                    self.assertEqual(worker.package, f"system-images;android-{api};{variant};arm64-v8a")

    @patch("huntmob.android_worker._run")
    def test_online_status_reads_owned_emulator(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "List of devices attached\nemulator-5556\tdevice\n", ""),
            subprocess.CompletedProcess([], 0, "huntmob_api35_arm64\nOK\n", ""),
            *[subprocess.CompletedProcess([], 0, value, "") for value in ("15\n", "35\n", "arm64-v8a\n", "1\n")],
        ]
        status = AndroidWorker(self.sdk).status()
        self.assertEqual(status["state"], "device")
        self.assertEqual(status["properties"]["sys.boot_completed"], "1")

    @patch("huntmob.android_worker._run", side_effect=subprocess.TimeoutExpired("adb", 5))
    def test_adb_timeout_returns_explicit_error(self, run):
        status = AndroidWorker(self.sdk).status()
        self.assertEqual(status["state"], "error")
        self.assertIn("ADB", status["reason"])

    @patch("huntmob.android_worker._run")
    def test_attached_offline_device_is_distinct_from_stopped(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "List of devices attached\nemulator-5556\toffline\n", "")
        self.assertTrue(AndroidWorker(self.sdk).status()["attached"])
        run.return_value = subprocess.CompletedProcess([], 0, "List of devices attached\n", "")
        self.assertFalse(AndroidWorker(self.sdk).status()["attached"])

    @patch("huntmob.android_worker.subprocess.Popen")
    @patch.object(AndroidWorker, "create", return_value={"ok": True})
    @patch.object(AndroidWorker, "status")
    def test_booting_device_is_not_launched_twice(self, status, create, popen):
        import tempfile
        status.side_effect = [
            {"state": "device", "attached": True, "properties": {"sys.boot_completed": "0"}},
            {"state": "device", "attached": True, "properties": {"sys.boot_completed": "1"}},
        ]
        with tempfile.TemporaryDirectory() as directory, patch("huntmob.android_worker.Path.home", return_value=Path(directory)):
            self.assertTrue(AndroidWorker(self.sdk).start()["ok"])
        popen.assert_not_called()

    def test_native_disk_failure_has_actionable_reason_and_keeps_device(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory, patch("huntmob.android_worker.Path.home",return_value=Path(directory)), patch.object(AndroidWorker,"status",return_value={"state":"offline","attached":False}), patch.object(AndroidWorker,"create",return_value={"ok":True}), patch("huntmob.android_worker.subprocess.Popen") as popen:
            def launch(*args,**kwargs):
                kwargs['stdout'].write('FATAL | Your device does not have enough disk space to run avd')
                kwargs['stdout'].flush()
                process=Mock();process.poll.return_value=1;return process
            popen.side_effect=launch
            result=AndroidWorker(self.sdk).start()
        self.assertEqual(result['error_code'],'insufficient_disk_space')
        self.assertIn('preservados',result['reason'])

    def test_host_webcam_is_passed_only_to_selected_lab_at_boot(self):
        import tempfile
        from unittest.mock import Mock
        identifier = 'huntmob_lab_' + 'c'*32
        with tempfile.TemporaryDirectory() as directory, patch('huntmob.android_worker.Path.home', return_value=Path(directory)), patch.object(AndroidWorker, 'status', return_value={'state':'offline','attached':False}), patch.object(AndroidWorker, 'create', return_value={'ok':True}), patch('huntmob.android_worker.subprocess.Popen') as popen, patch('huntmob.lab_sessions.current', return_value={'id':identifier,'camera_front':'webcam0'}):
            process=Mock(); process.poll.return_value=1; popen.return_value=process
            AndroidWorker(self.sdk, avd_name=identifier).start()
            command=popen.call_args.args[0]
        self.assertEqual(command[-2:], ('-camera-front','webcam0'))

    def test_missing_apk_fails_closed(self):
        result = AndroidWorker(self.sdk).install_and_launch(Path("/missing.apk"), "br.com.test.app")
        self.assertFalse(result["ok"])

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run")
    def test_touch_coordinates_are_mapped_to_guest_display(self, run, _status):
        run.side_effect = [subprocess.CompletedProcess([], 0, "Viewport INTERNAL: displayId=0, orientation=0, logicalFrame=[0, 0, 1080, 1920]", ""), subprocess.CompletedProcess([], 0, "", "")]
        result = AndroidWorker(self.sdk).device_input({"action": "tap", "x": 0.5, "y": 0.25})
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.args[0][-3:], ("tap", "540", "480"))

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run")
    def test_landscape_touch_uses_rotated_input_viewport(self, run, _status):
        run.side_effect = [subprocess.CompletedProcess([], 0, "Viewport INTERNAL: displayId=0, orientation=1, logicalFrame=[0, 0, 1920, 1080]", ""), subprocess.CompletedProcess([], 0, "", "")]
        self.assertTrue(AndroidWorker(self.sdk).device_input({"action":"tap", "x":0.75, "y":0.5})['ok'])
        self.assertEqual(run.call_args.args[0][-3:], ('tap','1440','540'))

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

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run", return_value=subprocess.CompletedProcess([], 0, "10.0.2.2:8080\n", ""))
    @patch("huntmob.android_worker.socket.create_connection", side_effect=ConnectionRefusedError)
    def test_proxy_status_does_not_claim_other_port_as_configured(self, _socket, _run, _status):
        with patch("huntmob.lab_sessions.current", return_value={}):
            status = AndroidWorker(self.sdk).proxy_status(8081)
        self.assertFalse(status["configured"])
        self.assertTrue(status["device_proxy_set"])

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run", return_value=subprocess.CompletedProcess([], 0, "Starting: Intent", ""))
    def test_certificate_setup_only_opens_settings(self, run, _status):
        worker = AndroidWorker(self.sdk)
        self.assertTrue(worker.open_certificate_settings()["ok"])
        command = run.call_args.args[0]
        self.assertEqual(command[-4:], ("am", "start", "-a", "android.settings.SECURITY_SETTINGS"))
        self.assertNotIn("install", command)

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run")
    def test_adb_root_requires_debug_image_and_uid_readback(self, run, _status):
        name = "huntmob_lab_" + "a" * 32
        worker = AndroidWorker(self.sdk, avd_name=name, root_mode="root")
        answers = {
            ("emu", "avd", "name"): [name + "\nOK\n", name + "\nOK\n"],
            ("shell", "id", "-u"): ["2000\n", "0\n"],
            ("shell", "getprop", "ro.build.type"): ["userdebug\n"],
            ("shell", "getprop", "ro.debuggable"): ["1\n"],
        }
        def adb(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, answers[command[3:]].pop(0) if command[3:] in answers else "", "")
        run.side_effect = adb
        self.assertTrue(worker.enable_adb_root()["ok"])
        self.assertIn(("/sdk/adb", "-s", worker.serial, "root"), [call.args[0] for call in run.call_args_list])

        run.reset_mock()
        answers = {("emu", "avd", "name"): [name + "\nOK\n"], ("shell", "id", "-u"): ["2000\n"],
                   ("shell", "getprop", "ro.build.type"): ["user\n"], ("shell", "getprop", "ro.debuggable"): ["0\n"]}
        self.assertFalse(worker.enable_adb_root()["ok"])
        self.assertFalse(any(call.args[0][-1] == "root" for call in run.call_args_list))

        run.reset_mock()
        self.assertFalse(AndroidWorker(self.sdk, avd_name=name, root_mode="stock").enable_adb_root()["ok"])
        run.assert_not_called()

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

class AndroidOwnershipTests(unittest.TestCase):
    def worker(self):
        sdk=AndroidSdk(Path('/sdk'),Path('/sdk/emulator'),Path('/sdk/adb'),Path('/sdk/avdmanager'),Path('/sdk/sdkmanager'))
        return AndroidWorker(sdk)

    def test_wrong_avd_serial_never_adopted_or_killed(self):
        with patch('huntmob.android_worker._run',side_effect=[subprocess.CompletedProcess([],0,'List of devices attached\nemulator-5556\tdevice\n',''),subprocess.CompletedProcess([],0,'unrelated-avd\nOK\n','')]) as run:
            self.assertFalse(self.worker().stop()['ok'])
            self.assertFalse(any('kill' in call.args[0] for call in run.call_args_list))

    def test_owned_identity_unavailable_is_not_online(self):
        with patch('huntmob.android_worker._run',side_effect=[subprocess.CompletedProcess([],0,'List of devices attached\nemulator-5556\tdevice\n',''),subprocess.TimeoutExpired('avd',3)]):
            result=self.worker().status()
            self.assertEqual(result['state'],'error');self.assertFalse(result['ownership_verified'])

    def test_destroy_preserves_attached_offline_device(self):
        with patch.object(AndroidWorker,'status',return_value={'state':'offline','attached':True}),patch('huntmob.android_worker._run') as run:
            self.assertFalse(self.worker().destroy()['ok'])
            run.assert_not_called()

class InstalledTargetTests(AndroidOwnershipTests):
    def test_installed_app_binds_package_and_actual_sha(self):
        import hashlib
        lab={'id':'huntmob_api35_arm64','package_id':'','apk_sha256':''}
        def adb(command,**kwargs):
            if 'pull' in command:Path(command[-1]).write_bytes(b'installed-apk')
            return subprocess.CompletedProcess(command,0,'package:/data/app/base.apk\n','')
        with patch('huntmob.lab_sessions.current',return_value=lab),patch('huntmob.lab_sessions.save') as save,patch.object(AndroidWorker,'status',return_value={'state':'device','ownership_verified':True}),patch('huntmob.android_worker._run',side_effect=adb),patch('huntmob.dynamic_runtime.DYNAMIC.stop') as stop:
            result=self.worker().select_target('com.lab.app')
            self.assertTrue(result['ok'])
            self.assertEqual(save.call_args.args[0]['apk_sha256'],hashlib.sha256(b'installed-apk').hexdigest())
            self.assertEqual(save.call_args.args[0]['package_id'],'com.lab.app')
            stop.assert_called_once()

    def test_other_app_cannot_replace_bound_target(self):
        with patch('huntmob.lab_sessions.current',return_value={'id':'huntmob_api35_arm64','package_id':'com.lab.original'}),patch('huntmob.lab_sessions.save') as save,patch('huntmob.android_worker._run') as run:
            self.assertFalse(self.worker().select_target('com.lab.other')['ok'])
            save.assert_not_called();run.assert_not_called()

    def test_disconnected_app_selection_preserves_metadata(self):
        with patch('huntmob.lab_sessions.current',return_value={'id':'huntmob_api35_arm64','package_id':''}),patch.object(AndroidWorker,'status',return_value={'state':'error'}),patch('huntmob.lab_sessions.save') as save,patch('huntmob.android_worker._run') as run:
            self.assertFalse(self.worker().select_target('com.lab.app')['ok'])
            save.assert_not_called();run.assert_not_called()

    def test_absent_app_never_saves_empty_hash(self):
        with patch('huntmob.lab_sessions.current',return_value={'id':'huntmob_api35_arm64','package_id':''}),patch.object(AndroidWorker,'status',return_value={'state':'device'}),patch('huntmob.android_worker._run',return_value=subprocess.CompletedProcess([],0,'','')),patch('huntmob.lab_sessions.save') as save:
            self.assertFalse(self.worker().select_target('com.lab.app')['ok'])
            save.assert_not_called()
