# Spec: Wire DE Sweep in Optimizer

**Date:** 2026-03-25
**Status:** Stub
**Scope:** Backend optimizer — `engine/optimizer.py`, `engine/backtester.py`
**Prerequisite:** Backtester param override plumbing from mr_pressure plan

---

## Problem

7 parameter groups in `param_groups.py` use `sweep_method: "de"` (differential evolution) but `run_counterfactual_eval` skips them:

```python
# optimizer.py:353-356
else:
    logger.info("DE sweep for %s not yet wired — skipping", group_name)
    return None
```

**Affected groups:** `regime_caps`, `regime_outer`, `sigmoid_curves`, `order_flow`, `pattern_strengths`, `llm_factors`, `onchain`.

These groups have continuous parameters with large search spaces that make grid sweep impractical (e.g., `regime_caps` has 16 params across 4 regimes).

## Prerequisite

The mr_pressure plan adds `BacktestConfig.param_overrides` and threads overrides through `compute_technical_score`. This plumbing must be extended to cover all parameter dot-paths used by DE groups (regime weights, sigmoid curves, order flow max scores, etc.).

## Design Decisions Needed

1. **Algorithm:** `scipy.optimize.differential_evolution` vs custom implementation. scipy adds a dependency but is battle-tested. Custom is lighter but needs convergence tuning.

2. **Objective function:** Currently grid sweep uses profit factor. DE could use a composite fitness (profit factor + win rate + Sharpe) since it has budget for more evaluations.

3. **Population size & generations:** Tradeoff between search quality and backtest compute time. 16-param `regime_caps` with pop=30, generations=50 = 1500 backtest runs per eval cycle.

4. **Timeout / budget:** Max wall-clock time or max evaluations per group to prevent blocking the optimizer loop.

5. **Constraint handling:** DE groups have constraints (e.g., regime caps sum to 100). scipy supports `NonlinearConstraint` or penalty functions. The existing `constraints` callables in param_groups could be adapted.

6. **Param override mapping:** Each DE group's dot-paths (e.g., `regime_weights.*.*.trending_trend_cap`) must map to the override structure consumed by the backtester. Some paths target `RegimeWeights` DB rows, others target constants.

## Scope Estimate

- Wire DE branch in `run_counterfactual_eval`: ~40 lines
- Extend param override plumbing to all dot-path types: ~30 lines
- Constraint adapter (param_groups callable -> scipy bounds): ~15 lines
- Tests: ~50 lines

**Total:** ~135 lines across 2-3 files.
