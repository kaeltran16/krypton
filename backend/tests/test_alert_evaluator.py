import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from app.engine.alert_evaluator import (
    check_price_condition,
    check_cooldown,
    is_in_quiet_hours,
    check_signal_filters,
    check_indicator_condition,
)


def test_crosses_above_true():
    assert check_price_condition("crosses_above", 70000, 69999, 70001) is True

def test_crosses_above_false_already_above():
    assert check_price_condition("crosses_above", 70000, 70001, 70500) is False

def test_crosses_above_false_still_below():
    assert check_price_condition("crosses_above", 70000, 69000, 69500) is False

def test_crosses_below_true():
    assert check_price_condition("crosses_below", 60000, 60001, 59999) is True

def test_crosses_below_false_already_below():
    assert check_price_condition("crosses_below", 60000, 59999, 59500) is False

def test_pct_move_true():
    # 5% move: price was 100, now 106
    assert check_price_condition("pct_move", 5.0, 100.0, 106.0) is True

def test_pct_move_false():
    # 5% move: price was 100, now 103 (only 3%)
    assert check_price_condition("pct_move", 5.0, 100.0, 103.0) is False

def test_cooldown_not_expired():
    last = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert check_cooldown(last, cooldown_minutes=15) is False

def test_cooldown_expired():
    last = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert check_cooldown(last, cooldown_minutes=15) is True

def test_cooldown_never_triggered():
    assert check_cooldown(None, cooldown_minutes=15) is True

def test_quiet_hours_inside():
    # 23:00 UTC, quiet hours 22:00-08:00 UTC
    now = datetime(2026, 3, 15, 23, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, True, "22:00", "08:00", "UTC") is True

def test_quiet_hours_outside():
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, True, "22:00", "08:00", "UTC") is False

def test_quiet_hours_disabled():
    now = datetime(2026, 3, 15, 23, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, False, "22:00", "08:00", "UTC") is False


# Signal filter tests

def test_signal_filter_all_null_matches():
    assert check_signal_filters({}, {"pair": "BTC", "direction": "LONG"}) is True

def test_signal_filter_pair_match():
    assert check_signal_filters({"pair": "BTC-USDT-SWAP"}, {"pair": "BTC-USDT-SWAP", "final_score": 50}) is True

def test_signal_filter_pair_mismatch():
    assert check_signal_filters({"pair": "BTC-USDT-SWAP"}, {"pair": "ETH-USDT-SWAP"}) is False

def test_signal_filter_min_score():
    assert check_signal_filters({"min_score": 60}, {"final_score": 70}) is True
    assert check_signal_filters({"min_score": 60}, {"final_score": 50}) is False

def test_signal_filter_direction():
    assert check_signal_filters({"direction": "LONG"}, {"direction": "LONG", "final_score": 0}) is True
    assert check_signal_filters({"direction": "LONG"}, {"direction": "SHORT", "final_score": 0}) is False

def test_signal_filter_combined():
    filters = {"pair": "BTC-USDT-SWAP", "direction": "LONG", "min_score": 50}
    assert check_signal_filters(filters, {"pair": "BTC-USDT-SWAP", "direction": "LONG", "final_score": 60}) is True
    assert check_signal_filters(filters, {"pair": "BTC-USDT-SWAP", "direction": "SHORT", "final_score": 60}) is False


# Indicator condition tests

def test_indicator_gt():
    assert check_indicator_condition("gt", 70, 75) is True
    assert check_indicator_condition("gt", 70, 65) is False

def test_indicator_lt():
    assert check_indicator_condition("lt", 30, 25) is True
    assert check_indicator_condition("lt", 30, 35) is False
