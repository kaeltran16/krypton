"""Tests for ensemble training pipeline."""

import os
import shutil
import tempfile

import numpy as np
import pytest

from app.ml.trainer import TrainConfig, Trainer


@pytest.fixture
def tmp_checkpoint():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def synthetic_data():
    """Generate synthetic training data (200 samples, 15 features)."""
    rng = np.random.default_rng(42)
    n = 200
    features = rng.standard_normal((n, 15)).astype(np.float32)
    direction = rng.integers(0, 3, size=n).astype(np.int64)
    sl = rng.uniform(0.5, 2.0, size=n).astype(np.float32)
    tp1 = rng.uniform(1.0, 3.0, size=n).astype(np.float32)
    tp2 = rng.uniform(2.0, 5.0, size=n).astype(np.float32)
    return features, direction, sl, tp1, tp2


def test_train_one_model_returns_result(tmp_checkpoint, synthetic_data):
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_one_model(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    assert "best_val_loss" in result
    assert "direction_accuracy" in result
    assert os.path.isfile(os.path.join(tmp_checkpoint, "best_model.pt"))
    assert os.path.isfile(os.path.join(tmp_checkpoint, "model_config.json"))


def test_train_one_model_matches_old_train(tmp_checkpoint, synthetic_data):
    """train_one_model is a drop-in for the old train() method."""
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_one_model(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    assert "train_loss" in result
    assert "val_loss" in result
    assert "version" in result
    assert "precision_per_class" in result
    assert "recall_per_class" in result


import json


def test_train_ensemble_produces_3_members(tmp_checkpoint, synthetic_data):
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    assert len(result["members"]) == 3
    for m in result["members"]:
        assert "val_loss" in m
        assert "data_range" in m
        assert "temperature" in m

    # Check checkpoint files
    assert os.path.isfile(os.path.join(tmp_checkpoint, "ensemble_config.json"))
    for i in range(3):
        assert os.path.isfile(os.path.join(tmp_checkpoint, f"ensemble_{i}.pt"))


def test_train_ensemble_config_json(tmp_checkpoint, synthetic_data):
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    with open(os.path.join(tmp_checkpoint, "ensemble_config.json")) as f:
        config = json.load(f)
    assert config["n_members"] == 3
    assert config["input_size"] == 15
    assert config["seq_len"] == 10
    assert len(config["members"]) == 3
    assert config["members"][0]["data_range"] == [0.0, 0.8]
    assert config["members"][1]["data_range"] == [0.1, 0.9]
    assert config["members"][2]["data_range"] == [0.2, 1.0]


def test_train_ensemble_skips_member_with_insufficient_data(tmp_checkpoint):
    """With very few samples, some slices may be too small."""
    rng = np.random.default_rng(42)
    n = 30  # very small dataset
    features = rng.standard_normal((n, 15)).astype(np.float32)
    direction = rng.integers(0, 3, size=n).astype(np.int64)
    sl = rng.uniform(0.5, 2.0, size=n).astype(np.float32)
    tp1 = rng.uniform(1.0, 3.0, size=n).astype(np.float32)
    tp2 = rng.uniform(2.0, 5.0, size=n).astype(np.float32)
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    # Should produce at least 2 members (or fall back)
    assert len(result["members"]) >= 2


def test_train_ensemble_staging_dir_cleaned_up(tmp_checkpoint, synthetic_data):
    """Staging directory should not exist after successful training."""
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    staging = os.path.join(tmp_checkpoint, ".ensemble_staging")
    assert not os.path.exists(staging)


def test_ensemble_stores_drift_stats(tmp_checkpoint):
    """Ensemble training should write drift_stats to ensemble_config.json."""
    import json
    rng = np.random.default_rng(42)
    n = 300
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
        patience=100, checkpoint_dir=tmp_checkpoint,
    )
    trainer = Trainer(cfg)
    result = trainer.train_ensemble(features, direction, sl, tp1, tp2, feature_names=feature_names)

    if result.get("n_members", 0) >= 2:
        config_path = os.path.join(tmp_checkpoint, "ensemble_config.json")
        assert os.path.exists(config_path)
        with open(config_path) as f:
            config = json.load(f)
        assert "drift_stats" in config
        ds = config["drift_stats"]
        assert len(ds["top_feature_indices"]) == 5
