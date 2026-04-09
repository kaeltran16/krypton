"""Label generation for ML training — ATR-normalized forward returns."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TargetConfig:
    horizon: int = 48          # candles to look forward (48 for 15m = 12h)
    noise_floor: float = 0.3   # minimum |fwd_return| in ATR units for SL/TP training
    atr_epsilon: float = 1e-6  # minimum atr_pct to avoid division by zero


def generate_targets(
    candles: pd.DataFrame,
    config: TargetConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate ATR-normalized forward return and SL/TP regression targets.

    Returns:
        Tuple of (forward_return, sl_atr, tp1_atr, tp2_atr, valid_mask).
        forward_return: ATR-normalized return over horizon (float32).
        sl_atr, tp1_atr, tp2_atr: ATR-unit distances (0 for noise-floor samples).
        valid_mask: bool array — False for warmup, end-of-series, and zero-ATR rows.
    """
    if config is None:
        config = TargetConfig()

    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)

    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values

    # Compute ATR
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    atr_pct = atr / np.where(close > 0, close, 1.0)

    sl_atr = np.zeros(n, dtype=np.float32)
    tp1_atr = np.zeros(n, dtype=np.float32)
    tp2_atr = np.zeros(n, dtype=np.float32)

    # Vectorized forward return and valid mask
    h = config.horizon
    forward_return = np.zeros(n, dtype=np.float32)
    valid = np.zeros(n, dtype=bool)

    usable = n - h
    if usable > 0:
        raw_ret = (close[h:h + usable] - close[:usable]) / np.where(close[:usable] > 0, close[:usable], 1.0)
        atr_ok = atr_pct[:usable] >= config.atr_epsilon
        safe_atr_pct = np.where(atr_ok, atr_pct[:usable], 1.0)
        forward_return[:usable] = np.where(atr_ok, raw_ret / safe_atr_pct, 0.0)
        valid[:usable] = atr_ok

    # SL/TP requires per-row sliding windows — keep scalar loop for significant moves only
    significant = np.where(valid & (np.abs(forward_return) >= config.noise_floor))[0]
    for i in significant:
        future_high = high[i + 1 : i + 1 + h]
        future_low = low[i + 1 : i + 1 + h]
        atr_safe = max(atr[i], 1e-10)
        fwd = forward_return[i]

        if fwd > 0:
            mae = (close[i] - future_low.min()) / atr_safe
            mfe_median = np.median(future_high - close[i]) / atr_safe
            mfe_75 = np.percentile(future_high - close[i], 75) / atr_safe
        else:
            mae = (future_high.max() - close[i]) / atr_safe
            mfe_median = np.median(close[i] - future_low) / atr_safe
            mfe_75 = np.percentile(close[i] - future_low, 75) / atr_safe

        sl_atr[i] = max(mae, 0.5)
        tp1_atr[i] = max(mfe_median, 0.5)
        tp2_atr[i] = max(mfe_75, 1.0)

    return forward_return, sl_atr, tp1_atr, tp2_atr, valid
