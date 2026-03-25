import pytest


def test_cvd_accumulates_buys():
    """Buy trades should increase candle_delta."""
    from app.main import _update_cvd
    cvd = {"cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0}
    _update_cvd(cvd, size=10.0, side="buy")
    assert cvd["candle_delta"] == 10.0
    assert cvd["cumulative"] == 10.0


def test_cvd_accumulates_sells():
    """Sell trades should decrease candle_delta."""
    from app.main import _update_cvd
    cvd = {"cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0}
    _update_cvd(cvd, size=5.0, side="sell")
    assert cvd["candle_delta"] == -5.0
    assert cvd["cumulative"] == -5.0


def test_cvd_multiple_trades():
    """Multiple trades accumulate correctly."""
    from app.main import _update_cvd
    cvd = {"cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0}
    _update_cvd(cvd, size=10.0, side="buy")
    _update_cvd(cvd, size=3.0, side="sell")
    _update_cvd(cvd, size=7.0, side="buy")
    assert cvd["candle_delta"] == 14.0  # 10 - 3 + 7
    assert cvd["cumulative"] == 14.0
