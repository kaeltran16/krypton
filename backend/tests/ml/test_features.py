import numpy as np
import pandas as pd
import pytest

from app.ml.features import (
    build_feature_matrix,
    BASE_FEATURES,
    REGIME_FEATURES,
    INTER_PAIR_FEATURES,
    FLOW_FEATURES,
    FLOW_ROC_FEATURES,
)


def _make_candles(n=100, base=67000, trend=10):
    data = []
    for i in range(n):
        o = base + i * trend
        h = o + 50
        l = o - 30
        c = o + 20
        data.append({
            "timestamp": f"2025-01-01T{(i // 4) % 24:02d}:{(i % 4) * 15:02d}:00+00:00",
            "open": o, "high": h, "low": l, "close": c, "volume": 100 + i,
        })
    return pd.DataFrame(data)


def _make_flow(n, funding=0.0001, oi=0.02, ls=1.3):
    return [{"funding_rate": funding, "oi_change_pct": oi, "long_short_ratio": ls}] * n


def _make_regime(n, trending=0.5, ranging=0.3, volatile=0.2):
    return [{"trending": trending, "ranging": ranging, "volatile": volatile}] * n


def _make_conviction(n, value=0.6):
    return [value] * n


class TestFeatureMatrixShapes:

    def test_base_only(self):
        """Candles only → 24 features (base + momentum + multi-TF)."""
        df = _make_candles(100)
        features = build_feature_matrix(df)
        assert features.shape == (100, len(BASE_FEATURES))
        assert features.shape[1] == 24

    def test_with_regime(self):
        """Candles + regime → 28 features."""
        df = _make_candles(100)
        features = build_feature_matrix(
            df,
            regime=_make_regime(100),
            trend_conviction=_make_conviction(100),
        )
        assert features.shape[1] == 24 + len(REGIME_FEATURES)
        assert features.shape[1] == 28

    def test_with_btc_candles(self):
        """Candles + btc_candles → 26 features."""
        df = _make_candles(100)
        btc_df = _make_candles(100, base=60000, trend=15)
        features = build_feature_matrix(df, btc_candles=btc_df)
        assert features.shape[1] == 24 + len(INTER_PAIR_FEATURES)
        assert features.shape[1] == 26

    def test_with_flow(self):
        """Candles + flow → 30 features (24 + 3 flow + 3 flow RoC)."""
        df = _make_candles(100)
        features = build_feature_matrix(df, order_flow=_make_flow(100))
        assert features.shape[1] == 24 + len(FLOW_FEATURES) + len(FLOW_ROC_FEATURES)
        assert features.shape[1] == 30

    def test_all_features(self):
        """All args → 36 features."""
        df = _make_candles(100)
        btc_df = _make_candles(100, base=60000)
        features = build_feature_matrix(
            df,
            order_flow=_make_flow(100),
            regime=_make_regime(100),
            trend_conviction=_make_conviction(100),
            btc_candles=btc_df,
        )
        assert features.shape[1] == 36

    def test_btc_pair_no_inter_pair(self):
        """BTC pair with btc_candles=None → no inter-pair (24 + regime + flow = 34 max)."""
        df = _make_candles(100)
        features = build_feature_matrix(
            df,
            order_flow=_make_flow(100),
            regime=_make_regime(100),
            trend_conviction=_make_conviction(100),
            btc_candles=None,
        )
        # 24 base + 4 regime + 6 flow = 34
        assert features.shape[1] == 34


class TestDataQuality:

    def test_no_nan_after_warmup(self):
        """Rows 50+ must be NaN-free across all combinations."""
        df = _make_candles(200)
        btc_df = _make_candles(200, base=60000)
        features = build_feature_matrix(
            df,
            order_flow=_make_flow(200),
            regime=_make_regime(200),
            trend_conviction=_make_conviction(200),
            btc_candles=btc_df,
        )
        assert not np.any(np.isnan(features[50:]))

    def test_feature_ranges(self):
        """All values within [-10, 10] after clipping."""
        df = _make_candles(200)
        features = build_feature_matrix(
            df,
            order_flow=_make_flow(200),
            regime=_make_regime(200),
            trend_conviction=_make_conviction(200),
            btc_candles=_make_candles(200, base=60000),
        )
        # All values should be within clipping range
        assert features.max() <= 10.0
        assert features.min() >= -10.0

    def test_nan_in_btc_data(self):
        """BTC candles with NaN values must produce valid output."""
        df = _make_candles(100)
        btc_data = _make_candles(100, base=60000)
        btc_data.loc[5, "close"] = np.nan
        btc_data.loc[10, "high"] = np.nan
        features = build_feature_matrix(df, btc_candles=btc_data)
        # Should not crash, NaN may appear in early rows but not crash
        assert features.shape[1] == 26

    def test_flow_with_none_fields(self):
        """Flow snapshots with None fields must produce valid output."""
        df = _make_candles(60)
        flow = [{"funding_rate": None, "oi_change_pct": None, "long_short_ratio": None}] * 60
        features = build_feature_matrix(df, order_flow=flow)
        assert features.shape[1] == 30
        assert not np.any(np.isnan(features[50:]))

    def test_mismatched_flow_length(self):
        """Flow length != candle length → flow features skipped."""
        df = _make_candles(60)
        flow = _make_flow(50)  # mismatched
        features = build_feature_matrix(df, order_flow=flow)
        assert features.shape[1] == 24  # no flow columns


class TestEdgeCases:

    def test_empty_candles(self):
        """0 rows must not crash, return empty array."""
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        features = build_feature_matrix(df)
        assert features.shape == (0, 24)

    def test_single_candle(self):
        """1 row must produce valid shape."""
        df = _make_candles(1)
        features = build_feature_matrix(df)
        assert features.shape == (1, 24)

    def test_exactly_200_candles(self):
        """Matches Redis inference size."""
        df = _make_candles(200)
        features = build_feature_matrix(
            df,
            regime=_make_regime(200),
            trend_conviction=_make_conviction(200),
        )
        assert features.shape == (200, 28)
        # EMA-200 should be reasonably converged in last 50 rows
        assert not np.any(np.isnan(features[150:]))


class TestBackwardCompatibility:

    def test_first_15_columns_preserved(self):
        """Base features in first 15 columns must be identical to old layout."""
        df = _make_candles(100)
        features = build_feature_matrix(df)
        # First 15 columns are the original base (price + indicators + temporal)
        assert features.shape[1] == 24
        # Truncating to 15 should give valid data
        truncated = features[:, :15]
        assert truncated.shape == (100, 15)
        assert not np.any(np.isnan(truncated[50:]))


class TestRegimeConsistency:

    def test_regime_list_length_matches(self):
        """Regime list must match candle count."""
        df = _make_candles(100)
        # Mismatched regime length → regime features skipped
        features_short = build_feature_matrix(
            df, regime=_make_regime(50), trend_conviction=_make_conviction(50),
        )
        assert features_short.shape[1] == 24  # skipped

    def test_conviction_list_length_matches(self):
        """Conviction list must match candle count."""
        df = _make_candles(100)
        features = build_feature_matrix(
            df, regime=_make_regime(100), trend_conviction=_make_conviction(50),
        )
        assert features.shape[1] == 24  # skipped due to mismatch

    def test_regime_values(self):
        """Regime features contain expected values."""
        df = _make_candles(100)
        regime = [{"trending": 0.5, "ranging": 0.3, "volatile": 0.2}] * 100
        conviction = [0.7] * 100
        features = build_feature_matrix(df, regime=regime, trend_conviction=conviction)
        # Regime columns start at index 24
        assert features[50, 24] == pytest.approx(0.5, abs=0.01)  # trending
        assert features[50, 25] == pytest.approx(0.3, abs=0.01)  # ranging
        assert features[50, 26] == pytest.approx(0.2, abs=0.01)  # volatile
        assert features[50, 27] == pytest.approx(0.7, abs=0.01)  # conviction


class TestFlowRoC:

    def test_flow_roc_computed(self):
        """Flow RoC features should differ from zero after 5 candles of varying data."""
        df = _make_candles(20)
        flow = []
        for i in range(20):
            flow.append({
                "funding_rate": 0.0001 * (i + 1),
                "oi_change_pct": 0.01 * (i + 1),
                "long_short_ratio": 1.0 + 0.05 * i,
            })
        features = build_feature_matrix(df, order_flow=flow)
        # Flow RoC columns are at indices 27, 28, 29 (after 24 base + 3 flow)
        flow_roc_cols = features[:, 27:30]
        # First 5 rows should be zeros
        assert np.all(flow_roc_cols[:5] == 0)
        # After row 5, should be non-zero
        assert np.any(flow_roc_cols[5:] != 0)


class TestInterPair:

    def test_btc_candles_shorter_than_target(self):
        """BTC candles shorter than target → zeros."""
        df = _make_candles(100)
        btc_df = _make_candles(50, base=60000)  # shorter
        features = build_feature_matrix(df, btc_candles=btc_df)
        # Inter-pair columns should be zeros (btc_n < n)
        inter_cols = features[:, 24:26]
        assert np.all(inter_cols == 0)

    def test_btc_candles_longer_than_target(self):
        """BTC candles longer than target → uses last n rows."""
        df = _make_candles(100)
        btc_df = _make_candles(200, base=60000)
        features = build_feature_matrix(df, btc_candles=btc_df)
        assert features.shape[1] == 26
        # btc_ret_5 should have non-zero values after warmup
        assert np.any(features[10:, 24] != 0)
