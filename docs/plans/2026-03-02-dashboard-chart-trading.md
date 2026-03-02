# Dashboard, Chart & OKX Trading - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand Krypton from signal-only to a full trading dashboard with real-time charts, OKX account integration, and semi-auto trade execution.

**Architecture:** Backend-proxied -- OKX private API keys stay server-side. New REST endpoints proxy account data. WebSocket extended to stream candle ticks. Frontend gets 4 tabs: Dashboard, Chart, Signals, Settings.

**Tech Stack:** FastAPI, httpx (OKX REST), lightweight-charts (TradingView), Zustand, Tailwind CSS

---

## Task 0: Pre-requisite cleanup

**Step 1: Restore signal threshold and commit existing changes**

There are uncommitted changes in the working tree that overlap with files this plan modifies. Resolve them first:

In `backend/config.yaml`: change `signal_threshold: 1` back to `signal_threshold: 50`

In `web/src/features/settings/types.ts`: change `threshold: 1` back to `threshold: 50`

**Step 2: Stage and commit all pending changes**

```bash
git add -A
```

```
fix: restore signal threshold to 50
```

This ensures a clean working tree before starting the feature work.

---

## Task 1: Add OKX credentials to Settings

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/backend/.env`
- Modify: `backend/config.yaml` (no changes needed, env-only)

**Step 1: Add OKX fields to Settings class**

In `backend/app/config.py`, add after the `redis_url` field:

```python
# okx private api
okx_api_key: str = ""
okx_api_secret: str = ""
okx_passphrase: str = ""
okx_demo: bool = True
```

**Step 2: Add placeholder values to `.env`**

Append to `backend/.env`:

```
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
OKX_DEMO=true
```

**Step 3: Verify settings load**

Run: `cd backend && docker compose exec api python -c "from app.config import Settings; s = Settings(); print(s.okx_demo)"`
Expected: `True`

**Step 4: Commit**

```
feat(backend): add OKX private API credentials to settings
```

---

## Task 2: OKX Private Client - signing and balance

**Files:**
- Create: `backend/app/exchange/__init__.py`
- Create: `backend/app/exchange/okx_client.py`
- Create: `backend/tests/exchange/__init__.py`
- Create: `backend/tests/exchange/test_okx_client.py`

**Step 1: Write tests for signing and balance parsing**

```python
# backend/tests/exchange/test_okx_client.py
import pytest
from unittest.mock import AsyncMock, patch
from app.exchange.okx_client import OKXClient, _sign_request, parse_balance_response


def test_sign_request():
    """HMAC-SHA256 signing produces correct base64 output."""
    timestamp = "2024-01-01T00:00:00.000Z"
    method = "GET"
    path = "/api/v5/account/balance"
    body = ""
    secret = "test-secret"
    signature = _sign_request(timestamp, method, path, body, secret)
    assert isinstance(signature, str)
    assert len(signature) > 0


def test_parse_balance_response():
    raw = {
        "code": "0",
        "data": [{
            "totalEq": "10000.50",
            "upl": "150.25",
            "details": [{
                "ccy": "USDT",
                "availBal": "5000.00",
                "frozenBal": "2000.00",
                "eq": "7000.00",
            }],
        }],
    }
    result = parse_balance_response(raw)
    assert result["total_equity"] == 10000.50
    assert result["unrealized_pnl"] == 150.25
    assert len(result["currencies"]) == 1
    assert result["currencies"][0]["currency"] == "USDT"
    assert result["currencies"][0]["available"] == 5000.00


def test_parse_balance_response_error():
    raw = {"code": "50000", "msg": "error"}
    result = parse_balance_response(raw)
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/exchange/test_okx_client.py -v`
Expected: FAIL (module not found)

**Step 3: Implement signing and balance**

```python
# backend/app/exchange/__init__.py
(empty)

# backend/app/exchange/okx_client.py
import base64
import hashlib
import hmac
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

OKX_REST_BASE = "https://www.okx.com"


def _sign_request(timestamp: str, method: str, path: str, body: str, secret: str) -> str:
    message = timestamp + method.upper() + path + body
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def _timestamp_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + now.strftime("%f")[:3] + "Z"


def parse_balance_response(raw: dict) -> dict | None:
    if raw.get("code") != "0" or not raw.get("data"):
        return None
    data = raw["data"][0]
    return {
        "total_equity": float(data.get("totalEq", 0)),
        "unrealized_pnl": float(data.get("upl", 0)),
        "currencies": [
            {
                "currency": d["ccy"],
                "available": float(d.get("availBal", 0)),
                "frozen": float(d.get("frozenBal", 0)),
                "equity": float(d.get("eq", 0)),
            }
            for d in data.get("details", [])
        ],
    }


def parse_positions_response(raw: dict) -> list[dict]:
    if raw.get("code") != "0" or not raw.get("data"):
        return []
    positions = []
    for p in raw["data"]:
        if float(p.get("pos", 0)) == 0:
            continue
        positions.append({
            "pair": p["instId"],
            "side": "long" if p.get("posSide") == "long" else "short",
            "size": float(p["pos"]),
            "avg_price": float(p.get("avgPx", 0)),
            "mark_price": float(p.get("markPx", 0)),
            "unrealized_pnl": float(p.get("upl", 0)),
            "liquidation_price": float(p.get("liqPx", 0)) if p.get("liqPx") else None,
            "margin": float(p.get("margin", 0)),
            "leverage": p.get("lever", "0"),
        })
    return positions


def parse_order_response(raw: dict) -> dict:
    if raw.get("code") != "0":
        msg = raw.get("msg", "Unknown error")
        if raw.get("data") and raw["data"][0].get("sMsg"):
            msg = raw["data"][0]["sMsg"]
        return {"success": False, "error": msg}
    order = raw["data"][0]
    return {
        "success": True,
        "order_id": order.get("ordId"),
        "client_order_id": order.get("clOrdId"),
    }


class OKXClient:
    def __init__(self, api_key: str, api_secret: str, passphrase: str, demo: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.demo = demo
        self.base_url = OKX_REST_BASE

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        timestamp = _timestamp_iso()
        sign = _sign_request(timestamp, method, path, body, self.api_secret)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            headers["x-simulated-trading"] = "1"
        return headers

    async def get_balance(self) -> dict | None:
        path = "/api/v5/account/balance"
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.get(path, headers=self._headers("GET", path))
            resp.raise_for_status()
            return parse_balance_response(resp.json())

    async def get_positions(self) -> list[dict]:
        path = "/api/v5/account/positions"
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.get(path, headers=self._headers("GET", path))
            resp.raise_for_status()
            return parse_positions_response(resp.json())

    async def place_order(
        self,
        pair: str,
        side: str,
        size: str,
        order_type: str = "market",
        sl_price: str | None = None,
        tp_price: str | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        import json
        path = "/api/v5/trade/order"
        body_dict = {
            "instId": pair,
            "tdMode": "cross",
            "side": side,
            "ordType": order_type,
            "sz": size,
        }
        if client_order_id:
            body_dict["clOrdId"] = client_order_id
        if sl_price:
            body_dict["slTriggerPx"] = sl_price
            body_dict["slOrdPx"] = "-1"
        if tp_price:
            body_dict["tpTriggerPx"] = tp_price
            body_dict["tpOrdPx"] = "-1"
        body = json.dumps(body_dict)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.post(
                path,
                content=body,
                headers=self._headers("POST", path, body),
            )
            resp.raise_for_status()
            return parse_order_response(resp.json())
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/exchange/test_okx_client.py -v`
Expected: 3 passed

**Step 5: Commit**

```
feat(backend): add OKX private API client with signing
```

---

## Task 3: OKX Client - positions and order parsing tests

**Files:**
- Modify: `backend/tests/exchange/test_okx_client.py`

**Step 1: Add tests for positions and order parsing**

Append to `test_okx_client.py`:

```python
def test_parse_positions_response():
    raw = {
        "code": "0",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "posSide": "long",
                "pos": "1",
                "avgPx": "65000",
                "markPx": "66000",
                "upl": "1000",
                "liqPx": "60000",
                "margin": "6500",
                "lever": "10",
            },
            {
                "instId": "ETH-USDT-SWAP",
                "posSide": "short",
                "pos": "0",
                "avgPx": "0",
                "markPx": "0",
                "upl": "0",
                "liqPx": "",
                "margin": "0",
                "lever": "0",
            },
        ],
    }
    result = parse_positions_response(raw)
    assert len(result) == 1
    assert result[0]["pair"] == "BTC-USDT-SWAP"
    assert result[0]["side"] == "long"
    assert result[0]["unrealized_pnl"] == 1000.0


def test_parse_positions_response_empty():
    raw = {"code": "0", "data": []}
    assert parse_positions_response(raw) == []


def test_parse_order_response_success():
    raw = {
        "code": "0",
        "data": [{"ordId": "12345", "clOrdId": "abc"}],
    }
    result = parse_order_response(raw)
    assert result["success"] is True
    assert result["order_id"] == "12345"


def test_parse_order_response_error():
    raw = {
        "code": "51000",
        "msg": "Parameter error",
        "data": [{"sCode": "51000", "sMsg": "Invalid size"}],
    }
    result = parse_order_response(raw)
    assert result["success"] is False
    assert "Invalid size" in result["error"]
```

**Step 2: Run tests**

Run: `cd backend && python -m pytest tests/exchange/test_okx_client.py -v`
Expected: 7 passed

**Step 3: Commit**

```
test(backend): add position and order parsing tests
```

---

## Task 4: Candles REST endpoint

**Files:**
- Create: `backend/app/api/candles.py`
- Create: `backend/tests/api/test_candles.py`
- Modify: `backend/app/main.py` (register router)

**Step 1: Write test**

```python
# backend/tests/api/test_candles.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.lrange = AsyncMock(return_value=[
        json.dumps({"timestamp": 1700000000000, "open": 65000, "high": 65500, "low": 64800, "close": 65200, "volume": 100}),
        json.dumps({"timestamp": 1700000900000, "open": 65200, "high": 65300, "low": 65100, "close": 65250, "volume": 80}),
    ])
    return r


def test_parse_candles_from_redis(mock_redis):
    from app.api.candles import parse_redis_candles
    raw = [
        json.dumps({"timestamp": 1700000000000, "open": 65000, "high": 65500, "low": 64800, "close": 65200, "volume": 100}),
    ]
    result = parse_redis_candles(raw)
    assert len(result) == 1
    assert result[0]["open"] == 65000
    assert result[0]["close"] == 65200
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_candles.py -v`
Expected: FAIL

**Step 3: Implement candles endpoint**

```python
# backend/app/api/candles.py
import json

from fastapi import APIRouter, Query, Request

from app.api.auth import require_settings_api_key

router = APIRouter(prefix="/api")


def parse_redis_candles(raw_list: list[str]) -> list[dict]:
    return [json.loads(c) for c in raw_list]


@router.get("/candles")
async def get_candles(
    request: Request,
    _key: str = require_settings_api_key(),
    pair: str = Query(...),
    timeframe: str = Query(...),
    limit: int = Query(200, ge=1, le=500),
):
    redis = request.app.state.redis
    cache_key = f"candles:{pair}:{timeframe}"
    raw = await redis.lrange(cache_key, -limit, -1)
    return parse_redis_candles(raw)
```

**Step 4: Register router in main.py**

In `backend/app/main.py`, in `create_app()`, add after the push router:

```python
from app.api.candles import router as candles_router
app.include_router(candles_router)
```

**Step 5: Run test**

Run: `cd backend && python -m pytest tests/api/test_candles.py -v`
Expected: PASS

**Step 6: Commit**

```
feat(backend): add candles REST endpoint
```

---

## Task 5: Account API endpoints

**Files:**
- Create: `backend/app/api/account.py`
- Modify: `backend/app/main.py` (register router + init OKXClient in lifespan)

**Step 1: Implement account endpoints**

```python
# backend/app/api/account.py
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.api.auth import require_settings_api_key

router = APIRouter(prefix="/api/account")


class OrderRequest(BaseModel):
    pair: str
    side: str  # "buy" or "sell"
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
```

**Step 2: Init OKXClient in lifespan and register router**

In `backend/app/main.py`:

Add import at top:
```python
from app.exchange.okx_client import OKXClient
```

In `lifespan()`, after `app.state.prompt_template = ...`, add:
```python
if settings.okx_api_key:
    app.state.okx_client = OKXClient(
        api_key=settings.okx_api_key,
        api_secret=settings.okx_api_secret,
        passphrase=settings.okx_passphrase,
        demo=settings.okx_demo,
    )
else:
    app.state.okx_client = None
```

In `create_app()`, add after candles router:
```python
from app.api.account import router as account_router
app.include_router(account_router)
```

**Step 3: Commit**

```
feat(backend): add account balance, positions, and order endpoints
```

---

## Task 5b: Tests for account endpoints

**Files:**
- Create: `backend/tests/api/test_account.py`

**Step 1: Write tests**

```python
# backend/tests/api/test_account.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def mock_okx_client():
    client = AsyncMock()
    client.get_balance = AsyncMock(return_value={
        "total_equity": 10000.50,
        "unrealized_pnl": 150.25,
        "currencies": [{"currency": "USDT", "available": 5000.0, "frozen": 2000.0, "equity": 7000.0}],
    })
    client.get_positions = AsyncMock(return_value=[
        {"pair": "BTC-USDT-SWAP", "side": "long", "size": 1.0, "avg_price": 65000.0,
         "mark_price": 66000.0, "unrealized_pnl": 1000.0, "liquidation_price": 60000.0,
         "margin": 6500.0, "leverage": "10"},
    ])
    client.place_order = AsyncMock(return_value={
        "success": True, "order_id": "12345", "client_order_id": "abc",
    })
    return client


@pytest.fixture
def app_with_okx(mock_okx_client):
    from app.main import create_app
    app = create_app()
    app.state.okx_client = mock_okx_client
    app.state.settings = MagicMock()
    app.state.settings.krypton_api_key = "test-key"
    return app


@pytest.fixture
def app_without_okx():
    from app.main import create_app
    app = create_app()
    app.state.okx_client = None
    app.state.settings = MagicMock()
    app.state.settings.krypton_api_key = "test-key"
    return app


def test_get_balance(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.get("/api/account/balance", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.json()["total_equity"] == 10000.50


def test_get_balance_no_okx(app_without_okx):
    client = TestClient(app_without_okx)
    resp = client.get("/api/account/balance", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 503


def test_get_positions(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.get("/api/account/positions", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["pair"] == "BTC-USDT-SWAP"


def test_place_order_success(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "1",
    }, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_place_order_invalid_side(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "invalid", "size": "1",
    }, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 422


def test_place_order_invalid_size(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "abc",
    }, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 422


def test_place_order_negative_size(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "-1",
    }, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 422


def test_place_order_no_okx(app_without_okx):
    client = TestClient(app_without_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "1",
    }, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 503
```

**Step 2: Run tests**

Run: `cd backend && python -m pytest tests/api/test_account.py -v`
Expected: 8 passed

**Step 3: Commit**

```
test(backend): add account endpoint tests
```

---

## Task 6: Stream live candle ticks over WebSocket

**Files:**
- Modify: `backend/app/collector/ws_client.py`
- Modify: `backend/app/api/connections.py`
- Modify: `backend/app/main.py`

**Step 1: Extend ConnectionManager to broadcast candle ticks**

Add to `backend/app/api/connections.py`:

```python
async def broadcast_candle(self, candle: dict):
    dead = []
    for ws, sub in list(self.connections.items()):
        if candle["pair"] in sub["pairs"] and candle["timeframe"] in sub["timeframes"]:
            try:
                await ws.send_json({"type": "candle", "candle": candle})
            except Exception:
                dead.append(ws)
    for ws in dead:
        self.disconnect(ws)
```

**Step 2: Remove confirmed-only filter from ws_client.py**

In `backend/app/collector/ws_client.py`, in `_listen()`, replace the candle handling block (lines 175-180):

**Before:**
```python
                candle = parse_candle_message(msg)
                if candle and self.on_candle:
                    if candle["confirmed"]:
                        await self.on_candle(candle)
                    else:
                        logger.debug("Unconfirmed candle for %s %s, skipping", candle["pair"], candle["timeframe"])
                    continue
```

**After:**
```python
                candle = parse_candle_message(msg)
                if candle and self.on_candle:
                    await self.on_candle(candle)
                    continue
```

The confirmed/unconfirmed filtering moves to `main.py` where `handle_candle_tick` decides what to do with each candle.

In `backend/app/main.py`, add a new handler and update the existing one:

```python
async def handle_candle_tick(app: FastAPI, candle: dict):
    """Handle all candle ticks (confirmed and unconfirmed)."""
    manager = app.state.manager

    # broadcast live tick to frontend
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

    # only persist and run pipeline for confirmed candles
    if candle["confirmed"]:
        await handle_candle(app, candle)
```

Update the `OKXWebSocketClient` instantiation in lifespan to use `handle_candle_tick`:

```python
ws_client = OKXWebSocketClient(
    pairs=settings.pairs,
    timeframes=settings.timeframes,
    on_candle=lambda c: handle_candle_tick(app, c),
    ...
)
```

**Step 3: Commit**

```
feat(backend): stream live candle ticks over WebSocket
```

---

## Task 7: Frontend - expand Layout to 4 tabs

**Files:**
- Modify: `web/src/shared/components/Layout.tsx`
- Modify: `web/src/App.tsx`

**Step 1: Update Layout to support 4 tabs**

```typescript
// web/src/shared/components/Layout.tsx
import { useState, type ReactNode } from "react";

type Tab = "dashboard" | "chart" | "signals" | "settings";

interface LayoutProps {
  dashboard: ReactNode;
  chart: ReactNode;
  signals: ReactNode;
  settings: ReactNode;
}

const TABS: { key: Tab; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "chart", label: "Chart" },
  { key: "signals", label: "Signals" },
  { key: "settings", label: "Settings" },
];

export function Layout({ dashboard, chart, signals, settings }: LayoutProps) {
  const [tab, setTab] = useState<Tab>("dashboard");

  const content = { dashboard, chart, signals, settings }[tab];

  return (
    <div className="min-h-screen bg-surface text-white flex flex-col">
      <main className="flex-1 overflow-y-auto pb-16">{content}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card border-t border-gray-800 flex safe-bottom">
        {TABS.map(({ key, label }) => (
          <TabButton key={key} active={tab === key} onClick={() => setTab(key)} label={label} />
        ))}
      </nav>
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
}

function TabButton({ active, onClick, label }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-3 text-center text-sm font-medium transition-colors ${
        active ? "text-long" : "text-gray-500"
      }`}
    >
      {label}
    </button>
  );
}
```

**Step 2: Update App.tsx with placeholder components**

```typescript
// web/src/App.tsx
import { Layout } from "./shared/components/Layout";
import { SignalFeed } from "./features/signals/components/SignalFeed";
import { SettingsPage } from "./features/settings/components/SettingsPage";

function DashboardPlaceholder() {
  return <div className="p-4"><h1 className="text-xl font-bold">Dashboard</h1><p className="text-gray-500 mt-4">Coming soon...</p></div>;
}

function ChartPlaceholder() {
  return <div className="p-4"><h1 className="text-xl font-bold">Chart</h1><p className="text-gray-500 mt-4">Coming soon...</p></div>;
}

export default function App() {
  return (
    <Layout
      dashboard={<DashboardPlaceholder />}
      chart={<ChartPlaceholder />}
      signals={<SignalFeed />}
      settings={<SettingsPage />}
    />
  );
}
```

**Step 3: Verify the 4-tab layout renders in browser**

**Step 4: Commit**

```
feat(web): expand layout to 4 tabs with placeholders
```

---

## Task 8: Frontend - API client for account and candles

**Files:**
- Modify: `web/src/shared/lib/api.ts`

**Step 1: Add account and candle API methods**

```typescript
// Add these types and methods to web/src/shared/lib/api.ts

export interface AccountBalance {
  total_equity: number;
  unrealized_pnl: number;
  currencies: {
    currency: string;
    available: number;
    frozen: number;
    equity: number;
  }[];
}

export interface Position {
  pair: string;
  side: "long" | "short";
  size: number;
  avg_price: number;
  mark_price: number;
  unrealized_pnl: number;
  liquidation_price: number | null;
  margin: number;
  leverage: string;
}

export interface CandleData {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OrderRequest {
  pair: string;
  side: "buy" | "sell";
  size: string;
  order_type?: string;
  sl_price?: string;
  tp_price?: string;
}

export interface OrderResult {
  success: boolean;
  order_id?: string;
  error?: string;
}

// Add to the api object:
export const api = {
  getSignals: (params?: { ... }) => { ... },  // existing

  getBalance: () => request<AccountBalance>("/api/account/balance"),

  getPositions: () => request<Position[]>("/api/account/positions"),

  getCandles: (pair: string, timeframe: string, limit = 200) => {
    const query = new URLSearchParams({ pair, timeframe, limit: String(limit) });
    return request<CandleData[]>(`/api/candles?${query}`);
  },

  placeOrder: (order: OrderRequest) =>
    request<OrderResult>("/api/account/order", {
      method: "POST",
      body: JSON.stringify(order),
    }),
};
```

**Step 2: Commit**

```
feat(web): add account and candle API client methods
```

---

## Task 9: Frontend - Dashboard feature

**Files:**
- Create: `web/src/features/dashboard/components/Dashboard.tsx`
- Create: `web/src/features/dashboard/components/AccountSummary.tsx`
- Create: `web/src/features/dashboard/components/PositionList.tsx`
- Create: `web/src/features/dashboard/hooks/useAccount.ts`
- Modify: `web/src/App.tsx` (replace placeholder)

**Step 1: Create useAccount hook**

```typescript
// web/src/features/dashboard/hooks/useAccount.ts
import { useEffect, useState, useCallback } from "react";
import { api, type AccountBalance, type Position } from "../../../shared/lib/api";

export function useAccount(pollInterval = 10000) {
  const [balance, setBalance] = useState<AccountBalance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [bal, pos] = await Promise.all([api.getBalance(), api.getPositions()]);
      setBalance(bal);
      setPositions(pos);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch account");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollInterval);
    return () => clearInterval(id);
  }, [refresh, pollInterval]);

  return { balance, positions, loading, error, refresh };
}
```

**Step 2: Create AccountSummary component**

```typescript
// web/src/features/dashboard/components/AccountSummary.tsx
import type { AccountBalance } from "../../../shared/lib/api";
import { formatPrice } from "../../../shared/lib/format";

interface Props {
  balance: AccountBalance | null;
  loading: boolean;
}

export function AccountSummary({ balance, loading }: Props) {
  if (loading) return <div className="p-4 bg-card rounded-lg animate-pulse h-24" />;
  if (!balance) return null;

  const pnlColor = balance.unrealized_pnl >= 0 ? "text-long" : "text-short";

  return (
    <div className="p-4 bg-card rounded-lg space-y-2">
      <h2 className="text-sm text-gray-400">Account</h2>
      <div className="text-2xl font-mono font-bold">${formatPrice(balance.total_equity)}</div>
      <div className="flex gap-4 text-sm">
        <div>
          <span className="text-gray-400">Unrealized P&L </span>
          <span className={`font-mono ${pnlColor}`}>
            {balance.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(balance.unrealized_pnl)}
          </span>
        </div>
        {balance.currencies[0] && (
          <div>
            <span className="text-gray-400">Available </span>
            <span className="font-mono">{formatPrice(balance.currencies[0].available)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 3: Create PositionList component**

```typescript
// web/src/features/dashboard/components/PositionList.tsx
import type { Position } from "../../../shared/lib/api";
import { formatPrice } from "../../../shared/lib/format";

interface Props {
  positions: Position[];
}

export function PositionList({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="p-4 bg-card rounded-lg">
        <h2 className="text-sm text-gray-400 mb-2">Open Positions</h2>
        <p className="text-gray-500 text-sm">No open positions</p>
      </div>
    );
  }

  return (
    <div className="p-4 bg-card rounded-lg">
      <h2 className="text-sm text-gray-400 mb-3">Open Positions</h2>
      <div className="space-y-3">
        {positions.map((pos) => (
          <PositionRow key={`${pos.pair}-${pos.side}`} position={pos} />
        ))}
      </div>
    </div>
  );
}

function PositionRow({ position }: { position: Position }) {
  const pnlColor = position.unrealized_pnl >= 0 ? "text-long" : "text-short";
  const sideColor = position.side === "long" ? "text-long" : "text-short";

  return (
    <div className="border border-gray-800 rounded-lg p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{position.pair}</span>
          <span className={`text-xs font-mono uppercase ${sideColor}`}>{position.side}</span>
          <span className="text-xs text-gray-500">{position.leverage}x</span>
        </div>
        <span className={`font-mono font-bold ${pnlColor}`}>
          {position.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(position.unrealized_pnl)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-2 text-xs text-gray-400">
        <div>Size: <span className="text-white font-mono">{position.size}</span></div>
        <div>Entry: <span className="text-white font-mono">{formatPrice(position.avg_price)}</span></div>
        <div>Mark: <span className="text-white font-mono">{formatPrice(position.mark_price)}</span></div>
      </div>
    </div>
  );
}
```

**Step 4: Create Dashboard component**

```typescript
// web/src/features/dashboard/components/Dashboard.tsx
import { useAccount } from "../hooks/useAccount";
import { AccountSummary } from "./AccountSummary";
import { PositionList } from "./PositionList";

export function Dashboard() {
  const { balance, positions, loading, error } = useAccount();

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-bold">Dashboard</h1>
      {error && (
        <div className="p-3 bg-short/10 border border-short/30 rounded-lg text-sm text-short">
          {error}
        </div>
      )}
      <AccountSummary balance={balance} loading={loading} />
      <PositionList positions={positions} />
    </div>
  );
}
```

**Step 5: Wire into App.tsx**

Replace `DashboardPlaceholder` import with:
```typescript
import { Dashboard } from "./features/dashboard/components/Dashboard";
```
And pass `dashboard={<Dashboard />}`.

**Step 6: Commit**

```
feat(web): add dashboard with account summary and positions
```

---

## Task 10: Frontend - install lightweight-charts

**Step 1: Install dependency**

Run: `cd web && npm install lightweight-charts`

**Step 2: Commit**

```
chore(web): add lightweight-charts dependency
```

---

## Task 11: Frontend - Chart feature

**Files:**
- Modify: `web/src/features/signals/store.ts` (add candle listener registry)
- Modify: `web/src/features/signals/hooks/useSignalWebSocket.ts` (handle candle messages)
- Create: `web/src/features/chart/hooks/useChartData.ts`
- Create: `web/src/features/chart/components/ChartView.tsx`
- Create: `web/src/features/chart/components/CandlestickChart.tsx`
- Modify: `web/src/App.tsx` (replace placeholder)

**Step 1: Add candle listener support to signal store**

In `web/src/features/signals/store.ts`, add a candle listener registry so the existing WebSocket connection can dispatch candle messages without creating a second connection:

```typescript
// Add to SignalState interface:
candleListeners: Set<(candle: any) => void>;

// Add actions:
addCandleListener: (fn: (candle: any) => void) => void;
removeCandleListener: (fn: (candle: any) => void) => void;
notifyCandleListeners: (candle: any) => void;
```

Initialize in create:
```typescript
candleListeners: new Set(),
addCandleListener: (fn) => set((s) => { s.candleListeners.add(fn); }),
removeCandleListener: (fn) => set((s) => { s.candleListeners.delete(fn); }),
notifyCandleListeners: (candle) => { get().candleListeners.forEach((fn) => fn(candle)); },
```

**Step 1b: Handle candle messages in useSignalWebSocket**

In `web/src/features/signals/hooks/useSignalWebSocket.ts`, extend the `onMessage` handler to also process candle messages:

```typescript
ws.onMessage = (data: any) => {
  if (data.type === "signal" && data.signal) {
    addSignal(data.signal);
  } else if (data.type === "candle" && data.candle) {
    useSignalStore.getState().notifyCandleListeners(data.candle);
  }
};
```

**Step 1c: Create useChartData hook**

```typescript
// web/src/features/chart/hooks/useChartData.ts
import { useEffect, useState, useCallback } from "react";
import { api, type CandleData } from "../../../shared/lib/api";
import { useSignalStore } from "../../signals/store";
import type { Timeframe } from "../../signals/types";

export function useChartData(pair: string, timeframe: Timeframe) {
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState(true);
  const addCandleListener = useSignalStore((s) => s.addCandleListener);
  const removeCandleListener = useSignalStore((s) => s.removeCandleListener);

  const fetchCandles = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getCandles(pair, timeframe);
      setCandles(data);
    } catch {
      setCandles([]);
    } finally {
      setLoading(false);
    }
  }, [pair, timeframe]);

  useEffect(() => {
    fetchCandles();
  }, [fetchCandles]);

  useEffect(() => {
    const handler = (candle: any) => {
      if (candle.pair !== pair || candle.timeframe !== timeframe) return;
      setCandles((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.timestamp === candle.timestamp) {
          updated[updated.length - 1] = candle;
        } else if (candle.confirmed) {
          updated.push(candle);
        } else if (last && candle.timestamp > last.timestamp) {
          updated.push(candle);
        }
        return updated;
      });
    };
    addCandleListener(handler);
    return () => removeCandleListener(handler);
  }, [pair, timeframe, addCandleListener, removeCandleListener]);

  return { candles, loading };
}
```

**Step 2: Create CandlestickChart component**

```typescript
// web/src/features/chart/components/CandlestickChart.tsx
import { useEffect, useRef } from "react";
import { createChart, type IChartApi, type ISeriesApi, ColorType } from "lightweight-charts";
import type { CandleData } from "../../../shared/lib/api";

interface Props {
  candles: CandleData[];
}

export function CandlestickChart({ candles }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#121212" },
        textColor: "#9CA3AF",
      },
      grid: {
        vertLines: { color: "#1F2937" },
        horzLines: { color: "#1F2937" },
      },
      crosshair: { mode: 0 },
      timeScale: { timeVisible: true, secondsVisible: false },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#22C55E",
      downColor: "#EF4444",
      borderVisible: false,
      wickUpColor: "#22C55E",
      wickDownColor: "#EF4444",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;
    const mapped = candles.map((c) => ({
      time: (typeof c.timestamp === "number" ? c.timestamp / 1000 : new Date(c.timestamp).getTime() / 1000) as any,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    seriesRef.current.setData(mapped);
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  return <div ref={containerRef} className="w-full h-full" />;
}
```

**Step 3: Create ChartView component**

```typescript
// web/src/features/chart/components/ChartView.tsx
import { useState } from "react";
import { useChartData } from "../hooks/useChartData";
import { CandlestickChart } from "./CandlestickChart";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

export function ChartView() {
  const [pair, setPair] = useState<string>(AVAILABLE_PAIRS[0]);
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const { candles, loading } = useChartData(pair, timeframe);

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      <div className="p-4 flex items-center gap-3">
        <select
          value={pair}
          onChange={(e) => setPair(e.target.value)}
          className="bg-card border border-gray-800 rounded-lg px-3 py-2 text-sm"
        >
          {AVAILABLE_PAIRS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1.5 rounded text-sm ${
                timeframe === tf
                  ? "bg-long/20 text-long border border-long/30"
                  : "bg-card text-gray-400 border border-gray-800"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 px-4 pb-4">
        {loading ? (
          <div className="w-full h-full bg-card rounded-lg animate-pulse" />
        ) : (
          <CandlestickChart candles={candles} />
        )}
      </div>
    </div>
  );
}
```

**Step 4: Wire into App.tsx**

Replace `ChartPlaceholder` with:
```typescript
import { ChartView } from "./features/chart/components/ChartView";
```
And pass `chart={<ChartView />}`.

**Step 5: Commit**

```
feat(web): add real-time candlestick chart with lightweight-charts
```

---

## Task 12: Frontend - Trading confirmation dialog

**Files:**
- Create: `web/src/features/trading/components/OrderDialog.tsx`
- Modify: `web/src/features/signals/components/SignalCard.tsx` (add Execute button)
- Modify: `web/src/features/signals/components/SignalFeed.tsx` (manage dialog state)

**Step 1: Create OrderDialog**

```typescript
// web/src/features/trading/components/OrderDialog.tsx
import { useState, useRef, useEffect } from "react";
import type { Signal } from "../../signals/types";
import { api } from "../../../shared/lib/api";
import { formatPrice } from "../../../shared/lib/format";

interface Props {
  signal: Signal | null;
  onClose: () => void;
}

export function OrderDialog({ signal, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [size, setSize] = useState("1");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; error?: string } | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (signal) {
      setResult(null);
      setSize("1");
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const side = signal.direction === "LONG" ? "buy" : "sell";

  async function handleSubmit() {
    if (!signal) return;
    setSubmitting(true);
    try {
      const res = await api.placeOrder({
        pair: signal.pair,
        side,
        size,
        sl_price: String(signal.levels.stop_loss),
        tp_price: String(signal.levels.take_profit_1),
      });
      setResult(res);
    } catch (e) {
      setResult({ success: false, error: e instanceof Error ? e.message : "Order failed" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }} className="bg-card text-white rounded-xl w-full max-w-md border border-gray-800 backdrop:bg-black/60">
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <span className="text-lg font-bold">Confirm Order</span>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">&times;</button>
        </div>
      </div>

      <div className="p-4 space-y-3">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="text-gray-400">Pair</div>
          <div className="font-mono">{signal.pair}</div>
          <div className="text-gray-400">Side</div>
          <div className={`font-mono ${side === "buy" ? "text-long" : "text-short"}`}>{side.toUpperCase()}</div>
          <div className="text-gray-400">Entry</div>
          <div className="font-mono">{formatPrice(signal.levels.entry)}</div>
          <div className="text-gray-400">Stop Loss</div>
          <div className="font-mono text-short">{formatPrice(signal.levels.stop_loss)}</div>
          <div className="text-gray-400">Take Profit</div>
          <div className="font-mono text-long">{formatPrice(signal.levels.take_profit_1)}</div>
        </div>

        <div>
          <label className="text-sm text-gray-400 block mb-1">Size (contracts)</label>
          <input
            type="text"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            className="w-full p-3 bg-surface rounded-lg border border-gray-800 font-mono focus:border-long/50 focus:outline-none"
          />
        </div>

        {result && (
          <div className={`p-3 rounded-lg text-sm ${result.success ? "bg-long/10 text-long" : "bg-short/10 text-short"}`}>
            {result.success ? "Order placed successfully" : result.error}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-gray-800">
        {result?.success ? (
          <button onClick={onClose} className="w-full py-3 rounded-lg bg-card text-white font-medium">
            Close
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className={`w-full py-3 rounded-lg font-medium ${
              side === "buy" ? "bg-long text-black" : "bg-short text-white"
            } disabled:opacity-50`}
          >
            {submitting ? "Placing order..." : `${side.toUpperCase()} ${signal.pair}`}
          </button>
        )}
      </div>
    </dialog>
  );
}
```

**Step 2: Add Execute button to SignalCard**

In `web/src/features/signals/components/SignalCard.tsx`, add an `onExecute` prop and an Execute button:

Add prop: `onExecute?: (signal: Signal) => void`

Add button after the confidence badge row:

```typescript
{onExecute && (
  <button
    onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
    className={`mt-2 w-full py-2 rounded text-sm font-medium ${
      isLong ? "bg-long/20 text-long" : "bg-short/20 text-short"
    }`}
  >
    Execute {signal.direction}
  </button>
)}
```

**Step 3: Wire OrderDialog into SignalFeed**

In `SignalFeed.tsx`, add state for the trading signal and render OrderDialog:

```typescript
import { useState } from "react";
import { OrderDialog } from "../../trading/components/OrderDialog";
// ... existing imports

export function SignalFeed() {
  useSignalWebSocket();
  const { signals, selectedSignal, selectSignal, clearSelection } = useSignalStore();
  const [tradingSignal, setTradingSignal] = useState<Signal | null>(null);

  return (
    <div className="p-4">
      {/* ... existing header ... */}
      {signals.length === 0 ? (
        <p className="text-gray-500 text-center mt-12">Waiting for signals...</p>
      ) : (
        <div className="space-y-3">
          {signals.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              onSelect={selectSignal}
              onExecute={setTradingSignal}
            />
          ))}
        </div>
      )}
      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
      <OrderDialog signal={tradingSignal} onClose={() => setTradingSignal(null)} />
    </div>
  );
}
```

**Step 4: Commit**

```
feat(web): add order confirmation dialog with execute button on signals
```

---

## Task 13: Final integration test

**Step 1: Rebuild and start all services**

```bash
cd /path/to/krypton
docker compose up -d --build
```

**Step 2: Verify all endpoints**

```bash
# Health
curl http://localhost:8000/health

# Candles
curl -H "X-API-Key: <key>" http://localhost:8000/api/candles?pair=BTC-USDT-SWAP&timeframe=1h&limit=5

# Balance (will 503 if no OKX keys configured)
curl -H "X-API-Key: <key>" http://localhost:8000/api/account/balance

# Positions
curl -H "X-API-Key: <key>" http://localhost:8000/api/account/positions
```

**Step 3: Verify frontend**

- Dashboard tab shows account data (or error if no OKX keys)
- Chart tab shows candlestick chart with live updates
- Signals tab works as before
- Settings tab works as before

**Step 4: Commit any fixes needed**
