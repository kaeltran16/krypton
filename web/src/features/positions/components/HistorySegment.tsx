import { useState, useEffect, useCallback } from "react";
import { api, type TradeHistoryEntry } from "../../../shared/lib/api";
import { formatPair, formatPricePrecision, formatDuration } from "../../../shared/lib/format";
import { Badge } from "../../../shared/components/Badge";
import { Button } from "../../../shared/components/Button";
import { PillSelect } from "../../../shared/components/PillSelect";
import { Skeleton } from "../../../shared/components/Skeleton";

const PAIR_OPTIONS = ["All", "BTC", "ETH", "WIF"] as const;
type PairFilter = (typeof PAIR_OPTIONS)[number];

const PAIR_MAP: Record<PairFilter, string | undefined> = {
  All: undefined,
  BTC: "BTC-USDT-SWAP",
  ETH: "ETH-USDT-SWAP",
  WIF: "WIF-USDT-SWAP",
};

const OUTCOME_COLOR: Record<string, "long" | "short" | "muted"> = {
  TP1_HIT: "long",
  TP2_HIT: "long",
  SL_HIT: "short",
  EXPIRED: "muted",
};

const PAGE_SIZE = 20;

export function HistorySegment() {
  const [entries, setEntries] = useState<TradeHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pairFilter, setPairFilter] = useState<PairFilter>("All");
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const fetchHistory = useCallback(async (offset = 0, append = false) => {
    if (!append) setLoading(true);
    else setLoadingMore(true);
    setError(null);
    try {
      const data = await api.getTradeHistory({
        pair: PAIR_MAP[pairFilter],
        limit: PAGE_SIZE,
        offset,
      });
      if (append) {
        setEntries((prev) => [...prev, ...data]);
      } else {
        setEntries(data);
      }
      setHasMore(data.length === PAGE_SIZE);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [pairFilter]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  function handleLoadMore() {
    fetchHistory(entries.length, true);
  }

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton height="h-10" />
        <Skeleton height="h-32" />
        <Skeleton height="h-32" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <PillSelect
        options={PAIR_OPTIONS}
        selected={pairFilter}
        onToggle={(v) => setPairFilter(v)}
        size="sm"
      />

      {error && (
        <div className="bg-surface-container rounded-lg p-4 text-center">
          <p className="text-on-surface-variant text-sm mb-2">{error}</p>
          <Button variant="secondary" size="sm" onClick={() => fetchHistory()}>Retry</Button>
        </div>
      )}

      {!error && entries.length === 0 && (
        <div className="bg-surface-container rounded-lg p-6 text-center">
          <p className="text-on-surface-variant text-sm">No resolved signals yet</p>
        </div>
      )}

      {entries.map((entry) => (
        <HistoryCard key={entry.signal_id} entry={entry} />
      ))}

      {hasMore && (
        <Button variant="secondary" size="lg" loading={loadingMore} onClick={handleLoadMore}>
          Load more
        </Button>
      )}
    </div>
  );
}

function HistoryCard({ entry }: { entry: TradeHistoryEntry }) {
  const isLong = entry.direction === "long";
  const outcomeColor = OUTCOME_COLOR[entry.outcome] ?? "muted";

  return (
    <div className="bg-surface-container-high rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-headline font-bold text-sm">{formatPair(entry.pair)}</span>
          <Badge color={isLong ? "long" : "short"}>
            {entry.direction.toUpperCase()}
          </Badge>
        </div>
        <Badge color={outcomeColor}>
          {entry.outcome.replace("_", " ")}
        </Badge>
      </div>

      {/* P&L row */}
      <div className="flex items-baseline gap-3 mt-2">
        <span className={`font-headline font-bold tabular ${entry.pnl_pct >= 0 ? "text-long" : "text-short"}`}>
          {entry.pnl_pct >= 0 ? "+" : ""}{entry.pnl_pct.toFixed(2)}%
        </span>
        <span className="text-xs text-on-surface-variant tabular">
          {formatDuration(entry.duration_minutes)}
        </span>
      </div>

      {/* Detail row */}
      <div className="flex items-center gap-4 mt-2 text-xs text-on-surface-variant">
        <span className="tabular">Entry ${formatPricePrecision(entry.entry_price, entry.pair)}</span>
        {entry.sl_price != null && (
          <span className="tabular text-short/70">SL ${formatPricePrecision(entry.sl_price, entry.pair)}</span>
        )}
        {entry.tp1_price != null && (
          <span className="tabular text-long/70">TP ${formatPricePrecision(entry.tp1_price, entry.pair)}</span>
        )}
      </div>

      {/* Signal info */}
      <div className="flex items-center gap-2 mt-2 pt-2 border-t border-outline-variant/10">
        <span className="text-xs text-on-surface-variant">Score:</span>
        <span className={`text-xs font-bold tabular ${entry.signal_score >= 0 ? "text-long" : "text-short"}`}>
          {entry.signal_score > 0 ? "+" : ""}{entry.signal_score}
        </span>
        {entry.signal_reason && (
          <span className="text-xs text-on-surface-variant truncate max-w-[200px]">{entry.signal_reason}</span>
        )}
      </div>
    </div>
  );
}
