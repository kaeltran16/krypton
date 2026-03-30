# Krypton Signal Engine — Potential Improvements

Improvements are grouped by pipeline layer and rated by impact and implementation effort.

---

## 1. Signal Quality

### 1.1 Joint Bayesian ATR Optimization
**Layer:** `engine/performance_tracker.py`
**Impact:** High | **Effort:** High (~1 week)

**Problem:** The current 1D sweep optimizes SL, TP1, and TP2 independently. These dimensions are coupled — a wider SL allows price more room to breathe, which changes the probability of reaching TP2. Optimizing them sequentially will always find a locally suboptimal solution.

**Proposed change:** Replace the 1D sweep with a Gaussian process surrogate over the full 3D search space (SL × TP1 × TP2). The GP learns a smooth approximation of the Sortino surface from past backtest evaluations. An acquisition function (Expected Improvement) selects the next candidate, balancing exploitation of high-Sortino regions with exploration of uncertain areas. Converges to the true joint optimum in significantly fewer evaluations than a grid sweep.

**Implementation:** Swap the sweep loop in `performance_tracker.py` for `scikit-optimize` (`gp_minimize`) or `botorch`. Pass the existing guardrail bounds as the search space. The outcome replay logic is unchanged.

```python
from skopt import gp_minimize
from skopt.space import Real

space = [
    Real(0.8, 2.5, name='sl_atr'),
    Real(1.0, 4.0, name='tp1_atr'),
    Real(2.0, 6.0, name='tp2_atr'),
]

result = gp_minimize(
    func=lambda params: -sortino_from_replay(signals, *params),
    dimensions=space,
    n_calls=40,
    n_initial_points=8,
    acq_func='EI',
)
```

**Guardrails:** Keep existing bounds and per-cycle adjustment caps. Enforce TP1 >= SL and TP2 >= TP1 * 1.2 as constraints inside the replay function.

---

### 1.2 Tighten LLM Contribution Cap + Dual-Pass Consistency
**Layer:** `engine/combiner.py`, `engine/llm.py`
**Impact:** High | **Effort:** Low (~1 day)

**Problem:** The LLM can add up to ±35 points. Against a signal threshold of 40, this means a single LLM call can nearly manufacture a signal from a blended score of just 25. There is also no consistency check — the LLM is called once and trusted.

**Proposed changes:**

1. Reduce `llm_factor_total_cap` from 35 to 20.
2. Raise the minimum blended score to invoke the LLM from 25 to 30 (`llm_threshold`).
3. Run two LLM calls with slightly varied prompts (e.g. one framed as "assess bullish case", one as "assess bearish case"). Only apply the contribution if the net factor scores agree in direction. If they conflict, apply 50% of the smaller magnitude.

```python
LLM_FACTOR_TOTAL_CAP = 20       # was 35
LLM_THRESHOLD = 30              # was 25

def get_llm_contribution(context, desired_direction):
    call_a = score_factors(context, prompt_variant="standard")
    call_b = score_factors(context, prompt_variant="devil_advocate")
    if sign(call_a) == sign(call_b):
        return clamp((call_a + call_b) / 2, -LLM_FACTOR_TOTAL_CAP, LLM_FACTOR_TOTAL_CAP)
    else:
        return clamp(min(abs(call_a), abs(call_b)) / 2 * sign(call_a), -LLM_FACTOR_TOTAL_CAP, LLM_FACTOR_TOTAL_CAP)
```

---

### 1.3 Exponentially Weighted IC Pruning
**Layer:** `engine/optimizer.py`
**Impact:** Medium | **Effort:** Low (~1 day)

**Problem:** The current IC pruning requires 30 *consecutive* days below -0.05 before a source is pruned. A source that becomes harmful after a regime change can damage signals for nearly a month before being removed.

**Proposed change:** Replace the consecutive-day counter with an exponentially weighted moving average of daily IC values (alpha = 0.1, giving a ~10-day half-life). Prune when EW-IC < -0.05; re-enable when EW-IC > 0.0.

```python
ew_ic = alpha * daily_ic + (1 - alpha) * ew_ic   # alpha = 0.1

if ew_ic < -0.05:
    prune_source(source)
elif ew_ic > 0.0:
    reenable_source(source)
```

This reacts to a newly harmful source in days rather than months while still being robust to a single bad week.

---

## 2. Model and Learning

### 2.1 Deep Ensemble to Replace MC Dropout
**Layer:** `ml/model.py`, `ml/trainer.py`, `ml/predictor.py`
**Impact:** High | **Effort:** High (retraining overhead)

**Problem:** MC dropout with 5 passes estimates uncertainty by measuring prediction variance *within* one model's learned representation. It cannot detect out-of-distribution inputs — when the market enters a regime unseen during training, dropout variance barely changes. This causes the ML gate to pass signals at full weight precisely when it should be most skeptical.

**Proposed change:** Train 3 instances of `SignalLSTM` on different bootstrap samples of the training data (sample with replacement, ~80% of data each). At inference, run all three forward passes in parallel (no dropout needed) and use the disagreement between models as the uncertainty estimate.

```python
# Training
models = [SignalLSTM() for _ in range(3)]
for i, model in enumerate(models):
    bootstrap_data = sample_with_replacement(train_data, frac=0.80, seed=i)
    train(model, bootstrap_data)

# Inference
probs_list = [model(x) for model in models]           # shape: [3, batch, 3]
mean_probs = torch.stack(probs_list).mean(dim=0)      # [batch, 3]
disagreement = torch.stack(probs_list).var(dim=0).mean(dim=-1)   # [batch]

direction = mean_probs.argmax(dim=-1)
raw_confidence = mean_probs.max(dim=-1).values
uncertainty_penalty = (disagreement * 8).clamp(0, 1)
final_confidence = raw_confidence * (1 - uncertainty_penalty)
```

**Why this beats dropout:** Three models trained on different data slices develop genuinely different representations. In a regime transition or macro shock, models trained on different historical periods will disagree — confidence correctly collapses. Dropout only adds noise to one set of weights and cannot produce this kind of structural disagreement.

**Inference latency:** All three forward passes are embarrassingly parallel — GPU batching means latency is the same as a single pass.

**Staleness handling:** Instead of the current hard cliff at 14 days (confidence capped to 0.3), track each model's age independently and apply a smooth per-model weight decay in the ensemble average:

```python
def model_weight(age_days):
    if age_days <= 7:
        return 1.0
    elif age_days <= 21:
        return 1.0 - (age_days - 7) / 14 * 0.7   # decays from 1.0 to 0.3
    else:
        return 0.3

weights = torch.tensor([model_weight(m.age_days) for m in models])
weights /= weights.sum()
mean_probs = sum(w * p for w, p in zip(weights, probs_list))
```

---

### 2.2 Learned Regime Classifier
**Layer:** `engine/regime.py`
**Impact:** Medium | **Effort:** High (significant ML work)

**Problem:** The current regime detector uses two hard-coded indicators (ADX and BB width). It cannot use order flow or on-chain features, and it often lags regime transitions by several candles because the raw mix is smoothed with a 0.3 EMA alpha.

**Proposed change:** Train a lightweight classifier (e.g. a 2-layer GRU or gradient boosted tree) on labeled regime periods. Labels can be generated retrospectively: look forward 48 candles, classify as trending if the directional move > 2× ATR, ranging if price oscillates within 1× ATR, volatile if ATR expands > 1.5× without direction. Features include ADX, BB width, funding rate change, OI change, and on-chain netflow — giving the classifier early signals that raw price action lags.

This approach detects the trending → volatile transition earlier, which is where the current system takes its largest drawdowns (contrarian order flow signals fire against a developing trend).

---

## 3. Risk and Execution

### 3.1 Fractional Kelly Position Sizing
**Layer:** `engine/risk.py`
**Impact:** Medium | **Effort:** Medium (~3 days)

**Problem:** Fixed 1% risk per trade ignores signal quality, recent performance, and regime. A strong signal in a trending regime should size larger than a borderline signal in a choppy market.

**Proposed change:** Compute a per-signal Kelly fraction from the system's recent win rate and average win/loss ratio, then use a fixed fraction (25–50%) of Kelly to avoid overbetting:

```python
def kelly_fraction(recent_signals, regime, pair, lookback=30):
    wins = [s for s in recent_signals[-lookback:] if s.outcome in ('TP1_HIT', 'TP2_HIT')]
    losses = [s for s in recent_signals[-lookback:] if s.outcome == 'SL_HIT']
    if len(wins) + len(losses) < 10:
        return DEFAULT_RISK   # fall back to 1% if insufficient history

    win_rate = len(wins) / (len(wins) + len(losses))
    avg_win = mean(s.pnl_pct for s in wins)
    avg_loss = abs(mean(s.pnl_pct for s in losses))
    odds = avg_win / avg_loss if avg_loss > 0 else 1.0

    kelly = win_rate - (1 - win_rate) / odds
    return max(0.005, min(0.02, kelly * KELLY_FRACTION))   # KELLY_FRACTION = 0.35

KELLY_FRACTION = 0.35   # fractional Kelly — conservative
```

Existing hard caps (25% equity, daily loss limit, max exposure) remain unchanged as the safety net.

---

### 3.2 Partial Exit + ATR Trailing Stop
**Layer:** `engine/outcome_resolver.py`, `engine/risk.py`
**Impact:** Medium | **Effort:** Medium (~3 days)

**Problem:** Outcome resolution is binary — a signal either hits TP1, TP2, or SL. In practice, exiting the full position at TP1 leaves significant gains on the table when a strong trend continues. Holding for TP2 exposes the full position to retracement.

**Proposed change:** When TP1 is hit, close 50% of the position and activate an ATR trailing stop on the remainder. The trail starts at 1× ATR below (for longs) the TP1 price and moves up as price advances, locking in profits while giving the trade room to run to TP2 or beyond.

```python
if tp1_hit:
    close_partial(position, fraction=0.50)
    activate_trailing_stop(
        remaining=position * 0.50,
        initial_stop=tp1_price - 1.0 * atr,
        trail_atr=1.0,
        direction=signal.direction,
    )
```

Outcome resolution records two separate PnL entries (partial close at TP1, trail close at final exit) for accurate ML training labels and ATR multiplier learning.

---

## 4. Architecture

### 4.1 News Sentiment as a Standalone Scoring Source
**Layer:** `engine/`, `engine/combiner.py`
**Impact:** Medium | **Effort:** High (new pipeline component)

**Problem:** News and event data currently only reaches the system through the LLM gate, which is only invoked when `|blended_score| >= 25`. A major macro catalyst cannot lift a borderline technical signal — it's locked out of the pipeline entirely.

**Proposed change:** Add a `news_scorer.py` source that emits a score (-100 to +100) and confidence directly into the combiner. Confidence is a function of article recency, relevance to the pair, and article count within the lookback window. The scorer uses pre-computed LLM sentiments already being generated for high-impact articles (Section 2.5) — no new LLM calls needed.

```python
def compute_news_score(pair, lookback_minutes=120):
    articles = get_recent_articles(pair, lookback_minutes)
    if not articles:
        return score=0, confidence=0.0

    weighted_sentiment = sum(
        a.sentiment * recency_weight(a.timestamp) * a.relevance_score
        for a in articles
    )
    confidence = min(1.0, len(articles) / 5) * mean(a.relevance_score for a in articles)
    return clamp(weighted_sentiment * 50, -100, 100), confidence
```

Add `news` as a sixth source in the outer weight tables in `regime.py`, with low default weights (trending: 0.06, ranging: 0.08, volatile: 0.12, steady: 0.04) so it can influence borderline signals without dominating.

---

### 4.2 Cross-Pair Correlation Dampener
**Layer:** `engine/risk.py`
**Impact:** Medium | **Effort:** Medium (~2 days)

**Problem:** A new signal in a pair that is highly correlated with an existing open position effectively doubles the portfolio's exposure to the same market move. The current RiskGuard checks total exposure in dollar terms but not directional correlation.

**Proposed change:** Before emitting a signal, compute the rolling 20-candle return correlation between the new pair and all currently open positions. If a correlated position exists in the same direction, reduce the new signal's position size proportionally:

```python
def correlation_size_factor(new_pair, new_direction, open_positions, lookback=20):
    max_corr = 0.0
    for pos in open_positions:
        if pos.direction == new_direction:
            corr = rolling_correlation(new_pair, pos.pair, lookback)
            max_corr = max(max_corr, abs(corr))

    # Scale down linearly: 0 corr = full size, 1.0 corr = 40% size
    return max(0.4, 1.0 - max_corr * 0.6)

size *= correlation_size_factor(pair, direction, open_positions)
```

---

## 5. Anti-Whipsaw Signal Cooldown
**Layer:** `main.py` (pipeline orchestration)
**Impact:** Medium | **Effort:** Low (~1 day)

**Problem:** The pipeline runs on every confirmed candle. In choppy/ranging markets, it can emit alternating LONG/SHORT signals for the same pair in rapid succession, each hitting SL. This whipsaw pattern is the largest source of unnecessary losses in ranging regimes.

**Proposed change:** After a signal resolves as `SL_HIT`, suppress new signals for the same pair for N candles (configurable, default 3). The cooldown only applies after stop-outs — TP exits do not trigger suppression since they indicate the scoring was directionally correct.

```python
COOLDOWN_CANDLES = 3

def should_suppress(pair: str, recent_signals: list[Signal]) -> bool:
    last_resolved = next(
        (s for s in reversed(recent_signals) if s.pair == pair and s.outcome),
        None,
    )
    if last_resolved is None or last_resolved.outcome != "SL_HIT":
        return False
    candles_since = count_candles_since(last_resolved.resolved_at)
    return candles_since < COOLDOWN_CANDLES
```

**Guardrails:** Cooldown is per-pair only — other pairs remain unaffected. The cooldown counter resets on timeframe boundaries to avoid stale suppression after gaps.

---

## 6. Feature Importance Drift Detection
**Layer:** `ml/predictor.py`, `ml/trainer.py`
**Impact:** Medium | **Effort:** Medium (~3 days)

**Problem:** The LSTM trains on a fixed feature set, but feature relevance shifts over time (e.g., funding rate becomes less predictive in low-leverage environments). The current staleness detection is purely time-based — a 14-day cliff that caps confidence to 0.3. A model can become unreliable well before 14 days if the market regime shifts the importance of its input features.

**Proposed change:** At training time, compute permutation importance for the top features and store alongside the model checkpoint. At inference time, compare the current feature distribution (rolling 50-candle window) against the training distribution using a simple divergence metric (e.g., PSI — Population Stability Index). If any top-3 training feature's PSI exceeds a threshold, apply a confidence penalty before the staleness cliff kicks in.

```python
def feature_drift_penalty(current_features, training_stats, top_k=3):
    max_psi = 0.0
    for i in training_stats["top_feature_indices"][:top_k]:
        psi = population_stability_index(
            training_stats["feature_distributions"][i],
            current_features[:, i],
        )
        max_psi = max(max_psi, psi)

    if max_psi < 0.1:
        return 0.0       # stable
    elif max_psi < 0.25:
        return 0.3        # moderate drift
    else:
        return 0.6        # severe drift — model likely unreliable

confidence *= (1.0 - feature_drift_penalty(...))
```

This catches model unreliability from regime shifts days before the hard 14-day cliff, without requiring retraining.

---

## 7. LLM Factor Calibration
**Layer:** `engine/combiner.py`, `engine/llm.py`
**Impact:** Medium | **Effort:** Low (~1 day)

**Problem:** The 12 LLM factor weights (5.0–8.0) were hand-tuned with no feedback loop. There is no mechanism to detect whether a specific factor type (e.g., `NEWS_CATALYST`, `WHALE_ACTIVITY`) actually predicts outcomes. A factor that consistently misfires contributes noise to every LLM-gated signal.

**Proposed change:** Track per-factor-type accuracy over a rolling window of resolved signals. When a factor's directional accuracy drops below chance (50%) over the last 30 LLM-gated signals, halve its weight. Restore the original weight when accuracy recovers above 55%.

```python
def calibrate_factor_weights(
    base_weights: dict[str, float],
    factor_history: list[dict],
    lookback: int = 30,
) -> dict[str, float]:
    calibrated = dict(base_weights)
    for factor_type, weight in base_weights.items():
        recent = [h for h in factor_history[-lookback:] if h["type"] == factor_type]
        if len(recent) < 10:
            continue
        accuracy = sum(1 for h in recent if h["correct"]) / len(recent)
        if accuracy < 0.50:
            calibrated[factor_type] = weight * 0.5
        elif accuracy > 0.55:
            calibrated[factor_type] = weight  # restore
    return calibrated
```

---

## 8. Slippage-Aware Outcome Replay
**Layer:** `engine/performance_tracker.py`, `engine/optimizer.py`
**Impact:** Low–Medium | **Effort:** Low (~1 day)

**Problem:** ATR multiplier optimization and DE parameter sweeps replay outcomes at exact TP/SL price levels. Real fills slip — especially on WIF-USDT-SWAP which has thinner order books. This causes the optimizer to favor tight levels that look good in replay but underperform live.

**Proposed change:** Add a per-pair slippage model to the replay function. Apply slippage against the trade (widen SL hits, narrow TP hits) so the Sortino surface reflects realistic execution.

```python
SLIPPAGE_BPS = {
    "BTC-USDT-SWAP": 3,    # 0.03%
    "ETH-USDT-SWAP": 5,    # 0.05%
    "WIF-USDT-SWAP": 12,   # 0.12%
}

def apply_slippage(entry, exit_price, direction, pair):
    slip = SLIPPAGE_BPS.get(pair, 5) / 10_000
    if direction == "LONG":
        return exit_price * (1 - slip)   # sell fill is worse
    else:
        return exit_price * (1 + slip)   # buy-to-cover fill is worse
```

---

## 9. Adaptive Regime Weight Online Update
**Layer:** `engine/regime.py`
**Impact:** Medium | **Effort:** Medium (~2 days)

**Problem:** `RegimeWeights` stores per-pair learned outer weights, but these are only updated during full DE optimization sweeps. Between sweeps, regime weights can become stale — especially after a regime transition where the optimal source blend changes.

**Proposed change:** After each signal resolves, nudge outer weights toward sources that predicted the outcome correctly. Use a small learning rate to avoid overreacting to individual signals while keeping weights current between full optimization cycles.

```python
ONLINE_LR = 0.02

def update_regime_weights_online(
    current_weights: dict[str, float],
    regime: str,
    source_scores: dict[str, float],
    signal_direction: str,
    outcome: str,
) -> dict[str, float]:
    correct = outcome in ("TP1_HIT", "TP2_HIT")
    updated = dict(current_weights)

    for source, score in source_scores.items():
        predicted_correctly = (
            (score > 0 and signal_direction == "LONG") or
            (score < 0 and signal_direction == "SHORT")
        ) == correct

        if predicted_correctly:
            updated[source] += ONLINE_LR
        else:
            updated[source] -= ONLINE_LR
        updated[source] = max(0.02, min(0.5, updated[source]))

    # renormalize
    total = sum(updated.values())
    return {k: v / total for k, v in updated.items()}
```

---

## Summary Table

| # | Improvement | Layer | Impact | Effort | Priority |
|---|---|---|---|---|---|
| 1.3 | Exp-weighted IC pruning | optimizer | Medium | Low | Do first |
| 5 | Anti-whipsaw signal cooldown | main.py | Medium | Low | Do first |
| 3.2 | Partial exit + trailing stop | outcome_resolver, risk | Medium | Medium | High |
| 1.1 | Joint Bayesian ATR opt | performance_tracker | High | High | High |
| 1.2 | LLM cap + dual-pass | combiner, llm | High | Low | Medium |
| 4.1 | News sentiment source | engine/ | Medium | High | Medium |
| 4.2 | Cross-pair correlation dampener | risk | Medium | Medium | Medium |
| 3.1 | Fractional Kelly sizing | risk | Medium | Medium | Medium |
| 7 | LLM factor calibration | combiner, llm | Medium | Low | Medium |
| 8 | Slippage-aware outcome replay | performance_tracker, optimizer | Low–Medium | Low | Medium |
| 9 | Adaptive regime weight update | regime | Medium | Medium | Medium |
| 6 | Feature importance drift detection | ml/ | Medium | Medium | Long-term |
| 2.1 | Deep ensemble | ml/ | High | High | Long-term |
| 2.2 | Learned regime classifier | regime | Medium | High | Long-term |

### Notes

- **1.2 (LLM dual-pass):** The doc originally stated `llm_threshold = 25` — the actual value is **40**. The dual-pass consistency idea is still valid, but the cap reduction (35→20) may be too aggressive given the already-high invocation threshold. Re-evaluate numbers before implementing.
- **2.1 (Deep ensemble):** Consider temporal splits instead of random bootstrap to maximize model diversity with only 3 pairs.
- **3.1 (Fractional Kelly):** Increase minimum lookback from 30 to 50 signals — Kelly is sensitive to estimation error on small samples.
