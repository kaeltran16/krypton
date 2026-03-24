"""Data loading and preparation for ML training."""

import numpy as np
import pandas as pd

from app.ml.features import build_feature_matrix
from app.ml.labels import generate_labels, LabelConfig


def prepare_training_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    label_config: LabelConfig | None = None,
    btc_candles: list[dict] | None = None,
    regime: list[dict] | None = None,
    trend_conviction: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert raw candle data into features and labels for training.

    Args:
        candles: List of candle dicts with timestamp, open, high, low, close, volume.
        order_flow: Optional list of order flow dicts (one per candle).
        label_config: Label generation config.
        btc_candles: Optional list of BTC candle dicts for inter-pair features.
        regime: Optional list of regime dicts (one per candle).
        trend_conviction: Optional list of trend conviction floats (one per candle).

    Returns:
        Tuple of (features, direction, sl_atr, tp1_atr, tp2_atr).
    """
    df = pd.DataFrame(candles)
    btc_df = pd.DataFrame(btc_candles) if btc_candles else None
    features = build_feature_matrix(
        df,
        order_flow=order_flow,
        regime=regime,
        trend_conviction=trend_conviction,
        btc_candles=btc_df,
    )
    direction, sl_atr, tp1_atr, tp2_atr = generate_labels(df, label_config)
    return features, direction, sl_atr, tp1_atr, tp2_atr
