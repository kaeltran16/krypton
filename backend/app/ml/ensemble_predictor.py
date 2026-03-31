"""Ensemble inference for multiple SignalLSTM members."""

import json
import logging
import os
import time

import numpy as np
import torch

from app.ml.drift import DriftConfig, feature_drift_penalty
from app.ml.model import SignalLSTM
from app.ml.predictor import DIRECTION_MAP

logger = logging.getLogger(__name__)

_NEUTRAL_RESULT = {
    "direction": "NEUTRAL",
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
    "ensemble_disagreement": 0.0,
}


def _model_weight(
    age_days: float,
    fresh_days: float = 7.0,
    decay_days: float = 21.0,
    floor: float = 0.3,
) -> float:
    """Staleness decay for an ensemble member."""
    if age_days <= fresh_days:
        return 1.0
    elif age_days <= decay_days:
        span = decay_days - fresh_days
        return 1.0 - (age_days - fresh_days) / span * (1.0 - floor) if span > 0 else floor
    else:
        return floor


class EnsemblePredictor:
    """Loads N ensemble members and runs weighted inference."""

    def __init__(
        self,
        checkpoint_dir: str,
        ensemble_disagreement_scale: float = 8.0,
        stale_fresh_days: float = 7.0,
        stale_decay_days: float = 21.0,
        stale_floor: float = 0.3,
        confidence_cap_partial: float = 0.5,
        drift_config: DriftConfig | None = None,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._disagreement_scale = ensemble_disagreement_scale
        self._stale_fresh_days = stale_fresh_days
        self._stale_decay_days = stale_decay_days
        self._stale_floor = stale_floor
        self._confidence_cap_partial = confidence_cap_partial
        self._drift_config = drift_config or DriftConfig()

        config_path = os.path.join(checkpoint_dir, "ensemble_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self._expected_features = config.get("feature_names", [])
        self.flow_used = config.get("flow_used", False)
        self.regime_used = config.get("regime_used", False)
        self.btc_used = config.get("btc_used", False)
        self._drift_stats = config.get("drift_stats")

        self._feature_map = None
        self._available_features = None
        self._out_idx = None
        self._in_idx = None

        # Load member models
        self._models = []
        self._temperatures = []
        self._weights = []
        self._member_ages_days = []
        now = time.time()

        for member_info in config["members"]:
            idx = member_info["index"]
            pt_path = os.path.join(checkpoint_dir, f"ensemble_{idx}.pt")
            if not os.path.isfile(pt_path):
                logger.warning("Ensemble member %d checkpoint missing: %s", idx, pt_path)
                continue
            try:
                model = SignalLSTM(
                    input_size=config["input_size"],
                    hidden_size=config["hidden_size"],
                    num_layers=config["num_layers"],
                    dropout=config.get("dropout", 0.0),
                ).to(self.device)
                state_dict = torch.load(pt_path, map_location=self.device, weights_only=True)
                model.load_state_dict(state_dict)
                model.eval()

                age_days = (now - os.path.getmtime(pt_path)) / 86400
                weight = _model_weight(age_days, stale_fresh_days, stale_decay_days, stale_floor)

                self._models.append(model)
                self._temperatures.append(member_info.get("temperature", 1.0))
                self._weights.append(weight)
                self._member_ages_days.append(age_days)
            except Exception as e:
                logger.error("Failed to load ensemble member %d: %s", idx, e)

        self.n_members = len(self._models)
        if self.n_members == 0:
            logger.error("No ensemble members loaded from %s", checkpoint_dir)

    @property
    def stale_member_count(self) -> int:
        return sum(1 for w in self._weights if w <= self._stale_floor)

    @property
    def oldest_member_age_days(self) -> float:
        return max(self._member_ages_days) if self._member_ages_days else 0.0

    def set_available_features(self, names: list[str]):
        """Set feature names available at inference time."""
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
            logger.warning("Missing features for ensemble (filled with 0): %s", missing)

        out_idx = np.array([i for i, c in enumerate(raw_map) if c >= 0], dtype=np.intp)
        in_idx = np.array([c for c in raw_map if c >= 0], dtype=np.intp)
        valid = out_idx < self.input_size
        self._out_idx = out_idx[valid]
        self._in_idx = in_idx[valid]
        self._feature_map = raw_map

    def _map_features(self, features: np.ndarray) -> np.ndarray:
        if self._feature_map is None:
            if features.shape[1] > self.input_size:
                return features[:, :self.input_size]
            return features

        n_rows = features.shape[0]
        mapped = np.zeros((n_rows, self.input_size), dtype=np.float32)
        mapped[:, self._out_idx] = features[:, self._in_idx]
        return mapped

    def predict(self, features: np.ndarray) -> dict:
        """Run ensemble inference.

        Returns dict matching Predictor.predict() interface plus ensemble_disagreement.
        """
        if self.n_members == 0 or len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        features = self._map_features(features)
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        all_probs = []
        all_regs = []
        for model, temperature in zip(self._models, self._temperatures):
            with torch.no_grad():
                dir_logits, reg_out = model(x)
                probs = torch.softmax(dir_logits / temperature, dim=1).squeeze(0).cpu().numpy()
                all_probs.append(probs)
                all_regs.append(reg_out.squeeze(0).cpu().numpy())

        all_probs = np.array(all_probs)
        all_regs = np.array(all_regs)
        weights = np.array(self._weights)
        weights = weights / weights.sum()

        # Weighted mean
        mean_probs = np.average(all_probs, axis=0, weights=weights)
        mean_reg = np.average(all_regs, axis=0, weights=weights)

        # Weighted disagreement
        diff = all_probs - mean_probs[None, :]
        disagreement = float(np.average((diff ** 2).mean(axis=1), weights=weights))

        direction_idx = int(np.argmax(mean_probs))
        raw_confidence = float(mean_probs[direction_idx])

        uncertainty_penalty = min(1.0, disagreement * self._disagreement_scale)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence *= (1.0 - drift_pen)

        # Cap confidence for partial ensembles
        if self.n_members == 2:
            confidence = min(confidence, self._confidence_cap_partial)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "ensemble_disagreement": disagreement,
            "drift_penalty": drift_pen,
        }
