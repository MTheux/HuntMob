import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from huntmob.android_worker import AndroidSdk, AndroidWorker, _batch_wrap, _adb_devices


class BatchWrapTests(unittest.TestCase):
    def test_windows_bat_tools_run_through_cmd(self):
        with patch("huntmob.android_worker.platform.system", return_value="Windows"):
            wrapped = _batch_wrap([Path("C:/sdk/cmdline-tools/latest/bin/avdmanager.bat"), "create"])
        self.assertEqual(wrapped[0], "cmd")
        self.assertEqual(wrapped[1], "/c")
        self.assertEqual(wrapped[-1], "create")

    def test_windows_exe_tools_run_directly(self):
        with patch("huntmob.android_worker.platform.system", return_value="Windows"):
            self.assertEqual(_batch_wrap([Path("C:/sdk/platform-tools/adb.exe"), "devices"]),
                             [Path("C:/sdk/platform-tools/adb.exe"), "devices"])

    def test_posix_tools_run_directly(self):
        with patch("huntmob.android_worker.platform.system", return_value="Linux"):
            self.assertEqual(_batch_wrap(["/sdk/adb", "devices"]), ["/sdk/adb", "devices"])


class AndroidWorkerTests(unittest.TestCase):
    def setUp(self):
        self.sdk = AndroidSdk(Path("/sdk"), Path("/sdk/emulator/emulator"), Path("/sdk/adb"), Path("/sdk/avdmanager"), Path("/sdk/sdkmanager"))

    def test_desktop_graphics_and_stock_memory_do_not_inherit_disabled_avd_gpu(self):
        for system, gpu in [('Darwin', 'host'), ('Windows', 'host'), ('Linux', 'auto')]:
            with self.subTest(system=system), patch.dict('os.environ', {}, clear=True), patch('huntmob.android_worker.platform.system', return_value=system):
                options = AndroidWorker(self.sdk, root_mode='stock').emulator_options()
                self.assertEqual(options, ('-gpu', gpu, '-memory', '4096'))

    def test_graphics_fallback_and_memory_are_explicit_and_bounded(self):
        worker = AndroidWorker(self.sdk, root_mode='root')
        with patch.dict('os.environ', {'HUNTMOB_ANDROID_GPU': 'software', 'HUNTMOB_ANDROID_MEMORY_MB': '2048'}):
            self.assertEqual(worker.emulator_options(), ('-gpu', 'software', '-memory', '2048'))
        for key, value in [('HUNTMOB_ANDROID_GPU', 'arbitrary'), ('HUNTMOB_ANDROID_MEMORY_MB', '0'), ('HUNTMOB_ANDROID_MEMORY_MB', '999999'), ('HUNTMOB_ANDROID_MEMORY_MB', '4G')]:
            with self.subTest(key=key, value=value), patch.dict('os.environ', {key: value}):
                with self.assertRaises(ValueError): worker.emulator_options()

    def test_reconcile_stops_orphan_huntmob_emulator_and_frees_port(self):
        worker = AndroidWorker(self.sdk)
        orphan = 'huntmob_lab_' + 'b' * 32
        calls = []
        def run(command, **kwargs):
            calls.append(tuple(command))
            if command[-2:] == ('avd', 'name'):
                return subprocess.CompletedProcess(command, 0, orphan + '\n', '')
            return subprocess.CompletedProcess(command, 0, 'OK\n', '')
        with patch('huntmob.android_worker._run', side_effect=run), \
             patch('huntmob.android_worker.socket.create_connection', side_effect=ConnectionRefusedError), \
             patch('huntmob.android_worker.time.sleep'):
            self.assertTrue(worker._reconcile_port_owner())
        self.assertIn(('/sdk/adb', '-s', 'emulator-5556', 'emu', 'kill'), calls)

    def test_reconcile_never_touches_a_non_huntmob_or_same_avd(self):
        worker = AndroidWorker(self.sdk)
        def run_for(name):
            calls = []
            def run(command, **kwargs):
                calls.append(tuple(command))
                if command[-2:] == ('avd', 'name'):
                    return subprocess.CompletedProcess(command, 0, name + '\n', '')
                return subprocess.CompletedProcess(command, 0, 'OK\n', '')
            return run, calls
        # mesmo AVD selecionado: nada a reconciliar
        run, calls = run_for(worker.avd_name)
        with patch('huntmob.android_worker._run', side_effect=run):
            self.assertFalse(worker._reconcile_port_owner())
        self.assertFalse(any(c[-1] == 'kill' for c in calls))
        # AVD de terceiro (não HuntMob): nunca mata
        run, calls = run_for('Pixel_7_API_34')
        with patch('huntmob.android_worker._run', side_effect=run):
            self.assertFalse(worker._reconcile_port_owner())
        self.assertFalse(any(c[-1] == 'kill' for c in calls))

    def test_old_target_sdk_detected_from_badging(self):
        from huntmob.android_worker import _old_target_sdk
        self.assertTrue(_old_target_sdk("package: name='a'\nsdkVersion:'14'\ntargetSdkVersion:'19'\n"))
        self.assertTrue(_old_target_sdk("targetSdkVersion:'23'"))
        self.assertFalse(_old_target_sdk("targetSdkVersion:'24'"))
        self.assertFalse(_old_target_sdk("targetSdkVersion:'34'"))
        self.assertFalse(_old_target_sdk("package: name='a' (sem targetSdkVersion)"))

    def test_boot_wait_recovers_a_stale_transport_reporting_the_old_avd(self):
        import time
        worker = AndroidWorker(self.sdk)
        mismatch = {'state': 'error', 'ownership_verified': False,
                    'reason': 'O serial ADB pertence a outro AVD. Reconecte o laboratório selecionado.'}
        booted = {'state': 'device', 'properties': {'sys.boot_completed': '1'}}
        statuses = [mismatch] * 10 + [booted]
        calls = []
        def run(command, **kwargs):
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(worker, 'status', side_effect=statuses), \
             patch('huntmob.android_worker._run', side_effect=run), \
             patch('huntmob.android_worker.time.sleep'):
            result = worker._await_boot(None, Path('/x'), 0, time.monotonic() + 180)
        self.assertTrue(result['ok'])
        self.assertIn(('/sdk/adb', 'kill-server'), calls)

    def test_quickboot_on_api35_omits_no_snapshot_save(self):
        worker = AndroidWorker(self.sdk, android_api=35)
        with patch.dict('os.environ', {}, clear=True):
            command = worker._launch_command(('-gpu', 'host'), ())
        self.assertNotIn('-no-snapshot-save', command)
        self.assertNotIn('-writable-system', command)

    def test_api30_keeps_cold_boot_for_writable_system(self):
        worker = AndroidWorker(self.sdk, android_api=30)
        with patch.dict('os.environ', {}, clear=True):
            command = worker._launch_command(('-gpu', 'host'), ())
        self.assertIn('-no-snapshot-save', command)
        self.assertIn('-writable-system', command)

    def test_quickboot_env_opt_out_forces_clean_cold_boot(self):
        worker = AndroidWorker(self.sdk, android_api=35)
        with patch.dict('os.environ', {'HUNTMOB_ANDROID_QUICKBOOT': '0'}):
            command = worker._launch_command(('-gpu', 'host'), ())
        self.assertIn('-no-snapshot-save', command)

    def test_reboot_recovers_a_wedged_adb_server_before_timing_out(self):
        worker = AndroidWorker(self.sdk)
        booted = {'state': 'device', 'attached': True, 'ownership_verified': True, 'properties': {'sys.boot_completed': '1'}}
        offline = {'state': 'offline', 'attached': False}
        statuses = [booted] + [offline] * 10 + [booted]
        calls = []
        def run(command, **kwargs):
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(worker, 'status', side_effect=statuses), \
             patch('huntmob.android_worker._run', side_effect=run), \
             patch('huntmob.android_worker.time.sleep'):
            result = worker.reboot()
        self.assertTrue(result['ok'])
        self.assertTrue(result['recovered'])
        self.assertIn(('/sdk/adb', 'kill-server'), calls)
        self.assertIn(('/sdk/adb', 'start-server'), calls)

    def test_reboot_does_not_bounce_adb_when_device_comes_back_cleanly(self):
        worker = AndroidWorker(self.sdk)
        booted = {'state': 'device', 'attached': True, 'ownership_verified': True, 'properties': {'sys.boot_completed': '1'}}
        offline = {'state': 'offline', 'attached': False}
        statuses = [booted, offline, booted]
        calls = []
        def run(command, **kwargs):
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(worker, 'status', side_effect=statuses), \
             patch('huntmob.android_worker._run', side_effect=run), \
             patch('huntmob.android_worker.time.sleep'):
            result = worker.reboot()
        self.assertTrue(result['ok'])
        self.assertFalse(result['recovered'])
        self.assertNotIn(('/sdk/adb', 'kill-server'), calls)

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

    @patch("huntmob.android_worker._run")
    def test_shutdown_checks_ownership_without_querying_android_properties(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, 'List of devices attached\nemulator-5556\tdevice\n', ''),
            subprocess.CompletedProcess([], 0, 'huntmob_api35_arm64\nOK\n', ''),
            subprocess.CompletedProcess([], 0, '', ''),
            subprocess.CompletedProcess([], 0, 'List of devices attached\n', ''),
        ]
        with patch('huntmob.android_worker.socket.create_connection', side_effect=ConnectionRefusedError):
            result = AndroidWorker(self.sdk).stop()
        self.assertTrue(result['ok'])
        self.assertEqual(len(run.call_args_list), 4)
        self.assertEqual(run.call_args_list[1].args[0][-3:], ('emu', 'avd', 'name'))
        self.assertEqual(run.call_args_list[2].args[0][-2:], ('emu', 'kill'))
        self.assertFalse(any('getprop' in call.args[0] for call in run.call_args_list))

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

    @patch("huntmob.android_worker.time.sleep")
    @patch.object(AndroidWorker, "status", return_value={"state": "device", "properties": {"ro.build.version.sdk": "35"}})
    @patch("huntmob.android_worker._run")
    def test_legacy_install_grants_permissions_and_requires_stable_pid(self, run, _status, _sleep):
        import tempfile
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "Success\n", ""),
            subprocess.CompletedProcess([], 0, "br.com.test.app/.MainActivity\n", ""),
            subprocess.CompletedProcess([], 0, "Starting: Intent\n", ""),
            subprocess.CompletedProcess([], 0, " PID NAME\n4329 br.com.test.app:launcher\n", ""),
            subprocess.CompletedProcess([], 0, " PID NAME\n4329 br.com.test.app:launcher\n", ""),
        ]
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "app.apk"; apk.write_bytes(b"apk")
            result = AndroidWorker(self.sdk).install_and_launch(apk, "br.com.test.app", legacy_sdk=True, grant_permissions=True)
        self.assertTrue(result["launched"])
        self.assertEqual(result["pid"], "4329")
        self.assertEqual(run.call_args_list[0].args[0][3:7], ("install", "-r", "-g", "--bypass-low-target-sdk-block"))

    @patch.object(AndroidWorker, "launch_app", return_value={"ok": True, "installed": True, "launched": True})
    @patch.object(AndroidWorker, "status", return_value={"state": "device", "properties": {"ro.build.version.sdk": "35"}})
    @patch("huntmob.android_worker._run", return_value=subprocess.CompletedProcess([], 0, "Success\n", ""))
    def test_legacy_bypass_does_not_implicitly_grant_permissions(self, run, _status, _launch):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "app.apk"; apk.write_bytes(b"apk")
            result = AndroidWorker(self.sdk).install_and_launch(apk, "br.com.test.app", legacy_sdk=True)
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertIn("--bypass-low-target-sdk-block", command)
        self.assertNotIn("-g", command)

    @patch("huntmob.android_worker.time.sleep")
    @patch("huntmob.android_worker._run")
    def test_launch_fails_when_process_does_not_remain_alive(self, run, _sleep):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "br.com.test.app/.MainActivity\n", ""),
            subprocess.CompletedProcess([], 0, "Starting: Intent\n", ""),
            *[subprocess.CompletedProcess([], 0, "PID NAME\n", "") for _ in range(10)],
        ]
        result = AndroidWorker(self.sdk).launch_app("br.com.test.app")
        self.assertFalse(result["ok"])
        self.assertIn("did not remain alive", result["reason"])

    @patch("huntmob.android_worker.time.sleep")
    @patch("huntmob.android_worker._run")
    def test_launch_accepts_persistent_main_process_while_service_changes(self, run, _sleep):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "br.com.test.app/.MainActivity\n", ""),
            subprocess.CompletedProcess([], 0, "Starting: Intent\n", ""),
            subprocess.CompletedProcess([], 0, "PID NAME\n4329 br.com.test.app\n4400 br.com.test.app:worker\n", ""),
            subprocess.CompletedProcess([], 0, "PID NAME\n4329 br.com.test.app\n4401 br.com.test.app:worker\n", ""),
        ]
        result = AndroidWorker(self.sdk).launch_app("br.com.test.app")
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], "4329")

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

    def test_read_app_file_rejects_invalid_package(self):
        result = AndroidWorker(self.sdk).read_app_file("bad;pkg", "sandbox", "./files/x")
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    def test_read_app_file_rejects_unknown_source(self, _status):
        result = AndroidWorker(self.sdk).read_app_file("com.acme.app", "weird", "x")
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    def test_read_sandbox_file_rejects_unsafe_path(self, _status):
        for bad in ["../../etc/passwd", "files/$(id)", "a;b", "/abs/escape", "x`id`"]:
            result = AndroidWorker(self.sdk).read_app_file("com.acme.app", "sandbox", bad)
            self.assertFalse(result["ok"], bad)
            self.assertTrue(result["blocked"], bad)

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run")
    def test_read_sandbox_file_returns_text_via_run_as(self, run, _status):
        run.return_value = subprocess.CompletedProcess([], 0, "<map><string>token</string></map>\n", "")
        result = AndroidWorker(self.sdk).read_app_file("com.acme.app", "sandbox", "./shared_prefs/auth.xml")
        self.assertTrue(result["ok"])
        self.assertFalse(result["binary"])
        self.assertIn("token", result["content"])
        cmd = list(run.call_args.args[0])
        self.assertIn("run-as", cmd)
        self.assertEqual(cmd[-2], "cat")
        self.assertEqual(cmd[-1], "./shared_prefs/auth.xml")

    @patch.object(AndroidWorker, "status", return_value={"state": "device"})
    @patch("huntmob.android_worker._run")
    def test_read_apk_entry_returns_entry_text(self, run, _status):
        import zipfile as zf

        def fake_run(command, **kwargs):
            cmd = list(command)
            if "path" in cmd:  # pm path <pkg>
                return subprocess.CompletedProcess(cmd, 0, "package:/data/app/base.apk\n", "")
            if "pull" in cmd:
                with zf.ZipFile(cmd[-1], "w") as archive:
                    archive.writestr("res/values/strings.xml", "<resources>hello</resources>")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        run.side_effect = fake_run
        result = AndroidWorker(self.sdk).read_app_file("com.acme.app", "apk", "res/values/strings.xml")
        self.assertTrue(result["ok"])
        self.assertFalse(result["binary"])
        self.assertIn("hello", result["content"])

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


class AdbDevicesCacheTests(unittest.TestCase):
    def test_adb_devices_cache_coalesces_within_ttl(self):
        calls = []
        clock = [100.0]
        cache = {}

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "List of devices\n", "")

        now = lambda: clock[0]
        first = _adb_devices("/sdk/adb", now=now, run=fake_run, cache=cache)
        second = _adb_devices("/sdk/adb", now=now, run=fake_run, cache=cache)
        self.assertEqual(len(calls), 1)  # coalesced within TTL
        self.assertIs(first, second)
        clock[0] += 1.0  # past the 0.4s TTL
        _adb_devices("/sdk/adb", now=now, run=fake_run, cache=cache)
        self.assertEqual(len(calls), 2)
