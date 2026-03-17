# Signal Algorithm Improvements

Identified areas for improvement in the signal generation pipeline, with agreed approaches.

## 1. Multi-Timeframe Confluence

**Problem:** Each timeframe (15m, 1h, 4h) is scored independently. A 15m long signal has the same weight whether it aligns with 1h/4h uptrends or fights against them.

**Impact:** Signals that fight higher-timeframe structure get stopped out more frequently. Signals aligned across timeframes have higher probability but receive no conviction boost.

**Approach:** Higher-TF trend as an input signal. Feed the higher-timeframe ADX trend direction/strength as a new scoring component (±15 points, boost + penalize) into the lower timeframe's technical score.

- 15m looks at 1h trend
- 1h looks at 4h trend
- 4h has no parent (unless 1D ingestion is added later)
- Aligned with higher TF = up to +15, conflicting = down to -15

**Status:** Not started

---

## 2. Market Regime Awareness

**Problem:** Indicator weights are static (tech 40%, flow 22%, on-chain 23%, pattern 15%) regardless of market conditions. Trend indicators produce noise in ranges. Mean-reversion signals fire during strong trends.

**Impact:** False signals in regime transitions. The algorithm doesn't adapt to what's actually working in current conditions.

**Approach:** Regime detection using existing ADX + BB width percentile, then shift indicator component weights per regime.

- **Trending:** ADX > 25 + BB expanding → upweight trend components, downweight mean-reversion
- **Ranging:** ADX < 20 + BB narrow/stable → upweight mean-reversion, downweight trend
- **Volatile/Choppy:** Low ADX + BB wide → reduce overall conviction

**Status:** Not started

---

## 3. Order Flow Contrarian Bias

**Problem:** Funding rate and long/short ratio scoring is always contrarian — high funding = bearish, many longs = bearish. In strong trends, crowded positioning can sustain for weeks.

**Impact:** Premature reversal signals during trending markets. The contrarian logic fights momentum when it should follow it.

**Approach:** Combine regime-adaptive baseline (from #2) with rate-of-change filtering.

- **Regime-adaptive:** In trending regimes, reduce contrarian weight or flip to momentum-following. In ranging/choppy regimes, keep full contrarian logic.
- **Rate-of-change modifier:** Rapidly increasing funding/LS ratio = potential extreme (keep contrarian). Slowly elevated = sustained trend (reduce contrarian weight).

Depends on #2 (regime detection).

**Status:** Not started

---

## 4. Indicator Redundancy

**Problem:** RSI (±25) and BB position (±15) both measure mean-reversion. They're correlated, giving mean-reversion an effective weight of ~40 points out of 100 — potentially outsized relative to its predictive value.

**Impact:** Mean-reversion signals dominate the technical score, potentially drowning out trend and volume signals.

**Approach:** Merge RSI + BB position into a single mean-reversion component. Make all component caps configurable and determine optimal allocation via backtesting.

- Remove BB position as a separate component
- Create unified mean-reversion score combining RSI distance-from-50 and BB position
- All component caps (trend, mean-reversion, volatility, OBV, volume) become configurable parameters
- Run backtest sweeps to find optimal distribution

**Status:** Not started

---

## 5. Structured LLM Factors

**Problem:** LLM impact is fixed buckets (+20/-15/-30) scaled only by confidence (HIGH/MEDIUM/LOW). The LLM's explanation text and any nuance in its analysis is discarded programmatically.

**Impact:** A well-reasoned LLM contradiction with specific evidence has the same effect as a vague one. No way to extract graduated signal from LLM analysis.

**Approach:** Extract structured factors from LLM response. Have the LLM return tagged reasons (e.g., divergence, key level, volume exhaustion) alongside its opinion. Map specific factors to specific score adjustments.

- Extend `LLMResponse` Pydantic model with a `factors` list of tagged reasons
- Each factor has a type, direction (bullish/bearish), and weight
- Per-factor weights can be tuned via backtesting to learn which LLM-identified factors actually predict outcomes
- Factors can interact with other pipeline components (e.g., LLM flags exhaustion → dampen volume score)
- Maintains debuggability — can trace exactly what the LLM flagged per signal

**Status:** Not started
