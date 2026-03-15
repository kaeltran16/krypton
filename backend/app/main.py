import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(
    level=logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO").upper()),
    format="%(levelname)s %(name)s: %(message)s",
)

import httpx
import pandas as pd
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.dialects.postgresql import insert as pg_insert

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, cast, literal
from sqlalchemy.dialects.postgresql import JSONB

from app.config import Settings
from app.exchange.okx_client import OKXClient
from app.db.database import Base, Database
from app.db.models import Candle, NewsEvent, OrderFlowSnapshot, PipelineSettings, Signal
from app.collector.ws_client import OKXWebSocketClient
from app.collector.rest_poller import OKXRestPoller
from app.api.routes import create_router
from app.api.ws import manager as ws_manager
from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels, blend_with_ml, compute_agreement, scale_atr_multipliers
from app.engine.patterns import detect_candlestick_patterns, compute_pattern_score
from app.engine.llm import load_prompt_template, render_prompt, call_openrouter
from app.engine.risk import PositionSizer

logger = logging.getLogger(__name__)


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
                llm_opinion=signal_data.get("llm_opinion"),
                llm_confidence=signal_data.get("llm_confidence"),
                explanation=signal_data.get("explanation"),
                entry=signal_data["entry"],
                stop_loss=signal_data["stop_loss"],
                take_profit_1=signal_data["take_profit_1"],
                take_profit_2=signal_data["take_profit_2"],
                raw_indicators=signal_data.get("raw_indicators"),
                risk_metrics=signal_data.get("risk_metrics"),
                detected_patterns=signal_data.get("detected_patterns"),
                correlated_news_ids=signal_data.get("correlated_news_ids"),
            )
            session.add(row)
            await session.commit()
            signal_data["id"] = row.id
    except Exception as e:
        logger.error(f"Failed to persist signal {signal_data['pair']}: {e}")


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

    pair = candle["pair"]
    timeframe = candle["timeframe"]

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
    try:
        tech_result = compute_technical_score(df)
    except Exception as e:
        logger.error(f"Technical scoring failed for {pair}:{timeframe}: {e}")
        return

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
    # Inject price direction for direction-aware OI scoring
    flow_metrics = {**flow_metrics, "price_direction": 1 if candle["close"] >= candle["open"] else -1}
    flow_result = compute_order_flow_score(flow_metrics)

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

    # Pattern detection
    detected_patterns = []
    pat_score = 0
    try:
        detected_patterns = detect_candlestick_patterns(df)
        indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
        pat_score = compute_pattern_score(detected_patterns, indicator_ctx)
    except Exception as e:
        logger.debug(f"Pattern detection skipped: {e}")

    # On-chain scoring (if available)
    onchain_score = 0
    onchain_available = False
    if getattr(settings, "onchain_enabled", False):
        try:
            from app.engine.onchain_scorer import compute_onchain_score
            onchain_score = await compute_onchain_score(pair, redis)
            onchain_available = onchain_score != 0
        except Exception as e:
            logger.debug(f"On-chain scoring skipped: {e}")

    # Adaptive weight redistribution: zero unavailable sources, normalize rest
    flow_available = bool(flow_metrics)
    tech_w = settings.engine_traditional_weight
    flow_w = settings.engine_flow_weight if flow_available else 0.0
    onchain_w = settings.engine_onchain_weight if onchain_available else 0.0
    pattern_w = getattr(settings, "engine_pattern_weight", 0.15)
    total_w = tech_w + flow_w + onchain_w + pattern_w
    if total_w > 0:
        tech_w /= total_w
        flow_w /= total_w
        onchain_w /= total_w
        pattern_w /= total_w

    indicator_preliminary = compute_preliminary_score(
        tech_result["score"],
        flow_result["score"],
        tech_w,
        flow_w,
        onchain_score,
        onchain_w,
        pat_score,
        pattern_w,
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

            flow_for_features = None
            if getattr(ml_predictor, "flow_used", False):
                flow_data = order_flow.get(pair, {})
                if flow_data:
                    flow_for_features = [{
                        "funding_rate": flow_data.get("funding_rate", 0),
                        "oi_change_pct": flow_data.get("open_interest_change_pct", 0),
                        "long_short_ratio": flow_data.get("long_short_ratio", 1.0),
                    }] * len(df)

            feature_matrix = build_feature_matrix(df, order_flow=flow_for_features)
            ml_prediction = ml_predictor.predict(feature_matrix)

            ml_direction = ml_prediction["direction"]
            ml_confidence = ml_prediction["confidence"]

            # Convert ML output to -100..+100 score
            if ml_direction == "NEUTRAL":
                ml_score = 0.0
            elif ml_direction == "LONG":
                ml_score = ml_confidence * 100
            else:  # SHORT
                ml_score = -ml_confidence * 100

            ml_available = True
        except Exception as e:
            logger.error(f"ML scoring failed for {pair}:{timeframe}: {e}", exc_info=True)

    # ── Step 3: Blend indicator + ML scores ──
    blended = blend_with_ml(
        indicator_preliminary,
        ml_score,
        ml_confidence,
        ml_weight=settings.engine_ml_weight,
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
    llm_response = None
    if abs(blended) >= settings.engine_llm_threshold and prompt_template:
        direction_label = "LONG" if blended > 0 else "SHORT"

        # Build ML context string for LLM prompt
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
                preliminary_score=str(indicator_preliminary),
                direction=direction_label,
                blended_score=str(blended),
                agreement=agreement,
                candles=json.dumps(candles_data[-20:], indent=2),
            )
            llm_response = await call_openrouter(
                prompt=rendered,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                timeout=settings.engine_llm_timeout_seconds,
            )
        except Exception as e:
            logger.error(f"LLM call failed for {pair}:{timeframe}: {e}")

    # ── Step 6: Compute final score ──
    final = compute_final_score(blended, llm_response)
    direction = "LONG" if final > 0 else "SHORT"

    # ── Step 7: Hard veto on LLM contradict ──
    llm_opinion = llm_response.opinion if llm_response else None
    if llm_opinion == "contradict":
        _log_pipeline_evaluation(
            pair=pair, timeframe=timeframe,
            tech_score=tech_result["score"], flow_score=flow_result["score"],
            onchain_score=onchain_score if onchain_available else None,
            pattern_score=pat_score,
            ml_score=ml_score, ml_confidence=ml_confidence,
            indicator_preliminary=indicator_preliminary,
            blended_score=blended, final_score=final,
            llm_opinion=llm_opinion, ml_available=ml_available,
            agreement=agreement, emitted=False,
        )
        logger.info(f"Pipeline {pair}:{timeframe} — LLM contradict hard veto (final={final})")
        return

    # ── Step 8: Threshold check + emit ──
    emitted = abs(final) >= settings.engine_signal_threshold

    _log_pipeline_evaluation(
        pair=pair, timeframe=timeframe,
        tech_score=tech_result["score"], flow_score=flow_result["score"],
        onchain_score=onchain_score if onchain_available else None,
        pattern_score=pat_score,
        ml_score=ml_score, ml_confidence=ml_confidence,
        indicator_preliminary=indicator_preliminary,
        blended_score=blended, final_score=final,
        llm_opinion=llm_opinion, ml_available=ml_available,
        agreement=agreement, emitted=emitted,
    )

    if not emitted:
        return

    # ── Step 9: Calculate levels ──
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
        signal_threshold=settings.engine_signal_threshold,
    )

    llm_levels = None
    if llm_response and llm_response.opinion != "contradict" and llm_response.levels:
        llm_levels = llm_response.levels.model_dump()

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
        llm_opinion=llm_opinion,
        sl_bounds=(settings.ml_sl_min_atr, settings.ml_sl_max_atr),
        tp1_min_atr=settings.ml_tp1_min_atr,
        tp2_max_atr=settings.ml_tp2_max_atr,
        rr_floor=settings.ml_rr_floor,
        caution_sl_factor=settings.llm_caution_sl_factor,
        sl_atr_default=scaled["sl_atr"],
        tp1_atr_default=scaled["tp1_atr"],
        tp2_atr_default=scaled["tp2_atr"],
    )

    signal_data = {
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "final_score": final,
        "traditional_score": tech_result["score"],
        "llm_opinion": llm_response.opinion if llm_response else "skipped",
        "llm_confidence": llm_response.confidence if llm_response else None,
        "explanation": llm_response.explanation if llm_response else None,
        **levels,
        "raw_indicators": {
            **tech_result["indicators"],
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
        },
        "detected_patterns": detected_patterns or None,
    }

    await _emit_signal(app, signal_data, levels, correlated_news_ids)


def _log_pipeline_evaluation(
    *, pair, timeframe, tech_score, flow_score, onchain_score,
    pattern_score, ml_score, ml_confidence, indicator_preliminary,
    blended_score, final_score, llm_opinion, ml_available, agreement, emitted,
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
        "llm_opinion": llm_opinion,
        "ml_available": ml_available,
        "agreement": agreement,
        "emitted": emitted,
    }
    logger.info(f"Pipeline evaluation: {json.dumps(log_data)}")


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


async def handle_long_short_data(app: FastAPI, data: dict):
    flow = app.state.order_flow.setdefault(data["pair"], {})
    flow["long_short_ratio"] = data["long_short_ratio"]


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

        # Phase 2: check optimization triggers after batch resolution
        tracker = getattr(app.state, "tracker", None)
        if resolved_pairs_timeframes and tracker is not None:
            async with db.session_factory() as trigger_session:
                await tracker.check_optimization_triggers(
                    trigger_session, resolved_pairs_timeframes
                )


OKX_BAR_MAP = {"15m": "15m", "1h": "1H", "4h": "4H"}


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
    app.state.order_flow = {}
    app.state.pipeline_tasks = set()
    app.state.pipeline_settings_lock = asyncio.Lock()

    from app.engine.performance_tracker import PerformanceTracker
    app.state.tracker = PerformanceTracker(db.session_factory)

    try:
        await app.state.tracker.bootstrap_from_backtests()
    except Exception as e:
        logger.warning("Tracker bootstrap failed: %s", e)

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
            else:
                logger.warning("No PipelineSettings row found; using config defaults")
    except Exception as e:
        logger.warning("Failed to load PipelineSettings from DB: %s", e)

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
    news_collector.stop()
    news_task.cancel()
    ticker_collector.stop()
    ticker_task.cancel()
    account_poller.stop()
    account_task.cancel()
    alert_cleanup_task.cancel()
    if onchain_task:
        onchain_collector.stop()
        onchain_task.cancel()
    await redis.close()
    await db.close()


def create_app(lifespan_override=None) -> FastAPI:
    app = FastAPI(title="Krypton", version="0.1.0", lifespan=lifespan_override or lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

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

    return app


app = create_app()
