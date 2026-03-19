import { useState, useEffect } from "react";
import { api, type RiskSettings } from "../../../shared/lib/api";
import { SettingsGroup } from "./SettingsGroup";

export default function RiskPage() {
  const [settings, setSettings] = useState<RiskSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getRiskSettings()
      .then(setSettings)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function update(field: string, value: number | null) {
    if (!settings) return;
    setSaving(true);
    try {
      const updated = await api.updateRiskSettings({ [field]: value });
      setSettings(updated);
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="p-3">
        <div className="h-32 bg-card rounded-lg animate-pulse border border-border" />
      </div>
    );
  }

  if (!settings) return null;

  return (
    <div className="p-3">
      <SettingsGroup title="Risk Management">
        <RiskField
          label="Risk Per Trade"
          value={`${(settings.risk_per_trade * 100).toFixed(1)}%`}
          options={[
            { label: "0.5%", value: 0.005 },
            { label: "1%", value: 0.01 },
            { label: "2%", value: 0.02 },
          ]}
          onSelect={(v) => update("risk_per_trade", v)}
          saving={saving}
        />
        <RiskField
          label="Daily Loss Limit"
          value={`-${(settings.daily_loss_limit_pct * 100).toFixed(1)}%`}
          options={[
            { label: "2%", value: 0.02 },
            { label: "3%", value: 0.03 },
            { label: "5%", value: 0.05 },
          ]}
          onSelect={(v) => update("daily_loss_limit_pct", v)}
          saving={saving}
        />
        <RiskField
          label="Max Positions"
          value={String(settings.max_concurrent_positions)}
          options={[
            { label: "2", value: 2 },
            { label: "3", value: 3 },
            { label: "5", value: 5 },
          ]}
          onSelect={(v) => update("max_concurrent_positions", v)}
          saving={saving}
        />
        <RiskField
          label="Max Exposure"
          value={`${(settings.max_exposure_pct * 100).toFixed(0)}%`}
          options={[
            { label: "100%", value: 1.0 },
            { label: "150%", value: 1.5 },
            { label: "200%", value: 2.0 },
          ]}
          onSelect={(v) => update("max_exposure_pct", v)}
          saving={saving}
        />
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm">Loss Cooldown</span>
          <div className="flex gap-1.5">
            {[
              { label: "Off", value: null as number | null },
              { label: "15m", value: 15 },
              { label: "30m", value: 30 },
              { label: "60m", value: 60 },
            ].map((opt) => (
              <button
                key={opt.label}
                onClick={() => update("cooldown_after_loss_minutes", opt.value)}
                disabled={saving}
                className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
                  settings.cooldown_after_loss_minutes === opt.value
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : "bg-card-hover text-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </SettingsGroup>
    </div>
  );
}

function RiskField({ label, value, options, onSelect, saving }: {
  label: string;
  value: string;
  options: { label: string; value: number }[];
  onSelect: (v: number) => void;
  saving: boolean;
}) {
  return (
    <div className="px-3 py-3 border-b border-border flex items-center justify-between">
      <div>
        <span className="text-sm">{label}</span>
        <span className="text-xs text-muted ml-2 font-mono">{value}</span>
      </div>
      <div className="flex gap-1.5">
        {options.map((opt) => (
          <button
            key={opt.label}
            onClick={() => onSelect(opt.value)}
            disabled={saving}
            className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
              value === opt.label || value === `${opt.label}` || value === `-${opt.label}`
                ? "bg-accent/15 text-accent border border-accent/30"
                : "bg-card-hover text-muted"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

