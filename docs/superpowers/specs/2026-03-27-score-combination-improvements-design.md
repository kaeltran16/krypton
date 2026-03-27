# Score Combination Improvements Design

Improvements to the signal engine's score combination layer targeting signal accuracy: fixing structural bugs, normalizing confidence semantics, and adding adaptive blending mechanisms.

---

## 1. Eliminate Double Normalization

### Problem

Source outer weights are normalized twice before the final blend:

1. `main.py:619-633` zeros unavailable sources and renormalizes the remaining weights to sum to 1.0
2. `combiner.py:22-33` multiplies by confidence and renormalizes again

The first normalization distorts the regime-learned weight ratios. If the regime optimizer learns `tech=0.42, flow=0.23, pattern=0.11` and flow is unavailable, step 1 renormalizes to `tech=0.58, pattern=0.15` — then step 2 applies confidence and renormalizes again, producing a third set of weights unrelated to what was learned.

### Solution

Remove the normalization block in `main.py:619-633`. Pass raw regime outer weights directly to `compute_preliminary_score`. Unavailable sources already produce confidence=0 (flow freshness decays to 0 when stale, onchain returns 0/N for missing metrics, pruned sources are forced to 0), so the combiner's single confidence-weighted normalization handles exclusion naturally.

### Changes

- `main.py` — Remove lines 619-633 (zero + renormalize block). Pass `outer["tech"]`, `outer["flow"]`, etc. directly as base weights.
- `engine/backtester.py` — Align with new calling convention (pass raw outer weights).
- No changes to `combiner.py` — its internal normalization is the single source of truth.

---

## 2. Fix avg_confidence Calculation

### Problem

`combiner.py:44-52` computes `avg_confidence` using base weights (pre-confidence-modulation). This means the confidence tier label doesn't reflect the actual blend. A score dominated by high-confidence tech (0.9) with low-confidence onchain (0.1) still reports low avg_confidence because onchain's base weight drags it down.

### Solution

Use effective weights (post-confidence-normalization) to compute `avg_confidence`:

```python
avg_confidence = sum(confidence_i * effective_weight_i)
```

Where `effective_weight_i = base_weight_i * confidence_i / total_effective_weight`. The effective weights are already computed in lines 22-33, so this reuses them.

### Changes

- `combiner.py:44-52` — Replace base-weight avg_confidence with effective-weight version.

---

## 3. Wire IC Pruning Pipeline

### Problem

The IC (Information Coefficient) pruning framework is fully implemented but not wired:
- `SourceICHistory` DB table exists
- `compute_ic()`, `compute_daily_ic_for_sources()`, `should_prune_source()`, `get_pruned_sources()` all exist in `optimizer.py`
- `app.state.pruned_sources` is initialized as an empty set
- `main.py:640-650` already applies pruning by zeroing confidence for pruned sources
- Nothing populates the history table or updates the pruned set

### Solution

Wire a daily IC computation pipeline into the existing signal resolution background loop.

#### 3.1 Store per-source scores on signal emission

Verify that `tech_score`, `flow_score`, `onchain_score`, `pattern_score`, `liquidation_score` are persisted in the signal's `raw_indicators` JSONB column at emission time. Add any that are missing.

#### 3.2 Daily IC computation

Add a periodic check to the signal resolution background loop (runs every 60s). When last IC computation was >24h ago and there are new resolved signals:

1. Query resolved signals from the rolling window (configurable, default 7 days)
2. Call `compute_daily_ic_for_sources()` per pair/timeframe
3. Insert results into `SourceICHistory` table

#### 3.3 Pruning state update

After IC computation:

1. Query IC history for each source (last `min_days` entries)
2. Call `get_pruned_sources()` to identify sources meeting pruning criteria
3. Update `app.state.pruned_sources`
4. Log state changes (source pruned / re-enabled)

#### 3.4 Configurable parameters (PipelineSettings, not optimizer-swept)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ic_prune_threshold` | -0.05 | Prune if IC consistently below this |
| `ic_reenable_threshold` | 0.0 | Re-enable if latest IC exceeds this |
| `ic_min_days` | 30 | Consecutive days below threshold required to prune |

These operate on daily timescales with 30+ day lookback, making them unsuitable for automated optimizer sweeps. Configurable via PipelineSettings in the frontend settings tab.

### Changes

- `main.py` — Add IC computation check to resolution background loop
- `engine/optimizer.py` — No logic changes, just wire existing functions
- Verify signal emission includes per-source scores in `raw_indicators`

---

## 4. Confidence Split: Availability x Conviction

### Problem

The five sources compute "confidence" measuring fundamentally different things:

| Source | Current confidence measures |
|--------|---------------------------|
| Tech | Thesis conviction (trend/MR strength + indicator agreement) |
| Flow | Data availability * freshness decay |
| Onchain | Metric availability ratio |
| Pattern | Pattern count saturation * directional agreement |
| Liquidation | Cluster count * volume adequacy |

These aren't comparable. Flow confidence 0.8 ("4/5 feeds alive") and tech confidence 0.8 ("indicators strongly agree") get multiplied into blend weights as if they measure the same thing.

### Solution

Split into two dimensions:

- **Availability** (0-1): Is the data present and fresh? Gates whether the source participates in the blend.
- **Conviction** (0-1): Given available data, how directionally decisive is the signal? Scales the score magnitude.

#### 4.1 Formula

```python
effective_weight = base_weight * availability
scaled_score = score * (conviction_floor + (1 - conviction_floor) * conviction)
preliminary = sum(scaled_score_i * normalized_effective_weight_i)
```

`conviction_floor` (default 0.3) ensures even low-conviction sources contribute a baseline of their score. Tunable via optimizer.

#### 4.2 Per-source definitions

**Tech:**
- Availability: `1.0` (candle data always present when pipeline runs)
- Conviction: Current `thesis_conf` logic — `max(trend_conf, mr_conf) * 0.8 + (1 - indicator_conflict) * 0.2`

**Flow:**
- Availability: Current confidence logic — `(inputs_present / sources_available) * (1 - freshness_decay)`
- Conviction: Sub-signal directional agreement. For each non-zero sub-signal (funding, OI, L/S, CVD, book_imbalance), determine its direction (+/-). `max(positive_count, negative_count) / non_zero_count`. Sub-signals with score=0 are excluded from both numerator and denominator. Returns 0.0 if no non-zero sub-signals.

**Onchain:**
- Availability: Current confidence logic — `metrics_present / total_metrics`
- Conviction: Average absolute magnitude of available metric scores, normalized to [0, 1]. When individual metric scores are near zero, conviction is low; when they're at extremes, conviction is high.

**Pattern:**
- Availability: `min(non_neutral_count / 3.0, 1.0)` — are enough patterns detected?
- Conviction: Current agreement factor — `max(bull_count, bear_count) / non_neutral_count`

**Liquidation:**
- Availability: Current combined confidence — cluster count/volume adequacy + asymmetry event/volume adequacy
- Conviction: Weighted blend of cluster proximity strength (how close are clusters to current price) and asymmetry magnitude (how skewed is the liquidation distribution).

#### 4.3 Return value change

Each scorer returns `{"score": int, "availability": float, "conviction": float}` instead of `{"score": int, "confidence": float}`.

#### 4.4 Tunable parameters

```python
# param_groups.py
"conviction": {
    "params": {
        "floor": "blending.conviction.floor",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "floor": (0.0, 0.5, 0.1),
    },
    "constraints": lambda c: 0 <= c["floor"] < 1.0,
    "priority": 0,  # layer 0
}
```

### Changes

- `engine/traditional.py` — Split tech confidence into availability=1.0 + conviction=thesis_conf. Split flow confidence into availability (data presence * freshness) + conviction (sub-signal agreement).
- `engine/onchain_scorer.py` — Split into availability (metric ratio) + conviction (metric magnitude).
- `engine/patterns.py` — Split into availability (pattern count) + conviction (agreement).
- `engine/liquidation_scorer.py` — Split into availability (volume/event adequacy) + conviction (proximity + asymmetry strength).
- `engine/combiner.py` — Accept availability + conviction per source. Use availability for weight modulation, conviction for score scaling.
- `main.py` — Pass availability/conviction to combiner instead of single confidence.
- `engine/backtester.py` — Align with new scorer return format.
- `engine/constants.py` — Add `CONVICTION_FLOOR = 0.3` default.
- `engine/param_groups.py` — Add `conviction` param group.

---

## 5. Directional Agreement Bonus

### Problem

The linear blend treats 5 sources unanimously saying LONG the same as a split decision at the same weighted average. Multi-source consensus is empirically a stronger signal but the current combiner doesn't capture this.

### Solution

After computing the preliminary score, apply a multiplier based on source directional agreement:

```python
def apply_agreement_factor(
    preliminary: int,
    source_scores: list[int],        # scores from contributing sources
    source_availabilities: list[float],  # availability > 0 means contributing
    floor: float = 0.85,
    ceiling: float = 1.15,
) -> int:
    contributing = [(s, a) for s, a in zip(source_scores, source_availabilities) if a > 0 and s != 0]
    if len(contributing) < 2:
        return preliminary

    positive = sum(1 for s, _ in contributing if s > 0)
    negative = sum(1 for s, _ in contributing if s < 0)
    agreement_ratio = max(positive, negative) / len(contributing)

    # Linear interpolation: floor at 50% agreement, ceiling at 100%
    multiplier = floor + (ceiling - floor) * agreement_ratio
    return max(-100, min(100, round(preliminary * multiplier)))
```

### Properties

- Full agreement (5/5 same direction): multiplier = 1.15 (+15% boost)
- Strong agreement (4/5): multiplier = 1.09
- Moderate (3/5): multiplier = 1.03
- Split (2/4): multiplier = 0.85 (-15% penalty)
- Neutral sources (score=0) excluded from count
- Unavailable sources (availability=0) excluded from count
- Cannot create a signal from nothing (0 * any multiplier = 0)

### Tunable parameters

```python
# param_groups.py
"agreement": {
    "params": {
        "floor": "blending.agreement.floor",
        "ceiling": "blending.agreement.ceiling",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "floor": (0.70, 0.95, 0.05),
        "ceiling": (1.05, 1.25, 0.05),
    },
    "constraints": lambda c: c["floor"] < 1.0 < c["ceiling"],
    "priority": 0,  # layer 0
}
```

### Changes

- `engine/combiner.py` — Add `apply_agreement_factor()` function.
- `main.py` — Call after `compute_preliminary_score`, before `blend_with_ml`.
- `engine/constants.py` — Add `AGREEMENT_FLOOR = 0.85`, `AGREEMENT_CEILING = 1.15` defaults.
- `engine/param_groups.py` — Add `agreement` param group.
- `engine/backtester.py` — Align with new combiner call sequence.

---

## 6. Adaptive ML Weight Ramp

### Problem

ML gets a fixed 25% blend weight the instant confidence crosses 0.65. A prediction at 0.66 has identical influence to one at 0.95. This cliff-edge doesn't match the actual information content of the prediction.

### Solution

Linear ramp from minimum weight at threshold to maximum weight at confidence=1.0:

```python
def blend_with_ml(
    indicator_preliminary: int,
    ml_score: float | None,
    ml_confidence: float | None,
    ml_weight_min: float = 0.05,
    ml_weight_max: float = 0.30,
    ml_confidence_threshold: float = 0.65,
) -> int:
    if (
        ml_score is not None
        and ml_confidence is not None
        and ml_confidence >= ml_confidence_threshold
    ):
        t = (ml_confidence - ml_confidence_threshold) / (1.0 - ml_confidence_threshold)
        effective_weight = ml_weight_min + (ml_weight_max - ml_weight_min) * t
        blended = indicator_preliminary * (1 - effective_weight) + ml_score * effective_weight
        return max(min(round(blended), 100), -100)
    return indicator_preliminary
```

### Behavior

| ML Confidence | Effective Weight (defaults) |
|---------------|----------------------------|
| < 0.65 | 0% (ML excluded) |
| 0.65 | 5% |
| 0.75 | 12% |
| 0.85 | 19% |
| 0.95 | 26% |
| 1.00 | 30% |

### Tunable parameters

```python
# param_groups.py
"ml_blending": {
    "params": {
        "weight_min": "blending.ml.weight_min",
        "weight_max": "blending.ml.weight_max",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "weight_min": (0.0, 0.15, 0.05),
        "weight_max": (0.15, 0.40, 0.05),
    },
    "constraints": lambda c: c["weight_max"] > c["weight_min"] >= 0,
    "priority": 0,  # layer 0
}
```

### Changes

- `engine/combiner.py` — Update `blend_with_ml` signature and implementation.
- `engine/constants.py` — Add `ML_WEIGHT_MIN = 0.05`, `ML_WEIGHT_MAX = 0.30` defaults.
- `engine/param_groups.py` — Add `ml_blending` param group.
- `main.py` — Pass new params to `blend_with_ml`.
- `engine/backtester.py` — Align with new `blend_with_ml` signature.

---

## Files Changed Summary

| File | Sections |
|------|----------|
| `engine/combiner.py` | 1, 2, 4, 5, 6 |
| `engine/traditional.py` | 4 |
| `engine/onchain_scorer.py` | 4 |
| `engine/patterns.py` | 4 |
| `engine/liquidation_scorer.py` | 4 |
| `engine/param_groups.py` | 4, 5, 6 |
| `engine/constants.py` | 4, 5, 6 |
| `engine/optimizer.py` | 3 |
| `main.py` | 1, 3, 4, 5 |
| `engine/backtester.py` | 1, 4, 5, 6 |

## Not Changed

- `engine/regime.py` — Regime detection unchanged
- `engine/llm.py` — LLM gate unchanged
- `engine/confluence.py` — Stays additive to tech score
- Frontend — No UI changes; new param groups auto-surface in optimizer tab
