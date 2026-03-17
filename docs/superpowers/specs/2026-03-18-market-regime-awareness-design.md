# Market Regime Awareness Design

## Problem

Indicator weights are static (tech 40%, flow 22%, on-chain 23%, pattern 15%) regardless of market conditions. Inner technical sub-component caps (trend ±30, mean-reversion ±25, BB volatility ±25, volume ±20) are also fixed. Trend indicators produce noise in ranges. Mean-reversion signals fire during strong trends. The algorithm doesn't adapt to what's actually working in current conditions.

## Approach

Smooth regime detection using existing ADX + BB width percentile, producing a continuous regime mix (trending/ranging/volatile). The regime mix adjusts both inner sub-component caps inside `compute_technical_score()` and outer blend weights in `compute_preliminary_score()`. Weight tables are learnable per (pair, timeframe) via backtest optimization, with sensible hand-tuned defaults.

## Regime Detection

Inside `compute_technical_score()`, after computing ADX and BB width percentile (already computed at current lines 90-108), derive a continuous regime mix using two axes:

**Trend axis:** `trend_strength = sigmoid_scale(adx, center=20, steepness=0.25)` → 0.0 to 1.0
- ADX 10 → ~0.07 (no trend)
- ADX 20 → ~0.50 (threshold)
- ADX 35 → ~0.98 (strong trend)

**Volatility axis:** `vol_expansion = sigmoid_scale(bb_width_pct, center=50, steepness=0.08)` → 0.0 to 1.0
- BB width pct 20 → ~0.08 (narrow/contracting)
- BB width pct 50 → ~0.50 (neutral)
- BB width pct 80 → ~0.92 (expanding)

**Three regime weights** (normalized to sum to 1.0):

```
raw_trending  = trend_strength × vol_expansion
raw_ranging   = (1 - trend_strength) × (1 - vol_expansion)
raw_volatile  = (1 - trend_strength) × vol_expansion
total = raw_trending + raw_ranging + raw_volatile
regime = {trending: raw_trending/total, ranging: raw_ranging/total, volatile: raw_volatile/total}
```

The fourth quadrant (high trend + low vol, i.e., a quiet grinding trend) maps to approximately 80% trending + 18% ranging. This is intentional — the trending profile's momentum-following behavior still applies, while the partial ranging blend slightly tempers mean-reversion suppression, which is appropriate for low-volatility trends where mean-reversion is less harmful than in explosive trends.

These three values are added to the indicators dict (`regime_trending`, `regime_ranging`, `regime_volatile`) for downstream use and debugging.

## Weight Table Structure

A `RegimeWeights` DB table stores per-(pair, timeframe) weight profiles for each regime. Each row has 24 stored floats (8 effective parameters × 3 regime columns).

### Inner Caps

Used inside `compute_technical_score()` to replace hardcoded component caps:

| Parameter | Default Trending | Default Ranging | Default Volatile |
|-----------|-----------------|----------------|-----------------|
| `trend_cap` | 38 | 18 | 22 |
| `mean_rev_cap` | 15 | 32 | 20 |
| `bb_vol_cap` | 22 | 28 | 28 |
| `volume_cap` | 25 | 22 | 15 |

Caps are independent — they don't need to sum to 100. The total score is clamped to ±100.

The volatile regime sums to 85 (vs 100 for trending/ranging). This is intentional — choppy, directionless markets should produce lower-magnitude technical scores, making it harder to reach the signal threshold. This acts as implicit signal suppression in conditions where signals are least reliable.

### Outer Blend Weights

Used in `compute_preliminary_score()`:

| Parameter | Default Trending | Default Ranging | Default Volatile |
|-----------|-----------------|----------------|-----------------|
| `tech_weight` | 0.45 | 0.38 | 0.30 |
| `flow_weight` | 0.25 | 0.18 | 0.20 |
| `onchain_weight` | 0.18 | 0.26 | 0.25 |
| `pattern_weight` | 0.12 | 0.18 | 0.25 |

Outer weights per regime column sum to 1.0.

### Effective Weight Blending

At runtime, the 8 effective parameters are each a dot product of the regime mix × that parameter's 3 regime column values:

```
effective_trend_cap = regime.trending × trending.trend_cap
                    + regime.ranging  × ranging.trend_cap
                    + regime.volatile × volatile.trend_cap
```

Same for all 8 parameters (4 inner caps + 4 outer weights).

### Default Rationale

- **Trending**: Boost trend + volume (momentum confirmation), suppress mean-reversion (fights the trend). Higher tech + flow weight (trend signals + order flow most informative).
- **Ranging**: Boost mean-reversion + BB position (core range tools), suppress trend (noise). Higher onchain + pattern weight (support/resistance matters more).
- **Volatile**: Reduce volume (unreliable in chop), boost BB + pattern (volatility tools). Spread outer weights more evenly, reduce tech (noisy). Lower total inner cap sum (85) intentionally suppresses signal magnitude in choppy conditions.

## Integration into `compute_technical_score()`

`compute_technical_score()` gains an optional `regime_weights` parameter:

1. Compute regime mix from ADX + BB width pct
2. Blend effective caps from weight table (or defaults if None)
3. Apply effective caps to scoring:

```python
def compute_technical_score(candles, regime_weights=None):
    # ... existing indicator computation unchanged ...

    # Regime detection
    trend_strength = sigmoid_scale(adx_val, center=20, steepness=0.25)
    vol_expansion = sigmoid_scale(bb_width_pct, center=50, steepness=0.08)
    regime = compute_regime_mix(trend_strength, vol_expansion)

    # Blend effective caps
    caps = blend_caps(regime, regime_weights)

    # Scoring with effective caps
    trend_score = di_sign * sigmoid_scale(adx_val, ...) * caps["trend_cap"]
    rsi_score = sigmoid_score(50 - rsi_val, ...) * caps["mean_rev_cap"]
    bb_pos_score = sigmoid_score(0.5 - bb_pos, ...) * (caps["bb_vol_cap"] * 0.6)
    bb_width_score = bb_pos_sign * sigmoid_score(...) * (caps["bb_vol_cap"] * 0.4)
    obv_score = sigmoid_score(...) * (caps["volume_cap"] * 0.6)
    vol_score = candle_direction * sigmoid_score(...) * (caps["volume_cap"] * 0.4)

    indicators["regime_trending"] = round(regime["trending"], 4)
    indicators["regime_ranging"] = round(regime["ranging"], 4)
    indicators["regime_volatile"] = round(regime["volatile"], 4)

    return {"score": score, "indicators": indicators, "regime": regime}
```

`bb_vol_cap` splits 60/40 between BB position and BB width (preserving current ratio of 15:10). `volume_cap` splits 60/40 between OBV and volume ratio (preserving current 12:8 ratio).

When `regime_weights` is None, `blend_caps()` uses hardcoded defaults.

## Pipeline Integration

### `run_pipeline()` Changes

In `run_pipeline()`, load the regime weights for the current (pair, timeframe) and pass them through the full scoring chain:

```python
    # Look up learned regime weights (or None for defaults)
    rw_key = (pair, timeframe)
    regime_weights = app.state.regime_weights.get(rw_key)

    # compute_technical_score with regime-aware caps
    tech_result = compute_technical_score(df, regime_weights=regime_weights)

    # ... confluence scoring (unchanged — applied after regime-adjusted tech score, clamped to ±100) ...

    # Regime-aware outer weight blending
    regime = tech_result.get("regime")
    outer_weights = blend_outer_weights(regime, regime_weights)
```

### Interaction with Confluence Scoring

Confluence scoring from item #1 remains unchanged. The order of operations is: regime-adjusted tech score → add confluence → clamp to ±100. Confluence is not regime-adjusted — it always operates at its configured `max_score` regardless of regime.

### Unavailable Source Handling

The existing unavailable-source zeroing logic in `run_pipeline()` (which sets weight to 0 when a source has no data) must operate on the regime-blended outer weights, not the static settings defaults. After `blend_outer_weights()` produces the regime-aware weights, the unavailable-source check zeros out any source that returned no data, then renormalizes the remaining weights before passing to `compute_preliminary_score()`:

```python
    # Zero out unavailable sources from regime-blended weights
    if flow_score == 0 and not has_flow_data:
        outer_weights["flow"] = 0
    if onchain_score == 0 and not has_onchain_data:
        outer_weights["onchain"] = 0
    # ... renormalize remaining weights to sum to 1.0 ...

    preliminary = compute_preliminary_score(
        technical_score=tech_result["score"],
        order_flow_score=flow_score,
        tech_weight=outer_weights["tech"],
        flow_weight=outer_weights["flow"],
        onchain_score=onchain_score,
        onchain_weight=outer_weights["onchain"],
        pattern_score=pattern_score,
        pattern_weight=outer_weights["pattern"],
    )
```

### Loading Regime Weights

At pipeline startup (in `main.py` lifespan), load `RegimeWeights` rows from DB into `app.state.regime_weights: dict[tuple[str, str], RegimeWeights]`. Each row must be expunged from the session (`session.expunge(rw)`) before storing in `app.state` to ensure attribute access works outside the session context (async SQLAlchemy raises `DetachedInstanceError` otherwise). Same pattern as `PerformanceTracker` loading learned ATR multipliers. If no row exists for a pair/timeframe, `None` is passed and defaults apply.

### Signal Storage

Add to `raw_indicators` JSONB:
- `regime_trending`, `regime_ranging`, `regime_volatile` — the regime mix
- `effective_caps` — the blended inner caps used
- `effective_outer_weights` — the blended outer weights used

Downstream consumers of `raw_indicators` must handle missing regime fields gracefully — existing signals predate regime awareness and will not have these keys.

**Frontend scope:** This is backend-only for V1 — no frontend UI changes. Regime data is stored in `raw_indicators` for observability and debugging via the API. A follow-up task can add regime badges to the signals view (e.g., "Trending 72% | Ranging 20% | Volatile 8%") and display effective weights on signal detail cards.

## Backtest Optimization

The optimizer learns the weight values per (pair, timeframe) by running backtest sweeps.

### Optimizable Parameters

The backtester only exercises tech and pattern scores (flow and onchain are always 0 in backtests). Therefore the optimizer optimizes:
- **12 inner cap floats** (3 regimes × 4 caps) — all exercised via `compute_technical_score()`
- **6 outer weight floats** (3 regimes × 2 usable weights: tech + pattern) — flow and onchain outer weights are fixed at 0 during optimization

Total: 18 optimizable parameters. The flow/onchain outer weights can only be tuned with live data or when the backtester gains flow/onchain simulation support.

### Fitness Metric

All components normalized to 0-1 scale before weighting:

```
fitness = (win_rate/100 × 0.4) + (min(profit_factor, 5)/5 × 0.3) + (min(avg_rr, 5)/5 × 0.2) - (min(max_drawdown, 100)/100 × 0.1)
```

`profit_factor` and `avg_rr` are capped at 5 to prevent outlier backtests from dominating. All values already returned by `run_backtest()` in its `stats` dict.

### Optimizer

`scipy.optimize.differential_evolution` — gradient-free, handles bounded parameters, good for noisy objective functions. This requires adding `scipy>=1.10` to `requirements.txt` and the Docker image. scipy is already an indirect dependency via pandas/numpy but should be explicitly declared with a minimum version pin.

### Flow

1. **API endpoint:** `POST /api/backtest/optimize-regime` — accepts pair, timeframe, date range
2. **Parameter bounds:** Inner caps: 10-45, outer weights: 0.10-0.50
3. **Objective function:** Takes 18-float vector → constructs `RegimeWeights` (flow/onchain outer weights set to 0) → calls `run_backtest()` with those weights → returns negative fitness (minimization)
4. **Convergence:** ~200-500 iterations (configurable). Each iteration runs a full backtest — long-running background task using existing `cancel_flags` pattern. Progress (evaluation count, best fitness) is written to the `BacktestRun.results` JSONB every 25 evaluations so the frontend can poll for intermediate status.
5. **Result:** Best weight vector written to `RegimeWeights` DB table. The optimizer's tech:pattern ratio is preserved while flow/onchain weights use defaults, with all 4 weights per regime column scaled to sum to 1.0.
6. **Loaded on next pipeline cycle** or hot-reloaded via settings API. Hot-reload re-queries the DB row after commit and expunges the instance to avoid SQLAlchemy DetachedInstanceError.

### Safeguards

- Outer weights per regime column constrained to sum to 1.0 (enforced by scaling after optimization: optimizer's tech:pattern ratio preserved, flow/onchain at defaults, all four rescaled to sum to 1.0)
- Inner caps bounded 10-45 to prevent degenerate solutions
- Minimum 20 trades threshold — fewer trades → fitness = 0 (prevents overfitting to rare signals)

### Backtester Changes

`run_backtest()` accepts an optional `regime_weights` parameter:
1. Passes `regime_weights` to `compute_technical_score(df, regime_weights=regime_weights)` for inner cap adjustment (always — regime detection runs regardless)
2. When `regime_weights is not None`: reads `regime` from `tech_result["regime"]`, calls `blend_outer_weights(regime, regime_weights)` to get effective outer weights, renormalizes tech+pattern (since flow/onchain are 0 in backtester), passes to `compute_preliminary_score()`
3. When `regime_weights is None`: uses `config.tech_weight`/`config.pattern_weight` (preserving backward compatibility — existing backtests produce identical results)

Same pattern as confluence `parent_candles` from item #1.

## Module Structure

**New file: `backend/app/engine/regime.py`**
- `compute_regime_mix(trend_strength, vol_expansion)` → dict with trending/ranging/volatile
- `blend_caps(regime, regime_weights)` → effective inner caps dict
- `blend_outer_weights(regime, regime_weights)` → effective outer weights dict
- `DEFAULT_REGIME_WEIGHTS` — hardcoded defaults

All functions are public (no underscore prefix) since they are imported cross-module by `traditional.py`, `main.py`, and `backtester.py`.

## DB Model

New model in `backend/app/db/models.py`:

```python
class RegimeWeights(Base):
    __tablename__ = "regime_weights"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair: Mapped[str]
    timeframe: Mapped[str]

    # Inner caps (3 regimes × 4 caps = 12 floats)
    trending_trend_cap: Mapped[float] = mapped_column(default=38.0)
    trending_mean_rev_cap: Mapped[float] = mapped_column(default=15.0)
    trending_bb_vol_cap: Mapped[float] = mapped_column(default=22.0)
    trending_volume_cap: Mapped[float] = mapped_column(default=25.0)

    ranging_trend_cap: Mapped[float] = mapped_column(default=18.0)
    ranging_mean_rev_cap: Mapped[float] = mapped_column(default=32.0)
    ranging_bb_vol_cap: Mapped[float] = mapped_column(default=28.0)
    ranging_volume_cap: Mapped[float] = mapped_column(default=22.0)

    volatile_trend_cap: Mapped[float] = mapped_column(default=22.0)
    volatile_mean_rev_cap: Mapped[float] = mapped_column(default=20.0)
    volatile_bb_vol_cap: Mapped[float] = mapped_column(default=28.0)
    volatile_volume_cap: Mapped[float] = mapped_column(default=15.0)

    # Outer weights (3 regimes × 4 weights = 12 floats)
    trending_tech_weight: Mapped[float] = mapped_column(default=0.45)
    trending_flow_weight: Mapped[float] = mapped_column(default=0.25)
    trending_onchain_weight: Mapped[float] = mapped_column(default=0.18)
    trending_pattern_weight: Mapped[float] = mapped_column(default=0.12)

    ranging_tech_weight: Mapped[float] = mapped_column(default=0.38)
    ranging_flow_weight: Mapped[float] = mapped_column(default=0.18)
    ranging_onchain_weight: Mapped[float] = mapped_column(default=0.26)
    ranging_pattern_weight: Mapped[float] = mapped_column(default=0.18)

    volatile_tech_weight: Mapped[float] = mapped_column(default=0.30)
    volatile_flow_weight: Mapped[float] = mapped_column(default=0.20)
    volatile_onchain_weight: Mapped[float] = mapped_column(default=0.25)
    volatile_pattern_weight: Mapped[float] = mapped_column(default=0.25)

    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("pair", "timeframe"),)
```

Single Alembic migration creates the table. No existing tables modified.

## Testing

### Unit Tests: `test_regime.py`

- `compute_regime_mix` — trending/ranging/volatile sum to 1.0 across various ADX + BB width combos
- `compute_regime_mix` — high ADX + expanding BB → trending dominates
- `compute_regime_mix` — low ADX + narrow BB → ranging dominates
- `compute_regime_mix` — low ADX + wide BB → volatile dominates
- `compute_regime_mix` — high ADX + low BB (quiet trend) → ~80% trending
- `blend_caps` — with None weights uses defaults
- `blend_caps` — pure trending regime (1.0/0/0) returns trending column exactly
- `blend_caps` — 50/50 trending/ranging returns midpoint of those columns
- `blend_outer_weights` — output sums to 1.0 for any regime mix

### Modified Tests: `test_traditional.py`

- `compute_technical_score` returns `regime` dict with three keys
- `compute_technical_score` with `regime_weights` param produces different scores than without
- Scores still clamped to ±100 under all regime conditions
- Backward compatibility — existing tests pass without `regime_weights` param

### Integration Tests: `test_regime_pipeline.py`

- Pipeline with regime weights loaded in `app.state` uses them
- Pipeline without regime weights in `app.state` uses defaults
- `raw_indicators` on emitted signal contains regime mix and effective weights
- Regime values flow correctly from tech scoring → outer weight adjustment
- Unavailable source zeroing works correctly with regime-blended weights

### Backtester Tests: `test_regime_backtest.py`

- `run_backtest` with `regime_weights` produces different results than without
- `run_backtest` without `regime_weights` works identically to current behavior
- Regime-aware outer weights are applied inside backtester loop

### Optimizer Tests: `test_regime_optimizer.py`

- Objective function returns valid fitness for reasonable weight vectors
- Degenerate weight vectors (all zeros) return fitness = 0
- Outer weights normalized to sum to 1.0 after optimization
- Result written to DB with correct pair/timeframe
- Only 18 parameters optimized (flow/onchain outer weights excluded)
