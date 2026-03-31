"""Tests for EnsemblePredictor inference."""

import json
import os
import shutil
import tempfile

import numpy as np
import pytest
import torch

from app.ml.model import SignalLSTM
from app.ml.ensemble_predictor import EnsemblePredictor


@pytest.fixture
def ensemble_checkpoint():
    """Create a temporary ensemble checkpoint with 3 members."""
    d = tempfile.mkdtemp()
    input_size = 15
    hidden_size = 32
    num_layers = 1
    seq_len = 10

    members = []
    for i in range(3):
        model = SignalLSTM(input_size=input_size, hidden_size=hidden_size,
                           num_layers=num_layers, dropout=0.0)
        torch.save(model.state_dict(), os.path.join(d, f"ensemble_{i}.pt"))
        members.append({
            "index": i,
            "trained_at": "2026-03-31T12:00:00",
            "val_loss": 0.4,
            "temperature": 1.0,
            "data_range": [[0.0, 0.8], [0.1, 0.9], [0.2, 1.0]][i],
        })

    config = {
        "n_members": 3,
        "input_size": input_size,
        "hidden_size": hidden_size,
        "num_layers": num_layers,
        "dropout": 0.0,
        "seq_len": seq_len,
        "feature_names": [f"f{j}" for j in range(input_size)],
        "members": members,
    }
    with open(os.path.join(d, "ensemble_config.json"), "w") as f:
        json.dump(config, f)

    yield d
    shutil.rmtree(d)


def test_loads_all_members(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    assert pred.n_members == 3


def test_predict_returns_expected_keys(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert 0.0 <= result["confidence"] <= 1.0
    assert "ensemble_disagreement" in result
    assert "sl_atr" in result
    assert "tp1_atr" in result
    assert "tp2_atr" in result


def test_predict_too_few_candles_returns_neutral(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(5, 15).astype(np.float32)  # less than seq_len=10
    result = pred.predict(features)
    assert result["direction"] == "NEUTRAL"
    assert result["confidence"] == 0.0


def test_disagreement_is_nonnegative(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["ensemble_disagreement"] >= 0.0


def test_partial_load_2_members(ensemble_checkpoint):
    """Remove one member checkpoint — should still work with 2."""
    os.remove(os.path.join(ensemble_checkpoint, "ensemble_2.pt"))
    # Update config to reflect 2 members
    with open(os.path.join(ensemble_checkpoint, "ensemble_config.json")) as f:
        config = json.load(f)
    config["members"] = config["members"][:2]
    config["n_members"] = 2
    with open(os.path.join(ensemble_checkpoint, "ensemble_config.json"), "w") as f:
        json.dump(config, f)

    pred = EnsemblePredictor(ensemble_checkpoint)
    assert pred.n_members == 2
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    # Confidence capped at 0.5 for 2-member ensemble
    assert result["confidence"] <= 0.5


def test_feature_mapping(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    # Provide features in different order
    pred.set_available_features([f"f{14 - j}" for j in range(15)])
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")


def test_interface_matches_predictor(ensemble_checkpoint):
    """EnsemblePredictor has same public interface as Predictor."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    assert hasattr(pred, "predict")
    assert hasattr(pred, "set_available_features")
    assert hasattr(pred, "flow_used")
    assert hasattr(pred, "regime_used")
    assert hasattr(pred, "btc_used")
    assert hasattr(pred, "seq_len")


def _add_drift_stats_to_config(checkpoint_dir, input_size=15):
    """Add drift_stats to ensemble_config.json for testing."""
    from tests.ml.conftest import make_drift_stats

    rng = np.random.default_rng(42)
    training_data = rng.standard_normal((500, input_size)).astype(np.float32)
    drift_stats = make_drift_stats(training_data, [0, 1, 2, 3, 4])

    config_path = os.path.join(checkpoint_dir, "ensemble_config.json")
    with open(config_path) as f:
        config = json.load(f)
    config["drift_stats"] = drift_stats
    with open(config_path, "w") as f:
        json.dump(config, f)
    return drift_stats


def test_no_drift_stats_backward_compatible(ensemble_checkpoint):
    """Ensemble without drift_stats should work unchanged."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert result.get("drift_penalty", 0.0) == 0.0


def test_drift_penalty_in_result(ensemble_checkpoint):
    """predict() should include drift_penalty key."""
    _add_drift_stats_to_config(ensemble_checkpoint)
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert "drift_penalty" in result


def test_severe_drift_reduces_confidence(ensemble_checkpoint):
    """Severe drift should reduce confidence vs no penalty."""
    _add_drift_stats_to_config(ensemble_checkpoint)

    rng = np.random.default_rng(42)
    drifted_features = (rng.standard_normal((20, 15)) * 5 + 3).astype(np.float32)

    pred_with = EnsemblePredictor(ensemble_checkpoint)
    result_with = pred_with.predict(drifted_features)

    from app.ml.drift import DriftConfig
    pred_without = EnsemblePredictor(
        ensemble_checkpoint, drift_config=DriftConfig(psi_moderate=10.0, psi_severe=20.0),
    )
    result_without = pred_without.predict(drifted_features)

    assert result_with["drift_penalty"] > 0
    if result_without["confidence"] > 0:
        assert result_with["confidence"] <= result_without["confidence"]


def test_custom_drift_thresholds(ensemble_checkpoint):
    """EnsemblePredictor should accept drift threshold overrides."""
    _add_drift_stats_to_config(ensemble_checkpoint)
    from app.ml.drift import DriftConfig
    pred = EnsemblePredictor(
        ensemble_checkpoint,
        drift_config=DriftConfig(psi_moderate=10.0, psi_severe=20.0),
    )
    rng = np.random.default_rng(42)
    drifted = (rng.standard_normal((20, 15)) * 5 + 3).astype(np.float32)
    result = pred.predict(drifted)
    assert result["drift_penalty"] == 0.0
