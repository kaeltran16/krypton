import numpy as np
import torch
import pytest

from app.ml.dataset import CandleDataset


class TestCandleDataset:

    @pytest.fixture
    def sample_data(self):
        n = 300
        n_features = 24
        features = np.random.randn(n, n_features).astype(np.float32)
        forward_return = np.random.randn(n).astype(np.float32)
        sl = np.random.uniform(0.5, 3.0, size=n).astype(np.float32)
        tp1 = np.random.uniform(1.0, 4.0, size=n).astype(np.float32)
        tp2 = np.random.uniform(2.0, 6.0, size=n).astype(np.float32)
        valid = np.ones(n, dtype=bool)
        valid[:10] = False
        valid[-5:] = False
        return features, forward_return, sl, tp1, tp2, valid

    def test_length_excludes_invalid(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        assert len(ds) > 0
        assert len(ds) < 300 - 50

    def test_item_shapes(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        x, y_return, y_reg = ds[0]
        assert x.shape == (50, features.shape[1])
        assert y_return.shape == ()
        assert y_reg.shape == (3,)

    def test_item_types(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        x, y_return, y_reg = ds[0]
        assert x.dtype == torch.float32
        assert y_return.dtype == torch.float32
        assert y_reg.dtype == torch.float32

    def test_noise_augmentation(self):
        n, nf = 200, 15
        features = np.ones((n, nf), dtype=np.float32)
        fwd = np.zeros(n, dtype=np.float32)
        sl = tp1 = tp2 = np.zeros(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10, noise_std=0.01)
        x, _, _ = ds[0]
        assert not torch.allclose(x, torch.ones_like(x))
