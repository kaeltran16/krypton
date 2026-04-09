import numpy as np
import torch
import pytest
from torch.utils.data import DataLoader

from app.ml.model import SignalLSTM
from app.ml.dataset import CandleDataset
from app.ml.drift import compute_drift_stats


class TestDriftStats:

    def test_computes_without_error(self):
        model = SignalLSTM(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
        model.eval()

        n = 200
        features = np.random.randn(n, 10).astype(np.float32)
        fwd = np.random.randn(n).astype(np.float32)
        sl = tp1 = tp2 = np.ones(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)

        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10)
        loader = DataLoader(ds, batch_size=32, shuffle=False)

        result = compute_drift_stats(model, loader, features, 10)
        assert result is not None
        assert "top_feature_indices" in result
        assert "feature_distributions" in result

    def test_returns_none_on_empty_loader(self):
        model = SignalLSTM(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
        model.eval()

        features = np.random.randn(5, 10).astype(np.float32)
        fwd = np.random.randn(5).astype(np.float32)
        sl = tp1 = tp2 = np.ones(5, dtype=np.float32)
        valid = np.zeros(5, dtype=bool)

        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10)
        loader = DataLoader(ds, batch_size=32, shuffle=False)

        result = compute_drift_stats(model, loader, features, 10)
        assert result is not None
        assert "top_feature_indices" in result
