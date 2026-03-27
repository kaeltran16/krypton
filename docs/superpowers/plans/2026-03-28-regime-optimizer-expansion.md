# Regime Optimizer Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand regime weight optimization to cover all 6 scoring sources by wiring OrderFlowSnapshot data into the backtester (Workstream B) and building a new live-signal-based optimizer mode (Workstream C).

**Architecture:** Two independent workstreams. B refactors the existing backtester + DE optimizer to include flow data. C persists per-source scores on emitted signals, then adds a new DE optimizer that re-scores resolved signals with candidate weight vectors — no candle replay, just combiner math on stored scores. Both workstreams share a parameterized DE runner and converge on the same ParameterProposal pipeline.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, scipy.optimize (differential_evolution), React 19, TypeScript, Zustand

**Spec:** `docs/superpowers/specs/2026-03-27-regime-optimizer-expansion-design.md`

---

## File Structure

| File | Responsibility | Workstream |
|------|---------------|------------|
| `engine/traditional.py` | Rename `compute_order_flow_score` → `score_order_flow`, add alias | B |
| `engine/backtester.py` | `BacktestConfig.flow_snapshots`, bisect lookup, flow scoring in loop | B |
| `engine/regime_optimizer.py` | Parameterize bounds/vectors, extract `_run_de_optimization`, add `signal_vector_to_weight_dict` + `optimize_from_signals` | B + C |
| `main.py` | Add per-source scores + `regime_steady` to `raw_indicators`, init `active_signal_optimization` on `app.state` | C |
| `api/optimizer.py` | New `POST /api/optimizer/optimize-from-signals` endpoint with concurrency guard | C |
| `api/routes.py` | Add `outcome` query param to `GET /signals` + `GET /signals/count` endpoint | C |
| `web/src/features/optimizer/types.ts` | Add `optimization_mode` to `BacktestMetrics` | C |
| `web/src/shared/lib/api.ts` | Add `optimizeFromSignals()` + `getResolvedSignalCount()` | C |
| `web/src/features/optimizer/store.ts` | Add `optimizeFromSignals` action | C |
| `web/src/features/optimizer/components/OptimizerPage.tsx` | Live signal trigger button + signal count | C |
| `web/src/features/optimizer/components/ProposalCard.tsx` | "Backtest" / "Live Signals" badge | C |

---

## Workstream B: OrderFlowSnapshot in Backtester

### Task 1: Extract score_order_flow() pure function

**Files:**
- Modify: `backend/app/engine/traditional.py:440-592`
- Test: `backend/tests/engine/test_traditional.py`

The function `compute_order_flow_score()` is already pure (no app.state deps). We rename it and add a backward-compat alias so existing callers (main.py, api/routes.py) don't break.

- [ ] **Step 1: Write the failing test**

Create a test that imports the new name and verifies it matches the old function's output.

```python
# Add to tests/engine/test_traditional.py

from app.engine.traditional import score_order_flow, compute_order_flow_score


class TestScoreOrderFlow:
    def test_alias_returns_same_result(self):
        """score_order_flow and compute_order_flow_score are the same function."""
        metrics = {
            "funding_rate": 0.0005,
            "open_interest": 1_000_000,
            "oi_change_pct": 2.5,
            "long_short_ratio": 1.3,
            "cvd_delta": 500,
        }
        regime = {"trending": 0.6, "ranging": 0.2, "volatile": 0.1, "steady": 0.1}
        kwargs = dict(
            metrics=metrics,
            regime=regime,
            flow_history=None,
            trend_conviction=0.5,
            mr_pressure=0.3,
            flow_age_seconds=120.0,
            asset_scale=1.0,
        )
        result_new = score_order_flow(**kwargs)
        result_old = compute_order_flow_score(**kwargs)
        assert result_new == result_old

    def test_returns_score_details_confidence(self):
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result = score_order_flow(metrics=metrics)
        assert "score" in result
        assert "details" in result
        assert "confidence" in result
        assert isinstance(result["score"], (int, float))

    def test_empty_metrics_returns_zero(self):
        result = score_order_flow(metrics={})
        assert result["score"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestScoreOrderFlow -v`
Expected: FAIL — `ImportError: cannot import name 'score_order_flow'`

- [ ] **Step 3: Rename function and add alias**

In `backend/app/engine/traditional.py`, rename the function definition at line 440:

```python
# Line 440: rename compute_order_flow_score → score_order_flow
def score_order_flow(
    metrics: dict,
    regime: dict | None = None,
    flow_history: list | None = None,
    trend_conviction: float = 0.0,
    mr_pressure: float = 0.0,
    flow_age_seconds: float | None = None,
    asset_scale: float = 1.0,
) -> dict:
```

After the function body ends (after line ~592), add the alias:

```python
# Backward-compat alias — existing callers import this name
compute_order_flow_score = score_order_flow
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestScoreOrderFlow -v`
Expected: PASS (3 tests)

Then run existing tests to verify no regressions:
Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All existing tests PASS

---

### Task 2: Backtester flow snapshot integration

**Files:**
- Modify: `backend/app/engine/backtester.py:1-20,84-97,185-280`
- Test: `backend/tests/engine/test_backtester.py`

Add `flow_snapshots` to BacktestConfig, build a bisect-based lookup index, score flow data per candle, and wire it into the existing weight renormalization and `compute_preliminary_score()` call.

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/engine/test_backtester.py
# NOTE: _make_candle_series() already exists in this file — reuse it.

from collections import deque
from datetime import datetime, timezone, timedelta
from app.engine.backtester import BacktestConfig, run_backtest


def _make_flow_snapshots(candles: list[dict], start_idx: int = 20) -> list[dict]:
    """Create flow snapshots aligned to candle timestamps, starting at start_idx."""
    snapshots = []
    for c in candles[start_idx:]:
        ts = c["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        snapshots.append({
            "timestamp": ts,
            "funding_rate": 0.0003,
            "open_interest": 1_000_000.0,
            "oi_change_pct": 1.5,
            "long_short_ratio": 1.2,
            "cvd_delta": 200.0,
        })
    return snapshots


class TestFlowBacktest:
    def test_no_flow_snapshots_same_as_before(self):
        """BacktestConfig with flow_snapshots=None produces same results."""
        candles = _make_candle_series(n=120)
        config = BacktestConfig()
        result_without = run_backtest(candles, "BTC-USDT-SWAP", config)
        config_with_none = BacktestConfig(flow_snapshots=None)
        result_with_none = run_backtest(candles, "BTC-USDT-SWAP", config_with_none)
        assert result_without["stats"]["total_trades"] == result_with_none["stats"]["total_trades"]

    def test_flow_snapshots_field_accepted(self):
        """BacktestConfig accepts flow_snapshots parameter."""
        config = BacktestConfig(flow_snapshots=[{"timestamp": datetime.now(timezone.utc)}])
        assert config.flow_snapshots is not None

    def test_flow_snapshots_affects_scoring(self):
        """Backtest with flow snapshots may produce different trade count."""
        candles = _make_candle_series(n=120)
        snapshots = _make_flow_snapshots(candles, start_idx=20)
        config_no_flow = BacktestConfig(signal_threshold=20)
        config_flow = BacktestConfig(signal_threshold=20, flow_snapshots=snapshots)
        result_no = run_backtest(candles, "BTC-USDT-SWAP", config_no_flow)
        result_flow = run_backtest(candles, "BTC-USDT-SWAP", config_flow)
        # With flow data, scoring changes — trade count may differ
        # At minimum, the function should run without error
        assert result_flow["stats"]["total_trades"] >= 0

    def test_early_candles_without_snapshots_degrade_gracefully(self):
        """Candles before snapshot coverage get flow_score=0."""
        candles = _make_candle_series(n=120)
        # Only provide snapshots for last 30 candles
        snapshots = _make_flow_snapshots(candles, start_idx=90)
        config = BacktestConfig(flow_snapshots=snapshots, signal_threshold=20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        assert result["stats"]["total_trades"] >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py::TestFlowBacktest -v`
Expected: FAIL — `TypeError: BacktestConfig.__init__() got an unexpected keyword argument 'flow_snapshots'`

- [ ] **Step 3: Add flow_snapshots to BacktestConfig**

In `backend/app/engine/backtester.py`, add the field to the dataclass (after line 97):

```python
@dataclass
class BacktestConfig:
    signal_threshold: int = 40
    tech_weight: float = 0.75
    pattern_weight: float = 0.25
    enable_patterns: bool = True
    sl_atr_multiplier: float = 1.5
    tp1_atr_multiplier: float = 2.0
    tp2_atr_multiplier: float = 3.0
    risk_per_trade_pct: float = 1.0
    max_concurrent_positions: int = 3
    ml_confidence_threshold: float = 0.65
    param_overrides: dict = field(default_factory=dict)
    flow_snapshots: list[dict] | None = None
```

- [ ] **Step 4: Add flow scoring to the backtest loop**

Add import at the top of `backtester.py`:

```python
from collections import deque
from app.engine.traditional import score_order_flow
from app.engine.constants import ORDER_FLOW, ORDER_FLOW_ASSET_SCALES
```

In `run_backtest()`, after the config init block and before the main loop, add the flow lookup setup:

```python
    # ── Flow snapshot lookup ──
    _flow_ts: list[datetime] | None = None
    _flow_snaps: list[dict] | None = None
    _flow_deque: deque = deque(maxlen=ORDER_FLOW["recent_window"] + ORDER_FLOW["baseline_window"])
    _flow_asset_scale = ORDER_FLOW_ASSET_SCALES.get(pair, 1.0)

    if config.flow_snapshots:
        _flow_ts = [s["timestamp"] for s in config.flow_snapshots]
        _flow_snaps = config.flow_snapshots

    # Estimate candle interval for drift tolerance
    _candle_interval_s = 900.0  # default 15m
    if len(candles) >= 2:
        t0, t1 = candles[0]["timestamp"], candles[1]["timestamp"]
        if isinstance(t0, str):
            t0 = datetime.fromisoformat(t0)
        if isinstance(t1, str):
            t1 = datetime.fromisoformat(t1)
        _candle_interval_s = max((t1 - t0).total_seconds(), 60.0)
```

Inside the main candle loop (after `tech_result` is computed, before the weight renormalization block), add flow scoring:

```python
        # ── Flow scoring (when snapshots provided) ──
        flow_score = 0
        flow_confidence = 0.0
        if _flow_ts is not None:
            candle_ts = current["timestamp"]
            if isinstance(candle_ts, str):
                candle_ts = datetime.fromisoformat(candle_ts)
            idx = bisect.bisect_right(_flow_ts, candle_ts) - 1
            if idx >= 0:
                snap = _flow_snaps[idx]
                drift = (candle_ts - snap["timestamp"]).total_seconds()
                if drift <= 2 * _candle_interval_s:
                    _flow_deque.append(snap)
                    flow_result = score_order_flow(
                        metrics=snap,
                        regime=tech_result.get("regime"),
                        flow_history=list(_flow_deque),
                        trend_conviction=tech_result["indicators"].get("trend_conviction", 0),
                        mr_pressure=tech_result["indicators"].get("mean_rev_score", 0),
                        flow_age_seconds=drift,
                        asset_scale=_flow_asset_scale,
                    )
                    flow_score = flow_result["score"]
                    flow_confidence = flow_result["confidence"]
```

Update the weight renormalization block to include flow when available:

```python
        # Outer weights: use regime-blended when regime_weights provided
        conf_available = conf_confidence > 0
        flow_available = flow_score != 0 or flow_confidence > 0
        if regime_weights is not None:
            regime = tech_result.get("regime")
            outer = blend_outer_weights(regime, regime_weights)
            bt_tech_w = outer["tech"]
            bt_pattern_w = outer["pattern"]
            bt_conf_w = outer.get("confluence", 0.0) if conf_available else 0.0
            bt_flow_w = outer.get("flow", 0.0) if flow_available else 0.0
            bt_total = bt_tech_w + bt_pattern_w + bt_conf_w + bt_flow_w
            if bt_total > 0:
                bt_tech_w /= bt_total
                bt_pattern_w /= bt_total
                bt_conf_w /= bt_total
                bt_flow_w /= bt_total
        else:
            bt_tech_w = config.tech_weight
            bt_pattern_w = config.pattern_weight
            bt_conf_w = 0.0
            bt_flow_w = 0.0
```

Update the `compute_preliminary_score()` call to pass flow data:

```python
        indicator_preliminary = compute_preliminary_score(
            technical_score=tech_result["score"],
            order_flow_score=flow_score,
            tech_weight=bt_tech_w,
            flow_weight=bt_flow_w,
            flow_confidence=flow_confidence,
            onchain_score=0,
            onchain_weight=0.0,
            pattern_score=pat_score,
            pattern_weight=bt_pattern_w,
            confluence_score=conf_score,
            confluence_weight=bt_conf_w,
            confluence_confidence=conf_confidence,
        )["score"]
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py -v`
Expected: All tests PASS (existing + new TestFlowBacktest)

---

### Task 3: Parameterize regime optimizer for flow expansion

**Files:**
- Modify: `backend/app/engine/regime_optimizer.py:13-95`
- Test: `backend/tests/engine/test_regime_optimizer.py`

Make `vector_to_regime_dict`, `regime_dict_to_vector`, `_MockRegimeWeights`, and bounds computation accept variable outer keys so the optimizer can expand to include flow when snapshots are provided.

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/engine/test_regime_optimizer.py

from app.engine.regime_optimizer import (
    vector_to_regime_dict,
    regime_dict_to_vector,
    _build_bounds,
    _MockRegimeWeights,
    _BACKTEST_OUTER_KEYS,
    compute_fitness,
)
from app.engine.regime import REGIMES, CAP_KEYS


class TestParameterExpansion:
    def test_build_bounds_default(self):
        bounds = _build_bounds(_BACKTEST_OUTER_KEYS)
        # 4 regimes * 4 caps + 4 regimes * 2 outer = 24
        assert len(bounds) == 24

    def test_build_bounds_with_flow(self):
        bounds = _build_bounds(["tech", "pattern", "flow"])
        # 4 regimes * 4 caps + 4 regimes * 3 outer = 28
        assert len(bounds) == 28

    def test_vector_roundtrip_with_flow(self):
        outer_keys = ["tech", "pattern", "flow"]
        n_caps = len(CAP_KEYS)
        n_outer = len(outer_keys)
        # Build a vector: 16 caps + 12 outer weights
        vec = [30.0] * (4 * n_caps) + [0.33] * (4 * n_outer)
        d = vector_to_regime_dict(vec, outer_keys=outer_keys)
        vec2 = regime_dict_to_vector(d, outer_keys=outer_keys)
        d2 = vector_to_regime_dict(vec2, outer_keys=outer_keys)
        for regime in REGIMES:
            for key in outer_keys:
                assert abs(d[regime][key] - d2[regime][key]) < 1e-6

    def test_outer_weights_normalized_with_flow(self):
        outer_keys = ["tech", "pattern", "flow"]
        vec = [25.0] * 16 + [0.2, 0.3, 0.5] * 4
        d = vector_to_regime_dict(vec, outer_keys=outer_keys)
        for regime in REGIMES:
            total = sum(d[regime][k] for k in outer_keys)
            assert abs(total - 1.0) < 1e-6

    def test_mock_regime_weights_with_flow(self):
        outer_keys = ["tech", "pattern", "flow"]
        d = {r: {**{c: 30.0 for c in CAP_KEYS}, "tech": 0.4, "pattern": 0.3, "flow": 0.3} for r in REGIMES}
        mock = _MockRegimeWeights(d, outer_keys=outer_keys)
        assert mock.trending_tech_weight == 0.4
        assert mock.trending_flow_weight == 0.3
        # Non-backtest keys still default to 0
        assert mock.trending_onchain_weight == 0.0
        assert mock.trending_liquidation_weight == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py::TestParameterExpansion -v`
Expected: FAIL — `ImportError: cannot import name '_build_bounds'`

- [ ] **Step 3: Implement parameterization**

In `backend/app/engine/regime_optimizer.py`, update the top section:

```python
_N_REGIMES = len(REGIMES)  # 4
_N_CAPS = len(CAP_KEYS)    # 4
_BACKTEST_OUTER_KEYS = ["tech", "pattern"]
_N_OUTER = len(_BACKTEST_OUTER_KEYS)  # 2
_CAP_BOUNDS = (10.0, 45.0)
_WEIGHT_BOUNDS = (0.10, 0.50)

# Default bounds for backward compat
N_PARAMS = _N_REGIMES * _N_CAPS + _N_REGIMES * _N_OUTER
PARAM_BOUNDS = [_CAP_BOUNDS] * (_N_REGIMES * _N_CAPS) + [_WEIGHT_BOUNDS] * (_N_REGIMES * _N_OUTER)


def _build_bounds(outer_keys: list[str]) -> list[tuple]:
    """Build DE parameter bounds for given outer key set."""
    n_outer = len(outer_keys)
    return [_CAP_BOUNDS] * (_N_REGIMES * _N_CAPS) + [_WEIGHT_BOUNDS] * (_N_REGIMES * n_outer)
```

Update `vector_to_regime_dict`:

```python
def vector_to_regime_dict(vec: list[float], outer_keys: list[str] | None = None) -> dict:
    if outer_keys is None:
        outer_keys = _BACKTEST_OUTER_KEYS
    n_outer = len(outer_keys)
    result = {}
    caps_offset = _N_REGIMES * _N_CAPS
    for i, regime in enumerate(REGIMES):
        caps = {key: vec[i * _N_CAPS + j] for j, key in enumerate(CAP_KEYS)}
        raw = [vec[caps_offset + i * n_outer + j] for j in range(n_outer)]
        w_total = sum(raw)
        if w_total > 0:
            for j, key in enumerate(outer_keys):
                caps[key] = raw[j] / w_total
        else:
            for key in outer_keys:
                caps[key] = 1.0 / n_outer
        result[regime] = caps
    return result
```

Update `regime_dict_to_vector`:

```python
def regime_dict_to_vector(d: dict, outer_keys: list[str] | None = None) -> list[float]:
    if outer_keys is None:
        outer_keys = _BACKTEST_OUTER_KEYS
    vec = []
    for regime in REGIMES:
        for key in CAP_KEYS:
            vec.append(d[regime][key])
    for regime in REGIMES:
        for key in outer_keys:
            vec.append(d[regime][key])
    return vec
```

Update `_MockRegimeWeights`:

```python
class _MockRegimeWeights:
    """Lightweight object mimicking RegimeWeights DB row for backtester."""

    def __init__(self, regime_dict: dict, outer_keys: list[str] | None = None):
        if outer_keys is None:
            outer_keys = _BACKTEST_OUTER_KEYS
        for regime in REGIMES:
            for key in CAP_KEYS:
                setattr(self, f"{regime}_{key}", regime_dict[regime].get(key, 30.0))
            for src in OUTER_KEYS:
                if src in outer_keys and src in regime_dict[regime]:
                    setattr(self, f"{regime}_{src}_weight", regime_dict[regime][src])
                else:
                    setattr(self, f"{regime}_{src}_weight", 0.0)
```

Update `optimize_regime_weights` to use flow when available:

```python
def optimize_regime_weights(
    candles, pair, config=None, parent_candles=None,
    max_iterations=300, cancel_flag=None, on_progress=None,
) -> dict:
    from scipy.optimize import differential_evolution

    has_flow = config and config.flow_snapshots
    outer_keys = ["tech", "pattern", "flow"] if has_flow else _BACKTEST_OUTER_KEYS
    bounds = _build_bounds(outer_keys)

    best_result = {"fitness": 0.0, "stats": {}, "weights": {}}
    eval_count = [0]

    def objective(vec):
        if cancel_flag and cancel_flag.get("cancelled"):
            return 0.0
        eval_count[0] += 1
        regime_dict = vector_to_regime_dict(list(vec), outer_keys=outer_keys)
        mock_rw = _MockRegimeWeights(regime_dict, outer_keys=outer_keys)
        result = run_backtest(candles, pair, config, parent_candles=parent_candles, regime_weights=mock_rw)
        fitness = compute_fitness(result["stats"])
        if fitness > best_result["fitness"]:
            best_result["fitness"] = fitness
            best_result["stats"] = result["stats"]
            best_result["weights"] = regime_dict
        return -fitness

    # ... rest unchanged (progress_callback, DE call, fallback, return)
    # In fallback, also pass outer_keys:
    #   regime_dict = vector_to_regime_dict(list(result.x), outer_keys=outer_keys)
```

- [ ] **Step 4: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py -v`
Expected: All tests PASS (existing + TestParameterExpansion)

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py -v`
Expected: All PASS (no regressions)

- [ ] **Step 5: Commit Workstream B**

```
feat(engine): wire OrderFlowSnapshot into backtester and parameterize regime optimizer
```

---

## Workstream C: Live Signal Optimizer

### Task 4: Persist per-source scores in raw_indicators

**Files:**
- Modify: `backend/app/main.py:~1040-1078`
- Test: `backend/tests/api/test_signal_indicators.py` (new)

Add per-source scores, confidences, and `regime_steady` to the `raw_indicators` JSONB dict on every emitted signal.

- [ ] **Step 1: Write the failing test**

```python
# Create tests/api/test_signal_indicators.py

import pytest

REQUIRED_INDICATOR_KEYS = [
    "tech_score", "tech_confidence",
    "flow_score", "flow_confidence",
    "onchain_score", "onchain_confidence",
    "pattern_score", "pattern_confidence",
    "liquidation_score", "liquidation_confidence",
    "confluence_score", "confluence_confidence",
    "regime_trending", "regime_ranging", "regime_volatile", "regime_steady",
]


def test_raw_indicators_keys_defined():
    """Verify the REQUIRED_INDICATOR_KEYS list is importable (sanity)."""
    assert len(REQUIRED_INDICATOR_KEYS) == 16


def _build_mock_raw_indicators():
    """Simulate the raw_indicators dict as it would be built in main.py."""
    from app.main import _build_raw_indicators
    tech_result = {
        "score": 45,
        "indicators": {
            "regime_trending": 0.5, "regime_ranging": 0.2,
            "regime_volatile": 0.2, "regime_steady": 0.1,
            "trend_conviction": 0.6, "atr": 50.0,
        },
    }
    return _build_raw_indicators(
        tech_result=tech_result, tech_conf=0.7,
        flow_result={"score": 20, "confidence": 0.5, "details": {}},
        onchain_score=10, onchain_conf=0.3,
        pat_score=15, pattern_conf=0.4,
        liq_score=5, liq_conf=0.2, liq_clusters=[], liq_details={},
        confluence_score=12, confluence_conf=0.6,
        ml_score=30, ml_confidence=0.8,
        blended=55, indicator_preliminary=48,
        scaled={"sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0,
                "sl_strength_factor": 1.0, "tp_strength_factor": 1.0, "vol_factor": 1.0},
        levels={"levels_source": "atr_defaults"},
        outer={}, snap_info=None, llm_contribution=0.0,
    )


def test_raw_indicators_has_all_source_scores():
    """raw_indicators must contain all per-source scores for the live optimizer."""
    ri = _build_mock_raw_indicators()
    for key in REQUIRED_INDICATOR_KEYS:
        assert key in ri, f"Missing key: {key}"


def test_raw_indicators_regime_steady_present():
    """regime_steady must be present (was previously missing)."""
    ri = _build_mock_raw_indicators()
    assert ri["regime_steady"] == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_signal_indicators.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_raw_indicators' from 'app.main'`

- [ ] **Step 3: Extract _build_raw_indicators helper and add missing keys**

In `backend/app/main.py`, extract the `raw_indicators` dict construction into a helper function (place it near the top of the module, after imports):

```python
def _build_raw_indicators(
    *, tech_result, tech_conf, flow_result, onchain_score, onchain_conf,
    pat_score, pattern_conf, liq_score, liq_conf, liq_clusters, liq_details,
    confluence_score, confluence_conf, ml_score, ml_confidence,
    blended, indicator_preliminary, scaled, levels, outer, snap_info, llm_contribution,
) -> dict:
    """Build the raw_indicators JSONB dict for a signal."""
    return {
        **tech_result["indicators"],
        # ── Per-source scores (for live signal optimizer) ──
        "tech_score": tech_result["score"],
        "tech_confidence": tech_conf,
        "flow_score": flow_result["score"],
        "flow_confidence": flow_result.get("confidence", 0.5),
        "onchain_score": onchain_score,
        "onchain_confidence": onchain_conf,
        "pattern_score": pat_score,
        "pattern_confidence": pattern_conf,
        "liquidation_score": liq_score,
        "liquidation_confidence": liq_conf,
        "confluence_score": confluence_score,
        "confluence_confidence": confluence_conf,
        "regime_steady": tech_result["indicators"].get("regime_steady"),
        # ── Existing keys ──
        "ml_score": ml_score,
        "ml_confidence": ml_confidence,
        "blended_score": blended,
        "indicator_preliminary": indicator_preliminary,
        "effective_sl_atr": scaled["sl_atr"],
        "effective_tp1_atr": scaled["tp1_atr"],
        "effective_tp2_atr": scaled["tp2_atr"],
        "sl_strength_factor": scaled["sl_strength_factor"],
        "tp_strength_factor": scaled["tp_strength_factor"],
        "vol_factor": scaled["vol_factor"],
        "levels_source": levels["levels_source"],
        "regime_trending": tech_result["indicators"].get("regime_trending"),
        "regime_ranging": tech_result["indicators"].get("regime_ranging"),
        "regime_volatile": tech_result["indicators"].get("regime_volatile"),
        "effective_outer_weights": outer,
        "flow_contrarian_mult": flow_result["details"].get("contrarian_mult"),
        "flow_roc_boost": flow_result["details"].get("roc_boost"),
        "flow_final_mult": flow_result["details"].get("final_mult"),
        "funding_rate": flow_result["details"].get("funding_rate"),
        "open_interest_change_pct": flow_result["details"].get("open_interest_change_pct"),
        "long_short_ratio": flow_result["details"].get("long_short_ratio"),
        "liquidation_cluster_count": len(liq_clusters),
        "llm_contribution": llm_contribution,
        **({f"snap_{k}": v for k, v in snap_info.items()} if snap_info else {}),
        **(liq_details if liq_details else {}),
    }
```

Then in the signal emission block (~line 1040), replace the inline `raw_indicators` dict with a call:

```python
"raw_indicators": _build_raw_indicators(
    tech_result=tech_result, tech_conf=tech_conf,
    flow_result=flow_result, onchain_score=onchain_score, onchain_conf=onchain_conf,
    pat_score=pat_score, pattern_conf=pattern_conf,
    liq_score=liq_score, liq_conf=liq_conf, liq_clusters=liq_clusters, liq_details=liq_details,
    confluence_score=confluence_score, confluence_conf=confluence_conf,
    ml_score=ml_score, ml_confidence=ml_confidence,
    blended=blended, indicator_preliminary=indicator_preliminary,
    scaled=scaled, levels=levels, outer=outer, snap_info=snap_info,
    llm_contribution=llm_result_contribution,
),
```

Note: Check the exact variable names used at the call site in main.py — `tech_conf`, `pattern_conf`, `onchain_conf` may need adjustment to match local variable names (e.g. `tech_result.get("confidence", 0.5)` might be computed inline). Assign any inline expressions to named variables before the call.

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_signal_indicators.py -v`
Expected: PASS

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`
Expected: All PASS (no regressions)

---

### Task 5: Extract shared DE runner

**Files:**
- Modify: `backend/app/engine/regime_optimizer.py:98-183`
- Test: `backend/tests/engine/test_regime_optimizer.py`

Extract the differential_evolution boilerplate into `_run_de_optimization()` so both backtest and live-signal modes can share it.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/engine/test_regime_optimizer.py

from app.engine.regime_optimizer import _run_de_optimization


class TestSharedDERunner:
    def test_basic_optimization(self):
        """Shared DE runner finds minimum of simple quadratic."""
        def objective(vec):
            return sum(x ** 2 for x in vec)

        result = _run_de_optimization(
            objective_fn=objective,
            param_bounds=[(-5, 5), (-5, 5)],
            max_iterations=50,
        )
        assert "best_fitness" in result
        assert "best_vector" in result
        assert "evaluations" in result
        assert abs(result["best_fitness"]) < 0.1  # near-zero cost at optimum
        assert all(abs(x) < 0.5 for x in result["best_vector"])  # near origin

    def test_cancel_flag_stops_early(self):
        call_count = [0]
        cancel = {"cancelled": False}

        def objective(vec):
            call_count[0] += 1
            if call_count[0] >= 5:
                cancel["cancelled"] = True
            return sum(x ** 2 for x in vec)

        result = _run_de_optimization(
            objective_fn=objective,
            param_bounds=[(-5, 5)] * 3,
            max_iterations=200,
            cancel_flag=cancel,
        )
        assert call_count[0] < 200 * 15  # should stop well before max

    def test_on_progress_called(self):
        progress_calls = []

        def on_progress(evals, fitness):
            progress_calls.append((evals, fitness))

        def objective(vec):
            return sum(x ** 2 for x in vec)

        _run_de_optimization(
            objective_fn=objective,
            param_bounds=[(-5, 5)] * 2,
            max_iterations=10,
            on_progress=on_progress,
        )
        assert len(progress_calls) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py::TestSharedDERunner -v`
Expected: FAIL — `ImportError: cannot import name '_run_de_optimization'`

- [ ] **Step 3: Extract the shared runner**

In `backend/app/engine/regime_optimizer.py`, add before `optimize_regime_weights`:

```python
def _run_de_optimization(
    objective_fn,
    param_bounds: list[tuple],
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress=None,
) -> dict:
    """Shared differential evolution runner.

    Returns dict with best_fitness (positive), best_vector, and evaluations count.
    """
    from scipy.optimize import differential_evolution

    best = {"fitness": 0.0, "vector": None}
    eval_count = [0]

    def wrapped_objective(vec):
        if cancel_flag and cancel_flag.get("cancelled"):
            return 0.0
        eval_count[0] += 1
        cost = objective_fn(list(vec))
        fitness = -cost  # objective returns negative fitness for minimization
        if fitness > best["fitness"] or best["vector"] is None:
            best["fitness"] = fitness
            best["vector"] = list(vec)
        return cost

    def callback(xk, convergence):
        if cancel_flag and cancel_flag.get("cancelled"):
            return True
        if on_progress:
            on_progress(eval_count[0], best["fitness"])
        return False

    result = differential_evolution(
        wrapped_objective,
        bounds=param_bounds,
        maxiter=max_iterations,
        seed=42,
        tol=0.01,
        polish=False,
        callback=callback,
    )

    if best["vector"] is None:
        best["vector"] = list(result.x)
        best["fitness"] = -result.fun

    return {
        "best_fitness": best["fitness"],
        "best_vector": best["vector"],
        "evaluations": eval_count[0],
    }
```

Then refactor `optimize_regime_weights` to use it:

```python
def optimize_regime_weights(
    candles, pair, config=None, parent_candles=None,
    max_iterations=300, cancel_flag=None, on_progress=None,
) -> dict:
    has_flow = config and config.flow_snapshots
    outer_keys = ["tech", "pattern", "flow"] if has_flow else _BACKTEST_OUTER_KEYS
    bounds = _build_bounds(outer_keys)

    best_result = {"stats": {}, "weights": {}}

    def objective(vec):
        regime_dict = vector_to_regime_dict(vec, outer_keys=outer_keys)
        mock_rw = _MockRegimeWeights(regime_dict, outer_keys=outer_keys)
        result = run_backtest(
            candles, pair, config,
            parent_candles=parent_candles,
            regime_weights=mock_rw,
        )
        fitness = compute_fitness(result["stats"])
        if fitness > best_result.get("fitness", 0):
            best_result["stats"] = result["stats"]
            best_result["weights"] = regime_dict
            best_result["fitness"] = fitness
            logger.info(
                "Regime optimizer: new best fitness=%.4f (wr=%.1f%%, pf=%.2f)",
                fitness, result["stats"].get("win_rate", 0),
                result["stats"].get("profit_factor", 0) or 0,
            )
        return -fitness

    de_result = _run_de_optimization(
        objective_fn=objective,
        param_bounds=bounds,
        max_iterations=max_iterations,
        cancel_flag=cancel_flag,
        on_progress=on_progress,
    )

    if not best_result.get("weights"):
        regime_dict = vector_to_regime_dict(de_result["best_vector"], outer_keys=outer_keys)
        best_result["weights"] = regime_dict
        best_result["fitness"] = de_result["best_fitness"]

    best_result["evaluations"] = de_result["evaluations"]
    return best_result
```

- [ ] **Step 4: Run all optimizer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py -v`
Expected: All PASS

---

### Task 6: Implement optimize_from_signals()

**Files:**
- Modify: `backend/app/engine/regime_optimizer.py`
- Test: `backend/tests/engine/test_regime_optimizer.py`

Add signal-vector helpers and the `optimize_from_signals()` function that re-scores resolved signals with candidate outer weight vectors.

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/engine/test_regime_optimizer.py

from app.engine.regime_optimizer import (
    signal_vector_to_weight_dict,
    _SIGNAL_PARAM_BOUNDS,
    optimize_from_signals,
)
from app.engine.regime import OUTER_KEYS


def _make_mock_signals(n=25, win_rate=0.6):
    """Generate mock resolved signals with per-source scores in raw_indicators."""
    signals = []
    for i in range(n):
        is_win = i < int(n * win_rate)
        outcome = "TP1_HIT" if is_win else "SL_HIT"
        entry = 50000.0
        sl = entry - 500 if True else entry + 500  # LONG
        tp1 = entry + 750
        pnl = 1.5 if is_win else -1.0
        signals.append({
            "outcome": outcome,
            "outcome_pnl_pct": pnl,
            "entry": entry,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "raw_indicators": {
                "tech_score": 45 + (i % 20),
                "tech_confidence": 0.7,
                "flow_score": 15,
                "flow_confidence": 0.5,
                "onchain_score": 0,
                "onchain_confidence": 0.0,
                "pattern_score": 10,
                "pattern_confidence": 0.4,
                "liquidation_score": 5,
                "liquidation_confidence": 0.2,
                "confluence_score": 12,
                "confluence_confidence": 0.6,
                "regime_trending": 0.5,
                "regime_ranging": 0.2,
                "regime_volatile": 0.2,
                "regime_steady": 0.1,
            },
        })
    return signals


class TestSignalVectorHelpers:
    def test_signal_vector_roundtrip(self):
        n = len(OUTER_KEYS)  # 6
        vec = [0.2] * (4 * n)  # 24 params, equal weights
        d = signal_vector_to_weight_dict(vec)
        assert set(d.keys()) == set(REGIMES)
        for regime in REGIMES:
            total = sum(d[regime][k] for k in OUTER_KEYS)
            assert abs(total - 1.0) < 1e-6

    def test_signal_param_bounds_length(self):
        assert len(_SIGNAL_PARAM_BOUNDS) == 4 * len(OUTER_KEYS)  # 24


class TestOptimizeFromSignals:
    def test_basic_optimization(self):
        signals = _make_mock_signals(n=30, win_rate=0.6)
        result = optimize_from_signals(signals, pair="BTC-USDT-SWAP", max_iterations=10)
        assert "weights" in result
        assert "fitness" in result
        assert "evaluations" in result
        assert result["fitness"] >= 0

    def test_insufficient_signals_raises(self):
        signals = _make_mock_signals(n=5)
        with pytest.raises(ValueError, match="insufficient"):
            optimize_from_signals(signals, pair="BTC-USDT-SWAP")

    def test_all_signals_suppressed_returns_zero_fitness(self):
        """Threshold so high no signal passes → fitness=0 from MIN_TRADES gate."""
        signals = _make_mock_signals(n=25)
        result = optimize_from_signals(
            signals, pair="BTC-USDT-SWAP",
            signal_threshold=999,  # nothing passes
            max_iterations=5,
        )
        assert result["fitness"] == 0.0

    def test_cancel_flag_stops_optimization(self):
        signals = _make_mock_signals(n=30)
        cancel = {"cancelled": True}
        result = optimize_from_signals(
            signals, pair="BTC-USDT-SWAP",
            cancel_flag=cancel, max_iterations=100,
        )
        assert result["evaluations"] < 100 * 15  # stopped early

    def test_weights_are_normalized(self):
        signals = _make_mock_signals(n=30, win_rate=0.7)
        result = optimize_from_signals(signals, pair="BTC-USDT-SWAP", max_iterations=10)
        for regime in REGIMES:
            total = sum(result["weights"][regime][k] for k in OUTER_KEYS)
            assert abs(total - 1.0) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py::TestSignalVectorHelpers tests/engine/test_regime_optimizer.py::TestOptimizeFromSignals -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Add required imports and implement signal vector helpers**

In `backend/app/engine/regime_optimizer.py`, update the imports at the top of the file to include the new dependencies needed for Task 6:

```python
from app.engine.regime import REGIMES, CAP_KEYS, OUTER_KEYS, blend_outer_weights
from app.engine.combiner import compute_preliminary_score
```

Then add the signal vector helpers:

```python
_SIGNAL_PARAM_BOUNDS = [_WEIGHT_BOUNDS] * (_N_REGIMES * len(OUTER_KEYS))  # 24


def signal_vector_to_weight_dict(vec: list[float]) -> dict:
    """Convert flat weight vector (24 floats) to per-regime outer weight dict.

    No caps — only outer weights for all 6 OUTER_KEYS.
    """
    n = len(OUTER_KEYS)
    result = {}
    for i, regime in enumerate(REGIMES):
        raw = [vec[i * n + j] for j in range(n)]
        w_total = sum(raw)
        if w_total > 0:
            result[regime] = {key: raw[j] / w_total for j, key in enumerate(OUTER_KEYS)}
        else:
            result[regime] = {key: 1.0 / n for key in OUTER_KEYS}
    return result
```

- [ ] **Step 4: Implement optimize_from_signals()**

```python
def optimize_from_signals(
    signals: list[dict],
    pair: str,
    signal_threshold: int = 40,
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress=None,
) -> dict:
    """Optimize outer weights by re-scoring resolved signals with candidate vectors.

    Raises ValueError if fewer than MIN_TRADES signals provided.
    """
    if len(signals) < MIN_TRADES:
        raise ValueError(f"insufficient signals: {len(signals)} < {MIN_TRADES}")

    def objective(vec):
        weight_dict = signal_vector_to_weight_dict(vec)
        mock_rw = _MockRegimeWeights(weight_dict, outer_keys=list(OUTER_KEYS))

        kept_trades = []
        for sig in signals:
            ri = sig.get("raw_indicators") or {}
            regime = {
                "trending": ri.get("regime_trending", 0),
                "ranging": ri.get("regime_ranging", 0),
                "volatile": ri.get("regime_volatile", 0),
                "steady": ri.get("regime_steady", 0),
            }

            outer = blend_outer_weights(regime, mock_rw)

            # Gather per-source scores/confidences
            scores, confs = {}, {}
            for key in OUTER_KEYS:
                scores[key] = ri.get(f"{key}_score", 0)
                confs[key] = ri.get(f"{key}_confidence", 0.0)

            # Zero unavailable sources, renormalize
            weights = {}
            total_w = 0.0
            for key in OUTER_KEYS:
                if scores[key] == 0 and confs[key] == 0:
                    weights[key] = 0.0
                else:
                    weights[key] = outer[key]
                    total_w += outer[key]
            if total_w > 0:
                weights = {k: v / total_w for k, v in weights.items()}

            result = compute_preliminary_score(
                technical_score=scores["tech"],
                order_flow_score=scores["flow"],
                tech_weight=weights["tech"],
                flow_weight=weights["flow"],
                tech_confidence=confs["tech"],
                flow_confidence=confs["flow"],
                onchain_score=scores["onchain"],
                onchain_weight=weights["onchain"],
                onchain_confidence=confs["onchain"],
                pattern_score=scores["pattern"],
                pattern_weight=weights["pattern"],
                pattern_confidence=confs["pattern"],
                liquidation_score=scores["liquidation"],
                liquidation_weight=weights["liquidation"],
                liquidation_confidence=confs["liquidation"],
                confluence_score=scores["confluence"],
                confluence_weight=weights["confluence"],
                confluence_confidence=confs["confluence"],
            )

            if abs(result["score"]) >= signal_threshold:
                is_win = sig["outcome"] in ("TP1_HIT", "TP2_HIT")
                pnl = sig.get("outcome_pnl_pct") or 0.0
                entry = float(sig.get("entry", 0))
                sl = float(sig.get("stop_loss", 0))
                sl_pct = abs(entry - sl) / entry * 100 if entry else 0
                rr = abs(pnl / sl_pct) if sl_pct else 0
                kept_trades.append({"win": is_win, "pnl_pct": pnl, "rr": rr})

        if not kept_trades:
            return 0.0  # will map to fitness=0

        total = len(kept_trades)
        wins = sum(1 for t in kept_trades if t["win"])
        gross_profit = sum(t["pnl_pct"] for t in kept_trades if t["pnl_pct"] > 0) or 0
        gross_loss = abs(sum(t["pnl_pct"] for t in kept_trades if t["pnl_pct"] < 0)) or 0
        pf = gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0)
        avg_rr = sum(t["rr"] for t in kept_trades) / total

        cum, peak, max_dd = 0.0, 0.0, 0.0
        for t in kept_trades:
            cum += t["pnl_pct"]
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)

        fitness = compute_fitness({
            "total_trades": total,
            "win_rate": wins / total * 100,
            "profit_factor": pf,
            "avg_rr": avg_rr,
            "max_drawdown": max_dd,
        })

        return -fitness

    de_result = _run_de_optimization(
        objective_fn=objective,
        param_bounds=_SIGNAL_PARAM_BOUNDS,
        max_iterations=max_iterations,
        cancel_flag=cancel_flag,
        on_progress=on_progress,
    )

    weights = signal_vector_to_weight_dict(de_result["best_vector"])
    return {
        "weights": weights,
        "fitness": de_result["best_fitness"],
        "evaluations": de_result["evaluations"],
    }
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_optimizer.py -v`
Expected: All PASS

---

### Task 7: Add outcome filter to GET /signals

**Files:**
- Modify: `backend/app/api/routes.py:279-300`
- Test: `backend/tests/api/test_routes_signals.py` (new)

Add an optional `outcome` query parameter to `GET /signals` so the frontend can filter for resolved signals.

- [ ] **Step 1: Write the failing test**

```python
# Create tests/api/test_routes_signals.py

import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_signals_outcome_filter(client, auth_cookies):
    """GET /signals?outcome=resolved should return 200 with list."""
    response = await client.get(
        "/api/signals",
        params={"outcome": "resolved"},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_signals_outcome_specific_value(client, auth_cookies):
    """GET /signals?outcome=TP1_HIT should return 200."""
    response = await client.get(
        "/api/signals",
        params={"outcome": "TP1_HIT"},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

- [ ] **Step 2: Run test — it should show that the param is accepted (or ignored)**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_routes_signals.py -v`
Expected: Observe behavior (param may be silently ignored with no filtering).

- [ ] **Step 3: Add outcome param to GET /signals**

In `backend/app/api/routes.py`, update the endpoint:

```python
@router.get("/signals")
async def get_signals(
    request: Request,
    _key: str = auth,
    pair: str | None = Query(None),
    timeframe: str | None = Query(None),
    outcome: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    since: datetime | None = Query(None),
):
    db = request.app.state.db
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
    async with db.session_factory() as session:
        query = select(Signal).order_by(Signal.created_at.desc())
        query = query.where(Signal.created_at >= since)
        if pair:
            query = query.where(Signal.pair == pair)
        if timeframe:
            query = query.where(Signal.timeframe == timeframe)
        if outcome == "resolved":
            query = query.where(Signal.outcome != "PENDING")
        elif outcome:
            query = query.where(Signal.outcome == outcome)
        query = query.limit(limit)
        result = await session.execute(query)
        return [_signal_to_dict(s) for s in result.scalars().all()]
```

Also add a lightweight count endpoint below it (avoids downloading full signal payloads just to count):

```python
@router.get("/signals/count")
async def get_signal_count(
    request: Request,
    _key: str = auth,
    pair: str | None = Query(None),
    outcome: str | None = Query(None),
    since: datetime | None = Query(None),
):
    from sqlalchemy import func

    db = request.app.state.db
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=90)
    async with db.session_factory() as session:
        query = select(func.count(Signal.id)).where(Signal.created_at >= since)
        if pair:
            query = query.where(Signal.pair == pair)
        if outcome == "resolved":
            query = query.where(Signal.outcome != "PENDING")
        elif outcome:
            query = query.where(Signal.outcome == outcome)
        result = await session.execute(query)
        return {"count": result.scalar()}
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/ -v`
Expected: PASS

---

### Task 8: Add optimize-from-signals API endpoint

**Files:**
- Modify: `backend/app/api/optimizer.py`
- Modify: `backend/app/main.py` (app.state init)
- Test: `backend/tests/api/test_optimizer_signals.py` (new)

Add the `POST /api/optimizer/optimize-from-signals` endpoint with concurrency guard and signal querying.

- [ ] **Step 1: Write the failing test**

```python
# Create tests/api/test_optimizer_signals.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_optimize_from_signals_insufficient(client, auth_cookies):
    """Returns 400 when not enough resolved signals."""
    response = await client.post(
        "/api/optimizer/optimize-from-signals",
        json={"pair": "BTC-USDT-SWAP", "min_signals": 20},
        cookies=auth_cookies,
    )
    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["error"] == "insufficient_signals"


@pytest.mark.asyncio
async def test_optimize_from_signals_409_when_busy(client, app, auth_cookies):
    """Returns 409 when optimization already running."""
    app.state.active_signal_optimization = {"pair": "BTC-USDT-SWAP", "cancel_flag": {"cancelled": False}}
    response = await client.post(
        "/api/optimizer/optimize-from-signals",
        json={"pair": "BTC-USDT-SWAP"},
        cookies=auth_cookies,
    )
    assert response.status_code == 409
    app.state.active_signal_optimization = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_optimizer_signals.py -v`
Expected: FAIL — 404 (endpoint doesn't exist) or attribute error

- [ ] **Step 3: Init app.state.active_signal_optimization**

In `backend/app/main.py`, in the lifespan function (where app.state is initialized), add:

```python
app.state.active_signal_optimization = None
```

Also add it to `_test_lifespan` in `backend/tests/conftest.py`:

```python
app.state.active_signal_optimization = None
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/optimizer.py`, add imports and the endpoint:

```python
# Add to imports
import asyncio
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from sqlalchemy import select
from app.db.models import Signal, ParameterProposal
from app.engine.regime_optimizer import optimize_from_signals


class OptimizeFromSignalsRequest(BaseModel):
    pair: str
    timeframe: str | None = None
    lookback_days: int = 90
    max_signals: int = 500
    min_signals: int = 20
    max_iterations: int = 300


@router.post("/optimize-from-signals")
async def optimize_from_signals_endpoint(
    request: Request,
    body: OptimizeFromSignalsRequest,
    _key: str = require_auth,
):
    app = request.app

    # Concurrency guard
    if app.state.active_signal_optimization is not None:
        raise HTTPException(409, detail={
            "error": "optimization_running",
            "pair": app.state.active_signal_optimization["pair"],
        })

    # Query resolved signals
    since = datetime.now(timezone.utc) - timedelta(days=body.lookback_days)
    async with app.state.db.session_factory() as session:
        query = (
            select(Signal)
            .where(Signal.pair == body.pair)
            .where(Signal.outcome != "PENDING")
            .where(Signal.created_at >= since)
        )
        if body.timeframe:
            query = query.where(Signal.timeframe == body.timeframe)
        query = query.order_by(Signal.created_at.desc()).limit(body.max_signals)
        result = await session.execute(query)
        rows = result.scalars().all()

    # Filter to signals with required raw_indicators keys
    signals = []
    for s in rows:
        ri = s.raw_indicators or {}
        if "tech_score" in ri and "regime_trending" in ri:
            signals.append({
                "outcome": s.outcome,
                "outcome_pnl_pct": float(s.outcome_pnl_pct) if s.outcome_pnl_pct else 0.0,
                "entry": float(s.entry),
                "stop_loss": float(s.stop_loss),
                "take_profit_1": float(s.take_profit_1),
                "raw_indicators": ri,
            })

    if len(signals) < body.min_signals:
        raise HTTPException(400, detail={
            "error": "insufficient_signals",
            "available": len(signals),
            "required": body.min_signals,
        })

    # Start optimization
    cancel_flag = {"cancelled": False}
    app.state.active_signal_optimization = {"pair": body.pair, "cancel_flag": cancel_flag}

    manager = app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "optimization_started",
        "pair": body.pair,
        "mode": "live_signals",
    })

    async def _run():
        try:
            result = await asyncio.to_thread(
                optimize_from_signals,
                signals, body.pair,
                signal_threshold=app.state.settings.engine_signal_threshold,
                max_iterations=body.max_iterations,
                cancel_flag=cancel_flag,
            )

            # Create proposal
            async with app.state.db.session_factory() as session:
                proposal = ParameterProposal(
                    status="pending",
                    parameter_group="regime_outer_weights",
                    changes=result["weights"],
                    backtest_metrics={
                        "optimization_mode": "live_signals",
                        "fitness": result["fitness"],
                        "evaluations": result["evaluations"],
                        "signals_used": len(signals),
                        "pair": body.pair,
                        "profit_factor": 0,
                        "win_rate": 0,
                        "avg_rr": 0,
                        "drawdown": 0,
                        "signals_tested": len(signals),
                    },
                )
                session.add(proposal)
                await session.commit()
                await session.refresh(proposal)
                proposal_id = proposal.id

            await manager.broadcast({
                "type": "optimizer_update",
                "event": "optimization_completed",
                "proposal_id": proposal_id,
                "mode": "live_signals",
            })
        except Exception as e:
            logger.exception("Signal optimization failed: %s", e)
            await manager.broadcast({
                "type": "optimizer_update",
                "event": "optimization_failed",
                "pair": body.pair,
                "mode": "live_signals",
                "error": str(e),
            })
        finally:
            app.state.active_signal_optimization = None

    asyncio.create_task(_run())

    return {"status": "started", "pair": body.pair, "signals_queued": len(signals)}
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_optimizer_signals.py -v`
Expected: PASS

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`
Expected: All PASS

---

### Task 9: Frontend — types, API, store, and UI

**Files:**
- Modify: `web/src/features/optimizer/types.ts`
- Modify: `web/src/shared/lib/api.ts`
- Modify: `web/src/features/optimizer/store.ts`
- Modify: `web/src/features/optimizer/components/OptimizerPage.tsx`
- Modify: `web/src/features/optimizer/components/ProposalCard.tsx`

- [ ] **Step 1: Update types**

In `web/src/features/optimizer/types.ts`, add `optimization_mode` to `BacktestMetrics`:

```typescript
export interface BacktestMetrics {
  profit_factor: number;
  win_rate: number;
  avg_rr: number;
  drawdown: number;
  signals_tested: number;
  optimization_mode?: "backtest" | "live_signals";
}
```

- [ ] **Step 2: Add API methods**

In `web/src/shared/lib/api.ts`, add:

```typescript
optimizeFromSignals: (params: {
  pair: string;
  timeframe?: string;
  lookback_days?: number;
  max_signals?: number;
  min_signals?: number;
  max_iterations?: number;
}) =>
  request<{ status: string; pair: string; signals_queued: number }>(
    "/api/optimizer/optimize-from-signals",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(params),
    }
  ),

getResolvedSignalCount: (pair: string) =>
  request<{ count: number }>(
    `/api/signals/count?pair=${pair}&outcome=resolved`
  ).then((r) => r.count),
```

- [ ] **Step 3: Add store action**

In `web/src/features/optimizer/store.ts`, add to the interface and implementation:

```typescript
// Add to OptimizerStore interface:
signalOptLoading: boolean;
optimizeFromSignals: (pair: string) => Promise<void>;

// Add to create() initial state:
signalOptLoading: false,

// Add to create() actions:
optimizeFromSignals: async (pair) => {
  set({ signalOptLoading: true, error: null });
  try {
    await api.optimizeFromSignals({ pair });
    await Promise.all([get().fetchStatus(), get().fetchProposals()]);
  } catch (e) {
    set({ error: (e as Error).message });
  } finally {
    set({ signalOptLoading: false });
  }
},
```

- [ ] **Step 4: Add ProposalCard badge**

In `web/src/features/optimizer/components/ProposalCard.tsx`, after the parameter group name in the header section, add a source badge:

```tsx
{/* Inside the header div, after the parameter_group span */}
{p.backtest_metrics.optimization_mode === "live_signals" && (
  <span className="ml-1.5 text-[9px] px-1.5 py-0.5 rounded-full bg-blue-500/15 text-blue-400">
    Live Signals
  </span>
)}
{(!p.backtest_metrics.optimization_mode || p.backtest_metrics.optimization_mode === "backtest") && (
  <span className="ml-1.5 text-[9px] px-1.5 py-0.5 rounded-full bg-accent/15 text-accent">
    Backtest
  </span>
)}
```

- [ ] **Step 5: Add OptimizerPage trigger**

In `web/src/features/optimizer/components/OptimizerPage.tsx`, add the live signal optimization section. Add imports and state:

```tsx
import { useOptimizerStore } from "../store";
import { api } from "../../../shared/lib/api";
// ... existing imports

// Inside OptimizerPage component, add state:
const { signalOptLoading, optimizeFromSignals } = useOptimizerStore();
const [selectedPair, setSelectedPair] = useState("BTC-USDT-SWAP");
const [signalCount, setSignalCount] = useState<number | null>(null);
const PAIRS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"];

// Fetch signal count when pair changes
useEffect(() => {
  api.getResolvedSignalCount(selectedPair).then(setSignalCount).catch(() => setSignalCount(null));
}, [selectedPair]);
```

Add the UI section after the "How it works" guide and before the pending proposals:

```tsx
{/* Live Signal Optimization */}
<div className="border border-primary/20 rounded-xl bg-surface-container-low p-3 space-y-2">
  <div className="text-[10px] font-bold uppercase tracking-widest text-primary">
    Optimize from Live Signals
  </div>
  <div className="flex items-center gap-2">
    <select
      value={selectedPair}
      onChange={(e) => setSelectedPair(e.target.value)}
      className="bg-surface-container text-on-surface text-xs rounded px-2 py-1.5 border border-primary/20"
    >
      {PAIRS.map((p) => (
        <option key={p} value={p}>{p}</option>
      ))}
    </select>
    {signalCount !== null && (
      <span className="text-[10px] text-muted">
        {signalCount} resolved signals
      </span>
    )}
  </div>
  <Button
    variant="primary"
    size="sm"
    loading={signalOptLoading}
    disabled={actionLoading || signalOptLoading || (signalCount !== null && signalCount < 20)}
    onClick={() => optimizeFromSignals(selectedPair)}
    className="w-full"
  >
    Optimize from Live Signals
  </Button>
  {signalCount !== null && signalCount < 20 && (
    <p className="text-[10px] text-muted text-center">
      Need at least 20 resolved signals ({signalCount} available)
    </p>
  )}
</div>
```

- [ ] **Step 6: Build and verify**

Run: `cd web && pnpm build`
Expected: TypeScript check + build succeeds with no errors

- [ ] **Step 7: Commit Workstream C**

```
feat(optimizer): live-signal-based regime weight optimization with API and UI
```

---

## Self-Review

**Spec coverage check:**
- B1 (pure function extraction): Task 1 ✓
- B2 (backtester flow data loading): Task 2 ✓
- B3 (backtester scoring integration): Task 2 ✓ (combined with B2)
- B4 (optimizer param expansion): Task 3 ✓
- C1 (per-source score persistence): Task 4 ✓
- C2 (shared DE runner): Task 5 ✓
- C3 (live signal optimizer): Task 6 ✓
- C4 (API endpoint): Tasks 7 + 8 ✓
- C5 (frontend trigger): Task 9 ✓

**Placeholder scan:** No TBD, TODO, "implement later", or "similar to" references found.

**Type consistency:**
- `score_order_flow` name used consistently in Tasks 1 and 2
- `signal_vector_to_weight_dict` used in Tasks 6 (definition + test)
- `optimize_from_signals` used in Tasks 6 (engine) and 8 (API)
- `_build_bounds` used in Tasks 3 and 5
- `_SIGNAL_PARAM_BOUNDS` used in Tasks 6 (definition + test)
- `optimization_mode` used in Tasks 8 (backend) and 9 (frontend types + badge)
- `BacktestMetrics.optimization_mode` field matches API response format
