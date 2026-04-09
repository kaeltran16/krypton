# ML V1 Classification Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all v1 classification ML code, rename v2 regression classes to canonical names, and fix API training defaults that cause best_epoch=1.

**Architecture:** Pure deletion + rename refactor. No new logic. The v2 regression pipeline stays identical — we just remove the v1 code that's no longer used and rename "Regression*" prefixes away since v2 is the only version.

**Tech Stack:** Python, PyTorch, FastAPI, pytest

---

### Task 1: Strip v1 from model.py

**Files:**
- Modify: `backend/app/ml/model.py`

- [ ] **Step 1: Remove SignalLSTM (v1) and rename SignalLSTMv2 → SignalLSTM**

Replace the entire file with:

```python
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
```

- [ ] **Step 2: Run model tests to verify**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_model.py -v`
Expected: Tests will fail because they still import `SignalLSTMv2` — that's fixed in Task 7.

---

### Task 2: Strip v1 from dataset.py

**Files:**
- Modify: `backend/app/ml/dataset.py`

- [ ] **Step 1: Remove CandleDataset (v1) and rename RegressionDataset → CandleDataset**

Replace the entire file with:

```python
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

        # Precompute valid indices: windows where target is valid
        self._valid_indices = []
        n = len(features)
        for idx in range(n - seq_len):
            target_idx = idx + seq_len - 1
            if valid[target_idx]:
                self._valid_indices.append(idx)

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
```

- [ ] **Step 2: Verify (tests will be updated in Task 7)**

---

### Task 3: Strip v1 from labels.py

**Files:**
- Modify: `backend/app/ml/labels.py`

- [ ] **Step 1: Remove generate_labels/LabelConfig, rename regression functions**

Replace the entire file with:

```python
"""Label generation for ML training — ATR-normalized forward returns."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TargetConfig:
    horizon: int = 48          # candles to look forward (48 for 15m = 12h)
    noise_floor: float = 0.3   # minimum |fwd_return| in ATR units for SL/TP training
    atr_epsilon: float = 1e-6  # minimum atr_pct to avoid division by zero


def generate_targets(
    candles: pd.DataFrame,
    config: TargetConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate ATR-normalized forward return and SL/TP regression targets.

    Returns:
        Tuple of (forward_return, sl_atr, tp1_atr, tp2_atr, valid_mask).
        forward_return: ATR-normalized return over horizon (float32).
        sl_atr, tp1_atr, tp2_atr: ATR-unit distances (0 for noise-floor samples).
        valid_mask: bool array — False for warmup, end-of-series, and zero-ATR rows.
    """
    if config is None:
        config = TargetConfig()

    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)

    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values

    # Compute ATR
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    atr_pct = atr / np.where(close > 0, close, 1.0)

    forward_return = np.zeros(n, dtype=np.float32)
    sl_atr = np.zeros(n, dtype=np.float32)
    tp1_atr = np.zeros(n, dtype=np.float32)
    tp2_atr = np.zeros(n, dtype=np.float32)
    valid = np.zeros(n, dtype=bool)

    for i in range(n - config.horizon):
        if atr_pct[i] < config.atr_epsilon:
            continue

        future_close = close[i + config.horizon]
        raw_return = (future_close - close[i]) / close[i]
        fwd = raw_return / atr_pct[i]
        forward_return[i] = fwd
        valid[i] = True

        # SL/TP only for significant moves
        if abs(fwd) >= config.noise_floor:
            future_high = high[i + 1 : i + 1 + config.horizon]
            future_low = low[i + 1 : i + 1 + config.horizon]
            atr_safe = max(atr[i], 1e-10)

            if fwd > 0:  # LONG-like
                mae = (close[i] - future_low.min()) / atr_safe
                mfe_median = np.median(future_high - close[i]) / atr_safe
                mfe_75 = np.percentile(future_high - close[i], 75) / atr_safe
            else:  # SHORT-like
                mae = (future_high.max() - close[i]) / atr_safe
                mfe_median = np.median(close[i] - future_low) / atr_safe
                mfe_75 = np.percentile(close[i] - future_low, 75) / atr_safe

            sl_atr[i] = max(mae, 0.5)
            tp1_atr[i] = max(mfe_median, 0.5)
            tp2_atr[i] = max(mfe_75, 1.0)

    return forward_return, sl_atr, tp1_atr, tp2_atr, valid
```

---

### Task 4: Strip v1 from data_loader.py

**Files:**
- Modify: `backend/app/ml/data_loader.py`

- [ ] **Step 1: Remove v1 prepare_training_data, rename regression version**

Replace the entire file with:

```python
"""Data loading and preparation for ML training."""

import numpy as np
import pandas as pd

from app.ml.features import (
    build_feature_matrix, compute_warmup_period, drop_warmup_rows,
    compute_standardization_stats, apply_standardization,
)
from app.ml.labels import generate_targets, TargetConfig


def prepare_training_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    target_config: TargetConfig | None = None,
    btc_candles: list[dict] | None = None,
    regime: list[dict] | None = None,
    trend_conviction: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    """Prepare features and regression targets for training.

    Returns:
        Tuple of (features, forward_return, sl_atr, tp1_atr, tp2_atr, valid, std_stats).
        Features are warmup-trimmed, winsorized, and z-score standardized.
    """
    df = pd.DataFrame(candles)
    btc_df = pd.DataFrame(btc_candles) if btc_candles else None

    features = build_feature_matrix(
        df, order_flow=order_flow, regime=regime,
        trend_conviction=trend_conviction, btc_candles=btc_df,
    )

    fwd, sl, tp1, tp2, valid = generate_targets(df, target_config)

    # Drop warmup rows
    warmup = compute_warmup_period(
        regime_used=regime is not None,
        btc_used=btc_candles is not None,
        flow_used=order_flow is not None,
    )
    features, offset = drop_warmup_rows(features, warmup)
    fwd = fwd[offset:]
    sl = sl[offset:]
    tp1 = tp1[offset:]
    tp2 = tp2[offset:]
    valid = valid[offset:]

    # Z-score standardize
    std_stats = compute_standardization_stats(features)
    features = apply_standardization(features, std_stats)

    return features, fwd, sl, tp1, tp2, valid, std_stats
```

---

### Task 5: Strip v1 from trainer.py

**Files:**
- Modify: `backend/app/ml/trainer.py`

- [ ] **Step 1: Remove v1 Trainer, FocalLoss, compute_class_weights, TrainConfig, _ENSEMBLE_SPLITS. Rename regression classes.**

Replace the entire file with the following. This keeps only the regression training code with renamed classes:

```python
"""Training loop for regression LSTM model."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from app.ml.dataset import CandleDataset
from app.ml.model import SignalLSTM
from app.ml.utils import directional_accuracy

logger = logging.getLogger(__name__)


# Walk-forward fold boundaries for 3-member ensemble
_WALKFORWARD_FOLDS = [
    (0.0, 0.60, 0.75),   # train [0%, 60%], val [60%, 75%]
    (0.0, 0.75, 0.90),   # train [0%, 75%], val [75%, 90%]
    (0.0, 0.90, 1.00),   # train [0%, 90%], val [90%, 100%]
]


@dataclass
class TrainConfig:
    epochs: int = 80
    batch_size: int = 128
    seq_len: int = 50
    hidden_size: int = 96
    num_layers: int = 2
    dropout: float = 0.3
    lr: float = 5e-4
    weight_decay: float = 1e-3
    reg_loss_weight: float = 0.3
    patience: int = 15
    min_epochs: int = 30
    warmup_epochs: int = 3
    noise_std: float = 0.02
    checkpoint_dir: str = "models"
    directional_accuracy_gate: float = 0.52
    prediction_std_gate: float = 0.01


class Trainer:
    """Trains SignalLSTM with Huber + SmoothL1 multi-task loss."""

    def __init__(self, config: TrainConfig):
        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def train_one_model(
        self,
        features: np.ndarray,
        forward_return: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        valid: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
        _skip_drift_stats: bool = False,
        _train_slice: tuple[int, int] | None = None,
        _val_slice: tuple[int, int] | None = None,
    ) -> dict:
        """Train a single regression model.

        Returns dict with val_huber_loss, directional_accuracy, best_epoch,
        prediction_std, version.
        """
        cfg = self.config
        input_size = features.shape[1]

        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(input_size)]

        n = len(features)

        # Determine train/val splits
        if _train_slice and _val_slice:
            t_start, t_end = _train_slice
            v_start, v_end = _val_slice
        else:
            split = int(n * 0.85)
            t_start, t_end = 0, split
            v_start, v_end = split, n

        train_ds = CandleDataset(
            features[t_start:t_end], forward_return[t_start:t_end],
            sl_atr[t_start:t_end], tp1_atr[t_start:t_end], tp2_atr[t_start:t_end],
            valid[t_start:t_end], seq_len=cfg.seq_len, noise_std=cfg.noise_std,
        )
        val_ds = CandleDataset(
            features[v_start:v_end], forward_return[v_start:v_end],
            sl_atr[v_start:v_end], tp1_atr[v_start:v_end], tp2_atr[v_start:v_end],
            valid[v_start:v_end], seq_len=cfg.seq_len,
        )

        if len(train_ds) < cfg.batch_size:
            raise ValueError(f"Training set too small: {len(train_ds)} samples")

        train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False) if len(val_ds) > 0 else None

        model = SignalLSTM(
            input_size=input_size,
            hidden_size=cfg.hidden_size,
            num_layers=cfg.num_layers,
            dropout=cfg.dropout,
        ).to(self.device)

        optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)

        warmup = cfg.warmup_epochs
        total = cfg.epochs

        def lr_lambda(epoch):
            if epoch < warmup:
                return (epoch + 1) / warmup
            progress = (epoch - warmup) / max(total - warmup, 1)
            return 0.5 * (1 + math.cos(math.pi * progress))

        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

        return_criterion = nn.HuberLoss(delta=1.0)
        reg_criterion = nn.SmoothL1Loss()

        best_val_loss = float("inf")
        best_epoch = 0
        epochs_without_improvement = 0

        os.makedirs(cfg.checkpoint_dir, exist_ok=True)

        avg_val_loss = None
        for epoch in range(cfg.epochs):
            model.train()
            epoch_loss = 0.0
            n_batches = 0
            for x, y_return, y_reg in train_loader:
                x = x.to(self.device)
                y_return = y_return.to(self.device)
                y_reg = y_reg.to(self.device)

                return_pred, reg_out = model(x)
                primary_loss = return_criterion(return_pred.squeeze(1), y_return)

                # Regression loss only for significant moves (sl > 0)
                has_sltp = y_reg[:, 0] > 0
                if has_sltp.any():
                    reg_loss = reg_criterion(reg_out[has_sltp], y_reg[has_sltp])
                else:
                    reg_loss = torch.tensor(0.0, device=self.device)

                loss = primary_loss + cfg.reg_loss_weight * reg_loss

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                epoch_loss += loss.item()
                n_batches += 1

            scheduler.step()

            # Validate
            if val_loader is not None:
                model.eval()
                val_loss = 0.0
                val_batches = 0
                with torch.no_grad():
                    for x, y_return, y_reg in val_loader:
                        x = x.to(self.device)
                        y_return = y_return.to(self.device)
                        y_reg = y_reg.to(self.device)

                        return_pred, reg_out = model(x)
                        primary_loss = return_criterion(return_pred.squeeze(1), y_return)
                        has_sltp = y_reg[:, 0] > 0
                        if has_sltp.any():
                            reg_loss = reg_criterion(reg_out[has_sltp], y_reg[has_sltp])
                        else:
                            reg_loss = torch.tensor(0.0, device=self.device)

                        val_loss += (primary_loss + cfg.reg_loss_weight * reg_loss).item()
                        val_batches += 1

                avg_val_loss = val_loss / max(val_batches, 1)

                if avg_val_loss < best_val_loss:
                    best_val_loss = avg_val_loss
                    best_epoch = epoch + 1
                    epochs_without_improvement = 0
                    torch.save(model.state_dict(), os.path.join(cfg.checkpoint_dir, "best_model.pt"))
                else:
                    epochs_without_improvement += 1
                    if (epoch + 1) >= cfg.min_epochs and epochs_without_improvement >= cfg.patience:
                        logger.info(f"Early stopping at epoch {epoch+1}")
                        break

            if progress_callback:
                progress_callback({
                    "epoch": epoch + 1, "total_epochs": cfg.epochs,
                    "train_loss": epoch_loss / max(n_batches, 1),
                    "val_loss": avg_val_loss if val_loader else None,
                })

        # Load best model and evaluate
        best_pt = os.path.join(cfg.checkpoint_dir, "best_model.pt")
        if os.path.exists(best_pt):
            model.load_state_dict(torch.load(best_pt, map_location=self.device, weights_only=True))

        dir_acc = 0.0
        pred_std = 0.0
        if val_loader is not None:
            model.eval()
            all_preds = []
            all_targets = []
            with torch.no_grad():
                for x, y_return, _ in val_loader:
                    x = x.to(self.device)
                    return_pred, _ = model(x)
                    all_preds.extend(return_pred.squeeze(1).cpu().numpy())
                    all_targets.extend(y_return.numpy())

            all_preds = np.array(all_preds)
            all_targets = np.array(all_targets)
            dir_acc = directional_accuracy(all_preds, all_targets)
            pred_std = float(all_preds.std())

        # Drift stats (uses regression-compatible permutation importance)
        drift_stats = None
        if not _skip_drift_stats and val_loader is not None:
            from app.ml.drift import compute_drift_stats
            drift_stats = compute_drift_stats(
                model, val_loader, features[t_start:t_end], input_size,
            )

        # Save config
        from datetime import datetime as _dt, timezone as _tz
        import json as _json
        version_tag = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
        config_meta = {
            "input_size": input_size,
            "hidden_size": cfg.hidden_size,
            "num_layers": cfg.num_layers,
            "dropout": cfg.dropout,
            "seq_len": cfg.seq_len,
            "model_version": "v2",
            "feature_names": feature_names,
        }
        if drift_stats:
            config_meta["drift_stats"] = drift_stats
        with open(os.path.join(cfg.checkpoint_dir, "model_config.json"), "w") as f:
            _json.dump(config_meta, f, indent=2)

        return {
            "val_huber_loss": best_val_loss,
            "directional_accuracy": dir_acc,
            "prediction_std": pred_std,
            "best_epoch": best_epoch,
            "version": version_tag,
        }

    def train_ensemble(
        self,
        features: np.ndarray,
        forward_return: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        valid: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
    ) -> dict:
        """Train 3-member walk-forward ensemble with quality gates."""
        import json as _json
        import shutil
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from datetime import datetime as _dt, timezone as _tz

        cfg = self.config
        n = len(features)

        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(features.shape[1])]

        staging_dir = os.path.join(cfg.checkpoint_dir, ".ensemble_staging")
        os.makedirs(staging_dir, exist_ok=True)

        def _train_member(idx, train_end_frac, val_end_frac):
            t_end = int(n * train_end_frac)
            v_end = int(n * val_end_frac)

            member_dir = os.path.join(staging_dir, f"member_{idx}")
            os.makedirs(member_dir, exist_ok=True)

            member_cfg = TrainConfig(
                epochs=cfg.epochs, batch_size=cfg.batch_size,
                seq_len=cfg.seq_len, hidden_size=cfg.hidden_size,
                num_layers=cfg.num_layers, dropout=cfg.dropout,
                lr=cfg.lr, weight_decay=cfg.weight_decay,
                reg_loss_weight=cfg.reg_loss_weight,
                patience=cfg.patience, min_epochs=cfg.min_epochs,
                warmup_epochs=cfg.warmup_epochs, noise_std=cfg.noise_std,
                checkpoint_dir=member_dir,
                directional_accuracy_gate=cfg.directional_accuracy_gate,
                prediction_std_gate=cfg.prediction_std_gate,
            )
            member_trainer = Trainer(member_cfg)
            try:
                result = member_trainer.train_one_model(
                    features, forward_return, sl_atr, tp1_atr, tp2_atr, valid,
                    progress_callback=progress_callback,
                    feature_names=feature_names,
                    _skip_drift_stats=True,
                    _train_slice=(0, t_end),
                    _val_slice=(t_end, v_end),
                )
            except ValueError as e:
                logger.warning("Ensemble member %d failed: %s", idx, e)
                return None

            # Quality gates
            excluded = False
            if result["directional_accuracy"] < cfg.directional_accuracy_gate:
                logger.warning(
                    "Member %d failed accuracy gate: %.3f < %.3f",
                    idx, result["directional_accuracy"], cfg.directional_accuracy_gate,
                )
                excluded = True
            if result["prediction_std"] < cfg.prediction_std_gate:
                logger.warning(
                    "Member %d failed prediction std gate: %.4f < %.4f",
                    idx, result["prediction_std"], cfg.prediction_std_gate,
                )
                excluded = True

            return {
                "index": idx,
                "trained_at": _dt.now(_tz.utc).isoformat(),
                "val_huber_loss": result["val_huber_loss"],
                "best_epoch": result["best_epoch"],
                "directional_accuracy": result["directional_accuracy"],
                "prediction_std": result["prediction_std"],
                "data_range": [0.0, val_end_frac],
                "excluded": excluded,
            }

        members = []
        with ThreadPoolExecutor(max_workers=len(_WALKFORWARD_FOLDS)) as pool:
            futures = {
                pool.submit(_train_member, idx, te, ve): idx
                for idx, (_, te, ve) in enumerate(_WALKFORWARD_FOLDS)
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    members.append(result)

        members.sort(key=lambda m: m["index"])

        active_members = [m for m in members if not m["excluded"]]
        if not active_members:
            logger.warning("All members failed quality gates — no model for this pair")
            shutil.rmtree(staging_dir, ignore_errors=True)
            return {"members": members, "n_members": 0}

        # Loss gate: exclude members with loss > 2x best
        best_loss = min(m["val_huber_loss"] for m in active_members)
        for m in members:
            if not m["excluded"] and m["val_huber_loss"] > 2 * best_loss:
                m["excluded"] = True
                logger.warning("Member %d excluded: loss %.4f > 2x best %.4f",
                               m["index"], m["val_huber_loss"], best_loss)

        active_members = [m for m in members if not m["excluded"]]

        # Copy active member checkpoints
        for m in active_members:
            idx = m["index"]
            src = os.path.join(staging_dir, f"member_{idx}", "best_model.pt")
            dst = os.path.join(cfg.checkpoint_dir, f"ensemble_{idx}.pt")
            shutil.copy2(src, dst)

        # Drift stats from first active member
        drift_stats = None
        first_active = active_members[0]
        first_pt = os.path.join(staging_dir, f"member_{first_active['index']}", "best_model.pt")
        if os.path.exists(first_pt):
            perm_model = SignalLSTM(
                input_size=features.shape[1], hidden_size=cfg.hidden_size,
                num_layers=cfg.num_layers, dropout=cfg.dropout,
            ).to(self.device)
            perm_model.load_state_dict(torch.load(first_pt, map_location=self.device, weights_only=True))
            perm_model.eval()

            val_start = int(n * 0.85)
            val_ds = CandleDataset(
                features[val_start:], forward_return[val_start:],
                sl_atr[val_start:], tp1_atr[val_start:], tp2_atr[val_start:],
                valid[val_start:], seq_len=cfg.seq_len,
            )
            if len(val_ds) > 0:
                val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False)
                from app.ml.drift import compute_drift_stats
                drift_stats = compute_drift_stats(
                    perm_model, val_loader, features[:val_start], features.shape[1],
                )

        # Write ensemble_config.json LAST
        # Note: flow_used/regime_used/btc_used are patched by api/ml.py after training
        ensemble_config = {
            "n_members": len(active_members),
            "input_size": features.shape[1],
            "hidden_size": cfg.hidden_size,
            "num_layers": cfg.num_layers,
            "dropout": cfg.dropout,
            "seq_len": cfg.seq_len,
            "model_version": "v2",
            "feature_names": feature_names,
            "members": members,  # includes excluded members for audit trail
        }
        if drift_stats:
            ensemble_config["drift_stats"] = drift_stats

        with open(os.path.join(cfg.checkpoint_dir, "ensemble_config.json"), "w") as f:
            _json.dump(ensemble_config, f, indent=2)

        shutil.rmtree(staging_dir, ignore_errors=True)

        return {"members": members, "n_members": len(active_members)}
```

---

### Task 6: Strip v1 from predictor.py, ensemble_predictor.py, drift.py

**Files:**
- Modify: `backend/app/ml/predictor.py`
- Modify: `backend/app/ml/ensemble_predictor.py`
- Modify: `backend/app/ml/drift.py`

- [ ] **Step 1: Rewrite predictor.py — remove v1 Predictor, rename RegressionPredictor → Predictor**

Replace the entire file with:

```python
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
    "ml_score": 0.0,
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
    "mc_variance": 0.0,
}

MC_DROPOUT_PASSES = 5

SCORE_SCALE = 40  # ±2.5 ATR saturates at ±100


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
        self._expected_features = config.get("feature_names", [])
        self._feature_map = None
        self._available_features = None
        self._n_missing_features = 0
        self._n_expected_features = 0
        self._drift_stats = config.get("drift_stats")

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

    def set_available_features(self, names: list[str]):
        if names == self._available_features:
            return
        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            self._n_missing_features = 0
            self._n_expected_features = 0
            return
        available_idx = {name: i for i, name in enumerate(names)}
        raw_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            raw_map.append(idx)
            if idx == -1:
                missing.append(name)
        self._n_missing_features = len(missing)
        self._n_expected_features = len(expected)
        if missing:
            logger.warning("Missing features for model (filled with 0): %s", missing)
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
        if len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        features = self._map_features(features)
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        # MC Dropout
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

        # Direction from sign
        direction = "LONG" if mean_return > 0 else ("SHORT" if mean_return < 0 else "NEUTRAL")

        # ml_score: scale to [-100, 100]
        ml_score = float(np.clip(mean_return * SCORE_SCALE, -100, 100))

        # Confidence: sigmoid(|prediction| / uncertainty - 1)
        uncertainty = max(np.sqrt(mc_variance), 1e-6)
        raw_confidence = 1.0 / (1.0 + np.exp(-(abs(mean_return) / uncertainty - 1.0)))

        # Drift penalty
        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence = raw_confidence * (1.0 - drift_pen)

        # Staleness cap
        confidence = min(confidence, self._max_confidence)

        return {
            "direction": direction,
            "ml_score": ml_score,
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "mc_variance": mc_variance,
            "drift_penalty": drift_pen,
        }
```

- [ ] **Step 2: Rewrite ensemble_predictor.py — remove v1 EnsemblePredictor, rename RegressionEnsemblePredictor → EnsemblePredictor**

Replace the entire file with:

```python
"""Ensemble inference for multiple SignalLSTM members."""

import json
import logging
import os
import time

import numpy as np
import torch

from app.ml.drift import DriftConfig, feature_drift_penalty
from app.ml.model import SignalLSTM
from app.ml.predictor import DIRECTION_MAP, SCORE_SCALE

logger = logging.getLogger(__name__)

_NEUTRAL_RESULT = {
    "direction": "NEUTRAL",
    "ml_score": 0.0,
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
        self._n_missing_features = 0
        self._n_expected_features = 0
        self._out_idx = None
        self._in_idx = None

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

    def set_available_features(self, names: list[str]):
        if names == self._available_features:
            return
        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            self._n_missing_features = 0
            self._n_expected_features = 0
            return
        available_idx = {name: i for i, name in enumerate(names)}
        raw_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            raw_map.append(idx)
            if idx == -1:
                missing.append(name)
        self._n_missing_features = len(missing)
        self._n_expected_features = len(expected)
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

    @property
    def stale_member_count(self) -> int:
        return sum(1 for w in self._weights if w <= self._stale_floor)

    @property
    def oldest_member_age_days(self) -> float:
        return max(self._member_ages_days) if self._member_ages_days else 0.0

    def predict(self, features: np.ndarray) -> dict:
        if self.n_members == 0 or len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        features = self._map_features(features)
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

        direction = "LONG" if mean_return > 0 else ("SHORT" if mean_return < 0 else "NEUTRAL")
        ml_score = float(np.clip(mean_return * SCORE_SCALE, -100, 100))

        uncertainty = max(np.sqrt(disagreement), 1e-6)
        raw_confidence = 1.0 / (1.0 + np.exp(-(abs(mean_return) / uncertainty - 1.0)))

        uncertainty_penalty = min(1.0, disagreement * self._disagreement_scale)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence *= (1.0 - drift_pen)

        if self.n_members == 2:
            confidence = min(confidence, self._confidence_cap_partial)

        return {
            "direction": direction,
            "ml_score": ml_score,
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "ensemble_disagreement": disagreement,
            "drift_penalty": drift_pen,
        }
```

- [ ] **Step 3: Rewrite drift.py — remove v1 compute_drift_stats and _permutation_importance, rename regression versions**

Replace the entire file with:

```python
"""Feature distribution drift detection via Population Stability Index."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


@dataclass
class DriftConfig:
    """Thresholds and penalties for PSI-based feature drift detection."""
    psi_moderate: float = 0.1
    psi_severe: float = 0.25
    penalty_moderate: float = 0.3
    penalty_severe: float = 0.6


def compute_feature_distributions(
    data: np.ndarray,
    n_bins: int = 10,
) -> dict:
    """Compute decile bin edges and proportions from training data.

    Args:
        data: 1D array of feature values from training set.
        n_bins: number of bins (default 10 = deciles).

    Returns:
        dict with 'bin_edges' (list of n_bins+1 floats including -inf/+inf)
        and 'proportions' (list of n_bins floats summing to 1.0).
    """
    data = data[np.isfinite(data)]
    if len(data) == 0:
        edges = [-np.inf] + [i * 1e-10 for i in range(1, n_bins)] + [np.inf]
        return {"bin_edges": edges, "proportions": [1.0 / n_bins] * n_bins}

    quantiles = np.linspace(0, 100, n_bins + 1)
    edges = np.percentile(data, quantiles)
    edges[0] = -np.inf
    edges[-1] = np.inf
    for i in range(1, len(edges)):
        if edges[i] <= edges[i - 1]:
            edges[i] = edges[i - 1] + 1e-10

    counts = np.histogram(data, bins=edges)[0].astype(np.float64)
    proportions = counts / counts.sum()

    return {
        "bin_edges": edges.tolist(),
        "proportions": proportions.tolist(),
    }


def compute_psi(
    bin_edges: list[float],
    expected_proportions: list[float],
    actual_values: np.ndarray,
    floor: float = 0.001,
) -> float:
    """Compute Population Stability Index between expected and actual distributions.

    Args:
        bin_edges: bin edges from training distribution (n_bins+1 values).
        expected_proportions: proportion in each bin from training (n_bins values).
        actual_values: 1D array of current feature values.
        floor: minimum proportion to avoid log(0).

    Returns:
        PSI value (>= 0). <0.1 = stable, 0.1-0.25 = moderate, >0.25 = severe.
    """
    actual_values = actual_values[np.isfinite(actual_values)]
    edges = np.array(bin_edges)
    expected = np.array(expected_proportions, dtype=np.float64)
    expected = np.maximum(expected, floor)

    actual_counts = np.histogram(actual_values, bins=edges)[0].astype(np.float64)
    total = actual_counts.sum()
    if total == 0:
        return 0.0
    actual = actual_counts / total
    actual = np.maximum(actual, floor)

    psi = float(np.sum((actual - expected) * np.log(actual / expected)))
    return max(0.0, psi)


def feature_drift_penalty(
    current_features: np.ndarray,
    drift_stats: dict | None,
    top_k: int = 3,
    config: DriftConfig | None = None,
) -> float:
    """Compute confidence penalty based on feature distribution drift.

    Args:
        current_features: (n_candles, n_features) array.
        drift_stats: dict with 'top_feature_indices' and 'feature_distributions',
                     or None if not available.
        top_k: number of top features to check.
        config: drift thresholds and penalties.

    Returns:
        Penalty float (0.0, penalty_moderate, or penalty_severe).
    """
    if drift_stats is None:
        return 0.0

    if config is None:
        config = DriftConfig()

    top_indices = drift_stats.get("top_feature_indices", [])[:top_k]
    distributions = drift_stats.get("feature_distributions", {})

    if not top_indices or not distributions:
        return 0.0

    max_psi = 0.0
    n_features = current_features.shape[1]

    for idx in top_indices:
        dist = distributions.get(str(idx))
        if dist is None:
            continue
        if idx >= n_features:
            continue
        psi = compute_psi(
            dist["bin_edges"],
            dist["proportions"],
            current_features[:, idx],
        )
        max_psi = max(max_psi, psi)

    if max_psi < config.psi_moderate:
        return 0.0
    elif max_psi < config.psi_severe:
        return config.penalty_moderate
    else:
        return config.penalty_severe


def _permutation_importance(
    model: nn.Module,
    val_loader,
    input_size: int,
    n_repeats: int = 3,
) -> list[tuple[int, float]]:
    """Permutation importance using HuberLoss for regression models.

    val_loader yields (x, y_return, y_reg) from CandleDataset.
    model returns (return_pred, reg_out) from SignalLSTM.
    """
    device = next(model.parameters()).device
    criterion = nn.HuberLoss(delta=1.0)
    model.eval()

    baseline_loss = 0.0
    n_batches = 0
    all_x = []
    all_y = []
    with torch.no_grad():
        for x, y_return, _ in val_loader:
            x = x.to(device)
            y_return = y_return.to(device)
            return_pred, _ = model(x)
            baseline_loss += criterion(return_pred.squeeze(1), y_return).item()
            all_x.append(x)
            all_y.append(y_return)
            n_batches += 1

    if n_batches == 0:
        return [(i, 0.0) for i in range(input_size)]

    baseline_loss /= n_batches

    importance = []
    for feat_idx in range(input_size):
        total_increase = 0.0
        for _ in range(n_repeats):
            shuffled_loss = 0.0
            for x, y_return in zip(all_x, all_y):
                x_perm = x.clone()
                perm = torch.randperm(x_perm.size(0), device=device)
                x_perm[:, :, feat_idx] = x_perm[perm, :, feat_idx]
                with torch.no_grad():
                    return_pred, _ = model(x_perm)
                    shuffled_loss += criterion(return_pred.squeeze(1), y_return).item()
            shuffled_loss /= n_batches
            total_increase += shuffled_loss - baseline_loss

        importance.append((feat_idx, total_increase / n_repeats))

    importance.sort(key=lambda x: x[1], reverse=True)
    return importance


def compute_drift_stats(
    model: nn.Module,
    val_loader,
    training_features: np.ndarray,
    input_size: int,
    top_n: int = 5,
    n_repeats: int = 3,
) -> dict | None:
    """Compute drift reference stats (importance ranking + distributions)."""
    try:
        importance = _permutation_importance(
            model, val_loader, input_size, n_repeats=n_repeats,
        )
        top_indices = [idx for idx, _ in importance[:top_n]]
        distributions = {}
        for idx in top_indices:
            distributions[str(idx)] = compute_feature_distributions(
                training_features[:, idx], n_bins=10,
            )
        logger.info("Drift stats computed for top %d features: %s", top_n, top_indices)
        return {
            "top_feature_indices": top_indices,
            "feature_distributions": distributions,
        }
    except Exception as e:
        logger.warning("Failed to compute drift stats: %s", e)
        return None
```

---

### Task 7: Update tests — delete v1 tests, update imports for renamed classes

**Files:**
- Modify: `backend/tests/ml/test_model.py`
- Modify: `backend/tests/ml/test_dataset.py`
- Modify: `backend/tests/ml/test_labels.py`
- Modify: `backend/tests/ml/test_data_loader.py`
- Modify: `backend/tests/ml/test_regression_predictor.py`
- Modify: `backend/tests/ml/test_regression_drift.py`
- Modify: `backend/tests/ml/test_regression_trainer.py`
- Delete: `backend/tests/ml/test_trainer.py`
- Delete: `backend/tests/ml/test_ensemble_training.py`
- Delete: `backend/tests/ml/test_predictor.py`
- Delete: `backend/tests/ml/test_ensemble_predictor.py`
- Delete: `backend/tests/ml/test_ml_calibration.py`
- Modify: `backend/tests/api/test_ml.py`
- Modify: `backend/tests/ml/test_drift.py`

**Note:** `test_feature_fallback.py` and `test_pipeline_ml_fallback.py` need NO changes — they import `SignalLSTM`, `Predictor`, `EnsemblePredictor` which are the canonical names that survive the rename.

- [ ] **Step 1: Delete pure v1 test files**

```bash
docker exec krypton-api-1 rm -f \
  tests/ml/test_trainer.py \
  tests/ml/test_ensemble_training.py \
  tests/ml/test_predictor.py \
  tests/ml/test_ensemble_predictor.py \
  tests/ml/test_ml_calibration.py
```

Also delete the local copies:

```bash
rm -f \
  backend/tests/ml/test_trainer.py \
  backend/tests/ml/test_ensemble_training.py \
  backend/tests/ml/test_predictor.py \
  backend/tests/ml/test_ensemble_predictor.py \
  backend/tests/ml/test_ml_calibration.py
```

- [ ] **Step 2: Update test_model.py — remove v1 SignalLSTM tests, rename v2**

Replace the entire file with:

```python
import torch
import pytest

from app.ml.model import SignalLSTM


class TestSignalLSTM:

    @pytest.fixture
    def model(self):
        return SignalLSTM(input_size=15, hidden_size=96, num_layers=2, dropout=0.3)

    def test_forward_output_shapes(self, model):
        batch = torch.randn(8, 50, 15)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (8, 1), "Primary head: single return prediction"
        assert reg_out.shape == (8, 3), "Secondary head: sl, tp1, tp2"

    def test_return_prediction_unbounded(self, model):
        """Return prediction should have no activation — can be negative."""
        batch = torch.randn(8, 50, 15) * 5
        return_pred, _ = model(batch)
        has_negative = (return_pred < 0).any()
        has_positive = (return_pred > 0).any()
        assert has_negative or has_positive

    def test_regression_outputs_positive(self, model):
        batch = torch.randn(8, 50, 15)
        _, reg_out = model(batch)
        assert (reg_out >= 0).all(), "SL/TP must be non-negative (ReLU)"

    def test_no_nan_outputs(self, model):
        batch = torch.randn(8, 50, 15) * 100
        return_pred, reg_out = model(batch)
        assert not torch.isnan(return_pred).any()
        assert not torch.isnan(reg_out).any()

    def test_multiscale_pooling_short_sequence(self):
        model = SignalLSTM(input_size=15, hidden_size=96, num_layers=2, dropout=0.3)
        batch = torch.randn(4, 3, 15)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (4, 1)
        assert reg_out.shape == (4, 3)

    def test_input_batchnorm_exists(self, model):
        assert hasattr(model, 'input_bn')

    def test_multiscale_pooling(self, model):
        batch = torch.randn(4, 50, 15)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (4, 1)
        assert reg_out.shape == (4, 3)
        assert hasattr(model, 'scale_proj')

    def test_different_input_sizes(self):
        model = SignalLSTM(input_size=18, hidden_size=64, num_layers=1)
        batch = torch.randn(2, 30, 18)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (2, 1)
        assert reg_out.shape == (2, 3)
```

- [ ] **Step 3: Update test_dataset.py — remove v1 CandleDataset tests, rename**

Replace the entire file with:

```python
import numpy as np
import torch
import pytest

from app.ml.dataset import CandleDataset


class TestCandleDataset:

    @pytest.fixture
    def sample_data(self):
        n = 300
        n_features = 24
        features = np.random.randn(n, n_features).astype(np.float32)
        forward_return = np.random.randn(n).astype(np.float32)
        sl = np.random.uniform(0.5, 3.0, size=n).astype(np.float32)
        tp1 = np.random.uniform(1.0, 4.0, size=n).astype(np.float32)
        tp2 = np.random.uniform(2.0, 6.0, size=n).astype(np.float32)
        valid = np.ones(n, dtype=bool)
        valid[:10] = False
        valid[-5:] = False
        return features, forward_return, sl, tp1, tp2, valid

    def test_length_excludes_invalid(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        assert len(ds) > 0
        assert len(ds) < 300 - 50

    def test_item_shapes(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        x, y_return, y_reg = ds[0]
        assert x.shape == (50, features.shape[1])
        assert y_return.shape == ()
        assert y_reg.shape == (3,)

    def test_item_types(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        x, y_return, y_reg = ds[0]
        assert x.dtype == torch.float32
        assert y_return.dtype == torch.float32
        assert y_reg.dtype == torch.float32

    def test_noise_augmentation(self):
        n, nf = 200, 15
        features = np.ones((n, nf), dtype=np.float32)
        fwd = np.zeros(n, dtype=np.float32)
        sl = tp1 = tp2 = np.zeros(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)
        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10, noise_std=0.01)
        x, _, _ = ds[0]
        assert not torch.allclose(x, torch.ones_like(x))
```

- [ ] **Step 4: Update test_labels.py — remove v1 TestGenerateLabels, rename**

Replace the entire file with:

```python
import numpy as np
import pandas as pd
import pytest

from app.ml.labels import generate_targets, TargetConfig


def _make_candles_df(n=500, base=67000):
    """Candles with a mix of flat and trending periods."""
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    data = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        noise = rng.uniform(-50, 50)
        trend = 20 * np.sin(2 * np.pi * i / 100)
        c = base + trend + noise
        data.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - 5, "high": c + 30, "low": c - 30, "close": c, "volume": 100,
        })
    return pd.DataFrame(data)


class TestGenerateTargets:

    def test_output_shapes(self):
        df = _make_candles_df(500)
        cfg = TargetConfig(horizon=48)
        fwd, sl, tp1, tp2, valid = generate_targets(df, cfg)
        assert fwd.shape == (500,)
        assert sl.shape == (500,)
        assert valid.shape == (500,)

    def test_last_horizon_candles_invalid(self):
        df = _make_candles_df(200)
        cfg = TargetConfig(horizon=48)
        _, _, _, _, valid = generate_targets(df, cfg)
        assert not valid[-48:].any()
        assert valid[:100].any()

    def test_atr_normalization(self):
        df = _make_candles_df(500)
        cfg = TargetConfig(horizon=48)
        fwd, _, _, _, valid = generate_targets(df, cfg)
        valid_fwd = fwd[valid]
        assert valid_fwd.std() > 0.1
        assert valid_fwd.std() < 20

    def test_zero_atr_skipped(self):
        df = _make_candles_df(200)
        for col in ["open", "high", "low", "close"]:
            df.loc[:13, col] = 67000.0
        cfg = TargetConfig(horizon=48)
        _, _, _, _, valid = generate_targets(df, cfg)
        assert not valid[:14].any()

    def test_sltp_only_for_significant_moves(self):
        df = _make_candles_df(500)
        cfg = TargetConfig(horizon=48, noise_floor=0.3)
        fwd, sl, tp1, tp2, valid = generate_targets(df, cfg)
        small_moves = valid & (np.abs(fwd) < 0.3)
        if small_moves.any():
            assert (sl[small_moves] == 0).all()
            assert (tp1[small_moves] == 0).all()
```

- [ ] **Step 5: Update test_data_loader.py — remove v1 tests, rename**

Replace the entire file with:

```python
import numpy as np
import pytest

from app.ml.data_loader import prepare_training_data
from app.ml.labels import TargetConfig


def _make_candle_dicts(n=500, base=67000):
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        noise = rng.uniform(-50, 50)
        trend = 20 * np.sin(2 * np.pi * i / 100)
        c = base + trend + noise
        spread = rng.uniform(10, 40)
        candles.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - rng.uniform(1, 10), "high": c + spread,
            "low": c - spread, "close": c, "volume": 80 + rng.uniform(0, 40),
        })
    return candles


class TestPrepareTrainingData:

    def test_returns_expected_tuple(self):
        candles = _make_candle_dicts(500)
        result = prepare_training_data(candles)
        features, fwd, sl, tp1, tp2, valid, std_stats = result
        assert features.shape[0] == fwd.shape[0]
        assert isinstance(std_stats, dict)
        assert "mean" in std_stats

    def test_warmup_rows_removed(self):
        candles = _make_candle_dicts(500)
        result = prepare_training_data(candles)
        features, fwd, sl, tp1, tp2, valid, std_stats = result
        assert features.shape[0] == 300  # 500 - 200

    def test_features_are_standardized(self):
        candles = _make_candle_dicts(500)
        result = prepare_training_data(candles)
        features = result[0]
        for col in range(min(5, features.shape[1])):
            assert abs(features[:, col].mean()) < 0.1
```

- [ ] **Step 6: Update test_regression_predictor.py — rename imports**

Replace imports in the file:

```python
import json
import numpy as np
import os
import pytest
import torch

from app.ml.model import SignalLSTM


class TestRegressionPredictor:

    @pytest.fixture
    def model_dir(self, tmp_path):
        """Create a minimal saved model for testing."""
        model = SignalLSTM(input_size=15, hidden_size=32, num_layers=1, dropout=0.1)
        torch.save(model.state_dict(), tmp_path / "best_model.pt")
        config = {
            "input_size": 15, "hidden_size": 32, "num_layers": 1,
            "dropout": 0.1, "seq_len": 20, "model_version": "v2",
            "feature_names": [f"f{i}" for i in range(15)],
        }
        with open(tmp_path / "model_config.json", "w") as f:
            json.dump(config, f)
        return str(tmp_path)

    def test_predict_returns_expected_keys(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert "ml_score" in result
        assert "confidence" in result
        assert "sl_atr" in result
        assert "direction" in result

    def test_ml_score_range(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert -100 <= result["ml_score"] <= 100

    def test_confidence_range(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_too_few_candles_returns_neutral(self, model_dir):
        from app.ml.predictor import Predictor
        pred = Predictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(5, 15).astype(np.float32)
        result = pred.predict(features)
        assert result["confidence"] == 0.0


class TestRegressionEnsemblePredictor:

    @pytest.fixture
    def ensemble_dir(self, tmp_path):
        """Create a minimal 2-member ensemble."""
        for idx in range(2):
            model = SignalLSTM(input_size=15, hidden_size=32, num_layers=1, dropout=0.1)
            torch.save(model.state_dict(), tmp_path / f"ensemble_{idx}.pt")
        config = {
            "n_members": 2, "input_size": 15, "hidden_size": 32,
            "num_layers": 1, "dropout": 0.1, "seq_len": 20,
            "model_version": "v2",
            "feature_names": [f"f{i}" for i in range(15)],
            "members": [
                {"index": 0, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.5, "directional_accuracy": 0.55,
                 "prediction_std": 0.1, "excluded": False},
                {"index": 1, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.6, "directional_accuracy": 0.53,
                 "prediction_std": 0.1, "excluded": False},
            ],
        }
        with open(tmp_path / "ensemble_config.json", "w") as f:
            json.dump(config, f)
        return str(tmp_path)

    def test_predict_returns_expected_keys(self, ensemble_dir):
        from app.ml.ensemble_predictor import EnsemblePredictor
        pred = EnsemblePredictor(ensemble_dir)
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert "ml_score" in result
        assert "confidence" in result
        assert "ensemble_disagreement" in result
        assert "direction" in result

    def test_skips_excluded_members(self, tmp_path):
        for idx in range(3):
            model = SignalLSTM(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
            torch.save(model.state_dict(), tmp_path / f"ensemble_{idx}.pt")
        config = {
            "n_members": 2, "input_size": 10, "hidden_size": 16,
            "num_layers": 1, "dropout": 0.1, "seq_len": 10,
            "model_version": "v2",
            "feature_names": [f"f{i}" for i in range(10)],
            "members": [
                {"index": 0, "excluded": False, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.5, "directional_accuracy": 0.55, "prediction_std": 0.1},
                {"index": 1, "excluded": True, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 1.5, "directional_accuracy": 0.48, "prediction_std": 0.02},
                {"index": 2, "excluded": False, "trained_at": "2026-04-09T00:00:00Z",
                 "val_huber_loss": 0.6, "directional_accuracy": 0.54, "prediction_std": 0.1},
            ],
        }
        with open(tmp_path / "ensemble_config.json", "w") as f:
            json.dump(config, f)
        from app.ml.ensemble_predictor import EnsemblePredictor
        pred = EnsemblePredictor(str(tmp_path))
        assert pred.n_members == 2
```

- [ ] **Step 7: Update test_regression_drift.py — rename imports**

Replace the entire file with:

```python
import numpy as np
import torch
import pytest
from torch.utils.data import DataLoader

from app.ml.model import SignalLSTM
from app.ml.dataset import CandleDataset
from app.ml.drift import compute_drift_stats


class TestDriftStats:

    def test_computes_without_error(self):
        model = SignalLSTM(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
        model.eval()

        n = 200
        features = np.random.randn(n, 10).astype(np.float32)
        fwd = np.random.randn(n).astype(np.float32)
        sl = tp1 = tp2 = np.ones(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)

        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10)
        loader = DataLoader(ds, batch_size=32, shuffle=False)

        result = compute_drift_stats(model, loader, features, 10)
        assert result is not None
        assert "top_feature_indices" in result
        assert "feature_distributions" in result

    def test_returns_none_on_empty_loader(self):
        model = SignalLSTM(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
        model.eval()

        features = np.random.randn(5, 10).astype(np.float32)
        fwd = np.random.randn(5).astype(np.float32)
        sl = tp1 = tp2 = np.ones(5, dtype=np.float32)
        valid = np.zeros(5, dtype=bool)

        ds = CandleDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10)
        loader = DataLoader(ds, batch_size=32, shuffle=False)

        result = compute_drift_stats(model, loader, features, 10)
        assert result is not None
        assert "top_feature_indices" in result
```

- [ ] **Step 8: Update test_regression_trainer.py — rename imports**

Replace the entire file with:

```python
import numpy as np
import pytest
import os

from app.ml.trainer import Trainer, TrainConfig


class TestTrainer:

    @pytest.fixture
    def training_data(self):
        rng = np.random.default_rng(42)
        n = 600
        n_features = 15
        features = rng.standard_normal((n, n_features)).astype(np.float32)
        forward_return = (features[:, 0] * 0.5 + rng.standard_normal(n) * 0.3).astype(np.float32)
        sl = np.abs(forward_return) * 0.5 + 0.5
        tp1 = np.abs(forward_return) * 0.8 + 0.5
        tp2 = np.abs(forward_return) * 1.2 + 1.0
        valid = np.ones(n, dtype=bool)
        sl = sl.astype(np.float32)
        tp1 = tp1.astype(np.float32)
        tp2 = tp2.astype(np.float32)
        return features, forward_return, sl, tp1, tp2, valid

    def test_train_one_model(self, training_data, tmp_path):
        features, fwd, sl, tp1, tp2, valid = training_data
        cfg = TrainConfig(
            epochs=5, batch_size=32, seq_len=20, hidden_size=32,
            num_layers=1, patience=5, min_epochs=3,
            checkpoint_dir=str(tmp_path),
        )
        trainer = Trainer(cfg)
        result = trainer.train_one_model(features, fwd, sl, tp1, tp2, valid)
        assert "val_huber_loss" in result
        assert "directional_accuracy" in result
        assert "best_epoch" in result
        assert os.path.exists(os.path.join(str(tmp_path), "best_model.pt"))

    def test_train_ensemble(self, training_data, tmp_path):
        features, fwd, sl, tp1, tp2, valid = training_data
        cfg = TrainConfig(
            epochs=5, batch_size=32, seq_len=20, hidden_size=32,
            num_layers=1, patience=5, min_epochs=3,
            checkpoint_dir=str(tmp_path),
            directional_accuracy_gate=0.40,
            prediction_std_gate=0.001,
        )
        trainer = Trainer(cfg)
        result = trainer.train_ensemble(
            features, fwd, sl, tp1, tp2, valid,
            feature_names=[f"f{i}" for i in range(15)],
        )
        assert "members" in result
        assert "n_members" in result
        config_path = os.path.join(str(tmp_path), "ensemble_config.json")
        assert os.path.exists(config_path)

    def test_quality_gate_excludes_bad_member(self, tmp_path):
        rng = np.random.default_rng(99)
        n = 400
        features = rng.standard_normal((n, 10)).astype(np.float32)
        fwd = rng.standard_normal(n).astype(np.float32)
        sl = tp1 = tp2 = np.ones(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)
        cfg = TrainConfig(
            epochs=3, batch_size=32, seq_len=10, hidden_size=16,
            num_layers=1, patience=3, min_epochs=2,
            checkpoint_dir=str(tmp_path),
            directional_accuracy_gate=0.52,
        )
        trainer = Trainer(cfg)
        result = trainer.train_one_model(features, fwd, sl, tp1, tp2, valid)
        assert "directional_accuracy" in result
```

- [ ] **Step 9: Update test_drift.py — remove v1 permutation importance test**

Remove the `test_compute_permutation_importance` test that uses `SignalLSTM` (v1) and `CandleDataset` (v1). Keep all PSI and distribution tests. Update the import line:

In `backend/tests/ml/test_drift.py`, remove:
- The `from app.ml.model import SignalLSTM` import
- The `from app.ml.dataset import CandleDataset` import
- The `TestPermutationImportance` class (which uses v1 `SignalLSTM` and v1 `CandleDataset`)

Keep all `TestPSI`, `TestFeatureDistributions`, and `TestFeatureDriftPenalty` classes unchanged.

- [ ] **Step 10: Update test_ml.py (API test) — fix reload_predictors test**

In `backend/tests/api/test_ml.py`, change line 275:

```python
# Old:
from app.ml.model import SignalLSTM

# New:
from app.ml.model import SignalLSTM
```

No actual change needed here since the class name stays `SignalLSTM` — but the model now produces `(return_pred, reg_out)` instead of `(dir_logits, reg_out)`. The test only saves/loads the model, doesn't call `.forward()`, so the checkpoint format is compatible. However, the test creates a v1-style config without `model_version`, which now defaults to loading the new `EnsemblePredictor` instead of the old v1 `EnsemblePredictor`. Add `"model_version": "v2"` to the test's config dict:

In `backend/tests/api/test_ml.py` around line 293, add `"model_version": "v2"` to the config dict.

---

### Task 8: Update api/ml.py — fix imports, TrainRequest defaults, _reload_predictors

**Files:**
- Modify: `backend/app/api/ml.py`

- [ ] **Step 1: Fix imports at top of file (lines 17-20)**

Replace:

```python
from app.ml.data_loader import prepare_training_data
from app.ml.labels import LabelConfig
from app.ml.trainer import Trainer, TrainConfig
from app.ml.utils import TF_MINUTES, bucket_timestamp, compute_per_candle_regime, geometric_balanced_accuracy
```

With:

```python
from app.ml.trainer import Trainer, TrainConfig
from app.ml.utils import TF_MINUTES, bucket_timestamp, compute_per_candle_regime
```

- [ ] **Step 2: Fix TrainRequest defaults (lines 27-39)**

Replace:

```python
class TrainRequest(BaseModel):
    timeframe: str = "1h"
    lookback_days: int = Field(default=365, ge=30, le=1825)
    epochs: int = Field(default=100, ge=1, le=500)
    batch_size: int = Field(default=64, ge=8, le=512)
    hidden_size: int = Field(default=128, ge=32, le=512)
    num_layers: int = Field(default=2, ge=1, le=4)
    lr: float = Field(default=1e-3, gt=0)
    seq_len: int = Field(default=50, ge=25, le=200)
    dropout: float = Field(default=0.3, ge=0.0, le=0.7)
    label_horizon: int = Field(default=24, ge=4, le=96)
    label_threshold_pct: float = Field(default=1.5, gt=0, le=10)
    preset_label: str | None = None
```

With:

```python
class TrainRequest(BaseModel):
    timeframe: str = "1h"
    lookback_days: int = Field(default=365, ge=30, le=1825)
    epochs: int = Field(default=80, ge=1, le=500)
    batch_size: int = Field(default=128, ge=8, le=512)
    hidden_size: int = Field(default=96, ge=32, le=512)
    num_layers: int = Field(default=2, ge=1, le=4)
    lr: float = Field(default=5e-4, gt=0)
    seq_len: int = Field(default=50, ge=25, le=200)
    dropout: float = Field(default=0.3, ge=0.0, le=0.7)
    label_horizon: int = Field(default=48, ge=4, le=96)
    preset_label: str | None = None
```

Note: `label_threshold_pct` removed — it was only used by the deleted v1 `LabelConfig` and is not consumed by `TargetConfig`.

- [ ] **Step 3: Update training endpoint — rename imports inside function**

In the training endpoint function, update:

```python
# Old (line 253):
from app.ml.trainer import RegressionTrainer, RegressionTrainConfig

# New:
from app.ml.trainer import Trainer, TrainConfig
```

And:

```python
# Old (line 255):
train_config = RegressionTrainConfig(

# New:
train_config = TrainConfig(
```

And:

```python
# Old (line 311):
trainer = RegressionTrainer(train_config)

# New:
trainer = Trainer(train_config)
```

- [ ] **Step 4: Update _reload_predictors — remove v1/v2 branching**

Replace the `_reload_predictors` function (starting at line 803). Remove the v1 `Predictor` and `EnsemblePredictor` imports, remove the `model_version` branching, remove the legacy single-file predictor fallback. Always load `EnsemblePredictor`:

```python
def _reload_predictors(app, settings):
    """Reload per-pair ML predictors from checkpoints."""
    import os
    from app.ml.ensemble_predictor import EnsemblePredictor
    from app.ml.features import get_feature_names

    predictors = {}
    checkpoint_dir = getattr(settings, "ml_checkpoint_dir", "models")
    if not os.path.isdir(checkpoint_dir):
        return
    disagreement_scale = getattr(settings, "ensemble_disagreement_scale", 8.0)
    stale_fresh = getattr(settings, "ensemble_stale_fresh_days", 7.0)
    stale_decay = getattr(settings, "ensemble_stale_decay_days", 21.0)
    stale_floor = getattr(settings, "ensemble_stale_floor", 0.3)
    cap_partial = getattr(settings, "ensemble_confidence_cap_partial", 0.5)
    from app.ml.drift import DriftConfig
    drift_config = DriftConfig(
        psi_moderate=getattr(settings, "drift_psi_moderate", 0.1),
        psi_severe=getattr(settings, "drift_psi_severe", 0.25),
        penalty_moderate=getattr(settings, "drift_penalty_moderate", 0.3),
        penalty_severe=getattr(settings, "drift_penalty_severe", 0.6),
    )

    for entry in os.listdir(checkpoint_dir):
        pair_dir = os.path.join(checkpoint_dir, entry)
        if not os.path.isdir(pair_dir):
            continue

        ensemble_config = os.path.join(pair_dir, "ensemble_config.json")

        try:
            if not os.path.isfile(ensemble_config):
                continue

            predictor = EnsemblePredictor(
                pair_dir,
                ensemble_disagreement_scale=disagreement_scale,
                stale_fresh_days=stale_fresh,
                stale_decay_days=stale_decay,
                stale_floor=stale_floor,
                confidence_cap_partial=cap_partial,
                drift_config=drift_config,
            )
            logger.info(
                "Ensemble predictor loaded for %s (%d members)",
                entry, predictor.n_members,
            )
            feature_names = get_feature_names(
                flow_used=predictor.flow_used,
                regime_used=predictor.regime_used,
                btc_used=predictor.btc_used,
            )
            predictor.set_available_features(feature_names)
            predictors[entry] = predictor
        except Exception as e:
            logger.error("Failed to load ML predictor for %s: %s", entry, e)

    app.state.ml_predictors = predictors
```

- [ ] **Step 5: Update the prepare_regression_data and RegressionTargetConfig imports in the training function**

Find and replace in the training endpoint:

```python
# Old (line 234-235):
from app.ml.data_loader import prepare_regression_data
from app.ml.labels import RegressionTargetConfig

# New:
from app.ml.data_loader import prepare_training_data
from app.ml.labels import TargetConfig
```

And update the instantiation:

```python
# Old (line 237):
target_config = RegressionTargetConfig(

# New:
target_config = TargetConfig(
```

And update the call:

```python
# Old (line 240):
features, fwd, sl, tp1, tp2, valid, std_stats = prepare_regression_data(

# New:
features, fwd, sl, tp1, tp2, valid, std_stats = prepare_training_data(
```

---

### Task 9: Remove utils.py v1-only function

**Files:**
- Modify: `backend/app/ml/utils.py`

- [ ] **Step 1: Remove geometric_balanced_accuracy**

This function is only used by the deleted v1 classification Trainer. Remove it from `utils.py`. Keep `directional_accuracy` and all other functions.

---

### Task 10: Run full test suite and verify

- [ ] **Step 1: Run all ML tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ -v`
Expected: All tests pass.

- [ ] **Step 2: Run API tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_ml.py -v`
Expected: All tests pass.

- [ ] **Step 3: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest -x -q`
Expected: No failures related to ML changes.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(ml): remove v1 classification code, fix regression training defaults

Remove dead v1 classification model (SignalLSTM dual-head), trainer,
dataset, and label generation. Rename v2 regression classes to drop
the Regression prefix since they are now the only version.

Fix TrainRequest API defaults that were overriding regression-tuned
config (lr 1e-3→5e-4, hidden 128→96, batch 64→128), which caused
all ensemble members to converge at epoch 1."
```
