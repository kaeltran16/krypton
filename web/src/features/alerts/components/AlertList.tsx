import { useState } from "react";
import { useAlertStore } from "../store";
import { api } from "../../../shared/lib/api";
import type { Alert } from "../types";

const URGENCY_BADGE: Record<string, string> = {
  critical: "bg-short/20 text-short",
  normal: "bg-accent/20 text-accent",
  silent: "bg-border text-dim",
};

export function AlertList({ onEdit }: { onEdit: (alert: Alert) => void }) {
  const { alerts, loading, removeAlert } = useAlertStore();
  const [error, setError] = useState<string | null>(null);

  async function handleDelete(id: string) {
    setError(null);
    try {
      await api.deleteAlert(id);
      removeAlert(id);
    } catch (e) {
      setError("Failed to delete alert");
    }
  }

  async function handleToggle(alert: Alert) {
    setError(null);
    try {
      const updated = await api.updateAlert(alert.id, { is_active: !alert.is_active });
      useAlertStore.getState().updateAlertInList(updated);
    } catch (e) {
      setError("Failed to update alert");
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 bg-card rounded-lg animate-pulse border border-border" />
        ))}
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <div className="text-center py-12 text-muted">
        <p className="text-lg mb-2">No alerts configured</p>
        <p className="text-sm">Create your first alert to get started</p>
      </div>
    );
  }

  const errorBanner = error ? (
    <p className="text-short text-xs bg-short/10 rounded-lg p-2 mb-2">{error}</p>
  ) : null;

  return (
    <div className="space-y-2">
      {errorBanner}
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className="bg-card border border-border rounded-lg p-3 flex items-center justify-between gap-3"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium uppercase text-dim">{alert.type}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${URGENCY_BADGE[alert.urgency]}`}>
                {alert.urgency}
              </span>
            </div>
            <p className="text-sm font-medium truncate">{alert.label}</p>
            {alert.last_triggered_at && (
              <p className="text-[11px] text-dim mt-0.5">
                Last: {new Date(alert.last_triggered_at).toLocaleString()}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onEdit(alert)}
              className="text-xs text-muted hover:text-foreground p-2 min-w-[44px] min-h-[44px] flex items-center justify-center"
            >
              Edit
            </button>
            <button
              onClick={() => handleToggle(alert)}
              className={`text-xs p-2 min-w-[44px] min-h-[44px] flex items-center justify-center ${
                alert.is_active ? "text-long" : "text-dim"
              }`}
            >
              {alert.is_active ? "On" : "Off"}
            </button>
            <button
              onClick={() => handleDelete(alert.id)}
              className="text-xs text-short/70 hover:text-short p-2 min-w-[44px] min-h-[44px] flex items-center justify-center"
            >
              Del
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
