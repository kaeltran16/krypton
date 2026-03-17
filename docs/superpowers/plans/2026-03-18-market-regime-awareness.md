# Market Regime Awareness Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add smooth regime detection (trending/ranging/volatile) that adapts both inner technical sub-component caps and outer blend weights, with per-(pair, timeframe) weight tables learnable via backtest optimization.

**Architecture:** `compute_technical_score()` detects regime from existing ADX + BB width percentile, blends effective caps from a `RegimeWeights` DB table (or defaults), and returns regime data. `run_pipeline()` uses the regime to blend outer weights before `compute_preliminary_score()`. A backtest optimizer endpoint learns optimal weight tables via `differential_evolution`.

**Tech Stack:** Python, FastAPI, SQLAlchemy async (Postgres), Redis, scipy, existing `sigmoid_scale` from `scoring.py`

**Spec:** `docs/superpowers/specs/2026-03-18-market-regime-awareness-design.md`

**Deploy note:** This changes live pipeline scoring behavior. The old hardcoded inner caps (trend ±30, mean-rev ±25, BB vol ±25, volume ±20) are replaced by regime-blended defaults that vary with market conditions. In a trending market the effective trend cap rises to ~34 while mean-rev drops to ~17; in ranging markets the reverse. Scores will differ from pre-deploy values. Any PENDING signals near the threshold boundary may behave differently. Consider resolving or expiring active PENDING signals before deploying.

---

## Chunk 1: Core Regime Module + Unit Tests

### Task 1: `regime.py` Unit Tests + Implementation

**Files:**
- Create: `backend/app/engine/regime.py`
- Create: `backend/tests/engine/test_regime.py`

- [ ] **Step 1: Write the test file**

```python
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
        assert "bb_vol_cap" in caps
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime.py -v`
Expected: ImportError — `app.engine.regime` does not exist yet.

- [ ] **Step 3: Implement `regime.py`**

```python
# backend/app/engine/regime.py
"""Market regime detection and adaptive weight blending."""


DEFAULT_CAPS = {
    "trending": {"trend_cap": 38, "mean_rev_cap": 15, "bb_vol_cap": 22, "volume_cap": 25},
    "ranging": {"trend_cap": 18, "mean_rev_cap": 32, "bb_vol_cap": 28, "volume_cap": 22},
    "volatile": {"trend_cap": 22, "mean_rev_cap": 20, "bb_vol_cap": 28, "volume_cap": 15},
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


def _extract_caps(regime_weights) -> dict:
    """Extract caps dict from a RegimeWeights DB row."""
    return {
        "trending": {
            "trend_cap": regime_weights.trending_trend_cap,
            "mean_rev_cap": regime_weights.trending_mean_rev_cap,
            "bb_vol_cap": regime_weights.trending_bb_vol_cap,
            "volume_cap": regime_weights.trending_volume_cap,
        },
        "ranging": {
            "trend_cap": regime_weights.ranging_trend_cap,
            "mean_rev_cap": regime_weights.ranging_mean_rev_cap,
            "bb_vol_cap": regime_weights.ranging_bb_vol_cap,
            "volume_cap": regime_weights.ranging_volume_cap,
        },
        "volatile": {
            "trend_cap": regime_weights.volatile_trend_cap,
            "mean_rev_cap": regime_weights.volatile_mean_rev_cap,
            "bb_vol_cap": regime_weights.volatile_bb_vol_cap,
            "volume_cap": regime_weights.volatile_volume_cap,
        },
    }


def _extract_outer(regime_weights) -> dict:
    """Extract outer weights dict from a RegimeWeights DB row."""
    return {
        "trending": {
            "tech": regime_weights.trending_tech_weight,
            "flow": regime_weights.trending_flow_weight,
            "onchain": regime_weights.trending_onchain_weight,
            "pattern": regime_weights.trending_pattern_weight,
        },
        "ranging": {
            "tech": regime_weights.ranging_tech_weight,
            "flow": regime_weights.ranging_flow_weight,
            "onchain": regime_weights.ranging_onchain_weight,
            "pattern": regime_weights.ranging_pattern_weight,
        },
        "volatile": {
            "tech": regime_weights.volatile_tech_weight,
            "flow": regime_weights.volatile_flow_weight,
            "onchain": regime_weights.volatile_onchain_weight,
            "pattern": regime_weights.volatile_pattern_weight,
        },
    }


def _blend(regime: dict, per_regime: dict, keys: list[str]) -> dict:
    """Dot product of regime mix × per-regime columns."""
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
        Dict with trend_cap, mean_rev_cap, bb_vol_cap, volume_cap.
    """
    caps = _extract_caps(regime_weights) if regime_weights else DEFAULT_CAPS
    return _blend(regime, caps, ["trend_cap", "mean_rev_cap", "bb_vol_cap", "volume_cap"])


def blend_outer_weights(regime: dict, regime_weights=None) -> dict:
    """Blend effective outer blend weights from regime mix.

    Args:
        regime: Dict with trending/ranging/volatile weights.
        regime_weights: RegimeWeights DB row, or None for defaults.

    Returns:
        Dict with tech, flow, onchain, pattern weights summing to ~1.0.
    """
    outer = _extract_outer(regime_weights) if regime_weights else DEFAULT_OUTER_WEIGHTS
    return _blend(regime, outer, ["tech", "flow", "onchain", "pattern"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime.py -v`
Expected: All 14 tests PASS.

---

## Chunk 2: Integrate Regime into Technical Scoring

### Task 2: Modify `compute_technical_score()` + Update Existing Tests

**Files:**
- Modify: `backend/app/engine/traditional.py:1-4` — add imports
- Modify: `backend/app/engine/traditional.py:56` — add `regime_weights` parameter
- Modify: `backend/app/engine/traditional.py:126-158` — replace hardcoded caps with regime-blended caps
- Modify: `backend/tests/engine/test_traditional.py` — add regime tests

- [ ] **Step 5: Write new regime-related tests in existing test file**

Append to `backend/tests/engine/test_traditional.py`:

```python
class TestRegimeIntegration:
    def test_returns_regime_dict(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "regime" in result
        regime = result["regime"]
        assert "trending" in regime
        assert "ranging" in regime
        assert "volatile" in regime

    def test_regime_sums_to_one(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        regime = result["regime"]
        total = regime["trending"] + regime["ranging"] + regime["volatile"]
        assert abs(total - 1.0) < 1e-6

    def test_regime_indicators_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        assert "regime_trending" in indicators
        assert "regime_ranging" in indicators
        assert "regime_volatile" in indicators

    def test_backward_compatible_without_regime_weights(self):
        """Calling without regime_weights still works (uses defaults)."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100

    def test_with_regime_weights_changes_score(self):
        """Passing regime_weights should produce a different score than defaults."""
        from unittest.mock import MagicMock
        df = _make_candles(80, "up")

        result_default = compute_technical_score(df)

        # Create a mock regime_weights that heavily favors mean-reversion
        rw = MagicMock()
        rw.trending_trend_cap = 10.0
        rw.trending_mean_rev_cap = 40.0
        rw.trending_bb_vol_cap = 25.0
        rw.trending_volume_cap = 25.0
        rw.ranging_trend_cap = 10.0
        rw.ranging_mean_rev_cap = 40.0
        rw.ranging_bb_vol_cap = 25.0
        rw.ranging_volume_cap = 25.0
        rw.volatile_trend_cap = 10.0
        rw.volatile_mean_rev_cap = 40.0
        rw.volatile_bb_vol_cap = 25.0
        rw.volatile_volume_cap = 25.0
        rw.trending_tech_weight = 0.25
        rw.trending_flow_weight = 0.25
        rw.trending_onchain_weight = 0.25
        rw.trending_pattern_weight = 0.25
        rw.ranging_tech_weight = 0.25
        rw.ranging_flow_weight = 0.25
        rw.ranging_onchain_weight = 0.25
        rw.ranging_pattern_weight = 0.25
        rw.volatile_tech_weight = 0.25
        rw.volatile_flow_weight = 0.25
        rw.volatile_onchain_weight = 0.25
        rw.volatile_pattern_weight = 0.25

        result_custom = compute_technical_score(df, regime_weights=rw)
        # Different caps should produce different scores
        assert result_custom["score"] != result_default["score"]

    def test_score_still_clamped(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100
```

- [ ] **Step 6: Run new tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestRegimeIntegration -v`
Expected: FAIL — `compute_technical_score` does not return `regime` key yet.

- [ ] **Step 7: Modify `compute_technical_score()` to add regime detection and adaptive caps**

In `backend/app/engine/traditional.py`:

**Line 4** — add import:

```python
from app.engine.regime import compute_regime_mix, blend_caps
```

**Line 56** — add `regime_weights` parameter:

Change:
```python
def compute_technical_score(candles: pd.DataFrame) -> dict:
```
to:
```python
def compute_technical_score(candles: pd.DataFrame, regime_weights=None) -> dict:
```

**Lines 126-158** — replace scoring section. Change from:

```python
    # === Scoring ===
    # 1. Trend (max ±30)
    di_sign = 1 if di_plus_val > di_minus_val else -1
    trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=0.30) * 30

    # 2. Mean reversion (max ±25)
    rsi_score = sigmoid_score(50 - rsi_val, center=0, steepness=0.25) * 25

    # 3. Volatility & position (max ±25)
    bb_pos_score = sigmoid_score(0.5 - bb_pos, center=0, steepness=10) * 15
    bb_pos_sign = 1 if bb_pos_score > 0 else (-1 if bb_pos_score < 0 else 0)
    bb_width_score = bb_pos_sign * sigmoid_score(50 - bb_width_pct, center=0, steepness=0.10) * 10

    # 4. Volume confirmation (max ±20)
    obv_score = sigmoid_score(obv_slope_norm, center=0, steepness=4) * 12
    vol_score = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=3.0) * 8

    total = trend_score + rsi_score + bb_pos_score + bb_width_score + obv_score + vol_score
    score = max(min(round(total), 100), -100)

    indicators = {
        "adx": round(adx_val, 2),
        "di_plus": round(di_plus_val, 2),
        "di_minus": round(di_minus_val, 2),
        "rsi": round(rsi_val, 2),
        "bb_upper": round(bb_upper_val, 2),
        "bb_lower": round(bb_lower_val, 2),
        "bb_pos": round(bb_pos, 4),
        "bb_width_pct": round(bb_width_pct, 1),
        "obv_slope": round(obv_slope_norm, 4),
        "vol_ratio": round(vol_ratio, 4),
        "atr": round(atr_val, 4),
    }

    return {"score": score, "indicators": indicators}
```

to:

```python
    # === Regime detection ===
    trend_strength = sigmoid_scale(adx_val, center=20, steepness=0.25)
    vol_expansion = sigmoid_scale(bb_width_pct, center=50, steepness=0.08)
    regime = compute_regime_mix(trend_strength, vol_expansion)
    caps = blend_caps(regime, regime_weights)

    # === Scoring (caps from regime-aware blending) ===
    # 1. Trend
    di_sign = 1 if di_plus_val > di_minus_val else -1
    trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=0.30) * caps["trend_cap"]

    # 2. Mean reversion
    rsi_score = sigmoid_score(50 - rsi_val, center=0, steepness=0.25) * caps["mean_rev_cap"]

    # 3. Volatility & position (60/40 split)
    bb_pos_score = sigmoid_score(0.5 - bb_pos, center=0, steepness=10) * (caps["bb_vol_cap"] * 0.6)
    bb_pos_sign = 1 if bb_pos_score > 0 else (-1 if bb_pos_score < 0 else 0)
    bb_width_score = bb_pos_sign * sigmoid_score(50 - bb_width_pct, center=0, steepness=0.10) * (caps["bb_vol_cap"] * 0.4)

    # 4. Volume confirmation (60/40 split)
    obv_score = sigmoid_score(obv_slope_norm, center=0, steepness=4) * (caps["volume_cap"] * 0.6)
    vol_score = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=3.0) * (caps["volume_cap"] * 0.4)

    total = trend_score + rsi_score + bb_pos_score + bb_width_score + obv_score + vol_score
    score = max(min(round(total), 100), -100)

    indicators = {
        "adx": round(adx_val, 2),
        "di_plus": round(di_plus_val, 2),
        "di_minus": round(di_minus_val, 2),
        "rsi": round(rsi_val, 2),
        "bb_upper": round(bb_upper_val, 2),
        "bb_lower": round(bb_lower_val, 2),
        "bb_pos": round(bb_pos, 4),
        "bb_width_pct": round(bb_width_pct, 1),
        "obv_slope": round(obv_slope_norm, 4),
        "vol_ratio": round(vol_ratio, 4),
        "atr": round(atr_val, 4),
        "regime_trending": round(regime["trending"], 4),
        "regime_ranging": round(regime["ranging"], 4),
        "regime_volatile": round(regime["volatile"], 4),
    }

    return {"score": score, "indicators": indicators, "regime": regime}
```

- [ ] **Step 7b: Audit and fix existing test assertions**

**Known behavior change:** The regime-blended default caps differ from the old hardcoded caps (e.g., trend cap was 30, now varies by regime mix — ~34 in trending markets, ~18 in ranging). The following tests need attention:

**Tests that will pass without changes** (bounds, direction, structure only):
- `test_score_within_bounds` (line 39) — checks `-100 <= score <= 100`, enforced by final clamp
- `test_returns_integer` (line 44) — structural check, unaffected
- `test_new_indicators_present` (line 63) — structural check, unaffected
- `test_old_indicators_removed` (line 71) — structural check, unaffected
- `test_rsi_no_dead_zone` (line 80) — RSI sigmoid tuning unchanged
- `test_monotonic_rsi_scoring` (line 90) — relative ordering preserved across regimes
- `test_obv_slope_present` (line 104) — structural check, unaffected
- `test_vol_ratio_present` (line 109) — structural check, unaffected
- `test_requires_70_candles` (line 116) — error raised before regime detection
- `test_exactly_70_candles_succeeds` (line 121) — checks bounds only
- All `TestOrderFlowScore` tests (lines 127-200) — order flow scoring is not regime-aware

**Tests that may break — review and fix if needed:**
- `test_uptrend_positive` (line 51) — asserts `score > 0`. The synthetic uptrend data (`_make_candles(80, "up")`) produces weak drift that may land in a ranging regime, where trend cap drops from 30→18 and mean-reversion cap rises from 25→32. If the regime mix suppresses trend enough to flip sign, lower the drift threshold or add a comment noting that the test exercises the default regime blend, not a specific regime.
- `test_downtrend_negative` (line 56) — asserts `score < 0`. Less likely to break (downtrend RSI is oversold → mean-reversion pushes bullish, but trend still pushes bearish). Verify after implementation.
- `test_uptrend_produces_nonzero_score` (line 181) — asserts `abs(score) > 5`. In volatile regime (caps sum to 85 vs 100), weak-drift scores compress. Lower threshold to `> 3` if needed, or verify the synthetic data lands in a trending/ranging regime where cap sums are still 100.

- [ ] **Step 8: Run all traditional scoring tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All existing + new tests pass after Step 7b adjustments.

---

## Chunk 3: Pipeline Integration

### Task 3: DB Model + Migration

**Files:**
- Modify: `backend/app/db/models.py:276-293` — add `RegimeWeights` model after `PerformanceTrackerRow`
- New migration via Alembic

- [ ] **Step 9: Add `RegimeWeights` model**

In `backend/app/db/models.py`, after the `PerformanceTrackerRow` class (after line 293), add:

```python
class RegimeWeights(Base):
    __tablename__ = "regime_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)

    # Inner caps (3 regimes × 4 caps = 12 floats)
    trending_trend_cap: Mapped[float] = mapped_column(Float, nullable=False, default=38.0)
    trending_mean_rev_cap: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    trending_bb_vol_cap: Mapped[float] = mapped_column(Float, nullable=False, default=22.0)
    trending_volume_cap: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)

    ranging_trend_cap: Mapped[float] = mapped_column(Float, nullable=False, default=18.0)
    ranging_mean_rev_cap: Mapped[float] = mapped_column(Float, nullable=False, default=32.0)
    ranging_bb_vol_cap: Mapped[float] = mapped_column(Float, nullable=False, default=28.0)
    ranging_volume_cap: Mapped[float] = mapped_column(Float, nullable=False, default=22.0)

    volatile_trend_cap: Mapped[float] = mapped_column(Float, nullable=False, default=22.0)
    volatile_mean_rev_cap: Mapped[float] = mapped_column(Float, nullable=False, default=20.0)
    volatile_bb_vol_cap: Mapped[float] = mapped_column(Float, nullable=False, default=28.0)
    volatile_volume_cap: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)

    # Outer weights (3 regimes × 4 weights = 12 floats)
    trending_tech_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.45)
    trending_flow_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    trending_onchain_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.18)
    trending_pattern_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.12)

    ranging_tech_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.38)
    ranging_flow_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.18)
    ranging_onchain_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.26)
    ranging_pattern_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.18)

    volatile_tech_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.30)
    volatile_flow_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.20)
    volatile_onchain_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    volatile_pattern_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("pair", "timeframe", name="uq_regime_weights_pair_timeframe"),
    )
```

- [ ] **Step 10: Generate and run Alembic migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add regime_weights table"
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```

Expected: Migration creates `regime_weights` table with 26 columns (id + pair + timeframe + 24 floats + updated_at) and a unique constraint on (pair, timeframe).

---

### Task 4: Pipeline Integration — Regime-Aware Outer Weights

**Files:**
- Modify: `backend/app/main.py:37-40` — add regime import
- Modify: `backend/app/main.py:853-870` — load regime weights in lifespan
- Modify: `backend/app/main.py:262-264` — pass regime_weights to `compute_technical_score()`
- Modify: `backend/app/main.py:366-388` — use regime-blended outer weights
- Modify: `backend/app/main.py:582-600` — add regime fields to `raw_indicators`

- [ ] **Step 11: Add regime imports to `main.py`**

In `backend/app/main.py`, after line 40 (the confluence import block), add:

```python
from app.engine.regime import blend_outer_weights, blend_caps
from app.db.models import RegimeWeights
```

- [ ] **Step 12: Load regime weights in lifespan**

In `backend/app/main.py`, after the PerformanceTracker bootstrap (after line 873), add:

```python
    # Load learned regime weights from DB
    app.state.regime_weights = {}
    try:
        async with db.session_factory() as session:
            result = await session.execute(select(RegimeWeights))
            for rw in result.scalars().all():
                session.expunge(rw)  # detach from session so attributes remain accessible
                app.state.regime_weights[(rw.pair, rw.timeframe)] = rw
        if app.state.regime_weights:
            logger.info("Loaded regime weights for %d pair/timeframe combos", len(app.state.regime_weights))
    except Exception as e:
        logger.warning("Failed to load regime weights: %s", e)
```

- [ ] **Step 13: Pass `regime_weights` to `compute_technical_score()`**

In `backend/app/main.py`, add the regime weights lookup **before** the try block (before line 262), then modify the `compute_technical_score` call inside the try:

Before `try:` (around line 262), add:
```python
    rw_key = (pair, timeframe)
    regime_weights = app.state.regime_weights.get(rw_key)
```

Then change line 264 from:
```python
        tech_result = compute_technical_score(df)
```
to:
```python
        tech_result = compute_technical_score(df, regime_weights=regime_weights)
```

- [ ] **Step 14: Replace static outer weights with regime-blended weights**

In `backend/app/main.py`, replace lines 366-377 (the adaptive weight redistribution block):

From:
```python
    # Adaptive weight redistribution: zero unavailable sources, normalize rest
    flow_available = bool(flow_metrics)
    tech_w = settings.engine_traditional_weight
    flow_w = settings.engine_flow_weight if flow_available else 0.0
    onchain_w = settings.engine_onchain_weight if onchain_available else 0.0
    pattern_w = getattr(settings, "engine_pattern_weight", 0.15)
    total_w = tech_w + flow_w + onchain_w + pattern_w
    if total_w > 0:
        tech_w /= total_w
        flow_w /= total_w
        onchain_w /= total_w
        pattern_w /= total_w
```

to:
```python
    # Regime-aware outer weight blending
    regime = tech_result.get("regime")
    outer = blend_outer_weights(regime, regime_weights)

    # Zero unavailable sources, then renormalize
    flow_available = bool(flow_metrics)
    tech_w = outer["tech"]
    flow_w = outer["flow"] if flow_available else 0.0
    onchain_w = outer["onchain"] if onchain_available else 0.0
    pattern_w = outer["pattern"]
    total_w = tech_w + flow_w + onchain_w + pattern_w
    if total_w > 0:
        tech_w /= total_w
        flow_w /= total_w
        onchain_w /= total_w
        pattern_w /= total_w
```

- [ ] **Step 15: Add regime fields to `raw_indicators`**

In `backend/app/main.py`, inside the `raw_indicators` dict (around line 582-600), after the `"parent_di_minus"` line, add:

```python
            "regime_trending": tech_result["indicators"].get("regime_trending"),
            "regime_ranging": tech_result["indicators"].get("regime_ranging"),
            "regime_volatile": tech_result["indicators"].get("regime_volatile"),
            "effective_caps": {k: round(v, 2) for k, v in blend_caps(regime, regime_weights).items()} if regime else None,
            "effective_outer_weights": {k: round(v, 4) for k, v in outer.items()} if regime else None,
```

Note: `outer` was already computed in Step 14, and `regime`/`regime_weights` are in scope from Step 13. The `blend_caps` import was added in Step 11 (add it to the import if not already included — update the import line to: `from app.engine.regime import blend_outer_weights, blend_caps`).

- [ ] **Step 15b: Add `regime_weights` to test conftest**

In `backend/tests/conftest.py`, inside `_test_lifespan()`, add after `app.state.settings = mock_settings` (line 21):

```python
    app.state.regime_weights = {}
```

This prevents `AttributeError` when `run_pipeline()` accesses `app.state.regime_weights.get(rw_key)` during integration tests.

- [ ] **Step 16: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass.

---

## Chunk 4: Backtester Integration

### Task 5: Backtester Regime-Aware Scoring

**Files:**
- Modify: `backend/app/engine/backtester.py:16` — add regime import
- Modify: `backend/app/engine/backtester.py:69-81` — add `regime_weights` to `BacktestConfig`
- Modify: `backend/app/engine/backtester.py:102-108` — add `regime_weights` parameter to `run_backtest()`
- Modify: `backend/app/engine/backtester.py:152-153` — pass `regime_weights` to `compute_technical_score()`
- Modify: `backend/app/engine/backtester.py:180-188` — use regime-blended outer weights
- Create: `backend/tests/engine/test_regime_backtest.py`

- [ ] **Step 17: Write backtester regime tests**

```python
# backend/tests/engine/test_regime_backtest.py
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from app.engine.backtester import run_backtest, BacktestConfig


def _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=15):
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        o = base_price + i * trend
        candles.append({
            "timestamp": (start + timedelta(minutes=minutes_per_candle * i)).isoformat(),
            "open": o, "high": o + 50, "low": o - 30, "close": o + 20, "volume": 100 + i,
        })
    return candles


class TestBacktestWithRegimeWeights:
    def test_without_regime_weights_runs_normally(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=None)
        assert "stats" in result
        assert "trades" in result

    def test_with_regime_weights_runs_successfully(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=20)
        rw = MagicMock()
        # Set all 24 float attributes
        for regime in ["trending", "ranging", "volatile"]:
            setattr(rw, f"{regime}_trend_cap", 30.0)
            setattr(rw, f"{regime}_mean_rev_cap", 25.0)
            setattr(rw, f"{regime}_bb_vol_cap", 25.0)
            setattr(rw, f"{regime}_volume_cap", 20.0)
            setattr(rw, f"{regime}_tech_weight", 0.40)
            setattr(rw, f"{regime}_flow_weight", 0.20)
            setattr(rw, f"{regime}_onchain_weight", 0.20)
            setattr(rw, f"{regime}_pattern_weight", 0.20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=rw)
        assert "stats" in result

    def test_regime_weights_affect_scoring(self):
        """Different regime weights should produce different backtest results."""
        candles = _make_candle_series(n=120, trend=15)
        config = BacktestConfig(signal_threshold=15)

        result_default = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=None)

        # Extreme regime weights: all trend, no mean-rev
        rw = MagicMock()
        for regime in ["trending", "ranging", "volatile"]:
            setattr(rw, f"{regime}_trend_cap", 45.0)
            setattr(rw, f"{regime}_mean_rev_cap", 10.0)
            setattr(rw, f"{regime}_bb_vol_cap", 25.0)
            setattr(rw, f"{regime}_volume_cap", 20.0)
            setattr(rw, f"{regime}_tech_weight", 0.80)
            setattr(rw, f"{regime}_flow_weight", 0.0)
            setattr(rw, f"{regime}_onchain_weight", 0.0)
            setattr(rw, f"{regime}_pattern_weight", 0.20)
        result_custom = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=rw)

        # Both should run and produce different trade counts or stats
        assert "stats" in result_default
        assert "stats" in result_custom
        # Extreme cap changes should affect signal generation
        default_trades = result_default["stats"]["total_trades"]
        custom_trades = result_custom["stats"]["total_trades"]
        default_wr = result_default["stats"]["win_rate"]
        custom_wr = result_custom["stats"]["win_rate"]
        assert (default_trades != custom_trades) or (default_wr != custom_wr), \
            "Regime weights should produce different backtest outcomes"
```

- [ ] **Step 18: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_backtest.py -v`
Expected: TypeError — `run_backtest()` does not accept `regime_weights` yet.

- [ ] **Step 19: Add regime import and parameter to backtester**

In `backend/app/engine/backtester.py`:

**Line 16** — add import:
```python
from app.engine.regime import blend_outer_weights
```

**Line 81** (end of `BacktestConfig`) — add field:
```python
    confluence_max_score: int = 15
```
is already there. No change needed to `BacktestConfig` — regime_weights is passed as a function parameter, not config.

**Line 102-108** — change `run_backtest` signature from:
```python
def run_backtest(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    cancel_flag: dict | None = None,
    ml_predictor=None,
    parent_candles: list[dict] | None = None,
) -> dict:
```
to:
```python
def run_backtest(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    cancel_flag: dict | None = None,
    ml_predictor=None,
    parent_candles: list[dict] | None = None,
    regime_weights=None,
) -> dict:
```

- [ ] **Step 20: Pass `regime_weights` to `compute_technical_score()` and use regime-blended outer weights**

In `backend/app/engine/backtester.py`:

**Line 153** — change from:
```python
            tech_result = compute_technical_score(df)
```
to:
```python
            tech_result = compute_technical_score(df, regime_weights=regime_weights)
```

**Lines 180-188** — replace the `compute_preliminary_score` call. Change from:
```python
        indicator_preliminary = compute_preliminary_score(
            technical_score=tech_result["score"],
            order_flow_score=0,
            tech_weight=config.tech_weight,
            flow_weight=0.0,
            onchain_score=0,
            onchain_weight=0.0,
            pattern_score=pat_score,
            pattern_weight=config.pattern_weight,
        )
```
to:
```python
        # Outer weights: use regime-blended when regime_weights provided,
        # otherwise preserve config defaults for backward compatibility
        if regime_weights is not None:
            regime = tech_result.get("regime")
            outer = blend_outer_weights(regime, regime_weights)
            bt_tech_w = outer["tech"]
            bt_pattern_w = outer["pattern"]
            # flow and onchain are 0 in backtester, renormalize tech+pattern
            bt_total = bt_tech_w + bt_pattern_w
            if bt_total > 0:
                bt_tech_w /= bt_total
                bt_pattern_w /= bt_total
        else:
            bt_tech_w = config.tech_weight
            bt_pattern_w = config.pattern_weight

        indicator_preliminary = compute_preliminary_score(
            technical_score=tech_result["score"],
            order_flow_score=0,
            tech_weight=bt_tech_w,
            flow_weight=0.0,
            onchain_score=0,
            onchain_weight=0.0,
            pattern_score=pat_score,
            pattern_weight=bt_pattern_w,
        )
```

This ensures `run_backtest()` without `regime_weights` produces identical results to the current behavior (using `config.tech_weight=0.75` and `config.pattern_weight=0.25`). Only when regime_weights is explicitly provided does the regime-blended outer weight path activate.

- [ ] **Step 21: Run backtester tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_backtest.py tests/engine/test_backtester.py tests/engine/test_confluence_backtest.py -v`
Expected: All new and existing backtester tests pass.

---

## Chunk 5: Backtest Optimizer

### Task 6: Optimizer Implementation + Tests

**Files:**
- Create: `backend/app/engine/regime_optimizer.py`
- Create: `backend/tests/engine/test_regime_optimizer.py`
- Modify: `backend/requirements.txt` — add `scipy` (if not present)

- [ ] **Step 22: Add scipy to dependencies**

scipy is not in the current `requirements.txt` and must be added. Add `scipy>=1.10` to `backend/requirements.txt`, then rebuild:
```bash
# After adding "scipy" to requirements.txt:
docker compose build api && docker compose up -d
```

Verify it works:
Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "import scipy; print(scipy.__version__)"`

- [ ] **Step 23: Write optimizer tests**

```python
# backend/tests/engine/test_regime_optimizer.py
import pytest

from app.engine.regime_optimizer import (
    compute_fitness, vector_to_regime_dict, regime_dict_to_vector,
    PARAM_BOUNDS, N_PARAMS,
)


class TestFitness:
    def test_reasonable_stats_produce_positive_fitness(self):
        stats = {
            "win_rate": 55, "profit_factor": 1.5,
            "avg_rr": 1.2, "max_drawdown": 8, "total_trades": 30,
        }
        assert compute_fitness(stats) > 0

    def test_too_few_trades_returns_zero(self):
        stats = {
            "win_rate": 80, "profit_factor": 3.0,
            "avg_rr": 2.0, "max_drawdown": 2, "total_trades": 5,
        }
        assert compute_fitness(stats) == 0

    def test_zero_trades_returns_zero(self):
        stats = {
            "win_rate": 0, "profit_factor": None,
            "avg_rr": 0, "max_drawdown": 0, "total_trades": 0,
        }
        assert compute_fitness(stats) == 0

    def test_higher_win_rate_increases_fitness(self):
        base = {"profit_factor": 1.5, "avg_rr": 1.2, "max_drawdown": 8, "total_trades": 30}
        f1 = compute_fitness({**base, "win_rate": 50})
        f2 = compute_fitness({**base, "win_rate": 60})
        assert f2 > f1


class TestVectorConversion:
    def test_roundtrip_with_prenormalized_weights(self):
        """vector -> dict -> vector is identity when outer weights are already normalized."""
        # Use caps that are arbitrary + outer weights that already sum to 1.0 per regime
        vec = [30.0, 25.0, 22.0, 18.0] * 3 + [0.6, 0.4] * 3  # 0.6+0.4=1.0
        d = vector_to_regime_dict(vec)
        vec2 = regime_dict_to_vector(d)
        assert len(vec2) == N_PARAMS
        for a, b in zip(vec, vec2):
            assert abs(a - b) < 1e-9

    def test_vector_length_matches_param_count(self):
        assert N_PARAMS == len(PARAM_BOUNDS)
        assert N_PARAMS == 18  # 12 inner caps + 6 outer weights (tech+pattern × 3 regimes)

    def test_outer_weights_normalized(self):
        """vector_to_regime_dict should normalize outer weights per regime."""
        vec = [30.0] * 12 + [0.5, 0.3] * 3  # 12 caps + 6 outer weights
        d = vector_to_regime_dict(vec)
        for regime in ["trending", "ranging", "volatile"]:
            tech = d[regime]["tech"]
            pattern = d[regime]["pattern"]
            # tech + pattern should sum to 1.0 (since flow/onchain are 0 in backtester)
            assert abs(tech + pattern - 1.0) < 1e-9

    def test_normalization_changes_raw_values(self):
        """Non-normalized input should be corrected by vector_to_regime_dict."""
        vec = [30.0] * 12 + [0.3, 0.2] * 3  # 0.3+0.2=0.5, not 1.0
        d = vector_to_regime_dict(vec)
        # After normalization: tech=0.6, pattern=0.4
        assert abs(d["trending"]["tech"] - 0.6) < 1e-9
        assert abs(d["trending"]["pattern"] - 0.4) < 1e-9
```

- [ ] **Step 24: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py -v`
Expected: ImportError — `app.engine.regime_optimizer` does not exist yet.

- [ ] **Step 25: Implement `regime_optimizer.py`**

```python
# backend/app/engine/regime_optimizer.py
"""Backtest-driven regime weight optimizer using differential evolution."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.backtester import run_backtest, BacktestConfig

logger = logging.getLogger(__name__)

# 12 inner caps (3 regimes × 4 caps) + 6 outer weights (3 regimes × 2: tech + pattern)
# Flow and onchain outer weights are not optimized (always 0 in backtester)
N_PARAMS = 18

# Bounds: (min, max) for each parameter
_CAP_BOUNDS = (10.0, 45.0)
_WEIGHT_BOUNDS = (0.10, 0.50)

PARAM_BOUNDS = [_CAP_BOUNDS] * 12 + [_WEIGHT_BOUNDS] * 6

# Parameter layout:
# [0-3]   trending: trend_cap, mean_rev_cap, bb_vol_cap, volume_cap
# [4-7]   ranging:  trend_cap, mean_rev_cap, bb_vol_cap, volume_cap
# [8-11]  volatile: trend_cap, mean_rev_cap, bb_vol_cap, volume_cap
# [12-13] trending: tech_weight, pattern_weight
# [14-15] ranging:  tech_weight, pattern_weight
# [16-17] volatile: tech_weight, pattern_weight

_CAP_KEYS = ["trend_cap", "mean_rev_cap", "bb_vol_cap", "volume_cap"]
_REGIMES = ["trending", "ranging", "volatile"]

MIN_TRADES = 20


def compute_fitness(stats: dict, min_trades: int = MIN_TRADES) -> float:
    """Compute normalized fitness from backtest stats.

    All components scaled to 0-1 before weighting.
    Returns 0 if too few trades.
    """
    total_trades = stats.get("total_trades", 0)
    if total_trades < min_trades:
        return 0.0

    win_rate = stats.get("win_rate", 0) / 100
    pf = stats.get("profit_factor", 0) or 0
    profit_factor = min(pf, 5) / 5
    avg_rr = min(stats.get("avg_rr", 0), 5) / 5
    max_dd = min(stats.get("max_drawdown", 0), 100) / 100

    return win_rate * 0.4 + profit_factor * 0.3 + avg_rr * 0.2 - max_dd * 0.1


def vector_to_regime_dict(vec: list[float]) -> dict:
    """Convert a flat parameter vector to a nested regime dict.

    Returns dict with keys: trending, ranging, volatile.
    Each has: trend_cap, mean_rev_cap, bb_vol_cap, volume_cap, tech, pattern.
    Outer weights (tech + pattern) are normalized to sum to 1.0 per regime.
    """
    result = {}
    for i, regime in enumerate(_REGIMES):
        caps = {key: vec[i * 4 + j] for j, key in enumerate(_CAP_KEYS)}
        raw_tech = vec[12 + i * 2]
        raw_pattern = vec[12 + i * 2 + 1]
        w_total = raw_tech + raw_pattern
        if w_total > 0:
            caps["tech"] = raw_tech / w_total
            caps["pattern"] = raw_pattern / w_total
        else:
            caps["tech"] = 0.5
            caps["pattern"] = 0.5
        result[regime] = caps
    return result


def regime_dict_to_vector(d: dict) -> list[float]:
    """Convert nested regime dict back to flat vector."""
    vec = []
    for regime in _REGIMES:
        for key in _CAP_KEYS:
            vec.append(d[regime][key])
    for regime in _REGIMES:
        vec.append(d[regime]["tech"])
        vec.append(d[regime]["pattern"])
    return vec


class _MockRegimeWeights:
    """Lightweight object mimicking RegimeWeights DB row for backtester."""

    def __init__(self, regime_dict: dict):
        for regime in _REGIMES:
            for key in _CAP_KEYS:
                setattr(self, f"{regime}_{key}", regime_dict[regime][key])
            setattr(self, f"{regime}_tech_weight", regime_dict[regime]["tech"])
            setattr(self, f"{regime}_pattern_weight", regime_dict[regime]["pattern"])
            # Flow and onchain are fixed at 0 for backtester optimization
            setattr(self, f"{regime}_flow_weight", 0.0)
            setattr(self, f"{regime}_onchain_weight", 0.0)


def optimize_regime_weights(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    parent_candles: list[dict] | None = None,
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress: Any = None,
) -> dict:
    """Run differential evolution to find optimal regime weights.

    Args:
        candles: Historical candle data for backtesting.
        pair: Trading pair.
        config: Backtest config (threshold, patterns, etc.)
        parent_candles: Parent TF candles for confluence.
        max_iterations: Max optimizer iterations.
        cancel_flag: Dict with "cancelled" key to abort.
        on_progress: Optional callable(eval_count, best_fitness) called each generation.

    Returns:
        Dict with "weights" (regime dict), "fitness" (float), "stats" (backtest stats).
    """
    from scipy.optimize import differential_evolution

    best_result: dict[str, Any] = {"fitness": 0.0, "stats": {}, "weights": {}}
    eval_count = [0]  # mutable counter for closure

    def objective(vec):
        if cancel_flag and cancel_flag.get("cancelled"):
            return 0.0  # early exit

        eval_count[0] += 1
        regime_dict = vector_to_regime_dict(list(vec))
        mock_rw = _MockRegimeWeights(regime_dict)

        result = run_backtest(
            candles, pair, config,
            parent_candles=parent_candles,
            regime_weights=mock_rw,
        )
        fitness = compute_fitness(result["stats"])

        if fitness > best_result["fitness"]:
            best_result["fitness"] = fitness
            best_result["stats"] = result["stats"]
            best_result["weights"] = regime_dict
            logger.info(
                "Regime optimizer eval #%d: new best fitness=%.4f (wr=%.1f%%, pf=%.2f)",
                eval_count[0], fitness,
                result["stats"].get("win_rate", 0),
                result["stats"].get("profit_factor", 0) or 0,
            )

        return -fitness  # minimize negative fitness

    def progress_callback(xk, convergence):
        """Called after each generation — log progress and notify caller."""
        if cancel_flag and cancel_flag.get("cancelled"):
            return True  # stops the optimizer
        logger.info(
            "Regime optimizer: %d evals, best fitness=%.4f, convergence=%.4f",
            eval_count[0], best_result["fitness"], convergence,
        )
        if on_progress:
            on_progress(eval_count[0], best_result["fitness"])
        return False

    result = differential_evolution(
        objective,
        bounds=PARAM_BOUNDS,
        maxiter=max_iterations,
        seed=42,
        tol=0.01,
        polish=False,
        callback=progress_callback,
    )

    if best_result["fitness"] == 0.0:
        # Fallback: use the scipy result
        regime_dict = vector_to_regime_dict(list(result.x))
        best_result["weights"] = regime_dict
        best_result["fitness"] = -result.fun

    best_result["evaluations"] = eval_count[0]
    return best_result
```

- [ ] **Step 26: Run optimizer tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py -v`
Expected: All 7 tests PASS.

---

### Task 7: Optimizer API Endpoint

**Files:**
- Modify: `backend/app/api/backtest.py:16-17` — add imports
- Modify: `backend/app/api/backtest.py` — add request model and endpoint

- [ ] **Step 27: Add optimizer API endpoint**

In `backend/app/api/backtest.py`:

**Line 17** — add imports:
```python
from app.engine.regime_optimizer import optimize_regime_weights
from app.db.models import BacktestRun, Candle, RegimeWeights
```

(Replace the existing `from app.db.models import BacktestRun, Candle` line.)

After the `CompareRequest` class (line 52), add the request model:

```python
class OptimizeRegimeRequest(BaseModel):
    pair: str
    timeframe: str
    date_from: str
    date_to: str
    signal_threshold: int = Field(default=40, ge=1, le=100)
    enable_patterns: bool = True
    max_iterations: int = Field(default=300, ge=10, le=1000)
```

After the `delete_run` endpoint (line 361), before the helpers section, add:

```python
@router.post("/optimize-regime", dependencies=[require_settings_api_key()])
async def optimize_regime(body: OptimizeRegimeRequest, request: Request):
    """Run differential evolution to find optimal regime weights for a pair/timeframe."""
    db = request.app.state.db
    cancel_flags = _get_cancel_flags(request.app)

    try:
        date_from = datetime.fromisoformat(body.date_from).replace(tzinfo=timezone.utc)
        date_to = datetime.fromisoformat(body.date_to).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601.")

    run_id = str(uuid4())
    cancel_flags[run_id] = {"cancelled": False}

    # Create a tracking row
    async with db.session_factory() as session:
        run = BacktestRun(
            id=run_id,
            status="running",
            config={"type": "optimize-regime", **body.model_dump()},
            pairs=[body.pair],
            timeframe=body.timeframe,
            date_from=date_from,
            date_to=date_to,
        )
        session.add(run)
        await session.commit()

    async def _run():
        try:
            bt_config = BacktestConfig(
                signal_threshold=body.signal_threshold,
                enable_patterns=body.enable_patterns,
            )

            # Load candles
            async with db.session_factory() as session:
                result = await session.execute(
                    select(Candle)
                    .where(Candle.pair == body.pair)
                    .where(Candle.timeframe == body.timeframe)
                    .where(Candle.timestamp >= date_from)
                    .where(Candle.timestamp <= date_to)
                    .order_by(Candle.timestamp)
                )
                candle_rows = result.scalars().all()

                # Load parent candles for confluence
                parent_tf = TIMEFRAME_PARENT.get(body.timeframe)
                parent_rows = []
                if parent_tf and parent_tf in TIMEFRAME_PERIOD_HOURS:
                    parent_prewarm = date_from - timedelta(
                        hours=TIMEFRAME_PERIOD_HOURS[parent_tf] * 70
                    )
                    parent_result = await session.execute(
                        select(Candle)
                        .where(Candle.pair == body.pair)
                        .where(Candle.timeframe == parent_tf)
                        .where(Candle.timestamp >= parent_prewarm)
                        .where(Candle.timestamp <= date_to)
                        .order_by(Candle.timestamp)
                    )
                    parent_rows = parent_result.scalars().all()

            candles = [
                {
                    "timestamp": c.timestamp.isoformat(),
                    "open": float(c.open), "high": float(c.high),
                    "low": float(c.low), "close": float(c.close),
                    "volume": float(c.volume),
                }
                for c in candle_rows
            ]
            parent_candles = [
                {
                    "timestamp": c.timestamp.isoformat(),
                    "open": float(c.open), "high": float(c.high),
                    "low": float(c.low), "close": float(c.close),
                    "volume": float(c.volume),
                }
                for c in parent_rows
            ] if parent_rows else None

            if len(candles) < 70:
                raise ValueError(f"Not enough candles ({len(candles)}). Need at least 70.")

            # Progress callback — updates BacktestRun.results periodically so
            # the frontend can poll for intermediate progress (eval count, best fitness).
            last_progress_update = [0]  # mutable counter for closure

            def _on_progress(evals, best_fitness):
                # Throttle DB writes: only update every 25 evaluations
                if evals - last_progress_update[0] >= 25:
                    last_progress_update[0] = evals
                    asyncio.get_event_loop().call_soon_threadsafe(
                        asyncio.ensure_future,
                        _update_progress(run_id, evals, best_fitness),
                    )

            async def _update_progress(rid, evals, best_fitness):
                try:
                    async with db.session_factory() as s:
                        r = await s.execute(select(BacktestRun).where(BacktestRun.id == rid))
                        row = r.scalar_one()
                        row.results = {"status": "optimizing", "evaluations": evals, "best_fitness": round(best_fitness, 4)}
                        await s.commit()
                except Exception:
                    pass  # best-effort progress update

            opt_result = await asyncio.to_thread(
                optimize_regime_weights,
                candles, body.pair, bt_config, parent_candles,
                body.max_iterations, cancel_flags.get(run_id),
                _on_progress,
            )

            # Save optimized weights to DB
            if opt_result["fitness"] > 0:
                weights = opt_result["weights"]
                async with db.session_factory() as session:
                    # Upsert RegimeWeights row
                    existing = await session.execute(
                        select(RegimeWeights)
                        .where(RegimeWeights.pair == body.pair)
                        .where(RegimeWeights.timeframe == body.timeframe)
                    )
                    rw = existing.scalar_one_or_none()
                    if rw is None:
                        rw = RegimeWeights(pair=body.pair, timeframe=body.timeframe)
                        session.add(rw)

                    for regime in ["trending", "ranging", "volatile"]:
                        for cap_key in ["trend_cap", "mean_rev_cap", "bb_vol_cap", "volume_cap"]:
                            setattr(rw, f"{regime}_{cap_key}", weights[regime][cap_key])

                        # Scale all 4 outer weights to sum to 1.0 per regime column.
                        # The optimizer only tunes tech:pattern ratio; flow/onchain
                        # use defaults. We preserve the optimizer's tech:pattern ratio
                        # while keeping default flow:onchain proportions.
                        from app.engine.regime import DEFAULT_OUTER_WEIGHTS
                        defaults = DEFAULT_OUTER_WEIGHTS[regime]
                        opt_tech = weights[regime]["tech"]
                        opt_pattern = weights[regime]["pattern"]
                        opt_ratio = opt_tech / opt_pattern if opt_pattern > 0 else 1.0
                        flow_default = defaults["flow"]
                        onchain_default = defaults["onchain"]
                        remaining = 1.0 - flow_default - onchain_default
                        new_pattern = remaining / (opt_ratio + 1.0)
                        new_tech = remaining - new_pattern
                        setattr(rw, f"{regime}_tech_weight", new_tech)
                        setattr(rw, f"{regime}_pattern_weight", new_pattern)
                        setattr(rw, f"{regime}_flow_weight", flow_default)
                        setattr(rw, f"{regime}_onchain_weight", onchain_default)

                    await session.commit()

                    # Re-query after commit to get a cleanly loaded instance
                    # (commit expires in-session objects; detached access would fail)
                    refreshed = await session.execute(
                        select(RegimeWeights)
                        .where(RegimeWeights.pair == body.pair)
                        .where(RegimeWeights.timeframe == body.timeframe)
                    )
                    rw_fresh = refreshed.scalar_one()
                    # Expunge so it can be used outside this session
                    session.expunge(rw_fresh)

                # Hot-reload into app state (using the detached-but-loaded instance)
                request.app.state.regime_weights[(body.pair, body.timeframe)] = rw_fresh

            final_status = "cancelled" if cancel_flags.get(run_id, {}).get("cancelled") else "completed"

            async with db.session_factory() as session:
                result = await session.execute(
                    select(BacktestRun).where(BacktestRun.id == run_id)
                )
                run_row = result.scalar_one()
                run_row.status = final_status
                run_row.results = {
                    "fitness": opt_result["fitness"],
                    "stats": opt_result["stats"],
                    "weights": opt_result["weights"],
                    "evaluations": opt_result.get("evaluations", 0),
                }
                await session.commit()

        except Exception as e:
            logger.error(f"Regime optimization {run_id} failed: {e}")
            try:
                async with db.session_factory() as session:
                    result = await session.execute(
                        select(BacktestRun).where(BacktestRun.id == run_id)
                    )
                    run_row = result.scalar_one()
                    run_row.status = "failed"
                    run_row.results = {"error": str(e)}
                    await session.commit()
            except Exception:
                pass
        finally:
            cancel_flags.pop(run_id, None)

    asyncio.create_task(_run())
    return {"run_id": run_id, "status": "running"}
```

- [ ] **Step 28: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass.

---

## Chunk 6: Pipeline Integration Tests

### Task 8: Pipeline Integration Tests

**Files:**
- Create: `backend/tests/engine/test_regime_pipeline.py`

- [ ] **Step 29: Write pipeline integration tests**

```python
# backend/tests/engine/test_regime_pipeline.py
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.main import run_pipeline


def _mock_db():
    mock_session = AsyncMock()
    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db, mock_session


def _make_app(regime_weights=None):
    """Build a minimal FastAPI app with all app.state attributes run_pipeline() accesses."""
    app = FastAPI()

    # Settings — run_pipeline reads many attributes via app.state.settings
    app.state.settings = MagicMock()
    app.state.settings.engine_confluence_max_score = 15
    app.state.settings.engine_signal_threshold = 40
    app.state.settings.engine_llm_threshold = 20
    app.state.settings.engine_ml_weight = 0.25
    app.state.settings.ml_confidence_threshold = 0.65
    app.state.settings.onchain_enabled = False
    app.state.settings.vapid_private_key = ""
    app.state.settings.vapid_claims_email = ""
    app.state.settings.news_llm_context_window_minutes = 30
    app.state.settings.openrouter_api_key = ""
    app.state.settings.pairs = ["BTC-USDT-SWAP"]
    app.state.settings.timeframes = ["1h"]

    # Core infrastructure
    app.state.redis = AsyncMock()
    mock_db, mock_session = _mock_db()
    app.state.db = mock_db
    app.state.order_flow = {}
    app.state.prompt_template = ""

    # WebSocket manager
    app.state.manager = MagicMock()
    app.state.manager.broadcast = AsyncMock()
    app.state.manager.broadcast_candle = AsyncMock()

    # Regime weights (the feature under test)
    app.state.regime_weights = regime_weights or {}

    # Pipeline task tracking
    app.state.pipeline_tasks = set()

    # Optional subsystems accessed via getattr() — set to None/empty to skip
    app.state.ml_predictors = {}
    app.state.tracker = None
    app.state.okx_client = None

    return app, mock_session


def _raw_candles(n=200):
    return [
        json.dumps({
            "timestamp": f"2026-01-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00+00:00",
            "open": 67000 + i * 10, "high": 67100 + i * 10,
            "low": 66900 + i * 10, "close": 67050 + i * 10,
            "volume": 100,
        })
        for i in range(n)
    ]


class TestPipelineWithoutRegimeWeights:
    @pytest.mark.asyncio
    async def test_runs_with_empty_regime_weights(self):
        """Pipeline with no learned regime weights should use defaults."""
        app, _ = _make_app()
        app.state.redis.lrange = AsyncMock(return_value=_raw_candles())
        app.state.redis.get = AsyncMock(return_value=None)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1h",
            "timestamp": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }
        # Should not raise
        await run_pipeline(app, candle)


class TestPipelineWithRegimeWeights:
    @pytest.mark.asyncio
    async def test_runs_with_learned_regime_weights(self):
        """Pipeline with learned regime weights should use them."""
        rw = MagicMock()
        for regime in ["trending", "ranging", "volatile"]:
            setattr(rw, f"{regime}_trend_cap", 30.0)
            setattr(rw, f"{regime}_mean_rev_cap", 25.0)
            setattr(rw, f"{regime}_bb_vol_cap", 25.0)
            setattr(rw, f"{regime}_volume_cap", 20.0)
            setattr(rw, f"{regime}_tech_weight", 0.40)
            setattr(rw, f"{regime}_flow_weight", 0.20)
            setattr(rw, f"{regime}_onchain_weight", 0.20)
            setattr(rw, f"{regime}_pattern_weight", 0.20)

        app, _ = _make_app(regime_weights={("BTC-USDT-SWAP", "1h"): rw})
        app.state.redis.lrange = AsyncMock(return_value=_raw_candles())
        app.state.redis.get = AsyncMock(return_value=None)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1h",
            "timestamp": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }
        # Should not raise
        await run_pipeline(app, candle)
```

Note: These tests verify the pipeline wiring doesn't crash with and without regime weights. Full signal emission tests are integration-level and depend on score thresholds; the unit tests in `test_regime.py` and `test_traditional.py` cover the scoring logic itself.

- [ ] **Step 29b: Run integration tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_pipeline.py -v`
Expected: All tests PASS.

---

## Chunk 7: Final Verification

### Task 9: Full Test Suite + Docs Update + Commit

- [ ] **Step 30: Run the complete test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 30b: Update `docs/signal-algorithm-improvements.md`**

Change item #2 (Market Regime Awareness) status from `Not started` to `Implemented` and update the approach description to reflect the actual implementation:

In `docs/signal-algorithm-improvements.md`, replace the #2 section's approach and status:

From:
```
**Approach:** Regime detection using existing ADX + BB width percentile, then shift indicator component weights per regime.

- **Trending:** ADX > 25 + BB expanding → upweight trend components, downweight mean-reversion
- **Ranging:** ADX < 20 + BB narrow/stable → upweight mean-reversion, downweight trend
- **Volatile/Choppy:** Low ADX + BB wide → reduce overall conviction

**Status:** Not started
```

To:
```
**Approach:** Smooth regime detection via sigmoid-scaled ADX + BB width percentile produces a continuous regime mix (trending/ranging/volatile). The mix adjusts both inner sub-component caps inside `compute_technical_score()` and outer blend weights in `compute_preliminary_score()`. Weight tables are per-(pair, timeframe) and learnable via backtest optimization using `differential_evolution`.

- **Trending:** Boost trend cap (38), suppress mean-reversion (15), higher tech+flow outer weight
- **Ranging:** Boost mean-reversion (32), suppress trend (18), higher onchain+pattern outer weight
- **Volatile:** Reduce all caps (sum 85 vs 100) for implicit signal suppression in choppy conditions

**Status:** Implemented — see `docs/superpowers/specs/2026-03-18-market-regime-awareness-design.md`
```

Also update item #3 (Order Flow Contrarian Bias) dependency note — regime detection is now available.

- [ ] **Step 31: Commit all changes**

```bash
git add backend/app/engine/regime.py backend/app/engine/regime_optimizer.py backend/app/engine/traditional.py backend/app/engine/backtester.py backend/app/db/models.py backend/app/main.py backend/app/api/backtest.py backend/tests/engine/test_regime.py backend/tests/engine/test_regime_backtest.py backend/tests/engine/test_regime_optimizer.py backend/tests/engine/test_regime_pipeline.py backend/tests/conftest.py backend/requirements.txt backend/alembic/versions/ docs/superpowers/specs/2026-03-18-market-regime-awareness-design.md docs/signal-algorithm-improvements.md
git commit -m "feat: add market regime awareness with adaptive weight blending and backtest optimizer"
```
