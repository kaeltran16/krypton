import numpy as np
import torch
import pytest

from app.ml.dataset import CandleDataset


class TestCandleDataset:

    @pytest.fixture
    def sample_data(self):
        n = 200
        n_features = 15
        features = np.random.randn(n, n_features).astype(np.float32)
        direction = np.random.randint(0, 3, size=n).astype(np.int64)
        sl = np.random.uniform(0.5, 3.0, size=n).astype(np.float32)
        tp1 = np.random.uniform(1.0, 4.0, size=n).astype(np.float32)
        tp2 = np.random.uniform(2.0, 6.0, size=n).astype(np.float32)
        return features, direction, sl, tp1, tp2

    def test_length(self, sample_data):
        features, direction, sl, tp1, tp2 = sample_data
        ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=50)
        # Should have n - seq_len valid sequences
        assert len(ds) == 200 - 50

    def test_item_shapes(self, sample_data):
        features, direction, sl, tp1, tp2 = sample_data
        ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=50)
        x, y_dir, y_reg = ds[0]
        assert x.shape == (50, features.shape[1])
        assert y_dir.shape == ()  # scalar
        assert y_reg.shape == (3,)  # sl, tp1, tp2

    def test_item_types(self, sample_data):
        features, direction, sl, tp1, tp2 = sample_data
        ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=50)
        x, y_dir, y_reg = ds[0]
        assert x.dtype == torch.float32
        assert y_dir.dtype == torch.long
        assert y_reg.dtype == torch.float32
