# Order Flow Scoring Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 issues in the order flow scorer: eliminate hardcoded literals, fix zero-value confidence bug, add freshness decay, rebalance max scores, add per-asset sigmoid calibration, upgrade CVD to trend-based, include OI in flow history RoC, integrate order book depth as 5th component, and stabilize price direction to 3-candle net move.

**Architecture:** All scoring changes happen in `engine/traditional.py:compute_order_flow_score()`. Constants move to `engine/constants.py`. Caller changes (price direction, CVD history, book imbalance, freshness age) happen in `main.py:run_pipeline`. New params register in `engine/param_groups.py`. ALGORITHM.md updated last.

**Tech Stack:** Python 3.11, FastAPI, NumPy (`polynomial.polynomial.polyfit` for CVD slope), pytest (asyncio_mode="auto")

**Spec:** `docs/superpowers/specs/2026-03-26-order-flow-scoring-overhaul.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/engine/constants.py:30-39` | Modify | Add `book` to max_scores/steepnesses, add `freshness_*` keys, add `ORDER_FLOW_ASSET_SCALES` dict |
| `backend/app/engine/constants.py:130+` | Modify | Add PARAMETER_DESCRIPTIONS for `book_max`, `book_steepness`, `freshness_fresh_seconds`, `freshness_stale_seconds` |
| `backend/app/engine/constants.py:553-605` | Modify | Add `asset_scales` and `freshness` to `get_engine_constants()` return |
| `backend/app/engine/traditional.py:400-409` | Modify | Add module-level constants: `FUNDING_MAX`, `OI_MAX`, `LS_MAX`, `CVD_MAX`, `BOOK_MAX`, `BOOK_STEEPNESS`, `FRESH_SECONDS`, `STALE_SECONDS` |
| `backend/app/engine/traditional.py:425-538` | Modify | Rewrite `compute_order_flow_score()`: new params, constants-based scoring, key-based confidence, CVD trend, book imbalance, freshness decay, asset scaling |
| `backend/app/engine/param_groups.py:216-239` | Modify | Expand `order_flow` group to 12 params with new sweep ranges + constraints |
| `backend/app/main.py:460-494` | Modify | 3-candle price direction, CVD history, book imbalance computation, flow age, asset scale, OI in flow history query |
| `backend/tests/engine/test_traditional.py:369-629` | Modify | New test classes for all 9 issues + update `_make_snapshots` helper |

---

### Task 1: Constants Foundation (Issue 9 — Step 1)

Add `book` to max_scores/steepnesses, freshness thresholds, and `ORDER_FLOW_ASSET_SCALES` to `constants.py`. Add PARAMETER_DESCRIPTIONS. Update `get_engine_constants()`.

**Files:**
- Modify: `backend/app/engine/constants.py:30-39` (ORDER_FLOW dict)
- Modify: `backend/app/engine/constants.py:130+` (PARAMETER_DESCRIPTIONS)
- Modify: `backend/app/engine/constants.py:553-605` (get_engine_constants)

- [ ] **Step 1: Write failing test — constants structure**

In `backend/tests/engine/test_traditional.py`, add at the bottom (after the existing `TestOrderFlowRoCOverride` class):

```python
from app.engine.constants import ORDER_FLOW


class TestOrderFlowConstants:
    def test_max_scores_sum_to_100(self):
        total = sum(ORDER_FLOW["max_scores"].values())
        assert total == 100, f"Max scores sum to {total}, expected 100"

    def test_all_components_have_steepness(self):
        for key in ORDER_FLOW["max_scores"]:
            assert key in ORDER_FLOW["sigmoid_steepnesses"], f"Missing steepness for {key}"

    def test_freshness_thresholds_ordered(self):
        assert ORDER_FLOW["freshness_stale_seconds"] > ORDER_FLOW["freshness_fresh_seconds"]

    def test_asset_scales_exist_for_all_pairs(self):
        from app.engine.constants import ORDER_FLOW_ASSET_SCALES
        for pair in ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"]:
            assert pair in ORDER_FLOW_ASSET_SCALES, f"Missing asset scale for {pair}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowConstants -v`
Expected: FAIL — `book` missing from max_scores, no `freshness_*` keys, no `ORDER_FLOW_ASSET_SCALES`

- [ ] **Step 3: Update ORDER_FLOW dict**

**Behavioral changes:** Max scores rebalance from `{funding:30, oi:20, ls_ratio:30, cvd:20}` to `{funding:22, oi:22, ls_ratio:22, cvd:22, book:12}`. CVD steepness changes from `3` to `5` (stronger sigmoid response to same inputs). These affect existing test thresholds — see Step 6 for required test adjustments.

In `backend/app/engine/constants.py`, replace lines 30-39:

```python
# -- Order flow scoring --
ORDER_FLOW = {
    "max_scores": {"funding": 22, "oi": 22, "ls_ratio": 22, "cvd": 22, "book": 12},
    "sigmoid_steepnesses": {"funding": 400, "oi": 20, "ls_ratio": 6, "cvd": 5, "book": 4},
    "trending_floor": 0.3,
    "recent_window": 3,
    "baseline_window": 7,
    "roc_threshold": 0.0005,
    "roc_steepness": 8000,
    "ls_roc_scale": 0.003,
    "freshness_fresh_seconds": 300,
    "freshness_stale_seconds": 900,
}

ORDER_FLOW_ASSET_SCALES = {
    "BTC-USDT-SWAP": 1.0,
    "ETH-USDT-SWAP": 0.85,
    "WIF-USDT-SWAP": 0.4,
}
```

- [ ] **Step 4: Add PARAMETER_DESCRIPTIONS for new params**

In `backend/app/engine/constants.py`, in the `PARAMETER_DESCRIPTIONS` dict after the existing `"cvd_steepness"` entry (around line 290), add:

```python
    "book_max": {
        "description": "Maximum score contribution from order book bid/ask imbalance. Low cap because top-5 depth is shallow and spoofable",
        "pipeline_stage": "Order Flow Scoring",
        "range": "5-20",
    },
    "book_steepness": {
        "description": "Sigmoid steepness for book imbalance scoring. Input is already normalized to [-1, +1]",
        "pipeline_stage": "Order Flow Scoring",
        "range": "2-8",
    },
    "freshness_fresh_seconds": {
        "description": "Age in seconds below which flow data is considered fully fresh (no confidence penalty)",
        "pipeline_stage": "Order Flow Scoring",
        "range": "120-600",
    },
    "freshness_stale_seconds": {
        "description": "Age in seconds at which flow data is considered fully stale (confidence decays to zero). Must be greater than freshness_fresh_seconds",
        "pipeline_stage": "Order Flow Scoring",
        "range": "600-1800",
    },
```

Also update the existing `"funding_max"` range description from `"15-50 — funding + oi + ls_ratio max scores must sum <= 100"` to `"10-35 — all five max scores must sum <= 100"`.

- [ ] **Step 5: Update get_engine_constants()**

In `backend/app/engine/constants.py`, in `get_engine_constants()`, update the `"order_flow"` section (around line 577-587) to add `asset_scales` and `freshness`:

```python
        "order_flow": {
            "max_scores": _wrap(ORDER_FLOW["max_scores"]),
            "sigmoid_steepnesses": _wrap(ORDER_FLOW["sigmoid_steepnesses"]),
            "asset_scales": _wrap(ORDER_FLOW_ASSET_SCALES),
            "freshness": _wrap({
                "fresh_seconds": ORDER_FLOW["freshness_fresh_seconds"],
                "stale_seconds": ORDER_FLOW["freshness_stale_seconds"],
            }),
            "regime_params": _wrap({
                "trending_floor": ORDER_FLOW["trending_floor"],
                "roc_threshold": ORDER_FLOW["roc_threshold"],
                "roc_steepness": ORDER_FLOW["roc_steepness"],
                "ls_roc_scale": ORDER_FLOW["ls_roc_scale"],
                "recent_window": ORDER_FLOW["recent_window"],
                "baseline_window": ORDER_FLOW["baseline_window"],
            }),
        },
```

- [ ] **Step 6: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowConstants -v`
Expected: PASS

- [ ] **Step 7: Fix existing tests broken by max score and steepness changes**

The rebalance (30/20 → 22/22) and CVD steepness change (3 → 5) will break these tests:

- `TestCVDScoring` (line 787): All threshold assertions are calibrated to `CVD_STEEPNESS=3`. With steepness=5 the sigmoid saturates faster — update expected score magnitudes. Direction tests (positive/negative) still pass.
- `TestRecalibratedScoreMagnitude::test_order_flow_score_magnitude`: If it asserts `score > 20`, verify it still holds with the new weights (max 22+22+22+22=88 for 4 non-book components, so strong inputs should still exceed 20).
- `TestOrderFlowBounds` (line 373): If it asserts specific bounds based on old max scores, update to reflect new 22/22/22/22/12 distribution.
- `TestOrderFlowRegimeScaling` (line 529): Ratio checks (e.g., 0.25-0.40) depend on `contrarian_mult`, not max scores — should still pass.
- `TestDynamicConfidence` (line 824): Value-based confidence (`funding != 0`, `ls != 1.0`) is replaced in Task 4 — these tests will be rewritten then. For now they may fail on CVD steepness; defer fixing until Task 4.

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Fix any assertion threshold failures by adjusting to match the new score ranges.

---

### Task 2: Scorer Reads from Constants (Issue 9 — Step 2)

Replace hardcoded `30`, `20`, `30`, `20` literals in the scorer with module-level constants loaded from `ORDER_FLOW`. Add the new constants (`BOOK_MAX`, `BOOK_STEEPNESS`, `FRESH_SECONDS`, `STALE_SECONDS`).

**Files:**
- Modify: `backend/app/engine/traditional.py:400-409` (module-level constants)
- Modify: `backend/app/engine/traditional.py:480-503` (scoring lines)

- [ ] **Step 1: Write failing test — no hardcoded score literals**

In `backend/tests/engine/test_traditional.py`, add:

```python
import re
import inspect
from app.engine.traditional import compute_order_flow_score


class TestOrderFlowNoHardcodedLiterals:
    def test_scorer_uses_constants_not_literals(self):
        """Verify the scorer body has no hardcoded max score literals (30, 20)."""
        source = inspect.getsource(compute_order_flow_score)
        # Strip comments to avoid false positives
        lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
        body = "\n".join(lines)
        # Use word-boundary regex to match exactly "* 30" or "* 20" (not "* 200", "* 300", etc.)
        assert not re.search(r"\*\s*\b30\b", body), "Found hardcoded '* 30' in scorer"
        assert not re.search(r"\*\s*\b20\b", body), "Found hardcoded '* 20' in scorer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowNoHardcodedLiterals -v`
Expected: FAIL — scorer currently has `* 30` and `* 20`

- [ ] **Step 3: Add module-level constants and replace literals**

In `backend/app/engine/traditional.py`, replace lines 400-409 with:

```python
OI_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["oi"]
LS_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["ls_ratio"]
CVD_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["cvd"]
FUNDING_MAX = ORDER_FLOW["max_scores"]["funding"]
OI_MAX = ORDER_FLOW["max_scores"]["oi"]
LS_MAX = ORDER_FLOW["max_scores"]["ls_ratio"]
CVD_MAX = ORDER_FLOW["max_scores"]["cvd"]
BOOK_MAX = ORDER_FLOW["max_scores"]["book"]
BOOK_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["book"]
FRESH_SECONDS = ORDER_FLOW["freshness_fresh_seconds"]
STALE_SECONDS = ORDER_FLOW["freshness_stale_seconds"]
TRENDING_FLOOR = ORDER_FLOW["trending_floor"]
RECENT_WINDOW = ORDER_FLOW["recent_window"]
BASELINE_WINDOW = ORDER_FLOW["baseline_window"]
TOTAL_SNAPSHOTS = RECENT_WINDOW + BASELINE_WINDOW
ROC_THRESHOLD = ORDER_FLOW["roc_threshold"]
ROC_STEEPNESS = ORDER_FLOW["roc_steepness"]
LS_ROC_SCALE = ORDER_FLOW["ls_roc_scale"]
```

Then in `compute_order_flow_score()`, replace:
- `* 30 * final_mult` on the funding line → `* FUNDING_MAX * final_mult`
- `* 20` on the OI line → `* OI_MAX`
- `* 30 * final_mult` on the L/S line → `* LS_MAX * final_mult`
- `* 20` on the CVD line → `* CVD_MAX`

- [ ] **Step 4: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowNoHardcodedLiterals -v`
Expected: PASS

- [ ] **Step 5: Run full order flow test suite to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowBounds tests/engine/test_traditional.py::TestOrderFlowContinuity tests/engine/test_traditional.py::TestOrderFlowDirectionalOI tests/engine/test_traditional.py::TestRecalibratedScoreMagnitude -v`
Expected: Some tests may need adjustment due to new max scores (22 instead of 30/20). Update magnitude assertions if needed — the scoring behavior is correct, only the scale changed.

**Note on test adjustments:** The `TestOrderFlowContinuity`, `TestOrderFlowDirectionalOI`, and `TestOrderFlowRegimeScaling` tests check direction (positive/negative) and relative ordering — these should still pass since the score directions haven't changed. The `TestRecalibratedScoreMagnitude::test_order_flow_score_magnitude` checks `score > 20` which should still hold since strong inputs across 4 components (22+22+22+22=88 max) still produce significant total. If any threshold assertions fail, adjust them to match the new score ranges.

---

### Task 3: Param Groups Update (Issue 9 — Step 3)

Expand the `order_flow` param group from 6 to 12 parameters with updated sweep ranges and constraints.

**Files:**
- Modify: `backend/app/engine/param_groups.py:216-239`

- [ ] **Step 1: Write failing test — param group completeness**

In `backend/tests/engine/test_traditional.py`, add:

```python
class TestOrderFlowParamGroup:
    def test_param_group_has_12_params(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        assert len(group["params"]) == 12, f"Expected 12 params, got {len(group['params'])}"

    def test_all_params_have_sweep_ranges(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        for param in group["params"]:
            assert param in group["sweep_ranges"], f"Missing sweep range for {param}"

    def test_constraint_rejects_sum_over_100(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        over_budget = {
            "funding_max": 30, "oi_max": 30, "ls_ratio_max": 30,
            "cvd_max": 20, "book_max": 20,
            "funding_steepness": 400, "oi_steepness": 20,
            "ls_ratio_steepness": 6, "cvd_steepness": 5, "book_steepness": 4,
            "freshness_fresh_seconds": 300, "freshness_stale_seconds": 900,
        }
        assert not group["constraints"](over_budget)

    def test_constraint_accepts_valid_config(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        valid = {
            "funding_max": 22, "oi_max": 22, "ls_ratio_max": 22,
            "cvd_max": 22, "book_max": 12,
            "funding_steepness": 400, "oi_steepness": 20,
            "ls_ratio_steepness": 6, "cvd_steepness": 5, "book_steepness": 4,
            "freshness_fresh_seconds": 300, "freshness_stale_seconds": 900,
        }
        assert group["constraints"](valid)

    def test_constraint_rejects_stale_before_fresh(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        bad_freshness = {
            "funding_max": 22, "oi_max": 22, "ls_ratio_max": 22,
            "cvd_max": 22, "book_max": 12,
            "funding_steepness": 400, "oi_steepness": 20,
            "ls_ratio_steepness": 6, "cvd_steepness": 5, "book_steepness": 4,
            "freshness_fresh_seconds": 900, "freshness_stale_seconds": 300,
        }
        assert not group["constraints"](bad_freshness)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowParamGroup -v`
Expected: FAIL — only 6 params, missing cvd/book/freshness

- [ ] **Step 3: Update param_groups.py**

Replace `backend/app/engine/param_groups.py` lines 216-239 with:

```python
    "order_flow": {
        "params": {
            "funding_max": "order_flow.max_scores.funding",
            "oi_max": "order_flow.max_scores.oi",
            "ls_ratio_max": "order_flow.max_scores.ls_ratio",
            "cvd_max": "order_flow.max_scores.cvd",
            "book_max": "order_flow.max_scores.book",
            "funding_steepness": "order_flow.sigmoid_steepnesses.funding",
            "oi_steepness": "order_flow.sigmoid_steepnesses.oi",
            "ls_ratio_steepness": "order_flow.sigmoid_steepnesses.ls_ratio",
            "cvd_steepness": "order_flow.sigmoid_steepnesses.cvd",
            "book_steepness": "order_flow.sigmoid_steepnesses.book",
            "freshness_fresh_seconds": "order_flow.freshness_fresh_seconds",
            "freshness_stale_seconds": "order_flow.freshness_stale_seconds",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "funding_max": (10, 35, None),
            "oi_max": (10, 35, None),
            "ls_ratio_max": (10, 35, None),
            "cvd_max": (10, 35, None),
            "book_max": (5, 20, None),
            "funding_steepness": (200, 800, None),
            "oi_steepness": (10, 40, None),
            "ls_ratio_steepness": (2, 12, None),
            "cvd_steepness": (2, 10, None),
            "book_steepness": (2, 8, None),
            "freshness_fresh_seconds": (120, 600, None),
            "freshness_stale_seconds": (600, 1800, None),
        },
        "constraints": lambda c: (
            sum(c.get(k, 0) for k in ("funding_max", "oi_max", "ls_ratio_max", "cvd_max", "book_max")) <= 100
            and all(v > 0 for v in c.values())
            and c.get("freshness_stale_seconds", 900) > c.get("freshness_fresh_seconds", 300)
        ),
        "priority": _priority_for("order_flow"),
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowParamGroup -v`
Expected: PASS

---

### Task 4: Fix Zero-Value Confidence Bug (Issue 2)

Change confidence calculation from value-based to key-based presence detection.

**Files:**
- Modify: `backend/app/engine/traditional.py:527-536` (confidence block)
- Test: `backend/tests/engine/test_traditional.py`

- [ ] **Step 1: Write failing test — zero funding counts as present**

```python
class TestOrderFlowConfidenceBug:
    def test_zero_funding_still_counts_as_present(self):
        """funding_rate=0.0 should count as present data, not absent."""
        result = compute_order_flow_score({"funding_rate": 0.0})
        # 1 source present, 1 available → confidence = 1.0
        assert result["confidence"] > 0.0, "Zero funding treated as absent"

    def test_exact_ls_one_still_counts_as_present(self):
        """long_short_ratio=1.0 should count as present data, not absent."""
        result = compute_order_flow_score({"long_short_ratio": 1.0})
        assert result["confidence"] > 0.0, "L/S ratio 1.0 treated as absent"

    def test_empty_metrics_zero_confidence(self):
        """No keys at all = truly absent = zero confidence."""
        result = compute_order_flow_score({})
        assert result["confidence"] == 0.0

    def test_all_three_legacy_present_full_confidence(self):
        """All three legacy keys present = confidence 1.0 (before book)."""
        result = compute_order_flow_score({
            "funding_rate": 0.0001,
            "open_interest_change_pct": 0.01,
            "price_direction": 1,
            "long_short_ratio": 1.2,
        })
        # 3 sources present, 3 available (no CVD, no book) = 1.0
        # inputs_present may be 3/3 (all contribute nonzero) = 1.0
        assert result["confidence"] >= 0.75
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowConfidenceBug -v`
Expected: FAIL — `test_zero_funding_still_counts_as_present` returns confidence 0.0

- [ ] **Step 3: Replace confidence calculation in compute_order_flow_score**

Replace the confidence block (lines 527-536) with:

```python
    # dynamic confidence: key-based presence detection
    inputs_present = sum([
        "funding_rate" in metrics,
        "open_interest_change_pct" in metrics and price_dir != 0,
        "long_short_ratio" in metrics,
        cvd_delta is not None and avg_vol > 0,
        book_imbalance is not None,
    ])
    sources_available = sum([
        "funding_rate" in metrics,
        "open_interest_change_pct" in metrics,
        "long_short_ratio" in metrics,
        cvd_delta is not None,
        book_imbalance is not None,
    ])
    flow_confidence = round(inputs_present / max(sources_available, 1), 4)
```

**Important:** `book_imbalance` scoring is added in Task 10, but the confidence block references it now. Add this line before the confidence block to avoid `NameError`:

```python
    book_imbalance = metrics.get("book_imbalance")
```

This evaluates to `None` until Task 10 adds book scoring, so the confidence lines evaluate to `False` and are harmless.

- [ ] **Step 4: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowConfidenceBug -v`
Expected: PASS

---

### Task 5: 3-Candle Price Direction (Issue 1)

Replace single-candle body direction with 3-candle net move in `main.py`.

**Files:**
- Modify: `backend/app/main.py:460-462` (price direction injection)
- Test: `backend/tests/engine/test_traditional.py` (caller-level unit test)

- [ ] **Step 1: Write test — 3-candle direction logic**

This is a caller change in `main.py`. The scorer's interface is unchanged. Test the direction computation logic directly:

```python
class TestThreeCandlePriceDirection:
    def test_uptrend_doji_still_bullish(self):
        """In an uptrend, a doji candle should not flip price direction to bearish."""
        # Simulate: candles[-4] close=100, current close=103 (net up), but current open=103.05 (doji)
        # 3-candle net move: 103 - 100 = +3 → price_direction = 1
        recent_close = 103.0
        lookback_close = 100.0
        net_move = recent_close - lookback_close
        price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
        assert price_direction == 1

    def test_downtrend_produces_bearish(self):
        recent_close = 97.0
        lookback_close = 100.0
        net_move = recent_close - lookback_close
        price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
        assert price_direction == -1

    def test_flat_produces_zero(self):
        recent_close = 100.0
        lookback_close = 100.0
        net_move = recent_close - lookback_close
        price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
        assert price_direction == 0
```

- [ ] **Step 2: Run test to verify it passes** (this tests pure logic, not the old code)

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestThreeCandlePriceDirection -v`
Expected: PASS (logic test, not integration)

- [ ] **Step 3: Update main.py price direction computation**

In `backend/app/main.py`, replace line 462:

```python
    flow_metrics = {**flow_metrics, "price_direction": 1 if candle["close"] > candle["open"] else (-1 if candle["close"] < candle["open"] else 0)}
```

With:

```python
    # 3-candle net move for stable price direction (Issue 1)
    recent_close = float(candle["close"])
    lookback_close = float(candles_data[-4]["close"]) if len(candles_data) >= 4 else float(candle["open"])
    net_move = recent_close - lookback_close
    price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
    flow_metrics = {**flow_metrics, "price_direction": price_direction}
```

- [ ] **Step 4: Run existing OI tests to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowDirectionalOI -v`
Expected: PASS (scorer interface unchanged)

---

### Task 6: OI in Flow History RoC (Issue 7)

Add `oi_change_pct` to the flow history query and compute OI RoC.

**Files:**
- Modify: `backend/app/main.py:478-484` (flow history query)
- Modify: `backend/app/engine/traditional.py:462-472` (RoC block)
- Modify: `backend/tests/engine/test_traditional.py` (_make_snapshots + new tests)

- [ ] **Step 1: Update _make_snapshots helper**

In `backend/tests/engine/test_traditional.py`, replace `_make_snapshots` (lines 569-576):

```python
def _make_snapshots(funding_rates, ls_ratios=None, oi_changes=None):
    """Create mock OrderFlowSnapshot-like objects for testing."""
    if ls_ratios is None:
        ls_ratios = [1.0] * len(funding_rates)
    if oi_changes is None:
        oi_changes = [0.0] * len(funding_rates)
    return [
        SimpleNamespace(funding_rate=fr, long_short_ratio=ls, oi_change_pct=oi)
        for fr, ls, oi in zip(funding_rates, ls_ratios, oi_changes)
    ]
```

- [ ] **Step 2: Write failing test — OI RoC boosts score**

```python
class TestOrderFlowOIRoC:
    def test_spiking_oi_in_history_produces_roc_boost(self):
        """Rapidly increasing OI should produce roc_boost > 0."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        oi_changes = [0.01] * 7 + [0.10] * 3  # big spike in recent
        snapshots = _make_snapshots([0.0001] * 10, [1.0] * 10, oi_changes)
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        assert result["details"]["roc_boost"] > 0.0

    def test_oi_roc_in_details(self):
        """OI RoC should appear in details dict."""
        snapshots = _make_snapshots([0.0001] * 10, [1.0] * 10, [0.01] * 10)
        result = compute_order_flow_score(
            {"funding_rate": 0.0001}, flow_history=snapshots
        )
        assert "oi_roc" in result["details"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowOIRoC -v`
Expected: FAIL — `oi_roc` not in details, OI not in RoC computation

- [ ] **Step 4: Add OI RoC to scorer**

In `backend/app/engine/traditional.py`, in the RoC block (around line 466-472), after the `ls_roc` computation:

```python
        funding_roc, has_funding = _field_roc(baseline, recent, lambda s: s.funding_rate)
        ls_roc, has_ls = _field_roc(baseline, recent, lambda s: s.long_short_ratio)
        oi_roc, has_oi = _field_roc(baseline, recent, lambda s: s.oi_change_pct)

        if has_funding or has_ls or has_oi:
            ls_roc_scaled = ls_roc * LS_ROC_SCALE
            max_roc = max(abs(funding_roc), abs(ls_roc_scaled), abs(oi_roc))
            roc_boost = sigmoid_scale(max_roc, center=ROC_THRESHOLD, steepness=ROC_STEEPNESS)
```

Initialize `oi_roc = 0.0` alongside `funding_roc` and `ls_roc` at the top of the function.

Add to the details dict:

```python
        "oi_roc": round(oi_roc, 8),
```

- [ ] **Step 5: Update flow history query in main.py**

In `backend/app/main.py`, replace line 479:

```python
                    select(OrderFlowSnapshot.funding_rate, OrderFlowSnapshot.long_short_ratio)
```

With:

```python
                    select(OrderFlowSnapshot.funding_rate, OrderFlowSnapshot.long_short_ratio, OrderFlowSnapshot.oi_change_pct)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowOIRoC -v`
Expected: PASS

- [ ] **Step 7: Fix manually-constructed snapshot tests**

Two existing tests in `TestOrderFlowRoCOverride` create `SimpleNamespace` objects directly (not via `_make_snapshots`) and lack the new `oi_change_pct` attribute. The `_field_roc` accessor `lambda s: s.oi_change_pct` will raise `AttributeError` on them.

In `test_null_fields_handled_gracefully`, replace:
```python
        snapshots = [
            SimpleNamespace(funding_rate=None, long_short_ratio=None)
            for _ in range(10)
        ]
```
With:
```python
        snapshots = [
            SimpleNamespace(funding_rate=None, long_short_ratio=None, oi_change_pct=None)
            for _ in range(10)
        ]
```

If a `test_nan_fields_excluded_from_roc` test exists with similar manually-constructed snapshots, add `oi_change_pct=float('nan')` to those as well.

- [ ] **Step 8: Run existing RoC tests to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowRoCOverride -v`
Expected: PASS (snapshots via `_make_snapshots` now have `oi_change_pct=0.0` via default — no OI RoC contribution, behavior unchanged. Manually-constructed snapshots updated in Step 7.)

---

### Task 7: Per-Asset Sigmoid Calibration (Issue 5)

Add `asset_scale` parameter to the scorer, applied to funding + L/S steepnesses.

**Files:**
- Modify: `backend/app/engine/traditional.py:425-431` (function signature)
- Modify: `backend/app/engine/traditional.py:480-494` (funding + L/S scoring lines)
- Modify: `backend/app/main.py:488-494` (caller passes asset_scale)

- [ ] **Step 1: Write failing test — asset scale reduces score**

```python
class TestOrderFlowAssetScale:
    def test_wif_scale_produces_lower_score_than_btc(self):
        """WIF (scale=0.4) should produce lower absolute score than BTC (scale=1.0) for same funding."""
        metrics = {"funding_rate": -0.005, "long_short_ratio": 0.8}
        btc_result = compute_order_flow_score(metrics, asset_scale=1.0)
        wif_result = compute_order_flow_score(metrics, asset_scale=0.4)
        assert abs(wif_result["score"]) < abs(btc_result["score"])

    def test_asset_scale_in_details(self):
        result = compute_order_flow_score({"funding_rate": 0.001}, asset_scale=0.85)
        assert result["details"]["asset_scale"] == 0.85

    def test_default_asset_scale_is_one(self):
        """Without asset_scale param, behavior is unchanged (scale=1.0)."""
        result = compute_order_flow_score({"funding_rate": 0.001})
        assert result["details"]["asset_scale"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowAssetScale -v`
Expected: FAIL — `asset_scale` not a valid parameter

- [ ] **Step 3: Add asset_scale to scorer**

In `backend/app/engine/traditional.py`, update function signature:

```python
def compute_order_flow_score(
    metrics: dict,
    regime: dict | None = None,
    flow_history: list | None = None,
    trend_conviction: float = 0.0,
    mr_pressure: float = 0.0,
    flow_age_seconds: float | None = None,
    asset_scale: float = 1.0,
) -> dict:
```

Apply scaling to contrarian components:

```python
    # Funding rate — contrarian, asset-scaled
    funding = metrics.get("funding_rate", 0.0)
    funding_steepness = FUNDING_STEEPNESS * asset_scale
    funding_score = sigmoid_score(-funding, center=0, steepness=funding_steepness) * FUNDING_MAX * final_mult

    # ...

    # L/S ratio — contrarian, asset-scaled
    ls = metrics.get("long_short_ratio", 1.0)
    ls_steepness = LS_STEEPNESS * asset_scale
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=ls_steepness) * LS_MAX * final_mult
```

Add to details:

```python
        "asset_scale": round(asset_scale, 4),
```

- [ ] **Step 4: Update caller in main.py**

In `backend/app/main.py`, before the `compute_order_flow_score` call (around line 488), add:

```python
    from app.engine.constants import ORDER_FLOW_ASSET_SCALES
    asset_scale = ORDER_FLOW_ASSET_SCALES.get(pair, 1.0)
```

And pass it:

```python
    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=flow_history,
        trend_conviction=tech_result["indicators"].get("trend_conviction", 0.0),
        mr_pressure=tech_result.get("mr_pressure", 0.0),
        asset_scale=asset_scale,
    )
```

(Move the import to the top of the file with other constant imports.)

- [ ] **Step 5: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowAssetScale -v`
Expected: PASS

---

### Task 8: CVD Trend-Based Scoring (Issue 6)

Upgrade CVD from single-candle delta to slope-based trend scoring.

**Files:**
- Modify: `backend/app/main.py:464-471` (CVD history maintenance)
- Modify: `backend/app/engine/traditional.py:496-503` (CVD scoring block)

- [ ] **Step 1: Write failing test — CVD trend scoring**

```python
import numpy as np


class TestOrderFlowCVDTrend:
    def test_rising_cvd_history_produces_positive_score(self):
        """10-candle rising CVD history should produce a positive cvd_score via slope."""
        trend_result = compute_order_flow_score({
            "cvd_delta": 500.0,
            "cvd_history": [i * 500 for i in range(1, 11)],  # 500, 1000, ..., 5000
            "avg_candle_volume": 1000.0,
        })
        assert trend_result["details"]["cvd_score"] > 0

    def test_falling_cvd_history_produces_negative_score(self):
        """10-candle falling CVD history should produce a negative cvd_score."""
        trend_result = compute_order_flow_score({
            "cvd_delta": -500.0,
            "cvd_history": [-i * 500 for i in range(1, 11)],
            "avg_candle_volume": 1000.0,
        })
        assert trend_result["details"]["cvd_score"] < 0

    def test_cvd_trend_fallback_with_insufficient_history(self):
        """With <5 entries in cvd_history, fall back to single-delta scoring."""
        result = compute_order_flow_score({
            "cvd_delta": 500.0,
            "cvd_history": [100, 200, 300],  # only 3 entries
            "avg_candle_volume": 1000.0,
        })
        # Should still score (fallback to single delta)
        assert result["details"]["cvd_score"] != 0.0

    def test_no_cvd_history_uses_single_delta(self):
        """Without cvd_history key, uses single-delta scoring (backward compat)."""
        result = compute_order_flow_score({
            "cvd_delta": 500.0,
            "avg_candle_volume": 1000.0,
        })
        assert result["details"]["cvd_score"] != 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowCVDTrend -v`
Expected: FAIL — scorer ignores `cvd_history`

- [ ] **Step 3: Add numpy import and update CVD scoring**

At the top of `backend/app/engine/traditional.py`, add `import numpy as np` if not already present.

Replace the CVD scoring block in `compute_order_flow_score()`:

```python
    # CVD — directional, trend-based when history available (max +/-CVD_MAX)
    cvd_delta = metrics.get("cvd_delta")
    avg_vol = metrics.get("avg_candle_volume", 0)
    cvd_history = metrics.get("cvd_history")

    if cvd_history and len(cvd_history) >= 5 and avg_vol > 0:
        arr = np.array(cvd_history[-10:], dtype=float)
        x = np.arange(len(arr))
        # polynomial.polyfit returns coefficients in ascending order [c0, c1], so [1] is the slope
        slope = np.polynomial.polynomial.polyfit(x, arr, 1)[1]
        cvd_normalized = slope / avg_vol
        cvd_score = sigmoid_score(cvd_normalized, center=0, steepness=CVD_STEEPNESS) * CVD_MAX
    elif cvd_delta is not None and avg_vol > 0:
        cvd_normalized = cvd_delta / avg_vol
        cvd_score = sigmoid_score(cvd_normalized, center=0, steepness=CVD_STEEPNESS) * CVD_MAX
    else:
        cvd_score = 0.0
```

- [ ] **Step 4: Add CVD history maintenance in main.py**

In `backend/app/main.py`, after `cvd_state["candle_delta"] = 0.0` (line 469), add CVD history tracking:

```python
    if cvd_state:
        cvd_delta_val = cvd_state["candle_delta"]
        cvd_state["candle_delta"] = 0.0

        # Maintain rolling CVD history for trend scoring
        history = cvd_state.setdefault("history", [])
        history.append(cvd_delta_val)
        if len(history) > 10:
            history.pop(0)

        flow_metrics["cvd_delta"] = cvd_delta_val
        flow_metrics["cvd_history"] = list(history)
        flow_metrics["avg_candle_volume"] = float(candle.get("volume", 0))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowCVDTrend -v`
Expected: PASS

---

### Task 9: Freshness Decay (Issue 3)

Add `flow_age_seconds` parameter with confidence penalty.

**Files:**
- Modify: `backend/app/engine/traditional.py:425-431` (signature, already added in Task 7 step 3)
- Modify: `backend/app/engine/traditional.py` (freshness decay block before confidence)
- Modify: `backend/app/main.py` (compute and pass flow_age)

- [ ] **Step 1: Write failing test — freshness decay**

```python
class TestOrderFlowFreshnessDecay:
    def test_fresh_data_no_penalty(self):
        """flow_age_seconds=0 → full confidence (no penalty)."""
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result = compute_order_flow_score(metrics, flow_age_seconds=0)
        result_no_age = compute_order_flow_score(metrics)
        assert result["confidence"] == result_no_age["confidence"]

    def test_half_stale_halves_confidence(self):
        """flow_age_seconds=600 (midpoint of 300-900) → ~50% confidence penalty."""
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result_fresh = compute_order_flow_score(metrics, flow_age_seconds=0)
        result_half = compute_order_flow_score(metrics, flow_age_seconds=600)
        assert result_half["confidence"] < result_fresh["confidence"]
        assert result_half["confidence"] > 0.0

    def test_fully_stale_zeroes_confidence(self):
        """flow_age_seconds=900+ → confidence decays to zero."""
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result = compute_order_flow_score(metrics, flow_age_seconds=1000)
        assert result["confidence"] == 0.0

    def test_none_age_no_penalty(self):
        """flow_age_seconds=None (default) → no penalty."""
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics, flow_age_seconds=None)
        result_explicit = compute_order_flow_score(metrics, flow_age_seconds=0)
        assert result["confidence"] == result_explicit["confidence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowFreshnessDecay -v`
Expected: FAIL — `flow_age_seconds` parameter already in signature (Task 7) but no decay logic yet

- [ ] **Step 3: Add freshness decay logic**

In `compute_order_flow_score()`, after computing `flow_confidence` and before the return statement:

```python
    # Freshness decay — penalize confidence for stale flow data
    freshness_decay = 0.0
    if flow_age_seconds is not None and flow_age_seconds > FRESH_SECONDS:
        freshness_decay = min(1.0, (flow_age_seconds - FRESH_SECONDS) / (STALE_SECONDS - FRESH_SECONDS))
        flow_confidence *= (1.0 - freshness_decay)
        flow_confidence = round(flow_confidence, 4)
```

Add to details dict for observability:

```python
        "flow_age_seconds": round(flow_age_seconds, 1) if flow_age_seconds is not None else None,
        "freshness_decay": round(freshness_decay, 4),
```

- [ ] **Step 4: Pass flow_age in main.py**

**Pre-check:** Verify that the collector sets `_last_updated` on `app.state.order_flow[pair]`. Check `collector/okx_ws.py` (or wherever `app.state.order_flow` is populated). If the key isn't set, add `flow_data["_last_updated"] = time.time()` in the collector's update path. Without this, `flow_age` will always be `None` and freshness decay is silently disabled.

In `backend/app/main.py`, before the `compute_order_flow_score` call, compute the age:

```python
    flow_updated = flow_metrics.get("_last_updated")
    flow_age = (time.time() - flow_updated) if flow_updated else None
```

And pass it:

```python
    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=flow_history,
        trend_conviction=tech_result["indicators"].get("trend_conviction", 0.0),
        mr_pressure=tech_result.get("mr_pressure", 0.0),
        flow_age_seconds=flow_age,
        asset_scale=asset_scale,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowFreshnessDecay -v`
Expected: PASS

---

### Task 10: Order Book Depth Integration (Issue 8)

Add book imbalance as 5th order flow component.

**Files:**
- Modify: `backend/app/main.py` (book imbalance computation before scorer call)
- Modify: `backend/app/engine/traditional.py` (book_score in scorer)

- [ ] **Step 1: Write failing test — book imbalance scoring**

```python
class TestOrderFlowBookImbalance:
    def test_bid_heavy_book_positive_score(self):
        """More bids than asks → positive book_score."""
        result = compute_order_flow_score({"book_imbalance": 0.6})
        assert result["details"]["book_score"] > 0

    def test_ask_heavy_book_negative_score(self):
        """More asks than bids → negative book_score."""
        result = compute_order_flow_score({"book_imbalance": -0.6})
        assert result["details"]["book_score"] < 0

    def test_absent_book_zero_score(self):
        """No book_imbalance key → book_score = 0."""
        result = compute_order_flow_score({"funding_rate": 0.001})
        assert result["details"]["book_score"] == 0.0

    def test_book_imbalance_in_confidence(self):
        """book_imbalance present should increase sources_available."""
        result_with = compute_order_flow_score({
            "funding_rate": 0.001, "book_imbalance": 0.3
        })
        result_without = compute_order_flow_score({"funding_rate": 0.001})
        # With book: 2/2 sources. Without book: 1/1. Both are 1.0.
        # Better test: check book shows up in score
        assert result_with["details"]["book_score"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowBookImbalance -v`
Expected: FAIL — `book_score` not in details

- [ ] **Step 3: Add book imbalance scoring to compute_order_flow_score**

In the scorer, after the CVD scoring block and before the `total = ...` line:

```python
    # Book imbalance — directional, NOT contrarian (max +/-BOOK_MAX)
    book_imbalance = metrics.get("book_imbalance")
    if book_imbalance is not None:
        book_score = sigmoid_score(book_imbalance, center=0, steepness=BOOK_STEEPNESS) * BOOK_MAX
    else:
        book_score = 0.0

    total = funding_score + oi_score + ls_score + cvd_score + book_score
```

**Important:** This block now reads `book_imbalance` from metrics before the confidence block, making the placeholder `book_imbalance = metrics.get("book_imbalance")` added in Task 4 Step 3 redundant. **Remove that placeholder line** to avoid duplicate assignment.

Add to details:

```python
        "book_score": round(book_score, 1),
```

- [ ] **Step 4: Add book imbalance computation in main.py**

In `backend/app/main.py`, before the `compute_order_flow_score` call, after the CVD injection block:

```python
    # Inject book imbalance if fresh depth data available
    # 30s hard limit is a data-validity gate (not a tunable scoring param) —
    # stale depth snapshots are unreliable due to spoofing/cancellation
    depth = app.state.order_book.get(pair)
    if depth and depth.get("bids") and depth.get("asks"):
        book_age = time.time() - depth.get("_last_updated", 0)
        if book_age <= 30:
            bid_vol = sum(size for _, size in depth["bids"])
            ask_vol = sum(size for _, size in depth["asks"])
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                flow_metrics["book_imbalance"] = (bid_vol - ask_vol) / total_vol
```

- [ ] **Step 5: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowBookImbalance -v`
Expected: PASS

---

### Task 11: Integration Test

Verify full scorer works with all new parameters together.

**Files:**
- Test: `backend/tests/engine/test_traditional.py`

- [ ] **Step 1: Write integration test**

```python
class TestOrderFlowIntegration:
    def test_full_scorer_all_params(self):
        """Full call with all new parameters — score in [-100, 100], all detail fields present."""
        regime = {"trending": 0.3, "ranging": 0.3, "volatile": 0.2, "steady": 0.2}
        snapshots = _make_snapshots(
            [0.0001] * 7 + [0.0005] * 3,
            [1.1] * 10,
            [0.01] * 7 + [0.05] * 3,
        )
        metrics = {
            "funding_rate": -0.0003,
            "open_interest_change_pct": 0.03,
            "price_direction": 1,
            "long_short_ratio": 1.3,
            "cvd_delta": 200.0,
            "cvd_history": [i * 50 for i in range(1, 11)],
            "avg_candle_volume": 1000.0,
            "book_imbalance": 0.25,
        }
        result = compute_order_flow_score(
            metrics,
            regime=regime,
            flow_history=snapshots,
            trend_conviction=0.4,
            mr_pressure=0.2,
            flow_age_seconds=100,  # fresh
            asset_scale=0.85,
        )
        assert -100 <= result["score"] <= 100
        details = result["details"]
        expected_keys = [
            "funding_score", "oi_score", "ls_score", "cvd_score", "book_score",
            "contrarian_mult", "roc_boost", "final_mult", "asset_scale",
            "funding_roc", "ls_roc", "oi_roc", "max_roc", "trend_conviction",
            "flow_age_seconds", "freshness_decay",
        ]
        for key in expected_keys:
            assert key in details, f"Missing detail key: {key}"
        assert result["confidence"] > 0.0

    def test_full_scorer_stale_data(self):
        """Fully stale data → confidence = 0."""
        result = compute_order_flow_score(
            {"funding_rate": 0.001, "long_short_ratio": 1.5},
            flow_age_seconds=1200,
        )
        assert result["confidence"] == 0.0
        # Score is still computed (direction preserved), only confidence zeroed
        assert result["score"] != 0

    def test_score_clamped_at_extremes(self):
        """Extreme inputs across all 5 components still clamp to [-100, 100]."""
        metrics = {
            "funding_rate": -0.05,
            "open_interest_change_pct": 10.0,
            "price_direction": 1,
            "long_short_ratio": 0.2,
            "cvd_delta": 50000.0,
            "avg_candle_volume": 100.0,
            "book_imbalance": 0.95,
        }
        result = compute_order_flow_score(metrics)
        assert -100 <= result["score"] <= 100
```

- [ ] **Step 2: Run integration test**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowIntegration -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: ALL PASS. If any existing tests fail due to the max score rebalance (22 instead of 30/20), update their threshold assertions. Direction tests should pass unchanged. The `TestOrderFlowRegimeScaling::test_trending_regime_reduces_contrarian` ratio check (0.25-0.40) should still hold since the ratio depends on `contrarian_mult`, not max scores.

---

### Task 12: ALGORITHM.md Update

Update the Order Flow Scoring section to reflect all changes.

**Files:**
- Modify: `docs/ALGORITHM.md:202-253` (Section 4)

- [ ] **Step 1: Rewrite Section 4**

Replace `docs/ALGORITHM.md` lines 202-253 with:

```markdown
## 4. Order Flow Scoring

**File:** `engine/traditional.py` (`compute_order_flow_score`)

Applies contrarian bias on derivatives market metrics, modulated by regime and rate-of-change detection. Directional metrics (OI, CVD, book) are regime-independent.

### 4.1 Regime-Aware Contrarian Multiplier

```
contrarian_mult = 1.0 - (trending_strength * (1.0 - trending_floor))
```

- `trending_floor = 0.3`: even in strong trends, at least 30% contrarian signal preserved
- Ranging market: full contrarian (1.0x)
- Strong trending market: reduced contrarian (~0.3x)
- Mean-reversion pressure relaxes the floor toward 1.0

### 4.2 Rate-of-Change Override

Tracks 10 candle flow history (3 recent + 7 baseline). If funding rate, L/S ratio, or OI change rapidly:

```
roc_boost = sigmoid_scale(max_roc, center=0.0005, steepness=8000)
final_mult = contrarian_mult + roc_boost * (1 - contrarian_mult)
```

Rapid shifts in crowd positioning or commitment increase contrarian sensitivity even in trends.

### 4.3 Trend Conviction Dampening

```
final_mult = min(final_mult, 1.0 - trend_conviction)
```

High trend conviction further suppresses contrarian order flow signals.

### 4.4 Five Scoring Components

| Component | Max Score | Logic | Type | Regime-Affected |
|-----------|-----------|-------|------|-----------------|
| Funding Rate | +/-22 | Contrarian: negative funding = bullish | Contrarian | Yes |
| Open Interest Change | +/-22 | Directional: agrees with price direction | Directional | No |
| Long/Short Ratio | +/-22 | Contrarian: ratio > 1 (more longs) = bearish | Contrarian | Yes |
| CVD (trend) | +/-22 | Slope of last 5-10 candle deltas, normalized by volume | Directional | No |
| Book Imbalance | +/-12 | Top-5 bid/ask volume ratio | Directional | No |

Total max: +/-100. Contrarian components (funding, L/S) have per-asset sigmoid scaling to account for different market microstructure (e.g., WIF funding is 5-10x more volatile than BTC).

### 4.5 Price Direction

Uses 3-candle net move (`candles[-1].close - candles[-4].close`) instead of single-candle body to filter noise from dojis and small counter-trend candles.

### 4.6 CVD Trend Scoring

When >= 5 candle deltas are available, computes linear slope of last 10 deltas normalized by average volume. Falls back to single-candle delta/volume when insufficient history.

### 4.7 Confidence

```
inputs_present = count of keys that produced a scoring contribution
sources_available = count of keys present in metrics dict
confidence = inputs_present / sources_available
```

Key-based presence detection: `funding_rate=0.0` counts as present (not absent). OI requires nonzero price direction to produce a scoring contribution but still counts as available.

### 4.8 Freshness Decay

Stale flow data (WebSocket dropped) gets confidence-penalized, not score-penalized:

```
if age > fresh_seconds (300):
    decay = min(1.0, (age - 300) / (900 - 300))
    confidence *= (1.0 - decay)
```

This causes the combiner to redistribute weight to fresher sources (tech, patterns) rather than zeroing out the directional signal.

### 4.9 Per-Asset Sigmoid Calibration

Asset scales multiply contrarian steepnesses (funding, L/S):

| Asset | Scale | Effect |
|-------|-------|--------|
| BTC-USDT-SWAP | 1.0 | Baseline |
| ETH-USDT-SWAP | 0.85 | Slightly wider S-curve |
| WIF-USDT-SWAP | 0.4 | Much wider — preserves discrimination at extreme funding |
```

- [ ] **Step 2: Verify the markdown renders correctly**

Read the file back and confirm no formatting issues.

---

### Task 13: Commit

- [ ] **Step 1: Run full test suite one final time**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Commit**

```bash
git add backend/app/engine/constants.py backend/app/engine/traditional.py backend/app/engine/param_groups.py backend/app/main.py backend/tests/engine/test_traditional.py docs/ALGORITHM.md
git commit -m "feat(engine): order flow scoring overhaul — 9 fixes

- Replace hardcoded max score literals with constants from ORDER_FLOW
- Fix zero-value confidence bug (key-based presence, not value-based)
- Add freshness decay for stale flow data (confidence penalty)
- Rebalance max scores: 22/22/22/22/12 (funding/oi/ls/cvd/book)
- Add per-asset sigmoid calibration (BTC 1.0, ETH 0.85, WIF 0.4)
- Upgrade CVD to trend-based slope scoring (5-10 candle history)
- Add OI to flow history RoC computation
- Integrate order book depth as 5th scoring component
- Stabilize price direction to 3-candle net move
- Expand order_flow param group to 12 tunable parameters
- Update ALGORITHM.md section 4"
```
