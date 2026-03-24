"""Pull signals from production API into local dev database.

Usage (run inside Docker container):
  MSYS_NO_PATHCONV=1 docker exec -it -e PYTHONPATH=/app krypton-api-1 python3 scripts/pull_signals.py

Options:
  --limit      Max signals to fetch (default: 200)
  --days       How many days back to fetch (default: 30)
  --dry-run    Print what would be inserted without writing to DB
"""

PROD_URL = "https://krypton.kael.life"

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.db.database import Database
from app.db.models import Signal
from app.config import Settings


async def fetch_prod_signals(token: str, limit: int, days: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    params = {"limit": limit, "since": since}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(
            f"{PROD_URL}/api/signals",
            params=params,
            cookies={"krypton_token": token},
        )
        resp.raise_for_status()
        return resp.json()


async def insert_signals(signals: list[dict], dry_run: bool = False):
    settings = Settings()
    db = Database(str(settings.database_url))

    async with db.session_factory() as session:
        existing = await session.execute(select(Signal.id))
        existing_ids = {row[0] for row in existing.all()}

        new_signals = [s for s in signals if s["id"] not in existing_ids]
        if not new_signals:
            print("No new signals to insert.")
            return

        print(f"Found {len(new_signals)} new signals (skipping {len(signals) - len(new_signals)} existing)")

        if dry_run:
            for s in new_signals:
                print(f"  [DRY] {s['id']} {s['pair']} {s['timeframe']} {s['direction']} score={s['final_score']} {s['outcome']} {s['created_at']}")
            return

        for s in new_signals:
            levels = s.get("levels", {})
            row = Signal(
                id=s["id"],
                pair=s["pair"],
                timeframe=s["timeframe"],
                direction=s["direction"],
                final_score=s["final_score"],
                traditional_score=s["traditional_score"],
                explanation=s.get("explanation"),
                llm_factors=s.get("llm_factors"),
                entry=Decimal(str(levels["entry"])),
                stop_loss=Decimal(str(levels["stop_loss"])),
                take_profit_1=Decimal(str(levels["take_profit_1"])),
                take_profit_2=Decimal(str(levels["take_profit_2"])),
                raw_indicators=s.get("raw_indicators"),
                risk_metrics=s.get("risk_metrics"),
                detected_patterns=s.get("detected_patterns"),
                correlated_news_ids=s.get("correlated_news_ids"),
                engine_snapshot=s.get("engine_snapshot"),
                outcome=s.get("outcome", "PENDING"),
                outcome_pnl_pct=Decimal(str(s["outcome_pnl_pct"])) if s.get("outcome_pnl_pct") is not None else None,
                outcome_duration_minutes=s.get("outcome_duration_minutes"),
                outcome_at=datetime.fromisoformat(s["outcome_at"]) if s.get("outcome_at") else None,
                created_at=datetime.fromisoformat(s["created_at"]) if s.get("created_at") else None,
                user_note=s.get("user_note"),
                user_status=s.get("user_status", "OBSERVED"),
            )
            session.add(row)

        await session.commit()
        print(f"Inserted {len(new_signals)} signals.")


async def main():
    parser = argparse.ArgumentParser(description="Pull signals from prod into dev DB")
    parser.add_argument("--limit", type=int, default=200, help="Max signals to fetch")
    parser.add_argument("--days", type=int, default=30, help="Days back to fetch")
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting")
    args = parser.parse_args()

    token = input("Paste krypton_token (browser > DevTools > Application > Cookies): ").strip()
    if not token:
        print("No token provided, aborting.")
        return

    print(f"Fetching up to {args.limit} signals from last {args.days} days from {PROD_URL}...")
    signals = await fetch_prod_signals(token, args.limit, args.days)
    print(f"Fetched {len(signals)} signals from prod.")

    await insert_signals(signals, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
