# Signal Engine v2 -- Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Scope:** Ambitious overhaul of the signal scoring pipeline -- calibration fixes, confidence-weighted blending, optimizer improvements, risk management, and new data sources.
**Constraints:** No backward compatibility required (MVP). Clean break on scoring scale, thresholds, and schema is acceptable.

---

## 1. Sigmoid Recalibration & Threshold Fixes

### Problem

Several sigmoids are miscalibrated, producing binary instead of gradual scoring. The funding rate sigmoid (steepness=8000) only activates at extreme values (~+-0.0001). EMA alignment is a discrete 0/0.5/1.0 instead of continuous.

### Changes

**Funding rate sigmoid**: Reduce steepness from 8000 to ~300-500. This activates across the typical +-0.01% to +-0.05% funding range instead of only at extremes.

**OI change sigmoid**: Reduce steepness from 65 to ~15-25. Responds to 2-10% OI changes instead of being binary.

**Continuous EMA alignment**: Replace the 3-step function (0/0.5/1.0) with a continuous measure based on normalized distance between EMA pairs: `(ema8 - ema21) / ATR` passed through a sigmoid. Preserves direction, adds magnitude sensitivity.

**All sigmoid parameters consolidated in `constants.py`** with clear documentation of their activation ranges.

### Scope

- Files: `engine/constants.py`, `engine/traditional.py`, `engine/param_groups.py` (update bounds for recalibrated sigmoid defaults)
- No structural changes. Scoring ranges (-100 to +100) unchanged.
- DE wiring for runtime tuning is deferred (tracked in `docs/TODO-signal-engine-v2.md`).

---

## 2. Regime Detection Improvements

### Problem

Regime mix (trending/ranging/volatile/steady) can flip on a single candle with no smoothing. BB width percentile computed over only 50 candles. No per-asset ADX calibration.

### Changes

**EMA smoothing on regime mix**: Apply EMA (alpha ~0.3) to the 4 regime components across consecutive candles. Prevents single-candle whipsaws while adapting within 3-5 candles to genuine regime shifts. Smoothed state stored in `app.state` keyed by `(pair, timeframe)`, initialized from raw values on cold start (same pattern as `app.state.order_flow`).

**BB width percentile window**: Expand from 50 to 100 candles for more stable volatility context. Still within the 200-candle Redis cache. Update `INDICATOR_PERIODS["bb_width_percentile_window"]` constant accordingly. **Implementation note**: Verify that `regime.py` and `traditional.py` actually read this constant rather than using a hardcoded 50. If hardcoded, wire the constant first before changing its value.

**Per-pair ADX center**: Store a learned ADX midpoint per (pair, timeframe) in `RegimeWeights` table, initialized at 20 but updated from rolling median ADX. Allows WIF (typically higher ADX) to have different regime boundaries than BTC.

### Scope

- Files: `engine/regime.py`, `engine/constants.py`, `db/models.py` (RegimeWeights table -- add `adx_center` column), `main.py` (initialize smoothed regime state in `app.state`)
- 4-regime model, inner cap system, outer weight blending unchanged.

---

## 3. Confidence-Weighted Blending

### Problem

The combiner uses flat outer weights regardless of whether a source's data is stale, noisy, or high-conviction. All signals treated equally once above threshold.

### Architecture Clarification

The pipeline has two weighting layers:
- **Inner caps** (from `regime.py`): Per-regime caps on technical sub-score components (trend, mean_rev, squeeze, volume). These constrain `compute_technical_score()` output. **Unchanged by this section.**
- **Outer weights** (also from `regime.py` via `blend_outer_weights()`): Blend the four scoring sources (tech, flow, onchain, pattern) in `compute_preliminary_score()`. **This is where confidence weighting applies.**

**Prerequisite**: Verify that the live pipeline in `main.py` threads regime-blended outer weights (from `blend_outer_weights()`) into `compute_preliminary_score()`. If not, wire that as the first step before adding confidence modulation.

### Changes

**Source confidence emission**: Each scoring function adds a `confidence` key (0.0-1.0) to its return dict, derived from data quality. This preserves the existing rich-metadata dict pattern (`{"score": int, "details": dict, ...}`) used across all scorers — no return-type changes, only a new key. For `compute_onchain_score()` (currently returns bare `int`), upgrade to dict return: `{"score": int, "confidence": float}`. The caller in `main.py` must be updated to read `result["score"]` and `result["confidence"]` instead of using the bare int.

| Source | Confidence derived from |
|--------|------------------------|
| Technical | Candle count (ramps 0.5 at 70 candles to 1.0 at 150+) and indicator agreement (trend + volume aligned = higher) |
| Order flow | Data freshness (decays if last snapshot >5 min old) and completeness (all 3 metrics = 1.0, missing any = proportional reduction) |
| On-chain | Data freshness: check timestamp stored alongside Redis value (not Redis TTL). Unsupported pairs = 0.0. Note: `compute_onchain_score` is async; caller in `main.py:453-454` must be updated from `onchain_score = await compute_onchain_score(...)` to `onchain_result = await compute_onchain_score(...)` then `onchain_score = onchain_result["score"]`, `onchain_confidence = onchain_result["confidence"]`. The current `onchain_available = onchain_score != 0` check must also change to use confidence (`onchain_available = onchain_confidence > 0.0`). |
| Pattern | Volume confirmation strength and number of confirming patterns |
| Liquidation (new) | Data freshness and cluster density near price |

**Combiner formula** (applied at the outer-weight level):
```
# base_weight_i = regime-blended outer weight from blend_outer_weights()
effective_weight_i = base_weight_i * confidence_i
renormalize effective_weights to sum to 1.0
blended = sum(effective_weight_i * score_i)
```

A source with confidence 0.0 naturally drops out. High-confidence sources get proportionally more influence. The inner cap system within `compute_technical_score` is unaffected.

**Signal confidence tier**: The final blended score gets an overall confidence derived from weighted average of source confidences. Exposed to frontend as `high` / `medium` / `low`. Stored on the Signal model as a new field.

### Scope

- Files: `engine/traditional.py` (add `confidence` key to return dict), `engine/onchain_scorer.py` (async, upgrade from bare `int` return to `{"score": int, "confidence": float}` dict), `engine/patterns.py` (add `confidence` key), `engine/combiner.py` (read `confidence` from source dicts, apply weighted formula), `main.py` (regime-blended outer weights already wired — verified at lines 460-484; update on-chain caller at lines 453-454 to read dict instead of bare int), `db/models.py` (Signal model -- add `confidence_tier` varchar, nullable)
- Frontend: signal list and signal detail views display confidence tier.
- Score range (-100 to +100) and base outer weights unchanged. Inner cap system unchanged.

---

## 4. Flow/On-chain in Backtester

### Problem

Backtester zeros out flow and on-chain weights, making the optimizer blind to ~45% of scoring sources.

### Changes

**Historical flow replay**: Load `OrderFlowSnapshot` records for the backtest window. For each candle, find the snapshot closest to the candle's timestamp via bisect lookup. Build a rolling `flow_history` list from the preceding 10 snapshots (matching the live pipeline's RoC window). Feed the current snapshot as `metrics` and the history list as `flow_history` to `compute_order_flow_score()`. Missing snapshots for a candle result in flow confidence = 0.0 (handled by confidence-weighted blending).

**On-chain snapshot persistence**: New `OnchainSnapshot` table:
```
pair: str
timestamp: datetime
metric_name: str  (e.g., "btc_exchange_netflow", "eth_gas_trend")
value: float
```
On-chain scorer writes to this table alongside Redis. Backtester loads snapshots for replay, grouped by (pair, timestamp) and reconstructed into the metrics dict format expected by `compute_onchain_score()`.

**Coverage-gated optimization**: Backtester reports coverage % for flow and on-chain data per run. When optimizing flow/on-chain parameter groups, fitness is computed only over the subset of candles that have flow/on-chain snapshots present — this gives accurate fitness even at low coverage. If fewer than 30 candles have data for a source, optimizer skips tuning that source's parameters entirely (too few samples for meaningful fitness). When optimizing, optimizer selects the most recent window where covered candle count is sufficient.

**Backtester config update**: Remove hardcoded `flow_weight=0, onchain_weight=0`. Use regime-based outer weights matching the live pipeline.

### Missing data handling

Candles without flow/on-chain snapshots get confidence 0.0 for that source. Other sources absorb the weight via renormalization. No imputation or synthetic fill. The backtester produces mixed-fidelity results -- this is realistic and mirrors live behavior when a data source drops out.

### Scope

- Files: `engine/backtester.py`, `engine/onchain_scorer.py`, `engine/optimizer.py`, `db/models.py` (new OnchainSnapshot model)
- New Alembic migration for OnchainSnapshot table.

---

## 5. ML Calibration

### Problem

LSTM softmax outputs are overconfident. No epistemic uncertainty estimate. Feature truncation silently drops features on input size mismatch.

### Changes

**Temperature scaling**: After training, learn a single scalar `T` on a held-out validation set that rescales logits: `softmax(logits / T)`. Uses the same validation split as early stopping (`val_ratio=0.15` in TrainConfig) -- this is acceptable since temperature scaling has only 1 parameter and overfitting risk is negligible. Stored in the model checkpoint JSON sidecar. No architecture change. **Note**: With per-pair models the validation set may be as small as 50-100 samples. Acceptable for v1, but revisit with a dedicated calibration split when training data grows (tracked in TODO).

**MC Dropout for uncertainty**: At inference, run 5 forward passes with dropout enabled (reduced from 10 to respect CPU latency budget -- must complete in <2s per pair on the Docker container's CPU). Mean of predictions = calibrated score. Variance across passes = epistemic uncertainty. High variance reduces ML confidence proportionally, feeding into confidence-weighted blending. If latency proves acceptable, can be increased to 10 later.

**Feature layout versioning**: Each checkpoint sidecar records expected feature names (ordered list). At load time, predictor maps available features to expected features by name, fills missing with 0, logs warnings. Replaces silent truncation.

**Stale model handling**: Replace input_size heuristic with checkpoint age check. Models not retrained within N days (configurable, default 14) get confidence reduced to 0.3 instead of returning neutral.

### Scope

- Files: `ml/predictor.py`, `ml/trainer.py`, `ml/model.py`
- SignalLSTM architecture unchanged. Training pipeline unchanged. Per-pair model approach unchanged.

---

## 6. Optimizer Fitness & Shadow Testing

### Problem

Optimizer uses profit factor as sole fitness metric. PF is brittle with small samples. Shadow testing uses fixed 20-signal window with no statistical significance check.

### Changes

**Multi-metric fitness function**:
```
fitness = 0.35 * sharpe_norm + 0.25 * pf_norm + 0.25 * win_rate_norm - 0.15 * max_dd_norm
```
Each metric normalized to [0, 1]. Fitness weights are hardcoded defaults (meta-tuning deferred, tracked in `docs/TODO-signal-engine-v2.md`).

**Statistical significance gate**: Shadow testing requires minimum 20 signals but continues until a one-tailed proportional z-test reaches p < 0.10 (or max 60 signals). Prevents promoting changes that look good on a lucky run.

**Rollback window expansion**: Last 10 -> last 20 signals. PF drop threshold 15% -> 20%. Reduces false-positive rollbacks.

**Coverage-gated optimization**: From Section 4 -- optimizer skips flow/on-chain parameter groups when backtest coverage is insufficient.

**IC pruning interaction**: When IC-based pruning (Section 8) sets a source weight to 0, the optimizer's fitness evaluation accounts for this -- backtests run with the pruned source disabled, so fitness reflects reality.

### Scope

- Files: `engine/optimizer.py`, `engine/backtester.py`
- Shadow testing concept, proposal lifecycle, priority layers, 60s loop interval, auto-rollback mechanism all unchanged.

---

## 7. Risk Management Improvements

### Problem

Position sizing ignores cross-pair correlation. Daily loss limit is flat 3% with no drawdown tracking. All signals sized equally regardless of confidence.

### Changes

**Correlation-adjusted position sizing**: Maintain rolling 30-day return correlation matrix using 1h candle returns (balances noise vs responsiveness). Stored in `app.state` as a numpy array, recomputed daily. With 3 pairs this is a 3x3 matrix. **Cold start**: When fewer than 7 days of 1h candle data exist for any pair, default to identity matrix (zero cross-pair correlation assumed, no position reduction applied). This is conservative — it allows full sizing during warm-up rather than guessing correlations. When two correlated pairs have open positions in the same direction, reduce the newer position's size proportional to both correlation and the existing position's size relative to equity:
```
reduction = correlation * (existing_position_value / equity)
new_size = base_size * max(0.2, 1 - reduction)
```
Floor of 0.2 prevents complete suppression. Example: BTC LONG using 10% of equity, ETH LONG triggers with 0.8 correlation -> reduction = 0.8 * 0.1 = 0.08, ETH sized at 92% of normal. If BTC were using 50% of equity -> reduction = 0.4, ETH at 60%.

**Confidence-based sizing**: Scale position size by signal confidence tier. High = 100%, medium = 70%, low = 50%.

**Fractional Kelly**: Replace fixed `risk_per_trade` with 20% Kelly fraction. Kelly formula: `f* = (b*p - q) / b` where `b` = avg_win/avg_loss, `p` = win_rate, `q` = 1-p. Computed from rolling 100 resolved signals per (pair, timeframe). Falls back to current fixed percentage when < 40 resolved signals exist. If Kelly computes negative (strategy is losing money), use 25% of the fixed `risk_per_trade` as a probe size — full fallback would ignore the Kelly signal entirely. Caps at existing `max_position_size_usd` and 25% equity limits.

**Sizing interaction order**: `kelly_base * confidence_multiplier * correlation_adjustment`. Each step can only reduce, never increase beyond Kelly base.

**Drawdown-aware daily limit**: Track peak equity intraday. If drawdown from today's peak exceeds 3%, pause new signal emission until next UTC day. Stricter than current flat 3% loss limit.

### Scope

- Files: `engine/risk.py`, `main.py` (where risk guard is checked before signal emission)
- PositionSizer/RiskGuard class structure unchanged. Lot rounding, min order size, max concurrent, cooldown unchanged.

---

## 8. New Data Sources

### Phase 1 (This Implementation)

**Liquidation level scoring**:
- Data source: OKX `/api/v5/public/liquidation-orders` REST endpoint, polled every 5 minutes. Returns individual recent liquidation events, not pre-aggregated clusters.
- Aggregation logic: Bucket liquidation events by price level (bucket width = 0.25 * ATR). Maintain a rolling 24h window of events. Apply exponential decay (half-life 4h) so recent liquidations weigh more. Cluster = any bucket with total liquidation volume > 2x median bucket volume.
- Scoring: When price approaches a dense cluster (within 2 ATR), boost signal in that direction. Score magnitude scales with cluster density relative to median. Clusters behind price act as S/R zones for level placement.
- Integrates with structure snapping as additional S/R zones alongside swing pivots.
- Returns `{"score": int, "confidence": float, "clusters": list}` dict (consistent with other scorers). Confidence based on data freshness and cluster density.
- Works for all perpetual pairs including WIF.
- **Backtester limitation**: Liquidation data is ephemeral (in-memory, lost on restart). No persistence table -- backtester cannot replay liquidation data. Optimizer skips liquidation parameters when backtesting (same coverage-gated pattern as flow/on-chain). Liquidation persistence can be added later if optimizer tuning proves valuable.

**IC-based source pruning**:
- Track rolling 30-day Information Coefficient per (source, pair, timeframe): correlation between source score and subsequent signal outcome.
- If IC < -0.05 for 30 days, set base weight to 0, log warning.
- Re-enable when IC recovers above 0.0.
- **Liquidation source excluded from IC pruning** until liquidation data persistence is added (deferred item #4). Without persistence, IC history resets on every restart and cannot maintain a meaningful 30-day window. The liquidation source's per-signal scores are still recorded in `engine_snapshot` JSONB for future IC computation once persistence exists.
- Stored in `SourceICHistory` DB table (must persist across restarts for 30-day window):
  ```
  source: str (e.g., "technical", "order_flow")
  pair: str
  timeframe: str
  date: date
  ic_value: float
  ```

**On-chain graceful degradation**:
- Unsupported pairs return confidence=0.0 instead of score=0 with implicit confidence=1.0.
- Handled by confidence-weighted blending -- source drops out naturally.

### Phase 2 (Deferred -- tracked in `docs/TODO-signal-engine-v2.md`)

**Order book depth scoring**:
- New collector: OKX depth WebSocket channel (books5 or books50).
- Scoring: Bid/ask imbalance in top N levels. Heavy bids vs asks = directional microstructure signal. Most useful on 15m/1h timeframes.
- Returns dict with `score`, `confidence`, and `details` keys (consistent with other scorers).
- New entry in combiner source list with own base weight.
- Persist depth snapshots for backtester (similar to OrderFlowSnapshot pattern).
- Deferred because current 3 pairs don't justify the high-frequency WebSocket overhead. Architecture designed to accommodate it. Revisit when expanding beyond 3-5 pairs.

### Scope

- New files: `collector/liquidation.py`, `engine/liquidation_scorer.py`
- Modified files: `engine/combiner.py` (new source + 5th weight slot), `engine/regime.py` (add liquidation to DEFAULT_OUTER_WEIGHTS per regime), `engine/structure.py` (liquidation zones as S/R), `engine/optimizer.py` (IC tracking interaction with fitness), `engine/param_groups.py` (add liquidation weight to regime_outer group), `db/models.py` (RegimeWeights -- add liquidation outer weight column)
- New DB: `OnchainSnapshot` (from Section 4), `SourceICHistory`
- New Alembic migrations for OnchainSnapshot, SourceICHistory, and RegimeWeights (liquidation weight column).

---

## 9. Adaptive Signal Threshold

### Problem

Global signal threshold (default 40) applied uniformly. BTC in a trend produces scores 60-80 while WIF ranging peaks at 45. Global threshold either misses good WIF signals or lets through weak BTC signals.

### Changes

**Per-pair, per-regime threshold**: Stored in `PipelineSettings` table (or new lightweight table). Initialized at global default (40). Updated by optimizer as a **separate lightweight pass** after the main parameter optimization completes — each (pair, regime) bucket is swept independently as a 1D search, not jointly with other parameters. This avoids exploding the grid search space (3 pairs x 4 regimes = 12 thresholds in a joint grid is prohibitive).

**Threshold learning rule**: For each (pair, regime) bucket, find threshold maximizing multi-metric fitness (from Section 6) over rolling outcome window. Requires minimum 10 resolved signals in that bucket before overriding default (lower than the standard 20 minimum used elsewhere, since threshold is a simpler 1D parameter). For rare buckets (e.g., WIF in volatile regime), convergence may take weeks -- the fallback cascade handles this gracefully.

**Fallback cascade**:
1. (pair, regime) -- specific learned threshold
2. (pair, any_regime) -- pair-level average
3. (any_pair, regime) -- regime-level average
4. Global default

**LLM threshold interaction**: Per-pair signal thresholds do not affect the LLM threshold (remains global). The signal threshold check happens after LLM contribution is added to the blended score, so there is no risk of wasted LLM calls from mismatched thresholds. Test case: verify that a per-pair threshold lower than the LLM threshold does not cause unnecessary LLM invocations.

**Frontend**: Settings page keeps single "Default Threshold" slider (sets the global fallback). Per-pair/per-regime overrides displayed read-only on the engine page alongside other optimizer-tuned params.

### Scope

- Files: `main.py` (threshold lookup in `run_pipeline`), `engine/optimizer.py` (expanded grid), `engine/param_groups.py` (register per-pair/regime threshold params), `db/models.py` (threshold storage)
- Frontend: `features/settings/` (rename label), `features/engine/` (display overrides)
- LLM threshold and ML confidence threshold remain global.

---

## Cross-Cutting Concerns

### Data Model Changes

| Change | Table | Migration |
|--------|-------|-----------|
| Signal confidence tier | Signal (add `confidence_tier` varchar, nullable) | Yes |
| On-chain snapshots | OnchainSnapshot (new table) | Yes |
| Per-pair ADX center | RegimeWeights (add `adx_center` float) | Yes |
| Per-pair/regime threshold | PipelineSettings or new table | Yes |
| Source IC tracking | SourceICHistory (new table) | Yes |
| Liquidation data | In-memory or Redis (no persistence needed beyond cache) | No |

### Frontend Changes

| Area | Change |
|------|--------|
| Signal list/detail | Display confidence tier badge (high/medium/low) |
| Engine page | Display per-pair/per-regime threshold overrides (read-only) |
| Settings page | Rename threshold slider to "Default Threshold" |

### Backward Compatibility

None required. Clean break acceptable. Existing signals in DB will lack `confidence_tier` (nullable field, frontend handles gracefully). Scoring scale remains -100 to +100 for continuity but thresholds and internal mechanics change freely.

### Testing Strategy

Each section should have unit tests covering:
- Sigmoid recalibration: verify activation ranges match documented expectations
- Regime smoothing: verify no single-candle flips, verify cold-start initialization from raw values
- Confidence blending: verify source with confidence=0 drops out, verify renormalization, verify on-chain dict return (`{"score", "confidence"}`) handled correctly in main.py caller
- Backtester flow replay: verify snapshot-to-candle timestamp alignment via bisect, verify flow_history rolling window construction, verify fitness computed only over covered candle subset
- ML calibration: verify temperature scaling changes output distribution, verify MC Dropout variance reduces confidence, verify <2s latency with 5 passes
- Optimizer fitness: verify multi-metric composite, verify z-test gate, verify IC pruning interaction (liquidation source excluded)
- Risk correlation: verify position size reduction scales with both correlation and existing position size, verify identity matrix fallback on cold start (<7 days data), verify Kelly negative output uses 25% probe size
- Liquidation scoring: verify bucket aggregation, decay, cluster detection, and S/R integration
- Adaptive threshold: verify fallback cascade, verify per-pair/regime lookup, verify LLM threshold non-interaction, verify 1D sweep runs as separate pass after main optimizer

---

## New Constants -- Tunability Status

Constants introduced in this spec that are intentionally hardcoded (not optimizer-tunable) for initial implementation:

| Constant | Section | Value | Rationale for hardcoding |
|----------|---------|-------|-------------------------|
| Regime EMA alpha | 2 | 0.3 | Smoothing factor; changing it has subtle effects on regime lag -- human tuning preferred |
| MC Dropout passes | 5 | 5 | Performance constraint, not a quality knob |
| Correlation warm-up days | 7 | 7 days | Below this, identity matrix used; tuning not useful |
| Kelly probe fraction | 7 | 0.25 | Fraction of fixed risk_per_trade used when Kelly is negative |
| Kelly fraction | 7 | 0.20 | Risk tolerance decision -- should be human-set |
| Confidence sizing multipliers | 7 | 1.0/0.7/0.5 | Simple mapping; optimizer could chase noise here |
| Correlation floor | 7 | 0.2 | Safety floor; should not be optimizer-adjustable |
| Liquidation bucket width | 8 | 0.25 * ATR | Geometric parameter; will tune manually based on observation |
| Liquidation decay half-life | 8 | 4h | Deferred to optimizer once liquidation persistence added |
| Liquidation cluster threshold | 8 | 2x median | Deferred to optimizer once liquidation persistence added |
| IC pruning threshold | 8 | -0.05 | Conservative default; adjust based on observed IC distributions |

These can be promoted to `param_groups.py` later if manual observation suggests they need data-driven tuning.

---

## Deferred Items

Tracked in `docs/TODO-signal-engine-v2.md`:
1. Wire DE sweep in optimizer (~82 params across 7 groups)
2. Meta-tunable optimizer fitness weights
3. Order book depth scoring (Phase 2 data source)
4. Liquidation data persistence for backtester replay (also unblocks IC pruning for liquidation source)
5. Dedicated temperature scaling calibration split (separate from early-stopping val set) when per-pair training data grows beyond ~500 samples
6. Regime dwell time (3-candle lock on dominant label) — deferred from initial implementation since EMA smoothing already prevents single-candle whipsaws; add only if EMA alone proves insufficient
