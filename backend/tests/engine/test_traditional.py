import pandas as pd
import pytest

from app.engine.traditional import compute_technical_score, compute_order_flow_score


@pytest.fixture
def sample_candles():
    """50 candles of synthetic BTC data with an uptrend."""
    base = 67000
    data = []
    for i in range(50):
        o = base + i * 10
        h = o + 50
        l = o - 30
        c = o + 20
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": 100 + i})
    return pd.DataFrame(data)


@pytest.fixture
def sample_candles_downtrend():
    """50 candles of synthetic BTC data with a downtrend."""
    base = 70000
    closes = [base]
    for i in range(49):
        if i % 5 == 0:
            closes.append(closes[-1] - 100)
        else:
            closes.append(closes[-1] + 20)
    data = []
    for c in closes:
        data.append({"open": c + 10, "high": c + 50, "low": c - 30, "close": c, "volume": 100})
    return pd.DataFrame(data)


def test_technical_score_returns_bounded_value(sample_candles):
    """Score must be between -100 and +100."""
    result = compute_technical_score(sample_candles)
    assert -100 <= result["score"] <= 100


def test_technical_score_uptrend_is_positive(sample_candles):
    """Uptrend should produce positive score."""
    result = compute_technical_score(sample_candles)
    assert result["score"] > 0


def test_technical_score_downtrend_is_negative(sample_candles_downtrend):
    """Downtrend should produce negative score."""
    result = compute_technical_score(sample_candles_downtrend)
    assert result["score"] < 0


def test_technical_score_includes_indicators(sample_candles):
    """Result should include individual indicator values."""
    result = compute_technical_score(sample_candles)
    assert "rsi" in result["indicators"]
    assert "macd" in result["indicators"]
    assert "ema_9" in result["indicators"]
    assert "atr" in result["indicators"]


def test_order_flow_score_returns_bounded_value():
    """Order flow score must be between -100 and +100."""
    metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 0.02,
        "long_short_ratio": 1.2,
    }
    result = compute_order_flow_score(metrics)
    assert -100 <= result["score"] <= 100


def test_order_flow_high_long_ratio_is_cautious():
    """Very high long/short ratio suggests crowded long — should dampen score."""
    metrics = {
        "funding_rate": 0.001,
        "open_interest_change_pct": 0.01,
        "long_short_ratio": 3.0,
    }
    result = compute_order_flow_score(metrics)
    assert result["score"] < 0


def test_order_flow_missing_keys_uses_defaults():
    """Missing optional keys should not crash — use safe defaults."""
    metrics = {"long_short_ratio": 1.0}
    result = compute_order_flow_score(metrics)
    assert -100 <= result["score"] <= 100
