"""Bulk historical candle import from OKX REST API."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Candle

logger = logging.getLogger(__name__)

OKX_BAR_MAP = {"15m": "15m", "1h": "1H", "4h": "4H", "1D": "1D"}

# OKX returns max 100 candles per request for history endpoints
OKX_PAGE_SIZE = 100


async def import_historical_candles(
    db,
    pairs: list[str],
    timeframes: list[str],
    lookback_days: int = 365,
    progress_callback=None,
    job_id: str | None = None,
) -> dict:
    """Import historical candles from OKX REST API.

    Args:
        db: Database instance with session_factory.
        pairs: List of instrument IDs (e.g., ["BTC-USDT-SWAP"]).
        timeframes: List of timeframes (e.g., ["15m", "1h"]).
        lookback_days: How many days of history to import.
        progress_callback: Optional callable(job_id, status_dict) for progress updates.
        job_id: Job tracking ID.

    Returns:
        Dict with total candles imported and any errors.
    """
    if job_id is None:
        job_id = str(uuid4())

    now = datetime.now(timezone.utc)
    cutoff_ms = int((now.timestamp() - lookback_days * 86400) * 1000)
    total_imported = 0
    errors = []

    async with httpx.AsyncClient(timeout=30) as client:
        for pair in pairs:
            for tf in timeframes:
                bar = OKX_BAR_MAP.get(tf)
                if not bar:
                    errors.append(f"Unsupported timeframe: {tf}")
                    continue

                try:
                    count = await _import_pair_timeframe(
                        client, db, pair, tf, bar, cutoff_ms,
                        progress_callback, job_id,
                    )
                    total_imported += count
                except Exception as e:
                    msg = f"Import failed for {pair}:{tf}: {e}"
                    logger.error(msg)
                    errors.append(msg)

    return {"job_id": job_id, "total_imported": total_imported, "errors": errors}


async def _import_pair_timeframe(
    client: httpx.AsyncClient,
    db,
    pair: str,
    timeframe: str,
    bar: str,
    cutoff_ms: int,
    progress_callback,
    job_id: str,
) -> int:
    """Paginate backwards through OKX history for one pair+timeframe."""
    imported = 0
    after = ""  # empty = start from most recent

    while True:
        params = {"instId": pair, "bar": bar, "limit": str(OKX_PAGE_SIZE)}
        if after:
            params["after"] = after

        # Try long history endpoint first, fall back to regular
        for endpoint in (
            "https://www.okx.com/api/v5/market/history-candles",
        ):
            try:
                resp = await client.get(endpoint, params=params)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception:
                continue
        else:
            logger.error(f"All endpoints failed for {pair}:{timeframe}")
            break

        rows = data.get("data", [])
        if not rows:
            break

        # Upsert candles to DB
        batch_count = await _upsert_candles(db, pair, timeframe, rows)
        imported += batch_count

        # Progress update
        if progress_callback:
            try:
                progress_callback(job_id, {
                    "pair": pair,
                    "timeframe": timeframe,
                    "imported": imported,
                    "status": "importing",
                })
            except Exception:
                pass

        # OKX returns newest-first; last row has the oldest timestamp
        oldest_ts = int(rows[-1][0])
        if oldest_ts <= cutoff_ms:
            break

        # Paginate: use the oldest timestamp as the `after` cursor
        after = str(oldest_ts)

        # Rate limiting: 50ms between requests (OKX 20 req/s limit)
        await asyncio.sleep(0.05)

    logger.info(f"Imported {imported} candles for {pair}:{timeframe}")
    return imported


async def _upsert_candles(db, pair: str, timeframe: str, rows: list) -> int:
    """Upsert a batch of OKX candle rows into the database.

    OKX row format: [timestamp_ms, open, high, low, close, volume, ...]
    """
    count = 0
    try:
        async with db.session_factory() as session:
            for row in rows:
                ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                stmt = pg_insert(Candle).values(
                    pair=pair,
                    timeframe=timeframe,
                    timestamp=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                ).on_conflict_do_nothing(constraint="uq_candle")
                result = await session.execute(stmt)
                if result.rowcount > 0:
                    count += 1
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to upsert candle batch for {pair}:{timeframe}: {e}")

    return count
