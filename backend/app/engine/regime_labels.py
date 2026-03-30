"""Retrospective regime label generation for classifier training."""

import numpy as np
import pandas as pd

# Class mapping: int → name (must match REGIMES in regime.py)
LABEL_MAP = {0: "trending", 1: "steady", 2: "volatile", 3: "ranging"}
NAME_TO_LABEL = {v: k for k, v in LABEL_MAP.items()}
DEFAULT_LABEL = NAME_TO_LABEL["ranging"]


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def generate_regime_labels(
    df: pd.DataFrame,
    horizon: int = 48,
) -> pd.Series:
    """Generate regime labels by looking forward `horizon` candles.

    For each candle, classifies the forward window as:
    - trending: directional move > 2x ATR with expanding or stable vol
    - steady: directional move > 1.5x ATR with contracting vol
    - volatile: ATR expands > 1.5x without sustained direction (> 1.5x ATR)
    - ranging: none of the above

    Args:
        df: OHLCV DataFrame.
        horizon: Number of candles to look forward.

    Returns:
        pd.Series of integer labels (0=trending, 1=steady, 2=volatile, 3=ranging).
    """
    n = len(df)
    labels = np.full(n, DEFAULT_LABEL, dtype=np.int64)

    if n <= horizon:
        return pd.Series(labels, index=df.index)

    atr = _compute_atr(df).values
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    for i in range(n - horizon):
        window_close = close[i:i + horizon]
        window_high = high[i:i + horizon]
        window_low = low[i:i + horizon]
        current_atr = atr[i]
        if current_atr <= 0:
            continue

        # Directional move: net close change
        net_move = abs(window_close[-1] - window_close[0])

        # ATR expansion: compare window ATR to current
        window_tr = np.maximum(
            window_high - window_low,
            np.maximum(
                np.abs(window_high - np.roll(window_close, 1)),
                np.abs(window_low - np.roll(window_close, 1)),
            ),
        )
        window_tr[0] = window_high[0] - window_low[0]
        window_atr = window_tr.mean()
        atr_expansion = window_atr / current_atr

        is_directional = net_move > 1.5 * current_atr
        is_strongly_directional = net_move > 2.0 * current_atr
        vol_contracting = atr_expansion < 0.9

        if is_strongly_directional and not vol_contracting:
            labels[i] = NAME_TO_LABEL["trending"]
        elif is_directional and vol_contracting:
            labels[i] = NAME_TO_LABEL["steady"]
        elif atr_expansion > 1.5 and not is_directional:
            labels[i] = NAME_TO_LABEL["volatile"]
        # else: ranging (default)

    return pd.Series(labels, index=df.index)
