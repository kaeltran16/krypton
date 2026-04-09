"""LSTM model for forward return prediction and SL/TP regression."""

import torch
import torch.nn as nn


class TemporalAttention(nn.Module):
    """Attention layer over LSTM time steps."""

    def __init__(self, hidden_size: int):
        super().__init__()
        self.attention = nn.Linear(hidden_size, 1)

    def forward(self, lstm_output: torch.Tensor) -> torch.Tensor:
        # lstm_output: (batch, seq_len, hidden_size)
        scores = self.attention(lstm_output).squeeze(-1)  # (batch, seq_len)
        weights = torch.softmax(scores, dim=1).unsqueeze(-1)  # (batch, seq_len, 1)
        context = (lstm_output * weights).sum(dim=1)  # (batch, hidden_size)
        return context


class SignalLSTM(nn.Module):
    """Regression-first LSTM: forward return prediction + SL/TP regression."""

    def __init__(
        self,
        input_size: int = 24,
        hidden_size: int = 96,
        num_layers: int = 2,
        dropout: float = 0.3,
        num_regression: int = 3,
    ):
        super().__init__()
        self.input_bn = nn.BatchNorm1d(input_size)
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
        )
        self.attention = TemporalAttention(hidden_size)
        self.dropout = nn.Dropout(dropout)

        self.pool_windows = [5, 10, 25]
        self.scale_proj = nn.Linear(hidden_size * (1 + len(self.pool_windows)), hidden_size)

        # Primary head: predicted ATR-normalized forward return (no activation)
        self.return_head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, 1),
        )

        # Secondary head: SL, TP1, TP2 (as ATR multiples, non-negative)
        self.reg_head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, num_regression),
            nn.ReLU(),
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass.

        Args:
            x: (batch, seq_len, input_size) tensor of features.

        Returns:
            return_pred: (batch, 1) predicted ATR-normalized forward return.
            reg_out: (batch, 3) predicted SL/TP distances in ATR units.
        """
        x = self.input_bn(x.transpose(1, 2)).transpose(1, 2)

        lstm_out, _ = self.lstm(x)
        seq_len = lstm_out.size(1)

        attn_ctx = self.attention(lstm_out)

        pools = [attn_ctx]
        for w in self.pool_windows:
            w_clamped = min(w, seq_len)
            pooled = lstm_out[:, -w_clamped:, :].mean(dim=1)
            pools.append(pooled)

        context = self.scale_proj(torch.cat(pools, dim=1))
        context = self.dropout(context)

        return_pred = self.return_head(context)
        reg_out = self.reg_head(context)

        return return_pred, reg_out
