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
        # Close near lower BB = boost
        indicators = {"close": 100, "bb_lower": 99, "bb_upper": 200, "ema_21": 150, "ema_50": 160}
        score_boosted = compute_pattern_score(patterns, indicators)
        score_normal = compute_pattern_score(patterns)
        assert score_boosted > score_normal
        assert score_boosted == round(12 * 1.5)  # 18

    def test_ema_proximity_boost(self):
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        # Close very near EMA 21 = boost
        indicators = {"close": 100, "bb_lower": 50, "bb_upper": 150, "ema_21": 100.3, "ema_50": 120}
        score = compute_pattern_score(patterns, indicators)
        assert score == round(12 * 1.5)
