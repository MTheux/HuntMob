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


if __name__ == "__main__":
    unittest.main()
