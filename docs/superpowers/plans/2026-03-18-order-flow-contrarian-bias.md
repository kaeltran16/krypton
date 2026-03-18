# Order Flow Contrarian Bias Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add regime-based contrarian scaling and rate-of-change override to `compute_order_flow_score()` so it dampens contrarian signals during trends and restores them on blowoff spikes.

**Architecture:** Two orthogonal modifiers applied to funding rate and L/S ratio scores only — (1) regime scaling reduces contrarian strength in trending markets, (2) RoC override restores it when funding/LS are rapidly spiking. The function gains two optional parameters (`regime`, `flow_history`) with backward-compatible defaults. Pipeline integration queries the last 10 `OrderFlowSnapshot` rows and passes the current regime dict.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, pytest

**Spec:** `docs/superpowers/specs/2026-03-18-order-flow-contrarian-bias-design.md`

---

### Task 1: Regime-Based Contrarian Scaling

**Files:**
- Modify: `backend/app/engine/traditional.py` (`compute_order_flow_score` at line 173)
- Test: `backend/tests/engine/test_traditional.py`

- [ ] **Step 1: Write failing tests for regime scaling**

Add to `backend/tests/engine/test_traditional.py`:

```python
class TestOrderFlowRegimeScaling:
    def test_ranging_regime_full_contrarian(self):
        """Pure ranging regime (trending=0) gives full contrarian scores."""
        regime = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        result_with = compute_order_flow_score(
            {"funding_rate": -0.0005}, regime=regime
        )
        result_without = compute_order_flow_score({"funding_rate": -0.0005})
        assert result_with["score"] == result_without["score"]

    def test_trending_regime_reduces_contrarian(self):
        """Pure trending regime (trending=1) reduces contrarian to ~30%."""
        regime_trending = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        regime_ranging = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        score_trending = abs(compute_order_flow_score(metrics, regime=regime_trending)["score"])
        score_ranging = abs(compute_order_flow_score(metrics, regime=regime_ranging)["score"])
        ratio = score_trending / score_ranging
        assert 0.25 <= ratio <= 0.40, f"Expected ~30% ratio, got {ratio:.2f}"

    def test_mixed_regime_interpolates(self):
        """Mixed regime gives intermediate contrarian strength."""
        regime_trending = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        regime_mixed = {"trending": 0.5, "ranging": 0.3, "volatile": 0.2}
        regime_ranging = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        metrics = {"funding_rate": -0.0005}
        score_trending = abs(compute_order_flow_score(metrics, regime=regime_trending)["score"])
        score_mixed = abs(compute_order_flow_score(metrics, regime=regime_mixed)["score"])
        score_ranging = abs(compute_order_flow_score(metrics, regime=regime_ranging)["score"])
        assert score_trending < score_mixed < score_ranging

    def test_oi_unaffected_by_regime(self):
        """OI score is not affected by regime scaling."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        result_with = compute_order_flow_score(metrics, regime=regime)
        result_without = compute_order_flow_score(metrics)
        assert result_with["score"] == result_without["score"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowRegimeScaling -v`
Expected: TypeError — `compute_order_flow_score()` got unexpected keyword argument `regime`

- [ ] **Step 3: Implement regime scaling in compute_order_flow_score**

Replace `compute_order_flow_score` in `backend/app/engine/traditional.py` (currently lines 173-198) with:

```python
# --- Order flow contrarian bias constants ---
TRENDING_FLOOR = 0.3
RECENT_WINDOW = 3
BASELINE_WINDOW = 7
TOTAL_SNAPSHOTS = RECENT_WINDOW + BASELINE_WINDOW
ROC_THRESHOLD = 0.0005
ROC_STEEPNESS = 8000
LS_ROC_SCALE = 0.003


def compute_order_flow_score(
    metrics: dict,
    regime: dict | None = None,
    flow_history: list | None = None,
) -> dict:
    """Compute order flow score from funding rate, OI changes, and L/S ratio.

    Returns dict with 'score' (-100 to +100) and 'details' dict.
    All keys are optional with safe defaults.

    Args:
        regime: Market regime mix from compute_technical_score().
            {"trending": float, "ranging": float, "volatile": float}
            None defaults to full contrarian (mult=1.0).
        flow_history: Recent OrderFlowSnapshot rows (oldest first).
            None or < 10 rows disables RoC override.
    """
    # regime-based contrarian scaling
    if regime is not None:
        trending = regime.get("trending", 0.0)
        contrarian_mult = 1.0 - (trending * (1.0 - TRENDING_FLOOR))
        contrarian_mult = max(TRENDING_FLOOR, min(1.0, contrarian_mult))
    else:
        contrarian_mult = 1.0

    # rate-of-change override (populated in Task 2)
    roc_boost = 0.0
    funding_roc = 0.0
    ls_roc = 0.0
    max_roc = 0.0
    final_mult = contrarian_mult + roc_boost * (1.0 - contrarian_mult)

    # Funding rate — contrarian (max +/-35)
    funding = metrics.get("funding_rate", 0.0)
    funding_score = sigmoid_score(-funding, center=0, steepness=8000) * 35 * final_mult

    # OI change — direction-aware (max +/-20), NOT affected by regime/RoC
    oi_change = metrics.get("open_interest_change_pct", 0.0)
    price_dir = metrics.get("price_direction", 0)
    if price_dir == 0:
        oi_score = 0.0
    else:
        oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=65) * 20

    # L/S ratio — contrarian (max +/-35)
    ls = metrics.get("long_short_ratio", 1.0)
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=6) * 35 * final_mult

    total = funding_score + oi_score + ls_score
    score = max(min(round(total), 100), -100)

    details = {
        "funding_rate": metrics.get("funding_rate", 0.0),
        "open_interest": metrics.get("open_interest"),
        "open_interest_change_pct": metrics.get("open_interest_change_pct", 0.0),
        "long_short_ratio": metrics.get("long_short_ratio", 1.0),
        "price_direction": metrics.get("price_direction", 0),
        "funding_score": round(funding_score, 1),
        "oi_score": round(oi_score, 1),
        "ls_score": round(ls_score, 1),
        "contrarian_mult": round(contrarian_mult, 4),
        "roc_boost": round(roc_boost, 4),
        "final_mult": round(final_mult, 4),
        "funding_roc": round(funding_roc, 8),
        "ls_roc": round(ls_roc, 8),
        "max_roc": round(max_roc, 8),
    }

    return {"score": score, "details": details}
```

- [ ] **Step 4: Run regime scaling tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowRegimeScaling -v`
Expected: all 4 PASS

- [ ] **Step 5: Run ALL existing order flow tests to verify backward compat**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -k "OrderFlow" -v`
Expected: all existing tests PASS (default `regime=None` gives mult=1.0)

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/traditional.py backend/tests/engine/test_traditional.py
git commit -m "feat(engine): add regime-based contrarian scaling to order flow scoring"
```

---

### Task 2: Rate-of-Change Override

**Files:**
- Modify: `backend/app/engine/traditional.py` (`compute_order_flow_score`)
- Test: `backend/tests/engine/test_traditional.py`

- [ ] **Step 1: Write failing tests for RoC override**

Add helper and test class to `backend/tests/engine/test_traditional.py`:

```python
from types import SimpleNamespace


def _make_snapshots(funding_rates, ls_ratios=None):
    """Create mock OrderFlowSnapshot-like objects for testing."""
    if ls_ratios is None:
        ls_ratios = [1.0] * len(funding_rates)
    return [
        SimpleNamespace(funding_rate=fr, long_short_ratio=ls)
        for fr, ls in zip(funding_rates, ls_ratios)
    ]


class TestOrderFlowRoCOverride:
    def test_stable_history_no_boost(self):
        """Stable flow history keeps regime scaling unchanged."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = _make_snapshots([0.0001] * 10, [1.2] * 10)
        metrics = {"funding_rate": -0.0005}
        result_with = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_without = compute_order_flow_score(metrics, regime=regime)
        # stable history should produce near-identical score to no history
        assert abs(result_with["score"] - result_without["score"]) <= 1

    def test_spiking_history_restores_contrarian(self):
        """Rapid funding spike restores contrarian strength despite trending regime."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        # baseline: 7 low funding, recent: 3 high funding (10x spike)
        funding_rates = [0.0001] * 7 + [0.001] * 3
        snapshots = _make_snapshots(funding_rates, [1.0] * 10)
        metrics = {"funding_rate": -0.0005}
        result_spike = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        # spiking history should produce higher magnitude than regime-dampened
        assert abs(result_spike["score"]) > abs(result_no_hist["score"])

    def test_insufficient_history_skips_roc(self):
        """Fewer than 10 snapshots disables RoC — only regime scaling applies."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = _make_snapshots([0.001] * 5, [1.0] * 5)
        metrics = {"funding_rate": -0.0005}
        result_partial = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result_partial["score"] == result_no_hist["score"]

    def test_null_fields_handled_gracefully(self):
        """Snapshots with None funding/LS are excluded from RoC computation."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = [
            SimpleNamespace(funding_rate=None, long_short_ratio=None)
            for _ in range(10)
        ]
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        # no valid data -> roc_boost = 0, result equals regime-only
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]
        assert result["details"]["roc_boost"] == 0.0

    def test_nine_snapshots_skips_roc(self):
        """Exactly 9 snapshots (below threshold of 10) disables RoC."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = _make_snapshots([0.0001] * 6 + [0.001] * 3, [1.0] * 9)
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]

    def test_nan_fields_excluded_from_roc(self):
        """Snapshots with NaN funding/LS are excluded from RoC computation."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = [
            SimpleNamespace(funding_rate=float('nan'), long_short_ratio=float('nan'))
            for _ in range(10)
        ]
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]
        assert result["details"]["roc_boost"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowRoCOverride -v`
Expected: `test_spiking_history_restores_contrarian` FAILS (RoC not implemented yet, spike has no effect). Others may pass trivially since RoC defaults to 0.

- [ ] **Step 3: Implement RoC override in compute_order_flow_score**

In `backend/app/engine/traditional.py`:

First, add `import math` to the file imports (near the top, with other stdlib imports).

Then locate the RoC placeholder block in `compute_order_flow_score` (the section with `# rate-of-change override (populated in Task 2)`) and replace it with:

```python
    # rate-of-change override from flow history
    roc_boost = 0.0
    funding_roc = 0.0
    ls_roc = 0.0
    max_roc = 0.0

    if flow_history and len(flow_history) >= TOTAL_SNAPSHOTS:
        baseline = flow_history[-TOTAL_SNAPSHOTS:-RECENT_WINDOW]
        recent = flow_history[-RECENT_WINDOW:]

        def _finite(v):
            return v is not None and math.isfinite(v)

        baseline_funding = [s.funding_rate for s in baseline if _finite(s.funding_rate)]
        recent_funding = [s.funding_rate for s in recent if _finite(s.funding_rate)]
        has_funding = bool(baseline_funding and recent_funding)
        if has_funding:
            funding_roc = (
                sum(recent_funding) / len(recent_funding)
                - sum(baseline_funding) / len(baseline_funding)
            )

        baseline_ls = [s.long_short_ratio for s in baseline if _finite(s.long_short_ratio)]
        recent_ls = [s.long_short_ratio for s in recent if _finite(s.long_short_ratio)]
        has_ls = bool(baseline_ls and recent_ls)
        if has_ls:
            ls_roc = (
                sum(recent_ls) / len(recent_ls)
                - sum(baseline_ls) / len(baseline_ls)
            )

        if has_funding or has_ls:
            ls_roc_scaled = ls_roc * LS_ROC_SCALE
            max_roc = max(abs(funding_roc), abs(ls_roc_scaled))
            roc_boost = sigmoid_scale(max_roc, center=ROC_THRESHOLD, steepness=ROC_STEEPNESS)

    final_mult = contrarian_mult + roc_boost * (1.0 - contrarian_mult)
```

This replaces the 5 lines:
```python
    # rate-of-change override (populated in Task 2)
    roc_boost = 0.0
    funding_roc = 0.0
    ls_roc = 0.0
    max_roc = 0.0
    final_mult = contrarian_mult + roc_boost * (1.0 - contrarian_mult)
```

- [ ] **Step 4: Run RoC tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowRoCOverride -v`
Expected: all 6 PASS

- [ ] **Step 5: Run full test suite to verify nothing broken**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: ALL tests PASS (regime + RoC + all existing)

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/traditional.py backend/tests/engine/test_traditional.py
git commit -m "feat(engine): add rate-of-change blowoff override to order flow scoring"
```

---

### Task 3: Backward Compatibility & Observability Verification

**Files:**
- Test: `backend/tests/engine/test_traditional.py`

- [ ] **Step 1: Write verification tests**

Add to `backend/tests/engine/test_traditional.py`:

```python
class TestOrderFlowBackwardCompat:
    def test_no_regime_no_history_mult_is_one(self):
        """Default params produce mult=1.0 (identical behavior to pre-change)."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        result = compute_order_flow_score(metrics)
        assert result["details"]["contrarian_mult"] == 1.0
        assert result["details"]["final_mult"] == 1.0

    def test_details_has_diagnostic_fields(self):
        """Details dict includes all raw metrics and diagnostic fields."""
        metrics = {"funding_rate": -0.0005}
        regime = {"trending": 0.5, "ranging": 0.3, "volatile": 0.2}
        result = compute_order_flow_score(metrics, regime=regime)
        details = result["details"]
        for key in [
            "funding_rate", "open_interest", "open_interest_change_pct",
            "long_short_ratio", "price_direction",
            "funding_score", "oi_score", "ls_score",
            "contrarian_mult", "roc_boost", "final_mult",
            "funding_roc", "ls_roc", "max_roc",
        ]:
            assert key in details, f"Missing field: {key}"

    def test_score_clamped_extreme_inputs(self):
        """Score stays in [-100, +100] under extreme inputs with full contrarian."""
        metrics = {
            "funding_rate": -0.01,
            "long_short_ratio": 0.1,
            "open_interest_change_pct": 0.5,
            "price_direction": 1,
        }
        regime = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        spiking = _make_snapshots([0.0001] * 7 + [0.01] * 3, [1.0] * 10)
        result = compute_order_flow_score(metrics, regime=regime, flow_history=spiking)
        assert -100 <= result["score"] <= 100
```

- [ ] **Step 2: Run verification tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowBackwardCompat -v`
Expected: all 3 PASS

- [ ] **Step 3: Run full test suite (unit + pipeline)**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: ALL tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/engine/test_traditional.py
git commit -m "test(engine): add backward compat and observability verification for order flow bias"
```

---

### Task 4: Pipeline Integration

**Files:**
- Modify: `backend/app/main.py:328-331` (pipeline call site)
- Modify: `backend/app/main.py:590-613` (raw_indicators — add flow diagnostics)
- Modify: `backend/app/api/routes.py:509` (manual score endpoint)
- Test: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Write integration test**

Add to `backend/tests/test_pipeline.py`:

```python
from types import SimpleNamespace


def test_pipeline_with_regime_and_flow_history():
    """Pipeline passes regime mix and flow history, signal includes diagnostic fields."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)
    tech_result = compute_technical_score(df)

    flow_metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 0.02,
        "long_short_ratio": 1.1,
        "price_direction": 1,
    }
    snapshots = [
        SimpleNamespace(funding_rate=0.00005, long_short_ratio=1.05)
        for _ in range(10)
    ]
    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=snapshots,
    )
    assert -100 <= flow_result["score"] <= 100
    assert "contrarian_mult" in flow_result["details"]
    assert "final_mult" in flow_result["details"]
    assert flow_result["details"]["contrarian_mult"] <= 1.0

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])
    assert isinstance(preliminary, (int, float))
```

- [ ] **Step 2: Run integration test**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/test_pipeline.py::test_pipeline_with_regime_and_flow_history -v`
Expected: PASS

- [ ] **Step 3: Wire up flow history query in main.py**

In `backend/app/main.py`, replace lines 328-331:

```python
    flow_metrics = order_flow.get(pair, {})
    # Inject price direction for direction-aware OI scoring
    flow_metrics = {**flow_metrics, "price_direction": 1 if candle["close"] >= candle["open"] else -1}
    flow_result = compute_order_flow_score(flow_metrics)
```

With:

```python
    flow_metrics = order_flow.get(pair, {})
    # Inject price direction for direction-aware OI scoring
    flow_metrics = {**flow_metrics, "price_direction": 1 if candle["close"] >= candle["open"] else -1}

    # Query flow history for contrarian bias RoC detection
    flow_history = []
    try:
        async with db.session_factory() as session:
            result = await session.execute(
                select(OrderFlowSnapshot)
                .where(OrderFlowSnapshot.pair == pair)
                .order_by(OrderFlowSnapshot.timestamp.desc())
                .limit(10)
            )
            flow_history = list(reversed(result.scalars().all()))
    except Exception as e:
        logger.debug(f"Flow history query skipped: {e}")

    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=flow_history,
    )
```

Note: `select`, `OrderFlowSnapshot`, and `db` are all already imported/available in scope at this location. No new imports needed.

- [ ] **Step 4: Add flow diagnostics to raw_indicators in main.py**

In `backend/app/main.py`, inside the `raw_indicators` dict (lines 590-613), add flow diagnostic fields after the existing `effective_outer_weights` entry:

```python
            "effective_outer_weights": {k: round(v, 4) for k, v in outer.items()} if regime else None,
            "flow_contrarian_mult": flow_result["details"].get("contrarian_mult"),
            "flow_roc_boost": flow_result["details"].get("roc_boost"),
            "flow_final_mult": flow_result["details"].get("final_mult"),
            "flow_funding_roc": flow_result["details"].get("funding_roc"),
            "flow_ls_roc": flow_result["details"].get("ls_roc"),
            "flow_max_roc": flow_result["details"].get("max_roc"),
```

This persists regime/RoC diagnostics in `Signal.raw_indicators` JSONB for auditability, matching what the spec promises.

- [ ] **Step 5: Add regime to routes.py manual score endpoint**

In `backend/app/api/routes.py`, replace line 509:

```python
        flow = compute_order_flow_score(request.app.state.order_flow.get(pair, {}))
```

With:

```python
        flow = compute_order_flow_score(
            request.app.state.order_flow.get(pair, {}),
            regime=tech["regime"],
        )
```

This ensures the manual score endpoint also applies regime-based contrarian scaling. Flow history (RoC override) is intentionally omitted here — this is a quick score snapshot, not a full pipeline run.

- [ ] **Step 6: Run all tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: ALL tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/api/routes.py backend/tests/test_pipeline.py
git commit -m "feat(engine): wire regime and flow history into pipeline for contrarian bias"
```
