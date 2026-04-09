"""PyTorch Dataset for candle sequence training."""

import numpy as np
import torch
from torch.utils.data import Dataset


class CandleDataset(Dataset):
    """Sliding-window dataset for regression targets.

    Only windows where the target candle has valid=True are included.
    """

    def __init__(
        self,
        features: np.ndarray,
        forward_return: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        valid: np.ndarray,
        seq_len: int = 50,
        noise_std: float = 0.0,
    ):
        self.features = torch.tensor(features, dtype=torch.float32)
        self.forward_return = torch.tensor(forward_return, dtype=torch.float32)
        self.regression = torch.stack([
            torch.tensor(sl_atr, dtype=torch.float32),
            torch.tensor(tp1_atr, dtype=torch.float32),
            torch.tensor(tp2_atr, dtype=torch.float32),
        ], dim=1)
        self.seq_len = seq_len
        self.noise_std = noise_std

        # Precompute valid indices: windows where target candle is valid
        self._valid_indices = np.where(valid[seq_len - 1:])[0]

    def __len__(self):
        return len(self._valid_indices)

    def __getitem__(self, idx):
        real_idx = self._valid_indices[idx]
        x = self.features[real_idx : real_idx + self.seq_len]
        if self.noise_std > 0:
            x = x + torch.randn_like(x) * self.noise_std
        target_idx = real_idx + self.seq_len - 1
        y_return = self.forward_return[target_idx]
        y_reg = self.regression[target_idx]
        return x, y_return, y_reg
