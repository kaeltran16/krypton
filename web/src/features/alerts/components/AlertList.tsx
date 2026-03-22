import { useState } from "react";
import { useAlertStore } from "../store";
import { api } from "../../../shared/lib/api";
import { Pencil, Trash2 } from "lucide-react";
import { Toggle } from "../../../shared/components/Toggle";
import type { Alert } from "../types";
import { Skeleton } from "../../../shared/components/Skeleton";

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
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete(id: string) {
    setError(null);
    setDeleting(true);
    try {
      await api.deleteAlert(id);
      removeAlert(id);
    } catch (e) {
      setError("Failed to delete alert");
    } finally {
      setDeleting(false);
      setConfirmDeleteId(null);
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
        <Skeleton count={3} />
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
    <div className="space-y-3">
      {errorBanner}
      {alerts.map((alert) => (
        <div key={alert.id}>
          <div
            className={`bg-surface-container-lowest p-4 flex items-center justify-between gap-4 border-l-2 rounded-r-lg transition-opacity active:opacity-80 ${
              URGENCY_BORDER[alert.urgency] ?? "border-outline-variant/30"
            } ${!alert.is_active ? "opacity-50" : ""}`}
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
                onClick={() => setConfirmDeleteId(alert.id)}
                className="min-w-[44px] min-h-[44px] flex items-center justify-center text-error/70 hover:text-error transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded"
                aria-label="Delete alert"
              >
                <Trash2 size={16} />
              </button>
            </div>
          </div>

          {/* Delete confirmation */}
          {confirmDeleteId === alert.id && (
            <div className="flex items-center justify-between gap-2 mt-1 p-2 bg-error/10 border border-error/20 rounded-lg">
              <span className="text-xs text-error">Delete this alert?</span>
              <div className="flex gap-1">
                <button
                  onClick={() => setConfirmDeleteId(null)}
                  disabled={deleting}
                  className="px-3 py-1.5 text-xs rounded bg-surface-container text-on-surface-variant min-h-[36px] focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleDelete(alert.id)}
                  disabled={deleting}
                  className="px-3 py-1.5 text-xs rounded bg-error text-on-error font-bold min-h-[36px] disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
                >
                  {deleting ? "Deleting..." : "Delete"}
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
