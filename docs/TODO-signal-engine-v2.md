# TODO: Signal Engine v2 -- Deferred Items

**Date:** 2026-03-24
**Context:** Identified during signal algorithm improvement analysis

## Problem

Differential Evolution (DE) parameter groups are fully defined in `backend/app/engine/param_groups.py` but the optimizer loop in `backend/app/engine/optimizer.py` explicitly skips them:

```python
# optimizer.py ~line 351-354
else:
    # DE-based groups: skip for now
    logger.info("DE sweep for %s not yet wired — skipping", group_name)
    return None
```

## Affected Groups

| Group | Params | Priority Layer |
|-------|--------|---------------|
| sigmoid_curves | 7 | Layer 2 |
| order_flow | 6 | Layer 2 |
| pattern_strengths | 15 | Layer 2 |
| llm_factors | 12 | Layer 2 |
| onchain | 10 | Layer 2 |
| regime_caps | 16 | Layer 1 |
| regime_outer | 16 | Layer 1 |

## What Works Today (Grid Only)

- source_weights
- thresholds
- atr_levels
- indicator_periods
- mean_reversion

## What Needs to Happen

1. Implement DE counterfactual evaluation in `run_counterfactual_eval()` using `scipy.optimize.differential_evolution` (already used in `regime_optimizer.py`)
2. Wire DE groups into the optimizer loop alongside grid groups
3. Consider adding manual parameter adjustment UI on the frontend engine page (currently read-only)

## Why It Matters

Sigmoid recalibration (e.g., funding rate steepness 8000 -> 400) was done with better defaults, but these values cannot be tuned at runtime. Until DE is wired, ~82 parameters across 7 groups are frozen at their initial values regardless of market conditions.

## Future Consideration: Meta-Tunable Optimizer Fitness Weights

The multi-metric optimizer fitness function uses hardcoded weights:

```
fitness = 0.35 * sharpe_norm + 0.25 * pf_norm + 0.25 * win_rate_norm - 0.15 * max_dd_norm
```

These are educated defaults, not proven optimal:
- **Sharpe (0.35)**: Rewards consistency over magnitude
- **Profit factor (0.25)**: Absolute gains-vs-losses
- **Win rate (0.25)**: System trust + psychological factor
- **Max drawdown penalty (0.15)**: Lower weight because partially captured by Sharpe already

Could be made into a tunable parameter group in `param_groups.py` in the future (meta-optimization). Deferred because the fitness weights are a judgment call about what "good trading" means -- better as a human decision for now. Revisit if the hardcoded weights produce unintuitive optimizer behavior.

## Future: Order Book Depth Scoring (Phase 2)

**Date:** 2026-03-24
**Context:** Identified during signal engine v2 design. Deferred because current 3 pairs (BTC, ETH, WIF) don't justify the added complexity, but the system is expected to expand to more pairs.

### Concept

Bid/ask imbalance in the top N levels of the order book predicts short-term directional pressure:
- Heavy bids relative to asks = bullish microstructure signal
- Most useful on shorter timeframes (15m, 1h) where microstructure matters

### Implementation Outline

1. **New collector**: Subscribe to OKX depth WebSocket channel (books5 or books50) per pair
2. **Scoring function**: Compute imbalance ratio, return dict with `score`, `confidence`, and `details` keys following the confidence-weighted blending pattern
3. **Combiner integration**: Add as a new source in the combiner's source list with its own base weight
4. **Backtester support**: Persist depth snapshots (similar to OrderFlowSnapshot) so optimizer can tune the parameters

### Why Deferred

- Adds a new high-frequency WebSocket feed with significant message volume
- Complexity not justified for 3 pairs during MVP
- Interface is fully defined in the v2 design spec -- wiring it in is straightforward when more pairs are added

### When to Revisit

- When expanding beyond 3-5 pairs
- When shorter timeframe signals (5m, 15m) become a priority
- When the confidence-weighted blending and IC-based pruning are proven stable

## Future: Liquidation Data Persistence for Backtester Replay

**Date:** 2026-03-24
**Context:** Liquidation data is currently in-memory only (lost on restart). This means the optimizer cannot tune liquidation parameters via backtesting, and IC-based source pruning cannot track a meaningful 30-day IC window for the liquidation source. Per-signal liquidation scores are stored in `engine_snapshot` JSONB on the Signal model for future IC computation.

### When to Add
- When manual observation confirms liquidation scoring adds value and parameter tuning would be beneficial
- Unblocks: IC pruning for liquidation source, optimizer tuning of liquidation parameters

## Future: Temperature Scaling Dedicated Calibration Split

**Date:** 2026-03-24
**Context:** Currently reuses the early-stopping validation split (`val_ratio=0.15`) for temperature scaling calibration. Acceptable for v1 since temperature scaling has 1 parameter, but with per-pair models the val set may be 50-100 samples.

### When to Add
- When per-pair training data grows beyond ~500 samples
- Split into 3 sets: train (70%), val for early stopping (15%), calibration for temperature (15%)

## Future: Regime Dwell Time

**Date:** 2026-03-24
**Context:** Deferred from initial v2 implementation. EMA smoothing (alpha=0.3) already prevents single-candle regime whipsaws. Dwell time (3-candle lock on dominant regime label) was dropped because it only affected logging/debugging — the continuous mix still drives scoring regardless.

### When to Add
- If EMA smoothing alone proves insufficient to prevent rapid regime label oscillation in logs/alerts
- Implementation: After dominant regime changes, lock label for 3 candles while smoothed mix continues updating
