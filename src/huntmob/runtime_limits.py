"""Shared resource budgets for device streaming and uploads."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager


MAX_STREAMS = 4
MAX_UPLOADS = 2
MAX_STREAM_SECONDS = 30 * 60
STREAM_STALL_SECONDS = 8
MAX_CODEC_QUEUE_BYTES = 16 * 1024 * 1024

_STREAM_SLOTS = threading.BoundedSemaphore(MAX_STREAMS)
_UPLOAD_SLOTS = threading.BoundedSemaphore(MAX_UPLOADS)


class CapacityExceeded(RuntimeError):
    pass


@contextmanager
def stream_slot():
    if not _STREAM_SLOTS.acquire(blocking=False):
        raise CapacityExceeded("stream_capacity_exceeded")
    try:
        yield
    finally:
        _STREAM_SLOTS.release()


@contextmanager
def upload_slot():
    if not _UPLOAD_SLOTS.acquire(blocking=False):
        raise CapacityExceeded("upload_capacity_exceeded")
    started = time.monotonic()
    try:
        yield lambda: time.monotonic() - started
    finally:
        _UPLOAD_SLOTS.release()
