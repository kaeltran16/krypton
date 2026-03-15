# Signal Frequency Recalibration

## Problem

The signal engine generates very few signals — well below the target of ~1-2 signals per pair per day. Root causes:

1. **Score compression**: Sigmoid steepness values produce scores that cluster in ±20-45 under normal market conditions, leaving the upper half of the ±100 range nearly unused
2. **Signal threshold too high**: `config.yaml` overrides the default threshold from 35 to 50, sitting above the practical score ceiling. Additionally, the `PipelineSettings` DB singleton row has `signal_threshold=50` and overrides config.yaml at startup.
3. **LLM double veto**: The "contradict" opinion both hard-clamps scores to ±40 in `combiner.py` AND triggers an early return in `main.py` that unconditionally skips signal emission — two independent vetoes
4. **Order flow scoring also compressed**: Same sigmoid compression issue in funding rate, OI, and L/S ratio scoring
5. **Backtester divergence**: Backtester uses hardcoded defaults (threshold=35, tech=0.75/pattern=0.25) that don't match live config, so backtest results don't predict live behavior

## Target

~1-2 signals per pair per day across 3 pairs (BTC, ETH, WIF) and 3 timeframes (15m, 1h, 4h). Roughly 3-6 signals/day total.

## Changes

### 1. Technical Score Sigmoid Recalibration

**File:** `backend/app/engine/traditional.py`, `compute_technical_score()`

Increase sigmoid steepness (and lower the ADX center from 20 to 15) so normal market conditions produce scores that use more of the ±100 range. Component caps stay the same.

The trend component uses `sigmoid_scale` (unipolar [0,1]) not `sigmoid_score` (bipolar [-1,+1]), so the ADX center shift is needed — steepness alone barely moves the needle because typical ADX values (18-25) are close to the old center of 20.

| Component | Cap | Current Params | New Params | Verified Score Change |
|-----------|-----|----------------|------------|----------------------|
| Trend (ADX) | ±30 | center=20, steepness=0.15 | center=15, steepness=0.30 | ±17 → ±27 at ADX=22 |
| RSI | ±25 | steepness=0.15 | steepness=0.25 | ±13 → ±19 at RSI=42 |
| BB Position | ±15 | steepness=6.0 | steepness=10.0 | ±6 → ±10 at bb_pos=0.35 |
| BB Width | ±10 | steepness=0.06 | steepness=0.10 | ±5 → ±6 at pct=35 |
| OBV Slope | ±12 | steepness=2.0 | steepness=4.0 | ±2 → ±5 at norm=0.2 |
| Volume Ratio | ±8 | steepness=1.5 | steepness=3.0 | ±2 → ±3 at ratio=1.3 |

Note: In trending markets, trend-following (ADX) and mean-reversion (RSI, BB position) indicators partially cancel each other, which is by design — it prevents false signals from single-dimension extremes. The recalibration increases score magnitude on both sides, so the net effect when indicators align is significantly higher total scores.

### 2. Order Flow Sigmoid Recalibration

**File:** `backend/app/engine/traditional.py`, `compute_order_flow_score()`

When order flow data is available, compressed flow scores leave points on the table.

| Component | Cap | Current Steepness | New Steepness | Rationale |
|-----------|-----|-------------------|---------------|-----------|
| Funding Rate | ±35 | 5000 | 8000 | Funding rates are tiny (0.0001-0.001); need higher sensitivity |
| OI Change | ±20 | 40 | 65 | OI changes of 1-3% should produce meaningful scores |
| L/S Ratio | ±35 | 4 | 6 | Ratio deviations of 0.1-0.3 from 1.0 should score higher |

### 3. LLM Contradict: Penalty Instead of Double Veto

Two changes to remove the absolute LLM veto:

**File 1:** `backend/app/engine/combiner.py`, `compute_final_score()`

Replace the hard clamp with a sign-aware proportional penalty:

```python
if llm_response.opinion == "confirm":
    final = preliminary_score + 20 * multiplier   # +6 to +20
elif llm_response.opinion == "caution":
    final = preliminary_score - 15 * multiplier   # -4.5 to -15
else:  # contradict
    if preliminary_score == 0:
        final = 0
    else:
        sign = 1 if preliminary_score > 0 else -1
        penalty = sign * min(30 * multiplier, abs(preliminary_score))
        final = preliminary_score - penalty   # reduces magnitude by 9 to 30, clamped at zero
```

The sign-aware penalty always pushes the score toward zero (reducing magnitude), regardless of whether the signal is LONG (positive) or SHORT (negative). The `min(30 * multiplier, abs(preliminary_score))` clamp ensures the penalty never exceeds the score's magnitude — without this, a score of +20 with HIGH contradict would produce -10 (sign flip), which is conceptually wrong. With the clamp, it produces 0. A zero score is left unchanged (it can't reach LLM threshold in practice, but the guard avoids introducing a directional bias).

**Boundary behavior:** The threshold check uses `>=` (`abs(final) >= signal_threshold`), so a score landing exactly at 40 **will** emit. For example, +70 with HIGH-confidence contradict → +40 → emits as a borderline signal. This is intentional — the LLM penalty should weaken, not veto.

| Preliminary | Confidence | Multiplier | Final | Emits? (threshold=40) |
|-------------|------------|------------|-------|-----------------------|
| +80 | HIGH | 1.0 | +50 | Yes |
| +70 | HIGH | 1.0 | +40 | Yes (borderline) |
| +60 | HIGH | 1.0 | +30 | No |
| +70 | MEDIUM | 0.6 | +52 | Yes |
| +70 | LOW | 0.3 | +61 | Yes |
| -80 | HIGH | 1.0 | -50 | Yes |
| -70 | HIGH | 1.0 | -40 | Yes (borderline) |
| 0 | any | any | 0 | No |

**File 2:** `backend/app/main.py`, `run_pipeline()` (lines 454-469)

Remove the hard veto early-return on LLM contradict. The penalty in `compute_final_score` is sufficient — the score reduction will naturally suppress weak signals below threshold while allowing strong signals through. Delete the `if llm_opinion == "contradict": return` block and let the normal threshold check at line 472 handle it.

### 4. Threshold and Config Alignment

Three layers must all be updated for the threshold change to take effect:

**File 1:** `backend/config.yaml`

| Key | Old Value | New Value | Notes |
|-----|-----------|-----------|-------|
| `engine.signal_threshold` | 50 | 40 | Matches recalibrated score range |
| `engine.llm_threshold` | 30 | 20 | Borderline signals still get LLM review (see LLM call volume note below) |
| `engine.llm_weight` | 0.40 | removed | Dead key — no `engine_llm_weight` field in Settings |

**File 2:** `backend/app/db/models.py`, `PipelineSettings` model

Change the column default from 50 to 40:
```python
signal_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
```

**File 3:** Alembic migration

Create a migration to update the existing `PipelineSettings` singleton row:
```sql
UPDATE pipeline_settings SET signal_threshold = 40 WHERE id = 1;
```

This is necessary because the DB value overrides config.yaml at startup (`main.py` lines 840-860).

**Note on weights:** `config.yaml` sets `engine.traditional_weight: 0.60`, overriding the `config.py` default of `0.40`. This override remains unchanged — tech weight stays at 60% in the live system.

**LLM call volume:** Lowering `llm_threshold` from 30 to 20 increases the number of candles that trigger an OpenRouter API call. With 3 pairs × 3 timeframes and recalibrated sigmoids producing higher scores, more candle evaluations will land in the 20-30 range that previously skipped LLM review. Estimated increase: ~2-3x more LLM calls. At OpenRouter rates this is marginal cost, but monitor via logs (`LLM gate triggered` entries) in the first 24h. If call volume is problematic, 25 is a viable compromise that still captures more borderline signals than 30.

### 5. Backtester Alignment

**Backend:** `backend/app/api/backtest.py`

The `RunRequest` Pydantic model hardcodes `signal_threshold: int = Field(default=50, ...)`. Update this default to 40 to match the new live threshold. When the frontend omits the field, the API should use the same default as the live engine.

**Backend:** `backend/app/engine/backtester.py`

Update `BacktestConfig` defaults to match: `signal_threshold=40`.

**Frontend:** `web/src/features/backtest/store.ts`

Update `defaultConfig.signal_threshold` from 30 to 40. The BacktestSetup slider remains fully functional for user override.

## Files Modified

| File | Change |
|------|--------|
| `backend/app/engine/traditional.py` | Sigmoid steepness values (tech + order flow), ADX center |
| `backend/app/engine/combiner.py` | LLM contradict: sign-aware penalty instead of clamp |
| `backend/app/main.py` | Remove hard veto early-return on LLM contradict |
| `backend/config.yaml` | Threshold values, remove dead `llm_weight` key |
| `backend/app/db/models.py` | PipelineSettings default threshold 50 → 40 |
| `backend/app/api/backtest.py` | RunRequest default threshold 50 → 40 |
| `backend/app/engine/backtester.py` | BacktestConfig default threshold 35 → 40 |
| `web/src/features/backtest/store.ts` | Default threshold 30 → 40 |
| Alembic migration | Update existing PipelineSettings row threshold to 40 |

## Deployment

All code changes and the Alembic migration must deploy atomically in a single container restart. The Docker Compose volume-mount setup naturally ensures this — a `docker compose up -d --build` picks up both code and migration together. Do not run the migration separately before deploying the code (lower threshold + old compressed scores = signal flood) or vice versa (recalibrated scores + old high threshold = no improvement).

## Testing

### Combiner tests (`test_combiner.py`)

- `test_final_score_with_contradict` — change assertion from `final <= 40` to `final == 50` (input=80, contradict HIGH: 80 - min(30,80)×1.0 = 50)
- `test_final_score_with_contradict_negative` — change assertion from `final >= -40` to `final == -50` (input=-80, contradict HIGH: -80 + min(30,80)×1.0 = -50)
- **New:** `test_final_score_with_contradict_medium` — `compute_final_score(80, contradict MEDIUM)` = 80 - 18 = 62
- **New:** `test_final_score_with_contradict_zero` — `compute_final_score(0, contradict HIGH)` = 0
- **New:** `test_final_score_with_contradict_clamps_at_zero` — `compute_final_score(20, contradict HIGH)` = 0 (penalty clamped to abs(score), not -10)
- **New:** `test_final_score_with_contradict_clamps_at_zero_negative` — `compute_final_score(-25, contradict HIGH)` = 0 (not +5)
- **New:** `test_final_score_with_contradict_borderline_emission` — `compute_final_score(70, contradict HIGH)` = 40 (borderline emit at threshold)

### Technical score tests

Update expected values for recalibrated steepness. Representative assertions (using `sigmoid_score` / `sigmoid_scale` with new params):

| Component | Test Input | New Expected Score | Old Expected Score |
|-----------|-----------|-------------------|-------------------|
| Trend (ADX) | ADX=22 | ±27 | ±17 |
| RSI | RSI=42 (deviation=8 from 50) | ±19 | ±13 |
| BB Position | bb_pos=0.35 (deviation=0.15 from 0.5) | ±10 | ±6 |
| BB Width | pct=35 | ±6 | ±5 |
| OBV Slope | norm=0.2 | ±5 | ±2 |
| Volume Ratio | ratio=1.3 (deviation=0.3 from 1.0) | ±3 | ±2 |

### Order flow score tests

Update expected values for recalibrated steepness:

| Component | Test Input | New Expected Score | Old Expected Score |
|-----------|-----------|-------------------|-------------------|
| Funding Rate | rate=0.0005 | ±27 | ±19 |
| OI Change | change=2% (0.02) | ±15 | ±10 |
| L/S Ratio | ratio=1.2 (deviation=0.2) | ±25 | ±18 |

### Pipeline integration test

**Updated test in `test_pipeline_ml.py`:** `test_contradict_penalizes_but_does_not_veto` — verify that a strong signal with LLM contradict is still emitted (not vetoed). Mock setup: low signal threshold, LLM returns contradict HIGH. Assert that `persist_signal` is called (veto removed) and the emitted `signal_data["score"]` exceeds the threshold (penalty applied but signal still emits). This covers the `main.py` early-return removal that combiner unit tests can't reach.

### Backtest validation

Run backtest with new parameters across all 3 pairs × 3 timeframes to validate signal frequency approaches the ~1-2 per pair per day target.

## Post-Deployment Verification

After deploying, verify signal frequency in the first 24-48h:

```sql
-- Signal frequency per pair per day (run after 24h)
SELECT symbol, timeframe, DATE(created_at) AS day, COUNT(*) AS signals
FROM signals
WHERE created_at > NOW() - INTERVAL '48 hours'
GROUP BY symbol, timeframe, day
ORDER BY day, symbol, timeframe;
```

**Target:** ~1-2 rows per pair/timeframe/day. If frequency is significantly off:
- Too low (< 0.5/pair/day): Consider lowering `signal_threshold` to 35 or further steepness increases
- Too high (> 4/pair/day): Raise `signal_threshold` to 45 or reduce steepness adjustments
- Check LLM call volume via `docker logs krypton-api-1 | grep "LLM gate triggered" | wc -l` — compare to pre-deployment baseline

## What This Does NOT Change

- Component score caps (±30/±25/±15+±10/±12+±8 for tech, ±35/±20/±35 for flow)
- Weight distribution (tech 60% via config.yaml override, flow 22%, onchain 23%, pattern 15%)
- Adaptive SL/TP Phase 1 scaling logic
- Risk guard filters (post-emission, unrelated to signal frequency)
- ML blending logic
- Minimum candle requirement (70)
