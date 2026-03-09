# ML Signal Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the rule-based scoring engine with a PyTorch LSTM model that predicts trade direction (LONG/SHORT/NEUTRAL) and optimal SL/TP levels, ensembled with the existing LLM gate.

**Architecture:** A per-pair multi-head LSTM processes 50-candle sequences of normalized features (OHLCV + indicators) and outputs direction probabilities + SL/TP distances as ATR multiples. One model is trained per trading pair to avoid cross-pair boundary artifacts. The LLM gate runs on every ML signal as an ensemble voter — both must agree for full-confidence signals. Training happens offline via API endpoint; inference runs in the live pipeline replacing `compute_technical_score()` + `compute_preliminary_score()`. Checkpoints are stored at `models/{pair_slug}/best_model.pt`.

**Tech Stack:** PyTorch (LSTM), pandas/numpy (features), SQLAlchemy (data loading), existing FastAPI infrastructure.

---

## Phase 1: Data Foundation

**Checkpoint:** After this phase, order flow data is persisted to Postgres, 1 year of candle history is importable, and the `OrderFlowSnapshot` table exists with a migration.

---

### Task 1: Add OrderFlowSnapshot DB model

**Files:**
- Modify: `backend/app/db/models.py:176` (before BacktestRun class)
- Test: `backend/tests/test_db_models.py`

**Step 1: Write the failing test**

Add to `backend/tests/test_db_models.py`:

```python
from app.db.models import OrderFlowSnapshot

def test_order_flow_snapshot_instantiation():
    snap = OrderFlowSnapshot(
        pair="BTC-USDT-SWAP",
        funding_rate=0.0001,
        open_interest=500000000.0,
        oi_change_pct=0.02,
        long_short_ratio=1.3,
    )
    assert snap.pair == "BTC-USDT-SWAP"
    assert snap.funding_rate == 0.0001
    assert snap.long_short_ratio == 1.3
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/test_db_models.py::test_order_flow_snapshot_instantiation -v`
Expected: FAIL with `ImportError: cannot import name 'OrderFlowSnapshot'`

**Step 3: Write minimal implementation**

Add to `backend/app/db/models.py` before the `BacktestRun` class (line 176):

```python
class OrderFlowSnapshot(Base):
    __tablename__ = "order_flow_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    funding_rate: Mapped[float | None] = mapped_column(Float)
    open_interest: Mapped[float | None] = mapped_column(Float)
    oi_change_pct: Mapped[float | None] = mapped_column(Float)
    long_short_ratio: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_oflow_pair_ts", "pair", "timestamp"),
    )
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/test_db_models.py::test_order_flow_snapshot_instantiation -v`
Expected: PASS

**Step 5: Create Alembic migration**

Run: `docker exec krypton-api-1 alembic revision --autogenerate -m "add order_flow_snapshots table"`
Then: `docker exec krypton-api-1 alembic upgrade head`

---

### Task 2: Persist order flow data on each candle tick

**Files:**
- Modify: `backend/app/main.py:136-168` (in `run_pipeline()`)

**Step 1: Write the persistence logic**

In `backend/app/main.py`, add an import at the top with the other model imports:

```python
from app.db.models import OrderFlowSnapshot
```

In `run_pipeline()`, after line 168 (`flow_result = compute_order_flow_score(flow_metrics)`), add:

```python
    # Persist order flow snapshot for ML training data
    if flow_metrics:
        try:
            async with db.session_factory() as session:
                snap = OrderFlowSnapshot(
                    pair=pair,
                    funding_rate=flow_metrics.get("funding_rate"),
                    open_interest=flow_metrics.get("open_interest"),
                    oi_change_pct=flow_metrics.get("open_interest_change_pct"),
                    long_short_ratio=flow_metrics.get("long_short_ratio"),
                )
                session.add(snap)
                await session.commit()
        except Exception as e:
            logger.debug(f"Order flow snapshot save skipped: {e}")
```

**Step 2: Verify existing tests still pass**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline.py -v`
Expected: PASS (existing pipeline tests should not break)

---

### Task 3: Add PyTorch to dependencies

**Files:**
- Modify: `backend/requirements.txt`

**Step 1: Add torch dependency**

Add to `backend/requirements.txt` after `numpy==2.4.2`:

```
torch==2.6.0+cpu --extra-index-url https://download.pytorch.org/whl/cpu
```

Note: Using CPU-only PyTorch. `--extra-index-url` (not `--index-url`) is required so PyPI is still available for other packages. GPU support can be added later by changing the index URL.

**Step 2: Convert Dockerfile to multi-stage build**

The CPU-only torch package adds ~800MB. Use a multi-stage build to keep the final image leaner. Replace `backend/Dockerfile`:

```dockerfile
# --- Builder stage: install all Python deps ---
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Runtime stage: copy only installed packages ---
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    redis-tools \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

COPY . .

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Rebuild Docker image**

Run: `docker compose build api`
Then: `docker compose up -d`

**Step 4: Verify torch imports work**

Run: `docker exec krypton-api-1 python -c "import torch; print(torch.__version__)"`
Expected: `2.6.0+cpu` (or similar)

---

## Phase 2: Feature Engineering & Labeling

**Checkpoint:** After this phase, raw candle + order flow data can be transformed into normalized feature tensors and labeled training samples. All feature/label logic is tested independently.

---

### Task 4: Create feature engineering module

**Files:**
- Create: `backend/app/ml/__init__.py`
- Create: `backend/app/ml/features.py`
- Create: `backend/tests/ml/__init__.py`
- Test: `backend/tests/ml/test_features.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/__init__.py` (empty file).

Create `backend/tests/ml/test_features.py`:

```python
import numpy as np
import pandas as pd
import pytest

from app.ml.features import build_feature_matrix


def _make_candles(n=60, base=67000, trend=10):
    data = []
    for i in range(n):
        o = base + i * trend
        h = o + 50
        l = o - 30
        c = o + 20
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": 100 + i})
    return pd.DataFrame(data)


class TestBuildFeatureMatrix:

    def test_output_shape(self):
        df = _make_candles(100)
        features = build_feature_matrix(df)
        # Should have rows for each candle and multiple feature columns
        assert features.shape[0] == 100
        assert features.shape[1] >= 15  # at least 15 features per candle

    def test_no_nan_after_warmup(self):
        df = _make_candles(100)
        features = build_feature_matrix(df)
        # First 50 rows may have NaN from indicator warmup; after that, none
        assert not np.any(np.isnan(features[50:]))

    def test_values_are_normalized(self):
        df = _make_candles(100)
        features = build_feature_matrix(df)
        # After warmup, values should be roughly in [-5, 5] range (z-scored)
        valid = features[50:]
        assert np.abs(valid).max() < 20  # no extreme outliers

    def test_includes_order_flow_columns(self):
        df = _make_candles(60)
        flow = [{"funding_rate": 0.0001, "oi_change_pct": 0.02, "long_short_ratio": 1.3}] * 60
        features = build_feature_matrix(df, order_flow=flow)
        # Should have 3 more columns than without flow
        features_no_flow = build_feature_matrix(df)
        assert features.shape[1] == features_no_flow.shape[1] + 3
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ml'`

**Step 3: Write minimal implementation**

Create `backend/app/ml/__init__.py` (empty file).

Create `backend/app/ml/features.py`:

```python
"""Feature engineering pipeline for ML model training and inference."""

import numpy as np
import pandas as pd


# Feature column order (for documentation and consistency)
PRICE_FEATURES = [
    "ret",           # close-to-close return
    "body_ratio",    # (close - open) / (high - low)
    "upper_wick",    # (high - max(open, close)) / (high - low)
    "lower_wick",    # (min(open, close) - low) / (high - low)
    "volume_zscore", # z-scored volume over lookback
]

INDICATOR_FEATURES = [
    "ema9_dist",     # (close - EMA9) / ATR
    "ema21_dist",    # (close - EMA21) / ATR
    "ema50_dist",    # (close - EMA50) / ATR
    "rsi_norm",      # (RSI - 50) / 50 → [-1, 1]
    "macd_norm",     # MACD histogram / close * 10000
    "bb_position",   # (close - BB_lower) / (BB_upper - BB_lower)
    "bb_width",      # (BB_upper - BB_lower) / close
    "atr_pct",       # ATR / close
]

TEMPORAL_FEATURES = [
    "hour_sin",      # sin(2π * hour / 24)
    "hour_cos",      # cos(2π * hour / 24)
]

FLOW_FEATURES = [
    "funding_rate",
    "oi_change_pct",
    "long_short_ratio_norm",  # (ls_ratio - 1.0), centered at neutral
]

ALL_FEATURES = PRICE_FEATURES + INDICATOR_FEATURES + TEMPORAL_FEATURES
ALL_FEATURES_WITH_FLOW = ALL_FEATURES + FLOW_FEATURES


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def build_feature_matrix(
    candles: pd.DataFrame,
    order_flow: list[dict] | None = None,
) -> np.ndarray:
    """Build normalized feature matrix from candle data.

    Args:
        candles: DataFrame with columns: open, high, low, close, volume.
                 Optionally 'timestamp' for temporal features.
        order_flow: Optional list of dicts (one per candle) with keys:
                    funding_rate, oi_change_pct, long_short_ratio.

    Returns:
        np.ndarray of shape (n_candles, n_features).
        First ~50 rows may contain NaN due to indicator warmup.
    """
    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)

    features = np.zeros((n, len(ALL_FEATURES)), dtype=np.float32)

    close = df["close"].astype(float)
    opn = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)

    hl_range = (high - low).replace(0, np.nan)

    # Price features
    features[:, 0] = close.pct_change().fillna(0).values                         # ret
    features[:, 1] = ((close - opn) / hl_range).fillna(0).values                 # body_ratio
    features[:, 2] = ((high - np.maximum(opn, close)) / hl_range).fillna(0).values  # upper_wick
    features[:, 3] = ((np.minimum(opn, close) - low) / hl_range).fillna(0).values   # lower_wick

    vol_mean = vol.rolling(20, min_periods=1).mean()
    vol_std = vol.rolling(20, min_periods=1).std().replace(0, 1)
    features[:, 4] = ((vol - vol_mean) / vol_std).fillna(0).values               # volume_zscore

    # Indicators
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_safe = atr.replace(0, np.nan)

    features[:, 5] = ((close - ema9) / atr_safe).fillna(0).values                # ema9_dist
    features[:, 6] = ((close - ema21) / atr_safe).fillna(0).values               # ema21_dist
    features[:, 7] = ((close - ema50) / atr_safe).fillna(0).values               # ema50_dist

    rsi = _rsi(close, 14)
    features[:, 8] = ((rsi - 50) / 50).fillna(0).values                          # rsi_norm

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd_hist = (ema12 - ema26) - _ema(ema12 - ema26, 9)
    features[:, 9] = (macd_hist / close * 10000).fillna(0).values                # macd_norm

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    features[:, 10] = ((close - bb_lower) / bb_range).fillna(0).values           # bb_position
    features[:, 11] = ((bb_upper - bb_lower) / close).fillna(0).values           # bb_width
    features[:, 12] = (atr / close).fillna(0).values                             # atr_pct

    # Temporal features (if timestamp available)
    if "timestamp" in df.columns:
        try:
            ts = pd.to_datetime(df["timestamp"])
            hours = ts.dt.hour + ts.dt.minute / 60
            features[:, 13] = np.sin(2 * np.pi * hours / 24).values              # hour_sin
            features[:, 14] = np.cos(2 * np.pi * hours / 24).values              # hour_cos
        except Exception:
            pass  # leave as zeros

    # Clip extreme values
    features = np.clip(features, -10, 10)

    # Order flow features
    if order_flow is not None and len(order_flow) == n:
        flow_arr = np.zeros((n, len(FLOW_FEATURES)), dtype=np.float32)
        for i, f in enumerate(order_flow):
            flow_arr[i, 0] = f.get("funding_rate", 0) * 10000  # scale up
            flow_arr[i, 1] = f.get("oi_change_pct", 0) * 100   # to percent
            flow_arr[i, 2] = f.get("long_short_ratio", 1.0) - 1.0  # center at 0
        flow_arr = np.clip(flow_arr, -10, 10)
        features = np.concatenate([features, flow_arr], axis=1)

    return features
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_features.py -v`
Expected: PASS

---

### Task 5: Create label generation module

**Files:**
- Create: `backend/app/ml/labels.py`
- Test: `backend/tests/ml/test_labels.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/test_labels.py`:

```python
import numpy as np
import pandas as pd
import pytest

from app.ml.labels import generate_labels, LabelConfig


def _make_candles_with_known_move(n=100, base=67000):
    """First 80 candles flat, then sharp up move."""
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    data = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        if i < 80:
            c = base + rng.uniform(-10, 10)
        else:
            c = base + (i - 80) * 200  # sharp up
        data.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - 5, "high": c + 20, "low": c - 20, "close": c, "volume": 100,
        })
    return pd.DataFrame(data)


class TestGenerateLabels:

    def test_output_shape(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        direction, sl_atr, tp1_atr, tp2_atr = generate_labels(df, config)
        assert len(direction) == len(df)
        assert len(sl_atr) == len(df)

    def test_labels_are_valid_classes(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        direction, _, _, _ = generate_labels(df, config)
        # 0=NEUTRAL, 1=LONG, 2=SHORT
        assert set(np.unique(direction)).issubset({0, 1, 2})

    def test_last_horizon_candles_are_neutral(self):
        df = _make_candles_with_known_move(100)
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        direction, _, _, _ = generate_labels(df, config)
        # Last 10 candles can't look forward far enough — should be NEUTRAL
        assert all(direction[-10:] == 0)

    def test_regression_targets_positive(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=1.0)
        _, sl_atr, tp1_atr, tp2_atr = generate_labels(df, config)
        # SL/TP distances should be non-negative where defined
        valid = sl_atr[sl_atr > 0]
        assert (valid >= 0).all()

    def test_high_threshold_mostly_neutral(self):
        df = _make_candles_with_known_move()
        config = LabelConfig(horizon=10, threshold_pct=50.0)  # 50% move required
        direction, _, _, _ = generate_labels(df, config)
        # Almost all should be NEUTRAL with such high threshold
        neutral_pct = (direction == 0).sum() / len(direction)
        assert neutral_pct > 0.9
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_labels.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `backend/app/ml/labels.py`:

```python
"""Label generation for ML training — fixed % threshold method."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


# Direction classes
NEUTRAL = 0
LONG = 1
SHORT = 2


@dataclass
class LabelConfig:
    horizon: int = 24       # candles to look forward
    threshold_pct: float = 1.5  # minimum % move for non-neutral label


def generate_labels(
    candles: pd.DataFrame,
    config: LabelConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate direction labels and SL/TP regression targets.

    Args:
        candles: DataFrame with open, high, low, close columns.
        config: Label generation parameters.

    Returns:
        Tuple of (direction, sl_atr, tp1_atr, tp2_atr), each np.ndarray of length n.
        direction: 0=NEUTRAL, 1=LONG, 2=SHORT.
        sl_atr, tp1_atr, tp2_atr: optimal distances in ATR units (0 for NEUTRAL).
    """
    if config is None:
        config = LabelConfig()

    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)

    close = df["close"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values

    # Compute ATR for normalizing SL/TP distances
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    atr_safe = np.where(atr > 0, atr, 1.0)

    direction = np.zeros(n, dtype=np.int64)
    sl_atr = np.zeros(n, dtype=np.float32)
    tp1_atr = np.zeros(n, dtype=np.float32)
    tp2_atr = np.zeros(n, dtype=np.float32)

    threshold = config.threshold_pct / 100.0

    for i in range(n - config.horizon):
        future_high = high[i + 1 : i + 1 + config.horizon]
        future_low = low[i + 1 : i + 1 + config.horizon]
        future_close = close[i + 1 : i + 1 + config.horizon]

        price = close[i]
        if price <= 0:
            continue

        max_up = (future_high.max() - price) / price    # max favorable for LONG
        max_down = (price - future_low.min()) / price    # max favorable for SHORT

        if max_up >= threshold and max_up > max_down:
            direction[i] = LONG

            # MFE/MAE for LONG
            cum_max = np.maximum.accumulate(future_high)
            cum_min = np.minimum.accumulate(future_low)
            mae = (price - cum_min.min()) / atr_safe[i]  # worst drawdown
            mfe_median = np.median((future_high - price)) / atr_safe[i]
            mfe_75 = np.percentile((future_high - price), 75) / atr_safe[i]

            sl_atr[i] = max(mae, 0.5)  # minimum 0.5 ATR SL
            tp1_atr[i] = max(mfe_median, 0.5)
            tp2_atr[i] = max(mfe_75, 1.0)

        elif max_down >= threshold and max_down > max_up:
            direction[i] = SHORT

            # MFE/MAE for SHORT
            cum_min = np.minimum.accumulate(future_low)
            cum_max = np.maximum.accumulate(future_high)
            mae = (cum_max.max() - price) / atr_safe[i]
            mfe_median = np.median((price - future_low)) / atr_safe[i]
            mfe_75 = np.percentile((price - future_low), 75) / atr_safe[i]

            sl_atr[i] = max(mae, 0.5)
            tp1_atr[i] = max(mfe_median, 0.5)
            tp2_atr[i] = max(mfe_75, 1.0)

    return direction, sl_atr, tp1_atr, tp2_atr
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_labels.py -v`
Expected: PASS

---

### Task 6: Create PyTorch Dataset

**Files:**
- Create: `backend/app/ml/dataset.py`
- Test: `backend/tests/ml/test_dataset.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/test_dataset.py`:

```python
import numpy as np
import torch
import pytest

from app.ml.dataset import CandleDataset


class TestCandleDataset:

    @pytest.fixture
    def sample_data(self):
        n = 200
        n_features = 15
        features = np.random.randn(n, n_features).astype(np.float32)
        direction = np.random.randint(0, 3, size=n).astype(np.int64)
        sl = np.random.uniform(0.5, 3.0, size=n).astype(np.float32)
        tp1 = np.random.uniform(1.0, 4.0, size=n).astype(np.float32)
        tp2 = np.random.uniform(2.0, 6.0, size=n).astype(np.float32)
        return features, direction, sl, tp1, tp2

    def test_length(self, sample_data):
        features, direction, sl, tp1, tp2 = sample_data
        ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=50)
        # Should have n - seq_len valid sequences
        assert len(ds) == 200 - 50

    def test_item_shapes(self, sample_data):
        features, direction, sl, tp1, tp2 = sample_data
        ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=50)
        x, y_dir, y_reg = ds[0]
        assert x.shape == (50, features.shape[1])
        assert y_dir.shape == ()  # scalar
        assert y_reg.shape == (3,)  # sl, tp1, tp2

    def test_item_types(self, sample_data):
        features, direction, sl, tp1, tp2 = sample_data
        ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=50)
        x, y_dir, y_reg = ds[0]
        assert x.dtype == torch.float32
        assert y_dir.dtype == torch.long
        assert y_reg.dtype == torch.float32
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_dataset.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `backend/app/ml/dataset.py`:

```python
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
    ):
        self.features = torch.tensor(features, dtype=torch.float32)
        self.direction = torch.tensor(direction, dtype=torch.long)
        self.regression = torch.stack([
            torch.tensor(sl_atr, dtype=torch.float32),
            torch.tensor(tp1_atr, dtype=torch.float32),
            torch.tensor(tp2_atr, dtype=torch.float32),
        ], dim=1)
        self.seq_len = seq_len

    def __len__(self):
        return len(self.features) - self.seq_len

    def __getitem__(self, idx):
        x = self.features[idx : idx + self.seq_len]
        target_idx = idx + self.seq_len - 1
        y_dir = self.direction[target_idx]
        y_reg = self.regression[target_idx]
        return x, y_dir, y_reg
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_dataset.py -v`
Expected: PASS

---

## Phase 2 Checkpoint

Run all ML tests so far:

```bash
docker exec krypton-api-1 python -m pytest tests/ml/ -v
```

Expected: All tests pass. Feature matrix builds correctly, labels generate correctly, dataset produces valid tensors.

---

## Phase 3: LSTM Model & Training

**Checkpoint:** After this phase, the LSTM model can be instantiated, run forward passes, and trained on synthetic data via a training loop. Model checkpoints can be saved/loaded.

---

### Task 7: Create LSTM model

**Files:**
- Create: `backend/app/ml/model.py`
- Test: `backend/tests/ml/test_model.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/test_model.py`:

```python
import torch
import pytest

from app.ml.model import SignalLSTM


class TestSignalLSTM:

    @pytest.fixture
    def model(self):
        return SignalLSTM(input_size=15, hidden_size=64, num_layers=2, dropout=0.1)

    def test_forward_output_shapes(self, model):
        batch = torch.randn(8, 50, 15)  # (batch, seq_len, features)
        dir_logits, reg_out = model(batch)
        assert dir_logits.shape == (8, 3)   # 3 classes
        assert reg_out.shape == (8, 3)      # sl, tp1, tp2

    def test_direction_logits_sum_to_one_after_softmax(self, model):
        batch = torch.randn(4, 50, 15)
        dir_logits, _ = model(batch)
        probs = torch.softmax(dir_logits, dim=1)
        sums = probs.sum(dim=1)
        assert torch.allclose(sums, torch.ones(4), atol=1e-5)

    def test_regression_outputs_positive(self, model):
        batch = torch.randn(4, 50, 15)
        _, reg_out = model(batch)
        # ReLU ensures non-negative SL/TP distances
        assert (reg_out >= 0).all()

    def test_different_input_sizes(self):
        model = SignalLSTM(input_size=18, hidden_size=128, num_layers=1)
        batch = torch.randn(2, 30, 18)
        dir_logits, reg_out = model(batch)
        assert dir_logits.shape == (2, 3)
        assert reg_out.shape == (2, 3)
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_model.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `backend/app/ml/model.py`:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_model.py -v`
Expected: PASS

---

### Task 8: Create training loop

**Files:**
- Create: `backend/app/ml/trainer.py`
- Test: `backend/tests/ml/test_trainer.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/test_trainer.py`:

```python
import os
import tempfile

import numpy as np
import pytest

from app.ml.trainer import Trainer, TrainConfig


class TestTrainer:

    @pytest.fixture
    def synthetic_data(self):
        """Synthetic features + labels for training test."""
        n = 500
        n_features = 15
        features = np.random.randn(n, n_features).astype(np.float32)
        direction = np.random.randint(0, 3, size=n).astype(np.int64)
        sl = np.random.uniform(0.5, 3.0, size=n).astype(np.float32)
        tp1 = np.random.uniform(1.0, 4.0, size=n).astype(np.float32)
        tp2 = np.random.uniform(2.0, 6.0, size=n).astype(np.float32)
        return features, direction, sl, tp1, tp2

    def test_train_runs_without_error(self, synthetic_data):
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=2,
                batch_size=32,
                seq_len=50,
                hidden_size=32,
                num_layers=1,
                lr=1e-3,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)

            assert "train_loss" in result
            assert "val_loss" in result
            assert "best_epoch" in result
            assert len(result["train_loss"]) == 2

    def test_checkpoint_saved(self, synthetic_data):
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=2, batch_size=32, seq_len=50,
                hidden_size=32, num_layers=1,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            trainer.train(features, direction, sl, tp1, tp2)

            # Best checkpoint should exist
            assert os.path.exists(os.path.join(tmpdir, "best_model.pt"))

    def test_val_split(self, synthetic_data):
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=1, batch_size=32, seq_len=50,
                hidden_size=32, num_layers=1,
                val_ratio=0.2,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)
            assert len(result["val_loss"]) == 1
            assert result["val_loss"][0] > 0
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `backend/app/ml/trainer.py`:

```python
"""Training loop for SignalLSTM model."""

import logging
import os
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from app.ml.dataset import CandleDataset
from app.ml.model import SignalLSTM

logger = logging.getLogger(__name__)


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
    checkpoint_dir: str = "models"
    neutral_subsample_ratio: float = 0.5  # keep only 50% of NEUTRAL samples to reduce imbalance


class Trainer:
    """Trains SignalLSTM with classification + regression multi-task loss."""

    def __init__(self, config: TrainConfig):
        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def train(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
    ) -> dict:
        """Run full training loop.

        Returns dict with train_loss, val_loss, best_epoch.
        """
        cfg = self.config
        input_size = features.shape[1]

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

        # Train/val split (temporal — no shuffle to respect time ordering)
        split = int(n * (1 - cfg.val_ratio))
        train_ds = CandleDataset(
            features[:split], direction[:split],
            sl_atr[:split], tp1_atr[:split], tp2_atr[:split],
            seq_len=cfg.seq_len,
        )
        val_ds = CandleDataset(
            features[split:], direction[split:],
            sl_atr[split:], tp1_atr[split:], tp2_atr[split:],
            seq_len=cfg.seq_len,
        )

        train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True)
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
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", patience=10, factor=0.5,
        )

        cls_criterion = nn.CrossEntropyLoss(weight=class_weights_tensor)
        reg_criterion = nn.SmoothL1Loss()

        best_val_loss = float("inf")
        best_epoch = 0
        epochs_without_improvement = 0
        train_losses = []
        val_losses = []

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
            scheduler.step(avg_val_loss)

            logger.info(
                f"Epoch {epoch+1}/{cfg.epochs} — "
                f"train_loss={avg_train_loss:.4f} val_loss={avg_val_loss:.4f}"
            )

            if progress_callback:
                progress_callback({
                    "epoch": epoch + 1,
                    "total_epochs": cfg.epochs,
                    "train_loss": avg_train_loss,
                    "val_loss": avg_val_loss,
                })

            # Early stopping
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
                }
                with open(os.path.join(cfg.checkpoint_dir, "model_config.json"), "w") as f:
                    _json.dump(config_meta, f, indent=2)
            else:
                epochs_without_improvement += 1
                if epochs_without_improvement >= cfg.patience:
                    logger.info(f"Early stopping at epoch {epoch+1}")
                    break

        # Save a versioned copy for rollback
        from datetime import datetime as _dt, timezone as _tz
        version_tag = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
        versioned_pt = os.path.join(cfg.checkpoint_dir, f"model_{version_tag}.pt")
        best_pt = os.path.join(cfg.checkpoint_dir, "best_model.pt")
        if os.path.exists(best_pt):
            import shutil
            shutil.copy2(best_pt, versioned_pt)
            logger.info(f"Versioned checkpoint saved: {versioned_pt}")

        return {
            "train_loss": train_losses,
            "val_loss": val_losses,
            "best_epoch": best_epoch,
            "best_val_loss": best_val_loss,
            "version": version_tag,
        }
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py -v`
Expected: PASS

---

## Phase 3 Checkpoint

Run all ML tests:

```bash
docker exec krypton-api-1 python -m pytest tests/ml/ -v
```

Expected: All pass. Model trains on synthetic data, saves checkpoints, and early stopping works.

---

## Phase 4: Inference & Ensemble

**Checkpoint:** After this phase, a trained model can be loaded for inference and ensembled with the LLM gate to produce final trading signals.

---

### Task 9: Create inference predictor

**Files:**
- Create: `backend/app/ml/predictor.py`
- Test: `backend/tests/ml/test_predictor.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/test_predictor.py`:

```python
import os
import tempfile

import numpy as np
import torch
import pytest

from app.ml.model import SignalLSTM
from app.ml.predictor import Predictor


class TestPredictor:

    @pytest.fixture
    def saved_model(self):
        """Save a dummy model checkpoint and return path."""
        import json
        tmpdir = tempfile.mkdtemp()
        model = SignalLSTM(input_size=15, hidden_size=32, num_layers=1, dropout=0.0)
        path = os.path.join(tmpdir, "best_model.pt")
        torch.save(model.state_dict(), path)
        config_path = os.path.join(tmpdir, "model_config.json")
        with open(config_path, "w") as f:
            json.dump({
                "input_size": 15,
                "hidden_size": 32,
                "num_layers": 1,
                "dropout": 0.0,
                "seq_len": 50,
                "epoch": 1,
                "val_loss": 0.5,
            }, f)
        return path

    def test_load_model(self, saved_model):
        predictor = Predictor(saved_model)
        assert predictor.model is not None
        assert predictor.seq_len == 50

    def test_predict_returns_valid_output(self, saved_model):
        predictor = Predictor(saved_model)
        features = np.random.randn(50, 15).astype(np.float32)
        result = predictor.predict(features)

        assert "direction" in result
        assert "confidence" in result
        assert "sl_atr" in result
        assert "tp1_atr" in result
        assert "tp2_atr" in result
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
        assert 0 <= result["confidence"] <= 1

    def test_predict_too_few_candles_returns_neutral(self, saved_model):
        predictor = Predictor(saved_model)
        features = np.random.randn(10, 15).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] == "NEUTRAL"
        assert result["confidence"] == 0.0
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `backend/app/ml/predictor.py`:

```python
"""Inference wrapper for trained SignalLSTM model."""

import json
import logging
import os

import numpy as np
import torch

from app.ml.model import SignalLSTM

logger = logging.getLogger(__name__)

DIRECTION_MAP = {0: "NEUTRAL", 1: "LONG", 2: "SHORT"}


class Predictor:
    """Loads a trained model checkpoint and runs inference."""

    def __init__(self, checkpoint_path: str):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Load config from JSON sidecar (avoids weights_only restrictions)
        config_path = os.path.join(os.path.dirname(checkpoint_path), "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self.flow_used = config.get("flow_used", False)

        self.model = SignalLSTM(
            input_size=config["input_size"],
            hidden_size=config["hidden_size"],
            num_layers=config["num_layers"],
            dropout=0.0,  # no dropout at inference
        ).to(self.device)

        # Load weights only — safe and fast
        state_dict = torch.load(checkpoint_path, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def predict(self, features: np.ndarray) -> dict:
        """Run inference on a feature matrix.

        Args:
            features: (n_candles, n_features) array. Uses last seq_len rows.

        Returns:
            dict with direction, confidence, sl_atr, tp1_atr, tp2_atr.
        """
        if len(features) < self.seq_len:
            return {
                "direction": "NEUTRAL",
                "confidence": 0.0,
                "sl_atr": 0.0,
                "tp1_atr": 0.0,
                "tp2_atr": 0.0,
            }

        # Take last seq_len candles
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        with torch.no_grad():
            dir_logits, reg_out = self.model(x)

        probs = torch.softmax(dir_logits, dim=1).squeeze(0).cpu().numpy()
        reg = reg_out.squeeze(0).cpu().numpy()

        direction_idx = int(np.argmax(probs))
        confidence = float(probs[direction_idx])

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(reg[0]),
            "tp1_atr": float(reg[1]),
            "tp2_atr": float(reg[2]),
        }
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py -v`
Expected: PASS

---

### Task 10: Create ensemble module

**Files:**
- Create: `backend/app/ml/ensemble.py`
- Test: `backend/tests/ml/test_ensemble.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/test_ensemble.py`:

```python
import pytest
from app.ml.ensemble import compute_ensemble_signal


class TestComputeEnsembleSignal:

    def test_ml_and_llm_agree_long(self):
        ml = {"direction": "LONG", "confidence": 0.85, "sl_atr": 1.3, "tp1_atr": 2.1, "tp2_atr": 3.4}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["direction"] == "LONG"
        assert result["emit"] is True
        assert result["position_scale"] == 1.0

    def test_ml_and_llm_agree_short(self):
        ml = {"direction": "SHORT", "confidence": 0.75, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "confirm", "confidence": "MEDIUM"}
        result = compute_ensemble_signal(ml, llm)
        assert result["direction"] == "SHORT"
        assert result["emit"] is True

    def test_llm_caution_tightens_sl(self):
        ml = {"direction": "LONG", "confidence": 0.80, "sl_atr": 2.0, "tp1_atr": 3.0, "tp2_atr": 4.0}
        llm = {"opinion": "caution", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is True
        assert result["sl_atr"] < 2.0  # tightened
        assert result["position_scale"] < 1.0

    def test_llm_contradict_blocks(self):
        ml = {"direction": "LONG", "confidence": 0.90, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "contradict", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is False

    def test_ml_neutral_no_signal(self):
        ml = {"direction": "NEUTRAL", "confidence": 0.60, "sl_atr": 0, "tp1_atr": 0, "tp2_atr": 0}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is False

    def test_low_confidence_no_signal(self):
        ml = {"direction": "LONG", "confidence": 0.50, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is False

    def test_custom_min_confidence(self):
        ml = {"direction": "LONG", "confidence": 0.70, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm, min_confidence=0.80)
        assert result["emit"] is False
        result2 = compute_ensemble_signal(ml, llm, min_confidence=0.60)
        assert result2["emit"] is True

    def test_no_llm_response_still_works(self):
        ml = {"direction": "LONG", "confidence": 0.80, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        result = compute_ensemble_signal(ml, llm_response=None)
        # Without LLM confirmation, emit with reduced scale
        assert result["emit"] is True
        assert result["position_scale"] < 1.0
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `backend/app/ml/ensemble.py`:

```python
"""ML + LLM ensemble decision logic."""

# Default minimum ML confidence to emit any signal
DEFAULT_MIN_CONFIDENCE = 0.65


def compute_ensemble_signal(
    ml_prediction: dict,
    llm_response: dict | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> dict:
    """Combine ML model prediction with LLM gate opinion.

    Args:
        ml_prediction: dict with direction, confidence, sl_atr, tp1_atr, tp2_atr.
        llm_response: dict with opinion (confirm/caution/contradict) and
                      confidence (HIGH/MEDIUM/LOW). None if LLM unavailable.

    Returns:
        dict with: emit (bool), direction, confidence, sl_atr, tp1_atr, tp2_atr,
                   position_scale (0-1 multiplier for position sizing).
    """
    direction = ml_prediction["direction"]
    confidence = ml_prediction["confidence"]
    sl_atr = ml_prediction["sl_atr"]
    tp1_atr = ml_prediction["tp1_atr"]
    tp2_atr = ml_prediction["tp2_atr"]

    # No signal if NEUTRAL or low confidence
    if direction == "NEUTRAL" or confidence < min_confidence:
        return {"emit": False, "direction": direction, "confidence": confidence,
                "sl_atr": sl_atr, "tp1_atr": tp1_atr, "tp2_atr": tp2_atr,
                "position_scale": 0.0}

    position_scale = 1.0

    if llm_response is None:
        # No LLM available — emit with reduced confidence
        position_scale = 0.7
    elif llm_response["opinion"] == "contradict":
        # Hard veto
        return {"emit": False, "direction": direction, "confidence": confidence,
                "sl_atr": sl_atr, "tp1_atr": tp1_atr, "tp2_atr": tp2_atr,
                "position_scale": 0.0}
    elif llm_response["opinion"] == "caution":
        # Tighten SL, reduce position
        sl_atr = sl_atr * 0.8
        position_scale = 0.6
    elif llm_response["opinion"] == "confirm":
        # Full agreement
        llm_confidence_map = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.7}
        position_scale = llm_confidence_map.get(llm_response.get("confidence", "MEDIUM"), 0.85)

    return {
        "emit": True,
        "direction": direction,
        "confidence": confidence,
        "sl_atr": sl_atr,
        "tp1_atr": tp1_atr,
        "tp2_atr": tp2_atr,
        "position_scale": position_scale,
    }
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble.py -v`
Expected: PASS

---

## Phase 4 Checkpoint

Run all ML tests:

```bash
docker exec krypton-api-1 python -m pytest tests/ml/ -v
```

Expected: All pass. Full ML pipeline from features → labels → dataset → model → training → inference → ensemble is tested.

---

## Phase 5: Training API & Data Pipeline

**Checkpoint:** After this phase, a REST endpoint triggers model training on historical data, with progress tracking. Historical data can be loaded from Postgres and transformed into training samples.

---

### Task 11: Create data loading pipeline

**Files:**
- Create: `backend/app/ml/data_loader.py`
- Test: `backend/tests/ml/test_data_loader.py`

**Step 1: Write the failing test**

Create `backend/tests/ml/test_data_loader.py`:

```python
import numpy as np
import pytest

from app.ml.data_loader import prepare_training_data


class TestPrepareTrainingData:

    def test_returns_expected_arrays(self):
        """Test with synthetic candle list."""
        candles = []
        for i in range(200):
            candles.append({
                "timestamp": f"2025-01-01T{i:02d}:00:00+00:00",
                "open": 67000 + i * 10,
                "high": 67000 + i * 10 + 50,
                "low": 67000 + i * 10 - 30,
                "close": 67000 + i * 10 + 20,
                "volume": 100 + i,
            })

        features, direction, sl, tp1, tp2 = prepare_training_data(candles)

        assert features.shape[0] == 200
        assert features.shape[1] >= 15
        assert len(direction) == 200
        assert len(sl) == 200
        assert features.dtype == np.float32

    def test_with_order_flow(self):
        candles = []
        flow_snapshots = []
        for i in range(200):
            candles.append({
                "timestamp": f"2025-01-01T{i:02d}:00:00+00:00",
                "open": 67000 + i * 10,
                "high": 67000 + i * 10 + 50,
                "low": 67000 + i * 10 - 30,
                "close": 67000 + i * 10 + 20,
                "volume": 100 + i,
            })
            flow_snapshots.append({
                "funding_rate": 0.0001,
                "oi_change_pct": 0.02,
                "long_short_ratio": 1.3,
            })

        features, direction, sl, tp1, tp2 = prepare_training_data(
            candles, order_flow=flow_snapshots
        )

        # Should have 3 extra features for order flow
        features_no_flow, _, _, _, _ = prepare_training_data(candles)
        assert features.shape[1] == features_no_flow.shape[1] + 3
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_data_loader.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `backend/app/ml/data_loader.py`:

```python
"""Data loading and preparation for ML training."""

import numpy as np
import pandas as pd

from app.ml.features import build_feature_matrix
from app.ml.labels import generate_labels, LabelConfig


def prepare_training_data(
    candles: list[dict],
    order_flow: list[dict] | None = None,
    label_config: LabelConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert raw candle data into features and labels for training.

    Args:
        candles: List of candle dicts with timestamp, open, high, low, close, volume.
        order_flow: Optional list of order flow dicts (one per candle).
        label_config: Label generation config.

    Returns:
        Tuple of (features, direction, sl_atr, tp1_atr, tp2_atr).
    """
    df = pd.DataFrame(candles)
    features = build_feature_matrix(df, order_flow=order_flow)
    direction, sl_atr, tp1_atr, tp2_atr = generate_labels(df, label_config)
    return features, direction, sl_atr, tp1_atr, tp2_atr
```

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_data_loader.py -v`
Expected: PASS

---

### Task 12: Create ML training API endpoint

**Files:**
- Create: `backend/app/api/ml.py`
- Modify: `backend/app/main.py` (register router)
- Modify: `backend/app/config.py` (add ML settings)

**Step 1: Add ML config settings**

Add to `backend/app/config.py` in the `Settings` class, after the engine section (after line 64):

```python
    # ML model
    ml_enabled: bool = False
    ml_confidence_threshold: float = 0.65
    ml_llm_threshold: float = 0.65  # only call LLM above this ML confidence
    ml_checkpoint_dir: str = "models"
```

**Step 2: Create the ML API router**

Create `backend/app/api/ml.py`:

```python
"""ML model training and status API endpoints."""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import require_settings_api_key
from app.db.models import Candle, OrderFlowSnapshot
from app.ml.data_loader import prepare_training_data
from app.ml.labels import LabelConfig
from app.ml.trainer import Trainer, TrainConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml", tags=["ml"])


class TrainRequest(BaseModel):
    timeframe: str = "1h"
    lookback_days: int = Field(default=365, ge=30, le=1825)
    epochs: int = Field(default=100, ge=1, le=500)
    batch_size: int = Field(default=64, ge=8, le=512)
    hidden_size: int = Field(default=128, ge=32, le=512)
    num_layers: int = Field(default=2, ge=1, le=4)
    lr: float = Field(default=1e-3, gt=0)
    label_horizon: int = Field(default=24, ge=4, le=96)
    label_threshold_pct: float = Field(default=1.5, gt=0, le=10)


@router.post("/train", dependencies=[require_settings_api_key()])
async def start_training(body: TrainRequest, request: Request):
    """Start ML model training on historical data."""
    db = request.app.state.db
    settings = request.app.state.settings
    train_jobs = _get_train_jobs(request.app)

    # Check if already training
    for job in train_jobs.values():
        if job.get("status") == "running":
            raise HTTPException(status_code=429, detail="Training already in progress")

    job_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    train_jobs[job_id] = {"status": "running", "progress": {}}

    async def _run():
        try:
            cutoff = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0
            )
            date_from = cutoff - timedelta(days=body.lookback_days)

            # Train one model per pair (avoids cross-pair boundary artifacts)
            pairs = settings.pairs
            pair_results = {}

            for pair in pairs:
                async with db.session_factory() as session:
                    result = await session.execute(
                        select(Candle)
                        .where(Candle.pair == pair)
                        .where(Candle.timeframe == body.timeframe)
                        .where(Candle.timestamp >= date_from)
                        .order_by(Candle.timestamp)
                    )
                    rows = result.scalars().all()

                candles = [{
                    "timestamp": c.timestamp.isoformat(),
                    "open": float(c.open), "high": float(c.high),
                    "low": float(c.low), "close": float(c.close),
                    "volume": float(c.volume),
                } for c in rows]

                if len(candles) < 100:
                    logger.warning(f"Skipping {pair}:{body.timeframe} — only {len(candles)} candles")
                    continue

                # Load matching order flow snapshots
                flow = None
                async with db.session_factory() as session:
                    result = await session.execute(
                        select(OrderFlowSnapshot)
                        .where(OrderFlowSnapshot.pair == pair)
                        .where(OrderFlowSnapshot.timestamp >= date_from)
                        .order_by(OrderFlowSnapshot.timestamp)
                    )
                    flow_rows = result.scalars().all()

                flow_used = False
                if flow_rows:
                    # Align flow snapshots to candles by nearest timestamp
                    # (flow data may have partial coverage — pad missing with zeros)
                    from datetime import datetime as _dt
                    flow_by_ts = {}
                    for f in flow_rows:
                        # Bucket to hour to match candle timestamps
                        ts_key = f.timestamp.replace(minute=0, second=0, microsecond=0)
                        flow_by_ts[ts_key] = {
                            "funding_rate": f.funding_rate or 0,
                            "oi_change_pct": f.oi_change_pct or 0,
                            "long_short_ratio": f.long_short_ratio or 1.0,
                        }

                    zero_flow = {"funding_rate": 0, "oi_change_pct": 0, "long_short_ratio": 1.0}
                    flow = []
                    matched = 0
                    for c in candles:
                        c_ts = _dt.fromisoformat(c["timestamp"]).replace(minute=0, second=0, microsecond=0)
                        snap = flow_by_ts.get(c_ts, zero_flow)
                        if snap is not zero_flow:
                            matched += 1
                        flow.append(snap)

                    coverage = matched / len(candles) if candles else 0
                    if coverage < 0.1:
                        logger.warning(
                            f"Order flow coverage too low for {pair}: "
                            f"{matched}/{len(candles)} ({coverage:.0%}) — skipping flow features"
                        )
                        flow = None
                    else:
                        flow_used = True
                        logger.info(
                            f"Order flow aligned for {pair}: "
                            f"{matched}/{len(candles)} ({coverage:.0%}) candles matched"
                        )

                label_config = LabelConfig(
                    horizon=body.label_horizon,
                    threshold_pct=body.label_threshold_pct,
                )
                features, direction, sl, tp1, tp2 = prepare_training_data(
                    candles, order_flow=flow, label_config=label_config,
                )

                # Per-pair checkpoint directory
                pair_slug = pair.replace("-", "_").lower()
                pair_checkpoint_dir = os.path.join(settings.ml_checkpoint_dir, pair_slug)

                train_config = TrainConfig(
                    epochs=body.epochs,
                    batch_size=body.batch_size,
                    hidden_size=body.hidden_size,
                    num_layers=body.num_layers,
                    lr=body.lr,
                    checkpoint_dir=pair_checkpoint_dir,
                )

                def on_progress(info, _pair=pair):
                    train_jobs[job_id]["progress"][_pair] = info

                trainer = Trainer(train_config)
                pair_result = await asyncio.to_thread(
                    trainer.train, features, direction, sl, tp1, tp2, on_progress,
                )

                # Patch model_config.json with flow_used flag so inference
                # knows whether to include order flow features
                config_path = os.path.join(pair_checkpoint_dir, "model_config.json")
                if os.path.isfile(config_path):
                    import json as _j
                    with open(config_path) as f:
                        meta = _j.load(f)
                    meta["flow_used"] = flow_used
                    with open(config_path, "w") as f:
                        _j.dump(meta, f, indent=2)

                pair_results[pair] = {
                    "best_epoch": pair_result["best_epoch"],
                    "best_val_loss": pair_result["best_val_loss"],
                    "total_epochs": len(pair_result["train_loss"]),
                    "total_samples": len(features),
                    "flow_data_used": flow_used,
                    "version": pair_result.get("version"),
                }

            if not pair_results:
                train_jobs[job_id] = {"status": "failed", "error": "No pair had enough data"}
                return

            train_jobs[job_id] = {
                "status": "completed",
                "result": pair_results,
            }

            # Reload per-pair predictors if live
            _reload_predictors(request.app, settings)

        except Exception as e:
            logger.error(f"Training failed: {e}", exc_info=True)
            train_jobs[job_id] = {"status": "failed", "error": str(e)}

    task = asyncio.create_task(_run())
    train_jobs[job_id]["task"] = task
    _prune_old_jobs(train_jobs)
    return {"job_id": job_id, "status": "running"}


@router.get("/train/{job_id}", dependencies=[require_settings_api_key()])
async def get_training_status(job_id: str, request: Request):
    train_jobs = _get_train_jobs(request.app)
    job = train_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")
    # Don't expose asyncio task in response
    return {"job_id": job_id, **{k: v for k, v in job.items() if k != "task"}}


@router.post("/train/{job_id}/cancel", dependencies=[require_settings_api_key()])
async def cancel_training(job_id: str, request: Request):
    """Cancel a running training job."""
    train_jobs = _get_train_jobs(request.app)
    job = train_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")
    if job.get("status") != "running":
        raise HTTPException(status_code=409, detail="Job is not running")
    task = job.get("task")
    if task and not task.done():
        task.cancel()
    job["status"] = "cancelled"
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/status", dependencies=[require_settings_api_key()])
async def get_ml_status(request: Request):
    """Check if ML model is loaded and ready."""
    predictors = getattr(request.app.state, "ml_predictors", {})
    return {
        "ml_enabled": getattr(request.app.state.settings, "ml_enabled", False),
        "loaded_pairs": list(predictors.keys()),
    }


MAX_RETAINED_JOBS = 10


def _get_train_jobs(app) -> dict:
    if not hasattr(app.state, "ml_train_jobs"):
        app.state.ml_train_jobs = {}
    return app.state.ml_train_jobs


def _prune_old_jobs(train_jobs: dict):
    """Keep only the most recent MAX_RETAINED_JOBS completed/failed jobs."""
    finished = [
        (k, v) for k, v in train_jobs.items()
        if v.get("status") in ("completed", "failed", "cancelled")
    ]
    if len(finished) > MAX_RETAINED_JOBS:
        # Job IDs are timestamp-sortable
        finished.sort(key=lambda x: x[0])
        for k, _ in finished[:-MAX_RETAINED_JOBS]:
            del train_jobs[k]


def _reload_predictors(app, settings):
    """Reload per-pair ML predictors from checkpoints."""
    import os
    from app.ml.predictor import Predictor
    predictors = {}
    checkpoint_dir = getattr(settings, "ml_checkpoint_dir", "models")
    if not os.path.isdir(checkpoint_dir):
        return
    for entry in os.listdir(checkpoint_dir):
        pair_dir = os.path.join(checkpoint_dir, entry)
        if not os.path.isdir(pair_dir):
            continue
        model_path = os.path.join(pair_dir, "best_model.pt")
        if os.path.isfile(model_path):
            try:
                predictors[entry] = Predictor(model_path)
                logger.info(f"ML predictor loaded for {entry}")
            except Exception as e:
                logger.error(f"Failed to load ML predictor for {entry}: {e}")
    app.state.ml_predictors = predictors
```

**Step 3: Register the router**

In `backend/app/main.py`, find where other routers are registered (look for `app.include_router`) and add:

```python
from app.api.ml import router as ml_router
```

And in `create_app()`:

```python
app.include_router(ml_router)
```

**Step 4: Verify it loads**

Run: `docker exec krypton-api-1 python -c "from app.api.ml import router; print('OK')"`
Expected: OK

**Step 5: Write API test**

Create `backend/tests/api/test_ml.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMLEndpoints:

    @pytest.mark.asyncio
    async def test_status_returns_disabled_by_default(self, client):
        resp = await client.get(
            "/api/ml/status",
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ml_enabled"] is False
        assert data["loaded_pairs"] == []

    @pytest.mark.asyncio
    async def test_train_returns_job_id(self, app, client):
        """Test that training endpoint starts a job (mocked DB)."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.__aenter__.return_value.execute.return_value = mock_result

        app.state.db = MagicMock()
        app.state.db.session_factory.return_value = mock_session
        app.state.settings.pairs = ["BTC-USDT-SWAP"]

        resp = await client.post(
            "/api/ml/train",
            json={"timeframe": "1h", "epochs": 1},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_train_status_not_found(self, client):
        resp = await client.get(
            "/api/ml/train/nonexistent",
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_train_background_job_handles_no_data(self, app, client):
        """Verify background job completes with 'failed' status when no data."""
        import asyncio

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.__aenter__.return_value.execute.return_value = mock_result

        app.state.db = MagicMock()
        app.state.db.session_factory.return_value = mock_session
        app.state.settings.pairs = ["BTC-USDT-SWAP"]
        app.state.settings.ml_checkpoint_dir = "/tmp/test_models"

        resp = await client.post(
            "/api/ml/train",
            json={"timeframe": "1h", "epochs": 1},
            headers={"X-API-Key": "test-key"},
        )
        job_id = resp.json()["job_id"]

        # Wait for background task to finish
        await asyncio.sleep(0.5)

        resp = await client.get(
            f"/api/ml/train/{job_id}",
            headers={"X-API-Key": "test-key"},
        )
        data = resp.json()
        assert data["status"] == "failed"
        assert "No pair had enough data" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_cancel_training(self, app, client):
        """Test cancelling a running job."""
        from app.api.ml import _get_train_jobs
        train_jobs = _get_train_jobs(app)
        train_jobs["test_cancel"] = {"status": "running", "task": AsyncMock()}

        resp = await client.post(
            "/api/ml/train/test_cancel/cancel",
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
```

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_ml.py -v`
Expected: PASS

---

## Phase 5 Checkpoint

Run all tests:

```bash
docker exec krypton-api-1 python -m pytest tests/ml/ -v
docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60
```

Expected: All pass. Training endpoint is wired up.

---

## Phase 6: Live Pipeline Integration

**Checkpoint:** After this phase, the live signal pipeline uses the ML model (when available) instead of rule-based scoring, ensembled with the LLM gate.

---

### Task 13: Integrate ML model into live pipeline

**Files:**
- Modify: `backend/app/main.py` (the `run_pipeline()` function + `lifespan()`)
- Test: `backend/tests/test_pipeline_ml.py`

**Step 1: Add ML predictor loading in lifespan**

In `backend/app/main.py`, in the `lifespan()` function, before the `yield` (line 673), add:

```python
    # Load per-pair ML predictors if enabled
    app.state.ml_predictors = {}
    if getattr(settings, "ml_enabled", False):
        from app.api.ml import _reload_predictors
        _reload_predictors(app, settings)
```

**Step 2: Extract signal emission into a helper**

To avoid duplicating the risk-metrics/persist/broadcast/push logic, extract it from `run_pipeline()`. Add this function above `run_pipeline()`.

**Lines to extract:** The following code in `run_pipeline()` (lines 282-357) will be moved into `_emit_signal()`:
- Lines 282-338: Risk metrics enrichment block
- Lines 340-341: `signal_data["risk_metrics"] = ...` and `signal_data["correlated_news_ids"] = ...`
- Lines 343-345: `await persist_signal(...)`, `await manager.broadcast(...)`, logger.info
- Lines 347-357: Web Push dispatch block

**After extraction:** Replace lines 282-357 in `run_pipeline()` with a single call:
```python
    await _emit_signal(app, signal_data, levels, correlated_news_ids)
```

Here is the extracted helper to add above `run_pipeline()`:

```python
async def _emit_signal(app, signal_data: dict, levels: dict, correlated_news_ids=None):
    """Persist signal, compute risk metrics, broadcast, and push."""
    settings = app.state.settings
    db = app.state.db
    redis = app.state.redis
    manager = app.state.manager

    # Enrich with risk metrics if OKX client is available
    risk_metrics = None
    okx_client = getattr(app.state, "okx_client", None)
    if okx_client:
        try:
            balance = await okx_client.get_balance()
            if balance:
                equity = balance["total_equity"]
                from app.db.models import RiskSettings
                risk_per_trade = 0.01
                max_pos_usd = None
                try:
                    async with db.session_factory() as session:
                        result = await session.execute(
                            select(RiskSettings).where(RiskSettings.id == 1)
                        )
                        rs = result.scalar_one_or_none()
                        if rs:
                            risk_per_trade = rs.risk_per_trade
                            max_pos_usd = rs.max_position_size_usd
                except Exception:
                    pass

                sizer = PositionSizer(equity, risk_per_trade, max_pos_usd)

                lot_size = None
                min_order_size = None
                try:
                    cache_key_inst = f"instruments:{signal_data['pair']}"
                    cached_inst = await redis.get(cache_key_inst)
                    if cached_inst:
                        import json as _j
                        inst = _j.loads(cached_inst)
                        lot_size = inst.get("lot_size")
                        min_order_size = inst.get("min_order_size")
                    else:
                        instruments = await okx_client.get_instruments()
                        if signal_data["pair"] in instruments:
                            inst = instruments[signal_data["pair"]]
                            lot_size = inst.get("lot_size")
                            min_order_size = inst.get("min_order_size")
                            await redis.set(cache_key_inst, json.dumps(inst), ex=3600)
                except Exception:
                    pass

                risk_metrics = sizer.calculate(
                    entry=levels["entry"],
                    stop_loss=levels["stop_loss"],
                    take_profit_1=levels.get("take_profit_1"),
                    take_profit_2=levels.get("take_profit_2"),
                    lot_size=lot_size,
                    min_order_size=min_order_size,
                )
        except Exception as e:
            logger.debug(f"Risk metrics enrichment skipped: {e}")

    signal_data["risk_metrics"] = risk_metrics
    signal_data["correlated_news_ids"] = correlated_news_ids

    await persist_signal(db, signal_data)
    await manager.broadcast(signal_data)
    logger.info(
        f"Signal emitted: {signal_data['pair']} {signal_data['timeframe']} "
        f"{signal_data['direction']} score={signal_data['final_score']}"
    )

    try:
        from app.push.dispatch import dispatch_push_for_signal
        await dispatch_push_for_signal(
            session_factory=db.session_factory,
            signal=signal_data,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims_email=settings.vapid_claims_email,
        )
    except Exception as e:
        logger.debug(f"Signal push dispatch skipped: {e}")
```

Then in `run_pipeline()`, **delete lines 282-357** (the entire risk metrics enrichment + persist + broadcast + push block) and replace with:

```python
    await _emit_signal(app, signal_data, levels, correlated_news_ids)
```

This single line replaces all of the following removed code:
- Risk metrics enrichment (OKX balance, risk settings, position sizer, instrument cache)
- `signal_data["risk_metrics"] = risk_metrics`
- `signal_data["correlated_news_ids"] = correlated_news_ids`
- `await persist_signal(db, signal_data)`
- `await manager.broadcast(signal_data)`
- `logger.info(...)`
- Web Push dispatch block

**Step 3: Add ML scoring branch in run_pipeline**

In `run_pipeline()`, after the DataFrame is built (line 159: `df = pd.DataFrame(candles_data)`), add the ML scoring branch. If the ML predictor handles the candle, it returns early; otherwise the existing rule-based code runs unchanged.

```python
    # --- ML scoring path ---
    pair_slug = pair.replace("-", "_").lower()
    ml_predictors = getattr(app.state, "ml_predictors", {})
    ml_predictor = ml_predictors.get(pair_slug)
    if ml_predictor is not None:
        try:
            from app.ml.features import build_feature_matrix
            from app.ml.ensemble import compute_ensemble_signal

            # Include order flow features if model was trained with them
            flow_for_features = None
            if getattr(ml_predictor, "flow_used", False):
                flow_data = order_flow.get(pair, {})
                if flow_data:
                    # Build a flow list matching candle count (use current
                    # snapshot for all rows — only the last row matters for
                    # the sliding window, but shape must match)
                    flow_for_features = [{
                        "funding_rate": flow_data.get("funding_rate", 0),
                        "oi_change_pct": flow_data.get("open_interest_change_pct", 0),
                        "long_short_ratio": flow_data.get("long_short_ratio", 1.0),
                    }] * len(df)

            feature_matrix = build_feature_matrix(df, order_flow=flow_for_features)
            ml_prediction = ml_predictor.predict(feature_matrix)

            tech_result = compute_technical_score(df)
            flow_metrics = order_flow.get(pair, {})

            # Fetch news context for LLM prompt
            news_context = "No recent news available."
            correlated_news_ids = None
            try:
                window = getattr(settings, "news_llm_context_window_minutes", 30)
                news_context, correlated_news_ids = await _fetch_news_context(db, pair, window)
                correlated_news_ids = correlated_news_ids or None
            except Exception as e:
                logger.debug(f"News context fetch skipped: {e}")

            # Only call LLM when ML confidence exceeds threshold
            llm_response_dict = None
            ml_confidence_threshold = getattr(settings, "ml_confidence_threshold", 0.65)
            ml_llm_threshold = getattr(settings, "ml_llm_threshold", 0.65)
            if prompt_template and ml_prediction["confidence"] >= ml_llm_threshold:
                try:
                    rendered = render_prompt(
                        template=prompt_template,
                        pair=pair, timeframe=timeframe,
                        indicators=json.dumps(tech_result["indicators"], indent=2),
                        order_flow=json.dumps(flow_metrics, indent=2),
                        news=news_context,
                        preliminary_score=str(int(ml_prediction["confidence"] * 100)),
                        direction=ml_prediction["direction"],
                        candles=json.dumps(candles_data[-20:], indent=2),
                    )
                    llm_resp = await call_openrouter(
                        prompt=rendered,
                        api_key=settings.openrouter_api_key,
                        model=settings.openrouter_model,
                        timeout=settings.engine_llm_timeout_seconds,
                    )
                    if llm_resp:
                        llm_response_dict = {
                            "opinion": llm_resp.opinion,
                            "confidence": llm_resp.confidence,
                        }
                except Exception as e:
                    logger.error(f"LLM call failed in ML path: {e}")

            ensemble = compute_ensemble_signal(
                ml_prediction, llm_response_dict,
                min_confidence=ml_confidence_threshold,
            )

            if not ensemble["emit"]:
                logger.info(
                    f"ML pipeline {pair}:{timeframe} "
                    f"dir={ml_prediction['direction']} "
                    f"conf={ml_prediction['confidence']:.2f} — not emitted"
                )
                return

            direction = ensemble["direction"]
            atr = tech_result["indicators"].get("atr", 200)
            price = float(candle["close"])

            if direction == "LONG":
                levels = {
                    "entry": price,
                    "stop_loss": price - ensemble["sl_atr"] * atr,
                    "take_profit_1": price + ensemble["tp1_atr"] * atr,
                    "take_profit_2": price + ensemble["tp2_atr"] * atr,
                }
            else:
                levels = {
                    "entry": price,
                    "stop_loss": price + ensemble["sl_atr"] * atr,
                    "take_profit_1": price - ensemble["tp1_atr"] * atr,
                    "take_profit_2": price - ensemble["tp2_atr"] * atr,
                }

            final_score = int(ensemble["confidence"] * 100)
            if direction == "SHORT":
                final_score = -final_score

            signal_data = {
                "pair": pair,
                "timeframe": timeframe,
                "direction": direction,
                "final_score": final_score,
                "traditional_score": 0,
                "llm_opinion": llm_response_dict["opinion"] if llm_response_dict else "skipped",
                "llm_confidence": llm_response_dict.get("confidence") if llm_response_dict else None,
                "explanation": f"ML model confidence: {ml_prediction['confidence']:.2f}",
                **levels,
                "raw_indicators": tech_result["indicators"],
                "detected_patterns": None,
                "correlated_news_ids": correlated_news_ids,
            }

            await _emit_signal(app, signal_data, levels, correlated_news_ids)
            return  # ML path handled — skip rule-based scoring

        except Exception as e:
            logger.error(f"ML scoring failed for {pair}:{timeframe}: {e}", exc_info=True)
            # Fall through to rule-based scoring as fallback
```

Note: The existing rule-based code stays below this block — if no ML predictor exists for this pair (or ML scoring throws), the original pipeline runs unchanged. Order flow features at inference are included when the model's `model_config.json` has `flow_used: true` — this is set automatically during training (Task 12) to ensure train/inference consistency.

**Step 4: Write integration test**

Create `backend/tests/test_pipeline_ml.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import run_pipeline


class TestMLPipelinePath:

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        settings = MagicMock()
        settings.ml_enabled = True
        settings.ml_confidence_threshold = 0.65
        settings.ml_llm_threshold = 0.65
        settings.engine_signal_threshold = 30
        settings.pairs = ["BTC-USDT-SWAP"]
        app.state.settings = settings
        app.state.order_flow = {"BTC-USDT-SWAP": {}}
        app.state.prompt_template = None
        app.state.manager = AsyncMock()
        app.state.db = MagicMock()
        app.state.db.session_factory = MagicMock(return_value=AsyncMock())
        app.state.okx_client = None

        # Mock Redis with 50 candles
        candles = []
        for i in range(50):
            candles.append(json.dumps({
                "open": 67000 + i * 10,
                "high": 67000 + i * 10 + 50,
                "low": 67000 + i * 10 - 30,
                "close": 67000 + i * 10 + 20,
                "volume": 100 + i,
            }))
        redis = AsyncMock()
        redis.lrange.return_value = candles
        app.state.redis = redis

        return app

    @pytest.fixture
    def mock_predictor(self):
        predictor = MagicMock()
        predictor.seq_len = 50
        predictor.predict.return_value = {
            "direction": "LONG",
            "confidence": 0.85,
            "sl_atr": 1.5,
            "tp1_atr": 2.0,
            "tp2_atr": 3.0,
        }
        return predictor

    @pytest.mark.asyncio
    async def test_ml_path_emits_signal(self, mock_app, mock_predictor):
        mock_app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}

        candle = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "close": 67500}

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(mock_app, candle)

            mock_predictor.predict.assert_called_once()
            mock_persist.assert_called_once()
            signal = mock_persist.call_args[0][1]
            assert signal["direction"] == "LONG"
            assert signal["pair"] == "BTC-USDT-SWAP"

    @pytest.mark.asyncio
    async def test_ml_path_low_confidence_no_signal(self, mock_app, mock_predictor):
        mock_predictor.predict.return_value["confidence"] = 0.40
        mock_app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}

        candle = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "close": 67500}

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(mock_app, candle)
            mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_ml_failure_falls_through_to_rule_based(self, mock_app, mock_predictor):
        mock_predictor.predict.side_effect = RuntimeError("model error")
        mock_app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}

        candle = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "close": 67500}

        # Should not raise — falls through to rule-based path
        with patch("app.main.persist_signal", new_callable=AsyncMock):
            await run_pipeline(mock_app, candle)
```

**Step 5: Verify all tests pass**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60`
Expected: All pass (ML is disabled by default, so existing behavior unchanged; new tests validate the ML path)

---

## Phase 6 Checkpoint

Verify the full system:

```bash
# All tests pass
docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60

# ML modules importable
docker exec krypton-api-1 python -c "from app.ml.predictor import Predictor; from app.ml.ensemble import compute_ensemble_signal; print('OK')"
```

---

## Phase 7: Backtester Integration

**Checkpoint:** After this phase, the backtester supports an ML scoring mode so you can compare ML vs rule-based signals on the same historical data.

---

### Task 14: Add ML mode to backtester

**Files:**
- Modify: `backend/app/engine/backtester.py`
- Test: `backend/tests/engine/test_backtester.py`

**Step 1: Write the failing test**

Add to `backend/tests/engine/test_backtester.py`:

```python
class TestMLBacktest:

    def test_ml_mode_runs(self):
        """ML backtest should work with a dummy predictor."""
        candles = _make_candle_series(n=120)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)

        # Create a mock predictor
        class MockPredictor:
            seq_len = 50
            def predict(self, features):
                import numpy as np
                return {
                    "direction": "LONG" if np.random.random() > 0.5 else "SHORT",
                    "confidence": 0.75,
                    "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0,
                }

        result = run_backtest(candles, "BTC-USDT-SWAP", config, ml_predictor=MockPredictor())
        assert "trades" in result
        assert "stats" in result

    def test_ml_mode_produces_trades(self):
        """ML backtest should produce some trades."""
        candles = _make_candle_series(n=150, trend=15)
        config = BacktestConfig(signal_threshold=10, max_concurrent_positions=5)

        class AlwaysLongPredictor:
            seq_len = 50
            def predict(self, features):
                return {
                    "direction": "LONG",
                    "confidence": 0.90,
                    "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0,
                }

        result = run_backtest(candles, "BTC-USDT-SWAP", config, ml_predictor=AlwaysLongPredictor())
        assert result["stats"]["total_trades"] > 0
```

**Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py::TestMLBacktest -v`
Expected: FAIL (run_backtest doesn't accept ml_predictor yet)

**Step 3: Modify the backtester**

First, add `ml_confidence_threshold` to `BacktestConfig` in `backend/app/engine/backtester.py` (after `max_concurrent_positions` on line 35):

```python
    ml_confidence_threshold: float = 0.65  # minimum ML confidence to emit signal
```

Then modify `run_backtest` to accept an optional `ml_predictor`:

Change the function signature (line 56-60):

```python
def run_backtest(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    cancel_flag: dict | None = None,
    ml_predictor=None,
) -> dict:
```

Inside the loop (replace lines 94-127), add the ML branch:

```python
        # Score current candle
        df = pd.DataFrame(window)

        if ml_predictor is not None:
            # ML scoring mode
            try:
                from app.ml.features import build_feature_matrix
                feature_matrix = build_feature_matrix(df)
                prediction = ml_predictor.predict(feature_matrix)

                if prediction["direction"] == "NEUTRAL" or prediction["confidence"] < config.ml_confidence_threshold:
                    continue

                direction = prediction["direction"]
                score = int(prediction["confidence"] * 100)
                if direction == "SHORT":
                    score = -score

                # Use compute_technical_score for ATR (same as rule-based path)
                try:
                    tech_result = compute_technical_score(df)
                    atr = tech_result["indicators"].get("atr", 0)
                except Exception:
                    continue
                if atr <= 0:
                    continue

                price = float(current["close"])
                if direction == "LONG":
                    sl = price - prediction["sl_atr"] * atr
                    tp1 = price + prediction["tp1_atr"] * atr
                    tp2 = price + prediction["tp2_atr"] * atr
                else:
                    sl = price + prediction["sl_atr"] * atr
                    tp1 = price - prediction["tp1_atr"] * atr
                    tp2 = price - prediction["tp2_atr"] * atr

                detected = []

            except Exception:
                continue
        else:
            # Rule-based scoring mode (existing logic)
            try:
                tech_result = compute_technical_score(df)
            except Exception:
                continue

            pat_score = 0
            detected = []
            if config.enable_patterns:
                try:
                    detected = detect_candlestick_patterns(df)
                    indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
                    pat_score = compute_pattern_score(detected, indicator_ctx)
                except Exception:
                    pass

            score = compute_preliminary_score(
                technical_score=tech_result["score"],
                order_flow_score=0,
                tech_weight=config.tech_weight,
                flow_weight=0.0,
                onchain_score=0,
                onchain_weight=0.0,
                pattern_score=pat_score,
                pattern_weight=config.pattern_weight,
            )

            direction = "LONG" if score > 0 else "SHORT"

            if abs(score) < config.signal_threshold:
                continue

            atr = tech_result["indicators"].get("atr", 0)
            if atr <= 0:
                continue

            price = float(current["close"])
            if direction == "LONG":
                sl = price - config.sl_atr_multiplier * atr
                tp1 = price + config.tp1_atr_multiplier * atr
                tp2 = price + config.tp2_atr_multiplier * atr
            else:
                sl = price + config.sl_atr_multiplier * atr
                tp1 = price - config.tp1_atr_multiplier * atr
                tp2 = price - config.tp2_atr_multiplier * atr
```

The rest of the trade creation code (lines 129-163) stays the same — it uses `direction`, `score`, `sl`, `tp1`, `tp2`, `detected` which are now set by whichever branch ran.

**Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py -v`
Expected: All pass (both old and new tests)

---

### Task 15: Add ML backtest mode to API

**Files:**
- Modify: `backend/app/api/backtest.py`

**Step 1: Add ml_mode flag to RunRequest**

In `backend/app/api/backtest.py`, add to `RunRequest` (line 33-45):

```python
class RunRequest(BaseModel):
    pairs: list[str]
    timeframe: str
    date_from: str
    date_to: str
    signal_threshold: int = Field(default=50, ge=1, le=100)
    tech_weight: float = Field(default=0.75, ge=0, le=1)
    pattern_weight: float = Field(default=0.25, ge=0, le=1)
    enable_patterns: bool = True
    sl_atr_multiplier: float = Field(default=1.5, gt=0)
    tp1_atr_multiplier: float = Field(default=2.0, gt=0)
    tp2_atr_multiplier: float = Field(default=3.0, gt=0)
    max_concurrent_positions: int = Field(default=3, ge=1, le=20)
    ml_mode: bool = False  # NEW: use ML model instead of rule-based scoring
    ml_confidence_threshold: float = Field(default=0.65, ge=0.1, le=1.0)
```

**Step 2: Pass predictor and confidence threshold in the backtest task**

In the `_run()` async function inside `start_backtest()`, first add `ml_confidence_threshold` when constructing `bt_config` (around line 145-154):

```python
            bt_config = BacktestConfig(
                signal_threshold=body.signal_threshold,
                tech_weight=body.tech_weight,
                pattern_weight=body.pattern_weight,
                enable_patterns=body.enable_patterns,
                sl_atr_multiplier=body.sl_atr_multiplier,
                tp1_atr_multiplier=body.tp1_atr_multiplier,
                tp2_atr_multiplier=body.tp2_atr_multiplier,
                max_concurrent_positions=body.max_concurrent_positions,
                ml_confidence_threshold=body.ml_confidence_threshold,
            )
```

Then modify the `run_backtest` call (around line 187):

```python
                # Load per-pair ML predictor if ml_mode requested
                ml_predictor = None
                if body.ml_mode:
                    predictors = getattr(request.app.state, "ml_predictors", {})
                    pair_slug = pair.replace("-", "_").lower()
                    ml_predictor = predictors.get(pair_slug)
                    if ml_predictor is None:
                        raise ValueError(f"No ML model for {pair}. Train via POST /api/ml/train")

                result = await asyncio.to_thread(
                    run_backtest, candles, pair, bt_config, cancel_flags.get(run_id),
                    ml_predictor,
                )
```

**Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_backtest.py tests/engine/test_backtester.py -v`
Expected: All pass

---

## Phase 7 Checkpoint — FINAL

Run the full test suite:

```bash
docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60
```

Expected: All tests pass.

---

## Usage Guide

### 1. Import historical data

```bash
curl -X POST http://localhost:8000/api/backtest/import \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pairs": ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"], "timeframes": ["1h"], "lookback_days": 365}'
```

### 2. Train the model

```bash
curl -X POST http://localhost:8000/api/ml/train \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"timeframe": "1h", "epochs": 100, "hidden_size": 128, "label_horizon": 24, "label_threshold_pct": 1.5}'
```

### 3. Enable ML in live pipeline

Set in `.env`:
```
ML_ENABLED=true
```

Restart the container.

### 4. Backtest ML vs rule-based

In the Backtest UI, use the **Scoring Mode** toggle to switch between "Rule-Based" and "ML Model". When ML is selected, rule-based configs (scoring weights, indicators, SL/TP multipliers) are hidden since the ML model handles these. Run one backtest with each mode, then use the Compare tab to see the difference.

Alternatively via API — run two backtests with `ml_mode: false` and `ml_mode: true`, then compare via `/api/backtest/compare`.

---

## Phase 8: Frontend Integration

**Checkpoint:** After this phase, the backtest UI supports an ML mode toggle that hides irrelevant rule-based configs, and the settings page shows ML model status.

---

### Task 16: Add ML fields to frontend backtest types and store

**Files:**
- Modify: `web/src/features/backtest/types.ts`
- Modify: `web/src/features/backtest/store.ts`

**Step 1: Add ML fields to BacktestConfig interface**

In `web/src/features/backtest/types.ts`, add to `BacktestConfig` (after `max_concurrent_positions`):

```typescript
export interface BacktestConfig {
  pairs: string[];
  timeframe: string;
  date_from: string;
  date_to: string;
  signal_threshold: number;
  tech_weight: number;
  pattern_weight: number;
  enable_patterns: boolean;
  sl_atr_multiplier: number;
  tp1_atr_multiplier: number;
  tp2_atr_multiplier: number;
  max_concurrent_positions: number;
  ml_mode: boolean;
  ml_confidence_threshold: number;
}
```

**Step 2: Add defaults in store**

In `web/src/features/backtest/store.ts`, add to `defaultConfig`:

```typescript
const defaultConfig: BacktestConfig = {
  pairs: [...AVAILABLE_PAIRS],
  timeframe: "15m",
  date_from: new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10),
  date_to: new Date().toISOString().slice(0, 10),
  signal_threshold: 30,
  tech_weight: 75,
  pattern_weight: 25,
  enable_patterns: true,
  sl_atr_multiplier: 1.5,
  tp1_atr_multiplier: 2.0,
  tp2_atr_multiplier: 3.0,
  max_concurrent_positions: 3,
  ml_mode: false,
  ml_confidence_threshold: 65,
};
```

**Step 3: Update startRun payload**

The `startRun` function in `store.ts` (line 84) already spreads `...config` into the payload, so `ml_mode` and `ml_confidence_threshold` will be sent automatically. Update the weight conversion to also convert `ml_confidence_threshold` from 0-100 to 0-1:

Replace lines 84-88:

```typescript
      const payload = {
        ...config,
        tech_weight: config.tech_weight / 100,
        pattern_weight: config.pattern_weight / 100,
        ml_confidence_threshold: config.ml_confidence_threshold / 100,
      };
```

**Step 4: Verify build**

Run: `cd web && pnpm build`
Expected: No type errors

---

### Task 17: Update BacktestSetup UI with ML mode toggle and conditional config visibility

**Files:**
- Modify: `web/src/features/backtest/components/BacktestSetup.tsx`

**Step 1: Add ML Mode toggle section**

In `BacktestSetup.tsx`, add a new section right after the Timeframe section (after line 70 — `</Section>`). This toggle switches between ML and rule-based scoring:

```tsx
      {/* Scoring Mode */}
      <Section title="Scoring Mode">
        <div className="flex gap-1.5">
          <button
            onClick={() => updateConfig({ ml_mode: false })}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
              !config.ml_mode
                ? "bg-accent/15 text-accent border border-accent/30"
                : "bg-card-hover text-muted"
            }`}
          >
            Rule-Based
          </button>
          <button
            onClick={() => updateConfig({ ml_mode: true })}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
              config.ml_mode
                ? "bg-accent/15 text-accent border border-accent/30"
                : "bg-card-hover text-muted"
            }`}
          >
            ML Model
          </button>
        </div>
        {config.ml_mode && (
          <p className="text-[10px] text-dim mt-2">
            Uses trained LSTM model for scoring. Train a model first via Settings.
          </p>
        )}
      </Section>
```

**Step 2: Conditionally show/hide rule-based configs**

When `ml_mode` is true, the following sections are **not used** by the ML scoring branch and should be hidden:
- **Scoring Weights** (tech_weight, pattern_weight) — ML doesn't use these
- **Thresholds** (signal_threshold) — ML uses ml_confidence_threshold instead
- **Indicators** (EMA/MACD/RSI/BB/Patterns) — ML uses its own features
- **SL/TP multipliers** — ML provides its own SL/TP via the model

Wrap these sections with `{!config.ml_mode && ...}`:

```tsx
      {/* Scoring Weights — only shown in rule-based mode */}
      {!config.ml_mode && (
        <Section title="Scoring Weights">
          {/* ... existing weight sliders unchanged ... */}
        </Section>
      )}

      {/* Thresholds — swap between signal_threshold and ml_confidence */}
      <Section title="Thresholds">
        {config.ml_mode ? (
          <>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm">ML Confidence</span>
              <span className="text-sm font-mono text-accent">{config.ml_confidence_threshold}%</span>
            </div>
            <input
              type="range"
              min={50}
              max={95}
              value={config.ml_confidence_threshold}
              onChange={(e) => updateConfig({ ml_confidence_threshold: Number(e.target.value) })}
              className="w-full accent-accent"
            />
            <div className="flex justify-between text-[10px] text-dim mt-0.5">
              <span>More signals</span>
              <span>High confidence only</span>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm">Signal Threshold</span>
              <span className="text-sm font-mono text-accent">{config.signal_threshold}</span>
            </div>
            <input
              type="range"
              min={10}
              max={100}
              value={config.signal_threshold}
              onChange={(e) => updateConfig({ signal_threshold: Number(e.target.value) })}
              className="w-full accent-accent"
            />
            <div className="flex justify-between text-[10px] text-dim mt-0.5">
              <span>More signals</span>
              <span>Strong only</span>
            </div>
          </>
        )}
      </Section>

      {/* Indicators — only shown in rule-based mode */}
      {!config.ml_mode && (
        <Section title="Indicators">
          {/* ... existing indicator badges unchanged ... */}
        </Section>
      )}

      {/* Risk & Levels */}
      <Section title="Risk & Levels">
        {/* SL/TP multipliers — only in rule-based mode */}
        {!config.ml_mode ? (
          <>
            <NumberInput label="SL (ATR ×)" value={config.sl_atr_multiplier} step={0.1} min={0.5} max={5}
              onChange={(v) => updateConfig({ sl_atr_multiplier: v })} />
            <NumberInput label="TP1 (ATR ×)" value={config.tp1_atr_multiplier} step={0.1} min={0.5} max={10}
              onChange={(v) => updateConfig({ tp1_atr_multiplier: v })} />
            <NumberInput label="TP2 (ATR ×)" value={config.tp2_atr_multiplier} step={0.1} min={0.5} max={10}
              onChange={(v) => updateConfig({ tp2_atr_multiplier: v })} />
          </>
        ) : (
          <p className="text-xs text-dim py-1">SL/TP levels are set by the ML model</p>
        )}
        <NumberInput label="Max Positions" value={config.max_concurrent_positions} step={1} min={1} max={10}
          onChange={(v) => updateConfig({ max_concurrent_positions: v })} />
      </Section>
```

**Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: No type errors

---

### Task 18: Add ML status section to MorePage settings

**Files:**
- Modify: `web/src/features/more/components/MorePage.tsx`
- Modify: `web/src/shared/lib/api.ts` (add ML status API method)

**Step 1: Add ML API methods to api client**

In `web/src/shared/lib/api.ts`, add after the backtest methods (after `deleteBacktestRun`):

```typescript
  // ML
  getMLStatus: () =>
    request<{ ml_enabled: boolean; loaded_pairs: string[] }>("/api/ml/status"),

  startMLTraining: (params: {
    timeframe?: string;
    epochs?: number;
    lookback_days?: number;
  }) =>
    request<{ job_id: string; status: string }>("/api/ml/train", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  getMLTrainingStatus: (jobId: string) =>
    request<{ job_id: string; status: string; progress: Record<string, unknown>; result?: Record<string, unknown> }>(
      `/api/ml/train/${jobId}`,
    ),
```

**Step 2: Add ML Status section to MorePage**

In `web/src/features/more/components/MorePage.tsx`, add a new `MLStatusSection` component and render it between `DataSourcesSection` and `RiskManagementSection` (between lines 183 and 186):

```tsx
      {/* ML MODEL */}
      <MLStatusSection />
```

Add the component:

```tsx
function MLStatusSection() {
  const [status, setStatus] = useState<{ ml_enabled: boolean; loaded_pairs: string[] } | null>(null);
  const [training, setTraining] = useState(false);
  const [trainJobId, setTrainJobId] = useState<string | null>(null);
  const [trainStatus, setTrainStatus] = useState<string | null>(null);

  useEffect(() => {
    api.getMLStatus().then(setStatus).catch(() => {});
  }, []);

  async function handleTrain() {
    setTraining(true);
    setTrainStatus("starting...");
    try {
      const { job_id } = await api.startMLTraining({ timeframe: "1h", epochs: 100 });
      setTrainJobId(job_id);
      // Poll for completion
      const interval = setInterval(async () => {
        try {
          const result = await api.getMLTrainingStatus(job_id);
          setTrainStatus(result.status);
          if (result.status !== "running") {
            clearInterval(interval);
            setTraining(false);
            // Refresh status
            api.getMLStatus().then(setStatus).catch(() => {});
          }
        } catch {
          clearInterval(interval);
          setTraining(false);
          setTrainStatus("error");
        }
      }, 3000);
    } catch {
      setTraining(false);
      setTrainStatus("failed to start");
    }
  }

  return (
    <SettingsGroup title="ML Model">
      <div className="px-3 py-3 border-b border-border flex items-center justify-between">
        <div>
          <span className="text-sm">Status</span>
          {status && (
            <p className="text-[10px] text-dim mt-0.5">
              {status.loaded_pairs.length > 0
                ? `Loaded: ${status.loaded_pairs.map((p) => p.replace("_", "-").toUpperCase()).join(", ")}`
                : "No models trained yet"}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${status?.loaded_pairs.length ? "bg-long" : "bg-muted"}`} />
          <span className="text-sm text-muted">
            {status?.loaded_pairs.length ? "Ready" : "Inactive"}
          </span>
        </div>
      </div>
      <div className="px-3 py-3 flex items-center justify-between">
        <div>
          <span className="text-sm">Train Model</span>
          {trainStatus && (
            <p className="text-[10px] text-dim mt-0.5">
              {trainStatus === "running" ? "Training in progress..." : `Last: ${trainStatus}`}
            </p>
          )}
        </div>
        <button
          onClick={handleTrain}
          disabled={training}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
            training
              ? "bg-card-hover text-dim"
              : "bg-accent/15 text-accent border border-accent/30"
          }`}
        >
          {training ? "Training..." : "Train"}
        </button>
      </div>
    </SettingsGroup>
  );
}
```

**Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: No type errors

---

## Phase 8 Checkpoint

Run frontend build and lint:

```bash
cd web && pnpm build && pnpm lint
```

Expected: No errors. ML mode toggle works in backtest setup, rule-based configs hide when ML is selected, and ML status shows in settings.

---

## File Summary

| Action | Path |
|--------|------|
| Create | `backend/app/ml/__init__.py` |
| Create | `backend/app/ml/features.py` |
| Create | `backend/app/ml/labels.py` |
| Create | `backend/app/ml/dataset.py` |
| Create | `backend/app/ml/model.py` |
| Create | `backend/app/ml/trainer.py` |
| Create | `backend/app/ml/predictor.py` |
| Create | `backend/app/ml/ensemble.py` |
| Create | `backend/app/ml/data_loader.py` |
| Create | `backend/app/api/ml.py` |
| Create | `backend/tests/ml/__init__.py` |
| Create | `backend/tests/ml/test_features.py` |
| Create | `backend/tests/ml/test_labels.py` |
| Create | `backend/tests/ml/test_dataset.py` |
| Create | `backend/tests/ml/test_model.py` |
| Create | `backend/tests/ml/test_trainer.py` |
| Create | `backend/tests/ml/test_predictor.py` |
| Create | `backend/tests/ml/test_ensemble.py` |
| Create | `backend/tests/ml/test_data_loader.py` |
| Create | `backend/tests/api/test_ml.py` |
| Create | `backend/tests/test_pipeline_ml.py` |
| Modify | `backend/app/db/models.py` (add OrderFlowSnapshot) |
| Modify | `backend/app/main.py` (ML integration + order flow persist) |
| Modify | `backend/app/config.py` (ML settings) |
| Modify | `backend/app/engine/backtester.py` (ML mode) |
| Modify | `backend/app/api/backtest.py` (ml_mode flag) |
| Modify | `backend/requirements.txt` (torch) |
| Modify | `backend/Dockerfile` (multi-stage build for torch) |
| Modify | `web/src/features/backtest/types.ts` (add ml_mode, ml_confidence_threshold) |
| Modify | `web/src/features/backtest/store.ts` (ML defaults + payload conversion) |
| Modify | `web/src/features/backtest/components/BacktestSetup.tsx` (ML toggle + conditional config) |
| Modify | `web/src/features/more/components/MorePage.tsx` (ML status section) |
| Modify | `web/src/shared/lib/api.ts` (ML API methods) |
| Migration | `alembic revision --autogenerate` (order_flow_snapshots table) |
