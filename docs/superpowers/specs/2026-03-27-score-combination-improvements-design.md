# Score Combination Improvements Design

Improvements to the signal engine's score combination layer targeting signal accuracy: fixing structural bugs, normalizing confidence semantics, and adding adaptive blending mechanisms.

---

## 1. Eliminate Double Normalization

### Problem

Source outer weights are normalized twice before the final blend:

1. `main.py` zeros unavailable sources and renormalizes the remaining weights to sum to 1.0 (search: `total_w = tech_w + flow_w`)
2. `combiner.py` `compute_preliminary_score` multiplies by confidence and renormalizes again (search: `ew_tech = tech_weight * tech_confidence`)

The first normalization distorts the regime-learned weight ratios. If the regime optimizer learns `tech=0.42, flow=0.23, pattern=0.11` and flow is unavailable, step 1 renormalizes to `tech=0.58, pattern=0.15` — then step 2 applies confidence and renormalizes again, producing a third set of weights unrelated to what was learned.

### Solution

Remove the normalization block in `main.py` (the zero + renormalize block starting at `tech_w = outer["tech"]`). Pass raw regime outer weights directly to `compute_preliminary_score`. The combiner's single confidence-weighted normalization handles exclusion naturally.

**Prerequisite:** Unavailable sources must produce confidence=0 so the combiner zeros their effective weight. Currently tech and flow default to 0.5 when results are missing. Fix these defaults to 0.0:

- `main.py` — Change `tech_conf = tech_result.get("confidence", 0.5)` → `tech_result.get("confidence", 0.0)` (and same for flow). Tech is always available when the pipeline runs, so this default is only a safety net. Flow correctly decays to 0 via freshness when stale, but the `.get()` fallback must also be 0.0.

**All-zero edge case:** If all sources have confidence=0 (e.g., IC prunes everything), the combiner's effective weight total is 0. The existing fallback in `compute_preliminary_score` (`if total > 0: ... else: equal weights`) should be changed to return `{"score": 0, "avg_confidence": 0.0}` instead of falling back to equal weights — a score computed from zero-confidence sources is meaningless.

### Changes

- `main.py` — Remove the zero + renormalize block. Pass `outer["tech"]`, `outer["flow"]`, etc. directly as base weights. Fix confidence defaults from 0.5 → 0.0.
- `engine/combiner.py` — Change the all-zero fallback to return score=0 instead of equal-weight blend.
- `engine/backtester.py` — Align with new calling convention (pass raw outer weights).

---

## 2. Fix avg_confidence Calculation

### Problem

`combiner.py` `compute_preliminary_score` computes `avg_confidence` using base weights (pre-confidence-modulation). This means the confidence tier label doesn't reflect the actual blend. A score dominated by high-confidence tech (0.9) with low-confidence onchain (0.1) still reports low avg_confidence because onchain's base weight drags it down.

### Solution

Use effective weights (post-confidence-normalization) to compute `avg_confidence`:

```python
avg_confidence = sum(confidence_i * effective_weight_i)
```

Where `effective_weight_i = base_weight_i * confidence_i / total_effective_weight`. Since effective weights are normalized to sum to 1.0, no additional denominator is needed. The effective weights are already computed in the confidence-weighting block, so this reuses them.

When all effective weights are zero (total=0), return `avg_confidence = 0.0`.

### Changes

- `combiner.py` — Replace base-weight avg_confidence with effective-weight version. Use the already-normalized `ew_*` variables.

---

## 3. Wire IC Pruning Pipeline

### Problem

The IC (Information Coefficient) pruning framework is fully implemented but not wired:
- `SourceICHistory` DB table exists
- `compute_ic()`, `compute_daily_ic_for_sources()`, `should_prune_source()`, `get_pruned_sources()` all exist in `optimizer.py`
- `app.state.pruned_sources` is initialized as an empty set
- `main.py` already applies pruning by zeroing confidence for pruned sources (search: `pruned = getattr(app.state, "pruned_sources"`)
- Nothing populates the history table or updates the pruned set

### Solution

Wire a daily IC computation pipeline into the existing signal resolution background loop.

#### 3.1 Store per-source scores on signal emission

Currently only `confluence_score` and `liquidation_score` are persisted in the signal's `raw_indicators` JSONB column. Add the missing four:

```python
# In raw_indicators dict at signal emission
"tech_score": tech_result["score"],
"flow_score": flow_result["score"],
"onchain_score": onchain_score,
"pattern_score": pat_score,
```

These are required for IC computation — `optimizer.py` `_IC_SOURCE_KEYS` maps each source to `"{source}_score"` in raw_indicators.

#### 3.2 Daily IC computation

Add a periodic check to the signal resolution background loop (runs every 60s). Track `app.state.last_ic_computed_at` (initialized to `None` at startup). When `last_ic_computed_at` is None or >24h ago, and there are resolved signals:

1. Query resolved signals from the rolling window (configurable, default 7 days)
2. Call `compute_daily_ic_for_sources()` per pair/timeframe
3. Insert results into `SourceICHistory` table
4. Update `app.state.last_ic_computed_at = datetime.utcnow()`

#### 3.3 Pruning state update

After IC computation:

1. Query IC history for each source (last `min_days` entries)
2. Call `get_pruned_sources()` to identify sources meeting pruning criteria
3. Update `app.state.pruned_sources`
4. Log state changes (source pruned / re-enabled)

**Pruning vs re-enabling asymmetry:** Pruning requires `ic_min_days` (30) consecutive days below threshold — a high bar to avoid premature removal. Re-enabling checks only the latest IC value against `ic_reenable_threshold` — fast recovery is intentional because a source that starts performing well again should be reincorporated quickly. The worst case of a yo-yo (prune after 30 bad days, re-enable on 1 good day, prune after 30 more bad days) is acceptable: during the "re-enabled" period the source's low IC means its organic confidence will be low anyway, minimizing blend impact.

**Bootstrap behavior:** During the first `ic_min_days` (30) days after deployment, `should_prune_source()` returns False for all sources (insufficient history). All sources remain active. This is the correct default — no pruning without evidence.

**Minimum sources guard:** Tech (candle-derived) is never prunable — IC pruning only applies to flow, onchain, pattern, liquidation, confluence. If all five non-tech sources are pruned, log a warning but continue — tech alone can still produce signals, and re-enabling will restore sources as their IC recovers.

#### 3.4 Configurable parameters (PipelineSettings, not optimizer-swept)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ic_prune_threshold` | -0.05 | Prune if IC consistently below this |
| `ic_reenable_threshold` | 0.0 | Re-enable if latest IC exceeds this |
| `ic_min_days` | 30 | Consecutive days below threshold required to prune |

These operate on daily timescales with 30+ day lookback, making them unsuitable for automated optimizer sweeps. Configurable via PipelineSettings in the frontend settings tab.

### Changes

- `main.py` — Add `tech_score`, `flow_score`, `onchain_score`, `pattern_score` to `raw_indicators` at signal emission. Add `app.state.last_ic_computed_at = None` at startup. Add IC computation check to resolution background loop with 24h throttle. Exclude `"tech"` from prunable sources.
- `engine/optimizer.py` — No logic changes, just wire existing functions.

---

## 4. Confidence Split: Availability x Conviction

### Problem

The six sources compute "confidence" measuring fundamentally different things:

| Source | Current confidence measures |
|--------|---------------------------|
| Tech | Thesis conviction (trend/MR strength + indicator agreement) |
| Flow | Data availability * freshness decay |
| Onchain | Metric availability ratio |
| Pattern | Pattern count saturation * directional agreement |
| Liquidation | Cluster count * volume adequacy |
| Confluence | Multi-timeframe signal availability |

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

`conviction_floor` (default 0.3) ensures even low-conviction sources contribute a baseline of their score. Rationale: when few sources are available, fully suppressing a low-conviction source could make the blend unstable or overly dependent on a single source. The floor guarantees every available source contributes at least 30% of its score magnitude, preserving blend diversity. Tunable via optimizer.

#### 4.2 Per-source definitions

**Tech:**
- Availability: `1.0` (candle data always present when pipeline runs)
- Conviction: Current `thesis_conf` logic — `max(trend_conf, mr_conf) * 0.8 + (1 - indicator_conflict) * 0.2`

**Flow:**
- Availability: Current confidence logic — `(inputs_present / sources_available) * (1 - freshness_decay)`
- Conviction: Sub-signal directional agreement. For each sub-signal (funding, OI, L/S, CVD, book_imbalance) that has data available (availability contributed by that feed), determine its direction: positive (+1), negative (-1), or neutral (0). Neutral sub-signals (score=0) contribute 0.5 to conviction (they are present but indecisive, not absent). `conviction = (max(positive_count, negative_count) + 0.5 * neutral_count) / total_available_count`. If no sub-signals have data, conviction=0.0.

**Onchain:**
- Availability: Current confidence logic — `metrics_present / total_metrics`
- Conviction: `mean(abs(metric_score_i) for i in available_metrics) / 100.0`. Each metric's individual score ranges -100 to +100, so dividing the average absolute value by 100 normalizes to [0, 1]. Near-zero metric scores → low conviction; extreme scores → high conviction.

**Pattern:**
- Availability: `min(non_neutral_count / 3.0, 1.0)` — are enough patterns detected?
- Conviction: Current agreement factor — `max(bull_count, bear_count) / non_neutral_count`

**Liquidation:**
- Availability: Current combined confidence — cluster count/volume adequacy + asymmetry event/volume adequacy
- Conviction: Weighted blend of cluster proximity strength (how close are clusters to current price) and asymmetry magnitude (how skewed is the liquidation distribution).

**Confluence:**
- Availability: Current confidence logic — proportion of higher timeframes with usable signal data.
- Conviction: Current directional agreement across timeframes — `max(bullish_tf_count, bearish_tf_count) / total_contributing_tfs`. If only one timeframe contributes, conviction=1.0 (no disagreement possible).

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

- `engine/traditional.py` — Split tech confidence into availability=1.0 + conviction=thesis_conf. Split flow confidence into availability (data presence * freshness) + conviction (sub-signal agreement with neutral handling).
- `engine/onchain_scorer.py` — Split into availability (metric ratio) + conviction (`mean(abs(score)) / 100`).
- `engine/patterns.py` — Split into availability (pattern count) + conviction (agreement).
- `engine/liquidation_scorer.py` — Split into availability (volume/event adequacy) + conviction (proximity + asymmetry strength).
- `engine/confluence.py` — Split into availability (timeframe data proportion) + conviction (timeframe directional agreement).
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
    if len(contributing) < 3:
        return preliminary  # require 3+ sources for meaningful consensus

    positive = sum(1 for s, _ in contributing if s > 0)
    negative = sum(1 for s, _ in contributing if s < 0)
    agreement_ratio = max(positive, negative) / len(contributing)

    # Linear interpolation: floor at 50% agreement, ceiling at 100%
    # At ratio=0.5: multiplier=floor (0.85). At ratio=1.0: multiplier=ceiling (1.15).
    multiplier = floor + (ceiling - floor) * (agreement_ratio - 0.5) / 0.5
    multiplier = max(floor, min(ceiling, multiplier))  # clamp to bounds
    return max(-100, min(100, round(preliminary * multiplier)))
```

### Properties

- Full agreement (5/5 same direction): multiplier = 1.15 (+15% boost)
- Strong agreement (4/5): multiplier = 1.03
- Split (3/5): multiplier = 0.91
- <3 contributing sources: no bonus/penalty applied (insufficient consensus signal)
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
    if ml_confidence_threshold >= 1.0:
        return indicator_preliminary  # threshold unreachable, ML never participates
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

### Migration from engine_ml_weight

The existing `engine_ml_weight` config/PipelineSettings column (fixed 0.25) is replaced by `engine_ml_weight_min` and `engine_ml_weight_max`. If a PipelineSettings row has a legacy `engine_ml_weight` override but no min/max values, use it as `ml_weight_max` with `ml_weight_min=0.0` for backward compatibility. New deployments use the defaults (0.05/0.30).

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

- `engine/combiner.py` — Update `blend_with_ml` signature and implementation. Add threshold >= 1.0 guard.
- `engine/constants.py` — Add `ML_WEIGHT_MIN = 0.05`, `ML_WEIGHT_MAX = 0.30` defaults.
- `engine/param_groups.py` — Add `ml_blending` param group.
- `main.py` — Pass new params to `blend_with_ml`.
- `engine/backtester.py` — Align with new `blend_with_ml` signature.
- `config.py` — Add `engine_ml_weight_min` and `engine_ml_weight_max` fields. Deprecate `engine_ml_weight`.
- `db/models.py` — Add `engine_ml_weight_min` and `engine_ml_weight_max` nullable columns to PipelineSettings. Add Alembic migration.

---

## Files Changed Summary

| File | Sections |
|------|----------|
| `engine/combiner.py` | 1, 2, 4, 5, 6 |
| `engine/traditional.py` | 4 |
| `engine/onchain_scorer.py` | 4 |
| `engine/patterns.py` | 4 |
| `engine/liquidation_scorer.py` | 4 |
| `engine/confluence.py` | 4 |
| `engine/param_groups.py` | 4, 5, 6 |
| `engine/constants.py` | 4, 5, 6 |
| `engine/optimizer.py` | 3 |
| `main.py` | 1, 3, 4, 5 |
| `engine/backtester.py` | 1, 4, 5, 6 |
| `config.py` | 6 |
| `db/models.py` + migration | 6 |

## Not Changed

- `engine/regime.py` — Regime detection unchanged
- `engine/llm.py` — LLM gate unchanged
- Frontend — No UI changes; new param groups auto-surface in optimizer tab
