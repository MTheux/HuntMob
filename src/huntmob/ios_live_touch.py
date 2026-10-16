"""Bounded per-gesture HID stream; no input history is retained."""
import asyncio
import time


class LiveTouch:
    def __init__(self, client, event_factory, idle_seconds=5):
        self.client = client
        self.event_factory = event_factory
        self.idle_seconds = idle_seconds
        self.stream = self.context = self.watchdog = None
        self.point = (0, 0)
        self.last_event = 0
        self.lock = asyncio.Lock()

    async def handle(self, phase, x, y):
        async with self.lock:
            if phase == 'down':
                await self._release()
                self.context = self.client.stub.hid.open()
                self.stream = await self.context.__aenter__()
            elif phase not in {'move', 'up', 'cancel'}:
                raise ValueError('Invalid touch phase')
            elif self.stream is None:
                if phase == 'cancel':
                    return
                raise ValueError('Touch gesture is not active')
            self.point = (x, y)
            self.last_event = time.monotonic()
            try:
                await asyncio.wait_for(self.stream.send_message(self.event_factory(phase, x, y)), 2)
                if phase in {'up', 'cancel'}:
                    await self._finish()
                elif self.watchdog is None:
                    self.watchdog = asyncio.create_task(self._expire())
            except Exception:
                await self._finish(failed=True)
                raise

    async def _expire(self):
        try:
            while self.stream is not None:
                await asyncio.sleep(self.idle_seconds)
                async with self.lock:
                    if self.stream and time.monotonic() - self.last_event >= self.idle_seconds:
                        await self._release()
        except Exception:
            # A disconnected companion is surfaced by the next input request.
            pass
        finally:
            if self.watchdog is asyncio.current_task():
                self.watchdog = None

    async def _release(self):
        if self.stream:
            try:
                await asyncio.wait_for(self.stream.send_message(self.event_factory('cancel', *self.point)), 2)
            finally:
                await self._finish()

    async def _finish(self, failed=False):
        stream, context = self.stream, self.context
        self.stream = self.context = None
        if self.watchdog and self.watchdog is not asyncio.current_task():
            self.watchdog.cancel()
            self.watchdog = None
        if stream:
            try:
                if not failed:
                    await asyncio.wait_for(stream.end(), 2)
                    await asyncio.wait_for(stream.recv_message(), 2)
            finally:
                await asyncio.wait_for(context.__aexit__(None, None, None), 2)

    async def close(self):
        async with self.lock:
            await self._release()
