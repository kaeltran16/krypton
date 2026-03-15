import { useEffect, useRef } from "react";
import { useAlertStore } from "../store";
import { hapticPulse, hapticDoublePulse } from "../../../shared/lib/haptics";

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
    <div className="fixed top-0 left-0 right-0 z-50 p-3 space-y-2 pointer-events-none">
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
            <button className="text-dim text-xs p-1">&times;</button>
          </div>
        </div>
      ))}
    </div>
  );
}
