import socket
import struct
import unittest
from unittest.mock import Mock, patch
from huntmob.codec_relay import CodecRelay,read_exact

LAB='huntmob_lab_'+'a'*32

class CodecRelayTests(unittest.TestCase):
    def test_restart_invalidates_delayed_input_generation(self):
        relay = CodecRelay(owner_check=lambda value: value == 'lab', forward_port=39999)
        relay.target = ('adb', 'emulator-5558', 'lab')
        relay.control = Mock()
        generation = relay.snapshot()['generation']
        relay.thread = None
        relay.restart()
        result = relay.input({'action': 'home', 'session_generation': generation})
        self.assertFalse(result['ok'])
        self.assertTrue(result['stale_session'])

    def test_snapshot_exposes_bounded_stream_telemetry(self):
        relay = CodecRelay()
        relay.connection_attempts = 2
        relay.reconnect_count = 1
        relay.stall_count = 1
        relay.first_frame_ms = 125.5
        relay.queue_bytes = 4096
        telemetry = relay.snapshot()['telemetry']
        self.assertEqual(telemetry['connection_attempts'], 2)
        self.assertEqual(telemetry['reconnect_count'], 1)
        self.assertEqual(telemetry['stall_count'], 1)
        self.assertEqual(telemetry['first_frame_ms'], 125.5)
        self.assertEqual(telemetry['queue_bytes'], 4096)
        self.assertGreater(telemetry['queue_limit_bytes'], telemetry['queue_bytes'])

    def relay(self):
        relay=CodecRelay();relay.target=('adb','emulator-5556',LAB);relay.width=648;relay.height=1440
        relay.control=unittest.mock.Mock();return relay

    def test_touch_wire_matches_pinned_protocol_and_uses_video_geometry(self):
        relay=self.relay()
        with patch('huntmob.codec_relay.current',return_value={'id':LAB}):
            self.assertTrue(relay.input({'action':'touch','phase':'down','x':.5,'y':.25})['ok'])
        data=relay.control.sendall.call_args.args[0]
        self.assertEqual(len(data),32)
        fields=struct.unpack('>BBQiiHHHII',data)
        self.assertEqual(fields,(2,0,0,324,360,648,1440,65535,0,0))

    def test_cancel_releases_touch_pressure(self):
        relay=self.relay()
        with patch('huntmob.codec_relay.current',return_value={'id':LAB}):
            self.assertTrue(relay.input({'action':'touch','phase':'cancel','x':0,'y':0})['ok'])
        self.assertEqual(struct.unpack('>BBQiiHHHII',relay.control.sendall.call_args.args[0])[7],0)

    def test_invalid_coordinates_and_unknown_actions_never_reach_control(self):
        relay=self.relay()
        with patch('huntmob.codec_relay.current',return_value={'id':LAB}):
            for value in [float('nan'),float('inf'),2,-1,'shell text']:
                self.assertFalse(relay.input({'action':'touch','phase':'move','x':value,'y':0})['ok'])
            self.assertFalse(relay.input({'action':'shell','text':'anything'})['ok'])
        relay.control.sendall.assert_not_called()

    def test_previous_lab_is_not_controllable(self):
        relay=self.relay()
        with patch('huntmob.codec_relay.current',return_value={'id':'different'}):
            self.assertFalse(relay.input({'action':'back'})['ok'])
        relay.control.sendall.assert_not_called()

    def test_read_exact_reassembles_partial_socket_reads(self):
        connection=unittest.mock.Mock();connection.recv.side_effect=[b'a',b'bc',b'd']
        self.assertEqual(read_exact(connection,4),b'abcd')

    def test_disconnected_socket_is_explicit_error(self):
        connection=unittest.mock.Mock();connection.recv.return_value=b''
        with self.assertRaises(OSError):read_exact(connection,4)

    def test_rotation_sends_updated_decoder_config_to_existing_viewer(self):
        from types import SimpleNamespace
        relay=self.relay();relay.thread=unittest.mock.Mock();relay.thread.is_alive.return_value=True
        relay.prefix=[b'new-geometry',b'new-sps'];relay.packets=[(11,b'new-keyframe')];relay.sequence=11;relay.config_sequence=11
        worker=SimpleNamespace(sdk=SimpleNamespace(adb='adb'),serial='emulator-5556',avd_name=LAB)
        with patch('huntmob.codec_relay.current',return_value={'id':LAB}):
            seq,packets=relay.get_packets(worker,after=10)
        self.assertEqual(seq,11);self.assertEqual(packets,[b'new-geometry',b'new-sps',b'new-keyframe'])

    def test_unchanged_decoder_only_receives_new_frame(self):
        from types import SimpleNamespace
        relay=self.relay();relay.thread=unittest.mock.Mock();relay.thread.is_alive.return_value=True
        relay.prefix=[b'geometry',b'sps'];relay.packets=[(11,b'keyframe'),(12,b'delta')];relay.sequence=12;relay.config_sequence=11
        worker=SimpleNamespace(sdk=SimpleNamespace(adb='adb'),serial='emulator-5556',avd_name=LAB)
        with patch('huntmob.codec_relay.current',return_value={'id':LAB}):
            _,packets=relay.get_packets(worker,after=11)
        self.assertEqual(packets,[b'delta'])

    def test_keyboard_editing_is_fixed_keycodes_not_arbitrary_commands(self):
        relay=self.relay()
        with patch('huntmob.codec_relay.current',return_value={'id':LAB}):
            self.assertTrue(relay.input({'action':'key','key':'Backspace'})['ok'])
            self.assertFalse(relay.input({'action':'key','key':'shell'})['ok'])
        data=relay.control.sendall.call_args.args[0]
        self.assertEqual(len(data),28)
        self.assertEqual(struct.unpack('>BBiii',data[:14]),(0,0,67,0,0))
