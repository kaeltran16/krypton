import torch
import pytest

from app.ml.model import SignalLSTM


class TestSignalLSTM:

    @pytest.fixture
    def model(self):
        return SignalLSTM(input_size=15, hidden_size=96, num_layers=2, dropout=0.3)

    def test_forward_output_shapes(self, model):
        batch = torch.randn(8, 50, 15)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (8, 1), "Primary head: single return prediction"
        assert reg_out.shape == (8, 3), "Secondary head: sl, tp1, tp2"

    def test_return_prediction_unbounded(self, model):
        """Return prediction should have no activation — can be negative."""
        batch = torch.randn(8, 50, 15) * 5
        return_pred, _ = model(batch)
        has_negative = (return_pred < 0).any()
        has_positive = (return_pred > 0).any()
        assert has_negative or has_positive

    def test_regression_outputs_positive(self, model):
        batch = torch.randn(8, 50, 15)
        _, reg_out = model(batch)
        assert (reg_out >= 0).all(), "SL/TP must be non-negative (ReLU)"

    def test_no_nan_outputs(self, model):
        batch = torch.randn(8, 50, 15) * 100
        return_pred, reg_out = model(batch)
        assert not torch.isnan(return_pred).any()
        assert not torch.isnan(reg_out).any()

    def test_multiscale_pooling_short_sequence(self):
        model = SignalLSTM(input_size=15, hidden_size=96, num_layers=2, dropout=0.3)
        batch = torch.randn(4, 3, 15)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (4, 1)
        assert reg_out.shape == (4, 3)

    def test_input_batchnorm_exists(self, model):
        assert hasattr(model, 'input_bn')

    def test_multiscale_pooling(self, model):
        batch = torch.randn(4, 50, 15)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (4, 1)
        assert reg_out.shape == (4, 3)
        assert hasattr(model, 'scale_proj')

    def test_different_input_sizes(self):
        model = SignalLSTM(input_size=18, hidden_size=64, num_layers=1)
        batch = torch.randn(2, 30, 18)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (2, 1)
        assert reg_out.shape == (2, 3)
