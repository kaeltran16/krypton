import { useEffect, useRef } from "react";
import { X, Zap, ExternalLink } from "lucide-react";
import { Button } from "../../../shared/components/Button";
import type { NewsEvent } from "../types";
import { IMPACT_BADGE, SENTIMENT_COLOR } from "../constants";
import { formatRelativeTime, formatPair } from "../../../shared/lib/format";

interface NewsReaderSheetProps {
  event: NewsEvent | null;
  onClose: () => void;
}

function estimateReadTime(text: string): number {
  return Math.max(1, Math.ceil(text.split(/\s+/).length / 200));
}

export function NewsReaderSheet({ event, onClose }: NewsReaderSheetProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const open = event !== null && event.content_text !== null;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      dialog.showModal();
      document.body.style.overflow = "hidden";
    } else {
      dialog.close();
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
      className="bottom-sheet"
      aria-label="Article reader"
    >
      {event && event.content_text && (
        <div className="flex flex-col max-h-[85dvh]">
          {/* Sticky header */}
          <div className="sticky top-0 z-10 bg-[var(--glass-dialog)] backdrop-blur-xl border-b border-outline-variant/10 pb-3">
            <div className="flex justify-center pt-3 pb-2">
              <div className="w-10 h-1 rounded-full bg-outline-variant/50" />
            </div>
            <div className="flex items-start justify-between px-4">
              <div className="flex items-center gap-2">
                {event.impact && (
                  <span className={`text-[10px] tracking-widest px-2 py-0.5 uppercase rounded font-medium ${IMPACT_BADGE[event.impact] ?? ""}`}>
                    {event.impact}
                  </span>
                )}
                {event.sentiment && (
                  <span className={`text-[10px] uppercase tracking-widest font-medium ${SENTIMENT_COLOR[event.sentiment] ?? ""}`}>
                    {event.sentiment}
                  </span>
                )}
                <span className="text-[10px] text-on-surface-variant tabular">
                  {estimateReadTime(event.content_text)} min read
                </span>
              </div>
              <Button variant="ghost" size="sm" icon={<X size={18} />} onClick={onClose} aria-label="Close article" />
            </div>
          </div>

          {/* Scrollable content */}
          <div className="overflow-y-auto flex-1 p-4 pt-5">
            <div className="mb-5">
              <h2 className="font-headline text-xl font-bold leading-tight mb-2">{event.headline}</h2>
              <p className="text-on-surface-variant text-sm">
                {event.source}
                {event.published_at && ` · ${formatRelativeTime(event.published_at)}`}
              </p>
            </div>

            {event.llm_summary && (
              <div className="bg-surface-container-lowest rounded-lg p-4 border border-outline-variant/10 mb-4">
                <div className="flex items-center gap-2 mb-2">
                  <Zap size={14} className="text-primary" />
                  <h3 className="text-[10px] uppercase tracking-widest text-primary">Krypton AI Summary</h3>
                </div>
                <p className="text-sm text-on-surface-variant leading-relaxed">{event.llm_summary}</p>
              </div>
            )}

            <div className="border-t border-outline-variant/15 pt-4">
              <article className="max-w-prose">
                {event.content_text.split(/\n+/).filter((s) => s.trim()).map((para, i) => (
                  <p
                    key={i}
                    className={`text-on-surface/90 leading-[1.75] mb-4 ${
                      i === 0 ? "text-base" : "text-[15px]"
                    }`}
                  >
                    {para.trim()}
                  </p>
                ))}
              </article>
            </div>

            <div className="border-t border-outline-variant/15 pt-4 flex items-center justify-between">
              <div className="flex flex-wrap gap-2">
                {event.affected_pairs
                  .filter((p) => p !== "ALL")
                  .map((pair) => (
                    <div key={pair} className="bg-surface-container-highest px-2 py-1 rounded">
                      <span className="text-[10px] font-mono font-bold text-on-surface">{formatPair(pair)}</span>
                    </div>
                  ))}
              </div>
              {event.url && (
                <a
                  href={event.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 bg-primary/10 border border-primary/20 rounded-lg px-3 py-2 text-primary text-xs shrink-0"
                >
                  <ExternalLink size={12} />
                  Open original
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </dialog>
  );
}
