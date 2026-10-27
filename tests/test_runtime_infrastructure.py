import unittest
from unittest.mock import patch

from huntmob import runtime_cleanup
from huntmob.runtime_limits import CapacityExceeded, upload_slot


class RuntimeInfrastructureTests(unittest.TestCase):
    def test_upload_concurrency_is_bounded_and_slots_are_released(self):
        with upload_slot():
            with upload_slot():
                with self.assertRaisesRegex(CapacityExceeded, 'upload_capacity_exceeded'):
                    with upload_slot():
                        pass
        with upload_slot():
            pass

    def test_primary_cleanup_runs_all_resources_and_sanitizes_failure(self):
        with patch('huntmob.dynamic_runtime.DYNAMIC.stop') as analysis, \
             patch('huntmob.dynamic_runtime.stop_workspace') as companions, \
             patch('huntmob.workspace_pairs.release_workspace') as connections, \
             patch('huntmob.codec_relay.CODEC_RELAY.restart', side_effect=RuntimeError('private detail')), \
             patch('huntmob.screen_relay.SCREEN_RELAY.restart') as screen, \
             patch('huntmob.managed_proxy.stop_for_lab') as proxy:
            result = runtime_cleanup.cleanup_primary_session('huntmob_lab_' + 'a' * 32)
        self.assertFalse(result['ok'])
        self.assertEqual([item['resource'] for item in result['resources']], ['analysis', 'companion-analysis', 'companion-connections', 'h264', 'mjpeg', 'proxy'])
        self.assertEqual(next(item for item in result['resources'] if item['resource'] == 'h264')['status'], 'cleanup_failed')
        self.assertNotIn('private detail', str(result))
        analysis.assert_called_once(); screen.assert_called_once(); proxy.assert_called_once()
        companions.assert_called_once_with('huntmob_lab_' + 'a' * 32)
        connections.assert_called_once_with('huntmob_lab_' + 'a' * 32)
