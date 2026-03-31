import numpy as np

from app.ml.drift import compute_feature_distributions


def make_drift_stats(training_data: np.ndarray, top_indices: list[int]) -> dict:
    """Build drift_stats dict from training data for testing."""
    distributions = {}
    for idx in top_indices:
        distributions[str(idx)] = compute_feature_distributions(training_data[:, idx])
    return {
        "top_feature_indices": top_indices,
        "feature_distributions": distributions,
    }
