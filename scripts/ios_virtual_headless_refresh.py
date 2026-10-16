"""Bounded host display refresh for the isolated DATA-v2 research guest.

Use the existing QMP display callback; do not change the guest or engine.
Intermediate pixels go only to the host null device, never to logs or IPC.
"""
import json
import os
import socket
import stat
import time
from pathlib import Path


class HeadlessRefresh:
    def __init__(self, path, hz=10):
        if hz != 10 or Path(path).name != 'qmp.sock':
            raise ValueError('Only the bounded 10 Hz owned QMP experiment is supported')
        self.path = Path(path)
        self.client = self.stream = None
        self.next_tick = 0
        self.started = time.monotonic()
        self.count = 0
        self.total_seconds = self.max_seconds = 0.0
        self.sequence = 0

    def _receive(self, expected=None):
        for _ in range(32):
            raw = self.stream.readline(8193)
            if not raw.endswith(b'\n') or len(raw) > 8192:
                raise ValueError('Invalid or oversized QMP response')
            reply = json.loads(raw)
            if not isinstance(reply, dict):
                raise ValueError('QMP response must be an object')
            if expected is None:
                if not isinstance(reply.get('QMP'), dict):
                    raise ValueError('QMP greeting required')
                return reply
            if reply.get('id') == expected:
                if 'return' not in reply or 'error' in reply:
                    raise ValueError('QMP display request rejected')
                return reply['return']
        raise ValueError('QMP response bound exceeded')

    def _call(self, name, arguments=None):
        self.sequence += 1
        request = {'execute': name, 'id': self.sequence}
        if arguments is not None:
            request['arguments'] = arguments
        self.stream.write((json.dumps(request) + '\n').encode())
        self.stream.flush()
        return self._receive(self.sequence)

    def _connect(self):
        directory = self.path.parent.lstat()
        endpoint = self.path.lstat()
        if not (stat.S_ISDIR(directory.st_mode) and stat.S_IMODE(directory.st_mode) == 0o700 and
                directory.st_uid == os.getuid() and stat.S_ISSOCK(endpoint.st_mode) and
                endpoint.st_uid == os.getuid()):
            raise ValueError('Only the owned private QMP socket may refresh this guest')
        null = Path('/dev/null').stat()
        if not stat.S_ISCHR(null.st_mode):
            raise ValueError('Host null sink must be a character device')
        self.client = socket.socket(socket.AF_UNIX)
        self.client.settimeout(1)
        self.client.connect(str(self.path))
        self.stream = self.client.makefile('rwb')
        self._receive()
        self._call('qmp_capabilities')

    def tick(self):
        now = time.monotonic()
        if now < self.next_tick:
            return
        if self.client is None:
            if not self.path.exists():
                if now - self.started > 15:
                    raise ValueError('Owned QMP display did not become available')
                self.next_tick = now + 0.1
                return
            self._connect()
        started = time.monotonic()
        self._call('screendump', {'filename': '/dev/null'})
        elapsed = time.monotonic() - started
        self.count += 1
        self.total_seconds += elapsed
        self.max_seconds = max(self.max_seconds, elapsed)
        self.next_tick = time.monotonic() + 0.1

    def save_final_frame(self, path):
        path = Path(path)
        if self.stream is None or path.exists() or path.is_symlink() or path.name != 'headless-refresh-final.ppm':
            raise ValueError('A new private final-frame path is required')
        self._call('screendump', {'filename': str(path)})

    def close(self):
        try:
            if self.stream is not None:
                try:
                    self.stream.close()
                except OSError:
                    pass
        finally:
            if self.client is not None:
                try:
                    self.client.close()
                except OSError:
                    pass
            self.stream = self.client = None

    def metadata(self):
        return {'headless_refresh_hz_requested': 10, 'headless_refresh_accepted_count': self.count,
                'headless_refresh_total_seconds': round(self.total_seconds, 4),
                'headless_refresh_max_seconds': round(self.max_seconds, 4),
                'headless_refresh_intermediate_pixels_saved': False,
                'headless_refresh_does_not_validate_ui': True}
