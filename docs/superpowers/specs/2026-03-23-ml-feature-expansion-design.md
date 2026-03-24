# ML Feature Expansion Design

**Date**: 2026-03-23
**Status**: Revised (post-review)
**Scope**: Expand ML feature set from 15-18 to up to 36 features across 5 new categories

## Problem

The current ML model (`SignalLSTM`) uses 15 base features (price action, indicators, temporal) plus 3 optional order flow features. It lacks:

- Explicit momentum/acceleration signals
- Market regime awareness (the rule-based engine has this, the ML model doesn't)
- Rate-of-change on order flow data
- Longer-term trend context (multi-timeframe proxy)
- Cross-asset context (BTC leads alts)

These gaps cause the ML model to miss patterns the rule-based engine captures, and to generate predictions that conflict with the current market regime.

## New Features (18 total)

### Momentum (6 features) — always computed

| Feature | Formula | Range |
|---------|---------|-------|
| `ret_5` | Cumulative return over last 5 candles | ~[-0.1, 0.1] |
| `ret_10` | Cumulative return over last 10 candles | ~[-0.2, 0.2] |
| `ret_20` | Cumulative return over last 20 candles | ~[-0.3, 0.3] |
| `rsi_roc` | (RSI[now] - RSI[5 ago]) / 50 | [-1, 1] |
| `vol_trend` | Linear slope of volume over last 10 candles, z-scored | ~[-3, 3] |
| `macd_accel` | (MACD_hist[now] - MACD_hist[3 ago]) / close * 10000 | ~[-10, 10] |

**Rationale**: The LSTM sees raw return sequences but struggles to learn explicit acceleration. Multi-horizon returns (5/10/20) give the model trend context at different scales without requiring different timeframe data.

### Multi-TF Proxy (3 features) — always computed

| Feature | Formula | Range |
|---------|---------|-------|
| `rsi_slow` | RSI with period=56 (4x standard 14), normalized (rsi-50)/50 | [-1, 1] |
| `ema_slow_dist` | (close - EMA-200) / ATR | ~[-5, 5] |
| `bb_pos_slow` | BB position with period=80, std period=80 | ~[0, 1] (can exceed bounds when price is outside bands; clipped to [-10, 10] with all other features) |

**Rationale**: Approximates higher-timeframe indicators without cross-timeframe data fetching. RSI-56 on 15m roughly captures the same overbought/oversold bias as RSI-14 on 1h. EMA-200 provides long-term trend position. BB-80 gives a wider volatility envelope.

**Warmup**: EMA-200 needs ~200 candles. During training (Postgres, thousands of candles) this is fine. During inference (Redis, exactly 200 candles), the first ~100 rows will have partially-converged EMA-200 values. **Accepted limitation**: the LSTM's `seq_len=50` window sees only the last 50 rows, where EMA-200 is reasonably converged (rows 150-200 of the series). The first 100 rows affect only the LSTM's hidden state warm-up, not the final prediction window. If this proves problematic in practice, SMA-200 (no convergence issue) can be substituted for inference without retraining — the values are close enough for the model to generalize.

### Regime (4 features) — optional, appended when regime is available

| Feature | Formula | Range |
|---------|---------|-------|
| `regime_trend` | Trending component from regime mix | [0, 1] |
| `regime_range` | Ranging component | [0, 1] |
| `regime_vol` | Volatile component | [0, 1] |
| `trend_conv` | Trend conviction | [0, 1] |

**Computation approach**: Regime and trend conviction are computed **externally** by the caller, not inside `build_feature_matrix()`. The feature builder is a pure matrix assembly function — it receives pre-computed per-candle values and slots them into the matrix. This avoids cross-module imports from `engine/` into `ml/` and ensures training and inference use identical code paths through `build_feature_matrix()`.

Note: `compute_trend_conviction()` returns `{"conviction": float, "direction": int}`. Callers must extract `["conviction"]` — only the magnitude is used as a feature (direction is already captured by EMA distances and RSI).

**Training path**: The training endpoint (`api/ml.py`) computes regime per-candle before calling `build_feature_matrix()`:
1. Computes ADX, DI+, DI-, BB width percentile from the candle series
2. Calls `sigmoid_scale()` → `compute_regime_mix()` per candle
3. Calls `compute_trend_conviction(...)["conviction"]` per candle
4. Passes `regime=list[dict]` and `trend_conviction=list[float]` to `build_feature_matrix()`

**Inference path**: `run_pipeline()` computes regime per-candle from the 200 Redis candles using the same engine functions (already imported in `main.py`). This produces per-candle lists matching the training distribution — no broadcast asymmetry. The computation is cheap (pure math on 200 rows, sub-millisecond).

### Inter-pair (2 features) — optional, appended when `btc_candles` arg provided

| Feature | Formula | Range |
|---------|---------|-------|
| `btc_ret_5` | BTC cumulative return over last 5 candles | ~[-0.1, 0.1] |
| `btc_atr_pct` | BTC ATR(14) / BTC close | ~[0, 0.05] |

**Rationale**: BTC dominance is the strongest cross-asset signal in crypto. When BTC dumps, alts follow. The model for ETH/WIF currently can't see this.

**BTC model handling**: BTC pairs are trained **without** inter-pair features. `btc_candles=None` for BTC, which means inter-pair columns are not appended. BTC models will have a smaller `input_size` than alt models. This avoids the BatchNorm NaN issue that would occur with all-zero constant columns (BatchNorm1d divides by std, which is 0 for constant columns).

**Training**: For non-BTC pairs, query BTC candles from Postgres for the same timeframe and date range. Align by timestamp (exact match on candle timestamps). For BTC, `btc_candles=None` — inter-pair features are omitted entirely.

**Inference**: For non-BTC pairs, fetch BTC candles from Redis (`candles:BTC-USDT-SWAP:{timeframe}`, one `lrange` call). For BTC, skip. The `Predictor` checks `btc_used` flag in model config to decide whether to request BTC data.

### Flow RoC (3 features) — optional, appended alongside existing flow features

| Feature | Formula | Range |
|---------|---------|-------|
| `funding_delta` | (funding_rate[now] - funding_rate[5 ago]) * 10000 | ~[-5, 5] |
| `ls_delta` | long_short_ratio[now] - ls_ratio[5 ago] | ~[-1, 1] |
| `oi_accel` | (oi_change_pct[now] - oi_change_pct[5 ago]) * 100 | ~[-10, 10] |

**Rationale**: The rule-based engine computes funding RoC and LS RoC via `_field_roc()` and uses them for `roc_boost`. The ML model only sees raw flow values, not their rate of change. "Funding is spiking" vs "funding is high but stable" are very different signals.

**Dependency**: Only computed when `order_flow` is provided and has enough history (>5 candles). Falls back to zeros for early candles in the series.

**Inference flow data strategy**: The current inference code repeats a single flow snapshot across all candles. This must change:

1. **Query**: Fetch the most recent 200 `OrderFlowSnapshot` rows for the pair from Postgres (same query pattern as the existing `flow_history` fetch, but with a larger limit).
2. **Alignment**: Match snapshots to candle timestamps. The alignment must be timeframe-aware:
   - For 15m candles: bucket snapshot timestamps to 15-minute boundaries
   - For 1h candles: bucket to hour boundaries (existing logic)
   - For 4h/1D: bucket to 4h/day boundaries
3. **Coverage threshold**: If less than 10% of candles have matching flow snapshots, skip flow features entirely (same threshold as training). This means `flow_used` models fall back to `input_size` without flow columns — handled by column truncation in `Predictor`.
4. **Unmatched candles**: Fill with zeros (neutral values: funding=0, ls_ratio=1.0, oi_change=0).

**Performance**: Querying 200 `OrderFlowSnapshot` rows from Postgres on every pipeline cycle adds latency to the hot path. Mitigation:
1. Cache the aligned flow list in Redis at key `flow_matrix:{pair}:{timeframe}`, with TTL equal to the candle interval (e.g., 900s for 15m).
2. Invalidate on new snapshot insertion (happens once per confirmed candle, not per tick).
3. On cache miss, query Postgres with a 100ms timeout; fall back to single-snapshot broadcast if the query is slow.
4. The cache stores the pre-aligned list of dicts as JSON, so `build_feature_matrix()` receives the same format regardless of source.

## Feature Ordering and `input_size`

Features are concatenated in this fixed order. Optional groups are appended only when their data is available:

| Group | Size | Condition | Cumulative (all enabled) |
|-------|------|-----------|--------------------------|
| Base (price + indicators + temporal) | 15 | Always | 15 |
| Momentum + Multi-TF proxy | 9 | Always | 24 |
| Regime | 4 | If regime available | 28 |
| Inter-pair | 2 | If btc_candles provided (non-BTC pairs only) | 30 |
| Flow + Flow RoC | 6 | If order_flow provided | 36 |

**Min `input_size`**: 24 (no optional groups)
**Max `input_size`**: 36 (all optional groups, non-BTC pair)
**Max for BTC**: 34 (no inter-pair)

The `input_size` recorded in `model_config.json` determines what the trained model expects.

## Backward Compatibility

`build_feature_matrix()` now always produces at least 24 columns (base + momentum + multi-TF). Old models expect fewer columns.

### `input_size=15` models (base only) — supported

`Predictor.predict()` truncates the feature matrix to match `input_size`:

```python
if features.shape[1] > self.input_size:
    features = features[:, :self.input_size]
```

This works because new features are always **appended** — the first 15 columns remain the original base features in the same order. Truncating to 15 gives the old model exactly what it expects.

### `input_size` 16-23 models (old flow layout) — NOT compatible, must retrain

The old layout placed flow features at positions 15-17. The new layout places momentum features at 15-17 and flow at positions 30-35. Truncation to 18 would silently feed momentum data where the model expects flow data, producing garbage predictions.

`Predictor.__init__()` detects stale models and disables them:

```python
if 16 <= self.input_size <= 23:
    logger.warning(
        "Model %s has input_size=%d (pre-expansion layout), needs retraining",
        pair, self.input_size,
    )
    self._stale = True
```

When `_stale` is True, `predict()` returns NEUTRAL immediately — same behavior as insufficient data. The pipeline continues without ML, and the model is flagged for retraining.

### `input_size >= 24` models (new layout) — fully supported

The `Predictor` truncates if the feature matrix has more columns than the model expects (e.g., model trained without inter-pair features but inference provides them). The inference call site in `main.py` always builds the full feature matrix with all available data.

## API Changes

### `build_feature_matrix()` new signature

```python
def build_feature_matrix(
    candles: pd.DataFrame,
    order_flow: list[dict] | None = None,
    regime: list[dict] | None = None,
    trend_conviction: list[float] | None = None,
    btc_candles: pd.DataFrame | None = None,
) -> np.ndarray:
```

All new parameters are optional with `None` defaults — fully backward compatible at the call site. `regime` and `trend_conviction` are **per-candle lists** (one entry per row in `candles`), computed externally by the caller. The feature builder is a pure matrix assembly function with no engine module imports.

### `prepare_training_data()` new signature

```python
def prepare_training_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    label_config: LabelConfig | None = None,
    btc_candles: list[dict] | None = None,
    regime: list[dict] | None = None,
    trend_conviction: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
```

Regime and trend conviction are computed by the caller (`api/ml.py`) and passed through. `btc_candles` passed through as a DataFrame.

### `model_config.json` new fields

```json
{
  "input_size": 36,
  "flow_used": true,
  "regime_used": true,
  "btc_used": true
}
```

### Inference changes in `main.py:run_pipeline()`

When calling `build_feature_matrix()` for ML prediction:

1. If predictor is stale (`_stale=True`, `input_size` 16-23): skip ML prediction entirely, log warning once.
2. If `model_config.regime_used`: compute regime per-candle from the 200-candle DataFrame using `sigmoid_scale()`, `compute_regime_mix()`, and `compute_trend_conviction()["conviction"]` (already imported in `main.py`). Pass as `regime=list[dict]` and `trend_conviction=list[float]`. This matches the training path exactly — no broadcast asymmetry.
3. For non-BTC pairs if `model_config.btc_used`: fetch BTC candles from Redis (`candles:BTC-USDT-SWAP:{timeframe}`) and pass as `btc_candles`.
4. If `model_config.flow_used`: check Redis cache `flow_matrix:{pair}:{timeframe}`. On miss, query per-candle `OrderFlowSnapshot` rows from Postgres (100ms timeout), align to candle timestamps using timeframe-aware bucketing, cache result with candle-interval TTL. Pass as `order_flow`.

### Training changes in `api/ml.py`

1. Regime features: compute per-candle from the training candle series using `sigmoid_scale()`, `compute_regime_mix()`, and `compute_trend_conviction()["conviction"]` (import from engine modules, already used in `main.py`). Pass as `regime` and `trend_conviction` lists to `prepare_training_data()`.
2. For non-BTC pairs: query BTC candles from Postgres for the same timeframe/date range, pass as `btc_candles`
3. For BTC: `btc_candles=None`, resulting in smaller `input_size`
4. Save `regime_used: true`, `btc_used: true/false`, `flow_used: true/false` in `model_config.json`

## Testing

### Feature matrix shapes (all 5 combinations)

1. `(candles)` → 24 features (base + momentum + multi-TF)
2. `(candles, regime=..., trend_conviction=...)` → 28 features
3. `(candles, btc_candles=...)` → 26 features
4. `(candles, order_flow=...)` → 30 features (24 + 3 flow + 3 flow RoC)
5. All args → 36 features
6. All args for BTC pair (no inter-pair) → 34 features

### Data quality

7. **No NaN after warmup**: first 50 rows may have NaN, rows 50+ must be clean across all combinations
8. **Feature ranges**: all values within [-10, 10] after clipping
9. **NaN in input data**: BTC candles with NaN values, flow snapshots with None fields — must produce valid output (zeros for missing)
10. **Mismatched lengths**: `len(order_flow) != len(candles)` — must raise or handle gracefully

### Edge cases

11. **Empty candles** (0 rows): must not crash, return empty array
12. **Single candle** (1 row): must produce valid shape, NaN in warmup-dependent features is acceptable
13. **Exactly 200 candles**: matches Redis inference size, verify EMA-200 convergence behavior

### Backward compatibility

14. **input_size=15 truncation**: build 24+ column matrix, pass to Predictor with `input_size=15`, verify first 15 columns preserved and shape correct
15. **input_size=18 stale detection**: Predictor with `input_size=18` sets `_stale=True`, `predict()` returns NEUTRAL
16. **input_size=24+ truncation**: build 36-column matrix, pass to Predictor with `input_size=24`, verify truncation to 24

### BTC pair exclusion

17. BTC pair with `btc_candles=None` → no inter-pair features (verify column count)
18. BTC pair with `btc_candles` provided → must be ignored or raise (BTC should not have self-referential features)

### Flow alignment

19. **15m bucketing**: snapshots bucketed to :00/:15/:30/:45 boundaries
20. **1h bucketing**: snapshots bucketed to hour boundaries
21. **4h bucketing**: snapshots bucketed to 4h boundaries
22. **Coverage threshold**: 0% coverage → skip flow features; 5% → skip; 10% → include; 100% → include
23. **Unmatched candles**: filled with neutral values (funding=0, ls_ratio=1.0, oi_change=0)

### Regime consistency

24. **Per-candle regime**: verify `regime` list length matches candle count
25. **Per-candle trend_conviction**: verify list length matches candle count
26. **Value ranges**: regime components sum to ~1.0, conviction in [0, 1]

### Integration

27. **`prepare_training_data()`**: run with all optional args (BTC candles, regime, conviction), verify output shapes
28. **Inference path**: mock `run_pipeline()` ML section with regime computation from 200-candle DataFrame, verify feature matrix shape matches model config
29. **Config flag round-trip**: train with all features, verify `model_config.json` has `regime_used=true`, `btc_used=true`, `flow_used=true`; load Predictor, verify flags read correctly

### Flow cache (Redis)

30. **Cache hit**: pre-populate `flow_matrix:{pair}:{timeframe}` in Redis, verify it's used instead of Postgres query
31. **Cache miss**: no Redis key, verify Postgres fallback produces correct alignment

## Files Changed

| File | Change |
|------|--------|
| `backend/app/ml/features.py` | Add 5 feature categories (momentum, multi-TF, regime, inter-pair, flow RoC), expand `build_feature_matrix()` signature to accept pre-computed regime/conviction/BTC data. No engine imports — pure matrix assembly. |
| `backend/app/ml/data_loader.py` | Pass `btc_candles`, `regime`, `trend_conviction` through to feature builder |
| `backend/app/api/ml.py` | Compute per-candle regime and trend conviction from training candles using engine functions. Fetch BTC candles for non-BTC pairs. Save `regime_used`, `btc_used`, `flow_used` config flags. |
| `backend/app/main.py` | Compute per-candle regime from 200-candle DataFrame. Fetch BTC candles from Redis. Fetch per-candle flow from Redis cache (with Postgres fallback + 100ms timeout). Detect stale predictors. |
| `backend/app/ml/predictor.py` | Read new config flags. Detect stale models (`input_size` 16-23) and return NEUTRAL. Truncate features to `input_size` for backward compat (input_size=15 and >=24 only). |
| `backend/tests/ml/test_features.py` | Comprehensive tests: all 5 feature combinations, edge cases, NaN/range checks, backward compat, flow alignment, stale model detection, regime per-candle consistency |
