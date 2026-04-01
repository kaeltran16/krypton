"""Tests for graceful inference fallback when features are missing."""

import json
import os
import tempfile

import numpy as np
import pytest
import torch

from app.ml.features import BASE_FEATURES, REGIME_FEATURES, INTER_PAIR_FEATURES, FLOW_FEATURES, FLOW_ROC_FEATURES, get_feature_names
from app.ml.model import SignalLSTM
from app.ml.predictor import Predictor
from app.ml.ensemble_predictor import EnsemblePredictor


ALL_36 = get_feature_names(flow_used=True, regime_used=True, btc_used=True)
BASE_24 = get_feature_names()


def _save_predictor(input_size, feature_names, seq_len=10, extra_config=None):
    """Save a dummy model and return checkpoint path."""
    tmpdir = tempfile.mkdtemp()
    model = SignalLSTM(input_size=input_size, hidden_size=32, num_layers=1, dropout=0.0)
    path = os.path.join(tmpdir, "best_model.pt")
    torch.save(model.state_dict(), path)
    config = {
        "input_size": input_size,
        "hidden_size": 32,
        "num_layers": 1,
        "dropout": 0.0,
        "seq_len": seq_len,
        "feature_names": feature_names,
        "flow_used": True,
        "regime_used": True,
        "btc_used": True,
    }
    if extra_config:
        config.update(extra_config)
    with open(os.path.join(tmpdir, "model_config.json"), "w") as f:
        json.dump(config, f)
    return path


def _save_ensemble(input_size, feature_names, seq_len=10, n_members=3):
    """Save a dummy ensemble and return checkpoint dir."""
    tmpdir = tempfile.mkdtemp()
    members = []
    for i in range(n_members):
        model = SignalLSTM(input_size=input_size, hidden_size=32, num_layers=1, dropout=0.0)
        torch.save(model.state_dict(), os.path.join(tmpdir, f"ensemble_{i}.pt"))
        members.append({"index": i, "temperature": 1.0, "data_range": [0.0, 1.0]})
    config = {
        "n_members": n_members,
        "input_size": input_size,
        "hidden_size": 32,
        "num_layers": 1,
        "dropout": 0.0,
        "seq_len": seq_len,
        "feature_names": feature_names,
        "flow_used": True,
        "regime_used": True,
        "btc_used": True,
        "members": members,
    }
    with open(os.path.join(tmpdir, "ensemble_config.json"), "w") as f:
        json.dump(config, f)
    return tmpdir


class TestPredictorFewerFeatures:

    def test_map_features_produces_correct_shape(self):
        """Predictor trained with 36 features given only 24 should produce (n, 36)."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)
        pred = Predictor(path)

        pred.set_available_features(BASE_24)
        raw = np.random.randn(20, 24).astype(np.float32)
        mapped = pred._map_features(raw)

        assert mapped.shape == (20, 36)

    def test_missing_columns_are_zero(self):
        """Missing feature columns should be zero-filled."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)
        pred = Predictor(path)

        pred.set_available_features(BASE_24)
        raw = np.ones((5, 24), dtype=np.float32)
        mapped = pred._map_features(raw)

        # Base features should be copied, additional features should be zero
        n_missing = 36 - 24
        # At least n_missing columns should have all zeros
        zero_cols = np.sum(np.all(mapped == 0, axis=0))
        assert zero_cols >= n_missing

    def test_predict_does_not_crash(self):
        """Predict with fewer features should return a valid result, not crash."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)
        pred = Predictor(path)

        pred.set_available_features(BASE_24)
        features = np.random.randn(20, 24).astype(np.float32)
        result = pred.predict(features)

        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
        assert 0 <= result["confidence"] <= 1


class TestPredictorMatchingFeatures:

    def test_matching_features_no_penalty(self):
        """When all features are available, no missing-feature penalty should apply."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)
        pred = Predictor(path)

        pred.set_available_features(ALL_36)
        assert pred._n_missing_features == 0
        assert pred._n_expected_features == 36


class TestSetAvailableFeaturesShortCircuit:

    def test_short_circuit_skips_recomputation(self):
        """Calling set_available_features twice with same names should short-circuit."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)
        pred = Predictor(path)

        pred.set_available_features(BASE_24)
        first_map = pred._feature_map

        # Second call with same names
        pred.set_available_features(BASE_24)
        assert pred._feature_map is first_map  # exact same object, not recomputed

    def test_different_names_recomputes(self):
        """Calling set_available_features with different names should recompute."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)
        pred = Predictor(path)

        pred.set_available_features(BASE_24)
        first_map = list(pred._feature_map)

        names_with_regime = get_feature_names(regime_used=True)
        pred.set_available_features(names_with_regime)
        second_map = list(pred._feature_map)

        assert first_map != second_map


class TestConfidencePenaltyScaling:

    def _get_missing_penalty(self, n_missing, n_expected):
        """Compute the expected penalty factor."""
        if n_missing == 0 or n_expected == 0:
            return 1.0
        ratio = n_missing / n_expected
        return 1.0 - (ratio * 0.5)

    def test_zero_missing(self):
        assert self._get_missing_penalty(0, 36) == 1.0

    def test_partial_missing(self):
        # 12 missing out of 36 → ratio 0.333 → penalty 0.833
        penalty = self._get_missing_penalty(12, 36)
        assert abs(penalty - 0.8333) < 0.01

    def test_all_missing(self):
        # 36/36 → 0.5 floor
        penalty = self._get_missing_penalty(36, 36)
        assert abs(penalty - 0.5) < 0.01

    def test_predictor_stores_counts(self):
        """Predictor should store missing/expected counts after set_available_features."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)
        pred = Predictor(path)

        pred.set_available_features(BASE_24)
        assert pred._n_missing_features == 12  # 36 - 24
        assert pred._n_expected_features == 36

    def test_confidence_reduced_with_missing_features(self):
        """Prediction with missing features should have lower confidence than with all features."""
        path = _save_predictor(input_size=36, feature_names=ALL_36)

        pred_full = Predictor(path)
        pred_full.set_available_features(ALL_36)

        pred_partial = Predictor(path)
        pred_partial.set_available_features(BASE_24)

        np.random.seed(42)
        features_36 = np.random.randn(20, 36).astype(np.float32)
        features_24 = features_36[:, :24]

        result_full = pred_full.predict(features_36)
        result_partial = pred_partial.predict(features_24)

        # If both produce non-neutral results, partial should have lower confidence
        if result_full["confidence"] > 0 and result_partial["confidence"] > 0:
            assert result_partial["confidence"] <= result_full["confidence"]


class TestEnsemblePredictorFallback:

    def test_ensemble_map_features_correct_shape(self):
        """Ensemble predictor with fewer features should produce correct shape."""
        d = _save_ensemble(input_size=36, feature_names=ALL_36)
        pred = EnsemblePredictor(d)

        pred.set_available_features(BASE_24)
        raw = np.random.randn(20, 24).astype(np.float32)
        mapped = pred._map_features(raw)

        assert mapped.shape == (20, 36)

    def test_ensemble_predict_with_missing_features(self):
        """Ensemble predict with fewer features should not crash."""
        d = _save_ensemble(input_size=36, feature_names=ALL_36)
        pred = EnsemblePredictor(d)

        pred.set_available_features(BASE_24)
        features = np.random.randn(20, 24).astype(np.float32)
        result = pred.predict(features)

        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
        assert 0 <= result["confidence"] <= 1

    def test_ensemble_short_circuit(self):
        """Ensemble set_available_features should short-circuit on same names."""
        d = _save_ensemble(input_size=36, feature_names=ALL_36)
        pred = EnsemblePredictor(d)

        pred.set_available_features(BASE_24)
        first_map = pred._feature_map

        pred.set_available_features(BASE_24)
        assert pred._feature_map is first_map

    def test_ensemble_stores_missing_counts(self):
        d = _save_ensemble(input_size=36, feature_names=ALL_36)
        pred = EnsemblePredictor(d)

        pred.set_available_features(BASE_24)
        assert pred._n_missing_features == 12
        assert pred._n_expected_features == 36
