import base64
import hashlib
import hmac
import json
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
