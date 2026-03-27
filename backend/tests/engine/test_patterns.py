import pandas as pd
import pytest

from app.engine.patterns import detect_candlestick_patterns, compute_pattern_score


def _make_candles(rows: list[dict]) -> pd.DataFrame:
    """Helper to build a DataFrame from OHLCV dicts, padded to 10 rows for avg_body."""
    base = {"open": 100, "high": 105, "low": 95, "close": 102, "volume": 50}
    padding = [base.copy() for _ in range(max(0, 10 - len(rows)))]
    return pd.DataFrame(padding + rows)


class TestSingleCandlePatterns:

    def test_hammer_detected(self):
        # Small body at top, long lower shadow, no upper shadow
        candles = _make_candles([
            {"open": 100.3, "high": 100.5, "low": 90, "close": 100.5, "volume": 50},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hammer" in names

    def test_inverted_hammer_detected(self):
        # Small body at bottom, long upper shadow, no lower shadow
        candles = _make_candles([
            {"open": 100, "high": 110, "low": 100, "close": 100.2, "volume": 50},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Inverted Hammer" in names

    def test_doji_detected(self):
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Doji" in names

    def test_marubozu_bullish(self):
        candles = _make_candles([
            {"open": 100, "high": 110.2, "low": 99.8, "close": 110, "volume": 50},
        ])
        patterns = detect_candlestick_patterns(candles)
        marubozus = [p for p in patterns if p["name"] == "Marubozu"]
        assert len(marubozus) == 1
        assert marubozus[0]["bias"] == "bullish"

    def test_marubozu_bearish(self):
        candles = _make_candles([
            {"open": 110, "high": 110.2, "low": 99.8, "close": 100, "volume": 50},
        ])
        patterns = detect_candlestick_patterns(candles)
        marubozus = [p for p in patterns if p["name"] == "Marubozu"]
        assert len(marubozus) == 1
        assert marubozus[0]["bias"] == "bearish"


class TestTwoCandlePatterns:

    def test_bullish_engulfing(self):
        candles = _make_candles([
            {"open": 105, "high": 106, "low": 99, "close": 100, "volume": 50},
            {"open": 99, "high": 108, "low": 98, "close": 107, "volume": 80},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Bullish Engulfing" in names

    def test_bearish_engulfing(self):
        candles = _make_candles([
            {"open": 100, "high": 106, "low": 99, "close": 105, "volume": 50},
            {"open": 106, "high": 107, "low": 97, "close": 98, "volume": 80},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Bearish Engulfing" in names

    def test_piercing_line(self):
        candles = _make_candles([
            {"open": 108, "high": 109, "low": 100, "close": 101, "volume": 50},
            {"open": 99, "high": 106, "low": 98, "close": 105.5, "volume": 60},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Piercing Line" in names

    def test_dark_cloud_cover(self):
        candles = _make_candles([
            {"open": 100, "high": 108, "low": 99, "close": 107, "volume": 50},
            {"open": 109, "high": 110, "low": 102, "close": 102.5, "volume": 60},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Dark Cloud Cover" in names


class TestThreeCandlePatterns:

    def test_morning_star(self):
        candles = _make_candles([
            {"open": 110, "high": 111, "low": 100, "close": 101, "volume": 50},
            {"open": 101, "high": 102, "low": 100, "close": 100.5, "volume": 30},
            {"open": 101, "high": 112, "low": 100, "close": 109, "volume": 70},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Morning Star" in names

    def test_evening_star(self):
        candles = _make_candles([
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 50},
            {"open": 109, "high": 110, "low": 108, "close": 109.5, "volume": 30},
            {"open": 109, "high": 110, "low": 100, "close": 101, "volume": 70},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Evening Star" in names

    def test_three_white_soldiers(self):
        candles = _make_candles([
            {"open": 100, "high": 107, "low": 99, "close": 106, "volume": 50},
            {"open": 106, "high": 113, "low": 105, "close": 112, "volume": 55},
            {"open": 112, "high": 119, "low": 111, "close": 118, "volume": 60},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Three White Soldiers" in names

    def test_three_black_crows(self):
        candles = _make_candles([
            {"open": 118, "high": 119, "low": 111, "close": 112, "volume": 50},
            {"open": 112, "high": 113, "low": 105, "close": 106, "volume": 55},
            {"open": 106, "high": 107, "low": 99, "close": 100, "volume": 60},
        ])
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Three Black Crows" in names


class TestNoFalsePositives:

    def test_flat_candles_no_patterns(self):
        """Candles with minimal movement should not trigger strong patterns."""
        rows = [
            {"open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 50}
            for _ in range(10)
        ]
        candles = pd.DataFrame(rows)
        patterns = detect_candlestick_patterns(candles)
        strong = [p for p in patterns if p["strength"] >= 12]
        assert len(strong) == 0


class TestPatternScoring:

    def test_bullish_pattern_positive_score(self):
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        result = compute_pattern_score(patterns)
        assert result["score"] > 0

    def test_bearish_pattern_negative_score(self):
        patterns = [{"name": "Bearish Engulfing", "type": "candlestick", "bias": "bearish", "strength": 15}]
        result = compute_pattern_score(patterns)
        assert result["score"] < 0

    def test_stacking_patterns(self):
        patterns = [
            {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
            {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15},
        ]
        result = compute_pattern_score(patterns)
        assert result["score"] == 27  # 12 + 15

    def test_neutral_pattern_no_score(self):
        patterns = [{"name": "Doji", "type": "candlestick", "bias": "neutral", "strength": 8}]
        result = compute_pattern_score(patterns)
        assert result["score"] == 0

    def test_empty_patterns_zero_score(self):
        assert compute_pattern_score([])["score"] == 0

    def test_score_clamped_to_100(self):
        patterns = [
            {"name": f"Pat{i}", "type": "candlestick", "bias": "bullish", "strength": 15}
            for i in range(10)
        ]
        result = compute_pattern_score(patterns)
        assert result["score"] == 100

    def test_level_proximity_boost(self):
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        _NEAR_LOWER_BB_CTX = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.01, "close": 100}
        score_boosted = compute_pattern_score(patterns, _NEAR_LOWER_BB_CTX)["score"]
        score_normal = compute_pattern_score(patterns)["score"]
        assert score_boosted > score_normal

    def test_near_upper_band_boost(self):
        patterns = [{"name": "Bearish Engulfing", "type": "candlestick", "bias": "bearish", "strength": 15}]
        _NEAR_UPPER_BB_CTX = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.99, "close": 100}
        score_boosted = compute_pattern_score(patterns, _NEAR_UPPER_BB_CTX)["score"]
        score_normal = compute_pattern_score(patterns)["score"]
        assert abs(score_boosted) > abs(score_normal)


class TestTrendAlignmentBoost:
    def test_reversal_pattern_gets_boost(self):
        """Bullish pattern in bearish ADX trend (reversal) gets 1.3x."""
        patterns = [{"name": "Bullish Engulfing", "type": "two_candle", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score > 15  # boosted above base strength

    def test_weak_trend_no_boost(self):
        """ADX < 15 — no trend-alignment boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score == 12  # no boost


class TestVolumeConfirmationBoost:
    def test_high_volume_gets_boost(self):
        """Volume ratio > 1.5 gets 1.3x boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 2.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score > 12

    def test_normal_volume_no_boost(self):
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score == 12


class TestLevelProximityBoost:
    def test_near_band_edge_gets_boost(self):
        """bb_pos near 0 or 1 should boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.05, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score > 12

    def test_center_no_boost(self):
        """bb_pos at 0.5 — no boost (1.0x)."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score == 12

    def test_boost_never_below_one(self):
        """Level proximity boost should never go below 1.0."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        for bb in [0.0, 0.2, 0.3, 0.5, 0.7, 0.8, 1.0]:
            ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
                   "bb_pos": bb, "close": 100}
            score = compute_pattern_score(patterns, ctx)["score"]
            assert score >= 12  # never penalized


class TestDojiBiasContext:
    def test_doji_bearish_in_uptrend(self):
        """Doji in uptrend gets bearish bias (potential reversal)."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "bearish"

    def test_doji_bullish_in_downtrend(self):
        """Doji in downtrend gets bullish bias."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "bullish"

    def test_doji_neutral_low_adx(self):
        """Doji stays neutral in ranging market (ADX < 15)."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "neutral"

    def test_doji_neutral_without_ctx(self):
        """Doji stays neutral without indicator_ctx (backward compat)."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        patterns = detect_candlestick_patterns(candles)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "neutral"

    def test_spinning_top_bearish_in_uptrend(self):
        """Spinning Top in uptrend gets bearish bias."""
        candles = _make_candles([
            {"open": 100, "high": 103, "low": 97, "close": 100.7, "volume": 50},
        ])
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        sp = next((p for p in patterns if p["name"] == "Spinning Top"), None)
        assert sp is not None
        assert sp["bias"] == "bearish"


class TestStrengthProportionalDetection:
    # -- Engulfing (3.1) --
    def test_bullish_engulfing_scales_by_ratio(self):
        """Barely engulfing gets weaker strength than dominant engulfing."""
        barely = _make_candles([
            {"open": 105, "high": 106, "low": 99, "close": 100, "volume": 50},
            {"open": 99, "high": 106, "low": 98, "close": 105.1, "volume": 80},
        ])
        dominant = _make_candles([
            {"open": 102, "high": 103, "low": 99, "close": 100, "volume": 50},
            {"open": 99, "high": 108, "low": 98, "close": 107, "volume": 80},
        ])
        barely_eng = next(p for p in detect_candlestick_patterns(barely) if p["name"] == "Bullish Engulfing")
        dominant_eng = next(p for p in detect_candlestick_patterns(dominant) if p["name"] == "Bullish Engulfing")
        assert dominant_eng["strength"] > barely_eng["strength"]

    def test_bearish_engulfing_scales_by_ratio(self):
        """Same scaling applies to bearish engulfing."""
        barely = _make_candles([
            {"open": 100, "high": 106, "low": 99, "close": 105, "volume": 50},
            {"open": 106, "high": 107, "low": 99.5, "close": 99.9, "volume": 80},
        ])
        dominant = _make_candles([
            {"open": 100, "high": 103, "low": 99, "close": 102, "volume": 50},
            {"open": 103, "high": 104, "low": 92, "close": 93, "volume": 80},
        ])
        barely_eng = next(p for p in detect_candlestick_patterns(barely) if p["name"] == "Bearish Engulfing")
        dominant_eng = next(p for p in detect_candlestick_patterns(dominant) if p["name"] == "Bearish Engulfing")
        assert dominant_eng["strength"] > barely_eng["strength"]

    # -- Piercing / Dark Cloud (3.2) --
    def test_piercing_line_scales_by_penetration(self):
        """Deep penetration gives higher strength than barely past midpoint."""
        shallow = _make_candles([
            {"open": 110, "high": 111, "low": 100, "close": 101, "volume": 50},
            {"open": 100, "high": 106.5, "low": 99, "close": 106, "volume": 60},
        ])
        deep = _make_candles([
            {"open": 110, "high": 111, "low": 100, "close": 101, "volume": 50},
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 60},
        ])
        shallow_pl = next(p for p in detect_candlestick_patterns(shallow) if p["name"] == "Piercing Line")
        deep_pl = next(p for p in detect_candlestick_patterns(deep) if p["name"] == "Piercing Line")
        assert deep_pl["strength"] > shallow_pl["strength"]

    def test_dark_cloud_scales_by_penetration(self):
        """Deep dark cloud penetration gives higher strength."""
        shallow = _make_candles([
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 50},
            {"open": 110, "high": 111, "low": 103.5, "close": 104, "volume": 60},
        ])
        deep = _make_candles([
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 50},
            {"open": 110, "high": 111, "low": 100, "close": 101, "volume": 60},
        ])
        shallow_dc = next(p for p in detect_candlestick_patterns(shallow) if p["name"] == "Dark Cloud Cover")
        deep_dc = next(p for p in detect_candlestick_patterns(deep) if p["name"] == "Dark Cloud Cover")
        assert deep_dc["strength"] > shallow_dc["strength"]

    # -- Three White Soldiers / Black Crows exhaustion (3.3) --
    def test_three_white_soldiers_exhaustion_reduces_strength(self):
        """Shrinking last body reduces strength."""
        healthy = _make_candles([
            {"open": 100, "high": 107, "low": 99, "close": 106, "volume": 50},
            {"open": 106, "high": 113, "low": 105, "close": 112, "volume": 55},
            {"open": 112, "high": 119, "low": 111, "close": 118, "volume": 60},
        ])
        exhausted = _make_candles([
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 50},
            {"open": 109, "high": 118, "low": 108, "close": 117, "volume": 55},
            {"open": 117, "high": 120, "low": 116, "close": 119, "volume": 60},
        ])
        healthy_3ws = next(p for p in detect_candlestick_patterns(healthy) if p["name"] == "Three White Soldiers")
        exhausted_3ws = next(p for p in detect_candlestick_patterns(exhausted) if p["name"] == "Three White Soldiers")
        assert healthy_3ws["strength"] > exhausted_3ws["strength"]

    def test_three_black_crows_exhaustion_reduces_strength(self):
        """Growing lower shadow on last candle reduces strength."""
        healthy = _make_candles([
            {"open": 118, "high": 119, "low": 111, "close": 112, "volume": 50},
            {"open": 112, "high": 113, "low": 105, "close": 106, "volume": 55},
            {"open": 106, "high": 107, "low": 99, "close": 100, "volume": 60},
        ])
        exhausted = _make_candles([
            {"open": 118, "high": 119, "low": 111, "close": 112, "volume": 50},
            {"open": 112, "high": 113, "low": 105, "close": 106, "volume": 55},
            {"open": 106, "high": 107, "low": 96, "close": 103, "volume": 60},
        ])
        healthy_3bc = next(p for p in detect_candlestick_patterns(healthy) if p["name"] == "Three Black Crows")
        exhausted_3bc = next(p for p in detect_candlestick_patterns(exhausted) if p["name"] == "Three Black Crows")
        assert healthy_3bc["strength"] > exhausted_3bc["strength"]


class TestIndicatorCtxHammerDetection:
    HAMMER_SHAPE = {"open": 100.3, "high": 100.5, "low": 90, "close": 100.5, "volume": 50}
    INV_HAMMER_SHAPE = {"open": 100, "high": 110, "low": 100, "close": 100.2, "volume": 50}

    def _uptrend_candles(self, final: dict) -> pd.DataFrame:
        rows = [
            {"open": 90 + i * 2, "high": 91 + i * 2, "low": 88 + i * 2,
             "close": 89 + i * 2, "volume": 50}
            for i in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    def test_adx_di_overrides_price_delta(self):
        """Price delta says uptrend but DI says downtrend -> Hammer (not Hanging Man)."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        names = [p["name"] for p in patterns]
        assert "Hammer" in names
        assert "Hanging Man" not in names

    def test_low_adx_suppresses_hammer(self):
        """ADX < 15 with indicator_ctx suppresses all hammer family."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        ctx = {"adx": 10, "di_plus": 10, "di_minus": 30}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        names = [p["name"] for p in patterns]
        assert "Hammer" not in names
        assert "Hanging Man" not in names

    def test_no_ctx_uses_price_delta(self):
        """Without indicator_ctx, falls back to 5-candle delta (existing behavior)."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hanging Man" in names  # price delta says uptrend

    def test_shooting_star_in_uptrend_ctx(self):
        """Inverted hammer shape + uptrend DI -> Shooting Star."""
        candles = self._uptrend_candles(self.INV_HAMMER_SHAPE)
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        names = [p["name"] for p in patterns]
        assert "Shooting Star" in names

    def test_empty_ctx_falls_back_to_price_delta(self):
        """Empty dict indicator_ctx behaves like None (price delta fallback)."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        patterns_none = detect_candlestick_patterns(candles)
        patterns_empty = detect_candlestick_patterns(candles, indicator_ctx={})
        names_none = [p["name"] for p in patterns_none]
        names_empty = [p["name"] for p in patterns_empty]
        assert names_none == names_empty


class TestDirectionalConfidence:
    def test_contradictory_patterns_reduce_confidence(self):
        """2 bull + 1 bear has lower confidence than 3 bull (same count)."""
        unanimous = [
            {"name": "A", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "C", "type": "c", "bias": "bullish", "strength": 10},
        ]
        mixed = [
            {"name": "A", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "C", "type": "c", "bias": "bearish", "strength": 10},
        ]
        conf_unanimous = compute_pattern_score(unanimous)["confidence"]
        conf_mixed = compute_pattern_score(mixed)["confidence"]
        assert conf_unanimous > conf_mixed

    def test_evenly_split_half_confidence(self):
        """1 bull + 1 bear -> agreement 0.5, count-based 0.67, product ~0.33."""
        patterns = [
            {"name": "A", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bearish", "strength": 10},
        ]
        conf = compute_pattern_score(patterns)["confidence"]
        assert 0.30 <= conf <= 0.40

    def test_unanimous_full_confidence(self):
        """3 same-direction patterns -> confidence 1.0."""
        patterns = [
            {"name": "A", "type": "c", "bias": "bearish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bearish", "strength": 10},
            {"name": "C", "type": "c", "bias": "bearish", "strength": 10},
        ]
        conf = compute_pattern_score(patterns)["confidence"]
        assert conf == 1.0

    def test_single_pattern_confidence(self):
        """1 non-neutral pattern -> agreement 1.0, count-based 0.33."""
        patterns = [{"name": "A", "type": "c", "bias": "bullish", "strength": 10}]
        conf = compute_pattern_score(patterns)["confidence"]
        assert 0.30 <= conf <= 0.40

    def test_all_neutral_patterns_zero_confidence(self):
        """Only neutral patterns -> 0 non-neutral -> confidence 0.0."""
        patterns = [
            {"name": "A", "type": "c", "bias": "neutral", "strength": 5},
            {"name": "B", "type": "c", "bias": "neutral", "strength": 5},
        ]
        conf = compute_pattern_score(patterns)["confidence"]
        assert conf == 0.0


class TestRegimeAwareTrendBoost:
    def test_regime_trending_scales_reversal_boost(self):
        """Higher regime_trending gives larger reversal boost."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score_low = compute_pattern_score(patterns, ctx, regime_trending=0.2)["score"]
        score_high = compute_pattern_score(patterns, ctx, regime_trending=0.8)["score"]
        assert score_high > score_low

    def test_regime_trending_scales_continuation_boost(self):
        """Continuation boost also scales with regime_trending."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        # bullish pattern + bullish DI = continuation
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score_low = compute_pattern_score(patterns, ctx, regime_trending=0.2)["score"]
        score_high = compute_pattern_score(patterns, ctx, regime_trending=0.8)["score"]
        assert score_high > score_low

    def test_regime_trending_zero_no_boost(self):
        """regime_trending=0 gives trend_boost 1.0 regardless of ADX."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 40, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx, regime_trending=0.0)["score"]
        assert score == 15  # no trend boost

    def test_regime_trending_none_fallback(self):
        """When regime_trending=None, use legacy ADX thresholds."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx, regime_trending=None)["score"]
        # legacy: reversal at adx >= 15 gives 1.3x -> round(15 * 1.3) = 20
        assert score == 20

    def test_boost_overrides_reversal_base(self):
        """boost_overrides can change the reversal boost base."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score_default = compute_pattern_score(patterns, ctx, regime_trending=1.0)["score"]
        score_boosted = compute_pattern_score(
            patterns, ctx, regime_trending=1.0,
            boost_overrides={"reversal_boost": 0.5},
        )["score"]
        assert score_boosted > score_default


class TestContinuousVolumeBoost:
    def test_continuous_curve_no_jump(self):
        """Small vol_ratio change across old threshold should produce small score change."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx_130 = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.30, "bb_pos": 0.5, "close": 100}
        ctx_140 = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.40, "bb_pos": 0.5, "close": 100}
        score_130 = compute_pattern_score(patterns, ctx_130)["score"]
        score_140 = compute_pattern_score(patterns, ctx_140)["score"]
        # continuous curve: nearby ratios produce different but close scores
        assert score_140 > score_130

    def test_low_volume_minimal_boost(self):
        """vol_ratio 1.0 should give negligible boost."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score == 12

    def test_high_volume_approaches_max(self):
        """vol_ratio 2.0+ should give near-max boost (~1.3x)."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 2.5, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert 15 <= score <= 16  # 12 * ~1.3 = ~15.6

    def test_boost_overrides_vol_params(self):
        """boost_overrides can shift the volume sigmoid center."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.2, "bb_pos": 0.5, "close": 100}
        score_default = compute_pattern_score(patterns, ctx)["score"]
        # shift center down so 1.2 is well above center -> bigger boost
        score_shifted = compute_pattern_score(
            patterns, ctx, boost_overrides={"vol_center": 1.0, "vol_steepness": 10.0}
        )["score"]
        assert score_shifted > score_default


class TestTrendAwarePatterns:
    """Hammer/Inverted Hammer shape → different name depending on prior trend."""

    def _downtrend_candles(self, final: dict) -> pd.DataFrame:
        """10 padding candles forming a downtrend, then the final candle."""
        rows = [
            {"open": 120 - i * 2, "high": 121 - i * 2, "low": 118 - i * 2,
             "close": 119 - i * 2, "volume": 50}
            for i in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    def _uptrend_candles(self, final: dict) -> pd.DataFrame:
        """10 padding candles forming an uptrend, then the final candle."""
        rows = [
            {"open": 90 + i * 2, "high": 91 + i * 2, "low": 88 + i * 2,
             "close": 89 + i * 2, "volume": 50}
            for i in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    def _flat_candles(self, final: dict) -> pd.DataFrame:
        """10 padding candles with identical close, then the final candle."""
        rows = [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}
            for _ in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    # -- Hammer shape (long lower shadow, small body at top, no upper shadow)
    HAMMER_SHAPE = {"open": 100.3, "high": 100.5, "low": 90, "close": 100.5, "volume": 50}

    # -- Inverted Hammer shape (long upper shadow, small body at bottom, no lower shadow)
    INV_HAMMER_SHAPE = {"open": 100, "high": 110, "low": 100, "close": 100.2, "volume": 50}

    def test_hammer_after_downtrend(self):
        candles = self._downtrend_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hammer" in names
        hammer = next(p for p in patterns if p["name"] == "Hammer")
        assert hammer["bias"] == "bullish"
        assert hammer["strength"] == 12

    def test_hanging_man_after_uptrend(self):
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hanging Man" in names
        hm = next(p for p in patterns if p["name"] == "Hanging Man")
        assert hm["bias"] == "bearish"
        assert hm["strength"] == 12

    def test_inverted_hammer_after_downtrend(self):
        candles = self._downtrend_candles(self.INV_HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Inverted Hammer" in names
        ih = next(p for p in patterns if p["name"] == "Inverted Hammer")
        assert ih["bias"] == "bullish"
        assert ih["strength"] == 10

    def test_shooting_star_after_uptrend(self):
        candles = self._uptrend_candles(self.INV_HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Shooting Star" in names
        ss = next(p for p in patterns if p["name"] == "Shooting Star")
        assert ss["bias"] == "bearish"
        assert ss["strength"] == 10

    def test_hammer_shape_flat_market_suppressed(self):
        candles = self._flat_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hammer" not in names
        assert "Hanging Man" not in names

    def test_inverted_hammer_shape_flat_market_suppressed(self):
        candles = self._flat_candles(self.INV_HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Inverted Hammer" not in names
        assert "Shooting Star" not in names

    def test_insufficient_lookback_suppressed(self):
        """Fewer than 6 candles total → can't determine trend → no hammer patterns."""
        rows = [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}
            for _ in range(2)
        ]
        rows.append(self.HAMMER_SHAPE)
        candles = pd.DataFrame(rows)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hammer" not in names
        assert "Hanging Man" not in names
        assert "Inverted Hammer" not in names
        assert "Shooting Star" not in names


class TestProductionWiring:
    def test_detect_with_indicator_ctx_does_not_crash(self):
        """detect_candlestick_patterns accepts indicator_ctx without error."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 102, "volume": 50},
        ])
        ctx = {"adx": 20, "di_plus": 25, "di_minus": 15, "vol_ratio": 1.3,
               "bb_pos": 0.5, "close": 102}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        assert isinstance(patterns, list)

    def test_compute_score_full_params(self):
        """compute_pattern_score accepts all new params together."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.5,
               "bb_pos": 0.5, "close": 100}
        result = compute_pattern_score(
            patterns, ctx,
            strength_overrides={"hammer": 14},
            regime_trending=0.6,
            boost_overrides={"vol_center": 1.2, "reversal_boost": 0.4},
        )
        assert "score" in result
        assert "confidence" in result
        assert result["score"] != 0

    def test_regime_none_and_boost_none_backward_compat(self):
        """Passing None for regime_trending and boost_overrides matches legacy behavior."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        legacy = compute_pattern_score(patterns, ctx)
        explicit_none = compute_pattern_score(
            patterns, ctx, regime_trending=None, boost_overrides=None,
        )
        assert legacy["score"] == explicit_none["score"]
        assert legacy["confidence"] == explicit_none["confidence"]
