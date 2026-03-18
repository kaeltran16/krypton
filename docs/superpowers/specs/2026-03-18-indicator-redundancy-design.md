# Indicator Redundancy: Unified Mean-Reversion & Squeeze Separation

**Date:** 2026-03-18
**Status:** Approved
**Relates to:** `docs/signal-algorithm-improvements.md` item #4

## Problem

RSI (capped by `mean_rev_cap`) and BB position (capped by 60% of `bb_vol_cap`) both measure mean-reversion. They're correlated, giving mean-reversion an outsized effective weight (up to 60 of 100 points in ranging regime). Meanwhile, BB width (squeeze detection) — a genuinely different volatility signal — is bundled under `bb_vol_cap` alongside BB position, preventing independent tuning.

## Approach: Split BB, Unify Mean-Reversion (Option A)

Move BB position under the mean-reversion umbrella with RSI. Separate BB width into its own squeeze/volatility component. This keeps 4 caps but with cleaner semantics — each cap controls one orthogonal concept.

## Component Restructure

### Current (4 caps)

| Cap | Signals | Sub-split |
|-----|---------|-----------|
| `trend_cap` | ADX direction/strength | — |
| `mean_rev_cap` | RSI only | — |
| `bb_vol_cap` | BB position + BB width | 60/40 |
| `volume_cap` | OBV + volume ratio | 60/40 |

### New (4 caps, renamed)

| Cap | Signals | Sub-split |
|-----|---------|-----------|
| `trend_cap` | ADX direction/strength | — |
| `mean_rev_cap` | RSI + BB position (unified) | configurable blend ratio (default 60/40) |
| `squeeze_cap` | BB width (squeeze/expansion) | — |
| `volume_cap` | OBV + volume ratio | 60/40 |

## Default Cap Values

Caps sum to 100 per regime.

| Regime | `trend_cap` | `mean_rev_cap` | `squeeze_cap` | `volume_cap` | Total |
|--------|-------------|----------------|---------------|--------------|-------|
| **trending** | 38 | 22 | 12 | 28 | 100 |
| **ranging** | 18 | 40 | 16 | 26 | 100 |
| **volatile** | 25 | 28 | 22 | 25 | 100 |

Rationale:
- `mean_rev_cap` increases to accommodate two blended signals (was 15/32/20)
- `squeeze_cap` is modest — confirmatory signal, not primary. Higher in volatile regime where squeeze/expansion matters most
- `volume_cap` slight bump in trending (freed budget from old `bb_vol_cap`)
- All values are starting points; final allocation is tuned via backtesting through `RegimeWeights`

## Scoring Logic

### Unified Mean-Reversion Score

```python
rsi_raw = sigmoid_score(50 - rsi_val, center=0, steepness=mean_rev_rsi_steepness)
bb_pos_raw = sigmoid_score(0.5 - bb_pos, center=0, steepness=mean_rev_bb_pos_steepness)
mean_rev_score = (blend_ratio * rsi_raw + (1 - blend_ratio) * bb_pos_raw) * caps["mean_rev_cap"]
```

- RSI and BB position both produce [-1, +1] via `sigmoid_score` before blending
- `blend_ratio` default 0.6 (RSI is the stronger signal, BB position confirms)
- Single cap controls total mean-reversion influence

### Squeeze Score

```python
mean_rev_sign = 1 if mean_rev_score > 0 else (-1 if mean_rev_score < 0 else 0)
squeeze_score = mean_rev_sign * sigmoid_score(50 - bb_width_pct, center=0, steepness=squeeze_steepness) * caps["squeeze_cap"]
```

- Inherits direction from the blended mean-reversion signal. This is a behavioral change from current code, which derives direction from BB position alone. The blended approach means RSI now influences squeeze direction — intentional, since the unified mean-reversion signal is a better directional estimate than BB position alone.
- When `mean_rev_score == 0` (both signals perfectly neutral), squeeze contribution is zero. This is acceptable — a squeeze with no directional bias has no predictive value for signal direction.
- Independent cap allows tuning squeeze contribution separately from mean-reversion

### Volume Scoring (unchanged)

OBV and volume ratio scoring remain as-is under `volume_cap` with the existing 60/40 split.

### Total

```python
total = trend_score + mean_rev_score + squeeze_score + obv_score + vol_score
score = max(min(round(total), 100), -100)
```

## Configuration

### Regime-Varying Parameters (`RegimeWeights` table)

Per (pair, timeframe), per regime — tunable via backtest optimizer:

| Column | Replaces | Default |
|--------|----------|---------|
| `trending_squeeze_cap` | — (new) | 12 |
| `ranging_squeeze_cap` | — (new) | 16 |
| `volatile_squeeze_cap` | — (new) | 22 |

Remove 3 columns: `trending_bb_vol_cap`, `ranging_bb_vol_cap`, `volatile_bb_vol_cap`.

Update `mean_rev_cap` defaults: trending=22, ranging=40, volatile=28.

### Shape Parameters (`PipelineSettings` table)

Not regime-dependent — the sigmoid response curve shape is independent of market regime:

| Setting | Default | Purpose |
|---------|---------|---------|
| `mean_rev_rsi_steepness` | 0.25 | RSI sigmoid response curve |
| `mean_rev_bb_pos_steepness` | 10.0 | BB position sigmoid response curve |
| `squeeze_steepness` | 0.10 | BB width sigmoid response curve |
| `mean_rev_blend_ratio` | 0.6 | RSI weight in blend (BB position gets `1 - ratio`) |

## Code Changes

### `backend/app/engine/regime.py`

- `CAP_KEYS`: replace `"bb_vol_cap"` with `"squeeze_cap"`
- `DEFAULT_CAPS`: update all 3 regime dicts with new values

### `backend/app/engine/traditional.py`

- `compute_technical_score()` signature: add optional `scoring_params: dict | None` for steepness/blend values (defaults used when `None`)
- Replace sections 2 and 3 with unified mean-reversion and squeeze scoring
- Update `indicators` dict: add `mean_rev_rsi_raw`, `mean_rev_bb_pos_raw` for debuggability

### `backend/app/db/models.py`

- `RegimeWeights`: replace `*_bb_vol_cap` columns with `*_squeeze_cap`, update `*_mean_rev_cap` defaults
- `PipelineSettings`: add 4 new columns for steepness and blend ratio

### `backend/app/engine/regime_optimizer.py`

- Update `N_PARAMS` comment and parameter layout docs (replace `bb_vol_cap` references with `squeeze_cap`)
- `PARAM_BOUNDS` stays at `[_CAP_BOUNDS] * 12` (still 3 regimes x 4 caps)
- `vector_to_regime_dict` iterates `CAP_KEYS` generically — works automatically after `regime.py` update
- Update docstring at line 57

### `backend/app/main.py`

- Build `scoring_params` dict from `app.state.pipeline_settings` and pass to `compute_technical_score()`

### Alembic Migration

Single migration:
1. Add `*_squeeze_cap` columns to `RegimeWeights` with defaults
2. Migrate existing rows: update `mean_rev_cap` values and populate `squeeze_cap` from old `bb_vol_cap` budget
3. Alter `*_mean_rev_cap` column defaults
4. Drop `*_bb_vol_cap` columns
5. Add steepness + blend ratio columns to `PipelineSettings`

### `backend/app/engine/regime.py` (blend function)

- `_extract_regime_dict` and `blend_caps` work generically on `CAP_KEYS` — updating the key list is sufficient

### No Changes Needed (verified)

- `backend/app/engine/combiner.py` — uses `bb_width_pct` from indicators dict (unchanged); does not read sub-score keys
- `backend/app/engine/backtester.py` — gets caps through `regime.py` via `blend_caps`; no direct `bb_vol_cap` references. Calls `compute_technical_score()` without `scoring_params`, so backtester uses default steepness/blend values (acceptable — backtester should test with defaults unless explicitly sweeping shape params)
- `backend/app/ml/features.py` — computes features from raw candle data independently; uses `bb_position`/`bb_width` feature names unrelated to scoring cap keys
- Frontend — does not parse individual sub-scores from `raw_indicators`

## Indicators Dict & Downstream

The `indicators` dict returned from `compute_technical_score()`:
- Raw values unchanged: `rsi`, `bb_pos`, `bb_width_pct` still present
- New score breakdown fields added: `mean_rev_score`, `squeeze_score`, `mean_rev_rsi_raw`, `mean_rev_bb_pos_raw` (the current dict has no sub-score keys, so these are all additions)
- Frontend does not parse individual sub-scores from `raw_indicators` — no frontend changes needed

## Tests

- Update test fixtures to use new cap keys (`squeeze_cap` instead of `bb_vol_cap`)
- Update assertions checking individual sub-scores
- Add test for RSI/BB position blend (both oversold should produce stronger score than either alone)
- Existing regime blending tests just need the new key added
- Update `regime_optimizer.py` tests (`test_regime_backtest.py`) for renamed cap key
- No new test files needed

## Note: Pre-existing Volatile Regime Cap Bug

The current `DEFAULT_CAPS` for volatile regime sums to 85, not 100 (22+20+28+15). This was an intentional design choice for implicit signal suppression in choppy conditions (see `docs/signal-algorithm-improvements.md` item #2). The new defaults fix this to sum to 100 (25+28+22+25) since the regime system now has better tools for suppression via outer weight blending.
