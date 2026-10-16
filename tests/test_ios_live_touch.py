import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from huntmob.ios_live_touch import LiveTouch


class LiveTouchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stream = SimpleNamespace(send_message=AsyncMock(), end=AsyncMock(), recv_message=AsyncMock())
        self.context = SimpleNamespace(__aenter__=AsyncMock(return_value=self.stream), __aexit__=AsyncMock())
        self.open = Mock(return_value=self.context)
        self.touch = LiveTouch(SimpleNamespace(stub=SimpleNamespace(hid=SimpleNamespace(open=self.open))),
                               lambda phase, x, y: (phase, x, y))

    async def asyncTearDown(self):
        await self.touch.close()

    async def test_moves_are_sent_before_release_on_one_stream_without_swipe_delay(self):
        await self.touch.handle('down', .1, .2)
        await self.touch.handle('move', .3, .4)
        self.assertEqual(self.stream.send_message.await_args_list[-1].args, (('move', .3, .4),))
        self.stream.end.assert_not_awaited()
        await self.touch.handle('up', .5, .6)
        self.open.assert_called_once()
        self.assertEqual([call.args[0][0] for call in self.stream.send_message.await_args_list], ['down', 'move', 'up'])
        self.stream.end.assert_awaited_once()
        self.stream.recv_message.assert_awaited_once()
        self.assertIsNone(self.touch.stream)

    async def test_close_releases_the_last_position(self):
        await self.touch.handle('down', .1, .2)
        await self.touch.handle('move', .6, .7)
        await self.touch.close()
        self.assertEqual(self.stream.send_message.await_args.args, (('cancel', .6, .7),))

    async def test_idle_pointer_is_released_when_viewer_disappears(self):
        self.touch.idle_seconds=.01
        await self.touch.handle('down', .1, .2)
        for _ in range(50):
            if self.touch.stream is None: break
            await asyncio.sleep(.005)
        self.assertIsNone(self.touch.stream)
        self.assertEqual(self.stream.send_message.await_args.args, (('cancel', .1, .2),))

    async def test_no_move_without_down_and_cancel_is_idempotent(self):
        for phase in ('move', 'up', 'invalid'):
            with self.assertRaises(ValueError):
                await self.touch.handle(phase, .1, .2)
        await self.touch.handle('cancel', .1, .2)
        self.open.assert_not_called()

    async def test_failed_stream_is_closed_and_not_reused(self):
        self.stream.send_message.side_effect=OSError('disconnected')
        with self.assertRaises(OSError):
            await self.touch.handle('down', .1, .2)
        self.assertIsNone(self.touch.stream)
        self.context.__aexit__.assert_awaited_once()
