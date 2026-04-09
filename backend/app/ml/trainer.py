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
