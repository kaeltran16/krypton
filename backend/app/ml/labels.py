"""Label generation for ML training — fixed % threshold method."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


# Direction classes
NEUTRAL = 0
LONG = 1
SHORT = 2


@dataclass
class LabelConfig:
    horizon: int = 24       # candles to look forward
    threshold_pct: float = 1.5  # minimum % move for non-neutral label


def generate_labels(
    candles: pd.DataFrame,
    config: LabelConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate direction labels and SL/TP regression targets.

    Args:
        candles: DataFrame with open, high, low, close columns.
        config: Label generation parameters.

    Returns:
        Tuple of (direction, sl_atr, tp1_atr, tp2_atr), each np.ndarray of length n.
        direction: 0=NEUTRAL, 1=LONG, 2=SHORT.
        sl_atr, tp1_atr, tp2_atr: optimal distances in ATR units (0 for NEUTRAL).
    """
    if config is None:
        config = LabelConfig()

    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)

    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values

    # Compute ATR for normalizing SL/TP distances
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    atr_safe = np.where(atr > 0, atr, 1.0)

    direction = np.zeros(n, dtype=np.int64)
    sl_atr = np.zeros(n, dtype=np.float32)
    tp1_atr = np.zeros(n, dtype=np.float32)
    tp2_atr = np.zeros(n, dtype=np.float32)

    threshold = config.threshold_pct / 100.0

    for i in range(n - config.horizon):
        future_high = high[i + 1 : i + 1 + config.horizon]
        future_low = low[i + 1 : i + 1 + config.horizon]
        future_close = close[i + 1 : i + 1 + config.horizon]

        price = close[i]
        if price <= 0:
            continue

        max_up = (future_high.max() - price) / price    # max favorable for LONG
        max_down = (price - future_low.min()) / price    # max favorable for SHORT

        if max_up >= threshold and max_up > max_down:
            direction[i] = LONG

            # MFE/MAE for LONG
            cum_max = np.maximum.accumulate(future_high)
            cum_min = np.minimum.accumulate(future_low)
            mae = (price - cum_min.min()) / atr_safe[i]  # worst drawdown
            mfe_median = np.median((future_high - price)) / atr_safe[i]
            mfe_75 = np.percentile((future_high - price), 75) / atr_safe[i]

            sl_atr[i] = max(mae, 0.5)  # minimum 0.5 ATR SL
            tp1_atr[i] = max(mfe_median, 0.5)
            tp2_atr[i] = max(mfe_75, 1.0)

        elif max_down >= threshold and max_down > max_up:
            direction[i] = SHORT

            # MFE/MAE for SHORT
            cum_min = np.minimum.accumulate(future_low)
            cum_max = np.maximum.accumulate(future_high)
            mae = (cum_max.max() - price) / atr_safe[i]
            mfe_median = np.median((price - future_low)) / atr_safe[i]
            mfe_75 = np.percentile((price - future_low), 75) / atr_safe[i]

            sl_atr[i] = max(mae, 0.5)
            tp1_atr[i] = max(mfe_median, 0.5)
            tp2_atr[i] = max(mfe_75, 1.0)

    return direction, sl_atr, tp1_atr, tp2_atr
