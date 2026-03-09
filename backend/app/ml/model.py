"""LSTM model for trade direction prediction and SL/TP regression."""

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
    """Multi-head LSTM: direction classification + SL/TP regression."""

    def __init__(
        self,
        input_size: int = 15,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.3,
        num_classes: int = 3,
        num_regression: int = 3,
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
        )
        self.attention = TemporalAttention(hidden_size)
        self.dropout = nn.Dropout(dropout)

        # Classification head: NEUTRAL / LONG / SHORT
        self.cls_head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, num_classes),
        )

        # Regression head: SL, TP1, TP2 (as ATR multiples)
        self.reg_head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, num_regression),
            nn.ReLU(),  # distances must be non-negative
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass.

        Args:
            x: (batch, seq_len, input_size) tensor of features.

        Returns:
            dir_logits: (batch, 3) raw logits for direction.
            reg_out: (batch, 3) predicted SL/TP distances in ATR units.
        """
        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden)
        context = self.attention(lstm_out)  # (batch, hidden)
        context = self.dropout(context)

        dir_logits = self.cls_head(context)
        reg_out = self.reg_head(context)

        return dir_logits, reg_out
