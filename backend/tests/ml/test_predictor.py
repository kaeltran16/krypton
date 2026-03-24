import os
import tempfile

import numpy as np
import torch
import pytest

from app.ml.model import SignalLSTM
from app.ml.predictor import Predictor


def _save_model(input_size=15, hidden_size=32, num_layers=1, dropout=0.0,
                seq_len=50, extra_config=None):
    """Save a dummy model checkpoint and return path."""
    import json
    tmpdir = tempfile.mkdtemp()
    model = SignalLSTM(
        input_size=input_size, hidden_size=hidden_size,
        num_layers=num_layers, dropout=dropout,
    )
    path = os.path.join(tmpdir, "best_model.pt")
    torch.save(model.state_dict(), path)
    config = {
        "input_size": input_size,
        "hidden_size": hidden_size,
        "num_layers": num_layers,
        "dropout": dropout,
        "seq_len": seq_len,
        "epoch": 1,
        "val_loss": 0.5,
    }
    if extra_config:
        config.update(extra_config)
    with open(os.path.join(tmpdir, "model_config.json"), "w") as f:
        json.dump(config, f)
    return path


class TestPredictor:

    @pytest.fixture
    def saved_model(self):
        return _save_model()

    def test_load_model(self, saved_model):
        predictor = Predictor(saved_model)
        assert predictor.model is not None
        assert predictor.seq_len == 50

    def test_predict_returns_valid_output(self, saved_model):
        predictor = Predictor(saved_model)
        features = np.random.randn(50, 15).astype(np.float32)
        result = predictor.predict(features)

        assert "direction" in result
        assert "confidence" in result
        assert "sl_atr" in result
        assert "tp1_atr" in result
        assert "tp2_atr" in result
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
        assert 0 <= result["confidence"] <= 1

    def test_predictor_loads_new_architecture(self):
        """Predictor should load a model trained with BatchNorm + multi-scale pooling."""
        path = _save_model(input_size=15, hidden_size=64, num_layers=2, dropout=0.3)
        predictor = Predictor(path)
        features = np.random.randn(50, 15).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] in ("NEUTRAL", "LONG", "SHORT")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_predict_too_few_candles_returns_neutral(self, saved_model):
        predictor = Predictor(saved_model)
        features = np.random.randn(10, 15).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] == "NEUTRAL"
        assert result["confidence"] == 0.0


class TestStaleModelDetection:

    def test_input_size_18_is_stale(self):
        """input_size=18 (pre-expansion layout) sets _stale=True."""
        path = _save_model(input_size=18)
        predictor = Predictor(path)
        assert predictor._stale is True

    def test_input_size_16_is_stale(self):
        path = _save_model(input_size=16)
        predictor = Predictor(path)
        assert predictor._stale is True

    def test_input_size_23_is_stale(self):
        path = _save_model(input_size=23)
        predictor = Predictor(path)
        assert predictor._stale is True

    def test_stale_predict_returns_neutral(self):
        """Stale model predict() returns NEUTRAL immediately."""
        path = _save_model(input_size=18)
        predictor = Predictor(path)
        features = np.random.randn(50, 18).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] == "NEUTRAL"
        assert result["confidence"] == 0.0

    def test_input_size_15_not_stale(self):
        path = _save_model(input_size=15)
        predictor = Predictor(path)
        assert predictor._stale is False

    def test_input_size_24_not_stale(self):
        path = _save_model(input_size=24)
        predictor = Predictor(path)
        assert predictor._stale is False


class TestFeatureTruncation:

    def test_truncation_to_15(self):
        """36-column matrix truncated to first 15 for input_size=15 model."""
        path = _save_model(input_size=15)
        predictor = Predictor(path)
        features = np.random.randn(50, 36).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")

    def test_truncation_to_24(self):
        """36-column matrix truncated to 24 for input_size=24 model."""
        path = _save_model(input_size=24)
        predictor = Predictor(path)
        features = np.random.randn(50, 36).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")

    def test_exact_match_no_truncation(self):
        """Feature count matches input_size exactly — no truncation needed."""
        path = _save_model(input_size=24)
        predictor = Predictor(path)
        features = np.random.randn(50, 24).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")


class TestConfigFlags:

    def test_regime_used_flag(self):
        path = _save_model(input_size=28, extra_config={"regime_used": True})
        predictor = Predictor(path)
        assert predictor.regime_used is True

    def test_btc_used_flag(self):
        path = _save_model(input_size=26, extra_config={"btc_used": True})
        predictor = Predictor(path)
        assert predictor.btc_used is True

    def test_flow_used_flag(self):
        path = _save_model(input_size=30, extra_config={"flow_used": True})
        predictor = Predictor(path)
        assert predictor.flow_used is True

    def test_defaults_to_false(self):
        path = _save_model(input_size=24)
        predictor = Predictor(path)
        assert predictor.regime_used is False
        assert predictor.btc_used is False
        assert predictor.flow_used is False
