import asyncio
import time
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from app.logging_config import setup_logging
setup_logging()

_direction_counts = {"LONG": 0, "SHORT": 0}
_direction_lifetime = {"LONG": 0, "SHORT": 0}

import httpx
import pandas as pd
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.dialects.postgresql import insert as pg_insert

from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, cast, literal, update
from sqlalchemy.dialects.postgresql import JSONB

from app.config import Settings
from app.exchange.okx_client import OKXClient
from app.db.database import Base, Database
from app.db.models import Candle, MLTrainingRun, NewsEvent, OrderFlowSnapshot, PipelineEvaluation, PipelineSettings, Signal
from app.collector.ws_client import OKXWebSocketClient
from app.collector.rest_poller import OKXRestPoller
from app.api.routes import create_router
from app.api.connections import ConnectionManager
from app.api.ws import manager as ws_manager
from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.constants import ORDER_FLOW_ASSET_SCALES
from app.engine.combiner import compute_preliminary_score, compute_confidence_tier, compute_llm_contribution, compute_final_score, calculate_levels, blend_with_ml, compute_agreement, apply_agreement_factor, scale_atr_multipliers
from app.engine.patterns import detect_candlestick_patterns, compute_pattern_score
from app.engine.llm import load_prompt_template, render_prompt, call_openrouter
from app.engine.risk import PositionSizer
from app.engine.confluence import (
    CONFLUENCE_ONLY_TIMEFRAMES,
    TIMEFRAME_CACHE_TTL, TIMEFRAME_ANCESTORS, compute_confluence_score,
)
from app.engine.regime import blend_outer_weights, smooth_regime_mix
from app.engine.structure import collect_structure_levels, snap_levels_to_structure
from app.engine.optimizer import lookup_signal_threshold
from app.db.models import RegimeWeights

logger = logging.getLogger(__name__)


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
    "confluence_level_weight_1": "engine_confluence_level_weight_1",
    "confluence_level_weight_2": "engine_confluence_level_weight_2",
    "confluence_trend_alignment_steepness": "engine_confluence_trend_alignment_steepness",
    "confluence_adx_strength_center": "engine_confluence_adx_strength_center",
    "confluence_adx_conviction_ratio": "engine_confluence_adx_conviction_ratio",
    "confluence_mr_penalty_factor": "engine_confluence_mr_penalty_factor",
    "liquidation_weight": "engine_liquidation_weight",
    "liquidation_cluster_max_score": "engine_liquidation_cluster_max_score",
    "liquidation_asymmetry_max_score": "engine_liquidation_asymmetry_max_score",
    "liquidation_cluster_weight": "engine_liquidation_cluster_weight",
    "liquidation_proximity_steepness": "engine_liquidation_proximity_steepness",
    "liquidation_decay_half_life_hours": "engine_liquidation_decay_half_life_hours",
    "liquidation_asymmetry_steepness": "engine_liquidation_asymmetry_steepness",
}


def _update_cvd(cvd: dict, size: float, side: str):
    """Update CVD accumulator with a single trade."""
    delta = size if side == "buy" else -size
    cvd["cumulative"] += delta
    cvd["candle_delta"] += delta
    cvd["_last_updated"] = time.time()


async def handle_trade(app: FastAPI, data: dict):
    """Handle incoming trade from OKX trades channel."""
    pair = data["pair"]
    cvd = app.state.cvd.setdefault(pair, {
        "cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0,
    })
    _update_cvd(cvd, data["size"], data["side"])


async def handle_depth(app: FastAPI, data: dict):
    """Handle incoming order book depth from OKX books5 channel."""
    pair = data["pair"]
    app.state.order_book[pair] = {
        "bids": data["bids"],
        "asks": data["asks"],
        "_last_updated": time.time(),
    }


async def _seed_order_flow(order_flow: dict, session):
    """Seed order_flow dict from latest OrderFlowSnapshot per pair."""
    from sqlalchemy import func
    subq = (
        select(
            OrderFlowSnapshot.pair,
            func.max(OrderFlowSnapshot.id).label("max_id"),
        )
        .group_by(OrderFlowSnapshot.pair)
        .subquery()
    )
    stmt = select(OrderFlowSnapshot).join(
        subq,
        (OrderFlowSnapshot.pair == subq.c.pair)
        & (OrderFlowSnapshot.id == subq.c.max_id),
    )
    result = await session.execute(stmt)
    for snap in result.scalars().all():
        entry = {}
        if snap.funding_rate is not None:
            entry["funding_rate"] = snap.funding_rate
        if snap.open_interest is not None:
            entry["open_interest"] = snap.open_interest
        if snap.long_short_ratio is not None:
            entry["long_short_ratio"] = snap.long_short_ratio
        if entry:
            order_flow[snap.pair] = entry


def _apply_pipeline_overrides(settings, ps):
    """Apply non-None PipelineSettings overrides onto in-memory Settings."""
    for db_col, settings_field in _OVERRIDE_MAP.items():
        value = getattr(ps, db_col, None)
        if value is not None:
            object.__setattr__(settings, settings_field, value)


def _build_raw_indicators(
    *, tech_result, tech_conf, flow_result, onchain_score, onchain_conf,
    pat_score, pattern_conf, liq_score, liq_conf, liq_clusters, liq_details,
    confluence_score, confluence_conf, ml_score, ml_confidence,
    blended, indicator_preliminary, scaled, levels, outer, snap_info, llm_contribution,
    regime=None, llm_result=None,
) -> dict:
    """Build the raw_indicators JSONB dict for a signal."""
    return {
        **tech_result["indicators"],
        # ── Per-source scores (for live signal optimizer) ──
        "tech_score": tech_result["score"],
        "tech_confidence": tech_conf,
        "flow_score": flow_result["score"],
        "flow_confidence": flow_result.get("confidence", 0.0),
        "onchain_score": onchain_score,
        "onchain_confidence": onchain_conf,
        "pattern_score": pat_score,
        "pattern_confidence": pattern_conf,
        "liquidation_score": liq_score,
        "liquidation_confidence": liq_conf,
        "confluence_score": confluence_score,
        "confluence_confidence": confluence_conf,
        "regime_steady": tech_result["indicators"].get("regime_steady"),
        # ── Existing keys ──
        "ml_score": ml_score,
        "ml_confidence": ml_confidence,
        "blended_score": blended,
        "indicator_preliminary": indicator_preliminary,
        "effective_sl_atr": scaled["sl_atr"],
        "effective_tp1_atr": scaled["tp1_atr"],
        "effective_tp2_atr": scaled["tp2_atr"],
        "sl_strength_factor": scaled["sl_strength_factor"],
        "tp_strength_factor": scaled["tp_strength_factor"],
        "vol_factor": scaled["vol_factor"],
        "levels_source": levels["levels_source"],
        "regime_trending": tech_result["indicators"].get("regime_trending"),
        "regime_ranging": tech_result["indicators"].get("regime_ranging"),
        "regime_volatile": tech_result["indicators"].get("regime_volatile"),
        "effective_caps": {k: round(v, 2) for k, v in tech_result["caps"].items()} if regime else None,
        "effective_outer_weights": {k: round(v, 4) for k, v in outer.items()} if regime else None,
        "flow_contrarian_mult": flow_result["details"].get("contrarian_mult"),
        "flow_roc_boost": flow_result["details"].get("roc_boost"),
        "flow_final_mult": flow_result["details"].get("final_mult"),
        "flow_funding_roc": flow_result["details"].get("funding_roc"),
        "flow_ls_roc": flow_result["details"].get("ls_roc"),
        "flow_max_roc": flow_result["details"].get("max_roc"),
        "funding_rate": flow_result["details"].get("funding_rate"),
        "open_interest_change_pct": flow_result["details"].get("open_interest_change_pct"),
        "long_short_ratio": flow_result["details"].get("long_short_ratio"),
        "liquidation_cluster_count": len(liq_clusters),
        **(liq_details if liq_details else {}),
        "llm_contribution": llm_contribution,
        "llm_prompt_tokens": llm_result.prompt_tokens if llm_result else None,
        "llm_completion_tokens": llm_result.completion_tokens if llm_result else None,
        "llm_model": llm_result.model if llm_result else None,
        **({f"snap_{k}": v for k, v in snap_info.items()} if snap_info else {}),
    }


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
        "confluence": {
            "level_weight_1": settings.engine_confluence_level_weight_1,
            "level_weight_2": settings.engine_confluence_level_weight_2,
            "trend_alignment_steepness": settings.engine_confluence_trend_alignment_steepness,
            "adx_strength_center": settings.engine_confluence_adx_strength_center,
            "adx_conviction_ratio": settings.engine_confluence_adx_conviction_ratio,
            "mr_penalty_factor": settings.engine_confluence_mr_penalty_factor,
        },
    }


async def _fetch_news_context(db, pair: str, window_minutes: int = 30) -> tuple[str, list[int]]:
    """Fetch recent high/medium impact news for LLM context and correlation.

    Returns (news_text_for_prompt, list_of_correlated_news_ids).
    """
    symbol = pair.split("-")[0].upper()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    try:
        async with db.session_factory() as session:
            result = await session.execute(
                select(NewsEvent)
                .where(NewsEvent.published_at >= cutoff)
                .where(NewsEvent.impact.in_(["high", "medium"]))
                .where(
                    NewsEvent.affected_pairs.op("@>")(cast(literal(f'["{symbol}"]'), JSONB))
                    | NewsEvent.affected_pairs.op("@>")(cast(literal(f'["ALL"]'), JSONB))
                )
                .order_by(NewsEvent.published_at.desc())
                .limit(10)
            )
            events = result.scalars().all()
    except Exception:
        return "No recent news available.", []

    if not events:
        return "No recent news available.", []

    lines = []
    ids = []
    for e in events:
        impact_tag = f"[{e.impact.upper()}]" if e.impact else ""
        sentiment_tag = f"({e.sentiment})" if e.sentiment else ""
        summary = e.llm_summary or ""
        lines.append(f"- {impact_tag} {e.headline} {sentiment_tag} — {summary}")
        ids.append(e.id)

    return "\n".join(lines), ids


def _pipeline_done_callback(task: asyncio.Task, tasks: set):
    tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(f"Pipeline task failed: {exc}", exc_info=exc)


async def persist_candle(db: Database, candle: dict):
    try:
        async with db.session_factory() as session:
            stmt = pg_insert(Candle).values(
                pair=candle["pair"],
                timeframe=candle["timeframe"],
                timestamp=candle["timestamp"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            ).on_conflict_do_nothing(constraint="uq_candle")
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to persist candle {candle['pair']}:{candle['timeframe']}: {e}")


async def persist_signal(db: Database, signal_data: dict):
    try:
        async with db.session_factory() as session:
            row = Signal(
                pair=signal_data["pair"],
                timeframe=signal_data["timeframe"],
                direction=signal_data["direction"],
                final_score=signal_data["final_score"],
                traditional_score=signal_data["traditional_score"],
                explanation=signal_data.get("explanation"),
                llm_factors=signal_data.get("llm_factors"),
                entry=signal_data["entry"],
                stop_loss=signal_data["stop_loss"],
                take_profit_1=signal_data["take_profit_1"],
                take_profit_2=signal_data["take_profit_2"],
                raw_indicators=signal_data.get("raw_indicators"),
                risk_metrics=signal_data.get("risk_metrics"),
                detected_patterns=signal_data.get("detected_patterns"),
                correlated_news_ids=signal_data.get("correlated_news_ids"),
                engine_snapshot=signal_data.get("engine_snapshot"),
                confidence_tier=signal_data.get("confidence_tier"),
            )
            session.add(row)
            await session.commit()
            signal_data["id"] = row.id
    except Exception as e:
        logger.error(f"Failed to persist signal {signal_data['pair']}: {e}")


async def persist_pipeline_evaluation(db: Database, eval_data: dict):
    """Best-effort persistence of a pipeline evaluation row."""
    try:
        async with db.session_factory() as session:
            session.add(PipelineEvaluation(**eval_data))
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to persist pipeline evaluation for {eval_data.get('pair')}:{eval_data.get('timeframe')}: {e}")


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

    # Evaluate signal alerts
    try:
        from app.engine.alert_evaluator import evaluate_signal_alerts
        push_ctx = {
            "vapid_private_key": settings.vapid_private_key,
            "vapid_claims_email": settings.vapid_claims_email,
        }
        await evaluate_signal_alerts(
            signal_data, db.session_factory, manager, push_ctx,
        )
    except Exception as e:
        logger.debug(f"Signal alert evaluation skipped: {e}")


async def run_pipeline(app: FastAPI, candle: dict):
    settings = app.state.settings
    redis = app.state.redis
    db = app.state.db
    order_flow = app.state.order_flow
    prompt_template = app.state.prompt_template

    # snapshot mutable params to avoid mid-cycle mutation
    scoring_params = dict(getattr(app.state, "scoring_params", {}) or {})
    regime_weights_dict = dict(app.state.regime_weights)

    pair = candle["pair"]
    timeframe = candle["timeframe"]
    order_book = getattr(app.state, "order_book", {})

    try:
        cache_key = f"candles:{pair}:{timeframe}"
        raw_candles = await redis.lrange(cache_key, -200, -1)
    except Exception as e:
        logger.error(f"Redis fetch failed for {pair}:{timeframe}: {e}")
        return

    if len(raw_candles) < 70:
        logger.warning(f"Not enough candles for {pair}:{timeframe} ({len(raw_candles)})")
        return

    candles_data = [json.loads(c) for c in raw_candles]
    df = pd.DataFrame(candles_data)

    # ── Step 1: Indicator scoring (always runs) ──
    rw_key = (pair, timeframe)
    regime_weights = regime_weights_dict.get(rw_key)
    try:
        tech_result = compute_technical_score(
            df, regime_weights=regime_weights,
            scoring_params=scoring_params or None,
            timeframe=timeframe,
        )
    except Exception as e:
        logger.error(f"Technical scoring failed for {pair}:{timeframe}: {e}")
        return

    # ── HTF indicator caching (enriched for multi-level confluence) ──
    indicators = tech_result["indicators"]
    candle_ts = candle.get("timestamp")
    htf_cache = json.dumps({
        "trend_score": indicators.get("trend_score", 0),
        "mean_rev_score": indicators.get("mean_rev_score", 0),
        "trend_conviction": indicators.get("trend_conviction", 0),
        "adx": indicators["adx"],
        "di_plus": indicators["di_plus"],
        "di_minus": indicators["di_minus"],
        "regime": tech_result.get("regime", {}),
        "timestamp": candle_ts.isoformat()
        if hasattr(candle_ts, "isoformat")
        else candle_ts,
    })
    htf_key = f"htf_indicators:{pair}:{timeframe}"
    ttl = TIMEFRAME_CACHE_TTL.get(timeframe, 7200)
    try:
        await redis.set(htf_key, htf_cache, ex=ttl)
    except Exception as e:
        logger.warning(f"HTF indicator cache write failed for {pair}:{timeframe}: {e}")

    # 1D is confluence-only — cache indicators, skip signal emission
    if timeframe in CONFLUENCE_ONLY_TIMEFRAMES:
        return

    # ── Confluence scoring (multi-level, independent source) ──
    confluence_result = {"score": 0, "confidence": 0.0}
    ancestors = TIMEFRAME_ANCESTORS.get(timeframe, [])
    parent_cache_list = []
    if ancestors:
        keys = [f"htf_indicators:{pair}:{anc_tf}" for anc_tf in ancestors]
        try:
            raw_values = await redis.mget(*keys)
        except Exception as e:
            logger.warning(f"HTF cache mget failed for {pair}: {e}")
            raw_values = [None] * len(keys)
        for i, raw in enumerate(raw_values):
            try:
                parent_cache_list.append(json.loads(raw) if raw else None)
            except Exception as e:
                logger.warning(f"HTF cache parse failed for {pair}:{ancestors[i]}: {e}")
                parent_cache_list.append(None)

    if ancestors:
        child_indicators = {
            "trend_score": indicators.get("trend_score", 0),
            "mean_rev_score": indicators.get("mean_rev_score", 0),
            "trend_conviction": indicators.get("trend_conviction", 0),
        }
        confluence_result = compute_confluence_score(
            child_indicators, parent_cache_list,
            timeframe=timeframe,
            level_weight_1=settings.engine_confluence_level_weight_1,
            level_weight_2=settings.engine_confluence_level_weight_2,
            trend_alignment_steepness=settings.engine_confluence_trend_alignment_steepness,
            adx_strength_center=settings.engine_confluence_adx_strength_center,
            adx_conviction_ratio=settings.engine_confluence_adx_conviction_ratio,
            mr_penalty_factor=settings.engine_confluence_mr_penalty_factor,
        )
    confluence_score = confluence_result["score"]
    confluence_conf = confluence_result["confidence"]
    mr_pressure_val = tech_result.get("mr_pressure", 0.0)

    # Evaluate indicator alerts on this candle's indicators
    try:
        from app.engine.alert_evaluator import evaluate_indicator_alerts
        push_ctx = {
            "vapid_private_key": settings.vapid_private_key,
            "vapid_claims_email": settings.vapid_claims_email,
        }
        await evaluate_indicator_alerts(
            pair, timeframe, tech_result["indicators"],
            db.session_factory, app.state.manager, push_ctx,
        )
    except Exception as e:
        logger.debug(f"Indicator alert evaluation skipped: {e}")

    flow_metrics = order_flow.get(pair, {})
    # 3-candle net move smooths doji / small counter-trend noise
    recent_close = float(candle["close"])
    lookback_close = float(candles_data[-4]["close"]) if len(candles_data) >= 4 else float(candle["open"])
    net_move = recent_close - lookback_close
    price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
    flow_metrics = {**flow_metrics, "price_direction": price_direction}

    # Inject CVD into flow_metrics before scoring — read+reset adjacent
    cvd_state = app.state.cvd.get(pair)
    cvd_delta_val = None
    if cvd_state:
        cvd_delta_val = cvd_state["candle_delta"]
        cvd_state["candle_delta"] = 0.0

        # Maintain rolling CVD history for trend scoring
        history = cvd_state.setdefault("history", [])
        history.append(cvd_delta_val)
        if len(history) > 10:
            history.pop(0)

        flow_metrics["cvd_delta"] = cvd_delta_val
        flow_metrics["cvd_history"] = list(history)
        flow_metrics["avg_candle_volume"] = float(candle.get("volume", 0))

    # Query flow history for contrarian bias RoC detection (skip if no flow data)
    flow_history = []
    if flow_metrics:
        try:
            async with db.session_factory() as session:
                result = await session.execute(
                    select(OrderFlowSnapshot.funding_rate, OrderFlowSnapshot.long_short_ratio, OrderFlowSnapshot.oi_change_pct)
                    .where(OrderFlowSnapshot.pair == pair)
                    .order_by(OrderFlowSnapshot.timestamp.desc())
                    .limit(10)
                )
                flow_history = list(reversed(result.all()))
        except Exception as e:
            logger.debug(f"Flow history query skipped: {e}")

    # Compute flow age and asset scale for scoring
    flow_updated = flow_metrics.get("_last_updated")
    flow_age = (time.time() - flow_updated) if flow_updated else None
    asset_scale = ORDER_FLOW_ASSET_SCALES.get(pair, 1.0)

    # Inject book imbalance if fresh depth data available
    # 30s hard limit is a data-validity gate (not a tunable scoring param) —
    # stale depth snapshots are unreliable due to spoofing/cancellation
    depth = app.state.order_book.get(pair)
    if depth and depth.get("bids") and depth.get("asks"):
        book_age = time.time() - depth.get("_last_updated", 0)
        if book_age <= 30:
            bid_vol = sum(size for _, size in depth["bids"])
            ask_vol = sum(size for _, size in depth["asks"])
            total_vol = bid_vol + ask_vol
            if total_vol > 0:
                flow_metrics["book_imbalance"] = (bid_vol - ask_vol) / total_vol

    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=flow_history,
        trend_conviction=tech_result["indicators"].get("trend_conviction", 0.0),
        mr_pressure=tech_result.get("mr_pressure", 0.0),
        flow_age_seconds=flow_age,
        asset_scale=asset_scale,
    )

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
                    cvd_delta=cvd_delta_val,
                )
                session.add(snap)
                await session.commit()
        except Exception as e:
            logger.warning(f"Order flow snapshot save skipped: {e}")

    # Pattern detection
    detected_patterns = []
    pat_result = {"score": 0, "confidence": 0.0}
    try:
        indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
        detected_patterns = detect_candlestick_patterns(df, indicator_ctx)
        regime_mix = tech_result.get("regime") or {}
        pat_result = compute_pattern_score(
            detected_patterns, indicator_ctx,
            strength_overrides=getattr(app.state, "pattern_strength_overrides", None),
            regime_trending=regime_mix.get("trending", 0),
            boost_overrides=getattr(app.state, "pattern_boost_overrides", None),
        )
    except Exception as e:
        logger.debug(f"Pattern detection skipped: {e}")
    pat_score = pat_result["score"]

    # On-chain scoring (if available)
    onchain_result = {"score": 0, "confidence": 0.0}
    onchain_available = False
    if getattr(settings, "onchain_enabled", False):
        try:
            from app.engine.onchain_scorer import compute_onchain_score
            onchain_result = await compute_onchain_score(pair, redis)
            onchain_available = onchain_result["score"] != 0
        except Exception as e:
            logger.debug(f"On-chain scoring skipped: {e}")
    onchain_score = onchain_result["score"]

    # Liquidation scoring (if collector available)
    liq_score = 0
    liq_conf = 0.0
    liq_clusters = []
    liq_details = {}
    liq_result = {}
    liq_collector = getattr(app.state, "liquidation_collector", None)
    if liq_collector:
        try:
            from app.engine.liquidation_scorer import compute_liquidation_score
            liq_atr = tech_result["indicators"].get("atr", None)
            current_price = float(candle["close"])
            if liq_atr is None or liq_atr <= 0:
                liq_atr = current_price * 0.02
            liq_result = compute_liquidation_score(
                events=liq_collector.events.get(pair, []),
                current_price=current_price,
                atr=liq_atr,
                depth=depth,
                cluster_max_score=settings.engine_liquidation_cluster_max_score,
                asymmetry_max_score=settings.engine_liquidation_asymmetry_max_score,
                cluster_weight=settings.engine_liquidation_cluster_weight,
                proximity_steepness=settings.engine_liquidation_proximity_steepness,
                decay_half_life_hours=settings.engine_liquidation_decay_half_life_hours,
                asymmetry_steepness=settings.engine_liquidation_asymmetry_steepness,
            )
            liq_score = liq_result["score"]
            liq_conf = liq_result["confidence"]
            liq_clusters = liq_result["clusters"]
            liq_details = liq_result.get("details", {})
        except Exception as e:
            logger.debug(f"Liquidation scoring skipped: {e}")

    # Regime-aware outer weight blending (smoothed to prevent single-candle flips)
    regime = tech_result.get("regime")
    if regime:
        regime = smooth_regime_mix(regime, app.state.smoothed_regime, pair, timeframe)
    outer = blend_outer_weights(regime, regime_weights)

    tech_w = outer["tech"]
    flow_w = outer["flow"]
    onchain_w = outer["onchain"]
    pattern_w = outer["pattern"]
    liq_w = outer.get("liquidation", 0.0)
    conf_w = outer.get("confluence", 0.0)

    tech_avail = tech_result.get("availability", tech_result.get("confidence", 0.0))
    tech_conv = tech_result.get("conviction", 1.0)
    flow_avail = flow_result.get("availability", flow_result.get("confidence", 0.0))
    flow_conv = flow_result.get("conviction", 1.0)
    onchain_avail = onchain_result.get("availability", onchain_result.get("confidence", 0.0))
    onchain_conv = onchain_result.get("conviction", 1.0)
    pattern_avail = pat_result.get("availability", pat_result.get("confidence", 0.0))
    pattern_conv = pat_result.get("conviction", 1.0)
    liq_avail = liq_result.get("availability", liq_conf)
    liq_conv = liq_result.get("conviction", 1.0)
    confluence_avail = confluence_result.get("availability", confluence_conf)
    confluence_conv = confluence_result.get("conviction", 1.0)

    pruned = getattr(app.state, "pruned_sources", set())
    avail_vars = {"tech": tech_avail, "flow": flow_avail, "onchain": onchain_avail,
                  "pattern": pattern_avail, "liquidation": liq_avail, "confluence": confluence_avail}
    for src in pruned:
        if src in avail_vars:
            avail_vars[src] = 0.0
    tech_avail = avail_vars["tech"]
    flow_avail = avail_vars["flow"]
    onchain_avail = avail_vars["onchain"]
    pattern_avail = avail_vars["pattern"]
    liq_avail = avail_vars["liquidation"]
    confluence_avail = avail_vars["confluence"]

    tech_conf = tech_result.get("confidence", 0.0)
    flow_conf = flow_result.get("confidence", 0.0)
    onchain_conf = onchain_result.get("confidence", 0.0)
    pattern_conf = pat_result.get("confidence", 0.0)

    prelim_result = compute_preliminary_score(
        tech_result["score"],
        flow_result["score"],
        tech_w,
        flow_w,
        onchain_score,
        onchain_w,
        pat_score,
        pattern_w,
        tech_availability=tech_avail,
        tech_conviction=tech_conv,
        flow_availability=flow_avail,
        flow_conviction=flow_conv,
        onchain_availability=onchain_avail,
        onchain_conviction=onchain_conv,
        pattern_availability=pattern_avail,
        pattern_conviction=pattern_conv,
        liquidation_score=liq_score,
        liquidation_weight=liq_w,
        liquidation_availability=liq_avail,
        liquidation_conviction=liq_conv,
        confluence_score=confluence_score,
        confluence_weight=conf_w,
        confluence_availability=confluence_avail,
        confluence_conviction=confluence_conv,
    )
    indicator_preliminary = prelim_result["score"]
    confidence_tier = compute_confidence_tier(prelim_result["avg_confidence"])

    source_scores = [
        tech_result["score"], flow_result["score"], onchain_score,
        pat_score, liq_score, confluence_score,
    ]
    source_avails = [tech_avail, flow_avail, onchain_avail,
                     pattern_avail, liq_avail, confluence_avail]
    indicator_preliminary = apply_agreement_factor(
        indicator_preliminary, source_scores, source_avails,
    )

    # ── Step 2: ML scoring (when available) ──
    ml_score = None
    ml_confidence = None
    ml_prediction = None
    ml_available = False

    pair_slug = pair.replace("-", "_").lower()
    ml_predictors = getattr(app.state, "ml_predictors", {})
    ml_predictor = ml_predictors.get(pair_slug)

    if ml_predictor is not None:
        try:
            from app.ml.features import build_feature_matrix
            from app.ml.utils import bucket_timestamp, compute_per_candle_regime

            # Compute per-candle regime if model needs it
            ml_regime = None
            ml_conviction = None
            if getattr(ml_predictor, "regime_used", False):
                ml_regime, ml_conviction = compute_per_candle_regime(df)

            # Fetch BTC candles from Redis for non-BTC pairs
            ml_btc_df = None
            is_btc = pair.startswith("BTC")
            if not is_btc and getattr(ml_predictor, "btc_used", False):
                try:
                    btc_key = f"candles:BTC-USDT-SWAP:{timeframe}"
                    raw_btc = await redis.lrange(btc_key, -200, -1)
                    if raw_btc:
                        ml_btc_df = pd.DataFrame([json.loads(c) for c in raw_btc])
                except Exception as e:
                    logger.debug(f"BTC candle fetch for ML skipped: {e}")

            # Fetch per-candle flow data
            flow_for_features = None
            if getattr(ml_predictor, "flow_used", False):
                try:
                    cache_key_flow = f"flow_matrix:{pair}:{timeframe}"
                    cached_flow = await redis.get(cache_key_flow)
                    if cached_flow:
                        flow_for_features = json.loads(cached_flow)
                    else:
                        # Postgres fallback with timeout
                        try:
                            async with asyncio.timeout(0.1):
                                async with db.session_factory() as session:
                                    result = await session.execute(
                                        select(OrderFlowSnapshot)
                                        .where(OrderFlowSnapshot.pair == pair)
                                        .order_by(OrderFlowSnapshot.timestamp.desc())
                                        .limit(200)
                                    )
                                    flow_rows = list(reversed(result.scalars().all()))

                            if flow_rows:
                                flow_by_ts = {}
                                for f in flow_rows:
                                    ts_key = bucket_timestamp(f.timestamp, timeframe)
                                    flow_by_ts[ts_key] = {
                                        "funding_rate": f.funding_rate or 0,
                                        "oi_change_pct": f.oi_change_pct or 0,
                                        "long_short_ratio": f.long_short_ratio or 1.0,
                                    }

                                zero_flow = {"funding_rate": 0, "oi_change_pct": 0, "long_short_ratio": 1.0}
                                flow_for_features = []
                                matched = 0
                                for _, row in df.iterrows():
                                    c_ts = pd.Timestamp(row.get("timestamp", 0))
                                    if hasattr(c_ts, "to_pydatetime"):
                                        c_dt = c_ts.to_pydatetime()
                                        if c_dt.tzinfo is None:
                                            from datetime import timezone as _tz
                                            c_dt = c_dt.replace(tzinfo=_tz.utc)
                                        c_dt = bucket_timestamp(c_dt, timeframe)
                                    else:
                                        c_dt = None
                                    snap = flow_by_ts.get(c_dt, zero_flow) if c_dt else zero_flow
                                    if snap is not zero_flow:
                                        matched += 1
                                    flow_for_features.append(snap)

                                coverage = matched / len(df) if len(df) > 0 else 0
                                if coverage < 0.1:
                                    flow_for_features = None
                                else:
                                    # Cache for next cycle
                                    tf_minutes = {"15m": 900, "1h": 3600, "4h": 14400, "1D": 86400}
                                    ttl_flow = tf_minutes.get(timeframe, 3600)
                                    try:
                                        await redis.set(
                                            cache_key_flow,
                                            json.dumps(flow_for_features),
                                            ex=ttl_flow,
                                        )
                                    except Exception:
                                        pass
                        except Exception as e:
                            logger.debug(f"Flow matrix fetch timed out for {pair}: {e}")
                            # Fall back to single-snapshot broadcast
                            flow_data = order_flow.get(pair, {})
                            if flow_data:
                                flow_for_features = [{
                                    "funding_rate": flow_data.get("funding_rate", 0),
                                    "oi_change_pct": flow_data.get("open_interest_change_pct", 0),
                                    "long_short_ratio": flow_data.get("long_short_ratio", 1.0),
                                }] * len(df)
                except Exception as e:
                    logger.debug(f"Flow feature fetch skipped: {e}")

            feature_matrix = build_feature_matrix(
                df,
                order_flow=flow_for_features,
                regime=ml_regime,
                trend_conviction=ml_conviction,
                btc_candles=ml_btc_df,
            )
            ml_prediction = ml_predictor.predict(feature_matrix)

            ml_direction = ml_prediction["direction"]
            ml_confidence = ml_prediction["confidence"]

            # Convert ML output to -100..+100 score
            # Center at 1/3 (uniform probability for 3-class softmax)
            # so confidence=0.33 → 0, confidence=1.0 → 100
            if ml_direction == "NEUTRAL":
                ml_score = 0.0
            else:
                centered = (ml_confidence - 1 / 3) / (2 / 3) * 100
                ml_score = centered if ml_direction == "LONG" else -centered

            ml_available = True
        except Exception as e:
            logger.error(f"ML scoring failed for {pair}:{timeframe}: {e}", exc_info=True)

    # ── Step 3: Blend indicator + ML scores ──
    blended = blend_with_ml(
        indicator_preliminary,
        ml_score,
        ml_confidence,
        ml_weight_min=settings.engine_ml_weight_min,
        ml_weight_max=settings.engine_ml_weight_max,
        ml_confidence_threshold=settings.ml_confidence_threshold,
    )
    agreement = compute_agreement(indicator_preliminary, ml_score)

    # ── Step 4: Fetch news context ──
    news_context = "No recent news available."
    correlated_news_ids = None
    try:
        window = getattr(settings, "news_llm_context_window_minutes", 30)
        news_context, correlated_news_ids = await _fetch_news_context(db, pair, window)
        correlated_news_ids = correlated_news_ids or None
    except Exception as e:
        logger.debug(f"News context fetch skipped: {e}")

    # ── Step 5: LLM gate (on blended score) ──
    llm_result = None
    should_call_llm = (
        abs(blended) >= settings.engine_llm_threshold
        or mr_pressure_val >= settings.engine_mr_llm_trigger
    )
    if should_call_llm and prompt_template:
        if ml_available and ml_prediction:
            ml_context = (
                f"Direction: {ml_prediction['direction']}, "
                f"Confidence: {ml_confidence:.2f}, "
                f"Suggested SL: {ml_prediction['sl_atr']:.2f}x ATR, "
                f"TP1: {ml_prediction['tp1_atr']:.2f}x ATR, "
                f"TP2: {ml_prediction['tp2_atr']:.2f}x ATR"
            )
        else:
            ml_context = "ML model not available for this pair."

        try:
            rendered = render_prompt(
                template=prompt_template,
                pair=pair,
                timeframe=timeframe,
                indicators=json.dumps(tech_result["indicators"], indent=2),
                order_flow=json.dumps(flow_result["details"], indent=2),
                patterns=json.dumps(detected_patterns, indent=2) if detected_patterns else "No patterns detected.",
                onchain=f"Score: {onchain_score}" if onchain_available else "On-chain data not available.",
                ml_context=ml_context,
                news=news_context,
                candles=json.dumps(candles_data[-20:], indent=2),
            )
            llm_result = await call_openrouter(
                prompt=rendered,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                timeout=settings.engine_llm_timeout_seconds,
            )
        except Exception as e:
            logger.error(f"LLM call failed for {pair}:{timeframe}: {e}")

    # ── Step 6: Compute final score ──
    llm_contribution = 0
    if llm_result:
        llm_contribution = compute_llm_contribution(
            llm_result.response.factors,
            settings.llm_factor_weights,
            settings.llm_factor_total_cap,
        )
    final = compute_final_score(blended, llm_contribution)
    direction = "LONG" if final > 0 else "SHORT"

    # ── Step 7: Threshold check + emit (adaptive per-pair/regime) ──
    dominant = max(regime, key=regime.get) if regime else "steady"
    effective_threshold = lookup_signal_threshold(
        pair, dominant, getattr(app.state, "learned_thresholds", {}),
        default=settings.engine_signal_threshold,
    )
    emitted = abs(final) >= effective_threshold

    _log_pipeline_evaluation(
        pair=pair, timeframe=timeframe,
        tech_score=tech_result["score"], flow_score=flow_result["score"],
        onchain_score=onchain_score if onchain_available else None,
        pattern_score=pat_score,
        ml_score=ml_score, ml_confidence=ml_confidence,
        indicator_preliminary=indicator_preliminary,
        blended_score=blended, final_score=final,
        llm_contribution=llm_contribution, ml_available=ml_available,
        agreement=agreement, emitted=emitted,
    )

    manager: ConnectionManager = app.state.manager
    await manager.broadcast_scores({
        "pair": pair,
        "timeframe": timeframe,
        "technical": round(tech_result["score"], 1),
        "order_flow": round(flow_result["score"], 1),
        "onchain": round(onchain_score, 1) if onchain_available else None,
        "patterns": round(pat_score, 1) if pat_score else None,
        "regime_blend": round(indicator_preliminary, 1),
        "ml_gate": round(ml_score, 1) if ml_score is not None else None,
        "llm_gate": round(llm_contribution, 2) if llm_contribution else None,
        "signal": round(final, 1),
        "emitted": emitted,
    })

    app.state.last_pipeline_cycle = time.time()

    # Build lightweight indicators dict for evaluation persistence
    eval_indicators = dict(tech_result.get("indicators", {}))
    pair_flow = order_flow.get(pair, {})
    eval_indicators.update({
        k: pair_flow[k] for k in ("funding_rate", "long_short_ratio", "open_interest_change_pct", "cvd_delta")
        if k in pair_flow
    })

    eval_regime = {
        "trending": regime.get("trending", 0) if regime else 0,
        "ranging": regime.get("ranging", 0) if regime else 0,
        "volatile": regime.get("volatile", 0) if regime else 0,
    }

    eval_availabilities = {
        "tech": {"availability": tech_avail, "conviction": tech_conv},
        "flow": {"availability": flow_avail, "conviction": flow_conv},
        "onchain": {"availability": onchain_avail, "conviction": onchain_conv},
        "pattern": {"availability": pattern_avail, "conviction": pattern_conv},
        "liquidation": {"availability": liq_avail, "conviction": liq_conv},
        "confluence": {"availability": confluence_avail, "conviction": confluence_conv},
    }

    eval_ts = candle.get("timestamp")
    if isinstance(eval_ts, str):
        eval_ts = datetime.fromisoformat(eval_ts)

    eval_kwargs = dict(
        pair=pair,
        timeframe=timeframe,
        evaluated_at=eval_ts,
        emitted=emitted,
        signal_id=None,
        final_score=round(final),
        effective_threshold=round(effective_threshold),
        tech_score=round(tech_result["score"]),
        flow_score=round(flow_result["score"]),
        onchain_score=round(onchain_score) if onchain_available else None,
        pattern_score=round(pat_score) if pat_score else None,
        liquidation_score=round(liq_score) if liq_score else None,
        confluence_score=round(confluence_score) if confluence_score else None,
        indicator_preliminary=round(indicator_preliminary),
        blended_score=round(blended),
        ml_score=ml_score,
        ml_confidence=ml_confidence,
        llm_contribution=round(llm_contribution),
        ml_agreement=agreement,
        indicators=eval_indicators,
        regime=eval_regime,
        availabilities=eval_availabilities,
    )

    if not emitted:
        asyncio.create_task(persist_pipeline_evaluation(db, eval_kwargs))
        return

    # ── Step 8: Calculate levels ──
    atr = tech_result["indicators"].get("atr", 200)
    bb_width_pct = tech_result["indicators"].get("bb_width_pct", 50.0)

    # Phase 1: signal strength + volatility scaling
    # Phase 2 learned base multipliers are fetched from tracker if available,
    # otherwise defaults (1.5/2.0/3.0) are used.
    sl_base, tp1_base, tp2_base = 1.5, 2.0, 3.0
    tracker = getattr(app.state, "tracker", None)
    if tracker is not None:
        sl_base, tp1_base, tp2_base = await tracker.get_multipliers(pair, timeframe)

    scaled = scale_atr_multipliers(
        score=final, bb_width_pct=bb_width_pct,
        sl_base=sl_base, tp1_base=tp1_base, tp2_base=tp2_base,
        signal_threshold=effective_threshold,
    )

    llm_levels = None
    if llm_result and llm_result.response.levels:
        llm_levels = llm_result.response.levels.model_dump()

    ml_atr_multiples = None
    if (
        ml_available
        and ml_prediction
        and ml_confidence is not None
        and ml_confidence >= settings.ml_confidence_threshold
    ):
        # Phase 1 scaling applies to ML multiples too
        ml_atr_multiples = {
            "sl_atr": ml_prediction["sl_atr"] * scaled["sl_strength_factor"] * scaled["vol_factor"],
            "tp1_atr": ml_prediction["tp1_atr"] * scaled["tp_strength_factor"] * scaled["vol_factor"],
            "tp2_atr": ml_prediction["tp2_atr"] * scaled["tp_strength_factor"] * scaled["vol_factor"],
        }

    levels = calculate_levels(
        direction=direction,
        current_price=float(candle["close"]),
        atr=atr,
        llm_levels=llm_levels,
        ml_atr_multiples=ml_atr_multiples,
        llm_contribution=llm_contribution,
        sl_bounds=(settings.ml_sl_min_atr, settings.ml_sl_max_atr),
        tp1_min_atr=settings.ml_tp1_min_atr,
        tp2_max_atr=settings.ml_tp2_max_atr,
        rr_floor=settings.ml_rr_floor,
        sl_atr_default=scaled["sl_atr"],
        tp1_atr_default=scaled["tp1_atr"],
        tp2_atr_default=scaled["tp2_atr"],
    )

    # Post-process: snap levels to nearby technical structure
    structure = collect_structure_levels(df, tech_result["indicators"], atr,
                                         liquidation_clusters=liq_clusters,
                                         depth=depth)
    levels, snap_info = snap_levels_to_structure(
        levels, structure, direction, atr,
        sl_min_atr=settings.ml_sl_min_atr,
        sl_max_atr=settings.ml_sl_max_atr,
    )

    regime_mix = regime if regime else {
        "trending": tech_result["indicators"].get("regime_trending", 0),
        "ranging": tech_result["indicators"].get("regime_ranging", 0),
        "volatile": tech_result["indicators"].get("regime_volatile", 0),
    }
    snapshot_caps = {k: round(v, 2) for k, v in tech_result["caps"].items()} if tech_result.get("caps") else {}
    snapshot_outer = {k: round(v, 4) for k, v in outer.items()} if regime else {}
    atr_source = "performance_tracker" if tracker else "defaults"
    engine_snapshot = build_engine_snapshot(
        settings,
        scoring_params or None,
        regime_mix, snapshot_caps, snapshot_outer,
        (sl_base, tp1_base, tp2_base), atr_source,
    )

    signal_data = {
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "final_score": final,
        "traditional_score": tech_result["score"],
        "explanation": llm_result.response.explanation if llm_result else None,
        "llm_factors": [f.model_dump() for f in llm_result.response.factors] if llm_result else None,
        **levels,
        "raw_indicators": _build_raw_indicators(
            tech_result=tech_result, tech_conf=tech_conf,
            flow_result=flow_result, onchain_score=onchain_score, onchain_conf=onchain_conf,
            pat_score=pat_score, pattern_conf=pattern_conf,
            liq_score=liq_score, liq_conf=liq_conf, liq_clusters=liq_clusters, liq_details=liq_details,
            confluence_score=confluence_score, confluence_conf=confluence_conf,
            ml_score=ml_score, ml_confidence=ml_confidence,
            blended=blended, indicator_preliminary=indicator_preliminary,
            scaled=scaled, levels=levels, outer=outer, snap_info=snap_info,
            llm_contribution=llm_contribution, regime=regime, llm_result=llm_result,
        ),
        "detected_patterns": detected_patterns or None,
        "engine_snapshot": engine_snapshot,
        "confidence_tier": confidence_tier,
    }

    await _emit_signal(app, signal_data, levels, correlated_news_ids)

    eval_kwargs["signal_id"] = signal_data.get("id")
    asyncio.create_task(persist_pipeline_evaluation(db, eval_kwargs))


def _log_pipeline_evaluation(
    *, pair, timeframe, tech_score, flow_score, onchain_score,
    pattern_score, ml_score, ml_confidence, indicator_preliminary,
    blended_score, final_score, llm_contribution, ml_available, agreement, emitted,
):
    """Structured observability log for each pipeline evaluation."""
    log_data = {
        "pair": pair,
        "timeframe": timeframe,
        "tech_score": tech_score,
        "flow_score": flow_score,
        "onchain_score": onchain_score,
        "pattern_score": pattern_score,
        "ml_score": round(ml_score, 1) if ml_score is not None else None,
        "ml_confidence": round(ml_confidence, 3) if ml_confidence is not None else None,
        "indicator_preliminary": indicator_preliminary,
        "blended_score": blended_score,
        "final_score": final_score,
        "llm_contribution": llm_contribution,
        "ml_available": ml_available,
        "agreement": agreement,
        "emitted": emitted,
    }
    logger.info(f"Pipeline evaluation: {json.dumps(log_data)}")

    if emitted:
        direction = "LONG" if final_score > 0 else "SHORT"
        _direction_counts[direction] += 1
        _direction_lifetime[direction] += 1
        total = _direction_counts["LONG"] + _direction_counts["SHORT"]
        if total >= 20:
            long_c, short_c = _direction_counts["LONG"], _direction_counts["SHORT"]
            lt_long, lt_short = _direction_lifetime["LONG"], _direction_lifetime["SHORT"]
            lt_total = lt_long + lt_short
            logger.info(f"Direction split (last {total}): LONG={long_c} ({round(long_c*100/total)}%) SHORT={short_c} ({round(short_c*100/total)}%)")
            logger.info(f"Direction split (lifetime {lt_total}): LONG={lt_long} ({round(lt_long*100/lt_total)}%) SHORT={lt_short} ({round(lt_short*100/lt_total)}%)")
            _direction_counts["LONG"] = 0
            _direction_counts["SHORT"] = 0


async def handle_candle(app: FastAPI, candle: dict):
    redis = app.state.redis
    db = app.state.db

    cache_key = f"candles:{candle['pair']}:{candle['timeframe']}"
    candle_json = json.dumps({
        "timestamp": candle["timestamp"].isoformat(),
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
    })

    try:
        await redis.rpush(cache_key, candle_json)
        await redis.ltrim(cache_key, -200, -1)
    except Exception as e:
        logger.error(f"Redis cache failed for {candle['pair']}:{candle['timeframe']}: {e}")

    await persist_candle(db, candle)

    task = asyncio.create_task(run_pipeline(app, candle))
    app.state.pipeline_tasks.add(task)
    task.add_done_callback(
        lambda t: _pipeline_done_callback(t, app.state.pipeline_tasks)
    )


async def handle_candle_tick(app: FastAPI, candle: dict):
    """Handle all candle ticks (confirmed and unconfirmed)."""
    manager = app.state.manager

    tick = {
        "pair": candle["pair"],
        "timeframe": candle["timeframe"],
        "timestamp": candle["timestamp"].isoformat() if hasattr(candle["timestamp"], "isoformat") else candle["timestamp"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
        "confirmed": candle["confirmed"],
    }
    await manager.broadcast_candle(tick)

    if candle["confirmed"]:
        await handle_candle(app, candle)


async def handle_funding_rate(app: FastAPI, data: dict):
    flow = app.state.order_flow.setdefault(data["pair"], {})
    flow["funding_rate"] = data["funding_rate"]
    flow["_last_updated"] = time.time()

    try:
        from app.engine.alert_evaluator import evaluate_indicator_alerts
        push_ctx = {
            "vapid_private_key": app.state.settings.vapid_private_key,
            "vapid_claims_email": app.state.settings.vapid_claims_email,
        }
        await evaluate_indicator_alerts(
            data["pair"], None,
            {"funding_rate": data["funding_rate"]},
            app.state.db.session_factory, app.state.manager, push_ctx,
        )
    except Exception as e:
        logger.debug(f"Funding rate alert evaluation skipped: {e}")


async def handle_open_interest(app: FastAPI, data: dict):
    flow = app.state.order_flow.setdefault(data["pair"], {})
    prev_oi = flow.get("open_interest", data["open_interest"])
    current_oi = data["open_interest"]
    if prev_oi > 0:
        flow["open_interest_change_pct"] = (current_oi - prev_oi) / prev_oi
    flow["open_interest"] = current_oi
    flow["_last_updated"] = time.time()


async def handle_long_short_data(app: FastAPI, data: dict):
    flow = app.state.order_flow.setdefault(data["pair"], {})
    flow["long_short_ratio"] = data["long_short_ratio"]
    flow["_last_updated"] = time.time()


async def check_pending_signals(app: FastAPI):
    """Check all PENDING signals against recent candles for outcome resolution."""
    db = app.state.db
    redis = app.state.redis

    from app.engine.outcome_resolver import resolve_signal_outcome

    async with db.session_factory() as session:
        result = await session.execute(
            select(Signal).where(Signal.outcome == "PENDING").order_by(Signal.created_at.desc()).limit(50)
        )
        pending = result.scalars().all()
        resolved_pairs_timeframes: set[tuple[str, str]] = set()

        for signal in pending:
            # Check expiry (24h)
            age = (datetime.now(timezone.utc) - signal.created_at).total_seconds()
            if age > 86400:
                signal.outcome = "EXPIRED"
                signal.outcome_at = datetime.now(timezone.utc)
                signal.outcome_duration_minutes = round(age / 60)
                resolved_pairs_timeframes.add((signal.pair, signal.timeframe))
                continue

            cache_key = f"candles:{signal.pair}:{signal.timeframe}"
            raw_candles = await redis.lrange(cache_key, -200, -1)
            if not raw_candles:
                continue

            import json as _json
            candles_data = [_json.loads(c) for c in raw_candles]

            # Only check candles after signal creation
            signal_ts = signal.created_at.isoformat()
            candles_after = [c for c in candles_data if c["timestamp"] > signal_ts]
            if not candles_after:
                continue

            signal_dict = {
                "direction": signal.direction,
                "entry": float(signal.entry),
                "stop_loss": float(signal.stop_loss),
                "take_profit_1": float(signal.take_profit_1),
                "take_profit_2": float(signal.take_profit_2),
                "created_at": signal.created_at,
            }

            # Parse candle floats
            parsed = []
            for c in candles_after:
                parsed.append({
                    "high": float(c.get("high", c.get("h", 0))),
                    "low": float(c.get("low", c.get("l", 0))),
                    "close": float(c.get("close", c.get("c", 0))),
                    "timestamp": c["timestamp"],
                })

            outcome = resolve_signal_outcome(signal_dict, parsed)
            if outcome:
                signal.outcome = outcome["outcome"]
                signal.outcome_at = outcome["outcome_at"]
                signal.outcome_pnl_pct = outcome["outcome_pnl_pct"]
                signal.outcome_duration_minutes = outcome["outcome_duration_minutes"]
                resolved_pairs_timeframes.add((signal.pair, signal.timeframe))

        await session.commit()

        # Notify optimizer of resolved signals
        optimizer = getattr(app.state, "optimizer", None)
        if optimizer is not None:
            for signal in pending:
                if signal.outcome != "PENDING" and signal.outcome_pnl_pct is not None:
                    optimizer.record_resolution(signal.outcome_pnl_pct)

        # Phase 2: check optimization triggers after batch resolution
        tracker = getattr(app.state, "tracker", None)
        if resolved_pairs_timeframes and tracker is not None:
            async with db.session_factory() as trigger_session:
                await tracker.check_optimization_triggers(
                    trigger_session, resolved_pairs_timeframes
                )

        # ── IC pruning: daily computation ──
        last_ic = getattr(app.state, "last_ic_computed_at", None)
        now = datetime.now(timezone.utc)
        if last_ic is None or (now - last_ic).total_seconds() > 86400:
            try:
                from app.engine.optimizer import run_ic_pruning_cycle

                current_pruned = getattr(app.state, "pruned_sources", set())
                updated = await run_ic_pruning_cycle(db, current_pruned, logger)
                if updated is not None:
                    app.state.pruned_sources = updated
                app.state.last_ic_computed_at = now
            except Exception as e:
                logger.warning(f"IC pruning computation failed: {e}")


OKX_BAR_MAP = {"15m": "15m", "1h": "1H", "4h": "4H", "1D": "1Dutc"}


async def backfill_candles(redis, db, pairs: list[str], timeframes: list[str]):
    """Fetch historical candles from OKX REST API and seed Redis + DB."""
    async with httpx.AsyncClient(timeout=15) as client:
        for pair in pairs:
            for tf in timeframes:
                cache_key = f"candles:{pair}:{tf}"
                bar = OKX_BAR_MAP.get(tf)
                if not bar:
                    continue

                try:
                    resp = await client.get(
                        "https://www.okx.com/api/v5/market/candles",
                        params={"instId": pair, "bar": bar, "limit": "100"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Backfill fetch failed for {pair}:{tf}: {e}")
                    continue

                rows = data.get("data", [])
                if not rows:
                    logger.warning(f"Backfill: no data returned for {pair}:{tf}")
                    continue

                # OKX returns newest-first; reverse for chronological order
                rows.reverse()

                # Clear stale cache to avoid ordering issues with leftover live candles
                await redis.delete(cache_key)

                pipe = redis.pipeline()
                for row in rows:
                    ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                    candle = {
                        "timestamp": ts.isoformat(),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                    pipe.rpush(cache_key, json.dumps(candle))

                    await persist_candle(db, {
                        "pair": pair,
                        "timeframe": tf,
                        "timestamp": ts,
                        **{k: candle[k] for k in ("open", "high", "low", "close", "volume")},
                    })

                pipe.ltrim(cache_key, -200, -1)
                await pipe.execute()
                logger.info(f"Backfilled {len(rows)} candles for {pair}:{tf}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = Database(settings.database_url)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    app.state.settings = settings
    app.state.db = db
    app.state.session_factory = db.session_factory
    app.state.redis = redis
    app.state.manager = ws_manager

    setup_logging()  # re-apply after uvicorn overrides root logger
    from app.logging_config import DBErrorHandler
    db_log_handler = DBErrorHandler(session_factory=db.session_factory)
    logging.getLogger().addHandler(db_log_handler)
    db_log_flush_task = asyncio.create_task(db_log_handler.start_flush_loop())
    app.state.order_flow = {}
    app.state.cvd = {}
    app.state.order_book = {}
    try:
        async with db.session_factory() as session:
            await _seed_order_flow(app.state.order_flow, session)
        logger.info("Seeded order flow for %d pairs", len(app.state.order_flow))
    except Exception as e:
        logger.warning("Order flow preload failed: %s", e)
    app.state.pipeline_tasks = set()
    app.state.active_signal_optimization = None
    app.state.start_time = time.time()
    app.state.last_pipeline_cycle = 0.0
    app.state.pattern_strength_overrides = None
    app.state.pattern_boost_overrides = None
    app.state.pipeline_settings_lock = asyncio.Lock()

    from app.engine.performance_tracker import PerformanceTracker
    app.state.tracker = PerformanceTracker(db.session_factory)

    try:
        await app.state.tracker.bootstrap_from_backtests()
    except Exception as e:
        logger.warning("Tracker bootstrap failed: %s", e)

    from app.engine.optimizer import OptimizerState
    app.state.optimizer = OptimizerState()

    # Load learned regime weights from DB
    app.state.regime_weights = {}
    try:
        async with db.session_factory() as session:
            result = await session.execute(select(RegimeWeights))
            for rw in result.scalars().all():
                session.expunge(rw)  # detach from session so attributes remain accessible
                app.state.regime_weights[(rw.pair, rw.timeframe)] = rw
        if app.state.regime_weights:
            logger.info("Loaded regime weights for %d pair/timeframe combos", len(app.state.regime_weights))
    except Exception as e:
        logger.warning("Failed to load regime weights: %s", e)

    app.state.smoothed_regime = {}

    # Load PipelineSettings from DB and patch onto in-memory settings
    _db_to_settings = {
        "signal_threshold": "engine_signal_threshold",
        "news_alerts_enabled": "news_high_impact_push_enabled",
        "news_context_window": "news_llm_context_window_minutes",
    }
    try:
        async with db.session_factory() as session:
            result = await session.execute(
                select(PipelineSettings).where(PipelineSettings.id == 1)
            )
            ps = result.scalar_one_or_none()
            if ps:
                for db_field in ("pairs", "timeframes", "signal_threshold", "onchain_enabled", "news_alerts_enabled", "news_context_window"):
                    settings_field = _db_to_settings.get(db_field, db_field)
                    object.__setattr__(settings, settings_field, getattr(ps, db_field))
                logger.info("Pipeline settings loaded from DB")
                app.state.scoring_params = {
                    "mean_rev_rsi_steepness": ps.mean_rev_rsi_steepness,
                    "mean_rev_bb_pos_steepness": ps.mean_rev_bb_pos_steepness,
                    "squeeze_steepness": ps.squeeze_steepness,
                    "mean_rev_blend_ratio": ps.mean_rev_blend_ratio,
                }
                _apply_pipeline_overrides(settings, ps)
                app.state.pattern_strength_overrides = getattr(ps, "pattern_strength_overrides", None)
                app.state.pattern_boost_overrides = getattr(ps, "pattern_boost_overrides", None)
            else:
                logger.warning("No PipelineSettings row found; using config defaults")
                app.state.scoring_params = None
                app.state.pattern_strength_overrides = None
                app.state.pattern_boost_overrides = None
    except Exception as e:
        logger.warning("Failed to load PipelineSettings from DB: %s", e)
        app.state.scoring_params = None
        app.state.pattern_strength_overrides = None
        app.state.pattern_boost_overrides = None

    # Clean up stale backtest/ML runs orphaned by previous container restarts
    try:
        from app.db.models import BacktestRun
        async with db.session_factory() as session:
            result = await session.execute(
                select(BacktestRun).where(BacktestRun.status == "running")
            )
            stale = result.scalars().all()
            for run in stale:
                run.status = "failed"
            if stale:
                await session.commit()
                logger.info("Marked %d stale backtest run(s) as failed", len(stale))
    except Exception as e:
        logger.warning("Failed to clean up stale runs: %s", e)

    try:
        async with db.session_factory() as session:
            await session.execute(
                update(MLTrainingRun)
                .where(MLTrainingRun.status == "running")
                .values(
                    status="failed",
                    error="Server restarted during training",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
    except Exception as e:
        logger.warning("Failed to clean up stale ML training runs: %s", e)

    prompt_path = Path(__file__).parent / "prompts" / "signal_analysis.txt"
    app.state.prompt_template = load_prompt_template(prompt_path) if prompt_path.exists() else ""

    if settings.okx_api_key:
        app.state.okx_client = OKXClient(
            api_key=settings.okx_api_key,
            api_secret=settings.okx_api_secret,
            passphrase=settings.okx_passphrase,
            demo=settings.okx_demo,
        )
    else:
        app.state.okx_client = None

    await backfill_candles(redis, db, settings.pairs, settings.timeframes)

    ws_client = OKXWebSocketClient(
        pairs=settings.pairs,
        timeframes=settings.timeframes,
        on_candle=lambda c: handle_candle_tick(app, c),
        on_funding_rate=lambda d: handle_funding_rate(app, d),
        on_open_interest=lambda d: handle_open_interest(app, d),
        on_trade=lambda d: handle_trade(app, d),
        on_depth=lambda d: handle_depth(app, d),
    )
    rest_poller = OKXRestPoller(
        pairs=settings.pairs,
        interval_seconds=settings.collector_rest_poll_interval_seconds,
        on_data=lambda d: handle_long_short_data(app, d),
    )

    app.state.ws_client = ws_client
    app.state.rest_poller = rest_poller

    ws_task = asyncio.create_task(ws_client.connect())
    app.state.ws_task = ws_task
    poller_task = asyncio.create_task(rest_poller.run())

    async def outcome_loop():
        while True:
            try:
                await check_pending_signals(app)
            except Exception as e:
                logger.error(f"Outcome check failed: {e}")
            await asyncio.sleep(60)

    outcome_task = asyncio.create_task(outcome_loop())

    # On-chain collector
    onchain_task = None
    onchain_collector = None
    if settings.onchain_enabled:
        from app.collector.onchain import OnChainCollector
        onchain_collector = OnChainCollector(
            pairs=settings.pairs,
            redis=redis,
            poll_interval=settings.onchain_poll_interval_seconds,
            tier2_interval=settings.onchain_tier2_poll_interval_seconds,
            cryptoquant_api_key=settings.cryptoquant_api_key,
        )
        onchain_task = asyncio.create_task(onchain_collector.run())
    app.state.onchain_collector = onchain_collector

    # Liquidation collector
    from app.collector.liquidation import LiquidationCollector
    liq_collector = LiquidationCollector(app.state.okx_client, settings.pairs, redis=app.state.redis)
    await liq_collector.load_from_redis()
    await liq_collector.start()
    app.state.liquidation_collector = liq_collector
    app.state.learned_thresholds = {}  # populated by optimizer
    app.state.pruned_sources = set()   # populated by IC tracking
    app.state.last_ic_computed_at = None  # populated by IC tracking

    # News collector
    from app.collector.news import NewsCollector
    news_collector = NewsCollector(
        pairs=settings.pairs,
        db=db,
        redis=redis,
        ws_manager=ws_manager,
        poll_interval=settings.news_poll_interval_seconds,
        cryptopanic_api_key=settings.cryptopanic_api_key,
        news_api_key=settings.news_api_key,
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_model=settings.openrouter_model,
        relevance_keywords=settings.news_relevance_keywords,
        rss_feeds=settings.news_rss_feeds,
        llm_daily_budget=settings.news_llm_daily_budget,
        high_impact_push_enabled=settings.news_high_impact_push_enabled,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims_email=settings.vapid_claims_email,
    )
    app.state.news_collector = news_collector
    news_task = asyncio.create_task(news_collector.run())

    # Ticker collector (for price alerts)
    from app.collector.ticker import TickerCollector
    from app.engine.alert_evaluator import evaluate_price_alerts, evaluate_portfolio_alerts, cleanup_alert_history

    push_ctx = {
        "vapid_private_key": settings.vapid_private_key,
        "vapid_claims_email": settings.vapid_claims_email,
    }

    ticker_collector = TickerCollector(
        pairs=settings.pairs,
        redis=redis,
        session_factory=db.session_factory,
        manager=ws_manager,
        push_ctx=push_ctx,
        evaluate_fn=evaluate_price_alerts,
    )
    app.state.ticker_collector = ticker_collector
    ticker_task = asyncio.create_task(ticker_collector.run())

    # Account poller (for portfolio alerts)
    from app.collector.account_poller import AccountPoller
    account_poller = AccountPoller(
        okx_client=app.state.okx_client,
        redis=redis,
        session_factory=db.session_factory,
        manager=ws_manager,
        push_ctx=push_ctx,
        evaluate_fn=evaluate_portfolio_alerts,
    )
    app.state.account_poller = account_poller
    account_task = asyncio.create_task(account_poller.run())

    # Alert history cleanup (daily — run immediately then every 24h)
    async def alert_cleanup_loop():
        while True:
            try:
                await cleanup_alert_history(db.session_factory)
            except Exception as e:
                logger.error(f"Alert history cleanup failed: {e}")
            await asyncio.sleep(86400)  # 24 hours

    alert_cleanup_task = asyncio.create_task(alert_cleanup_loop())

    async def error_log_cleanup_loop():
        from app.db.models import ErrorLog
        while True:
            try:
                async with db.session_factory() as session:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                    await session.execute(
                        ErrorLog.__table__.delete().where(ErrorLog.timestamp < cutoff)
                    )
                    count_result = await session.execute(
                        select(func.count()).select_from(ErrorLog)
                    )
                    total = count_result.scalar() or 0
                    if total > 10000:
                        keep_cutoff = select(ErrorLog.timestamp).order_by(
                            ErrorLog.timestamp.desc()
                        ).offset(10000).limit(1).scalar_subquery()
                        await session.execute(
                            ErrorLog.__table__.delete().where(ErrorLog.timestamp < keep_cutoff)
                        )
                    await session.commit()
            except Exception as e:
                logger.error(f"Error log cleanup failed: {e}")
            await asyncio.sleep(3600)

    error_log_cleanup_task = asyncio.create_task(error_log_cleanup_loop())

    async def pipeline_eval_prune_loop():
        while True:
            try:
                async with db.session_factory() as session:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                    await session.execute(
                        PipelineEvaluation.__table__.delete().where(
                            PipelineEvaluation.evaluated_at < cutoff
                        )
                    )
                    await session.commit()
                logger.info("Pipeline evaluation pruning completed")
            except Exception as e:
                logger.error(f"Pipeline evaluation pruning failed: {e}")
            await asyncio.sleep(86400)

    pipeline_eval_prune_task = asyncio.create_task(pipeline_eval_prune_loop())

    # Start optimizer background loop
    from app.engine.optimizer import run_optimizer_loop
    optimizer_task = asyncio.create_task(run_optimizer_loop(app))

    # Data freshness watchdog
    from app.collector.watchdog import run_watchdog
    watchdog_task = asyncio.create_task(run_watchdog(app.state))

    # Load per-pair ML predictors if enabled
    app.state.ml_predictors = {}
    if getattr(settings, "ml_enabled", False):
        from app.api.ml import _reload_predictors
        _reload_predictors(app, settings)

    yield

    await ws_client.stop()
    rest_poller.stop()
    ws_task.cancel()
    poller_task.cancel()
    outcome_task.cancel()
    optimizer_task.cancel()
    news_collector.stop()
    news_task.cancel()
    ticker_collector.stop()
    ticker_task.cancel()
    account_poller.stop()
    account_task.cancel()
    alert_cleanup_task.cancel()
    db_log_flush_task.cancel()
    error_log_cleanup_task.cancel()
    pipeline_eval_prune_task.cancel()
    logging.getLogger().removeHandler(db_log_handler)
    watchdog_task.cancel()
    if onchain_task:
        onchain_collector.stop()
        onchain_task.cancel()
    liq_collector = getattr(app.state, "liquidation_collector", None)
    if liq_collector:
        await liq_collector.stop()
    await redis.close()
    await db.close()


def create_app(lifespan_override=None) -> FastAPI:
    app = FastAPI(title="Krypton", version="0.1.0", lifespan=lifespan_override or lifespan)

    allowed_origins = [
        "http://localhost:5173",
        "http://localhost:4173",
    ]
    cors_origin = os.environ.get("CORS_ORIGIN", "")
    for origin in cors_origin.split(","):
        origin = origin.strip()
        if origin:
            allowed_origins.append(origin)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    from app.api.auth import router as auth_router
    app.include_router(auth_router)

    router = create_router()
    app.include_router(router)

    from app.api.ws import router as ws_router
    app.include_router(ws_router)

    from app.api.push import router as push_router
    app.include_router(push_router)

    from app.api.candles import router as candles_router
    app.include_router(candles_router)

    from app.api.account import router as account_router
    app.include_router(account_router)

    from app.api.risk import router as risk_router
    app.include_router(risk_router)

    from app.api.news import router as news_router
    app.include_router(news_router)

    from app.api.backtest import router as backtest_router
    app.include_router(backtest_router)

    from app.api.pipeline_settings import router as pipeline_router
    app.include_router(pipeline_router)

    from app.api.ml import router as ml_router
    app.include_router(ml_router)

    from app.api.alerts import router as alerts_router
    app.include_router(alerts_router)

    from app.api.engine import router as engine_router
    app.include_router(engine_router)

    from app.api.system import router as system_router
    app.include_router(system_router)

    from app.api.optimizer import router as optimizer_router
    app.include_router(optimizer_router)

    from app.api.monitor import router as monitor_router
    app.include_router(monitor_router)

    return app


app = create_app()
