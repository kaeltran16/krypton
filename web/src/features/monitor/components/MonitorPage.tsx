import { Dropdown, Button, Skeleton, Card, EmptyState } from "../../../shared/components";
import { RefreshCw, Inbox } from "lucide-react";
import { useMonitorData } from "../hooks/useMonitorData";
import { SummaryCards } from "./SummaryCards";
import { PairBreakdown } from "./PairBreakdown";
import { EvaluationTable } from "./EvaluationTable";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { formatPair } from "../../../shared/lib/format";
import type { MonitorPeriod } from "../types";

const PAIR_OPTIONS = [
  { value: "", label: "All Pairs" },
  ...AVAILABLE_PAIRS.map((p) => ({ value: p, label: formatPair(p) })),
];

const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "true", label: "Emitted" },
  { value: "false", label: "Rejected" },
];

const PERIOD_OPTIONS = [
  { value: "1h", label: "1h" },
  { value: "6h", label: "6h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

export function MonitorPage() {
  const {
    filters, updateFilter,
    items, summary,
    loading, error,
    refresh, loadMore, hasMore,
  } = useMonitorData();

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <Dropdown
          options={PAIR_OPTIONS}
          value={filters.pair ?? ""}
          onChange={(v) => updateFilter("pair", v || null)}
          size="sm"
          ariaLabel="Filter by pair"
        />
        <Dropdown
          options={STATUS_OPTIONS}
          value={filters.emitted === null ? "" : String(filters.emitted)}
          onChange={(v) => updateFilter("emitted", v === "" ? null : v === "true")}
          size="sm"
          ariaLabel="Filter by status"
        />
        <Dropdown
          options={PERIOD_OPTIONS}
          value={filters.period}
          onChange={(v) => updateFilter("period", v as MonitorPeriod)}
          size="sm"
          ariaLabel="Time range"
        />
        <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={refresh} />
      </div>

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Skeleton height="h-16" />
            <Skeleton height="h-16" />
            <Skeleton height="h-16" />
          </div>
          <Skeleton count={5} height="h-10" />
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <Card border={false} className="border border-error/20 text-center py-6">
          <p className="text-sm text-on-surface mb-2">{error}</p>
          <Button variant="primary" size="sm" onClick={refresh}>Retry</Button>
        </Card>
      )}

      {/* Content */}
      {!loading && !error && (
        <>
          <SummaryCards summary={summary} />
          {summary && <PairBreakdown pairs={summary.per_pair} />}

          {items.length === 0 ? (
            <EmptyState
              icon={<Inbox size={32} className="text-on-surface-variant" />}
              title="No evaluations found"
              subtitle={
                summary?.total_evaluations === 0
                  ? "Pipeline evaluations will appear here after the first candle closes."
                  : "No evaluations match your filters."
              }
            />
          ) : (
            <EvaluationTable items={items} hasMore={hasMore} onLoadMore={loadMore} />
          )}
        </>
      )}
    </div>
  );
}
