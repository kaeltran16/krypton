"""Sync production data to local dev database for ML training.

Two-step workflow for when prod DB isn't directly reachable from local:

  1. Export on prod:
     docker exec -e PYTHONPATH=/app backend-api-1 \
       python3 scripts/sync_prod_data.py export \
       --source postgresql://krypton:PASS@postgres:5432/krypton \
       --days 30 --pairs BTC-USDT-SWAP,ETH-USDT-SWAP,WIF-USDT-SWAP

  2. Copy file to local machine:
     scp root@prod-host:/app/sync_export.sql .

  3. Import locally:
     docker exec -i krypton-postgres-1 psql -U krypton krypton < sync_export.sql

Or direct sync when both DBs are reachable:

  python3 scripts/sync_prod_data.py sync \
    --source postgresql://... --target postgresql://... --days 30
"""

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

import asyncpg

from app.ml.utils import bucket_timestamp

BATCH_SIZE = 1000


async def export_data(args: argparse.Namespace):
    """Export candles and flow snapshots to a SQL file with ON CONFLICT upserts."""
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    pairs = [p.strip() for p in args.pairs.split(",")] if args.pairs else None

    conn = await asyncpg.connect(args.source, ssl=False)
    out_path = args.output
    try:
        with open(out_path, "w") as f:
            # Candles
            where = "WHERE timestamp >= $1"
            params: list = [since]
            if pairs:
                where += " AND pair = ANY($2)"
                params.append(pairs)

            total = await conn.fetchval(f"SELECT count(*) FROM candles {where}", *params)
            print(f"Exporting {total} candles...")

            offset = 0
            candle_count = 0
            while offset < total:
                rows = await conn.fetch(
                    f"""SELECT pair, timeframe, timestamp, "open", high, low, close, volume
                    FROM candles {where}
                    ORDER BY timestamp
                    LIMIT {BATCH_SIZE} OFFSET {offset}""",
                    *params,
                )
                if not rows:
                    break
                for r in rows:
                    ts = r["timestamp"].isoformat()
                    pair = _esc(r["pair"])
                    tf = _esc(r["timeframe"])
                    f.write(
                        f'INSERT INTO candles (pair, timeframe, timestamp, "open", high, low, close, volume) '
                        f"VALUES ('{pair}', '{tf}', '{ts}', {r['open']}, {r['high']}, {r['low']}, {r['close']}, {r['volume']}) "
                        f"ON CONFLICT ON CONSTRAINT uq_candle DO NOTHING;\n"
                    )
                candle_count += len(rows)
                offset += BATCH_SIZE
                print(f"  {candle_count}/{total} candles...")

            # Flow snapshots with dedup
            total_flow = await conn.fetchval(
                f"SELECT count(*) FROM order_flow_snapshots {where}", *params,
            )
            print(f"\nExporting flow snapshots ({total_flow} raw)...")

            deduped: dict[tuple[str, datetime], dict] = {}
            offset = 0
            while offset < total_flow:
                rows = await conn.fetch(
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

            print(f"  Deduped → {len(deduped)} bucketed snapshots")

            for r in deduped.values():
                ts = r["timestamp"].isoformat()
                pair = _esc(r["pair"])
                fr = _sql_num(r["funding_rate"])
                oi = _sql_num(r["open_interest"])
                oic = _sql_num(r["oi_change_pct"])
                lsr = _sql_num(r["long_short_ratio"])
                cvd = _sql_num(r["cvd_delta"])
                f.write(
                    f"INSERT INTO order_flow_snapshots (pair, timestamp, funding_rate, open_interest, oi_change_pct, long_short_ratio, cvd_delta) "
                    f"VALUES ('{pair}', '{ts}', {fr}, {oi}, {oic}, {lsr}, {cvd}) "
                    f"ON CONFLICT ON CONSTRAINT uq_oflow_pair_ts DO NOTHING;\n"
                )

            # Update pipeline_settings pairs to include synced pairs
            if pairs:
                pairs_json = json.dumps(pairs)
                f.write(
                    f"\nUPDATE pipeline_settings SET pairs = '{pairs_json}'::jsonb WHERE id = 1;\n"
                )

        print(f"\nExported to {out_path}")
        print(f"  Candles: {candle_count}")
        print(f"  Flow snapshots: {len(deduped)}")
        if pairs:
            print(f"  Pipeline pairs set to: {pairs}")
    finally:
        await conn.close()


async def sync_direct(args: argparse.Namespace):
    """Direct sync between two reachable databases."""
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    pairs = [p.strip() for p in args.pairs.split(",")] if args.pairs else None

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
        candle_count = await _sync_candles(source_conn, target_conn, since, pairs)

        print("\nOrder flow snapshots:")
        flow_count = await _sync_flow_snapshots(source_conn, target_conn, since, pairs)

        # Update pipeline_settings pairs on target
        if pairs:
            pairs_json = json.dumps(pairs)
            await target_conn.execute(
                f"UPDATE pipeline_settings SET pairs = $1::jsonb WHERE id = 1",
                pairs_json,
            )
            print(f"\nPipeline pairs set to: {pairs}")

        print(f"\n{'='*40}")
        print(f"Summary:")
        print(f"  Candles synced: {candle_count}")
        print(f"  Flow snapshots synced: {flow_count}")

    finally:
        if source_conn:
            await source_conn.close()
        if target_conn:
            await target_conn.close()
        if tunnel:
            tunnel.stop()
            print("\nSSH tunnel closed.")


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _sql_num(v) -> str:
    return "NULL" if v is None else str(v)


async def _sync_candles(source, target, since, pairs) -> int:
    where = "WHERE timestamp >= $1"
    params: list = [since]
    if pairs:
        where += " AND pair = ANY($2)"
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


async def _sync_flow_snapshots(source, target, since, pairs) -> int:
    where = "WHERE timestamp >= $1"
    params: list = [since]
    if pairs:
        where += " AND pair = ANY($2)"
        params.append(pairs)

    total = await source.fetchval(
        f"SELECT count(*) FROM order_flow_snapshots {where}", *params,
    )
    if total == 0:
        print("  No flow snapshots to sync.")
        return 0

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


def main():
    parser = argparse.ArgumentParser(description="Sync production data to local DB for ML training")
    sub = parser.add_subparsers(dest="command", required=True)

    # Export subcommand
    exp = sub.add_parser("export", help="Export data to SQL file (run on prod)")
    exp.add_argument("--source", required=True, help="Source Postgres DSN")
    exp.add_argument("--output", default="sync_export.sql", help="Output SQL file path")
    exp.add_argument("--days", type=int, default=30, help="Days of data to export")
    exp.add_argument("--pairs", help="Comma-separated pair filter")

    # Sync subcommand (direct)
    syn = sub.add_parser("sync", help="Direct sync between two databases")
    syn.add_argument("--ssh", help="SSH destination (e.g., user@prod-host)")
    syn.add_argument("--ssh-key", default="~/.ssh/id_rsa", help="SSH private key path")
    syn.add_argument("--remote-port", type=int, default=5432, help="Remote Postgres port")
    syn.add_argument("--source-db", default="krypton", help="Source database name")
    syn.add_argument("--source", help="Direct source Postgres DSN")
    syn.add_argument("--target", help="Target (local) Postgres DSN")
    syn.add_argument("--days", type=int, default=30, help="Days of data to sync")
    syn.add_argument("--pairs", help="Comma-separated pair filter")

    args = parser.parse_args()
    if args.command == "export":
        asyncio.run(export_data(args))
    elif args.command == "sync":
        asyncio.run(sync_direct(args))


if __name__ == "__main__":
    main()
