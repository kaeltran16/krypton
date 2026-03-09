import os
import tempfile

import numpy as np
import pytest

from app.ml.trainer import Trainer, TrainConfig


class TestTrainer:

    @pytest.fixture
    def synthetic_data(self):
        """Synthetic features + labels for training test."""
        n = 500
        n_features = 15
        features = np.random.randn(n, n_features).astype(np.float32)
        direction = np.random.randint(0, 3, size=n).astype(np.int64)
        sl = np.random.uniform(0.5, 3.0, size=n).astype(np.float32)
        tp1 = np.random.uniform(1.0, 4.0, size=n).astype(np.float32)
        tp2 = np.random.uniform(2.0, 6.0, size=n).astype(np.float32)
        return features, direction, sl, tp1, tp2

    def test_train_runs_without_error(self, synthetic_data):
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=2,
                batch_size=32,
                seq_len=50,
                hidden_size=32,
                num_layers=1,
                lr=1e-3,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)

            assert "train_loss" in result
            assert "val_loss" in result
            assert "best_epoch" in result
            assert len(result["train_loss"]) == 2

    def test_checkpoint_saved(self, synthetic_data):
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=2, batch_size=32, seq_len=50,
                hidden_size=32, num_layers=1,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            trainer.train(features, direction, sl, tp1, tp2)

            # Best checkpoint should exist
            assert os.path.exists(os.path.join(tmpdir, "best_model.pt"))

    def test_val_split(self, synthetic_data):
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=1, batch_size=32, seq_len=50,
                hidden_size=32, num_layers=1,
                val_ratio=0.2,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)
            assert len(result["val_loss"]) == 1
            assert result["val_loss"][0] > 0
