"""Ensemble inference for multiple SignalLSTM members."""

import json
import logging
import os
import time

import numpy as np
import torch

from app.ml.drift import DriftConfig, feature_drift_penalty
from app.ml.model import SignalLSTM
from app.ml.utils import (
    NEUTRAL_RESULT, FeatureMapper,
    regression_result, sigmoid_confidence,
)

logger = logging.getLogger(__name__)


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
    """Ensemble inference for SignalLSTM regression members."""

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
        self._stale_floor = stale_floor
        self._confidence_cap_partial = confidence_cap_partial
        self._drift_config = drift_config or DriftConfig()

        config_path = os.path.join(checkpoint_dir, "ensemble_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self.flow_used = config.get("flow_used", False)
        self.regime_used = config.get("regime_used", False)
        self.btc_used = config.get("btc_used", False)
        self._drift_stats = config.get("drift_stats")

        self._mapper = FeatureMapper(self.input_size, config.get("feature_names", []))

        self._models = []
        self._weights = []
        self._member_ages_days = []
        now = time.time()

        for member_info in config["members"]:
            if member_info.get("excluded", False):
                continue
            idx = member_info["index"]
            pt_path = os.path.join(checkpoint_dir, f"ensemble_{idx}.pt")
            if not os.path.isfile(pt_path):
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
                self._weights.append(weight)
                self._member_ages_days.append(age_days)
            except Exception as e:
                logger.error("Failed to load ensemble member %d: %s", idx, e)

        self.n_members = len(self._models)

    @property
    def _feature_map(self):
        return self._mapper._feature_map

    @property
    def _n_missing_features(self):
        return self._mapper._n_missing_features

    @property
    def _n_expected_features(self):
        return self._mapper._n_expected_features

    def set_available_features(self, names: list[str]):
        self._mapper.set_available_features(names)

    def _map_features(self, features: np.ndarray) -> np.ndarray:
        return self._mapper.map_features(features)

    @property
    def stale_member_count(self) -> int:
        return sum(1 for w in self._weights if w <= self._stale_floor)

    @property
    def oldest_member_age_days(self) -> float:
        return max(self._member_ages_days) if self._member_ages_days else 0.0

    def predict(self, features: np.ndarray) -> dict:
        if self.n_members == 0 or len(features) < self.seq_len:
            return dict(NEUTRAL_RESULT, ensemble_disagreement=0.0)

        features = self._mapper.map_features(features)
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        all_returns = []
        all_regs = []
        for model in self._models:
            with torch.no_grad():
                return_pred, reg_out = model(x)
                all_returns.append(return_pred.squeeze().cpu().item())
                all_regs.append(reg_out.squeeze(0).cpu().numpy())

        all_returns = np.array(all_returns)
        all_regs = np.array(all_regs)
        weights = np.array(self._weights)
        weights = weights / weights.sum()

        mean_return = float(np.average(all_returns, weights=weights))
        mean_reg = np.average(all_regs, axis=0, weights=weights)

        diff = all_returns - mean_return
        disagreement = float(np.average(diff ** 2, weights=weights))

        result = regression_result(mean_return, mean_reg)

        uncertainty = np.sqrt(disagreement)
        raw_confidence = sigmoid_confidence(mean_return, uncertainty)

        uncertainty_penalty = min(1.0, disagreement * self._disagreement_scale)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence *= (1.0 - drift_pen)

        if self.n_members == 2:
            confidence = min(confidence, self._confidence_cap_partial)

        result["confidence"] = confidence
        result["ensemble_disagreement"] = disagreement
        result["drift_penalty"] = drift_pen
        return result
