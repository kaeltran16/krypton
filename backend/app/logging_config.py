import asyncio
import json
import logging
import os
import re
import threading
import traceback as tb_module
from datetime import datetime, timezone

_PAIR_RE = re.compile(r"\b([A-Z]{2,10}-USDT-SWAP)\b")


def _extract_pair(message: str) -> str | None:
    match = _PAIR_RE.search(message)
    return match.group(1) if match else None


def _format_traceback(record: logging.LogRecord) -> str | None:
    if record.exc_info and record.exc_info[0] is not None:
        return "".join(tb_module.format_exception(*record.exc_info))
    return None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        entry: dict = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "module": record.name,
            "msg": message,
        }
        pair = _extract_pair(message)
        if pair:
            entry["pair"] = pair
        tb = _format_traceback(record)
        if tb:
            entry["traceback"] = tb
        return json.dumps(entry, default=str)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    root.setLevel(logging.getLevelName(level_name))


class DBErrorHandler(logging.Handler):
    """Buffers WARNING+ log records and flushes to the error_log table periodically."""

    FLUSH_INTERVAL = 5
    MAX_BUFFER = 100

    def __init__(self, session_factory):
        super().__init__(level=logging.WARNING)
        self._session_factory = session_factory
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._flush_task: asyncio.Task | None = None

    def emit(self, record: logging.LogRecord):
        if record.levelno < logging.WARNING:
            return
        message = record.getMessage()
        entry = {
            "level": record.levelname,
            "module": record.name,
            "message": message,
            "traceback": _format_traceback(record),
            "pair": _extract_pair(message),
        }
        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self.MAX_BUFFER:
                self._schedule_flush()

    def _schedule_flush(self):
        try:
            loop = asyncio.get_running_loop()
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = loop.create_task(self._flush())
        except RuntimeError:
            pass

    async def start_flush_loop(self):
        while True:
            await asyncio.sleep(self.FLUSH_INTERVAL)
            await self._flush()

    async def _flush(self):
        from app.db.models import ErrorLog

        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()
        try:
            async with self._session_factory() as session:
                session.add_all([ErrorLog(**entry) for entry in batch])
                await session.commit()
        except Exception:
            with self._lock:
                self._buffer[:0] = batch[:self.MAX_BUFFER - len(self._buffer)]
