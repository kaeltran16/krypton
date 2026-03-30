"""LightGBM regime classifier — train, predict, persistence."""

import json
import logging
import os
import time

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from app.engine.regime_labels import LABEL_MAP

logger = logging.getLogger(__name__)

# Reverse map: int → name
_IDX_TO_NAME = dict(LABEL_MAP)
# Regime names in class order
_CLASS_NAMES = [_IDX_TO_NAME[i] for i in range(4)]

MIN_TRAINING_SAMPLES = 500
MIN_MACRO_F1 = 0.65


def build_regime_features(
    df: pd.DataFrame,
    flow: list[dict] | None = None,
    ensemble_disagreement: list[float] | None = None,
) -> tuple[np.ndarray, list[str]]:
    """Build feature matrix for regime classification.

    Args:
        df: OHLCV DataFrame.
        flow: Optional order flow dicts with funding_rate, oi_change_pct.
        ensemble_disagreement: Optional per-candle disagreement values.

    Returns:
        (features array, feature names list)
    """
    n = len(df)
    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)
    volume = df["volume"].values.astype(np.float64)

    # ATR
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    atr_pct = np.where(close > 0, atr / close, 0.0)

    # ADX (simplified: directional movement index)
    up_move = high - np.roll(high, 1)
    down_move = np.roll(low, 1) - low
    up_move[0] = 0
    down_move[0] = 0
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    smoothed_tr = pd.Series(tr).ewm(span=14, adjust=False).mean().values
    smoothed_plus = pd.Series(plus_dm).ewm(span=14, adjust=False).mean().values
    smoothed_minus = pd.Series(minus_dm).ewm(span=14, adjust=False).mean().values
    plus_di = np.where(smoothed_tr > 0, smoothed_plus / smoothed_tr * 100, 0.0)
    minus_di = np.where(smoothed_tr > 0, smoothed_minus / smoothed_tr * 100, 0.0)
    dx = np.where(plus_di + minus_di > 0, np.abs(plus_di - minus_di) / (plus_di + minus_di) * 100, 0.0)
    adx = pd.Series(dx).ewm(span=14, adjust=False).mean().values

    # Bollinger width
    sma20 = pd.Series(close).rolling(20, min_periods=1).mean().values
    std20 = pd.Series(close).rolling(20, min_periods=1).std(ddof=0).values
    bb_width = np.where(sma20 > 0, (2 * std20) / sma20, 0.0)

    # Deltas
    adx_delta_5 = adx - np.roll(adx, 5)
    adx_delta_5[:5] = 0
    adx_delta_10 = adx - np.roll(adx, 10)
    adx_delta_10[:10] = 0
    bb_width_delta_5 = bb_width - np.roll(bb_width, 5)
    bb_width_delta_5[:5] = 0
    atr_pct_delta_5 = atr_pct - np.roll(atr_pct, 5)
    atr_pct_delta_5[:5] = 0

    # OBV slope (volume trend)
    obv = np.cumsum(np.where(np.diff(close, prepend=close[0]) > 0, volume, -volume))
    vol_trend = np.zeros(n)
    for i in range(10, n):
        y = obv[i - 10:i]
        x = np.arange(10, dtype=np.float64)
        vol_trend[i] = np.polyfit(x, y, 1)[0]
    # Normalize
    vol_std = np.std(vol_trend[10:]) if n > 10 else 1.0
    if vol_std > 0:
        vol_trend = vol_trend / vol_std

    features_list = [adx, adx_delta_5, adx_delta_10, bb_width, bb_width_delta_5,
                     atr_pct, atr_pct_delta_5, vol_trend]
    names = ["adx", "adx_delta_5", "adx_delta_10", "bb_width", "bb_width_delta_5",
             "atr_pct", "atr_pct_delta_5", "volume_trend"]

    # Optional flow features
    if flow and len(flow) == n:
        funding = np.array([f.get("funding_rate", 0.0) or 0.0 for f in flow], dtype=np.float64)
        funding_delta = funding - np.roll(funding, 5)
        funding_delta[:5] = 0
        oi_change = np.array([f.get("oi_change_pct", 0.0) or 0.0 for f in flow], dtype=np.float64)
        features_list.extend([funding_delta, oi_change])
        names.extend(["funding_rate_change", "oi_change_pct"])

    # Optional ensemble disagreement
    if ensemble_disagreement and len(ensemble_disagreement) == n:
        features_list.append(np.array(ensemble_disagreement, dtype=np.float64))
        names.append("ensemble_disagreement")

    result = np.column_stack(features_list).astype(np.float32)
    # Replace NaN with 0
    result = np.nan_to_num(result, nan=0.0)
    return result, names


class RegimeClassifier:
    """LightGBM 4-class regime classifier."""

    def __init__(self):
        self._model = None
        self._feature_names = None
        self._trained_at = None

    def train(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        feature_names: list[str],
    ) -> dict:
        """Train the classifier. Returns metrics dict."""
        from datetime import datetime, timezone

        n = len(features)
        # Holdout split (last 20%)
        split = int(n * 0.8)
        X_train, X_test = features[:split], features[split:]
        y_train, y_test = labels[:split], labels[split:]

        self._model = lgb.LGBMClassifier(
            objective="multiclass",
            num_class=4,
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            verbose=-1,
        )
        self._model.fit(X_train, y_train)
        self._feature_names = feature_names
        self._trained_at = datetime.now(timezone.utc).isoformat()

        # Compute metrics on holdout
        y_pred = self._model.predict(X_test)
        accuracy = float((y_pred == y_test).mean())

        # Per-class precision, recall, F1
        per_class = {}
        f1s = []
        for cls_id, cls_name in _IDX_TO_NAME.items():
            tp = int(((y_pred == cls_id) & (y_test == cls_id)).sum())
            fp = int(((y_pred == cls_id) & (y_test != cls_id)).sum())
            fn = int(((y_pred != cls_id) & (y_test == cls_id)).sum())
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            per_class[cls_name] = {"precision": prec, "recall": rec, "f1": f1}
            f1s.append(f1)

        macro_f1 = float(np.mean(f1s))

        return {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "per_class": per_class,
            "n_train": len(y_train),
            "n_test": len(y_test),
        }

    def _align_features(self, features: np.ndarray, feature_names: list[str] | None) -> np.ndarray:
        """Align input features to match training feature order.

        If the model was trained with 11 features (including flow + disagreement)
        but only 8 base features are available at inference, missing features are
        filled with 0.
        """
        if self._feature_names is None or feature_names is None:
            return features
        if feature_names == self._feature_names:
            return features

        name_to_idx = {n: i for i, n in enumerate(feature_names)}
        row = features[0:1] if features.ndim == 2 else features.reshape(1, -1)
        aligned = np.zeros((1, len(self._feature_names)), dtype=np.float32)
        for i, name in enumerate(self._feature_names):
            src_idx = name_to_idx.get(name, -1)
            if src_idx >= 0 and src_idx < row.shape[1]:
                aligned[0, i] = row[0, src_idx]
        return aligned

    def predict_proba(self, features: np.ndarray, feature_names: list[str] | None = None) -> dict:
        """Predict regime probabilities for a single sample (or first row).

        Args:
            features: Feature array (1D or 2D).
            feature_names: Optional feature names for alignment. If the model
                was trained with more features than provided, missing ones are
                filled with 0.

        Returns dict with trending/ranging/volatile/steady probabilities.
        """
        if self._model is None:
            raise RuntimeError("Classifier not trained or loaded")
        if features.ndim == 1:
            features = features.reshape(1, -1)
        features = self._align_features(features, feature_names)
        probs = self._model.predict_proba(features[0:1])[0]
        return {name: float(probs[i]) for i, name in enumerate(_CLASS_NAMES)}

    def save(self, directory: str):
        """Save model + config to directory."""
        os.makedirs(directory, exist_ok=True)
        joblib.dump(self._model, os.path.join(directory, "regime_classifier.joblib"))

        config = {
            "feature_names": self._feature_names,
            "trained_at": self._trained_at,
            "n_classes": 4,
            "class_names": _CLASS_NAMES,
        }
        with open(os.path.join(directory, "regime_config.json"), "w") as f:
            json.dump(config, f, indent=2)

    @classmethod
    def load(cls, directory: str) -> "RegimeClassifier":
        """Load a saved classifier."""
        obj = cls()
        obj._model = joblib.load(os.path.join(directory, "regime_classifier.joblib"))
        config_path = os.path.join(directory, "regime_config.json")
        with open(config_path) as f:
            config = json.load(f)
        obj._feature_names = config.get("feature_names")
        obj._trained_at = config.get("trained_at")
        return obj

    @property
    def age_days(self) -> int | None:
        """Days since model was trained, or None if unknown."""
        from datetime import datetime, timezone
        if not self._trained_at:
            return None
        try:
            trained = datetime.fromisoformat(self._trained_at)
            return (datetime.now(timezone.utc) - trained).days
        except (ValueError, TypeError):
            return None

    def is_stale(self, max_age_days: int = 30) -> bool:
        """Check if model is older than max_age_days."""
        age = self.age_days
        return age is None or age > max_age_days
