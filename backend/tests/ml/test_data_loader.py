import numpy as np
import pytest

from app.ml.data_loader import prepare_training_data


class TestPrepareTrainingData:

    def test_returns_expected_arrays(self):
        """Test with synthetic candle list."""
        candles = []
        for i in range(200):
            candles.append({
                "timestamp": f"2025-01-01T{i:02d}:00:00+00:00",
                "open": 67000 + i * 10,
                "high": 67000 + i * 10 + 50,
                "low": 67000 + i * 10 - 30,
                "close": 67000 + i * 10 + 20,
                "volume": 100 + i,
            })

        features, direction, sl, tp1, tp2 = prepare_training_data(candles)

        assert features.shape[0] == 200
        assert features.shape[1] >= 15
        assert len(direction) == 200
        assert len(sl) == 200
        assert features.dtype == np.float32

    def test_with_order_flow(self):
        candles = []
        flow_snapshots = []
        for i in range(200):
            candles.append({
                "timestamp": f"2025-01-01T{i:02d}:00:00+00:00",
                "open": 67000 + i * 10,
                "high": 67000 + i * 10 + 50,
                "low": 67000 + i * 10 - 30,
                "close": 67000 + i * 10 + 20,
                "volume": 100 + i,
            })
            flow_snapshots.append({
                "funding_rate": 0.0001,
                "oi_change_pct": 0.02,
                "long_short_ratio": 1.3,
            })

        features, direction, sl, tp1, tp2 = prepare_training_data(
            candles, order_flow=flow_snapshots
        )

        # Should have 3 extra features for order flow
        features_no_flow, _, _, _, _ = prepare_training_data(candles)
        assert features.shape[1] == features_no_flow.shape[1] + 3
