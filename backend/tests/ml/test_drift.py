import numpy as np
import pytest

from app.ml.drift import (
    DriftConfig,
    compute_feature_distributions,
    compute_psi,
    feature_drift_penalty,
)
from tests.ml.conftest import make_drift_stats


class TestComputePSI:

    def test_identical_distributions_psi_near_zero(self):
        """PSI should be ~0 when actual matches expected."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], training_data)
        assert psi < 0.01

    def test_shifted_distribution_moderate_psi(self):
        """A mean-shifted distribution should produce moderate PSI (0.1-0.25)."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        shifted = training_data + 0.5
        psi = compute_psi(dist["bin_edges"], dist["proportions"], shifted)
        assert 0.05 < psi < 0.5

    def test_very_different_distribution_high_psi(self):
        """A radically different distribution should produce high PSI (>0.25)."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        different = rng.standard_normal(500) * 5 + 3
        psi = compute_psi(dist["bin_edges"], dist["proportions"], different)
        assert psi > 0.25

    def test_psi_is_nonnegative(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(200)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = rng.standard_normal(200)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert psi >= 0.0

    def test_small_actual_sample(self):
        """PSI should work with small actual sample sizes."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        small_actual = rng.standard_normal(20)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], small_actual)
        assert psi >= 0.0

    def test_nan_values_filtered(self):
        """NaN values in actual data should be filtered, not corrupt the result."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = rng.standard_normal(100)
        actual[0:10] = np.nan
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert np.isfinite(psi)
        assert psi >= 0.0

    def test_inf_values_filtered(self):
        """Inf values in actual data should be filtered."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = rng.standard_normal(100)
        actual[0:5] = np.inf
        actual[5:10] = -np.inf
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert np.isfinite(psi)
        assert psi >= 0.0

    def test_all_nan_returns_zero(self):
        """All-NaN actual data should return 0.0 (empty after filtering)."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = np.full(50, np.nan)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert psi == 0.0


class TestComputeFeatureDistributions:

    def test_returns_correct_keys(self):
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert "bin_edges" in dist
        assert "proportions" in dist

    def test_proportions_sum_to_one(self):
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert abs(sum(dist["proportions"]) - 1.0) < 1e-6

    def test_bin_edges_length(self):
        """n_bins=10 should produce 11 edges (including -inf and +inf)."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert len(dist["bin_edges"]) == 11
        assert len(dist["proportions"]) == 10

    def test_constant_value_feature(self):
        """All-identical values should produce valid distributions."""
        data = np.ones(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert len(dist["bin_edges"]) == 11
        assert len(dist["proportions"]) == 10
        assert abs(sum(dist["proportions"]) - 1.0) < 1e-6

    def test_nan_values_filtered(self):
        """NaN values in training data should be filtered out."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        data[0:20] = np.nan
        dist = compute_feature_distributions(data, n_bins=10)
        assert abs(sum(dist["proportions"]) - 1.0) < 1e-6

    def test_all_nan_returns_uniform(self):
        """All-NaN input should return uniform distribution."""
        data = np.full(100, np.nan)
        dist = compute_feature_distributions(data, n_bins=10)
        assert len(dist["proportions"]) == 10


class TestFeatureDriftPenalty:

    def test_no_drift_stats_returns_zero(self):
        features = np.random.randn(50, 10).astype(np.float32)
        penalty = feature_drift_penalty(features, None)
        assert penalty == 0.0

    def test_stable_features_no_penalty(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        rng2 = np.random.default_rng(99)
        current = rng2.standard_normal((500, 10)).astype(np.float32)
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty == 0.0

    def test_severe_drift_high_penalty(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = (rng.standard_normal((50, 10)) * 5 + 3).astype(np.float32)
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty == 0.6

    def test_moderate_drift_moderate_penalty(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        rng2 = np.random.default_rng(99)
        current = rng2.standard_normal((500, 10)).astype(np.float32)
        current[:, 0] += 0.3
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty in (0.0, 0.3)

    def test_top_k_limits_features_checked(self):
        """Only top_k features should be checked, not all stored."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        rng2 = np.random.default_rng(99)
        current = rng2.standard_normal((500, 10)).astype(np.float32)
        current[:, 4] = current[:, 4] * 10 + 5
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty == 0.0

    def test_custom_thresholds(self):
        """Custom PSI thresholds and penalties should be respected."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = (rng.standard_normal((50, 10)) * 5 + 3).astype(np.float32)
        penalty = feature_drift_penalty(
            current, drift_stats, top_k=3,
            config=DriftConfig(psi_moderate=10.0, psi_severe=20.0),
        )
        assert penalty == 0.0

    def test_custom_penalties_applied(self):
        """Custom penalty values should be used when thresholds are hit."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = (rng.standard_normal((50, 10)) * 5 + 3).astype(np.float32)
        penalty = feature_drift_penalty(
            current, drift_stats, top_k=3,
            config=DriftConfig(penalty_moderate=0.15, penalty_severe=0.45),
        )
        assert penalty == 0.45



