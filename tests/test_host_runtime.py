import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from huntmob.host_runtime import android_host
from huntmob.android_worker import AndroidWorker,AndroidSdk
from huntmob.bootstrap import bootstrap_android


class HostRuntimeTests(unittest.TestCase):
    def sdk(self,root):
        return AndroidSdk(root,root/'emulator',root/'adb',root/'avdmanager',root/'sdkmanager')

    def test_native_images_match_supported_hosts_and_both_profiles(self):
        for system,machine,arch in [('Windows','AMD64','x86_64'),('Linux','x86_64','x86_64'),('Darwin','arm64','arm64-v8a'),('Darwin','x86_64','x86_64')]:
            with self.subTest(system=system,machine=machine),patch('platform.system',return_value=system),patch('platform.machine',return_value=machine):
                self.assertEqual(android_host()['architecture'],arch)
                for mode in ['root','stock']:
                    w=AndroidWorker(self.sdk(Path('/sdk')),root_mode=mode,android_api=30)
                    self.assertTrue(w.package.endswith(';'+arch));self.assertIn(';android-30;',w.package)

    def test_unsupported_hosts_do_not_install_or_boot(self):
        for system,machine in [('Windows','ARM64'),('Linux','aarch64'),('Darwin','unknown')]:
            with patch('platform.system',return_value=system),patch('platform.machine',return_value=machine),patch('huntmob.bootstrap.subprocess.run') as run:
                self.assertFalse(bootstrap_android(install=True)['ok']);run.assert_not_called()
                w=AndroidWorker(self.sdk(Path('/sdk')))
                self.assertFalse(w.prerequisites()['ready'])
                self.assertFalse(w.prepare_profile('stock')['ok'])

    def test_existing_avd_for_other_cpu_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder,patch('platform.system',return_value='Windows'),patch('platform.machine',return_value='AMD64'),patch('huntmob.android_worker.Path.home',return_value=Path(folder)):
            root=Path(folder);config=root/'.android/avd/huntmob_api35_arm64.avd/config.ini';config.parent.mkdir(parents=True);config.write_text('abi.type=arm64-v8a\n')
            w=AndroidWorker(self.sdk(root))
            self.assertFalse(w.prerequisites()['ready']);self.assertEqual(config.read_text(),'abi.type=arm64-v8a\n')

    def test_linux_bootstrap_uses_installed_native_worker(self):
        with patch('platform.system',return_value='Linux'),patch('platform.machine',return_value='x86_64'),patch('huntmob.bootstrap.AndroidSdk.discover',return_value=self.sdk(Path('/sdk'))),patch.object(AndroidWorker,'prerequisites',return_value={'ready':True,'apk_metadata_ready':True,'architecture':'x86_64'}):
            r=bootstrap_android();self.assertTrue(r['ready']);self.assertEqual(r['mode'],'native')

    def test_existing_emulator_without_aapt_still_prepares_build_tools(self):
        import subprocess
        before={'ready':True,'apk_metadata_ready':False};after={'ready':True,'apk_metadata_ready':True}
        with patch('platform.system',return_value='Windows'),patch('platform.machine',return_value='AMD64'),patch('huntmob.bootstrap.AndroidSdk.discover',return_value=self.sdk(Path('/sdk'))),patch.object(AndroidWorker,'prerequisites',side_effect=[before,after]),patch('huntmob.analysis_core.EmbeddedAnalysis.status',return_value={'ready':False}),patch('huntmob.bootstrap.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            result=bootstrap_android(install=True);command=run.call_args.args[0]
            self.assertIn('build-tools;35.0.0',command);self.assertIn('system-images;android-35;default;x86_64',command);self.assertTrue(result['ready'])

    def test_sdk_timeout_is_not_announced_as_ready(self):
        import subprocess
        with patch('platform.system',return_value='Linux'),patch('platform.machine',return_value='x86_64'),patch('huntmob.bootstrap.AndroidSdk.discover',return_value=self.sdk(Path('/sdk'))),patch.object(AndroidWorker,'prerequisites',return_value={'ready':False}),patch('huntmob.analysis_core.EmbeddedAnalysis.status',return_value={'ready':False}),patch('huntmob.bootstrap.subprocess.run',side_effect=subprocess.TimeoutExpired('sdkmanager',1)):
            result=bootstrap_android(install=True);self.assertFalse(result['ready']);self.assertTrue(result['blocked'])
