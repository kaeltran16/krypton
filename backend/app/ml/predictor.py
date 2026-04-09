"""Inference wrapper for trained SignalLSTM model."""

import json
import logging
import os

import numpy as np
import torch
import torch.nn as nn

from app.ml.drift import DriftConfig, feature_drift_penalty
from app.ml.model import SignalLSTM
from app.ml.utils import (
    NEUTRAL_RESULT, FeatureMapper,
    regression_result, sigmoid_confidence,
)

logger = logging.getLogger(__name__)

MC_DROPOUT_PASSES = 5


class Predictor:
    """Inference wrapper for SignalLSTM regression model."""

    def __init__(
        self,
        checkpoint_path: str,
        max_age_days: int = 14,
        drift_config: DriftConfig | None = None,
        standardization_stats: dict | None = None,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._max_confidence = 1.0
        self._drift_config = drift_config or DriftConfig()
        self._std_stats = standardization_stats

        config_path = os.path.join(os.path.dirname(checkpoint_path), "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self.flow_used = config.get("flow_used", False)
        self.regime_used = config.get("regime_used", False)
        self.btc_used = config.get("btc_used", False)
        self._drift_stats = config.get("drift_stats")

        self._mapper = FeatureMapper(self.input_size, config.get("feature_names", []))

        import time as _time
        file_age_days = (_time.time() - os.path.getmtime(checkpoint_path)) / 86400
        if file_age_days > max_age_days:
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

    def predict(self, features: np.ndarray) -> dict:
        if len(features) < self.seq_len:
            return dict(NEUTRAL_RESULT, mc_variance=0.0)

        features = self._mapper.map_features(features)
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        # MC Dropout: enable only Dropout layers, not BatchNorm
        self.model.eval()
        for m in self.model.modules():
            if isinstance(m, nn.Dropout):
                m.train()

        all_returns = []
        all_regs = []
        for _ in range(MC_DROPOUT_PASSES):
            with torch.no_grad():
                return_pred, reg_out = self.model(x)
                all_returns.append(return_pred.squeeze().cpu().item())
                all_regs.append(reg_out.squeeze(0).cpu().numpy())

        self.model.eval()

        mean_return = float(np.mean(all_returns))
        mean_reg = np.mean(all_regs, axis=0)
        mc_variance = float(np.var(all_returns))

        result = regression_result(mean_return, mean_reg)

        uncertainty = np.sqrt(mc_variance)
        raw_confidence = sigmoid_confidence(mean_return, uncertainty)

        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence = raw_confidence * (1.0 - drift_pen)
        confidence = min(confidence, self._max_confidence)

        result["confidence"] = confidence
        result["mc_variance"] = mc_variance
        result["drift_penalty"] = drift_pen
        return result
