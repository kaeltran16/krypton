# LLM Factor Calibration

## Problem

The 12 LLM factor weights (5.0-8.0) were hand-tuned with no feedback loop. There is no mechanism to detect whether a specific factor type (e.g., `news_catalyst`, `crowded_positioning`) actually predicts outcomes. A factor that consistently misfires contributes noise to every LLM-gated signal.

The DE optimizer can sweep factor weights periodically, but it operates in batch mode and cannot react to a factor becoming unreliable between sweeps.

## Success Criteria

- Factors with directional accuracy below chance (50%) over the rolling window have their effective weight reduced
- Factors with accuracy above 55% retain full weight
- Calibration reacts within days (not weeks) to a factor becoming unreliable
- No measurable impact on pipeline latency (multipliers read from memory, not DB)
- DE optimizer remains unaffected -- it sees base weights, not calibrated ones

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Interaction with DE | Temporary multipliers on base weights | Keeps DE and calibration orthogonal; DE optimizes joint weight surface, calibration tracks per-factor reliability. No feedback loops. After DE promotes new weights, existing calibration multipliers remain valid because they track *directional accuracy* (bullish/bearish correctness), which is independent of weight magnitude. |
| Scope | Global with per-pair override | Global accumulates 30 samples fast. Per-pair overrides when a pair reaches 15 samples for factor type. Scales as more pairs are added. |
| State storage | In-memory + DB persistence | Pipeline reads from `app.state` (fast). DB writes only on signal resolution. Full rebuild from DB on restart. |
| Multiplier function | Smooth linear ramp | Avoids binary flipping at threshold boundaries. A single signal resolution causes a small multiplier change, not a 0.5x/1.0x jump. |
| Expired signals | Excluded | Ambiguous outcome; including them would dilute accuracy signal. |
| Tunable parameters | PipelineSettings only, not DE | Meta-parameters that control calibration aggressiveness. Letting DE tune them creates circular dependency. |

## Data Model

### New table: `llm_factor_outcome`

| Column | Type | Purpose |
|--------|------|---------|
| `id` | Integer PK | Auto-increment |
| `signal_id` | Integer FK -> signals.id | Source signal |
| `pair` | String(32) | Denormalized for per-pair queries |
| `factor_type` | String(32) | e.g. "rsi_divergence" |
| `direction` | String(8) | "bullish" or "bearish" |
| `strength` | SmallInteger | 1, 2, or 3 |
| `correct` | Boolean | Factor direction aligned with signal outcome? |
| `resolved_at` | DateTime(tz) | When the signal resolved |

**Index:** Composite on `(factor_type, resolved_at DESC)`.

**Correctness definition:**
- Signal won (TP1_HIT, TP2_HIT, TP1_TRAIL, TP1_TP2) and factor is bullish on LONG / bearish on SHORT -> correct
- Signal lost (SL_HIT) -> inverse of above
- EXPIRED -> not recorded (ambiguous)

No cascade delete -- records represent historical accuracy data independent of signal lifecycle.

## Calibration Logic

### Multiplier computation (smooth ramp)

```
accuracy below 40%  -> multiplier = 0.5 (floor)
accuracy 40% - 55%  -> linear interpolation from 0.5 to 1.0
accuracy above 55%  -> multiplier = 1.0 (no penalty)
```

Formula: `multiplier = clamp((accuracy - 0.40) / 0.15, 0.0, 1.0) * 0.5 + 0.5`

Where `0.5` is the configurable floor (`calibration_floor`).

Generalized: `multiplier = clamp((accuracy - ramp_low) / (ramp_high - ramp_low), 0.0, 1.0) * (1.0 - floor) + floor`

With defaults: `ramp_low = 0.40`, `ramp_high = 0.55`, `floor = 0.5`.

### Scope resolution

1. Collect factor outcomes from the last `calibration_window_global` (default 30) resolved LLM-gated signals. Each signal contributes up to 5 factor outcomes (one per factor present). A factor type that appeared in 20 of the 30 signals has 20 samples; a rare type that appeared in 6 has 6 samples.
2. Compute global accuracy per factor type from those collected outcomes
3. For the current pair, count per-pair records per factor type within the same window
4. If per-pair count >= `calibration_window_pair_min` (default 15), use per-pair accuracy instead of global for that (pair, factor_type) combination
5. Global minimum of `CALIBRATION_MIN_SAMPLES` (10) is the gate. If a factor type has <10 global samples, multiplier = 1.0 regardless of per-pair count.
6. Apply smooth ramp to derive multiplier

Window is by signal count, not time -- avoids stale windows during low-activity periods.

**Example:** The last 30 LLM-gated signals produce 142 factor outcomes across 12 types. `news_catalyst` appeared in 8 signals (8 samples, below min 10 -> multiplier = 1.0). `rsi_divergence` appeared in 25 signals with 60% accuracy globally -> multiplier = 1.0. For BTC-USDT-SWAP specifically, `rsi_divergence` appeared in 16 of those signals with 38% accuracy -> per-pair override applies, multiplier = 0.5.

### Effective weight

```
effective_weight[factor_type] = base_weight[factor_type] * multiplier[factor_type]
```

Base weights come from DE-optimized or default config. Multipliers are read from `app.state.llm_calibration`.

## Configuration

### PipelineSettings (runtime-tunable)

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `calibration_window_global` | int, nullable | 30 | Number of resolved LLM-gated signals for global accuracy window. Validation: >= 1. |
| `calibration_floor` | float, nullable | 0.5 | Minimum multiplier (floor of the ramp). Validation: [0.0, 1.0]. Values outside range are rejected, not clamped. |

### Settings (env/yaml)

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `engine_calibration_window_global` | int | 30 | >= 1 |
| `engine_calibration_floor` | float | 0.5 | [0.0, 1.0] |

Setting `calibration_floor` to 1.0 effectively disables calibration (multiplier is always 1.0).

### Constants (hardcoded)

| Constant | Value | Purpose |
|----------|-------|---------|
| `CALIBRATION_WINDOW_PAIR_MIN` | 15 | Minimum per-pair records before per-pair accuracy overrides global |
| `CALIBRATION_MIN_SAMPLES` | 10 | Minimum global records for a factor type before calibration activates |
| `CALIBRATION_RAMP_LOW` | 0.40 | Accuracy below this gets floor multiplier |
| `CALIBRATION_RAMP_HIGH` | 0.55 | Accuracy above this gets full multiplier (1.0) |

## State Lifecycle

### Startup (app lifespan)

1. Query `llm_factor_outcome` for records from the last 30 days, ordered by `resolved_at DESC`, keeping the most recent 20 rows per `(factor_type, pair)` combination (`ROW_NUMBER() OVER (PARTITION BY factor_type, pair ORDER BY resolved_at DESC) <= 20`). This guarantees minimum coverage per category while bounding total load to at most `12 factor types * 3 pairs * 20 = 720` rows.
2. Build `app.state.llm_calibration` containing raw records list and pre-computed multiplier dicts (global + per-pair)
3. If table is empty, all multipliers default to 1.0

### On signal resolution (outcome resolver)

1. Check if resolved signal has `llm_factors` and outcome is not EXPIRED
2. Compute correctness for each factor, insert rows into `llm_factor_outcome`
3. Append to in-memory records list, trim beyond window
4. Recompute multiplier dicts

### On pipeline run (run_pipeline)

1. Read `app.state.llm_calibration.get_multipliers(pair)` -- returns `{factor_type: float}`
2. Apply multipliers to base weights: `calibrated_weight = base_weight * multiplier`
3. Pass calibrated weights to `compute_llm_contribution()`

### Concurrency

Outcome resolver and pipeline run on the same asyncio event loop. Only the outcome resolver mutates state, pipeline only reads. Multiplier dicts are rebuilt as new `dict` objects and assigned via single reference swap (`self._global_multipliers = new_dict`). Because `record_outcomes()` involves `await` calls (DB writes) that yield control, the pipeline may read during a rebuild -- it sees either the previous or the new dict, never a partial state. No locks needed.

### Restart recovery

Full state rebuilt from DB at startup. No data loss.

## Integration Points

### engine/llm_calibration.py (new module)

Core calibration logic:
- `LLMCalibrationState` class holding records + multiplier cache
- `compute_multiplier(accuracy, floor)` -- smooth ramp function
- `get_multipliers(pair)` -- returns factor_type -> multiplier dict for a pair
- `record_outcomes(signal)` -- processes a resolved signal's factors
- `apply_calibration(base_weights, multipliers)` -- returns adjusted weight dict

### engine/combiner.py -- No changes

`compute_llm_contribution` already accepts `factor_weights: dict[str, float]`. Caller passes calibrated weights. Combiner is unaware of calibration.

### main.py -- Pipeline run (read path)

Before calling `compute_llm_contribution`, apply multipliers:

```python
calibrated_weights = apply_calibration(
    base_weights=settings.llm_factor_weights,
    multipliers=app.state.llm_calibration.get_multipliers(pair),
)
```

### engine/outcome_resolver.py -- Signal resolution (write path)

After resolving a signal, if `signal.llm_factors is not None` and outcome is not EXPIRED:

```python
await record_factor_outcomes(db, app.state.llm_calibration, signal)
```

### config.py / db/models.py -- Settings

Add `calibration_window_global` and `calibration_floor` to both `PipelineSettings` model and `Settings` class.

### main.py -- _OVERRIDE_MAP

Register `calibration_window_global` and `calibration_floor` in `_OVERRIDE_MAP` so DB overrides from `PipelineSettings` propagate to runtime settings via `_apply_pipeline_overrides()`.

### api/engine.py -- Visibility

Add calibration multipliers to `GET /api/engine/parameters` response under a `calibration` section. No new endpoints.

### api/pipeline_settings.py -- Tuning

Add `calibration_window_global` and `calibration_floor` to `PipelineSettingsUpdate` model and serialization.

### Frontend

No frontend changes required. Calibrated weights flow through `engine_snapshot` already stored per signal.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| No resolved LLM-gated signals yet | All multipliers = 1.0. Calibration is inert. |
| Factor type never appears in window | Multiplier = 1.0 (no data = no penalty). |
| All factors for a type are correct | Multiplier = 1.0. |
| Factor type has < 10 records globally | Skip calibration for that type (too few samples). Multiplier = 1.0. |
| Per-pair count < 15 | Fall back to global accuracy for that pair+factor combo. |
| `calibration_floor` set to 1.0 | Calibration disabled -- all multipliers = 1.0 regardless of accuracy. |
| Signal has no llm_factors | No records written. Common for signals that didn't trigger LLM gate. |
| DB unavailable at startup | Start with empty records, all multipliers = 1.0. Log warning. Rebuilds as signals resolve. |
| Factor direction matches signal direction but signal lost | Factor marked incorrect. A bullish factor on a LONG signal that hits SL was wrong. |

## Database Migration

One Alembic migration:
- Create `llm_factor_outcome` table with columns and composite index
- Add `calibration_window_global` (Integer, nullable) and `calibration_floor` (Float, nullable) to `PipelineSettings`
