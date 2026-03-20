import { useEffect } from "react";
import { useAlertStore } from "../store";
import { CheckCircle, XCircle, Clock } from "lucide-react";

const STATUS_STYLES: Record<string, string> = {
  delivered: "text-tertiary-dim",
  failed: "text-error",
  silenced_by_cooldown: "text-on-surface-variant",
  silenced_by_quiet_hours: "text-on-surface-variant",
};

const STATUS_ICON: Record<string, typeof CheckCircle> = {
  delivered: CheckCircle,
  failed: XCircle,
  silenced_by_cooldown: Clock,
  silenced_by_quiet_hours: Clock,
};

export function AlertHistoryList() {
  const { history, fetchHistory } = useAlertStore();

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (history.length === 0) {
    return (
      <div className="text-center py-12 text-on-surface-variant">
        <p className="text-lg mb-2">No alerts triggered yet</p>
        <p className="text-sm">Alert history will appear here</p>
      </div>
    );
  }

  return (
    <div className="bg-surface-container-lowest border border-outline-variant/20 rounded overflow-hidden">
      {/* Terminal header */}
      <div className="p-3 bg-surface-container flex items-center gap-2">
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-error/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-tertiary-dim/40" />
          <div className="w-2.5 h-2.5 rounded-full bg-primary/40" />
        </div>
        <span className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider ml-2">Terminal Alert Log</span>
      </div>

      {/* Log entries */}
      <div className="p-3 space-y-1">
        {history.map((h) => {
          const Icon = STATUS_ICON[h.delivery_status] ?? Clock;
          return (
            <div key={h.id} className="font-mono text-[11px] leading-relaxed flex items-start gap-2">
              <span className="text-on-surface-variant flex-shrink-0">
                {new Date(h.triggered_at).toLocaleTimeString()}
              </span>
              <span className={`font-bold uppercase flex-shrink-0 ${STATUS_STYLES[h.delivery_status] ?? "text-on-surface-variant"}`}>
                {h.delivery_status.replace(/_/g, " ")}
              </span>
              <span className="text-on-surface truncate">{h.alert_label ?? "Deleted alert"}</span>
              <span className="text-on-surface-variant tabular-nums flex-shrink-0">val={h.trigger_value.toLocaleString()}</span>
              <Icon size={12} className={`flex-shrink-0 mt-0.5 ${STATUS_STYLES[h.delivery_status] ?? "text-on-surface-variant"}`} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
