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
        score = compute_pattern_score(patterns)
        assert score > 0

    def test_bearish_pattern_negative_score(self):
        patterns = [{"name": "Bearish Engulfing", "type": "candlestick", "bias": "bearish", "strength": 15}]
        score = compute_pattern_score(patterns)
        assert score < 0

    def test_stacking_patterns(self):
        patterns = [
            {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
            {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15},
        ]
        score = compute_pattern_score(patterns)
        assert score == 27  # 12 + 15

    def test_neutral_pattern_no_score(self):
        patterns = [{"name": "Doji", "type": "candlestick", "bias": "neutral", "strength": 8}]
        score = compute_pattern_score(patterns)
        assert score == 0

    def test_empty_patterns_zero_score(self):
        assert compute_pattern_score([]) == 0

    def test_score_clamped_to_100(self):
        patterns = [
            {"name": f"Pat{i}", "type": "candlestick", "bias": "bullish", "strength": 15}
            for i in range(10)
        ]
        score = compute_pattern_score(patterns)
        assert score == 100

    def test_level_proximity_boost(self):
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        # bb_pos=0.01 puts price near lower band edge, triggering level-proximity boost
        _NEAR_LOWER_BB_CTX = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.01, "close": 100}
        score_boosted = compute_pattern_score(patterns, _NEAR_LOWER_BB_CTX)
        score_normal = compute_pattern_score(patterns)
        assert score_boosted > score_normal

    def test_near_upper_band_boost(self):
        patterns = [{"name": "Bearish Engulfing", "type": "candlestick", "bias": "bearish", "strength": 15}]
        _NEAR_UPPER_BB_CTX = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.99, "close": 100}
        score_boosted = compute_pattern_score(patterns, _NEAR_UPPER_BB_CTX)
        score_normal = compute_pattern_score(patterns)
        assert abs(score_boosted) > abs(score_normal)


class TestTrendAlignmentBoost:
    def test_reversal_pattern_gets_boost(self):
        """Bullish pattern in bearish ADX trend (reversal) gets 1.3x."""
        patterns = [{"name": "Bullish Engulfing", "type": "two_candle", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        # 15 * 1.3 (reversal) = 19.5, rounded = 20
        # No other boosts active (vol_ratio=1.0, bb_pos=0.5)
        assert score > 15  # boosted above base strength

    def test_weak_trend_no_boost(self):
        """ADX < 15 — no trend-alignment boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score == 12  # no boost


class TestVolumeConfirmationBoost:
    def test_high_volume_gets_boost(self):
        """Volume ratio > 1.5 gets 1.3x boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 2.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score > 12

    def test_normal_volume_no_boost(self):
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score == 12


class TestLevelProximityBoost:
    def test_near_band_edge_gets_boost(self):
        """bb_pos near 0 or 1 should boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.05, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score > 12

    def test_center_no_boost(self):
        """bb_pos at 0.5 — no boost (1.0x)."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score == 12

    def test_boost_never_below_one(self):
        """Level proximity boost should never go below 1.0."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        for bb in [0.0, 0.2, 0.3, 0.5, 0.7, 0.8, 1.0]:
            ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
                   "bb_pos": bb, "close": 100}
            score = compute_pattern_score(patterns, ctx)
            assert score >= 12  # never penalized


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
