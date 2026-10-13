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
        self.assertIn("/api/device/screenshot", javascript)

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
        self.assertNotIn("localStorage", javascript)
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

    def test_destructive_session_end_requires_confirmation_dialog(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="sessionDialog"', html)
        self.assertIn('id="destroyDevice"', html)
        self.assertIn("deviceAction('destroy')", javascript)

    def test_frida_ui_uses_validated_package_and_curated_scripts(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="packageId"', html)
        self.assertIn('value="tls-observe"', html)
        self.assertIn("function validPackage", javascript)
        self.assertNotIn("shell=True", javascript)


if __name__ == "__main__":
    unittest.main()
