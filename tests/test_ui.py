import unittest

from huntmob.ui import validate_bind, web_root


class UiServerTests(unittest.TestCase):
    def test_ui_assets_exist(self):
        self.assertTrue((web_root() / "index.html").is_file())

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

    def test_frida_ui_uses_validated_package_and_curated_scripts(self):
        html = (web_root() / "index.html").read_text(encoding="utf-8")
        javascript = (web_root() / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="packageId"', html)
        self.assertIn('value="tls-observe"', html)
        self.assertIn("function validPackage", javascript)
        self.assertNotIn("shell=True", javascript)


if __name__ == "__main__":
    unittest.main()
