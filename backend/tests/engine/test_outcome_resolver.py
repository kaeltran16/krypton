import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from app.engine.outcome_resolver import resolve_signal_outcome


def test_long_tp1_hit():
    signal = {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67100.0, "low": 66900.0, "close": 67050.0, "timestamp": "2026-03-01T12:15:00+00:00"},
        {"high": 67600.0, "low": 67000.0, "close": 67550.0, "timestamp": "2026-03-01T12:30:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result["outcome"] == "TP1_HIT"
    assert result["outcome_pnl_pct"] == pytest.approx(0.7463, rel=0.01)


def test_long_sl_hit():
    signal = {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67050.0, "low": 66400.0, "close": 66450.0, "timestamp": "2026-03-01T12:15:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result["outcome"] == "SL_HIT"
    assert result["outcome_pnl_pct"] < 0


def test_short_tp1_hit():
    signal = {
        "direction": "SHORT",
        "entry": 67000.0,
        "stop_loss": 67500.0,
        "take_profit_1": 66500.0,
        "take_profit_2": 66000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67050.0, "low": 66400.0, "close": 66450.0, "timestamp": "2026-03-01T12:15:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result["outcome"] == "TP1_HIT"


def test_no_resolution_yet():
    signal = {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67200.0, "low": 66800.0, "close": 67100.0, "timestamp": "2026-03-01T12:15:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result is None
