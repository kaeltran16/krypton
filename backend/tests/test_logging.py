import json
import logging

from app.logging_config import JsonFormatter


def test_json_formatter_basic():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.collector.onchain",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Tier 1 poll failed: timeout",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "ERROR"
    assert data["module"] == "app.collector.onchain"
    assert data["msg"] == "Tier 1 poll failed: timeout"
    assert "ts" in data


def test_json_formatter_extracts_pair():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.engine",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Processing BTC-USDT-SWAP candle",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["pair"] == "BTC-USDT-SWAP"


def test_json_formatter_no_pair():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.main",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Server starting",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "pair" not in data


def test_json_formatter_with_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.main",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Something failed",
        args=(),
        exc_info=exc_info,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "traceback" in data
    assert "ValueError: test error" in data["traceback"]


def test_json_formatter_with_args():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.main",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="Failed for %s: %s",
        args=("BTC-USDT-SWAP", "timeout"),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["msg"] == "Failed for BTC-USDT-SWAP: timeout"
    assert data["pair"] == "BTC-USDT-SWAP"


def test_error_log_model_fields():
    from app.db.models import ErrorLog

    row = ErrorLog(
        level="ERROR",
        module="app.collector.onchain",
        message="Tier 1 poll failed",
        traceback=None,
        pair="BTC-USDT-SWAP",
    )
    assert row.level == "ERROR"
    assert row.module == "app.collector.onchain"
    assert row.message == "Tier 1 poll failed"
    assert row.traceback is None
    assert row.pair == "BTC-USDT-SWAP"


def test_db_handler_captures_error():
    from unittest.mock import MagicMock
    from app.logging_config import DBErrorHandler

    mock_session_factory = MagicMock()
    handler = DBErrorHandler(session_factory=mock_session_factory)

    record = logging.LogRecord(
        name="app.collector.onchain",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="BTC-USDT-SWAP poll failed: timeout",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    assert len(handler._buffer) == 1
    entry = handler._buffer[0]
    assert entry["level"] == "ERROR"
    assert entry["module"] == "app.collector.onchain"
    assert entry["message"] == "BTC-USDT-SWAP poll failed: timeout"
    assert entry["pair"] == "BTC-USDT-SWAP"


def test_db_handler_ignores_info():
    from unittest.mock import MagicMock
    from app.logging_config import DBErrorHandler

    mock_session_factory = MagicMock()
    handler = DBErrorHandler(session_factory=mock_session_factory)

    record = logging.LogRecord(
        name="app.main",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Server starting",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    assert len(handler._buffer) == 0
