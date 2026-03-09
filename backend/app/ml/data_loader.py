"""Data loading and preparation for ML training."""

import numpy as np
import pandas as pd

from app.ml.features import build_feature_matrix
from app.ml.labels import generate_labels, LabelConfig


def prepare_training_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    label_config: LabelConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert raw candle data into features and labels for training.

    Args:
        candles: List of candle dicts with timestamp, open, high, low, close, volume.
        order_flow: Optional list of order flow dicts (one per candle).
        label_config: Label generation config.

    Returns:
        Tuple of (features, direction, sl_atr, tp1_atr, tp2_atr).
    """
    df = pd.DataFrame(candles)
    features = build_feature_matrix(df, order_flow=order_flow)
    direction, sl_atr, tp1_atr, tp2_atr = generate_labels(df, label_config)
    return features, direction, sl_atr, tp1_atr, tp2_atr
