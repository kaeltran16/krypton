import { useEffect } from "react";
import { useAlertStore } from "../store";

const STATUS_STYLES: Record<string, string> = {
  delivered: "text-long",
  failed: "text-short",
  silenced_by_cooldown: "text-dim",
  silenced_by_quiet_hours: "text-muted",
};

export function AlertHistoryList() {
  const { history, fetchHistory } = useAlertStore();

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (history.length === 0) {
    return (
      <div className="text-center py-12 text-muted">
        <p className="text-lg mb-2">No alerts triggered yet</p>
        <p className="text-sm">Alert history will appear here</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {history.map((h) => (
        <div key={h.id} className="bg-card border border-border rounded-lg p-3">
          <p className="text-sm font-medium mb-1">{h.alert_label ?? "Deleted alert"}</p>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted">
              Value: {h.trigger_value.toLocaleString()}
            </span>
            <span className={`text-[11px] ${STATUS_STYLES[h.delivery_status] ?? "text-muted"}`}>
              {h.delivery_status.replace(/_/g, " ")}
            </span>
          </div>
          <p className="text-[11px] text-dim mt-1">
            {new Date(h.triggered_at).toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}
