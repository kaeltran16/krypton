import type { Signal } from "../types";
import { formatScore, formatPrice, formatRelativeTime } from "../../../shared/lib/format";
import { PatternBadges } from "./PatternBadges";

interface SignalCardProps {
  signal: Signal;
  onSelect: (signal: Signal) => void;
  onExecute?: (signal: Signal) => void;
}

export function SignalCard({ signal, onSelect, onExecute }: SignalCardProps) {
  const isLong = signal.direction === "LONG";
  const dirColor = isLong ? "text-long" : "text-short";
  const borderColor = isLong ? "border-long/20" : "border-short/20";
  const bgColor = isLong ? "bg-long/5" : "bg-short/5";
  const isPending = !signal.outcome || signal.outcome === "PENDING";

  return (
    <button
      onClick={() => onSelect(signal)}
      className={`w-full p-3 rounded-lg border text-left transition-colors active:opacity-80 ${borderColor} ${bgColor}${isPending ? " animate-pulse-glow" : ""}`}
    >
      {/* Header: pair, direction badge, timeframe */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5 text-accent flex-shrink-0"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>
          <span className="font-medium text-sm">{signal.pair.replace("-USDT-SWAP", "")}</span>
          <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
            isLong ? "bg-long/15 text-long" : "bg-short/15 text-short"
          }`}>
            {signal.direction}
          </span>
          <span className="text-xs text-dim px-1.5 py-0.5 rounded bg-card-hover">
            {signal.timeframe}
          </span>
        </div>
        {!isPending && <OutcomeBadge outcome={signal.outcome} />}
      </div>

      {/* Score with visual bar */}
      <div className="flex items-center gap-2 mt-2">
        <span className="text-xs text-muted">Score</span>
        <span className={`font-mono font-bold text-sm ${dirColor}`}>
          {formatScore(signal.final_score)}
        </span>
        <div className="flex-1 h-1.5 bg-card-hover rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${isLong ? "bg-long" : "bg-short"}`}
            style={{ width: `${Math.min(Math.max(signal.final_score, 0), 100)}%` }}
          />
        </div>
      </div>

      {/* Pattern badges */}
      {signal.detected_patterns && signal.detected_patterns.length > 0 && (
        <div className="mt-1.5">
          <PatternBadges patterns={signal.detected_patterns} compact />
        </div>
      )}

      {/* Price levels */}
      <div className="flex items-center gap-3 mt-2 text-xs font-mono text-muted">
        <span>Entry <span className="text-foreground">{formatPrice(signal.levels.entry)}</span></span>
        <span>SL <span className="text-short">{formatPrice(signal.levels.stop_loss)}</span></span>
        <span>TP <span className="text-long">{formatPrice(signal.levels.take_profit_1)}</span></span>
      </div>

      {/* Risk metrics */}
      {signal.risk_metrics ? (
        <div className="flex items-center gap-3 mt-1.5 text-[11px] font-mono text-muted">
          <span>Size <span className="text-foreground">{signal.risk_metrics.position_size_base.toFixed(4)}</span></span>
          <span>Risk <span className="text-short">${signal.risk_metrics.risk_amount_usd.toFixed(0)} ({signal.risk_metrics.risk_pct}%)</span></span>
          {signal.risk_metrics.tp1_rr != null && (
            <span>R:R <span className="text-long">1:{signal.risk_metrics.tp1_rr}{signal.risk_metrics.tp2_rr != null ? ` / 1:${signal.risk_metrics.tp2_rr}` : ""}</span></span>
          )}
        </div>
      ) : (
        <RRFallback levels={signal.levels} />
      )}

      {/* Footer: timestamp + badges */}
      <div className="flex items-center justify-between mt-2">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-dim">{formatRelativeTime(signal.created_at)}</span>
          {signal.correlated_news_ids && signal.correlated_news_ids.length > 0 && (
            <span className="text-[11px] px-1 py-0.5 rounded bg-accent/10 text-accent" title="Correlated news">
              <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3 inline-block mr-0.5 -mt-0.5">
                <path d="M3 1h10a2 2 0 012 2v10a2 2 0 01-2 2H3a2 2 0 01-2-2V3a2 2 0 012-2zm1 3v2h8V4H4zm0 4v1h5V8H4zm0 3v1h3v-1H4z" />
              </svg>
              {signal.correlated_news_ids.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {signal.user_status === "TRADED" && (
            <span className="text-[11px] px-1.5 py-0.5 rounded border border-long/40 text-long">Traded</span>
          )}
          {signal.user_status === "SKIPPED" && (
            <span className="text-[11px] px-1.5 py-0.5 rounded border border-border text-muted">Skipped</span>
          )}
          {!isPending && signal.outcome_pnl_pct != null && (
            <span className={`text-xs font-mono ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>
              {signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%
            </span>
          )}
        </div>
      </div>

      {/* Execute button */}
      {onExecute && isPending && (
        <button
          onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
          className={`mt-2 w-full py-2 rounded text-xs font-medium transition-colors active:opacity-80 ${
            isLong ? "bg-long/15 text-long" : "bg-short/15 text-short"
          }`}
        >
          Execute {signal.direction}
        </button>
      )}
    </button>
  );
}

function RRFallback({ levels }: { levels: Signal["levels"] }) {
  const slDist = Math.abs(levels.entry - levels.stop_loss);
  if (slDist === 0) return null;
  const tp1rr = (Math.abs(levels.take_profit_1 - levels.entry) / slDist).toFixed(1);
  const tp2rr = (Math.abs(levels.take_profit_2 - levels.entry) / slDist).toFixed(1);
  return (
    <div className="flex items-center gap-3 mt-1.5 text-[11px] font-mono text-muted">
      <span>R:R <span className="text-long">1:{tp1rr} / 1:{tp2rr}</span></span>
      <span className="text-dim italic">Connect OKX for sizing</span>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    TP1_HIT: "bg-long/20 text-long",
    TP2_HIT: "bg-long/20 text-long",
    SL_HIT: "bg-short/20 text-short",
    EXPIRED: "bg-card-hover text-dim",
  };
  const labels: Record<string, string> = {
    TP1_HIT: "TP1 Hit",
    TP2_HIT: "TP2 Hit",
    SL_HIT: "SL Hit",
    EXPIRED: "Expired",
  };

  return (
    <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium ${styles[outcome] ?? ""}`}>
      {labels[outcome] ?? outcome}
    </span>
  );
}
