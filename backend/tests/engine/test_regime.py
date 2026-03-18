# backend/tests/engine/test_regime.py
import pytest

from app.engine.regime import (
    compute_regime_mix, blend_caps, blend_outer_weights,
    DEFAULT_CAPS, DEFAULT_OUTER_WEIGHTS,
)


class TestRegimeMixSumsToOne:
    @pytest.mark.parametrize("adx_strength,vol_expansion", [
        (0.07, 0.08),   # low ADX, narrow BB
        (0.5, 0.5),     # neutral
        (0.98, 0.92),   # strong trend, expanding
        (0.98, 0.08),   # strong trend, narrow BB (quiet trend)
        (0.07, 0.92),   # low ADX, wide BB (volatile)
    ])
    def test_sums_to_one(self, adx_strength, vol_expansion):
        regime = compute_regime_mix(adx_strength, vol_expansion)
        total = regime["trending"] + regime["ranging"] + regime["volatile"]
        assert abs(total - 1.0) < 1e-9

    def test_all_positive(self):
        regime = compute_regime_mix(0.5, 0.5)
        assert regime["trending"] >= 0
        assert regime["ranging"] >= 0
        assert regime["volatile"] >= 0


class TestRegimeMixDominance:
    def test_high_adx_expanding_bb_is_trending(self):
        regime = compute_regime_mix(0.98, 0.92)
        assert regime["trending"] > regime["ranging"]
        assert regime["trending"] > regime["volatile"]

    def test_low_adx_narrow_bb_is_ranging(self):
        regime = compute_regime_mix(0.07, 0.08)
        assert regime["ranging"] > regime["trending"]
        assert regime["ranging"] > regime["volatile"]

    def test_low_adx_wide_bb_is_volatile(self):
        regime = compute_regime_mix(0.07, 0.92)
        assert regime["volatile"] > regime["trending"]
        assert regime["volatile"] > regime["ranging"]

    def test_quiet_trend_is_mostly_trending(self):
        """High ADX + low vol = ~80% trending."""
        regime = compute_regime_mix(0.98, 0.08)
        assert regime["trending"] > 0.70


class TestBlendCaps:
    def test_none_weights_uses_defaults(self):
        regime = {"trending": 0.5, "ranging": 0.3, "volatile": 0.2}
        caps = blend_caps(regime, None)
        assert "trend_cap" in caps
        assert "mean_rev_cap" in caps
        assert "squeeze_cap" in caps
        assert "volume_cap" in caps

    def test_pure_trending_returns_trending_column(self):
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        caps = blend_caps(regime, None)
        assert caps["trend_cap"] == DEFAULT_CAPS["trending"]["trend_cap"]
        assert caps["mean_rev_cap"] == DEFAULT_CAPS["trending"]["mean_rev_cap"]

    def test_pure_ranging_returns_ranging_column(self):
        regime = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        caps = blend_caps(regime, None)
        assert caps["trend_cap"] == DEFAULT_CAPS["ranging"]["trend_cap"]

    def test_50_50_trending_ranging_returns_midpoint(self):
        regime = {"trending": 0.5, "ranging": 0.5, "volatile": 0.0}
        caps = blend_caps(regime, None)
        expected_trend_cap = (
            DEFAULT_CAPS["trending"]["trend_cap"] * 0.5
            + DEFAULT_CAPS["ranging"]["trend_cap"] * 0.5
        )
        assert abs(caps["trend_cap"] - expected_trend_cap) < 1e-9


class TestBlendOuterWeights:
    def test_sums_to_one(self):
        regime = {"trending": 0.4, "ranging": 0.35, "volatile": 0.25}
        weights = blend_outer_weights(regime, None)
        total = weights["tech"] + weights["flow"] + weights["onchain"] + weights["pattern"]
        assert abs(total - 1.0) < 1e-9

    def test_pure_trending_returns_trending_weights(self):
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        weights = blend_outer_weights(regime, None)
        assert abs(weights["tech"] - DEFAULT_OUTER_WEIGHTS["trending"]["tech"]) < 1e-9

    def test_none_weights_uses_defaults(self):
        regime = {"trending": 0.5, "ranging": 0.3, "volatile": 0.2}
        weights = blend_outer_weights(regime, None)
        assert "tech" in weights
        assert "flow" in weights
        assert "onchain" in weights
        assert "pattern" in weights
