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

    def test_input_batchnorm_exists(self, model):
        assert hasattr(model, 'input_bn'), "Model should have input BatchNorm layer"

    def test_batchnorm_normalizes_input(self, model):
        # Large-scale input should still produce reasonable outputs
        batch = torch.randn(8, 50, 15) * 100  # large scale
        model_large = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)
        dir_logits, reg_out = model_large(batch)
        assert dir_logits.shape == (8, 3)
        assert reg_out.shape == (8, 3)
        assert not torch.isnan(dir_logits).any()
        assert not torch.isnan(reg_out).any()

    def test_multiscale_pooling(self):
        model = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)
        batch = torch.randn(4, 50, 15)
        dir_logits, reg_out = model(batch)
        # Output shapes should be unchanged
        assert dir_logits.shape == (4, 3)
        assert reg_out.shape == (4, 3)
        # Model should have the multi-scale projection layer
        assert hasattr(model, 'scale_proj'), "Model should have multi-scale projection"

    def test_multiscale_pooling_short_sequence(self):
        """Multi-scale pooling should handle sequences shorter than all pool windows."""
        model = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)
        batch = torch.randn(4, 3, 15)  # seq_len=3, shorter than all pool windows (5/10/25)
        dir_logits, reg_out = model(batch)
        assert dir_logits.shape == (4, 3)
        assert reg_out.shape == (4, 3)
        assert not torch.isnan(dir_logits).any()

    def test_different_input_sizes(self):
        model = SignalLSTM(input_size=18, hidden_size=128, num_layers=1)
        batch = torch.randn(2, 30, 18)
        dir_logits, reg_out = model(batch)
        assert dir_logits.shape == (2, 3)
        assert reg_out.shape == (2, 3)
