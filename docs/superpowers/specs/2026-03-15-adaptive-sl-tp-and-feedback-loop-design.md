# Adaptive SL/TP Placement & Performance Feedback Loop

## Problem

The engine uses static ATR multipliers (1.5/2.0/3.0) for SL/TP1/TP2 regardless of signal strength, volatility regime, pair, or timeframe. There is no mechanism to learn from historical outcomes.

Backtest data (8 runs, ~840 trades) shows these static levels work well on 1h (PF 2.35-3.38) but poorly on 15m (PF 0.88) and marginally on 4h (PF 1.10-1.15). The same multipliers have never been varied across any backtest — they are the single biggest unoptimized lever.

## Goals

- Maximize risk-adjusted returns (Sortino ratio) rather than raw PnL or win rate
- Adapt SL/TP levels to signal conviction and market conditions (Phase 1)
- Learn optimal base multipliers from resolved signal outcomes (Phase 2)
- Auto-adjust within guardrails; flag changes that exceed bounds for manual approval

## Non-Goals

- Changing the scoring algorithm (technical, order flow, on-chain, patterns)
- Modifying signal emission thresholds
- Addressing low signal volume per bucket (separate effort)
- Cross-timeframe confluence or regime detection

---

## Phase 1: Signal Strength & Volatility Scaling (Rule-Based)

A new function `scale_atr_multipliers()` in `engine/combiner.py` that modifies ATR multipliers before `calculate_levels()` is called.

### Signal Strength Scaling

Differential scaling: SL uses a conservative factor, TP uses a more aggressive factor. This means higher conviction signals get proportionally better R:R ratios, not just uniformly wider levels.

```
t = (abs(score) - signal_threshold) / (100 - signal_threshold)   # 0.0 at threshold, 1.0 at max
sl_strength_factor = lerp(0.8, 1.2, t)   # SL: 0.8x to 1.2x
tp_strength_factor = lerp(0.8, 1.4, t)   # TP: 0.8x to 1.4x (more aggressive)
```

| Score (threshold=35) | sl_strength | tp_strength | Effective R:R (base 1.33) |
|----------------------|-------------|-------------|---------------------------|
| 35 (minimum)         | 0.80        | 0.80        | 1.33 (unchanged)          |
| 50                   | 0.89        | 0.94        | 1.41                      |
| 65                   | 0.98        | 1.08        | 1.47                      |
| 100 (maximum)        | 1.20        | 1.40        | 1.56                      |

Rationale: A weak signal barely crossing threshold gets uniformly tighter levels (less risk, less reward). As conviction grows, TPs scale faster than SL, improving the risk/reward profile — stronger signals earn both more room and better payoff.

### Volatility Regime Scaling

Uses BB width percentile (already computed in `traditional.py`) to detect squeeze vs expansion. Applied uniformly to all levels (volatility affects SL and TP equally).

```
vol_factor = lerp(0.75, 1.25, bb_width_pct / 100)
```

| BB Width Percentile | vol_factor | Effective SL (base 1.5) |
|---------------------|------------|-------------------------|
| 10 (squeeze)        | 0.82       | 1.23x ATR               |
| 50 (normal)         | 1.00       | 1.50x ATR               |
| 90 (expansion)      | 1.22       | 1.83x ATR               |

Rationale: Squeezes precede breakouts — tight stops capture directional moves with less risk. Expansions need wider stops to avoid noise-triggered SL hits.

### Combined Effect

```
effective_sl  = base_sl_atr  * sl_strength_factor * vol_factor
effective_tp1 = base_tp1_atr * tp_strength_factor * vol_factor
effective_tp2 = base_tp2_atr * tp_strength_factor * vol_factor
```

All results are clamped to the existing `sl_bounds`, `tp1_min_atr`, `tp2_max_atr`, and `rr_floor` constraints already enforced in `calculate_levels()`.

### Auditability

Store the effective multipliers used on each signal in `raw_indicators` as `effective_sl_atr`, `effective_tp1_atr`, `effective_tp2_atr`, along with `sl_strength_factor`, `tp_strength_factor`, and `vol_factor`. This avoids needing to re-derive scaling factors during Phase 2 replay and makes post-hoc analysis straightforward.

### LLM/ML Override Path Handling

`calculate_levels()` has three priority paths:
1. **LLM explicit levels** — returns LLM-provided levels directly, bypassing ATR multipliers entirely
2. **ML regression multiples** — uses ML-predicted ATR multiples instead of defaults
3. **ATR defaults** — uses base multipliers (1.5/2.0/3.0 or Phase 2 learned values)

Phase 1 scaling and Phase 2 learned multipliers only apply to **Path 3**. Phase 1 scaling also applies to **Path 2** (ML multiples), since ML confidence gating already filters low-quality predictions.

Store which path was used in `raw_indicators` as `levels_source`: `"llm"`, `"ml"`, or `"atr_default"`. Signals with `levels_source = "llm"` are **excluded** from the Phase 2 optimization window, since their levels were not derived from ATR multipliers and replaying them is meaningless.

---

## Phase 2: Rolling Performance Tracker (Data-Driven)

### Storage

New DB table `performance_tracker`:

| Column                | Type          | Purpose                                      |
|-----------------------|---------------|----------------------------------------------|
| id                    | Integer (PK)  | Auto-increment                               |
| pair                  | String(32)    | e.g., "BTC-USDT-SWAP"                        |
| timeframe             | String(8)     | e.g., "1h"                                   |
| current_sl_atr        | Float         | Learned SL multiplier (default 1.5)          |
| current_tp1_atr       | Float         | Learned TP1 multiplier (default 2.0)         |
| current_tp2_atr       | Float         | Learned TP2 multiplier (default 3.0)         |
| last_optimized_at     | DateTime(tz)  | When optimization last ran                   |
| last_optimized_count  | Integer       | Resolved count at last optimization          |
| updated_at            | DateTime(tz)  | Last update timestamp                        |

Unique constraint on (pair, timeframe).

Note: `resolved_count` is not stored — it is queried live from the `signals` table to avoid drift from manual signal edits or deletions:
```sql
SELECT COUNT(*) FROM signals
WHERE pair = :pair AND timeframe = :timeframe AND outcome != 'PENDING'
```

### Rolling Window

- **Window size:** 100 resolved signals per pair/timeframe
- **Minimum to start tuning:** 40 resolved signals
- **Optimization trigger:** Every 10 new resolved signals per bucket

Below 40 signals, the tracker returns static defaults (1.5/2.0/3.0).

### Independent 1D Optimization

Instead of a full grid search (which would overfit on 100 data points), each multiplier is optimized independently:

1. Fix TP1/TP2 at current values, sweep SL from 0.8 to 2.5 (step 0.2) → 9 candidates
2. Fix SL/TP2 at current values, sweep TP1 from 1.0 to 4.0 (step 0.5) → 7 candidates
3. Fix SL/TP1 at current values, sweep TP2 from 2.0 to 6.0 (step 0.5) → 9 candidates

Total: 25 evaluations on 100 data points — no overfitting risk.

### Replay Logic

For each candidate multiplier value, replay all 100 signals in the window:

1. From each signal row, read: `entry` (price), `direction`, `raw_indicators.atr`, `raw_indicators.effective_sl_atr` / `effective_tp1_atr` / `effective_tp2_atr` (Phase 1 scaling factors, stored for auditability), `created_at`, `outcome_at`
2. Re-derive SL/TP levels using the candidate multiplier. For the dimension being swept, compute `candidate_base * sl_strength_factor * vol_factor` (or `tp_strength_factor` for TP dimensions) using the Phase 1 factors stored on the signal. For the other two dimensions, use the stored `effective_*_atr` values as-is (Phase 1 scaling is already incorporated in those values)
3. Fetch candle data from **Postgres** (not Redis) for the signal's lifetime:
   ```sql
   SELECT high, low, timestamp FROM candles
   WHERE pair = :pair AND timeframe = :timeframe
     AND timestamp > :signal_created_at AND timestamp <= :signal_outcome_at
   ORDER BY timestamp
   ```
   Batch this query for all 100 signals to avoid N+1
4. Check candle highs/lows against the re-derived SL/TP levels using the same resolution logic as `outcome_resolver.py`
5. Compute PnL for each replayed trade
6. Compute Sortino ratio across all 100 replayed outcomes

Pick the candidate that maximizes Sortino ratio.

**Sortino edge cases:**
- All replayed trades are winners (downside deviation = 0): Sortino is undefined; treat this candidate as optimal (no losses is ideal)
- All replayed trades are losers: Sortino is negative; compare candidates by least-negative Sortino
- Fewer than 2 losing trades: use `abs(single_loss)` as downside deviation (matches existing backtester behavior at `backtester.py:330`)
- If all candidates produce identical Sortino: keep current multiplier (no change)

### Guardrails

| Parameter      | Min  | Max  | Max single adjustment |
|----------------|------|------|----------------------|
| SL ATR         | 0.8  | 2.5  | ±0.3 per cycle       |
| TP1 ATR        | 1.0  | 4.0  | ±0.5 per cycle       |
| TP2 ATR        | 2.0  | 6.0  | ±0.5 per cycle       |
| TP1/SL ratio   | >= 1.0 | —  | R:R floor preserved  |

- Changes within guardrails: auto-applied and logged
- Changes exceeding max adjustment: clamped to max, flagged in logs
- Changes breaking R:R floor: TP1 is clamped upward to maintain `tp1_atr >= sl_atr * rr_floor` (matches existing `calculate_levels()` behavior)

**Logging payload for each auto-adjustment:**
- Pair, timeframe, dimension adjusted (SL/TP1/TP2)
- Old multiplier → new multiplier
- Sortino improvement (old vs new)
- Number of signals in window
- Whether clamping was applied (guardrail hit)

### Cold Start Bootstrap

On first deployment, `tracker.bootstrap_from_backtests()` copies the ATR multiplier config from the best completed backtest per pair/timeframe (selected by profit factor). It does not re-optimize — it reads `sl_atr_multiplier`, `tp1_atr_multiplier`, `tp2_atr_multiplier` from the `backtest_runs.config` JSONB and uses those as starting learned values.

Note: backtest trade dicts do not store ATR or `raw_indicators`, so full replay optimization is not possible from backtest data alone. The bootstrap provides a reasonable starting point; actual optimization begins once enough live signals resolve.

---

## Integration Points

### Pipeline Integration (main.py)

```
run_pipeline()
  ├── ... existing scoring pipeline unchanged ...
  │
  ├── NEW: tracker.get_multipliers(pair, timeframe)
  │     → returns learned (sl, tp1, tp2) or defaults if < 40 resolved
  │
  ├── NEW: scale_atr_multipliers(score, bb_width_pct, sl, tp1, tp2)
  │     → applies strength_factor × vol_factor
  │
  └── calculate_levels(direction, price, atr, ...)
        → uses scaled multipliers

check_pending_signals()
  ├── resolve_signal_outcome() → unchanged
  │
  └── NEW: tracker.on_signal_resolved(pair, timeframe)
        ├── query live resolved_count from signals table (excluding levels_source="llm")
        ├── if count >= 40 and (count - last_optimized_count) >= 10:
        │     schedule optimization as background task (asyncio.create_task)
        │     to avoid blocking the outcome resolution loop
        │     update last_optimized_count = count
        └── log/flag adjustment
```

### Backtest Integration

- Phase 1 scaling applies during backtests (signal strength + volatility)
- Phase 2 learned multipliers are NOT used in backtests — backtests use whatever ATR multipliers are passed in the request config, then Phase 1 scales on top
- This lets you backtest different base multipliers while benefiting from dynamic scaling

### API Endpoints

| Endpoint                         | Method | Purpose                                       |
|----------------------------------|--------|-----------------------------------------------|
| `/api/engine/tuning`             | GET    | View current learned multipliers per bucket   |
| `/api/engine/tuning/reset`       | POST   | Reset a pair/timeframe bucket to defaults     |

---

## New Components

| Component                    | Location                          | Purpose                              |
|------------------------------|-----------------------------------|--------------------------------------|
| `scale_atr_multipliers()`    | `engine/combiner.py`              | Phase 1 strength + volatility scaling |
| `PerformanceTracker` class   | `engine/performance_tracker.py`   | Phase 2 rolling optimizer            |
| `PerformanceTrackerRow` model| `db/models.py`                    | Learned multipliers per bucket       |
| Alembic migration            | `db/migrations/`                  | Create `performance_tracker` table   |
| Tuning API endpoints         | `api/routes.py`                   | View/reset learned multipliers       |

## What Does NOT Change

- Scoring logic (technical, order flow, on-chain, patterns)
- Signal emission threshold or LLM gate
- Outcome resolver logic
- Risk management / position sizing
- Frontend (signals just arrive with better-calibrated levels)
