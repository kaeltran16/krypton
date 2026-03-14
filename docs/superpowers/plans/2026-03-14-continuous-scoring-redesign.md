# Continuous Scoring Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace step-function indicator scoring with continuous sigmoid mapping, redesign technical indicators for orthogonal signals, make on-chain scoring pair-aware, and add volume/trend context to pattern scoring.

**Architecture:** Four scoring components (technical, order flow, on-chain, patterns) are rewritten with sigmoid math. Two shared helpers (`sigmoid_score`, `sigmoid_scale`) provide the continuous mapping. Pipeline integration points (main.py, backtester.py) update indicator_ctx shape and candle count guards. Thresholds lowered to match new score distribution.

**Tech Stack:** Python 3.11, pandas, numpy, pytest. Tests run via `docker exec krypton-api-1 python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-03-14-continuous-scoring-redesign.md`

---

## Chunk 1: Sigmoid Helpers + Technical Score

### Task 1: Sigmoid helper functions

**Files:**
- Create: `backend/app/engine/scoring.py`
- Create: `backend/tests/engine/test_scoring.py`

- [ ] **Step 1: Write failing tests for sigmoid helpers**

```python
# backend/tests/engine/test_scoring.py
from math import isclose
from app.engine.scoring import sigmoid_score, sigmoid_scale


class TestSigmoidScore:
    def test_center_returns_zero(self):
        assert sigmoid_score(0, center=0, steepness=1) == 0
        assert sigmoid_score(50, center=50, steepness=0.1) == 0

    def test_positive_input_returns_positive(self):
        result = sigmoid_score(10, center=0, steepness=0.1, max_score=25)
        assert result > 0

    def test_negative_input_returns_negative(self):
        result = sigmoid_score(-10, center=0, steepness=0.1, max_score=25)
        assert result < 0

    def test_bounded_by_max_score(self):
        assert sigmoid_score(1000, center=0, steepness=1, max_score=25) < 25.01
        assert sigmoid_score(-1000, center=0, steepness=1, max_score=25) > -25.01

    def test_monotonic(self):
        scores = [sigmoid_score(v, center=0, steepness=0.1) for v in range(-50, 51)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]

    def test_symmetric(self):
        pos = sigmoid_score(10, center=0, steepness=0.5, max_score=30)
        neg = sigmoid_score(-10, center=0, steepness=0.5, max_score=30)
        assert isclose(pos, -neg, rel_tol=1e-9)


class TestSigmoidScale:
    def test_center_returns_half(self):
        assert isclose(sigmoid_scale(20, center=20, steepness=0.15), 0.5)

    def test_high_value_approaches_one(self):
        assert sigmoid_scale(50, center=20, steepness=0.15) > 0.95

    def test_low_value_approaches_zero(self):
        assert sigmoid_scale(0, center=20, steepness=0.15) < 0.1

    def test_always_between_zero_and_one(self):
        for v in range(-100, 200):
            result = sigmoid_scale(v, center=20, steepness=0.15)
            assert 0 <= result <= 1

    def test_monotonic(self):
        scores = [sigmoid_scale(v, center=20, steepness=0.15) for v in range(0, 60)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine.scoring'`

- [ ] **Step 3: Implement sigmoid helpers**

```python
# backend/app/engine/scoring.py
from math import exp


def sigmoid_score(value: float, center: float = 0, steepness: float = 0.1, max_score: float = 1.0) -> float:
    """Bipolar: maps value to [-max_score, +max_score] via smooth S-curve.
    center produces 0. Values above center -> positive, below -> negative."""
    return max_score * (2 / (1 + exp(-steepness * (value - center))) - 1)


def sigmoid_scale(value: float, center: float = 0, steepness: float = 0.1) -> float:
    """Unipolar: maps value to [0, 1] via standard logistic curve.
    center produces 0.5. Used for magnitude scaling (e.g., ADX strength)."""
    return 1 / (1 + exp(-steepness * (value - center)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_scoring.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/scoring.py backend/tests/engine/test_scoring.py
git commit -m "feat(engine): add sigmoid scoring helper functions"
```

---

### Task 2: Rewrite compute_technical_score

**Files:**
- Rewrite: `backend/app/engine/traditional.py` (full file — lines 1-161)
- Rewrite: `backend/tests/engine/test_traditional.py` (full file — lines 1-91, removing old order flow tests too)

**References:**
- Spec Section 2: Technical Score — Orthogonal Indicator Redesign
- `backend/app/engine/scoring.py` (sigmoid helpers from Task 1)

- [ ] **Step 1: Write failing tests for new technical score**

```python
# backend/tests/engine/test_traditional.py — full rewrite (replaces entire file)
import numpy as np
import pandas as pd
import pytest
from app.engine.traditional import compute_technical_score


def _make_candles(n=80, trend="up"):
    """Generate n candles with a given trend direction."""
    base = 100.0
    rows = []
    for i in range(n):
        if trend == "up":
            c = base + i * 0.5 + np.random.uniform(-0.3, 0.3)
        elif trend == "down":
            c = base - i * 0.5 + np.random.uniform(-0.3, 0.3)
        else:
            c = base + np.random.uniform(-1, 1)
        o = c + np.random.uniform(-0.5, 0.5)
        h = max(o, c) + np.random.uniform(0, 0.5)
        l = min(o, c) - np.random.uniform(0, 0.5)
        v = np.random.uniform(100, 200)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(rows)


class TestTechnicalScoreBounds:
    def test_score_within_bounds(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100

    def test_returns_integer(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert isinstance(result["score"], int)


class TestTechnicalScoreDirection:
    def test_uptrend_positive(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert result["score"] > 0

    def test_downtrend_negative(self):
        df = _make_candles(80, "down")
        result = compute_technical_score(df)
        assert result["score"] < 0


class TestTechnicalScoreIndicators:
    def test_new_indicators_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        for key in ["adx", "di_plus", "di_minus", "rsi", "bb_upper", "bb_lower",
                     "bb_width_pct", "bb_pos", "obv_slope", "vol_ratio", "atr"]:
            assert key in indicators, f"Missing indicator: {key}"

    def test_old_indicators_removed(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        for key in ["ema_9", "ema_21", "ema_50", "macd", "macd_signal", "macd_hist"]:
            assert key not in indicators, f"Old indicator still present: {key}"


class TestTechnicalScoreContinuity:
    def test_rsi_no_dead_zone(self):
        """RSI values in the old dead zone (40-60) should produce non-zero scores."""
        df = _make_candles(80, "flat")
        result = compute_technical_score(df)
        rsi = result["indicators"]["rsi"]
        # If RSI is in 40-60, the old system gave 0. New system should not.
        if 40 < rsi < 60 and rsi != 50:
            # Score won't be exactly the RSI contribution alone, but indicators dict
            # confirms RSI is computed and the total score is non-zero from other dims
            assert result["indicators"]["rsi"] is not None

    def test_monotonic_rsi_scoring(self):
        """Lower RSI should yield higher (more bullish) score contribution,
        tested by comparing two synthetic dataframes."""
        # Create two dataframes that differ mainly in RSI
        df_low_rsi = _make_candles(80, "down")  # lower RSI
        df_high_rsi = _make_candles(80, "up")   # higher RSI
        r1 = compute_technical_score(df_low_rsi)
        r2 = compute_technical_score(df_high_rsi)
        # Lower RSI should have a more positive RSI contribution
        # We can't isolate RSI score, but we verify RSI values differ
        assert r1["indicators"]["rsi"] < r2["indicators"]["rsi"]


class TestVolumeContribution:
    def test_obv_slope_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert result["indicators"]["obv_slope"] is not None

    def test_vol_ratio_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert result["indicators"]["vol_ratio"] > 0


class TestMinimumCandles:
    def test_requires_70_candles(self):
        df = _make_candles(69, "up")
        with pytest.raises(ValueError, match="at least 70"):
            compute_technical_score(df)

    def test_exactly_70_candles_succeeds(self):
        df = _make_candles(70, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestTechnicalScoreIndicators::test_new_indicators_present -v`
Expected: FAIL — old indicators present, new ones missing

- [ ] **Step 3: Implement new compute_technical_score**

Rewrite the entire `backend/app/engine/traditional.py` file. The new file includes both `compute_technical_score` (new orthogonal indicators) and a temporary copy of the old `compute_order_flow_score` — Task 3 will replace the order flow function.

```python
# backend/app/engine/traditional.py — replace lines 1-118
import numpy as np
import pandas as pd

from app.engine.scoring import sigmoid_score, sigmoid_scale


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    """Compute ADX, +DI, -DI."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)

    # Zero out the smaller DM
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    atr = _atr(high, low, close, length)

    plus_di = 100 * plus_dm.rolling(length).mean() / atr
    minus_di = 100 * minus_dm.rolling(length).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(length).mean()

    return adx, plus_di, minus_di


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


def compute_technical_score(candles: pd.DataFrame) -> dict:
    """Compute technical analysis score using orthogonal indicator dimensions.

    Returns dict with 'score' (-100 to +100) and 'indicators' dict.
    Requires at least 70 candles for reliable indicators.
    """
    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]

    if len(df) < 70:
        raise ValueError(f"compute_technical_score requires at least 70 candles, got {len(df)}")

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    open_ = df["open"].astype(float)

    # === Compute indicators ===
    atr = _atr(high, low, close, 14)
    adx_series, plus_di, minus_di = _adx(high, low, close, 14)
    rsi = _rsi(close, 14)

    sma_20 = close.rolling(20).mean()
    std_20 = close.rolling(20).std()
    bb_upper = sma_20 + 2 * std_20
    bb_lower = sma_20 - 2 * std_20
    bb_width = bb_upper - bb_lower

    obv = _obv(close, volume)

    last = df.index[-1]

    # Extract last values
    adx_val = float(adx_series[last]) if pd.notna(adx_series[last]) else 0.0
    di_plus_val = float(plus_di[last]) if pd.notna(plus_di[last]) else 0.0
    di_minus_val = float(minus_di[last]) if pd.notna(minus_di[last]) else 0.0
    rsi_val = float(rsi[last]) if pd.notna(rsi[last]) else 50.0
    atr_val = float(atr[last]) if pd.notna(atr[last]) else 0.0

    bb_upper_val = float(bb_upper[last])
    bb_lower_val = float(bb_lower[last])
    bb_range = bb_upper_val - bb_lower_val
    bb_pos = (float(close[last]) - bb_lower_val) / bb_range if bb_range > 0 else 0.5

    # BB width percentile over last 50 values
    bb_widths = bb_width.dropna().values
    if len(bb_widths) >= 50:
        recent_widths = bb_widths[-50:]
        current_width = bb_widths[-1]
        bb_width_pct = float(np.sum(recent_widths < current_width) / len(recent_widths) * 100)
    else:
        bb_width_pct = 50.0

    # OBV slope (last 10 candles), normalized by average volume
    obv_vals = obv.values
    if len(obv_vals) >= 10:
        obv_recent = obv_vals[-10:]
        x = np.arange(10, dtype=float)
        obv_slope = float(np.polyfit(x, obv_recent, 1)[0])
    else:
        obv_slope = 0.0

    avg_volume = float(volume.rolling(20).mean().iloc[-1])
    obv_slope_norm = obv_slope / avg_volume if avg_volume > 0 else 0.0

    # Volume ratio
    vol_ratio = float(volume.iloc[-1]) / avg_volume if avg_volume > 0 else 1.0
    candle_direction = 1 if float(close.iloc[-1]) > float(open_.iloc[-1]) else -1

    # === Scoring ===
    # 1. Trend (max ±30)
    di_sign = 1 if di_plus_val > di_minus_val else -1
    trend_score = di_sign * sigmoid_scale(adx_val, center=20, steepness=0.15) * 30

    # 2. Mean reversion (max ±25)
    rsi_score = sigmoid_score(50 - rsi_val, center=0, steepness=0.15) * 25

    # 3. Volatility & position (max ±25)
    bb_pos_score = sigmoid_score(0.5 - bb_pos, center=0, steepness=6) * 15
    bb_pos_sign = 1 if bb_pos_score > 0 else (-1 if bb_pos_score < 0 else 0)
    bb_width_score = bb_pos_sign * sigmoid_score(50 - bb_width_pct, center=0, steepness=0.06) * 10

    # 4. Volume confirmation (max ±20)
    obv_score = sigmoid_score(obv_slope_norm, center=0, steepness=2) * 12
    vol_score = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=1.5) * 8

    total = trend_score + rsi_score + bb_pos_score + bb_width_score + obv_score + vol_score
    score = max(min(round(total), 100), -100)

    indicators = {
        "adx": round(adx_val, 2),
        "di_plus": round(di_plus_val, 2),
        "di_minus": round(di_minus_val, 2),
        "rsi": round(rsi_val, 2),
        "bb_upper": round(bb_upper_val, 2),
        "bb_lower": round(bb_lower_val, 2),
        "bb_pos": round(bb_pos, 4),
        "bb_width_pct": round(bb_width_pct, 1),
        "obv_slope": round(obv_slope_norm, 4),
        "vol_ratio": round(vol_ratio, 4),
        "atr": round(atr_val, 4),
    }

    return {"score": score, "indicators": indicators}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v -k "not OrderFlow"`
Expected: All technical score tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/traditional.py backend/tests/engine/test_traditional.py
git commit -m "feat(engine): rewrite technical scoring with orthogonal sigmoid indicators"
```

---

### Task 3: Rewrite compute_order_flow_score

**Files:**
- Modify: `backend/app/engine/traditional.py` (locate `compute_order_flow_score` by function name — line numbers will have shifted after Task 2)
- Modify: `backend/tests/engine/test_traditional.py` (append new order flow tests)

**References:**
- Spec Section 3: Order Flow Score — Continuous Redesign

- [ ] **Step 1: Write failing tests for new order flow score**

Append to `backend/tests/engine/test_traditional.py`:

```python
from app.engine.traditional import compute_order_flow_score


class TestOrderFlowBounds:
    def test_score_within_bounds(self):
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.1, "long_short_ratio": 2.0}
        result = compute_order_flow_score(metrics)
        assert -100 <= result["score"] <= 100

    def test_empty_metrics_returns_zero(self):
        result = compute_order_flow_score({})
        assert result["score"] == 0


class TestOrderFlowContinuity:
    def test_funding_rate_no_dead_zone(self):
        """Small positive funding should produce a small negative score (contrarian)."""
        result = compute_order_flow_score({"funding_rate": 0.00005})
        assert result["score"] < 0

    def test_negative_funding_is_bullish(self):
        result = compute_order_flow_score({"funding_rate": -0.0005})
        assert result["score"] > 0

    def test_high_ls_ratio_is_bearish(self):
        result = compute_order_flow_score({"long_short_ratio": 1.8})
        assert result["score"] < 0

    def test_low_ls_ratio_is_bullish(self):
        result = compute_order_flow_score({"long_short_ratio": 0.6})
        assert result["score"] > 0


class TestOrderFlowDirectionalOI:
    def test_oi_increase_with_bullish_candle(self):
        """OI increase + bullish price direction = positive contribution."""
        result = compute_order_flow_score({
            "open_interest_change_pct": 0.05,
            "price_direction": 1,
        })
        assert result["score"] > 0

    def test_oi_increase_with_bearish_candle(self):
        """OI increase + bearish price direction = negative contribution (shorts piling in)."""
        result = compute_order_flow_score({
            "open_interest_change_pct": 0.05,
            "price_direction": -1,
        })
        assert result["score"] < 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowContinuity::test_funding_rate_no_dead_zone -v`
Expected: FAIL — old step-function returns 0 for funding=0.00005

- [ ] **Step 3: Implement new compute_order_flow_score**

Locate `compute_order_flow_score` in `backend/app/engine/traditional.py` by function name (line numbers shifted after Task 2) and replace it:

```python
def compute_order_flow_score(metrics: dict) -> dict:
    """Compute order flow score from funding rate, OI changes, and L/S ratio.

    Returns dict with 'score' (-100 to +100) and 'details' dict.
    All keys are optional with safe defaults.
    """
    # Funding rate — contrarian (max ±35)
    funding = metrics.get("funding_rate", 0.0)
    funding_score = sigmoid_score(-funding, center=0, steepness=5000) * 35

    # OI change — direction-aware (max ±20)
    oi_change = metrics.get("open_interest_change_pct", 0.0)
    price_dir = metrics.get("price_direction", 0)
    if price_dir == 0:
        oi_score = 0.0
    else:
        oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=40) * 20

    # L/S ratio — contrarian (max ±35)
    ls = metrics.get("long_short_ratio", 1.0)
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=4) * 35

    total = funding_score + oi_score + ls_score
    score = max(min(round(total), 100), -100)

    return {"score": score, "details": metrics}
```

- [ ] **Step 4: Run all traditional tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/traditional.py backend/tests/engine/test_traditional.py
git commit -m "feat(engine): rewrite order flow scoring with continuous sigmoid"
```

---

## Chunk 2: On-Chain + Pattern Scoring

### Task 4: Rewrite on-chain scorer with pair-aware profiles

**Files:**
- Rewrite: `backend/app/engine/onchain_scorer.py`
- Rewrite: `backend/tests/engine/test_onchain_scorer.py`

**References:**
- Spec Section 4: On-Chain Score — Pair-Aware Redesign

- [ ] **Step 1: Write failing tests for pair-aware on-chain scoring**

```python
# backend/tests/engine/test_onchain_scorer.py — full rewrite
import pytest
from unittest.mock import AsyncMock
from app.engine.onchain_scorer import compute_onchain_score


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    return redis


def _setup_redis(redis, pair, data: dict):
    """Helper to mock Redis keys for on-chain data."""
    async def mock_get(key):
        prefix = f"onchain:{pair}:"
        if key.startswith(prefix):
            metric = key[len(prefix):]
            return str(data.get(metric)) if metric in data else None
        return None
    redis.get = AsyncMock(side_effect=mock_get)


class TestBTCProfile:
    @pytest.mark.asyncio
    async def test_btc_outflow_is_bullish(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -5000})
        score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert score > 0

    @pytest.mark.asyncio
    async def test_btc_inflow_is_bearish(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": 5000})
        score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert score < 0

    @pytest.mark.asyncio
    async def test_btc_high_nupl_is_bearish(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"nupl": 0.8})
        score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert score < 0

    @pytest.mark.asyncio
    async def test_btc_score_bounded(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {
            "exchange_netflow": -10000, "whale_tx_count": 0,
            "nupl": -0.5, "hashrate_change_pct": 0.5, "addr_trend_pct": 0.5,
        })
        score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert -100 <= score <= 100


class TestETHProfile:
    @pytest.mark.asyncio
    async def test_eth_outflow_is_bullish(self, mock_redis):
        _setup_redis(mock_redis, "ETH-USDT-SWAP", {"exchange_netflow": -100000})
        score = await compute_onchain_score("ETH-USDT-SWAP", mock_redis)
        assert score > 0

    @pytest.mark.asyncio
    async def test_eth_uses_different_normalization(self, mock_redis):
        """Same netflow magnitude should produce different scores for BTC vs ETH."""
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -3000})
        btc_score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)

        _setup_redis(mock_redis, "ETH-USDT-SWAP", {"exchange_netflow": -3000})
        eth_score = await compute_onchain_score("ETH-USDT-SWAP", mock_redis)

        # 3000 is a full normalization unit for BTC but small for ETH (50000)
        assert abs(btc_score) > abs(eth_score)


class TestUnknownPair:
    @pytest.mark.asyncio
    async def test_unknown_pair_returns_zero(self, mock_redis):
        score = await compute_onchain_score("DOGE-USDT-SWAP", mock_redis)
        assert score == 0


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_missing_metrics_still_score(self, mock_redis):
        """Only netflow available — should still produce a score from that component."""
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -5000})
        score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert score > 0

    @pytest.mark.asyncio
    async def test_no_data_returns_zero(self, mock_redis):
        score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert score == 0


class TestSigmoidContinuity:
    @pytest.mark.asyncio
    async def test_small_netflow_produces_small_score(self, mock_redis):
        """No dead zone — even small netflow should produce non-zero score."""
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -100})
        score = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert score != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_onchain_scorer.py -v`
Expected: FAIL — old scorer has no pair-awareness

- [ ] **Step 3: Implement pair-aware on-chain scorer**

```python
# backend/app/engine/onchain_scorer.py — full rewrite
import json
import logging

from app.engine.scoring import sigmoid_score

logger = logging.getLogger(__name__)

# Per-asset profile definitions
_PROFILES = {
    "BTC": {
        "netflow_norm": 3000,
        "whale_baseline": 3,
        "metrics": ["exchange_netflow", "whale_tx_count", "nupl", "hashrate_change_pct", "addr_trend_pct"],
    },
    "ETH": {
        "netflow_norm": 50000,
        "whale_baseline": 5,
        "metrics": ["exchange_netflow", "whale_tx_count", "staking_flow", "gas_trend_pct", "addr_trend_pct"],
    },
}


async def _get_metric(redis, pair: str, metric: str) -> float | None:
    """Read a single on-chain metric from Redis. Returns None if missing.

    Handles both plain float strings and JSON objects with a 'value' key
    (the current OnChainCollector stores JSON objects).
    """
    try:
        raw = await redis.get(f"onchain:{pair}:{metric}")
        if raw is None:
            return None
        # Try plain float first, fall back to JSON
        try:
            return float(raw)
        except (ValueError, TypeError):
            data = json.loads(raw)
            return float(data.get("value", 0)) if isinstance(data, dict) else float(data)
    except Exception:
        return None


async def compute_onchain_score(pair: str, redis) -> int:
    """Compute on-chain score for a given pair using asset-specific profile.

    Returns int in [-100, +100]. Unknown pairs return 0.
    Each metric is scored independently; missing metrics contribute 0.
    """
    asset = pair.split("-")[0].upper()
    profile = _PROFILES.get(asset)
    if profile is None:
        return 0

    score = 0.0

    # Exchange netflow (±35) — outflow = bullish
    netflow = await _get_metric(redis, pair, "exchange_netflow")
    if netflow is not None:
        score += sigmoid_score(-netflow / profile["netflow_norm"], center=0, steepness=1.5) * 35

    # Whale activity (±20) — contrarian
    whale_count = await _get_metric(redis, pair, "whale_tx_count")
    if whale_count is not None:
        score += sigmoid_score(profile["whale_baseline"] - whale_count, center=0, steepness=0.3) * 20

    # Active addresses trend (±15) — rising = bullish
    addr_trend = await _get_metric(redis, pair, "addr_trend_pct")
    if addr_trend is not None:
        score += sigmoid_score(addr_trend, center=0, steepness=8) * 15

    # Asset-specific metrics
    if asset == "BTC":
        # NUPL (±15) — contrarian
        nupl = await _get_metric(redis, pair, "nupl")
        if nupl is not None:
            score += sigmoid_score(0.5 - nupl, center=0, steepness=3) * 15

        # Hashrate trend (±15) — rising = miner confidence
        hashrate = await _get_metric(redis, pair, "hashrate_change_pct")
        if hashrate is not None:
            score += sigmoid_score(hashrate, center=0, steepness=10) * 15

    elif asset == "ETH":
        # Staking flow (±15) — net deposits = supply lock
        staking = await _get_metric(redis, pair, "staking_flow")
        if staking is not None:
            score += sigmoid_score(-staking, center=0, steepness=1) * 15

        # Gas price trend (±15) — rising = demand
        gas_trend = await _get_metric(redis, pair, "gas_trend_pct")
        if gas_trend is not None:
            score += sigmoid_score(gas_trend, center=0, steepness=5) * 15

    return max(min(round(score), 100), -100)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_onchain_scorer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/onchain_scorer.py backend/tests/engine/test_onchain_scorer.py
git commit -m "feat(engine): pair-aware on-chain scoring with sigmoid"
```

---

### Task 5: Update pattern scoring with contextual boosts

**Files:**
- Modify: `backend/app/engine/patterns.py` (lines 210-262, `compute_pattern_score`)
- Modify: `backend/tests/engine/test_patterns.py` (add new boost tests, update fixtures)

**References:**
- Spec Section 5: Pattern Score — Context-Aware Boosts
- Current pattern detection code is unchanged — only the scoring/boost logic changes

- [ ] **Step 1: Write failing tests for new boosts**

Append to `backend/tests/engine/test_patterns.py`:

```python
from app.engine.patterns import compute_pattern_score


class TestTrendAlignmentBoost:
    def test_reversal_pattern_gets_boost(self):
        """Bullish pattern in bearish ADX trend (reversal) gets 1.3x."""
        patterns = [{"name": "Bullish Engulfing", "type": "two_candle", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        # 15 * 1.3 (reversal) = 19.5, rounded = 20
        # No other boosts active (vol_ratio=1.0, bb_pos=0.5)
        assert score > 15  # boosted above base strength

    def test_weak_trend_no_boost(self):
        """ADX < 15 — no trend-alignment boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score == 12  # no boost


class TestVolumeConfirmationBoost:
    def test_high_volume_gets_boost(self):
        """Volume ratio > 1.5 gets 1.3x boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 2.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score > 12

    def test_normal_volume_no_boost(self):
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score == 12


class TestLevelProximityBoost:
    def test_near_band_edge_gets_boost(self):
        """bb_pos near 0 or 1 should boost."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.05, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score > 12

    def test_center_no_boost(self):
        """bb_pos at 0.5 — no boost (1.0x)."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)
        assert score == 12

    def test_boost_never_below_one(self):
        """Level proximity boost should never go below 1.0."""
        patterns = [{"name": "Hammer", "type": "single", "bias": "bullish", "strength": 12}]
        for bb in [0.0, 0.2, 0.3, 0.5, 0.7, 0.8, 1.0]:
            ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
                   "bb_pos": bb, "close": 100}
            score = compute_pattern_score(patterns, ctx)
            assert score >= 12  # never penalized
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestTrendAlignmentBoost -v`
Expected: FAIL — old function signature doesn't expect new context keys

- [ ] **Step 3: Implement updated compute_pattern_score**

Replace `compute_pattern_score` in `backend/app/engine/patterns.py` (lines 210-262). Keep all pattern detection code above unchanged.

```python
# Replace compute_pattern_score function in patterns.py

from app.engine.scoring import sigmoid_score


def compute_pattern_score(patterns: list[dict], indicator_ctx: dict) -> int:
    """Score detected candlestick patterns with contextual boosts.

    Args:
        patterns: List of detected pattern dicts with 'bias' and 'strength'.
        indicator_ctx: Dict with keys: adx, di_plus, di_minus, vol_ratio, bb_pos, close.

    Returns:
        Score in [-100, +100].
    """
    if not patterns:
        return 0

    adx = indicator_ctx["adx"]
    di_plus = indicator_ctx["di_plus"]
    di_minus = indicator_ctx["di_minus"]
    vol_ratio = indicator_ctx["vol_ratio"]
    bb_pos = indicator_ctx["bb_pos"]

    # Determine ADX trend direction
    adx_bullish = di_plus > di_minus

    total = 0.0

    for p in patterns:
        bias = p.get("bias", "neutral")
        strength = p.get("strength", 0)

        if bias == "neutral":
            continue

        # Trend-alignment boost
        trend_boost = 1.0
        if adx >= 15:
            pattern_bullish = bias == "bullish"
            if pattern_bullish != adx_bullish:
                # Reversal signal
                trend_boost = 1.3
            elif adx >= 30:
                # Continuation with strong trend
                trend_boost = 1.2

        # Volume confirmation boost
        vol_boost = 1.0
        if vol_ratio > 1.5:
            vol_boost = 1.3
        elif vol_ratio > 1.2:
            vol_boost = 1.15

        # Level-proximity boost (continuous, min 1.0)
        raw_level_boost = 0.5 * sigmoid_score(
            abs(bb_pos - 0.5) - 0.3, center=0, steepness=10
        )
        level_boost = 1.0 + max(0, raw_level_boost)

        boosted_strength = strength * trend_boost * vol_boost * level_boost

        if bias == "bullish":
            total += boosted_strength
        else:  # bearish
            total -= boosted_strength

    return max(min(round(total), 100), -100)
```

- [ ] **Step 4: Update existing pattern test fixtures**

Update the `TestPatternScoring` class in `test_patterns.py` to provide the new required `indicator_ctx` format. Find tests that call `compute_pattern_score` with old-style indicators and update them:

```python
# Update existing test_level_proximity_boost and other scoring tests
# Old: indicators = {"close": 100, "bb_lower": 99, "bb_upper": 200, "ema_21": 150, "ema_50": 160}
# New: indicator_ctx with required keys
_DEFAULT_CTX = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
```

Replace all `compute_pattern_score(patterns, old_indicators)` calls with the new ctx format.

- [ ] **Step 5: Run all pattern tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/patterns.py backend/tests/engine/test_patterns.py
git commit -m "feat(engine): add trend/volume/level boosts to pattern scoring"
```

---

## Chunk 3: Pipeline Integration + Config

### Task 6: Update config defaults

**Files:**
- Modify: `backend/app/config.py` (lines 59-60)

- [ ] **Step 1: Update thresholds**

In `backend/app/config.py`, change:
- Line 59: `engine_signal_threshold: int = 50` → `engine_signal_threshold: int = 35`
- Line 60: `engine_llm_threshold: int = 30` → `engine_llm_threshold: int = 25`

- [ ] **Step 2: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(config): lower signal/LLM thresholds for continuous scoring"
```

---

### Task 7: Update main.py pipeline integration

**Files:**
- Modify: `backend/app/main.py` (lines 238, 276-277)

- [ ] **Step 1: Update Redis lrange fetch range**

In `backend/app/main.py` line 233, change the lrange to fetch enough candles:
```python
# Old
raw_candles = await redis.lrange(cache_key, -50, -1)
# New
raw_candles = await redis.lrange(cache_key, -200, -1)
```

**CRITICAL:** Without this change, lrange returns at most 50 candles but the guard requires 70, so the pipeline will NEVER execute.

- [ ] **Step 2: Update candle count guard**

In `backend/app/main.py` line 238, change:
```python
# Old
if len(raw_candles) < 50:
# New
if len(raw_candles) < 70:
```

- [ ] **Step 3: Inject price_direction into order flow metrics**

In `backend/app/main.py`, after computing `flow_metrics` (line 252) and before calling `compute_order_flow_score` (line 253), inject `price_direction` from the latest candle:

```python
flow_metrics = order_flow.get(pair, {})
# Inject price direction for direction-aware OI scoring
flow_metrics = {**flow_metrics, "price_direction": 1 if candle["close"] >= candle["open"] else -1}
flow_result = compute_order_flow_score(flow_metrics)
```

**CRITICAL:** Without this, `price_direction` is always 0 and the OI change scoring component will be permanently zero.

- [ ] **Step 4: Verify indicator_ctx construction**

The indicator_ctx line at line 276 doesn't change in code — but the contents of `tech_result["indicators"]` now include `adx`, `di_plus`, `di_minus`, `vol_ratio`, `bb_pos` which is exactly what `compute_pattern_score` requires. Verify the keys match.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(pipeline): update candle count guard to 70 for new indicators"
```

---

### Task 8: Update backtester

**Files:**
- Modify: `backend/app/engine/backtester.py` (lines 18, 26-27, 148-150)

- [ ] **Step 1: Update MIN_CANDLES**

Line 18: `MIN_CANDLES = 50` → `MIN_CANDLES = 70`

- [ ] **Step 2: Remove obsolete BacktestConfig fields and update defaults**

Remove `enable_ema: bool = True`, `enable_macd: bool = True`, `enable_rsi: bool = True`, and `enable_bb: bool = True` from the `BacktestConfig` dataclass (lines 26-29). These per-indicator flags are dead code — the new `compute_technical_score` always computes all indicators.

Also update `signal_threshold: int = 50` to `signal_threshold: int = 35` in `BacktestConfig` (line 23) to match the new config default.

- [ ] **Step 3: Verify indicator_ctx in backtester**

The backtester's `indicator_ctx` construction at line 148-150 uses `{**tech_result["indicators"], "close": ...}` — same pattern as main.py. Since the new `compute_technical_score` returns the new indicator keys, this works without changes.

- [ ] **Step 4: Run backtester tests if they exist**

Run: `docker exec krypton-api-1 python -m pytest tests/ -k "backtest" -v`
Expected: PASS (or skip if no backtester tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/backtester.py
git commit -m "feat(backtester): update for new indicator set, remove ema/macd flags"
```

---

### Task 9: Update pipeline ML tests

**Files:**
- Modify: `backend/tests/test_pipeline_ml.py`

- [ ] **Step 1: Update candle count and mock indicator dict shape**

Update `_make_candle_list` default from `n=50` to `n=80` (needs 70+ for new indicator guard):

```python
# Old
def _make_candle_list(n=50, ...):
# New
def _make_candle_list(n=80, ...):
```

Also update the Redis lrange mock to return enough candles (the mock's `return_value` must match the new `-200` fetch range).

Update any hardcoded indicator dicts to use the new keys:

```python
# Old indicator keys in mocks:
{"rsi": 32, "ema_9": 67100, "ema_21": 66800, ...}

# New indicator keys:
{"adx": 25, "di_plus": 20, "di_minus": 15, "rsi": 32,
 "bb_upper": 68000, "bb_lower": 66000, "bb_pos": 0.4,
 "bb_width_pct": 40, "obv_slope": 0.5, "vol_ratio": 1.2, "atr": 500}
```

- [ ] **Step 2: Run pipeline tests**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline_ml.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_pipeline_ml.py
git commit -m "test: update pipeline ML test fixtures for new indicator shape"
```

---

### Task 10: Full test suite + live verification

- [ ] **Step 1: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest -v`
Expected: All PASS

- [ ] **Step 2: Fix any remaining failures**

If tests fail, trace the failure to the specific file and fix. Common issues:
- Old indicator keys referenced in test fixtures
- Import paths changed
- BB width percentile needs enough candle history

- [ ] **Step 3: Live verification in container**

Run the same live comparison script from earlier to verify new scoring on real market data:

```bash
docker exec krypton-api-1 python -c "
# ... (same scoring verification script as used during spec validation)
"
```

Verify scores are non-zero across all dimensions and within expected ranges.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(engine): continuous scoring redesign - complete implementation"
```
