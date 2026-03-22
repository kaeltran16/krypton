import { useState, useEffect } from "react";
import { useAlertStore } from "../store";
import { AlertList } from "./AlertList";
import { AlertForm } from "./AlertForm";
import { AlertHistoryList } from "./AlertHistoryList";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import type { Alert } from "../types";

type Tab = "active" | "create" | "history";

const TABS: { value: Tab; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "create", label: "Create" },
  { value: "history", label: "History" },
];

export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  const [editingAlert, setEditingAlert] = useState<Alert | null>(null);
  const { fetchAlerts } = useAlertStore();

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  return (
    <div className="space-y-5">
      <SegmentedControl options={TABS} value={tab} onChange={setTab} fullWidth compact />

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
