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

FLOW_FEATURES = [
    "funding_rate",
    "oi_change_pct",
    "long_short_ratio_norm",  # (ls_ratio - 1.0), centered at neutral
]

ALL_FEATURES = PRICE_FEATURES + INDICATOR_FEATURES + TEMPORAL_FEATURES
ALL_FEATURES_WITH_FLOW = ALL_FEATURES + FLOW_FEATURES


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
) -> np.ndarray:
    """Build normalized feature matrix from candle data.

    Args:
        candles: DataFrame with columns: open, high, low, close, volume.
                 Optionally 'timestamp' for temporal features.
        order_flow: Optional list of dicts (one per candle) with keys:
                    funding_rate, oi_change_pct, long_short_ratio.

    Returns:
        np.ndarray of shape (n_candles, n_features).
        First ~50 rows may contain NaN due to indicator warmup.
    """
    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)

    features = np.zeros((n, len(ALL_FEATURES)), dtype=np.float32)

    close = df["close"].astype(float)
    opn = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)

    hl_range = (high - low).replace(0, np.nan)

    # Price features
    features[:, 0] = close.pct_change().fillna(0).values                         # ret
    features[:, 1] = ((close - opn) / hl_range).fillna(0).values                 # body_ratio
    features[:, 2] = ((high - np.maximum(opn, close)) / hl_range).fillna(0).values  # upper_wick
    features[:, 3] = ((np.minimum(opn, close) - low) / hl_range).fillna(0).values   # lower_wick

    vol_mean = vol.rolling(20, min_periods=1).mean()
    vol_std = vol.rolling(20, min_periods=1).std().replace(0, 1)
    features[:, 4] = ((vol - vol_mean) / vol_std).fillna(0).values               # volume_zscore

    # Indicators
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
    macd_hist = (ema12 - ema26) - _ema(ema12 - ema26, 9)
    features[:, 9] = (macd_hist / close * 10000).fillna(0).values                # macd_norm

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    features[:, 10] = ((close - bb_lower) / bb_range).fillna(0).values           # bb_position
    features[:, 11] = ((bb_upper - bb_lower) / close).fillna(0).values           # bb_width
    features[:, 12] = (atr / close).fillna(0).values                             # atr_pct

    # Temporal features (if timestamp available)
    if "timestamp" in df.columns:
        try:
            ts = pd.to_datetime(df["timestamp"])
            hours = ts.dt.hour + ts.dt.minute / 60
            features[:, 13] = np.sin(2 * np.pi * hours / 24).values              # hour_sin
            features[:, 14] = np.cos(2 * np.pi * hours / 24).values              # hour_cos
        except Exception:
            pass  # leave as zeros

    # Clip extreme values
    features = np.clip(features, -10, 10)

    # Order flow features
    if order_flow is not None and len(order_flow) == n:
        flow_arr = np.zeros((n, len(FLOW_FEATURES)), dtype=np.float32)
        for i, f in enumerate(order_flow):
            flow_arr[i, 0] = f.get("funding_rate", 0) * 10000  # scale up
            flow_arr[i, 1] = f.get("oi_change_pct", 0) * 100   # to percent
            flow_arr[i, 2] = f.get("long_short_ratio", 1.0) - 1.0  # center at 0
        flow_arr = np.clip(flow_arr, -10, 10)
        features = np.concatenate([features, flow_arr], axis=1)

    return features
