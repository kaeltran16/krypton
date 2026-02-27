# Backend Plan C: Signal Engine (Phases 4-5, Tasks 8-11)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the signal engine — traditional TA indicators (pure pandas), order flow scoring, signal combiner, LLM prompt system, and OpenRouter client.

**Architecture:** Two scoring layers. Layer 1 (traditional): computes technical indicators and order flow scores, combines them with configurable weights. Layer 2 (LLM): optionally calls OpenRouter for a second opinion, adjusts the final score. ATR-based level calculation with optional LLM override.

**Note for Plan D:** This plan provides scoring and level calculation but does not determine signal direction (LONG/SHORT). Plan D must map the final score to a direction (e.g., positive = LONG, negative = SHORT) and pass config weights from `Settings` to `compute_preliminary_score`.

**Tech Stack:** Python 3.11, pandas, numpy, httpx, Pydantic, pytest

**Depends on:** Plan A (project structure, config, Pydantic models)
**Unlocks:** Plan D (integration wiring)

---

## Phase 4: Signal Engine — Traditional Layer

### Task 8: Technical analysis indicators (pure pandas — no third-party TA library)

**Files:**
- Create: `backend/app/engine/__init__.py`
- Create: `backend/app/engine/traditional.py`
- Create: `backend/tests/engine/__init__.py`
- Test: `backend/tests/engine/test_traditional.py`
- Modify: `backend/requirements.txt`

**Step 0: Add dependencies and create packages**

Add pandas and numpy to `backend/requirements.txt`:

```
pandas==3.0.1
numpy==2.4.2
```

Create package `__init__.py` files:

```bash
mkdir -p backend/app/engine backend/tests/engine
touch backend/app/engine/__init__.py backend/tests/engine/__init__.py
```

**Step 1: Write the failing test**

```python
# backend/tests/engine/test_traditional.py
import pandas as pd
import pytest

from app.engine.traditional import compute_technical_score, compute_order_flow_score


@pytest.fixture
def sample_candles():
    """50 candles of synthetic BTC data with an uptrend."""
    base = 67000
    data = []
    for i in range(50):
        o = base + i * 10
        h = o + 50
        l = o - 30
        c = o + 20
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": 100 + i})
    return pd.DataFrame(data)


@pytest.fixture
def sample_candles_downtrend():
    """50 candles of synthetic BTC data with a downtrend."""
    base = 70000
    data = []
    for i in range(50):
        o = base - i * 10
        h = o + 30
        l = o - 50
        c = o - 20
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": 100 + i})
    return pd.DataFrame(data)


def test_technical_score_returns_bounded_value(sample_candles):
    """Score must be between -100 and +100."""
    result = compute_technical_score(sample_candles)
    assert -100 <= result["score"] <= 100


def test_technical_score_uptrend_is_positive(sample_candles):
    """Uptrend should produce positive score."""
    result = compute_technical_score(sample_candles)
    assert result["score"] > 0


def test_technical_score_downtrend_is_negative(sample_candles_downtrend):
    """Downtrend should produce negative score."""
    result = compute_technical_score(sample_candles_downtrend)
    assert result["score"] < 0


def test_technical_score_includes_indicators(sample_candles):
    """Result should include individual indicator values."""
    result = compute_technical_score(sample_candles)
    assert "rsi" in result["indicators"]
    assert "macd" in result["indicators"]
    assert "ema_9" in result["indicators"]
    assert "atr" in result["indicators"]


def test_order_flow_score_returns_bounded_value():
    """Order flow score must be between -100 and +100."""
    metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 0.02,
        "long_short_ratio": 1.2,
    }
    result = compute_order_flow_score(metrics)
    assert -100 <= result["score"] <= 100


def test_order_flow_high_long_ratio_is_cautious():
    """Very high long/short ratio suggests crowded long — should dampen score."""
    metrics = {
        "funding_rate": 0.001,
        "open_interest_change_pct": 0.01,
        "long_short_ratio": 3.0,
    }
    result = compute_order_flow_score(metrics)
    assert result["score"] < 0


def test_order_flow_missing_keys_uses_defaults():
    """Missing optional keys should not crash — use safe defaults."""
    metrics = {"long_short_ratio": 1.0}
    result = compute_order_flow_score(metrics)
    assert -100 <= result["score"] <= 100
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/engine/test_traditional.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement traditional.py**

Uses pure pandas for all indicator calculations — no third-party TA library needed.

```python
# backend/app/engine/traditional.py
import numpy as np
import pandas as pd


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


def _macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = _ema(series, 12)
    ema26 = _ema(series, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def compute_technical_score(candles: pd.DataFrame) -> dict:
    """
    Compute technical analysis score from OHLCV candle data.
    Returns dict with 'score' (-100 to +100) and 'indicators' dict.
    Requires at least 50 candles for reliable indicators.
    """
    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]

    df["ema_9"] = _ema(df["close"], 9)
    df["ema_21"] = _ema(df["close"], 21)
    df["ema_50"] = _ema(df["close"], 50)

    macd_line, macd_signal, macd_hist = _macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    df["rsi"] = _rsi(df["close"], 14)

    sma_20 = df["close"].rolling(20).mean()
    std_20 = df["close"].rolling(20).std()
    df["bb_upper"] = sma_20 + 2 * std_20
    df["bb_lower"] = sma_20 - 2 * std_20

    df["atr"] = _atr(df["high"], df["low"], df["close"], 14)

    last = df.iloc[-1]
    score = 0.0

    # EMA trend (max +/- 30)
    if last["ema_9"] > last["ema_21"] > last["ema_50"]:
        score += 30
    elif last["ema_9"] < last["ema_21"] < last["ema_50"]:
        score -= 30
    else:
        ema_diff = (last["ema_9"] - last["ema_21"]) / last["close"] * 1000
        score += max(min(ema_diff * 10, 15), -15)

    # MACD (max +/- 25)
    if last["macd_hist"] > 0:
        score += min(abs(last["macd_hist"]) / last["close"] * 10000, 25)
    else:
        score -= min(abs(last["macd_hist"]) / last["close"] * 10000, 25)

    # RSI (max +/- 25)
    rsi = last["rsi"]
    if rsi < 30:
        score += 25
    elif rsi < 40:
        score += 10
    elif rsi > 70:
        score -= 25
    elif rsi > 60:
        score -= 10

    # Bollinger Band position (max +/- 20)
    bb_range = last["bb_upper"] - last["bb_lower"]
    if bb_range > 0:
        bb_pos = (last["close"] - last["bb_lower"]) / bb_range
        if bb_pos < 0.2:
            score += 20
        elif bb_pos > 0.8:
            score -= 20

    score = max(min(round(score), 100), -100)

    indicators = {
        "ema_9": float(last["ema_9"]),
        "ema_21": float(last["ema_21"]),
        "ema_50": float(last["ema_50"]) if pd.notna(last["ema_50"]) else None,
        "macd": float(last["macd"]),
        "macd_signal": float(last["macd_signal"]),
        "macd_hist": float(last["macd_hist"]),
        "rsi": float(last["rsi"]),
        "bb_upper": float(last["bb_upper"]),
        "bb_lower": float(last["bb_lower"]),
        "atr": float(last["atr"]),
    }

    return {"score": score, "indicators": indicators}


def compute_order_flow_score(metrics: dict) -> dict:
    """
    Compute order flow score from funding rate, OI changes, and L/S ratio.
    Returns dict with 'score' (-100 to +100) and 'details' dict.
    All keys are optional with safe defaults.
    """
    score = 0.0

    # funding rate analysis (max +/- 35)
    funding = metrics.get("funding_rate", 0.0)
    if funding > 0.0005:
        score -= 35
    elif funding > 0.0001:
        score -= 15
    elif funding < -0.0005:
        score += 35
    elif funding < -0.0001:
        score += 15

    # open interest change (max +/- 15)
    oi_change = metrics.get("open_interest_change_pct", 0.0)
    if oi_change > 0.05:
        score += 15
    elif oi_change < -0.05:
        score -= 15

    # long/short ratio (max +/- 35)
    ls = metrics.get("long_short_ratio", 1.0)
    if ls > 2.0:
        score -= 35
    elif ls > 1.5:
        score -= 15
    elif ls < 0.5:
        score += 35
    elif ls < 0.7:
        score += 15

    score = max(min(round(score), 100), -100)

    return {"score": score, "details": metrics}
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/engine/test_traditional.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/engine/__init__.py backend/app/engine/traditional.py backend/tests/engine/__init__.py backend/tests/engine/test_traditional.py
git commit -m "feat: add technical analysis and order flow scoring (pure pandas)"
```

---

### Task 9: Signal combiner and pydantic models

**Files:**
- Create: `backend/app/engine/models.py`
- Create: `backend/app/engine/combiner.py`
- Test: `backend/tests/engine/test_combiner.py`

**Step 1: Write the failing test**

```python
# backend/tests/engine/test_combiner.py
from app.engine.models import LLMResponse
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels


def test_preliminary_score_weighted():
    """Preliminary score is 60% technical + 40% order flow."""
    result = compute_preliminary_score(technical_score=80, order_flow_score=50)
    expected = round(80 * 0.60 + 50 * 0.40)
    assert result == expected


def test_final_score_with_confirm():
    """LLM confirm should boost the score."""
    llm = LLMResponse(opinion="confirm", confidence="HIGH", explanation="Looks good", levels=None)
    final = compute_final_score(preliminary_score=60, llm_response=llm)
    assert final > 60


def test_final_score_with_caution():
    """LLM caution should dampen the score."""
    llm = LLMResponse(opinion="caution", confidence="HIGH", explanation="Be careful", levels=None)
    final = compute_final_score(preliminary_score=60, llm_response=llm)
    assert final < 60


def test_final_score_with_contradict():
    """LLM contradict should cap positive score at 40."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="No way", levels=None)
    final = compute_final_score(preliminary_score=80, llm_response=llm)
    assert final <= 40


def test_final_score_with_contradict_negative():
    """LLM contradict should cap negative score at -40."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Not that bad", levels=None)
    final = compute_final_score(preliminary_score=-80, llm_response=llm)
    assert final >= -40


def test_final_score_without_llm():
    """No LLM response = use preliminary score as-is."""
    final = compute_final_score(preliminary_score=65, llm_response=None)
    assert final == 65


def test_final_score_bounded():
    """Final score must stay within -100 to +100."""
    llm = LLMResponse(opinion="confirm", confidence="HIGH", explanation="Max boost", levels=None)
    final = compute_final_score(preliminary_score=95, llm_response=llm)
    assert -100 <= final <= 100


def test_calculate_levels_from_atr():
    """ATR-based levels: SL at 1.5x ATR, TP1 at 2x, TP2 at 3x."""
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0, llm_levels=None
    )
    assert levels["entry"] == 67000.0
    assert levels["stop_loss"] == 67000.0 - 1.5 * 200.0
    assert levels["take_profit_1"] == 67000.0 + 2.0 * 200.0
    assert levels["take_profit_2"] == 67000.0 + 3.0 * 200.0


def test_calculate_levels_short():
    """Short direction flips SL/TP."""
    levels = calculate_levels(
        direction="SHORT", current_price=67000.0, atr=200.0, llm_levels=None
    )
    assert levels["stop_loss"] == 67000.0 + 1.5 * 200.0
    assert levels["take_profit_1"] == 67000.0 - 2.0 * 200.0


def test_calculate_levels_rejects_invalid_llm_levels():
    """LLM levels with SL above entry for LONG should fall back to ATR."""
    bad_levels = {
        "entry": 67000.0,
        "stop_loss": 68000.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0, llm_levels=bad_levels
    )
    assert levels["stop_loss"] < levels["entry"]
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/engine/test_combiner.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement models.py**

```python
# backend/app/engine/models.py
from typing import Literal

from pydantic import BaseModel

Opinion = Literal["confirm", "caution", "contradict"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
Direction = Literal["LONG", "SHORT"]


class LLMLevels(BaseModel):
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float


class LLMResponse(BaseModel):
    opinion: Opinion
    confidence: Confidence
    explanation: str
    levels: LLMLevels | None = None


class SignalResult(BaseModel):
    pair: str
    timeframe: str
    direction: Direction
    final_score: int
    traditional_score: int
    llm_opinion: Opinion | None = None
    llm_confidence: Confidence | None = None
    explanation: str | None = None
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    raw_indicators: dict
```

**Step 4: Implement combiner.py**

```python
# backend/app/engine/combiner.py
from app.engine.models import LLMResponse

CONFIDENCE_MULTIPLIER = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}


def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    tech_weight: float = 0.60,
    flow_weight: float = 0.40,
) -> int:
    return round(technical_score * tech_weight + order_flow_score * flow_weight)


def compute_final_score(
    preliminary_score: int,
    llm_response: LLMResponse | None,
) -> int:
    if llm_response is None:
        return preliminary_score

    multiplier = CONFIDENCE_MULTIPLIER.get(llm_response.confidence, 0.5)

    if llm_response.opinion == "confirm":
        adjustment = 20 * multiplier
        final = preliminary_score + adjustment
    elif llm_response.opinion == "caution":
        adjustment = 15 * multiplier
        final = preliminary_score - adjustment
    elif llm_response.opinion == "contradict":
        final = min(preliminary_score, 40)
        if preliminary_score < 0:
            final = max(preliminary_score, -40)
    else:
        final = preliminary_score

    return max(min(round(final), 100), -100)


def _validate_llm_levels(direction: str, levels: dict) -> bool:
    """Sanity-check that LLM levels make directional sense."""
    if direction == "LONG":
        return levels["stop_loss"] < levels["entry"] < levels["take_profit_1"] < levels["take_profit_2"]
    return levels["stop_loss"] > levels["entry"] > levels["take_profit_1"] > levels["take_profit_2"]


def calculate_levels(
    direction: str,
    current_price: float,
    atr: float,
    llm_levels: dict | None = None,
) -> dict:
    if llm_levels and _validate_llm_levels(direction, llm_levels):
        return llm_levels

    if direction == "LONG":
        return {
            "entry": current_price,
            "stop_loss": current_price - 1.5 * atr,
            "take_profit_1": current_price + 2.0 * atr,
            "take_profit_2": current_price + 3.0 * atr,
        }
    else:
        return {
            "entry": current_price,
            "stop_loss": current_price + 1.5 * atr,
            "take_profit_1": current_price - 2.0 * atr,
            "take_profit_2": current_price - 3.0 * atr,
        }
```

**Step 5: Run tests**

```bash
cd backend && python -m pytest tests/engine/test_combiner.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add backend/app/engine/models.py backend/app/engine/combiner.py backend/tests/engine/test_combiner.py
git commit -m "feat: add signal combiner with preliminary/final score and level calculation"
```

---

## Phase 5: Signal Engine — LLM Layer

### Task 10: External prompt template loader

**Files:**
- Create: `backend/app/engine/llm.py` (partial — prompt loading only)
- Create: `backend/app/prompts/signal_analysis.txt`
- Test: `backend/tests/engine/test_llm.py`

**Step 1: Write the failing test**

```python
# backend/tests/engine/test_llm.py
import pytest
from pathlib import Path

from app.engine.llm import load_prompt_template, render_prompt


@pytest.fixture
def prompt_file(tmp_path):
    template = """Analyze the following crypto futures data for {pair} on {timeframe} timeframe.

Technical Indicators:
{indicators}

Order Flow:
{order_flow}

Preliminary Score: {preliminary_score} ({direction})

Recent Candles (last 20):
{candles}

Respond in JSON:
{{"opinion": "confirm|caution|contradict", "confidence": "HIGH|MEDIUM|LOW", "explanation": "...", "levels": {{"entry": 0, "stop_loss": 0, "take_profit_1": 0, "take_profit_2": 0}}}}"""
    f = tmp_path / "signal_analysis.txt"
    f.write_text(template)
    return f


def test_load_prompt_template(prompt_file):
    """Load a prompt template from file."""
    template = load_prompt_template(prompt_file)
    assert "{pair}" in template
    assert "{indicators}" in template


def test_render_prompt(prompt_file):
    """Render prompt with placeholder substitution."""
    template = load_prompt_template(prompt_file)
    rendered = render_prompt(
        template=template,
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        indicators="RSI: 32, EMA9: 67100",
        order_flow="Funding: 0.0001, L/S: 1.2",
        preliminary_score="72",
        direction="LONG",
        candles="[candle data here]",
    )
    assert "BTC-USDT-SWAP" in rendered
    assert "RSI: 32" in rendered
    assert "{pair}" not in rendered
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/engine/test_llm.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement prompt loading in llm.py**

```python
# backend/app/engine/llm.py
import json
import logging
from pathlib import Path

import httpx

from app.engine.models import LLMResponse, LLMLevels

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_prompt_template(path: Path) -> str:
    return path.read_text()


def render_prompt(template: str, **kwargs) -> str:
    return template.format(**kwargs)


async def call_openrouter(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 30,
) -> LLMResponse | None:
    """Call OpenRouter API and parse response into LLMResponse."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1000,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        return parse_llm_response(content)
    except httpx.TimeoutException:
        logger.warning("OpenRouter request timed out")
        return None
    except Exception as e:
        logger.error(f"OpenRouter call failed: {e}")
        return None


def parse_llm_response(content: str) -> LLMResponse | None:
    """Parse LLM text response into structured LLMResponse."""
    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        data = json.loads(text)

        levels = None
        if "levels" in data and data["levels"]:
            levels = LLMLevels(**data["levels"])

        return LLMResponse(
            opinion=data["opinion"],
            confidence=data["confidence"],
            explanation=data["explanation"],
            levels=levels,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return None
```

**Step 4: Create the default prompt template**

```
# backend/app/prompts/signal_analysis.txt
You are a crypto futures trading analyst. Analyze the following data for {pair} on the {timeframe} timeframe.

## Technical Indicators
{indicators}

## Order Flow Metrics
{order_flow}

## Current Assessment
Preliminary Score: {preliminary_score} (Direction: {direction})

## Recent Price Action (last 20 candles)
{candles}

## Instructions
Based on the data above, provide your analysis as JSON with exactly these fields:
- "opinion": one of "confirm", "caution", or "contradict"
  - "confirm" = the setup looks strong, traditional analysis is correct
  - "caution" = the setup has risks, some warning signs
  - "contradict" = the setup is misleading, likely to fail
- "confidence": one of "HIGH", "MEDIUM", "LOW"
- "explanation": 2-3 sentence human-readable analysis explaining your reasoning
- "levels": object with "entry", "stop_loss", "take_profit_1", "take_profit_2" as numbers

Respond ONLY with the JSON object, no other text.
```

**Step 5: Run tests**

```bash
cd backend && python -m pytest tests/engine/test_llm.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add backend/app/engine/llm.py backend/app/prompts/signal_analysis.txt backend/tests/engine/test_llm.py
git commit -m "feat: add LLM prompt template system and OpenRouter client"
```

---

### Task 11: LLM response parsing tests

**Files:**
- Modify: `backend/tests/engine/test_llm.py`

**Step 1: Add parsing and async client tests**

Append to `backend/tests/engine/test_llm.py`:

```python
from unittest.mock import AsyncMock, patch

import httpx

from app.engine.llm import parse_llm_response, call_openrouter


def test_parse_llm_response_valid_json():
    content = '{"opinion": "confirm", "confidence": "HIGH", "explanation": "Strong setup.", "levels": {"entry": 67420, "stop_loss": 66890, "take_profit_1": 67950, "take_profit_2": 68480}}'
    result = parse_llm_response(content)
    assert result is not None
    assert result.opinion == "confirm"
    assert result.levels.entry == 67420


def test_parse_llm_response_with_code_fences():
    content = '```json\n{"opinion": "caution", "confidence": "MEDIUM", "explanation": "Watch out.", "levels": null}\n```'
    result = parse_llm_response(content)
    assert result is not None
    assert result.opinion == "caution"
    assert result.levels is None


def test_parse_llm_response_invalid():
    result = parse_llm_response("This is not JSON at all")
    assert result is None


def test_parse_llm_response_missing_fields():
    content = '{"opinion": "confirm"}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_invalid_opinion():
    """Invalid opinion value should be rejected by Literal validation."""
    content = '{"opinion": "agree", "confidence": "HIGH", "explanation": "Strong."}'
    result = parse_llm_response(content)
    assert result is None


async def test_call_openrouter_success():
    """Successful API call returns parsed LLMResponse."""
    mock_response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"opinion": "confirm", "confidence": "HIGH", "explanation": "Looks good.", "levels": null}'
                    }
                }
            ]
        },
    )
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is not None
        assert result.opinion == "confirm"


async def test_call_openrouter_timeout():
    """Timeout returns None gracefully."""
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is None


async def test_call_openrouter_api_error():
    """HTTP error returns None gracefully."""
    mock_response = httpx.Response(500, text="Internal Server Error")
    mock_response.request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is None
```

**Step 2: Run tests**

```bash
cd backend && python -m pytest tests/engine/test_llm.py -v
```

Expected: ALL PASS

**Step 3: Commit**

```bash
git add backend/tests/engine/test_llm.py
git commit -m "test: add LLM response parsing edge case tests"
```
