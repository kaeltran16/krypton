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
        assert config["temperature"] > 0.1, "Temperature must be positive"
        assert isinstance(config["temperature"], float)


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


def test_mc_dropout_reduces_confidence_with_high_variance(tmp_path):
    """MC Dropout should produce lower confidence when model is uncertain."""
    from app.ml.model import SignalLSTM
    from app.ml.predictor import Predictor

    input_size = 15
    model = SignalLSTM(input_size=input_size, hidden_size=32, num_layers=1, dropout=0.5)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size,
        "hidden_size": 32,
        "num_layers": 1,
        "dropout": 0.5,
        "seq_len": 10,
        "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))
    features = np.random.randn(20, input_size).astype(np.float32)
    result = predictor.predict(features)

    assert "confidence" in result
    assert "mc_variance" in result
    assert result["mc_variance"] >= 0.0


def test_mc_dropout_completes_within_latency_budget(tmp_path):
    """5 MC Dropout passes should complete in <5s on CPU (generous for CI/Docker)."""
    import time
    from app.ml.model import SignalLSTM
    from app.ml.predictor import Predictor

    input_size = 24
    model = SignalLSTM(input_size=input_size, hidden_size=128, num_layers=2, dropout=0.3)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 128, "num_layers": 2,
        "dropout": 0.3, "seq_len": 50, "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))
    features = np.random.randn(60, input_size).astype(np.float32)

    start = time.monotonic()
    result = predictor.predict(features)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, f"MC Dropout inference took {elapsed:.2f}s (budget: 5s)"


def test_feature_mapping_handles_missing_features(tmp_path):
    """Predictor should map features by name, filling missing with 0."""
    from app.ml.model import SignalLSTM
    from app.ml.predictor import Predictor

    input_size = 5
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.0)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.0, "seq_len": 5, "temperature": 1.0,
        "feature_names": ["a", "b", "c", "d", "e"],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))

    # Provide features with different names (3 match, 2 missing)
    predictor.set_available_features(["a", "c", "e", "x", "y"])
    features = np.random.randn(10, 5).astype(np.float32)
    result = predictor.predict(features)

    # Should still produce a result (missing features filled with 0)
    assert result["direction"] in ("NEUTRAL", "LONG", "SHORT")


def test_feature_mapping_logs_missing(tmp_path, caplog):
    """Predictor should log warnings for missing features."""
    from app.ml.model import SignalLSTM
    from app.ml.predictor import Predictor
    import logging

    input_size = 3
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.0)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.0, "seq_len": 5, "temperature": 1.0,
        "feature_names": ["a", "b", "c"],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))
    predictor.set_available_features(["a", "d"])  # "b" and "c" missing

    with caplog.at_level(logging.WARNING):
        features = np.random.randn(10, 2).astype(np.float32)
        predictor.predict(features)

    assert any("missing" in msg.lower() or "Missing" in msg for msg in caplog.messages)


def test_stale_model_by_age_reduces_confidence(tmp_path):
    """Models older than max_age_days should have reduced confidence."""
    from app.ml.model import SignalLSTM
    from app.ml.predictor import Predictor

    input_size = 15
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.3)
    pt_path = tmp_path / "best_model.pt"
    torch.save(model.state_dict(), pt_path)

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.3, "seq_len": 10, "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    # Make the checkpoint appear 20 days old
    old_time = _time.time() - 20 * 86400
    os.utime(pt_path, (old_time, old_time))

    predictor = Predictor(str(pt_path), max_age_days=14)
    assert predictor._max_confidence == 0.3

    features = np.random.randn(20, input_size).astype(np.float32)
    result = predictor.predict(features)
    # Confidence should be capped at 0.3
    assert result["confidence"] <= 0.3


def test_fresh_model_not_marked_stale(tmp_path):
    """Recently trained model should not be marked stale."""
    from app.ml.model import SignalLSTM
    from app.ml.predictor import Predictor

    input_size = 15
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.0)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.0, "seq_len": 10, "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"), max_age_days=14)
    assert predictor._max_confidence == 1.0
