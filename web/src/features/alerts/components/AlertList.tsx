import { useState } from "react";
import { useAlertStore } from "../store";
import { api } from "../../../shared/lib/api";
import { Pencil, Trash2 } from "lucide-react";
import { Toggle } from "../../../shared/components/Toggle";
import type { Alert } from "../types";

const URGENCY_BORDER: Record<string, string> = {
  critical: "border-tertiary-dim",
  normal: "border-primary",
  silent: "border-outline-variant/30",
};

const URGENCY_TEXT: Record<string, string> = {
  critical: "text-tertiary-dim",
  normal: "text-primary",
  silent: "text-outline",
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
          <div key={i} className="h-20 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        ))}
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <div className="text-center py-12 text-on-surface-variant">
        <p className="text-lg mb-2">No alerts configured</p>
        <p className="text-sm">Create your first alert to get started</p>
      </div>
    );
  }

  const errorBanner = error ? (
    <p className="text-error text-xs bg-error/10 rounded-lg p-2 mb-2">{error}</p>
  ) : null;

  return (
    <div className="space-y-2">
      {errorBanner}
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className={`bg-surface-container-lowest p-3 flex items-center justify-between gap-4 border-l-2 rounded-r-lg ${URGENCY_BORDER[alert.urgency] ?? "border-outline-variant/30"}`}
        >
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <div className="w-10 h-10 rounded bg-surface-container-highest flex flex-col items-center justify-center flex-shrink-0">
              <span className="text-[10px] font-bold uppercase text-on-surface-variant">{alert.type}</span>
              <span className={`text-[10px] font-bold ${URGENCY_TEXT[alert.urgency] ?? "text-outline"}`}>{alert.urgency}</span>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-on-surface truncate">{alert.label}</p>
              {alert.last_triggered_at && (
                <p className="text-[10px] text-on-surface-variant mt-0.5">
                  Last: {new Date(alert.last_triggered_at).toLocaleString()}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            <Toggle checked={alert.is_active} onChange={() => handleToggle(alert)} />
            <button
              onClick={() => onEdit(alert)}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded"
              aria-label="Edit alert"
            >
              <Pencil size={16} />
            </button>
            <button
              onClick={() => handleDelete(alert.id)}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center text-error/70 hover:text-error transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded"
              aria-label="Delete alert"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
