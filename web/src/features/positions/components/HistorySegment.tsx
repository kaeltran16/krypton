import { useState, useEffect, useCallback } from "react";
import { ChevronDown } from "lucide-react";
import { api, type TradeHistoryEntry } from "../../../shared/lib/api";
import { formatPair, formatPricePrecision, formatDuration, formatRelativeTime } from "../../../shared/lib/format";
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
  const [expanded, setExpanded] = useState(false);
  const isLong = entry.direction === "long";
  const outcomeColor = OUTCOME_COLOR[entry.outcome] ?? "muted";

  return (
    <button
      onClick={() => setExpanded(!expanded)}
      aria-expanded={expanded}
      aria-label={`${formatPair(entry.pair)} ${entry.direction} trade — tap for details`}
      className="w-full bg-surface-container-high rounded-lg p-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary active:scale-[0.98] transition-transform"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-headline font-bold text-sm">{formatPair(entry.pair)}</span>
          <Badge color={isLong ? "long" : "short"}>
            {entry.direction.toUpperCase()}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Badge color={outcomeColor}>
            {entry.outcome.replaceAll("_", " ")}
          </Badge>
          <ChevronDown size={14} className={`text-outline transition-transform duration-200 ${expanded ? "rotate-180" : ""}`} />
        </div>
      </div>

      {/* P&L + entry price row */}
      <div className="flex items-baseline justify-between mt-2">
        <div className="flex items-baseline gap-3">
          <span className={`font-headline font-bold tabular ${entry.pnl_pct >= 0 ? "text-long" : "text-short"}`}>
            {entry.pnl_pct >= 0 ? "+" : ""}{entry.pnl_pct.toFixed(2)}%
          </span>
          <span className="text-xs text-on-surface-variant tabular">
            {formatDuration(entry.duration_minutes)}
          </span>
        </div>
        <span className={`text-xs font-bold tabular ${entry.signal_score >= 0 ? "text-long" : "text-short"}`}>
          {entry.signal_score > 0 ? "+" : ""}{entry.signal_score}
        </span>
      </div>

      {/* Summary row — always visible */}
      <div className="flex items-center gap-4 mt-2 text-xs text-on-surface-variant">
        <span className="tabular">Entry ${formatPricePrecision(entry.entry_price, entry.pair)}</span>
        {entry.sl_price != null && (
          <span className="tabular text-short/70">SL ${formatPricePrecision(entry.sl_price, entry.pair)}</span>
        )}
        {entry.tp1_price != null && (
          <span className="tabular text-long/70">TP ${formatPricePrecision(entry.tp1_price, entry.pair)}</span>
        )}
        <span className="ml-auto">{formatRelativeTime(entry.closed_at)}</span>
      </div>

      {/* Expandable detail */}
      <div className={`grid transition-[grid-template-rows] duration-200 ease-out ${expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
        <div className="overflow-hidden">
          {/* Price grid */}
          <div className="grid grid-cols-3 gap-x-4 gap-y-2 mt-3 pt-3 border-t border-outline-variant/10">
            <DetailCell label="Entry" value={`$${formatPricePrecision(entry.entry_price, entry.pair)}`} />
            {entry.sl_price != null && (
              <DetailCell label="Stop Loss" value={`$${formatPricePrecision(entry.sl_price, entry.pair)}`} color="text-short/80" />
            )}
            {entry.tp1_price != null && (
              <DetailCell label="Take Profit 1" value={`$${formatPricePrecision(entry.tp1_price, entry.pair)}`} color="text-long/80" />
            )}
            {entry.tp2_price != null && (
              <DetailCell label="Take Profit 2" value={`$${formatPricePrecision(entry.tp2_price, entry.pair)}`} color="text-long/80" />
            )}
          </div>

          {/* Timing */}
          <div className="flex items-center gap-4 mt-3 text-xs text-on-surface-variant">
            <span>Opened {formatRelativeTime(entry.opened_at)}</span>
            <span>Closed {formatRelativeTime(entry.closed_at)}</span>
          </div>

          {/* Signal info */}
          <div className="mt-3 pt-3 border-t border-outline-variant/10">
            <div className="flex items-center gap-2">
              <span className="text-xs text-on-surface-variant">Score:</span>
              <span className={`text-xs font-bold tabular ${entry.signal_score >= 0 ? "text-long" : "text-short"}`}>
                {entry.signal_score > 0 ? "+" : ""}{entry.signal_score}
              </span>
            </div>
            {entry.signal_reason && (
              <p className="text-xs text-on-surface-variant mt-1 leading-relaxed">{entry.signal_reason}</p>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

function DetailCell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <span className="text-[11px] text-on-surface-variant uppercase tracking-wider block">{label}</span>
      <span className={`text-xs font-medium tabular ${color ?? ""}`}>{value}</span>
    </div>
  );
}
