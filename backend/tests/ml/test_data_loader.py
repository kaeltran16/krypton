import numpy as np
import pytest

from app.ml.data_loader import prepare_training_data
from app.ml.labels import TargetConfig


def _make_candle_dicts(n=500, base=67000):
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        noise = rng.uniform(-50, 50)
        trend = 20 * np.sin(2 * np.pi * i / 100)
        c = base + trend + noise
        spread = rng.uniform(10, 40)
        candles.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - rng.uniform(1, 10), "high": c + spread,
            "low": c - spread, "close": c, "volume": 80 + rng.uniform(0, 40),
        })
    return candles


class TestPrepareTrainingData:

    def test_returns_expected_tuple(self):
        candles = _make_candle_dicts(500)
        result = prepare_training_data(candles)
        features, fwd, sl, tp1, tp2, valid, std_stats = result
        assert features.shape[0] == fwd.shape[0]
        assert isinstance(std_stats, dict)
        assert "mean" in std_stats

    def test_warmup_rows_removed(self):
        candles = _make_candle_dicts(500)
        result = prepare_training_data(candles)
        features, fwd, sl, tp1, tp2, valid, std_stats = result
        assert features.shape[0] == 300  # 500 - 200

    def test_features_are_standardized(self):
        candles = _make_candle_dicts(500)
        result = prepare_training_data(candles)
        features = result[0]
        for col in range(min(5, features.shape[1])):
            assert abs(features[:, col].mean()) < 0.1
