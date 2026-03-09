import numpy as np
import pandas as pd
import pytest

from app.ml.features import build_feature_matrix


def _make_candles(n=60, base=67000, trend=10):
    data = []
    for i in range(n):
        o = base + i * trend
        h = o + 50
        l = o - 30
        c = o + 20
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": 100 + i})
    return pd.DataFrame(data)


class TestBuildFeatureMatrix:

    def test_output_shape(self):
        df = _make_candles(100)
        features = build_feature_matrix(df)
        # Should have rows for each candle and multiple feature columns
        assert features.shape[0] == 100
        assert features.shape[1] >= 15  # at least 15 features per candle

    def test_no_nan_after_warmup(self):
        df = _make_candles(100)
        features = build_feature_matrix(df)
        # First 50 rows may have NaN from indicator warmup; after that, none
        assert not np.any(np.isnan(features[50:]))

    def test_values_are_normalized(self):
        df = _make_candles(100)
        features = build_feature_matrix(df)
        # After warmup, values should be roughly in [-5, 5] range (z-scored)
        valid = features[50:]
        assert np.abs(valid).max() < 20  # no extreme outliers

    def test_includes_order_flow_columns(self):
        df = _make_candles(60)
        flow = [{"funding_rate": 0.0001, "oi_change_pct": 0.02, "long_short_ratio": 1.3}] * 60
        features = build_feature_matrix(df, order_flow=flow)
        # Should have 3 more columns than without flow
        features_no_flow = build_feature_matrix(df)
        assert features.shape[1] == features_no_flow.shape[1] + 3
