# Regime Detection Improvement — Research Notes

Reference notes for the regime detection & adaptive weighting improvement effort.

## Current Architecture

### Regime Detection (engine/regime.py)

- Two inputs: ADX (trend strength) and BB width percentile (volatility expansion), both sigmoid-scaled to [0, 1]
- 2x2 matrix produces 4 continuous regime archetypes: trending, ranging, volatile, steady
- EMA-smoothed per pair/timeframe (alpha=0.3) to prevent single-candle flips
- Two output layers:
  - **Inner caps**: limit how much each technical dimension (trend, mean_rev, squeeze, volume) can contribute
  - **Outer weights**: control how much each source (tech, flow, onchain, pattern, liquidation) matters in the final blend

### Backtester (engine/backtester.py)

- Calls `compute_preliminary_score()` but hardcodes `order_flow_score=0`, `flow_weight=0.0`, `onchain_score=0`, `onchain_weight=0.0`
- Only uses **tech + pattern** scoring with either explicit config weights or regime-blended weights
- Missing sources handled by passing 0 score/weight; combiner renormalizes available sources

### Regime Optimizer (engine/regime_optimizer.py)

- Uses scipy `differential_evolution` to optimize inner caps (bounds: 10-45) and outer weights for **tech + pattern only**
- Flow/onchain/liquidation outer weights are NOT optimized because those data sources aren't available during backtesting
- Fitness: `win_rate*0.4 + profit_factor*0.3 + avg_rr*0.2 - max_dd*0.1` (min 20 trades)

### Signal Model (db/models.py)

- `Signal.final_score` (Integer): ultimate decision score after all blending
- `Signal.traditional_score` (Integer): technical analysis score only
- **No per-source score columns** — all detail scores are in `raw_indicators` JSONB:
  - Flow details: `flow_contrarian_mult`, `flow_roc_boost`, `funding_rate`, `open_interest_change_pct`, `long_short_ratio`
  - Liquidation: `liquidation_score`, `liquidation_confidence`
  - ML: `ml_score`, `ml_confidence`
  - Regime: `regime_trending`, `regime_ranging`, `regime_volatile`, `effective_caps`, `effective_outer_weights`
  - Blended scores: `blended_score`, `indicator_preliminary`
- **Missing**: individual `tech_score`, `flow_score`, `onchain_score`, `pattern_score` are NOT persisted in `raw_indicators` — they are logged but not stored on the signal record

### OrderFlowSnapshot Model (db/models.py)

- Created every candle cycle during pipeline evaluation
- Fields: `pair`, `timestamp`, `funding_rate`, `open_interest`, `oi_change_pct`, `long_short_ratio`, `cvd_delta`
- Indexed on `(pair, timestamp)`, no uniqueness constraint
- Seeded from DB at startup into `app.state.order_flow`

### Pipeline Flow (main.py)

1. `compute_technical_score(df, regime_weights)` returns score, indicators, regime mix, caps
2. `smooth_regime_mix()` via `app.state.smoothed_regime`
3. `blend_outer_weights(regime, regime_weights)` produces source weights
4. Unavailable sources zeroed out and weights renormalized
5. `compute_preliminary_score()` with confidence-weighted sources
6. ML gate, LLM gate, threshold check, signal emission

## Identified Gaps

1. **Backtester cannot use order flow data** — `OrderFlowSnapshot` exists per candle but the backtester doesn't load or replay it
2. **Per-source scores not persisted on signals** — can't re-run combiner with different outer weights on historical signals
3. **Optimizer only tunes tech + pattern** — flow/onchain/liquidation defaults are handcrafted, never validated
4. **Fixed smoothing alpha** — same alpha=0.3 for all pairs and timeframes

## Planned Approach

### B: Wire OrderFlowSnapshot into Backtester

- Load `OrderFlowSnapshot` records alongside candle history
- Replay flow data per candle so the backtester can call `compute_order_flow_score()` with real data
- Allows DE optimizer to tune flow outer weights where snapshot data exists

### C: Periodic DE Optimizer on Resolved Signals

- Persist per-source scores (`tech_score`, `flow_score`, `onchain_score`, `pattern_score`, `liquidation_score`) on `raw_indicators`
- Periodically run the DE optimizer against resolved signals with real per-source scores
- Covers all 5 outer weight categories using actual production data
- Only works on signals emitted after per-source score persistence ships; sufficient historical signals exist for initial coverage

### Future: Additional Regime Inputs

- Deferred until B + C infrastructure is in place
- Once the optimizer can measure impact, new regime inputs become testable hypotheses (A/B backtest with and without)
