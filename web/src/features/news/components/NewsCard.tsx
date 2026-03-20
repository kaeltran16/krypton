import { useState } from "react";
import { TrendingUp, TrendingDown, Minus, ChevronDown, Zap } from "lucide-react";
import type { NewsEvent } from "../types";
import { formatRelativeTime, formatPair } from "../../../shared/lib/format";

interface NewsCardProps {
  event: NewsEvent;
}

const IMPACT_BORDER: Record<string, string> = {
  high: "border-l-error",
  medium: "border-l-primary/40",
  low: "border-l-on-surface-variant/20",
};

const IMPACT_BADGE: Record<string, string> = {
  high: "bg-error-container text-on-error",
  medium: "bg-surface-container-highest text-on-surface-variant",
  low: "bg-surface-container-highest text-on-surface-variant",
};

const SENTIMENT_ICON: Record<string, typeof TrendingUp> = {
  bullish: TrendingUp,
  bearish: TrendingDown,
  neutral: Minus,
};

const SENTIMENT_COLOR: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

export function NewsCard({ event }: NewsCardProps) {
  const [expanded, setExpanded] = useState(false);
  const SentimentIcon = event.sentiment ? SENTIMENT_ICON[event.sentiment] : null;

  return (
    <button
      aria-expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      className={`w-full bg-surface-container-low rounded-lg p-4 border-l-4 text-left transition-all hover:bg-surface-container focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${IMPACT_BORDER[event.impact ?? "low"] ?? "border-l-outline-variant/20"}`}
    >
      {/* Header: impact badge + time + sentiment */}
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-3">
          {event.impact && (
            <span className={`text-[10px] tracking-widest px-2 py-0.5 uppercase rounded font-medium ${IMPACT_BADGE[event.impact] ?? ""}`}>
              {event.impact} Impact
            </span>
          )}
          <span className="text-xs text-on-surface-variant tabular">
            {event.published_at ? formatRelativeTime(event.published_at) : ""} {event.source ? `\u00B7 ${event.source}` : ""}
          </span>
        </div>
        {SentimentIcon && (
          <div className={`flex items-center gap-1 ${SENTIMENT_COLOR[event.sentiment!] ?? ""}`}>
            <SentimentIcon size={14} />
            <span className="text-[10px] uppercase tracking-widest">{event.sentiment}</span>
          </div>
        )}
      </div>

      {/* Headline */}
      <h3 className="font-headline text-base font-bold leading-tight mb-3">{event.headline}</h3>

      {/* Affected pairs */}
      {event.affected_pairs.length > 0 && event.affected_pairs[0] !== "ALL" && (
        <div className="flex flex-wrap gap-2 mb-2">
          {event.affected_pairs.map((pair) => (
            <div key={pair} className="bg-surface-container-highest px-2 py-1 rounded flex items-center gap-2">
              <span className="text-[10px] font-mono font-bold text-on-surface">{formatPair(pair)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Expandable AI summary */}
      {event.llm_summary && !expanded && (
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-primary/60">
          <ChevronDown size={14} />
          View AI Analysis
        </div>
      )}
      {expanded && event.llm_summary && (
        <div className="bg-surface-container-lowest rounded-lg p-4 border border-outline-variant/10 mt-2">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={14} className="text-primary" />
            <span className="text-[10px] uppercase tracking-widest text-primary">Krypton AI Summary</span>
          </div>
          <p className="text-sm text-on-surface-variant leading-relaxed">{event.llm_summary}</p>
        </div>
      )}
    </button>
  );
}
