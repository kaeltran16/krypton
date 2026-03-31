import os
import tempfile

import numpy as np
import torch
import pytest

from app.ml.drift import DriftConfig
from app.ml.model import SignalLSTM
from app.ml.predictor import Predictor
from tests.ml.conftest import make_drift_stats


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


class TestDriftPenalty:

    def test_no_drift_stats_no_penalty(self):
        """Old checkpoints without drift_stats should work unchanged."""
        path = _save_model(input_size=15)
        predictor = Predictor(path)
        features = np.random.randn(50, 15).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
        assert result.get("drift_penalty", 0.0) == 0.0

    def test_drift_penalty_reduces_confidence(self):
        """When drift stats indicate severe drift, confidence should decrease."""
        rng = np.random.default_rng(42)
        input_size = 15

        training_data = rng.standard_normal((500, input_size)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, [0, 1, 2, 3, 4])

        path = _save_model(input_size=input_size, extra_config={"drift_stats": drift_stats})
        drifted_features = (rng.standard_normal((50, input_size)) * 5 + 3).astype(np.float32)

        pred_with_penalty = Predictor(path)
        result_with = pred_with_penalty.predict(drifted_features)

        no_penalty_config = DriftConfig(psi_moderate=10.0, psi_severe=20.0)
        pred_no_penalty = Predictor(path, drift_config=no_penalty_config)
        result_without = pred_no_penalty.predict(drifted_features)

        assert result_with["drift_penalty"] > 0
        if result_without["confidence"] > 0:
            assert result_with["confidence"] <= result_without["confidence"]

    def test_drift_penalty_in_result(self):
        """predict() should include drift_penalty in result."""
        path = _save_model(input_size=15)
        predictor = Predictor(path)
        features = np.random.randn(50, 15).astype(np.float32)
        result = predictor.predict(features)
        assert "drift_penalty" in result

    def test_custom_drift_thresholds(self):
        """Predictor should accept drift threshold overrides."""
        rng = np.random.default_rng(42)
        input_size = 15

        training_data = rng.standard_normal((500, input_size)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, [0, 1, 2, 3, 4])

        path = _save_model(input_size=input_size, extra_config={"drift_stats": drift_stats})

        predictor = Predictor(
            path,
            drift_config=DriftConfig(psi_moderate=10.0, psi_severe=20.0),
        )
        drifted_features = (rng.standard_normal((50, input_size)) * 5 + 3).astype(np.float32)
        result = predictor.predict(drifted_features)
        assert result["drift_penalty"] == 0.0
