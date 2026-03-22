import { Newspaper } from "lucide-react";
import type { Signal } from "../types";
import { formatScore, formatPrice, formatRelativeTime, formatPair } from "../../../shared/lib/format";
import { PatternBadges } from "./PatternBadges";
import { Button } from "../../../shared/components/Button";
import { Badge } from "../../../shared/components/Badge";
import { ProgressBar } from "../../../shared/components/ProgressBar";

interface SignalCardProps {
  signal: Signal;
  onSelect: (signal: Signal) => void;
  onExecute?: (signal: Signal) => void;
}

export function SignalCard({ signal, onSelect, onExecute }: SignalCardProps) {
  const isLong = signal.direction === "LONG";
  const isPending = !signal.outcome || signal.outcome === "PENDING";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(signal)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(signal); } }}
      className={`w-full bg-surface-container border border-outline-variant/15 rounded-lg overflow-hidden text-left transition-all hover:bg-surface-container-high cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary${isPending ? " motion-safe:animate-pulse-glow" : ""}`}
    >
      {/* Header: pair, direction badge, score */}
      <div className="p-4 flex justify-between items-start border-b border-outline-variant/10">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-headline text-lg font-bold tracking-tight">{formatPair(signal.pair)}</span>
            <Badge color={isLong ? "long" : "short"} border pill className="px-2">
              {signal.direction} {signal.timeframe}
            </Badge>
          </div>
          <span className="text-on-surface-variant text-xs uppercase tracking-widest mt-1 block">
            {formatRelativeTime(signal.created_at)}
          </span>
        </div>
        <div className="text-right">
          <div className="text-xl font-headline font-bold text-primary tabular">
            {formatScore(signal.final_score)}<span className="text-xs text-on-surface-variant font-medium">/100</span>
          </div>
          <ProgressBar value={signal.final_score} height="sm" glow className="w-16 mt-1 ml-auto" />
          {!isPending && <OutcomeBadge outcome={signal.outcome} />}
        </div>
      </div>

      {/* Pattern badges */}
      {signal.detected_patterns && signal.detected_patterns.length > 0 && (
        <div className="px-4 py-3 flex items-center gap-2 overflow-x-auto [mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]">
          <PatternBadges patterns={signal.detected_patterns} />
          {signal.correlated_news_ids && signal.correlated_news_ids.length > 0 && (
            <Newspaper size={16} className="text-primary ml-auto flex-shrink-0" aria-label="Has correlated news" />
          )}
        </div>
      )}

      {/* Price grid */}
      <div className="px-4 py-3 grid grid-cols-2 gap-y-3 gap-x-6 bg-surface-container-low/50">
        <div>
          <span className="text-xs uppercase tracking-widest text-on-surface-variant mb-1 block">Entry Price</span>
          <span className="font-headline font-bold text-sm tabular">{formatPrice(signal.levels.entry)}</span>
        </div>
        <div>
          <span className="text-xs uppercase tracking-widest text-on-surface-variant mb-1 block">Stop Loss</span>
          <span className="font-headline font-bold text-sm text-short tabular">{formatPrice(signal.levels.stop_loss)}</span>
        </div>
        <div>
          <span className="text-xs uppercase tracking-widest text-on-surface-variant mb-1 block">Take Profit 1</span>
          <span className="font-headline font-bold text-sm text-long tabular">{formatPrice(signal.levels.take_profit_1)}</span>
        </div>
        <div>
          <span className="text-xs uppercase tracking-widest text-on-surface-variant mb-1 block">Take Profit 2</span>
          <span className="font-headline font-bold text-sm text-long tabular">{formatPrice(signal.levels.take_profit_2)}</span>
        </div>
      </div>

      {/* Footer: risk metrics + execute */}
      <div className="p-4 border-t border-outline-variant/10 flex items-center justify-between">
        <div className="flex gap-4">
          {signal.risk_metrics ? (
            <>
              <div className="flex flex-col">
                <span className="text-xs uppercase text-on-surface-variant">Risk</span>
                <span className="text-xs font-bold tabular">{signal.risk_metrics.risk_pct}%</span>
              </div>
              {signal.risk_metrics.tp1_rr != null && (
                <div className="flex flex-col">
                  <span className="text-xs uppercase text-on-surface-variant">R:R</span>
                  <span className="text-xs font-bold tabular">
                    {signal.risk_metrics.tp1_rr}{signal.risk_metrics.tp2_rr != null ? ` / ${signal.risk_metrics.tp2_rr}` : ""}
                  </span>
                </div>
              )}
            </>
          ) : (
            <RRFallback levels={signal.levels} />
          )}
          <div className="flex flex-col">
            <span className="text-xs uppercase text-on-surface-variant">Status</span>
            <span className={`text-xs font-bold uppercase flex items-center gap-1 ${isPending ? "text-long" : "text-on-surface-variant"}`}>
              {isPending && <span className="w-1 h-1 rounded-full bg-long motion-safe:animate-pulse" />}
              {isPending ? "Active" : signal.user_status ?? signal.outcome}
            </span>
          </div>
        </div>
        {onExecute && isPending && (
          <Button
            variant="solid"
            size="sm"
            onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
          >
            Execute
          </Button>
        )}
      </div>
    </div>
  );
}

function RRFallback({ levels }: { levels: Signal["levels"] }) {
  const slDist = Math.abs(levels.entry - levels.stop_loss);
  if (slDist === 0) return null;
  const tp1rr = (Math.abs(levels.take_profit_1 - levels.entry) / slDist).toFixed(1);
  const tp2rr = (Math.abs(levels.take_profit_2 - levels.entry) / slDist).toFixed(1);
  return (
    <div className="flex flex-col">
      <span className="text-xs uppercase text-on-surface-variant">R:R</span>
      <span className="text-xs font-bold tabular">1:{tp1rr} / 1:{tp2rr}</span>
    </div>
  );
}

const OUTCOME_COLOR: Record<string, "long" | "short" | "muted"> = {
  TP1_HIT: "long",
  TP2_HIT: "long",
  SL_HIT:  "short",
  EXPIRED: "muted",
};

const OUTCOME_LABEL: Record<string, string> = {
  TP1_HIT: "TP1 Hit",
  TP2_HIT: "TP2 Hit",
  SL_HIT:  "SL Hit",
  EXPIRED: "Expired",
};

function OutcomeBadge({ outcome }: { outcome: string }) {
  const color = OUTCOME_COLOR[outcome] ?? "muted";
  return (
    <Badge color={color} weight="medium" className="mt-1">
      {OUTCOME_LABEL[outcome] ?? outcome}
    </Badge>
  );
}
