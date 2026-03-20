import { useState, useEffect } from "react";
import { useAlertStore } from "../store";
import { AlertList } from "./AlertList";
import { AlertForm } from "./AlertForm";
import { AlertHistoryList } from "./AlertHistoryList";
import type { Alert } from "../types";

type Tab = "active" | "create" | "history";

export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const [editingAlert, setEditingAlert] = useState<Alert | null>(null);
  const { fetchAlerts } = useAlertStore();

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  return (
    <div className="space-y-4">
      <div className="flex gap-1 bg-surface-container-lowest rounded-lg p-1">
        {(["active", "create", "history"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider rounded min-h-[44px] transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
              tab === t
                ? "bg-surface-container-highest text-on-surface"
                : "text-on-surface-variant hover:text-on-surface"
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
          onClose={(saved?: boolean) => { setEditingAlert(null); setTab("active"); if (saved) fetchAlerts(); }}
          alert={editingAlert}
        />
      )}
      {tab === "history" && <AlertHistoryList />}
    </div>
  );
}
