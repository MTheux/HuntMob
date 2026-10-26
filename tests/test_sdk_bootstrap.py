"""First-run Android SDK provisioner: logic verified without a 1.5GB install."""

import hashlib
import os
import stat
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from huntmob import sdk_bootstrap as sb


class SourceTests(unittest.TestCase):
    def test_each_supported_host_has_pinned_url_and_sha(self):
        for host in ("darwin", "windows", "linux"):
            url, sha = sb.cmdline_tools_source(host)
            self.assertTrue(url.startswith("https://dl.google.com/android/repository/commandlinetools-"))
            self.assertEqual(len(sha), 64)

    def test_unsupported_host_raises(self):
        with self.assertRaises(ValueError):
            sb.cmdline_tools_source("plan9")


class SdkRootTests(unittest.TestCase):
    def test_env_android_sdk_root_wins(self):
        self.assertEqual(sb.default_sdk_root("linux", {"ANDROID_SDK_ROOT": "/x/sdk"}), Path("/x/sdk"))

    def test_windows_defaults_to_localappdata(self):
        root = sb.default_sdk_root("windows", {"LOCALAPPDATA": r"C:\Users\me\AppData\Local"})
        self.assertEqual(root, Path(r"C:\Users\me\AppData\Local") / "Android/Sdk")

    def test_posix_defaults_to_home_android_sdk(self):
        self.assertEqual(sb.default_sdk_root("linux", {}), Path.home() / "Android/Sdk")


class ShaTests(unittest.TestCase):
    def test_mismatch_raises_and_match_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            blob = Path(tmp) / "a.bin"
            blob.write_bytes(b"hello")
            sb.verify_sha256(blob, hashlib.sha256(b"hello").hexdigest())
            with self.assertRaises(ValueError):
                sb.verify_sha256(blob, "0" * 64)


class ExtractTests(unittest.TestCase):
    def _make_zip(self, path):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("cmdline-tools/bin/sdkmanager", "#!/bin/sh\necho hi\n")
            archive.writestr("cmdline-tools/lib/foo.jar", "x")
            archive.writestr("cmdline-tools/source.properties", "Pkg.Revision=1")

    def test_lands_at_latest_and_is_executable_on_posix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Sdk"
            archive = Path(tmp) / "ct.zip"
            self._make_zip(archive)
            target = sb.extract_cmdline_tools(archive, root)
            self.assertEqual(target, root / "cmdline-tools" / "latest")
            sdkmanager = target / "bin" / "sdkmanager"
            self.assertTrue(sdkmanager.is_file())
            if os.name != "nt":
                self.assertTrue(os.stat(sdkmanager).st_mode & stat.S_IXUSR)


class ToolCommandTests(unittest.TestCase):
    def test_windows_bat_wrapped_with_cmd(self):
        tool = Path("C:/sdk/cmdline-tools/latest/bin/sdkmanager.bat")
        command = sb.tool_command(tool, "windows", ["--licenses"])
        self.assertEqual(command[0], "cmd")
        self.assertEqual(command[1], "/c")
        self.assertEqual(command[-1], "--licenses")
        self.assertIn(str(tool), command)

    def test_posix_runs_tool_directly(self):
        command = sb.tool_command(Path("/sdk/bin/sdkmanager"), "linux", ["--licenses"])
        self.assertEqual(command, ["/sdk/bin/sdkmanager", "--licenses"])


class DownloadTests(unittest.TestCase):
    def test_downloads_and_verifies_sha(self):
        payload = b"android-tools-zip"
        good = hashlib.sha256(payload).hexdigest()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/ct.zip"
            with tempfile.TemporaryDirectory() as tmp:
                dest = sb.download(url, good, Path(tmp) / "ct.zip")
                self.assertEqual(dest.read_bytes(), payload)
                with self.assertRaises(ValueError):
                    sb.download(url, "0" * 64, Path(tmp) / "bad.zip")
        finally:
            server.shutdown()
            server.server_close()


class ProvisionTests(unittest.TestCase):
    def test_skips_work_when_already_ready(self):
        with patch("huntmob.sdk_bootstrap.AndroidSdk.discover", return_value=object()), \
             patch("huntmob.sdk_bootstrap._prerequisites_ready", return_value=True):
            result = sb.provision(lambda: self.fail("confirm must not run when ready"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["already_ready"])

    def test_declined_confirmation_installs_nothing(self):
        downloaded = {"hit": False}

        def downloader(*_a, **_k):
            downloaded["hit"] = True

        with patch("huntmob.sdk_bootstrap.AndroidSdk.discover", return_value=None), \
             patch("huntmob.sdk_bootstrap._prerequisites_ready", return_value=False):
            result = sb.provision(lambda: False, downloader=downloader, host="linux")
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertFalse(downloaded["hit"])

    def test_confirmed_flow_downloads_extracts_licenses_then_installs(self):
        order = []

        def downloader(url, sha, dest):
            order.append("download")
            Path(dest).write_bytes(b"zip")
            return Path(dest)

        env = {}
        with patch("huntmob.sdk_bootstrap.AndroidSdk.discover", side_effect=[None, "sdk-after"]), \
             patch("huntmob.sdk_bootstrap._prerequisites_ready", return_value=False), \
             patch("huntmob.sdk_bootstrap.extract_cmdline_tools",
                   side_effect=lambda z, r: order.append("extract") or (r / "cmdline-tools/latest")), \
             patch("huntmob.sdk_bootstrap.accept_licenses",
                   side_effect=lambda *a, **k: order.append("licenses") or True), \
             patch("huntmob.sdk_bootstrap.bootstrap_android",
                   side_effect=lambda install=False: order.append("install") or {"ok": True, "ready": True}):
            result = sb.provision(lambda: True, downloader=downloader, host="linux", env=env)
        self.assertTrue(result["ok"])
        self.assertEqual(order, ["download", "extract", "licenses", "install"])
        self.assertIn("ANDROID_SDK_ROOT", env)

    def test_declined_licenses_block_install(self):
        with patch("huntmob.sdk_bootstrap.AndroidSdk.discover", side_effect=[None, "sdk-after"]), \
             patch("huntmob.sdk_bootstrap._prerequisites_ready", return_value=False), \
             patch("huntmob.sdk_bootstrap.extract_cmdline_tools", side_effect=lambda z, r: r / "x"), \
             patch("huntmob.sdk_bootstrap.accept_licenses", return_value=False), \
             patch("huntmob.sdk_bootstrap.bootstrap_android") as install:
            result = sb.provision(lambda: True, downloader=lambda u, s, d: Path(d),
                                  host="linux", env={})
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
