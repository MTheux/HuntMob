import threading
import time
import unittest
from unittest.mock import patch
from huntmob.screen_relay import ScreenRelay


class ScreenRelayTests(unittest.TestCase):
    def test_viewers_share_producer_and_receive_latest_frame(self):
        relay = ScreenRelay()
        started = threading.Event()
        finish = threading.Event()
        def produce(*args):
            with relay.condition:
                relay.frame = b'latest'
                relay.sequence = 8
                started.set()
                relay.condition.notify_all()
            finish.wait(2)
        with patch.object(relay, '_produce', side_effect=produce) as producer:
            try:
                self.assertEqual(relay.get_frame('adb', 'owned', 'ffmpeg'), (8, b'latest'))
                self.assertEqual(relay.get_frame('adb', 'owned', 'ffmpeg'), (8, b'latest'))
                self.assertEqual(producer.call_count, 1)
            finally:
                finish.set()
                relay.thread.join(2)

    def test_static_screen_returns_current_frame_without_restarting(self):
        relay = ScreenRelay()
        finish = threading.Event()
        def produce(*args):
            with relay.condition:
                relay.frame = b'static'
                relay.sequence = 1
                relay.condition.notify_all()
            finish.wait(2)
        with patch.object(relay, '_produce', side_effect=produce) as producer:
            try:
                relay.get_frame('adb', 'owned', 'ffmpeg')
                self.assertEqual(relay.get_frame('adb', 'owned', 'ffmpeg', after=1, timeout=.01), (1, b'static'))
                self.assertEqual(producer.call_count, 1)
            finally:
                finish.set()
                relay.thread.join(2)
