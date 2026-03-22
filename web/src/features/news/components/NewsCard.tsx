import { TrendingUp, TrendingDown, Minus, BookOpen, ExternalLink } from "lucide-react";
import type { NewsEvent } from "../types";
import { IMPACT_BADGE, SENTIMENT_COLOR } from "../constants";
import { formatRelativeTime, formatPair } from "../../../shared/lib/format";

interface NewsCardProps {
  event: NewsEvent;
  onSelect?: (event: NewsEvent) => void;
}

const IMPACT_BORDER: Record<string, string> = {
  high: "border-l-error",
  medium: "border-l-primary/40",
  low: "border-l-on-surface-variant/20",
};

const SENTIMENT_ICON: Record<string, typeof TrendingUp> = {
  bullish: TrendingUp,
  bearish: TrendingDown,
  neutral: Minus,
};

const CARD_BASE = "w-full bg-surface-container-low rounded-lg p-4 border-l-4 text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary";

function CardContent({ event }: { event: NewsEvent }) {
  const SentimentIcon = event.sentiment ? SENTIMENT_ICON[event.sentiment] : null;

  return (
    <>
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

      <h3 className="font-headline text-base font-bold leading-tight mb-3">{event.headline}</h3>

      {event.affected_pairs.length > 0 && event.affected_pairs[0] !== "ALL" && (
        <div className="flex flex-wrap gap-2 mb-2">
          {event.affected_pairs.map((pair) => (
            <div key={pair} className="bg-surface-container-highest px-2 py-1 rounded flex items-center gap-2">
              <span className="text-[10px] font-mono font-bold text-on-surface">{formatPair(pair)}</span>
            </div>
          ))}
        </div>
      )}

      {event.content_text ? (
        <div className="flex items-center gap-1.5 text-xs text-primary/80 mt-1">
          <BookOpen size={14} />
          Read article
        </div>
      ) : event.url ? (
        <div className="flex items-center gap-1.5 text-xs text-primary/80 mt-1">
          <ExternalLink size={14} />
          Open in browser
        </div>
      ) : null}
    </>
  );
}

export function NewsCard({ event, onSelect }: NewsCardProps) {
  const borderClass = IMPACT_BORDER[event.impact ?? "low"] ?? "border-l-outline-variant/20";

  // Has extractable content → button that opens reader sheet
  if (event.content_text) {
    return (
      <button
        onClick={() => onSelect?.(event)}
        className={`${CARD_BASE} hover:bg-surface-container cursor-pointer ${borderClass}`}
      >
        <CardContent event={event} />
      </button>
    );
  }

  // Has URL but no content → external link
  if (event.url) {
    return (
      <a
        href={event.url}
        target="_blank"
        rel="noopener noreferrer"
        className={`${CARD_BASE} hover:bg-surface-container block cursor-pointer ${borderClass}`}
      >
        <CardContent event={event} />
      </a>
    );
  }

  // Neither → non-interactive div
  return (
    <div className={`${CARD_BASE} ${borderClass}`}>
      <CardContent event={event} />
    </div>
  );
}
