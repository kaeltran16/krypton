"""PyTorch Dataset for candle sequence training."""

import numpy as np
import torch
from torch.utils.data import Dataset


class CandleDataset(Dataset):
    """Sliding-window dataset over candle feature sequences.

    Each sample is a (seq_len, n_features) window, labeled by the
    direction and SL/TP targets at the last candle in the window.
    """

    def __init__(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        seq_len: int = 50,
        noise_std: float = 0.0,
    ):
        self.features = torch.tensor(features, dtype=torch.float32)
        self.direction = torch.tensor(direction, dtype=torch.long)
        self.regression = torch.stack([
            torch.tensor(sl_atr, dtype=torch.float32),
            torch.tensor(tp1_atr, dtype=torch.float32),
            torch.tensor(tp2_atr, dtype=torch.float32),
        ], dim=1)
        self.seq_len = seq_len
        self.noise_std = noise_std

    def __len__(self):
        return len(self.features) - self.seq_len

    def __getitem__(self, idx):
        x = self.features[idx : idx + self.seq_len]
        if self.noise_std > 0:
            x = x + torch.randn_like(x) * self.noise_std
        target_idx = idx + self.seq_len - 1
        y_dir = self.direction[target_idx]
        y_reg = self.regression[target_idx]
        return x, y_dir, y_reg
