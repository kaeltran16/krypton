import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

OKX_REST_BASE = "https://www.okx.com"


def _safe_float(val, default=0.0) -> float:
    """OKX returns empty strings for missing numeric fields."""
    if val is None or val == "":
        return default
    return float(val)


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
        "total_equity": _safe_float(data.get("totalEq")),
        "unrealized_pnl": _safe_float(data.get("upl")),
        "currencies": [
            {
                "currency": d["ccy"],
                "available": _safe_float(d.get("availBal")),
                "frozen": _safe_float(d.get("frozenBal")),
                "equity": _safe_float(d.get("eq")),
            }
            for d in data.get("details", [])
        ],
    }


def parse_positions_response(raw: dict) -> list[dict]:
    if raw.get("code") != "0" or not raw.get("data"):
        return []
    positions = []
    for p in raw["data"]:
        if _safe_float(p.get("pos")) == 0:
            continue
        positions.append({
            "pair": p["instId"],
            "side": "long" if p.get("posSide") == "long" else "short",
            "size": _safe_float(p.get("pos")),
            "avg_price": _safe_float(p.get("avgPx")),
            "mark_price": _safe_float(p.get("markPx")),
            "unrealized_pnl": _safe_float(p.get("upl")),
            "liquidation_price": _safe_float(p.get("liqPx")) or None,
            "margin": _safe_float(p.get("margin")),
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


def parse_instruments_response(raw: dict) -> dict[str, dict]:
    """Parse instruments response into {instId: {lot_size, min_order_size, tick_size}}."""
    if raw.get("code") != "0" or not raw.get("data"):
        return {}
    instruments = {}
    for inst in raw["data"]:
        instruments[inst["instId"]] = {
            "lot_size": _safe_float(inst.get("lotSz"), 1),
            "min_order_size": _safe_float(inst.get("minSz"), 1),
            "tick_size": _safe_float(inst.get("tickSz"), 0.01),
        }
    return instruments


def parse_fills_response(raw: dict) -> list[dict]:
    """Parse fills history response into list of fill dicts."""
    if raw.get("code") != "0" or not raw.get("data"):
        return []
    fills = []
    for f in raw["data"]:
        fills.append({
            "inst_id": f["instId"],
            "side": f["side"],
            "fill_sz": _safe_float(f.get("fillSz")),
            "fill_px": _safe_float(f.get("fillPx")),
            "pnl": _safe_float(f.get("pnl")),
            "fee": _safe_float(f.get("fee")),
            "ts": int(f.get("ts", 0)),
        })
    return fills


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

    async def get_instruments(self, inst_type: str = "SWAP") -> dict[str, dict]:
        """Fetch instrument specs (lot size, min order, tick size). Uses Redis cache (1h)."""
        path = f"/api/v5/public/instruments?instType={inst_type}"
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.get(path)
            resp.raise_for_status()
            return parse_instruments_response(resp.json())

    async def get_fills_today(self) -> list[dict]:
        """Fetch today's (UTC) fills from OKX."""
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        begin_ms = str(int(start_of_day.timestamp() * 1000))
        path = f"/api/v5/trade/fills-history?instType=SWAP&begin={begin_ms}"
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.get(path, headers=self._headers("GET", path.split("?")[0]))
            resp.raise_for_status()
            return parse_fills_response(resp.json())

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
