import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.api.auth import require_settings_api_key

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
async def get_balance(request: Request, _key: str = require_settings_api_key()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    result = await okx.get_balance()
    if result is None:
        raise HTTPException(502, "Failed to fetch balance from OKX")
    return result


@router.get("/positions")
async def get_positions(request: Request, _key: str = require_settings_api_key()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    return await okx.get_positions()


@router.get("/portfolio")
async def get_portfolio(request: Request, _key: str = require_settings_api_key()):
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
async def place_order(request: Request, order: OrderRequest, _key: str = require_settings_api_key()):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")
    result = await okx.place_order(
        pair=order.pair,
        side=order.side,
        size=order.size,
        order_type=order.order_type,
        sl_price=order.sl_price,
        tp_price=order.tp_price,
        client_order_id=uuid.uuid4().hex[:16],
    )
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result
