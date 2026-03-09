import torch
import pytest

from app.ml.model import SignalLSTM


class TestSignalLSTM:

    @pytest.fixture
    def model(self):
        return SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)

    def test_forward_output_shapes(self, model):
        batch = torch.randn(8, 50, 15)  # (batch, seq_len, features)
        dir_logits, reg_out = model(batch)
        assert dir_logits.shape == (8, 3)   # 3 classes
        assert reg_out.shape == (8, 3)      # sl, tp1, tp2

    def test_direction_logits_sum_to_one_after_softmax(self, model):
        batch = torch.randn(4, 50, 15)
        dir_logits, _ = model(batch)
        probs = torch.softmax(dir_logits, dim=1)
        sums = probs.sum(dim=1)
        assert torch.allclose(sums, torch.ones(4), atol=1e-5)

    def test_regression_outputs_positive(self, model):
        batch = torch.randn(4, 50, 15)
        _, reg_out = model(batch)
        # ReLU ensures non-negative SL/TP distances
        assert (reg_out >= 0).all()

    def test_different_input_sizes(self):
        model = SignalLSTM(input_size=18, hidden_size=128, num_layers=1)
        batch = torch.randn(2, 30, 18)
        dir_logits, reg_out = model(batch)
        assert dir_logits.shape == (2, 3)
        assert reg_out.shape == (2, 3)
