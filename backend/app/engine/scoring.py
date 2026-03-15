from math import exp


def _safe_exp(x: float) -> float:
    """Exp clamped to avoid OverflowError."""
    return exp(max(-500, min(500, x)))


def sigmoid_score(value: float, center: float = 0, steepness: float = 0.1, max_score: float = 1.0) -> float:
    """Bipolar: maps value to [-max_score, +max_score] via smooth S-curve.
    center produces 0. Values above center -> positive, below -> negative."""
    return max_score * (2 / (1 + _safe_exp(-steepness * (value - center))) - 1)


def sigmoid_scale(value: float, center: float = 0, steepness: float = 0.1) -> float:
    """Unipolar: maps value to [0, 1] via standard logistic curve.
    center produces 0.5. Used for magnitude scaling (e.g., ADX strength)."""
    return 1 / (1 + _safe_exp(-steepness * (value - center)))
