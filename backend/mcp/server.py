import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import redis.asyncio as aioredis
from mcp.server.fastmcp import FastMCP
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Add backend/ to the import path so app.* modules resolve when launched from repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.models import AgentAnalysis, OrderFlowSnapshot, PipelineEvaluation, Signal
from app.exchange.okx_client import OKXClient

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")
KRYPTON_API_URL = os.environ.get("KRYPTON_API_URL", "http://localhost:8000")
OKX_API_KEY = os.environ.get("OKX_API_KEY", "")
OKX_SECRET_KEY = os.environ.get("OKX_SECRET_KEY", "")
OKX_PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "")
OKX_DEMO = os.environ.get("OKX_DEMO", "true").lower() == "true"

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
redis_client = aioredis.from_url(REDIS_URL)

mcp = FastMCP(
    "krypton",
    instructions=(
        "Krypton trading engine MCP server. Provides tools to read market "
        "regime, signals, order flow, candles, indicators, positions, and "
        "to post analysis results."
    ),
)


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=_json_default)


def _decode_redis_value(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _serialize_signal(row: Signal) -> dict[str, Any]:
    return {
        "id": row.id,
        "pair": row.pair,
        "timeframe": row.timeframe,
        "direction": row.direction,
        "final_score": row.final_score,
        "traditional_score": row.traditional_score,
        "outcome": row.outcome,
        "entry": row.entry,
        "stop_loss": row.stop_loss,
        "take_profit_1": row.take_profit_1,
        "take_profit_2": row.take_profit_2,
        "explanation": row.explanation,
        "raw_indicators": row.raw_indicators,
        "created_at": row.created_at,
    }


def _serialize_analysis(row: AgentAnalysis) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "pair": row.pair,
        "narrative": row.narrative,
        "annotations": row.annotations,
        "metadata": row.metadata_,
        "created_at": row.created_at,
    }


@mcp.tool()
async def get_regime(pair: str | None = None) -> str:
    """Get current market regime for one or all pairs."""
    async with SessionLocal() as session:
        if pair:
            stmt = (
                select(PipelineEvaluation)
                .where(PipelineEvaluation.pair == pair)
                .order_by(PipelineEvaluation.evaluated_at.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if not row:
                return _dump_json({"error": f"No evaluation found for {pair}"})
            return _dump_json(
                {
                    "pair": row.pair,
                    "timeframe": row.timeframe,
                    "regime": row.regime,
                    "indicators": {
                        key: row.indicators.get(key)
                        for key in ("adx", "bb_width", "bb_width_pct", "rsi", "atr")
                        if key in row.indicators
                    },
                    "evaluated_at": row.evaluated_at,
                }
            )

        subquery = (
            select(
                PipelineEvaluation.pair,
                func.max(PipelineEvaluation.evaluated_at).label("evaluated_at"),
            )
            .group_by(PipelineEvaluation.pair)
            .subquery()
        )
        stmt = (
            select(PipelineEvaluation)
            .join(
                subquery,
                (PipelineEvaluation.pair == subquery.c.pair)
                & (PipelineEvaluation.evaluated_at == subquery.c.evaluated_at),
            )
            .order_by(PipelineEvaluation.pair)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return _dump_json({"error": "No pipeline evaluations found"})
        return _dump_json(
            [
                {
                    "pair": row.pair,
                    "timeframe": row.timeframe,
                    "regime": row.regime,
                    "indicators": {
                        key: row.indicators.get(key)
                        for key in ("adx", "bb_width", "bb_width_pct", "rsi", "atr")
                        if key in row.indicators
                    },
                    "evaluated_at": row.evaluated_at,
                }
                for row in rows
            ]
        )


@mcp.tool()
async def get_candles(pair: str, timeframe: str = "1h", limit: int = 100) -> str:
    """Get recent OHLCV candles from Redis cache."""
    cache_key = f"candles:{pair}:{timeframe}"
    raw = await redis_client.lrange(cache_key, -min(limit, 200), -1)
    if not raw:
        return _dump_json({"error": f"No candles cached for {cache_key}"})
    candles = [json.loads(_decode_redis_value(item)) for item in raw]
    return _dump_json(candles)


@mcp.tool()
async def get_signals(
    pair: str | None = None,
    outcome: str | None = None,
    limit: int = 10,
) -> str:
    """Get recent trading signals from the engine."""
    async with SessionLocal() as session:
        stmt = select(Signal).order_by(Signal.created_at.desc())
        if pair:
            stmt = stmt.where(Signal.pair == pair)
        if outcome:
            stmt = stmt.where(Signal.outcome == outcome)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
    return _dump_json([_serialize_signal(row) for row in rows])


@mcp.tool()
async def get_signal_scores(pair: str) -> str:
    """Get the latest pipeline score breakdown for a pair."""
    async with SessionLocal() as session:
        stmt = (
            select(PipelineEvaluation)
            .where(PipelineEvaluation.pair == pair)
            .order_by(PipelineEvaluation.evaluated_at.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return _dump_json({"error": f"No evaluation found for {pair}"})
    return _dump_json(
        {
            "pair": row.pair,
            "timeframe": row.timeframe,
            "tech_score": row.tech_score,
            "flow_score": row.flow_score,
            "onchain_score": row.onchain_score,
            "pattern_score": row.pattern_score,
            "liquidation_score": row.liquidation_score,
            "confluence_score": row.confluence_score,
            "news_score": row.news_score,
            "ml_score": row.ml_score,
            "ml_confidence": row.ml_confidence,
            "blended_score": row.blended_score,
            "final_score": row.final_score,
            "emitted": row.emitted,
            "evaluated_at": row.evaluated_at,
        }
    )


@mcp.tool()
async def get_order_flow(pair: str) -> str:
    """Get latest order flow data for a pair."""
    async with SessionLocal() as session:
        stmt = (
            select(OrderFlowSnapshot)
            .where(OrderFlowSnapshot.pair == pair)
            .order_by(OrderFlowSnapshot.timestamp.desc())
            .limit(5)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return _dump_json({"error": f"No order flow data for {pair}"})

    latest = rows[0]
    trend = None
    if len(rows) >= 2:
        oldest = rows[-1]
        trend = {
            "funding_direction": (
                "rising"
                if (latest.funding_rate or 0) > (oldest.funding_rate or 0)
                else "falling"
            ),
            "oi_direction": (
                "rising"
                if (latest.open_interest or 0) > (oldest.open_interest or 0)
                else "falling"
            ),
            "snapshots_compared": len(rows),
        }

    return _dump_json(
        {
            "pair": pair,
            "funding_rate": latest.funding_rate,
            "open_interest": latest.open_interest,
            "oi_change_pct": latest.oi_change_pct,
            "long_short_ratio": latest.long_short_ratio,
            "cvd_delta": latest.cvd_delta,
            "timestamp": latest.timestamp,
            "trend": trend,
        }
    )


@mcp.tool()
async def get_indicators(pair: str, timeframe: str = "1h") -> str:
    """Get computed indicator values from the latest pipeline evaluation."""
    async with SessionLocal() as session:
        stmt = (
            select(PipelineEvaluation)
            .where(PipelineEvaluation.pair == pair)
            .where(PipelineEvaluation.timeframe == timeframe)
            .order_by(PipelineEvaluation.evaluated_at.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return _dump_json({"error": f"No evaluation for {pair} {timeframe}"})

    return _dump_json(
        {
            "pair": pair,
            "timeframe": timeframe,
            "indicators": row.indicators,
            "regime": row.regime,
            "evaluated_at": row.evaluated_at,
        }
    )


@mcp.tool()
async def get_performance(pair: str | None = None) -> str:
    """Get recent signal performance stats."""
    resolved_outcomes = [
        "TP1_HIT",
        "TP2_HIT",
        "SL_HIT",
        "TP1_TRAIL",
        "TP1_TP2",
        "EXPIRED",
    ]
    async with SessionLocal() as session:
        stmt = (
            select(Signal)
            .where(Signal.outcome.in_(resolved_outcomes))
            .order_by(Signal.created_at.desc())
            .limit(50)
        )
        if pair:
            stmt = stmt.where(Signal.pair == pair)
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return _dump_json({"message": "No resolved signals found"})

    total = len(rows)
    wins = sum(
        1
        for row in rows
        if row.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2")
    )
    losses = sum(1 for row in rows if row.outcome == "SL_HIT")
    expired = sum(1 for row in rows if row.outcome == "EXPIRED")
    pnl_values = [
        float(row.outcome_pnl_pct)
        for row in rows
        if row.outcome_pnl_pct is not None
    ]

    return _dump_json(
        {
            "pair": pair or "all",
            "total_signals": total,
            "wins": wins,
            "losses": losses,
            "expired": expired,
            "win_rate": round(wins / max(total - expired, 1) * 100, 1),
            "avg_pnl_pct": round(sum(pnl_values) / len(pnl_values), 2)
            if pnl_values
            else None,
        }
    )


@mcp.tool()
async def get_positions() -> str:
    """Get current open positions from OKX."""
    if not OKX_API_KEY or not OKX_SECRET_KEY or not OKX_PASSPHRASE:
        return _dump_json(
            {"error": "OKX credentials not configured", "positions": []}
        )

    try:
        client = OKXClient(
            api_key=OKX_API_KEY,
            api_secret=OKX_SECRET_KEY,
            passphrase=OKX_PASSPHRASE,
            demo=OKX_DEMO,
        )
        positions = await client.get_positions()
        return _dump_json({"positions": positions})
    except Exception as exc:
        return _dump_json({"error": f"OKX API error: {exc}", "positions": []})


@mcp.tool()
async def get_last_analysis(
    type: str | None = None,
    pair: str | None = None,
) -> str:
    """Get the most recent agent analysis for comparison."""
    async with SessionLocal() as session:
        stmt = select(AgentAnalysis).order_by(AgentAnalysis.created_at.desc())
        if type:
            stmt = stmt.where(AgentAnalysis.type == type)
        if pair:
            stmt = stmt.where(AgentAnalysis.pair == pair)
        stmt = stmt.limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()

    if not row:
        return _dump_json({"message": "No previous analysis found"})
    return _dump_json(_serialize_analysis(row))


@mcp.tool()
async def post_analysis(
    type: str,
    narrative: str,
    annotations: list[dict] | None = None,
    metadata: dict | None = None,
    pair: str | None = None,
) -> str:
    """Post an analysis to the Krypton backend for display in the Agent tab."""
    body = {
        "type": type,
        "pair": pair,
        "narrative": narrative,
        "annotations": annotations or [],
        "metadata": metadata or {},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{KRYPTON_API_URL}/api/agent/analysis",
                json=body,
                headers={"X-Agent-Key": AGENT_API_KEY},
            )
            if response.status_code != 200:
                return _dump_json(
                    {
                        "error": (
                            f"Backend returned {response.status_code}: "
                            f"{response.text}"
                        )
                    }
                )
            return _dump_json({"success": True, "analysis": response.json()})
    except Exception as exc:
        return _dump_json({"error": f"Failed to post analysis: {exc}"})


if __name__ == "__main__":
    mcp.run()
