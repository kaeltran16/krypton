"""Market regime detection and adaptive weight blending."""


REGIMES = ["trending", "ranging", "volatile"]
CAP_KEYS = ["trend_cap", "mean_rev_cap", "squeeze_cap", "volume_cap"]
OUTER_KEYS = ["tech", "flow", "onchain", "pattern"]

DEFAULT_CAPS = {
    "trending": {"trend_cap": 38, "mean_rev_cap": 22, "squeeze_cap": 12, "volume_cap": 28},
    "ranging": {"trend_cap": 18, "mean_rev_cap": 40, "squeeze_cap": 16, "volume_cap": 26},
    "volatile": {"trend_cap": 25, "mean_rev_cap": 28, "squeeze_cap": 22, "volume_cap": 25},
}

DEFAULT_OUTER_WEIGHTS = {
    "trending": {"tech": 0.45, "flow": 0.25, "onchain": 0.18, "pattern": 0.12},
    "ranging": {"tech": 0.38, "flow": 0.18, "onchain": 0.26, "pattern": 0.18},
    "volatile": {"tech": 0.30, "flow": 0.20, "onchain": 0.25, "pattern": 0.25},
}


def compute_regime_mix(trend_strength: float, vol_expansion: float) -> dict:
    """Compute continuous regime mix from trend strength and volatility expansion.

    Args:
        trend_strength: 0-1 from sigmoid_scale(adx, center=20, steepness=0.25)
        vol_expansion: 0-1 from sigmoid_scale(bb_width_pct, center=50, steepness=0.08)

    Returns:
        Dict with trending/ranging/volatile weights summing to 1.0.
    """
    raw_trending = trend_strength * vol_expansion
    raw_ranging = (1 - trend_strength) * (1 - vol_expansion)
    raw_volatile = (1 - trend_strength) * vol_expansion
    total = raw_trending + raw_ranging + raw_volatile
    if total == 0:
        return {"trending": 1 / 3, "ranging": 1 / 3, "volatile": 1 / 3}
    return {
        "trending": raw_trending / total,
        "ranging": raw_ranging / total,
        "volatile": raw_volatile / total,
    }


def _extract_regime_dict(regime_weights, keys: list[str], suffix: str) -> dict:
    """Extract a regime-keyed dict from a RegimeWeights DB row.

    Args:
        regime_weights: RegimeWeights DB row.
        keys: Key names (e.g. CAP_KEYS or OUTER_KEYS).
        suffix: Attribute suffix — "" for caps (e.g. trending_trend_cap),
                "_weight" for outer weights (e.g. trending_tech_weight).
    """
    return {
        regime: {
            key: getattr(regime_weights, f"{regime}_{key}{suffix}")
            for key in keys
        }
        for regime in REGIMES
    }


def _blend(regime: dict, per_regime: dict, keys: list[str]) -> dict:
    """Dot product of regime mix x per-regime columns."""
    result = {}
    for key in keys:
        result[key] = (
            regime["trending"] * per_regime["trending"][key]
            + regime["ranging"] * per_regime["ranging"][key]
            + regime["volatile"] * per_regime["volatile"][key]
        )
    return result


def blend_caps(regime: dict, regime_weights=None) -> dict:
    """Blend effective inner caps from regime mix.

    Args:
        regime: Dict with trending/ranging/volatile weights.
        regime_weights: RegimeWeights DB row, or None for defaults.

    Returns:
        Dict with trend_cap, mean_rev_cap, squeeze_cap, volume_cap.
    """
    caps = _extract_regime_dict(regime_weights, CAP_KEYS, "") if regime_weights else DEFAULT_CAPS
    return _blend(regime, caps, CAP_KEYS)


def blend_outer_weights(regime: dict, regime_weights=None) -> dict:
    """Blend effective outer blend weights from regime mix.

    Args:
        regime: Dict with trending/ranging/volatile weights.
        regime_weights: RegimeWeights DB row, or None for defaults.

    Returns:
        Dict with tech, flow, onchain, pattern weights summing to ~1.0.
    """
    outer = _extract_regime_dict(regime_weights, OUTER_KEYS, "_weight") if regime_weights else DEFAULT_OUTER_WEIGHTS
    return _blend(regime, outer, OUTER_KEYS)
