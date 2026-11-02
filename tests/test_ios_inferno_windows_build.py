import unittest
from pathlib import Path


class InfernoWindowsBuildScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = (Path(__file__).resolve().parents[1] / "scripts/build_ios_inferno_windows.ps1").read_text()

    def test_build_is_pinned_and_refuses_overwrite(self):
        self.assertIn("cc4302a99167abec69b714cfd00c38caece7e7de", self.content)
        self.assertIn("Output already exists and will not be overwritten", self.content)
        self.assertIn("worktree add --detach", self.content)

    def test_receipt_requires_hash_and_t8030_inventory(self):
        self.assertIn("Get-FileHash", self.content)
        self.assertIn("-machine help", self.content)
        self.assertIn("machine_t8030 = $true", self.content)
        self.assertIn("state = 'compiled'", self.content)
        self.assertIn("ready = $false", self.content)

    def test_build_never_boots_or_packages_firmware(self):
        self.assertNotIn("-M t8030", self.content)
        self.assertNotIn("sep-rom=", self.content)
        self.assertNotIn("trustcache=", self.content)
        self.assertIn("firmware_included = $false", self.content)
        self.assertIn("firmware_boot_validated = $false", self.content)

    def test_required_msys2_dependencies_are_explicit(self):
        for package in ("glib2", "pixman", "gnutls", "nettle", "libslirp", "lzfse"):
            self.assertIn("mingw-w64-ucrt-x86_64-" + package, self.content)


if __name__ == "__main__":
    unittest.main()
