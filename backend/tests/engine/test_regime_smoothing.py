from app.engine.constants import INDICATOR_PERIODS
from app.engine.regime import compute_regime_mix, smooth_regime_mix
from app.engine.scoring import sigmoid_scale


def test_bb_width_percentile_window_is_100():
    """BB width percentile window should be 100 candles for stable volatility context."""
    assert INDICATOR_PERIODS["bb_width_percentile_window"] == 100


def test_regime_smoothing_prevents_single_candle_flip():
    """Smoothed regime should not flip from trending to ranging on a single candle."""
    smoothed_state = {}

    raw_trending = compute_regime_mix(trend_strength=0.9, vol_expansion=0.8)
    s1 = smooth_regime_mix(raw_trending, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)
    assert abs(s1["trending"] - raw_trending["trending"]) < 0.01

    raw_ranging = compute_regime_mix(trend_strength=0.1, vol_expansion=0.1)
    s2 = smooth_regime_mix(raw_ranging, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)
    assert s2["trending"] > s2["ranging"], "Single candle should not flip regime"


def test_regime_smoothing_cold_start_uses_raw():
    """On cold start (no prior state), smoothed regime should equal raw values."""
    smoothed_state = {}
    raw = compute_regime_mix(trend_strength=0.5, vol_expansion=0.5)
    result = smooth_regime_mix(raw, smoothed_state, "ETH-USDT-SWAP", "15m", alpha=0.3)
    for key in ["trending", "ranging", "volatile", "steady"]:
        assert abs(result[key] - raw[key]) < 0.001


def test_regime_smoothing_converges_after_several_candles():
    """After 5+ consistent candles, smoothed regime should approach the new raw regime."""
    smoothed_state = {}
    raw_trending = compute_regime_mix(trend_strength=0.9, vol_expansion=0.8)
    smooth_regime_mix(raw_trending, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)

    raw_ranging = compute_regime_mix(trend_strength=0.1, vol_expansion=0.1)
    for _ in range(10):
        result = smooth_regime_mix(raw_ranging, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)

    assert result["ranging"] > 0.6, f"Should have converged to ranging: {result}"


def test_regime_smoothing_isolates_pairs():
    """Different pairs sharing the same state dict should not cross-pollinate."""
    smoothed_state = {}

    raw_trending = compute_regime_mix(trend_strength=0.9, vol_expansion=0.8)
    smooth_regime_mix(raw_trending, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)

    raw_ranging = compute_regime_mix(trend_strength=0.1, vol_expansion=0.1)
    smooth_regime_mix(raw_ranging, smoothed_state, "ETH-USDT-SWAP", "1h", alpha=0.3)

    s_btc = smooth_regime_mix(raw_ranging, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)
    s_eth = smooth_regime_mix(raw_trending, smoothed_state, "ETH-USDT-SWAP", "1h", alpha=0.3)

    assert s_btc["trending"] > s_eth["trending"], (
        f"BTC trending={s_btc['trending']}, ETH trending={s_eth['trending']} — state leaked"
    )


def test_per_pair_adx_center_affects_regime():
    """Different ADX centers should produce different regime mixes for the same ADX value."""
    adx_val = 30.0

    ts_default = sigmoid_scale(adx_val, center=20.0, steepness=0.25)
    ts_high = sigmoid_scale(adx_val, center=35.0, steepness=0.25)

    regime_default = compute_regime_mix(ts_default, vol_expansion=0.5)
    regime_high = compute_regime_mix(ts_high, vol_expansion=0.5)

    assert regime_default["trending"] > regime_high["trending"], (
        "Higher ADX center should reduce trending component for same ADX"
    )
