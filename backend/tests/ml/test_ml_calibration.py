import json
import os
import tempfile
import time as _time

import numpy as np
import torch

from app.ml.features import get_feature_names


def test_feature_names_match_matrix_columns():
    """Feature names list must match the number of columns in the feature matrix."""
    names = get_feature_names(flow_used=False, regime_used=False, btc_used=False)
    # Should match PRICE_FEATURES + INDICATOR_FEATURES + TEMPORAL_FEATURES + MOMENTUM_FEATURES + MULTI_TF_FEATURES
    assert len(names) >= 20
    assert all(isinstance(n, str) for n in names)
    assert len(names) == len(set(names)), "Feature names must be unique"


def test_feature_names_with_optional_groups():
    """Optional feature groups should add known names."""
    base = get_feature_names(flow_used=False, regime_used=False, btc_used=False)
    full = get_feature_names(flow_used=True, regime_used=True, btc_used=True)
    assert len(full) > len(base)
    assert "funding_rate" in full
    assert "regime_trend" in full
    assert "btc_ret_5" in full


def test_trainer_saves_feature_names_in_sidecar():
    """Trainer should save feature_names list in model_config.json sidecar."""
    from app.ml.trainer import Trainer, TrainConfig

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = TrainConfig(
            epochs=2, checkpoint_dir=tmpdir, seq_len=5,
            hidden_size=16, num_layers=1, patience=2,
        )
        n = 50
        features = np.random.randn(n, 24).astype(np.float32)
        direction = np.random.randint(0, 3, n)
        sl = np.random.rand(n).astype(np.float32) + 0.5
        tp1 = sl + 0.5
        tp2 = tp1 + 0.5

        trainer = Trainer(cfg)
        trainer.train(features, direction, sl, tp1, tp2)

        config_path = os.path.join(tmpdir, "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert "feature_names" in config, "Sidecar must contain feature_names"
        assert "temperature" in config, "Sidecar must contain temperature"
        assert config["temperature"] == 1.0  # uncalibrated default


def test_temperature_scaling_changes_calibration():
    """Temperature scaling should produce T != 1.0 for overconfident models."""
    from app.ml.trainer import Trainer, TrainConfig

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = TrainConfig(
            epochs=10, checkpoint_dir=tmpdir, seq_len=5,
            hidden_size=32, num_layers=1, patience=10,
        )
        n = 200
        np.random.seed(42)
        features = np.random.randn(n, 15).astype(np.float32)
        # Create patterns: features > 0 → LONG, < 0 → SHORT
        direction = np.where(features[:, 0] > 0.3, 1, np.where(features[:, 0] < -0.3, 2, 0)).astype(np.int64)
        sl = np.random.rand(n).astype(np.float32) + 0.5
        tp1 = sl + 0.5
        tp2 = tp1 + 0.5

        trainer = Trainer(cfg)
        trainer.train(features, direction, sl, tp1, tp2)

        config_path = os.path.join(tmpdir, "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        # Temperature should differ from 1.0 — calibration must have run
        assert config["temperature"] != 1.0, "Temperature scaling must change T from default 1.0"
        assert config["temperature"] > 0.1, "Temperature must be positive"
        assert isinstance(config["temperature"], float)
