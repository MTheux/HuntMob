import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from huntmob import ios_runtimes as runtime

class IosRuntimeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.saved=dict(runtime.JOB);runtime.JOB.clear();runtime.JOB.update(state='idle')
        self.addCleanup(lambda:(runtime.JOB.clear(),runtime.JOB.update(self.saved)))

    def test_installed_offered_and_legacy_versions_are_distinct(self):
        info={'runtimes':[{'id':'com.apple.CoreSimulator.SimRuntime.iOS-26-0','name':'iOS 26.0'},{'id':'com.apple.CoreSimulator.SimRuntime.iOS-27-0','name':'iOS 27.0'}]}
        with patch.object(runtime.platform,'system',return_value='Darwin'),patch.object(runtime.ios_worker,'inventory',return_value=info),patch.object(runtime,'_run',return_value=subprocess.CompletedProcess([],0,'Xcode 27.1\n','')),patch.object(runtime.shutil,'disk_usage',return_value=SimpleNamespace(free=14_000_000_000)):
            data=runtime.catalog()
        by_version={v['version']:v for v in data['versions']}
        self.assertEqual(by_version['26.0']['state'],'installed')
        self.assertEqual(by_version['18.6']['state'],'disk-space');self.assertFalse(by_version['18.6']['can_install'])
        self.assertEqual(by_version['16']['state'],'other-worker')
        self.assertFalse(any(str(v) in by_version for v in range(19,26)))

    def test_low_space_and_unknown_versions_never_start_a_download(self):
        with patch.object(runtime,'catalog',return_value={'versions':[{'version':'18.6','can_install':False,'reason':'Falta espaço'}]}),patch.object(runtime,'_run') as run,patch.object(runtime.threading,'Thread') as thread:
            self.assertFalse(runtime.install('18.6')['ok']);self.assertFalse(runtime.install('--help')['ok'])
        run.assert_not_called();thread.assert_not_called()

    def test_download_success_requires_runtime_observed_in_simctl(self):
        for installed,expected in [([], 'failed'),([{'id':'com.apple.CoreSimulator.SimRuntime.iOS-18-6'}],'installed')]:
            with self.subTest(expected=expected),patch.object(runtime,'catalog',return_value={'versions':[{'version':'18.6','can_install':True}]}),patch.object(runtime,'_run',return_value=subprocess.CompletedProcess([],0,'','')) as run,patch.object(runtime.ios_worker,'inventory',return_value={'runtimes':installed}),patch.object(runtime.threading,'Thread',side_effect=lambda **kw:SimpleNamespace(start=kw['target'])):
                runtime.JOB['state']='idle';self.assertTrue(runtime.install('18.6')['ok'])
                self.assertEqual(runtime.JOB['state'],expected)
                command=run.call_args.args[0];self.assertEqual(command[:5],('xcodebuild','-downloadPlatform','iOS','-buildVersion','18.6'))

    def test_windows_does_not_offer_local_apple_downloads(self):
        with patch.object(runtime.platform,'system',return_value='Windows'),patch.object(runtime.ios_worker,'inventory',return_value={}),patch.object(runtime.shutil,'disk_usage',return_value=SimpleNamespace(free=100_000_000_000)),patch.object(runtime,'_run') as run:
            data=runtime.catalog()
        self.assertFalse(any(v['can_install'] for v in data['versions']));run.assert_not_called()
