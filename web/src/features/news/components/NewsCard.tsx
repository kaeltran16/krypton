import { BookOpen, ExternalLink } from "lucide-react";
import type { NewsEvent } from "../types";
import { formatRelativeTime, formatPair } from "../../../shared/lib/format";

interface NewsCardProps {
  event: NewsEvent;
  onSelect?: (event: NewsEvent) => void;
}

const CARD_BASE = "w-full bg-surface-container-low rounded-lg p-4 border-l-4 border-l-outline-variant/20 text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary";

function CardContent({ event }: { event: NewsEvent }) {
  return (
    <>
      <div className="flex justify-between items-start mb-2">
        <span className="text-xs text-on-surface-variant tabular">
          {event.published_at ? formatRelativeTime(event.published_at) : ""} {event.source ? `\u00B7 ${event.source}` : ""}
        </span>
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
  // Has extractable content → button that opens reader sheet
  if (event.content_text) {
    return (
      <button
        onClick={() => onSelect?.(event)}
        className={`${CARD_BASE} hover:bg-surface-container cursor-pointer`}
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
        className={`${CARD_BASE} hover:bg-surface-container block cursor-pointer`}
      >
        <CardContent event={event} />
      </a>
    );
  }

  // Neither → non-interactive div
  return (
    <div className={CARD_BASE}>
      <CardContent event={event} />
    </div>
  );
}
