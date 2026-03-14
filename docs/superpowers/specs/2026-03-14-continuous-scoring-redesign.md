# Continuous Scoring Redesign

**Date:** 2026-03-14
**Status:** Approved

## Problem

The rule-based scoring system in `traditional.py`, `onchain_scorer.py`, and `patterns.py` uses step-function thresholds with massive dead zones. RSI contributes 0 when between 40-60 (where it spends ~70% of its time). Bollinger Band position contributes 0 between 0.2-0.8 (~60% of the time). Order flow scoring has similar dead zones. The result: in normal market conditions, the technical score maxes out around ±40, while the signal threshold is 50. Signals almost never fire.

Additionally, the technical indicator set has redundancy — EMA alignment and MACD both measure trend/momentum, double-counting the same information — while lacking volume analysis entirely.

## Solution

Replace step-function scoring with continuous sigmoid mapping across all four scoring components. Redesign the technical indicator set for orthogonal signal dimensions. Make on-chain scoring pair-aware. Add volume confirmation to both technical scoring and pattern scoring.

## Design

### 1. Sigmoid Scoring Functions

Two shared sigmoid helpers used by all scoring components:

```python
def sigmoid_score(value, center=0, steepness=0.1, max_score=1.0):
    """Bipolar: maps value to [-max_score, +max_score] via smooth S-curve.
    center produces 0. Values above center → positive, below → negative."""
    return max_score * (2 / (1 + exp(-steepness * (value - center))) - 1)

def sigmoid_scale(value, center=0, steepness=0.1):
    """Unipolar: maps value to [0, 1] via standard logistic curve.
    center produces 0.5. Used for magnitude scaling (e.g., ADX strength)."""
    return 1 / (1 + exp(-steepness * (value - center)))
```

- `sigmoid_score`: output in `[-max_score, +max_score]`, used when the indicator has a natural neutral center (RSI at 50, BB position at 0.5, L/S ratio at 1.0)
- `sigmoid_scale`: output in `[0, 1]`, used when the indicator is non-negative and we need a strength multiplier (ADX 0-100 → 0-1 scaling)
- Both are smooth everywhere with no dead zones

### 2. Technical Score — Orthogonal Indicator Redesign

**Removed indicators:** EMA 9/21/50 alignment, MACD histogram. These are correlated (both measure trend/momentum) and double-count the same information.

**New indicator set — four orthogonal dimensions:**

**Minimum candle requirement: 70** (increased from 50). BB width percentile needs 50 BB width readings, which requires ~70 candles (20 for the first valid BB + 50 for the percentile window). The backfill already fetches 100 candles, so this is not a constraint in practice.

#### 2.1 Trend Strength & Direction (max ±30)

ADX (Average Directional Index) with Directional Indicators (+DI / -DI), 14-period.

- ADX measures trend strength (0-100), direction-agnostic
- +DI / -DI give direction
- Scoring: `sign(+DI - -DI) * sigmoid_scale(ADX, center=20, steepness=0.15) * 30`
- `sigmoid_scale` maps ADX to a 0-1 strength multiplier: ADX=0 → 0.05 (near zero). ADX=20 → 0.50 (half). ADX=30 → 0.82. ADX=40 → 0.95 (near full).

Example scores (with +DI > -DI, i.e., bullish direction):

| ADX | sigmoid_scale | Score |
|-----|--------------|-------|
| 0 | 0.05 | +1 |
| 10 | 0.18 | +5 |
| 20 | 0.50 | +15 |
| 30 | 0.82 | +25 |
| 40 | 0.95 | +29 |

ADX quantifies *how strong* the trend is on a continuous scale, avoiding the binary "aligned or not" problem of EMA checks.

#### 2.2 Mean Reversion (max ±25)

RSI (14-period), sigmoid-scored centered at 50.

- Scoring: `sigmoid_score(50 - RSI, center=0, steepness=0.15) * 25`
- RSI below 50 → positive (oversold, bullish). RSI above 50 → negative (overbought, bearish).

Example scores:

| RSI | Input (50-RSI) | Score |
|-----|---------------|-------|
| 50 | 0 | 0 |
| 45 | 5 | +9 |
| 40 | 10 | +16 |
| 35 | 15 | +20 |
| 30 | 20 | +23 |
| 60 | -10 | -16 |
| 70 | -20 | -23 |

RSI is retained over Stochastic RSI because it is well-understood, the ML model already uses it as a feature, and the problem was the scoring math, not the indicator itself.

#### 2.3 Volatility & Price Position (max ±25)

Two sub-signals replacing the binary BB edge check:

**BB Position (max ±15):** Where price sits within the bands.

- Scoring: `sigmoid_score(0.5 - bb_pos, center=0, steepness=6) * 15`

| bb_pos | Score |
|--------|-------|
| 0.0 | +14 |
| 0.1 | +13 |
| 0.3 | +6 |
| 0.5 | 0 |
| 0.7 | -6 |
| 0.9 | -13 |
| 1.0 | -14 |

**BB Width Percentile (max ±10):** Volatility expansion/contraction relative to recent history.

- Compute current BB width as percentile rank within the last 50 BB width values.
- Low percentile = squeeze (volatility contraction) → amplifies BB position score (breakout setup).
- High percentile = expansion → dampens BB position score (price can wander within wide bands).
- Scoring: `sign(bb_position_score) * sigmoid_score(50 - bb_width_pct, center=0, steepness=0.06) * 10`

Note the input is `50 - bb_width_pct` so that low percentile (squeeze) produces a positive sigmoid output, amplifying the directional signal.

| bb_width_pct | sigmoid output | Effect |
|-------------|---------------|--------|
| 10 (squeeze) | +8 | Amplifies BB position |
| 30 | +5 | Mild amplification |
| 50 | 0 | Neutral |
| 80 | -7 | Dampens BB position |

#### 2.4 Volume Confirmation (max ±20)

Entirely new dimension, currently missing from the scoring system.

**OBV Trend (max ±12):** On-Balance Volume slope over the last 10 candles, normalized.

- OBV is computed cumulatively: `OBV[i] = OBV[i-1] + sign(close[i] - close[i-1]) * volume[i]`
- Slope: linear regression slope of the last 10 OBV values
- Normalization: divide slope by the 20-period average volume, producing a dimensionless ratio. Values typically range -2 to +2.
- Scoring: `sigmoid_score(obv_slope_normalized, center=0, steepness=2) * 12`

Rising OBV confirms buying pressure. Divergence (price up, OBV down) warns of weakness.

**Volume Ratio (max ±8):** Current candle volume vs 20-period average.

- `vol_ratio = current_volume / sma(volume, 20)`
- `candle_direction = sign(close - open)` — positive for bullish candles, negative for bearish
- Above-average volume on directional moves confirms conviction. Score is directional: high volume aligned with candle direction → positive; high volume against prevailing trend → negative.
- Scoring: `sign(candle_direction) * sigmoid_score(vol_ratio - 1, center=0, steepness=1.5) * 8`

Together OBV + Volume Ratio answer "is smart money backing this move?"

#### 2.5 Interface

```python
def compute_technical_score(candles: pd.DataFrame) -> dict:
    """Returns {"score": int, "indicators": dict}
    Requires at least 70 candles for reliable indicators."""
```

Same function signature. The `indicators` dict contains: `adx`, `di_plus`, `di_minus`, `rsi`, `bb_upper`, `bb_lower`, `bb_width_pct`, `bb_pos`, `obv_slope`, `vol_ratio`, `atr`. Old keys (`ema_9`, `ema_21`, `ema_50`, `macd`, `macd_signal`, `macd_hist`) are removed.

Total max: ±100 (30 + 25 + 25 + 20). Same range as current system.

### 3. Order Flow Score — Continuous Redesign

Same three inputs, sigmoid math replacing step functions. All inputs use their natural units as received from the OKX API.

#### 3.1 Funding Rate (max ±35)

Contrarian signal — extreme positive funding means crowded longs (bearish).

- Scoring: `sigmoid_score(-funding_rate, center=0, steepness=5000) * 35`
- Steepness of 5000 because funding rates are small numbers (typically 0.0001-0.001).

| Funding Rate | Score |
|-------------|-------|
| -0.0008 | +34 (crowded short, bullish) |
| -0.0003 | +22 |
| -0.0001 | +9 |
| 0 | 0 |
| +0.0001 | -9 |
| +0.0003 | -22 |
| +0.0008 | -34 (crowded long, bearish) |

#### 3.2 Open Interest Change (max ±20)

Rising OI = new money entering. **Direction-aware**: OI increase is only bullish when price is also rising. OI increase during a downtrend means new shorts are piling in.

- `oi_change_pct` is a fraction: 0.03 = 3% change
- `price_direction = sign(close - open)` of the latest candle
- Scoring: `sign(price_direction) * sigmoid_score(oi_change_pct, center=0, steepness=40) * 20`

| OI Change | sigmoid output | Score (if price rising) |
|-----------|---------------|------------------------|
| 1% (0.01) | 4 | +4 |
| 3% (0.03) | 11 | +11 |
| 5% (0.05) | 15 | +15 |
| 10% (0.10) | 19 | +19 |

Direction flips when price is falling — same OI increase yields negative score (shorts piling in).

#### 3.3 Long/Short Ratio (max ±35)

Contrarian signal — extreme L/S means crowded positioning.

- Scoring: `sigmoid_score(1.0 - ls_ratio, center=0, steepness=4) * 35`
- Centered at 1.0 (balanced market).

| L/S Ratio | Score |
|-----------|-------|
| 0.5 | +30 (crowded short, bullish) |
| 0.8 | +13 |
| 1.0 | 0 |
| 1.2 | -13 |
| 1.5 | -27 |
| 2.0 | -34 (crowded long, bearish) |

#### 3.4 Effective Range Note

Component maximums sum to 90 (35 + 20 + 35), not 100. This matches the current system (35 + 15 + 35 = 85). The combiner's adaptive weighting already handles this — it weights by trust in the source, not by the source's internal range. The output is still clamped to [-100, +100] for interface compatibility.

#### 3.5 Empty Data Handling

When `flow_metrics` is empty dict, all inputs default to neutral values (funding=0, oi_change=0, ls=1.0). All sigmoids output ~0. No special-casing needed.

#### 3.6 Interface

```python
def compute_order_flow_score(metrics: dict) -> dict:
    """Returns {"score": int, "details": dict}"""
```

Same function signature. Score range clamped to [-100, +100].

### 4. On-Chain Score — Pair-Aware Redesign

Per-asset metric profiles with shared sigmoid scoring. The function selects the asset profile based on the pair's base currency: `pair.split("-")[0]` → "BTC" or "ETH". Unknown pairs return 0.

#### 4.1 Asset Profiles

**BTC profile:**

| Component | Max | Scoring | Data Source |
|-----------|-----|---------|-------------|
| Exchange Netflow | ±35 | `sigmoid_score(-netflow / 3000, center=0, steepness=1.5) * 35` — outflow = bullish | CryptoQuant, blockchain.info |
| Whale Activity | ±20 | `sigmoid_score(3 - whale_tx_count, center=0, steepness=0.3) * 20` — baseline 3 txs | mempool.space |
| NUPL | ±15 | `sigmoid_score(0.5 - nupl, center=0, steepness=3) * 15` — contrarian | blockchain.info |
| Hashrate Trend | ±15 | `sigmoid_score(hashrate_change_pct, center=0, steepness=10) * 15` — rising = miner confidence | blockchain.info |
| Active Addresses | ±15 | `sigmoid_score(addr_trend_pct, center=0, steepness=8) * 15` — rising = bullish | blockchain.info |

**ETH profile:**

| Component | Max | Scoring | Data Source |
|-----------|-----|---------|-------------|
| Exchange Netflow | ±35 | `sigmoid_score(-netflow / 50000, center=0, steepness=1.5) * 35` — outflow = bullish | CryptoQuant |
| Whale Activity | ±20 | `sigmoid_score(5 - whale_tx_count, center=0, steepness=0.3) * 20` — baseline 5 txs | Etherscan |
| Staking Flow | ±15 | `sigmoid_score(-net_staking_withdrawal, center=0, steepness=1) * 15` — net deposits = supply lock | Beacon Chain API |
| Gas Price Trend | ±15 | `sigmoid_score(gas_trend_pct, center=0, steepness=5) * 15` — rising gas = demand | Etherscan / node |
| Active Addresses | ±15 | `sigmoid_score(addr_trend_pct, center=0, steepness=8) * 15` — rising = bullish | Etherscan |

Other pairs: returns 0. The `onchain_enabled` config already gates this.

#### 4.2 Graceful Degradation

Each metric is read from Redis independently. If a specific metric key is missing (e.g., ETH staking data not yet collected), that component contributes 0 to the total. The function sums whatever is available. This means on-chain scoring works with partial data — a BTC score with only netflow and whale data is still useful, just lower magnitude.

New ETH-specific collectors (staking flow, gas price) are out of scope for this spec. Until they are built, those components contribute 0 and the ETH on-chain score operates on the shared metrics (netflow, whales, active addresses) that the existing collectors already provide.

#### 4.3 Interface

```python
async def compute_onchain_score(pair: str, redis) -> int:
```

Same interface, same return range [-100, +100].

### 5. Pattern Score — Context-Aware Boosts

Pattern detection logic (hammer, engulfing, morning star, etc.) is unchanged. The scoring adds three contextual boosts that multiply the base pattern strength.

#### 5.1 Trend-Alignment Boost

Patterns are more significant when they appear in context:

- Pattern direction opposes current ADX trend direction (reversal) → 1.3x strength
- Pattern aligns with strong trend, ADX > 30 (continuation with conviction) → 1.2x strength
- Weak trend, ADX < 15 → no boost (1.0x)

Uses `adx`, `di_plus`, `di_minus` from the technical scorer, passed via `indicator_ctx`.

#### 5.2 Volume Confirmation Boost

Patterns are more reliable when volume confirms them:

- Volume ratio > 1.5 → 1.3x strength
- Volume ratio > 1.2 → 1.15x strength
- Otherwise → no boost (1.0x)

Uses `vol_ratio` from the technical scorer, passed via `indicator_ctx`.

#### 5.3 Level-Proximity Boost (updated)

Current: binary 1.5x when near BB edge or EMA. Updated to use continuous BB position:

- `boost = 1.0 + max(0, 0.5 * sigmoid_score(abs(bb_pos - 0.5) - 0.3, center=0, steepness=10))`
- The `max(0, ...)` ensures the boost never drops below 1.0. Patterns at center of bands get 1.0x (no penalty), patterns near edges get up to 1.5x.

| bb_pos | boost |
|--------|-------|
| 0.5 (center) | 1.0 |
| 0.3 / 0.7 | 1.0 |
| 0.2 / 0.8 | 1.0 |
| 0.1 / 0.9 | 1.23 |
| 0.0 / 1.0 | 1.38 |

EMA proximity checks are removed since EMAs are no longer computed.

#### 5.4 Interface

```python
def compute_pattern_score(
    patterns: list[dict],
    indicator_ctx: dict,    # requires: adx, di_plus, di_minus, vol_ratio, bb_pos, close
) -> int:
```

`indicator_ctx` requires the new keys from the technical scorer.

### 6. Pipeline Integration & Threshold Calibration

#### 6.1 Weights — No Change

Current adaptive weight system is retained:
- tech=0.40, flow=0.22, onchain=0.23, pattern=0.15
- Zero unavailable sources, renormalize the rest

Weights represent trust in each information source, not the scoring math within each source.

#### 6.2 Signal Threshold — Lowered

**New default: `engine_signal_threshold = 35`** (from 50)

With continuous sigmoid scoring, the score distribution shifts — moderate-conviction setups that scored 0 before will now score 15-30. Sigmoid saturation means a score of 35 requires multiple indicators agreeing with moderate-to-strong readings. A single strong indicator alone maxes at ~25-30 — it can't hit 35 without confirmation from at least one other dimension.

#### 6.3 LLM Threshold — Lowered

**New default: `engine_llm_threshold = 25`** (from 30)

Lower to match the new score distribution so the LLM sees more candidates and can apply judgment.

#### 6.4 Shadow Mode for Rollout

Deploy behind the existing `engine_unified_shadow = True` flag. New scoring runs and logs full evaluations, but doesn't emit. Compare new score distributions against historical signals. Flip to False once satisfied.

#### 6.5 Minimum Candle Requirement

Updated from 50 to 70 in `main.py` (the `run_pipeline` guard) and `backtester.py`. BB width percentile requires 50 BB width readings, which needs ~70 candles (20 for the first valid BB + 50 for percentile history). The backfill already fetches 100 candles, so this is not a constraint in practice.

### 7. Code Changes

**Rewritten:**
- `backend/app/engine/traditional.py` — new indicator set (ADX, RSI, BB+width, OBV+volume), sigmoid scoring, `compute_technical_score()` and `compute_order_flow_score()`
- `backend/app/engine/onchain_scorer.py` — pair-aware profiles, sigmoid scoring
- `backend/tests/engine/test_traditional.py` — new tests for sigmoid continuity, monotonicity, bounds, volume dimension
- `backend/tests/engine/test_onchain_scorer.py` — per-asset profile tests, sigmoid continuity

**Modified:**
- `backend/app/engine/patterns.py` — `compute_pattern_score()` adds trend-alignment boost, volume confirmation boost, continuous level-proximity boost. Requires new context keys.
- `backend/app/config.py` — `engine_signal_threshold` default 50→35, `engine_llm_threshold` default 30→25
- `backend/app/main.py` — pass expanded `indicator_ctx` to `compute_pattern_score()` (adx, di_plus, di_minus, vol_ratio, bb_pos). Update minimum candle guard from 50 to 70.
- `backend/app/engine/backtester.py` — update `indicator_ctx` construction to use new indicator keys. Update minimum candle constant to 70. Remove `enable_ema` and `enable_macd` config flags from `BacktestConfig` (indicators no longer exist).
- `backend/tests/engine/test_patterns.py` — add tests for new boosts, update fixtures with required context keys
- `backend/tests/test_pipeline_ml.py` — update mock `compute_technical_score` return shape

**Not changed:**
- `backend/app/engine/combiner.py` — blending, final score, levels logic unchanged
- `backend/app/ml/features.py` — ML feature engineering has its own independent feature computation
- `backend/app/ml/model.py`, `predictor.py`, `labels.py` — ML model unchanged
- Signal DB model — no schema changes, scores still go into `traditional_score` and `raw_indicators`
- LLM prompt template (`backend/app/prompts/signal_analysis.txt`) — receives `{indicators}` as JSON dynamically, no hardcoded indicator key references. The LLM will see new indicator names (adx, obv_slope, etc.) instead of old ones (ema_9, macd, etc.)
- Frontend chart indicators (MACD overlay, EMA lines in `web/src/features/chart/`) — computed independently for display, unaffected by backend scoring

### 8. Testing Strategy

Tests run via `docker exec krypton-api-1 python -m pytest`.

**`test_traditional.py` — full rewrite:**
- Sigmoid continuity: score changes smoothly across indicator range, no jumps
- Monotonicity: higher RSI → lower score, higher ADX → higher absolute score, etc.
- Bounds: output always in [-100, +100]
- Volume dimension: OBV trend + volume ratio contribute to score
- ADX replaces EMA/MACD: old indicators absent from output
- Order flow: sigmoid continuity, direction-aware OI change, neutral defaults for empty dict

**`test_onchain_scorer.py` — full rewrite:**
- BTC profile: netflow, whales, NUPL, hashrate, addresses all produce continuous scores
- ETH profile: netflow, whales, staking flow, gas trend, addresses
- Unknown pair returns 0
- Sigmoid continuity for each component
- Graceful degradation: missing individual metrics produce 0 for that component, rest still score

**`test_patterns.py` — extend:**
- Pattern detection tests unchanged (detection logic unchanged)
- New: trend-alignment boost varies with ADX value and direction
- New: volume confirmation boost at different volume ratios
- New: continuous level-proximity boost never drops below 1.0
- New: required context keys

**`test_combiner.py` — no changes:**
- `compute_preliminary_score`, `blend_with_ml`, `compute_final_score`, `calculate_levels` unchanged

**`test_pipeline_ml.py` — update fixtures:**
- Mock `compute_technical_score` returns updated indicator dict shape (adx, di_plus, di_minus, obv_slope, vol_ratio, bb_width_pct instead of ema/macd)
- Pipeline integration tests still validate same flow

## Out of Scope

- ML model retraining or feature engineering changes
- Frontend changes (scores are still -100 to +100)
- Changes to LLM prompt template content (it already receives raw indicator values dynamically)
- Changes to outcome resolution, risk management, or position sizing
- New data source integrations for ETH on-chain (uses existing collectors where available; new ETH-specific collectors are a separate task)
- Sigmoid steepness tuning — starting values are reasonable estimates, will be calibrated from shadow mode logs
