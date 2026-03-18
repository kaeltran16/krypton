# Order Flow Contrarian Bias — Design Spec

## Problem

Order flow scoring (funding rate and long/short ratio) is always fully contrarian — high funding = bearish, many longs = bearish. In strong trends, crowded positioning can sustain for weeks, producing premature reversal signals that fight momentum.

## Approach

Two orthogonal modifiers applied to the funding rate (±35) and L/S ratio (±35) contrarian scores:

1. **Regime-based contrarian scaling** — reduces contrarian strength in trending markets
2. **Rate-of-change override** — restores contrarian strength when funding/LS are rapidly spiking (blowoff detection)

OI change scoring (±20) is already direction-aware and is not modified.

## Detailed Design

### 1. Function Signature Change

`compute_order_flow_score()` in `engine/traditional.py` gains two optional parameters:

```python
from app.db.models import OrderFlowSnapshot

def compute_order_flow_score(
    metrics: dict,
    regime: dict | None = None,                        # {"trending": float, "ranging": float, "volatile": float}
    flow_history: list[OrderFlowSnapshot] | None = None, # recent snapshots, oldest first
) -> dict:
```

- `regime=None` → multiplier defaults to 1.0 (full contrarian, backward compatible)
- `flow_history=None` or fewer than 10 rows → RoC override disabled, only regime scaling applies

The function accesses snapshot fields via attribute access (`snap.funding_rate`, `snap.long_short_ratio`), avoiding key-name confusion between ORM columns and the ephemeral `app.state.order_flow` dict.

### 2. Regime-Based Contrarian Scaling

The trending component of the regime mix controls how much the contrarian signal is dampened:

```
TRENDING_FLOOR = 0.3

contrarian_mult = 1.0 - (regime["trending"] * (1.0 - TRENDING_FLOOR))
```

Clamp to `[TRENDING_FLOOR, 1.0]` defensively (regime dict is always normalized by `compute_regime_mix()`, but protects against unexpected inputs).

Examples:
- Pure ranging (trending=0.0): `1.0 - (0.0 * 0.7) = 1.0` — full contrarian
- Pure trending (trending=1.0): `1.0 - (1.0 * 0.7) = 0.3` — mild contrarian
- Mixed (trending=0.5): `1.0 - (0.5 * 0.7) = 0.65` — moderate contrarian

Only the `trending` weight matters. Volatile regime doesn't need its own floor — volatile + weak trend = ranging-like (keep contrarian), volatile + strong trend = trending dominates anyway.

Applied to funding and L/S scores only (using `final_mult` after RoC override, see section 3):

```
funding_score = sigmoid_score(-funding, center=0, steepness=8000) * 35 * final_mult
ls_score = sigmoid_score(1.0 - ls, center=0, steepness=6) * 35 * final_mult
```

### 3. Rate-of-Change Override

Detects rapid spikes in funding/LS that signal potential blowoff tops/bottoms, restoring contrarian strength regardless of regime.

**Computation from `flow_history` (last 10 snapshots):**

Split into recent window (last 3) and baseline window (previous 7):

```
funding_roc = avg(recent_3_funding) - avg(baseline_7_funding)
ls_roc = avg(recent_3_ls) - avg(baseline_7_ls)
```

Normalize L/S RoC to funding rate scale. The scaling factor aligns magnitudes so neither field dominates `max()` — initial value based on typical OKX ranges, should be validated empirically:

```
LS_ROC_SCALE = 0.003
ls_roc_scaled = ls_roc * LS_ROC_SCALE
max_roc = max(abs(funding_roc), abs(ls_roc_scaled))
```

**RoC boost:**

```
ROC_THRESHOLD = 0.0005
ROC_STEEPNESS = 8000

roc_boost = sigmoid_scale(max_roc, center=ROC_THRESHOLD, steepness=ROC_STEEPNESS)
final_mult = contrarian_mult + roc_boost * (1.0 - contrarian_mult)
```

- `ROC_THRESHOLD = 0.0005` — sigmoid center. Typical sustained funding RoC is well below this (0.00001-0.0001 range), so `sigmoid_scale` returns near 0. Blowoff spikes push RoC above this center, producing `roc_boost` above 0.5 and toward 1.0.
- `ROC_STEEPNESS = 8000` — matches the steepness used for funding rate scoring itself. Creates a sharp transition: values below threshold produce near-zero boost, values above produce near-full boost.
- Low `max_roc` (stable/sustained positioning): `roc_boost ≈ 0`, regime scaling applies normally
- High `max_roc` (rapid spike): `roc_boost → 1.0`, multiplier restored toward 1.0 (full contrarian)
- Formula `mult + boost * (1 - mult)` ensures result never exceeds 1.0

**Named constants (tunable via backtesting):**

```
RECENT_WINDOW = 3
BASELINE_WINDOW = 7
TOTAL_SNAPSHOTS = RECENT_WINDOW + BASELINE_WINDOW  # 10
```

**Edge cases:**
- Fewer than 10 snapshots: skip RoC computation, use regime scaling only
- Missing funding or LS in some snapshots: compute each field's RoC independently. Minimum requirement per field: at least 1 non-null value in the baseline window AND at least 1 non-null value in the recent window. If a field doesn't meet this, its RoC = 0 (excluded from `max_roc`). If neither field has sufficient data, `roc_boost = 0`.

### 4. Pipeline Integration

In `main.py`, before calling `compute_order_flow_score()`:

1. Query last 10 `OrderFlowSnapshot` rows for the current pair, ordered by timestamp ascending. `OrderFlowSnapshot` has no `timeframe` column — funding rate, OI, and L/S ratio are exchange-level per-pair metrics, not per-timeframe. This is correct: all timeframes for the same pair should see the same flow history.
2. Pass `regime` from `tech_result["regime"]` (returned by `compute_technical_score()`) and the snapshot rows as `flow_history`

No changes to anything downstream — function still returns `{"score": int, "details": dict}`.

### 5. Observability

Extended details dict for debuggability. Raw input metrics are preserved (the LLM prompt at `main.py:483` passes `flow_result["details"]` as JSON context — it needs access to actual funding rate, OI, and L/S values for analysis). Computed diagnostic fields are added alongside:

```python
"details": {
    # raw input metrics (preserved for LLM context)
    "funding_rate": 0.0003,       # raw funding rate value
    "open_interest": 150000000,   # raw OI value
    "open_interest_change_pct": 0.02,  # raw OI change
    "long_short_ratio": 1.8,     # raw L/S ratio
    "price_direction": 1,        # candle direction
    # computed scores
    "funding_score": -10.5,       # after regime scaling
    "oi_score": 12.0,             # unchanged
    "ls_score": -8.2,             # after regime scaling
    # regime/RoC diagnostics
    "contrarian_mult": 0.3,       # regime-derived multiplier
    "roc_boost": 0.0,             # rate-of-change override strength
    "final_mult": 0.3,            # effective multiplier after RoC
    "funding_roc": 0.00002,       # raw funding rate-of-change
    "ls_roc": 0.05,               # raw L/S rate-of-change
    "max_roc": 0.00015,           # normalized max RoC used for boost calc
}
```

Note: the current function returns `{"score": score, "details": metrics}` where `details` is the raw input metrics dict passed through. The new `details` dict merges the original raw metrics with computed diagnostic fields. This preserves LLM context (raw values) while adding observability (scores and multipliers). No downstream code reads individual fields from `details` — combiner uses only `flow_result["score"]`.

These flow through to `Signal.raw_indicators` JSONB — no schema changes needed.

### 6. Data Source

Historical flow data comes from `OrderFlowSnapshot` table (already persisted per candle). Query is a simple indexed lookup on `(pair)` ordered by timestamp descending, limited to 10 rows. The table's existing index on `("pair", "timestamp")` covers this query.

## Testing Strategy

Unit tests in `test_traditional.py`:

1. **Regime scaling** — pure ranging gives full contrarian scores, pure trending gives ~30% strength, mixed regimes interpolate
2. **RoC override** — stable history keeps regime scaling, spiking history restores toward full contrarian
3. **Backward compatibility** — `regime=None, flow_history=None` produces identical scores to current behavior
4. **OI unchanged** — OI score not affected by regime or RoC
5. **Bounds** — score still clamped to [-100, +100] under all modifier combinations
6. **Insufficient history** — fewer than 10 snapshots disables RoC gracefully

Integration test in existing `test_pipeline.py` (extend the 2 existing order flow tests):

7. **End-to-end** — pipeline passes regime mix and flow history through, signal includes new detail fields

## What Does NOT Change

- OI change scoring logic
- Score range (-100 to +100)
- Combiner, outer weights, LLM gate — all downstream unchanged
- `OrderFlowSnapshot` schema — no new columns
- Signal schema — new fields in existing JSONB columns
