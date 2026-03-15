import { useState, useEffect } from "react";
import { useSettingsStore } from "../../settings/store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import { useSignalStore } from "../../signals/store";
import { api, type RiskSettings } from "../../../shared/lib/api";
import type { Timeframe } from "../../signals/types";
import { BacktestView } from "../../backtest/components/BacktestView";
import { MLTrainingView } from "../../ml/components/MLTrainingView";
import { AlertsPage } from "../../alerts/components/AlertsPage";
import { QuietHoursSettings } from "../../alerts/components/QuietHoursSettings";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

function toggleItem<T>(list: T[], item: T, minOne = true): T[] {
  if (list.includes(item)) {
    if (minOne && list.length <= 1) return list;
    return list.filter((i) => i !== item);
  }
  return [...list, item];
}

export function MorePage() {
  const {
    pairs, timeframes, threshold, notificationsEnabled, apiBaseUrl,
    onchainEnabled, newsAlertsEnabled, newsContextWindow,
    loading, syncError,
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled, setApiBaseUrl,
    setOnchainEnabled, setNewsAlertsEnabled, setNewsContextWindow,
  } = useSettingsStore();
  const connected = useSignalStore((s) => s.connected);
  const [pushStatus, setPushStatus] = useState<"idle" | "subscribing" | "error">("idle");
  const [showBacktest, setShowBacktest] = useState(false);
  const [showMLTraining, setShowMLTraining] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);
  const [mlStatus, setMlStatus] = useState<{ ml_enabled: boolean; loaded_pairs: string[] } | null>(null);

  useEffect(() => {
    api.getMLStatus().then(setMlStatus).catch(() => {});
  }, []);

  async function handleNotificationToggle(enabled: boolean) {
    setNotificationsEnabled(enabled);
    if (enabled) {
      setPushStatus("subscribing");
      const ok = await subscribeToPush(pairs, timeframes, threshold);
      setPushStatus(ok ? "idle" : "error");
      if (!ok) setNotificationsEnabled(false);
    } else {
      await unsubscribeFromPush();
    }
  }

  if (showAlerts) {
    return <AlertsPage onBack={() => setShowAlerts(false)} />;
  }

  if (showBacktest) {
    return <BacktestView onBack={() => setShowBacktest(false)} />;
  }

  if (showMLTraining) {
    return <MLTrainingView onBack={() => setShowMLTraining(false)} />;
  }

  if (loading) {
    return (
      <div className="p-3 space-y-4">
        <div className="h-32 bg-card rounded-lg animate-pulse border border-border" />
        <div className="h-24 bg-card rounded-lg animate-pulse border border-border" />
        <div className="h-24 bg-card rounded-lg animate-pulse border border-border" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-4">
      {syncError && (
        <div className="bg-short/10 border border-short/30 rounded-lg px-3 py-2 text-xs text-short">
          Settings sync failed — changes may not be saved
        </div>
      )}
      {/* TOOLS */}
      <SettingsGroup title="Tools">
        <ToolRow
          icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5"><path d="M3 3v18h18" /><path d="M7 16l4-6 4 4 5-8" /></svg>}
          iconBg="bg-accent/15 text-accent"
          label="Backtester"
          sub="Test strategies against historical data"
          onClick={() => setShowBacktest(true)}
        />
        <ToolRow
          icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>}
          iconBg="bg-purple/15 text-purple"
          label="ML Training"
          sub="Train models on historical data"
          badge={mlStatus ? (
            <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${
              mlStatus.loaded_pairs.length ? "bg-long/15 text-long" : "bg-border text-muted"
            }`}>
              {mlStatus.loaded_pairs.length ? "Ready" : "Inactive"}
            </span>
          ) : undefined}
          onClick={() => setShowMLTraining(true)}
        />
        <ToolRow
          icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg>}
          iconBg="bg-long/15 text-long"
          label="Alerts"
          sub="Price, signal & portfolio alerts"
          onClick={() => setShowAlerts(true)}
          last
        />
      </SettingsGroup>

      {/* TRADING (merged with Data Sources) */}
      <SettingsGroup title="Trading">
        {/* Pairs */}
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[11px] text-dim uppercase tracking-wider mb-2">Pairs</div>
          <div className="flex gap-1.5">
            {AVAILABLE_PAIRS.map((pair) => (
              <button
                key={pair}
                onClick={() => setPairs(toggleItem(pairs, pair))}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                  pairs.includes(pair)
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : "bg-card-hover text-muted"
                }`}
              >
                {pair.replace("-USDT-SWAP", "")}
              </button>
            ))}
          </div>
        </div>

        {/* Timeframes */}
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[11px] text-dim uppercase tracking-wider mb-2">Timeframes</div>
          <div className="flex gap-1.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframes(toggleItem(timeframes, tf))}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                  timeframes.includes(tf)
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : "bg-card-hover text-muted"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Threshold */}
        <div className="px-3 py-3 border-b border-border">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm">Signal Threshold</span>
            <span className="text-sm font-mono text-accent">{threshold}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full accent-accent"
          />
          <div className="flex justify-between text-[11px] text-dim mt-0.5">
            <span>All</span>
            <span>Strong only</span>
          </div>
        </div>

        {/* On-Chain Scoring (was Data Sources) */}
        <div className="px-3 py-3 border-b border-border flex items-center justify-between">
          <div>
            <span className="text-sm">On-Chain Scoring</span>
            <p className="text-[11px] text-dim mt-0.5">Blend exchange flows and whale metrics</p>
          </div>
          <Toggle checked={onchainEnabled} onChange={setOnchainEnabled} />
        </div>

        {/* News Context (was Data Sources) */}
        <div className="px-3 py-3 border-b border-border flex items-center justify-between">
          <div>
            <span className="text-sm">News Alerts</span>
            <p className="text-[11px] text-dim mt-0.5">Push for high-impact news</p>
          </div>
          <Toggle checked={newsAlertsEnabled} onChange={setNewsAlertsEnabled} />
        </div>
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm">LLM News Window</span>
          <div className="flex gap-1.5">
            {[15, 30, 60].map((mins) => (
              <button
                key={mins}
                onClick={() => setNewsContextWindow(mins)}
                className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
                  newsContextWindow === mins
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : "bg-card-hover text-muted"
                }`}
              >
                {mins}m
              </button>
            ))}
          </div>
        </div>
      </SettingsGroup>

      {/* NOTIFICATIONS */}
      <SettingsGroup title="Notifications">
        <div className="px-3 py-3 border-b border-border flex items-center justify-between">
          <div>
            <span className="text-sm">Push Notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-short mt-0.5">Permission denied</p>
            )}
          </div>
          <Toggle
            checked={notificationsEnabled}
            disabled={pushStatus === "subscribing"}
            onChange={(v) => handleNotificationToggle(v)}
          />
        </div>
        <div className="px-3 py-3">
          <QuietHoursSettings />
        </div>
      </SettingsGroup>

      {/* RISK MANAGEMENT */}
      <RiskManagementSection />

      {/* SYSTEM (merged Connection + About) */}
      <SettingsGroup title="System">
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[11px] text-dim uppercase tracking-wider mb-2">API URL</div>
          <input
            type="url"
            value={apiBaseUrl}
            onChange={(e) => setApiBaseUrl(e.target.value)}
            className="w-full p-2.5 bg-card-hover rounded-lg border border-border text-sm font-mono focus:border-accent/50 focus:outline-none"
          />
        </div>
        <div className="px-3 py-3 border-b border-border flex items-center justify-between">
          <span className="text-sm">Connection</span>
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${connected ? "bg-long" : "bg-short animate-pulse"}`} />
            <span className="text-sm text-muted">{connected ? "Connected" : "Disconnected"}</span>
          </div>
        </div>
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm">Version</span>
          <span className="text-sm text-muted font-mono">1.0.0</span>
        </div>
      </SettingsGroup>
    </div>
  );
}

function RiskManagementSection() {
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
      <div>
        <h2 className="text-[11px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">Risk Management</h2>
        <div className="h-32 bg-card rounded-lg animate-pulse border border-border" />
      </div>
    );
  }

  if (!settings) return null;

  return (
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

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${checked ? "bg-accent" : "bg-border"} ${disabled ? "opacity-50" : ""}`}
    >
      <span className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white transition-transform ${checked ? "translate-x-5" : ""}`} />
    </button>
  );
}

function ToolRow({ icon, iconBg, label, sub, badge, onClick, last }: {
  icon: React.ReactNode;
  iconBg: string;
  label: string;
  sub: string;
  badge?: React.ReactNode;
  onClick: () => void;
  last?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full px-3 py-3 flex items-center gap-3 text-left transition-colors active:bg-card-hover ${last ? "" : "border-b border-border"}`}
    >
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${iconBg}`}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{label}</span>
          {badge}
        </div>
        <p className="text-[11px] text-dim mt-0.5 truncate">{sub}</p>
      </div>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted flex-shrink-0">
        <path d="M9 18l6-6-6-6" />
      </svg>
    </button>
  );
}

function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[11px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">{title}</h2>
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        {children}
      </div>
    </div>
  );
}
