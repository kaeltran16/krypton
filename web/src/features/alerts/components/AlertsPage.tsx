import { useState, useEffect } from "react";
import { useAlertStore } from "../store";
import { AlertList } from "./AlertList";
import { AlertForm } from "./AlertForm";
import { AlertHistoryList } from "./AlertHistoryList";
import type { Alert } from "../types";

type Tab = "active" | "create" | "history";

export function AlertsPage({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("active");
  const [editingAlert, setEditingAlert] = useState<Alert | null>(null);
  const { fetchAlerts } = useAlertStore();

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  return (
    <div className="p-3 space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="text-muted text-sm p-2 min-w-[44px] min-h-[44px] flex items-center justify-center"
        >
          Back
        </button>
        <h2 className="text-lg font-semibold flex-1">Alerts</h2>
      </div>

      <div className="flex gap-1 bg-card rounded-lg p-1 border border-border">
        {(["active", "create", "history"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 text-xs font-medium rounded-md min-h-[44px] ${
              tab === t ? "bg-surface text-foreground" : "text-muted"
            }`}
          >
            {t === "active" ? "Active" : t === "create" ? "Create" : "History"}
          </button>
        ))}
      </div>

      {tab === "active" && (
        <AlertList onEdit={(a) => { setEditingAlert(a); setTab("create"); }} />
      )}
      {tab === "create" && (
        <AlertForm
          onClose={() => { setEditingAlert(null); setTab("active"); fetchAlerts(); }}
          alert={editingAlert}
        />
      )}
      {tab === "history" && <AlertHistoryList />}
    </div>
  );
}
