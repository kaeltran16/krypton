import { useEffect, useRef } from "react";
import { useAlertStore } from "../store";
import { hapticPulse, hapticDoublePulse } from "../../../shared/lib/haptics";
import { X } from "lucide-react";

const URGENCY_STYLES: Record<string, string> = {
  critical: "border-short/60 bg-short/15",
  normal: "border-accent/40 bg-accent/10",
};

export function AlertToast() {
  const toasts = useAlertStore((s) => s.toasts);
  const dismiss = useAlertStore((s) => s.dismissToast);
  const prevLength = useRef(toasts.length);

  useEffect(() => {
    if (toasts.length > prevLength.current && toasts.length > 0) {
      const latest = toasts[0];
      if (latest.urgency === "critical") {
        hapticDoublePulse();
      } else {
        hapticPulse();
      }
    }
    prevLength.current = toasts.length;
  }, [toasts]);

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed top-0 left-0 right-0 z-50 p-3 pt-[calc(0.75rem+env(safe-area-inset-top))] space-y-2 pointer-events-none"
      role="alert"
      aria-live="polite"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-lg border p-3 shadow-lg backdrop-blur-md pointer-events-auto animate-slide-down ${
            URGENCY_STYLES[toast.urgency] ?? URGENCY_STYLES.normal
          }`}
          onClick={() => dismiss(toast.id)}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex-1 min-w-0">
              <span className={`text-[10px] font-bold uppercase ${
                toast.urgency === "critical" ? "text-short" : "text-accent"
              }`}>
                {toast.urgency} alert
              </span>
              <p className="text-sm font-medium mt-0.5">{toast.label}</p>
              <p className="text-xs text-muted">
                Value: {toast.triggerValue.toLocaleString()}
              </p>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); dismiss(toast.id); }}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-colors rounded focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
              aria-label="Dismiss alert"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
