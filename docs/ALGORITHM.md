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
8. [News Scoring](#8-news-scoring)
9. [Regime Detection & Adaptive Weighting](#9-regime-detection--adaptive-weighting)
10. [Online Regime Weight Adaptation](#10-online-regime-weight-adaptation)
11. [Multi-Timeframe Confluence](#11-multi-timeframe-confluence)
12. [Score Combination](#12-score-combination)
13. [ML Gate](#13-ml-gate)
14. [LLM Gate](#14-llm-gate)
15. [LLM Factor Calibration](#15-llm-factor-calibration)
16. [Signal Emission & Level Calculation](#16-signal-emission--level-calculation)
17. [Structure-Aware Level Snapping](#17-structure-aware-level-snapping)
18. [Position Sizing & Risk Management](#18-position-sizing--risk-management)
19. [Anti-Whipsaw Cooldown](#19-anti-whipsaw-cooldown)
20. [Signal Delivery](#20-signal-delivery)
21. [Outcome Resolution](#21-outcome-resolution)
22. [ATR Multiplier Learning](#22-atr-multiplier-learning)
23. [Parameter Optimizer](#23-parameter-optimizer)
24. [ML Pipeline](#24-ml-pipeline)
25. [Key Thresholds & Constants](#25-key-thresholds--constants)

---

## 1. Pipeline Overview

On every confirmed candle close, `run_pipeline()` executes the full scoring pipeline:

```
Confirmed Candle (min 70 candles required)
  |
  +-- 1. Technical Score ----------+
  +-- 2. Order Flow Score ---------+
  +-- 3. On-Chain Score -----------+
  +-- 4. Liquidation Score --------+--> Regime-Weighted Blend --> Preliminary Score
  +-- 5. Pattern Score ------------+        (adaptive outer weights)
  +-- 6. Confluence Score ---------+
  +-- 7. News Score ---------------+
  |
  +-- 8. Agreement Factor (directional consensus boost/penalty)
  |
  +-- 9. ML Gate (ensemble, if confidence >= 0.65) --> Blended Score
  |
  +-- 10. LLM Gate (dual-pass, if |blended| >= 40 or MR pressure >= 0.30)
  |        --> LLM Calibration (rolling-accuracy multipliers)
  |        --> Final Score = Blended + LLM Contribution
  |
  +-- 11. Threshold Check (|final| >= adaptive threshold?)
  |        + Cooldown Check (anti-whipsaw suppression)
  |        |
  |        +-- YES --> Calculate Levels --> Snap to Structure --> Position Sizing --> Emit Signal
  |        +-- NO  --> Discard
  |
  +-- 12. Background: Resolve pending signals (two-pass: partial exit + trailing stop)
  +-- 13. Background: Learn ATR multipliers from outcomes (with slippage modeling)
  +-- 14. Background: Optimize scoring parameters
  +-- 15. Background: Update regime weight overlays from outcomes
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

Quantifies price action across 4 orthogonal dimensions using standard indicators computed over the candle history.

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

Each dimension is capped by the current regime (see [Section 9](#9-regime-detection--adaptive-weighting)). All use sigmoid scaling for smooth, bounded outputs.

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

Applied as a multiplicative factor (0.6x to 1.4x) on the combined trend + mean-reversion score.

### 3.3 Mean-Reversion Pressure

When both RSI and BB position are at extremes simultaneously, the cap system dynamically shifts weight from trend toward mean reversion:

```
rsi_extremity = max(0, |rsi - 50| - 10) / 30        # 0-1, activates beyond RSI 40/60
bb_extremity  = max(0, |bb_pos - 0.5| - 0.2) / 0.3  # 0-1, activates beyond BB 20%/80%

pressure = rsi_extremity * bb_extremity               # multiplicative gate — both must fire

mean_rev_cap += pressure * 18
trend_cap    -= pressure * 18
```

This ensures the engine can respond to extreme conditions even in trending regimes.

### 3.4 Trend Conviction

A separate 0-1.0 measure used to dampen order flow contrarian signals when a strong trend is in play:

```
ema_alignment  = sigmoid_scale(|ema_spread|, center=0.5, steepness=2.0)  # with penalty if spread/DI mismatch
adx_strength   = sigmoid_scale(adx, center=20, steepness=0.25)
price_confirm  = 1.0 if price on correct side of all 3 EMAs, else 0

trend_conviction = mean(ema_alignment, adx_strength, price_confirm)
```

### 3.5 Confidence

Uses a thesis-based approach — the engine identifies whether its primary thesis is trend-following or mean-reversion, then scores confidence accordingly:

```
trend_conf = 0.5 * trend_strength + 0.5 * trend_conviction
mr_conf    = mr_pressure

thesis_confidence    = max(trend_conf, mr_conf)
indicator_conflict   = 1 - |trend_score + mean_rev_score| / (|trend_score| + |mean_rev_score|)

confidence = 0.8 * thesis_confidence + 0.2 * (1.0 - indicator_conflict)
```

High confidence when the primary thesis is strong and indicators agree on direction.

### 3.6 Divergence Detection (HTF only: 4H, 1D)

Detects RSI/price divergences using swing point detection (order=3):
- **Bullish divergence:** price makes lower low, RSI makes higher low
- **Bearish divergence:** price makes higher high, RSI makes lower high

Returns 0-1.0 confidence. Scored separately from the main technical score.

---

## 4. Order Flow Scoring

**File:** `engine/traditional.py` (`score_order_flow`)

Applies contrarian bias on derivatives market metrics, modulated by regime and rate-of-change detection. Directional metrics (OI, CVD, book) are regime-independent.

### 4.1 Regime-Aware Contrarian Multiplier

```
contrarian_mult = 1.0 - (trending_strength * (1.0 - trending_floor))
```

- `trending_floor = 0.3`: even in strong trends, at least 30% contrarian signal preserved
- Ranging market: full contrarian (1.0x)
- Strong trending market: reduced contrarian (~0.3x)
- Mean-reversion pressure relaxes the floor toward 1.0: `relaxed_floor = 0.3 + mr_pressure * 0.7`

### 4.2 Rate-of-Change Override

Tracks 10 candle flow history (3 recent + 7 baseline). If funding rate, L/S ratio, or OI change rapidly:

```
roc_boost = sigmoid_scale(max_roc, center=0.0005, steepness=8000)
final_mult = contrarian_mult + roc_boost * (1 - contrarian_mult)
```

Rapid shifts in crowd positioning or commitment increase contrarian sensitivity even in trends.

### 4.3 Trend Conviction Dampening

```
final_mult = min(final_mult, 1.0 - trend_conviction * (1.0 - mr_pressure))
```

High trend conviction suppresses contrarian order flow signals, but mean-reversion pressure relaxes this dampening — allowing flow signals through when prices are at extremes even in a trend.

### 4.4 Five Scoring Components

| Component | Max Score | Logic | Type | Regime-Affected |
|-----------|-----------|-------|------|-----------------|
| Funding Rate | +/-22 | Contrarian: negative funding = bullish | Contrarian | Yes |
| Open Interest Change | +/-22 | Directional: agrees with price direction | Directional | No |
| Long/Short Ratio | +/-22 | Contrarian: ratio > 1 (more longs) = bearish | Contrarian | Yes |
| CVD (trend) | +/-22 | Slope of last 5-10 candle deltas, normalized by volume | Directional | No |
| Book Imbalance | +/-12 | Top-5 bid/ask volume ratio (30s freshness gate) | Directional | No |

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

Detects 14 pattern types with contextual boosts.

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

## 8. News Scoring

**File:** `engine/news_scorer.py`

LLM-based sentiment analysis on high/medium impact news events affecting the asset.

### 8.1 Input

Recent news articles within a 30-120 minute window of the current candle, filtered by pair relevance.

### 8.2 Scoring

The LLM evaluates each article for directional impact and conviction:

```
Output: {
    score:       -100 to +100,   # directional sentiment
    availability: 0.0 to 1.0,    # confidence in the score
    conviction:   0.0 to 1.0,    # agreement among sources
    confidence:   combined        # availability * conviction
}
```

### 8.3 Integration

News scores enter the combiner as a separate source with regime-dependent outer weight (typically 0.04-0.12 depending on regime). In volatile/ranging regimes, news carries more weight since event-driven moves dominate.

---

## 9. Regime Detection & Adaptive Weighting

**File:** `engine/regime.py`

The market regime determines both the inner caps (how much each scoring dimension can contribute) and the outer weights (how much each source matters in the final blend).

### 9.1 Raw Regime Mix

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

### 9.1b Optional LightGBM Classifier

**File:** `engine/regime_classifier.py`

When a trained LightGBM classifier is available and not stale (< 30 days old), it replaces the heuristic above. The classifier uses a richer feature set including ADX, BB width, funding rate change, OI change, and on-chain netflow — detecting regime transitions earlier than price-only heuristics. Training labels are generated retrospectively by `engine/regime_labels.py` (e.g., trending if directional move > 2x ATR over 48 candles). Falls back to the heuristic when the classifier is unavailable or stale.

### 9.2 Regime Smoothing

EMA smoothing (alpha=0.3) prevents single-candle regime flips. Per pair/timeframe, the smoothed regime blends 30% new observation with 70% prior state.

### 9.3 Inner Caps (per-dimension score limits)

The regime mix modulates how much each technical scoring dimension can contribute:

| Regime | Trend Cap | Mean Rev Cap | Squeeze Cap | Volume Cap |
|--------|-----------|--------------|-------------|------------|
| Trending | 38 | 22 | 12 | 28 |
| Ranging | 18 | 40 | 16 | 26 |
| Volatile | 25 | 28 | 22 | 25 |
| Steady | 40 | 15 | 20 | 25 |

Blended by dot product: e.g., `trend_cap = trending*38 + ranging*18 + volatile*25 + steady*40`.

### 9.4 Outer Weights (source blending)

Each scoring source receives a regime-dependent weight. All 7 sources are included:

| Regime | Tech | Flow | On-Chain | Pattern | Liquidation | Confluence | News |
|--------|------|------|----------|---------|-------------|------------|------|
| Trending | 0.34 | 0.19 | 0.13 | 0.08 | 0.07 | 0.13 | 0.06 |
| Ranging | 0.29 | 0.13 | 0.20 | 0.13 | 0.09 | 0.08 | 0.08 |
| Volatile | 0.30 | 0.16 | 0.14 | 0.09 | 0.09 | 0.10 | 0.12 |
| Steady | 0.35 | 0.15 | 0.15 | 0.10 | 0.08 | 0.13 | 0.04 |

Per-pair learned adjustments stored in `RegimeWeights` DB table can override these defaults. Additionally, online regime weight adaptation (see [Section 10](#10-online-regime-weight-adaptation)) applies overlay deltas learned from recent signal outcomes.

---

## 10. Online Regime Weight Adaptation

**File:** `engine/regime_online.py`

Adapts outer weights based on recent signal outcomes over a rolling 14-day window. This allows the engine to learn from its own performance and shift source emphasis toward what's working.

### 10.1 Workflow

1. **Startup rebuild:** `rebuild_regime_online_state()` loads resolved signals from the last 14 days and computes initial overlay deltas
2. **Per-resolution update:** when a signal resolves (TP/SL/EXPIRED), its outcome updates the overlay state
3. **Per-signal application:** `resolve_effective_outer_weights()` merges baseline weights + overlay deltas

### 10.2 Overlay Delta Calculation

For each resolved signal, the engine updates per-source deltas based on outcome quality:

```
effect    = compute_outcome_effect(outcome, direction, score)
           # +1 for win aligned with signal direction
           # -1 for loss aligned with signal direction
           # 0 for neutral/ambiguous outcomes

influence = compute_source_influence(score, confidence)
           # combines score magnitude + confidence (range 0.5-1.0)

delta = BASE_LR * regime_mix[regime] * effect * influence
        # BASE_LR = 0.01
        # regime_mix weights the update to the regime that was active
```

Each overlay delta is clamped to [-0.12, +0.12] per source per regime.

### 10.3 Effective Weight Resolution

1. Extract baseline weights from `RegimeWeights` (or defaults from Section 9.4)
2. Add per-regime overlay deltas
3. Normalize via bounded constraints (floor 0.02, ceiling 0.50)
4. Blend with current regime mix for final outer weights

Requires a minimum of **20 resolved signals** in the window before overlay deltas are applied.

---

## 11. Multi-Timeframe Confluence

**File:** `engine/confluence.py`

Lower timeframes receive a bonus/penalty based on alignment with their parent timeframe's trend direction.

| Child TF | Parent TFs |
|----------|------------|
| 15m | 1H, 4H, 1D |
| 1H | 4H, 1D |
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

Multiple parent timeframes are blended with configurable weights (immediate parent 0.5, grandparent 0.3, great-grandparent 0.2). Mean-reversion driven child signals receive reduced confluence weight.

---

## 12. Score Combination

**File:** `engine/combiner.py`

### 12.1 Confidence-Weighted Preliminary Blend

Each source's base weight (from regime outer weights) is multiplied by its confidence, with a conviction floor:

```
effective_weight[source] = base_weight[source] * confidence[source]
normalized_weight[source] = effective_weight[source] / sum(all effective weights)

# conviction scaling: floor of 0.3 ensures even low-conviction sources contribute minimally
scaled_score[source] = score * (0.3 + 0.7 * conviction)

preliminary_score = sum(scaled_score * normalized_weight for each source)
```

If a source is unavailable (confidence=0), its weight redistributes proportionally to the others.

Default base weights (before regime modulation):

| Source | Default Weight |
|--------|----------------|
| Technical | 0.40 |
| Order Flow | 0.22 |
| On-Chain | 0.23 |
| Pattern | 0.15 |
| Liquidation | 0.0 |
| Confluence | 0.0 |
| News | 0.0 |

### 12.2 Agreement Factor

When 3+ sources contribute, a directional consensus multiplier adjusts the score:

```
agreement_ratio = max(positive_count, negative_count) / total_contributing
multiplier = 0.85 + (1.15 - 0.85) * (agreement_ratio - 0.5) / 0.5
preliminary_score *= multiplier
```

- All sources agree: 1.15x boost
- Even split (50/50): 0.85x penalty
- This rewards conviction across multiple independent signals and penalizes mixed readings

### 12.3 Confidence Tier

```
avg_confidence = weighted average of all source confidences
```

| Tier | Condition |
|------|-----------|
| High | avg_confidence >= 0.70 |
| Medium | avg_confidence >= 0.40 |
| Low | avg_confidence < 0.40 |

---

## 13. ML Gate

**Files:** `ml/ensemble_predictor.py`, `engine/combiner.py`

Per-pair LSTM ensemble models predict direction and confidence. ML only contributes when sufficiently confident.

### 13.1 Ensemble Architecture

Multiple LSTM members (typically 3) trained via temporal splits. Each member produces:
- Direction logits (NEUTRAL / LONG / SHORT) with temperature-scaled softmax
- Regression outputs (SL, TP1, TP2 in ATR multiples)

### 13.2 Aggregation & Confidence Penalties

```
# per-member: forward pass on feature matrix
# aggregate: weighted mean of direction probabilities

disagreement = weighted_variance(member_probs)
uncertainty_penalty = min(1.0, disagreement * 8.0)
confidence = raw_confidence * (1.0 - uncertainty_penalty)
```

**PSI-based drift detection** further penalizes confidence when input features have shifted from the training distribution:

```
if psi > 0.25:  confidence *= (1.0 - 0.6)    # severe drift
elif psi > 0.1: confidence *= (1.0 - 0.3)    # moderate drift
```

Partial ensembles (only 2 members) are capped at 0.5 confidence.

### 13.3 ML Score Conversion

```
if direction == "NEUTRAL":
    ml_score = 0
else:
    centered = (confidence - 1/3) / (2/3) * 100   # re-center from [0.33, 1.0] to [0, 100]
    ml_score = centered if LONG, else -centered
```

### 13.4 Adaptive Blending

Unlike a fixed weight, ML influence ramps linearly with confidence:

```
if ml_confidence >= ml_confidence_threshold (default 0.65):
    t = (confidence - threshold) / (1.0 - threshold)
    ml_weight = 0.05 + (0.30 - 0.05) * t       # ramps from 5% to 30%
    blended = preliminary * (1 - ml_weight) + ml_score * ml_weight
else:
    blended = preliminary   # ML has no influence
```

At minimum confidence (0.65), ML contributes just 5%. At maximum confidence (1.0), up to 30%.

---

## 14. LLM Gate

**Files:** `engine/combiner.py`, `engine/llm.py`

When the blended score exceeds the LLM threshold, the full market context is sent to an LLM for qualitative analysis. The LLM response acts as an additive contribution, not an override.

### 14.1 Trigger Condition

```
if |blended_score| >= llm_threshold (default 40):
    call LLM with full context
elif mr_pressure >= mr_llm_trigger (default 0.30):
    call LLM (mean-reversion opportunity worth analyzing even at lower scores)
```

### 14.2 Dual-Pass Analysis

Two concurrent LLM calls provide balanced analysis:

1. **Standard pass:** experienced trader persona — analyzes the setup, identifies factors
2. **Devil's advocate pass:** critical analyst persona — looks for reasons the trade could fail

Both passes return structured factor lists. Results are aggregated via weighted mean to produce a merged contribution and an agreement flag.

### 14.3 LLM Factor Analysis

The LLM returns structured factors (max 5 per pass) across 4 categories:

| Category | Factors | Default Weights |
|----------|---------|-----------------|
| Structure | Support proximity, resistance proximity, level breakout, HTF alignment | 6, 6, 8, 7 |
| Momentum | RSI divergence, volume divergence, MACD divergence | 7, 6, 6 |
| Exhaustion | Volume exhaustion, funding extreme, crowded positioning | 5, 5, 5 |
| Event | Pattern confirmation, news catalyst | 5, 7 |

### 14.4 Contribution Computation

```
for each factor:
    aligned = (factor.direction == desired_direction)
    sign = +1 if aligned, else -1
    total += sign * factor_weight * factor.strength    # strength in {1, 2, 3}

llm_contribution = clamp(total, -factor_cap, +factor_cap)   # cap default 25.0
```

Factor weights are subject to calibration multipliers (see [Section 15](#15-llm-factor-calibration)).

### 14.5 Final Score

```
final_score = clamp(blended_score + llm_contribution, -100, +100)
```

---

## 15. LLM Factor Calibration

**File:** `engine/llm_calibration.py`

Tracks the historical accuracy of each LLM factor type and applies rolling multipliers to their weights, reducing the influence of factors that don't predict outcomes well.

### 15.1 Per-Factor Accuracy Tracking

For each resolved signal where the LLM contributed:
- Record which factors were cited and their direction
- Compare factor direction against actual outcome (TP = win, SL = loss)
- Maintain a rolling window of the last **30 signals** per pair

### 15.2 Accuracy-to-Multiplier Ramp

```
accuracy = wins / (wins + losses)   # per factor type

# sigmoid ramp between floor and ceiling
if accuracy <= ramp_low (0.40):  multiplier = floor (0.5)
elif accuracy >= ramp_high (0.55): multiplier = ceiling (1.0)
else: multiplier = 0.5 + (accuracy - 0.40) / (0.55 - 0.40) * 0.5
```

- Factors with < 40% accuracy are halved in weight
- Factors with > 55% accuracy get full weight
- Linear ramp between

### 15.3 Per-Pair Customization

- Uses per-pair multipliers when the pair has >= 15 calibrated signals
- Falls back to global (cross-pair) multipliers otherwise
- Applied before the contribution computation in Section 14.4

---

## 16. Signal Emission & Level Calculation

**File:** `engine/combiner.py`

### 16.1 Emission Check

```
direction = "LONG" if final_score > 0, else "SHORT"

effective_threshold = lookup_signal_threshold(pair, regime)   # adaptive per pair/regime
if |final_score| >= effective_threshold AND not cooldown_suppressed:
    emit signal
```

### 16.2 Level Priority Cascade

Entry, stop-loss, and take-profit levels are determined by the first available source:

| Priority | Source | Condition |
|----------|--------|-----------|
| 1 | ML regression | ML confidence >= threshold, model provides SL/TP ATR multiples |
| 2 | LLM explicit levels | LLM contribution >= 0, levels pass sanity check |
| 3 | ATR defaults | Learned multipliers from performance tracker, or defaults (1.5/2.0/3.0) |

### 16.3 Signal Strength Scaling

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

### 16.4 Level Guardrails

| Level | Bounds (ATR multiples) | Additional Constraint |
|-------|------------------------|-----------------------|
| SL | [0.5, 3.0] | R:R floor: tp1/sl >= 1.0 |
| TP1 | [1.0, 4.0] | -- |
| TP2 | [2.0, 6.0] | Must be >= tp1 * 1.2 |

---

## 17. Structure-Aware Level Snapping

**File:** `engine/structure.py`

After initial level calculation, levels are post-processed to sit at meaningful technical structure.

### 17.1 Structure Level Collection

Aggregates technical levels from multiple sources:

1. **Swing-based S/R zones** — pivot highs/lows clustered within 0.5 ATR tolerance, minimum 2 touches
2. **Bollinger Bands** — upper, lower, midline (SMA20)
3. **EMAs** — EMA 50 (strength 3), EMA 21 (strength 2), EMA 9 (strength 1)
4. **Liquidation clusters** — high-volume liquidation price zones

### 17.2 Snapping Logic

For each level (SL, TP1, TP2):
1. Find nearby structure within `max_snap_atr` (1.5 ATR) of the target
2. Select the best candidate: closest distance weighted by structure strength
3. Place the level just beyond the structure (0.15 ATR buffer)
4. Enforce SL bounds and R:R floor after snapping

This aligns algorithmic levels with technical structure that market participants actually watch.

---

## 18. Position Sizing & Risk Management

**File:** `engine/risk.py`

### 18.1 Base Position Sizing

```
sl_distance      = |entry - stop_loss| / entry
risk_amount      = equity * risk_per_trade           # default 1%
position_size    = risk_amount / sl_distance

position_size    = min(position_size, max_position_size_usd)
position_size    = min(position_size, equity * 0.25)  # hard cap at 25% of equity
```

### 18.2 Kelly Criterion

Dynamically adjusts `risk_per_trade` based on recent win rate and reward/risk ratio:

```
# computed from last 100 resolved signals
odds = average_win / average_loss
kelly_raw = win_rate - (1 - win_rate) / odds
kelly_frac = kelly_raw * kelly_fraction              # kelly_fraction = 0.35 (fractional Kelly)

risk_per_trade = clamp(kelly_frac, floor=0.005, ceiling=0.02)
```

Fractional Kelly (35%) provides a conservative estimate that balances growth with drawdown protection.

### 18.3 Correlation Dampening

Reduces position size when a new signal is correlated with existing open positions:

```
# for each PENDING signal in the same direction:
corr = pearson_correlation(20_candle_returns_of_new_pair, 20_candle_returns_of_open_pair)
max_corr = max across all same-direction open positions

dampening = 1.0 - max_corr * 0.6    # floor = 0.4
position_size *= dampening
```

This prevents concentrated exposure across correlated assets (e.g., ETH and BTC moving together).

### 18.4 RiskGuard Checks

| Check | Condition | Action |
|-------|-----------|--------|
| Daily Loss Limit | daily_pnl <= -3% | BLOCKED |
| Max Concurrent Positions | open_positions >= 3 | BLOCKED |
| Max Exposure | (total_exposure + new) / equity > 1.5% | BLOCKED |
| Cooldown After Loss | last SL hit < cooldown_minutes ago | WARNING |
| Max Risk Per Trade | size / equity > 2% | WARNING |

Blocked signals are not emitted. Warnings are logged but signal proceeds.

---

## 19. Anti-Whipsaw Cooldown

**File:** `engine/cooldown.py`

Suppresses signals after consecutive stop-loss hits to prevent the engine from repeatedly entering losing positions in choppy conditions.

### 19.1 Logic

Per-(pair, timeframe, direction) tracking:

```
on SL_HIT:  consecutive_sl_count += 1
on TP_HIT:  consecutive_sl_count = 0   # reset on any winning exit

if consecutive_sl_count > 0:
    cooldown_candles = min(consecutive_sl_count - 1, max_candles)   # max_candles = 3
    suppress signal for cooldown_candles after last SL
```

### 19.2 Behavior

- 1 SL hit: no suppression (first loss is normal)
- 2 consecutive SLs: 1 candle cooldown
- 3 consecutive SLs: 2 candle cooldown
- 4+ consecutive SLs: 3 candle cooldown (maximum)
- Any TP exit resets the counter

---

## 20. Signal Delivery

### 20.1 Persistence

Signal saved to Postgres `Signal` table with all metadata: scores, indicators, levels, risk metrics, detected patterns, correlated news IDs, engine snapshot, confidence tier.

### 20.2 WebSocket Broadcast

```json
{"type": "signal", "signal": { ...full signal data }}
```

Sent to all connected clients subscribed to the signal's pair and timeframe.

### 20.3 Web Push Notifications

Dispatched to all registered `PushSubscription` endpoints with signal summary.

### 20.4 Alert Evaluation

User-configured signal alerts are checked and triggered (e.g., "notify on any LONG BTC signal").

---

## 21. Outcome Resolution

**File:** `engine/outcome_resolver.py`

Background loop runs every 60 seconds, checking all PENDING signals. Uses a **two-pass resolution** system with partial exits and trailing stops.

### 21.1 Pass 1 — Immediate Checks

Per candle after signal creation, checked in priority order:

**For LONG signals:**

| Priority | Condition | Outcome |
|----------|-----------|---------|
| 1 | candle low <= stop_loss | SL_HIT |
| 2 | candle high >= take_profit_2 | TP2_HIT |
| 3 | candle high >= take_profit_1 | (proceed to Pass 2) |

**For SHORT signals:** (reversed high/low checks)

### 21.2 Pass 2 — Partial Exit + Trailing Stop

When TP1 is hit and ATR data is available:

1. **Partial exit at TP1:** 50% of position closed at TP1 price
2. **Trailing stop activated** on the remaining 50%:
   - Initial trail: 1 ATR below TP1 (LONG) or above TP1 (SHORT)
   - Ratchets forward as price makes new highs/lows: `trail = max(trail, high - atr)` for LONG
3. **Resolution of remainder:**
   - If price hits TP2: full exit at TP2, outcome = `TP1_TP2`
   - If trail stop hit: exit at trail price, outcome = `TP1_TRAIL`
   - Blended PnL computed: `0.5 * tp1_pnl + 0.5 * remainder_pnl`

### 21.3 Fallback

- If ATR is unavailable at TP1, resolves as simple `TP1_HIT`
- **Expiry:** signals older than 24 hours without hitting any level are force-closed at the current price and marked `EXPIRED`

Each resolution records PnL percentage, duration in minutes, and outcome type.

---

## 22. ATR Multiplier Learning

**File:** `engine/performance_tracker.py`

Learns optimal SL/TP ATR multipliers per pair/timeframe from historical signal outcomes.

### 22.1 Optimization Trigger

- Minimum 10 resolved signals required (configurable)
- Triggers every N resolved signals (configurable interval)
- Excludes signals that used LLM-provided levels (tests only ATR-derived levels)

### 22.2 Slippage Modeling

Outcome replays include realistic slippage scaled by volatility:

```
slippage = entry * base_bps * max(0.5, min(3.0, atr / median_atr)) / 10_000
```

| Pair | Base BPS | Rationale |
|------|----------|-----------|
| BTC-USDT-SWAP | 3 | Deep liquidity, tight spreads |
| ETH-USDT-SWAP | 5 | Good liquidity, moderate spreads |
| WIF-USDT-SWAP | 12 | Thin order books, wider spreads |

The ATR/median_atr ratio scales slippage higher during volatile periods (up to 3x) and lower during calm periods (down to 0.5x).

### 22.3 1D Sweep Optimization

For each dimension (SL, TP1, TP2) independently:

1. Generate candidate multiplier values across the valid range
2. For each candidate, replay all signals in the window with the candidate value while keeping the other two dimensions at their deployed effective values
3. Compute Sortino ratio for each candidate's outcome distribution
4. Select the candidate with the best Sortino if it improves over the current value

**Sortino ratio** (downside-risk-adjusted return):

```
downside_returns = [pnl for pnl in all_pnls if pnl < 0]
sortino = mean(all_pnls) / stdev(downside_returns)
```

### 22.4 Guardrails

| Dimension | Bounds | Max Per-Cycle Adjustment |
|-----------|--------|--------------------------|
| SL | [0.8, 2.5] | 0.3 |
| TP1 | [1.0, 4.0] | 0.5 |
| TP2 | [2.0, 6.0] | 0.5 |

R:R floor enforced after all adjustments: TP1 >= SL. TP2 >= TP1 * 1.2.

### 22.5 Bootstrap

On startup, seeds tracker rows from the best completed backtest (by profit factor) per pair/timeframe. Does not re-optimize — just copies starting values.

---

## 23. Parameter Optimizer

**File:** `engine/optimizer.py`, `engine/param_groups.py`

Monitors global signal fitness and proposes parameter changes via counterfactual backtesting.

### 23.1 Parameter Groups by Priority

| Layer | Groups | Method |
|-------|--------|--------|
| 0 (highest impact) | source_weights, thresholds | Grid sweep |
| 1 | regime_caps, regime_outer, atr_levels | Grid / DE |
| 2 | sigmoid_curves, order_flow, pattern_strengths, indicator_periods, mean_reversion, llm_factors, onchain | DE |

### 23.2 Shadow Mode Validation

1. Proposal created with backtest metrics on historical data
2. Shadow mode: next 20 signals re-scored with proposed parameters alongside live parameters
3. Compare profit factors: current vs shadow
4. Decision: **promote** (replace live params), **reject** (discard), or **inconclusive** (extend shadow)
5. Auto-rollback if profit factor drops 15% within 10 signals post-promotion

### 23.3 IC-Based Source Pruning

Computes Information Coefficient (Pearson correlation) of each source's scores vs actual outcomes:
- Prunes source if IC < -0.05 for 30 consecutive days (actively harmful signal)
- Re-enables if IC > 0.0 (returns to neutral or positive contribution)

---

## 24. ML Pipeline

**Files:** `ml/features.py`, `ml/model.py`, `ml/labels.py`, `ml/trainer.py`, `ml/ensemble_predictor.py`

### 24.1 Feature Engineering (~40 features)

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

### 24.2 Model Architecture — SignalLSTM

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

### 24.3 Label Generation

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

### 24.4 Training

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

### 24.5 Ensemble Training

3-member ensemble via temporal splits: the training data is divided into 3 overlapping temporal windows, producing members that specialize on different market periods. This creates natural diversity without random seed tricks.

### 24.6 Ensemble Inference

```
For each member:
    Forward pass --> direction probs (temp-scaled softmax), regression outputs
    Weight by member staleness (exponential decay)

Aggregate:
    weighted_mean_probs = sum(weight_i * probs_i) / sum(weights)
    disagreement = weighted_variance(probs across members)
    confidence_penalty = min(1.0, disagreement * 8.0)
    drift_penalty = PSI-based feature drift check

final_confidence = raw_confidence * (1 - confidence_penalty) * (1 - drift_penalty)

if only 2 members: cap confidence at 0.5
if model_age > 14 days: cap confidence at 0.3
```

---

## 25. Key Thresholds & Constants

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `signal_threshold` | 40 | Minimum \|score\| to emit a signal |
| `llm_threshold` | 40 | Minimum \|score\| to invoke LLM analysis |
| `mr_llm_trigger` | 0.30 | MR pressure threshold to invoke LLM even below score threshold |
| `ml_confidence_threshold` | 0.65 | ML confidence gate for blending |
| `ml_weight_min` | 0.05 | ML contribution at minimum confidence |
| `ml_weight_max` | 0.30 | ML contribution at maximum confidence |
| `llm_factor_total_cap` | 25.0 | Maximum LLM additive contribution |
| `confluence_max_score` | 15 | Maximum HTF alignment bonus |
| `min_candles` | 70 | Minimum candle history for reliable indicators |
| `risk_per_trade` | 1% | Equity risked per signal (adjusted by Kelly) |
| `kelly_fraction` | 0.35 | Fractional Kelly multiplier |
| `kelly_floor` | 0.5% | Minimum risk per trade |
| `kelly_ceiling` | 2% | Maximum risk per trade |
| `daily_loss_limit` | 3% | Daily drawdown cutoff |
| `max_concurrent_positions` | 3 | Portfolio position limit |
| `max_exposure` | 1.5% | Account leverage limit |
| `correlation_dampening_floor` | 0.4 | Minimum position size after correlation dampening |
| `regime_smoothing_alpha` | 0.3 | EMA smoothing for regime transitions |
| `sl_atr_default` | 1.5 | Default stop-loss ATR multiplier |
| `tp1_atr_default` | 2.0 | Default TP1 ATR multiplier |
| `tp2_atr_default` | 3.0 | Default TP2 ATR multiplier |
| `model_max_age_days` | 14 | ML model staleness threshold |
| `cooldown_max_candles` | 3 | Maximum anti-whipsaw suppression candles |
| `regime_online_base_lr` | 0.01 | Learning rate for online regime weight adaptation |
| `regime_online_min_signals` | 20 | Minimum signals before overlay deltas apply |
| `regime_online_overlay_bounds` | [-0.12, +0.12] | Per-source per-regime delta clamp |
| `llm_calibration_window` | 30 | Rolling signal window for factor accuracy |
| `llm_calibration_ramp` | [0.40, 0.55] | Accuracy range mapped to [0.5, 1.0] multiplier |
| `agreement_factor_range` | [0.85, 1.15] | Directional consensus multiplier bounds |
| `conviction_floor` | 0.3 | Minimum conviction scaling in preliminary blend |
| `ensemble_disagreement_scale` | 8.0 | Disagreement-to-penalty multiplier |
| `psi_moderate` / `psi_severe` | 0.1 / 0.25 | Feature drift PSI thresholds |
| `drift_penalty_moderate` / `severe` | 0.3 / 0.6 | Confidence penalties for drift |
