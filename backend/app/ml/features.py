"""Feature engineering pipeline for ML model training and inference."""

import numpy as np
import pandas as pd


# Feature column order (for documentation and consistency)
PRICE_FEATURES = [
    "ret",           # close-to-close return
    "body_ratio",    # (close - open) / (high - low)
    "upper_wick",    # (high - max(open, close)) / (high - low)
    "lower_wick",    # (min(open, close) - low) / (high - low)
    "volume_zscore", # z-scored volume over lookback
]

INDICATOR_FEATURES = [
    "ema9_dist",     # (close - EMA9) / ATR
    "ema21_dist",    # (close - EMA21) / ATR
    "ema50_dist",    # (close - EMA50) / ATR
    "rsi_norm",      # (RSI - 50) / 50 → [-1, 1]
    "macd_norm",     # MACD histogram / close * 10000
    "bb_position",   # (close - BB_lower) / (BB_upper - BB_lower)
    "bb_width",      # (BB_upper - BB_lower) / close
    "atr_pct",       # ATR / close
]

TEMPORAL_FEATURES = [
    "hour_sin",      # sin(2π * hour / 24)
    "hour_cos",      # cos(2π * hour / 24)
]

MOMENTUM_FEATURES = [
    "ret_5",         # cumulative return over last 5 candles
    "ret_10",        # cumulative return over last 10 candles
    "ret_20",        # cumulative return over last 20 candles
    "rsi_roc",       # (RSI[now] - RSI[5 ago]) / 50
    "vol_trend",     # linear slope of volume over last 10 candles, z-scored
    "macd_accel",    # (MACD_hist[now] - MACD_hist[3 ago]) / close * 10000
]

MULTI_TF_FEATURES = [
    "rsi_slow",      # RSI(56) normalized: (rsi-50)/50
    "ema_slow_dist", # (close - EMA-200) / ATR
    "bb_pos_slow",   # BB position with period=80
]

REGIME_FEATURES = [
    "regime_trend",  # trending component from regime mix
    "regime_range",  # ranging component
    "regime_vol",    # volatile component
    "trend_conv",    # trend conviction magnitude
]

INTER_PAIR_FEATURES = [
    "btc_ret_5",     # BTC cumulative return over last 5 candles
    "btc_atr_pct",   # BTC ATR(14) / BTC close
]

FLOW_FEATURES = [
    "funding_rate",
    "oi_change_pct",
    "long_short_ratio_norm",  # (ls_ratio - 1.0), centered at neutral
]

FLOW_ROC_FEATURES = [
    "funding_delta",  # (funding_rate[now] - funding_rate[5 ago]) * 10000
    "ls_delta",       # long_short_ratio[now] - ls_ratio[5 ago]
    "oi_accel",       # (oi_change_pct[now] - oi_change_pct[5 ago]) * 100
]

# Base features always produced (24 columns)
BASE_FEATURES = PRICE_FEATURES + INDICATOR_FEATURES + TEMPORAL_FEATURES + MOMENTUM_FEATURES + MULTI_TF_FEATURES

ALL_FEATURES = BASE_FEATURES
ALL_FEATURES_WITH_FLOW = BASE_FEATURES + FLOW_FEATURES + FLOW_ROC_FEATURES


def get_feature_names(
    flow_used: bool = False,
    regime_used: bool = False,
    btc_used: bool = False,
) -> list[str]:
    """Return ordered list of feature column names matching build_feature_matrix output."""
    names = list(BASE_FEATURES)
    if regime_used:
        names = names + REGIME_FEATURES
    if btc_used:
        names = names + INTER_PAIR_FEATURES
    if flow_used:
        names = names + FLOW_FEATURES + FLOW_ROC_FEATURES
    return names


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def build_feature_matrix(
    candles: pd.DataFrame,
    order_flow: list[dict] | None = None,
    regime: list[dict] | None = None,
    trend_conviction: list[float] | None = None,
    btc_candles: pd.DataFrame | None = None,
) -> np.ndarray:
    """Build normalized feature matrix from candle data.

    Args:
        candles: DataFrame with columns: open, high, low, close, volume.
                 Optionally 'timestamp' for temporal features.
        order_flow: Optional list of dicts (one per candle) with keys:
                    funding_rate, oi_change_pct, long_short_ratio.
        regime: Optional list of dicts (one per candle) with keys:
                trending, ranging, volatile.
        trend_conviction: Optional list of floats (one per candle), 0-1.
        btc_candles: Optional DataFrame of BTC candles for inter-pair features.

    Returns:
        np.ndarray of shape (n_candles, n_features).
        First ~50 rows may contain NaN due to indicator warmup.
    """
    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)

    if n == 0:
        return np.empty((0, len(BASE_FEATURES)), dtype=np.float32)

    features = np.zeros((n, len(BASE_FEATURES)), dtype=np.float32)

    close = df["close"].astype(float)
    opn = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)

    hl_range = (high - low).replace(0, np.nan)

    # Price features (0-4)
    features[:, 0] = close.pct_change().fillna(0).values                         # ret
    features[:, 1] = ((close - opn) / hl_range).fillna(0).values                 # body_ratio
    features[:, 2] = ((high - np.maximum(opn, close)) / hl_range).fillna(0).values  # upper_wick
    features[:, 3] = ((np.minimum(opn, close) - low) / hl_range).fillna(0).values   # lower_wick

    vol_mean = vol.rolling(20, min_periods=1).mean()
    vol_std = vol.rolling(20, min_periods=1).std().replace(0, 1)
    features[:, 4] = ((vol - vol_mean) / vol_std).fillna(0).values               # volume_zscore

    # Indicators (5-12)
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_safe = atr.replace(0, np.nan)

    features[:, 5] = ((close - ema9) / atr_safe).fillna(0).values                # ema9_dist
    features[:, 6] = ((close - ema21) / atr_safe).fillna(0).values               # ema21_dist
    features[:, 7] = ((close - ema50) / atr_safe).fillna(0).values               # ema50_dist

    rsi = _rsi(close, 14)
    features[:, 8] = ((rsi - 50) / 50).fillna(0).values                          # rsi_norm

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd_line = ema12 - ema26
    macd_signal = _ema(macd_line, 9)
    macd_hist = macd_line - macd_signal
    features[:, 9] = (macd_hist / close * 10000).fillna(0).values                # macd_norm

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    features[:, 10] = ((close - bb_lower) / bb_range).fillna(0).values           # bb_position
    features[:, 11] = ((bb_upper - bb_lower) / close).fillna(0).values           # bb_width
    features[:, 12] = (atr / close).fillna(0).values                             # atr_pct

    # Temporal features (13-14)
    if "timestamp" in df.columns:
        try:
            ts = pd.to_datetime(df["timestamp"])
            hours = ts.dt.hour + ts.dt.minute / 60
            features[:, 13] = np.sin(2 * np.pi * hours / 24).values              # hour_sin
            features[:, 14] = np.cos(2 * np.pi * hours / 24).values              # hour_cos
        except Exception:
            pass  # leave as zeros

    # Momentum features (15-20)
    col = 15
    ret_5 = close.pct_change(5).fillna(0)
    ret_10 = close.pct_change(10).fillna(0)
    ret_20 = close.pct_change(20).fillna(0)
    features[:, col] = ret_5.values                                               # ret_5
    features[:, col + 1] = ret_10.values                                          # ret_10
    features[:, col + 2] = ret_20.values                                          # ret_20

    rsi_roc = (rsi - rsi.shift(5)).fillna(0) / 50
    features[:, col + 3] = rsi_roc.values                                         # rsi_roc

    # vol_trend: linear slope of volume over last 10 candles, z-scored
    vol_slope = pd.Series(np.nan, index=vol.index)
    if n >= 10:
        x = np.arange(10, dtype=float)
        x_mean = x.mean()
        x_var = ((x - x_mean) ** 2).sum()
        windows = np.lib.stride_tricks.sliding_window_view(vol.values, 10)
        y_means = windows.mean(axis=1)
        slopes = ((windows - y_means[:, None]) * (x - x_mean)).sum(axis=1) / x_var
        vol_slope.iloc[9:] = slopes
    vol_slope_mean = vol_slope.rolling(20, min_periods=1).mean()
    vol_slope_std = vol_slope.rolling(20, min_periods=1).std().replace(0, 1)
    features[:, col + 4] = ((vol_slope - vol_slope_mean) / vol_slope_std).fillna(0).values  # vol_trend

    macd_accel = (macd_hist - macd_hist.shift(3)).fillna(0) / close * 10000
    features[:, col + 5] = macd_accel.values                                      # macd_accel

    # Multi-TF proxy features (21-23)
    col = 21
    rsi_slow = _rsi(close, 56)
    features[:, col] = ((rsi_slow - 50) / 50).fillna(0).values                   # rsi_slow

    ema200 = _ema(close, 200)
    features[:, col + 1] = ((close - ema200) / atr_safe).fillna(0).values        # ema_slow_dist

    sma80 = close.rolling(80).mean()
    std80 = close.rolling(80).std()
    bb_upper_slow = sma80 + 2 * std80
    bb_lower_slow = sma80 - 2 * std80
    bb_range_slow = (bb_upper_slow - bb_lower_slow).replace(0, np.nan)
    features[:, col + 2] = ((close - bb_lower_slow) / bb_range_slow).fillna(0).values  # bb_pos_slow

    # Winsorize at 1st/99th percentile per feature instead of hard ±10 clip.
    # Hard clipping at ±10 destroyed 17.8% of macd_norm values; percentile
    # winsorization preserves the distribution shape while taming outliers.
    # BatchNorm1d in the model handles the actual normalization.
    p1, p99 = np.percentile(features, [1, 99], axis=0)
    mask = p1 < p99
    features[:, mask] = np.clip(features[:, mask], p1[mask], p99[mask])

    # Optional: Regime features (4 columns)
    if regime is not None and trend_conviction is not None:
        if len(regime) == n and len(trend_conviction) == n:
            regime_arr = np.zeros((n, len(REGIME_FEATURES)), dtype=np.float32)
            for i in range(n):
                r = regime[i]
                regime_arr[i, 0] = r.get("trending", 0)
                regime_arr[i, 1] = r.get("ranging", 0)
                regime_arr[i, 2] = r.get("volatile", 0)
                regime_arr[i, 3] = trend_conviction[i]
            features = np.concatenate([features, regime_arr], axis=1)

    # Optional: Inter-pair features (2 columns)
    if btc_candles is not None:
        btc_df = btc_candles.copy()
        btc_df.columns = [c.lower() for c in btc_df.columns]
        btc_n = len(btc_df)
        inter_arr = np.zeros((n, len(INTER_PAIR_FEATURES)), dtype=np.float32)
        if btc_n >= n:
            # align: take the last n rows of BTC data
            btc_close = btc_df["close"].astype(float).values[-n:]
            btc_high = btc_df["high"].astype(float).values[-n:]
            btc_low = btc_df["low"].astype(float).values[-n:]

            btc_close_s = pd.Series(btc_close)
            btc_ret_5 = btc_close_s.pct_change(5).fillna(0).values
            inter_arr[:, 0] = btc_ret_5

            btc_prev = np.roll(btc_close, 1)
            btc_prev[0] = btc_close[0]
            btc_tr = np.maximum(
                btc_high - btc_low,
                np.maximum(
                    np.abs(btc_high - btc_prev),
                    np.abs(btc_low - btc_prev),
                ),
            )
            btc_atr = pd.Series(btc_tr).rolling(14).mean().fillna(0).values
            btc_close_safe = np.where(btc_close == 0, np.nan, btc_close)
            inter_arr[:, 1] = np.nan_to_num(btc_atr / btc_close_safe, nan=0.0)

        features = np.concatenate([features, inter_arr], axis=1)

    # Optional: Flow features (3 base + 3 RoC = 6 columns)
    if order_flow is not None and len(order_flow) == n:
        flow_arr = np.zeros((n, len(FLOW_FEATURES) + len(FLOW_ROC_FEATURES)), dtype=np.float32)
        funding = np.zeros(n, dtype=np.float32)
        ls_ratio = np.zeros(n, dtype=np.float32)
        oi_change = np.zeros(n, dtype=np.float32)

        for i, f in enumerate(order_flow):
            funding[i] = (f.get("funding_rate") or 0) * 10000
            oi_change[i] = (f.get("oi_change_pct") or 0) * 100
            ls_ratio[i] = (f.get("long_short_ratio") or 1.0) - 1.0

        flow_arr[:, 0] = funding
        flow_arr[:, 1] = oi_change
        flow_arr[:, 2] = ls_ratio

        # Flow RoC features (vectorized)
        if n > 5:
            flow_arr[5:, 3] = funding[5:] - funding[:-5]
            flow_arr[5:, 4] = ls_ratio[5:] - ls_ratio[:-5]
            flow_arr[5:, 5] = oi_change[5:] - oi_change[:-5]

        features = np.concatenate([features, flow_arr], axis=1)

    return features
