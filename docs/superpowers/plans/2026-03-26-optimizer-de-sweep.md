# Optimizer DE Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire differential evolution (DE) sweep into the optimizer so the 7 DE-method parameter groups produce real candidates instead of being skipped.

**Architecture:** Extend the existing `BacktestConfig.param_overrides` dict to route sigmoid and pattern override values to the correct scoring functions. Regime overrides flow through the existing `regime_weights` argument via a `SimpleNamespace` built from candidate values. A thin `_run_de_sweep()` wrapper around `scipy.optimize.differential_evolution` replaces the skip branch in `run_counterfactual_eval`. Non-backtestable groups (order_flow, llm_factors, onchain) are explicitly skipped since the backtester doesn't compute those scores.

**Tech Stack:** Python 3.11, scipy (already present via PyTorch), existing backtester + scoring functions

**Spec:** `docs/superpowers/specs/2026-03-25-optimizer-de-sweep-spec.md`

---

## Backtestable vs Non-Backtestable DE Groups

The backtester only runs tech + pattern scoring (order_flow=0, onchain=0, no LLM). This limits which DE groups can be meaningfully optimized:

| Group | Params | Backtestable | Override Channel |
|-------|--------|-------------|-----------------|
| `regime_caps` | 16 | Yes | `regime_weights` argument |
| `regime_outer` | 8 (backtestable) | Partial — only `tech_weight` + `pattern_weight` per regime | `regime_weights` argument (flow/onchain/liquidation pinned) |
| `sigmoid_curves` | 7 | Yes | `scoring_params` via `param_overrides` |
| `pattern_strengths` | 15 | Yes | `strength_overrides` via `param_overrides` |
| `order_flow` | 6 | **No** | Skipped |
| `llm_factors` | 13 | **No** | Skipped |
| `onchain` | 10 | **No** | Skipped |

## Existing Override Plumbing

`BacktestConfig` already has `param_overrides: dict` (line 83). The backtester passes it to `compute_technical_score(overrides=config.param_overrides)` which reads `overrides.get("mr_pressure")` and `overrides.get("vol_multiplier")` for MR pressure. This channel must be preserved. We add two new extraction layers on top: sigmoid keys -> `scoring_params`, pattern keys -> `strength_overrides`. The remaining keys (after extracting sigmoid + pattern) are passed as `overrides=` so MR pressure still flows through cleanly.

## Promotion Path Note

Promoted DE candidates flow through `PipelineSettings` → `app.state.scoring_params` → `compute_technical_score(scoring_params=...)` in the live pipeline. Currently `PipelineSettings` only stores 4 mean-reversion scoring params. Adding the new sigmoid keys to `PipelineSettings` is out of scope for this plan — DE results for sigmoid/pattern groups will be proposed and shadow-tested, but full live promotion requires a follow-up migration to add sigmoid columns to `PipelineSettings`. Regime weight promotion already works via the existing `RegimeWeights` DB table.

## Key Codebase Fact: `run_backtest` Return Structure

`run_backtest()` returns `{"trades": [...], "stats": {...}}`. Metrics like `profit_factor`, `win_rate`, etc. are nested under `["stats"]`. The existing grid sweep at `optimizer.py:345` has a pre-existing bug accessing these at the wrong level (`results.get("profit_factor", 0)` instead of `results["stats"].get("profit_factor", 0)`). This plan fixes it.

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/engine/traditional.py:287-335` | Read sigmoid params from `scoring_params` dict instead of hardcoded values |
| Modify | `backend/app/engine/patterns.py:237-271` | Accept `strength_overrides` dict in `compute_pattern_score` |
| Modify | `backend/app/engine/backtester.py:139,156,178` | Extract sigmoid/pattern overrides from `param_overrides`; pass to scoring functions |
| Modify | `backend/app/engine/optimizer.py:345-366` | Wire DE sweep; fix grid sweep stats access; add `_run_de_sweep()` and `_build_regime_weights()` helpers |
| Create | `backend/tests/engine/test_de_sweep.py` | Tests for all override plumbing + DE sweep integration |

---

## Task 1: Extend `compute_technical_score` Sigmoid Overrides

**Files:**
- Modify: `backend/app/engine/traditional.py:287-335`
- Test: `backend/tests/engine/test_de_sweep.py`

Currently 5 sigmoid values are hardcoded in `compute_technical_score` (lines 287, 288, 311, 332, 335). The function already accepts `scoring_params` and reads mean-reversion params from it (lines 302-306). Extend this pattern to sigmoid curves.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/engine/test_de_sweep.py
"""Tests for DE sweep parameter override plumbing and optimizer integration."""
import pandas as pd
import pytest

from app.engine.traditional import compute_technical_score


def _make_candles(n: int = 100, trend: str = "up") -> pd.DataFrame:
    """Generate synthetic candle DataFrame for testing."""
    import numpy as np
    rng = np.random.RandomState(42)
    base = 50000.0
    rows = []
    for i in range(n):
        if trend == "up":
            c = base + i * 10 + rng.uniform(-5, 15)
        else:
            c = base - i * 10 + rng.uniform(-15, 5)
        o = c + rng.uniform(-20, 20)
        h = max(o, c) + rng.uniform(0, 30)
        l = min(o, c) - rng.uniform(0, 30)
        rows.append({
            "timestamp": f"2026-01-01T{i:04d}",
            "open": o, "high": h, "low": l, "close": c,
            "volume": 100 + rng.uniform(0, 50),
        })
    return pd.DataFrame(rows)


class TestSigmoidOverrides:
    def test_custom_sigmoid_params_change_score(self):
        """Sigmoid overrides via scoring_params produce different scores."""
        df = _make_candles(100, "up")
        r_default = compute_technical_score(df)
        r_override = compute_technical_score(df, scoring_params={
            "trend_strength_steepness": 0.05,  # much flatter than default 0.25
            "trend_score_steepness": 0.10,      # flatter than default 0.30
        })
        # Scores should differ (flatter sigmoid = less extreme scores)
        assert r_default["score"] != r_override["score"]

    def test_sigmoid_defaults_unchanged(self):
        """Empty scoring_params produces identical score to no scoring_params."""
        df = _make_candles(100, "up")
        r_none = compute_technical_score(df)
        r_empty = compute_technical_score(df, scoring_params={})
        assert r_none["score"] == r_empty["score"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestSigmoidOverrides::test_custom_sigmoid_params_change_score -v`
Expected: FAIL -- sigmoid params are hardcoded so scoring_params overrides have no effect, scores are equal.

- [ ] **Step 3: Implement sigmoid override reads**

In `backend/app/engine/traditional.py`, move the `sp = scoring_params or {}` line earlier (before line 287) and replace hardcoded sigmoid values.

Find (lines 301-302):
```python
    # === Scoring parameters (shape + blend) ===
    sp = scoring_params or {}
```

Move this block to just before line 286 (before `adx_center = ...`), so `sp` is available for sigmoid reads:
```python
    # === Scoring parameters (shape + blend) ===
    sp = scoring_params or {}

    adx_center = getattr(regime_weights, "adx_center", 20.0) if regime_weights else 20.0
```

Then update the 5 hardcoded sigmoid lines:

Line 287 -- replace `steepness=0.25`:
```python
    trend_strength = sigmoid_scale(adx_val, center=sp.get("trend_strength_center", adx_center), steepness=sp.get("trend_strength_steepness", 0.25))
```

Line 288 -- replace `center=50, steepness=0.08`:
```python
    vol_expansion = sigmoid_scale(bb_width_pct, center=sp.get("vol_expansion_center", 50), steepness=sp.get("vol_expansion_steepness", 0.08))
```

Line 311 -- replace `steepness=0.30`:
```python
    trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=sp.get("trend_score_steepness", 0.30)) * caps["trend_cap"]
```

Line 332 -- replace `steepness=4`:
```python
        obv_strength = sigmoid_scale(abs(obv_slope_norm), center=0, steepness=sp.get("obv_slope_steepness", 4))
```

Line 335 -- replace `steepness=3`:
```python
        vol_strength = sigmoid_scale(vol_ratio - 1, center=0, steepness=sp.get("volume_ratio_steepness", 3))
```

Remove the now-duplicate `sp = scoring_params or {}` from the old location (around line 301). Keep the mean-reversion reads (`mr_rsi_steep`, etc.) in place -- they already read from `sp`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestSigmoidOverrides -v`
Expected: PASS

---

## Task 2: Make Pattern Strengths Overridable

**Files:**
- Modify: `backend/app/engine/patterns.py:237-271`
- Test: `backend/tests/engine/test_de_sweep.py`

Pattern detector functions return hardcoded `"strength"` values (e.g., `"strength": 12` for hammer). `compute_pattern_score` reads `p.get("strength", 0)` at line 271. Add a `strength_overrides` dict parameter that overrides individual pattern strengths by name.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/engine/test_de_sweep.py`:

```python
from app.engine.patterns import compute_pattern_score


class TestPatternStrengthOverrides:
    def test_strength_override_changes_score(self):
        """Custom pattern strengths via strength_overrides change output score."""
        patterns = [
            {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
        ]
        ctx = {"adx": 10, "di_plus": 20, "di_minus": 15, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 50000}

        r_default = compute_pattern_score(patterns, ctx)
        r_override = compute_pattern_score(patterns, ctx, strength_overrides={"hammer": 25})
        assert r_override["score"] > r_default["score"]

    def test_no_override_preserves_score(self):
        """None/empty strength_overrides gives identical result."""
        patterns = [
            {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15},
        ]
        ctx = {"adx": 10, "di_plus": 20, "di_minus": 15, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 50000}

        r_none = compute_pattern_score(patterns, ctx)
        r_empty = compute_pattern_score(patterns, ctx, strength_overrides={})
        assert r_none["score"] == r_empty["score"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestPatternStrengthOverrides::test_strength_override_changes_score -v`
Expected: FAIL -- `compute_pattern_score()` does not accept `strength_overrides` kwarg.

- [ ] **Step 3: Implement strength overrides**

In `backend/app/engine/patterns.py`:

Add name-to-key helper (above `compute_pattern_score`, around line 236):
```python
def _pattern_key(name: str) -> str:
    """Convert display name to PATTERN_STRENGTHS key: 'Bullish Engulfing' -> 'bullish_engulfing'."""
    return name.lower().replace(" ", "_")
```

Update function signature (line 237):
```python
def compute_pattern_score(
    patterns: list[dict],
    indicator_ctx: dict | None = None,
    strength_overrides: dict[str, int | float] | None = None,
) -> dict:
```

In the scoring loop (line 271), after `strength = p.get("strength", 0)`, add override lookup:
```python
        strength = p.get("strength", 0)
        if strength_overrides:
            strength = strength_overrides.get(_pattern_key(p.get("name", "")), strength)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestPatternStrengthOverrides -v`
Expected: PASS

---

## Task 3: Add Override Routing in Backtester

**Files:**
- Modify: `backend/app/engine/backtester.py:139,156,178`
- Test: `backend/tests/engine/test_de_sweep.py`

`BacktestConfig.param_overrides` already exists (line 83) and is already passed as `overrides=` to `compute_technical_score` (line 156) for MR pressure. Extend the backtester to ALSO extract sigmoid keys into `scoring_params` and pattern keys into `strength_overrides`, passing them alongside the existing `overrides` channel.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/engine/test_de_sweep.py`:

```python
from app.engine.backtester import run_backtest, BacktestConfig


class TestBacktestParamOverrides:
    def test_sigmoid_override_via_backtest(self):
        """param_overrides with sigmoid keys reach compute_technical_score and change results."""
        candles = _make_candles(120, "up").to_dict("records")
        r_default = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(signal_threshold=15))
        r_override = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={
                "trend_strength_steepness": 0.05,
                "vol_expansion_steepness": 0.01,
            },
        ))
        # Both complete without error; stats key exists
        assert "profit_factor" in r_default["stats"]
        assert "profit_factor" in r_override["stats"]
        # Overrides must change behavior — stats should differ
        assert r_default["stats"] != r_override["stats"], (
            "Sigmoid overrides had no effect on backtest results"
        )

    def test_pattern_override_via_backtest(self):
        """param_overrides with pattern keys reach compute_pattern_score and change results."""
        candles = _make_candles(120, "up").to_dict("records")
        r_default = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(signal_threshold=15))
        r_override = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={"hammer": 25, "bullish_engulfing": 25},
        ))
        assert "profit_factor" in r_default["stats"]
        assert "profit_factor" in r_override["stats"]
        # Overrides must change behavior — stats should differ
        assert r_default["stats"] != r_override["stats"], (
            "Pattern strength overrides had no effect on backtest results"
        )

    def test_empty_overrides_matches_no_overrides(self):
        """Empty param_overrides dict produces same result as None."""
        candles = _make_candles(120, "up").to_dict("records")
        r_none = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(signal_threshold=15))
        r_empty = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15, param_overrides={},
        ))
        assert r_none["stats"]["profit_factor"] == r_empty["stats"]["profit_factor"]

    def test_mr_pressure_overrides_still_work(self):
        """Existing MR pressure override channel is preserved."""
        candles = _make_candles(120, "up").to_dict("records")
        # This should not raise -- MR pressure overrides flow through overrides= channel
        r = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={"mr_pressure": {"max_cap_shift": 0}},
        ))
        assert "profit_factor" in r["stats"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestBacktestParamOverrides::test_sigmoid_override_via_backtest -v`
Expected: FAIL -- sigmoid keys in `param_overrides` are not extracted to `scoring_params`, so `compute_technical_score` ignores them.

- [ ] **Step 3: Add override extraction and routing**

In `backend/app/engine/backtester.py`, add override partitioning before the main loop (around line 139, after `return _build_results(...)` early exit):

```python
    from app.engine.constants import PATTERN_STRENGTHS

    _SIGMOID_KEYS = frozenset({
        "trend_strength_center", "trend_strength_steepness",
        "vol_expansion_center", "vol_expansion_steepness",
        "trend_score_steepness", "obv_slope_steepness",
        "volume_ratio_steepness",
        "mean_rev_rsi_steepness", "mean_rev_bb_pos_steepness",
        "squeeze_steepness", "mean_rev_blend_ratio",
    })

    _overrides = config.param_overrides or {}
    scoring_params = {k: v for k, v in _overrides.items() if k in _SIGMOID_KEYS} or None
    strength_overrides = {k: v for k, v in _overrides.items() if k in PATTERN_STRENGTHS} or None
    # Pass only unconsumed keys to overrides= (MR pressure, vol_multiplier)
    _remaining = {k: v for k, v in _overrides.items() if k not in _SIGMOID_KEYS and k not in PATTERN_STRENGTHS} or None
```

Update the `compute_technical_score` call (line 156) to pass `scoring_params` and the filtered `overrides`:
```python
            tech_result = compute_technical_score(
                df, regime_weights=regime_weights,
                scoring_params=scoring_params,
                overrides=_remaining,
            )
```

Update the `compute_pattern_score` call (line 178) to pass `strength_overrides`:
```python
                pat_score = compute_pattern_score(detected, indicator_ctx, strength_overrides=strength_overrides)["score"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestBacktestParamOverrides -v`
Expected: PASS

- [ ] **Step 5: Run existing MR pressure tests for regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py -v`
Expected: All existing tests PASS (MR pressure overrides still flow through `overrides=` channel)

---

## Task 4: Regime Candidate Builder + DE Sweep Core

**Files:**
- Modify: `backend/app/engine/optimizer.py`
- Test: `backend/tests/engine/test_de_sweep.py`

Add two helpers to `optimizer.py`:
1. `_build_regime_weights()` -- constructs a regime_weights-like namespace from a flat candidate dict, overlaid on a base RegimeWeights object. When `base` is None (no learned weights), populates all defaults from `DEFAULT_CAPS` and `DEFAULT_OUTER_WEIGHTS`.
2. `_run_de_sweep()` -- thin wrapper around `scipy.optimize.differential_evolution`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/engine/test_de_sweep.py`:

```python
from types import SimpleNamespace


class TestBuildRegimeWeights:
    def test_candidate_overrides_base(self):
        """Candidate values override base regime_weights attributes."""
        from app.engine.optimizer import _build_regime_weights

        base = SimpleNamespace(
            trending_trend_cap=38.0, trending_mean_rev_cap=22.0,
            trending_squeeze_cap=12.0, trending_volume_cap=28.0,
            trending_tech_weight=0.45, trending_flow_weight=0.25,
        )
        candidate = {"trending_trend_cap": 30.0, "trending_mean_rev_cap": 30.0}
        rw = _build_regime_weights(candidate, base)

        assert rw.trending_trend_cap == 30.0      # overridden
        assert rw.trending_mean_rev_cap == 30.0    # overridden
        assert rw.trending_squeeze_cap == 12.0     # from base
        assert rw.trending_tech_weight == 0.45     # from base

    def test_no_base_populates_defaults(self):
        """Without base, defaults are populated so blend_caps/blend_outer_weights work."""
        from app.engine.optimizer import _build_regime_weights

        candidate = {"trending_trend_cap": 35.0}
        rw = _build_regime_weights(candidate)
        assert rw.trending_trend_cap == 35.0        # overridden
        assert rw.ranging_trend_cap == 18            # from DEFAULT_CAPS
        assert rw.trending_tech_weight == 0.42       # from DEFAULT_OUTER_WEIGHTS
        assert rw.volatile_flow_weight == 0.18       # from DEFAULT_OUTER_WEIGHTS


class TestRunDeSweep:
    def test_maximizes_simple_quadratic(self):
        """DE sweep finds maximum of a simple quadratic objective."""
        from app.engine.optimizer import _run_de_sweep

        group_def = {
            "sweep_ranges": {"x": (0, 10, None), "y": (0, 10, None)},
            "constraints": lambda c: True,
        }

        # Objective: maximize -(x-3)^2 - (y-7)^2  (i.e., find x=3, y=7)
        def objective(candidate):
            return -((candidate["x"] - 3) ** 2 + (candidate["y"] - 7) ** 2)

        best, fitness = _run_de_sweep(objective, group_def, max_evals=300)
        assert abs(best["x"] - 3) < 0.5
        assert abs(best["y"] - 7) < 0.5

    def test_respects_constraints(self):
        """DE sweep rejects candidates that fail constraints."""
        from app.engine.optimizer import _run_de_sweep

        group_def = {
            "sweep_ranges": {"a": (0, 100, None), "b": (0, 100, None)},
            "constraints": lambda c: c["a"] + c["b"] <= 50,
        }

        def objective(candidate):
            return candidate["a"] + candidate["b"]  # maximize sum

        best, _ = _run_de_sweep(objective, group_def, max_evals=300)
        assert best["a"] + best["b"] <= 50 + 0.5  # within tolerance
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestBuildRegimeWeights -v`
Expected: FAIL -- `_build_regime_weights` does not exist.

- [ ] **Step 3: Implement `_build_regime_weights`**

Add to `backend/app/engine/optimizer.py` (above `run_counterfactual_eval`, around line 254):

```python
from types import SimpleNamespace

from app.engine.regime import REGIMES, CAP_KEYS, OUTER_KEYS, DEFAULT_CAPS, DEFAULT_OUTER_WEIGHTS


def _build_regime_weights(candidate: dict, base=None) -> SimpleNamespace:
    """Build a regime_weights namespace from candidate values overlaid on a base.

    Used by DE sweep to construct regime_weights objects that blend_caps()
    and blend_outer_weights() can read via getattr.
    When base is None, populates all attributes from DEFAULT_CAPS and
    DEFAULT_OUTER_WEIGHTS to prevent AttributeError in blend functions.
    """
    rw = SimpleNamespace()
    if base is not None:
        for attr, value in vars(base).items():
            if not attr.startswith("_"):
                setattr(rw, attr, value)
    else:
        # Populate from defaults so all attributes exist
        for regime in REGIMES:
            for cap_key in CAP_KEYS:
                setattr(rw, f"{regime}_{cap_key}", DEFAULT_CAPS[regime][cap_key])
            for outer_key in OUTER_KEYS:
                setattr(rw, f"{regime}_{outer_key}_weight", DEFAULT_OUTER_WEIGHTS[regime][outer_key])
    # Overlay candidate values
    for key, value in candidate.items():
        setattr(rw, key, value)
    return rw
```

- [ ] **Step 4: Implement `_run_de_sweep`**

Add to `backend/app/engine/optimizer.py` (below `_build_regime_weights`):

```python
def _run_de_sweep(
    objective,
    group_def: dict,
    max_evals: int = 500,
    seed: int | None = 42,
) -> tuple[dict, float]:
    """Run differential evolution to maximize an objective function.

    Args:
        objective: callable(candidate_dict) -> float (higher is better)
        group_def: param group with sweep_ranges and constraints
        max_evals: maximum function evaluations
        seed: random seed (42 for tests, None for production variance)

    Returns:
        (best_candidate_dict, best_fitness)
    """
    from scipy.optimize import differential_evolution

    param_names = list(group_def["sweep_ranges"].keys())
    bounds = [(lo, hi) for lo, hi, _ in group_def["sweep_ranges"].values()]
    constraint_fn = group_def["constraints"]

    def neg_objective(x):
        candidate = dict(zip(param_names, x))
        if not constraint_fn(candidate):
            return 1e6
        return -objective(candidate)

    n_params = len(param_names)
    # Higher popsize for constrained problems (regime caps/outer have
    # sum-equality constraints that random init rarely satisfies)
    popsize = max(15, min(25, max_evals // 20))
    maxiter = max(10, max_evals // (popsize * n_params))

    result = differential_evolution(
        neg_objective,
        bounds=bounds,
        maxiter=maxiter,
        popsize=popsize,
        tol=0.01,
        seed=seed,
        init="sobol",  # quasi-random init for better coverage of constrained spaces
    )

    best = dict(zip(param_names, result.x))
    return best, -result.fun
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestBuildRegimeWeights tests/engine/test_de_sweep.py::TestRunDeSweep -v`
Expected: PASS

---

## Task 5: Wire DE Branch in `run_counterfactual_eval`

**Files:**
- Modify: `backend/app/engine/optimizer.py:345-366`
- Test: `backend/tests/engine/test_de_sweep.py`

Replace the DE skip branch with actual DE sweep logic. Route regime groups through `_build_regime_weights` + `regime_weights` arg; route sigmoid/pattern groups through `param_overrides`. Also fix the pre-existing grid sweep bug where `results.get("profit_factor", 0)` accesses the wrong nesting level (should be `results["stats"].get("profit_factor", 0)`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/engine/test_de_sweep.py`:

```python
from unittest.mock import patch, AsyncMock, MagicMock


class TestDeWiring:
    @pytest.mark.asyncio
    async def test_de_group_calls_de_sweep(self):
        """DE-method groups invoke _run_de_sweep instead of being skipped."""
        from app.engine.optimizer import run_counterfactual_eval

        # Build minimal mock app
        app = MagicMock()
        app.state.settings = MagicMock()
        app.state.settings.engine_signal_threshold = 40
        app.state.regime_weights = {}

        # Mock DB to return enough candles
        mock_candle = MagicMock()
        mock_candle.timestamp = "2026-01-01T00:00"
        mock_candle.open = 50000
        mock_candle.high = 50100
        mock_candle.low = 49900
        mock_candle.close = 50050
        mock_candle.volume = 100

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_candle] * 200
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        app.state.db.session_factory.return_value = mock_session

        with patch("app.engine.optimizer._run_de_sweep") as mock_de:
            mock_de.return_value = ({"trend_strength_steepness": 0.20}, 1.5)

            with patch("app.engine.optimizer.run_backtest") as mock_bt:
                mock_bt.return_value = {
                    "trades": [],
                    "stats": {
                        "profit_factor": 1.5, "win_rate": 55,
                        "avg_rr": 1.2, "max_drawdown": 5, "total_trades": 20,
                    },
                }
                result = await run_counterfactual_eval(app, "sigmoid_curves")

            assert mock_de.called
            assert result is not None
            assert result["candidate"]["trend_strength_steepness"] == 0.20
            assert result["metrics"]["profit_factor"] == 1.5

    @pytest.mark.asyncio
    async def test_regime_outer_filters_non_backtestable_weights(self):
        """regime_outer DE sweep only includes tech+pattern weights, not flow/onchain/liquidation."""
        from app.engine.optimizer import run_counterfactual_eval

        app = MagicMock()
        app.state.settings = MagicMock()
        app.state.settings.engine_signal_threshold = 40
        app.state.regime_weights = {}

        mock_candle = MagicMock()
        mock_candle.timestamp = "2026-01-01T00:00"
        mock_candle.open = 50000
        mock_candle.high = 50100
        mock_candle.low = 49900
        mock_candle.close = 50050
        mock_candle.volume = 100

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_candle] * 200
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        app.state.db.session_factory.return_value = mock_session

        with patch("app.engine.optimizer._run_de_sweep") as mock_de:
            mock_de.return_value = ({"trending_tech_weight": 0.40, "trending_pattern_weight": 0.15}, 1.2)

            with patch("app.engine.optimizer.run_backtest") as mock_bt:
                mock_bt.return_value = {
                    "trades": [],
                    "stats": {
                        "profit_factor": 1.2, "win_rate": 52,
                        "avg_rr": 1.1, "max_drawdown": 6, "total_trades": 15,
                    },
                }
                await run_counterfactual_eval(app, "regime_outer")

            # Verify only tech+pattern keys were in the sweep_ranges passed to DE
            call_args = mock_de.call_args
            group_def = call_args[0][1]  # second positional arg
            sweep_keys = set(group_def["sweep_ranges"].keys())
            for key in sweep_keys:
                assert "tech" in key or "pattern" in key, (
                    f"Non-backtestable key {key!r} should not be in regime_outer sweep"
                )
            # flow/onchain/liquidation must not be present
            assert not any("flow" in k for k in sweep_keys)
            assert not any("onchain" in k for k in sweep_keys)
            assert not any("liquidation" in k for k in sweep_keys)

    @pytest.mark.asyncio
    async def test_non_backtestable_group_skipped(self):
        """Non-backtestable DE groups (order_flow, etc.) return None."""
        from app.engine.optimizer import run_counterfactual_eval

        app = MagicMock()
        app.state.settings = MagicMock()
        app.state.regime_weights = {}

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [MagicMock()] * 200
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        app.state.db.session_factory.return_value = mock_session

        result = await run_counterfactual_eval(app, "order_flow")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestDeWiring::test_de_group_calls_de_sweep -v`
Expected: FAIL -- current code returns None for all DE groups.

- [ ] **Step 3: Fix grid sweep stats access**

In `backend/app/engine/optimizer.py`, fix lines 345-358 (grid sweep result extraction). Change:

```python
                        pf = results.get("profit_factor", 0) or 0
```
To:
```python
                        stats = results.get("stats", {})
                        pf = stats.get("profit_factor", 0) or 0
```

And change the best_metrics extraction (lines 353-362):
```python
                if best_candidate and best_metrics:
                    best_stats = best_metrics.get("stats", {})
                    return {
                        "candidate": best_candidate,
                        "metrics": {
                            "profit_factor": best_stats.get("profit_factor", 0),
                            "win_rate": best_stats.get("win_rate", 0),
                            "avg_rr": best_stats.get("avg_rr", 0),
                            "drawdown": best_stats.get("max_drawdown", 0),
                            "signals_tested": best_stats.get("total_trades", 0),
                        },
                    }
```

- [ ] **Step 4: Wire DE branch**

Replace lines 363-366 (the DE skip):

```python
            else:
                # DE-based groups: skip for now
                logger.info("DE sweep for %s not yet wired -- skipping", group_name)
                return None
```

With:

```python
            else:
                # DE-based sweep
                _NON_BACKTESTABLE = {"order_flow", "llm_factors", "onchain"}
                if group_name in _NON_BACKTESTABLE:
                    logger.info(
                        "DE group %s requires signal replay (not backtestable) -- skipping",
                        group_name,
                    )
                    return None

                from app.engine.backtester import run_backtest, BacktestConfig

                candle_dicts = [
                    {
                        "timestamp": c.timestamp,
                        "open": c.open, "high": c.high,
                        "low": c.low, "close": c.close,
                        "volume": c.volume,
                    }
                    for c in candles
                ]

                is_regime_group = group_name in ("regime_caps", "regime_outer")
                base_rw = app.state.regime_weights.get((pair, "15m"))

                # For regime_outer, only sweep tech+pattern weights (backtestable);
                # flow/onchain/liquidation multiply zero in backtests so optimizing
                # them would learn zero-weights that suppress real signals in prod.
                _BACKTESTABLE_OUTER = {"tech", "pattern"}
                if group_name == "regime_outer":
                    group = {
                        **group,
                        "sweep_ranges": {
                            k: v for k, v in group["sweep_ranges"].items()
                            if any(src in k for src in _BACKTESTABLE_OUTER)
                        },
                    }

                def objective(candidate):
                    if is_regime_group:
                        rw = _build_regime_weights(candidate, base_rw)
                        bt_config = BacktestConfig(
                            signal_threshold=settings.engine_signal_threshold,
                        )
                        return (
                            run_backtest(candle_dicts, pair, bt_config, regime_weights=rw)
                            ["stats"].get("profit_factor", 0) or 0
                        )
                    else:
                        bt_config = BacktestConfig(
                            signal_threshold=settings.engine_signal_threshold,
                            param_overrides=candidate,
                        )
                        return (
                            run_backtest(candle_dicts, pair, bt_config, regime_weights=base_rw)
                            ["stats"].get("profit_factor", 0) or 0
                        )

                n_params = len(group["sweep_ranges"])
                max_evals = min(500, n_params * 30)
                best_candidate, best_fitness = _run_de_sweep(
                    objective, group, max_evals=max_evals,
                    seed=None,  # non-deterministic for production (avoids re-proposing same candidate)
                )

                if best_fitness > 0:
                    # Final eval for full metrics
                    if is_regime_group:
                        rw = _build_regime_weights(best_candidate, base_rw)
                        final_config = BacktestConfig(
                            signal_threshold=settings.engine_signal_threshold,
                        )
                        final = run_backtest(
                            candle_dicts, pair, final_config, regime_weights=rw,
                        )
                    else:
                        final_config = BacktestConfig(
                            signal_threshold=settings.engine_signal_threshold,
                            param_overrides=best_candidate,
                        )
                        final = run_backtest(
                            candle_dicts, pair, final_config, regime_weights=base_rw,
                        )
                    final_stats = final.get("stats", {})
                    return {
                        "candidate": best_candidate,
                        "metrics": {
                            "profit_factor": final_stats.get("profit_factor", 0),
                            "win_rate": final_stats.get("win_rate", 0),
                            "avg_rr": final_stats.get("avg_rr", 0),
                            "drawdown": final_stats.get("max_drawdown", 0),
                            "signals_tested": final_stats.get("total_trades", 0),
                        },
                    }
                return None
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run the full engine test suite for regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/ -v`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/engine/traditional.py backend/app/engine/patterns.py backend/app/engine/backtester.py backend/app/engine/optimizer.py backend/tests/engine/test_de_sweep.py
git commit -m "feat(engine): wire DE sweep into optimizer for backtestable parameter groups

- Extend compute_technical_score scoring_params to accept sigmoid overrides
- Add strength_overrides param to compute_pattern_score
- Route sigmoid/pattern overrides from BacktestConfig.param_overrides
  (filter consumed keys out of overrides= to keep MR pressure channel clean)
- Add _build_regime_weights helper for regime group DE candidates
- Add _run_de_sweep wrapper around scipy differential_evolution
  (sobol init + configurable seed for better constrained-space coverage)
- Replace DE skip branch with real sweep for regime_caps, regime_outer,
  sigmoid_curves, and pattern_strengths groups
- Filter regime_outer to only tech+pattern weights (flow/onchain/liquidation
  are zero in backtests and would learn suppressive weights)
- Skip non-backtestable groups (order_flow, llm_factors, onchain)
- Fix grid sweep accessing profit_factor at wrong nesting level"
```
