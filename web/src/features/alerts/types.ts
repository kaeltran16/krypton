export type AlertType = "price" | "signal" | "indicator" | "portfolio";
export type AlertUrgency = "critical" | "normal" | "silent";
export type DeliveryStatus = "delivered" | "failed" | "silenced_by_cooldown" | "silenced_by_quiet_hours";

export interface Alert {
  id: string;
  type: AlertType;
  label: string;
  pair: string | null;
  timeframe: string | null;
  condition: string | null;
  threshold: number | null;
  secondary_threshold: number | null;
  filters: SignalFilters | null;
  urgency: AlertUrgency;
  cooldown_minutes: number;
  is_active: boolean;
  is_one_shot: boolean;
  last_triggered_at: string | null;
  created_at: string | null;
}

export interface SignalFilters {
  pair?: string | null;
  direction?: "LONG" | "SHORT" | null;
  min_score?: number | null;
  timeframe?: string | null;
}

export interface AlertHistoryEntry {
  id: string;
  alert_id: string;
  alert_label: string | null;
  triggered_at: string;
  trigger_value: number;
  delivery_status: DeliveryStatus;
}

export interface AlertSettings {
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  quiet_hours_tz: string;
}

export interface AlertCreateRequest {
  type: AlertType;
  label?: string;
  pair?: string | null;
  timeframe?: string | null;
  condition?: string;
  threshold?: number;
  secondary_threshold?: number;
  filters?: SignalFilters;
  urgency?: AlertUrgency;
  cooldown_minutes?: number;
  is_one_shot?: boolean;
}

export interface AlertUpdateRequest {
  label?: string;
  threshold?: number;
  secondary_threshold?: number;
  urgency?: AlertUrgency;
  cooldown_minutes?: number;
  is_active?: boolean;
  filters?: SignalFilters;
}

export interface AlertTriggeredEvent {
  type: "alert_triggered";
  alert_id: string;
  label: string;
  trigger_value: number;
  urgency: AlertUrgency;
}
