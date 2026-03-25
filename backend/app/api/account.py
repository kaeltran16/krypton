import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from app.api.auth import require_auth
from app.db.models import Signal

router = APIRouter(prefix="/api/account")


class OrderRequest(BaseModel):
    pair: str
    side: str
    size: str
    order_type: str = "market"
    sl_price: str | None = None
    tp_price: str | None = None

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return v

    @field_validator("size")
    @classmethod
    def validate_size(cls, v: str) -> str:
        try:
            val = float(v)
        except ValueError:
            raise ValueError("size must be a valid number")
        if val <= 0:
            raise ValueError("size must be positive")
        return v


@router.get("/balance")
async def get_balance(request: Request, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    result = await okx.get_balance()
    if result is None:
        raise HTTPException(502, "Failed to fetch balance from OKX")
    return result


@router.get("/positions")
async def get_positions(request: Request, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    return await okx.get_positions()


@router.get("/portfolio")
async def get_portfolio(request: Request, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    try:
        balance, positions = await asyncio.gather(
            okx.get_balance(), okx.get_positions()
        )
        if balance is None:
            raise HTTPException(502, "Failed to fetch balance from OKX")

        equity = balance["total_equity"]
        # Compute available balance from USDT currency
        available = 0.0
        for c in balance.get("currencies", []):
            if c["currency"] == "USDT":
                available = c["available"]
                break

        used_margin = sum(p.get("margin", 0) for p in positions)
        total_exposure = sum(
            abs(p.get("size", 0) * p.get("mark_price", 0)) for p in positions
        )
        margin_utilization = (used_margin / equity * 100) if equity > 0 else 0

        return {
            "total_equity": equity,
            "unrealized_pnl": balance["unrealized_pnl"],
            "available_balance": round(available, 2),
            "used_margin": round(used_margin, 2),
            "total_exposure": round(total_exposure, 2),
            "margin_utilization": round(margin_utilization, 1),
            "positions": positions,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Portfolio fetch failed: {str(e)}")


@router.post("/order")
async def place_order(request: Request, order: OrderRequest, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    result = await okx.place_order(
        pair=order.pair,
        side=order.side,
        size=order.size,
        order_type=order.order_type,
        client_order_id=uuid.uuid4().hex[:16],
    )
    if not result["success"]:
        msg = result["error"]
        if "instrument" in msg.lower() and okx.demo:
            msg = f"{order.pair} not available in OKX demo mode. Disable demo mode (OKX_DEMO=false) or use a supported instrument."
        raise HTTPException(400, msg)

    if order.tp_price or order.sl_price:
        # Validate TP/SL against last price before placing algo order
        tp = float(order.tp_price) if order.tp_price else None
        sl = float(order.sl_price) if order.sl_price else None
        last_price = await okx.get_last_price(order.pair)
        is_long = order.side == "buy"

        invalid_reasons = []
        if last_price:
            if sl is not None:
                if is_long and sl >= last_price:
                    invalid_reasons.append(f"SL ({sl}) must be below last price ({last_price}) for a long")
                elif not is_long and sl <= last_price:
                    invalid_reasons.append(f"SL ({sl}) must be above last price ({last_price}) for a short")
            if tp is not None:
                if is_long and tp <= last_price:
                    invalid_reasons.append(f"TP ({tp}) must be above last price ({last_price}) for a long")
                elif not is_long and tp >= last_price:
                    invalid_reasons.append(f"TP ({tp}) must be below last price ({last_price}) for a short")

        if invalid_reasons:
            result["warning"] = "Entry filled but TP/SL skipped: " + "; ".join(invalid_reasons)
        else:
            algo_result = await okx.place_algo_order(
                pair=order.pair,
                side=order.side,
                size=order.size,
                tp_trigger_price=order.tp_price,
                sl_trigger_price=order.sl_price,
            )
            if algo_result["success"]:
                result["algo_id"] = algo_result["algo_id"]
            else:
                result["warning"] = f"Entry filled but TP/SL failed: {algo_result['error']}"

    return result


class ClosePositionRequest(BaseModel):
    pair: str
    pos_side: str

    @field_validator("pos_side")
    @classmethod
    def validate_pos_side(cls, v: str) -> str:
        if v not in ("long", "short"):
            raise ValueError("pos_side must be 'long' or 'short'")
        return v


@router.post("/close-position")
async def close_position(request: Request, body: ClosePositionRequest, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    result = await okx.close_position(pair=body.pair, pos_side=body.pos_side)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


# --- Algo orders ---


@router.get("/algo-orders")
async def get_algo_orders(request: Request, pair: str, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    return await okx.get_algo_orders_pending(pair)


class AmendAlgoRequest(BaseModel):
    pair: str
    side: str
    size: str
    sl_price: str | None = None
    tp_price: str | None = None

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return v


@router.post("/amend-algo")
async def amend_algo(request: Request, body: AmendAlgoRequest, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")

    # 1. Fetch current pending algos
    pending = await okx.get_algo_orders_pending(body.pair)
    if not pending:
        raise HTTPException(404, "No pending algo orders found for this pair")

    # 2. Cancel existing algo
    algo_id = pending[0]["algo_id"]
    cancel_result = await okx.cancel_algo_order(body.pair, algo_id)
    if not cancel_result["success"]:
        raise HTTPException(400, f"Failed to cancel existing algo: {cancel_result['error']}")

    # 3. Place new algo
    algo_result = await okx.place_algo_order(
        pair=body.pair,
        side=body.side,
        size=body.size,
        tp_trigger_price=body.tp_price,
        sl_trigger_price=body.sl_price,
    )
    if not algo_result["success"]:
        return {
            "success": False,
            "error": f"Old SL/TP removed but new placement failed: {algo_result['error']}",
            "sl_tp_removed": True,
        }
    return {"success": True, "algo_id": algo_result["algo_id"]}


# --- Partial close ---


class PartialCloseRequest(BaseModel):
    pair: str
    pos_side: str
    size: str

    @field_validator("pos_side")
    @classmethod
    def validate_pos_side(cls, v: str) -> str:
        if v not in ("long", "short"):
            raise ValueError("pos_side must be 'long' or 'short'")
        return v

    @field_validator("size")
    @classmethod
    def validate_size(cls, v: str) -> str:
        try:
            val = float(v)
        except ValueError:
            raise ValueError("size must be a valid number")
        if val <= 0:
            raise ValueError("size must be positive")
        return v


@router.post("/partial-close")
async def partial_close(request: Request, body: PartialCloseRequest, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    # Closing side is opposite of position side
    closing_side = "sell" if body.pos_side == "long" else "buy"
    result = await okx.place_order(
        pair=body.pair,
        side=closing_side,
        size=body.size,
        pos_side=body.pos_side,
        client_order_id=uuid.uuid4().hex[:16],
    )
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


# --- Funding costs ---


@router.get("/funding-costs")
async def get_funding_costs(request: Request, pair: str, _key: str = require_auth()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    bills = await okx.get_funding_costs(pair)
    total = sum(b["pnl"] for b in bills)
    return {"pair": pair, "total_funding": round(total, 6), "bills": bills}


# --- Trade history (resolved signals) ---


@router.get("/trade-history")
async def get_trade_history(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    pair: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _key: str = require_auth(),
):
    db = request.app.state.db
    if not db:
        raise HTTPException(503, "Database not available")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with db.session_factory() as session:
        query = (
            select(Signal)
            .where(Signal.outcome != "PENDING")
            .where(Signal.outcome_at.isnot(None))
            .where(Signal.outcome_at >= cutoff)
        )
        if pair:
            query = query.where(Signal.pair == pair)
        query = query.order_by(Signal.outcome_at.desc()).offset(offset).limit(limit)
        result = await session.execute(query)
        signals = result.scalars().all()
        return [
            {
                "signal_id": s.id,
                "pair": s.pair,
                "direction": s.direction.lower(),
                "entry_price": float(s.entry),
                "sl_price": float(s.stop_loss),
                "tp1_price": float(s.take_profit_1),
                "tp2_price": float(s.take_profit_2),
                "pnl_pct": float(s.outcome_pnl_pct) if s.outcome_pnl_pct is not None else 0,
                "duration_minutes": s.outcome_duration_minutes or 0,
                "outcome": s.outcome,
                "signal_score": s.final_score,
                "signal_reason": s.explanation,
                "opened_at": s.created_at.isoformat() if s.created_at else None,
                "closed_at": s.outcome_at.isoformat() if s.outcome_at else None,
            }
            for s in signals
        ]
