# Design: Order Flow Scoring Overhaul

**Date:** 2026-03-26
**Status:** Draft
**Scope:** Backend signal engine — `engine/traditional.py` (`compute_order_flow_score`), `engine/constants.py`, `main.py` pipeline integration

---

## Problem Statement

The order flow scorer has 8 issues ranging from bugs to missing capabilities. Together they reduce signal quality: stale data gets scored at full weight, present-but-neutral data is treated as absent, single-candle noise drives OI scoring, and all three assets share identical sigmoid calibrations despite very different market microstructure.

### Issue Summary

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| 1 | Single-candle `price_direction` for OI scoring | High | `main.py:462` |
| 2 | Zero-value treated as absent in confidence | Bug | `traditional.py:528-533` |
| 3 | No freshness decay for stale flow data | High | `traditional.py` / `main.py` |
| 4 | Funding + L/S correlation double-counting | Medium | `traditional.py:481,493` / `constants.py:31` |
| 5 | No per-asset sigmoid calibration | Medium | `constants.py:32` |
| 6 | CVD is single-candle delta, not trend | Medium | `main.py:468-469` / `traditional.py:496-502` |
| 7 | Flow history query misses OI | Low | `main.py:479` |
| 8 | Order book depth collected but unused | Medium | `main.py:85-92` |
| 9 | Scorer hardcodes literals, new params missing from param_groups | Medium | `traditional.py`, `param_groups.py` |

---

## Issue 1: Single-Candle Price Direction

### Problem

OI scoring depends on `price_direction`, which is derived from a single candle's body:

```python
# main.py:462
"price_direction": 1 if candle["close"] > candle["open"] else (-1 if ...)
```

A doji or small counter-trend candle in the middle of a strong uptrend sets `price_dir = -1`, flipping OI's contribution to bearish. This is noise, not signal.

### Solution

Replace single-candle body direction with a 3-candle net move direction. This is stable enough to filter noise but responsive enough to catch actual reversals.

**In `main.py`, before building `flow_metrics`:**

```python
# Use recent 3-candle net move instead of single candle body
recent_close = float(candle["close"])
lookback_close = float(candles_data[-4]["close"]) if len(candles_data) >= 4 else float(candle["open"])
net_move = recent_close - lookback_close
price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
```

The `candles_data` list is already available from the Redis fetch at `main.py:386`. Pass the computed direction into `flow_metrics` instead of the current single-candle logic. Note: the `len(candles_data) >= 4` guard is defensive — the pipeline already enforces `>= 70` candles — but it's kept for robustness since the fallback is free.

### Backward Compatibility

`compute_order_flow_score` still receives `price_direction` as `1`, `-1`, or `0` — no signature change needed. Only the caller changes.

---

## Issue 2: Zero-Value = Absent Confidence Bug

### Problem

```python
inputs_present = sum([
    funding != 0.0,          # funding CAN be exactly 0.0
    oi_change != 0.0 and price_dir != 0,
    ls != 1.0,               # L/S of exactly 1.0 is real data
    cvd_delta is not None and avg_vol > 0 and cvd_delta != 0.0,
])
```

When funding is exactly `0.0`, it's counted as absent even though it was received — perfectly balanced funding is informative data. Same for L/S ratio of `1.0`. This deflates confidence when all data is present.

### Solution

Track presence based on whether the metric was provided in the input dict, not whether its value is nonzero.

```python
inputs_present = sum([
    "funding_rate" in metrics,
    "open_interest_change_pct" in metrics and "price_direction" in metrics and price_dir != 0,
    "long_short_ratio" in metrics,
    cvd_delta is not None and avg_vol > 0,
])
sources_available = sum([
    "funding_rate" in metrics,
    "open_interest_change_pct" in metrics,
    "long_short_ratio" in metrics,
    cvd_delta is not None,
])
```

Both `inputs_present` and `sources_available` are now key-based, replacing the old hardcoded `3 + (1 if cvd ...)`. The distinction: `sources_available` counts what data was provided (regardless of value), while `inputs_present` counts what data produced a nonzero scoring contribution. The `price_dir != 0` check stays for OI in `inputs_present` because OI scoring is genuinely undefined when price direction is flat — it's not about data absence, it's about the scoring model not applying. But OI still counts toward `sources_available` because the data is present.

### Test Impact

- `test_three_legacy_sources_full_confidence` — passes (all keys present)
- `test_only_funding_partial_confidence` — passes (only `funding_rate` key in dict)
- New test: `test_zero_funding_still_counts_as_present` — `{"funding_rate": 0.0}` should give confidence `1/3`, not `0/3`

---

## Issue 3: Freshness Decay for Stale Data

### Problem

`_last_updated` timestamps are stored on `app.state.order_flow[pair]` and `app.state.cvd[pair]`, but the scorer never sees them. If the WebSocket drops for 30 minutes, stale funding/OI/L/S values are scored at full weight. The watchdog logs staleness but doesn't act on it.

### Solution

Pass `flow_age_seconds` into `compute_order_flow_score`. Apply a confidence penalty that ramps from 0 at fresh data to 1.0 (total discount) at fully stale data.

**New parameter:**

```python
def compute_order_flow_score(
    metrics: dict,
    regime: dict | None = None,
    flow_history: list | None = None,
    trend_conviction: float = 0.0,
    mr_pressure: float = 0.0,
    flow_age_seconds: float | None = None,  # NEW
) -> dict:
```

**Freshness penalty (applied to confidence only, not score):**

```python
FLOW_FRESH_SECONDS = 300    # 5 min — data is fresh
FLOW_STALE_SECONDS = 900    # 15 min — data is fully stale

if flow_age_seconds is not None and flow_age_seconds > FLOW_FRESH_SECONDS:
    decay = min(1.0, (flow_age_seconds - FLOW_FRESH_SECONDS) / (FLOW_STALE_SECONDS - FLOW_FRESH_SECONDS))
    flow_confidence *= (1.0 - decay)
```

Rationale for confidence-not-score: the combiner already uses confidence to weight sources. Decaying confidence causes the combiner to redistribute weight to fresher sources (tech, patterns) rather than zeroing out the flow score, which preserves the directional signal but reduces its influence.

**Caller change in `main.py`:**

```python
flow_updated = flow_metrics.get("_last_updated")
flow_age = (time.time() - flow_updated) if flow_updated else None

flow_result = compute_order_flow_score(
    flow_metrics,
    ...,
    flow_age_seconds=flow_age,
)
```

Note: strip `_last_updated` from `flow_metrics` before passing (or ignore unknown keys in the scorer). Currently the scorer uses `.get()` on all keys, so unknown keys are harmless.

**Known simplification:** A single `flow_age_seconds` applies the same freshness penalty to all components, including CVD. If the flow WebSocket drops but the trades WebSocket (CVD source) stays up, CVD data is fresh but still gets confidence-penalized. This is acceptable for now — if the flow WS is down, the composite quality is degraded and redistributing weight to tech/patterns is reasonable. A future refinement could use per-component ages (e.g., `min(flow_age, cvd_age)`) but adds complexity without clear payoff at this stage.

### Constants

Add to `ORDER_FLOW` in `constants.py`:

```python
"freshness_fresh_seconds": 300,
"freshness_stale_seconds": 900,
```

---

## Issue 4: Funding/L/S Correlation Double-Counting

### Problem

Funding rate and L/S ratio both measure directional crowd positioning. When longs are crowded: funding goes positive AND L/S goes above 1. Giving them 30 + 30 = 60 points out of 100 means the score is ~60% driven by a single axis of information. Meanwhile OI and CVD (genuinely different signals — commitment and execution) only get 20 + 20.

### Solution

Rebalance max scores to reduce the correlated pair's dominance:

| Component | Current Max | New Max | Rationale |
|-----------|------------|---------|-----------|
| Funding Rate | 30 | 25 | Still the most reliable single metric |
| L/S Ratio | 30 | 25 | Correlated with funding — reduce combined weight |
| OI Change | 20 | 25 | Independent signal (commitment), deserves parity |
| CVD Delta | 20 | 25 | Independent signal (execution), deserves parity |

Total stays at 100. The change flattens the contribution from 60/40 (correlated vs independent) to 50/50.

**Update in `constants.py`:**

```python
"max_scores": {"funding": 25, "oi": 25, "ls_ratio": 25, "cvd": 25},
```

**Update in `traditional.py`:** Replace hardcoded `30`, `20`, `30`, `20` with constants:

```python
FUNDING_MAX = ORDER_FLOW["max_scores"]["funding"]
OI_MAX = ORDER_FLOW["max_scores"]["oi"]
LS_MAX = ORDER_FLOW["max_scores"]["ls_ratio"]
CVD_MAX = ORDER_FLOW["max_scores"]["cvd"]

funding_score = sigmoid_score(-funding, ...) * FUNDING_MAX * final_mult
oi_score = price_dir * sigmoid_score(oi_change, ...) * OI_MAX
ls_score = sigmoid_score(1.0 - ls, ...) * LS_MAX * final_mult
cvd_score = sigmoid_score(cvd_normalized, ...) * CVD_MAX
```

Currently the max scores in `constants.py` exist but the scorer uses hardcoded literals. This fix also eliminates the duplication.

**Update param_groups.py constraints:**

```python
"constraints": lambda c: (
    c.get("funding_max", 0) + c.get("oi_max", 0) + c.get("ls_ratio_max", 0) + c.get("cvd_max", 0) <= 100
    ...
),
```

Add `cvd_max` and `cvd_steepness` to the `order_flow` param group sweep ranges.

---

## Issue 5: Per-Asset Sigmoid Calibration

### Problem

All three pairs use identical sigmoid steepnesses. WIF regularly has funding rates 5-10x higher than BTC due to lower liquidity and higher speculative interest. With steepness 400, WIF's funding score saturates at +/-25 most of the time, losing discrimination between "moderately crowded" and "dangerously crowded."

### Solution

Add per-asset steepness profiles that scale the base steepness by a volatility tier multiplier. This avoids a full per-asset constant table while still providing meaningful differentiation.

**New structure in `constants.py`:**

```python
ORDER_FLOW_ASSET_SCALES = {
    "BTC-USDT-SWAP": 1.0,       # baseline
    "ETH-USDT-SWAP": 0.85,      # slightly more volatile funding
    "WIF-USDT-SWAP": 0.4,       # much more volatile — halve steepness to preserve discrimination
}
```

The scale multiplies the steepness: `effective_steepness = base_steepness * asset_scale`. Lower steepness = wider S-curve = more discrimination at extreme values.

**New parameter on `compute_order_flow_score`:**

```python
def compute_order_flow_score(
    metrics: dict,
    ...,
    asset_scale: float = 1.0,  # NEW — per-asset sigmoid scaling
) -> dict:
```

**Applied to contrarian components only** (funding + L/S). OI and CVD are already normalized (percentage and volume-ratio respectively), so they don't need asset scaling.

```python
funding_steepness = FUNDING_STEEPNESS * asset_scale
ls_steepness = LS_STEEPNESS * asset_scale

funding_score = sigmoid_score(-funding, center=0, steepness=funding_steepness) * FUNDING_MAX * final_mult
ls_score = sigmoid_score(1.0 - ls, center=0, steepness=ls_steepness) * LS_MAX * final_mult
```

**Caller in `main.py`:**

```python
from app.engine.constants import ORDER_FLOW_ASSET_SCALES
asset_scale = ORDER_FLOW_ASSET_SCALES.get(pair, 1.0)

flow_result = compute_order_flow_score(
    flow_metrics,
    ...,
    asset_scale=asset_scale,
)
```

Expose `asset_scale` in `details` dict for diagnostics.

**API visibility:** Add `ORDER_FLOW_ASSET_SCALES` to `get_engine_constants()` so the parameter tree exposed via `GET /api/engine/parameters` includes per-asset scaling for debugging:

```python
"order_flow": {
    ...,
    "asset_scales": _wrap(ORDER_FLOW_ASSET_SCALES),
},
```

---

## Issue 6: CVD as Trend, Not Single-Candle Delta

### Problem

```python
cvd_delta_val = cvd_state["candle_delta"]
cvd_state["candle_delta"] = 0.0  # reset after read
```

A single candle's net buy/sell volume is noisy. The technical scorer uses OBV slope over 10 candles for volume confirmation — CVD should get similar treatment.

### Solution

Maintain a rolling CVD history (last 10 candle deltas) in `app.state.cvd[pair]` and pass the trend slope to the scorer instead of (or alongside) the raw delta.

**State change in `main.py`:**

```python
# In handle_candle, after reading cvd_delta_val:
if cvd_state:
    cvd_delta_val = cvd_state["candle_delta"]
    cvd_state["candle_delta"] = 0.0

    # Maintain rolling history
    history = cvd_state.setdefault("history", [])
    history.append(cvd_delta_val)
    if len(history) > 10:
        history.pop(0)

    flow_metrics["cvd_delta"] = cvd_delta_val
    flow_metrics["cvd_history"] = list(history)  # copy to avoid mutation
    flow_metrics["avg_candle_volume"] = float(candle.get("volume", 0))
```

**Scoring change in `traditional.py`:**

When `cvd_history` has >= 5 entries, compute a slope-based score (same approach as OBV). When insufficient history, fall back to single-delta scoring.

```python
cvd_history = metrics.get("cvd_history")
if cvd_history and len(cvd_history) >= 5 and avg_vol > 0:
    # Slope of last N deltas, normalized by average volume
    arr = np.array(cvd_history[-10:])
    x = np.arange(len(arr))
    slope = np.polyfit(x, arr, 1)[0]
    cvd_normalized = slope / avg_vol
    cvd_score = sigmoid_score(cvd_normalized, center=0, steepness=CVD_STEEPNESS) * CVD_MAX
elif cvd_delta is not None and avg_vol > 0:
    # Fallback: single-candle delta (startup / insufficient history)
    cvd_normalized = cvd_delta / avg_vol
    cvd_score = sigmoid_score(cvd_normalized, center=0, steepness=CVD_STEEPNESS) * CVD_MAX
else:
    cvd_score = 0.0
```

**CVD steepness recalibration:** The slope-based normalization produces smaller values than the single-delta normalization. Increase CVD steepness from `3` to `5` to compensate. This should be verified empirically by checking score distributions on recent data.

**Update in `constants.py`:**

```python
"sigmoid_steepnesses": {"funding": 400, "oi": 20, "ls_ratio": 6, "cvd": 5},
```

This change is independent of Issue 8. If Issue 8 lands, it adds `"book": 4` to this same dict.

---

## Issue 7: Flow History Query Misses OI

### Problem

```python
# main.py:479
select(OrderFlowSnapshot.funding_rate, OrderFlowSnapshot.long_short_ratio)
    .where(OrderFlowSnapshot.pair == pair)
    .order_by(OrderFlowSnapshot.timestamp.desc())
    .limit(10)
```

Only `funding_rate` and `long_short_ratio` are fetched. OI momentum (rapid OI expansion/contraction) is one of the strongest flow signals — the data is persisted in `OrderFlowSnapshot.oi_change_pct` but never queried for RoC.

### Solution

Add `oi_change_pct` to the query and compute OI RoC alongside funding and L/S RoC.

**Query change in `main.py`:**

```python
select(
    OrderFlowSnapshot.funding_rate,
    OrderFlowSnapshot.long_short_ratio,
    OrderFlowSnapshot.oi_change_pct,
).where(...)
```

**RoC computation in `traditional.py`:** Add OI RoC to the existing block:

```python
oi_roc, has_oi = _field_roc(baseline, recent, lambda s: s.oi_change_pct)

if has_funding or has_ls or has_oi:
    ls_roc_scaled = ls_roc * LS_ROC_SCALE
    max_roc = max(abs(funding_roc), abs(ls_roc_scaled), abs(oi_roc))
    roc_boost = sigmoid_scale(max_roc, center=ROC_THRESHOLD, steepness=ROC_STEEPNESS)
```

OI RoC doesn't need the `LS_ROC_SCALE` treatment because OI change is already a percentage, similar in magnitude to funding rate changes.

**Expose in details:**

```python
"oi_roc": round(oi_roc, 8),
```

### Snapshot mock update

`_make_snapshots` test helper needs a third field:

```python
def _make_snapshots(funding_rates, ls_ratios=None, oi_changes=None):
    if ls_ratios is None:
        ls_ratios = [1.0] * len(funding_rates)
    if oi_changes is None:
        oi_changes = [0.0] * len(funding_rates)
    return [
        SimpleNamespace(funding_rate=fr, long_short_ratio=ls, oi_change_pct=oi)
        for fr, ls, oi in zip(funding_rates, ls_ratios, oi_changes)
    ]
```

Existing callers pass only `funding_rates` and `ls_ratios` — they continue working unchanged since `oi_changes` defaults to zeros.

---

## Issue 8: Order Book Depth Integration

### Problem

`handle_depth` stores top-5 bid/ask data to `app.state.order_book[pair]` with timestamps, and it's passed to liquidation scoring. But order flow scoring never sees it. Bid/ask imbalance is a strong short-term directional signal.

### Solution

Compute a book imbalance ratio from the top-5 depth and pass it as a 5th order flow component. This is a **directional** signal (not contrarian), similar to OI and CVD.

**Imbalance computation in `main.py` (before calling `compute_order_flow_score`):**

```python
depth = order_book.get(pair)
if depth and depth.get("bids") and depth.get("asks"):
    # Gate: stale book data (>30s) is misleading — skip entirely
    book_age = time.time() - depth.get("_last_updated", 0)
    if book_age <= 30:
        bid_vol = sum(size for _, size in depth["bids"])
        ask_vol = sum(size for _, size in depth["asks"])
        total = bid_vol + ask_vol
        if total > 0:
            # Range: -1.0 (all asks) to +1.0 (all bids)
            flow_metrics["book_imbalance"] = (bid_vol - ask_vol) / total
```

**Scoring in `traditional.py`:**

```python
# Book imbalance — directional, NOT contrarian (max +/-BOOK_MAX)
book_imbalance = metrics.get("book_imbalance")
if book_imbalance is not None:
    book_score = sigmoid_score(book_imbalance, center=0, steepness=BOOK_STEEPNESS) * BOOK_MAX
else:
    book_score = 0.0

total = funding_score + oi_score + ls_score + cvd_score + book_score
```

**Max score rebalance with book imbalance:**

Adding a 5th component means rebalancing to keep total at 100:

| Component | New Max | Type |
|-----------|---------|------|
| Funding Rate | 22 | Contrarian |
| L/S Ratio | 22 | Contrarian |
| OI Change | 22 | Directional |
| CVD Delta | 22 | Directional |
| Book Imbalance | 12 | Directional |

Book imbalance gets a lower max because top-5 depth is shallow and easily spoofed. It's a weak but useful confirmation signal, not a primary driver.

**Constants:**

```python
"max_scores": {"funding": 22, "oi": 22, "ls_ratio": 22, "cvd": 22, "book": 12},
"sigmoid_steepnesses": {"funding": 400, "oi": 20, "ls_ratio": 6, "cvd": 5, "book": 4},
```

**Book steepness of 4:** Imbalance is already normalized to [-1, +1]. Steepness 4 means a 60/40 bid/ask split (imbalance = 0.2) produces ~38% of max = ~4.5 points. A 80/20 split (imbalance = 0.6) produces ~88% of max = ~10.6 points.

**Freshness:** Book depth staleness is handled at the caller level (see imbalance computation above): if `_last_updated` is older than 30 seconds, `book_imbalance` is never added to `flow_metrics`, so the scorer sees it as absent and produces `book_score = 0.0`. This is simpler than adding a second age parameter to the scorer and keeps the freshness gate visible at the call site. The 30-second threshold is appropriate for a real-time feed — unlike the 5-15 minute ramp for flow metrics (Issue 3), stale book data is actively misleading rather than just less useful.

**Confidence:** Book imbalance enters the same key-based confidence calculation (see Issue 2). Add to both `inputs_present` and `sources_available`:

```python
# In inputs_present:
book_imbalance is not None,
# In sources_available:
book_imbalance is not None,
```

**Param group update:** Add `book_max` and `book_steepness` to the `order_flow` param group in `param_groups.py`.

---

## Issue 9: Make All Parameters Optimizer-Tunable

### Problem

The scorer hardcodes max scores as literals (`30`, `20`, `30`, `20`) instead of reading from `ORDER_FLOW["max_scores"]`. The `order_flow` param group in `param_groups.py` defines 6 tunable params but is missing CVD entirely, and won't include the new book imbalance, asset scales, or freshness thresholds after this overhaul.

The optimizer currently skips `order_flow` as non-backtestable — that's a separate concern (needs signal-replay infrastructure). But the param group definition should still be complete so that:
1. The scorer reads all values from constants (not literals) — a promoted override takes effect
2. All new params are registered in `param_groups.py` with sweep ranges — ready for when signal-replay lands
3. The GroupHealthTable in the optimizer UI shows the full parameter set

### Solution

**Step 1: Scorer reads from constants (not hardcoded)**

This is already covered by Issue 4's fix — replace `30`, `20`, `30`, `20` with `FUNDING_MAX`, `OI_MAX`, `LS_MAX`, `CVD_MAX` read from `ORDER_FLOW["max_scores"]`. Extend to also read `BOOK_MAX` (Issue 8) and all steepnesses the same way. The scorer should have **zero hardcoded scoring constants**.

**Step 2: Register all new params in `param_groups.py`**

Current `order_flow` param group (6 params):

```python
"order_flow": {
    "params": {
        "funding_max": "order_flow.max_scores.funding",
        "oi_max": "order_flow.max_scores.oi",
        "ls_ratio_max": "order_flow.max_scores.ls_ratio",
        "funding_steepness": "order_flow.sigmoid_steepnesses.funding",
        "oi_steepness": "order_flow.sigmoid_steepnesses.oi",
        "ls_ratio_steepness": "order_flow.sigmoid_steepnesses.ls_ratio",
    },
    ...
}
```

Updated param group (12 params):

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

**Note on `ORDER_FLOW_ASSET_SCALES`:** Per-asset scales (Issue 5) are NOT added to param_groups. They are per-asset multipliers, not global tuning parameters — the optimizer sweeps one parameter set globally. Asset scales are static configuration that should be updated manually based on observed funding rate distributions per asset. If we later add per-asset optimizer sweeps, they'd become tunable then.

**Step 2b: Add PARAMETER_DESCRIPTIONS for new params**

Add to `PARAMETER_DESCRIPTIONS` in `constants.py`:

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

**Step 3: Scorer loads all constants at module level**

```python
# At top of traditional.py, alongside existing constant loading
FUNDING_MAX = ORDER_FLOW["max_scores"]["funding"]
OI_MAX = ORDER_FLOW["max_scores"]["oi"]
LS_MAX = ORDER_FLOW["max_scores"]["ls_ratio"]
CVD_MAX = ORDER_FLOW["max_scores"]["cvd"]
BOOK_MAX = ORDER_FLOW["max_scores"]["book"]
BOOK_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["book"]
FRESH_SECONDS = ORDER_FLOW["freshness_fresh_seconds"]
STALE_SECONDS = ORDER_FLOW["freshness_stale_seconds"]
```

**Note on runtime updates:** Module-level variables are set once at import — if the optimizer mutates the `ORDER_FLOW` dict at runtime, these variables remain stale until the next container restart. This is the same pattern the existing steepness constants (`FUNDING_STEEPNESS` etc.) already use. The benefit here is DRY/single-source-of-truth, not runtime hot-reloading. A future improvement could read directly from `ORDER_FLOW[...]` inside the function body for runtime pickup, but that's out of scope for this change.

---

## Interaction Between Issues

Several fixes interact and should be implemented in a specific order:

1. **Issue 9 (constants + param_groups)** — foundation. Replaces hardcoded literals with constants, registers all params. Do first so subsequent issues write against constants, not literals.
2. **Issue 2 (confidence bug)** — standalone, no dependencies.
3. **Issue 1 (price direction)** — standalone caller change.
4. **Issue 7 (OI in flow history)** — small query + RoC change.
5. **Issue 4 (score rebalancing)** — changes max scores in constants. Must land before Issue 8.
6. **Issue 5 (per-asset calibration)** — new parameter. Independent of 4 but test together.
7. **Issue 6 (CVD trend)** — state + scoring change. Independent.
8. **Issue 3 (freshness decay)** — new parameter + caller change. Reads freshness thresholds from constants (set up in Issue 9).
9. **Issue 8 (book depth)** — depends on Issue 4's rebalancing. Do last.

Issues 4 and 8 both touch `max_scores`. If both land, use the Issue 8 values (22/22/22/22/12) which supersede Issue 4's intermediate values (25/25/25/25). If Issue 8 is deferred, Issue 4's values stand.

---

## ALGORITHM.md Updates

The current ALGORITHM.md section 4 is stale (lists max +/-35 for funding/L/S, missing CVD). After implementation, update:

- Component table with new max scores and book imbalance
- Confidence calculation (presence-based, freshness decay)
- Price direction methodology (3-candle net move)
- CVD scoring (trend-based)
- Flow history RoC (now includes OI)
- Per-asset calibration note
- Freshness decay parameters

---

## Test Strategy

Each issue should have focused unit tests in `tests/engine/test_traditional.py`:

| Issue | Key Test Cases |
|-------|---------------|
| 1 | 3-candle direction: verify uptrend doji still produces `price_dir=1` |
| 2 | `{"funding_rate": 0.0}` → confidence = 1/3 (not 0/3); `{}` → confidence = 0/3 |
| 3 | `flow_age_seconds=0` → no penalty; `=600` → half confidence; `=900+` → zero confidence |
| 4 | Max scores sum to 100; extreme inputs still clamp to [-100, +100] |
| 5 | WIF scale 0.4 produces lower score than BTC scale 1.0 for same funding rate |
| 6 | CVD with 10-candle rising history scores higher than single positive delta |
| 7 | Spiking OI in flow history produces roc_boost > 0 |
| 8 | Bid-heavy book → positive book_score; ask-heavy → negative; absent → zero |
| 9 | Scorer uses no hardcoded score literals; all max_scores sum to 100 from constants; param_groups has 12 params with valid sweep ranges; constraint rejects sum > 100 |

Integration test: full `compute_order_flow_score` call with all new parameters, verify score in [-100, +100] and all detail fields present.
