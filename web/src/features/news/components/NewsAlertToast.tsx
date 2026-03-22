import { useEffect, useState } from "react";
import { useNewsStore } from "../store";

const IMPACT_STYLES: Record<string, string> = {
  high: "border-short/40 bg-short/10",
  medium: "border-primary/40 bg-primary/10",
  low: "border-outline-variant bg-surface-container",
};

const SENTIMENT_STYLES: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

export function NewsAlertToast() {
  const alert = useNewsStore((s) => s.currentAlert);
  const dismiss = useNewsStore((s) => s.dismissAlert);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!alert) return;
    setExpanded(false);
    const timer = setTimeout(dismiss, 8000);
    return () => clearTimeout(timer);
  }, [alert, dismiss]);

  if (!alert) return null;

  const borderStyle = IMPACT_STYLES[alert.impact ?? "low"] ?? IMPACT_STYLES.low;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 p-3 animate-slide-down">
      <div
        className={`rounded-lg border p-3 shadow-lg backdrop-blur-md ${borderStyle}`}
        onClick={() => setExpanded(!expanded)}
        onTouchEnd={(e) => {
          if (expanded) {
            e.preventDefault();
            dismiss();
          }
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              {alert.impact && (
                <span className={`text-[10px] font-bold uppercase ${
                  alert.impact === "high" ? "text-short" : "text-primary"
                }`}>
                  {alert.impact}
                </span>
              )}
              {alert.sentiment && (
                <span className={`text-[10px] font-medium ${SENTIMENT_STYLES[alert.sentiment] ?? ""}`}>
                  {alert.sentiment}
                </span>
              )}
              <span className="text-[10px] text-outline">{alert.source}</span>
            </div>
            <p className="text-sm font-medium leading-snug">{alert.headline}</p>
            {expanded && alert.llm_summary && (
              <p className="mt-1.5 text-xs text-on-surface-variant leading-relaxed">
                {alert.llm_summary}
              </p>
            )}
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              dismiss();
            }}
            className="text-outline text-xs p-1"
          >
            &times;
          </button>
        </div>
      </div>
    </div>
  );
}
