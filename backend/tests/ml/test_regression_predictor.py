import json
import numpy as np
import os
import pytest
import torch

from app.ml.model import SignalLSTM


class TestRegressionPredictor:

    @pytest.fixture
    def model_dir(self, tmp_path):
        """Create a minimal saved model for testing."""
        model = SignalLSTM(input_size=15, hidden_size=32, num_layers=1, dropout=0.1)
        torch.save(model.state_dict(), tmp_path / "best_model.pt")
        config = {
            "input_size": 15, "hidden_size": 32, "num_layers": 1,
            "dropout": 0.1, "seq_len": 20, "model_version": "v2",
            "feature_names": [f"f{i}" for i in range(15)],
        }
        with open(tmp_path / "model_config.json", "w") as f:
            json.dump(config, f)
        return str(tmp_path)

    def test_predict_returns_expected_keys(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert "ml_score" in result
        assert "confidence" in result
        assert "sl_atr" in result
        assert "direction" in result

    def test_ml_score_range(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert -100 <= result["ml_score"] <= 100

    def test_confidence_range(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_too_few_candles_returns_neutral(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(5, 15).astype(np.float32)
        result = pred.predict(features)
        assert result["confidence"] == 0.0


class TestRegressionEnsemblePredictor:

    @pytest.fixture
    def ensemble_dir(self, tmp_path):
        """Create a minimal 2-member ensemble."""
        for idx in range(2):
            model = SignalLSTM(input_size=15, hidden_size=32, num_layers=1, dropout=0.1)
            torch.save(model.state_dict(), tmp_path / f"ensemble_{idx}.pt")
        config = {
            "n_members": 2, "input_size": 15, "hidden_size": 32,
            "num_layers": 1, "dropout": 0.1, "seq_len": 20,
            "model_version": "v2",
            "feature_names": [f"f{i}" for i in range(15)],
            "members": [
                {"index": 0, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.5, "directional_accuracy": 0.55,
                 "prediction_std": 0.1, "excluded": False},
                {"index": 1, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.6, "directional_accuracy": 0.53,
                 "prediction_std": 0.1, "excluded": False},
            ],
        }
        with open(tmp_path / "ensemble_config.json", "w") as f:
            json.dump(config, f)
        return str(tmp_path)

    def test_predict_returns_expected_keys(self, ensemble_dir):
        from app.ml.ensemble_predictor import EnsemblePredictor
        pred = EnsemblePredictor(ensemble_dir)
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert "ml_score" in result
        assert "confidence" in result
        assert "ensemble_disagreement" in result
        assert "direction" in result

    def test_skips_excluded_members(self, tmp_path):
        for idx in range(3):
            model = SignalLSTM(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
            torch.save(model.state_dict(), tmp_path / f"ensemble_{idx}.pt")
        config = {
            "n_members": 2, "input_size": 10, "hidden_size": 16,
            "num_layers": 1, "dropout": 0.1, "seq_len": 10,
            "model_version": "v2",
            "feature_names": [f"f{i}" for i in range(10)],
            "members": [
                {"index": 0, "excluded": False, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.5, "directional_accuracy": 0.55, "prediction_std": 0.1},
                {"index": 1, "excluded": True, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 1.5, "directional_accuracy": 0.48, "prediction_std": 0.02},
                {"index": 2, "excluded": False, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.6, "directional_accuracy": 0.54, "prediction_std": 0.1},
            ],
        }
        with open(tmp_path / "ensemble_config.json", "w") as f:
            json.dump(config, f)
        from app.ml.ensemble_predictor import EnsemblePredictor
        pred = EnsemblePredictor(str(tmp_path))
        assert pred.n_members == 2
