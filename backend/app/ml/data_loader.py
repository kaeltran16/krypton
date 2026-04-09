"""Data loading and preparation for ML training."""

import numpy as np
import pandas as pd

from app.ml.features import (
    build_feature_matrix, WARMUP_ROWS, drop_warmup_rows,
    compute_standardization_stats, apply_standardization,
)
from app.ml.labels import generate_targets, TargetConfig


def prepare_training_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    target_config: TargetConfig | None = None,
    btc_candles: list[dict] | None = None,
    regime: list[dict] | None = None,
    trend_conviction: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    """Prepare features and regression targets for training.

    Returns:
        Tuple of (features, forward_return, sl_atr, tp1_atr, tp2_atr, valid, std_stats).
        Features are warmup-trimmed, winsorized, and z-score standardized.
    """
    df = pd.DataFrame(candles)
    btc_df = pd.DataFrame(btc_candles) if btc_candles else None

    features = build_feature_matrix(
        df, order_flow=order_flow, regime=regime,
        trend_conviction=trend_conviction, btc_candles=btc_df,
    )

    fwd, sl, tp1, tp2, valid = generate_targets(df, target_config)

    features, offset = drop_warmup_rows(features, WARMUP_ROWS)
    fwd = fwd[offset:]
    sl = sl[offset:]
    tp1 = tp1[offset:]
    tp2 = tp2[offset:]
    valid = valid[offset:]

    # Z-score standardize
    std_stats = compute_standardization_stats(features)
    features = apply_standardization(features, std_stats)

    return features, fwd, sl, tp1, tp2, valid, std_stats
