import { useEffect, useState } from "react";
import { useNewsStore } from "../store";

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

  return (
    <div className="fixed top-0 left-0 right-0 z-50 p-3 animate-slide-down">
      <div
        className="rounded-lg border border-outline-variant bg-surface-container p-3 shadow-lg backdrop-blur-md"
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
              <span className="text-[10px] text-outline">{alert.source}</span>
            </div>
            <p className="text-sm font-medium leading-snug">{alert.headline}</p>
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
