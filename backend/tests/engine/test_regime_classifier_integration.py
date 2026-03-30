"""Test integration of regime classifier with compute_regime_mix."""

import numpy as np
import pytest

from app.engine.regime import compute_regime_mix, REGIMES


def test_compute_regime_mix_without_classifier():
    """Existing heuristic still works when no classifier provided."""
    result = compute_regime_mix(0.8, 0.7)
    assert set(result.keys()) == set(REGIMES)
    assert abs(sum(result.values()) - 1.0) < 1e-6


def test_compute_regime_mix_with_classifier():
    """When classifier provided, its output is used."""
    class MockClassifier:
        def predict_proba(self, features, feature_names=None):
            return {"trending": 0.6, "ranging": 0.2, "volatile": 0.1, "steady": 0.1}
        def is_stale(self, max_age_days=30):
            return False

    result = compute_regime_mix(0.8, 0.7, classifier=MockClassifier(),
                                 classifier_features=np.zeros((1, 11)))
    assert result["trending"] == 0.6
    assert result["ranging"] == 0.2


def test_compute_regime_mix_stale_classifier_uses_heuristic():
    """Stale classifier falls back to heuristic."""
    class StaleClassifier:
        def predict_proba(self, features, feature_names=None):
            return {"trending": 0.9, "ranging": 0.0, "volatile": 0.1, "steady": 0.0}
        def is_stale(self, max_age_days=30):
            return True

    result = compute_regime_mix(0.1, 0.1, classifier=StaleClassifier(),
                                 classifier_features=np.zeros((1, 11)))
    # Should use heuristic (low trend, low vol → ranging dominant)
    assert result["ranging"] > result["trending"]
