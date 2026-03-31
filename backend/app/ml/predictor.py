"""Inference wrapper for trained SignalLSTM model."""

import json
import logging
import os

import numpy as np
import torch
import torch.nn as nn

from app.ml.drift import DriftConfig, feature_drift_penalty
from app.ml.model import SignalLSTM

logger = logging.getLogger(__name__)

DIRECTION_MAP = {0: "NEUTRAL", 1: "LONG", 2: "SHORT"}

_NEUTRAL_RESULT = {
    "direction": "NEUTRAL",
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
    "mc_variance": 0.0,
}

MC_DROPOUT_PASSES = 5


class Predictor:
    """Loads a trained model checkpoint and runs inference."""

    def __init__(
        self,
        checkpoint_path: str,
        max_age_days: int = 14,
        drift_config: DriftConfig | None = None,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._max_confidence = 1.0
        self._drift_config = drift_config or DriftConfig()

        # Load config from JSON sidecar (avoids weights_only restrictions)
        config_path = os.path.join(os.path.dirname(checkpoint_path), "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self.flow_used = config.get("flow_used", False)
        self.regime_used = config.get("regime_used", False)
        self.btc_used = config.get("btc_used", False)
        self._temperature = config.get("temperature", 1.0)
        self._expected_features = config.get("feature_names", [])
        if self._expected_features and len(self._expected_features) != self.input_size:
            logger.warning(
                "Config inconsistency in %s: input_size=%d but feature_names has %d entries — truncating",
                os.path.basename(os.path.dirname(checkpoint_path)),
                self.input_size, len(self._expected_features),
            )
            self._expected_features = self._expected_features[:self.input_size]
        self._feature_map = None
        self._available_features = None
        self._drift_stats = config.get("drift_stats")

        # Check checkpoint age
        import time as _time
        file_age_days = (_time.time() - os.path.getmtime(checkpoint_path)) / 86400
        if file_age_days > max_age_days:
            logger.warning(
                "Model %s is %.1f days old (max %d), confidence capped at 0.3",
                os.path.basename(os.path.dirname(checkpoint_path)),
                file_age_days, max_age_days,
            )
            self._max_confidence = 0.3

        self.model = SignalLSTM(
            input_size=config["input_size"],
            hidden_size=config["hidden_size"],
            num_layers=config["num_layers"],
            dropout=config.get("dropout", 0.0),
        ).to(self.device)

        state_dict = torch.load(checkpoint_path, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def set_available_features(self, names: list[str]):
        """Set the feature names available at inference time.

        Builds a mapping from available feature columns to the model's expected layout.
        """
        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            return

        available_idx = {name: i for i, name in enumerate(names)}
        raw_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            raw_map.append(idx)
            if idx == -1:
                missing.append(name)

        if missing:
            logger.warning("Missing features for model (filled with 0): %s", missing)

        # Precompute numpy index arrays for vectorized gather in _map_features
        out_idx = np.array([i for i, c in enumerate(raw_map) if c >= 0], dtype=np.intp)
        in_idx = np.array([c for c in raw_map if c >= 0], dtype=np.intp)
        valid = out_idx < self.input_size
        self._out_idx = out_idx[valid]
        self._in_idx = in_idx[valid]
        self._feature_map = raw_map

    def _map_features(self, features: np.ndarray) -> np.ndarray:
        """Remap feature columns to match model's expected layout."""
        if self._feature_map is None:
            if features.shape[1] > self.input_size:
                return features[:, :self.input_size]
            return features

        n_rows = features.shape[0]
        mapped = np.zeros((n_rows, self.input_size), dtype=np.float32)
        mapped[:, self._out_idx] = features[:, self._in_idx]
        return mapped

    def predict(self, features: np.ndarray) -> dict:
        """Run inference on a feature matrix.

        Args:
            features: (n_candles, n_features) array. Uses last seq_len rows.

        Returns:
            dict with direction, confidence, sl_atr, tp1_atr, tp2_atr, mc_variance.
        """
        if len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        # Feature mapping by name (if available)
        features = self._map_features(features)

        # Take last seq_len candles
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        temperature = self._temperature

        # Only enable Dropout layers, NOT BatchNorm
        self.model.eval()
        for m in self.model.modules():
            if isinstance(m, nn.Dropout):
                m.train()

        all_probs = []
        all_regs = []
        for _ in range(MC_DROPOUT_PASSES):
            with torch.no_grad():
                dir_logits, reg_out = self.model(x)
                probs = torch.softmax(dir_logits / temperature, dim=1).squeeze(0).cpu().numpy()
                all_probs.append(probs)
                all_regs.append(reg_out.squeeze(0).cpu().numpy())

        self.model.eval()  # restore all layers to eval

        mean_probs = np.mean(all_probs, axis=0)
        mean_reg = np.mean(all_regs, axis=0)

        # Epistemic uncertainty: variance across passes
        prob_variance = float(np.mean(np.var(all_probs, axis=0)))

        direction_idx = int(np.argmax(mean_probs))
        raw_confidence = float(mean_probs[direction_idx])

        # Reduce confidence proportionally to uncertainty
        uncertainty_penalty = min(1.0, prob_variance * 10)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence *= (1.0 - drift_pen)

        # Cap confidence for stale models
        confidence = min(confidence, self._max_confidence)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "mc_variance": prob_variance,
            "drift_penalty": drift_pen,
        }
