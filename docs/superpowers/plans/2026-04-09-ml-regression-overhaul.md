# ML Regression Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken 3-class classification ML pipeline with a continuous regression model that predicts ATR-normalized forward returns, fixing label imbalance, feature scaling, and confidence calibration so ML actually contributes to live signals.

**Architecture:** New `SignalLSTMv2` (regression-first, smaller) replaces `SignalLSTM`. New `generate_regression_targets()` replaces `generate_labels()`. Walk-forward 3-fold validation replaces overlapping temporal splits. Simplified confidence formula with lower threshold (0.40) replaces the current penalty stack that crushes confidence to ~0.3.

**Tech Stack:** Python 3.11, PyTorch (CPU), NumPy, Pandas, FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-04-09-ml-regression-overhaul-design.md`

**Note on commits:** Per CLAUDE.md, do not make small incremental commits per task. The per-task commit steps below are logical checkpoints — combine into one or two commits at the end of the implementation batch.

---

### Task 1: Regression Target Generation

**Files:**
- Modify: `backend/app/ml/labels.py`
- Test: `backend/tests/ml/test_labels.py`

- [ ] **Step 1: Write failing tests for `generate_regression_targets`**

Add to `backend/tests/ml/test_labels.py`:

```python
from app.ml.labels import generate_regression_targets, RegressionTargetConfig


def _make_candles_df(n=500, base=67000):
    """Candles with a mix of flat and trending periods."""
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    data = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        noise = rng.uniform(-50, 50)
        trend = 20 * np.sin(2 * np.pi * i / 100)  # gentle oscillation
        c = base + trend + noise
        data.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - 5, "high": c + 30, "low": c - 30, "close": c, "volume": 100,
        })
    return pd.DataFrame(data)


class TestRegressionTargets:

    def test_output_shapes(self):
        df = _make_candles_df(500)
        cfg = RegressionTargetConfig(horizon=48)
        fwd, sl, tp1, tp2, valid = generate_regression_targets(df, cfg)
        assert fwd.shape == (500,)
        assert sl.shape == (500,)
        assert valid.shape == (500,)

    def test_last_horizon_candles_invalid(self):
        df = _make_candles_df(200)
        cfg = RegressionTargetConfig(horizon=48)
        _, _, _, _, valid = generate_regression_targets(df, cfg)
        # Last 48 candles can't look forward — should be invalid
        assert not valid[-48:].any()
        # Some earlier candles should be valid
        assert valid[:100].any()

    def test_atr_normalization(self):
        """Forward return should be divided by ATR — result should be O(1) not O(0.001)."""
        df = _make_candles_df(500)
        cfg = RegressionTargetConfig(horizon=48)
        fwd, _, _, _, valid = generate_regression_targets(df, cfg)
        valid_fwd = fwd[valid]
        # ATR-normalized returns should be in roughly [-5, 5] range, not [-.001, .001]
        assert valid_fwd.std() > 0.1, "Returns should be ATR-normalized (not raw)"
        assert valid_fwd.std() < 20, "Returns should not be wildly inflated"

    def test_zero_atr_skipped(self):
        """Candles where ATR is near zero should be marked invalid."""
        df = _make_candles_df(200)
        # Force flat candles at start (zero ATR)
        for col in ["open", "high", "low", "close"]:
            df.loc[:13, col] = 67000.0
        cfg = RegressionTargetConfig(horizon=48)
        _, _, _, _, valid = generate_regression_targets(df, cfg)
        # First 14 candles have zero ATR — should be invalid
        assert not valid[:14].any()

    def test_sltp_only_for_significant_moves(self):
        """SL/TP targets should be zero for small-move candles."""
        df = _make_candles_df(500)
        cfg = RegressionTargetConfig(horizon=48, noise_floor=0.3)
        fwd, sl, tp1, tp2, valid = generate_regression_targets(df, cfg)
        small_moves = valid & (np.abs(fwd) < 0.3)
        if small_moves.any():
            assert (sl[small_moves] == 0).all()
            assert (tp1[small_moves] == 0).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_labels.py::TestRegressionTargets -v`
Expected: FAIL — `generate_regression_targets` and `RegressionTargetConfig` don't exist

- [ ] **Step 3: Implement `generate_regression_targets`**

Add to `backend/app/ml/labels.py`:

```python
@dataclass
class RegressionTargetConfig:
    horizon: int = 48          # candles to look forward (48 for 15m = 12h)
    noise_floor: float = 0.3   # minimum |fwd_return| in ATR units for SL/TP training
    atr_epsilon: float = 1e-6  # minimum atr_pct to avoid division by zero


def generate_regression_targets(
    candles: pd.DataFrame,
    config: RegressionTargetConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate ATR-normalized forward return and SL/TP regression targets.

    Returns:
        Tuple of (forward_return, sl_atr, tp1_atr, tp2_atr, valid_mask).
        forward_return: ATR-normalized return over horizon (float32).
        sl_atr, tp1_atr, tp2_atr: ATR-unit distances (0 for noise-floor samples).
        valid_mask: bool array — False for warmup, end-of-series, and zero-ATR rows.
    """
    if config is None:
        config = RegressionTargetConfig()

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_labels.py -v`
Expected: All tests PASS (both old TestGenerateLabels and new TestRegressionTargets)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/labels.py backend/tests/ml/test_labels.py
git commit -m "feat(ml): add regression target generation with ATR normalization"
```

---

### Task 2: Feature Standardization & Warmup Removal

**Files:**
- Modify: `backend/app/ml/features.py`
- Test: `backend/tests/ml/test_features.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/ml/test_features.py`:

```python
from app.ml.features import (
    compute_warmup_period, drop_warmup_rows,
    compute_standardization_stats, apply_standardization,
)


class TestWarmupRemoval:

    def test_warmup_period_base_features(self):
        """Base features need EMA(200) → warmup should be 200."""
        period = compute_warmup_period(regime_used=False, btc_used=False, flow_used=False)
        assert period == 200

    def test_drop_warmup_rows(self):
        data = np.random.randn(500, 24).astype(np.float32)
        trimmed, offset = drop_warmup_rows(data, warmup=200)
        assert trimmed.shape[0] == 300
        assert offset == 200
        np.testing.assert_array_equal(trimmed, data[200:])


class TestStandardization:

    def test_zero_mean_unit_var(self):
        rng = np.random.default_rng(42)
        data = rng.normal(loc=5.0, scale=3.0, size=(1000, 10)).astype(np.float32)
        stats = compute_standardization_stats(data)
        normed = apply_standardization(data, stats)
        # Each column should be ~zero mean, ~unit std
        for col in range(10):
            assert abs(normed[:, col].mean()) < 0.05
            assert abs(normed[:, col].std() - 1.0) < 0.05

    def test_stats_dict_has_expected_keys(self):
        data = np.random.randn(100, 5).astype(np.float32)
        stats = compute_standardization_stats(data)
        assert "mean" in stats
        assert "std" in stats
        assert len(stats["mean"]) == 5
        assert len(stats["std"]) == 5

    def test_zero_std_feature_not_nan(self):
        """Constant feature should not produce NaN after standardization."""
        data = np.ones((100, 3), dtype=np.float32)
        data[:, 1] = 5.0  # constant column
        stats = compute_standardization_stats(data)
        normed = apply_standardization(data, stats)
        assert not np.isnan(normed).any()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_features.py::TestWarmupRemoval tests/ml/test_features.py::TestStandardization -v`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement warmup and standardization functions**

Add to `backend/app/ml/features.py` (after the `get_feature_names` function):

```python
# Maximum indicator lookback per feature group
_LOOKBACK = {
    "base": 200,     # EMA(200) in ema_slow_dist
    "regime": 0,     # computed externally
    "btc": 0,        # computed externally
    "flow": 0,       # no lookback needed
}


def compute_warmup_period(
    regime_used: bool = False,
    btc_used: bool = False,
    flow_used: bool = False,
) -> int:
    """Return the number of warmup rows to discard based on active feature groups."""
    return _LOOKBACK["base"]


def drop_warmup_rows(
    features: np.ndarray,
    warmup: int = 200,
) -> tuple[np.ndarray, int]:
    """Slice off warmup rows from feature matrix.

    Returns (trimmed_features, offset) where offset is the number of rows removed.
    """
    if warmup >= len(features):
        return features, 0  # not enough data — return all
    return features[warmup:], warmup


def compute_standardization_stats(features: np.ndarray) -> dict:
    """Compute per-feature mean and std for z-score normalization.

    Returns dict with 'mean' and 'std' lists, serializable to JSON.
    """
    mean = features.mean(axis=0)
    std = features.std(axis=0)
    # Replace zero std with 1.0 to avoid division by zero
    std = np.where(std < 1e-10, 1.0, std)
    return {
        "mean": mean.tolist(),
        "std": std.tolist(),
    }


def apply_standardization(
    features: np.ndarray,
    stats: dict,
) -> np.ndarray:
    """Apply z-score normalization using precomputed stats."""
    mean = np.array(stats["mean"], dtype=np.float32)
    std = np.array(stats["std"], dtype=np.float32)
    return ((features - mean) / std).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/features.py backend/tests/ml/test_features.py
git commit -m "feat(ml): add warmup removal and z-score standardization"
```

---

### Task 3: SignalLSTMv2 Model

**Files:**
- Modify: `backend/app/ml/model.py`
- Modify: `backend/tests/ml/test_model.py`

- [ ] **Step 1: Write failing tests for `SignalLSTMv2`**

Add to `backend/tests/ml/test_model.py`:

```python
from app.ml.model import SignalLSTMv2


class TestSignalLSTMv2:

    @pytest.fixture
    def model(self):
        return SignalLSTMv2(input_size=15, hidden_size=96, num_layers=2, dropout=0.3)

    def test_forward_output_shapes(self, model):
        batch = torch.randn(8, 50, 15)
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (8, 1), "Primary head: single return prediction"
        assert reg_out.shape == (8, 3), "Secondary head: sl, tp1, tp2"

    def test_return_prediction_unbounded(self, model):
        """Return prediction should have no activation — can be negative."""
        batch = torch.randn(8, 50, 15) * 5
        return_pred, _ = model(batch)
        # With random input, some predictions should be negative
        has_negative = (return_pred < 0).any()
        has_positive = (return_pred > 0).any()
        assert has_negative or has_positive  # not all zero

    def test_regression_outputs_positive(self, model):
        batch = torch.randn(8, 50, 15)
        _, reg_out = model(batch)
        assert (reg_out >= 0).all(), "SL/TP must be non-negative (ReLU)"

    def test_no_nan_outputs(self, model):
        batch = torch.randn(8, 50, 15) * 100  # large scale
        return_pred, reg_out = model(batch)
        assert not torch.isnan(return_pred).any()
        assert not torch.isnan(reg_out).any()

    def test_multiscale_pooling_short_sequence(self):
        model = SignalLSTMv2(input_size=15, hidden_size=96, num_layers=2, dropout=0.3)
        batch = torch.randn(4, 3, 15)  # shorter than pool windows
        return_pred, reg_out = model(batch)
        assert return_pred.shape == (4, 1)
        assert reg_out.shape == (4, 3)

    def test_parameter_count_smaller_than_v1(self):
        v1 = SignalLSTM(input_size=24, hidden_size=256, num_layers=3, dropout=0.3)
        v2 = SignalLSTMv2(input_size=24, hidden_size=96, num_layers=2, dropout=0.3)
        v1_params = sum(p.numel() for p in v1.parameters())
        v2_params = sum(p.numel() for p in v2.parameters())
        assert v2_params < v1_params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_model.py::TestSignalLSTMv2 -v`
Expected: FAIL — `SignalLSTMv2` doesn't exist

- [ ] **Step 3: Implement `SignalLSTMv2`**

Add to `backend/app/ml/model.py` after the `SignalLSTM` class:

```python
class SignalLSTMv2(nn.Module):
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_model.py -v`
Expected: All tests PASS (both v1 and v2)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/model.py backend/tests/ml/test_model.py
git commit -m "feat(ml): add SignalLSTMv2 regression model"
```

---

### Task 4: Regression Dataset

**Files:**
- Modify: `backend/app/ml/dataset.py`
- Modify: `backend/tests/ml/test_dataset.py`

- [ ] **Step 1: Write failing tests for `RegressionDataset`**

Add to `backend/tests/ml/test_dataset.py`:

```python
from app.ml.dataset import RegressionDataset


class TestRegressionDataset:

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
        valid[:10] = False  # first 10 invalid
        valid[-5:] = False  # last 5 invalid
        return features, forward_return, sl, tp1, tp2, valid

    def test_length_excludes_invalid(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = RegressionDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        # Valid windows: indices where target (idx + seq_len - 1) is valid
        # and idx >= 0 and idx + seq_len <= n
        assert len(ds) > 0
        assert len(ds) < 300 - 50  # less than full sliding window (some invalid)

    def test_item_shapes(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = RegressionDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
        x, y_return, y_reg = ds[0]
        assert x.shape == (50, features.shape[1])
        assert y_return.shape == ()  # scalar
        assert y_reg.shape == (3,)

    def test_item_types(self, sample_data):
        features, fwd, sl, tp1, tp2, valid = sample_data
        ds = RegressionDataset(features, fwd, sl, tp1, tp2, valid, seq_len=50)
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
        ds = RegressionDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10, noise_std=0.01)
        x, _, _ = ds[0]
        assert not torch.allclose(x, torch.ones_like(x))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_dataset.py::TestRegressionDataset -v`
Expected: FAIL — `RegressionDataset` doesn't exist

- [ ] **Step 3: Implement `RegressionDataset`**

Add to `backend/app/ml/dataset.py`:

```python
class RegressionDataset(Dataset):
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_dataset.py -v`
Expected: All tests PASS (both old CandleDataset and new RegressionDataset)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/dataset.py backend/tests/ml/test_dataset.py
git commit -m "feat(ml): add RegressionDataset with validity filtering"
```

---

### Task 5: Data Loader v2

**Files:**
- Modify: `backend/app/ml/data_loader.py`
- Modify: `backend/tests/ml/test_data_loader.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/ml/test_data_loader.py`:

```python
from app.ml.data_loader import prepare_regression_data
from app.ml.labels import RegressionTargetConfig


def _make_candle_dicts(n=500, base=67000):
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        noise = rng.uniform(-50, 50)
        c = base + noise
        candles.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - 5, "high": c + 30, "low": c - 30, "close": c, "volume": 100,
        })
    return candles


class TestPrepareRegressionData:

    def test_returns_expected_tuple(self):
        candles = _make_candle_dicts(500)
        result = prepare_regression_data(candles)
        features, fwd, sl, tp1, tp2, valid, std_stats = result
        assert features.shape[0] == fwd.shape[0]
        assert isinstance(std_stats, dict)
        assert "mean" in std_stats

    def test_warmup_rows_removed(self):
        candles = _make_candle_dicts(500)
        result = prepare_regression_data(candles)
        features, fwd, sl, tp1, tp2, valid, std_stats = result
        # Should have fewer rows than input (200 warmup removed)
        assert features.shape[0] == 300  # 500 - 200

    def test_features_are_standardized(self):
        candles = _make_candle_dicts(500)
        result = prepare_regression_data(candles)
        features = result[0]
        # After standardization, mean should be near 0, std near 1
        for col in range(min(5, features.shape[1])):
            assert abs(features[:, col].mean()) < 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_data_loader.py::TestPrepareRegressionData -v`
Expected: FAIL — `prepare_regression_data` doesn't exist

- [ ] **Step 3: Implement `prepare_regression_data`**

Add to `backend/app/ml/data_loader.py`:

```python
from app.ml.features import (
    build_feature_matrix, compute_warmup_period, drop_warmup_rows,
    compute_standardization_stats, apply_standardization,
)
from app.ml.labels import generate_regression_targets, RegressionTargetConfig


def prepare_regression_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    target_config: RegressionTargetConfig | None = None,
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

    fwd, sl, tp1, tp2, valid = generate_regression_targets(df, target_config)

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_data_loader.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/data_loader.py backend/tests/ml/test_data_loader.py
git commit -m "feat(ml): add regression data loader with warmup removal and standardization"
```

---

### Task 6: Regression Trainer with Walk-Forward Validation

**Files:**
- Modify: `backend/app/ml/trainer.py`
- Modify: `backend/app/ml/utils.py`
- Create: `backend/tests/ml/test_regression_trainer.py`

- [ ] **Step 1: Add `directional_accuracy` helper to utils.py**

Add to `backend/app/ml/utils.py`:

```python
def directional_accuracy(predictions: np.ndarray, targets: np.ndarray) -> float:
    """Fraction of predictions with matching sign to targets.

    Samples where target is near-zero (|target| < 1e-6) are excluded.
    """
    mask = np.abs(targets) > 1e-6
    if not mask.any():
        return 0.0
    pred_sign = np.sign(predictions[mask])
    target_sign = np.sign(targets[mask])
    return float((pred_sign == target_sign).mean())
```

- [ ] **Step 2: Write failing tests for `RegressionTrainer`**

Create `backend/tests/ml/test_regression_trainer.py`:

```python
import numpy as np
import pytest
import tempfile
import os

from app.ml.trainer import RegressionTrainer, RegressionTrainConfig


class TestRegressionTrainer:

    @pytest.fixture
    def training_data(self):
        """Synthetic data with learnable signal."""
        rng = np.random.default_rng(42)
        n = 600
        n_features = 15
        features = rng.standard_normal((n, n_features)).astype(np.float32)
        # Target has linear relationship with first feature + noise
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
        cfg = RegressionTrainConfig(
            epochs=5, batch_size=32, seq_len=20, hidden_size=32,
            num_layers=1, patience=5, min_epochs=3,
            checkpoint_dir=str(tmp_path),
        )
        trainer = RegressionTrainer(cfg)
        result = trainer.train_one_model(features, fwd, sl, tp1, tp2, valid)
        assert "val_huber_loss" in result
        assert "directional_accuracy" in result
        assert "best_epoch" in result
        assert os.path.exists(os.path.join(str(tmp_path), "best_model.pt"))

    def test_train_ensemble(self, training_data, tmp_path):
        features, fwd, sl, tp1, tp2, valid = training_data
        cfg = RegressionTrainConfig(
            epochs=5, batch_size=32, seq_len=20, hidden_size=32,
            num_layers=1, patience=5, min_epochs=3,
            checkpoint_dir=str(tmp_path),
        )
        trainer = RegressionTrainer(cfg)
        result = trainer.train_ensemble(
            features, fwd, sl, tp1, tp2, valid,
            feature_names=[f"f{i}" for i in range(15)],
        )
        assert "members" in result
        assert "n_members" in result
        config_path = os.path.join(str(tmp_path), "ensemble_config.json")
        assert os.path.exists(config_path)

    def test_quality_gate_excludes_bad_member(self, tmp_path):
        """Members with directional_accuracy < 0.52 should be excluded."""
        rng = np.random.default_rng(99)
        n = 400
        features = rng.standard_normal((n, 10)).astype(np.float32)
        # Pure noise — no signal to learn
        fwd = rng.standard_normal(n).astype(np.float32)
        sl = tp1 = tp2 = np.ones(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)
        cfg = RegressionTrainConfig(
            epochs=3, batch_size=32, seq_len=10, hidden_size=16,
            num_layers=1, patience=3, min_epochs=2,
            checkpoint_dir=str(tmp_path),
            directional_accuracy_gate=0.52,
        )
        trainer = RegressionTrainer(cfg)
        result = trainer.train_one_model(features, fwd, sl, tp1, tp2, valid)
        # Model on noise should have low directional accuracy
        assert "directional_accuracy" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_regression_trainer.py -v`
Expected: FAIL — `RegressionTrainer` and `RegressionTrainConfig` don't exist

- [ ] **Step 4: Implement `RegressionTrainer`**

Add to `backend/app/ml/trainer.py` after the existing `Trainer` class:

```python
from app.ml.model import SignalLSTMv2
from app.ml.dataset import RegressionDataset
from app.ml.utils import directional_accuracy


_WALKFORWARD_FOLDS = [
    (0.0, 0.60, 0.75),   # train [0%, 60%], val [60%, 75%]
    (0.0, 0.75, 0.90),   # train [0%, 75%], val [75%, 90%]
    (0.0, 0.90, 1.00),   # train [0%, 90%], val [90%, 100%]
]


@dataclass
class RegressionTrainConfig:
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


class RegressionTrainer:
    """Trains SignalLSTMv2 with Huber + SmoothL1 multi-task loss."""

    def __init__(self, config: RegressionTrainConfig):
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

        train_ds = RegressionDataset(
            features[t_start:t_end], forward_return[t_start:t_end],
            sl_atr[t_start:t_end], tp1_atr[t_start:t_end], tp2_atr[t_start:t_end],
            valid[t_start:t_end], seq_len=cfg.seq_len, noise_std=cfg.noise_std,
        )
        val_ds = RegressionDataset(
            features[v_start:v_end], forward_return[v_start:v_end],
            sl_atr[v_start:v_end], tp1_atr[v_start:v_end], tp2_atr[v_start:v_end],
            valid[v_start:v_end], seq_len=cfg.seq_len,
        )

        if len(train_ds) < cfg.batch_size:
            raise ValueError(f"Training set too small: {len(train_ds)} samples")

        train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False) if len(val_ds) > 0 else None

        model = SignalLSTMv2(
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
            from app.ml.drift import compute_regression_drift_stats
            drift_stats = compute_regression_drift_stats(
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

        # Feature selection: train fold 1, get importance, prune for folds 2-3
        # (Deferred to Task 8 — for now, use all features)

        def _train_member(idx, train_end_frac, val_end_frac):
            t_end = int(n * train_end_frac)
            v_end = int(n * val_end_frac)

            member_dir = os.path.join(staging_dir, f"member_{idx}")
            os.makedirs(member_dir, exist_ok=True)

            member_cfg = RegressionTrainConfig(
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
            member_trainer = RegressionTrainer(member_cfg)
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
            perm_model = SignalLSTMv2(
                input_size=features.shape[1], hidden_size=cfg.hidden_size,
                num_layers=cfg.num_layers, dropout=cfg.dropout,
            ).to(self.device)
            perm_model.load_state_dict(torch.load(first_pt, map_location=self.device, weights_only=True))
            perm_model.eval()

            val_start = int(n * 0.85)
            val_ds = RegressionDataset(
                features[val_start:], forward_return[val_start:],
                sl_atr[val_start:], tp1_atr[val_start:], tp2_atr[val_start:],
                valid[val_start:], seq_len=cfg.seq_len,
            )
            if len(val_ds) > 0:
                val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False)
                from app.ml.drift import compute_regression_drift_stats
                drift_stats = compute_regression_drift_stats(
                    perm_model, val_loader, features[:val_start], features.shape[1],
                )

        # Write ensemble_config.json LAST
        # Note: flow_used/regime_used/btc_used are patched by api/ml.py after training
        # (lines 339-347) since the trainer doesn't know what data sources were active.
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_regression_trainer.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ml/trainer.py backend/app/ml/utils.py backend/tests/ml/test_regression_trainer.py
git commit -m "feat(ml): add RegressionTrainer with walk-forward validation and quality gates"
```

---

### Task 7: Regression Predictor & Ensemble Predictor

**Files:**
- Modify: `backend/app/ml/predictor.py`
- Modify: `backend/app/ml/ensemble_predictor.py`
- Create: `backend/tests/ml/test_regression_predictor.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/ml/test_regression_predictor.py`:

```python
import json
import numpy as np
import os
import pytest
import torch

from app.ml.model import SignalLSTMv2


class TestRegressionPredictor:

    @pytest.fixture
    def model_dir(self, tmp_path):
        """Create a minimal saved model for testing."""
        model = SignalLSTMv2(input_size=15, hidden_size=32, num_layers=1, dropout=0.1)
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
        from app.ml.predictor import RegressionPredictor
        pred = RegressionPredictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert "ml_score" in result
        assert "confidence" in result
        assert "sl_atr" in result
        assert "direction" in result

    def test_ml_score_range(self, model_dir):
        from app.ml.predictor import RegressionPredictor
        pred = RegressionPredictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert -100 <= result["ml_score"] <= 100

    def test_confidence_range(self, model_dir):
        from app.ml.predictor import RegressionPredictor
        pred = RegressionPredictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_too_few_candles_returns_neutral(self, model_dir):
        from app.ml.predictor import RegressionPredictor
        pred = RegressionPredictor(os.path.join(model_dir, "best_model.pt"))
        features = np.random.randn(5, 15).astype(np.float32)  # too few
        result = pred.predict(features)
        assert result["confidence"] == 0.0


class TestRegressionEnsemblePredictor:

    @pytest.fixture
    def ensemble_dir(self, tmp_path):
        """Create a minimal 2-member ensemble."""
        for idx in range(2):
            model = SignalLSTMv2(input_size=15, hidden_size=32, num_layers=1, dropout=0.1)
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
        from app.ml.ensemble_predictor import RegressionEnsemblePredictor
        pred = RegressionEnsemblePredictor(ensemble_dir)
        features = np.random.randn(50, 15).astype(np.float32)
        result = pred.predict(features)
        assert "ml_score" in result
        assert "confidence" in result
        assert "ensemble_disagreement" in result
        assert "direction" in result

    def test_skips_excluded_members(self, tmp_path):
        """Members marked excluded should not be loaded."""
        for idx in range(3):
            model = SignalLSTMv2(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
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
        from app.ml.ensemble_predictor import RegressionEnsemblePredictor
        pred = RegressionEnsemblePredictor(str(tmp_path))
        assert pred.n_members == 2  # excluded member not counted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_regression_predictor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `RegressionPredictor`**

Add to `backend/app/ml/predictor.py`:

```python
from app.ml.model import SignalLSTMv2

_REGRESSION_NEUTRAL = {
    "direction": "NEUTRAL",
    "ml_score": 0.0,
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
    "mc_variance": 0.0,
}

SCORE_SCALE = 40  # ±2.5 ATR saturates at ±100


class RegressionPredictor:
    """Inference wrapper for SignalLSTMv2 regression model."""

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

        self.model = SignalLSTMv2(
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
            return dict(_REGRESSION_NEUTRAL)

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

- [ ] **Step 4: Implement `RegressionEnsemblePredictor`**

Add to `backend/app/ml/ensemble_predictor.py`:

```python
from app.ml.model import SignalLSTMv2
from app.ml.predictor import SCORE_SCALE

_REGRESSION_NEUTRAL = {
    "direction": "NEUTRAL",
    "ml_score": 0.0,
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
    "ensemble_disagreement": 0.0,
}


class RegressionEnsemblePredictor:
    """Ensemble inference for SignalLSTMv2 regression members."""

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
                model = SignalLSTMv2(
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
            return dict(_REGRESSION_NEUTRAL)

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

- [ ] **Step 5: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_regression_predictor.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ml/predictor.py backend/app/ml/ensemble_predictor.py backend/tests/ml/test_regression_predictor.py
git commit -m "feat(ml): add regression predictor and ensemble predictor"
```

---

### Task 8: Config, Constants & Combiner Updates

**Files:**
- Modify: `backend/app/config.py:126,133-134`
- Modify: `backend/app/engine/constants.py:172-173`
- Modify: `backend/app/engine/combiner.py:100,114,121-127`
- Modify: `backend/tests/engine/test_combiner.py`

- [ ] **Step 1: Update config defaults**

In `backend/app/config.py`, change:
- Line 126: `ml_confidence_threshold: float = 0.65` → `ml_confidence_threshold: float = 0.40`
- Line 133: `engine_ml_weight_min: float = 0.05` → `engine_ml_weight_min: float = 0.20`
- Line 134: `engine_ml_weight_max: float = 0.30` → `engine_ml_weight_max: float = 0.50`

- [ ] **Step 2: Update constants**

In `backend/app/engine/constants.py`, change:
- Line 172: `ML_WEIGHT_MIN = 0.05` → `ML_WEIGHT_MIN = 0.20`
- Line 173: `ML_WEIGHT_MAX = 0.30` → `ML_WEIGHT_MAX = 0.50`

- [ ] **Step 3: Update blend_with_ml threshold ramp**

In `backend/app/engine/combiner.py`, change line 114:
```python
# Old:
t = (ml_confidence - ml_confidence_threshold) / (1.0 - ml_confidence_threshold)
# New:
t = (ml_confidence - ml_confidence_threshold) / max(1.0 - ml_confidence_threshold, 0.01)
```

And update `compute_agreement` (lines 121-127) to handle numeric ml_score directly — no change needed, it already accepts `float | None` and checks sign. This is already correct for regression output.

- [ ] **Step 4: Update combiner tests if any assert on old threshold/weight values**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py tests/engine/test_combiner_confidence.py -v`

If any tests fail due to changed defaults, update those test assertions to match the new default values.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/engine/constants.py backend/app/engine/combiner.py backend/tests/engine/test_combiner.py
git commit -m "feat(ml): update blend threshold 0.65->0.40 and weight ramp 0.20-0.50"
```

---

### Task 9: Regression-Compatible Drift Detection

**Files:**
- Modify: `backend/app/ml/drift.py`
- Create: `backend/tests/ml/test_regression_drift.py`

The existing `compute_permutation_importance` uses `nn.CrossEntropyLoss` on 3-class logits (`drift.py:168-180`). SignalLSTMv2 returns `(return_pred, reg_out)` where return_pred is `(batch, 1)`, not class logits. The val_loader also yields `(x, y_return, y_reg)` where `y_return` is a float, not a class index. Both the loss function and the data format are incompatible.

- [ ] **Step 1: Write failing test**

Create `backend/tests/ml/test_regression_drift.py`:

```python
import numpy as np
import torch
import pytest
from torch.utils.data import DataLoader

from app.ml.model import SignalLSTMv2
from app.ml.dataset import RegressionDataset
from app.ml.drift import compute_regression_drift_stats


class TestRegressionDriftStats:

    def test_computes_without_error(self):
        model = SignalLSTMv2(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
        model.eval()

        n = 200
        features = np.random.randn(n, 10).astype(np.float32)
        fwd = np.random.randn(n).astype(np.float32)
        sl = tp1 = tp2 = np.ones(n, dtype=np.float32)
        valid = np.ones(n, dtype=bool)

        ds = RegressionDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10)
        loader = DataLoader(ds, batch_size=32, shuffle=False)

        result = compute_regression_drift_stats(model, loader, features, 10)
        assert result is not None
        assert "top_feature_indices" in result
        assert "feature_distributions" in result

    def test_returns_none_on_empty_loader(self):
        model = SignalLSTMv2(input_size=10, hidden_size=16, num_layers=1, dropout=0.1)
        model.eval()

        features = np.random.randn(5, 10).astype(np.float32)
        fwd = np.random.randn(5).astype(np.float32)
        sl = tp1 = tp2 = np.ones(5, dtype=np.float32)
        valid = np.zeros(5, dtype=bool)  # all invalid

        ds = RegressionDataset(features, fwd, sl, tp1, tp2, valid, seq_len=10)
        loader = DataLoader(ds, batch_size=32, shuffle=False)

        result = compute_regression_drift_stats(model, loader, features, 10)
        # Empty dataset → None or empty stats
        assert result is None or len(result.get("top_feature_indices", [])) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_regression_drift.py -v`
Expected: FAIL — `compute_regression_drift_stats` doesn't exist

- [ ] **Step 3: Implement regression drift functions**

Add to `backend/app/ml/drift.py` after the existing `compute_drift_stats`:

```python
def compute_regression_permutation_importance(
    model: nn.Module,
    val_loader,
    input_size: int,
    n_repeats: int = 3,
) -> list[tuple[int, float]]:
    """Permutation importance using HuberLoss for regression models.

    val_loader yields (x, y_return, y_reg) from RegressionDataset.
    model returns (return_pred, reg_out) from SignalLSTMv2.
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


def compute_regression_drift_stats(
    model: nn.Module,
    val_loader,
    training_features: np.ndarray,
    input_size: int,
    top_n: int = 5,
    n_repeats: int = 3,
) -> dict | None:
    """Compute drift stats for regression models (SignalLSTMv2)."""
    try:
        importance = compute_regression_permutation_importance(
            model, val_loader, input_size, n_repeats=n_repeats,
        )
        top_indices = [idx for idx, _ in importance[:top_n]]
        distributions = {}
        for idx in top_indices:
            distributions[str(idx)] = compute_feature_distributions(
                training_features[:, idx], n_bins=10,
            )
        logger.info("Regression drift stats computed for top %d features: %s", top_n, top_indices)
        return {
            "top_feature_indices": top_indices,
            "feature_distributions": distributions,
        }
    except Exception as e:
        logger.warning("Failed to compute regression drift stats: %s", e)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_regression_drift.py tests/ml/test_drift.py -v`
Expected: All PASS (old classification drift tests unchanged, new regression tests pass)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/drift.py backend/tests/ml/test_regression_drift.py
git commit -m "feat(ml): add regression-compatible drift detection with HuberLoss"
```

---

### Task 10: Redis Cache, Main Pipeline, API Integration

**Files:**
- Modify: `backend/app/main.py` (5 cache locations + ML score wiring)
- Modify: `backend/app/engine/backtester.py` (blend_with_ml call)
- Modify: `backend/app/api/ml.py` (training endpoint + _reload_predictors)

- [ ] **Step 1: Increase Redis cache from 200 to 300**

In `backend/app/main.py`, find all 5 locations with `-200` and change to `-300`:
- Line 646: `await redis.lrange(cache_key, -300, -1)`
- Line 1034: `await redis.lrange(btc_key, -300, -1)`
- Lines 1517-1518: `await redis.ltrim(cache_key, -300, -1)`
- Line 1638: `await redis.lrange(cache_key, -300, -1)`
- Line 1904: `pipe.ltrim(cache_key, -300, -1)`

- [ ] **Step 2: Update main.py ml_score extraction**

In `backend/app/main.py`, replace lines 1135-1145 (the current ml_score derivation):

```python
# Old code (lines 1135-1145):
ml_direction = ml_prediction["direction"]
ml_confidence = ml_prediction["confidence"]
if ml_direction == "NEUTRAL":
    ml_score = 0.0
else:
    centered = (ml_confidence - 1 / 3) / (2 / 3) * 100
    ml_score = centered if ml_direction == "LONG" else -centered
```

Replace with:

```python
ml_direction = ml_prediction["direction"]
ml_confidence = ml_prediction["confidence"]

# v2 regression predictors return ml_score directly;
# v1 classification predictors derive it from direction + confidence
if "ml_score" in ml_prediction:
    ml_score = ml_prediction["ml_score"]
else:
    if ml_direction == "NEUTRAL":
        ml_score = 0.0
    else:
        centered = (ml_confidence - 1 / 3) / (2 / 3) * 100
        ml_score = centered if ml_direction == "LONG" else -centered
```

This is backward-compatible: v1 predictors (without `ml_score` key) fall through to the old derivation, v2 predictors use the direct score.

- [ ] **Step 3: Update backtester to pass config weights**

In `backend/app/engine/backtester.py`, at the `blend_with_ml()` call site (~line 363), add the weight parameters:

```python
score = blend_with_ml(
    indicator_preliminary, ml_score, ml_confidence,
    ml_weight_min=config.engine_ml_weight_min,
    ml_weight_max=config.engine_ml_weight_max,
    ml_confidence_threshold=config.ml_confidence_threshold,
)
```

- [ ] **Step 4: Update _reload_predictors to detect model version**

In `backend/app/api/ml.py`, update the `_reload_predictors` function (line 814). Replace the try block (lines 846-878) with version-aware loading:

```python
        try:
            if os.path.isfile(ensemble_config):
                import json as _j
                with open(ensemble_config) as f:
                    meta = _j.load(f)
                model_version = meta.get("model_version", "v1")

                if model_version == "v2":
                    from app.ml.ensemble_predictor import RegressionEnsemblePredictor
                    predictor = RegressionEnsemblePredictor(
                        pair_dir,
                        ensemble_disagreement_scale=disagreement_scale,
                        stale_fresh_days=stale_fresh,
                        stale_decay_days=stale_decay,
                        stale_floor=stale_floor,
                        confidence_cap_partial=cap_partial,
                        drift_config=drift_config,
                    )
                    logger.info(
                        "Regression ensemble predictor loaded for %s (%d members)",
                        entry, predictor.n_members,
                    )
                else:
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
            elif os.path.isfile(model_path):
                predictor = Predictor(
                    model_path,
                    drift_config=drift_config,
                )
                logger.info("Legacy predictor loaded for %s", entry)
            else:
                continue
```

- [ ] **Step 5: Update training endpoint to use regression pipeline**

In `backend/app/api/ml.py`, update the training code block (around lines 234-310). Replace the data preparation and trainer instantiation:

```python
# Replace prepare_training_data call (line 238) with:
from app.ml.data_loader import prepare_regression_data
from app.ml.labels import RegressionTargetConfig

target_config = RegressionTargetConfig(
    horizon=body.label_horizon * 2 if timeframe == "15m" else body.label_horizon,
)
features, fwd, sl, tp1, tp2, valid, std_stats = prepare_regression_data(
    candles,
    order_flow=flow,
    target_config=target_config,
    btc_candles=btc_candles_list,
    regime=regime_list,
    trend_conviction=conviction_list,
)

# Replace TrainConfig + Trainer (lines 251-309) with:
from app.ml.trainer import RegressionTrainer, RegressionTrainConfig

train_config = RegressionTrainConfig(
    epochs=body.epochs,
    batch_size=body.batch_size,
    seq_len=body.seq_len,
    hidden_size=body.hidden_size,
    num_layers=body.num_layers,
    dropout=body.dropout,
    lr=body.lr,
    checkpoint_dir=pair_checkpoint_dir,
)

trainer = RegressionTrainer(train_config)
ensemble_result = await asyncio.to_thread(
    trainer.train_ensemble, features, fwd, sl, tp1, tp2, valid,
    on_progress, train_feature_names,
)
```

- [ ] **Step 6: Update pair_results construction for regression metrics**

In `backend/app/api/ml.py`, replace the pair_result extraction (lines 312-332) and pair_results construction (lines 349-368):

```python
# After train_ensemble returns:
if ensemble_result["n_members"] == 0:
    # All members failed quality gates
    pair_results[pair] = {
        "best_epoch": 0, "best_val_loss": None,
        "total_epochs": 0, "total_samples": len(features),
        "flow_data_used": flow_used, "version": None,
        "directional_accuracy": 0.0, "ensemble_members": ensemble_result["members"],
        "loss_history": [],
    }
else:
    # Use best active member for DB summary
    active = [m for m in ensemble_result["members"] if not m.get("excluded")]
    best_member = min(active, key=lambda m: m["val_huber_loss"])
    pair_results[pair] = {
        "best_epoch": best_member.get("best_epoch", 0),
        "best_val_loss": best_member["val_huber_loss"],
        "total_epochs": 0,
        "total_samples": len(features),
        "flow_data_used": flow_used,
        "version": None,
        "directional_accuracy": best_member.get("directional_accuracy", 0.0),
        "prediction_std": best_member.get("prediction_std", 0.0),
        "ensemble_members": ensemble_result["members"],
        "loss_history": [],
    }
```

Note: the old keys `direction_accuracy`, `precision_per_class`, `recall_per_class` are replaced by `directional_accuracy` and `prediction_std`. Since these are stored in JSONB (`MLTrainingRun.result`), no DB migration is needed — the schema is flexible.

- [ ] **Step 7: Save standardization stats alongside ensemble config**

After the ensemble config is patched with flow_used/regime_used/btc_used (lines 339-347 in ml.py), also save the standardization stats for inference-time use:

```python
# After the existing meta patching block:
if std_stats is not None:
    import json as _j
    stats_path = os.path.join(pair_checkpoint_dir, "standardization_stats.json")
    with open(stats_path, "w") as f:
        _j.dump(std_stats, f, indent=2)
```

- [ ] **Step 8: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests pass. Fix any failures from changed defaults.

- [ ] **Step 9: Commit**

```bash
git add backend/app/main.py backend/app/engine/backtester.py backend/app/api/ml.py
git commit -m "feat(ml): integrate regression pipeline — cache 300, v2 predictors, updated blending"
```

---

### Task 11: Feature Selection (Post-Fold-1)

**Files:**
- Modify: `backend/app/ml/trainer.py` (inside `RegressionTrainer.train_ensemble`)
- Modify: `backend/app/ml/features.py`
- Create: `backend/tests/ml/test_feature_selection.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/ml/test_feature_selection.py`:

```python
import numpy as np
from app.ml.features import select_features_by_importance


class TestFeatureSelection:

    def test_drops_low_importance_features(self):
        importances = np.array([0.30, 0.25, 0.20, 0.15, 0.05, 0.03, 0.02])
        names = ["f0", "f1", "f2", "f3", "f4", "f5", "f6"]
        selected, indices = select_features_by_importance(
            importances, names, threshold=0.01,
        )
        # f5 (3%) and f6 (2%) should be kept (above 1% of total)
        # All features are above 1% threshold in this case
        assert len(selected) == 7

    def test_drops_below_threshold(self):
        importances = np.array([0.50, 0.30, 0.15, 0.04, 0.005, 0.005])
        names = ["f0", "f1", "f2", "f3", "f4", "f5"]
        selected, indices = select_features_by_importance(
            importances, names, threshold=0.01,
        )
        # f4 and f5 are each 0.5% of total — below 1%
        assert "f4" not in selected
        assert "f5" not in selected
        assert len(selected) == 4
```

- [ ] **Step 2: Implement `select_features_by_importance`**

Add to `backend/app/ml/features.py`:

```python
def select_features_by_importance(
    importances: np.ndarray,
    feature_names: list[str],
    threshold: float = 0.01,
) -> tuple[list[str], list[int]]:
    """Select features contributing above threshold fraction of total importance.

    Args:
        importances: Per-feature importance scores.
        feature_names: Feature names matching importances.
        threshold: Minimum fraction of total importance to keep.

    Returns:
        (selected_names, selected_indices) — features that passed.
    """
    total = importances.sum()
    if total <= 0:
        return list(feature_names), list(range(len(feature_names)))
    fractions = importances / total
    selected_names = []
    selected_indices = []
    for i, (name, frac) in enumerate(zip(feature_names, fractions)):
        if frac >= threshold:
            selected_names.append(name)
            selected_indices.append(i)
    return selected_names, selected_indices
```

- [ ] **Step 3: Run tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_feature_selection.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/ml/features.py backend/tests/ml/test_feature_selection.py
git commit -m "feat(ml): add permutation importance feature selection"
```

---

### Task 12: Run Full Test Suite & Verify

- [ ] **Step 1: Run all tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v --tb=short`

Fix any remaining failures.

- [ ] **Step 2: Verify old classification code still works**

The old `SignalLSTM`, `Predictor`, `EnsemblePredictor`, and `generate_labels` are still in the codebase. Existing tests for them should still pass since we added new classes alongside, not replaced.

- [ ] **Step 3: Final commit with all fixes**

```bash
git add -A
git commit -m "feat(ml): ML regression overhaul — complete implementation"
```
