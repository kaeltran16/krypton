# Krypton Signal Engine — Algorithm Reference

This document details how Krypton's trading signal engine works, from raw market data ingestion through signal emission, outcome resolution, and continuous self-optimization.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Data Ingestion](#2-data-ingestion)
3. [Technical Scoring](#3-technical-scoring)
4. [Order Flow Scoring](#4-order-flow-scoring)
5. [On-Chain Scoring](#5-on-chain-scoring)
6. [Liquidation Scoring](#6-liquidation-scoring)
7. [Candlestick Pattern Scoring](#7-candlestick-pattern-scoring)
8. [Regime Detection & Adaptive Weighting](#8-regime-detection--adaptive-weighting)
9. [Multi-Timeframe Confluence](#9-multi-timeframe-confluence)
10. [Score Combination](#10-score-combination)
11. [ML Gate](#11-ml-gate)
12. [LLM Gate](#12-llm-gate)
13. [Signal Emission & Level Calculation](#13-signal-emission--level-calculation)
14. [Structure-Aware Level Snapping](#14-structure-aware-level-snapping)
15. [Position Sizing & Risk Management](#15-position-sizing--risk-management)
16. [Signal Delivery](#16-signal-delivery)
17. [Outcome Resolution](#17-outcome-resolution)
18. [ATR Multiplier Learning](#18-atr-multiplier-learning)
19. [Parameter Optimizer](#19-parameter-optimizer)
20. [ML Pipeline](#20-ml-pipeline)
21. [Key Thresholds & Constants](#21-key-thresholds--constants)

---

## 1. Pipeline Overview

On every confirmed candle close, `run_pipeline()` executes the full scoring pipeline:

```
Confirmed Candle (min 70 candles required)
  |
  +-- 1. Technical Score ----------+
  +-- 2. Order Flow Score ---------+
  +-- 3. On-Chain Score -----------+--> Confidence-Weighted Blend --> Preliminary Score
  +-- 4. Liquidation Score --------+        (regime outer weights)
  +-- 5. Pattern Score ------------+
  |
  +-- 6. ML Gate (if confidence >= 0.65) --> Blended Score
  |
  +-- 7. LLM Gate (if |blended| >= 25) ----> Final Score = Blended + LLM Contribution
  |
  +-- 8. Threshold Check (|final| >= 40?)
  |       |
  |       +-- YES --> Calculate Levels --> Snap to Structure --> Position Sizing --> Emit Signal
  |       +-- NO  --> Discard
  |
  +-- 9. Background: Resolve pending signals (TP/SL/expiry)
  +-- 10. Background: Learn ATR multipliers from outcomes
  +-- 11. Background: Optimize scoring parameters
```

All scores operate on a **-100 to +100** scale. Positive = LONG bias, negative = SHORT bias. Each source also emits a **confidence** value (0.0 to 1.0) that modulates its influence in the final blend.

---

## 2. Data Ingestion

### 2.1 Candle Data (OKX WebSocket)

- Subscribes to `candle15m`, `candle1H`, `candle4H`, `candle1Dutc` per pair
- Each message: `[timestamp_ms, open, high, low, close, volume, ..., confirmed_flag]`
- Unconfirmed ticks broadcast to frontend for live chart updates
- Confirmed candles cached in Redis (rolling 200-candle list per pair/timeframe), persisted to Postgres, and trigger the pipeline

### 2.2 Order Flow (OKX WebSocket + REST)

| Metric | Source | Frequency |
|--------|--------|-----------|
| Funding Rate | WebSocket `funding-rate` channel | Real-time |
| Open Interest | WebSocket `open-interest` channel | Real-time |
| Long/Short Ratio | REST API poll | Every 5 min |

Stored in-memory at `app.state.order_flow[pair]`. Snapshots persisted to `OrderFlowSnapshot` table per confirmed candle for ML training data.

### 2.3 On-Chain Data

**Tier 1 (every 5 min, no auth):** Mempool.space (large BTC txns), CoinGecko (market data), Blockchain.info (stats).

**Tier 2 (every 30 min, API key):** CryptoQuant (exchange netflows).

Cached in Redis with 600s TTL.

### 2.4 Liquidation Data

- Polls OKX liquidation endpoint every 5 minutes
- Maintains rolling 24-hour window per pair
- Each event: `{price, volume, timestamp, side}`

### 2.5 News & Events

- Polls CryptoPanic, CoinGecko News, RSS feeds every 2.5 min
- Two-pass deduplication: exact URL match, then fuzzy headline match (85% threshold, 6h window)
- Relevance filtering by pair symbol and macro keywords
- High-impact articles scored by LLM for summary and sentiment

---

## 3. Technical Scoring

**File:** `engine/traditional.py`

Quantifies price action across 5 orthogonal dimensions using standard indicators computed over the candle history.

### 3.1 Indicators Computed

| Indicator | Params | Purpose |
|-----------|--------|---------|
| ADX | period=14 | Trend strength (0-100) |
| +DI / -DI | period=14 | Directional index |
| RSI | period=14 | Momentum / overbought-oversold |
| Bollinger Bands | SMA(20), 2-std | Volatility bands & price position |
| OBV | cumulative | Volume-price confirmation |
| EMA 9 / 21 / 50 | close | Trend structure |
| ATR | period=14 | Volatility for position sizing |

### 3.2 Scoring Dimensions

Each dimension is capped by the current regime (see [Section 8](#8-regime-detection--adaptive-weighting)). All use sigmoid scaling for smooth, bounded outputs.

**1. Trend Score (cap: 18-40 depending on regime)**

```
direction = +1 if DI+ > DI-, else -1
trend_score = direction * sigmoid_scale(adx, center=15, steepness=0.30) * trend_cap
```

Strong ADX + clear DI separation = strong trend score. Capped highest in steady (40) and trending (38) regimes.

**2. Mean Reversion Score (cap: 15-40)**

Blends RSI deviation from 50 with Bollinger Band position at a 60/40 ratio:

```
rsi_raw    = sigmoid_score(50 - rsi, center=0, steepness=0.25)        # [-1, +1]
bb_pos_raw = sigmoid_score(0.5 - bb_position, center=0, steepness=10) # [-1, +1]
combined   = 0.6 * rsi_raw + 0.4 * bb_pos_raw
mean_rev_score = combined * mean_rev_cap
```

Capped highest in ranging regimes (40) where reversion strategies excel.

**3. Squeeze/Expansion Score (cap: 12-22)**

Detects Bollinger Band width percentile, signed to match mean-reversion direction:

```
squeeze_score = mean_rev_sign * sigmoid_scale(50 - bb_width_pct, center=0, steepness=0.10) * squeeze_cap
```

Narrow bands (squeeze) amplify the mean-reversion signal. Capped highest in volatile regimes (22).

**4. Volume Confirmation Score (cap: 25-28)**

Two components weighted 60/40:
- **OBV slope** (last 10 candles, normalized by average volume): directional volume flow
- **Volume ratio** (current / 20-candle average): confirms conviction with above-average volume

```
obv_component = sigmoid_score(obv_slope_norm, center=0, steepness=4) * (cap * 0.6)
vol_component = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=3) * (cap * 0.4)
```

### 3.3 Trend Conviction

A separate 0-1.0 measure used to dampen order flow contrarian signals when a strong trend is in play:

```
ema_alignment  = sigmoid_scale(|ema_spread|, center=0.5, steepness=2.0)  # with penalty if spread/DI mismatch
adx_strength   = sigmoid_scale(adx, center=20, steepness=0.25)
price_confirm  = 1.0 if price on correct side of all 3 EMAs, else 0

trend_conviction = mean(ema_alignment, adx_strength, price_confirm)
```

### 3.4 Confidence

```
indicator_conflict = 1 - |trend_score + mean_rev_score| / (|trend_score| + |mean_rev_score|)
confidence = trend_strength * 0.4 + trend_conviction * 0.4 + (1 - indicator_conflict) * 0.2
```

High confidence when trend is clear, conviction is strong, and indicators agree.

### 3.5 Divergence Detection (HTF only: 4H, 1D)

Detects RSI/price divergences using swing point detection (order=3):
- **Bullish divergence:** price makes lower low, RSI makes higher low
- **Bearish divergence:** price makes higher high, RSI makes lower high

Returns 0-1.0 confidence. Scored separately from the main technical score.

---

## 4. Order Flow Scoring

**File:** `engine/traditional.py` (`compute_order_flow_score`)

Applies contrarian bias on derivatives market metrics, modulated by regime and rate-of-change detection. Directional metrics (OI, CVD, book) are regime-independent.

### 4.1 Regime-Aware Contrarian Multiplier

```
contrarian_mult = 1.0 - (trending_strength * (1.0 - trending_floor))
```

- `trending_floor = 0.3`: even in strong trends, at least 30% contrarian signal preserved
- Ranging market: full contrarian (1.0x)
- Strong trending market: reduced contrarian (~0.3x)
- Mean-reversion pressure relaxes the floor toward 1.0

### 4.2 Rate-of-Change Override

Tracks 10 candle flow history (3 recent + 7 baseline). If funding rate, L/S ratio, or OI change rapidly:

```
roc_boost = sigmoid_scale(max_roc, center=0.0005, steepness=8000)
final_mult = contrarian_mult + roc_boost * (1 - contrarian_mult)
```

Rapid shifts in crowd positioning or commitment increase contrarian sensitivity even in trends.

### 4.3 Trend Conviction Dampening

```
final_mult = min(final_mult, 1.0 - trend_conviction)
```

High trend conviction further suppresses contrarian order flow signals.

### 4.4 Five Scoring Components

| Component | Max Score | Logic | Type | Regime-Affected |
|-----------|-----------|-------|------|-----------------|
| Funding Rate | +/-22 | Contrarian: negative funding = bullish | Contrarian | Yes |
| Open Interest Change | +/-22 | Directional: agrees with price direction | Directional | No |
| Long/Short Ratio | +/-22 | Contrarian: ratio > 1 (more longs) = bearish | Contrarian | Yes |
| CVD (trend) | +/-22 | Slope of last 5-10 candle deltas, normalized by volume | Directional | No |
| Book Imbalance | +/-12 | Top-5 bid/ask volume ratio | Directional | No |

Total max: +/-100. Contrarian components (funding, L/S) have per-asset sigmoid scaling to account for different market microstructure (e.g., WIF funding is 5-10x more volatile than BTC).

### 4.5 Price Direction

Uses 3-candle net move (`candles[-1].close - candles[-4].close`) instead of single-candle body to filter noise from dojis and small counter-trend candles.

### 4.6 CVD Trend Scoring

When >= 5 candle deltas are available, computes linear slope of last 10 deltas normalized by average volume. Falls back to single-candle delta/volume when insufficient history.

### 4.7 Confidence

```
inputs_present = count of keys that produced a scoring contribution
sources_available = count of keys present in metrics dict
confidence = inputs_present / sources_available
```

Key-based presence detection: `funding_rate=0.0` counts as present (not absent). OI requires nonzero price direction to produce a scoring contribution but still counts as available.

### 4.8 Freshness Decay

Stale flow data (WebSocket dropped) gets confidence-penalized, not score-penalized:

```
if age > fresh_seconds (300):
    decay = min(1.0, (age - 300) / (900 - 300))
    confidence *= (1.0 - decay)
```

This causes the combiner to redistribute weight to fresher sources (tech, patterns) rather than zeroing out the directional signal.

### 4.9 Per-Asset Sigmoid Calibration

Asset scales multiply contrarian steepnesses (funding, L/S):

| Asset | Scale | Effect |
|-------|-------|--------|
| BTC-USDT-SWAP | 1.0 | Baseline |
| ETH-USDT-SWAP | 0.85 | Slightly wider S-curve |
| WIF-USDT-SWAP | 0.4 | Much wider — preserves discrimination at extreme funding |

---

## 5. On-Chain Scoring

**File:** `engine/onchain_scorer.py`

Macro trend signals from blockchain activity. Asset-specific metric profiles.

### BTC Profile

| Metric | Max Score | Logic |
|--------|-----------|-------|
| Exchange Netflow | +/-35 | Outflow = bullish (accumulation) |
| Whale Activity | +/-20 | Contrarian (baseline: 3 whales) |
| NUPL | +/-15 | Contrarian (0.5 = neutral) |
| Hashrate Change | +/-15 | Rising = bullish |
| Address Trend | +/-15 | Rising = bullish |

### ETH Profile

| Metric | Max Score | Logic |
|--------|-----------|-------|
| Exchange Netflow | +/-35 | Outflow = bullish |
| Whale Activity | +/-20 | Contrarian (baseline: 5 whales) |
| Staking Flow | +/-15 | Contrarian (deposits = bullish turn) |
| Gas Price Trend | +/-15 | Rising = bullish |
| Address Trend | +/-15 | Rising = bullish |

Confidence = metrics_present / total_metrics.

---

## 6. Liquidation Scoring

**File:** `engine/liquidation_scorer.py`

Identifies price-level clusters of liquidation events as obstacles or springboards.

### Process

1. **Bucket aggregation:** events grouped into 0.25 ATR price buckets with exponential decay (4h half-life)
2. **Cluster detection:** buckets exceeding 2.0x median volume, within 2 ATR of current price
3. **Directional scoring:**
   - Cluster ABOVE price = short liquidations = bullish squeeze potential (+)
   - Cluster BELOW price = long liquidations = bearish cascade potential (-)
4. **Per-cluster contribution:**

```
sign = +1 if cluster above price, else -1
proximity = sigmoid_score(2.0 - distance_in_atr, center=0, steepness=2.0)
contribution = sign * proximity * (density / density_norm) * 30
```

Confidence based on cluster count and total volume relative to baseline.

---

## 7. Candlestick Pattern Scoring

**File:** `engine/patterns.py`

Detects 15 pattern types with contextual boosts.

### 7.1 Patterns Detected

| Category | Patterns | Base Strength |
|----------|----------|---------------|
| Single-candle | Hammer, Hanging Man, Inverted Hammer, Shooting Star, Doji, Spinning Top, Marubozu | 5-13 |
| Two-candle | Bullish/Bearish Engulfing, Piercing Line, Dark Cloud Cover | 12-15 |
| Three-candle | Morning/Evening Star, Three White Soldiers, Three Black Crows | 15 |

### 7.2 Contextual Boost Multipliers

| Boost | Condition | Multiplier |
|-------|-----------|------------|
| Trend alignment | ADX >= 15 + reversal pattern | 1.3x |
| Trend continuation | ADX >= 30 + continuation pattern | 1.2x |
| Volume confirmation | vol_ratio > 1.5 | 1.3x |
| Volume moderate | vol_ratio > 1.2 | 1.15x |
| Level proximity | Near Bollinger Band extremes | 1.0x - 1.5x |

Total boost = trend_boost * volume_boost * level_boost.

Confidence = min(non_neutral_patterns / 3.0, 1.0).

---

## 8. Regime Detection & Adaptive Weighting

**File:** `engine/regime.py`

The market regime determines both the inner caps (how much each scoring dimension can contribute) and the outer weights (how much each source matters in the final blend).

### 8.1 Raw Regime Mix

Computed from ADX and Bollinger Band width:

```
trend_strength = sigmoid_scale(adx, center=20, steepness=0.25)  # 0-1
vol_expansion  = sigmoid_scale(bb_width_pct, center=50, steepness=0.08)  # 0-1

raw_trending = trend_strength * vol_expansion
raw_ranging  = (1 - trend_strength) * (1 - vol_expansion)
raw_volatile = (1 - trend_strength) * vol_expansion
raw_steady   = trend_strength * (1 - vol_expansion)
```

This produces a continuous mix across 4 regime archetypes (sums to 1.0).

### 8.2 Regime Smoothing

EMA smoothing (alpha=0.3) prevents single-candle regime flips. Per pair/timeframe, the smoothed regime blends 30% new observation with 70% prior state.

### 8.3 Inner Caps (per-dimension score limits)

The regime mix modulates how much each technical scoring dimension can contribute:

| Regime | Trend Cap | Mean Rev Cap | Squeeze Cap | Volume Cap |
|--------|-----------|--------------|-------------|------------|
| Trending | 38 | 22 | 12 | 28 |
| Ranging | 18 | 40 | 16 | 26 |
| Volatile | 25 | 28 | 22 | 25 |
| Steady | 40 | 15 | 20 | 25 |

Blended by dot product: e.g., `trend_cap = trending*38 + ranging*18 + volatile*25 + steady*40`.

### 8.4 Outer Weights (source blending)

Each scoring source receives a regime-dependent weight:

| Regime | Technical | Order Flow | On-Chain | Pattern | Liquidation |
|--------|-----------|------------|----------|---------|-------------|
| Trending | 0.42 | 0.23 | 0.16 | 0.11 | 0.08 |
| Ranging | 0.35 | 0.16 | 0.24 | 0.16 | 0.09 |
| Volatile | 0.27 | 0.18 | 0.22 | 0.22 | 0.11 |
| Steady | 0.45 | 0.20 | 0.16 | 0.11 | 0.08 |

Per-pair learned adjustments stored in `RegimeWeights` DB table can override these defaults.

---

## 9. Multi-Timeframe Confluence

**File:** `engine/confluence.py`

Lower timeframes receive a bonus/penalty based on alignment with their parent timeframe's trend direction.

| Child TF | Parent TF |
|----------|-----------|
| 15m | 1H |
| 1H | 4H |
| 4H | 1D |

1D is **confluence-only** — it computes indicators cached for child timeframes but does not emit signals itself.

### Confluence Score

```
parent_direction = +1 if parent DI+ > DI-, else -1
parent_strength  = sigmoid_scale(parent_adx, center=15, steepness=0.30)

if child_direction == parent_direction:
    confluence = +max_score * parent_strength   # alignment bonus (up to +15)
else:
    confluence = -max_score * parent_strength   # divergence penalty (down to -15)
```

Added directly to the technical score (clamped to [-100, +100]).

---

## 10. Score Combination

**File:** `engine/combiner.py`

### 10.1 Confidence-Weighted Preliminary Blend

Each source's base weight (from regime outer weights) is multiplied by its confidence:

```
effective_weight[source] = base_weight[source] * confidence[source]
normalized_weight[source] = effective_weight[source] / sum(all effective weights)

preliminary_score = sum(source_score * normalized_weight for each source)
```

If a source is unavailable (confidence=0), its weight redistributes proportionally to the others.

### 10.2 Confidence Tier

```
avg_confidence = weighted average of all source confidences
```

| Tier | Condition |
|------|-----------|
| High | avg_confidence >= 0.70 |
| Medium | avg_confidence >= 0.40 |
| Low | avg_confidence < 0.40 |

---

## 11. ML Gate

**File:** `engine/combiner.py` (`blend_with_ml`)

Per-pair PyTorch LSTM models predict direction and confidence. ML only contributes when sufficiently confident.

### 11.1 ML Score Conversion

```
if direction == "NEUTRAL":
    ml_score = 0
else:
    centered = (confidence - 1/3) / (2/3) * 100   # re-center from [0.33, 1.0] to [0, 100]
    ml_score = centered if LONG, else -centered
```

### 11.2 Blending

```
if ml_confidence >= ml_confidence_threshold (default 0.65):
    blended = preliminary * (1 - ml_weight) + ml_score * ml_weight
else:
    blended = preliminary   # ML has no influence
```

Default `ml_weight = 0.25` — ML contributes up to 25% of the blended score when confident.

---

## 12. LLM Gate

**Files:** `engine/combiner.py`, `engine/llm.py`

When the blended score exceeds the LLM threshold, the full market context is sent to an LLM for qualitative analysis. The LLM response acts as an additive contribution, not an override.

### 12.1 Trigger Condition

```
if |blended_score| >= llm_threshold (default 25):
    call LLM with full context (indicators, flow, patterns, ML prediction, news, last 20 candles)
```

### 12.2 LLM Factor Analysis

The LLM returns structured factors across 4 categories:

| Category | Factors | Default Weights |
|----------|---------|-----------------|
| Structure | Support proximity, resistance proximity, level breakout, HTF alignment | 6, 6, 8, 7 |
| Momentum | RSI divergence, volume divergence, MACD divergence | 7, 6, 6 |
| Exhaustion | Volume exhaustion, funding extreme, crowded positioning | 5, 5, 5 |
| Event | Pattern confirmation, news catalyst | 5, 7 |

### 12.3 Contribution Computation

```
for each factor:
    aligned = (factor.direction == desired_direction)
    sign = +1 if aligned, else -1
    total += sign * factor_weight * factor.strength    # strength in {1, 2, 3}

llm_contribution = clamp(total, -factor_cap, +factor_cap)   # cap default 35
```

### 12.4 Final Score

```
final_score = clamp(blended_score + llm_contribution, -100, +100)
```

---

## 13. Signal Emission & Level Calculation

**File:** `engine/combiner.py`

### 13.1 Emission Check

```
direction = "LONG" if final_score > 0, else "SHORT"

if |final_score| >= signal_threshold (default 40):
    emit signal
```

The threshold can be adaptive per pair/regime via the optimizer.

### 13.2 Level Priority Cascade

Entry, stop-loss, and take-profit levels are determined by the first available source:

| Priority | Source | Condition |
|----------|--------|-----------|
| 1 | ML regression | ML confidence >= threshold, model provides SL/TP ATR multiples |
| 2 | LLM explicit levels | LLM contribution >= 0, levels pass sanity check |
| 3 | ATR defaults | Learned multipliers from performance tracker, or defaults (1.5/2.0/3.0) |

### 13.3 Signal Strength Scaling

Levels are scaled by signal strength and market volatility:

```
t = (|score| - threshold) / (100 - threshold)       # 0 at threshold, 1 at max score

sl_strength  = 0.8 + (1.2 - 0.8) * t               # 0.8x to 1.2x
tp_strength  = 0.8 + (1.4 - 0.8) * t               # 0.8x to 1.4x
vol_factor   = 0.75 + (1.25 - 0.75) * (bb_width_pct / 100)  # 0.75x to 1.25x

sl_atr  *= sl_strength * vol_factor
tp1_atr *= tp_strength * vol_factor
tp2_atr *= tp_strength * vol_factor
```

Stronger signals get wider targets. Higher volatility stretches all levels.

### 13.4 Level Guardrails

| Level | Bounds (ATR multiples) | Additional Constraint |
|-------|------------------------|-----------------------|
| SL | [0.5, 3.0] | R:R floor: tp1/sl >= 1.0 |
| TP1 | [1.0, 4.0] | — |
| TP2 | [2.0, 6.0] | Must be >= tp1 * 1.2 |

---

## 14. Structure-Aware Level Snapping

**File:** `engine/structure.py`

After initial level calculation, levels are post-processed to sit at meaningful technical structure.

### 14.1 Structure Level Collection

Aggregates technical levels from multiple sources:

1. **Swing-based S/R zones** — pivot highs/lows clustered within 0.5 ATR tolerance, minimum 2 touches
2. **Bollinger Bands** — upper, lower, midline (SMA20)
3. **EMAs** — EMA 50 (strength 3), EMA 21 (strength 2), EMA 9 (strength 1)
4. **Liquidation clusters** — high-volume liquidation price zones

### 14.2 Snapping Logic

For each level (SL, TP1, TP2):
1. Find nearby structure within `max_snap_atr` (1.5 ATR) of the target
2. Select the best candidate: closest distance weighted by structure strength
3. Place the level just beyond the structure (0.15 ATR buffer)
4. Enforce SL bounds and R:R floor after snapping

This aligns algorithmic levels with technical structure that market participants actually watch.

---

## 15. Position Sizing & Risk Management

**File:** `engine/risk.py`

### 15.1 Position Sizing

```
sl_distance      = |entry - stop_loss| / entry
risk_amount      = equity * risk_per_trade           # default 1%
position_size    = risk_amount / sl_distance

position_size    = min(position_size, max_position_size_usd)
position_size    = min(position_size, equity * 0.25)  # hard cap at 25% of equity
```

### 15.2 RiskGuard Checks

| Check | Condition | Action |
|-------|-----------|--------|
| Daily Loss Limit | daily_pnl <= -3% | BLOCKED |
| Max Concurrent Positions | open_positions >= 3 | BLOCKED |
| Max Exposure | (total_exposure + new) / equity > 1.5% | BLOCKED |
| Cooldown After Loss | last SL hit < cooldown_minutes ago | WARNING |
| Max Risk Per Trade | size / equity > 2% | WARNING |

Blocked signals are not emitted. Warnings are logged but signal proceeds.

---

## 16. Signal Delivery

### 16.1 Persistence

Signal saved to Postgres `Signal` table with all metadata: scores, indicators, levels, risk metrics, detected patterns, correlated news IDs, engine snapshot, confidence tier.

### 16.2 WebSocket Broadcast

```json
{"type": "signal", "signal": { ...full signal data }}
```

Sent to all connected clients subscribed to the signal's pair and timeframe.

### 16.3 Web Push Notifications

Dispatched to all registered `PushSubscription` endpoints with signal summary.

### 16.4 Alert Evaluation

User-configured signal alerts are checked and triggered (e.g., "notify on any LONG BTC signal").

---

## 17. Outcome Resolution

**File:** `engine/outcome_resolver.py`

Background loop runs every 60 seconds, checking all PENDING signals.

### Resolution Priority (checked per candle after signal creation)

**For LONG signals:**

| Priority | Condition | Outcome |
|----------|-----------|---------|
| 1 | candle low <= stop_loss | SL_HIT |
| 2 | candle high >= take_profit_2 | TP2_HIT |
| 3 | candle high >= take_profit_1 | TP1_HIT |

**For SHORT signals:**

| Priority | Condition | Outcome |
|----------|-----------|---------|
| 1 | candle high >= stop_loss | SL_HIT |
| 2 | candle low <= take_profit_2 | TP2_HIT |
| 3 | candle low <= take_profit_1 | TP1_HIT |

**Expiry:** signals older than 24 hours without hitting any level are marked EXPIRED.

Each resolution records PnL percentage and duration in minutes.

---

## 18. ATR Multiplier Learning

**File:** `engine/performance_tracker.py`

Learns optimal SL/TP ATR multipliers per pair/timeframe from historical signal outcomes.

### 18.1 Optimization Trigger

- Minimum 10 resolved signals required (configurable)
- Triggers every N resolved signals (configurable interval)
- Excludes signals that used LLM-provided levels (tests only ATR-derived levels)

### 18.2 1D Sweep Optimization

For each dimension (SL, TP1, TP2) independently:

1. Generate candidate multiplier values across the valid range
2. For each candidate, replay all signals in the window with the candidate value while keeping the other two dimensions at their deployed effective values
3. Compute Sortino ratio for each candidate's outcome distribution
4. Select the candidate with the best Sortino if it improves over the current value

### 18.3 Guardrails

| Dimension | Bounds | Max Per-Cycle Adjustment |
|-----------|--------|--------------------------|
| SL | [0.8, 2.5] | 0.3 |
| TP1 | [1.0, 4.0] | 0.5 |
| TP2 | [2.0, 6.0] | 0.5 |

R:R floor enforced after all adjustments: TP1 >= SL.

### 18.4 Bootstrap

On startup, seeds tracker rows from the best completed backtest (by profit factor) per pair/timeframe. Does not re-optimize — just copies starting values.

---

## 19. Parameter Optimizer

**File:** `engine/optimizer.py`, `engine/param_groups.py`

Monitors global signal fitness and proposes parameter changes via counterfactual backtesting.

### 19.1 Parameter Groups by Priority

| Layer | Groups | Method |
|-------|--------|--------|
| 0 (highest impact) | source_weights, thresholds | Grid sweep |
| 1 | regime_caps, regime_outer, atr_levels | Grid / DE |
| 2 | sigmoid_curves, order_flow, pattern_strengths, indicator_periods, mean_reversion, llm_factors, onchain | DE |

### 19.2 Shadow Mode Validation

1. Proposal created with backtest metrics on historical data
2. Shadow mode: next 20 signals re-scored with proposed parameters alongside live parameters
3. Compare profit factors: current vs shadow
4. Decision: **promote** (replace live params), **reject** (discard), or **inconclusive** (extend shadow)
5. Auto-rollback if profit factor drops 15% within 10 signals post-promotion

### 19.3 IC-Based Source Pruning

Computes Information Coefficient (Pearson correlation) of each source's scores vs actual outcomes:
- Prunes source if IC < -0.05 for 30 consecutive days (actively harmful signal)
- Re-enables if IC > 0.0 (returns to neutral or positive contribution)

---

## 20. ML Pipeline

**Files:** `ml/features.py`, `ml/model.py`, `ml/labels.py`, `ml/trainer.py`, `ml/predictor.py`

### 20.1 Feature Engineering (~40 features)

| Category | Features | Count |
|----------|----------|-------|
| Price | returns, body ratio, upper/lower wick, volume z-score | 5 |
| Indicators | EMA distances (9/21/50), RSI, MACD, BB position/width, ATR% | 8 |
| Temporal | hour sin/cos encoding | 2 |
| Momentum | cumulative returns (5/10/20), RSI RoC, volume trend, MACD acceleration | 6 |
| Multi-TF proxy | RSI(56), EMA(200) distance, BB position(80) | 3 |
| Regime (optional) | trending/ranging/volatile mix, trend conviction | 4 |
| Inter-pair (optional) | BTC cumulative return, BTC ATR% | 2 |
| Order flow (optional) | Funding rate, OI change, L/S ratio + their deltas | 6 |

All features clipped to [-10, 10] for stability.

### 20.2 Model Architecture — SignalLSTM

```
Input (batch, seq_len=50, features)
  --> BatchNorm1d
  --> LSTM (hidden=128, layers=2, dropout=0.3)
  --> Temporal Attention (learns to weight time steps)
  --> Multi-Scale Pooling (attention + last 5/10/25 mean pools)
  --> Linear projection [4 * hidden] --> hidden
  --> Dropout(0.3)
      |
      +--> Classification Head --> 3 classes (NEUTRAL / LONG / SHORT)
      |    Linear(128) --> ReLU --> Linear(64) --> ReLU --> Dropout --> Linear(3)
      |
      +--> Regression Head --> 3 values (SL, TP1, TP2 in ATR units)
           Linear(128) --> ReLU --> Linear(64) --> ReLU --> Dropout --> Linear(3) --> ReLU
```

Temporal attention allows the model to focus on the most relevant historical candles. Multi-scale pooling captures both recent (5-candle) and medium-term (25-candle) context. Classification and regression share the LSTM backbone via multi-task learning.

### 20.3 Label Generation

Direction labels using forward-looking horizon:

```
horizon   = 24 candles
threshold = 1.5% minimum move

For each candle:
    max_up   = (future_high_max - price) / price
    max_down = (price - future_low_min) / price

    if max_up >= 1.5% and max_up > max_down:  LONG
    elif max_down >= 1.5% and max_down > max_up:  SHORT
    else:  NEUTRAL
```

Regression targets (SL/TP in ATR units) derived from Maximum Adverse Excursion (MAE) and Maximum Favorable Excursion (MFE).

### 20.4 Training

| Parameter | Value |
|-----------|-------|
| Epochs | 100 (max) |
| Batch size | 64 |
| Sequence length | 50 candles |
| Learning rate | 1e-3 with cosine annealing |
| Warmup | 5 epochs linear |
| Early stopping | 20 epochs patience |
| Label smoothing | 0.1 |
| Neutral subsample | 50% (reduce class imbalance) |
| Loss | CrossEntropy (class-weighted) + 0.5 * SmoothL1 (regression, non-neutral only) |
| Train/Val split | 85/15 temporal (no shuffle) |

**Post-training:** temperature scaling calibration via LBFGS optimization on the validation set. Temperature clamped to [0.1, 10.0].

### 20.5 Inference — MC Dropout Uncertainty

```
For i in 1..5:
    Enable dropout layers (not BatchNorm)
    Forward pass --> probs, regression
    Collect outputs

mean_probs      = average across 5 passes
prob_variance   = variance across passes (epistemic uncertainty)
direction       = argmax(mean_probs)
raw_confidence  = mean_probs[direction]

uncertainty_penalty = min(1.0, prob_variance * 10)
final_confidence    = raw_confidence * (1.0 - uncertainty_penalty)

if model_age > 14 days: cap confidence at 0.3
```

5 stochastic forward passes with dropout active quantify model uncertainty. High variance across passes indicates the model is unsure, reducing effective confidence.

---

## 21. Key Thresholds & Constants

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `signal_threshold` | 40 | Minimum \|score\| to emit a signal |
| `llm_threshold` | 25 | Minimum \|score\| to invoke LLM analysis |
| `ml_confidence_threshold` | 0.65 | ML confidence gate for blending |
| `ml_weight` | 0.25 | ML contribution weight in blend |
| `llm_factor_total_cap` | 35 | Maximum LLM additive contribution |
| `confluence_max_score` | 15 | Maximum HTF alignment bonus |
| `min_candles` | 70 | Minimum candle history for reliable indicators |
| `risk_per_trade` | 1% | Equity risked per signal |
| `daily_loss_limit` | 3% | Daily drawdown cutoff |
| `max_concurrent_positions` | 3 | Portfolio position limit |
| `max_exposure` | 1.5% | Account leverage limit |
| `regime_smoothing_alpha` | 0.3 | EMA smoothing for regime transitions |
| `sl_atr_default` | 1.5 | Default stop-loss ATR multiplier |
| `tp1_atr_default` | 2.0 | Default TP1 ATR multiplier |
| `tp2_atr_default` | 3.0 | Default TP2 ATR multiplier |
| `model_max_age_days` | 14 | ML model staleness threshold |
| `mc_dropout_passes` | 5 | Inference uncertainty sampling passes |
