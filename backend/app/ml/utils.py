"""Shared ML utilities used by both training (api/ml.py) and inference (main.py)."""

import math
from datetime import datetime

import numpy as np
import pandas as pd

from app.engine.scoring import sigmoid_scale
from app.engine.regime import compute_regime_mix
from app.engine.traditional import compute_trend_conviction

TF_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1D": 1440}


def geometric_balanced_accuracy(recalls: dict | list, epsilon: float = 1e-6) -> float:
    """Geometric mean of per-class recalls.

    Exponentially penalises near-zero recall on any class, preventing
    degenerate single-class-collapse models that arithmetic mean misses.
    """
    vals = list(recalls.values()) if isinstance(recalls, dict) else list(recalls)
    if not vals:
        return 0.0
    log_vals = [math.log(max(v, epsilon)) for v in vals]
    return math.exp(sum(log_vals) / len(log_vals))


def bucket_timestamp(ts: datetime, timeframe: str) -> datetime:
    """Bucket a timestamp to the nearest candle boundary for a given timeframe."""
    minutes = TF_MINUTES.get(timeframe, 60)
    ts = ts.replace(second=0, microsecond=0)
    if minutes >= 1440:
        return ts.replace(hour=0, minute=0)
    if minutes >= 60:
        hours = minutes // 60
        return ts.replace(minute=0, hour=(ts.hour // hours) * hours)
    return ts.replace(minute=(ts.minute // minutes) * minutes)


def compute_per_candle_regime(candles_df) -> tuple[list[dict], list[float]]:
    """Compute regime mix and trend conviction for each candle in the DataFrame."""
    df = candles_df.copy()
    df.columns = [c.lower() for c in df.columns]
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    n = len(df)

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

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
    atr14 = tr.rolling(14).mean()

    plus_di = 100 * plus_dm.rolling(14).mean() / atr14
    minus_di = 100 * minus_dm.rolling(14).mean() / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(14).mean()

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_width = 4 * std20

    # Pre-compute non-NaN BB width values once to avoid O(n^2) re-slicing
    bb_vals = bb_width.dropna().values
    bb_valid_indices = bb_width.dropna().index

    regime_list = []
    conviction_list = []

    for i in range(n):
        adx_val = float(adx.iloc[i]) if pd.notna(adx.iloc[i]) else 0.0
        di_p = float(plus_di.iloc[i]) if pd.notna(plus_di.iloc[i]) else 0.0
        di_m = float(minus_di.iloc[i]) if pd.notna(minus_di.iloc[i]) else 0.0

        # BB width percentile over last 50 valid values up to this candle
        valid_up_to = np.searchsorted(bb_valid_indices, i, side="right")
        if valid_up_to >= 50:
            recent = bb_vals[valid_up_to - 50:valid_up_to]
            bb_pct = float(np.sum(recent < recent[-1]) / len(recent) * 100)
        else:
            bb_pct = 50.0

        trend_strength = sigmoid_scale(adx_val, center=20, steepness=0.25)
        vol_expansion = sigmoid_scale(bb_pct, center=50, steepness=0.08)
        regime = compute_regime_mix(trend_strength, vol_expansion)
        regime_list.append(regime)

        tc = compute_trend_conviction(
            close=float(close.iloc[i]),
            ema_9=float(ema9.iloc[i]),
            ema_21=float(ema21.iloc[i]),
            ema_50=float(ema50.iloc[i]),
            adx=adx_val,
            di_direction=di_p - di_m,
        )
        conviction_list.append(tc["conviction"])

    return regime_list, conviction_list
