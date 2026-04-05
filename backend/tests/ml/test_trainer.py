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

    def test_cosine_lr_schedule(self, synthetic_data):
        """LR should decrease over epochs with cosine schedule."""
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=10,
                batch_size=32,
                seq_len=50,
                hidden_size=32,
                num_layers=1,
                lr=1e-3,
                warmup_epochs=2,
                patience=999,  # disable early stopping so all 10 epochs run
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)
            assert "lr_history" in result
            lrs = result["lr_history"]
            assert len(lrs) == 10, "All 10 epochs should run"
            # After warmup (epoch 2), LR should generally decrease
            assert lrs[2] >= lrs[-1], "LR should decrease after warmup via cosine annealing"

    def test_label_smoothing_applied(self, synthetic_data):
        """Label smoothing should be configured and affect the loss function."""
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=2,
                batch_size=32,
                seq_len=50,
                hidden_size=32,
                num_layers=1,
                label_smoothing=0.1,
                checkpoint_dir=tmpdir,
            )
            assert config.label_smoothing == 0.1
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)
            # Should train successfully with label smoothing
            assert result["best_val_loss"] > 0

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

    def test_train_returns_classification_metrics(self, synthetic_data):
        """Trainer.train() result includes direction_accuracy, precision_per_class, recall_per_class."""
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=3,
                batch_size=32,
                seq_len=50,
                hidden_size=32,
                num_layers=1,
                lr=1e-3,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)

            # Existing fields still present
            assert "best_epoch" in result
            assert "best_val_loss" in result
            assert "train_loss" in result
            assert "val_loss" in result

            # New fields
            assert "direction_accuracy" in result
            assert isinstance(result["direction_accuracy"], float)
            assert 0.0 <= result["direction_accuracy"] <= 1.0

            assert "precision_per_class" in result
            for cls in ("long", "short", "neutral"):
                assert cls in result["precision_per_class"]
                assert 0.0 <= result["precision_per_class"][cls] <= 1.0

            assert "recall_per_class" in result
            for cls in ("long", "short", "neutral"):
                assert cls in result["recall_per_class"]
                assert 0.0 <= result["recall_per_class"][cls] <= 1.0


def test_class_weights_prevalence_gated():
    """Sqrt-inverse-frequency with rare-class cap.

    Rare classes (<5%) are capped to prevent runaway weights.
    Common classes keep natural sqrt-inverse-frequency weights so the
    loss properly compensates for imbalance.
    """
    from app.ml.trainer import compute_class_weights

    # WIF-like: 1% NEUTRAL (below 5% threshold �� gets boost, capped at 3x median)
    wif_labels = np.concatenate([
        np.full(470, 1, dtype=np.int64),
        np.full(520, 2, dtype=np.int64),
        np.full(10, 0, dtype=np.int64),
    ])
    w = compute_class_weights(wif_labels)
    # NEUTRAL should get a boost but capped at rare_cap (3x median)
    assert w[0] / np.median(w) < 3.2, f"Rare class weight ratio too high: {w}"
    assert w[0] > w[1], "Rare NEUTRAL should have higher weight than common LONG"

    # ETH-like: 7% NEUTRAL (above threshold → uncapped sqrt-inv-freq)
    eth_labels = np.concatenate([
        np.full(465, 1, dtype=np.int64),
        np.full(465, 2, dtype=np.int64),
        np.full(70, 0, dtype=np.int64),
    ])
    w = compute_class_weights(eth_labels)
    # NEUTRAL (7%) should get higher weight than LONG/SHORT (46.5% each)
    assert w[0] > w[1], f"Minority NEUTRAL should outweigh common LONG: {w}"
    assert abs(w[1] - w[2]) < 0.01, f"Equal-count classes should have equal weight: {w}"
    # Weights should sum to num_classes
    assert abs(sum(w) - 3.0) < 0.01, f"Weights should sum to 3: {w}"


def test_train_stores_drift_stats(tmp_path):
    """Training should write drift_stats to model_config.json."""
    import json
    rng = np.random.default_rng(42)
    n = 200
    input_size = 10
    features = rng.standard_normal((n, input_size)).astype(np.float32)
    direction = rng.integers(0, 3, n).astype(np.int64)
    sl = rng.uniform(0.5, 2, n).astype(np.float32)
    tp1 = rng.uniform(1, 3, n).astype(np.float32)
    tp2 = rng.uniform(2, 5, n).astype(np.float32)
    feature_names = [f"feat_{i}" for i in range(input_size)]

    cfg = TrainConfig(
        epochs=3, batch_size=32, seq_len=10,
        hidden_size=16, num_layers=1, dropout=0.1,
        patience=100, checkpoint_dir=str(tmp_path),
    )
    trainer = Trainer(cfg)
    trainer.train_one_model(features, direction, sl, tp1, tp2, feature_names=feature_names)

    config_path = tmp_path / "model_config.json"
    assert config_path.exists()
    with open(config_path) as f:
        config = json.load(f)

    assert "drift_stats" in config
    ds = config["drift_stats"]
    assert "top_feature_indices" in ds
    assert "feature_distributions" in ds
    assert len(ds["top_feature_indices"]) == 5
    for idx in ds["top_feature_indices"]:
        dist = ds["feature_distributions"][str(idx)]
        assert "bin_edges" in dist
        assert "proportions" in dist
        assert len(dist["proportions"]) == 10
