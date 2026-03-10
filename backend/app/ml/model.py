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

        # Multi-scale temporal pooling: average last 5, 10, 25 steps
        self.pool_windows = [5, 10, 25]
        # Projects concatenated [attention_ctx + 3 pooled vectors] back to hidden_size
        self.scale_proj = nn.Linear(hidden_size * (1 + len(self.pool_windows)), hidden_size)

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
        # BatchNorm1d expects (batch, features, seq_len), so transpose
        x = self.input_bn(x.transpose(1, 2)).transpose(1, 2)

        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden)
        seq_len = lstm_out.size(1)

        # Attention context
        attn_ctx = self.attention(lstm_out)  # (batch, hidden)

        # Multi-scale mean pooling over last N steps (clamped to seq_len)
        pools = [attn_ctx]
        for w in self.pool_windows:
            w_clamped = min(w, seq_len)
            pooled = lstm_out[:, -w_clamped:, :].mean(dim=1)  # (batch, hidden)
            pools.append(pooled)

        context = self.scale_proj(torch.cat(pools, dim=1))  # (batch, hidden)
        context = self.dropout(context)

        dir_logits = self.cls_head(context)
        reg_out = self.reg_head(context)

        return dir_logits, reg_out
