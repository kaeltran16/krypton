"""Tests for LightGBM regime classifier."""

import os
import shutil
import tempfile

import numpy as np
import pytest

from app.engine.regime_classifier import RegimeClassifier


@pytest.fixture
def tmp_model_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def synthetic_regime_data():
    """Generate synthetic features + labels for 4 regimes."""
    rng = np.random.default_rng(42)
    n = 600
    features = rng.standard_normal((n, 11)).astype(np.float32)
    labels = rng.integers(0, 4, size=n).astype(np.int64)
    feature_names = [
        "adx", "adx_delta_5", "adx_delta_10",
        "bb_width", "bb_width_delta_5",
        "atr_pct", "atr_pct_delta_5",
        "volume_trend",
        "funding_rate_change", "oi_change_pct",
        "ensemble_disagreement",
    ]
    return features, labels, feature_names


def test_train_and_predict(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    metrics = clf.train(features, labels, feature_names)
    assert "macro_f1" in metrics
    assert "accuracy" in metrics
    assert metrics["macro_f1"] >= 0.0

    # Predict
    probs = clf.predict_proba(features[:1])
    assert set(probs.keys()) == {"trending", "ranging", "volatile", "steady"}
    assert abs(sum(probs.values()) - 1.0) < 1e-5


def test_save_and_load(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    clf.train(features, labels, feature_names)
    clf.save(tmp_model_dir)

    assert os.path.isfile(os.path.join(tmp_model_dir, "regime_classifier.joblib"))
    assert os.path.isfile(os.path.join(tmp_model_dir, "regime_config.json"))

    loaded = RegimeClassifier.load(tmp_model_dir)
    probs = loaded.predict_proba(features[:1])
    assert set(probs.keys()) == {"trending", "ranging", "volatile", "steady"}


def test_staleness_check(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    clf.train(features, labels, feature_names)
    clf.save(tmp_model_dir)

    loaded = RegimeClassifier.load(tmp_model_dir)
    assert not loaded.is_stale(max_age_days=30)


def test_predict_proba_returns_4_classes(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    clf.train(features, labels, feature_names)
    probs = clf.predict_proba(features[0:1])
    assert len(probs) == 4
    for v in probs.values():
        assert 0.0 <= v <= 1.0


def test_build_features_from_candle_data():
    """Test feature extraction helper."""
    from app.engine.regime_classifier import build_regime_features
    import pandas as pd

    rng = np.random.default_rng(42)
    n = 100
    df = pd.DataFrame({
        "open": rng.uniform(99, 101, n),
        "high": rng.uniform(101, 103, n),
        "low": rng.uniform(97, 99, n),
        "close": rng.uniform(99, 101, n),
        "volume": rng.uniform(100, 1000, n),
    })
    features, names = build_regime_features(df)
    assert features.shape[0] == n
    assert features.shape[1] >= 7  # at least base features
    assert len(names) == features.shape[1]
    # No NaN after warmup
    assert not np.isnan(features[20:]).any()
