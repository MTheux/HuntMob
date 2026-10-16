"""One screen encoder per owned device, with a latest-frame relay for all viewers."""
from __future__ import annotations

import select
import subprocess
import threading
import time


class ScreenRelay:
    def __init__(self):
        self.condition = threading.Condition()
        self.thread = None
        self.frame = b""
        self.sequence = 0
        self.last_viewer = 0.0
        self.error = ""
        self.closing = threading.Event()

    def shutdown(self):
        self.closing.set()
        with self.condition:
            self.error = "Video server shutting down"
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=8)

    def restart(self):
        self.shutdown()
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Previous video session has not stopped")
        with self.condition:
            self.closing.clear()
            self.error = ""
            self.frame = b""
            self.thread = None

    def get_frame(self, adb: str, serial: str, ffmpeg: str, after: int = -1, timeout: float = 15):
        with self.condition:
            if self.closing.is_set():
                raise RuntimeError("Video server shutting down")
            self.last_viewer = time.monotonic()
            if self.thread is None or not self.thread.is_alive():
                self.frame = b""
                self.error = ""
                self.thread = threading.Thread(target=self._produce, args=(adb, serial, ffmpeg), daemon=True)
                self.thread.start()
            deadline = time.monotonic() + timeout
            while not self.frame or self.sequence <= after:
                if self.error:
                    raise RuntimeError(self.error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if self.frame:
                        return self.sequence, self.frame
                    raise TimeoutError("No Android video frame received")
                self.last_viewer = time.monotonic()
                self.condition.wait(min(remaining, 1))
            return self.sequence, self.frame

    def _produce(self, adb, serial, ffmpeg):
        recorder = decoder = None
        guest_pid = None
        try:
            screenshot = subprocess.run((adb, "-s", serial, "exec-out", "screencap", "-p"), capture_output=True, timeout=10)
            seed = subprocess.run((ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-vf", "scale=540:1200", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"), input=screenshot.stdout, capture_output=True, timeout=5)
            if seed.returncode == 0 and seed.stdout:
                with self.condition:
                    self.frame = seed.stdout
                    self.sequence += 1
                    self.condition.notify_all()
            # The fixed command returns its own PID before the H264 stream, so
            # teardown can stop this recording without touching other tools.
            command = "echo $$; exec screenrecord --output-format=h264 --size 540x1200 --bit-rate 2000000 --time-limit 180 -"
            recorder = subprocess.Popen((adb, "-s", serial, "exec-out", "sh", "-c", command), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            if not select.select([recorder.stdout], [], [], 5)[0]:
                raise TimeoutError("Android screen encoder did not start")
            pid_line = bytearray()
            while len(pid_line) < 16:
                byte = recorder.stdout.read(1)
                if byte == b"\n":
                    break
                if not byte:
                    raise RuntimeError("Android screen encoder exited")
                pid_line.extend(byte)
            guest_pid = int(pid_line)
            decoder = subprocess.Popen(
                (ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "+genpts", "-flags", "low_delay",
                 "-probesize", "32", "-analyzeduration", "0", "-f", "h264", "-i", "pipe:0",
                 "-q:v", "5", "-flush_packets", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"),
                stdin=recorder.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            recorder.stdout.close()
            buffer = bytearray()
            last_frame = time.monotonic()
            while not self.closing.is_set() and time.monotonic() - self.last_viewer < 10:
                if not select.select([decoder.stdout], [], [], 1)[0]:
                    if decoder.poll() is not None or recorder.poll() is not None:
                        raise RuntimeError("Android video ended")
                    continue
                chunk = decoder.stdout.read(65536)
                if not chunk:
                    raise RuntimeError("Android video ended")
                buffer.extend(chunk)
                if len(buffer) > 8 * 1024 * 1024:
                    raise RuntimeError("Android video frame exceeds limit")
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", max(start, 0) + 2)
                    if start < 0 or end < 0:
                        break
                    frame = bytes(buffer[start:end + 2])
                    del buffer[:end + 2]
                    with self.condition:
                        self.frame = frame
                        self.sequence += 1
                        last_frame = time.monotonic()
                        self.condition.notify_all()
        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
            with self.condition:
                self.error = str(error)
                self.condition.notify_all()
        finally:
            if guest_pid is not None:
                try:
                    subprocess.run((adb, "-s", serial, "shell", "kill", "-INT", str(guest_pid)), capture_output=True, timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            for process in (decoder, recorder):
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            with self.condition:
                self.frame = b""
                if not self.error:
                    self.error = "Video session closed"
                self.condition.notify_all()


SCREEN_RELAY = ScreenRelay()
