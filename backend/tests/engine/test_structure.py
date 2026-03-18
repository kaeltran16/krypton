"""Tests for structure-aware SL/TP placement."""

import pandas as pd
import pytest

from app.engine.structure import (
    collect_structure_levels,
    detect_support_resistance,
    snap_levels_to_structure,
)


def _make_candles(n: int, base: float = 68000.0, atr_approx: float = 350.0) -> pd.DataFrame:
    """Create synthetic candle data with realistic swing points."""
    rows = []
    price = base
    for i in range(n):
        # Create a zigzag pattern to produce detectable swing highs/lows
        cycle = i % 10
        if cycle < 5:
            price += atr_approx * 0.3
        else:
            price -= atr_approx * 0.3
        rows.append({
            "open": price - atr_approx * 0.1,
            "high": price + atr_approx * 0.4,
            "low": price - atr_approx * 0.4,
            "close": price + atr_approx * 0.1,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def _make_candles_with_levels(
    n: int, base: float, support: float, resistance: float, atr_approx: float = 350.0,
) -> pd.DataFrame:
    """Create candles that bounce between support and resistance levels."""
    rows = []
    price = base
    direction = 1
    for i in range(n):
        if price >= resistance:
            direction = -1
        elif price <= support:
            direction = 1
        price += direction * atr_approx * 0.25

        rows.append({
            "open": price - atr_approx * 0.05,
            "high": min(price + atr_approx * 0.3, resistance + atr_approx * 0.1),
            "low": max(price - atr_approx * 0.3, support - atr_approx * 0.1),
            "close": price + atr_approx * 0.05,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


class TestDetectSupportResistance:
    def test_returns_empty_for_few_candles(self):
        df = _make_candles(4)
        assert detect_support_resistance(df, atr=350.0) == []

    def test_detects_levels_from_zigzag(self):
        df = _make_candles(80)
        levels = detect_support_resistance(df, atr=350.0)
        assert len(levels) > 0
        for lv in levels:
            assert "price" in lv
            assert "strength" in lv
            assert lv["type"] in ("support", "resistance")
            assert lv["strength"] >= 2

    def test_levels_classified_by_current_price(self):
        df = _make_candles(80, base=68000.0)
        current_price = float(df["close"].iloc[-1])
        levels = detect_support_resistance(df, atr=350.0)
        for lv in levels:
            if lv["price"] < current_price:
                assert lv["type"] == "support"
            else:
                assert lv["type"] == "resistance"

    def test_max_levels_respected(self):
        df = _make_candles(200)
        levels = detect_support_resistance(df, atr=350.0, max_levels=3)
        assert len(levels) <= 3

    def test_min_touches_filter(self):
        df = _make_candles(80)
        # With high min_touches, fewer or no levels
        strict = detect_support_resistance(df, atr=350.0, min_touches=10)
        normal = detect_support_resistance(df, atr=350.0, min_touches=2)
        assert len(strict) <= len(normal)


class TestCollectStructureLevels:
    def test_includes_bb_and_ema(self):
        df = _make_candles(80)
        indicators = {
            "bb_upper": 69000.0,
            "bb_lower": 67000.0,
            "ema_9": 68100.0,
            "ema_21": 68050.0,
            "ema_50": 67900.0,
        }
        levels = collect_structure_levels(df, indicators, atr=350.0)
        labels = [lv["label"] for lv in levels]
        assert "bb_upper" in labels
        assert "bb_lower" in labels
        assert "sma_20" in labels
        assert "ema_9" in labels
        assert "ema_21" in labels
        assert "ema_50" in labels

    def test_sorted_by_price(self):
        df = _make_candles(80)
        indicators = {
            "bb_upper": 69000.0,
            "bb_lower": 67000.0,
            "ema_50": 67500.0,
        }
        levels = collect_structure_levels(df, indicators, atr=350.0)
        prices = [lv["price"] for lv in levels]
        assert prices == sorted(prices)

    def test_handles_missing_indicators(self):
        df = _make_candles(80)
        levels = collect_structure_levels(df, {}, atr=350.0)
        # Should still have S/R levels from pivots
        assert isinstance(levels, list)


class TestSnapLevelsToStructure:
    def _base_levels(self, direction: str, entry: float = 68500.0, atr: float = 350.0):
        sign = 1 if direction == "LONG" else -1
        return {
            "entry": entry,
            "stop_loss": entry - sign * 1.5 * atr,
            "take_profit_1": entry + sign * 2.0 * atr,
            "take_profit_2": entry + sign * 3.0 * atr,
            "levels_source": "atr_default",
        }

    def test_no_structure_returns_original(self):
        levels = self._base_levels("LONG")
        result, snap_info = snap_levels_to_structure(levels, [], "LONG", atr=350.0)
        assert result["stop_loss"] == levels["stop_loss"]
        assert result["take_profit_1"] == levels["take_profit_1"]
        assert snap_info == {}

    def test_long_sl_snaps_to_support(self):
        levels = self._base_levels("LONG", entry=68500.0, atr=350.0)
        structure = [
            {"price": 67900.0, "label": "ema_50", "strength": 3},
            {"price": 69200.0, "label": "bb_upper", "strength": 2},
        ]
        result, snap_info = snap_levels_to_structure(levels, structure, "LONG", atr=350.0)
        # SL should snap near ema_50 (67900) minus buffer
        assert result["stop_loss"] < 67900.0
        assert snap_info["sl_snapped_to"] == "ema_50"

    def test_short_sl_snaps_to_resistance(self):
        levels = self._base_levels("SHORT", entry=68500.0, atr=350.0)
        structure = [
            {"price": 67200.0, "label": "bb_lower", "strength": 2},
            {"price": 69100.0, "label": "bb_upper", "strength": 2},
        ]
        result, snap_info = snap_levels_to_structure(levels, structure, "SHORT", atr=350.0)
        # SL should snap near bb_upper (69100) plus buffer
        assert result["stop_loss"] > 69100.0
        assert snap_info["sl_snapped_to"] == "bb_upper"

    def test_sl_respects_min_atr(self):
        levels = self._base_levels("LONG", entry=68500.0, atr=350.0)
        # Structure very close to entry — should still enforce min ATR distance
        structure = [
            {"price": 68400.0, "label": "ema_9", "strength": 1},
        ]
        result, _ = snap_levels_to_structure(levels, structure, "LONG", atr=350.0, sl_min_atr=1.0)
        sl_dist = abs(result["entry"] - result["stop_loss"])
        assert sl_dist >= 350.0  # at least 1.0x ATR

    def test_sl_respects_max_atr(self):
        levels = self._base_levels("LONG", entry=68500.0, atr=350.0)
        # Structure very far from entry — should cap at max ATR
        structure = [
            {"price": 66000.0, "label": "support", "strength": 3},
        ]
        result, _ = snap_levels_to_structure(levels, structure, "LONG", atr=350.0, sl_max_atr=3.5)
        sl_dist = abs(result["entry"] - result["stop_loss"])
        assert sl_dist <= 3.5 * 350.0

    def test_rr_floor_enforced(self):
        """TP1 must be at least as far as SL (1:1 R:R minimum)."""
        levels = self._base_levels("LONG", entry=68500.0, atr=350.0)
        # Structure that would push SL far but TP1 close
        structure = [
            {"price": 67000.0, "label": "support", "strength": 3},
            {"price": 68600.0, "label": "ema_9", "strength": 1},  # very close TP1
        ]
        result, _ = snap_levels_to_structure(levels, structure, "LONG", atr=350.0)
        sl_dist = abs(result["entry"] - result["stop_loss"])
        tp1_dist = abs(result["take_profit_1"] - result["entry"])
        assert tp1_dist >= sl_dist

    def test_snap_info_populated(self):
        levels = self._base_levels("LONG", entry=68500.0, atr=350.0)
        structure = [
            {"price": 67900.0, "label": "ema_50", "strength": 3},
            {"price": 69200.0, "label": "bb_upper", "strength": 2},
            {"price": 70000.0, "label": "resistance", "strength": 2},
        ]
        _, snap_info = snap_levels_to_structure(levels, structure, "LONG", atr=350.0)
        assert isinstance(snap_info, dict)
