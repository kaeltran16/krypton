"""Feature distribution drift detection via Population Stability Index."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


@dataclass
class DriftConfig:
    """Thresholds and penalties for PSI-based feature drift detection."""
    psi_moderate: float = 0.1
    psi_severe: float = 0.25
    penalty_moderate: float = 0.3
    penalty_severe: float = 0.6


def compute_feature_distributions(
    data: np.ndarray,
    n_bins: int = 10,
) -> dict:
    """Compute decile bin edges and proportions from training data.

    Args:
        data: 1D array of feature values from training set.
        n_bins: number of bins (default 10 = deciles).

    Returns:
        dict with 'bin_edges' (list of n_bins+1 floats including -inf/+inf)
        and 'proportions' (list of n_bins floats summing to 1.0).
    """
    data = data[np.isfinite(data)]
    if len(data) == 0:
        edges = [-np.inf] + [i * 1e-10 for i in range(1, n_bins)] + [np.inf]
        return {"bin_edges": edges, "proportions": [1.0 / n_bins] * n_bins}

    quantiles = np.linspace(0, 100, n_bins + 1)
    edges = np.percentile(data, quantiles)
    edges[0] = -np.inf
    edges[-1] = np.inf
    for i in range(1, len(edges)):
        if edges[i] <= edges[i - 1]:
            edges[i] = edges[i - 1] + 1e-10

    counts = np.histogram(data, bins=edges)[0].astype(np.float64)
    proportions = counts / counts.sum()

    return {
        "bin_edges": edges.tolist(),
        "proportions": proportions.tolist(),
    }


def compute_psi(
    bin_edges: list[float],
    expected_proportions: list[float],
    actual_values: np.ndarray,
    floor: float = 0.001,
) -> float:
    """Compute Population Stability Index between expected and actual distributions.

    Args:
        bin_edges: bin edges from training distribution (n_bins+1 values).
        expected_proportions: proportion in each bin from training (n_bins values).
        actual_values: 1D array of current feature values.
        floor: minimum proportion to avoid log(0).

    Returns:
        PSI value (>= 0). <0.1 = stable, 0.1-0.25 = moderate, >0.25 = severe.
    """
    actual_values = actual_values[np.isfinite(actual_values)]
    edges = np.array(bin_edges)
    expected = np.array(expected_proportions, dtype=np.float64)
    expected = np.maximum(expected, floor)

    actual_counts = np.histogram(actual_values, bins=edges)[0].astype(np.float64)
    total = actual_counts.sum()
    if total == 0:
        return 0.0
    actual = actual_counts / total
    actual = np.maximum(actual, floor)

    psi = float(np.sum((actual - expected) * np.log(actual / expected)))
    return max(0.0, psi)


def feature_drift_penalty(
    current_features: np.ndarray,
    drift_stats: dict | None,
    top_k: int = 3,
    config: DriftConfig | None = None,
) -> float:
    """Compute confidence penalty based on feature distribution drift.

    Args:
        current_features: (n_candles, n_features) array.
        drift_stats: dict with 'top_feature_indices' and 'feature_distributions',
                     or None if not available.
        top_k: number of top features to check.
        config: drift thresholds and penalties.

    Returns:
        Penalty float (0.0, penalty_moderate, or penalty_severe).
    """
    if drift_stats is None:
        return 0.0

    if config is None:
        config = DriftConfig()

    top_indices = drift_stats.get("top_feature_indices", [])[:top_k]
    distributions = drift_stats.get("feature_distributions", {})

    if not top_indices or not distributions:
        return 0.0

    max_psi = 0.0
    n_features = current_features.shape[1]

    for idx in top_indices:
        dist = distributions.get(str(idx))
        if dist is None:
            continue
        if idx >= n_features:
            continue
        psi = compute_psi(
            dist["bin_edges"],
            dist["proportions"],
            current_features[:, idx],
        )
        max_psi = max(max_psi, psi)

    if max_psi < config.psi_moderate:
        return 0.0
    elif max_psi < config.psi_severe:
        return config.penalty_moderate
    else:
        return config.penalty_severe


def _permutation_importance(
    model: nn.Module,
    val_loader,
    input_size: int,
    n_repeats: int = 3,
) -> list[tuple[int, float]]:
    """Permutation importance using HuberLoss for regression models.

    val_loader yields (x, y_return, y_reg) from CandleDataset.
    model returns (return_pred, reg_out) from SignalLSTM.
    """
    device = next(model.parameters()).device
    criterion = nn.HuberLoss(delta=1.0)
    model.eval()

    baseline_loss = 0.0
    n_batches = 0
    all_x = []
    all_y = []
    with torch.no_grad():
        for x, y_return, _ in val_loader:
            x = x.to(device)
            y_return = y_return.to(device)
            return_pred, _ = model(x)
            baseline_loss += criterion(return_pred.squeeze(1), y_return).item()
            all_x.append(x)
            all_y.append(y_return)
            n_batches += 1

    if n_batches == 0:
        return [(i, 0.0) for i in range(input_size)]

    baseline_loss /= n_batches

    importance = []
    for feat_idx in range(input_size):
        total_increase = 0.0
        for _ in range(n_repeats):
            shuffled_loss = 0.0
            for x, y_return in zip(all_x, all_y):
                x_perm = x.clone()
                perm = torch.randperm(x_perm.size(0), device=device)
                x_perm[:, :, feat_idx] = x_perm[perm, :, feat_idx]
                with torch.no_grad():
                    return_pred, _ = model(x_perm)
                    shuffled_loss += criterion(return_pred.squeeze(1), y_return).item()
            shuffled_loss /= n_batches
            total_increase += shuffled_loss - baseline_loss

        importance.append((feat_idx, total_increase / n_repeats))

    importance.sort(key=lambda x: x[1], reverse=True)
    return importance


def compute_drift_stats(
    model: nn.Module,
    val_loader,
    training_features: np.ndarray,
    input_size: int,
    top_n: int = 5,
    n_repeats: int = 3,
) -> dict | None:
    """Compute drift reference stats (importance ranking + distributions)."""
    try:
        importance = _permutation_importance(
            model, val_loader, input_size, n_repeats=n_repeats,
        )
        top_indices = [idx for idx, _ in importance[:top_n]]
        distributions = {}
        for idx in top_indices:
            distributions[str(idx)] = compute_feature_distributions(
                training_features[:, idx], n_bins=10,
            )
        logger.info("Drift stats computed for top %d features: %s", top_n, top_indices)
        return {
            "top_feature_indices": top_indices,
            "feature_distributions": distributions,
        }
    except Exception as e:
        logger.warning("Failed to compute drift stats: %s", e)
        return None
