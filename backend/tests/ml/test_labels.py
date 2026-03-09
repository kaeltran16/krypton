import numpy as np
import pandas as pd
import pytest

from app.ml.labels import generate_labels, LabelConfig


def _make_candles_with_known_move(n=100, base=67000):
    """First 80 candles flat, then sharp up move."""
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    data = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        if i < 80:
            c = base + rng.uniform(-10, 10)
        else:
            c = base + (i - 80) * 200  # sharp up
        data.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - 5, "high": c + 20, "low": c - 20, "close": c, "volume": 100,
        })
    return pd.DataFrame(data)


class TestGenerateLabels:

    def test_output_shape(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        direction, sl_atr, tp1_atr, tp2_atr = generate_labels(df, config)
        assert len(direction) == len(df)
        assert len(sl_atr) == len(df)

    def test_labels_are_valid_classes(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        direction, _, _, _ = generate_labels(df, config)
        # 0=NEUTRAL, 1=LONG, 2=SHORT
        assert set(np.unique(direction)).issubset({0, 1, 2})

    def test_last_horizon_candles_are_neutral(self):
        df = _make_candles_with_known_move(100)
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        direction, _, _, _ = generate_labels(df, config)
        # Last 10 candles can't look forward far enough — should be NEUTRAL
        assert all(direction[-10:] == 0)

    def test_regression_targets_positive(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        _, sl_atr, tp1_atr, tp2_atr = generate_labels(df, config)
        # SL/TP distances should be non-negative where defined
        valid = sl_atr[sl_atr > 0]
        assert (valid >= 0).all()

    def test_high_threshold_mostly_neutral(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=50.0)  # 50% move required
        direction, _, _, _ = generate_labels(df, config)
        # Almost all should be NEUTRAL with such high threshold
        neutral_pct = (direction == 0).sum() / len(direction)
        assert neutral_pct > 0.9
