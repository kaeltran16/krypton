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


# -- Two-pass resolution tests (atr provided) --

def _long_signal():
    return {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68500.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }


def _short_signal():
    return {
        "direction": "SHORT",
        "entry": 67000.0,
        "stop_loss": 67500.0,
        "take_profit_1": 66500.0,
        "take_profit_2": 65500.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }


class TestTwoPassLong:
    def test_tp1_then_trail_hit(self):
        """TP1 hit on candle 1, trail ratchets up, trail hit on candle 3."""
        candles = [
            {"high": 67600.0, "low": 67050.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit (67600>=67500)
            {"high": 67900.0, "low": 67600.0, "close": 67850.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # trail ratchets: max(67300, 67900-200)=67700
            {"high": 67800.0, "low": 67650.0, "close": 67700.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail: max(67700, 67800-200)=67700, low=67650<=67700 → HIT
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TRAIL"
        # tp1_pnl = (67500-67000)/67000*100 = 0.7463%
        # trail_pnl = (67700-67000)/67000*100 = 1.0448%
        # blended = 0.5*0.7463 + 0.5*1.0448 = 0.8955%
        assert result["outcome_pnl_pct"] == pytest.approx(0.8955, abs=0.01)
        assert result["partial_exit_pnl_pct"] == pytest.approx(0.7463, abs=0.01)
        assert result["trail_exit_pnl_pct"] == pytest.approx(1.0448, abs=0.01)
        assert result["trail_exit_price"] == pytest.approx(67700.0, abs=1.0)

    def test_tp1_then_tp2_hit(self):
        """TP1 hit, then TP2 hit → TP1_TP2."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 68600.0, "low": 67800.0, "close": 68500.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # TP2 hit (68600>=68500)
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TP2"
        # tp1_pnl = 0.7463%, tp2_pnl = (68500-67000)/67000*100 = 2.2388%
        # blended = 0.5*0.7463 + 0.5*2.2388 = 1.4925%
        assert result["outcome_pnl_pct"] == pytest.approx(1.4925, abs=0.01)

    def test_trail_still_running_returns_none(self):
        """TP1 hit, trail not yet triggered → None (still pending)."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 67700.0, "low": 67600.0, "close": 67650.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # trail=max(67300,67700-200)=67500, low=67600>67500
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result is None

    def test_tp1_hit_on_last_candle_returns_none(self):
        """TP1 hit on the last candle, no more candles for Pass 2."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit, no more candles
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result is None

    def test_force_close_on_expiry(self):
        """TP1 hit, trail still running at expiry → force close at given price."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 67700.0, "low": 67600.0, "close": 67650.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # no trail hit
        ]
        result = resolve_signal_outcome(
            _long_signal(), candles, atr=200.0, force_close_price=67650.0,
        )
        assert result["outcome"] == "TP1_TRAIL"
        # tp1_pnl = 0.7463%, remainder_pnl = (67650-67000)/67000*100 = 0.9701%
        # blended = 0.5*0.7463 + 0.5*0.9701 = 0.8582%
        assert result["outcome_pnl_pct"] == pytest.approx(0.8582, abs=0.01)

    def test_sl_before_tp1_unchanged(self):
        """SL hit before TP1 → SL_HIT (same as legacy)."""
        candles = [
            {"high": 67050.0, "low": 66400.0, "close": 66450.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "SL_HIT"
        assert "partial_exit_pnl_pct" not in result

    def test_tp2_before_tp1_unchanged(self):
        """TP2 hit before TP1 (price blew past) → TP2_HIT."""
        candles = [
            {"high": 68600.0, "low": 67100.0, "close": 68500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP2_HIT"
        assert "partial_exit_pnl_pct" not in result


class TestTwoPassShort:
    def test_tp1_then_trail_hit(self):
        """SHORT: TP1 hit, trail ratchets down, trail hit."""
        candles = [
            {"high": 66900.0, "low": 66400.0, "close": 66450.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit (66400<=66500)
            {"high": 66250.0, "low": 66100.0, "close": 66200.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # trail=min(66700, 66100+200)=66300, high=66250<66300 no hit
            {"high": 66350.0, "low": 66050.0, "close": 66100.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail=min(66300, 66050+200)=66250, high=66350>=66250 → HIT
        ]
        result = resolve_signal_outcome(_short_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TRAIL"
        # tp1_pnl = (67000-66500)/67000*100 = 0.7463%
        # trail_pnl = (67000-66250)/67000*100 = 1.1194%
        # blended = 0.5*0.7463 + 0.5*1.1194 = 0.9328%
        assert result["outcome_pnl_pct"] == pytest.approx(0.9328, abs=0.02)

    def test_tp1_then_tp2_hit(self):
        """SHORT: TP1 hit, then TP2 hit → TP1_TP2."""
        candles = [
            {"high": 66900.0, "low": 66400.0, "close": 66450.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 66100.0, "low": 65400.0, "close": 65500.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # TP2 hit (65400<=65500)
        ]
        result = resolve_signal_outcome(_short_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TP2"


class TestBackwardCompatibility:
    def test_atr_none_returns_tp1_hit(self):
        """Without ATR, TP1 hit returns TP1_HIT (legacy behavior)."""
        candles = [
            {"high": 67600.0, "low": 67000.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
        ]
        result = resolve_signal_outcome(_long_signal(), candles)
        assert result["outcome"] == "TP1_HIT"
        assert "partial_exit_pnl_pct" not in result

    def test_atr_none_default_matches_legacy(self):
        """Calling with no extra args matches original behavior exactly."""
        signal = {
            "direction": "LONG",
            "entry": 67000.0,
            "stop_loss": 66500.0,
            "take_profit_1": 67500.0,
            "take_profit_2": 68000.0,
            "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        }
        candles = [
            {"high": 67100.0, "low": 66900.0, "close": 67050.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
            {"high": 67600.0, "low": 67000.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},
        ]
        result = resolve_signal_outcome(signal, candles)
        assert result["outcome"] == "TP1_HIT"
        assert result["outcome_pnl_pct"] == pytest.approx(0.7463, rel=0.01)


class TestPartialResultFields:
    def test_partial_exit_at_is_tp1_time(self):
        """partial_exit_at should be the TP1 hit candle timestamp."""
        candles = [
            {"high": 67600.0, "low": 67050.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
            {"high": 67800.0, "low": 67650.0, "close": 67700.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},
            {"high": 67750.0, "low": 67550.0, "close": 67600.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail hit
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result is not None
        assert result["partial_exit_at"] == datetime(2026, 3, 1, 12, 15, tzinfo=timezone.utc)
        assert result["outcome_at"] == datetime(2026, 3, 1, 12, 45, tzinfo=timezone.utc)

    def test_outcome_duration_is_creation_to_final_exit(self):
        """outcome_duration_minutes spans signal creation to final exit."""
        candles = [
            {"high": 67600.0, "low": 67050.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
            {"high": 67800.0, "low": 67650.0, "close": 67700.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},
            {"high": 67750.0, "low": 67550.0, "close": 67600.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail hit
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        # 12:00 → 12:45 = 45 minutes
        assert result["outcome_duration_minutes"] == 45
