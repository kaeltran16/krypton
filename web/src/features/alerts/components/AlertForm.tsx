import { useState } from "react";
import { api } from "../../../shared/lib/api";
import { useAlertStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
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

const inputCls = "w-full bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm min-h-[44px] focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none";

export function AlertForm({ onClose, alert: editAlert }: { onClose: (saved?: boolean) => void; alert?: Alert | null }) {
  const [type, setType] = useState<AlertType>(editAlert?.type as AlertType ?? "price");
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
    <form onSubmit={handleSubmit} className="space-y-4">
      {!editAlert && (
        <div className="grid grid-cols-2 gap-2">
          {ALERT_TYPES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => { setType(t.value); setCondition(""); }}
              className={`py-3 text-xs font-bold uppercase tracking-wider rounded-lg border min-h-[44px] transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                type === t.value
                  ? "bg-surface-container-highest text-primary border-primary/40"
                  : "bg-surface-container-lowest text-on-surface-variant border-outline-variant/20"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {type !== "portfolio" && (
        <select
          value={pair}
          onChange={(e) => setPair(e.target.value)}
          className={inputCls}
        >
          <option value="">All pairs</option>
          {AVAILABLE_PAIRS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      )}

      {type !== "signal" && conditions.length > 0 && !editAlert && (
        <select
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          className={inputCls}
          required
        >
          <option value="">Select condition</option>
          {conditions.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      )}

      {type !== "signal" && (
        <input
          type="number"
          placeholder="Threshold"
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          className={inputCls}
          required
          step="any"
        />
      )}

      {type === "price" && condition === "pct_move" && (
        <input
          type="number"
          placeholder="Window (minutes, 5-60)"
          value={secondaryThreshold}
          onChange={(e) => setSecondaryThreshold(e.target.value)}
          className={inputCls}
          min={5}
          max={60}
          required
        />
      )}

      {type === "signal" && (
        <div className="space-y-3">
          <select
            value={filterDirection}
            onChange={(e) => setFilterDirection(e.target.value)}
            className={inputCls}
          >
            <option value="">Any direction</option>
            <option value="LONG">LONG</option>
            <option value="SHORT">SHORT</option>
          </select>
          <input
            type="number"
            placeholder="Min score (0-100)"
            value={filterMinScore}
            onChange={(e) => setFilterMinScore(e.target.value)}
            className={inputCls}
            min={0}
            max={100}
          />
          <select
            value={filterTimeframe}
            onChange={(e) => setFilterTimeframe(e.target.value)}
            className={inputCls}
          >
            <option value="">Any timeframe</option>
            <option value="15m">15m</option>
            <option value="1h">1H</option>
            <option value="4h">4H</option>
          </select>
        </div>
      )}

      <div>
        <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">Urgency</div>
        <div className="bg-surface-container-lowest rounded p-1 flex gap-1">
          {URGENCIES.map((u) => (
            <button
              key={u}
              type="button"
              onClick={() => setUrgency(u)}
              className={`flex-1 py-2 text-xs font-bold uppercase rounded min-h-[44px] transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                urgency === u
                  ? "bg-surface-container-highest text-on-surface rounded"
                  : "text-on-surface-variant"
              }`}
            >
              {u}
            </button>
          ))}
        </div>
      </div>

      <input
        type="number"
        placeholder="Cooldown (minutes)"
        value={cooldown}
        onChange={(e) => setCooldown(e.target.value)}
        className={inputCls}
        min={1}
        max={1440}
      />

      {error && (
        <p className="text-error text-xs">{error}</p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onClose}
          className="flex-1 py-3 text-sm bg-surface-container border border-outline-variant/20 rounded-lg min-h-[44px] text-on-surface-variant focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="flex-1 bg-primary-container text-on-primary-fixed py-3 rounded-lg font-headline font-bold uppercase tracking-widest text-xs min-h-[44px] disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        >
          {submitting ? "Saving..." : editAlert ? "Update Alert" : "Create Alert"}
        </button>
      </div>
    </form>
  );
}
