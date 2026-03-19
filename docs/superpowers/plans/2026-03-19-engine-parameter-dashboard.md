# Engine Parameter Dashboard & Backtest Optimization UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose all engine parameters to the frontend as a read-only dashboard, capture parameter snapshots on each signal, and build a backtest-driven optimization UI with diff-based apply flow.

**Architecture:** Three Alembic migrations add columns to existing tables. A centralized `constants.py` module replaces scattered hardcoded values. A new `engine.py` API router serves parameter reads and the apply endpoint. The frontend refactors MorePage into sub-tabs and adds a new Engine feature slice with Zustand store.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, React 19, TypeScript, Zustand, Tailwind CSS v3

**Spec:** `docs/superpowers/specs/2026-03-19-engine-parameter-dashboard-design.md`

---

### Task 1: Alembic Migrations

Add three migrations for the new/modified columns across `signals`, `pipeline_settings`, and `backtest_runs` tables.

**Files:**
- Create: `backend/app/db/migrations/versions/<auto>_engine_snapshot_column.py`
- Create: `backend/app/db/migrations/versions/<auto>_pipeline_settings_overrides.py`
- Create: `backend/app/db/migrations/versions/<auto>_backtest_parameter_overrides.py`
- Modify: `backend/app/db/models.py:45-85` (Signal model — add `engine_snapshot`)
- Modify: `backend/app/db/models.py:149-185` (PipelineSettings model — add override columns)
- Modify: `backend/app/db/models.py:206-223` (BacktestRun model — add `parameter_overrides`)

- [ ] **Step 1: Add `engine_snapshot` column to Signal model**

In `backend/app/db/models.py`, add to the Signal class (after the existing JSONB columns around line 75):

```python
engine_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 2: Add override columns to PipelineSettings model**

In `backend/app/db/models.py`, add to PipelineSettings class (after `mean_rev_blend_ratio` around line 178):

```python
# nullable overrides — None means "use env default"
traditional_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
flow_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
onchain_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
pattern_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
ml_blend_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
ml_confidence_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
llm_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
llm_factor_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
llm_factor_total_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
confluence_max_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: Add `parameter_overrides` column to BacktestRun model**

In `backend/app/db/models.py`, add to BacktestRun class (after `results` column around line 222):

```python
parameter_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 4: Generate and run migrations**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add engine_snapshot to signals"
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add override columns to pipeline_settings"
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add parameter_overrides to backtest_runs"
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```

Note: If autogenerate produces a single migration covering all three changes, that is fine. The key is that all columns are created.

- [ ] **Step 5: Verify migrations applied**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python3 -c "
from sqlalchemy import inspect
from app.db.database import Database
from app.config import Settings
import asyncio

async def check():
    db = Database(Settings().database_url)
    async with db.session_factory() as s:
        result = await s.execute(__import__('sqlalchemy').text(
            \"SELECT column_name FROM information_schema.columns WHERE table_name='signals' AND column_name='engine_snapshot'\"
        ))
        print('engine_snapshot:', result.fetchone())
        result = await s.execute(__import__('sqlalchemy').text(
            \"SELECT column_name FROM information_schema.columns WHERE table_name='pipeline_settings' AND column_name='traditional_weight'\"
        ))
        print('traditional_weight:', result.fetchone())
        result = await s.execute(__import__('sqlalchemy').text(
            \"SELECT column_name FROM information_schema.columns WHERE table_name='backtest_runs' AND column_name='parameter_overrides'\"
        ))
        print('parameter_overrides:', result.fetchone())
asyncio.run(check())
"
```

Expected: all three column names printed (not None).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/
git commit -m "feat(db): add engine_snapshot, pipeline overrides, and backtest parameter_overrides columns"
```

---

### Task 2: Centralized Engine Constants Module

Extract all hardcoded engine constants from scattered modules into a single `constants.py` that provides a `get_engine_constants()` function.

**Files:**
- Create: `backend/app/engine/constants.py`
- Modify: `backend/app/engine/traditional.py:196-202` (import from constants)
- Modify: `backend/app/engine/combiner.py:88-94` (import from constants)
- Modify: `backend/app/engine/performance_tracker.py:15-30` (import from constants)

- [ ] **Step 1: Create `backend/app/engine/constants.py`**

```python
"""Centralized engine constants registry.

All hardcoded scoring/scaling constants live here. Engine modules
import what they need; the API reads the full tree via
get_engine_constants().
"""

# -- Technical scoring --
INDICATOR_PERIODS = {
    "adx": 14,
    "rsi": 14,
    "sma": 20,
    "bb_std": 2,
    "ema_spans": [9, 21, 50],
    "obv_slope_window": 10,
    "bb_width_percentile_window": 50,
}

SIGMOID_PARAMS = {
    "trend_strength_center": 20,
    "trend_strength_steepness": 0.25,
    "vol_expansion_center": 50,
    "vol_expansion_steepness": 0.08,
    "trend_score_steepness": 0.30,
    "obv_slope_steepness": 4,
    "volume_ratio_steepness": 3.0,
}

# -- Order flow scoring --
ORDER_FLOW = {
    "max_scores": {"funding": 35, "oi": 20, "ls_ratio": 35},
    "sigmoid_steepnesses": {"funding": 8000, "oi": 65, "ls_ratio": 6},
    "trending_floor": 0.3,
    "recent_window": 3,
    "baseline_window": 7,
    "roc_threshold": 0.0005,
    "roc_steepness": 8000,
    "ls_roc_scale": 0.003,
}

# -- On-chain scoring --
ONCHAIN_PROFILES = {
    "btc": {
        "netflow_normalization": 3000,
        "whale_baseline": 3,
        "max_scores": {
            "netflow": 35, "whale": 20, "addresses": 15,
            "nupl": 15, "hashrate": 15,
        },
    },
    "eth": {
        "netflow_normalization": 50000,
        "whale_baseline": 5,
        "max_scores": {
            "netflow": 35, "whale": 20, "addresses": 15,
            "staking": 15, "gas": 15,
        },
    },
}

# -- Level calculation / ATR scaling --
LEVEL_DEFAULTS = {
    "atr_defaults": {"sl": 1.5, "tp1": 2.0, "tp2": 3.0},
    "atr_guardrails": {
        "sl_bounds": [0.5, 3.0],
        "tp1_min": 1.0,
        "tp2_max": 8.0,
        "rr_floor": 1.0,
    },
    "phase1_scaling": {
        "strength_min": 0.8,
        "sl_strength_max": 1.2,
        "tp_strength_max": 1.4,
        "vol_factor_min": 0.75,
        "vol_factor_max": 1.25,
    },
}

# -- Pattern strengths --
PATTERN_STRENGTHS = {
    "bullish_engulfing": 15,
    "bearish_engulfing": 15,
    "morning_star": 15,
    "evening_star": 15,
    "three_white_soldiers": 15,
    "three_black_crows": 15,
    "marubozu": 13,
    "hammer": 12,
    "piercing_line": 12,
    "dark_cloud_cover": 12,
    "inverted_hammer": 10,
    "doji": 8,
    "spinning_top": 5,
}

# -- Performance tracker --
PERFORMANCE_TRACKER = {
    "optimization_params": {
        "min_signals": 40,
        "window_size": 100,
        "trigger_interval": 10,
    },
    "guardrails": {
        "sl_range": [0.8, 2.5],
        "tp1_range": [1.0, 4.0],
        "tp2_range": [2.0, 6.0],
        "max_sl_adj": 0.3,
        "max_tp_adj": 0.5,
    },
}


def get_engine_constants() -> dict:
    """Return all hardcoded engine constants as a nested dict.

    Used by GET /api/engine/parameters to serve the full parameter tree.
    Each leaf is wrapped as {"value": ..., "source": "hardcoded"}.
    """

    def _wrap(d):
        """Recursively wrap leaf values with source annotation.

        Dicts are treated as branches and recursed into.
        Non-dict values (int, float, list, str) become leaves.
        """
        if isinstance(d, dict):
            return {k: _wrap(v) for k, v in d.items()}
        return {"value": d, "source": "hardcoded"}

    return {
        "technical": {
            "indicator_periods": _wrap(INDICATOR_PERIODS),
            "sigmoid_params": _wrap(SIGMOID_PARAMS),
        },
        "order_flow": {
            "max_scores": _wrap(ORDER_FLOW["max_scores"]),
            "sigmoid_steepnesses": _wrap(ORDER_FLOW["sigmoid_steepnesses"]),
            "regime_params": _wrap({
                "trending_floor": ORDER_FLOW["trending_floor"],
                "roc_threshold": ORDER_FLOW["roc_threshold"],
                "roc_steepness": ORDER_FLOW["roc_steepness"],
                "ls_roc_scale": ORDER_FLOW["ls_roc_scale"],
                "recent_window": ORDER_FLOW["recent_window"],
                "baseline_window": ORDER_FLOW["baseline_window"],
            }),
        },
        "onchain": {
            "btc_profile": _wrap(ONCHAIN_PROFILES["btc"]),
            "eth_profile": _wrap(ONCHAIN_PROFILES["eth"]),
        },
        "levels": {
            "atr_defaults": _wrap(LEVEL_DEFAULTS["atr_defaults"]),
            "atr_guardrails": _wrap(LEVEL_DEFAULTS["atr_guardrails"]),
            "phase1_scaling": _wrap(LEVEL_DEFAULTS["phase1_scaling"]),
        },
        "patterns": {
            "strengths": _wrap(PATTERN_STRENGTHS),
        },
        "performance_tracker": {
            "optimization_params": _wrap(PERFORMANCE_TRACKER["optimization_params"]),
            "guardrails": _wrap(PERFORMANCE_TRACKER["guardrails"]),
        },
    }
```

- [ ] **Step 2: Update `traditional.py` to import from constants**

Replace module-level constants at lines 196-202 with imports:

```python
from app.engine.constants import ORDER_FLOW

TRENDING_FLOOR = ORDER_FLOW["trending_floor"]
RECENT_WINDOW = ORDER_FLOW["recent_window"]
BASELINE_WINDOW = ORDER_FLOW["baseline_window"]
TOTAL_SNAPSHOTS = RECENT_WINDOW + BASELINE_WINDOW
ROC_THRESHOLD = ORDER_FLOW["roc_threshold"]
ROC_STEEPNESS = ORDER_FLOW["roc_steepness"]
LS_ROC_SCALE = ORDER_FLOW["ls_roc_scale"]
```

- [ ] **Step 3: Update `combiner.py` to import from constants**

Replace module-level constants at lines 88-94 with imports:

```python
from app.engine.constants import LEVEL_DEFAULTS

_p1 = LEVEL_DEFAULTS["phase1_scaling"]
STRENGTH_MIN = _p1["strength_min"]
SL_STRENGTH_MAX = _p1["sl_strength_max"]
TP_STRENGTH_MAX = _p1["tp_strength_max"]
VOL_FACTOR_MIN = _p1["vol_factor_min"]
VOL_FACTOR_MAX = _p1["vol_factor_max"]
```

- [ ] **Step 4: Update `performance_tracker.py` to import from constants**

Replace module-level constants at lines 15-30 with imports:

```python
from app.engine.constants import LEVEL_DEFAULTS, PERFORMANCE_TRACKER

_atr = LEVEL_DEFAULTS["atr_defaults"]
DEFAULT_SL = _atr["sl"]
DEFAULT_TP1 = _atr["tp1"]
DEFAULT_TP2 = _atr["tp2"]

_opt = PERFORMANCE_TRACKER["optimization_params"]
MIN_SIGNALS = _opt["min_signals"]
WINDOW_SIZE = _opt["window_size"]
TRIGGER_INTERVAL = _opt["trigger_interval"]

_guard = PERFORMANCE_TRACKER["guardrails"]
SL_RANGE = tuple(_guard["sl_range"])
TP1_RANGE = tuple(_guard["tp1_range"])
TP2_RANGE = tuple(_guard["tp2_range"])
MAX_SL_ADJ = _guard["max_sl_adj"]
MAX_TP_ADJ = _guard["max_tp_adj"]
```

- [ ] **Step 5: Run existing tests to confirm no regressions**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/constants.py backend/app/engine/traditional.py backend/app/engine/combiner.py backend/app/engine/performance_tracker.py
git commit -m "refactor(engine): centralize hardcoded constants into constants.py"
```

---

### Task 3: Config Resolution — Promote Env-Only Params to DB-Overridable

Extend the startup PipelineSettings loading to apply nullable DB overrides on top of env-based settings.

**Files:**
- Modify: `backend/app/main.py:946-974` (lifespan — PipelineSettings loading)
- Test: `backend/tests/test_config_resolution.py` (new)

- [ ] **Step 1: Write test for config resolution**

Create `backend/tests/test_config_resolution.py`:

```python
"""Test that nullable PipelineSettings columns override env-based Settings."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace


def _make_ps(**overrides):
    """Create a mock PipelineSettings row with defaults + overrides."""
    defaults = {
        "pairs": ["BTC-USDT-SWAP"],
        "timeframes": ["15m", "1h"],
        "signal_threshold": 40,
        "onchain_enabled": True,
        "news_alerts_enabled": True,
        "news_context_window": 30,
        "mean_rev_rsi_steepness": 0.25,
        "mean_rev_bb_pos_steepness": 10.0,
        "squeeze_steepness": 0.10,
        "mean_rev_blend_ratio": 0.6,
        # nullable overrides — None by default
        "traditional_weight": None,
        "flow_weight": None,
        "onchain_weight": None,
        "pattern_weight": None,
        "ml_blend_weight": None,
        "ml_confidence_threshold": None,
        "llm_threshold": None,
        "llm_factor_weights": None,
        "llm_factor_total_cap": None,
        "confluence_max_score": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_none_override_keeps_env_default():
    """When DB column is None, env value should remain untouched."""
    from app.main import _apply_pipeline_overrides

    settings = MagicMock()
    settings.engine_traditional_weight = 0.40
    settings.engine_flow_weight = 0.22

    ps = _make_ps()  # all overrides None
    _apply_pipeline_overrides(settings, ps)

    assert settings.engine_traditional_weight == 0.40
    assert settings.engine_flow_weight == 0.22


def test_non_none_override_applies():
    """When DB column has a value, it should override the env setting."""
    from app.main import _apply_pipeline_overrides

    settings = MagicMock()
    settings.engine_traditional_weight = 0.40
    settings.engine_llm_threshold = 20
    settings.llm_factor_total_cap = 35.0

    ps = _make_ps(traditional_weight=0.50, llm_threshold=30, llm_factor_total_cap=40.0)
    _apply_pipeline_overrides(settings, ps)

    assert settings.engine_traditional_weight == 0.50
    assert settings.engine_llm_threshold == 30
    assert settings.llm_factor_total_cap == 40.0


@pytest.mark.parametrize("db_col,settings_field,value", [
    ("traditional_weight", "engine_traditional_weight", 0.50),
    ("flow_weight", "engine_flow_weight", 0.30),
    ("onchain_weight", "engine_onchain_weight", 0.20),
    ("pattern_weight", "engine_pattern_weight", 0.10),
    ("ml_blend_weight", "engine_ml_weight", 0.35),
    ("ml_confidence_threshold", "ml_confidence_threshold", 0.80),
    ("llm_threshold", "engine_llm_threshold", 30),
    ("llm_factor_weights", "llm_factor_weights", {"support_proximity": 8.0}),
    ("llm_factor_total_cap", "llm_factor_total_cap", 40.0),
    ("confluence_max_score", "engine_confluence_max_score", 20),
])
def test_each_override_mapping(db_col, settings_field, value):
    """Verify every entry in _OVERRIDE_MAP routes correctly."""
    from app.main import _apply_pipeline_overrides

    settings = MagicMock()
    setattr(settings, settings_field, "original")

    ps = _make_ps(**{db_col: value})
    _apply_pipeline_overrides(settings, ps)

    assert getattr(settings, settings_field) == value
```

- [ ] **Step 2: Run test to verify it fails**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/test_config_resolution.py -v
```

Expected: ImportError — `_apply_pipeline_overrides` does not exist yet.

- [ ] **Step 3: Implement `_apply_pipeline_overrides` and update lifespan**

In `backend/app/main.py`, add the helper function (before the `lifespan` function):

```python
# Maps nullable PipelineSettings columns → Settings field names
_OVERRIDE_MAP = {
    "traditional_weight": "engine_traditional_weight",
    "flow_weight": "engine_flow_weight",
    "onchain_weight": "engine_onchain_weight",
    "pattern_weight": "engine_pattern_weight",
    "ml_blend_weight": "engine_ml_weight",
    "ml_confidence_threshold": "ml_confidence_threshold",
    "llm_threshold": "engine_llm_threshold",
    "llm_factor_weights": "llm_factor_weights",
    "llm_factor_total_cap": "llm_factor_total_cap",
    "confluence_max_score": "engine_confluence_max_score",
}


def _apply_pipeline_overrides(settings, ps):
    """Apply non-None PipelineSettings overrides onto in-memory Settings."""
    for db_col, settings_field in _OVERRIDE_MAP.items():
        value = getattr(ps, db_col, None)
        if value is not None:
            object.__setattr__(settings, settings_field, value)
```

Then in the `lifespan` function, after the existing PipelineSettings loading block (around line 968 after `app.state.scoring_params` is set), add:

```python
                _apply_pipeline_overrides(settings, ps)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/test_config_resolution.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_config_resolution.py
git commit -m "feat(config): apply nullable PipelineSettings overrides at startup"
```

---

### Task 4: Engine Parameters API Endpoint

New `GET /api/engine/parameters` endpoint that assembles the full parameter tree.

**Files:**
- Create: `backend/app/api/engine.py`
- Modify: `backend/app/main.py:1160-1193` (register engine router)
- Test: `backend/tests/api/test_engine_params.py` (new)

- [ ] **Step 1: Write test**

Create `backend/tests/api/test_engine_params.py`:

```python
"""Test GET /api/engine/parameters endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_get_engine_parameters(client):
    resp = await client.get("/api/engine/parameters", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    # top-level categories present
    for key in ("technical", "order_flow", "onchain", "blending", "levels", "patterns", "performance_tracker"):
        assert key in data, f"Missing category: {key}"

    # check a hardcoded param
    adx = data["technical"]["indicator_periods"]["adx"]
    assert adx == {"value": 14, "source": "hardcoded"}

    # check a configurable param
    signal = data["blending"]["thresholds"]["signal"]
    assert signal["source"] == "configurable"
    assert isinstance(signal["value"], int)

    # regime_weights and learned_atr are dynamic (empty in test)
    assert "regime_weights" in data
    assert "learned_atr" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_engine_params.py -v
```

Expected: 404 (route does not exist).

- [ ] **Step 3: Create `backend/app/api/engine.py`**

```python
"""Engine parameter visibility and apply endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.auth import require_settings_api_key
from app.db.models import PipelineSettings, RegimeWeights, PerformanceTrackerRow
from app.engine.constants import get_engine_constants

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engine", tags=["engine"])


def _configurable(value):
    return {"value": value, "source": "configurable"}


@router.get("/parameters")
async def get_parameters(request: Request, _key: str = require_settings_api_key()):
    """Return the full engine parameter tree."""
    settings = request.app.state.settings
    db = request.app.state.db

    # Start with hardcoded constants
    params = get_engine_constants()

    # Add configurable mean-reversion params
    scoring = getattr(request.app.state, "scoring_params", None) or {}
    params["technical"]["mean_reversion"] = {
        "rsi_steepness": _configurable(scoring.get("mean_rev_rsi_steepness", 0.25)),
        "bb_pos_steepness": _configurable(scoring.get("mean_rev_bb_pos_steepness", 10.0)),
        "squeeze_steepness": _configurable(scoring.get("squeeze_steepness", 0.10)),
        "blend_ratio": _configurable(scoring.get("mean_rev_blend_ratio", 0.6)),
    }

    # Add blending params (configurable via PipelineSettings overrides)
    params["blending"] = {
        "source_weights": {
            "traditional": _configurable(settings.engine_traditional_weight),
            "flow": _configurable(settings.engine_flow_weight),
            "onchain": _configurable(settings.engine_onchain_weight),
            "pattern": _configurable(settings.engine_pattern_weight),
        },
        "ml_blend_weight": _configurable(settings.engine_ml_weight),
        "thresholds": {
            "signal": _configurable(settings.engine_signal_threshold),
            "llm": _configurable(settings.engine_llm_threshold),
            "ml_confidence": _configurable(settings.ml_confidence_threshold),
        },
        "llm_factor_weights": {
            k: _configurable(v)
            for k, v in settings.llm_factor_weights.items()
        },
        "llm_factor_cap": _configurable(settings.llm_factor_total_cap),
        "confluence_max_score": _configurable(settings.engine_confluence_max_score),
    }

    # Regime weights (per pair/timeframe from DB or app.state)
    regime_data = {}
    regime_weights_dict = getattr(request.app.state, "regime_weights", {})
    for (pair, tf), rw in regime_weights_dict.items():
        regime_data.setdefault(pair, {})[tf] = _regime_row_to_dict(rw)

    # If empty, also check DB
    if not regime_data:
        try:
            async with db.session_factory() as session:
                result = await session.execute(select(RegimeWeights))
                for rw in result.scalars().all():
                    regime_data.setdefault(rw.pair, {})[rw.timeframe] = _regime_row_to_dict(rw)
        except Exception:
            pass

    params["regime_weights"] = regime_data

    # Learned ATR multipliers
    learned_atr = {}
    try:
        async with db.session_factory() as session:
            result = await session.execute(select(PerformanceTrackerRow))
            for row in result.scalars().all():
                learned_atr.setdefault(row.pair, {})[row.timeframe] = {
                    "sl_atr": _configurable(row.current_sl_atr),
                    "tp1_atr": _configurable(row.current_tp1_atr),
                    "tp2_atr": _configurable(row.current_tp2_atr),
                    "last_optimized_at": row.last_optimized_at.isoformat() if row.last_optimized_at else None,
                    "signal_count": row.last_optimized_count,
                }
    except Exception:
        pass

    params["learned_atr"] = learned_atr

    return params


def _regime_row_to_dict(rw) -> dict:
    """Convert a RegimeWeights row to the API response format."""
    result = {}
    for regime in ("trending", "ranging", "volatile"):
        result[regime] = {
            "inner_caps": {
                "trend": getattr(rw, f"{regime}_trend_cap"),
                "mean_rev": getattr(rw, f"{regime}_mean_rev_cap"),
                "squeeze": getattr(rw, f"{regime}_squeeze_cap"),
                "volume": getattr(rw, f"{regime}_volume_cap"),
            },
            "outer_weights": {
                "tech": getattr(rw, f"{regime}_tech_weight"),
                "flow": getattr(rw, f"{regime}_flow_weight"),
                "onchain": getattr(rw, f"{regime}_onchain_weight"),
                "pattern": getattr(rw, f"{regime}_pattern_weight"),
            },
        }
    return result
```

- [ ] **Step 4: Register the router in `main.py`**

In `backend/app/main.py`, add after the alerts router registration (around line 1191):

```python
from app.api.engine import router as engine_router
app.include_router(engine_router)
```

- [ ] **Step 5: Update test conftest to stub required state**

In `backend/tests/conftest.py`, add to the `_test_lifespan` function (around line 22):

```python
mock_settings.engine_traditional_weight = 0.40
mock_settings.engine_flow_weight = 0.22
mock_settings.engine_onchain_weight = 0.23
mock_settings.engine_pattern_weight = 0.15
mock_settings.engine_ml_weight = 0.25
mock_settings.engine_signal_threshold = 40
mock_settings.engine_llm_threshold = 20
mock_settings.ml_confidence_threshold = 0.65
mock_settings.llm_factor_weights = {
    "support_proximity": 6.0, "resistance_proximity": 6.0,
    "level_breakout": 8.0, "htf_alignment": 7.0,
    "rsi_divergence": 7.0, "volume_divergence": 6.0,
    "macd_divergence": 6.0, "volume_exhaustion": 5.0,
    "funding_extreme": 5.0, "crowded_positioning": 5.0,
    "pattern_confirmation": 5.0, "news_catalyst": 7.0,
}
mock_settings.llm_factor_total_cap = 35.0
mock_settings.engine_confluence_max_score = 15
app.state.scoring_params = {
    "mean_rev_rsi_steepness": 0.25,
    "mean_rev_bb_pos_steepness": 10.0,
    "squeeze_steepness": 0.10,
    "mean_rev_blend_ratio": 0.6,
}
```

Also set up `app.state.db` with an async-compatible mock. The engine endpoint uses `async with db.session_factory() as session:` which requires an async context manager. The endpoint wraps DB calls in `try/except: pass`, so a mock that raises will just return empty data:

```python
from unittest.mock import MagicMock, AsyncMock

mock_db = MagicMock()
mock_session = AsyncMock()
mock_session.__aenter__ = AsyncMock(return_value=mock_session)
mock_session.__aexit__ = AsyncMock(return_value=False)
mock_session.execute = AsyncMock(side_effect=Exception("no real DB"))
mock_db.session_factory = MagicMock(return_value=mock_session)
app.state.db = mock_db
```

- [ ] **Step 6: Run test to verify it passes**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_engine_params.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/engine.py backend/app/main.py backend/tests/conftest.py backend/tests/api/test_engine_params.py
git commit -m "feat(api): add GET /api/engine/parameters endpoint"
```

---

### Task 5: Apply Endpoint

`POST /api/engine/apply` with preview/confirm modes, dot-path routing, and in-memory refresh.

**Files:**
- Modify: `backend/app/api/engine.py` (add apply endpoint)
- Test: `backend/tests/api/test_engine_apply.py` (new)

- [ ] **Step 1: Write test**

Create `backend/tests/api/test_engine_apply.py`:

```python
"""Test POST /api/engine/apply endpoint."""

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock, AsyncMock

HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_preview_returns_diff(client):
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={
            "changes": {"blending.thresholds.signal": 35},
            "confirm": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview"] is True
    assert len(data["diff"]) == 1
    assert data["diff"][0]["path"] == "blending.thresholds.signal"
    assert data["diff"][0]["current"] == 40
    assert data["diff"][0]["proposed"] == 35


@pytest.mark.asyncio
async def test_preview_is_default(client):
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={"changes": {"blending.thresholds.signal": 35}},
    )
    assert resp.status_code == 200
    assert resp.json()["preview"] is True


@pytest.mark.asyncio
async def test_empty_changes_rejected(client):
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={"changes": {}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_confirm_applies_and_updates_in_memory(app_with_db):
    """Confirm mode persists to DB and patches in-memory settings."""
    from httpx import ASGITransport, AsyncClient

    app = app_with_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/engine/apply",
            headers=HEADERS,
            json={
                "changes": {"blending.thresholds.signal": 35},
                "confirm": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is True
        assert data["diff"][0]["proposed"] == 35

        # verify in-memory update
        assert app.state.settings.engine_signal_threshold == 35


@pytest.mark.asyncio
async def test_unknown_dot_path_returns_unknown_source(client):
    """Unknown dot-paths are included in diff with source 'unknown'."""
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={
            "changes": {"nonexistent.path": 42},
            "confirm": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["diff"][0]["source"] == "unknown"
    assert data["diff"][0]["current"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_engine_apply.py -v
```

Expected: FAIL (endpoint does not exist).

- [ ] **Step 3: Implement apply endpoint**

Add to `backend/app/api/engine.py`:

```python
from pydantic import BaseModel, Field


class ApplyRequest(BaseModel):
    changes: dict[str, float | int | dict]
    confirm: bool = False


# Maps dot-paths to (settings_field, db_column) for PipelineSettings
_PIPELINE_SETTINGS_MAP = {
    "blending.source_weights.traditional": ("engine_traditional_weight", "traditional_weight"),
    "blending.source_weights.flow": ("engine_flow_weight", "flow_weight"),
    "blending.source_weights.onchain": ("engine_onchain_weight", "onchain_weight"),
    "blending.source_weights.pattern": ("engine_pattern_weight", "pattern_weight"),
    "blending.ml_blend_weight": ("engine_ml_weight", "ml_blend_weight"),
    "blending.thresholds.signal": ("engine_signal_threshold", "signal_threshold"),
    "blending.thresholds.llm": ("engine_llm_threshold", "llm_threshold"),
    "blending.thresholds.ml_confidence": ("ml_confidence_threshold", "ml_confidence_threshold"),
    "blending.llm_factor_weights": ("llm_factor_weights", "llm_factor_weights"),
    "blending.llm_factor_cap": ("llm_factor_total_cap", "llm_factor_total_cap"),
    "confluence_max_score": ("engine_confluence_max_score", "confluence_max_score"),
}

# Mean-reversion params → scoring_params key + PipelineSettings column
_SCORING_PARAMS_MAP = {
    "mean_reversion.rsi_steepness": ("mean_rev_rsi_steepness", "mean_rev_rsi_steepness"),
    "mean_reversion.bb_pos_steepness": ("mean_rev_bb_pos_steepness", "mean_rev_bb_pos_steepness"),
    "mean_reversion.squeeze_steepness": ("squeeze_steepness", "squeeze_steepness"),
    "mean_reversion.blend_ratio": ("mean_rev_blend_ratio", "mean_rev_blend_ratio"),
}


def _resolve_current_value(path: str, app) -> tuple[float | int | dict | None, str]:
    """Get the current value and source type for a dot-path."""
    settings = app.state.settings
    scoring = getattr(app.state, "scoring_params", {}) or {}

    if path in _PIPELINE_SETTINGS_MAP:
        settings_field, _ = _PIPELINE_SETTINGS_MAP[path]
        return getattr(settings, settings_field, None), "configurable"

    if path in _SCORING_PARAMS_MAP:
        scoring_key, _ = _SCORING_PARAMS_MAP[path]
        return scoring.get(scoring_key), "configurable"

    if path.startswith("regime_weights."):
        parts = path.split(".", 3)  # regime_weights.<pair>.<tf>.<col>
        if len(parts) == 4:
            _, pair, tf, col = parts
            rw = app.state.regime_weights.get((pair, tf))
            if rw:
                return getattr(rw, col, None), "configurable"
        return None, "configurable"

    if path.startswith("learned_atr."):
        parts = path.split(".", 3)
        if len(parts) == 4:
            _, pair, tf, col = parts
            tracker = getattr(app.state, "tracker", None)
            if tracker and hasattr(tracker, "_cache"):
                cached = tracker._cache.get((pair, tf))
                if cached:
                    # _cache stores tuples: (sl_atr, tp1_atr, tp2_atr)
                    _ATR_INDEX = {"current_sl_atr": 0, "current_tp1_atr": 1, "current_tp2_atr": 2}
                    idx = _ATR_INDEX.get(col)
                    if idx is not None:
                        return cached[idx], "configurable"
        return None, "configurable"

    return None, "unknown"


@router.post("/apply")
async def apply_parameters(body: ApplyRequest, request: Request, _key: str = require_settings_api_key()):
    """Preview or apply parameter changes."""
    from fastapi import HTTPException

    if not body.changes:
        raise HTTPException(400, "No changes provided")

    app = request.app

    # Build diff
    diff = []
    for path, proposed in body.changes.items():
        current, source = _resolve_current_value(path, app)
        diff.append({
            "path": path,
            "current": current,
            "proposed": proposed,
            "source": source,
        })

    if not body.confirm:
        return {"preview": True, "diff": diff}

    # Apply changes
    db = app.state.db
    settings = app.state.settings
    lock = app.state.pipeline_settings_lock

    async with lock:
        async with db.session_factory() as session:
            # Load PipelineSettings
            result = await session.execute(
                select(PipelineSettings).where(PipelineSettings.id == 1)
            )
            ps = result.scalar_one_or_none()
            if not ps:
                raise HTTPException(500, "Pipeline settings not initialized")

            for path, proposed in body.changes.items():
                if path in _PIPELINE_SETTINGS_MAP:
                    settings_field, db_col = _PIPELINE_SETTINGS_MAP[path]
                    setattr(ps, db_col, proposed)
                    object.__setattr__(settings, settings_field, proposed)

                elif path in _SCORING_PARAMS_MAP:
                    scoring_key, db_col = _SCORING_PARAMS_MAP[path]
                    setattr(ps, db_col, proposed)
                    scoring = getattr(app.state, "scoring_params", None)
                    if scoring:
                        scoring[scoring_key] = proposed

                elif path.startswith("regime_weights."):
                    parts = path.split(".", 3)
                    if len(parts) == 4:
                        _, pair, tf, col = parts
                        rw_result = await session.execute(
                            select(RegimeWeights)
                            .where(RegimeWeights.pair == pair)
                            .where(RegimeWeights.timeframe == tf)
                        )
                        rw = rw_result.scalar_one_or_none()
                        if rw:
                            setattr(rw, col, proposed)
                            # refresh in-memory after commit below

                elif path.startswith("learned_atr."):
                    parts = path.split(".", 3)
                    if len(parts) == 4:
                        _, pair, tf, col = parts
                        pt_result = await session.execute(
                            select(PerformanceTrackerRow)
                            .where(PerformanceTrackerRow.pair == pair)
                            .where(PerformanceTrackerRow.timeframe == tf)
                        )
                        pt = pt_result.scalar_one_or_none()
                        if pt:
                            setattr(pt, col, proposed)

            from datetime import datetime, timezone
            ps.updated_at = datetime.now(timezone.utc)
            await session.commit()

            # Refresh regime weights in memory
            rw_result = await session.execute(select(RegimeWeights))
            app.state.regime_weights = {}
            for rw in rw_result.scalars().all():
                session.expunge(rw)
                app.state.regime_weights[(rw.pair, rw.timeframe)] = rw

        # Refresh tracker cache
        tracker = getattr(app.state, "tracker", None)
        if tracker:
            await tracker.reload_cache()

    return {"applied": True, "diff": diff}
```

- [ ] **Step 4: Set up lock mock in conftest**

In `backend/tests/conftest.py`, add to `_test_lifespan`:

```python
app.state.pipeline_settings_lock = asyncio.Lock()
```

The `test_confirm_applies_and_updates_in_memory` test requires a real (or SQLite-backed) DB session. Create an `app_with_db` fixture in `tests/api/test_engine_apply.py` that provides a PipelineSettings-seeded database. If the existing test infrastructure doesn't support this easily, use a mock DB that returns a mutable `SimpleNamespace` from `scalar_one_or_none()` and records `commit()` calls. The key assertion is that `app.state.settings.engine_signal_threshold` is updated after the call.

- [ ] **Step 5: Run test to verify it passes**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_engine_apply.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/engine.py backend/tests/api/test_engine_apply.py backend/tests/conftest.py
git commit -m "feat(api): add POST /api/engine/apply with preview/confirm"
```

---

### Task 6: Engine Snapshot on Signal Emission

Populate `engine_snapshot` JSONB when signals are created in `run_pipeline`.

**Files:**
- Modify: `backend/app/main.py:240-662` (run_pipeline — build snapshot dict and include in signal_data)
- Test: `backend/tests/engine/test_snapshot.py` (new)

- [ ] **Step 1: Write test**

Create `backend/tests/engine/test_snapshot.py`:

```python
"""Test that build_engine_snapshot produces the expected structure."""

import pytest


def test_build_engine_snapshot_keys():
    from app.main import build_engine_snapshot

    # Minimal mock objects
    class MockSettings:
        engine_traditional_weight = 0.40
        engine_flow_weight = 0.22
        engine_onchain_weight = 0.23
        engine_pattern_weight = 0.15
        engine_ml_weight = 0.25
        engine_signal_threshold = 40
        engine_llm_threshold = 20
        ml_confidence_threshold = 0.65
        llm_factor_weights = {"support_proximity": 6.0}
        llm_factor_total_cap = 35.0
        engine_confluence_max_score = 15

    scoring_params = {
        "mean_rev_rsi_steepness": 0.25,
        "mean_rev_bb_pos_steepness": 10.0,
        "squeeze_steepness": 0.10,
        "mean_rev_blend_ratio": 0.6,
    }

    regime_mix = {"trending": 0.6, "ranging": 0.3, "volatile": 0.1}
    caps = {"trend": 38.0, "mean_rev": 22.0, "squeeze": 12.0, "volume": 28.0}
    outer = {"tech": 0.45, "flow": 0.25, "onchain": 0.18, "pattern": 0.12}
    atr = (1.5, 2.0, 3.0)

    snap = build_engine_snapshot(
        MockSettings(), scoring_params, regime_mix, caps, outer, atr, "performance_tracker"
    )

    assert snap["source_weights"]["traditional"] == 0.40
    assert snap["regime_mix"] == regime_mix
    assert snap["atr_multipliers"]["sl"] == 1.5
    assert snap["thresholds"]["signal"] == 40
    assert snap["confluence_max_score"] == 15
```

- [ ] **Step 2: Run test to verify it fails**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_snapshot.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `build_engine_snapshot` in main.py**

Add a helper function in `backend/app/main.py` (before `run_pipeline`):

```python
def build_engine_snapshot(
    settings, scoring_params, regime_mix, caps, outer, atr_tuple, atr_source
) -> dict:
    """Build the engine_snapshot dict for a signal record."""
    return {
        "source_weights": {
            "traditional": settings.engine_traditional_weight,
            "flow": settings.engine_flow_weight,
            "onchain": settings.engine_onchain_weight,
            "pattern": settings.engine_pattern_weight,
        },
        "ml_blend_weight": settings.engine_ml_weight,
        "regime_mix": regime_mix,
        "regime_caps": caps,
        "regime_outer": outer,
        "atr_multipliers": {
            "sl": atr_tuple[0],
            "tp1": atr_tuple[1],
            "tp2": atr_tuple[2],
            "source": atr_source,
        },
        "thresholds": {
            "signal": settings.engine_signal_threshold,
            "llm": settings.engine_llm_threshold,
            "ml_confidence": settings.ml_confidence_threshold,
        },
        "mean_reversion": scoring_params or {},
        "llm_factor_weights": dict(settings.llm_factor_weights),
        "llm_factor_cap": settings.llm_factor_total_cap,
        "confluence_max_score": settings.engine_confluence_max_score,
    }
```

- [ ] **Step 4: Call `build_engine_snapshot` in `run_pipeline` and include in signal_data**

In `run_pipeline` (around line 615, before `signal_data = {`), add:

```python
    # Build regime mix from indicators for the snapshot
    regime_mix = {
        "trending": tech_result["indicators"].get("regime_trending", 0),
        "ranging": tech_result["indicators"].get("regime_ranging", 0),
        "volatile": tech_result["indicators"].get("regime_volatile", 0),
    }
    snapshot_caps = {k: round(v, 2) for k, v in tech_result["caps"].items()} if tech_result.get("caps") else {}
    snapshot_outer = {k: round(v, 4) for k, v in outer.items()} if regime else {}
    atr_source = "performance_tracker" if tracker else "defaults"
    engine_snapshot = build_engine_snapshot(
        settings,
        getattr(app.state, "scoring_params", None),
        regime_mix, snapshot_caps, snapshot_outer,
        (sl_base, tp1_base, tp2_base), atr_source,
    )
```

Then include `"engine_snapshot": engine_snapshot` in the `signal_data` dict.

- [ ] **Step 5: Update `persist_signal` to include `engine_snapshot`**

The `persist_signal` function (called by `_emit_signal`) uses explicit keyword arguments in the `Signal()` constructor — it does NOT use `**signal_data`. You must add `engine_snapshot=signal_data.get("engine_snapshot")` to the `Signal()` constructor call in `persist_signal`. Find the constructor call (around `backend/app/main.py` in `persist_signal`) and add the new kwarg alongside the existing ones like `correlated_news_ids`.

- [ ] **Step 6: Run test to verify it passes**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_snapshot.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/engine/test_snapshot.py
git commit -m "feat(engine): populate engine_snapshot on signal emission"
```

---

### Task 7: ATR Optimization Endpoint + Regime Optimizer Breaking Change

Add `POST /api/backtest/optimize-atr` and modify regime optimizer to not auto-save.

**Files:**
- Modify: `backend/app/api/backtest.py:370-546` (regime optimizer — remove auto-save)
- Modify: `backend/app/api/backtest.py` (add optimize-atr endpoint)
- Test: `backend/tests/api/test_optimize_endpoints.py` (new)

- [ ] **Step 1: Write test for ATR optimization endpoint**

Create `backend/tests/api/test_optimize_endpoints.py`:

```python
"""Test optimization endpoints."""

import pytest

HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_optimize_atr_requires_pair_and_timeframe(client):
    resp = await client.post(
        "/api/backtest/optimize-atr",
        headers=HEADERS,
        json={},
    )
    assert resp.status_code == 422  # validation error


@pytest.mark.asyncio
async def test_optimize_atr_success(client):
    """Happy path: returns current/proposed multipliers and metrics."""
    from unittest.mock import AsyncMock, MagicMock

    tracker = MagicMock()
    tracker.get_multipliers = AsyncMock(return_value=(1.5, 2.0, 3.0))
    tracker.optimize = AsyncMock(return_value={
        "sl_atr": 1.3, "tp1_atr": 2.2, "tp2_atr": 3.5,
        "signals_analyzed": 85,
        "current_sortino": 1.42,
        "proposed_sortino": 1.78,
    })
    client.app.state.tracker = tracker

    resp = await client.post(
        "/api/backtest/optimize-atr",
        headers=HEADERS,
        json={"pair": "BTC-USDT-SWAP", "timeframe": "1h"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"]["sl_atr"] == 1.5
    assert data["proposed"]["sl_atr"] == 1.3
    assert data["metrics"]["signals_analyzed"] == 85
    assert data["metrics"]["proposed_sortino"] == 1.78

    # verify dry_run=True was passed
    tracker.optimize.assert_called_once_with("BTC-USDT-SWAP", "1h", dry_run=True)


@pytest.mark.asyncio
async def test_optimize_atr_insufficient_signals(client):
    """Returns 400 when not enough resolved signals."""
    from unittest.mock import AsyncMock, MagicMock

    tracker = MagicMock()
    tracker.get_multipliers = AsyncMock(return_value=(1.5, 2.0, 3.0))
    tracker.optimize = AsyncMock(return_value=None)
    client.app.state.tracker = tracker

    resp = await client.post(
        "/api/backtest/optimize-atr",
        headers=HEADERS,
        json={"pair": "BTC-USDT-SWAP", "timeframe": "1h"},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Add `POST /api/backtest/optimize-atr` endpoint**

In `backend/app/api/backtest.py`, add a new request model and endpoint:

```python
class OptimizeAtrRequest(BaseModel):
    pair: str
    timeframe: str


@router.post("/optimize-atr")
async def optimize_atr(body: OptimizeAtrRequest, request: Request, _key: str = require_settings_api_key()):
    """Run ATR multiplier optimization on demand."""
    tracker = getattr(request.app.state, "tracker", None)
    if tracker is None:
        raise HTTPException(500, "Performance tracker not initialized")

    current = await tracker.get_multipliers(body.pair, body.timeframe)

    result = await tracker.optimize(body.pair, body.timeframe, dry_run=True)
    if result is None:
        raise HTTPException(400, "Not enough resolved signals for optimization")

    return {
        "current": {"sl_atr": current[0], "tp1_atr": current[1], "tp2_atr": current[2]},
        "proposed": {
            "sl_atr": result["sl_atr"],
            "tp1_atr": result["tp1_atr"],
            "tp2_atr": result["tp2_atr"],
        },
        "metrics": {
            "signals_analyzed": result["signals_analyzed"],
            "current_sortino": result.get("current_sortino"),
            "proposed_sortino": result.get("proposed_sortino"),
        },
    }
```

**Important:** This requires modifying `PerformanceTracker.optimize()` in `backend/app/engine/performance_tracker.py` to accept a `dry_run: bool = False` parameter. When `dry_run=True`, skip the DB write at the end of `optimize()` (the block that does `session.commit()` to update the `PerformanceTrackerRow`). Return a dict with the proposed multipliers and metrics instead of persisting them. The method signature becomes:

```python
async def optimize(self, pair: str, timeframe: str, dry_run: bool = False) -> dict | None:
```

At the end of the method, before the DB write block, add:
```python
if dry_run:
    return {
        "sl_atr": best_sl, "tp1_atr": best_tp1, "tp2_atr": best_tp2,
        "signals_analyzed": len(signals),
        "current_sortino": current_sortino,
        "proposed_sortino": best_sortino,
    }
```

- [ ] **Step 3: Modify regime optimizer to not auto-save (lines 472-511)**

In `backend/app/api/backtest.py`, in the `optimize_regime` endpoint's `_run()` coroutine, remove the block at lines 472-511 that saves to `RegimeWeights` and hot-reloads into `app.state`. Instead, just store the proposed weights in the BacktestRun results so the user can review and apply via `POST /api/engine/apply`.

Replace lines 472-511 with:

```python
            # Return proposed weights without auto-saving.
            # User applies via POST /api/engine/apply after review.
```

Keep the results saving block (lines 515-527) — it already stores weights in results.

- [ ] **Step 3b: Write regression test for regime auto-save removal**

Add to `backend/tests/api/test_optimize_endpoints.py`:

```python
@pytest.mark.asyncio
async def test_regime_optimizer_does_not_auto_save(client):
    """Regime optimization must NOT write to RegimeWeights or update app.state.regime_weights."""
    from unittest.mock import AsyncMock, MagicMock, patch

    # Seed app.state.regime_weights with a known value
    original_weights = dict(client.app.state.regime_weights)

    # Mock the optimizer to run and "succeed"
    # The real test requires the full backtester infra; for the unit test,
    # mock the internal _run coroutine to produce results and verify
    # that the endpoint response does NOT call session.commit() on RegimeWeights.
    # This test verifies the code path no longer contains the auto-save block.

    # At minimum, verify the removed code is absent:
    import inspect
    from app.api.backtest import optimize_regime
    source = inspect.getsource(optimize_regime)
    assert "session.merge" not in source, "optimize_regime should not merge RegimeWeights"
    assert "regime_weights[" not in source, "optimize_regime should not update app.state.regime_weights"
```

- [ ] **Step 4: Run tests**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_optimize_endpoints.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/backtest.py backend/app/engine/performance_tracker.py backend/tests/api/test_optimize_endpoints.py
git commit -m "feat(api): add optimize-atr endpoint, stop regime optimizer auto-save"
```

---

### Task 8: Backtest Parameter Overrides Extension

Extend `POST /api/backtest/run` to accept dot-path parameter overrides and store them.

**Files:**
- Modify: `backend/app/api/backtest.py:47-62` (RunRequest model)
- Modify: `backend/app/api/backtest.py:128-282` (start_backtest handler)

- [ ] **Step 1: Add `parameter_overrides` to RunRequest**

In `backend/app/api/backtest.py`, update the `RunRequest` model:

```python
class RunRequest(BaseModel):
    # ... existing fields ...
    parameter_overrides: dict[str, float | int] | None = None
```

- [ ] **Step 2: Add dot-path to BacktestConfig mapping**

Add a helper function in `backtest.py`:

```python
_OVERRIDE_TO_CONFIG = {
    "blending.source_weights.traditional": "tech_weight",
    "blending.source_weights.pattern": "pattern_weight",
    "blending.thresholds.signal": "signal_threshold",
    "blending.thresholds.ml_confidence": "ml_confidence_threshold",
    "levels.atr_defaults.sl": "sl_atr_multiplier",
    "levels.atr_defaults.tp1": "tp1_atr_multiplier",
    "levels.atr_defaults.tp2": "tp2_atr_multiplier",
    "confluence_max_score": "confluence_max_score",
}


def _apply_overrides(config: BacktestConfig, overrides: dict) -> BacktestConfig:
    """Apply dot-path overrides onto a BacktestConfig."""
    for dot_path, value in overrides.items():
        config_field = _OVERRIDE_TO_CONFIG.get(dot_path)
        if config_field and hasattr(config, config_field):
            setattr(config, config_field, value)
    return config
```

- [ ] **Step 3: Use overrides in start_backtest handler**

In the `_run()` coroutine (around line 181, after `bt_config` is created), add:

```python
            if body.parameter_overrides:
                bt_config = _apply_overrides(bt_config, body.parameter_overrides)
```

- [ ] **Step 4: Store overrides in BacktestRun row**

When creating the BacktestRun (around line 155), add:

```python
        run = BacktestRun(
            # ... existing fields ...
            parameter_overrides=body.parameter_overrides,
        )
```

- [ ] **Step 5: Include overrides in run response dicts**

Update `_run_to_dict` (line 564) to include:

```python
"parameter_overrides": run.parameter_overrides,
```

- [ ] **Step 6: Write test for `_apply_overrides` helper**

Create `backend/tests/api/test_backtest_overrides.py`:

```python
"""Test backtest parameter override mapping."""

import pytest


def test_apply_overrides_maps_dot_paths():
    """Verify dot-path overrides are routed to the correct BacktestConfig fields."""
    from app.api.backtest import _apply_overrides
    from app.engine.backtester import BacktestConfig

    config = BacktestConfig()
    original_threshold = config.signal_threshold
    original_sl = config.sl_atr_multiplier

    overrides = {
        "blending.thresholds.signal": 25,
        "levels.atr_defaults.sl": 1.8,
        "blending.source_weights.traditional": 0.50,
        "nonexistent.path": 999,  # should be silently ignored
    }
    result = _apply_overrides(config, overrides)

    assert result.signal_threshold == 25
    assert result.sl_atr_multiplier == 1.8
    assert result.tech_weight == 0.50
    # original values changed
    assert result.signal_threshold != original_threshold or original_threshold == 25


def test_apply_overrides_ignores_unknown_paths():
    """Unknown dot-paths should not raise or modify config."""
    from app.api.backtest import _apply_overrides
    from app.engine.backtester import BacktestConfig

    config = BacktestConfig()
    original = BacktestConfig()

    _apply_overrides(config, {"unknown.path": 42, "also.unknown": 99})

    assert config.signal_threshold == original.signal_threshold
    assert config.sl_atr_multiplier == original.sl_atr_multiplier
```

- [ ] **Step 7: Run existing backtest tests + new tests**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/backtest.py backend/tests/api/test_backtest_overrides.py
git commit -m "feat(backtest): accept dot-path parameter overrides in run requests"
```

---

### Task 9: Pipeline Snapshot-on-Read for Concurrency Safety

Snapshot mutable parameters at the start of each pipeline cycle.

**Files:**
- Modify: `backend/app/main.py:240-290` (run_pipeline top — snapshot params into locals)

- [ ] **Step 1: Snapshot parameters at the top of run_pipeline**

At the top of `run_pipeline` (around line 245, after `settings = app.state.settings`), add:

```python
    # snapshot mutable params to avoid mid-cycle mutation
    scoring_params = dict(getattr(app.state, "scoring_params", {}) or {})
    regime_weights_dict = dict(app.state.regime_weights)
```

Then update the references below:
- Line 266: change `app.state.regime_weights.get(rw_key)` to `regime_weights_dict.get(rw_key)`
- Line 270: change `getattr(app.state, "scoring_params", None)` to `scoring_params or None`

- [ ] **Step 1b: Write test for snapshot isolation**

Add to `backend/tests/engine/test_snapshot.py`:

```python
def test_snapshot_produces_independent_copy():
    """dict() on scoring_params must produce an independent copy
    so mid-cycle mutations to app.state don't affect the snapshot."""
    original = {"mean_rev_rsi_steepness": 0.25, "squeeze_steepness": 0.10}
    snapshot = dict(original)

    # mutate the "app.state" source after snapshot
    original["mean_rev_rsi_steepness"] = 0.99

    # snapshot should be unaffected
    assert snapshot["mean_rev_rsi_steepness"] == 0.25
```

This confirms `dict()` shallow copy is sufficient since `scoring_params` values are all scalars (no nested dicts).

- [ ] **Step 2: Run full test suite**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "fix(pipeline): snapshot mutable params at cycle start for concurrency safety"
```

---

### Task 10: Frontend — API Client Extensions

Add the new API methods to the shared API client.

**Note:** Tasks 10 and 11 must be completed together before running `pnpm build`, since the API methods reference types defined in Task 11.

**Files:**
- Modify: `web/src/shared/lib/api.ts`

- [ ] **Step 1: Add engine API methods**

In `web/src/shared/lib/api.ts`, add:

```typescript
getEngineParameters: () =>
  request<EngineParameters>("/api/engine/parameters"),

previewEngineApply: (changes: Record<string, number | Record<string, number>>) =>
  request<{ preview: true; diff: ParameterDiff[] }>("/api/engine/apply", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ changes, confirm: false }),
  }),

confirmEngineApply: (changes: Record<string, number | Record<string, number>>) =>
  request<{ applied: true; diff: ParameterDiff[] }>("/api/engine/apply", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ changes, confirm: true }),
  }),

optimizeAtr: (pair: string, timeframe: string) =>
  request<AtrOptimizationResult>("/api/backtest/optimize-atr", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ pair, timeframe }),
  }),
```

The types (`EngineParameters`, `ParameterDiff`, `AtrOptimizationResult`) will be defined in Task 11.

- [ ] **Step 2: Commit**

```bash
git add web/src/shared/lib/api.ts
git commit -m "feat(api-client): add engine parameters and apply methods"
```

---

### Task 11: Frontend — Engine Feature Types & Store

Define TypeScript interfaces and Zustand store for the Engine feature.

**Files:**
- Create: `web/src/features/engine/types.ts`
- Create: `web/src/features/engine/store.ts`

- [ ] **Step 1: Create `web/src/features/engine/types.ts`**

```typescript
export interface ParameterValue {
  value: number | number[] | string | Record<string, number>;
  source: "hardcoded" | "configurable";
}

export interface ParameterDiff {
  path: string;
  current: number | null;
  proposed: number;
  source: string;
}

export interface AtrOptimizationResult {
  current: { sl_atr: number; tp1_atr: number; tp2_atr: number };
  proposed: { sl_atr: number; tp1_atr: number; tp2_atr: number };
  metrics: {
    signals_analyzed: number;
    current_sortino: number | null;
    proposed_sortino: number | null;
  };
}

export interface RegimeCapWeights {
  inner_caps: Record<string, number>;
  outer_weights: Record<string, number>;
}

export interface LearnedAtrEntry {
  sl_atr: ParameterValue;
  tp1_atr: ParameterValue;
  tp2_atr: ParameterValue;
  last_optimized_at: string | null;
  signal_count: number;
}

export interface EngineParameters {
  technical: {
    indicator_periods: Record<string, ParameterValue>;
    sigmoid_params: Record<string, ParameterValue>;
    mean_reversion: Record<string, ParameterValue>;
  };
  order_flow: {
    max_scores: Record<string, ParameterValue>;
    sigmoid_steepnesses: Record<string, ParameterValue>;
    regime_params: Record<string, ParameterValue>;
  };
  onchain: Record<string, Record<string, ParameterValue | Record<string, ParameterValue>>>;
  blending: {
    source_weights: Record<string, ParameterValue>;
    ml_blend_weight: ParameterValue;
    thresholds: Record<string, ParameterValue>;
    llm_factor_weights: Record<string, ParameterValue>;
    llm_factor_cap: ParameterValue;
    confluence_max_score: ParameterValue;
  };
  levels: Record<string, Record<string, ParameterValue>>;
  patterns: { strengths: Record<string, ParameterValue> };
  regime_weights: Record<string, Record<string, Record<string, RegimeCapWeights>>>;
  learned_atr: Record<string, Record<string, LearnedAtrEntry>>;
  performance_tracker: Record<string, Record<string, ParameterValue>>;
}
```

- [ ] **Step 2: Create `web/src/features/engine/store.ts`**

```typescript
import { create } from "zustand";
import { api } from "../../shared/lib/api";
import type { EngineParameters } from "./types";

interface EngineStore {
  params: EngineParameters | null;
  loading: boolean;
  error: string | null;
  fetch: () => Promise<void>;
  refresh: () => Promise<void>;
}

export const useEngineStore = create<EngineStore>((set, get) => ({
  params: null,
  loading: false,
  error: null,

  fetch: async () => {
    if (get().params) return; // already loaded
    set({ loading: true, error: null });
    try {
      const data = await api.getEngineParameters();
      set({ params: data, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  refresh: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getEngineParameters();
      set({ params: data, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },
}));
```

- [ ] **Step 3: Write frontend store test**

Create `web/src/features/engine/__tests__/store.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEngineStore } from "../store";

// Mock the API module
vi.mock("../../../shared/lib/api", () => ({
  api: {
    getEngineParameters: vi.fn(),
  },
}));

import { api } from "../../../shared/lib/api";
const mockApi = api as { getEngineParameters: ReturnType<typeof vi.fn> };

describe("useEngineStore", () => {
  beforeEach(() => {
    // Reset store state between tests
    useEngineStore.setState({ params: null, loading: false, error: null });
    vi.clearAllMocks();
  });

  it("fetch loads params and sets loading states", async () => {
    const mockParams = { technical: {}, blending: {} };
    mockApi.getEngineParameters.mockResolvedValue(mockParams);

    await useEngineStore.getState().fetch();

    expect(useEngineStore.getState().params).toEqual(mockParams);
    expect(useEngineStore.getState().loading).toBe(false);
    expect(useEngineStore.getState().error).toBeNull();
  });

  it("fetch skips if params already loaded", async () => {
    useEngineStore.setState({ params: { technical: {} } as any });

    await useEngineStore.getState().fetch();

    expect(mockApi.getEngineParameters).not.toHaveBeenCalled();
  });

  it("fetch sets error on failure", async () => {
    mockApi.getEngineParameters.mockRejectedValue(new Error("Network error"));

    await useEngineStore.getState().fetch();

    expect(useEngineStore.getState().error).toBe("Network error");
    expect(useEngineStore.getState().params).toBeNull();
  });

  it("refresh always re-fetches", async () => {
    useEngineStore.setState({ params: { technical: {} } as any });
    const newParams = { technical: {}, blending: {} };
    mockApi.getEngineParameters.mockResolvedValue(newParams);

    await useEngineStore.getState().refresh();

    expect(mockApi.getEngineParameters).toHaveBeenCalled();
    expect(useEngineStore.getState().params).toEqual(newParams);
  });
});
```

- [ ] **Step 4: Run frontend tests**

```bash
cd web && npx vitest run src/features/engine/__tests__/store.test.ts
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/engine/types.ts web/src/features/engine/store.ts web/src/features/engine/__tests__/store.test.ts
git commit -m "feat(engine): add TypeScript types, Zustand store, and store tests"
```

---

### Task 12: Frontend — More Tab Sub-Navigation Refactor

Break MorePage into sub-tab router with extracted components.

**Files:**
- Modify: `web/src/features/more/components/MorePage.tsx` (rewrite as sub-tab router)
- Create: `web/src/features/settings/components/SettingsPage.tsx` (extracted from MorePage)
- Create: `web/src/features/settings/components/RiskPage.tsx` (extracted from MorePage)
- Modify: `web/src/features/backtest/components/BacktestView.tsx` (make header conditional)
- Modify: `web/src/features/ml/components/MLTrainingView.tsx` (make header conditional)
- Modify: `web/src/features/alerts/components/AlertsPage.tsx` (make header conditional)

- [ ] **Step 1: Make back-button headers conditional in sub-view components**

In each of `BacktestView.tsx`, `MLTrainingView.tsx`, `AlertsPage.tsx`, make the `onBack` prop optional and only render the back-arrow header when `onBack` is provided:

```typescript
// Example for BacktestView.tsx
interface Props {
  onBack?: () => void;  // was: onBack: () => void
}

// In render:
{onBack && (
  <div className="flex items-center gap-2 ...">
    <button onClick={onBack}>←</button>
    <h2>Backtester</h2>
  </div>
)}
```

Apply the same pattern to all three components.

- [ ] **Step 2: Extract SettingsPage from MorePage**

Create `web/src/features/settings/components/SettingsPage.tsx`. Extract the Trading, Notifications, and System sections from MorePage. Use the same `SettingsGroup` helper component. Import from `useSettingsStore`.

- [ ] **Step 3: Extract RiskPage from MorePage**

Create `web/src/features/settings/components/RiskPage.tsx`. Extract the Risk Management section from MorePage. Uses its own API calls to `GET/PUT /api/risk/settings`.

- [ ] **Step 4: Rewrite MorePage as sub-tab router**

Replace the 463-line `MorePage.tsx` with a ~50-line sub-tab router:

```typescript
import { useState } from "react";
import SettingsPage from "../../settings/components/SettingsPage";
import RiskPage from "../../settings/components/RiskPage";
import EnginePage from "../../engine/components/EnginePage";
// NOTE: Check actual export style of these components. If they use named exports
// (e.g., `export function BacktestView`), use `{ BacktestView }` instead.
// If they use `export default`, use default import. Adjust as needed.
import { BacktestView } from "../../backtest/components/BacktestView";
import { MLTrainingView } from "../../ml/components/MLTrainingView";
import { AlertsPage } from "../../alerts/components/AlertsPage";

const SUB_TABS = ["Settings", "Risk", "Engine", "Backtest", "ML", "Alerts"] as const;
type SubTab = (typeof SUB_TABS)[number];

export default function MorePage() {
  const [active, setActive] = useState<SubTab>("Settings");

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1.5 px-3 py-2 overflow-x-auto scrollbar-hide border-b border-border">
        {SUB_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActive(tab)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
              active === tab
                ? "bg-accent/20 text-accent"
                : "bg-surface text-muted hover:text-foreground"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        {active === "Settings" && <SettingsPage />}
        {active === "Risk" && <RiskPage />}
        {active === "Engine" && <EnginePage />}
        {active === "Backtest" && <BacktestView />}
        {active === "ML" && <MLTrainingView />}
        {active === "Alerts" && <AlertsPage />}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Verify the app builds**

```bash
cd web && pnpm build
```

Expected: build succeeds with no type errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/more/ web/src/features/settings/components/ web/src/features/backtest/components/ web/src/features/ml/components/ web/src/features/alerts/components/
git commit -m "refactor(more): split MorePage into sub-tab router with extracted pages"
```

---

### Task 13: Frontend — Engine Parameter Dashboard Components

Build the read-only parameter dashboard.

**Files:**
- Create: `web/src/features/engine/components/EnginePage.tsx`
- Create: `web/src/features/engine/components/ParameterCategory.tsx`
- Create: `web/src/features/engine/components/ParameterRow.tsx`
- Create: `web/src/features/engine/components/SourceBadge.tsx`
- Create: `web/src/features/engine/components/WeightBar.tsx`
- Create: `web/src/features/engine/components/RegimeGrid.tsx`

- [ ] **Step 1: Create SourceBadge component**

```typescript
// web/src/features/engine/components/SourceBadge.tsx
interface Props {
  source: "hardcoded" | "configurable";
}

export default function SourceBadge({ source }: Props) {
  const styles =
    source === "configurable"
      ? "bg-green-500/15 text-green-400"
      : "bg-white/8 text-muted";

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${styles}`}>
      {source}
    </span>
  );
}
```

- [ ] **Step 2: Create ParameterRow component**

```typescript
// web/src/features/engine/components/ParameterRow.tsx
import SourceBadge from "./SourceBadge";

interface Props {
  name: string;
  value: unknown;
  source: "hardcoded" | "configurable";
  last?: boolean;
}

export default function ParameterRow({ name, value, source, last }: Props) {
  const display = Array.isArray(value)
    ? value.join(", ")
    : typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value);

  return (
    <div
      className={`flex items-center justify-between px-3 py-2 ${
        last ? "" : "border-b border-border/50"
      }`}
    >
      <span className="text-xs text-muted">{name}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-foreground">{display}</span>
        <SourceBadge source={source} />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create ParameterCategory component**

```typescript
// web/src/features/engine/components/ParameterCategory.tsx
import { useState } from "react";
import ParameterRow from "./ParameterRow";

interface Props {
  title: string;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  params?: Record<string, { value: unknown; source: "hardcoded" | "configurable" }>;
}

export default function ParameterCategory({ title, defaultOpen = false, children, params }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  const entries = params ? Object.entries(params) : [];

  return (
    <div className="border border-border/50 rounded-lg overflow-hidden mb-2">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-surface/50 hover:bg-surface transition-colors"
      >
        <span className="text-sm font-medium text-foreground">{title}</span>
        <span className="text-muted text-xs">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div>
          {params &&
            entries.map(([key, param], i) => (
              <ParameterRow
                key={key}
                name={key}
                value={param.value}
                source={param.source}
                last={i === entries.length - 1}
              />
            ))}
          {children}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create WeightBar component**

```typescript
// web/src/features/engine/components/WeightBar.tsx
const COLORS = ["#F0B90B", "#0ECB81", "#3B82F6", "#A855F7"];

interface Props {
  weights: Record<string, { value: number; source: string }>;
}

export default function WeightBar({ weights }: Props) {
  const entries = Object.entries(weights);
  return (
    <div className="px-3 py-2">
      <div className="flex h-5 rounded overflow-hidden">
        {entries.map(([name, w], i) => (
          <div
            key={name}
            style={{ width: `${w.value * 100}%`, backgroundColor: COLORS[i % COLORS.length] }}
            className="flex items-center justify-center text-[9px] font-medium text-black"
            title={`${name}: ${(w.value * 100).toFixed(0)}%`}
          >
            {(w.value * 100).toFixed(0)}%
          </div>
        ))}
      </div>
      <div className="flex justify-between mt-1">
        {entries.map(([name], i) => (
          <span key={name} className="text-[10px] text-muted" style={{ color: COLORS[i % COLORS.length] }}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create RegimeGrid component**

```typescript
// web/src/features/engine/components/RegimeGrid.tsx
import type { RegimeCapWeights } from "../types";

interface Props {
  regimes: Record<string, RegimeCapWeights>;
}

const REGIMES = ["trending", "ranging", "volatile"] as const;

export default function RegimeGrid({ regimes }: Props) {
  if (!regimes || Object.keys(regimes).length === 0) return null;

  const capKeys = Object.keys(regimes[REGIMES[0]]?.inner_caps || {});
  const weightKeys = Object.keys(regimes[REGIMES[0]]?.outer_weights || {});

  return (
    <div className="px-3 py-2 space-y-3">
      <div>
        <div className="text-[10px] text-muted mb-1 uppercase">inner caps</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted">
              <th className="text-left font-normal py-1"></th>
              {capKeys.map((k) => (
                <th key={k} className="text-right font-normal py-1 px-1">{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {REGIMES.map((r) => (
              <tr key={r} className="border-t border-border/30">
                <td className="py-1 text-muted capitalize">{r}</td>
                {capKeys.map((k) => (
                  <td key={k} className="text-right py-1 px-1 font-mono">
                    {regimes[r]?.inner_caps[k] ?? "-"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="text-[10px] text-muted mb-1 uppercase">outer weights</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted">
              <th className="text-left font-normal py-1"></th>
              {weightKeys.map((k) => (
                <th key={k} className="text-right font-normal py-1 px-1">{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {REGIMES.map((r) => (
              <tr key={r} className="border-t border-border/30">
                <td className="py-1 text-muted capitalize">{r}</td>
                {weightKeys.map((k) => (
                  <td key={k} className="text-right py-1 px-1 font-mono">
                    {regimes[r]?.outer_weights[k]?.toFixed(2) ?? "-"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create EnginePage component**

```typescript
// web/src/features/engine/components/EnginePage.tsx
import { useEffect, useState } from "react";
import { useEngineStore } from "../store";
import ParameterCategory from "./ParameterCategory";
import ParameterRow from "./ParameterRow";
import WeightBar from "./WeightBar";
import RegimeGrid from "./RegimeGrid";

export default function EnginePage() {
  const { params, loading, error, fetch, refresh } = useEngineStore();
  const [selectedPair, setSelectedPair] = useState("");
  const [selectedTf, setSelectedTf] = useState("");

  useEffect(() => { fetch(); }, [fetch]);

  // auto-select first pair/tf when params load
  useEffect(() => {
    if (!params) return;
    const pairs = Object.keys(params.regime_weights || {});
    if (pairs.length > 0 && !selectedPair) {
      setSelectedPair(pairs[0]);
      const tfs = Object.keys(params.regime_weights[pairs[0]] || {});
      if (tfs.length > 0) setSelectedTf(tfs[0]);
    }
  }, [params, selectedPair]);

  if (loading) return <div className="p-4 text-muted text-sm">Loading parameters...</div>;
  if (error) return <div className="p-4 text-red-400 text-sm">Error: {error}</div>;
  if (!params) return null;

  const regimeData = selectedPair && selectedTf
    ? params.regime_weights?.[selectedPair]?.[selectedTf]
    : null;
  const learnedAtr = selectedPair && selectedTf
    ? params.learned_atr?.[selectedPair]?.[selectedTf]
    : null;

  const allPairs = [
    ...new Set([
      ...Object.keys(params.regime_weights || {}),
      ...Object.keys(params.learned_atr || {}),
    ]),
  ];
  const allTfs = selectedPair
    ? [
        ...new Set([
          ...Object.keys(params.regime_weights?.[selectedPair] || {}),
          ...Object.keys(params.learned_atr?.[selectedPair] || {}),
        ]),
      ]
    : [];

  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-foreground">Engine Parameters</h3>
        <button onClick={refresh} className="text-xs text-accent hover:text-accent/80">
          Refresh
        </button>
      </div>

      <ParameterCategory title="Blending" defaultOpen>
        <WeightBar weights={params.blending.source_weights} />
        <ParameterRow name="ml_blend_weight" value={params.blending.ml_blend_weight.value} source={params.blending.ml_blend_weight.source} />
        {Object.entries(params.blending.thresholds).map(([k, v], i, arr) => (
          <ParameterRow key={k} name={k} value={v.value} source={v.source} last={i === arr.length - 1} />
        ))}
      </ParameterCategory>

      <ParameterCategory title="LLM Factor Weights" params={params.blending.llm_factor_weights}>
        <ParameterRow name="factor_cap" value={params.blending.llm_factor_cap.value} source={params.blending.llm_factor_cap.source} last />
      </ParameterCategory>

      <ParameterCategory title="Technical — Indicators" params={params.technical.indicator_periods} />
      <ParameterCategory title="Technical — Sigmoid Params" params={params.technical.sigmoid_params} />
      <ParameterCategory title="Technical — Mean Reversion" params={params.technical.mean_reversion} />
      <ParameterCategory title="Order Flow" params={params.order_flow.regime_params}>
        {Object.entries(params.order_flow.max_scores).map(([k, v]) => (
          <ParameterRow key={k} name={`max_${k}`} value={v.value} source={v.source} />
        ))}
      </ParameterCategory>
      <ParameterCategory title="On-Chain — BTC" params={params.onchain.btc_profile as Record<string, any>} />
      <ParameterCategory title="On-Chain — ETH" params={params.onchain.eth_profile as Record<string, any>} />
      <ParameterCategory title="Levels & ATR" params={params.levels.atr_defaults} />
      <ParameterCategory title="ATR Guardrails" params={params.levels.atr_guardrails} />
      <ParameterCategory title="Phase 1 Scaling" params={params.levels.phase1_scaling} />
      <ParameterCategory title="Pattern Strengths" params={params.patterns.strengths} />
      <ParameterCategory title="Performance Tracker" params={params.performance_tracker.optimization_params} />
      <ParameterCategory title="Optimization Guardrails" params={params.performance_tracker.guardrails} />

      {allPairs.length > 0 && (
        <>
          <div className="flex gap-2 pt-2">
            <select
              value={selectedPair}
              onChange={(e) => {
                setSelectedPair(e.target.value);
                const tfs = Object.keys(params.regime_weights?.[e.target.value] || {});
                if (tfs.length > 0) setSelectedTf(tfs[0]);
              }}
              className="bg-surface border border-border rounded px-2 py-1 text-xs text-foreground"
            >
              {allPairs.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <select
              value={selectedTf}
              onChange={(e) => setSelectedTf(e.target.value)}
              className="bg-surface border border-border rounded px-2 py-1 text-xs text-foreground"
            >
              {allTfs.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
            </select>
          </div>

          {regimeData && (
            <ParameterCategory title={`Regime Weights — ${selectedPair} ${selectedTf}`}>
              <RegimeGrid regimes={regimeData} />
            </ParameterCategory>
          )}

          {learnedAtr && (
            <ParameterCategory title={`Learned ATR — ${selectedPair} ${selectedTf}`}>
              <ParameterRow name="sl_atr" value={learnedAtr.sl_atr.value} source={learnedAtr.sl_atr.source} />
              <ParameterRow name="tp1_atr" value={learnedAtr.tp1_atr.value} source={learnedAtr.tp1_atr.source} />
              <ParameterRow name="tp2_atr" value={learnedAtr.tp2_atr.value} source={learnedAtr.tp2_atr.source} />
              <ParameterRow name="last_optimized" value={learnedAtr.last_optimized_at || "never"} source="configurable" />
              <ParameterRow name="signal_count" value={learnedAtr.signal_count} source="configurable" last />
            </ParameterCategory>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Verify build**

```bash
cd web && pnpm build
```

Expected: builds successfully.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/engine/components/
git commit -m "feat(engine): add parameter dashboard UI components"
```

---

### Task 14: Frontend — Signal Snapshot Display

Add collapsible engine snapshot section to signal detail view.

**Files:**
- Modify: `web/src/features/signals/types.ts` (add `engine_snapshot` to Signal interface)
- Modify: `web/src/features/signals/components/SignalDetail.tsx` (add snapshot section)

- [ ] **Step 1: Add `engine_snapshot` to Signal interface**

In `web/src/features/signals/types.ts`, add to the Signal interface:

```typescript
engine_snapshot: Record<string, unknown> | null;
```

- [ ] **Step 2: Add snapshot section to SignalDetail**

In `web/src/features/signals/components/SignalDetail.tsx`, after the existing score breakdown section, add a collapsible "Engine Parameters" section:

```typescript
import ParameterRow from "../../engine/components/ParameterRow";

// Inside the component, after the score breakdown section:
{signal.engine_snapshot ? (
  <SnapshotSection snapshot={signal.engine_snapshot} />
) : (
  <p className="text-xs text-muted px-3 py-2">Parameter snapshot not available</p>
)}
```

Create a small `SnapshotSection` component inline or as a separate file that renders the snapshot keys using `ParameterRow`:

```typescript
function SnapshotSection({ snapshot }: { snapshot: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-t border-border/50">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs text-muted hover:text-foreground"
      >
        Engine Parameters
        <span>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div>
          {Object.entries(snapshot).map(([key, value]) => (
            <ParameterRow
              key={key}
              name={key}
              value={value as unknown}
              source="configurable"
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd web && pnpm build
```

Expected: builds.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/signals/types.ts web/src/features/signals/components/SignalDetail.tsx
git commit -m "feat(signals): display engine snapshot in signal detail view"
```

---

### Task 15: Frontend — Backtest Apply Flow Modal

Add the apply flow modal for applying backtest/optimization results to the live engine.

**Files:**
- Create: `web/src/features/backtest/components/ApplyModal.tsx`
- Modify: `web/src/features/backtest/components/BacktestView.tsx` (add "Apply to Live" button)

- [ ] **Step 1: Create ApplyModal component**

```typescript
// web/src/features/backtest/components/ApplyModal.tsx
import { useState, useEffect } from "react";
import { api } from "../../../shared/lib/api";
import { useEngineStore } from "../../engine/store";
import type { ParameterDiff } from "../../engine/types";

interface Props {
  changes: Record<string, number>;
  onClose: () => void;
}

export default function ApplyModal({ changes, onClose }: Props) {
  const [diff, setDiff] = useState<ParameterDiff[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = useEngineStore((s) => s.refresh);

  const preview = async () => {
    setLoading(true);
    try {
      const result = await api.previewEngineApply(changes);
      setDiff(result.diff);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const confirm = async () => {
    setLoading(true);
    try {
      await api.confirmEngineApply(changes);
      setApplied(true);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // auto-preview on mount
  useEffect(() => { preview(); }, []);

  return (
    <dialog open className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card rounded-xl p-4 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto">
        <h3 className="text-sm font-medium mb-3">
          {applied ? "Changes Applied" : "Review Parameter Changes"}
        </h3>

        {error && <p className="text-xs text-red-400 mb-2">{error}</p>}

        {diff && (
          <table className="w-full text-xs mb-3">
            <thead>
              <tr className="text-muted border-b border-border">
                <th className="text-left py-1">Parameter</th>
                <th className="text-right py-1">Current</th>
                <th className="text-right py-1">Proposed</th>
              </tr>
            </thead>
            <tbody>
              {diff.map((d) => (
                <tr key={d.path} className="border-b border-border/30">
                  <td className="py-1.5 text-muted font-mono">{d.path.split(".").pop()}</td>
                  <td className="text-right py-1.5 font-mono">{d.current ?? "—"}</td>
                  <td className="text-right py-1.5 font-mono text-accent">{d.proposed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 text-xs text-muted hover:text-foreground">
            {applied ? "Close" : "Cancel"}
          </button>
          {!applied && diff && (
            <button
              onClick={confirm}
              disabled={loading}
              className="px-3 py-1.5 text-xs bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-50"
            >
              {loading ? "Applying..." : "Confirm Apply"}
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}
```

- [ ] **Step 2: Add "Apply to Live" button to BacktestView results**

In the BacktestView results tab or wherever results are displayed, add a button that opens the ApplyModal with the parameter overrides from the run. The exact integration point depends on the existing results rendering, but the pattern is:

```typescript
const [showApply, setShowApply] = useState(false);
const [applyChanges, setApplyChanges] = useState<Record<string, number>>({});

// In results display:
<button
  onClick={() => {
    setApplyChanges(run.parameter_overrides || {});
    setShowApply(true);
  }}
  className="text-xs text-accent"
>
  Apply to Live
</button>

{showApply && (
  <ApplyModal changes={applyChanges} onClose={() => setShowApply(false)} />
)}
```

- [ ] **Step 3: Write ApplyModal test**

Create `web/src/features/backtest/__tests__/ApplyModal.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ApplyModal from "../components/ApplyModal";

vi.mock("../../../shared/lib/api", () => ({
  api: {
    previewEngineApply: vi.fn(),
    confirmEngineApply: vi.fn(),
  },
}));

vi.mock("../../engine/store", () => ({
  useEngineStore: vi.fn(() => vi.fn()),
}));

import { api } from "../../../shared/lib/api";
const mockApi = api as {
  previewEngineApply: ReturnType<typeof vi.fn>;
  confirmEngineApply: ReturnType<typeof vi.fn>;
};

describe("ApplyModal", () => {
  const changes = { "blending.thresholds.signal": 35 };
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches preview on mount and renders diff table", async () => {
    mockApi.previewEngineApply.mockResolvedValue({
      preview: true,
      diff: [{ path: "blending.thresholds.signal", current: 40, proposed: 35, source: "configurable" }],
    });

    render(<ApplyModal changes={changes} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByText("35")).toBeInTheDocument();
      expect(screen.getByText("40")).toBeInTheDocument();
    });

    expect(mockApi.previewEngineApply).toHaveBeenCalledWith(changes);
  });

  it("shows error on preview failure", async () => {
    mockApi.previewEngineApply.mockRejectedValue(new Error("Server error"));

    render(<ApplyModal changes={changes} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByText("Server error")).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 4: Verify build**

```bash
cd web && pnpm build
```

Expected: builds.

- [ ] **Step 5: Run frontend tests**

```bash
cd web && npx vitest run src/features/backtest/__tests__/ApplyModal.test.tsx
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/backtest/components/ApplyModal.tsx web/src/features/backtest/components/BacktestView.tsx web/src/features/backtest/__tests__/ApplyModal.test.tsx
git commit -m "feat(backtest): add apply-to-live modal with diff preview and tests"
```

---

### Task 16: Frontend — Backtest Optimize Tab

Add the Optimize tab to BacktestView for regime and ATR optimization.

**Files:**
- Create: `web/src/features/backtest/components/OptimizeTab.tsx`
- Modify: `web/src/features/backtest/components/BacktestView.tsx` (add Optimize tab)

- [ ] **Step 1: Create OptimizeTab component**

```typescript
// web/src/features/backtest/components/OptimizeTab.tsx
import { useState } from "react";
import { api } from "../../../shared/lib/api";
import ApplyModal from "./ApplyModal";
import type { AtrOptimizationResult } from "../../engine/types";

const PAIRS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"];
const TIMEFRAMES = ["15m", "1h", "4h", "1D"];

export default function OptimizeTab() {
  const [pair, setPair] = useState(PAIRS[0]);
  const [timeframe, setTimeframe] = useState(TIMEFRAMES[1]);
  const [atrResult, setAtrResult] = useState<AtrOptimizationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showApply, setShowApply] = useState(false);
  const [applyChanges, setApplyChanges] = useState<Record<string, number>>({});

  const runAtrOptimize = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.optimizeAtr(pair, timeframe);
      setAtrResult(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleApplyAtr = () => {
    if (!atrResult) return;
    setApplyChanges({
      [`learned_atr.${pair}.${timeframe}.current_sl_atr`]: atrResult.proposed.sl_atr,
      [`learned_atr.${pair}.${timeframe}.current_tp1_atr`]: atrResult.proposed.tp1_atr,
      [`learned_atr.${pair}.${timeframe}.current_tp2_atr`]: atrResult.proposed.tp2_atr,
    });
    setShowApply(true);
  };

  return (
    <div className="p-3 space-y-4">
      <div className="flex gap-2">
        <select value={pair} onChange={(e) => setPair(e.target.value)}
          className="bg-surface border border-border rounded px-2 py-1.5 text-xs text-foreground">
          {PAIRS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}
          className="bg-surface border border-border rounded px-2 py-1.5 text-xs text-foreground">
          {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
        </select>
      </div>

      <div className="border border-border/50 rounded-lg p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-medium">ATR Optimization</h4>
          <button onClick={runAtrOptimize} disabled={loading}
            className="px-3 py-1.5 text-xs bg-accent/20 text-accent rounded-lg disabled:opacity-50">
            {loading ? "Running..." : "Optimize"}
          </button>
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}

        {atrResult && (
          <div className="space-y-2">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted border-b border-border">
                  <th className="text-left py-1"></th>
                  <th className="text-right py-1">Current</th>
                  <th className="text-right py-1">Proposed</th>
                </tr>
              </thead>
              <tbody>
                {(["sl_atr", "tp1_atr", "tp2_atr"] as const).map((k) => (
                  <tr key={k} className="border-b border-border/30">
                    <td className="py-1.5 text-muted">{k}</td>
                    <td className="text-right py-1.5 font-mono">{atrResult.current[k].toFixed(2)}</td>
                    <td className="text-right py-1.5 font-mono text-accent">{atrResult.proposed[k].toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="text-xs text-muted">
              {atrResult.metrics.signals_analyzed} signals analyzed |
              Sortino: {atrResult.metrics.current_sortino?.toFixed(2) ?? "—"} → {atrResult.metrics.proposed_sortino?.toFixed(2) ?? "—"}
            </div>
            <button onClick={handleApplyAtr}
              className="text-xs text-accent hover:text-accent/80">
              Apply to Live
            </button>
          </div>
        )}
      </div>

      {showApply && (
        <ApplyModal changes={applyChanges} onClose={() => setShowApply(false)} />
      )}
    </div>
  );
}
```

Note: The `OptimizeTab` above implements ATR optimization. **Regime optimization** should be added as a second section in this same component. It calls the existing `POST /api/backtest/optimize-regime` endpoint (which no longer auto-saves after Task 7), displays the proposed regime weights in a diff table, and triggers the apply flow via `ApplyModal` using dot-paths like `regime_weights.BTC-USDT-SWAP.15m.trending_trend_cap`. The implementation follows the same pattern as ATR optimization — pair/tf selector, run button, results diff, apply button. Add this when implementing this task.

- [ ] **Step 2: Add Optimize to BacktestView tabs**

In `BacktestView.tsx`, add "Optimize" to the TABS array and render `<OptimizeTab />` when active.

- [ ] **Step 3: Verify build**

```bash
cd web && pnpm build
```

Expected: builds.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/backtest/components/OptimizeTab.tsx web/src/features/backtest/components/BacktestView.tsx
git commit -m "feat(backtest): add Optimize tab with ATR/regime optimization and apply flow"
```

---

### Task 17: Backtest Setup — Parameter Override Panel

Add the "Advanced: Parameter Overrides" collapsible section to the backtest Setup tab.

**Files:**
- Create: `web/src/features/backtest/components/ParameterOverridePanel.tsx`
- Modify: Backtest Setup tab component (integrate the panel)

- [ ] **Step 1: Create ParameterOverridePanel component**

This component reads current live values from the Engine store and renders editable number inputs for the parameters the backtester supports (per the dot-path to BacktestConfig mapping in Task 8). Untouched params are dimmed, edited ones highlighted. A "Reset to Live" button clears all overrides.

```typescript
// web/src/features/backtest/components/ParameterOverridePanel.tsx
import { useState } from "react";
import { useEngineStore } from "../../engine/store";

const BACKTEST_PARAMS = [
  { path: "blending.source_weights.traditional", label: "Tech Weight", key: "traditional" },
  { path: "blending.source_weights.pattern", label: "Pattern Weight", key: "pattern" },
  { path: "blending.thresholds.signal", label: "Signal Threshold", key: "signal" },
  { path: "blending.thresholds.ml_confidence", label: "ML Confidence", key: "ml_conf" },
  { path: "levels.atr_defaults.sl", label: "SL ATR", key: "sl" },
  { path: "levels.atr_defaults.tp1", label: "TP1 ATR", key: "tp1" },
  { path: "levels.atr_defaults.tp2", label: "TP2 ATR", key: "tp2" },
  { path: "confluence_max_score", label: "Confluence Max", key: "conf" },
];

interface Props {
  overrides: Record<string, number>;
  onChange: (overrides: Record<string, number>) => void;
}

export default function ParameterOverridePanel({ overrides, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const params = useEngineStore((s) => s.params);

  const getLiveValue = (path: string): number | null => {
    if (!params) return null;
    const parts = path.split(".");
    let current: any = params;
    for (const p of parts) {
      current = current?.[p];
    }
    return current?.value ?? current ?? null;
  };

  const handleChange = (path: string, value: string) => {
    const num = parseFloat(value);
    if (isNaN(num)) {
      const next = { ...overrides };
      delete next[path];
      onChange(next);
    } else {
      onChange({ ...overrides, [path]: num });
    }
  };

  return (
    <div className="border border-border/50 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-surface/50"
      >
        <span className="text-xs font-medium text-muted">Advanced: Parameter Overrides</span>
        <span className="text-muted text-xs">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="p-3 space-y-2">
          {BACKTEST_PARAMS.map(({ path, label }) => {
            const live = getLiveValue(path);
            const edited = path in overrides;
            return (
              <div key={path} className="flex items-center justify-between">
                <span className={`text-xs ${edited ? "text-foreground" : "text-muted"}`}>{label}</span>
                <input
                  type="number"
                  step="any"
                  placeholder={live?.toString() ?? ""}
                  value={overrides[path] ?? ""}
                  onChange={(e) => handleChange(path, e.target.value)}
                  className={`w-20 text-right text-xs font-mono px-2 py-1 bg-surface border rounded ${
                    edited ? "border-accent text-accent" : "border-border text-muted"
                  }`}
                />
              </div>
            );
          })}
          <button
            onClick={() => onChange({})}
            className="text-xs text-muted hover:text-foreground"
          >
            Reset to Live
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Integrate into backtest Setup tab**

Import `ParameterOverridePanel` in the backtest setup component and render it below the existing config fields. Pass overrides state down and include them in the backtest run request as `parameter_overrides`.

- [ ] **Step 3: Verify build**

```bash
cd web && pnpm build
```

Expected: builds.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/backtest/components/ParameterOverridePanel.tsx
git commit -m "feat(backtest): add parameter override panel to setup tab"
```

---

### Task 18: Final Integration Test

End-to-end verification that all pieces work together.

**Deferred items:** The Compare tab "Parameter Differences" section (Spec Section 11) is intentionally deferred. It depends on backtest runs having `parameter_overrides` stored, which requires real usage to verify. Add it as a follow-up after the core feature is validated.

**Files:** (no new files)

- [ ] **Step 1: Run full backend test suite**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 2: Run frontend build**

```bash
cd web && pnpm build
```

Expected: builds with no errors.

- [ ] **Step 3: Run frontend tests**

```bash
cd web && npx vitest run
```

Expected: all tests pass (including new engine store and ApplyModal tests).

- [ ] **Step 4: Run frontend lint**

```bash
cd web && pnpm lint
```

Expected: no errors.

- [ ] **Step 5: Manual smoke test**

1. Open the app, navigate to More tab
2. Verify sub-tabs render (Settings, Risk, Engine, Backtest, ML, Alerts)
3. Click "Engine" — parameter dashboard loads with all categories
4. Click "Backtest" → "Optimize" tab — ATR optimization UI renders
5. Check a signal detail view — engine snapshot section appears (or "not available" for old signals)

- [ ] **Step 6: Final commit if any integration fixes needed**

```bash
git add -A
git commit -m "fix: integration adjustments for engine parameter dashboard"
```
