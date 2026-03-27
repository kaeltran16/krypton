"""Engine parameter visibility and apply endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import require_auth
from app.db.models import PipelineSettings, RegimeWeights, PerformanceTrackerRow
from app.engine.constants import get_engine_constants, PARAMETER_DESCRIPTIONS
from app.engine.regime import REGIMES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engine", tags=["engine"])


def _configurable(value):
    return {"value": value, "source": "configurable"}


@router.get("/parameters")
async def get_parameters(request: Request, _key: str = require_auth()):
    """Return the full engine parameter tree."""
    settings = request.app.state.settings
    db = request.app.state.db

    params = get_engine_constants()

    scoring = getattr(request.app.state, "scoring_params", None) or {}
    params["technical"]["mean_reversion"] = {
        "rsi_steepness": _configurable(scoring.get("mean_rev_rsi_steepness", 0.25)),
        "bb_pos_steepness": _configurable(scoring.get("mean_rev_bb_pos_steepness", 10.0)),
        "squeeze_steepness": _configurable(scoring.get("squeeze_steepness", 0.10)),
        "blend_ratio": _configurable(scoring.get("mean_rev_blend_ratio", 0.6)),
    }

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
        "confluence": {
            "level_weights": {
                "immediate": _configurable(settings.engine_confluence_level_weight_1),
                "grandparent": _configurable(settings.engine_confluence_level_weight_2),
                "great_grandparent": _configurable(round(max(0.0, 1.0 - settings.engine_confluence_level_weight_1 - settings.engine_confluence_level_weight_2), 4)),
            },
            "trend_alignment_steepness": _configurable(settings.engine_confluence_trend_alignment_steepness),
            "adx_strength_center": _configurable(settings.engine_confluence_adx_strength_center),
            "adx_conviction_ratio": _configurable(settings.engine_confluence_adx_conviction_ratio),
            "mr_penalty_factor": _configurable(settings.engine_confluence_mr_penalty_factor),
        },
    }

    regime_data = {}
    regime_weights_dict = getattr(request.app.state, "regime_weights", {})
    for (pair, tf), rw in regime_weights_dict.items():
        regime_data.setdefault(pair, {})[tf] = _regime_row_to_dict(rw)

    if not regime_data:
        try:
            async with db.session_factory() as session:
                result = await session.execute(select(RegimeWeights))
                for rw in result.scalars().all():
                    regime_data.setdefault(rw.pair, {})[rw.timeframe] = _regime_row_to_dict(rw)
        except Exception:
            pass

    params["regime_weights"] = regime_data

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

    params["descriptions"] = PARAMETER_DESCRIPTIONS

    return params


def _regime_row_to_dict(rw) -> dict:
    """Convert a RegimeWeights row to the API response format."""
    result = {}
    for regime in REGIMES:
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
                "liquidation": getattr(rw, f"{regime}_liquidation_weight"),
                "confluence": getattr(rw, f"{regime}_confluence_weight"),
            },
        }
    return result


# ── Apply endpoint ──


class ApplyRequest(BaseModel):
    changes: dict[str, float | int | dict]
    confirm: bool = False


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
    "blending.confluence.level_weights.immediate": ("engine_confluence_level_weight_1", "confluence_level_weight_1"),
    "blending.confluence.level_weights.grandparent": ("engine_confluence_level_weight_2", "confluence_level_weight_2"),
    "blending.confluence.trend_alignment_steepness": ("engine_confluence_trend_alignment_steepness", "confluence_trend_alignment_steepness"),
    "blending.confluence.adx_strength_center": ("engine_confluence_adx_strength_center", "confluence_adx_strength_center"),
    "blending.confluence.adx_conviction_ratio": ("engine_confluence_adx_conviction_ratio", "confluence_adx_conviction_ratio"),
    "blending.confluence.mr_penalty_factor": ("engine_confluence_mr_penalty_factor", "confluence_mr_penalty_factor"),
}

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
        parts = path.split(".", 3)
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
                    _ATR_INDEX = {"current_sl_atr": 0, "current_tp1_atr": 1, "current_tp2_atr": 2}
                    idx = _ATR_INDEX.get(col)
                    if idx is not None:
                        return cached[idx], "configurable"
        return None, "configurable"

    return None, "unknown"


@router.post("/apply")
async def apply_parameters(body: ApplyRequest, request: Request, _key: str = require_auth()):
    """Preview or apply parameter changes."""
    if not body.changes:
        raise HTTPException(400, "No changes provided")

    app = request.app

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

    db = app.state.db
    settings = app.state.settings
    lock = app.state.pipeline_settings_lock

    async with lock:
        async with db.session_factory() as session:
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

            ps.updated_at = datetime.now(timezone.utc)
            await session.commit()

            rw_result = await session.execute(select(RegimeWeights))
            app.state.regime_weights = {}
            for rw in rw_result.scalars().all():
                session.expunge(rw)
                app.state.regime_weights[(rw.pair, rw.timeframe)] = rw

        tracker = getattr(app.state, "tracker", None)
        if tracker:
            await tracker.reload_cache()

    return {"applied": True, "diff": diff}
