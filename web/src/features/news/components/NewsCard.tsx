import { useState } from "react";
import type { NewsEvent } from "../types";
import { formatRelativeTime } from "../../../shared/lib/format";

interface NewsCardProps {
  event: NewsEvent;
}

const IMPACT_STYLES: Record<string, string> = {
  high: "bg-short/20 text-short",
  medium: "bg-accent/20 text-accent",
  low: "bg-card-hover text-dim",
};

const SENTIMENT_STYLES: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-muted",
};

export function NewsCard({ event }: NewsCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <button
      onClick={() => setExpanded(!expanded)}
      className="w-full p-3 rounded-lg border border-border bg-card text-left transition-colors active:opacity-80"
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium leading-snug">{event.headline}</p>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <span className="text-[10px] text-muted font-mono">{event.source}</span>
            {event.impact && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${IMPACT_STYLES[event.impact] ?? ""}`}>
                {event.impact}
              </span>
            )}
            {event.sentiment && (
              <span className={`text-[10px] font-medium ${SENTIMENT_STYLES[event.sentiment] ?? ""}`}>
                {event.sentiment}
              </span>
            )}
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-card-hover text-dim">
              {event.category}
            </span>
            {event.affected_pairs.length > 0 && event.affected_pairs[0] !== "ALL" && (
              <span className="text-[10px] text-accent font-mono">
                {event.affected_pairs.join(", ")}
              </span>
            )}
          </div>
        </div>
        <span className="text-[10px] text-dim whitespace-nowrap">
          {event.published_at ? formatRelativeTime(event.published_at) : ""}
        </span>
      </div>

      {expanded && event.llm_summary && (
        <p className="mt-2 text-xs text-muted leading-relaxed border-t border-border pt-2">
          {event.llm_summary}
        </p>
      )}
    </button>
  );
}
