import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from huntmob import lab_sessions
from huntmob.android_worker import AndroidWorker


class LabSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root_patch = patch('huntmob.lab_sessions.root', return_value=self.directory / 'labs')
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_saved_sessions_have_independent_targets(self):
        one = {'id': 'huntmob_lab_' + 'a'*32, 'package_id': 'com.test.one'}
        two = {'id': 'huntmob_lab_' + 'b'*32, 'package_id': 'com.test.two'}
        lab_sessions.save(one)
        lab_sessions.save(two)
        self.assertEqual(lab_sessions.current(), two)
        self.assertEqual(len(lab_sessions.inventory()['labs']), 2)
        self.assertEqual(json.loads((lab_sessions.root() / (one['id'] + '.json')).read_text()), one)

    def test_temporary_lab_enters_inventory_only_after_explicit_save(self):
        temporary = {'id': 'huntmob_lab_' + 'c'*32, 'package_id': 'com.test.app', 'saved_at': None}
        lab_sessions.save(temporary)
        self.assertEqual(lab_sessions.inventory()['labs'], [])
        self.assertFalse(lab_sessions.resume_lab(MagicMock(), temporary['id'])['ok'])
        result = lab_sessions.save_current_lab(temporary['id'])
        self.assertTrue(result['ok'])
        self.assertEqual([item['id'] for item in lab_sessions.inventory()['labs']], [temporary['id']])
        self.assertTrue(lab_sessions.current()['saved_at'])

    def test_unsaved_lab_cannot_be_replaced_before_user_decides(self):
        lab_sessions.save({'id': 'huntmob_lab_' + 'c'*32, 'saved_at': None})
        worker = MagicMock()
        with patch('huntmob.android_worker.AndroidWorker') as factory:
            self.assertEqual(lab_sessions.create_lab(worker)['error_code'], 'unsaved_lab')
            self.assertEqual(lab_sessions.create_play_lab(worker)['error_code'], 'unsaved_lab')
            factory.assert_not_called()

    def test_close_rejects_stale_lab_without_touching_device(self):
        active = 'huntmob_lab_' + 'c'*32
        lab_sessions.save({'id': active, 'saved_at': None})
        worker = MagicMock(avd_name=active)
        result = lab_sessions.close_current_lab(worker, 'huntmob_lab_' + 'd'*32, preserve=False)
        self.assertFalse(result['ok'])
        worker.stop.assert_not_called()
        worker.destroy.assert_not_called()

    def test_save_and_stop_keeps_only_current_lab_resumable(self):
        old = {'id': 'huntmob_lab_' + 'a'*32, 'saved_at': '2026-10-20T00:00:00Z'}
        active = {'id': 'huntmob_lab_' + 'c'*32, 'saved_at': None}
        lab_sessions.save(old); lab_sessions.save(active)
        worker = MagicMock(avd_name=active['id'])
        worker.status.return_value = {'state': 'device'}
        worker.stop.return_value = {'ok': True}
        with patch('huntmob.workspace_devices.records', return_value=[]), patch('huntmob.dynamic_runtime.DYNAMIC.stop'), patch('huntmob.screen_relay.SCREEN_RELAY.restart'), patch('huntmob.codec_relay.CODEC_RELAY.restart'), patch('huntmob.managed_proxy.stop_for_lab'):
            result = lab_sessions.close_current_lab(worker, active['id'], preserve=True)
        self.assertTrue(result['ok'])
        worker.stop.assert_called_once()
        worker.destroy.assert_not_called()
        self.assertEqual(len(lab_sessions.inventory()['labs']), 2)

    def test_discard_removes_only_selected_lab(self):
        old = {'id': 'huntmob_lab_' + 'a'*32, 'saved_at': '2026-10-20T00:00:00Z'}
        active = {'id': 'huntmob_lab_' + 'c'*32, 'saved_at': None}
        lab_sessions.save(old); lab_sessions.save(active)
        active_dir = lab_sessions.root() / active['id']; active_dir.mkdir()
        (active_dir / 'sample.txt').write_text('fixture')
        worker = MagicMock(avd_name=active['id'])
        worker.status.return_value = {'state': 'offline'}
        worker.stop.return_value = {'ok': True}
        def destroy():
            lab_sessions.save({**active, 'state': 'destroyed'})
            return {'ok': True}
        worker.destroy.side_effect = destroy
        with patch('huntmob.workspace_devices.records', return_value=[]), patch('huntmob.dynamic_runtime.DYNAMIC.stop'), patch('huntmob.screen_relay.SCREEN_RELAY.restart'), patch('huntmob.codec_relay.CODEC_RELAY.restart'), patch('huntmob.managed_proxy.stop_for_lab'):
            result = lab_sessions.close_current_lab(worker, active['id'], preserve=False)
        self.assertTrue(result['ok'])
        self.assertFalse(active_dir.exists())
        self.assertEqual([item['id'] for item in lab_sessions.inventory()['labs']], [old['id']])
        self.assertEqual(lab_sessions.current(), {})

    def test_front_webcam_requires_native_discovery_and_selected_lab(self):
        identifier = 'huntmob_lab_' + 'c'*32
        lab_sessions.save({'id': identifier, 'saved_at': None})
        emulator = self.directory / 'emulator'; emulator.write_text('fixture')
        worker = MagicMock(avd_name=identifier)
        worker.sdk.emulator = emulator
        with patch('huntmob.android_worker._run', return_value=MagicMock(returncode=0, stdout='List of web cameras connected to the computer:\n Camera webcam0', stderr='')):
            self.assertTrue(lab_sessions.front_camera_status(worker, identifier)['available'])
        with patch('huntmob.android_worker._run', return_value=MagicMock(returncode=0, stdout='No web cameras', stderr='')), patch('huntmob.lab_sessions.switch') as switched:
            result = lab_sessions.set_front_camera(worker, identifier, use_webcam=True)
        self.assertFalse(result['ok'])
        switched.assert_not_called()
        self.assertNotIn('camera_front', lab_sessions.current())
        self.assertFalse(lab_sessions.front_camera_status(worker, 'huntmob_lab_' + 'd'*32)['ok'])

    def test_front_webcam_restarts_same_lab_without_saving_temporary_lab(self):
        identifier = 'huntmob_lab_' + 'c'*32
        lab_sessions.save({'id': identifier, 'saved_at': None})
        emulator = self.directory / 'emulator'; emulator.write_text('fixture')
        worker = MagicMock(avd_name=identifier)
        worker.sdk.emulator = emulator
        with patch('huntmob.android_worker._run', return_value=MagicMock(returncode=0, stdout='Camera webcam0', stderr='')), patch('huntmob.lab_sessions.switch', side_effect=lambda _worker, record: {'ok': True, 'lab': record}) as switched:
            result = lab_sessions.set_front_camera(worker, identifier, use_webcam=True)
        self.assertTrue(result['ok'])
        switched.assert_called_once()
        self.assertEqual(lab_sessions.current()['camera_front'], 'webcam0')
        self.assertEqual(lab_sessions.current()['camera_front_applied'], 'webcam0')
        self.assertIsNone(lab_sessions.current()['saved_at'])
        self.assertEqual(lab_sessions.inventory()['labs'], [])

    def test_engagement_is_persisted_for_new_lab(self):
        worker=MagicMock()
        with patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.lab_sessions.switch',side_effect=lambda worker,record: {'ok':True,'lab':record}):
            factory.return_value.create.return_value={'ok':True}
            result=lab_sessions.create_lab(worker,engagement='  auditoria-local  ')
        self.assertEqual(result['lab']['engagement'],'auditoria-local')

    def test_android_16_prepares_missing_arm64_image_before_creating_lab(self):
        worker=MagicMock()
        with patch('huntmob.android_worker.AndroidWorker') as factory,patch('huntmob.lab_sessions.switch',side_effect=lambda worker,record: {'ok':True,'lab':record}):
            target=factory.return_value
            target.architecture='arm64-v8a'
            target.prerequisites.return_value={'ready':False}
            target.prepare_profile.return_value={'ok':True}
            target.create.return_value={'ok':True}
            result=lab_sessions.create_lab(worker,root_mode='root',android_api=36)
        self.assertTrue(result['ok'])
        self.assertEqual(result['lab']['android_api'],36)
        self.assertEqual(result['lab']['architecture'],'arm64-v8a')
        target.prepare_profile.assert_called_once_with('root')
        target.create.assert_called_once()

    def test_failed_image_preparation_preserves_current_lab(self):
        original={'id':'huntmob_lab_'+'a'*32,'root_mode':'root','android_api':35}
        lab_sessions.save(original)
        with patch('huntmob.android_worker.AndroidWorker') as factory:
            target=factory.return_value
            target.prerequisites.return_value={'ready':False}
            target.prepare_profile.return_value={'ok':False,'reason':'Imagem indisponível'}
            result=lab_sessions.create_lab(MagicMock(),android_api=36)
        self.assertFalse(result['ok'])
        self.assertEqual(lab_sessions.current(),original)
        target.create.assert_not_called()

    def test_invalid_engagement_does_not_touch_worker(self):
        worker=MagicMock()
        for value in ('a'*121,'bad\nname',123):
            with self.assertRaises(ValueError):lab_sessions.create_lab(worker,engagement=value)
        worker.stop.assert_not_called()

    def test_resume_rejects_path_traversal_without_touching_worker(self):
        worker = MagicMock()
        self.assertFalse(lab_sessions.resume_lab(worker, '../../elsewhere')['ok'])
        worker.start.assert_not_called()

    @patch('huntmob.android_worker.AndroidWorker')
    def test_create_failure_preserves_current_session(self, factory):
        old = {'id': 'huntmob_lab_' + 'a'*32, 'package_id': 'com.old.app'}
        lab_sessions.save(old)
        factory.return_value.create.return_value = {'ok': False, 'reason': 'missing runtime'}
        worker = MagicMock()
        self.assertFalse(lab_sessions.create_lab(worker, 'com.new.app')['ok'])
        self.assertEqual(lab_sessions.current(), old)
        worker.stop.assert_not_called()

    @patch('huntmob.android_worker.AndroidWorker')
    def test_switch_stops_without_destroying_and_preserves_legacy(self, factory):
        worker = MagicMock()
        worker.avd_name = 'huntmob_api35_arm64'
        worker.status.side_effect = [{'state': 'device', 'attached': True}, {'state': 'offline', 'attached': False}]
        worker.stop.return_value = {'ok': True}
        factory.return_value.start.return_value = {'ok': True}
        factory.return_value.enable_adb_root.return_value = {'ok': True}
        factory.return_value.root_status.return_value = {'verified': True, 'root_available': True}
        record = {'id': 'huntmob_lab_' + 'a'*32, 'package_id': 'com.test.app'}
        self.assertTrue(lab_sessions.switch(worker, record)['ok'])
        worker.stop.assert_called_once()
        worker.destroy.assert_not_called()
        factory.return_value.enable_adb_root.assert_called_once()
        self.assertEqual(len(lab_sessions.inventory()['labs']), 2)
        self.assertEqual(lab_sessions.current()['id'], record['id'])

    def test_network_snapshots_are_separate_per_lab(self):
        lab_sessions.save({'id': 'huntmob_lab_' + 'a'*32})
        one = lab_sessions.network_store()
        lab_sessions.save({'id': 'huntmob_lab_' + 'b'*32})
        self.assertNotEqual(one, lab_sessions.network_store())

    def test_discarded_lab_is_not_offered_for_resume(self):
        record = {'id': 'huntmob_lab_' + 'a'*32, 'state': 'destroyed'}
        lab_sessions.save(record)
        self.assertEqual(lab_sessions.current(), {})
        self.assertEqual(lab_sessions.inventory()['labs'], [])
        worker = MagicMock()
        self.assertFalse(lab_sessions.resume_lab(worker, record['id'])['ok'])
        worker.stop.assert_not_called()

    def test_invalid_avd_name_is_rejected(self):
        with self.assertRaises(ValueError):
            AndroidWorker(avd_name='../other')

    def test_invalid_profile_does_not_stop_device(self):
        worker=MagicMock()
        self.assertFalse(lab_sessions.change_root_profile(worker,'fake')['ok'])
        worker.stop.assert_not_called()

    @patch('huntmob.android_worker.AndroidWorker')
    def test_missing_stock_image_preserves_active_lab(self,factory):
        original={'id':'huntmob_lab_'+'a'*32,'root_mode':'root','package_id':'com.test.app'}
        lab_sessions.save(original)
        factory.return_value.prerequisites.return_value={'ready':False}
        factory.return_value.package='system-images;android-35;google_apis_playstore;arm64-v8a'
        worker=MagicMock()
        self.assertFalse(lab_sessions.change_root_profile(worker,'stock')['ok'])
        worker.stop.assert_not_called();worker.clear_proxy.assert_not_called()
        self.assertEqual(lab_sessions.current(),original)

    @patch('huntmob.lab_sessions.resume_lab')
    @patch('huntmob.android_worker.AndroidWorker')
    def test_return_reuses_existing_profile_without_recreating_userdata(self,factory,resume):
        one={'id':'huntmob_lab_'+'a'*32,'root_mode':'root','profile_group':'pair'}
        two={'id':'huntmob_lab_'+'b'*32,'root_mode':'stock','profile_group':'pair'}
        lab_sessions.save(two);lab_sessions.save(one)
        factory.return_value.prerequisites.return_value={'ready':True}
        resume.return_value={'ok':True}
        worker=MagicMock()
        self.assertTrue(lab_sessions.change_root_profile(worker,'stock')['ok'])
        resume.assert_called_once_with(worker,two['id'])
        factory.return_value.create.assert_not_called()

    def test_profiles_select_different_system_images(self):
        root_worker=AndroidWorker(root_mode='root')
        stock_worker=AndroidWorker(root_mode='stock')
        self.assertIn(';default;',root_worker.package)
        self.assertIn(';google_apis_playstore;',stock_worker.package)
        with self.assertRaises(ValueError):AndroidWorker(root_mode='bogus')

    @patch('huntmob.android_worker.AndroidWorker')
    def test_profile_preparation_preserves_selected_android_version(self,factory):
        original={'id':'huntmob_lab_'+'a'*32,'root_mode':'root','android_api':30}
        lab_sessions.save(original);factory.return_value.prerequisites.return_value={'ready':False}
        worker=MagicMock()
        self.assertFalse(lab_sessions.change_root_profile(worker,'stock')['ok'])
        self.assertEqual(factory.call_args.kwargs['android_api'],30);worker.stop.assert_not_called()

    def test_stock_profile_rejects_root_even_on_user_build(self):
        from types import SimpleNamespace
        worker=AndroidWorker(root_mode='stock')
        outputs=[(0,'uid=2000(shell)'),(0,'uid=0(root)'),(0,'user'),(0,'0')]
        with patch.object(worker,'status',return_value={'state':'device'}),patch('huntmob.android_worker._run',side_effect=[SimpleNamespace(returncode=c,stdout=s) for c,s in outputs]):
            self.assertFalse(worker.root_status()['verified'])

    def test_stock_profile_requires_release_configuration(self):
        from types import SimpleNamespace
        worker=AndroidWorker(root_mode='stock')
        outputs=[(0,'uid=2000(shell)'),(1,''),(0,'userdebug'),(0,'1')]
        with patch.object(worker,'status',return_value={'state':'device'}),patch('huntmob.android_worker._run',side_effect=[SimpleNamespace(returncode=c,stdout=s) for c,s in outputs]):
            self.assertFalse(worker.root_status()['verified'])

    @patch('huntmob.android_worker.AndroidWorker')
    def test_resume_missing_image_keeps_active_lab_running(self,factory):
        old={'id':'huntmob_lab_'+'a'*32,'package_id':'com.old.app'}
        lab_sessions.save(old)
        worker=MagicMock();worker.status.return_value={'state':'device','attached':True}
        factory.return_value.prerequisites.return_value={'ready':False,'reason':'missing image'}
        with patch('huntmob.dynamic_runtime.DYNAMIC.stop') as dynamic_stop:
            result=lab_sessions.switch(worker,{'id':'huntmob_lab_'+'b'*32,'root_mode':'stock','android_api':30})
            self.assertFalse(result['ok']);self.assertEqual(lab_sessions.current(),old)
            worker.stop.assert_not_called();dynamic_stop.assert_not_called()

class RootProfileScopeTests(unittest.TestCase):
    def test_stale_root_shortcut_cannot_switch_a_newly_selected_lab(self):
        worker=MagicMock()
        with patch('huntmob.lab_sessions.current',return_value={'id':'huntmob_lab_'+'b'*32}),patch('huntmob.lab_sessions._change_root_profile') as change:
            result=lab_sessions.change_root_profile(worker,'root',expected_lab_id='huntmob_lab_'+'a'*32)
        self.assertFalse(result['ok']);change.assert_not_called();worker.stop.assert_not_called()

    def test_exact_lab_shortcut_reuses_existing_profile_switcher(self):
        identifier='huntmob_lab_'+'a'*32;worker=MagicMock()
        with patch('huntmob.lab_sessions.current',return_value={'id':identifier}),patch('huntmob.lab_sessions._change_root_profile',return_value={'ok':True}) as change:
            result=lab_sessions.change_root_profile(worker,'stock',expected_lab_id=identifier)
        self.assertTrue(result['ok']);change.assert_called_once_with(worker,'stock')
