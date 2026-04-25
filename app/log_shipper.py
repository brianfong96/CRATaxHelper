"""Aether centralized log shipper (same pattern as other Aether services)."""

from __future__ import annotations

import atexit
import json
import logging
import socket
import threading
import traceback
import urllib.error
import urllib.request


class AetherLogHandler(logging.Handler):
    """Ships log entries to the Archive service in batches."""

    def __init__(self, service: str, archive_url: str = "http://archive:7000",
                 buffer_size: int = 50, flush_interval: float = 5.0,
                 level: int = logging.INFO):
        super().__init__(level)
        self.service = service
        self.archive_url = archive_url.rstrip("/")
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.machine_id = socket.gethostname()
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._start_timer()
        atexit.register(self.flush)

    def emit(self, record: logging.LogRecord):
        entry = {
            "service": self.service,
            "level": record.levelname,
            "event": record.name,
            "message": record.getMessage(),
            "machine_id": self.machine_id,
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = "".join(traceback.format_exception(*record.exc_info))
        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self.buffer_size:
                self._do_flush()

    def flush(self):
        with self._lock:
            self._do_flush()

    def _do_flush(self):
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        try:
            url = f"{self.archive_url}/api/v1/logs/batch"
            data = json.dumps({"logs": batch}).encode()
            req = urllib.request.Request(url, data=data, method="POST")  # noqa: S310
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                resp.read()
        except Exception:  # noqa: S110
            pass

    def _start_timer(self):
        self._timer = threading.Timer(self.flush_interval, self._timer_flush)
        self._timer.daemon = True
        self._timer.start()

    def _timer_flush(self):
        self.flush()
        self._start_timer()
