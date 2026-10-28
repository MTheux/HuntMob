import unittest

from huntmob.ui import HuntMobHandler, validate_bind, web_root


class UiServerTests(unittest.TestCase):
    def test_ui_assets_exist(self):
        self.assertTrue((web_root() / "index.html").is_file())

    def test_runtime_api_handler_is_installed(self):
        self.assertTrue(hasattr(HuntMobHandler, "do_GET"))

    def test_real_device_screen_endpoint_is_used(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="deviceScreen"', html)
        self.assertIn("/api/device/stream", javascript)

    def test_files_tab_exposes_apk_and_sandbox_separately(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-tab="files"', html)
        self.assertIn('id="apkFiles"', html)
        self.assertIn('id="sandboxFiles"', html)
        self.assertIn("/api/device/files", javascript)

    def test_reverse_uses_real_installed_app_inventory(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="installedApps"', html)
        self.assertIn("/api/device/apps", javascript)
        self.assertIn("/api/reverse", javascript)
        self.assertNotIn("Token em memória por tempo excessivo", html)

    def test_proxy_controls_are_connected_to_api(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="startCapture"', html)
        self.assertIn('id="configureProxy"', html)
        self.assertIn("start-managed", javascript)
        self.assertIn("/api/proxy", javascript)

    def test_ready_worker_is_distinct_from_missing_runtime(self):
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn("Worker pronto · device desligado", javascript)
        self.assertIn("Android Emulator e imagem AOSP instalados", javascript)

    def test_runtime_inventory_refreshes_and_hides_stopped_device(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="runtimeEmpty"', html)
        self.assertIn("runtimeDevice').hidden = true", javascript)
        self.assertIn("everyVisible(loadRuntime, 2500)", javascript)
        self.assertIn("O lab atual será preservado", javascript)

    def test_loopback_is_allowed(self):
        validate_bind("127.0.0.1", False)

    def test_remote_bind_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "authorized-remote"):
            validate_bind("0.0.0.0", False)

    def test_explicit_remote_bind_is_accepted(self):
        validate_bind("0.0.0.0", True)

    def test_in_app_biometric_button_opens_fixture(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        self.assertIn(
            '<button type="button" data-panel="biometric">Entrar com biometria</button>',
            html,
        )

    def test_face_recognition_is_session_scoped(self):
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn("let enrolledEmbedding", javascript)
        self.assertIn("enrolledEmbedding = undefined", javascript)
        # Only layout/navigation preferences persist; biometric data stays in memory.
        import re
        writes = re.findall(r"localStorage\.setItem\(([^;]+)\)", javascript)
        self.assertEqual(writes, ["'huntmob.analysisOpen', analysisPreference", "'huntmob.activePhase', phase"])
        self.assertNotIn("JSON.stringify(enrolledEmbedding)", javascript)
        self.assertNotIn("indexedDB", javascript)

    def test_biometric_widget_matches_provider_outcomes(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        for outcome in ("recognized", "unrecognized", "dirty", "partial", "insufficient", "too-fast"):
            self.assertIn(f'data-biometric="{outcome}"', html)

    def test_unprovisioned_runtime_is_not_presented_as_live(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="runtimePlaceholder"', html)
        self.assertIn("Nenhuma VM HuntMob em execução", javascript)

    def test_new_lab_is_an_app_first_authorized_flow(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="newLabDialog"', html)
        self.assertIn('value="firebase"', html)
        self.assertIn('id="labApproval"', html)
        self.assertIn("newLabDialog.showModal()", javascript)
        self.assertIn('value="empty"', html)
        self.assertIn('id="closeNewLab"', html)
        self.assertIn("newLabDialog.close('cancel')", javascript)
        self.assertIn('id="createLab"', html)

    def test_destructive_session_end_requires_confirmation_dialog(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="sessionDialog"', html)
        self.assertIn('id="saveLabButton"', html)
        self.assertIn('id="closeLabButton"', html)
        self.assertIn('id="destroyDevice"', html)
        self.assertIn("deviceAction('save-lab', {lab_id: labId})", javascript)
        self.assertIn("finishLabShutdown('discard-lab')", javascript)
        self.assertIn("finishLabShutdown('save-stop')", javascript)

    def test_camera_factor_is_device_camera_not_browser_face_fixture(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="useHostWebcam"', html)
        self.assertIn('id="cameraSourceStatus"', html)
        self.assertIn('Teste facial separado no navegador', html)
        self.assertIn("deviceAction('front-camera-source'", javascript)

    def test_frida_ui_uses_validated_package_and_curated_scripts(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="packageId"', html)
        self.assertIn('value="tls-observe"', html)
        self.assertIn("function validPackage", javascript)
        self.assertNotIn("shell=True", javascript)


if __name__ == "__main__":
    unittest.main()

class DeviceApiFailureTests(unittest.TestCase):
    def test_invalid_engagement_returns_json_without_mutation(self):
        import json,threading,urllib.request,urllib.error
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        from huntmob.ui import SESSION_TOKEN
        server=ThreadingHTTPServer(('127.0.0.1',0),HuntMobHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            data={'action':'new-lab','engagement':'bad\nname','authorized':True,'approved':True}
            request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/device/action',data=json.dumps(data).encode(),headers={'X-HuntMob-CSRF':SESSION_TOKEN,'Content-Type':'application/json'})
            with patch('huntmob.ui.AndroidWorker') as worker,patch('huntmob.lab_sessions.save') as save:
                with self.assertRaises(urllib.error.HTTPError) as response:urllib.request.urlopen(request,timeout=3)
                self.assertEqual(response.exception.code,400)
                self.assertFalse(json.load(response.exception)['ok'])
                worker.return_value.stop.assert_not_called();save.assert_not_called()
        finally:server.shutdown();server.server_close();thread.join(2)


class DetachedServerTests(unittest.TestCase):
    def test_http_responses_survive_broken_or_closed_log_stream(self):
        import io
        import json
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch

        class BrokenLog(io.StringIO):
            def write(self, text):
                raise BrokenPipeError('terminal reader exited')

        closed = io.StringIO()
        closed.close()
        server = ThreadingHTTPServer(('127.0.0.1', 0), HuntMobHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            for stream in (BrokenLog(), closed):
                with self.subTest(stream=type(stream).__name__), patch('sys.stderr', stream):
                    with urllib.request.urlopen(base + '/api/client/ping', timeout=3) as response:
                        self.assertEqual(response.status, 200)
                        self.assertTrue(json.load(response)['ok'])
                    with urllib.request.urlopen(base + '/', timeout=3) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b'deviceScreen', response.read())
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(base + '/missing-detached-worker', timeout=3)
                    self.assertEqual(error.exception.code, 404)
                    error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
