"""Diagnostic script for long bias investigation.

Run inside the API container:
    docker exec krypton-api-1 python3 scripts/diagnose_long_bias.py

No app imports — standalone SQLAlchemy against the signals table.
Uses DATABASE_URL env var (already set in the container).
"""

import asyncio
import os
from collections import defaultdict

from sqlalchemy import (
    select, func, Column, Integer, String, DateTime, JSON, MetaData, Table,
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_async_engine(DATABASE_URL)
Session = async_sessionmaker(engine)

metadata = MetaData()
signals = Table(
    "signals", metadata,
    Column("id", Integer, primary_key=True),
    Column("pair", String),
    Column("timeframe", String),
    Column("direction", String),
    Column("final_score", Integer),
    Column("raw_indicators", JSON),
    Column("created_at", DateTime),
    autoload_with=None,
)


def fmt(v):
    if isinstance(v, float):
        return f"{v:>5.1f}"
    return f"{str(v):>5}"


async def main():
    async with Session() as s:
        # ── 1. Overall direction distribution ──
        rows = (await s.execute(
            select(signals.c.direction, func.count().label("c"))
            .group_by(signals.c.direction)
        )).all()
        total = sum(r[1] for r in rows)
        print("=" * 70)
        print("1. DIRECTION DISTRIBUTION")
        print("=" * 70)
        counts = {r[0]: r[1] for r in rows}
        for d in ("LONG", "SHORT"):
            c = counts.get(d, 0)
            pct = round(c * 100 / total) if total else 0
            bar = "#" * (pct // 2)
            print(f"  {d:5}: {c:>5} ({pct:>3}%) {bar}")
        print(f"  Total: {total}")

        # ── 2. Per-pair breakdown ──
        rows = (await s.execute(
            select(signals.c.pair, signals.c.direction, func.count().label("c"))
            .group_by(signals.c.pair, signals.c.direction)
            .order_by(signals.c.pair, signals.c.direction)
        )).all()
        print("\n" + "=" * 70)
        print("2. PER-PAIR DIRECTION")
        print("=" * 70)
        pair_totals = defaultdict(int)
        pair_dirs = defaultdict(dict)
        for pair, d, c in rows:
            pair_dirs[pair][d] = c
            pair_totals[pair] += c
        for pair in sorted(pair_dirs):
            t = pair_totals[pair]
            parts = []
            for d in ("LONG", "SHORT"):
                c = pair_dirs[pair].get(d, 0)
                pct = round(c * 100 / t) if t else 0
                parts.append(f"{d}={c}({pct}%)")
            print(f"  {pair:20} {' '.join(parts)}  total={t}")

        # ── 3. Per-timeframe breakdown ──
        rows = (await s.execute(
            select(signals.c.timeframe, signals.c.direction, func.count().label("c"))
            .group_by(signals.c.timeframe, signals.c.direction)
            .order_by(signals.c.timeframe, signals.c.direction)
        )).all()
        print("\n" + "=" * 70)
        print("3. PER-TIMEFRAME DIRECTION")
        print("=" * 70)
        tf_totals = defaultdict(int)
        tf_dirs = defaultdict(dict)
        for tf, d, c in rows:
            tf_dirs[tf][d] = c
            tf_totals[tf] += c
        for tf in sorted(tf_dirs):
            t = tf_totals[tf]
            parts = []
            for d in ("LONG", "SHORT"):
                c = tf_dirs[tf].get(d, 0)
                pct = round(c * 100 / t) if t else 0
                parts.append(f"{d}={c}({pct}%)")
            print(f"  {tf:5} {' '.join(parts)}  total={t}")

        # ── 4. Score distribution for LONG vs SHORT ──
        print("\n" + "=" * 70)
        print("4. SCORE STATS BY DIRECTION")
        print("=" * 70)
        for d in ("LONG", "SHORT"):
            row = (await s.execute(
                select(
                    func.count().label("c"),
                    func.avg(func.abs(signals.c.final_score)).label("avg_abs"),
                    func.min(signals.c.final_score).label("min_s"),
                    func.max(signals.c.final_score).label("max_s"),
                    func.percentile_cont(0.5).within_group(
                        signals.c.final_score
                    ).label("median"),
                ).where(signals.c.direction == d)
            )).first()
            if row and row[0]:
                c, avg_abs, min_s, median, max_s = row
                print(f"  {d:5}: n={c}  avg|score|={avg_abs:.1f}  "
                      f"min={min_s}  median={median:.0f}  max={max_s}")

        # ── 5. Raw indicator breakdown on recent signals ──
        rows = (await s.execute(
            select(
                signals.c.pair, signals.c.timeframe, signals.c.direction,
                signals.c.final_score, signals.c.raw_indicators,
                signals.c.created_at,
            )
            .order_by(signals.c.created_at.desc())
            .limit(30)
        )).all()
        print("\n" + "=" * 70)
        print("5. RECENT 30 SIGNALS - SCORE DECOMPOSITION")
        print("=" * 70)
        print(f"  {'dir':5} {'final':>5} {'tech':>5} {'flow':>5} {'pat':>5} "
              f"{'adx':>5} {'rsi':>5} {'di+':>5} {'di-':>5} {'bb%':>5} "
              f"{'mr_p':>5} {'pair':20} {'tf':4} {'when'}")
        print("  " + "-" * 120)

        tech_by_dir = defaultdict(list)
        flow_by_dir = defaultdict(list)
        trend_by_dir = defaultdict(list)
        mr_by_dir = defaultdict(list)

        for pair, tf, direction, final_score, ind, created_at in rows:
            ind = ind or {}
            tech = ind.get("tech_score", "?")
            flow = ind.get("flow_score", "?")
            pat = ind.get("pattern_score", "?")
            adx = ind.get("adx", "?")
            rsi = ind.get("rsi", "?")
            dip = ind.get("di_plus", "?")
            dim = ind.get("di_minus", "?")
            bbw = ind.get("bb_width_pct", "?")
            mrp = ind.get("mr_pressure", "?")
            trend_s = ind.get("trend_score", "?")
            mr_s = ind.get("mean_rev_score", "?")

            if isinstance(tech, (int, float)):
                tech_by_dir[direction].append(tech)
            if isinstance(flow, (int, float)):
                flow_by_dir[direction].append(flow)
            if isinstance(trend_s, (int, float)):
                trend_by_dir[direction].append(trend_s)
            if isinstance(mr_s, (int, float)):
                mr_by_dir[direction].append(mr_s)

            print(f"  {direction:5} {final_score:>+5} {fmt(tech)} {fmt(flow)} "
                  f"{fmt(pat)} {fmt(adx)} {fmt(rsi)} {fmt(dip)} {fmt(dim)} "
                  f"{fmt(bbw)} {fmt(mrp)} {pair:20} {tf:4} "
                  f"{str(created_at)[:16]}")

        # ── 6. Average sub-scores by direction ──
        print("\n" + "=" * 70)
        print("6. AVERAGE SUB-SCORES BY DIRECTION (from raw_indicators)")
        print("=" * 70)
        for d in ("LONG", "SHORT"):
            parts = []
            for label, store in [("tech", tech_by_dir), ("flow", flow_by_dir),
                                  ("trend", trend_by_dir), ("mr", mr_by_dir)]:
                vals = store.get(d, [])
                if vals:
                    parts.append(f"{label}={sum(vals)/len(vals):+.1f}")
                else:
                    parts.append(f"{label}=n/a")
            print(f"  {d:5}: {' | '.join(parts)}  (n={len(tech_by_dir.get(d, []))})")

        # ── 7. DI+ vs DI- on emitted signals ──
        print("\n" + "=" * 70)
        print("7. DI DIRECTION ON EMITTED SIGNALS")
        print("=" * 70)
        di_long = 0
        di_short = 0
        di_total = 0
        all_rows = (await s.execute(
            select(signals.c.raw_indicators)
            .order_by(signals.c.created_at.desc())
            .limit(200)
        )).all()
        for (ind,) in all_rows:
            if not ind:
                continue
            dip = ind.get("di_plus")
            dim = ind.get("di_minus")
            if dip is not None and dim is not None:
                di_total += 1
                if dip > dim:
                    di_long += 1
                else:
                    di_short += 1
        if di_total:
            print(f"  DI+ > DI- (bullish): {di_long} ({round(di_long*100/di_total)}%)")
            print(f"  DI- > DI+ (bearish): {di_short} ({round(di_short*100/di_total)}%)")
            print(f"  Total sampled: {di_total}")
        else:
            print("  No DI data in raw_indicators")

        # ── 8. Consecutive same-direction streaks ──
        print("\n" + "=" * 70)
        print("8. LONGEST CONSECUTIVE STREAKS")
        print("=" * 70)
        streak_rows = (await s.execute(
            select(signals.c.direction)
            .order_by(signals.c.created_at.asc())
        )).all()
        max_long_streak = 0
        max_short_streak = 0
        cur_dir = None
        cur_streak = 0
        for (d,) in streak_rows:
            if d == cur_dir:
                cur_streak += 1
            else:
                cur_dir = d
                cur_streak = 1
            if d == "LONG":
                max_long_streak = max(max_long_streak, cur_streak)
            else:
                max_short_streak = max(max_short_streak, cur_streak)
        print(f"  Longest LONG  streak: {max_long_streak}")
        print(f"  Longest SHORT streak: {max_short_streak}")

    await engine.dispose()
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


asyncio.run(main())
