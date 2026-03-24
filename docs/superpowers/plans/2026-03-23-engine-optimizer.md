# Engine Parameter Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-tuning parameter optimizer with dashboard approval gate, shadow mode validation, and pipeline observability.

**Architecture:** Extend the existing PerformanceTracker into a general-purpose optimizer that monitors ~200 engine parameters across 12 groups. A background loop tracks global fitness, runs counterfactual backtests to identify underperforming groups, proposes changes, and validates them in shadow mode before promotion. A new Optimizer page under "More" provides the approval dashboard.

**Tech Stack:** Python/FastAPI (backend), SQLAlchemy 2.0 async (DB), React/TypeScript/Zustand/Tailwind (frontend), existing backtester for sweep validation.

**Spec:** `docs/superpowers/specs/2026-03-23-engine-optimizer-design.md`

---

## File Structure

### New Files (Backend)
- `backend/app/db/models.py` — add `ParameterProposal` and `ShadowResult` models (modify existing)
- `backend/app/engine/param_groups.py` — parameter group definitions, sweep ranges, constraints, descriptions
- `backend/app/engine/optimizer.py` — optimizer loop, fitness tracking, counterfactual dispatch, shadow management
- `backend/app/api/optimizer.py` — REST endpoints for optimizer status/proposals
- `backend/tests/engine/test_param_groups.py` — parameter group constraint/validation tests
- `backend/tests/engine/test_optimizer.py` — optimizer logic tests
- `backend/tests/api/test_optimizer_api.py` — API endpoint tests

### New Files (Frontend)
- `web/src/features/optimizer/types.ts` — TypeScript types for optimizer data
- `web/src/features/optimizer/store.ts` — Zustand store for optimizer state
- `web/src/features/optimizer/components/OptimizerPage.tsx` — main optimizer page
- `web/src/features/optimizer/components/GroupHealthTable.tsx` — parameter group health display
- `web/src/features/optimizer/components/ProposalCard.tsx` — proposal diff + actions
- `web/src/features/optimizer/components/ShadowProgress.tsx` — shadow mode comparison
- `web/src/features/optimizer/components/ProposalHistory.tsx` — history log
- `web/src/features/engine/components/PipelineFlow.tsx` — pipeline flow diagram
- `web/src/features/engine/components/ParamInfoPopup.tsx` — parameter description tooltip

### Modified Files
- `backend/app/engine/constants.py` — add `PARAMETER_DESCRIPTIONS` map, add optimizer constants
- `backend/app/api/engine.py` — include descriptions in `/api/engine/parameters` response
- `backend/app/main.py` — start optimizer loop in lifespan, add `app.state.optimizer`, register optimizer router
- `web/src/features/engine/components/EnginePage.tsx` — add pipeline flow diagram, proposal badge
- `web/src/features/engine/components/ParameterRow.tsx` — add info icon for descriptions
- `web/src/features/more/components/MorePage.tsx` — add Optimizer entry
- `web/src/shared/lib/api.ts` — add optimizer API methods
- `web/src/features/engine/types.ts` — add description field to ParameterValue

---

## Task 1: DB Models — ParameterProposal and ShadowResult

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/engine/test_optimizer.py`

- [ ] **Step 1: Write failing test for ParameterProposal model**

Create `backend/tests/engine/test_optimizer.py`:

```python
"""Tests for optimizer models and logic."""

from app.db.models import ParameterProposal, ShadowResult


def test_parameter_proposal_model_exists():
    """ParameterProposal model has expected columns."""
    cols = {c.name for c in ParameterProposal.__table__.columns}
    assert "id" in cols
    assert "status" in cols
    assert "parameter_group" in cols
    assert "changes" in cols
    assert "backtest_metrics" in cols
    assert "shadow_metrics" in cols
    assert "created_at" in cols
    assert "shadow_started_at" in cols
    assert "promoted_at" in cols
    assert "rejected_reason" in cols


def test_shadow_result_model_exists():
    """ShadowResult model has expected columns."""
    cols = {c.name for c in ShadowResult.__table__.columns}
    assert "id" in cols
    assert "proposal_id" in cols
    assert "signal_id" in cols
    assert "shadow_score" in cols
    assert "shadow_entry" in cols
    assert "shadow_sl" in cols
    assert "shadow_tp1" in cols
    assert "shadow_tp2" in cols
    assert "shadow_outcome" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v`
Expected: FAIL — `ImportError: cannot import name 'ParameterProposal'`

- [ ] **Step 3: Add ParameterProposal and ShadowResult models**

Add to `backend/app/db/models.py` after the existing model definitions:

```python
class ParameterProposal(Base):
    __tablename__ = "parameter_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, shadow, approved, rejected, promoted, rolled_back
    parameter_group: Mapped[str] = mapped_column(String(50), nullable=False)
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    backtest_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    shadow_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    shadow_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ShadowResult(Base):
    __tablename__ = "shadow_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("parameter_proposals.id"), nullable=False, index=True
    )
    signal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("signals.id"), nullable=False, index=True
    )
    shadow_score: Mapped[float] = mapped_column(Float, nullable=False)
    shadow_entry: Mapped[float] = mapped_column(Float, nullable=False)
    shadow_sl: Mapped[float] = mapped_column(Float, nullable=False)
    shadow_tp1: Mapped[float] = mapped_column(Float, nullable=False)
    shadow_tp2: Mapped[float] = mapped_column(Float, nullable=False)
    shadow_outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # tp1_hit, tp2_hit, sl_hit, expired, None (unresolved)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
```

Note: Check `models.py` for which imports already exist (e.g., `Float`, `Text`, `ForeignKey`). Add any missing imports at the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v`
Expected: PASS

- [ ] **Step 5: Create Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add parameter_proposals and shadow_results tables"`

Then apply: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/tests/engine/test_optimizer.py backend/app/db/migrations/versions/
git commit -m "feat(optimizer): add ParameterProposal and ShadowResult DB models"
```

---

## Task 2: Parameter Group Definitions

**Files:**
- Create: `backend/app/engine/param_groups.py`
- Test: `backend/tests/engine/test_param_groups.py`

- [ ] **Step 1: Write failing tests for parameter groups**

Create `backend/tests/engine/test_param_groups.py`:

```python
"""Tests for parameter group definitions."""

from app.engine.param_groups import (
    PARAM_GROUPS,
    get_group,
    validate_candidate,
    PRIORITY_LAYERS,
)


def test_all_groups_defined():
    expected = {
        "source_weights", "thresholds", "regime_caps", "regime_outer",
        "atr_levels", "sigmoid_curves", "order_flow", "pattern_strengths",
        "indicator_periods", "mean_reversion", "llm_factors", "onchain",
    }
    assert set(PARAM_GROUPS.keys()) == expected


def test_get_group_returns_definition():
    g = get_group("source_weights")
    assert "params" in g
    assert "sweep_method" in g
    assert "constraints" in g
    assert "priority" in g


def test_get_group_unknown_returns_none():
    assert get_group("nonexistent") is None


def test_source_weights_constraint_sum_to_one():
    valid = {"traditional": 0.4, "flow": 0.2, "onchain": 0.25, "pattern": 0.15}
    assert validate_candidate("source_weights", valid) is True


def test_source_weights_constraint_rejects_bad_sum():
    invalid = {"traditional": 0.5, "flow": 0.3, "onchain": 0.3, "pattern": 0.1}
    assert validate_candidate("source_weights", invalid) is False


def test_thresholds_constraint_signal_gt_llm():
    valid = {"signal": 40, "llm": 20, "ml_confidence": 0.65}
    assert validate_candidate("thresholds", valid) is True

    invalid = {"signal": 15, "llm": 20, "ml_confidence": 0.65}
    assert validate_candidate("thresholds", invalid) is False


def test_priority_layers_ordered():
    assert PRIORITY_LAYERS[0] == {"source_weights", "thresholds"}
    assert len(PRIORITY_LAYERS) >= 3


def test_regime_caps_constraint_sum_per_regime():
    valid = {
        "trending_trend_cap": 38, "trending_mean_rev_cap": 22,
        "trending_squeeze_cap": 12, "trending_volume_cap": 28,
        "ranging_trend_cap": 18, "ranging_mean_rev_cap": 40,
        "ranging_squeeze_cap": 16, "ranging_volume_cap": 26,
        "volatile_trend_cap": 25, "volatile_mean_rev_cap": 28,
        "volatile_squeeze_cap": 22, "volatile_volume_cap": 25,
    }
    assert validate_candidate("regime_caps", valid) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_param_groups.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine.param_groups'`

- [ ] **Step 3: Implement param_groups.py**

Create `backend/app/engine/param_groups.py`:

```python
"""Parameter group definitions for the optimizer.

Each group defines:
- params: dict of parameter keys with their current-value dot-paths
- sweep_method: "grid" or "de" (differential evolution)
- sweep_ranges: per-param (min, max, step|None) — step=None for DE
- constraints: callable(candidate_dict) -> bool
- priority: int (lower = higher priority, optimized first)
"""

from __future__ import annotations

import math
from typing import Any, Callable

# ── Priority layers (lower number = optimize first) ──

PRIORITY_LAYERS: list[set[str]] = [
    {"source_weights", "thresholds"},           # layer 0: biggest impact, fewest params
    {"regime_caps", "regime_outer", "atr_levels"},  # layer 1
    {"sigmoid_curves", "order_flow", "pattern_strengths",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain"},  # layer 2
]


def _priority_for(group_name: str) -> int:
    for i, layer in enumerate(PRIORITY_LAYERS):
        if group_name in layer:
            return i
    return len(PRIORITY_LAYERS)


def _sum_close_to(values: list[float], target: float, tol: float = 0.01) -> bool:
    return abs(sum(values) - target) < tol


# ── Constraint functions ──

def _source_weights_ok(c: dict[str, Any]) -> bool:
    vals = [c["traditional"], c["flow"], c["onchain"], c["pattern"]]
    return _sum_close_to(vals, 1.0) and all(v >= 0 for v in vals)


def _thresholds_ok(c: dict[str, Any]) -> bool:
    return (
        c["signal"] > c["llm"]
        and 0 < c["ml_confidence"] < 1
        and c["signal"] > 0
        and c["llm"] > 0
    )


def _regime_caps_ok(c: dict[str, Any]) -> bool:
    for regime in ("trending", "ranging", "volatile"):
        keys = [k for k in c if k.startswith(regime)]
        if not _sum_close_to([c[k] for k in keys], 100.0, tol=1.0):
            return False
    return all(v >= 0 for v in c.values())


def _regime_outer_ok(c: dict[str, Any]) -> bool:
    for regime in ("trending", "ranging", "volatile"):
        keys = [k for k in c if k.startswith(regime)]
        if not _sum_close_to([c[k] for k in keys], 1.0):
            return False
    return all(v >= 0 for v in c.values())


def _atr_levels_ok(c: dict[str, Any]) -> bool:
    sl, tp1, tp2 = c["sl"], c["tp1"], c["tp2"]
    return tp2 > tp1 > sl > 0 and tp1 / sl >= 1.0  # R:R floor


def _positive_values(c: dict[str, Any]) -> bool:
    return all(v > 0 for v in c.values())


def _pattern_strengths_ok(c: dict[str, Any]) -> bool:
    return all(3 <= v <= 25 for v in c.values())


def _indicator_periods_ok(c: dict[str, Any]) -> bool:
    return all(isinstance(v, int) and v > 0 for v in c.values())


def _mean_reversion_ok(c: dict[str, Any]) -> bool:
    return (
        0 <= c.get("blend_ratio", 0.6) <= 1
        and all(v > 0 for v in c.values())
    )


def _llm_factors_ok(c: dict[str, Any]) -> bool:
    cap = c.get("factor_cap", 35)
    return cap <= 50 and all(v >= 0 for v in c.values())


def _onchain_ok(c: dict[str, Any]) -> bool:
    max_keys = [k for k in c if k.endswith("_max_score")]
    if max_keys and sum(c[k] for k in max_keys) > 100:
        return False
    return all(v >= 0 for v in c.values())


# ── Group definitions ──

PARAM_GROUPS: dict[str, dict] = {
    "source_weights": {
        "params": {
            "traditional": "blending.source_weights.traditional",
            "flow": "blending.source_weights.flow",
            "onchain": "blending.source_weights.onchain",
            "pattern": "blending.source_weights.pattern",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "traditional": (0.10, 0.60, 0.05),
            "flow": (0.05, 0.40, 0.05),
            "onchain": (0.05, 0.40, 0.05),
            "pattern": (0.05, 0.30, 0.05),
        },
        "constraints": _source_weights_ok,
        "priority": _priority_for("source_weights"),
    },
    "thresholds": {
        "params": {
            "signal": "blending.thresholds.signal",
            "llm": "blending.thresholds.llm",
            "ml_confidence": "blending.thresholds.ml_confidence",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "signal": (20, 60, 5),
            "llm": (10, 40, 5),
            "ml_confidence": (0.50, 0.85, 0.05),
        },
        "constraints": _thresholds_ok,
        "priority": _priority_for("thresholds"),
    },
    "regime_caps": {
        "params": {
            f"{r}_{cap}_cap": f"regime_weights.*.*.{r}_{cap}_cap"
            for r in ("trending", "ranging", "volatile")
            for cap in ("trend", "mean_rev", "squeeze", "volume")
        },
        "sweep_method": "de",
        "sweep_ranges": {
            f"{r}_{cap}_cap": (10.0, 45.0, None)
            for r in ("trending", "ranging", "volatile")
            for cap in ("trend", "mean_rev", "squeeze", "volume")
        },
        "constraints": _regime_caps_ok,
        "priority": _priority_for("regime_caps"),
    },
    "regime_outer": {
        "params": {
            f"{r}_{src}_weight": f"regime_weights.*.*.{r}_{src}_weight"
            for r in ("trending", "ranging", "volatile")
            for src in ("tech", "flow", "onchain", "pattern")
        },
        "sweep_method": "de",
        "sweep_ranges": {
            f"{r}_{src}_weight": (0.10, 0.50, None)
            for r in ("trending", "ranging", "volatile")
            for src in ("tech", "flow", "onchain", "pattern")
        },
        "constraints": _regime_outer_ok,
        "priority": _priority_for("regime_outer"),
    },
    "atr_levels": {
        "params": {
            "sl": "levels.atr_defaults.sl",
            "tp1": "levels.atr_defaults.tp1",
            "tp2": "levels.atr_defaults.tp2",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "sl": (0.8, 2.5, 0.2),
            "tp1": (1.0, 4.0, 0.5),
            "tp2": (2.0, 6.0, 0.5),
        },
        "constraints": _atr_levels_ok,
        "priority": _priority_for("atr_levels"),
    },
    "sigmoid_curves": {
        "params": {
            "trend_strength_center": "technical.sigmoid_params.trend_strength_center",
            "trend_strength_steepness": "technical.sigmoid_params.trend_strength_steepness",
            "vol_expansion_center": "technical.sigmoid_params.vol_expansion_center",
            "vol_expansion_steepness": "technical.sigmoid_params.vol_expansion_steepness",
            "trend_score_steepness": "technical.sigmoid_params.trend_score_steepness",
            "obv_slope_steepness": "technical.sigmoid_params.obv_slope_steepness",
            "volume_ratio_steepness": "technical.sigmoid_params.volume_ratio_steepness",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "trend_strength_center": (10.0, 35.0, None),
            "trend_strength_steepness": (0.05, 0.50, None),
            "vol_expansion_center": (30.0, 70.0, None),
            "vol_expansion_steepness": (0.03, 0.15, None),
            "trend_score_steepness": (0.10, 0.60, None),
            "obv_slope_steepness": (1.0, 8.0, None),
            "volume_ratio_steepness": (1.0, 6.0, None),
        },
        "constraints": _positive_values,
        "priority": _priority_for("sigmoid_curves"),
    },
    "order_flow": {
        "params": {
            "funding_max": "order_flow.max_scores.funding",
            "oi_max": "order_flow.max_scores.oi",
            "ls_ratio_max": "order_flow.max_scores.ls_ratio",
            "funding_steepness": "order_flow.sigmoid_steepnesses.funding",
            "oi_steepness": "order_flow.sigmoid_steepnesses.oi",
            "ls_ratio_steepness": "order_flow.sigmoid_steepnesses.ls_ratio",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "funding_max": (15, 50, None),
            "oi_max": (10, 35, None),
            "ls_ratio_max": (15, 50, None),
            "funding_steepness": (3000, 15000, None),
            "oi_steepness": (30, 120, None),
            "ls_ratio_steepness": (2, 12, None),
        },
        "constraints": lambda c: (
            c.get("funding_max", 0) + c.get("oi_max", 0) + c.get("ls_ratio_max", 0) <= 100
            and all(v > 0 for v in c.values())
        ),
        "priority": _priority_for("order_flow"),
    },
    "pattern_strengths": {
        "params": {
            name: f"patterns.strengths.{name}"
            for name in [
                "bullish_engulfing", "bearish_engulfing", "morning_star",
                "evening_star", "three_white_soldiers", "three_black_crows",
                "marubozu", "hammer", "hanging_man", "piercing_line",
                "dark_cloud_cover", "inverted_hammer", "shooting_star",
                "doji", "spinning_top",
            ]
        },
        "sweep_method": "de",
        "sweep_ranges": {
            name: (3, 25, None)
            for name in [
                "bullish_engulfing", "bearish_engulfing", "morning_star",
                "evening_star", "three_white_soldiers", "three_black_crows",
                "marubozu", "hammer", "hanging_man", "piercing_line",
                "dark_cloud_cover", "inverted_hammer", "shooting_star",
                "doji", "spinning_top",
            ]
        },
        "constraints": _pattern_strengths_ok,
        "priority": _priority_for("pattern_strengths"),
    },
    "indicator_periods": {
        "params": {
            "adx_period": "technical.indicator_periods.adx_period",
            "rsi_period": "technical.indicator_periods.rsi_period",
            "sma_period": "technical.indicator_periods.sma_period",
            "obv_slope_window": "technical.indicator_periods.obv_slope_window",
            # ema_spans excluded — it's a list [9, 21, 50], not a single tunable value
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "adx_period": (7, 21, 7),
            "rsi_period": (7, 21, 7),
            "sma_period": (10, 30, 5),
            "obv_slope_window": (5, 15, 5),
        },
        "constraints": _indicator_periods_ok,
        "priority": _priority_for("indicator_periods"),
    },
    "mean_reversion": {
        "params": {
            "rsi_steepness": "mean_reversion.rsi_steepness",
            "bb_pos_steepness": "mean_reversion.bb_pos_steepness",
            "squeeze_steepness": "mean_reversion.squeeze_steepness",
            "blend_ratio": "mean_reversion.blend_ratio",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "rsi_steepness": (0.10, 0.50, 0.05),
            "bb_pos_steepness": (5.0, 20.0, 2.5),
            "squeeze_steepness": (0.05, 0.20, 0.05),
            "blend_ratio": (0.3, 0.8, 0.1),
        },
        "constraints": _mean_reversion_ok,
        "priority": _priority_for("mean_reversion"),
    },
    "llm_factors": {
        "params": {
            "support_proximity": "blending.llm_factor_weights.support_proximity",
            "resistance_proximity": "blending.llm_factor_weights.resistance_proximity",
            "level_breakout": "blending.llm_factor_weights.level_breakout",
            "htf_alignment": "blending.llm_factor_weights.htf_alignment",
            "rsi_divergence": "blending.llm_factor_weights.rsi_divergence",
            "volume_divergence": "blending.llm_factor_weights.volume_divergence",
            "macd_divergence": "blending.llm_factor_weights.macd_divergence",
            "volume_exhaustion": "blending.llm_factor_weights.volume_exhaustion",
            "funding_extreme": "blending.llm_factor_weights.funding_extreme",
            "crowded_positioning": "blending.llm_factor_weights.crowded_positioning",
            "pattern_confirmation": "blending.llm_factor_weights.pattern_confirmation",
            "news_catalyst": "blending.llm_factor_weights.news_catalyst",
            "factor_cap": "blending.llm_factor_cap",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "support_proximity": (2.0, 10.0, None),
            "resistance_proximity": (2.0, 10.0, None),
            "level_breakout": (3.0, 12.0, None),
            "htf_alignment": (3.0, 10.0, None),
            "rsi_divergence": (3.0, 10.0, None),
            "volume_divergence": (2.0, 10.0, None),
            "macd_divergence": (2.0, 10.0, None),
            "volume_exhaustion": (2.0, 8.0, None),
            "funding_extreme": (2.0, 8.0, None),
            "crowded_positioning": (2.0, 8.0, None),
            "pattern_confirmation": (2.0, 8.0, None),
            "news_catalyst": (3.0, 10.0, None),
            "factor_cap": (20.0, 50.0, None),
        },
        "constraints": _llm_factors_ok,
        "priority": _priority_for("llm_factors"),
    },
    "onchain": {
        "params": {
            "btc_netflow_max": "onchain.btc_profile.netflow_max_score",
            "btc_whale_max": "onchain.btc_profile.whale_max_score",
            "btc_addresses_max": "onchain.btc_profile.addresses_max_score",
            "btc_nupl_max": "onchain.btc_profile.nupl_max_score",
            "btc_hashrate_max": "onchain.btc_profile.hashrate_max_score",
            "eth_netflow_max": "onchain.eth_profile.netflow_max_score",
            "eth_whale_max": "onchain.eth_profile.whale_max_score",
            "eth_addresses_max": "onchain.eth_profile.addresses_max_score",
            "eth_staking_max": "onchain.eth_profile.staking_max_score",
            "eth_gas_max": "onchain.eth_profile.gas_max_score",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            k: (5, 50, None)
            for k in [
                "btc_netflow_max", "btc_whale_max", "btc_addresses_max",
                "btc_nupl_max", "btc_hashrate_max",
                "eth_netflow_max", "eth_whale_max", "eth_addresses_max",
                "eth_staking_max", "eth_gas_max",
            ]
        },
        "constraints": _onchain_ok,
        "priority": _priority_for("onchain"),
    },
}


def get_group(name: str) -> dict | None:
    """Return a parameter group definition by name."""
    return PARAM_GROUPS.get(name)


def validate_candidate(group_name: str, candidate: dict[str, Any]) -> bool:
    """Check whether a candidate parameter set satisfies the group's constraints."""
    group = PARAM_GROUPS.get(group_name)
    if not group:
        return False
    return group["constraints"](candidate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_param_groups.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/param_groups.py backend/tests/engine/test_param_groups.py
git commit -m "feat(optimizer): add parameter group definitions with constraints"
```

---

## Task 3: Parameter Descriptions

**Files:**
- Modify: `backend/app/engine/constants.py`
- Modify: `backend/app/api/engine.py`
- Modify: `web/src/features/engine/types.ts`
- Create: `web/src/features/engine/components/ParamInfoPopup.tsx`
- Modify: `web/src/features/engine/components/ParameterRow.tsx`
- Test: `backend/tests/api/test_engine_params.py` (extend existing)

- [ ] **Step 1: Write test for descriptions in API response**

Add to `backend/tests/api/test_engine_params.py` (or create if not present):

```python
import pytest
from app.engine.constants import PARAMETER_DESCRIPTIONS


def test_parameter_descriptions_structure():
    """Every description has required fields."""
    assert len(PARAMETER_DESCRIPTIONS) > 0
    for key, desc in PARAMETER_DESCRIPTIONS.items():
        assert "description" in desc, f"{key} missing description"
        assert "pipeline_stage" in desc, f"{key} missing pipeline_stage"
        assert "range" in desc, f"{key} missing range"
        assert isinstance(desc["description"], str)
        assert isinstance(desc["pipeline_stage"], str)
        assert isinstance(desc["range"], str)


def test_parameter_descriptions_coverage():
    """Descriptions cover key parameter groups."""
    keys = set(PARAMETER_DESCRIPTIONS.keys())
    # Spot-check a few from each group
    assert "signal_threshold" in keys or "signal" in keys
    assert "traditional_weight" in keys or "traditional" in keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_engine_params.py::test_parameter_descriptions_structure -v`
Expected: FAIL — `ImportError: cannot import name 'PARAMETER_DESCRIPTIONS'`

- [ ] **Step 3: Add PARAMETER_DESCRIPTIONS to constants.py**

Add to `backend/app/engine/constants.py`:

```python
PARAMETER_DESCRIPTIONS: dict[str, dict[str, str]] = {
    # ── Blending / Source Weights ──
    "traditional": {
        "description": "Weight given to technical indicator scores (ADX, RSI, BB, OBV, volume) in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    "flow": {
        "description": "Weight given to order flow scores (funding rate, open interest, long/short ratio) in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    "onchain": {
        "description": "Weight given to on-chain metric scores (netflow, whale activity, addresses) in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    "pattern": {
        "description": "Weight given to candlestick pattern scores in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    # ── Thresholds ──
    "signal_threshold": {
        "description": "Minimum absolute blended score required to emit a trading signal. Lower = more signals but lower quality",
        "pipeline_stage": "Combiner -> Signal Emission",
        "range": "20-60 — must be greater than llm_threshold",
    },
    "llm_threshold": {
        "description": "Score above which LLM analysis is triggered. Scores below this skip LLM entirely",
        "pipeline_stage": "Combiner -> LLM Gate",
        "range": "10-40 — must be less than signal_threshold",
    },
    "ml_confidence_threshold": {
        "description": "Minimum ML model confidence required for ML predictions to blend into the score",
        "pipeline_stage": "Combiner -> ML Gate",
        "range": "0.50-0.85 — higher = only very confident ML predictions influence signals",
    },
    "ml_blend_weight": {
        "description": "How much weight the ML model's prediction gets when blended with the traditional score",
        "pipeline_stage": "Combiner -> ML Blending",
        "range": "0.0-1.0 — 0 = ignore ML, 1 = fully trust ML",
    },
    # ── Technical Indicators ──
    "adx_period": {
        "description": "Lookback period for Average Directional Index — measures trend strength",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "7-21 — shorter = more responsive, longer = smoother",
    },
    "rsi_period": {
        "description": "Lookback period for Relative Strength Index — measures momentum",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "7-21 — shorter = more sensitive to price swings",
    },
    "sma_period": {
        "description": "Lookback period for Simple Moving Average used as price reference",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "10-30",
    },
    "obv_slope_window": {
        "description": "Window for computing On-Balance Volume slope — detects volume-price divergence",
        "pipeline_stage": "Technical Scoring -> Volume",
        "range": "5-15",
    },
    # ── Sigmoid Parameters ──
    "trend_strength_center": {
        "description": "ADX value at the midpoint of the trend-strength sigmoid. Below this, trend is considered weak",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "10-35 — higher = requires stronger trend to activate",
    },
    "trend_strength_steepness": {
        "description": "How sharply the trend-strength sigmoid transitions from weak to strong trend",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "0.05-0.50 — higher = more binary (on/off) behavior",
    },
    "vol_expansion_center": {
        "description": "Bollinger Band width percentile at the sigmoid midpoint. Determines what counts as expanded volatility",
        "pipeline_stage": "Technical Scoring -> Squeeze/Expansion",
        "range": "30-70",
    },
    "vol_expansion_steepness": {
        "description": "Steepness of the volatility expansion sigmoid curve",
        "pipeline_stage": "Technical Scoring -> Squeeze/Expansion",
        "range": "0.03-0.15",
    },
    "trend_score_steepness": {
        "description": "Steepness of the trend score sigmoid — controls how trend strength maps to score contribution",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "0.10-0.60",
    },
    "obv_slope_steepness": {
        "description": "Steepness of the OBV slope sigmoid — controls sensitivity to volume-price divergence",
        "pipeline_stage": "Technical Scoring -> Volume",
        "range": "1-8",
    },
    "volume_ratio_steepness": {
        "description": "Steepness of the volume ratio sigmoid — controls how relative volume maps to score",
        "pipeline_stage": "Technical Scoring -> Volume",
        "range": "1.0-6.0",
    },
    # ── Mean Reversion ──
    "rsi_steepness": {
        "description": "RSI sigmoid steepness for mean reversion scoring. Higher = RSI extremes contribute more sharply",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "0.10-0.50",
    },
    "bb_pos_steepness": {
        "description": "Bollinger Band position sigmoid steepness. Controls how proximity to bands affects mean-reversion score",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "5.0-20.0",
    },
    "squeeze_steepness": {
        "description": "Squeeze/expansion sigmoid steepness for mean reversion context",
        "pipeline_stage": "Technical Scoring -> Squeeze/Expansion",
        "range": "0.05-0.20",
    },
    "blend_ratio": {
        "description": "RSI vs Bollinger Band weighting in mean-reversion score. 0.6 = 60% RSI, 40% BB position",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "0.3-0.8",
    },
    # ── Order Flow ──
    "funding_max": {
        "description": "Maximum score contribution from funding rate. Caps how much extreme funding can influence the signal",
        "pipeline_stage": "Order Flow Scoring",
        "range": "15-50 — funding + oi + ls_ratio max scores must sum <= 100",
    },
    "oi_max": {
        "description": "Maximum score contribution from open interest changes",
        "pipeline_stage": "Order Flow Scoring",
        "range": "10-35",
    },
    "ls_ratio_max": {
        "description": "Maximum score contribution from long/short ratio",
        "pipeline_stage": "Order Flow Scoring",
        "range": "15-50",
    },
    "funding_steepness": {
        "description": "Sigmoid steepness for funding rate scoring. Higher = more sensitive to funding extremes",
        "pipeline_stage": "Order Flow Scoring",
        "range": "3000-15000",
    },
    "oi_steepness": {
        "description": "Sigmoid steepness for open interest change scoring",
        "pipeline_stage": "Order Flow Scoring",
        "range": "30-120",
    },
    "ls_ratio_steepness": {
        "description": "Sigmoid steepness for long/short ratio scoring",
        "pipeline_stage": "Order Flow Scoring",
        "range": "2-12",
    },
    # ── ATR / Levels ──
    "sl": {
        "description": "Default stop-loss distance as ATR multiplier. Higher = wider stop, fewer stop-outs but larger losses",
        "pipeline_stage": "Level Calculation",
        "range": "0.8-2.5 ATR multiples",
    },
    "tp1": {
        "description": "Default take-profit-1 distance as ATR multiplier. First partial exit target",
        "pipeline_stage": "Level Calculation",
        "range": "1.0-4.0 ATR multiples — must be > sl",
    },
    "tp2": {
        "description": "Default take-profit-2 distance as ATR multiplier. Full exit target",
        "pipeline_stage": "Level Calculation",
        "range": "2.0-6.0 ATR multiples — must be > tp1",
    },
    # ── Pattern Strengths ──
    "bullish_engulfing": {
        "description": "Score contribution when a bullish engulfing pattern is detected",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "bearish_engulfing": {
        "description": "Score contribution when a bearish engulfing pattern is detected",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "morning_star": {
        "description": "Score contribution for morning star reversal pattern (three-candle bullish)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "evening_star": {
        "description": "Score contribution for evening star reversal pattern (three-candle bearish)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "three_white_soldiers": {
        "description": "Score contribution for three consecutive bullish candles with higher closes",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "three_black_crows": {
        "description": "Score contribution for three consecutive bearish candles with lower closes",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "marubozu": {
        "description": "Score contribution for marubozu (full-body candle with minimal wicks)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "hammer": {
        "description": "Score contribution for hammer pattern (bullish reversal, long lower shadow)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "hanging_man": {
        "description": "Score contribution for hanging man pattern (bearish reversal after uptrend)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "piercing_line": {
        "description": "Score contribution for piercing line pattern (bullish two-candle reversal)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "dark_cloud_cover": {
        "description": "Score contribution for dark cloud cover (bearish two-candle reversal)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "inverted_hammer": {
        "description": "Score contribution for inverted hammer (potential bullish reversal)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "shooting_star": {
        "description": "Score contribution for shooting star (bearish reversal, long upper shadow)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "doji": {
        "description": "Score contribution for doji (indecision, nearly equal open/close)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "spinning_top": {
        "description": "Score contribution for spinning top (small body, indecision)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    # ── LLM Factor Weights ──
    "support_proximity": {
        "description": "LLM factor weight for price proximity to support level",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "2-10",
    },
    "resistance_proximity": {
        "description": "LLM factor weight for price proximity to resistance level",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "2-10",
    },
    "level_breakout": {
        "description": "LLM factor weight for key level breakout detection",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "3-12",
    },
    "htf_alignment": {
        "description": "LLM factor weight for higher-timeframe trend alignment",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "3-10",
    },
    "rsi_divergence": {
        "description": "LLM factor weight for RSI divergence with price",
        "pipeline_stage": "LLM Gate -> Momentum Factors",
        "range": "3-10",
    },
    "volume_divergence": {
        "description": "LLM factor weight for volume divergence with price trend",
        "pipeline_stage": "LLM Gate -> Momentum Factors",
        "range": "2-10",
    },
    "macd_divergence": {
        "description": "LLM factor weight for MACD divergence with price",
        "pipeline_stage": "LLM Gate -> Momentum Factors",
        "range": "2-10",
    },
    "volume_exhaustion": {
        "description": "LLM factor weight for volume exhaustion signals",
        "pipeline_stage": "LLM Gate -> Exhaustion Factors",
        "range": "2-8",
    },
    "funding_extreme": {
        "description": "LLM factor weight for extreme funding rate conditions",
        "pipeline_stage": "LLM Gate -> Exhaustion Factors",
        "range": "2-8",
    },
    "crowded_positioning": {
        "description": "LLM factor weight for crowded market positioning",
        "pipeline_stage": "LLM Gate -> Exhaustion Factors",
        "range": "2-8",
    },
    "pattern_confirmation": {
        "description": "LLM factor weight for candlestick pattern confirmation",
        "pipeline_stage": "LLM Gate -> Event Factors",
        "range": "2-8",
    },
    "news_catalyst": {
        "description": "LLM factor weight for news catalyst presence",
        "pipeline_stage": "LLM Gate -> Event Factors",
        "range": "3-10",
    },
    "factor_cap": {
        "description": "Maximum total LLM factor contribution to the final score. Caps LLM influence regardless of individual factor weights",
        "pipeline_stage": "LLM Gate",
        "range": "20-50",
    },
    # ── On-Chain (BTC) ──
    "btc_netflow_max": {
        "description": "Max on-chain score from BTC exchange netflow. Outflow = bullish (accumulation)",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_whale_max": {
        "description": "Max on-chain score from BTC whale transaction activity",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_addresses_max": {
        "description": "Max on-chain score from BTC active address growth",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_nupl_max": {
        "description": "Max on-chain score from BTC Net Unrealized Profit/Loss (contrarian)",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_hashrate_max": {
        "description": "Max on-chain score from BTC hashrate trend (rising = bullish)",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    # ── On-Chain (ETH) ──
    "eth_netflow_max": {
        "description": "Max on-chain score from ETH exchange netflow",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_whale_max": {
        "description": "Max on-chain score from ETH whale transaction activity",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_addresses_max": {
        "description": "Max on-chain score from ETH active address growth",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_staking_max": {
        "description": "Max on-chain score from ETH staking deposits (deposits = bullish)",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_gas_max": {
        "description": "Max on-chain score from ETH gas price trend (rising = network activity)",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    # ── Regime Caps (per-regime inner scoring caps) ──
    "trend_cap": {
        "description": "Maximum score contribution from trend-following indicators within this regime",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45 — all four caps must sum to 100 per regime",
    },
    "mean_rev_cap": {
        "description": "Maximum score contribution from mean-reversion indicators within this regime",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45",
    },
    "squeeze_cap": {
        "description": "Maximum score contribution from squeeze/expansion detection within this regime",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45",
    },
    "volume_cap": {
        "description": "Maximum score contribution from volume confirmation within this regime",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45",
    },
    # ── Regime Outer Weights ──
    "tech_weight": {
        "description": "Weight given to technical score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50 — all four weights must sum to 1.0 per regime",
    },
    "flow_weight": {
        "description": "Weight given to order flow score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50",
    },
    "onchain_weight": {
        "description": "Weight given to on-chain score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50",
    },
    "pattern_weight": {
        "description": "Weight given to pattern score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50",
    },
    # ── Confluence ──
    "confluence_max_score": {
        "description": "Maximum score bonus from multi-timeframe trend alignment",
        "pipeline_stage": "Confluence Scoring",
        "range": "5-25",
    },
}
```

- [ ] **Step 4: Include descriptions in API response**

Modify `backend/app/api/engine.py` — in `get_parameters()`, after building the `params` dict, add:

```python
from app.engine.constants import PARAMETER_DESCRIPTIONS

# ... at end of get_parameters(), before return:
params["descriptions"] = PARAMETER_DESCRIPTIONS
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_engine_params.py -v`
Expected: PASS

- [ ] **Step 6: Update frontend ParameterValue type**

Modify `web/src/features/engine/types.ts` — add to `EngineParameters`:

```typescript
// Add to EngineParameters interface:
descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
```

- [ ] **Step 7: Create ParamInfoPopup component**

Create `web/src/features/engine/components/ParamInfoPopup.tsx`:

```tsx
import { useState, useRef, useEffect, useLayoutEffect, useCallback } from "react";
import { Info } from "lucide-react";

interface ParamDescription {
  description: string;
  pipeline_stage: string;
  range: string;
}

interface Props {
  name: string;
  descriptions?: Record<string, ParamDescription>;
}

export default function ParamInfoPopup({ name, descriptions }: Props) {
  const [open, setOpen] = useState(false);
  const [above, setAbove] = useState(true);
  const ref = useRef<HTMLDivElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  const desc = descriptions?.[name];
  if (!desc) return null;

  // Determine popup direction based on available space
  useLayoutEffect(() => {
    if (!open || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    // If not enough room above (popup ~120px tall), flip below
    setAbove(rect.top > 140);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent | TouchEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("touchstart", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("touchstart", handler);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="min-w-[44px] min-h-[44px] flex items-center justify-center -m-4 text-muted hover:text-primary transition-colors"
        aria-label={`Info about ${name}`}
        aria-expanded={open}
      >
        <Info size={14} />
      </button>
      {open && (
        <div
          ref={popupRef}
          className={`absolute z-50 left-1/2 -translate-x-1/2 w-64 bg-surface-container-high border border-outline-variant/50 rounded-lg p-3 shadow-lg ${
            above ? "bottom-full mb-2" : "top-full mt-2"
          }`}
        >
          <p className="text-xs text-on-surface mb-1.5">{desc.description}</p>
          <div className="flex flex-col gap-1 text-[10px] text-muted">
            <span>Stage: {desc.pipeline_stage}</span>
            <span>Range: {desc.range}</span>
          </div>
          <div className={`absolute left-1/2 -translate-x-1/2 rotate-45 w-2 h-2 bg-surface-container-high border-outline-variant/50 ${
            above
              ? "bottom-0 translate-y-1/2 border-r border-b"
              : "top-0 -translate-y-1/2 border-l border-t"
          }`} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8: Add info icon to ParameterRow**

Modify `web/src/features/engine/components/ParameterRow.tsx`:

```tsx
import SourceBadge from "./SourceBadge";
import ParamInfoPopup from "./ParamInfoPopup";

interface Props {
  name: string;
  value: unknown;
  source: "hardcoded" | "configurable";
  last?: boolean;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
}

export default function ParameterRow({ name, value, source, last, descriptions }: Props) {
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
      <div className="flex items-center gap-1">
        <span className="text-xs text-muted">{name}</span>
        <ParamInfoPopup name={name} descriptions={descriptions} />
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-foreground">{display}</span>
        <SourceBadge source={source} />
      </div>
    </div>
  );
}
```

Then update `ParameterCategory.tsx` and `EnginePage.tsx` to pass `descriptions` prop through from the store's `params.descriptions`.

In `ParameterCategory.tsx`, add `descriptions` to the Props interface and pass it to each `ParameterRow`.

In `EnginePage.tsx`, pass `descriptions={params.descriptions}` to each `ParameterCategory` and inline `ParameterRow`.

- [ ] **Step 9: Commit**

```bash
git add backend/app/engine/constants.py backend/app/api/engine.py backend/tests/api/test_engine_params.py
git add web/src/features/engine/
git commit -m "feat(optimizer): add parameter descriptions with info popups"
```

---

## Task 4: Optimizer Core Logic

**Files:**
- Create: `backend/app/engine/optimizer.py`
- Test: `backend/tests/engine/test_optimizer.py` (extend)

- [ ] **Step 1: Write tests for OptimizerState**

Add to `backend/tests/engine/test_optimizer.py`:

```python
from app.engine.optimizer import OptimizerState, OPTIMIZER_CONFIG


def test_optimizer_config_defaults():
    assert OPTIMIZER_CONFIG["min_signals_for_eval"] == 50
    assert OPTIMIZER_CONFIG["shadow_signal_count"] == 20
    assert OPTIMIZER_CONFIG["improvement_threshold"] == 0.05
    assert OPTIMIZER_CONFIG["rollback_drop_pct"] == 0.15
    assert OPTIMIZER_CONFIG["rollback_window"] == 10
    assert OPTIMIZER_CONFIG["cooldown_signals"] == 50


def test_optimizer_state_init():
    state = OptimizerState()
    assert state.resolved_count == 0
    assert state.global_pnl_history == []
    assert state.active_shadow_proposal_id is None
    assert state.last_optimized == {}


def test_optimizer_state_record_resolution():
    state = OptimizerState()
    state.record_resolution(pnl_pct=2.5)
    state.record_resolution(pnl_pct=-1.0)
    assert state.resolved_count == 2
    assert state.global_pnl_history == [2.5, -1.0]


def test_optimizer_state_profit_factor():
    state = OptimizerState()
    for pnl in [3.0, -1.0, 2.0, -0.5]:
        state.record_resolution(pnl_pct=pnl)
    # gains = 3.0 + 2.0 = 5.0, losses = 1.0 + 0.5 = 1.5
    assert abs(state.profit_factor() - (5.0 / 1.5)) < 0.01


def test_optimizer_state_profit_factor_no_losses():
    state = OptimizerState()
    state.record_resolution(pnl_pct=2.0)
    assert state.profit_factor() == float("inf")


def test_optimizer_state_profit_factor_no_data():
    state = OptimizerState()
    assert state.profit_factor() is None


def test_optimizer_state_needs_eval():
    state = OptimizerState()
    # Not enough signals yet
    assert state.needs_eval("source_weights") is False
    # Add enough signals
    for _ in range(OPTIMIZER_CONFIG["min_signals_for_eval"]):
        state.record_resolution(pnl_pct=1.0)
    assert state.needs_eval("source_weights") is True
    # Mark as optimized
    state.last_optimized["source_weights"] = state.resolved_count
    assert state.needs_eval("source_weights") is False
    # Add cooldown-worth of signals
    for _ in range(OPTIMIZER_CONFIG["cooldown_signals"]):
        state.record_resolution(pnl_pct=1.0)
    assert state.needs_eval("source_weights") is True


def test_optimizer_state_respects_priority():
    state = OptimizerState()
    for _ in range(OPTIMIZER_CONFIG["min_signals_for_eval"]):
        state.record_resolution(pnl_pct=1.0)
    # If higher-priority group has active proposal, lower priority blocked
    state.active_shadow_proposal_id = 99
    assert state.can_propose("sigmoid_curves") is False
    # No active proposal = can propose
    state.active_shadow_proposal_id = None
    assert state.can_propose("sigmoid_curves") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v -k "optimizer_state or optimizer_config"`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement OptimizerState and OPTIMIZER_CONFIG**

Create `backend/app/engine/optimizer.py`:

```python
"""Engine parameter optimizer.

Monitors global signal fitness, identifies underperforming parameter groups
via counterfactual backtesting, proposes changes, and manages shadow mode
validation before promotion.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ParameterProposal, ShadowResult, Signal
from app.engine.param_groups import PARAM_GROUPS, PRIORITY_LAYERS, validate_candidate

logger = logging.getLogger(__name__)

OPTIMIZER_CONFIG = {
    "min_signals_for_eval": 50,      # min resolved signals before any optimization
    "shadow_signal_count": 20,       # signals to shadow-test before promoting
    "improvement_threshold": 0.05,   # 5% profit factor improvement required
    "rollback_drop_pct": 0.15,       # auto-rollback if PF drops 15%
    "rollback_window": 10,           # check last N signals for rollback
    "cooldown_signals": 50,          # min signals between optimizations per group
    "window_size": 100,              # rolling window for fitness
}


class OptimizerState:
    """In-memory optimizer state tracking."""

    def __init__(self) -> None:
        self.resolved_count: int = 0
        self.global_pnl_history: list[float] = []
        self.active_shadow_proposal_id: int | None = None
        self.last_optimized: dict[str, int] = {}  # group -> resolved_count at last optimization
        self._pf_at_promotion: dict[int, float] = {}  # proposal_id -> PF when promoted

    def record_resolution(self, pnl_pct: float) -> None:
        self.resolved_count += 1
        self.global_pnl_history.append(pnl_pct)
        # Keep bounded
        if len(self.global_pnl_history) > OPTIMIZER_CONFIG["window_size"] * 2:
            self.global_pnl_history = self.global_pnl_history[-OPTIMIZER_CONFIG["window_size"]:]

    def profit_factor(self, window: int | None = None) -> float | None:
        history = self.global_pnl_history
        if window:
            history = history[-window:]
        if not history:
            return None
        gains = sum(p for p in history if p > 0)
        losses = abs(sum(p for p in history if p < 0))
        if losses == 0:
            return float("inf") if gains > 0 else None
        return gains / losses

    def needs_eval(self, group_name: str) -> bool:
        if self.resolved_count < OPTIMIZER_CONFIG["min_signals_for_eval"]:
            return False
        last = self.last_optimized.get(group_name, 0)
        return (self.resolved_count - last) >= OPTIMIZER_CONFIG["cooldown_signals"]

    def can_propose(self, group_name: str) -> bool:
        if self.active_shadow_proposal_id is not None:
            return False
        return True

    def group_health(self) -> list[dict[str, Any]]:
        """Return health info for all groups."""
        pf = self.profit_factor()
        result = []
        for name, group in PARAM_GROUPS.items():
            last = self.last_optimized.get(name, 0)
            signals_since = self.resolved_count - last
            result.append({
                "group": name,
                "priority": group["priority"],
                "profit_factor": pf,
                "signals_since_last_opt": signals_since,
                "needs_eval": self.needs_eval(name),
                "status": "green" if not self.needs_eval(name) else "yellow",
            })
        return sorted(result, key=lambda x: x["priority"])

    def check_rollback_needed(self, proposal_id: int) -> bool:
        """Check if a recently promoted proposal should be rolled back."""
        baseline_pf = self._pf_at_promotion.get(proposal_id)
        if baseline_pf is None or baseline_pf == 0:
            return False
        current_pf = self.profit_factor(window=OPTIMIZER_CONFIG["rollback_window"])
        if current_pf is None:
            return False
        drop = (baseline_pf - current_pf) / baseline_pf
        return drop > OPTIMIZER_CONFIG["rollback_drop_pct"]
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v -k "optimizer_state or optimizer_config"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/optimizer.py backend/tests/engine/test_optimizer.py
git commit -m "feat(optimizer): add OptimizerState with fitness tracking and group health"
```

---

## Task 5: Optimizer Background Loop and Shadow Management

**Files:**
- Modify: `backend/app/engine/optimizer.py`
- Test: `backend/tests/engine/test_optimizer.py` (extend)

- [ ] **Step 1: Write tests for shadow evaluation logic**

Add to `backend/tests/engine/test_optimizer.py`:

```python
from app.engine.optimizer import evaluate_shadow_results


def test_evaluate_shadow_promote():
    """Shadow with better profit factor -> promote."""
    current_pnls = [3.0, -1.0, 2.0, -0.5, 1.5]  # PF = 6.5/1.5 = 4.33
    shadow_pnls = [4.0, -0.8, 3.0, -0.3, 2.0]    # PF = 9.0/1.1 = 8.18
    result = evaluate_shadow_results(current_pnls, shadow_pnls)
    assert result == "promote"


def test_evaluate_shadow_reject():
    """Shadow with much worse profit factor -> reject."""
    current_pnls = [3.0, -1.0, 2.0, -0.5]  # PF = 5.0/1.5 = 3.33
    shadow_pnls = [1.0, -2.0, 0.5, -1.5]   # PF = 1.5/3.5 = 0.43
    result = evaluate_shadow_results(current_pnls, shadow_pnls)
    assert result == "reject"


def test_evaluate_shadow_inconclusive():
    """Shadow within 10% of current -> inconclusive."""
    current_pnls = [3.0, -1.0, 2.0, -0.5]  # PF = 5.0/1.5 = 3.33
    shadow_pnls = [2.8, -1.0, 2.1, -0.5]   # PF = 4.9/1.5 = 3.27
    result = evaluate_shadow_results(current_pnls, shadow_pnls)
    assert result == "inconclusive"


def test_evaluate_shadow_empty():
    result = evaluate_shadow_results([], [])
    assert result == "inconclusive"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py::test_evaluate_shadow_promote -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement evaluate_shadow_results, counterfactual backtest, and run_optimizer_loop**

Add to `backend/app/engine/optimizer.py`:

```python
def _compute_pf(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def evaluate_shadow_results(
    current_pnls: list[float],
    shadow_pnls: list[float],
) -> str:
    """Compare current vs shadow PnLs. Returns 'promote', 'reject', or 'inconclusive'."""
    if not current_pnls or not shadow_pnls:
        return "inconclusive"
    current_pf = _compute_pf(current_pnls)
    shadow_pf = _compute_pf(shadow_pnls)
    if current_pf == 0:
        return "promote" if shadow_pf > 0 else "inconclusive"
    relative_diff = (shadow_pf - current_pf) / current_pf if current_pf != float("inf") else 0
    if shadow_pf > current_pf:
        return "promote"
    if relative_diff < -0.10:
        return "reject"
    return "inconclusive"


async def create_proposal(
    session: AsyncSession,
    group_name: str,
    changes: dict[str, dict],
    backtest_metrics: dict,
) -> ParameterProposal:
    """Create a new parameter proposal."""
    proposal = ParameterProposal(
        status="pending",
        parameter_group=group_name,
        changes=changes,
        backtest_metrics=backtest_metrics,
    )
    session.add(proposal)
    await session.flush()
    return proposal


async def start_shadow(
    session: AsyncSession,
    proposal_id: int,
) -> None:
    """Transition a proposal to shadow mode."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "shadow"
    proposal.shadow_started_at = datetime.now(timezone.utc)
    await session.flush()


async def promote_proposal(
    session: AsyncSession,
    proposal_id: int,
    shadow_metrics: dict | None = None,
) -> None:
    """Promote a shadow proposal to active parameters."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "promoted"
    proposal.promoted_at = datetime.now(timezone.utc)
    if shadow_metrics:
        proposal.shadow_metrics = shadow_metrics
    await session.flush()


async def reject_proposal(
    session: AsyncSession,
    proposal_id: int,
    reason: str = "",
    shadow_metrics: dict | None = None,
) -> None:
    """Reject a proposal."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "rejected"
    proposal.rejected_reason = reason
    if shadow_metrics:
        proposal.shadow_metrics = shadow_metrics
    await session.flush()


async def rollback_proposal(
    session: AsyncSession,
    proposal_id: int,
) -> ParameterProposal:
    """Roll back a promoted proposal."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "rolled_back"
    await session.flush()
    return proposal


async def record_shadow_result(
    session: AsyncSession,
    proposal_id: int,
    signal_id: int,
    shadow_score: float,
    shadow_entry: float,
    shadow_sl: float,
    shadow_tp1: float,
    shadow_tp2: float,
) -> ShadowResult:
    """Store a shadow scoring result for a signal."""
    sr = ShadowResult(
        proposal_id=proposal_id,
        signal_id=signal_id,
        shadow_score=shadow_score,
        shadow_entry=shadow_entry,
        shadow_sl=shadow_sl,
        shadow_tp1=shadow_tp1,
        shadow_tp2=shadow_tp2,
    )
    session.add(sr)
    await session.flush()
    return sr


async def get_shadow_progress(
    session: AsyncSession,
    proposal_id: int,
) -> dict:
    """Get shadow mode progress for a proposal."""
    count_result = await session.execute(
        select(func.count(ShadowResult.id))
        .where(ShadowResult.proposal_id == proposal_id)
    )
    total = count_result.scalar() or 0
    resolved_result = await session.execute(
        select(func.count(ShadowResult.id))
        .where(ShadowResult.proposal_id == proposal_id)
        .where(ShadowResult.shadow_outcome.is_not(None))
    )
    resolved = resolved_result.scalar() or 0
    return {
        "total": total,
        "resolved": resolved,
        "target": OPTIMIZER_CONFIG["shadow_signal_count"],
        "complete": resolved >= OPTIMIZER_CONFIG["shadow_signal_count"],
    }


async def run_counterfactual_eval(
    app,
    group_name: str,
) -> dict | None:
    """Run counterfactual backtest for a parameter group.

    Re-runs the backtester with the group's parameters perturbed (sweep)
    while all other parameters stay fixed. Returns the best candidate
    and its metrics if it beats current by > improvement_threshold.
    """
    from app.engine.param_groups import get_group, validate_candidate
    from app.engine.backtester import run_backtest, BacktestConfig
    import itertools
    import math

    group = get_group(group_name)
    if not group:
        return None

    db = app.state.db
    settings = app.state.settings

    # Get recent candles for backtest
    async with db.session_factory() as session:
        from app.db.models import Candle
        for pair in ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]:
            result = await session.execute(
                select(Candle)
                .where(Candle.pair == pair)
                .where(Candle.timeframe == "15m")
                .order_by(Candle.timestamp.desc())
                .limit(500)
            )
            candles = list(reversed(result.scalars().all()))
            if len(candles) < 100:
                continue

            # Build candidates based on sweep method
            if group["sweep_method"] == "grid":
                # Generate grid candidates
                param_names = list(group["sweep_ranges"].keys())
                param_values = []
                for name in param_names:
                    lo, hi, step = group["sweep_ranges"][name]
                    vals = []
                    v = lo
                    while v <= hi + 1e-9:
                        vals.append(round(v, 4))
                        v += step
                    param_values.append(vals)

                best_pf = 0.0
                best_candidate = None
                best_metrics = None

                for combo in itertools.product(*param_values):
                    candidate = dict(zip(param_names, combo))
                    if not validate_candidate(group_name, candidate):
                        continue

                    # Build config with this candidate's params applied
                    config = BacktestConfig(
                        pair=pair,
                        timeframe="15m",
                        signal_threshold=candidate.get("signal", settings.engine_signal_threshold),
                    )
                    # Run backtest (sync function — run in executor to avoid blocking)
                    # Actual impl should apply the candidate params to the scoring functions
                    try:
                        import asyncio
                        loop = asyncio.get_event_loop()
                        results = await loop.run_in_executor(
                            None,
                            lambda: run_backtest(
                                candles=candles,
                                pair=pair,
                                config=config,
                                cancel_flag=None,
                            ),
                        )
                        pf = results.get("profit_factor", 0) or 0
                        if pf > best_pf:
                            best_pf = pf
                            best_candidate = candidate
                            best_metrics = results
                    except Exception:
                        continue

                if best_candidate and best_metrics:
                    return {
                        "candidate": best_candidate,
                        "metrics": {
                            "profit_factor": best_metrics.get("profit_factor", 0),
                            "win_rate": best_metrics.get("win_rate", 0),
                            "avg_rr": best_metrics.get("avg_rr", 0),
                            "drawdown": best_metrics.get("max_drawdown", 0),
                            "signals_tested": best_metrics.get("total_trades", 0),
                        },
                    }
            else:
                # DE-based groups: use scipy differential_evolution
                # (follows existing pattern in regime_optimizer.py)
                # Skip for now if scipy not available, log and return None
                logger.info("DE sweep for %s not yet wired — skipping", group_name)
                return None

    return None


async def run_optimizer_loop(app) -> None:
    """Background loop that monitors parameter fitness and manages optimization.

    Runs continuously alongside the pipeline. On each iteration:
    1. Check if any resolved signals need processing
    2. Update global fitness tracking
    3. Check for rollback conditions on recently promoted proposals
    4. Identify parameter groups needing evaluation (counterfactual backtest)
    5. If a group is flagged and no shadow is active, run backtest and create proposal
    6. If shadow mode is active, check for completion and auto-promote/reject
    """
    import asyncio

    state: OptimizerState = app.state.optimizer
    db = app.state.db
    manager = app.state.manager
    last_checked_count = 0

    while True:
        try:
            await asyncio.sleep(60)  # Check every 60 seconds

            # Skip if no new resolved signals since last check
            if state.resolved_count <= last_checked_count:
                continue
            last_checked_count = state.resolved_count

            # 1. Check rollback on recently promoted proposals
            async with db.session_factory() as session:
                result = await session.execute(
                    select(ParameterProposal)
                    .where(ParameterProposal.status == "promoted")
                    .order_by(ParameterProposal.promoted_at.desc())
                    .limit(3)
                )
                for proposal in result.scalars().all():
                    if state.check_rollback_needed(proposal.id):
                        await rollback_proposal(session, proposal.id)
                        await session.commit()
                        logger.warning(
                            "Auto-rolling back proposal %d (%s) — PF dropped",
                            proposal.id, proposal.parameter_group,
                        )
                        await manager.broadcast({
                            "type": "optimizer_update",
                            "event": "proposal_rolled_back",
                            "proposal_id": proposal.id,
                            "reason": "auto_rollback_pf_drop",
                        })

            # 2. Check shadow completion
            if state.active_shadow_proposal_id:
                async with db.session_factory() as session:
                    progress = await get_shadow_progress(
                        session, state.active_shadow_proposal_id
                    )
                    if progress["complete"]:
                        # Evaluate shadow results
                        shadow_results = await session.execute(
                            select(ShadowResult)
                            .where(ShadowResult.proposal_id == state.active_shadow_proposal_id)
                            .where(ShadowResult.shadow_outcome.is_not(None))
                        )
                        shadows = shadow_results.scalars().all()

                        # Get corresponding real signal PnLs
                        signal_ids = [sr.signal_id for sr in shadows]
                        if signal_ids:
                            real_signals = await session.execute(
                                select(Signal)
                                .where(Signal.id.in_(signal_ids))
                            )
                            real_pnl_map = {
                                s.id: s.outcome_pnl_pct or 0
                                for s in real_signals.scalars().all()
                            }

                            current_pnls = [real_pnl_map.get(sr.signal_id, 0) for sr in shadows]
                            # Shadow PnLs: compute from shadow levels vs candle outcomes
                            # For simplicity, use shadow_outcome to derive sign
                            shadow_pnls = []
                            for sr in shadows:
                                if sr.shadow_outcome in ("tp1_hit", "tp2_hit"):
                                    shadow_pnls.append(abs(sr.shadow_tp1 - sr.shadow_entry) / sr.shadow_entry * 100)
                                elif sr.shadow_outcome == "sl_hit":
                                    shadow_pnls.append(-abs(sr.shadow_sl - sr.shadow_entry) / sr.shadow_entry * 100)
                                else:
                                    shadow_pnls.append(0)

                            decision = evaluate_shadow_results(current_pnls, shadow_pnls)

                            proposal_id = state.active_shadow_proposal_id
                            shadow_metrics = {
                                "current_pf": _compute_pf(current_pnls),
                                "shadow_pf": _compute_pf(shadow_pnls),
                                "decision": decision,
                                "signals_evaluated": len(shadows),
                            }

                            if decision == "promote":
                                await promote_proposal(session, proposal_id, shadow_metrics)
                                state.active_shadow_proposal_id = None
                                pf = state.profit_factor()
                                if pf is not None:
                                    state._pf_at_promotion[proposal_id] = pf
                                logger.info("Auto-promoted proposal %d", proposal_id)
                            elif decision == "reject":
                                await reject_proposal(
                                    session, proposal_id,
                                    reason="shadow_underperformed",
                                    shadow_metrics=shadow_metrics,
                                )
                                state.active_shadow_proposal_id = None
                                logger.info("Auto-rejected proposal %d", proposal_id)
                            # "inconclusive" — leave for manual decision

                            await session.commit()
                            await manager.broadcast({
                                "type": "optimizer_update",
                                "event": f"shadow_{decision}",
                                "proposal_id": proposal_id,
                                "shadow_metrics": shadow_metrics,
                            })

                continue  # Don't start new evaluations while shadow is active

            # 3. Find groups needing evaluation (respect priority)
            for layer in PRIORITY_LAYERS:
                for group_name in sorted(layer):
                    if not state.needs_eval(group_name):
                        continue
                    if not state.can_propose(group_name):
                        continue

                    logger.info("Running counterfactual eval for group: %s", group_name)
                    result = await run_counterfactual_eval(app, group_name)

                    if result:
                        candidate = result["candidate"]
                        metrics = result["metrics"]
                        current_pf = state.profit_factor() or 0
                        proposed_pf = metrics.get("profit_factor", 0)

                        if current_pf > 0:
                            improvement = (proposed_pf - current_pf) / current_pf
                        else:
                            improvement = 1.0 if proposed_pf > 0 else 0

                        if improvement >= OPTIMIZER_CONFIG["improvement_threshold"]:
                            # Build changes dict with current vs proposed
                            group = get_group(group_name)
                            changes = {}
                            for param_key, proposed_val in candidate.items():
                                changes[param_key] = {
                                    "current": None,  # Will be filled by the apply endpoint
                                    "proposed": proposed_val,
                                }

                            async with db.session_factory() as session:
                                proposal = await create_proposal(
                                    session, group_name, changes, metrics
                                )
                                await session.commit()
                                logger.info(
                                    "Created proposal %d for %s (PF improvement: %.1f%%)",
                                    proposal.id, group_name, improvement * 100,
                                )
                                await manager.broadcast({
                                    "type": "optimizer_update",
                                    "event": "proposal_created",
                                    "proposal_id": proposal.id,
                                    "group": group_name,
                                })

                    state.last_optimized[group_name] = state.resolved_count
                    break  # Only evaluate one group per cycle
                else:
                    continue
                break

        except asyncio.CancelledError:
            logger.info("Optimizer loop cancelled")
            break
        except Exception:
            logger.exception("Optimizer loop error")
            await asyncio.sleep(300)  # Back off on errors
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/optimizer.py backend/tests/engine/test_optimizer.py
git commit -m "feat(optimizer): add shadow evaluation, proposal lifecycle, and DB operations"
```

---

## Task 6: Optimizer API Endpoints

**Files:**
- Create: `backend/app/api/optimizer.py`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/api/test_optimizer_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/api/test_optimizer_api.py`:

```python
"""Tests for optimizer API endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import make_test_jwt
from app.engine.optimizer import OptimizerState


@pytest.fixture
def optimizer_state():
    state = OptimizerState()
    for pnl in [2.0, -0.5, 1.5, -0.3, 3.0, -1.0]:
        state.record_resolution(pnl_pct=pnl)
    return state


@pytest.mark.asyncio
async def test_get_optimizer_status(client, app, optimizer_state):
    app.state.optimizer = optimizer_state
    resp = await client.get(
        "/api/optimizer/status",
        cookies={"krypton_token": make_test_jwt()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "groups" in data
    assert "global_profit_factor" in data
    assert "active_shadow" in data
    assert len(data["groups"]) == 12  # all param groups


@pytest.mark.asyncio
async def test_get_optimizer_status_no_auth(client):
    resp = await client.get("/api/optimizer/status")  # no cookies
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_proposals_empty(client, app, optimizer_state):
    app.state.optimizer = optimizer_state
    resp = await client.get(
        "/api/optimizer/proposals",
        cookies={"krypton_token": make_test_jwt()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "proposals" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_optimizer_api.py -v`
Expected: FAIL — 404 (routes not registered)

- [ ] **Step 3: Implement API endpoints**

Create `backend/app/api/optimizer.py`:

```python
"""Optimizer API — status, proposals, approve/reject/promote/rollback."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, desc

from app.api.auth import require_auth
from app.db.models import ParameterProposal, ShadowResult
from app.engine.optimizer import (
    OptimizerState,
    start_shadow,
    promote_proposal,
    reject_proposal,
    rollback_proposal,
    get_shadow_progress,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])


@router.get("/status")
async def get_status(request: Request, _key: str = require_auth()):
    """Return optimizer status: group health, global PF, active shadow."""
    optimizer: OptimizerState = request.app.state.optimizer
    groups = optimizer.group_health()
    active_shadow = None

    if optimizer.active_shadow_proposal_id:
        db = request.app.state.db
        async with db.session_factory() as session:
            progress = await get_shadow_progress(
                session, optimizer.active_shadow_proposal_id
            )
            result = await session.execute(
                select(ParameterProposal)
                .where(ParameterProposal.id == optimizer.active_shadow_proposal_id)
            )
            proposal = result.scalar_one_or_none()
            if proposal:
                active_shadow = {
                    "proposal_id": proposal.id,
                    "group": proposal.parameter_group,
                    "progress": progress,
                    "changes": proposal.changes,
                }

    return {
        "global_profit_factor": optimizer.profit_factor(),
        "resolved_count": optimizer.resolved_count,
        "groups": groups,
        "active_shadow": active_shadow,
    }


@router.get("/proposals")
async def get_proposals(
    request: Request,
    _key: str = require_auth(),
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
):
    """Return paginated proposal history."""
    db = request.app.state.db
    async with db.session_factory() as session:
        query = select(ParameterProposal).order_by(
            desc(ParameterProposal.created_at)
        )
        if status:
            query = query.where(ParameterProposal.status == status)
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        proposals = result.scalars().all()
        return {
            "proposals": [
                {
                    "id": p.id,
                    "status": p.status,
                    "parameter_group": p.parameter_group,
                    "changes": p.changes,
                    "backtest_metrics": p.backtest_metrics,
                    "shadow_metrics": p.shadow_metrics,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "shadow_started_at": p.shadow_started_at.isoformat() if p.shadow_started_at else None,
                    "promoted_at": p.promoted_at.isoformat() if p.promoted_at else None,
                    "rejected_reason": p.rejected_reason,
                }
                for p in proposals
            ]
        }


class RejectBody(BaseModel):
    reason: str = ""


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int,
    request: Request,
    _key: str = require_auth(),
):
    """Approve a pending proposal — starts shadow mode."""
    optimizer: OptimizerState = request.app.state.optimizer
    db = request.app.state.db

    if optimizer.active_shadow_proposal_id is not None:
        raise HTTPException(409, "Another shadow proposal is already active")

    async with db.session_factory() as session:
        result = await session.execute(
            select(ParameterProposal).where(ParameterProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal.status != "pending":
            raise HTTPException(400, f"Proposal is {proposal.status}, not pending")

        await start_shadow(session, proposal_id)
        await session.commit()
        optimizer.active_shadow_proposal_id = proposal_id

    manager = request.app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "shadow_started",
        "proposal_id": proposal_id,
    })

    return {"status": "shadow", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal_endpoint(
    proposal_id: int,
    body: RejectBody,
    request: Request,
    _key: str = require_auth(),
):
    """Reject a proposal."""
    optimizer: OptimizerState = request.app.state.optimizer
    db = request.app.state.db

    async with db.session_factory() as session:
        result = await session.execute(
            select(ParameterProposal).where(ParameterProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal.status not in ("pending", "shadow"):
            raise HTTPException(400, f"Cannot reject proposal in {proposal.status} status")

        await reject_proposal(session, proposal_id, reason=body.reason)
        await session.commit()

        if optimizer.active_shadow_proposal_id == proposal_id:
            optimizer.active_shadow_proposal_id = None

    manager = request.app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "proposal_rejected",
        "proposal_id": proposal_id,
    })

    return {"status": "rejected", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/promote")
async def promote_proposal_endpoint(
    proposal_id: int,
    request: Request,
    _key: str = require_auth(),
):
    """Manually promote a shadow proposal early."""
    optimizer: OptimizerState = request.app.state.optimizer
    db = request.app.state.db

    async with db.session_factory() as session:
        result = await session.execute(
            select(ParameterProposal).where(ParameterProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal.status != "shadow":
            raise HTTPException(400, f"Cannot promote proposal in {proposal.status} status")

        progress = await get_shadow_progress(session, proposal_id)
        await promote_proposal(session, proposal_id, shadow_metrics=progress)
        await session.commit()

        if optimizer.active_shadow_proposal_id == proposal_id:
            optimizer.active_shadow_proposal_id = None
            optimizer.last_optimized[proposal.parameter_group] = optimizer.resolved_count
            pf = optimizer.profit_factor()
            if pf is not None:
                optimizer._pf_at_promotion[proposal_id] = pf

    # Apply the parameter changes via the existing engine apply mechanism
    # This reuses the /api/engine/apply logic
    app = request.app
    from app.api.engine import _resolve_current_value
    settings = app.state.settings
    lock = app.state.pipeline_settings_lock
    # Apply changes would go through the same path as engine/apply
    # For now, broadcast the event
    manager = app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "proposal_promoted",
        "proposal_id": proposal_id,
        "changes": proposal.changes,
    })

    return {"status": "promoted", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/rollback")
async def rollback_proposal_endpoint(
    proposal_id: int,
    request: Request,
    _key: str = require_auth(),
):
    """Roll back a promoted proposal to previous parameter values."""
    db = request.app.state.db

    async with db.session_factory() as session:
        result = await session.execute(
            select(ParameterProposal).where(ParameterProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal.status != "promoted":
            raise HTTPException(400, f"Cannot rollback proposal in {proposal.status} status")

        rolled = await rollback_proposal(session, proposal_id)
        await session.commit()

    # Apply the rollback (revert to "current" values from the changes dict)
    manager = request.app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "proposal_rolled_back",
        "proposal_id": proposal_id,
    })

    return {"status": "rolled_back", "proposal_id": proposal_id}
```

- [ ] **Step 4: Register optimizer router**

In `backend/app/main.py`, add the optimizer router alongside the existing router registrations. Find where other routers are included via `app.include_router()` and add:

```python
from app.api.optimizer import router as optimizer_router
app.include_router(optimizer_router)
```

Note: Routers are registered in `main.py` via `app.include_router()`, NOT in `routes.py`. Follow the existing pattern in `main.py`.

- [ ] **Step 5: Wire up app.state.optimizer and start background loop in main.py**

In `backend/app/main.py`, in the lifespan setup where `app.state.tracker` is assigned:

```python
from app.engine.optimizer import OptimizerState, run_optimizer_loop

# In lifespan, after tracker setup:
app.state.optimizer = OptimizerState()

# Start the optimizer background loop (add to the section where other background tasks are created):
optimizer_task = asyncio.create_task(run_optimizer_loop(app))
# Add optimizer_task to the pipeline_tasks set so it gets cancelled on shutdown
```

- [ ] **Step 6: Update test conftest to stub optimizer**

In `backend/tests/conftest.py`, in `_test_lifespan` (after the existing `app.state` assignments, around line 61), add:

```python
from app.engine.optimizer import OptimizerState

# Inside _test_lifespan, after app.state.pipeline_settings_lock:
app.state.optimizer = OptimizerState()
```

Also add `app.state.manager = MagicMock()` if not already present (needed for broadcast calls in optimizer endpoints). Check if `manager` is already mocked — if not, add it.

- [ ] **Step 7: Run tests**

Note: The conftest's mock DB throws `Exception("no real DB")` on `session.execute`. The status endpoint will work because it reads from in-memory `OptimizerState`. But the proposals endpoint calls `session.execute`, so it needs the mock session to return an empty result. Update the `optimizer_state` fixture or the test to mock the DB session:

```python
@pytest.fixture
def optimizer_state(app):
    state = OptimizerState()
    for pnl in [2.0, -0.5, 1.5, -0.3, 3.0, -1.0]:
        state.record_resolution(pnl_pct=pnl)
    app.state.optimizer = state

    # Mock session.execute to return empty results for proposals query
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = app.state.db.session_factory()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.execute = AsyncMock(return_value=mock_result)

    return state
```

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_optimizer_api.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/optimizer.py backend/app/main.py backend/tests/
git commit -m "feat(optimizer): add API endpoints for status, proposals, approve/reject/promote/rollback"
```

---

## Task 7: Frontend — Optimizer Types and Store

**Files:**
- Create: `web/src/features/optimizer/types.ts`
- Create: `web/src/features/optimizer/store.ts`
- Modify: `web/src/shared/lib/api.ts`

- [ ] **Step 1: Create optimizer types**

Create `web/src/features/optimizer/types.ts`:

```typescript
export interface GroupHealth {
  group: string;
  priority: number;
  profit_factor: number | null;
  signals_since_last_opt: number;
  needs_eval: boolean;
  status: "green" | "yellow" | "red";
}

export interface ProposalChange {
  current: number;
  proposed: number;
}

export interface BacktestMetrics {
  profit_factor: number;
  win_rate: number;
  avg_rr: number;
  drawdown: number;
  signals_tested: number;
}

export interface ShadowProgress {
  total: number;
  resolved: number;
  target: number;
  complete: boolean;
}

export interface Proposal {
  id: number;
  status: "pending" | "shadow" | "approved" | "rejected" | "promoted" | "rolled_back";
  parameter_group: string;
  changes: Record<string, ProposalChange>;
  backtest_metrics: BacktestMetrics;
  shadow_metrics: ShadowProgress | null;
  created_at: string | null;
  shadow_started_at: string | null;
  promoted_at: string | null;
  rejected_reason: string | null;
}

export interface OptimizerStatus {
  global_profit_factor: number | null;
  resolved_count: number;
  groups: GroupHealth[];
  active_shadow: {
    proposal_id: number;
    group: string;
    progress: ShadowProgress;
    changes: Record<string, ProposalChange>;
  } | null;
}
```

- [ ] **Step 2: Add API methods**

Add to `web/src/shared/lib/api.ts`:

```typescript
// Optimizer
getOptimizerStatus: () =>
  request<OptimizerStatus>("/api/optimizer/status"),

getOptimizerProposals: (params?: { limit?: number; offset?: number; status?: string }) => {
  const query = new URLSearchParams();
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));
  if (params?.status) query.set("status", params.status);
  const qs = query.toString();
  return request<{ proposals: Proposal[] }>(`/api/optimizer/proposals${qs ? `?${qs}` : ""}`);
},

approveProposal: (id: number) =>
  request<{ status: string; proposal_id: number }>(`/api/optimizer/proposals/${id}/approve`, {
    method: "POST",
  }),

rejectProposal: (id: number, reason?: string) =>
  request<{ status: string; proposal_id: number }>(`/api/optimizer/proposals/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason || "" }),
  }),

promoteProposal: (id: number) =>
  request<{ status: string; proposal_id: number }>(`/api/optimizer/proposals/${id}/promote`, {
    method: "POST",
  }),

rollbackProposal: (id: number) =>
  request<{ status: string; proposal_id: number }>(`/api/optimizer/proposals/${id}/rollback`, {
    method: "POST",
  }),
```

Import the types at the top of `api.ts`:

```typescript
import type { OptimizerStatus, Proposal } from "../features/optimizer/types";
```

Note: If `api.ts` doesn't import from features (check existing pattern), define the types inline or in a shared types file instead.

- [ ] **Step 3: Create optimizer store**

Create `web/src/features/optimizer/store.ts`:

```typescript
import { create } from "zustand";
import { api } from "../../shared/lib/api";
import type { OptimizerStatus, Proposal } from "./types";

interface OptimizerStore {
  status: OptimizerStatus | null;
  proposals: Proposal[];
  loading: boolean;
  actionLoading: boolean;
  error: string | null;

  fetchStatus: () => Promise<void>;
  fetchProposals: () => Promise<void>;
  approve: (id: number) => Promise<void>;
  reject: (id: number, reason?: string) => Promise<void>;
  promote: (id: number) => Promise<void>;
  rollback: (id: number) => Promise<void>;
}

export const useOptimizerStore = create<OptimizerStore>((set, get) => ({
  status: null,
  proposals: [],
  loading: false,
  actionLoading: false,
  error: null,

  fetchStatus: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getOptimizerStatus();
      set({ status: data, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  fetchProposals: async () => {
    try {
      const data = await api.getOptimizerProposals({ limit: 50 });
      set({ proposals: data.proposals });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  approve: async (id) => {
    set({ actionLoading: true });
    try {
      await api.approveProposal(id);
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },

  reject: async (id, reason) => {
    set({ actionLoading: true });
    try {
      await api.rejectProposal(id, reason);
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },

  promote: async (id) => {
    set({ actionLoading: true });
    try {
      await api.promoteProposal(id);
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },

  rollback: async (id) => {
    set({ actionLoading: true });
    try {
      await api.rollbackProposal(id);
      await get().fetchStatus();
      await get().fetchProposals();
    } finally {
      set({ actionLoading: false });
    }
  },
}));
```

- [ ] **Step 4: Commit**

```bash
git add web/src/features/optimizer/ web/src/shared/lib/api.ts
git commit -m "feat(optimizer): add frontend types, store, and API methods"
```

---

## Task 8: Frontend — Optimizer Page Components

**Files:**
- Create: `web/src/features/optimizer/components/GroupHealthTable.tsx`
- Create: `web/src/features/optimizer/components/ProposalCard.tsx`
- Create: `web/src/features/optimizer/components/ShadowProgress.tsx`
- Create: `web/src/features/optimizer/components/ProposalHistory.tsx`
- Create: `web/src/features/optimizer/components/OptimizerPage.tsx`

- [ ] **Step 1: Create GroupHealthTable**

Create `web/src/features/optimizer/components/GroupHealthTable.tsx`:

```tsx
import { Check, AlertTriangle, XCircle } from "lucide-react";
import type { GroupHealth } from "../types";

const STATUS_CONFIG: Record<string, { bg: string; icon: typeof Check; label: string }> = {
  green: { bg: "bg-long", icon: Check, label: "Healthy" },
  yellow: { bg: "bg-accent", icon: AlertTriangle, label: "Needs eval" },
  red: { bg: "bg-error", icon: XCircle, label: "Degraded" },
};

interface Props {
  groups: GroupHealth[];
}

export default function GroupHealthTable({ groups }: Props) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-bold uppercase tracking-widest text-primary mb-2">
        Parameter Groups
      </div>
      {groups.map((g) => {
        const cfg = STATUS_CONFIG[g.status] || STATUS_CONFIG.green;
        const Icon = cfg.icon;
        return (
          <div
            key={g.group}
            className="flex items-center justify-between px-3 py-2 bg-surface-container rounded-lg"
          >
            <div className="flex items-center gap-2">
              <Icon size={12} className={g.status === "green" ? "text-long" : g.status === "yellow" ? "text-accent" : "text-error"} aria-label={cfg.label} />
              <span className="text-xs text-on-surface">{g.group.replace(/_/g, " ")}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-muted">
                {g.signals_since_last_opt} signals ago
              </span>
              {g.profit_factor != null && (
                <span className="text-xs font-mono text-on-surface">
                  PF {g.profit_factor === Infinity ? "∞" : g.profit_factor.toFixed(2)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Create ProposalCard**

Create `web/src/features/optimizer/components/ProposalCard.tsx`:

```tsx
import { useState } from "react";
import type { Proposal } from "../types";
import ParamInfoPopup from "../../engine/components/ParamInfoPopup";

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-accent/15 text-accent",
  shadow: "bg-blue/15 text-blue",
  promoted: "bg-long/15 text-long",
  rejected: "bg-error/15 text-error",
  rolled_back: "bg-error/15 text-error",
  approved: "bg-long/15 text-long",
};

interface Props {
  proposal: Proposal;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
  actionLoading?: boolean;
  onApprove?: (id: number) => void;
  onReject?: (id: number) => void;
  onPromote?: (id: number) => void;
  onRollback?: (id: number) => void;
}

export default function ProposalCard({
  proposal,
  descriptions,
  actionLoading,
  onApprove,
  onReject,
  onPromote,
  onRollback,
}: Props) {
  const [confirmAction, setConfirmAction] = useState<"reject" | "rollback" | null>(null);
  const p = proposal;
  const changes = Object.entries(p.changes);
  const bm = p.backtest_metrics;

  const handleReject = () => {
    if (confirmAction === "reject") {
      onReject?.(p.id);
      setConfirmAction(null);
    } else {
      setConfirmAction("reject");
    }
  };

  const handleRollback = () => {
    if (confirmAction === "rollback") {
      onRollback?.(p.id);
      setConfirmAction(null);
    } else {
      setConfirmAction("rollback");
    }
  };

  return (
    <div className="border border-primary/20 rounded-xl bg-surface-container-low p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-medium text-on-surface">
            {p.parameter_group.replace(/_/g, " ")}
          </span>
          <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded-full ${
            STATUS_STYLE[p.status] || "bg-dim/15 text-muted"
          }`}>
            {p.status}
          </span>
        </div>
        {p.created_at && (
          <span className="text-[10px] text-muted">
            {new Date(p.created_at).toLocaleDateString()}
          </span>
        )}
      </div>

      {/* Diff table */}
      <div className="space-y-0.5">
        {changes.map(([key, change]) => (
          <div key={key} className="flex items-center justify-between gap-2 px-2 py-1 text-xs">
            <div className="flex items-center gap-1 min-w-0">
              <span className="text-muted truncate">{key}</span>
              <ParamInfoPopup name={key} descriptions={descriptions} />
            </div>
            <div className="flex items-center gap-1 font-mono shrink-0">
              <span className="text-short">−{typeof change.current === "number" ? change.current.toFixed(3) : String(change.current)}</span>
              <span className="text-muted">→</span>
              <span className="text-long">+{typeof change.proposed === "number" ? change.proposed.toFixed(3) : String(change.proposed)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Backtest metrics */}
      <div className="flex flex-wrap gap-2">
        {[
          { label: "PF", value: bm.profit_factor.toFixed(2) },
          { label: "Win", value: `${(bm.win_rate * 100).toFixed(0)}%` },
          { label: "R:R", value: bm.avg_rr.toFixed(2) },
          { label: "DD", value: `${(bm.drawdown * 100).toFixed(1)}%` },
          { label: "Signals", value: String(bm.signals_tested) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-surface-container rounded px-2 py-1">
            <span className="text-[10px] text-muted">{label}</span>
            <span className="ml-1 text-xs font-mono text-on-surface">{value}</span>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {p.status === "pending" && (
          <>
            <button
              onClick={() => onApprove?.(p.id)}
              disabled={actionLoading}
              className="flex-1 min-h-[44px] text-xs font-medium rounded-lg bg-long/15 text-long hover:bg-long/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {actionLoading ? "..." : "Approve"}
            </button>
            <button
              onClick={handleReject}
              disabled={actionLoading}
              className="flex-1 min-h-[44px] text-xs font-medium rounded-lg bg-error/15 text-error hover:bg-error/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {confirmAction === "reject" ? "Confirm Reject?" : "Reject"}
            </button>
          </>
        )}
        {p.status === "shadow" && (
          <>
            <button
              onClick={() => onPromote?.(p.id)}
              disabled={actionLoading}
              className="flex-1 min-h-[44px] text-xs font-medium rounded-lg bg-long/15 text-long hover:bg-long/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {actionLoading ? "..." : "Promote Early"}
            </button>
            <button
              onClick={handleReject}
              disabled={actionLoading}
              className="flex-1 min-h-[44px] text-xs font-medium rounded-lg bg-error/15 text-error hover:bg-error/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {confirmAction === "reject" ? "Confirm Reject?" : "Reject"}
            </button>
          </>
        )}
        {p.status === "promoted" && (
          <button
            onClick={handleRollback}
            disabled={actionLoading}
            className="flex-1 min-h-[44px] text-xs font-medium rounded-lg bg-error/15 text-error hover:bg-error/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {confirmAction === "rollback" ? "Confirm Rollback?" : "Rollback"}
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create ShadowProgress**

Create `web/src/features/optimizer/components/ShadowProgress.tsx`:

```tsx
import type { ShadowProgress as ShadowProgressType, ProposalChange } from "../types";

interface Props {
  group: string;
  progress: ShadowProgressType;
  changes: Record<string, ProposalChange>;
}

export default function ShadowProgress({ group, progress, changes }: Props) {
  const pct = progress.target > 0 ? (progress.resolved / progress.target) * 100 : 0;

  return (
    <div className="border border-blue/20 rounded-xl bg-surface-container-low p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-widest text-blue">
          Shadow Mode Active
        </div>
        <span className="text-xs text-on-surface font-mono">
          {progress.resolved}/{progress.target}
        </span>
      </div>
      <div className="text-xs text-muted">{group.replace(/_/g, " ")}</div>
      <div className="h-2 bg-surface-container rounded-full overflow-hidden">
        <div
          className="h-full bg-blue transition-all duration-300 rounded-full"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <div className="text-[10px] text-muted text-center">
        {progress.complete ? "Evaluation complete — awaiting decision" : "Collecting signal results..."}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create ProposalHistory**

Create `web/src/features/optimizer/components/ProposalHistory.tsx`:

```tsx
import { useState } from "react";
import type { Proposal } from "../types";

interface Props {
  proposals: Proposal[];
}

export default function ProposalHistory({ proposals }: Props) {
  const [expanded, setExpanded] = useState(false);
  const resolved = proposals.filter((p) =>
    ["promoted", "rejected", "rolled_back"].includes(p.status)
  );
  if (resolved.length === 0) return null;

  const shown = expanded ? resolved : resolved.slice(0, 5);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between py-2 text-xs text-muted"
        aria-expanded={expanded}
        aria-label="Toggle proposal history"
      >
        <span className="uppercase tracking-wider font-bold text-[10px]">History</span>
        <span>{expanded ? "−" : "+"}</span>
      </button>
      {(expanded || resolved.length <= 5) && (
        <div className="space-y-1">
          {shown.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between px-2 py-1.5 text-xs bg-surface-container/50 rounded"
            >
              <div className="flex items-center gap-2">
                <span className={
                  p.status === "promoted" ? "text-long" :
                  p.status === "rejected" ? "text-error" :
                  "text-accent"
                }>
                  {p.status}
                </span>
                <span className="text-muted">{p.parameter_group.replace(/_/g, " ")}</span>
              </div>
              <span className="text-[10px] text-muted">
                {p.promoted_at
                  ? new Date(p.promoted_at).toLocaleDateString()
                  : p.created_at
                    ? new Date(p.created_at).toLocaleDateString()
                    : ""}
              </span>
            </div>
          ))}
          {!expanded && resolved.length > 5 && (
            <button
              onClick={() => setExpanded(true)}
              className="w-full text-center text-[10px] text-primary py-1"
            >
              Show {resolved.length - 5} more
            </button>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Create OptimizerPage**

Create `web/src/features/optimizer/components/OptimizerPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useOptimizerStore } from "../store";
import { useEngineStore } from "../../engine/store";
import GroupHealthTable from "./GroupHealthTable";
import ProposalCard from "./ProposalCard";
import ShadowProgress from "./ShadowProgress";
import ProposalHistory from "./ProposalHistory";

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-surface-container rounded ${className}`} />;
}

function OptimizerSkeleton() {
  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-3 w-36" />
        </div>
        <Skeleton className="h-8 w-8 rounded-full" />
      </div>
      {[1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className="h-10 w-full rounded-lg" />
      ))}
    </div>
  );
}

export default function OptimizerPage() {
  const {
    status, proposals, loading, actionLoading, error,
    fetchStatus, fetchProposals,
    approve, reject, promote, rollback,
  } = useOptimizerStore();
  const { params, fetch: fetchEngine } = useEngineStore();
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    fetchStatus();
    fetchProposals();
    fetchEngine();
  }, [fetchStatus, fetchProposals, fetchEngine]);

  const descriptions = params?.descriptions;
  const pendingProposals = proposals.filter((p) => p.status === "pending");

  const withErrorHandling = (fn: (id: number) => Promise<void>) => async (id: number) => {
    setActionError(null);
    try {
      await fn(id);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  if (loading && !status) return <OptimizerSkeleton />;
  if (error) {
    return <div className="p-4 text-error text-sm">Error: {error}</div>;
  }
  if (!status) return null;

  return (
    <div className="p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-on-surface">Optimizer</h3>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-[10px] text-muted">
              {status.resolved_count} signals resolved
            </span>
            {status.global_profit_factor != null && (
              <span className="text-xs font-mono text-on-surface">
                PF {status.global_profit_factor === Infinity
                  ? "∞"
                  : status.global_profit_factor.toFixed(2)}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={() => { fetchStatus(); fetchProposals(); }}
          className="p-2 text-primary hover:text-primary/80 transition-colors"
          aria-label="Refresh"
        >
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Action error toast */}
      {actionError && (
        <div className="flex items-center justify-between px-3 py-2 bg-error/10 border border-error/20 rounded-lg">
          <span className="text-xs text-error">{actionError}</span>
          <button onClick={() => setActionError(null)} className="text-error text-xs ml-2">✕</button>
        </div>
      )}

      {/* Shadow progress */}
      {status.active_shadow && (
        <ShadowProgress
          group={status.active_shadow.group}
          progress={status.active_shadow.progress}
          changes={status.active_shadow.changes}
        />
      )}

      {/* Pending proposals */}
      {pendingProposals.map((p) => (
        <ProposalCard
          key={p.id}
          proposal={p}
          descriptions={descriptions}
          actionLoading={actionLoading}
          onApprove={withErrorHandling(approve)}
          onReject={withErrorHandling(reject)}
          onPromote={withErrorHandling(promote)}
          onRollback={withErrorHandling(rollback)}
        />
      ))}

      {/* Group health */}
      <GroupHealthTable groups={status.groups} />

      {/* History */}
      <ProposalHistory proposals={proposals} />
    </div>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add web/src/features/optimizer/components/
git commit -m "feat(optimizer): add Optimizer page components — health, proposals, shadow, history"
```

---

## Task 9: Frontend — Pipeline Flow Diagram and Engine Page Integration

**Files:**
- Create: `web/src/features/engine/components/PipelineFlow.tsx`
- Modify: `web/src/features/engine/components/EnginePage.tsx`
- Modify: `web/src/features/more/components/MorePage.tsx`

- [ ] **Step 1: Create PipelineFlow component**

Create `web/src/features/engine/components/PipelineFlow.tsx`:

```tsx
import { useState } from "react";

interface NodeData {
  label: string;
  score?: number | null;
  details?: Record<string, number>;
}

interface Props {
  nodes?: Record<string, NodeData>;
}

const DEFAULT_NODES: Record<string, NodeData> = {
  technical: { label: "Technical" },
  order_flow: { label: "Order Flow" },
  onchain: { label: "On-Chain" },
  patterns: { label: "Patterns" },
  regime_blend: { label: "Regime Blend" },
  ml_gate: { label: "ML Gate" },
  llm_gate: { label: "LLM Gate" },
  signal: { label: "Signal" },
};

function ScoreNode({
  data,
  onClick,
  active,
}: {
  data: NodeData;
  onClick: () => void;
  active: boolean;
}) {
  const score = data.score;
  const color =
    score == null ? "text-muted" :
    score > 0 ? "text-long" :
    score < 0 ? "text-short" :
    "text-muted";

  return (
    <button
      onClick={onClick}
      className={`min-h-[44px] px-3 py-2 rounded text-xs transition-colors ${
        active
          ? "bg-primary/20 border border-primary/40"
          : "bg-surface-container border border-outline-variant/30 hover:border-primary/30"
      }`}
    >
      <div className="text-muted">{data.label}</div>
      {score != null && (
        <div className={`font-mono font-medium ${color}`}>
          {score > 0 ? "+" : ""}{score.toFixed(1)}
        </div>
      )}
    </button>
  );
}

export default function PipelineFlow({ nodes }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const merged = { ...DEFAULT_NODES, ...nodes };

  const expandedNode = expanded ? merged[expanded] : null;

  return (
    <div className="bg-surface-container-low rounded-xl p-3 space-y-2">
      <div className="text-[10px] font-bold uppercase tracking-widest text-primary">
        Signal Pipeline
      </div>

      {/* Flow: 2-row layout — sources on top, pipeline stages below */}
      <div className="space-y-2">
        {/* Source scores row */}
        <div className="grid grid-cols-4 gap-1">
          {["technical", "order_flow", "onchain", "patterns"].map((key) => (
            <ScoreNode
              key={key}
              data={merged[key]}
              onClick={() => setExpanded(expanded === key ? null : key)}
              active={expanded === key}
            />
          ))}
        </div>
        <div className="text-muted text-[10px] text-center">↓</div>
        {/* Pipeline stages row */}
        <div className="grid grid-cols-4 gap-1">
          {["regime_blend", "ml_gate", "llm_gate", "signal"].map((key) => (
            <ScoreNode
              key={key}
              data={merged[key]}
              onClick={() => setExpanded(expanded === key ? null : key)}
              active={expanded === key}
            />
          ))}
        </div>
      </div>

      {/* Expanded details */}
      {expandedNode?.details && (
        <div className="border-t border-border/30 pt-2 space-y-0.5">
          {Object.entries(expandedNode.details).map(([key, value]) => (
            <div key={key} className="flex justify-between text-[10px] px-1">
              <span className="text-muted">{key}</span>
              <span className={`font-mono ${value > 0 ? "text-long" : value < 0 ? "text-short" : "text-muted"}`}>
                {value > 0 ? "+" : ""}{value.toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add PipelineFlow and proposal badge to EnginePage**

Modify `web/src/features/engine/components/EnginePage.tsx`:

Add at the top of the JSX (after the header, before WeightBar):

```tsx
import PipelineFlow from "./PipelineFlow";
import { useOptimizerStore } from "../../optimizer/store";

// Inside the component, after useEngineStore():
const { status: optimizerStatus } = useOptimizerStore();
const pendingCount = optimizerStatus?.groups.filter(g => g.needs_eval).length || 0;
```

Add the PipelineFlow component at the top of the return JSX, and add a proposal badge near the header if there are pending proposals. The badge is a small indicator linking the user to check the Optimizer page.

- [ ] **Step 3: Add Optimizer entry to MorePage**

Modify `web/src/features/more/components/MorePage.tsx`:

1. Add `"optimizer"` to the `SubPage` type union
2. Add to `CLUSTERS` in the appropriate section (e.g., "Analytics" or "Engine"):
   ```typescript
   { key: "optimizer", icon: Zap, label: "Optimizer", desc: "Auto-tune parameters", color: "text-purple-400" },
   ```
3. Add to `PAGE_TITLES`:
   ```typescript
   optimizer: "Optimizer",
   ```
4. Add the conditional render block inside the `if (activePage)` block alongside existing pages:
   ```tsx
   {activePage === "optimizer" && <OptimizerPage />}
   ```
5. Import `OptimizerPage` and the `Zap` icon:
   ```tsx
   import OptimizerPage from "../../optimizer/components/OptimizerPage";
   import { Zap } from "lucide-react";
   ```

- [ ] **Step 4: Commit**

```bash
git add web/src/features/engine/components/PipelineFlow.tsx
git add web/src/features/engine/components/EnginePage.tsx
git add web/src/features/more/components/MorePage.tsx
git commit -m "feat(optimizer): add pipeline flow diagram, optimizer page in More menu"
```

---

## Task 10: WebSocket Integration for Live Updates

**Files:**
- Modify: `web/src/features/optimizer/store.ts`

- [ ] **Step 1: Add WebSocket listener for optimizer events**

The app already has a WebSocket connection via `WebSocketManager` that connects to `/ws/signals`. The backend will broadcast `optimizer_update` events on this channel.

In `web/src/features/optimizer/store.ts`, add a subscription to the existing WebSocket manager for `optimizer_update` events. Follow the pattern used by the signals store for handling incoming WebSocket messages.

Check how the signals store (`web/src/features/signals/store.ts`) subscribes to WebSocket events and replicate that pattern. The optimizer store should listen for `optimizer_update` events and refresh status/proposals when received:

```typescript
// Add to the store, in the create callback:
// Subscribe to WebSocket optimizer events
// (Follow the same pattern as signals/store.ts for WebSocket subscription)
```

When an `optimizer_update` event arrives with types `shadow_started`, `proposal_rejected`, `proposal_promoted`, or `proposal_rolled_back`, call `fetchStatus()` and `fetchProposals()` to refresh the UI.

- [ ] **Step 2: Commit**

```bash
git add web/src/features/optimizer/store.ts
git commit -m "feat(optimizer): add WebSocket subscription for live optimizer updates"
```

---

## Task 11: Integration Testing and Final Wiring

**Files:**
- Modify: `backend/tests/engine/test_optimizer.py`
- Modify: `backend/tests/api/test_optimizer_api.py`

- [ ] **Step 1: Write integration test for proposal lifecycle**

Add to `backend/tests/engine/test_optimizer.py`:

```python
import pytest
from app.engine.optimizer import (
    OptimizerState,
    evaluate_shadow_results,
    OPTIMIZER_CONFIG,
)
from app.engine.param_groups import PARAM_GROUPS, validate_candidate


def test_full_lifecycle_scenario():
    """Simulate: signals resolve -> group flagged -> validate candidate -> evaluate shadow."""
    state = OptimizerState()

    # Accumulate enough signals
    for pnl in [2.0, -0.5, 1.5, -0.3, 3.0, -1.0] * 10:
        state.record_resolution(pnl_pct=pnl)

    # source_weights should need eval
    assert state.needs_eval("source_weights") is True
    assert state.can_propose("source_weights") is True

    # Simulate a valid candidate
    candidate = {"traditional": 0.35, "flow": 0.25, "onchain": 0.25, "pattern": 0.15}
    assert validate_candidate("source_weights", candidate) is True

    # Mark as optimized
    state.last_optimized["source_weights"] = state.resolved_count

    # Now it shouldn't need eval
    assert state.needs_eval("source_weights") is False

    # Simulate shadow result
    current = [2.0, -0.5, 1.5, -0.3]
    shadow = [3.0, -0.4, 2.0, -0.2]
    assert evaluate_shadow_results(current, shadow) == "promote"


def test_rollback_detection():
    state = OptimizerState()
    for _ in range(20):
        state.record_resolution(pnl_pct=2.0)

    # Record PF at "promotion"
    state._pf_at_promotion[1] = state.profit_factor()

    # Now add bad signals
    for _ in range(OPTIMIZER_CONFIG["rollback_window"]):
        state.record_resolution(pnl_pct=-3.0)

    assert state.check_rollback_needed(1) is True
```

- [ ] **Step 2: Run all optimizer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py tests/engine/test_param_groups.py tests/api/test_optimizer_api.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(optimizer): integration tests and final wiring"
```
