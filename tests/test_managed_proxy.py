import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from huntmob.android_worker import AndroidSdk, AndroidWorker


class ManagedProxyTests(unittest.TestCase):
    def test_capture_starts_without_browser_or_web_listener(self):
        with tempfile.TemporaryDirectory() as folder:
            sdk=AndroidSdk(Path(folder),Path('/emulator'),Path('/adb'),Path('/avdmanager'),Path('/sdkmanager'))
            worker=AndroidWorker(sdk)
            with patch('huntmob.android_worker.Path.home',return_value=Path(folder)), patch('huntmob.android_worker.shutil.which',return_value='/managed/mitmdump'), patch.object(worker,'status',return_value={'state':'device'}), patch.object(worker,'proxy_status',side_effect=[{'listener':False},{'listener':True}]), patch.object(worker,'configure_proxy',return_value={'ok':True}), patch('huntmob.managed_proxy.owned',return_value=True),patch('huntmob.managed_proxy.remember'),patch('huntmob.android_worker.subprocess.Popen') as launch:
                launch.return_value.poll.return_value=None
                result=worker.start_managed_proxy()
            command=launch.call_args.args[0]
            self.assertEqual(command[0],'/managed/mitmdump')
            self.assertNotIn('--web-host',command)
            self.assertNotIn('--web-port',command)
            self.assertEqual(command[command.index('--listen-host')+1],'127.0.0.1')
            self.assertTrue(result['ok'])
            self.assertEqual(result['capture_backend'],'headless')
            self.assertNotIn('web_url',result)

    def test_missing_capture_worker_is_explicit_failure(self):
        with patch('huntmob.android_worker.shutil.which',return_value=None):
            self.assertFalse(AndroidWorker().start_managed_proxy()['ok'])

    def test_foreign_listener_is_not_claimed_as_native_capture(self):
        worker=AndroidWorker()
        with patch('huntmob.android_worker.shutil.which',return_value='/managed/mitmdump'),patch.object(worker,'status',return_value={'state':'device'}),patch.object(worker,'proxy_status',return_value={'listener':True}),patch('huntmob.managed_proxy.owned',return_value=False),patch.object(worker,'configure_proxy') as configure:
            self.assertFalse(worker.start_managed_proxy()['ok']);configure.assert_not_called()

    def test_receipt_checks_full_command_not_only_pid(self):
        import json
        from huntmob import managed_proxy
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'receipt.json';command=['/managed/mitmdump','--listen-port','8080','-s','/owned/addon.py']
            path.write_text(json.dumps({'pid':123,'port':8080,'command':command}))
            with patch('huntmob.managed_proxy.receipt_path',return_value=path),patch('huntmob.managed_proxy.command_line',return_value='/python '+' '.join(command)):
                self.assertTrue(managed_proxy.owned(8080))
            with patch('huntmob.managed_proxy.receipt_path',return_value=path),patch('huntmob.managed_proxy.command_line',return_value='/other/program'):
                self.assertFalse(managed_proxy.owned(8080))

class LocalAppRouteTests(unittest.TestCase):
    def test_route_is_limited_to_pinned_app_uid_and_local_backend(self):
        from types import SimpleNamespace
        lab={'id':'huntmob_lab_'+'a'*32,'package_id':'com.android.insecurebankv2','apk_sha256':'b18af2a0e44d7634bbcdf93664d9c78a2695e050393fcfbb5e8b91f902d194a4'}
        outputs=[(0,'uid=0(root)'),(0,'<map><string name="serverip">10.0.2.2</string><string name="serverport">8888</string></map>'),(0,'package:com.android.insecurebankv2 uid:10148'),(1,''),(0,'')]
        with tempfile.TemporaryDirectory() as folder:
            sdk=AndroidSdk(Path(folder),Path('/emulator'),Path('/adb'),Path('/avdmanager'),Path('/sdkmanager'))
            worker=AndroidWorker(sdk)
            with patch('huntmob.lab_sessions.current',return_value=lab), patch('huntmob.android_worker.Path.home',return_value=Path(folder)), patch.object(worker,'clear_local_app_capture'), patch('huntmob.android_worker._run',side_effect=[SimpleNamespace(returncode=c,stdout=s) for c,s in outputs]) as run, patch('huntmob.android_worker.socket.create_connection',side_effect=OSError):
                result=worker.configure_local_app_capture(8080)
            command=run.call_args.args[0]
            self.assertIn('-A',command)
            self.assertEqual(command[command.index('--uid-owner')+1],'10148')
            self.assertEqual(command[command.index('-d')+1],'10.0.2.2/32')
            self.assertEqual(command[command.index('--dport')+1],'8888')
            self.assertTrue(result['direct_capture'])
            self.assertFalse(result['backend_available'])
            with patch('huntmob.lab_sessions.current',return_value=lab), patch('huntmob.android_worker.Path.home',return_value=Path(folder)), patch('huntmob.android_worker._run',return_value=SimpleNamespace(returncode=0)) as remove:
                worker.clear_local_app_capture()
                self.assertIn('-D',remove.call_args.args[0])
                self.assertFalse((Path(folder)/'.huntmob/run/app-capture.json').exists())

    def test_unrecognized_apk_does_not_install_route(self):
        with patch('huntmob.lab_sessions.current',return_value={'package_id':'com.android.insecurebankv2','apk_sha256':'different'}), patch('huntmob.android_worker._run') as run:
            self.assertFalse(AndroidWorker().configure_local_app_capture(8080)['direct_capture'])
            run.assert_not_called()
