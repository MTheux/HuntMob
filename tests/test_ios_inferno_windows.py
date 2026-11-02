import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huntmob import ios_inferno_windows as windows


class InfernoWindowsReadinessTests(unittest.TestCase):
    def test_non_windows_host_is_not_promoted(self):
        result = windows.snapshot(system="Darwin", machine="arm64", environ={})
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse(result["build_supported"])
        self.assertFalse(result["runtime_validated"])

    def test_windows_without_toolchain_stays_build_blocked(self):
        with patch.object(windows.shutil, "which", return_value=None):
            result = windows.snapshot(system="Windows", machine="AMD64",
                                      environ={"LOCALAPPDATA": "C:/Users/lab/AppData/Local", "PATH": ""})
        self.assertEqual(result["state"], "toolchain-required")
        self.assertFalse(result["build_supported"])
        self.assertIn("build-receipt.json", result["receipt"])

    def test_msys2_enables_build_only_not_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bash = root / "usr/bin/bash.exe"
            bash.parent.mkdir(parents=True)
            bash.write_bytes(b"fixture")
            with patch.object(windows.shutil, "which", return_value=None):
                result = windows.snapshot(
                    system="Windows", machine="AMD64",
                    environ={"MSYS2_ROOT": str(root), "LOCALAPPDATA": str(root), "PATH": ""},
                )
        self.assertEqual(result["state"], "build-required")
        self.assertTrue(result["build_supported"])
        self.assertFalse(result["engine_compiled"])
        self.assertFalse(result["springboard_validated"])
        self.assertEqual(result["modes"][0]["id"], "native-msys2")

    def test_wsl_is_explicitly_experimental(self):
        with patch.object(windows.shutil, "which", return_value="C:/Windows/System32/wsl.exe"):
            result = windows.snapshot(system="Windows", machine="AMD64",
                                      environ={"LOCALAPPDATA": "C:/Local", "PATH": "C:/Windows/System32"})
        self.assertTrue(result["build_supported"])
        self.assertTrue(result["modes"][0]["experimental_apfs_preparation"])
        self.assertFalse(result["ipa_execution_validated"])
