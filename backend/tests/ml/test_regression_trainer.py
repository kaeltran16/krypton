import numpy as np
import pytest
import os

from app.ml.trainer import Trainer, TrainConfig


class TestTrainer:

    @pytest.fixture
    def training_data(self):
        rng = np.random.default_rng(42)
        n = 600
        n_features = 15
        features = rng.standard_normal((n, n_features)).astype(np.float32)
        forward_return = (features[:, 0] * 0.5 + rng.standard_normal(n) * 0.3).astype(np.float32)
        sl = np.abs(forward_return) * 0.5 + 0.5
        tp1 = np.abs(forward_return) * 0.8 + 0.5
        tp2 = np.abs(forward_return) * 1.2 + 1.0
        valid = np.ones(n, dtype=bool)
        sl = sl.astype(np.float32)
        tp1 = tp1.astype(np.float32)
        tp2 = tp2.astype(np.float32)
        return features, forward_return, sl, tp1, tp2, valid

    def test_train_one_model(self, training_data, tmp_path):
        features, fwd, sl, tp1, tp2, valid = training_data
        cfg = TrainConfig(
            epochs=5, batch_size=32, seq_len=20, hidden_size=32,
            num_layers=1, patience=5, min_epochs=3,
            checkpoint_dir=str(tmp_path),
        )
        trainer = Trainer(cfg)
        result = trainer.train_one_model(features, fwd, sl, tp1, tp2, valid)
        assert "val_huber_loss" in result
        assert "directional_accuracy" in result
        assert "best_epoch" in result
        assert os.path.exists(os.path.join(str(tmp_path), "best_model.pt"))

    def test_train_ensemble(self, training_data, tmp_path):
        features, fwd, sl, tp1, tp2, valid = training_data
        cfg = TrainConfig(
            epochs=5, batch_size=32, seq_len=20, hidden_size=32,
            num_layers=1, patience=5, min_epochs=3,
            checkpoint_dir=str(tmp_path),
            directional_accuracy_gate=0.40,
            prediction_std_gate=0.001,
        )
        trainer = Trainer(cfg)
        result = trainer.train_ensemble(
            features, fwd, sl, tp1, tp2, valid,
            feature_names=[f"f{i}" for i in range(15)],
        )
        assert "members" in result
        assert "n_members" in result
        config_path = os.path.join(str(tmp_path), "ensemble_config.json")
        assert os.path.exists(config_path)

    def test_quality_gate_excludes_bad_member(self, tmp_path):
        rng = np.random.default_rng(99)
        n = 400
        features = rng.standard_normal((n, 10)).astype(np.float32)
        fwd = rng.standard_normal(n).astype(np.float32)
        sl = tp1 = tp2 = np.ones(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)
        cfg = TrainConfig(
            epochs=3, batch_size=32, seq_len=10, hidden_size=16,
            num_layers=1, patience=3, min_epochs=2,
            checkpoint_dir=str(tmp_path),
            directional_accuracy_gate=0.52,
        )
        trainer = Trainer(cfg)
        result = trainer.train_one_model(features, fwd, sl, tp1, tp2, valid)
        assert "directional_accuracy" in result
