# Liquidation Scoring Improvements

## Overview

Overhaul the liquidation scoring subsystem to fix four accuracy issues in the existing cluster scorer, add a new asymmetry ratio component, wire tunable parameters into the optimizer, and add diagnostic output.

## Current State

### Collector (`collector/liquidation.py`)
- `LiquidationCollector` polls OKX `/api/v5/public/liquidation-orders` every 5 minutes
- Maintains rolling 24-hour in-memory window per pair, persisted to Redis for restart recovery
- Each event: `{price, volume, timestamp, side}`

### Scorer (`engine/liquidation_scorer.py`)
- `aggregate_liquidation_buckets` groups events into 0.25 ATR price buckets with 4h exponential decay
- `detect_clusters` finds buckets exceeding 2x median volume
- `compute_liquidation_score` scores clusters within 2 ATR by proximity and density, returns `{score, confidence, clusters}`
- `_depth_modifier` adjusts cluster contribution [0.7, 1.3] based on order book depth

### Problems
1. **Side-blind direction**: cluster direction inferred from price position, ignoring the `side` field already collected
2. **Volume burst sensitivity**: no normalization per poll cycle; a burst of 100 events dominates buckets
3. **Fragile cluster detection**: simple median threshold is unstable with few buckets
4. **Depth modifier discontinuity**: 3-tier piecewise logic has a 0.15 jump at the ratio=0.5 boundary

---

## Design

### 1. Side-Aware Cluster Direction

**Change**: Use the `side` field to determine cluster directional meaning instead of inferring from price position.

**Logic**:
- Short liquidation cluster = shorts getting squeezed = bullish (+)
- Long liquidation cluster = longs getting flushed = bearish (-)
- Direction comes from side, not spatial position relative to current price
- Proximity still modulates magnitude (closer clusters score higher)

**Mixed clusters**: When a bucket contains both long and short liquidations, use the net: `short_vol - long_vol` determines the sign, `abs(net) / total` scales the contribution.

**Backwards compatibility**: Events without a `side` field (e.g., old data still in Redis from before the collector tracked side) are skipped in side-aware calculations. `aggregate_liquidation_buckets` treats missing-side events as contributing to total bucket volume but not to either side's breakdown, so they affect density but not direction.

**Implementation**: `aggregate_liquidation_buckets` returns per-bucket long/short volume breakdown. `compute_cluster_score` uses the breakdown for direction.

### 2. Volume Normalization

**Change**: Pre-normalize each event's volume in the collector at poll time, before storage.

**Logic**: When the collector receives N events from a single poll, it divides each event's `volume` by N before appending to the in-memory window. The stored volume represents that event's share of the batch's total liquidation activity. This ensures total liquidation volume per time window matters, not individual event count from a burst poll.

**Why pre-normalize (not store batch_size)**: The collector's `_persist_events()` serializes only `{price, volume, timestamp, side}` to Redis. Adding a `batch_size` field would require updating both serialization and deserialization, and old events already in Redis would lack it. Pre-normalizing avoids this entirely — the volume stored is already normalized, Redis schema is unchanged, and the scorer needs no awareness of batch sizes.

### 3. Robust Cluster Detection

**Change**: Replace simple median threshold with MAD-based (Median Absolute Deviation) detection.

**Logic**:
```
median_vol = median(volumes)
mad = median(|vol - median_vol| for vol in volumes)
threshold = max(median_vol + MAD_MULTIPLIER * mad, MIN_CLUSTER_MEAN_MULT * mean(volumes))
```

Constants:
- `MAD_MULTIPLIER = 2.0`
- `MIN_CLUSTER_MEAN_MULT = 1.5`

The MAD is resistant to outliers. The mean floor prevents promoting noise when all buckets are uniformly distributed.

### 4. Smooth Depth Modifier

**Change**: Replace 3-tier piecewise logic with a single continuous sigmoid.

**Logic**:
```python
modifier = 0.7 + 0.6 * sigmoid_score(-ratio, center=1.0, steepness=1.5)
```

Same [0.7, 1.3] range, same intuition (thin book amplifies, thick book dampens), smooth everywhere. Reuses existing `sigmoid_score` utility (signature: `sigmoid_score(value, center=0, steepness=0.1, max_score=1.0)`, returns `[0, max_score]`).

**Verification**: Tests must assert the sigmoid variant produces values within 0.05 of the old piecewise logic at the key breakpoints (ratio=0.3, 0.5, 1.0, 2.0) to ensure behavioral continuity during the transition.

### 5. Asymmetry Ratio Component

**New function**: `compute_asymmetry_score(events, decay_half_life_hours) -> dict`

**Computation**:

OKX `side` semantics: `"buy"` = exchange bought to close a short (short liquidation), `"sell"` = exchange sold to close a long (long liquidation).

```
short_liq_vol = sum(volume * decay for event where side == "buy")   # shorts getting liquidated
long_liq_vol  = sum(volume * decay for event where side == "sell")  # longs getting liquidated
total = short_liq_vol + long_liq_vol

if total == 0:
    return {"score": 0, "confidence": 0.0, "raw_asymmetry": 0.0,
            "short_liq_vol": 0.0, "long_liq_vol": 0.0, "event_count": 0}

raw_asymmetry = (short_liq_vol - long_liq_vol) / total    # -1.0 to +1.0
```

Events without a `side` field are excluded from the asymmetry sums (they have no directional meaning). If all events lack `side`, total will be 0 and the early return triggers.

- Positive = more shorts liquidated = bullish
- Negative = more longs liquidated = bearish

**Scoring**: Sigmoid-scaled to configurable max (default 25):
```python
asymmetry_score = sigmoid_score(raw_asymmetry, center=0, steepness=asymmetry_steepness) * asymmetry_max_score
```

**Confidence**: Based on total volume and event count:
```python
min_volume_threshold = density_norm * 0.5
volume_ratio = min(total / min_volume_threshold, 1.0)
asymmetry_confidence = volume_ratio * min(event_count / 10, 1.0)
```

Both sufficient volume and sufficient event count (>= 10) needed for full confidence. Protects against thin data on smaller pairs (WIF).

**Why this adds value**: No other scorer captures the directional imbalance of forced exits. Order flow measures open positions and sentiment (funding, L/S ratio, CVD). Asymmetry measures who is being forcibly removed. Heavy one-sided liquidations indicate washout conditions that order flow cannot distinguish.

### 6. Score Composition

**Function structure** (matching engine convention of separate functions):
- `compute_cluster_score(events, current_price, atr, depth) -> dict` — existing logic with fixes 1-4
- `compute_asymmetry_score(events, decay_half_life_hours) -> dict` — new
- `compute_liquidation_score(events, current_price, atr, depth) -> dict` — thin composer

**Blend**:
```python
combined_score = cluster_result["score"] * cluster_weight + asymmetry_result["score"] * (1 - cluster_weight)
combined_confidence = cluster_result["confidence"] * cluster_weight + asymmetry_result["confidence"] * (1 - cluster_weight)
```

Default `cluster_weight = 0.6`. Cluster scoring is primary (spatial proximity is more actionable), asymmetry is secondary (directional enrichment).

**No regime logic inside the scorer**: The regime already modulates liquidation's outer weight in the combiner. Adding regime logic inside would double-count.

### 7. Diagnostic Details Dict

**New output shape** from `compute_liquidation_score`:
```python
{
    "score": int,
    "confidence": float,
    "clusters": [{"price": float, "volume": float, "side_breakdown": {"long": float, "short": float}}],
    "details": {
        "cluster_score": int,
        "cluster_confidence": float,
        "cluster_count": int,
        "buckets_total": int,
        "per_cluster": [
            {"price": float, "proximity": float, "density_ratio": float,
             "depth_mod": float, "direction": int, "contribution": float}
        ],
        "asymmetry_score": int,
        "asymmetry_confidence": float,
        "raw_asymmetry": float,
        "long_liq_vol": float,
        "short_liq_vol": float,
        "event_count": int,
        "cluster_weight": float,
        "asymmetry_weight": float,
    }
}
```

Details dict gets passed through to the signal's `raw_indicators` JSONB column. No new DB columns needed for diagnostics.

### 8. Constants & Configuration

**Structural constants** (moved to `engine/constants.py` as `LIQUIDATION` dict, not runtime-tunable):
- `BUCKET_WIDTH_ATR_MULT = 0.25`
- `MAD_MULTIPLIER = 2.0`
- `MIN_CLUSTER_MEAN_MULT = 1.5`
- `MAX_DISTANCE_ATR = 2.0`
- `DEPTH_SIGMOID_CENTER = 1.0`
- `DEPTH_SIGMOID_STEEPNESS = 1.5`
- `MIN_ASYMMETRY_EVENTS = 10`

**Tunable parameters** (optimizer + PipelineSettings override):

| Parameter | Config path | Default | Sweep range |
|-----------|------------|---------|-------------|
| `cluster_max_score` | `liquidation.cluster_max_score` | 30 | (15, 45) |
| `asymmetry_max_score` | `liquidation.asymmetry_max_score` | 25 | (10, 40) |
| `cluster_weight` | `liquidation.cluster_weight` | 0.6 | (0.4, 0.8) |
| `proximity_steepness` | `liquidation.proximity_steepness` | 2.0 | (1.0, 4.0) |
| `decay_half_life_hours` | `liquidation.decay_half_life_hours` | 4.0 | (2.0, 8.0) |
| `asymmetry_steepness` | `liquidation.asymmetry_steepness` | 3.0 | (1.5, 6.0) |

### 9. Optimizer Param Group

New `"liquidation"` group in `engine/param_groups.py`, following the existing `order_flow` group as a template:

```python
"liquidation": {
    "params": {
        "cluster_max_score": "liquidation.cluster_max_score",
        "asymmetry_max_score": "liquidation.asymmetry_max_score",
        "cluster_weight": "liquidation.cluster_weight",
        "proximity_steepness": "liquidation.proximity_steepness",
        "decay_half_life_hours": "liquidation.decay_half_life_hours",
        "asymmetry_steepness": "liquidation.asymmetry_steepness",
    },
    "sweep_method": "de",
    "sweep_ranges": {
        "cluster_max_score": (15, 45, None),
        "asymmetry_max_score": (10, 40, None),
        "cluster_weight": (0.4, 0.8, None),
        "proximity_steepness": (1.0, 4.0, None),
        "decay_half_life_hours": (2.0, 8.0, None),
        "asymmetry_steepness": (1.5, 6.0, None),
    },
    "constraints": "_liquidation_ok",
    "priority": 2,
}
```

Constraint function `_liquidation_ok`: `cluster_max_score + asymmetry_max_score <= 100`, all values positive, `0 < cluster_weight < 1`.

### 10. PipelineSettings Columns

Seven new nullable columns on `PipelineSettings` model, matching existing naming convention (`traditional_weight`, `flow_weight`, etc. — full subsystem name, no abbreviation). `None` = use env/config default:

- `liquidation_weight: Float | None` — outer source weight (matches `traditional_weight`, `flow_weight`, `onchain_weight`, `pattern_weight`)
- `liquidation_cluster_max_score: Float | None`
- `liquidation_asymmetry_max_score: Float | None`
- `liquidation_cluster_weight: Float | None`
- `liquidation_proximity_steepness: Float | None`
- `liquidation_decay_half_life_hours: Float | None`
- `liquidation_asymmetry_steepness: Float | None`

Requires Alembic migration.

### 11. Config & Override Wiring

**config.py** — add fields to the `Settings` class:
```python
engine_liquidation_weight: float = 0.0
engine_liquidation_cluster_max_score: float = 30.0
engine_liquidation_asymmetry_max_score: float = 25.0
engine_liquidation_cluster_weight: float = 0.6
engine_liquidation_proximity_steepness: float = 2.0
engine_liquidation_decay_half_life_hours: float = 4.0
engine_liquidation_asymmetry_steepness: float = 3.0
```

**main.py `_OVERRIDE_MAP`** — add entries so PipelineSettings values override Settings at startup:
```python
"liquidation_weight": "engine_liquidation_weight",
"liquidation_cluster_max_score": "engine_liquidation_cluster_max_score",
"liquidation_asymmetry_max_score": "engine_liquidation_asymmetry_max_score",
"liquidation_cluster_weight": "engine_liquidation_cluster_weight",
"liquidation_proximity_steepness": "engine_liquidation_proximity_steepness",
"liquidation_decay_half_life_hours": "engine_liquidation_decay_half_life_hours",
"liquidation_asymmetry_steepness": "engine_liquidation_asymmetry_steepness",
```

**main.py `run_pipeline`** — pass tunable params from settings to scorer:
```python
liq_result = compute_liquidation_score(
    events=liq_events, current_price=price, atr=atr, depth=depth,
    cluster_max_score=settings.engine_liquidation_cluster_max_score,
    asymmetry_max_score=settings.engine_liquidation_asymmetry_max_score,
    cluster_weight=settings.engine_liquidation_cluster_weight,
    proximity_steepness=settings.engine_liquidation_proximity_steepness,
    decay_half_life_hours=settings.engine_liquidation_decay_half_life_hours,
    asymmetry_steepness=settings.engine_liquidation_asymmetry_steepness,
)
```

This follows the existing pattern where PipelineSettings → `_OVERRIDE_MAP` → Settings fields → passed as arguments to scorer functions.

---

## Files Changed

| File | Change |
|------|--------|
| `collector/liquidation.py` | Pre-normalize event volumes by batch size at poll time (divide each volume by number of events in the poll response) |
| `engine/liquidation_scorer.py` | Refactor into `compute_cluster_score` + `compute_asymmetry_score` + composer; apply fixes 1-4; add details dict; handle missing `side` field gracefully; guard against division by zero in asymmetry |
| `engine/constants.py` | Add `LIQUIDATION` dict with structural constants |
| `engine/param_groups.py` | Add `"liquidation"` param group with DE sweep, constraint function, layer 2 priority |
| `engine/combiner.py` | No change (already accepts liquidation score/weight/confidence) |
| `config.py` | Add `engine_liquidation_*` fields to Settings class with defaults |
| `db/models.py` | Add 7 nullable columns to `PipelineSettings` (`liquidation_weight` + 6 tunable params) |
| `main.py` | Add 7 entries to `_OVERRIDE_MAP`; pass tunable params from settings to scorer; pass new details through to `raw_indicators` |
| `alembic/versions/` | New migration for PipelineSettings columns |
| `tests/engine/` | New/updated tests for liquidation scorer |

## Out of Scope

- Regime-specific logic inside the liquidation scorer (combiner handles this)
- Liquidation clusters influencing SL/TP level snapping
- Historical cluster memory
- Liquidation velocity signal
- Frontend changes to display liquidation details
