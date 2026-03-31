"""Training loop for SignalLSTM model."""

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

logger = logging.getLogger(__name__)

# Temporal split boundaries for 3-member ensemble
_ENSEMBLE_SPLITS = [
    (0.0, 0.8),
    (0.1, 0.9),
    (0.2, 1.0),
]


@dataclass
class TrainConfig:
    epochs: int = 100
    batch_size: int = 64
    seq_len: int = 50
    hidden_size: int = 128
    num_layers: int = 2
    dropout: float = 0.3
    lr: float = 1e-3
    weight_decay: float = 1e-4
    reg_loss_weight: float = 0.5
    val_ratio: float = 0.15
    patience: int = 20
    warmup_epochs: int = 5
    noise_std: float = 0.02
    label_smoothing: float = 0.1
    checkpoint_dir: str = "models"
    neutral_subsample_ratio: float = 0.5  # keep only 50% of NEUTRAL samples to reduce imbalance


class Trainer:
    """Trains SignalLSTM with classification + regression multi-task loss."""

    def __init__(self, config: TrainConfig):
        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def train_one_model(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
        _skip_drift_stats: bool = False,
    ) -> dict:
        """Train a single SignalLSTM model.

        Returns dict with train_loss, val_loss, best_epoch, direction_accuracy,
        precision_per_class, recall_per_class, version.
        """
        cfg = self.config
        input_size = features.shape[1]

        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(input_size)]

        if not _skip_drift_stats:
            pre_subsample_features = features.copy()
            pre_subsample_n = len(features)

        # Subsample NEUTRAL class to reduce imbalance
        if cfg.neutral_subsample_ratio < 1.0:
            rng = np.random.default_rng(42)
            neutral_mask = direction == 0
            neutral_idx = np.where(neutral_mask)[0]
            keep_n = int(len(neutral_idx) * cfg.neutral_subsample_ratio)
            drop_idx = set(rng.choice(neutral_idx, size=len(neutral_idx) - keep_n, replace=False))
            keep_mask = np.array([i not in drop_idx for i in range(len(features))])
            features = features[keep_mask]
            direction = direction[keep_mask]
            sl_atr = sl_atr[keep_mask]
            tp1_atr = tp1_atr[keep_mask]
            tp2_atr = tp2_atr[keep_mask]
            logger.info(f"Subsampled NEUTRAL: kept {keep_n}/{len(neutral_idx)} → {len(features)} total samples")

        n = len(features)
        min_samples = cfg.seq_len + 1
        if n < min_samples:
            raise ValueError(
                f"Not enough samples to train: {n} < {min_samples} "
                f"(seq_len={cfg.seq_len}). Need more historical data."
            )

        # Train/val split (temporal — no shuffle to respect time ordering)
        split = int(n * (1 - cfg.val_ratio))
        val_count = n - split

        # If validation set is too small for the sequence length, skip validation
        use_val = val_count > cfg.seq_len
        if not use_val:
            logger.warning(
                f"Validation set too small ({val_count} < seq_len {cfg.seq_len}), "
                f"training without validation / early stopping"
            )
            split = n  # use all data for training

        train_ds = CandleDataset(
            features[:split], direction[:split],
            sl_atr[:split], tp1_atr[:split], tp2_atr[:split],
            seq_len=cfg.seq_len, noise_std=cfg.noise_std,
        )
        train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True)

        val_loader = None
        if use_val:
            val_ds = CandleDataset(
                features[split:], direction[split:],
                sl_atr[split:], tp1_atr[split:], tp2_atr[split:],
                seq_len=cfg.seq_len,
            )
            val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False)

        # Class weights for imbalanced labels
        class_counts = np.bincount(direction[:split], minlength=3).astype(np.float32)
        class_counts = np.maximum(class_counts, 1)  # avoid div by zero
        class_weights = 1.0 / class_counts
        class_weights = class_weights / class_weights.sum() * 3  # normalize
        class_weights_tensor = torch.tensor(class_weights, device=self.device)

        model = SignalLSTM(
            input_size=input_size,
            hidden_size=cfg.hidden_size,
            num_layers=cfg.num_layers,
            dropout=cfg.dropout,
        ).to(self.device)

        optimizer = torch.optim.AdamW(
            model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay,
        )
        warmup = cfg.warmup_epochs
        total = cfg.epochs

        def lr_lambda(epoch):
            if epoch < warmup:
                return (epoch + 1) / warmup  # linear warmup
            progress = (epoch - warmup) / max(total - warmup, 1)
            return 0.5 * (1 + math.cos(math.pi * progress))  # cosine decay

        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

        cls_criterion = nn.CrossEntropyLoss(weight=class_weights_tensor, label_smoothing=cfg.label_smoothing)
        reg_criterion = nn.SmoothL1Loss()

        best_val_loss = float("inf")
        best_epoch = 0
        epochs_without_improvement = 0
        train_losses = []
        val_losses = []
        lr_history = []

        os.makedirs(cfg.checkpoint_dir, exist_ok=True)

        for epoch in range(cfg.epochs):
            # Train
            model.train()
            epoch_loss = 0.0
            n_batches = 0
            for x, y_dir, y_reg in train_loader:
                x = x.to(self.device)
                y_dir = y_dir.to(self.device)
                y_reg = y_reg.to(self.device)

                dir_logits, reg_out = model(x)

                cls_loss = cls_criterion(dir_logits, y_dir)

                # Regression loss only for non-NEUTRAL samples
                non_neutral = y_dir != 0
                if non_neutral.any():
                    reg_loss = reg_criterion(reg_out[non_neutral], y_reg[non_neutral])
                else:
                    reg_loss = torch.tensor(0.0, device=self.device)

                loss = cls_loss + cfg.reg_loss_weight * reg_loss

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                epoch_loss += loss.item()
                n_batches += 1

            avg_train_loss = epoch_loss / max(n_batches, 1)
            train_losses.append(avg_train_loss)

            # Validate
            avg_val_loss = None
            if val_loader is not None:
                model.eval()
                val_loss = 0.0
                val_batches = 0
                with torch.no_grad():
                    for x, y_dir, y_reg in val_loader:
                        x = x.to(self.device)
                        y_dir = y_dir.to(self.device)
                        y_reg = y_reg.to(self.device)

                        dir_logits, reg_out = model(x)
                        cls_loss = cls_criterion(dir_logits, y_dir)

                        non_neutral = y_dir != 0
                        if non_neutral.any():
                            reg_loss = reg_criterion(reg_out[non_neutral], y_reg[non_neutral])
                        else:
                            reg_loss = torch.tensor(0.0, device=self.device)

                        val_loss += (cls_loss + cfg.reg_loss_weight * reg_loss).item()
                        val_batches += 1

                avg_val_loss = val_loss / max(val_batches, 1)
                val_losses.append(avg_val_loss)

            # Step cosine scheduler and track LR
            scheduler.step()
            lr_history.append(optimizer.param_groups[0]["lr"])

            log_msg = f"Epoch {epoch+1}/{cfg.epochs} — train_loss={avg_train_loss:.4f}"
            if avg_val_loss is not None:
                log_msg += f" val_loss={avg_val_loss:.4f}"
            logger.info(log_msg)

            if progress_callback:
                progress_callback({
                    "epoch": epoch + 1,
                    "total_epochs": cfg.epochs,
                    "train_loss": avg_train_loss,
                    "val_loss": avg_val_loss,
                    "direction_acc": None,  # computed at end only
                })

            # Early stopping (only with validation)
            if avg_val_loss is not None:
                if avg_val_loss < best_val_loss:
                    best_val_loss = avg_val_loss
                    best_epoch = epoch + 1
                    epochs_without_improvement = 0

                    # Save model weights only (safe for weights_only=True loading)
                    torch.save(
                        model.state_dict(),
                        os.path.join(cfg.checkpoint_dir, "best_model.pt"),
                    )

                    # Save config + metadata as JSON (avoids weights_only issues)
                    import json as _json
                    config_meta = {
                        "input_size": input_size,
                        "hidden_size": cfg.hidden_size,
                        "num_layers": cfg.num_layers,
                        "dropout": cfg.dropout,
                        "seq_len": cfg.seq_len,
                        "epoch": epoch + 1,
                        "val_loss": best_val_loss,
                        "feature_names": feature_names,
                        "temperature": 1.0,
                    }
                    with open(os.path.join(cfg.checkpoint_dir, "model_config.json"), "w") as f:
                        _json.dump(config_meta, f, indent=2)
                else:
                    epochs_without_improvement += 1
                    if epochs_without_improvement >= cfg.patience:
                        logger.info(f"Early stopping at epoch {epoch+1}")
                        break
            else:
                # No validation — save every epoch (last one wins)
                best_epoch = epoch + 1
                torch.save(
                    model.state_dict(),
                    os.path.join(cfg.checkpoint_dir, "best_model.pt"),
                )
                import json as _json
                config_meta = {
                    "input_size": input_size,
                    "hidden_size": cfg.hidden_size,
                    "num_layers": cfg.num_layers,
                    "dropout": cfg.dropout,
                    "seq_len": cfg.seq_len,
                    "epoch": epoch + 1,
                    "val_loss": None,
                    "feature_names": feature_names,
                    "temperature": 1.0,
                }
                with open(os.path.join(cfg.checkpoint_dir, "model_config.json"), "w") as f:
                    _json.dump(config_meta, f, indent=2)

        # Save a versioned copy for rollback
        from datetime import datetime as _dt, timezone as _tz
        version_tag = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
        versioned_pt = os.path.join(cfg.checkpoint_dir, f"model_{version_tag}.pt")
        best_pt = os.path.join(cfg.checkpoint_dir, "best_model.pt")
        if os.path.exists(best_pt):
            import shutil
            shutil.copy2(best_pt, versioned_pt)
            logger.info(f"Versioned checkpoint saved: {versioned_pt}")

        # ── Temperature scaling on validation set ──
        temperature = 1.0
        if val_loader is not None:
            best_pt = os.path.join(cfg.checkpoint_dir, "best_model.pt")
            if os.path.exists(best_pt):
                model.load_state_dict(torch.load(best_pt, map_location=self.device, weights_only=True))

            model.eval()
            all_logits = []
            all_labels_temp = []
            with torch.no_grad():
                for x, y_dir, _ in val_loader:
                    x = x.to(self.device)
                    dir_logits, _ = model(x)
                    all_logits.append(dir_logits)
                    all_labels_temp.append(y_dir.to(self.device))

            if all_logits:
                all_logits = torch.cat(all_logits, dim=0)
                all_labels_temp = torch.cat(all_labels_temp, dim=0)

                log_temp = torch.tensor(0.0, device=self.device, requires_grad=True)
                temp_optimizer = torch.optim.LBFGS([log_temp], lr=0.01, max_iter=50)
                nll_fn = nn.CrossEntropyLoss()

                def temp_closure():
                    temp_optimizer.zero_grad()
                    t = log_temp.exp()
                    loss = nll_fn(all_logits / t, all_labels_temp)
                    loss.backward()
                    return loss

                temp_optimizer.step(temp_closure)
                temperature = float(log_temp.exp().item())
                temperature = max(0.1, min(10.0, temperature))
                logger.info(f"Temperature scaling: T={temperature:.4f}")

        # Re-write sidecar with calibrated temperature
        import json as _json
        config_path = os.path.join(cfg.checkpoint_dir, "model_config.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                config_meta = _json.load(f)
            config_meta["temperature"] = temperature
            with open(config_path, "w") as f:
                _json.dump(config_meta, f, indent=2)

        # ── Compute classification metrics on validation set at best epoch ──
        direction_accuracy = 0.0
        precision_per_class = {"long": 0.0, "short": 0.0, "neutral": 0.0}
        recall_per_class = {"long": 0.0, "short": 0.0, "neutral": 0.0}

        if use_val:
            # Load best checkpoint for evaluation
            best_pt = os.path.join(cfg.checkpoint_dir, "best_model.pt")
            if os.path.exists(best_pt):
                model.load_state_dict(torch.load(best_pt, map_location=self.device, weights_only=True))

            model.eval()
            all_preds = []
            all_labels = []
            with torch.no_grad():
                for x, y_dir, _y_reg in val_loader:
                    x = x.to(self.device)
                    y_dir = y_dir.to(self.device)
                    dir_logits, _ = model(x)
                    preds = dir_logits.argmax(dim=1)
                    all_preds.extend(preds.cpu().numpy())
                    all_labels.extend(y_dir.cpu().numpy())

            all_preds = np.array(all_preds)
            all_labels = np.array(all_labels)

            # Direction accuracy
            direction_accuracy = float((all_preds == all_labels).mean()) if len(all_labels) > 0 else 0.0

            # Per-class precision and recall (manual — no sklearn)
            class_names = {0: "neutral", 1: "long", 2: "short"}
            for cls_id, cls_name in class_names.items():
                tp = int(((all_preds == cls_id) & (all_labels == cls_id)).sum())
                fp = int(((all_preds == cls_id) & (all_labels != cls_id)).sum())
                fn = int(((all_preds != cls_id) & (all_labels == cls_id)).sum())
                precision_per_class[cls_name] = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                recall_per_class[cls_name] = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        drift_stats = None
        if _skip_drift_stats:
            pass
        elif use_val and val_loader is not None:
            from app.ml.drift import compute_drift_stats
            pre_split = int(pre_subsample_n * (1 - cfg.val_ratio))
            drift_stats = compute_drift_stats(
                model, val_loader, pre_subsample_features[:pre_split],
                input_size,
            )
        else:
            logger.info("Skipping drift stats: no validation set available")

        if drift_stats is not None:
            import json as _json
            config_path = os.path.join(cfg.checkpoint_dir, "model_config.json")
            if os.path.exists(config_path):
                with open(config_path) as f:
                    config_meta = _json.load(f)
                config_meta["drift_stats"] = drift_stats
                with open(config_path, "w") as f:
                    _json.dump(config_meta, f, indent=2)

        return {
            "train_loss": train_losses,
            "val_loss": val_losses,
            "best_epoch": best_epoch,
            "best_val_loss": best_val_loss,
            "version": version_tag,
            "lr_history": lr_history,
            "direction_accuracy": direction_accuracy,
            "precision_per_class": precision_per_class,
            "recall_per_class": recall_per_class,
        }

    def train_ensemble(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
    ) -> dict:
        """Train a 3-member ensemble on overlapping temporal splits.

        Members are trained in parallel via ThreadPoolExecutor for ~3x speedup.
        Members whose slice yields fewer than seq_len * 2 samples are skipped.
        Falls back to single-model training if fewer than 2 members are viable.

        Returns dict with 'members' list and 'n_members'.
        """
        import json as _json
        import shutil
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from datetime import datetime as _dt, timezone as _tz

        cfg = self.config
        n = len(features)
        min_per_slice = cfg.seq_len * 2

        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(features.shape[1])]

        staging_dir = os.path.join(cfg.checkpoint_dir, ".ensemble_staging")
        os.makedirs(staging_dir, exist_ok=True)

        def _train_member(idx, start_frac, end_frac):
            """Train a single ensemble member on its temporal slice."""
            s = int(n * start_frac)
            e = int(n * end_frac)
            sl_feat = features[s:e]
            sl_dir = direction[s:e]
            sl_sl = sl_atr[s:e]
            sl_tp1 = tp1_atr[s:e]
            sl_tp2 = tp2_atr[s:e]

            if len(sl_feat) < min_per_slice:
                logger.warning(
                    "Ensemble member %d: only %d samples (need %d), skipping",
                    idx, len(sl_feat), min_per_slice,
                )
                return None

            member_dir = os.path.join(staging_dir, f"member_{idx}")
            os.makedirs(member_dir, exist_ok=True)

            member_cfg = TrainConfig(
                epochs=cfg.epochs,
                batch_size=cfg.batch_size,
                seq_len=cfg.seq_len,
                hidden_size=cfg.hidden_size,
                num_layers=cfg.num_layers,
                dropout=cfg.dropout,
                lr=cfg.lr,
                weight_decay=cfg.weight_decay,
                reg_loss_weight=cfg.reg_loss_weight,
                val_ratio=cfg.val_ratio,
                patience=cfg.patience,
                warmup_epochs=cfg.warmup_epochs,
                noise_std=cfg.noise_std,
                label_smoothing=cfg.label_smoothing,
                checkpoint_dir=member_dir,
                neutral_subsample_ratio=cfg.neutral_subsample_ratio,
            )
            member_trainer = Trainer(member_cfg)
            try:
                result = member_trainer.train_one_model(
                    sl_feat, sl_dir, sl_sl, sl_tp1, sl_tp2,
                    progress_callback=progress_callback,
                    feature_names=feature_names,
                    _skip_drift_stats=True,
                )
            except ValueError as e:
                logger.warning("Ensemble member %d failed: %s", idx, e)
                return None

            # Read temperature from saved config
            config_path = os.path.join(member_dir, "model_config.json")
            with open(config_path) as f:
                saved_config = _json.load(f)

            return {
                "index": idx,
                "trained_at": _dt.now(_tz.utc).isoformat(),
                "val_loss": result["best_val_loss"],
                "temperature": saved_config.get("temperature", 1.0),
                "data_range": [start_frac, end_frac],
                "direction_accuracy": result.get("direction_accuracy", 0.0),
                "precision_per_class": result.get("precision_per_class"),
                "recall_per_class": result.get("recall_per_class"),
            }

        # Train all members in parallel
        members = []
        with ThreadPoolExecutor(max_workers=len(_ENSEMBLE_SPLITS)) as pool:
            futures = {
                pool.submit(_train_member, idx, s, e): idx
                for idx, (s, e) in enumerate(_ENSEMBLE_SPLITS)
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    members.append(result)

        # Sort by index so checkpoint naming is deterministic
        members.sort(key=lambda m: m["index"])

        if len(members) < 2:
            logger.warning(
                "Only %d ensemble members viable, falling back to single-model training",
                len(members),
            )
            shutil.rmtree(staging_dir, ignore_errors=True)
            result = self.train_one_model(
                features, direction, sl_atr, tp1_atr, tp2_atr,
                progress_callback, feature_names,
            )
            return {"members": [], "n_members": 0, "fallback": result}

        # Move member checkpoints to final location with canonical names.
        # Write .pt files first, ensemble_config.json LAST — this is the
        # detection file that _reload_predictors() checks, so it must only
        # appear after all .pt files are in place.
        for m in members:
            idx = m["index"]
            src_pt = os.path.join(staging_dir, f"member_{idx}", "best_model.pt")
            dst_pt = os.path.join(cfg.checkpoint_dir, f"ensemble_{idx}.pt")
            shutil.copy2(src_pt, dst_pt)

        # Write ensemble_config.json LAST for atomic visibility
        input_size = features.shape[1]
        ensemble_config = {
            "n_members": len(members),
            "input_size": input_size,
            "hidden_size": cfg.hidden_size,
            "num_layers": cfg.num_layers,
            "dropout": cfg.dropout,
            "seq_len": cfg.seq_len,
            "feature_names": feature_names,
            "members": members,
        }

        drift_stats = None
        first_member_dir = os.path.join(staging_dir, f"member_{members[0]['index']}")
        first_pt = os.path.join(first_member_dir, "best_model.pt")

        if os.path.exists(first_pt):
            perm_model = SignalLSTM(
                input_size=features.shape[1],
                hidden_size=cfg.hidden_size,
                num_layers=cfg.num_layers,
                dropout=cfg.dropout,
            ).to(self.device)
            perm_model.load_state_dict(
                torch.load(first_pt, map_location=self.device, weights_only=True)
            )
            perm_model.eval()

            n = len(features)
            val_start = int(n * (1 - cfg.val_ratio))
            val_feat = features[val_start:]
            val_dir = direction[val_start:]
            val_sl = sl_atr[val_start:]
            val_tp1 = tp1_atr[val_start:]
            val_tp2 = tp2_atr[val_start:]

            if len(val_feat) > cfg.seq_len:
                val_ds = CandleDataset(
                    val_feat, val_dir, val_sl, val_tp1, val_tp2,
                    seq_len=cfg.seq_len,
                )
                val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False)

                from app.ml.drift import compute_drift_stats
                drift_stats = compute_drift_stats(
                    perm_model, val_loader, features[:val_start],
                    features.shape[1],
                )

        if drift_stats is not None:
            ensemble_config["drift_stats"] = drift_stats

        with open(os.path.join(cfg.checkpoint_dir, "ensemble_config.json"), "w") as f:
            _json.dump(ensemble_config, f, indent=2)

        # Clean up staging
        shutil.rmtree(staging_dir, ignore_errors=True)

        return {"members": members, "n_members": len(members)}

    def train(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
    ) -> dict:
        """Backward-compatible wrapper for train_one_model."""
        return self.train_one_model(
            features, direction, sl_atr, tp1_atr, tp2_atr,
            progress_callback, feature_names,
        )
