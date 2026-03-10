import os
import tempfile

import numpy as np
import torch
import pytest

from app.ml.model import SignalLSTM
from app.ml.predictor import Predictor


class TestPredictor:

    @pytest.fixture
    def saved_model(self):
        """Save a dummy model checkpoint and return path."""
        import json
        tmpdir = tempfile.mkdtemp()
        model = SignalLSTM(input_size=15, hidden_size=32, num_layers=1, dropout=0.0)
        path = os.path.join(tmpdir, "best_model.pt")
        torch.save(model.state_dict(), path)
        config_path = os.path.join(tmpdir, "model_config.json")
        with open(config_path, "w") as f:
            json.dump({
                "input_size": 15,
                "hidden_size": 32,
                "num_layers": 1,
                "dropout": 0.0,
                "seq_len": 50,
                "epoch": 1,
                "val_loss": 0.5,
            }, f)
        return path

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
        import json
        import tempfile
        model_dir = tempfile.mkdtemp()
        model = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.3)
        model_path = os.path.join(model_dir, "best_model.pt")
        torch.save(model.state_dict(), model_path)
        config = {
            "input_size": 15, "hidden_size": 64, "num_layers": 2,
            "dropout": 0.3, "seq_len": 50, "epoch": 1, "val_loss": 1.0,
        }
        with open(os.path.join(model_dir, "model_config.json"), "w") as f:
            json.dump(config, f)

        predictor = Predictor(model_path)
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
