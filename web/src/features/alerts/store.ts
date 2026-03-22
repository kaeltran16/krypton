import { create } from "zustand";
import type { Alert, AlertHistoryEntry, AlertTriggeredEvent, AlertSettings } from "./types";
import { api } from "../../shared/lib/api";

interface AlertToast {
  id: string;
  label: string;
  triggerValue: number;
  urgency: "critical" | "normal" | "silent";
  dismissedAt?: number;
}

interface AlertState {
  alerts: Alert[];
  history: AlertHistoryEntry[];
  settings: AlertSettings | null;
  loading: boolean;
  historyLoading: boolean;
  toasts: AlertToast[];

  fetchAlerts: () => Promise<void>;
  fetchHistory: () => Promise<void>;
  fetchSettings: () => Promise<void>;
  addTriggeredAlert: (event: AlertTriggeredEvent) => void;
  dismissToast: (id: string) => void;
  removeAlert: (id: string) => void;
  updateAlertInList: (alert: Alert) => void;
  addAlert: (alert: Alert) => void;
}

export const useAlertStore = create<AlertState>()((set, get) => ({
  alerts: [],
  history: [],
  settings: null,
  loading: false,
  historyLoading: false,
  toasts: [],

  fetchAlerts: async () => {
    set({ loading: true });
    try {
      const alerts = await api.getAlerts();
      set({ alerts, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  fetchHistory: async () => {
    set({ historyLoading: true });
    try {
      const history = await api.getAlertHistory({ limit: 50 });
      set({ history, historyLoading: false });
    } catch {
      set({ historyLoading: false });
    }
  },

  fetchSettings: async () => {
    try {
      const settings = await api.getAlertSettings();
      set({ settings });
    } catch {}
  },

  addTriggeredAlert: (event) => {
    if (event.urgency === "silent") return; // No toast for silent
    const toast: AlertToast = {
      id: event.alert_id + "-" + Date.now(),
      label: event.label,
      triggerValue: event.trigger_value,
      urgency: event.urgency,
    };
    set((s) => ({ toasts: [toast, ...s.toasts].slice(0, 5) }));

    // Auto-dismiss non-critical after 3s
    if (event.urgency !== "critical") {
      setTimeout(() => get().dismissToast(toast.id), 3000);
    }
  },

  dismissToast: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },

  removeAlert: (id) => {
    set((s) => ({ alerts: s.alerts.filter((a) => a.id !== id) }));
  },

  updateAlertInList: (alert) => {
    set((s) => ({
      alerts: s.alerts.map((a) => (a.id === alert.id ? alert : a)),
    }));
  },

  addAlert: (alert) => {
    set((s) => ({ alerts: [alert, ...s.alerts] }));
  },
}));
