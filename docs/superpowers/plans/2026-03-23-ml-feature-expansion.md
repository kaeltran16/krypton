# ML Feature Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the ML feature set from 15-18 to up to 36 features across 5 new categories (momentum, multi-TF proxy, regime, inter-pair, flow RoC).

**Architecture:** All new features are added in `features.py:build_feature_matrix()` with optional parameters for regime, BTC candles, and flow data. Always-on features (momentum, multi-TF proxy) derive from candle data alone. Optional features (regime, inter-pair, flow RoC) are appended when their data is provided. Backward compat via column truncation in `Predictor`.

**Backward compat note:** Column truncation works cleanly for old models with `input_size=15`. Models with `input_size=18` (15 base + 3 flow) will receive momentum features in positions 16-18 instead of flow features — these models must be retrained. This is acceptable since retraining is required anyway to benefit from the expanded feature set.

**Tech Stack:** Python, NumPy, Pandas, PyTorch (model unchanged), pytest

**Spec:** `docs/superpowers/specs/2026-03-23-ml-feature-expansion-design.md`

---

## File Map

| File | Responsibility |
|------|---------------|
| `backend/app/ml/features.py` | Feature engineering — all 5 new categories added here |
| `backend/app/ml/data_loader.py` | Training data prep — passes btc_candles through |
| `backend/app/ml/predictor.py` | Inference — truncates features for backward compat, reads new config flags |
| `backend/app/api/ml.py` | Training API — fetches BTC candles, saves new config flags |
| `backend/app/main.py` | Pipeline inference — passes regime, BTC candles, per-candle flow to feature builder |
| `backend/tests/ml/test_features.py` | Unit tests for all feature combinations |
| `backend/tests/ml/test_data_loader.py` | Integration test with btc_candles |
| `backend/tests/test_pipeline_ml.py` | Update mock predictor with new config flags |

---

### Task 1: Add momentum features (always-on)

**Files:**
- Modify: `backend/app/ml/features.py`
- Test: `backend/tests/ml/test_features.py`

Adds 6 features: `ret_5`, `ret_10`, `ret_20`, `rsi_roc`, `vol_trend`, `macd_accel`.

- [ ] **Step 1: Write failing test for momentum feature count**

Add to `backend/tests/ml/test_features.py`:

```python
def test_momentum_features_included(self):
    """Momentum features (6) are always computed, increasing base from 15 to 21."""
    df = _make_candles(100)
    features = build_feature_matrix(df)
    # 15 base + 6 momentum = 21 (multi-TF proxy added in next task)
    # For now just check > 15
    assert features.shape[1] > 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_momentum_features_included -v`

Expected: FAIL (currently returns exactly 15 columns)

- [ ] **Step 3: Add momentum feature constants and computation**

In `backend/app/ml/features.py`, add after `FLOW_FEATURES`:

```python
MOMENTUM_FEATURES = [
    "ret_5",        # cumulative return over last 5 candles
    "ret_10",       # cumulative return over last 10 candles
    "ret_20",       # cumulative return over last 20 candles
    "rsi_roc",      # (RSI[now] - RSI[5 ago]) / 50
    "vol_trend",    # linear slope of volume over last 10 candles, z-scored
    "macd_accel",   # (MACD_hist[now] - MACD_hist[3 ago]) / close * 10000
]
```

Update `ALL_FEATURES` to include momentum:

```python
ALL_FEATURES = PRICE_FEATURES + INDICATOR_FEATURES + TEMPORAL_FEATURES + MOMENTUM_FEATURES
```

In `build_feature_matrix()`, after the temporal features block (line ~139), add momentum computation. The column indices shift — momentum starts at index 15:

```python
    # Momentum features
    mom_start = len(PRICE_FEATURES) + len(INDICATOR_FEATURES) + len(TEMPORAL_FEATURES)

    # ret_5, ret_10, ret_20
    for j, window in enumerate([5, 10, 20]):
        features[:, mom_start + j] = close.pct_change(window).fillna(0).values

    # rsi_roc: (RSI[now] - RSI[5 ago]) / 50
    rsi_shifted = rsi.shift(5)
    features[:, mom_start + 3] = ((rsi - rsi_shifted) / 50).fillna(0).values

    # vol_trend: linear slope of volume over 10 candles, z-scored
    vol_slopes = np.zeros(n, dtype=np.float32)
    x_10 = np.arange(10, dtype=float)
    for i in range(9, n):
        window_vol = vol.values[i - 9 : i + 1].astype(float)
        vol_slopes[i] = np.polyfit(x_10, window_vol, 1)[0]
    vs_mean = pd.Series(vol_slopes).rolling(20, min_periods=1).mean().values
    vs_std = pd.Series(vol_slopes).rolling(20, min_periods=1).std().replace(0, 1).values
    features[:, mom_start + 4] = ((vol_slopes - vs_mean) / vs_std).astype(np.float32)

    # macd_accel: (MACD_hist[now] - MACD_hist[3 ago]) / close * 10000
    macd_hist_shifted = macd_hist.shift(3)
    features[:, mom_start + 5] = ((macd_hist - macd_hist_shifted) / close * 10000).fillna(0).values
```

Update the feature array allocation size — change `len(ALL_FEATURES)` to use the updated list that includes momentum.

Note: `rsi` and `macd_hist` are already computed earlier in the function. `vol` (volume series) is also available.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_momentum_features_included -v`

Expected: PASS

- [ ] **Step 5: Run all existing feature tests to check for regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`

The existing `test_output_shape` test asserts `shape[1] >= 15` which will still pass. The `test_includes_order_flow_columns` test checks that flow adds 3 columns — this should still pass since flow is still +3.

---

### Task 2: Add multi-TF proxy features (always-on)

**Files:**
- Modify: `backend/app/ml/features.py`
- Test: `backend/tests/ml/test_features.py`

Adds 3 features: `rsi_slow`, `ema_slow_dist`, `bb_pos_slow`.

- [ ] **Step 1: Write failing test for base feature count = 24**

Add to `backend/tests/ml/test_features.py`:

```python
def test_base_feature_count_is_24(self):
    """Base features (no optional args) = 15 original + 6 momentum + 3 multi-TF = 24."""
    df = _make_candles(250)  # need 200+ for EMA-200
    features = build_feature_matrix(df)
    assert features.shape[1] == 24
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_base_feature_count_is_24 -v`

Expected: FAIL (currently 21 after Task 1)

- [ ] **Step 3: Add multi-TF proxy feature constants and computation**

In `backend/app/ml/features.py`, add after `MOMENTUM_FEATURES`:

```python
MULTI_TF_FEATURES = [
    "rsi_slow",      # RSI-56, normalized (rsi-50)/50
    "ema_slow_dist", # (close - EMA-200) / ATR
    "bb_pos_slow",   # BB position with period=80
]
```

Update `ALL_FEATURES`:

```python
ALL_FEATURES = PRICE_FEATURES + INDICATOR_FEATURES + TEMPORAL_FEATURES + MOMENTUM_FEATURES + MULTI_TF_FEATURES
```

In `build_feature_matrix()`, after momentum block, add:

```python
    # Multi-TF proxy features
    mtf_start = mom_start + len(MOMENTUM_FEATURES)

    # rsi_slow: RSI with period=56
    rsi_slow = _rsi(close, 56)
    features[:, mtf_start] = ((rsi_slow - 50) / 50).fillna(0).values

    # ema_slow_dist: (close - EMA-200) / ATR
    ema_200 = _ema(close, 200)
    features[:, mtf_start + 1] = ((close - ema_200) / atr_safe).fillna(0).values

    # bb_pos_slow: BB position with period=80
    sma80 = close.rolling(80).mean()
    std80 = close.rolling(80).std()
    bb_upper_slow = sma80 + 2 * std80
    bb_lower_slow = sma80 - 2 * std80
    bb_range_slow = (bb_upper_slow - bb_lower_slow).replace(0, np.nan)
    features[:, mtf_start + 2] = ((close - bb_lower_slow) / bb_range_slow).fillna(0).values
```

Note: `_ema` and `_rsi` helper functions already exist in the file. `atr_safe` is already computed.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_base_feature_count_is_24 -v`

Expected: PASS

- [ ] **Step 5: Run all feature tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`

Expected: All PASS

---

### Task 3: Add regime features (optional group)

**Files:**
- Modify: `backend/app/ml/features.py`
- Test: `backend/tests/ml/test_features.py`

Adds 4 features: `regime_trend`, `regime_range`, `regime_vol`, `trend_conv`. Requires computing ADX/DI series in features.py and importing engine pure functions.

- [ ] **Step 1: Write failing tests for regime features**

Add to `backend/tests/ml/test_features.py`:

```python
def test_regime_features_add_4_columns(self):
    """Regime features add 4 columns when regime dict is provided."""
    df = _make_candles(250)
    regime = {"trending": 0.6, "ranging": 0.3, "volatile": 0.1}
    features = build_feature_matrix(df, regime=regime, trend_conviction=0.7)
    features_no_regime = build_feature_matrix(df)
    assert features.shape[1] == features_no_regime.shape[1] + 4  # 28

def test_regime_computed_from_candles_when_no_arg(self):
    """When regime=None but training mode, regime is computed internally."""
    df = _make_candles(250)
    # regime='compute' signals training mode: compute from candles
    features = build_feature_matrix(df, regime="compute")
    assert features.shape[1] == 28
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_regime_features_add_4_columns tests/ml/test_features.py::TestBuildFeatureMatrix::test_regime_computed_from_candles_when_no_arg -v`

Expected: FAIL

- [ ] **Step 3: Add ADX/DI computation and regime features**

In `backend/app/ml/features.py`, add imports at the top:

```python
from app.engine.scoring import sigmoid_scale
from app.engine.regime import compute_regime_mix
from app.engine.traditional import compute_trend_conviction
```

Add feature constants:

```python
REGIME_FEATURES = [
    "regime_trend",  # trending component [0, 1]
    "regime_range",  # ranging component [0, 1]
    "regime_vol",    # volatile component [0, 1]
    "trend_conv",    # trend conviction [0, 1]
]
```

Add an `_adx` helper function (same logic as `traditional.py:_adx` but local to avoid importing a private function):

```python
def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    """Compute ADX, +DI, -DI."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_series = tr.rolling(length).mean()
    plus_di = 100 * plus_dm.rolling(length).mean() / atr_series
    minus_di = 100 * minus_dm.rolling(length).mean() / atr_series
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_series = dx.rolling(length).mean()
    return adx_series, plus_di, minus_di
```

Update `build_feature_matrix()` signature:

```python
def build_feature_matrix(
    candles: pd.DataFrame,
    order_flow: list[dict] | None = None,
    regime: dict | str | None = None,
    trend_conviction: float | None = None,
    btc_candles: pd.DataFrame | None = None,
) -> np.ndarray:
```

After the multi-TF proxy block, add regime feature computation:

```python
    # Regime features (optional)
    if regime is not None:
        n_base = len(ALL_FEATURES)
        regime_arr = np.zeros((n, len(REGIME_FEATURES)), dtype=np.float32)

        if isinstance(regime, dict):
            # Inference mode: broadcast single regime to all rows
            regime_arr[:, 0] = regime.get("trending", 0.0)
            regime_arr[:, 1] = regime.get("ranging", 0.0)
            regime_arr[:, 2] = regime.get("volatile", 0.0)
            regime_arr[:, 3] = trend_conviction if trend_conviction is not None else 0.0
        elif regime == "compute":
            # Training mode: compute per-candle from candle data
            adx_series, plus_di, minus_di = _adx(high, low, close, 14)

            bb_widths = bb_width_raw  # saved earlier where bb_width feature is computed
            for i in range(n):
                adx_val = float(adx_series.iloc[i]) if pd.notna(adx_series.iloc[i]) else 0.0
                di_p = float(plus_di.iloc[i]) if pd.notna(plus_di.iloc[i]) else 0.0
                di_m = float(minus_di.iloc[i]) if pd.notna(minus_di.iloc[i]) else 0.0

                trend_strength = sigmoid_scale(adx_val, center=20, steepness=0.25)

                # BB width percentile over last 50 values
                start = max(0, i - 49)
                recent = bb_widths[start : i + 1]
                if len(recent) >= 2:
                    bb_pct = float(np.sum(recent < recent[-1]) / len(recent) * 100)
                else:
                    bb_pct = 50.0
                vol_expansion = sigmoid_scale(bb_pct, center=50, steepness=0.08)

                rm = compute_regime_mix(trend_strength, vol_expansion)
                regime_arr[i, 0] = rm["trending"]
                regime_arr[i, 1] = rm["ranging"]
                regime_arr[i, 2] = rm["volatile"]

                tc = compute_trend_conviction(
                    close=float(close.iloc[i]),
                    ema_9=float(ema9.iloc[i]) if pd.notna(ema9.iloc[i]) else float(close.iloc[i]),
                    ema_21=float(ema21.iloc[i]) if pd.notna(ema21.iloc[i]) else float(close.iloc[i]),
                    ema_50=float(ema50.iloc[i]) if pd.notna(ema50.iloc[i]) else float(close.iloc[i]),
                    adx=adx_val,
                    di_plus=di_p,
                    di_minus=di_m,
                )
                regime_arr[i, 3] = tc["conviction"]

        regime_arr = np.clip(regime_arr, -10, 10)
        features = np.concatenate([features, regime_arr], axis=1)
```

This requires `bb_width_arr` — save the raw BB width values earlier in the function where `bb_width` is computed:

```python
    bb_width_raw = (bb_upper - bb_lower).values  # save for regime computation
```

Use `bb_width_raw` as `bb_width_arr` in the regime block. Also, `ema9`, `ema21`, `ema50` are already computed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_regime_features_add_4_columns tests/ml/test_features.py::TestBuildFeatureMatrix::test_regime_computed_from_candles_when_no_arg -v`

Expected: PASS

- [ ] **Step 5: Run all feature tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`

Expected: All PASS

---

### Task 4: Add inter-pair features (optional group)

**Files:**
- Modify: `backend/app/ml/features.py`
- Test: `backend/tests/ml/test_features.py`

Adds 2 features: `btc_ret_5`, `btc_atr_pct`.

- [ ] **Step 1: Write failing test**

Add to `backend/tests/ml/test_features.py`:

```python
def test_inter_pair_features_add_2_columns(self):
    """Inter-pair features add 2 columns when btc_candles is provided."""
    df = _make_candles(250)
    btc_df = _make_candles(250, base=60000, trend=15)
    features = build_feature_matrix(df, btc_candles=btc_df)
    features_no_btc = build_feature_matrix(df)
    assert features.shape[1] == features_no_btc.shape[1] + 2  # 26
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_inter_pair_features_add_2_columns -v`

Expected: FAIL

- [ ] **Step 3: Add inter-pair feature computation**

In `backend/app/ml/features.py`, add constants:

```python
INTER_PAIR_FEATURES = [
    "btc_ret_5",   # BTC cumulative return over last 5 candles
    "btc_atr_pct", # BTC ATR(14) / BTC close
]
```

In `build_feature_matrix()`, after the regime block (and before the flow block), add:

```python
    # Inter-pair features (optional)
    if btc_candles is not None:
        btc_df = btc_candles.copy()
        btc_df.columns = [c.lower() for c in btc_df.columns]
        btc_close = btc_df["close"].astype(float)
        btc_high = btc_df["high"].astype(float)
        btc_low = btc_df["low"].astype(float)

        btc_arr = np.zeros((n, len(INTER_PAIR_FEATURES)), dtype=np.float32)

        # btc_ret_5
        btc_ret = btc_close.pct_change(5).fillna(0)
        # btc_atr_pct
        btc_prev_close = btc_close.shift(1)
        btc_tr = pd.concat([
            btc_high - btc_low,
            (btc_high - btc_prev_close).abs(),
            (btc_low - btc_prev_close).abs(),
        ], axis=1).max(axis=1)
        btc_atr = btc_tr.rolling(14).mean()
        btc_atr_pct = (btc_atr / btc_close).fillna(0)

        # Align lengths: btc_candles may have different length than candles
        btc_n = len(btc_df)
        if btc_n >= n:
            btc_arr[:, 0] = btc_ret.values[-n:]
            btc_arr[:, 1] = btc_atr_pct.values[-n:]
        else:
            btc_arr[-btc_n:, 0] = btc_ret.values
            btc_arr[-btc_n:, 1] = btc_atr_pct.values

        btc_arr = np.clip(btc_arr, -10, 10)
        features = np.concatenate([features, btc_arr], axis=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_inter_pair_features_add_2_columns -v`

Expected: PASS

- [ ] **Step 5: Run all feature tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`

Expected: All PASS

---

### Task 5: Add flow RoC features (alongside existing flow)

**Files:**
- Modify: `backend/app/ml/features.py`
- Test: `backend/tests/ml/test_features.py`

Adds 3 features: `funding_delta`, `ls_delta`, `oi_accel` — appended after the existing 3 flow features.

- [ ] **Step 1: Write failing test**

Add to `backend/tests/ml/test_features.py`:

```python
def test_flow_now_adds_6_columns(self):
    """Order flow now adds 6 columns: 3 base flow + 3 flow RoC."""
    df = _make_candles(250)
    flow = [{"funding_rate": 0.0001 + i * 0.00001, "oi_change_pct": 0.02, "long_short_ratio": 1.3}
            for i in range(250)]
    features = build_feature_matrix(df, order_flow=flow)
    features_no_flow = build_feature_matrix(df)
    assert features.shape[1] == features_no_flow.shape[1] + 6  # 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_flow_now_adds_6_columns -v`

Expected: FAIL (currently adds only 3)

- [ ] **Step 3: Add flow RoC computation and update existing flow test**

First, update the existing test in `backend/tests/ml/test_features.py` to expect 6 columns instead of 3:

```python
def test_includes_order_flow_columns(self):
    df = _make_candles(60)
    flow = [{"funding_rate": 0.0001, "oi_change_pct": 0.02, "long_short_ratio": 1.3}] * 60
    features = build_feature_matrix(df, order_flow=flow)
    features_no_flow = build_feature_matrix(df)
    assert features.shape[1] == features_no_flow.shape[1] + 6
```

Then in `backend/app/ml/features.py`, add constants:

```python
FLOW_ROC_FEATURES = [
    "funding_delta",         # (funding_rate[now] - funding_rate[5 ago]) * 10000
    "ls_delta",              # ls_ratio[now] - ls_ratio[5 ago]
    "oi_accel",              # (oi_change_pct[now] - oi_change_pct[5 ago]) * 100
]
```

Update `ALL_FEATURES_WITH_FLOW`:

```python
ALL_FEATURES_WITH_FLOW = ALL_FEATURES + FLOW_FEATURES + FLOW_ROC_FEATURES
```

In the existing order flow block of `build_feature_matrix()`, after computing the base 3 flow features, add flow RoC:

```python
    if order_flow is not None and len(order_flow) == n:
        flow_arr = np.zeros((n, len(FLOW_FEATURES) + len(FLOW_ROC_FEATURES)), dtype=np.float32)
        for i, f in enumerate(order_flow):
            flow_arr[i, 0] = f.get("funding_rate", 0) * 10000
            flow_arr[i, 1] = f.get("oi_change_pct", 0) * 100
            flow_arr[i, 2] = f.get("long_short_ratio", 1.0) - 1.0

        # Flow RoC: delta over 5 candles
        roc_lag = 5
        for i in range(roc_lag, n):
            flow_arr[i, 3] = flow_arr[i, 0] - flow_arr[i - roc_lag, 0]  # funding_delta (already *10000)
            flow_arr[i, 4] = (order_flow[i].get("long_short_ratio", 1.0)
                              - order_flow[i - roc_lag].get("long_short_ratio", 1.0))  # ls_delta
            flow_arr[i, 5] = flow_arr[i, 1] - flow_arr[i - roc_lag, 1]  # oi_accel (already *100)

        flow_arr = np.clip(flow_arr, -10, 10)
        features = np.concatenate([features, flow_arr], axis=1)
```

This replaces the old 3-column flow block with a 6-column block.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestBuildFeatureMatrix::test_flow_now_adds_6_columns -v`

Expected: PASS

- [ ] **Step 5: Run all feature tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`

Expected: All PASS (existing `test_includes_order_flow_columns` was already updated in Step 3)

---

### Task 6: Add comprehensive feature combination tests

**Files:**
- Modify: `backend/tests/ml/test_features.py`

- [ ] **Step 1: Write tests for all feature combinations**

Add to `backend/tests/ml/test_features.py`:

```python
def test_all_features_36_columns(self):
    """All optional groups enabled = 36 columns (non-BTC pair)."""
    df = _make_candles(250)
    btc_df = _make_candles(250, base=60000, trend=15)
    regime = {"trending": 0.6, "ranging": 0.3, "volatile": 0.1}
    flow = [{"funding_rate": 0.0001, "oi_change_pct": 0.02, "long_short_ratio": 1.3}] * 250
    features = build_feature_matrix(
        df, order_flow=flow, regime=regime, trend_conviction=0.7, btc_candles=btc_df,
    )
    assert features.shape[1] == 36

def test_regime_and_flow_no_btc_is_34(self):
    """Regime + flow but no BTC = 34 columns (BTC model case)."""
    df = _make_candles(250)
    regime = {"trending": 0.6, "ranging": 0.3, "volatile": 0.1}
    flow = [{"funding_rate": 0.0001, "oi_change_pct": 0.02, "long_short_ratio": 1.3}] * 250
    features = build_feature_matrix(df, order_flow=flow, regime=regime, trend_conviction=0.7)
    assert features.shape[1] == 34

def test_no_nan_after_warmup_with_all_features(self):
    """No NaN in features after warmup period when all optional groups enabled."""
    df = _make_candles(250)
    btc_df = _make_candles(250, base=60000, trend=15)
    regime = {"trending": 0.6, "ranging": 0.3, "volatile": 0.1}
    flow = [{"funding_rate": 0.0001 + i * 0.00001, "oi_change_pct": 0.02, "long_short_ratio": 1.3}
            for i in range(250)]
    features = build_feature_matrix(
        df, order_flow=flow, regime=regime, trend_conviction=0.7, btc_candles=btc_df,
    )
    # After warmup (first 50 rows), no NaN
    assert not np.any(np.isnan(features[50:]))

def test_features_clipped(self):
    """All features are clipped to [-10, 10]."""
    df = _make_candles(250)
    features = build_feature_matrix(df)
    assert features.max() <= 10.0
    assert features.min() >= -10.0
```

- [ ] **Step 2: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`

Expected: All PASS

---

### Task 7: Update Predictor for backward compatibility

**Files:**
- Modify: `backend/app/ml/predictor.py`
- Test: `backend/tests/ml/test_features.py`

- [ ] **Step 1: Write failing test for feature truncation**

Add a new test class in `backend/tests/ml/test_features.py`:

```python
class TestPredictorTruncation:

    def test_truncation_to_input_size(self):
        """Predictor should truncate feature columns to match model's input_size."""
        from unittest.mock import patch, MagicMock
        import torch

        # Simulate old model with input_size=15
        mock_model = MagicMock()
        mock_model.eval = MagicMock()
        mock_model.return_value = (
            torch.tensor([[0.1, 0.8, 0.1]]),  # dir_logits
            torch.tensor([[1.5, 2.0, 3.0]]),   # reg_out
        )

        from app.ml.predictor import Predictor
        predictor = Predictor.__new__(Predictor)
        predictor.device = torch.device("cpu")
        predictor.seq_len = 50
        predictor.input_size = 15
        predictor.flow_used = False
        predictor.model = mock_model

        # Pass 24-column features (as if new feature builder produced them)
        features = np.random.randn(100, 24).astype(np.float32)
        result = predictor.predict(features)

        # Model should have received input with last dim = 15
        call_args = mock_model.call_args[0][0]
        assert call_args.shape[-1] == 15
        assert result["direction"] in ("NEUTRAL", "LONG", "SHORT")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestPredictorTruncation::test_truncation_to_input_size -v`

Expected: FAIL (model receives 24 columns, BatchNorm throws shape error)

- [ ] **Step 3: Add truncation to Predictor.predict()**

In `backend/app/ml/predictor.py`, modify the `__init__` method to read new config flags:

```python
    self.flow_used = config.get("flow_used", False)
    self.regime_used = config.get("regime_used", False)
    self.btc_used = config.get("btc_used", False)
```

In `predict()`, add truncation before creating the tensor (after `window = features[-self.seq_len:]`):

```python
    # Truncate columns to match model's expected input size
    if window.shape[1] > self.input_size:
        window = window[:, :self.input_size]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestPredictorTruncation::test_truncation_to_input_size -v`

Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ -v`

Expected: All PASS

---

### Task 8: Update data_loader.py

**Files:**
- Modify: `backend/app/ml/data_loader.py`
- Test: `backend/tests/ml/test_data_loader.py`

- [ ] **Step 1: Write failing test for btc_candles pass-through**

Add to `backend/tests/ml/test_data_loader.py`:

```python
def test_with_btc_candles(self):
    candles = []
    btc_candles = []
    for i in range(200):
        candles.append({
            "timestamp": f"2025-01-01T{i:02d}:00:00+00:00",
            "open": 3000 + i * 10, "high": 3000 + i * 10 + 50,
            "low": 3000 + i * 10 - 30, "close": 3000 + i * 10 + 20,
            "volume": 100 + i,
        })
        btc_candles.append({
            "timestamp": f"2025-01-01T{i:02d}:00:00+00:00",
            "open": 67000 + i * 10, "high": 67000 + i * 10 + 50,
            "low": 67000 + i * 10 - 30, "close": 67000 + i * 10 + 20,
            "volume": 500 + i,
        })

    features, direction, sl, tp1, tp2 = prepare_training_data(
        candles, btc_candles=btc_candles,
    )

    # Should have inter-pair features (24 base + regime 4 + btc 2 = 30)
    # Regime is always computed during training
    assert features.shape[1] == 30
    assert features.shape[0] == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_data_loader.py::TestPrepareTrainingData::test_with_btc_candles -v`

Expected: FAIL

- [ ] **Step 3: Update prepare_training_data()**

In `backend/app/ml/data_loader.py`:

```python
def prepare_training_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    label_config: LabelConfig | None = None,
    btc_candles: list[dict] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    df = pd.DataFrame(candles)
    btc_df = pd.DataFrame(btc_candles) if btc_candles else None
    features = build_feature_matrix(
        df,
        order_flow=order_flow,
        regime="compute",           # always compute regime during training
        btc_candles=btc_df,
    )
    direction, sl_atr, tp1_atr, tp2_atr = generate_labels(df, label_config)
    return features, direction, sl_atr, tp1_atr, tp2_atr
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_data_loader.py::TestPrepareTrainingData::test_with_btc_candles -v`

Expected: PASS

- [ ] **Step 5: Update existing data_loader tests for new feature counts**

The existing tests assert `shape[1] >= 15`. Update:

- `test_returns_expected_arrays`: Change to `assert features.shape[1] == 28` (24 base + 4 regime, since training always computes regime)
- `test_with_order_flow`: Change the flow diff assertion to expect 6 extra columns (3 flow + 3 flow RoC)

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_data_loader.py -v`

Expected: All PASS

---

### Task 9: Update training API (ml.py) — BTC candles + config flags

**Files:**
- Modify: `backend/app/api/ml.py`

- [ ] **Step 1: Add BTC candle fetching in training loop**

In `backend/app/api/ml.py`, inside the `_run()` function's per-pair loop (after flow alignment, around line 197), add BTC candle fetching:

```python
                # Fetch BTC candles for inter-pair features (non-BTC pairs only)
                btc_candle_list = None
                is_btc = "BTC" in pair.upper()
                if not is_btc:
                    async with db.session_factory() as session:
                        btc_result = await session.execute(
                            select(Candle)
                            .where(Candle.pair == "BTC-USDT-SWAP")
                            .where(Candle.timeframe == body.timeframe)
                            .where(Candle.timestamp >= date_from)
                            .order_by(Candle.timestamp)
                        )
                        btc_rows = btc_result.scalars().all()

                    if btc_rows:
                        btc_candle_list = [{
                            "timestamp": c.timestamp.isoformat(),
                            "open": float(c.open), "high": float(c.high),
                            "low": float(c.low), "close": float(c.close),
                            "volume": float(c.volume),
                        } for c in btc_rows]
                        logger.info(f"BTC candles loaded for {pair}: {len(btc_candle_list)} rows")
```

- [ ] **Step 2: Pass btc_candles to prepare_training_data()**

Update the `prepare_training_data()` call:

```python
                features, direction, sl, tp1, tp2 = prepare_training_data(
                    candles, order_flow=flow, label_config=label_config,
                    btc_candles=btc_candle_list,
                )
```

- [ ] **Step 3: Save new config flags in model_config.json**

Update the `model_config.json` patching block (around line 231):

```python
                if os.path.isfile(config_path):
                    import json as _j
                    with open(config_path) as f:
                        meta = _j.load(f)
                    meta["flow_used"] = flow_used
                    meta["regime_used"] = True  # always computed during training
                    meta["btc_used"] = btc_candle_list is not None
                    with open(config_path, "w") as f:
                        _j.dump(meta, f, indent=2)
```

- [ ] **Step 4: Run existing ML API tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/ -v -k ml`

Expected: PASS (tests use mocked DB so BTC fetch will return empty, which is fine)

---

### Task 10: Add `bucket_timestamp` helper and update training alignment

**Files:**
- Modify: `backend/app/api/ml.py`
- Test: `backend/tests/api/test_bucket_timestamp.py`

- [ ] **Step 1: Write unit tests for `bucket_timestamp`**

Create `backend/tests/api/test_bucket_timestamp.py`:

```python
from datetime import datetime, timezone
from app.api.ml import bucket_timestamp


class TestBucketTimestamp:

    def test_15m_rounds_down(self):
        ts = datetime(2025, 1, 1, 14, 37, 22, tzinfo=timezone.utc)
        result = bucket_timestamp(ts, "15m")
        assert result.minute == 30
        assert result.second == 0

    def test_1h_rounds_to_hour(self):
        ts = datetime(2025, 1, 1, 14, 37, 22, tzinfo=timezone.utc)
        result = bucket_timestamp(ts, "1h")
        assert result.minute == 0
        assert result.hour == 14

    def test_4h_rounds_to_4h_boundary(self):
        ts = datetime(2025, 1, 1, 14, 37, 22, tzinfo=timezone.utc)
        result = bucket_timestamp(ts, "4h")
        assert result.hour == 12
        assert result.minute == 0

    def test_1d_rounds_to_midnight(self):
        ts = datetime(2025, 1, 1, 14, 37, 22, tzinfo=timezone.utc)
        result = bucket_timestamp(ts, "1D")
        assert result.hour == 0
        assert result.minute == 0
```

- [ ] **Step 2: Add `bucket_timestamp` to ml.py**

In `backend/app/api/ml.py`, add a public helper function (no leading underscore since it's used cross-module):

```python
def bucket_timestamp(ts: datetime, timeframe: str) -> datetime:
    """Bucket a timestamp to the nearest timeframe boundary."""
    if timeframe == "15m":
        return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
    elif timeframe == "1h":
        return ts.replace(minute=0, second=0, microsecond=0)
    elif timeframe == "4h":
        return ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0)
    elif timeframe == "1D":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        return ts.replace(minute=0, second=0, microsecond=0)
```

- [ ] **Step 3: Run bucket_timestamp tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_bucket_timestamp.py -v`

Expected: PASS

- [ ] **Step 4: Update training flow alignment to use `bucket_timestamp`**

In `backend/app/api/ml.py`, replace the hardcoded hour-bucketing in the training flow alignment (around line 168-178):

```python
                    for f in flow_rows:
                        ts_key = bucket_timestamp(f.timestamp, body.timeframe)
                        flow_by_ts[ts_key] = { ... }
                    ...
                    for c in candles:
                        c_ts = bucket_timestamp(
                            _dt.fromisoformat(c["timestamp"]), body.timeframe
                        )
```

This replaces the old `.replace(minute=0, second=0, microsecond=0)` with timeframe-aware bucketing.

- [ ] **Step 5: Run training API tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/ -v -k ml`

Expected: PASS

---

### Task 11: Update inference in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Update ML feature building in run_pipeline()**

In `backend/app/main.py`, find the ML scoring block (around line 496). Replace the current feature building logic:

```python
    if ml_predictor is not None:
        try:
            from app.ml.features import build_feature_matrix

            # Build flow data for ML features
            flow_for_features = None
            if getattr(ml_predictor, "flow_used", False):
                # Fetch per-candle flow history from DB
                try:
                    async with db.session_factory() as session:
                        flow_result_rows = await session.execute(
                            select(OrderFlowSnapshot)
                            .where(OrderFlowSnapshot.pair == pair)
                            .order_by(OrderFlowSnapshot.timestamp.desc())
                            .limit(200)
                        )
                        flow_snapshots = list(reversed(flow_result_rows.scalars().all()))

                    if flow_snapshots:
                        from app.api.ml import bucket_timestamp
                        flow_by_ts = {}
                        for snap in flow_snapshots:
                            ts_key = bucket_timestamp(snap.timestamp, timeframe)
                            flow_by_ts[ts_key] = {
                                "funding_rate": snap.funding_rate or 0,
                                "oi_change_pct": snap.oi_change_pct or 0,
                                "long_short_ratio": snap.long_short_ratio or 1.0,
                            }

                        zero_flow = {"funding_rate": 0, "oi_change_pct": 0, "long_short_ratio": 1.0}
                        flow_for_features = []
                        matched = 0
                        for c in candles_data:
                            from datetime import datetime as _dt
                            c_ts = bucket_timestamp(
                                _dt.fromisoformat(c["timestamp"]), timeframe
                            )
                            snap = flow_by_ts.get(c_ts)
                            if snap is not None:
                                matched += 1
                                flow_for_features.append(snap)
                            else:
                                flow_for_features.append(zero_flow)

                        coverage = matched / len(candles_data) if candles_data else 0
                        if coverage < 0.1:
                            logger.debug(f"ML flow coverage too low for {pair}: {coverage:.0%}")
                            flow_for_features = None
                except Exception as e:
                    logger.debug(f"ML flow history fetch failed: {e}")

            # Build BTC candles for inter-pair features
            btc_df = None
            if getattr(ml_predictor, "btc_used", False) and "BTC" not in pair.upper():
                try:
                    btc_cache_key = f"candles:BTC-USDT-SWAP:{timeframe}"
                    btc_raw = await redis.lrange(btc_cache_key, -200, -1)
                    if btc_raw:
                        btc_df = pd.DataFrame([json.loads(c) for c in btc_raw])
                except Exception as e:
                    logger.debug(f"BTC candle fetch for ML failed: {e}")

            # Build regime args
            regime_arg = None
            tc_arg = None
            if getattr(ml_predictor, "regime_used", False):
                regime_arg = tech_result["regime"]
                tc_arg = tech_result["indicators"]["trend_conviction"]

            feature_matrix = build_feature_matrix(
                df,
                order_flow=flow_for_features,
                regime=regime_arg,
                trend_conviction=tc_arg,
                btc_candles=btc_df,
            )
            ml_prediction = ml_predictor.predict(feature_matrix)
```

Note: `OrderFlowSnapshot` is already imported at the top of `main.py` — no new import needed.

- [ ] **Step 2: Update mock predictors in test_pipeline_ml.py**

In `backend/tests/test_pipeline_ml.py`, find where mock predictors are created and add the new config flags:

```python
predictor.flow_used = False
predictor.regime_used = False
predictor.btc_used = False
```

Without this, `MagicMock` returns truthy values for unset attributes, causing the pipeline to attempt regime/BTC data fetches against the test mocks.

- [ ] **Step 3: Run pipeline tests**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline.py tests/test_pipeline_ml.py -v`

Expected: PASS

---

### Task 12: Final integration test and commit

**Files:**
- All modified files

- [ ] **Step 1: Run the full test suite**

Run: `docker exec krypton-api-1 python -m pytest -v`

Expected: All PASS

- [ ] **Step 2: Verify feature counts manually**

Run a quick sanity check:

```bash
docker exec krypton-api-1 python3 -c "
from app.ml.features import ALL_FEATURES, MOMENTUM_FEATURES, MULTI_TF_FEATURES, REGIME_FEATURES, INTER_PAIR_FEATURES, FLOW_FEATURES, FLOW_ROC_FEATURES
print(f'Base: {len(ALL_FEATURES)}')
print(f'  Momentum: {len(MOMENTUM_FEATURES)}')
print(f'  Multi-TF: {len(MULTI_TF_FEATURES)}')
print(f'Regime: {len(REGIME_FEATURES)}')
print(f'Inter-pair: {len(INTER_PAIR_FEATURES)}')
print(f'Flow: {len(FLOW_FEATURES)} + RoC: {len(FLOW_ROC_FEATURES)}')
print(f'Max total: {len(ALL_FEATURES) + len(REGIME_FEATURES) + len(INTER_PAIR_FEATURES) + len(FLOW_FEATURES) + len(FLOW_ROC_FEATURES)}')
"
```

Expected output:
```
Base: 24
  Momentum: 6
  Multi-TF: 3
Regime: 4
Inter-pair: 2
Flow: 3 + RoC: 3
Max total: 36
```

- [ ] **Step 3: Stage and review changes**

Show the diff summary and ask for approval before committing.

Files changed:
- `backend/app/ml/features.py` — 5 new feature groups
- `backend/app/ml/data_loader.py` — btc_candles pass-through, regime="compute"
- `backend/app/ml/predictor.py` — truncation + new config flags
- `backend/app/api/ml.py` — BTC candle fetch, `bucket_timestamp`, new config flags, timeframe-aware flow alignment
- `backend/app/main.py` — full feature args in inference
- `backend/tests/ml/test_features.py` — comprehensive tests
- `backend/tests/ml/test_data_loader.py` — updated expectations
- `backend/tests/api/test_bucket_timestamp.py` — new: bucket_timestamp unit tests
- `backend/tests/test_pipeline_ml.py` — updated mock predictor flags

Commit message: `feat(ml): expand feature set with momentum, regime, multi-TF, inter-pair, and flow RoC`
