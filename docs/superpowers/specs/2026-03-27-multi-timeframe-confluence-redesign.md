# Multi-Timeframe Confluence Redesign

## Problem

The current confluence system is too simple to meaningfully impact signal quality:

- Only 3 indicators (ADX, DI+, DI-) flow from parent to child timeframe
- Binary direction check (+1/-1) scaled by parent ADX strength
- Flat +/-15 max score additive to tech score, which shrinks to ~6 points after combiner weighting at 40%
- Only checks immediate parent (15m sees 1H but not 4H or 1D)
- No regime awareness -- same logic for trending, ranging, and volatile markets
- Invisible to confidence tier calculation
- `confluence_max_score` not in optimizer param groups

## Goals

1. **Signal quality** -- reduce signals that fight higher-timeframe trends
2. **Signal confidence** -- confluence contributes directly to confidence tier via the combiner
3. **Amplify multi-TF alignment** -- when 3 timeframes agree, the signal should be meaningfully stronger

### Acceptance Criteria

- Backtest on BTC-USDT-SWAP 15m: fewer signals where child direction opposes 1H trend direction compared to baseline (current confluence system)
- Average confluence confidence > 0.4 when 2+ parent levels are available
- Confluence score distribution covers the full [-100, +100] range (not clustered near 0 like the old +/-15 system)
- No regression in overall signal P&L on 30-day backtest vs baseline
- All existing combiner/pipeline/confluence tests pass with updated signatures

## Design

### Term Definitions

Formula variables and their sources:

| Term | Source | Description |
|------|--------|-------------|
| `child_trend_score` | `tech_result["indicators"]["trend_score"]` | Pre-confluence trend sub-score from `compute_technical_score` |
| `child_mean_rev_score` | `tech_result["indicators"]["mean_rev_score"]` | Pre-confluence mean-reversion sub-score from `compute_technical_score` |
| `child_mr_score` | Alias for `child_mean_rev_score` | Used in MR alignment formulas for brevity |
| `trend_conviction` | `tech_result["indicators"]["trend_conviction"]` | ADX-weighted directional strength (0-1), computed in `traditional.py` |
| `parent_trend_score` | `htf_indicators:{pair}:{tf}` cache → `trend_score` | Parent's cached trend sub-score |
| `parent_mean_rev_score` | `htf_indicators:{pair}:{tf}` cache → `mean_rev_score` | Parent's cached mean-reversion sub-score |
| `parent_mr_score` | Alias for `parent_mean_rev_score` | Used in MR alignment formulas for brevity |
| `parent_trend_conviction` | `htf_indicators:{pair}:{tf}` cache → `trend_conviction` | Parent's cached trend conviction |
| `parent_adx` | `htf_indicators:{pair}:{tf}` cache → `adx` | Parent's cached ADX value |
| `parent_regime` | `htf_indicators:{pair}:{tf}` cache → `regime` | Parent's cached regime mix dict |
| `sigmoid_scale` | `engine/scoring.py:sigmoid_scale()` | Existing unipolar logistic: `1 / (1 + exp(-steepness * (value - center)))`, maps input to [0, 1] |

### Confluence as Independent Combiner Source

Confluence becomes the 6th source in the combiner alongside tech, flow, onchain, pattern, and liquidation. It produces its own score (-100 to +100) and confidence (0-1), participates in confidence-weighted normalization, and has regime-aware outer weighting.

The old approach of adding +/-15 to tech score before the combiner is removed entirely.

### Enriched Parent Cache

Each confirmed candle caches enriched indicators to Redis at `htf_indicators:{pair}:{tf}`:

```json
{
  "trend_score": 35.2,
  "mean_rev_score": -12.5,
  "trend_conviction": 0.78,
  "adx": 28.4,
  "di_plus": 31.2,
  "di_minus": 18.7,
  "regime": {
    "trending": 0.62,
    "ranging": 0.15,
    "volatile": 0.18,
    "steady": 0.05
  },
  "timestamp": "2026-03-27T14:00:00Z"
}
```

TTL unchanged: 2x candle period (15m=1800s, 1h=7200s, 4h=28800s, 1D=172800s). Same key format. 1D remains confluence-only (caches but does not emit signals).

Values cached are pre-confluence, pre-volume-multiplication sub-scores from `compute_technical_score`. This avoids transitive confluence chains.

### Multi-Level Parent Lookup

Each child checks all available ancestors, not just the immediate parent:

| Child | Checks |
|-------|--------|
| 15m   | 1H, 4H, 1D |
| 1H    | 4H, 1D |
| 4H    | 1D |

Missing levels are skipped. Confidence scales with the number of available levels. No chain continuity requirement -- if 4H cache is expired, 15m still uses 1H and 1D.

### Per-Parent Alignment Scoring

For each available parent, alignment is computed based on the child's dominant thesis.

**Thesis detection:**

```
if |child_trend_score| == 0 and |child_mean_rev_score| == 0:
    # no thesis -- return score=0, confidence=0 (skip alignment)
    return {"score": 0, "confidence": 0.0}

child_thesis = "trend" if |child_trend_score| >= |child_mean_rev_score| else "mean_rev"
child_direction = sign of the dominant sub-score
```

When sub-scores are equal (but non-zero), trend takes precedence -- HTF alignment is more meaningful for directional trades. When both are zero, there is no thesis to align against, so confluence produces a neutral result and its weight redistributes via zero confidence.

**Trend-following child:**

Uses existing `scoring.sigmoid_scale()` (unipolar logistic, maps ADX to [0, 1]).

```
direction_match = sign(child_trend_score) * sign(parent_trend_score)
parent_strength = sigmoid_scale(parent_adx, center=adx_strength_center, steepness=trend_alignment_steepness)
conviction_bonus = parent_trend_conviction

alignment = direction_match * parent_strength * (adx_conviction_ratio + (1 - adx_conviction_ratio) * conviction_bonus)
```

Range: [-1, +1]. Fully aligned strong parent = ~+1.0. Opposing strong parent = ~-1.0. Weak parent = near 0.

**Mean-reverting child:**

`parent_mr_score` = `parent_mean_rev_score` from the HTF cache (see Term Definitions).

```
ranging_support = parent_regime["ranging"] * sign(child_mean_rev_score) * sign(parent_mean_rev_score)
trend_opposition = parent_regime["trending"] * sign(child_mean_rev_score) * sign(parent_trend_score)

alignment = clamp(ranging_support - mr_penalty_factor * trend_opposition, -1.0, +1.0)
```

The clamp is required because the raw expression can exceed [-1, +1] when `ranging_support` and `trend_opposition` have opposite signs (e.g., 1.0 - 0.8 * -1.0 = 1.8). No sigmoid is used here -- regime probabilities (0-1) already bound each term, and the clamp handles the edge case where both terms reinforce.

Range: [-1, +1]. Ranging parent + aligned extremes = positive. Trending parent opposing MR thesis = negative.

### Level Aggregation

```
weighted_sum = sum(alignment_i * level_weight_i for each available parent)
total_weight = sum(level_weight_i for each available parent)
normalized = weighted_sum / total_weight

score = round(normalized * 100)  # [-100, +100]
confidence = (available_levels / max_possible_levels) * avg_conviction
```

`max_possible_levels` is the number of ancestors that *exist* for the child timeframe (not 3 for everyone):

| Child | Max possible levels |
|-------|---------------------|
| 15m   | 3 (1H, 4H, 1D) |
| 1H    | 2 (4H, 1D) |
| 4H    | 1 (1D) |

`avg_conviction` depends on thesis:

- **Trend thesis**: `avg(parent_trend_conviction)` across available parents -- trend conviction directly measures how reliable alignment is.
- **Mean-rev thesis**: `avg(parent_regime["ranging"])` across available parents -- for MR signals, parent ranging-ness is the relevant conviction proxy (a strongly ranging parent supports mean-reversion more reliably than a weakly ranging one).

If no parents are available, `confidence = 0.0` and the confluence weight redistributes to other sources via the combiner's confidence-weighted normalization.

Default level weights (tunable):

| Level | Weight |
|-------|--------|
| Immediate parent (1 level up) | 0.50 |
| Grandparent (2 levels up) | 0.30 |
| Great-grandparent (3 levels up) | 0.20 |

Weights renormalize over available levels when parents are missing.

### Combiner Integration

`compute_preliminary_score` gains `confluence_score`, `confluence_weight`, `confluence_confidence` parameters. Same confidence-weighted normalization as existing sources -- if confluence confidence is 0 (no parent data), weight redistributes automatically.

Default regime outer weights (initial values, optimizer tunes):

| Regime | tech | flow | onchain | pattern | liquidation | confluence |
|--------|------|------|---------|---------|-------------|------------|
| Trending | 0.36 | 0.20 | 0.14 | 0.09 | 0.07 | 0.14 |
| Ranging | 0.32 | 0.14 | 0.22 | 0.14 | 0.10 | 0.08 |
| Volatile | 0.34 | 0.18 | 0.16 | 0.10 | 0.10 | 0.12 |
| Steady | 0.36 | 0.16 | 0.16 | 0.10 | 0.08 | 0.14 |

Confluence weighted higher in trending/steady (HTF alignment matters most), lower in ranging (mean-reversion is more local).

This is a **full rebalance** of all 6x4=24 outer weights, not just adding 4 new confluence values. All existing source weights change (e.g., trending tech drops from 0.42 to 0.36). The `DEFAULT_OUTER_WEIGHTS` dict and `RegimeWeights` DB defaults both update to these values.

**Migration strategy for existing customized RegimeWeights rows**: The Alembic migration adds 4 new `{regime}_confluence_weight` columns with defaults from the table above. Existing rows keep their current 5-source weights unchanged. On first load after migration, `blend_outer_weights` will use the new confluence column values. If the existing 5-source weights were customized (no longer sum to the original 1.0 minus confluence share), the combiner's confidence-weighted normalization handles this gracefully -- weights are always renormalized at runtime. The optimizer will tune all 6 source weights together via the existing `regime_outer` param group.

### Pipeline Flow

```
1. compute_technical_score(df, ...)          # tech score, no confluence
2. Cache enriched sub-scores to Redis        # trend_score, mean_rev_score, regime, etc.
3. If 1D: return                             # confluence-only, unchanged
4. compute_confluence_score(child, parents)   # independent score + confidence
5. compute_order_flow_score(...)
6. compute_pattern_score(...)
7. compute_onchain_score(...)
8. compute_liquidation_score(...)
9. blend_outer_weights(regime, ...)          # includes confluence slot
10. compute_preliminary_score(all 6 sources)
11. blend_with_ml(...)
12. LLM gate
13. Threshold check -> emit
```

### MR Pressure Dampening Removal

The explicit `confluence_dampening` constant in `MR_PRESSURE` is removed. Dampening is now handled structurally:

- Ranging regime gives confluence lower outer weight (0.08 vs 0.14 trending)
- The mean-rev branch in alignment already accounts for parent regime
- No special-case multiplier needed

### Optimizer Integration

New `confluence` param group:

```python
{
    "params": {
        "level_weight_1": "blending.confluence.level_weights.immediate",
        "level_weight_2": "blending.confluence.level_weights.grandparent",
        # level_weight_3 derived as 1.0 - w1 - w2, stored but not swept independently
        "trend_alignment_steepness": "blending.confluence.trend_alignment_steepness",
        "adx_strength_center": "blending.confluence.adx_strength_center",
        "adx_conviction_ratio": "blending.confluence.adx_conviction_ratio",
        "mr_penalty_factor": "blending.confluence.mr_penalty_factor",
    },
    "sweep_method": "de",
    "sweep_ranges": {
        "level_weight_1": (0.30, 0.65, None),
        "level_weight_2": (0.15, 0.45, None),
        # level_weight_3 is derived: 1.0 - level_weight_1 - level_weight_2
        "trend_alignment_steepness": (0.10, 0.50, None),
        "adx_strength_center": (10, 25, None),
        "adx_conviction_ratio": (0.40, 0.80, None),
        "mr_penalty_factor": (0.20, 0.80, None),
    },
    "constraints": _confluence_ok,  # w1 + w2 < 1.0 and derived w3 >= 0.05
    "priority": 2,
}
```

The outer weight for confluence (how much it contributes in the combiner) is tuned via existing `source_weights` and `regime_outer` param groups.

All params are manually editable via the Engine tab. `api/engine.py` GET exposes the 6 confluence params under `blending.confluence.*`, and POST `/apply` maps them to `PipelineSettings` columns via `_PIPELINE_SETTINGS_MAP`. Frontend `EngineParameters` type adds the corresponding fields. No new UI components needed -- existing parameter rendering handles new fields automatically.

### Backtester

- `precompute_parent_indicators()` returns enriched payload matching the Redis cache shape
- Supports multi-level precomputation (immediate + grandparent + great-grandparent)
- Calls `compute_confluence_score()` as independent source in the backtest loop
- Passes confluence score + confidence into `compute_preliminary_score`
- `BacktestConfig.confluence_max_score` removed, replaced by confluence param fields

## Files Changed

### Modified

| File | Changes |
|------|---------|
| `engine/confluence.py` | Replace `compute_confluence_score` and remove `di_direction`. New multi-level, regime-aware scoring. Keep `TIMEFRAME_PARENT`, `CONFLUENCE_ONLY_TIMEFRAMES`, `TIMEFRAME_CACHE_TTL`, `TIMEFRAME_PERIOD_HOURS`. |
| `engine/regime.py` | Add `"confluence"` to `OUTER_KEYS` list. Add `confluence` slot to all 4 regime dicts in `DEFAULT_OUTER_WEIGHTS` with values from the regime weight table. |
| `engine/combiner.py` | Add `confluence_score=0`, `confluence_weight=0.0`, `confluence_confidence=0.0` to `compute_preliminary_score` (defaulted for backward compat with existing callers). |
| `engine/constants.py` | Remove `confluence_dampening` from `MR_PRESSURE`. Add `CONFLUENCE` defaults dict. Add to param tree metadata. |
| `engine/param_groups.py` | Add `confluence` param group with DE sweep. Add to `PRIORITY_LAYERS[2]`. |
| `engine/backtester.py` | Expand `precompute_parent_indicators` payload. Multi-level parent precomputation. Call `compute_confluence_score` independently. Wire into `compute_preliminary_score`. Remove `confluence_max_score` from `BacktestConfig`. |
| `main.py` | Enrich HTF cache payload with sub-scores + regime. Call `compute_confluence_score` as step 4. Remove `tech_result["score"] += confluence_score` block. Remove MR pressure confluence dampening block. Pass confluence into `compute_preliminary_score`. Add `confluence_score` (int) and `confluence_confidence` (float) to signal dict and WebSocket broadcast payload. |
| `api/engine.py` | Expose confluence params as configurable. Update apply endpoint mapping. |
| `api/backtest.py` | Fetch multi-level parent candles. |
| `config.py` | Replace `engine_confluence_max_score` with confluence param fields. |
| `db/models.py` | Replace `confluence_max_score` on `PipelineSettings` with: `confluence_level_weight_1` (Float), `confluence_level_weight_2` (Float), `confluence_trend_alignment_steepness` (Float), `confluence_adx_strength_center` (Float), `confluence_adx_conviction_ratio` (Float), `confluence_mr_penalty_factor` (Float). All nullable. `level_weight_3` is derived as `1.0 - w1 - w2` at runtime, not stored. Add `{regime}_confluence_weight` (Float, nullable) columns to `RegimeWeights` for all 4 regimes. |
| `web/src/features/engine/types.ts` | Add confluence params to `EngineParameters` type. |
| `web/src/features/signals/` | Add `confluence_score` (int, -100 to +100) and `confluence_confidence` (float, 0-1) to signal types. Display in SignalDetail "Intelligence Components" section. Both fields optional for backward compat with old signals. |
| `web/src/features/backtest/components/ParameterOverridePanel.tsx` | Replace `confluence_max_score` reference with new confluence param fields in override list. |
| `api/routes.py` | Update debug endpoint `compute_preliminary_score` call to include `confluence_score=0, confluence_weight=0.0, confluence_confidence=0.0` defaults (uses positional args, will break without this). |
| `tests/conftest.py` | Replace `confluence_max_score` mock in test fixtures with new confluence param fields. |

### Deleted Code

| What | Where |
|------|-------|
| `di_direction()` | `engine/confluence.py` |
| `confluence_dampening` constant | `engine/constants.py` MR_PRESSURE dict |
| `engine_confluence_max_score` config field | `config.py`, `db/models.py`, `api/engine.py`, `tests/conftest.py` |
| `tech_result["score"] += confluence_score` block | `main.py` |
| MR pressure confluence dampening block | `main.py` |

### New

| What | Where |
|------|-------|
| Alembic migration | Single migration that: (1) drops `confluence_max_score` from `PipelineSettings`, adds 6 new confluence float columns with defaults; (2) adds `trending_confluence_weight`, `ranging_confluence_weight`, `volatile_confluence_weight`, `steady_confluence_weight` to `RegimeWeights` with defaults from regime weight table. Runs via `entrypoint.sh`. |

### Tests

| File | Changes |
|------|---------|
| `tests/engine/test_confluence.py` | Rewrite for new function signature, multi-level logic, thesis-aware alignment |
| `tests/engine/test_confluence_backtest.py` | Update for enriched precompute, multi-level, independent source |
| `tests/engine/test_confluence_caching.py` | Update cache payload assertions for enriched fields |
| `tests/engine/test_combiner.py` | Add confluence as 6th source in all combiner tests |
| `tests/engine/test_combiner_confidence.py` | Add confluence params to all `compute_preliminary_score` calls |
| `tests/engine/test_mr_pressure.py` | Add confluence params to `compute_preliminary_score` call |
| `tests/test_pipeline.py` | Add confluence params to all `compute_preliminary_score` calls |
| `tests/engine/test_regime.py` | Add `assert "confluence" in weights` to outer weight assertions |
