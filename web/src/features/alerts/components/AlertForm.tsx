import { useState } from "react";
import { api } from "../../../shared/lib/api";
import { useAlertStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { Dropdown } from "../../../shared/components/Dropdown";
import { Button } from "../../../shared/components/Button";
import { PillSelect } from "../../../shared/components/PillSelect";
import { FormField, INPUT_STYLES } from "../../../shared/components/FormField";
import type { Alert, AlertType, AlertUrgency, AlertCreateRequest } from "../types";

const ALERT_TYPES: { value: AlertType; label: string }[] = [
  { value: "price", label: "Price" },
  { value: "signal", label: "Signal" },
  { value: "indicator", label: "Indicator" },
  { value: "portfolio", label: "Portfolio" },
];

const PRICE_CONDITIONS = [
  { value: "crosses_above", label: "Crosses above" },
  { value: "crosses_below", label: "Crosses below" },
  { value: "pct_move", label: "% move in window" },
];

const INDICATOR_CONDITIONS = [
  { value: "rsi_above", label: "RSI above" },
  { value: "rsi_below", label: "RSI below" },
  { value: "adx_above", label: "ADX above" },
  { value: "bb_width_percentile_above", label: "BB width above" },
  { value: "bb_width_percentile_below", label: "BB width below" },
  { value: "funding_rate_above", label: "Funding rate above" },
  { value: "funding_rate_below", label: "Funding rate below" },
];

const PORTFOLIO_CONDITIONS = [
  { value: "drawdown_pct", label: "Drawdown exceeds %" },
  { value: "pnl_crosses", label: "PnL crosses threshold" },
  { value: "position_loss_pct", label: "Position loss exceeds %" },
];

const URGENCIES: AlertUrgency[] = ["critical", "normal", "silent"];


export function AlertForm({ onClose, alert: editAlert }: { onClose: (saved?: boolean) => void; alert?: Alert | null }) {
  const [type, setType] = useState<AlertType>(editAlert?.type as AlertType ?? "price");
  const [label, setLabel] = useState(editAlert?.label ?? "");
  const [pair, setPair] = useState<string>(editAlert?.pair ?? "");
  const [condition, setCondition] = useState(editAlert?.condition ?? "");
  const [threshold, setThreshold] = useState(editAlert?.threshold?.toString() ?? "");
  const [secondaryThreshold, setSecondaryThreshold] = useState(editAlert?.secondary_threshold?.toString() ?? "");
  const [urgency, setUrgency] = useState<AlertUrgency>(editAlert?.urgency ?? "normal");
  const [cooldown, setCooldown] = useState(editAlert?.cooldown_minutes?.toString() ?? "15");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [filterDirection, setFilterDirection] = useState(editAlert?.filters?.direction ?? "");
  const [filterMinScore, setFilterMinScore] = useState(editAlert?.filters?.min_score?.toString() ?? "");
  const [filterTimeframe, setFilterTimeframe] = useState(editAlert?.filters?.timeframe ?? "");

  const conditions =
    type === "price" ? PRICE_CONDITIONS :
    type === "indicator" ? INDICATOR_CONDITIONS :
    type === "portfolio" ? PORTFOLIO_CONDITIONS : [];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      if (editAlert) {
        const updated = await api.updateAlert(editAlert.id, {
          label: label.trim() || undefined,
          threshold: threshold ? parseFloat(threshold) : undefined,
          secondary_threshold: secondaryThreshold ? parseInt(secondaryThreshold) : undefined,
          urgency,
          cooldown_minutes: parseInt(cooldown) || 15,
          filters: type === "signal" ? {
            pair: pair || null,
            direction: (filterDirection || null) as "LONG" | "SHORT" | null,
            min_score: filterMinScore ? parseInt(filterMinScore) : null,
            timeframe: filterTimeframe || null,
          } : undefined,
        });
        useAlertStore.getState().updateAlertInList(updated);
      } else {
        const body: AlertCreateRequest = {
          type,
          label: label.trim() || undefined,
          pair: pair || null,
          urgency,
          cooldown_minutes: parseInt(cooldown) || 15,
        };

        if (type === "signal") {
          body.filters = {
            pair: pair || null,
            direction: (filterDirection || null) as "LONG" | "SHORT" | null,
            min_score: filterMinScore ? parseInt(filterMinScore) : null,
            timeframe: filterTimeframe || null,
          };
        } else {
          body.condition = condition;
          body.threshold = parseFloat(threshold);
          if (type === "price" && condition === "pct_move") {
            body.secondary_threshold = parseInt(secondaryThreshold) || 15;
          }
        }

        const alert = await api.createAlert(body);
        useAlertStore.getState().addAlert(alert);
      }
      onClose(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save alert");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {!editAlert && (
        <PillSelect
          options={ALERT_TYPES.map((t) => t.value)}
          selected={type}
          onToggle={(v) => { setType(v); setCondition(""); }}
          renderLabel={(v) => ALERT_TYPES.find((t) => t.value === v)?.label ?? v}
          size="sm"
          wrap
        />
      )}

      <FormField label="Name">
        <input
          type="text"
          placeholder="e.g. BTC breakout alert"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className={INPUT_STYLES}
        />
      </FormField>

      {type !== "portfolio" && (
        <Dropdown
          value={pair}
          onChange={setPair}
          placeholder="All pairs"
          options={[
            { value: "", label: "All pairs" },
            ...AVAILABLE_PAIRS.map((p) => ({ value: p, label: p })),
          ]}
          ariaLabel="Select trading pair"
        />
      )}

      {type !== "signal" && conditions.length > 0 && !editAlert && (
        <Dropdown
          value={condition}
          onChange={setCondition}
          placeholder="Select condition"
          options={[
            { value: "", label: "Select condition" },
            ...conditions,
          ]}
          ariaLabel="Select condition"
        />
      )}

      {type !== "signal" && (
        <FormField label="Threshold">
          <input
            type="number"
            placeholder="Enter value"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            className={INPUT_STYLES}
            required
            step="any"
          />
        </FormField>
      )}

      {type === "price" && condition === "pct_move" && (
        <FormField label="Window (minutes)">
          <input
            type="number"
            placeholder="5–60"
            value={secondaryThreshold}
            onChange={(e) => setSecondaryThreshold(e.target.value)}
            className={INPUT_STYLES}
            min={5}
            max={60}
            required
          />
        </FormField>
      )}

      {type === "signal" && (
        <div className="space-y-4">
          <Dropdown
            value={filterDirection}
            onChange={setFilterDirection}
            placeholder="Any direction"
            options={[
              { value: "", label: "Any direction" },
              { value: "LONG", label: "LONG" },
              { value: "SHORT", label: "SHORT" },
            ]}
            ariaLabel="Filter direction"
          />
          <FormField label="Min Score">
            <input
              type="number"
              placeholder="0–100"
              value={filterMinScore}
              onChange={(e) => setFilterMinScore(e.target.value)}
              className={INPUT_STYLES}
              min={0}
              max={100}
            />
          </FormField>
          <Dropdown
            value={filterTimeframe}
            onChange={setFilterTimeframe}
            placeholder="Any timeframe"
            options={[
              { value: "", label: "Any timeframe" },
              { value: "15m", label: "15m" },
              { value: "1h", label: "1H" },
              { value: "4h", label: "4H" },
            ]}
            ariaLabel="Filter timeframe"
          />
        </div>
      )}

      <FormField label="Urgency">
        <PillSelect
          options={URGENCIES}
          selected={urgency}
          onToggle={setUrgency}
          renderLabel={(u) => u.charAt(0).toUpperCase() + u.slice(1)}
          size="sm"
          wrap
        />
      </FormField>

      <FormField label="Cooldown (minutes)">
        <input
          type="number"
          placeholder="15"
          value={cooldown}
          onChange={(e) => setCooldown(e.target.value)}
          className={INPUT_STYLES}
          min={1}
          max={1440}
        />
      </FormField>

      {error && (
        <p className="text-error text-xs bg-error/10 rounded-lg p-2">{error}</p>
      )}

      <div className="flex gap-2">
        <Button variant="secondary" size="lg" type="button" onClick={() => onClose()} className="flex-1">Cancel</Button>
        <Button variant="solid" size="lg" type="submit" loading={submitting} className="flex-1">
          {editAlert ? "Update Alert" : "Create Alert"}
        </Button>
      </div>
    </form>
  );
}
