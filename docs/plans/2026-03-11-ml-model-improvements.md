# ML Model Improvements Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve SignalLSTM training quality so the model learns deeper patterns before early-stopping kicks in, reducing val_loss from ~1.36 to <1.0.

**Architecture:** Enhance the existing LSTM pipeline with input normalization (BatchNorm), cosine annealing LR schedule with warmup, Gaussian noise data augmentation, label smoothing, multi-scale temporal pooling, and optional longer sequences. These changes modify the model architecture — existing checkpoints are incompatible and will be deleted (Task 9). Models must be retrained after deployment. Note: `_reload_predictors()` already has per-pair try/except error handling, so incompatible checkpoints will be skipped gracefully (logged as errors, falls back to rule-based scoring).

**Commits:** Do NOT commit per-task. Commit once at the end after all tests pass (per CLAUDE.md).

**Unexposed hyperparameters:** `warmup_epochs`, `noise_std`, and `label_smoothing` are added to `TrainConfig` with sensible defaults but intentionally NOT exposed in the training API. This keeps the API simple for v1 — these can be added later if tuning is needed.

**Tech Stack:** PyTorch, NumPy, existing FastAPI training pipeline

---

## Task 1: Add Input BatchNorm to SignalLSTM

The LSTM receives raw features clipped to [-10, 10] but never standardized. A `BatchNorm1d` layer before the LSTM normalizes each feature to zero-mean/unit-variance per batch, which dramatically improves gradient flow and convergence.

**Files:**
- Modify: `backend/app/ml/model.py`
- Modify: `backend/tests/ml/test_model.py`

**Step 1: Write the failing test**

Add these tests **inside `class TestSignalLSTM`**:

```python
def test_input_batchnorm_exists(self, model):
    assert hasattr(model, 'input_bn'), "Model should have input BatchNorm layer"

def test_batchnorm_normalizes_input(self, model):
    # Large-scale input should still produce reasonable outputs
    batch = torch.randn(8, 50, 15) * 100  # large scale
    model_large = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)
    dir_logits, reg_out = model_large(batch)
    assert dir_logits.shape == (8, 3)
    assert reg_out.shape == (8, 3)
    assert not torch.isnan(dir_logits).any()
    assert not torch.isnan(reg_out).any()
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_model.py::TestSignalLSTM::test_input_batchnorm_exists -v`
Expected: FAIL — `AssertionError: Model should have input BatchNorm layer`

**Step 3: Implement BatchNorm in the model**

In `backend/app/ml/model.py`, modify `SignalLSTM.__init__` to add:

```python
self.input_bn = nn.BatchNorm1d(input_size)
```

And modify `forward` to apply it before the LSTM:

```python
def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    # x: (batch, seq_len, input_size)
    # BatchNorm1d expects (batch, features, seq_len), so transpose
    x = self.input_bn(x.transpose(1, 2)).transpose(1, 2)

    lstm_out, _ = self.lstm(x)
    context = self.attention(lstm_out)
    context = self.dropout(context)

    dir_logits = self.cls_head(context)
    reg_out = self.reg_head(context)
    return dir_logits, reg_out
```

**Step 4: Run all model tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_model.py -v`
Expected: All PASS

---

## Task 2: Add Cosine Annealing LR Schedule with Warmup

`ReduceLROnPlateau` is reactive — it only reduces LR after plateaus. Cosine annealing with warmup is proactive: it starts with a linear ramp-up (5 epochs), then smoothly decays LR following a cosine curve. This lets the model explore broadly early, then fine-tune later, and is the standard for modern training.

**Files:**
- Modify: `backend/app/ml/trainer.py`
- Modify: `backend/tests/ml/test_trainer.py`

**Step 1: Write the failing test**

Add **inside `class TestTrainer`**:

```python
def test_cosine_lr_schedule(self, synthetic_data):
    """LR should decrease over epochs with cosine schedule."""
    features, direction, sl, tp1, tp2 = synthetic_data
    with tempfile.TemporaryDirectory() as tmpdir:
        config = TrainConfig(
            epochs=10,
            batch_size=32,
            seq_len=50,
            hidden_size=32,
            num_layers=1,
            lr=1e-3,
            warmup_epochs=2,
            patience=999,  # disable early stopping so all 10 epochs run
            checkpoint_dir=tmpdir,
        )
        trainer = Trainer(config)
        result = trainer.train(features, direction, sl, tp1, tp2)
        assert "lr_history" in result
        lrs = result["lr_history"]
        assert len(lrs) == 10, "All 10 epochs should run"
        # After warmup (epoch 2), LR should generally decrease
        assert lrs[2] >= lrs[-1], "LR should decrease after warmup via cosine annealing"
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py::TestTrainer::test_cosine_lr_schedule -v`
Expected: FAIL — `TypeError: TrainConfig.__init__() got an unexpected keyword argument 'warmup_epochs'`

**Step 3: Implement cosine annealing with warmup**

In `backend/app/ml/trainer.py`:

Add `import math` at the top if not already imported.

Add `warmup_epochs: int = 5` to `TrainConfig`.

Replace the `ReduceLROnPlateau` scheduler with a `LambdaLR` that implements warmup + cosine decay:

```python
warmup = cfg.warmup_epochs
total = cfg.epochs

def lr_lambda(epoch):
    if epoch < warmup:
        return (epoch + 1) / warmup  # linear warmup
    progress = (epoch - warmup) / max(total - warmup, 1)
    return 0.5 * (1 + math.cos(math.pi * progress))  # cosine decay

scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
```

Change `scheduler.step(avg_val_loss)` → `scheduler.step()` (no longer needs val_loss).

Track LR history: append `optimizer.param_groups[0]["lr"]` each epoch, return in result dict as `"lr_history"`.

**Step 4: Run all trainer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py -v`
Expected: All PASS

---

## Task 3: Add Gaussian Noise Data Augmentation

Financial time series are noisy by nature, but the model sees each exact sequence once per epoch. Adding small Gaussian noise to features during training acts as regularization — the model learns to be robust to small perturbations, which improves generalization and delays early stopping.

**Files:**
- Modify: `backend/app/ml/dataset.py`
- Modify: `backend/tests/ml/test_dataset.py`

**Step 1: Write the failing test**

Add **inside `class TestCandleDataset`**:

```python
def test_noise_augmentation(self):
    """When noise_std > 0, returned features should differ from original."""
    n, nf = 100, 15
    features = np.ones((n, nf), dtype=np.float32)
    direction = np.zeros(n, dtype=np.int64)
    sl = tp1 = tp2 = np.zeros(n, dtype=np.float32)
    ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=10, noise_std=0.01)
    x1, _, _ = ds[0]
    # With constant input, noise should make output != 1.0
    assert not torch.allclose(x1, torch.ones_like(x1)), "Noise should perturb features"

def test_no_noise_when_disabled(self):
    """When noise_std=0.0 (default), features should be returned exactly."""
    n, nf = 100, 15
    features = np.ones((n, nf), dtype=np.float32)
    direction = np.zeros(n, dtype=np.int64)
    sl = tp1 = tp2 = np.zeros(n, dtype=np.float32)
    ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=10, noise_std=0.0)
    x1, _, _ = ds[0]
    assert torch.allclose(x1, torch.ones_like(x1)), "No noise should leave features unchanged"
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_dataset.py::TestCandleDataset::test_noise_augmentation -v`
Expected: FAIL — `TypeError: CandleDataset.__init__() got an unexpected keyword argument 'noise_std'`

**Step 3: Implement noise augmentation**

In `backend/app/ml/dataset.py`, add `noise_std: float = 0.0` parameter to `__init__`:

```python
def __init__(self, features, direction, sl_atr, tp1_atr, tp2_atr, seq_len=50, noise_std=0.0):
    # ... existing code ...
    self.noise_std = noise_std
```

In `__getitem__`, add noise when `noise_std > 0`:

```python
def __getitem__(self, idx):
    x = self.features[idx : idx + self.seq_len]
    if self.noise_std > 0:
        x = x + torch.randn_like(x) * self.noise_std
    target_idx = idx + self.seq_len - 1
    y_dir = self.direction[target_idx]
    y_reg = self.regression[target_idx]
    return x, y_dir, y_reg
```

**Step 4: Wire noise into Trainer**

In `backend/app/ml/trainer.py`:

Add `noise_std: float = 0.02` to `TrainConfig`.

Pass it when constructing the training dataset only (not val):

```python
train_ds = CandleDataset(
    features[:split], direction[:split],
    sl_atr[:split], tp1_atr[:split], tp2_atr[:split],
    seq_len=cfg.seq_len, noise_std=cfg.noise_std,
)
```

Val dataset keeps `noise_std=0.0` (no augmentation during evaluation).

**Step 5: Run all dataset and trainer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_dataset.py tests/ml/test_trainer.py -v`
Expected: All PASS

---

## Task 4: Add Label Smoothing to Classification Loss

Hard labels (0 or 1) create overconfident predictions. Label smoothing spreads a small portion (0.1) of probability mass to non-target classes, which regularizes the model and produces better-calibrated confidence scores — critical for a trading system.

**Files:**
- Modify: `backend/app/ml/trainer.py`
- Modify: `backend/tests/ml/test_trainer.py`

**Step 1: Write the failing test**

Add **inside `class TestTrainer`**:

```python
def test_label_smoothing_applied(self, synthetic_data):
    """Label smoothing should be configured and affect the loss function."""
    features, direction, sl, tp1, tp2 = synthetic_data
    with tempfile.TemporaryDirectory() as tmpdir:
        config = TrainConfig(
            epochs=2,
            batch_size=32,
            seq_len=50,
            hidden_size=32,
            num_layers=1,
            label_smoothing=0.1,
            checkpoint_dir=tmpdir,
        )
        assert config.label_smoothing == 0.1
        trainer = Trainer(config)
        result = trainer.train(features, direction, sl, tp1, tp2)
        # Should train successfully with label smoothing
        assert result["best_val_loss"] > 0
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py::TestTrainer::test_label_smoothing_applied -v`
Expected: FAIL — `TypeError: TrainConfig.__init__() got an unexpected keyword argument 'label_smoothing'`

**Step 3: Implement label smoothing**

In `backend/app/ml/trainer.py`:

Add `label_smoothing: float = 0.1` to `TrainConfig`.

Change the `CrossEntropyLoss` initialization:

```python
cls_criterion = nn.CrossEntropyLoss(weight=class_weights_tensor, label_smoothing=cfg.label_smoothing)
```

PyTorch's `CrossEntropyLoss` supports `label_smoothing` natively since PyTorch 1.10.

**Step 4: Run all trainer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py -v`
Expected: All PASS

---

## Task 5: Add Multi-Scale Temporal Pooling

The current model uses a single attention layer over all 50 time steps. Markets operate on multiple timescales — a 5-candle momentum pattern is different from a 25-candle trend. Multi-scale pooling captures both by averaging the last N steps at different scales and concatenating with the attention output.

**Files:**
- Modify: `backend/app/ml/model.py`
- Modify: `backend/tests/ml/test_model.py`

**Step 1: Write the failing test**

Add **inside `class TestSignalLSTM`**:

```python
def test_multiscale_pooling(self):
    model = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)
    batch = torch.randn(4, 50, 15)
    dir_logits, reg_out = model(batch)
    # Output shapes should be unchanged
    assert dir_logits.shape == (4, 3)
    assert reg_out.shape == (4, 3)
    # Model should have the multi-scale projection layer
    assert hasattr(model, 'scale_proj'), "Model should have multi-scale projection"

def test_multiscale_pooling_short_sequence(self):
    """Multi-scale pooling should handle sequences shorter than all pool windows."""
    model = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)
    batch = torch.randn(4, 3, 15)  # seq_len=3, shorter than all pool windows (5/10/25)
    dir_logits, reg_out = model(batch)
    assert dir_logits.shape == (4, 3)
    assert reg_out.shape == (4, 3)
    assert not torch.isnan(dir_logits).any()
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_model.py::TestSignalLSTM::test_multiscale_pooling -v`
Expected: FAIL — `AssertionError: Model should have multi-scale projection`

**Step 3: Implement multi-scale pooling**

In `backend/app/ml/model.py`, modify `SignalLSTM.__init__`:

```python
# Multi-scale temporal pooling: average last 5, 10, 25 steps
self.pool_windows = [5, 10, 25]
# Projects concatenated [attention_ctx + 3 pooled vectors] back to hidden_size
self.scale_proj = nn.Linear(hidden_size * (1 + len(self.pool_windows)), hidden_size)
```

Modify `forward` to compute pooled representations and combine. **Clamp each pool window to the actual sequence length** to handle short sequences correctly:

```python
def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
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
```

**Step 4: Run all model tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_model.py -v`
Expected: All PASS

---

## Task 6: Add Sequence Length to TrainConfig API

Allow configuring `seq_len` from the training API. The default is 50 but longer sequences (75-100) give the model more history to learn from, especially for trend detection. Also expose `dropout` for tuning. Minimum `seq_len` is 25 to ensure multi-scale pooling windows are meaningful.

**Files:**
- Modify: `backend/app/api/ml.py`
- Modify: `backend/tests/api/test_ml.py`

**Step 1: Write the failing test**

Add as a **module-level async function** (matching existing test patterns in this file):

```python
@pytest.mark.asyncio
async def test_train_accepts_seq_len_and_dropout(ml_client):
    resp = await ml_client.post(
        "/api/ml/train",
        json={"seq_len": 75, "dropout": 0.4},
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_ml.py::test_train_accepts_seq_len_and_dropout -v`
Expected: FAIL — 422 validation error (unknown fields)

**Step 3: Implement**

In `backend/app/api/ml.py`, add to `TrainRequest`:

```python
seq_len: int = Field(default=50, ge=25, le=200)
dropout: float = Field(default=0.3, ge=0.0, le=0.7)
```

Pass them to `TrainConfig`:

```python
train_config = TrainConfig(
    epochs=body.epochs,
    batch_size=body.batch_size,
    seq_len=body.seq_len,
    hidden_size=body.hidden_size,
    num_layers=body.num_layers,
    dropout=body.dropout,
    lr=body.lr,
    checkpoint_dir=pair_checkpoint_dir,
)
```

**Step 4: Run API tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_ml.py -v`
Expected: All PASS

---

## Task 7: Expose New Parameters in Frontend API Client

Update the frontend API client to pass the new training parameters so they can be used from the UI later. Note: `batch_size`, `hidden_size`, `num_layers`, `lr`, `label_horizon`, and `label_threshold_pct` already exist in the backend's `TrainRequest` but were not exposed in the frontend type — this task closes that gap alongside the new `seq_len` and `dropout` fields.

**Files:**
- Modify: `web/src/shared/lib/api.ts`

**Step 1: Update the startMLTraining type**

Find the `startMLTraining` method and expand the params type:

```typescript
startMLTraining: (params: {
    timeframe?: string;
    epochs?: number;
    lookback_days?: number;
    batch_size?: number;
    hidden_size?: number;
    num_layers?: number;
    lr?: number;
    seq_len?: number;
    dropout?: number;
    label_horizon?: number;
    label_threshold_pct?: number;
  }) =>
    request<{ job_id: string; status: string }>("/api/ml/train", {
      method: "POST",
      body: JSON.stringify(params),
    }),
```

**Step 2: Build to verify no type errors**

Run: `cd web && pnpm build`
Expected: Build succeeds

---

## Task 8: Update Predictor for BatchNorm Compatibility

The `Predictor` currently creates the model with `dropout=0.0` for inference. BatchNorm has different behavior in eval vs train mode (`model.eval()` handles this). We need to make sure the predictor creates the model with the correct architecture so `load_state_dict` doesn't fail when loading a model that has BatchNorm + multi-scale pooling layers.

**Files:**
- Modify: `backend/app/ml/predictor.py`
- Modify: `backend/tests/ml/test_predictor.py`

**Step 1: Write the failing test**

Add **inside `class TestPredictor`** (matching existing test patterns):

```python
def test_predictor_loads_new_architecture(self):
    """Predictor should load a model trained with BatchNorm + multi-scale pooling."""
    import json
    import tempfile
    model_dir = tempfile.mkdtemp()
    model = SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.3)
    model_path = os.path.join(model_dir, "best_model.pt")
    torch.save(model.state_dict(), model_path)
    config = {
        "input_size": 15, "hidden_size": 64, "num_layers": 2,
        "dropout": 0.3, "seq_len": 50, "epoch": 1, "val_loss": 1.0,
    }
    with open(os.path.join(model_dir, "model_config.json"), "w") as f:
        json.dump(config, f)

    predictor = Predictor(model_path)
    features = np.random.randn(50, 15).astype(np.float32)
    result = predictor.predict(features)
    assert result["direction"] in ("NEUTRAL", "LONG", "SHORT")
    assert 0.0 <= result["confidence"] <= 1.0
```

**Step 2: Run test to verify it passes with current code**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py::TestPredictor::test_predictor_loads_new_architecture -v`
Expected: PASS — since Tasks 1 & 5 unconditionally add `input_bn` and `scale_proj` to `SignalLSTM`, the Predictor already creates a model with matching architecture. `nn.Dropout` has no learnable parameters, so `dropout=0.0` vs `0.3` produces identical state_dict keys.

**Step 3: Fix Predictor for correctness**

While the test passes, the Predictor should still use the trained dropout value from config for architectural consistency:

```python
self.model = SignalLSTM(
    input_size=config["input_size"],
    hidden_size=config["hidden_size"],
    num_layers=config["num_layers"],
    dropout=config.get("dropout", 0.0),  # need matching architecture for state_dict
).to(self.device)
```

Then call `self.model.eval()` as before — this disables dropout and sets BatchNorm to use running statistics.

**Step 4: Run all predictor and integration tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py tests/test_pipeline_ml.py -v`
Expected: All PASS

---

## Task 9: Delete Old Model Checkpoints

The architecture changes (BatchNorm, multi-scale pooling) make old checkpoints incompatible — `load_state_dict` will fail with missing/unexpected keys. Delete all existing model files so the system starts fresh and models are retrained with the new architecture.

**Files:**
- Delete contents of: `backend/models/btc_usdt_swap/`
- Delete contents of: `backend/models/eth_usdt_swap/`

**Step 1: Remove old checkpoint files**

```bash
rm -f backend/models/btc_usdt_swap/*.pt backend/models/btc_usdt_swap/*.json
rm -f backend/models/eth_usdt_swap/*.pt backend/models/eth_usdt_swap/*.json
```

**Step 2: Add .gitkeep files to preserve directory structure**

```bash
touch backend/models/btc_usdt_swap/.gitkeep
touch backend/models/eth_usdt_swap/.gitkeep
```

**Step 3: Verify the models directories are clean**

```bash
ls -la backend/models/btc_usdt_swap/
ls -la backend/models/eth_usdt_swap/
```

Expected: Only `.gitkeep` in each directory.

---

## Task 10: Run Full Test Suite and Verify

Run the complete backend test suite to ensure all changes work together with no regressions.

**Step 1: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS

**Step 2: Run frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors

**Step 3: Commit all changes (single commit for the entire feature batch)**

```
feat(ml): improve SignalLSTM with BatchNorm, cosine LR, noise augmentation, label smoothing, and multi-scale pooling
```

---

## Summary of Expected Impact

| Improvement | Why It Helps | Expected Effect |
|------------|-------------|-----------------|
| Input BatchNorm | Normalizes feature distributions per-batch | Faster convergence, better gradient flow |
| Cosine annealing + warmup | Smooth LR decay, avoids premature convergence | Train longer before plateauing |
| Gaussian noise augmentation | Regularization via input perturbation | Better generalization, delays overfitting |
| Label smoothing (0.1) | Prevents overconfident predictions | Better-calibrated confidence scores |
| Multi-scale temporal pooling | Captures patterns at different timescales | Richer learned representations |
| Configurable seq_len/dropout | Allows tuning for different market conditions | Flexibility for experimentation |

**Recommended training config after improvements:**
- `lookback_days`: 1825 (max — backfill first)
- `epochs`: 200
- `hidden_size`: 128
- `seq_len`: 75
- `lr`: 5e-4 (slightly lower than before, warmup handles ramp-up)
- `dropout`: 0.3
