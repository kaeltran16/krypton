"""Inference wrapper for trained SignalLSTM model."""

import json
import logging
import os

import numpy as np
import torch

from app.ml.model import SignalLSTM

logger = logging.getLogger(__name__)

DIRECTION_MAP = {0: "NEUTRAL", 1: "LONG", 2: "SHORT"}

_NEUTRAL_RESULT = {
    "direction": "NEUTRAL",
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
}


class Predictor:
    """Loads a trained model checkpoint and runs inference."""

    def __init__(self, checkpoint_path: str):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Load config from JSON sidecar (avoids weights_only restrictions)
        config_path = os.path.join(os.path.dirname(checkpoint_path), "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self.flow_used = config.get("flow_used", False)
        self.regime_used = config.get("regime_used", False)
        self.btc_used = config.get("btc_used", False)

        # Detect stale models from pre-expansion layout (input_size 16-23)
        self._stale = False
        if 16 <= self.input_size <= 23:
            logger.warning(
                "Model %s has input_size=%d (pre-expansion layout), needs retraining",
                os.path.basename(os.path.dirname(checkpoint_path)),
                self.input_size,
            )
            self._stale = True
            return  # skip loading weights for stale model

        self.model = SignalLSTM(
            input_size=config["input_size"],
            hidden_size=config["hidden_size"],
            num_layers=config["num_layers"],
            dropout=config.get("dropout", 0.0),
        ).to(self.device)

        # Load weights only — safe and fast
        state_dict = torch.load(checkpoint_path, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def predict(self, features: np.ndarray) -> dict:
        """Run inference on a feature matrix.

        Args:
            features: (n_candles, n_features) array. Uses last seq_len rows.

        Returns:
            dict with direction, confidence, sl_atr, tp1_atr, tp2_atr.
        """
        if self._stale:
            return dict(_NEUTRAL_RESULT)

        if len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        # Truncate features to match model's expected input_size
        if features.shape[1] > self.input_size:
            features = features[:, :self.input_size]

        # Take last seq_len candles
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        with torch.no_grad():
            dir_logits, reg_out = self.model(x)

        probs = torch.softmax(dir_logits, dim=1).squeeze(0).cpu().numpy()
        reg = reg_out.squeeze(0).cpu().numpy()

        direction_idx = int(np.argmax(probs))
        confidence = float(probs[direction_idx])

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(reg[0]),
            "tp1_atr": float(reg[1]),
            "tp2_atr": float(reg[2]),
        }
