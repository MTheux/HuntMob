import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ios_virtual_headless_refresh import HeadlessRefresh
import boot_ios_virtual_data_v2 as boot


class HeadlessRefreshTests(unittest.TestCase):
    def setUp(self):
        # macOS AF_UNIX paths have a small bound; keep fixtures under /tmp.
        self.temp = tempfile.TemporaryDirectory(prefix='hm-rf-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)

    def server(self, *, reject=False):
        path = self.root / 'qmp.sock'
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path)); listener.listen(1); listener.settimeout(3)
        requests = []
        errors = []

        def run():
            try:
                client, _ = listener.accept()
                with client, client.makefile('rwb') as stream:
                    stream.write(b'{"QMP": {"version": {}}}\n'); stream.flush()
                    while True:
                        raw = stream.readline()
                        if not raw:
                            break
                        request = json.loads(raw); requests.append(request)
                        # Asynchronous events must not be mistaken for success.
                        stream.write(b'{"event": "PUBLIC-FIXTURE"}\n')
                        reply = {'id': request['id']}
                        if reject and request['execute'] == 'screendump':
                            reply['error'] = {'class': 'GenericError', 'desc': 'PUBLIC-FIXTURE'}
                        else:
                            reply['return'] = {}
                            filename = request.get('arguments', {}).get('filename')
                            if filename and filename != '/dev/null':
                                Path(filename).write_bytes(b'P6\n1 1\n255\n\0\0\0')
                        stream.write((json.dumps(reply) + '\n').encode()); stream.flush()
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                listener.close()

        worker = threading.Thread(target=run, daemon=True); worker.start()
        self.addCleanup(lambda: worker.join(4))
        return path, requests, errors, worker

    def test_existing_qmp_callback_refreshes_without_retaining_intermediate_pixels(self):
        path, requests, errors, worker = self.server()
        refresh = HeadlessRefresh(path)
        with patch('ios_virtual_headless_refresh.time.monotonic', return_value=1000000):
            refresh.tick(); refresh.tick()
        self.assertEqual(refresh.count, 1)
        self.assertEqual(requests[-1]['arguments'], {'filename': '/dev/null'})
        frame = self.root / 'headless-refresh-final.ppm'
        self.assertFalse(frame.exists())
        refresh.save_final_frame(frame)
        refresh.close(); worker.join(2)
        self.assertEqual(errors, [])
        self.assertTrue(frame.exists())
        self.assertEqual([item['execute'] for item in requests], ['qmp_capabilities', 'screendump', 'screendump'])
        self.assertFalse(refresh.metadata()['headless_refresh_intermediate_pixels_saved'])
        self.assertTrue(refresh.metadata()['headless_refresh_does_not_validate_ui'])

    def test_rejected_frame_never_counts_as_accepted_refresh(self):
        path, _, errors, worker = self.server(reject=True)
        refresh = HeadlessRefresh(path)
        with self.assertRaises(ValueError):
            refresh.tick()
        self.assertEqual(refresh.count, 0)
        refresh.close(); worker.join(2)
        self.assertEqual(errors, [])

    def test_regular_or_aliased_endpoint_refused(self):
        path = self.root / 'qmp.sock'; path.write_text('PUBLIC-FIXTURE')
        with self.assertRaises(ValueError):
            HeadlessRefresh(path).tick()
        path.unlink(); path.symlink_to(self.root / 'other.sock')
        with self.assertRaises(ValueError):
            HeadlessRefresh(path)._connect()

    def test_missing_endpoint_has_a_bounded_startup_deadline(self):
        refresh = HeadlessRefresh(self.root / 'qmp.sock')
        with patch('ios_virtual_headless_refresh.time.monotonic', return_value=refresh.started + 16):
            with self.assertRaises(ValueError):
                refresh.tick()

    def test_only_reviewed_rate_and_new_final_frame_path_accepted(self):
        for hz in (0, 1, 60):
            with self.assertRaises(ValueError):
                HeadlessRefresh(self.root / 'qmp.sock', hz)
        refresh = HeadlessRefresh(self.root / 'qmp.sock')
        with self.assertRaises(ValueError):
            refresh.save_final_frame(self.root / 'not-the-final-frame.ppm')

    def test_display_experiment_cannot_run_in_a_provisioning_mode_or_silently_change_plan(self):
        with patch.object(boot.legacy, 'root_pipe', side_effect=AssertionError('No root access')):
            with self.assertRaisesRegex(ValueError, 'normal-boot'):
                boot.boot(self.root, 10, False, 'serving', headless_refresh_hz=10)
            with patch.object(boot, 'validate_boot', return_value=(
                    {'normal_boot_v2': {'headless_refresh_hz_required': 10}}, Path('public-engine'), {})), \
                 patch.object(boot.resource, 'setrlimit'), patch.object(boot.os, 'umask'):
                with self.assertRaisesRegex(ValueError, 'exact reviewed'):
                    boot.boot(self.root, 10, False, 'serving', normal_boot=True)
        self.assertFalse((self.root / '.data-v2-launch.lock').exists())


if __name__ == '__main__':
    unittest.main()
