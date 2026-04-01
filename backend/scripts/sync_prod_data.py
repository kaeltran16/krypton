"""Sync production candle and order flow data to local dev database for ML training.

Usage (run inside Docker container):
  MSYS_NO_PATHCONV=1 docker exec -it -e PYTHONPATH=/app krypton-api-1 \
    python3 scripts/sync_prod_data.py --ssh user@prod-host --days 30

Or with a direct connection string:
  python3 scripts/sync_prod_data.py --source postgresql://user:pass@prod:5432/krypton --days 30
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

import asyncpg

from app.ml.utils import TF_MINUTES, bucket_timestamp

BATCH_SIZE = 1000


async def sync_candles(
    source: asyncpg.Connection,
    target: asyncpg.Connection,
    since: datetime,
    pairs: list[str] | None,
) -> int:
    """Sync candles from source to target."""
    where = "WHERE timestamp >= $1"
    params: list = [since]
    if pairs:
        where += f" AND pair = ANY($2)"
        params.append(pairs)

    total = await source.fetchval(f"SELECT count(*) FROM candles {where}", *params)
    if total == 0:
        print("  No candles to sync.")
        return 0

    synced = 0
    offset = 0
    while offset < total:
        rows = await source.fetch(
            f"""SELECT pair, timeframe, timestamp, "open", high, low, close, volume
            FROM candles {where}
            ORDER BY timestamp
            LIMIT {BATCH_SIZE} OFFSET {offset}""",
            *params,
        )
        if not rows:
            break

        await target.executemany(
            """INSERT INTO candles (pair, timeframe, timestamp, "open", high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT ON CONSTRAINT uq_candle DO NOTHING""",
            [(r["pair"], r["timeframe"], r["timestamp"], r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows],
        )
        synced += len(rows)
        offset += BATCH_SIZE
        print(f"  Synced {synced}/{total} candles...")

    return synced


async def sync_flow_snapshots(
    source: asyncpg.Connection,
    target: asyncpg.Connection,
    since: datetime,
    pairs: list[str] | None,
) -> int:
    """Sync order flow snapshots with per-bucket dedup."""
    where = "WHERE timestamp >= $1"
    params: list = [since]
    if pairs:
        where += f" AND pair = ANY($2)"
        params.append(pairs)

    total = await source.fetchval(
        f"SELECT count(*) FROM order_flow_snapshots {where}", *params,
    )
    if total == 0:
        print("  No flow snapshots to sync.")
        return 0

    # Stream in batches, dedup by (pair, bucketed_timestamp)
    deduped: dict[tuple[str, datetime], dict] = {}
    offset = 0
    while offset < total:
        rows = await source.fetch(
            f"""SELECT pair, timestamp, funding_rate, open_interest, oi_change_pct,
                       long_short_ratio, cvd_delta
            FROM order_flow_snapshots {where}
            ORDER BY timestamp
            LIMIT {BATCH_SIZE} OFFSET {offset}""",
            *params,
        )
        if not rows:
            break
        for r in rows:
            bucket_ts = bucket_timestamp(r["timestamp"], "15m")
            key = (r["pair"], bucket_ts)
            deduped[key] = dict(r)
        offset += BATCH_SIZE

    print(f"  Deduped {total} snapshots → {len(deduped)} bucketed snapshots")

    # Batch insert
    items = list(deduped.values())
    synced = 0
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i : i + BATCH_SIZE]
        await target.executemany(
            """INSERT INTO order_flow_snapshots
               (pair, timestamp, funding_rate, open_interest, oi_change_pct, long_short_ratio, cvd_delta)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT ON CONSTRAINT uq_oflow_pair_ts DO NOTHING""",
            [
                (r["pair"], r["timestamp"], r["funding_rate"], r["open_interest"],
                 r["oi_change_pct"], r["long_short_ratio"], r["cvd_delta"])
                for r in batch
            ],
        )
        synced += len(batch)
        print(f"  Synced {synced}/{len(items)} flow snapshots...")

    return synced


async def run(args: argparse.Namespace):
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    pairs = [p.strip() for p in args.pairs.split(",")] if args.pairs else None

    # Build source DSN
    tunnel = None
    if args.source:
        source_dsn = args.source
    elif args.ssh:
        try:
            from sshtunnel import SSHTunnelForwarder
        except ImportError:
            print("ERROR: sshtunnel package required for --ssh mode.")
            print("  pip install sshtunnel")
            return

        ssh_parts = args.ssh.split("@")
        ssh_user = ssh_parts[0] if len(ssh_parts) > 1 else None
        ssh_host = ssh_parts[-1]

        tunnel = SSHTunnelForwarder(
            ssh_host,
            ssh_username=ssh_user,
            ssh_pkey=args.ssh_key,
            remote_bind_address=("127.0.0.1", args.remote_port),
        )
        tunnel.start()
        source_dsn = f"postgresql://postgres:postgres@127.0.0.1:{tunnel.local_bind_port}/{args.source_db}"
        print(f"SSH tunnel open: localhost:{tunnel.local_bind_port} → {args.ssh}:{args.remote_port}")
    else:
        print("ERROR: Either --ssh or --source must be provided.")
        return

    # Resolve target DSN
    target_dsn = args.target
    if not target_dsn:
        try:
            from app.config import Settings
            settings = Settings()
            target_dsn = str(settings.database_url).replace("+asyncpg", "")
        except Exception:
            print("ERROR: --target not provided and could not load Settings.")
            return

    source_conn = None
    target_conn = None
    try:
        source_conn = await asyncpg.connect(source_dsn)
        target_conn = await asyncpg.connect(target_dsn)

        print(f"\nSyncing data since {since.date()} ({args.days} days)")
        if pairs:
            print(f"Pairs: {', '.join(pairs)}")
        print()

        print("Candles:")
        candle_count = await sync_candles(source_conn, target_conn, since, pairs)

        print("\nOrder flow snapshots:")
        flow_count = await sync_flow_snapshots(source_conn, target_conn, since, pairs)

        print(f"\n{'='*40}")
        print(f"Summary:")
        print(f"  Candles synced: {candle_count}")
        print(f"  Flow snapshots synced: {flow_count}")

        if pairs:
            print(f"\nFlow data coverage:")
            for p in pairs:
                candle_n = await target_conn.fetchval(
                    "SELECT count(*) FROM candles WHERE pair = $1 AND timestamp >= $2",
                    p, since,
                )
                flow_n = await target_conn.fetchval(
                    "SELECT count(*) FROM order_flow_snapshots WHERE pair = $1 AND timestamp >= $2",
                    p, since,
                )
                pct = (flow_n / candle_n * 100) if candle_n > 0 else 0
                print(f"  {p}: {flow_n} snapshots / {candle_n} candles ({pct:.0f}%)")

    finally:
        if source_conn:
            await source_conn.close()
        if target_conn:
            await target_conn.close()
        if tunnel:
            tunnel.stop()
            print("\nSSH tunnel closed.")


def main():
    parser = argparse.ArgumentParser(description="Sync production data to local DB for ML training")
    parser.add_argument("--ssh", help="SSH destination (e.g., user@prod-host)")
    parser.add_argument("--ssh-key", default="~/.ssh/id_rsa", help="SSH private key path")
    parser.add_argument("--remote-port", type=int, default=5432, help="Remote Postgres port")
    parser.add_argument("--source-db", default="krypton", help="Source database name")
    parser.add_argument("--source", help="Direct source Postgres DSN (alternative to --ssh)")
    parser.add_argument("--target", help="Target (local) Postgres DSN")
    parser.add_argument("--days", type=int, default=30, help="Days of data to sync")
    parser.add_argument("--pairs", help="Comma-separated pair filter")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
