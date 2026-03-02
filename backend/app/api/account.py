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
