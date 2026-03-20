import { useState, useEffect } from "react";
import { api, type RiskSettings } from "../../../shared/lib/api";

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
        <div className="h-32 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
      </div>
    );
  }

  if (!settings) return null;

  return (
    <div className="p-3 space-y-5">
      {/* Risk Per Trade */}
      <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-1 h-3 bg-primary rounded-full" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">Risk Per Trade</span>
        </div>
        <div className="font-headline text-3xl font-bold tabular-nums text-on-surface mb-3">
          {(settings.risk_per_trade * 100).toFixed(1)}%
        </div>
        <div className="flex gap-2">
          {[
            { label: "0.5%", value: 0.005 },
            { label: "1%", value: 0.01 },
            { label: "2%", value: 0.02 },
          ].map((opt) => {
            const active = Math.abs(settings.risk_per_trade - opt.value) < 0.0001;
            return (
              <button
                key={opt.label}
                onClick={() => update("risk_per_trade", opt.value)}
                disabled={saving}
                className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                  active
                    ? "bg-primary/15 text-primary border border-primary/30"
                    : "bg-surface-container-lowest text-on-surface-variant"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </section>

      {/* Daily Loss Limit */}
      <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-5">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-1 h-3 bg-primary rounded-full" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">Daily Loss Limit</span>
        </div>
        <RiskOptionRow
          value={settings.daily_loss_limit_pct}
          options={[
            { label: "2%", value: 0.02 },
            { label: "3%", value: 0.03 },
            { label: "5%", value: 0.05 },
          ]}
          onSelect={(v) => update("daily_loss_limit_pct", v)}
          saving={saving}
        />
      </section>

      {/* Position Sizing */}
      <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-5">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-1 h-3 bg-primary rounded-full" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">Position Sizing</span>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-on-surface">Max Positions</span>
            <div className="flex gap-2">
              {[2, 3, 5].map((v) => (
                <button
                  key={v}
                  onClick={() => update("max_concurrent_positions", v)}
                  disabled={saving}
                  className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                    settings.max_concurrent_positions === v
                      ? "bg-primary/15 text-primary border border-primary/30"
                      : "bg-surface-container-lowest text-on-surface-variant"
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
          <div className="h-[1px] bg-outline-variant/20" />
          <div className="flex items-center justify-between">
            <span className="text-sm text-on-surface">Max Exposure</span>
            <div className="flex gap-2">
              {[
                { label: "100%", value: 1.0 },
                { label: "150%", value: 1.5 },
                { label: "200%", value: 2.0 },
              ].map((opt) => {
                const active = Math.abs(settings.max_exposure_pct - opt.value) < 0.001;
                return (
                  <button
                    key={opt.label}
                    onClick={() => update("max_exposure_pct", opt.value)}
                    disabled={saving}
                    className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                      active
                        ? "bg-primary/15 text-primary border border-primary/30"
                        : "bg-surface-container-lowest text-on-surface-variant"
                    }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* Loss Cooldown */}
      <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-5">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-1 h-3 bg-primary rounded-full" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">Loss Cooldown</span>
        </div>
        <div className="flex gap-2">
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
              className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                settings.cooldown_after_loss_minutes === opt.value
                  ? "bg-primary/15 text-primary border border-primary/30"
                  : "bg-surface-container-lowest text-on-surface-variant"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function RiskOptionRow({ value, options, onSelect, saving }: {
  value: number;
  options: { label: string; value: number }[];
  onSelect: (v: number) => void;
  saving: boolean;
}) {
  return (
    <div className="flex gap-2">
      {options.map((opt) => {
        const active = Math.abs(value - opt.value) < 0.0001;
        return (
          <button
            key={opt.label}
            onClick={() => onSelect(opt.value)}
            disabled={saving}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
              active
                ? "bg-primary/15 text-primary border border-primary/30"
                : "bg-surface-container-lowest text-on-surface-variant"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
