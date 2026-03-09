import { useState, useEffect } from "react";
import { useSettingsStore } from "../../settings/store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import { useSignalStore } from "../../signals/store";
import { api, type RiskSettings } from "../../../shared/lib/api";
import type { Timeframe } from "../../signals/types";
import { BacktestView } from "../../backtest/components/BacktestView";

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
    loading, syncError,
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled, setApiBaseUrl,
  } = useSettingsStore();
  const connected = useSignalStore((s) => s.connected);
  const [pushStatus, setPushStatus] = useState<"idle" | "subscribing" | "error">("idle");
  const [showBacktest, setShowBacktest] = useState(false);

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

  if (showBacktest) {
    return <BacktestView onBack={() => setShowBacktest(false)} />;
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
      {/* BACKTESTER */}
      <div>
        <h2 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">Tools</h2>
        <button
          onClick={() => setShowBacktest(true)}
          className="w-full bg-card rounded-lg border border-border px-3 py-3 flex items-center justify-between hover:bg-card-hover transition-colors"
        >
          <div>
            <span className="text-sm font-medium">Backtester</span>
            <p className="text-[10px] text-dim mt-0.5">Test strategies against historical data</p>
          </div>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted">
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>
      </div>

      {/* TRADING */}
      <SettingsGroup title="Trading">
        {/* Pairs */}
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[10px] text-dim uppercase tracking-wider mb-2">Pairs</div>
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
          <div className="text-[10px] text-dim uppercase tracking-wider mb-2">Timeframes</div>
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
        <div className="px-3 py-3">
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
          <div className="flex justify-between text-[10px] text-dim mt-0.5">
            <span>All</span>
            <span>Strong only</span>
          </div>
        </div>
      </SettingsGroup>

      {/* NOTIFICATIONS */}
      <SettingsGroup title="Notifications">
        <div className="px-3 py-3 flex items-center justify-between">
          <div>
            <span className="text-sm">Push Notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-short mt-0.5">Permission denied</p>
            )}
          </div>
          <input
            type="checkbox"
            checked={notificationsEnabled}
            disabled={pushStatus === "subscribing"}
            onChange={(e) => handleNotificationToggle(e.target.checked)}
            className="accent-accent w-4 h-4"
          />
        </div>
      </SettingsGroup>

      {/* CONNECTION */}
      <SettingsGroup title="Connection">
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[10px] text-dim uppercase tracking-wider mb-2">API URL</div>
          <input
            type="url"
            value={apiBaseUrl}
            onChange={(e) => setApiBaseUrl(e.target.value)}
            className="w-full p-2.5 bg-card-hover rounded-lg border border-border text-sm font-mono focus:border-accent/50 focus:outline-none"
          />
        </div>
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm">Status</span>
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${connected ? "bg-long" : "bg-short animate-pulse"}`} />
            <span className="text-sm text-muted">{connected ? "Connected" : "Disconnected"}</span>
          </div>
        </div>
      </SettingsGroup>

      {/* DATA SOURCES */}
      <DataSourcesSection />

      {/* RISK MANAGEMENT */}
      <RiskManagementSection />

      {/* ABOUT */}
      <SettingsGroup title="About">
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm">Version</span>
          <span className="text-sm text-muted font-mono">1.0.0</span>
        </div>
      </SettingsGroup>
    </div>
  );
}

function DataSourcesSection() {
  const {
    onchainEnabled, newsAlertsEnabled, newsContextWindow,
    setOnchainEnabled, setNewsAlertsEnabled, setNewsContextWindow,
  } = useSettingsStore();

  return (
    <SettingsGroup title="Data Sources">
      <div className="px-3 py-3 border-b border-border flex items-center justify-between">
        <div>
          <span className="text-sm">On-Chain Scoring</span>
          <p className="text-[10px] text-dim mt-0.5">Blend exchange flows and whale metrics into signals</p>
        </div>
        <input
          type="checkbox"
          checked={onchainEnabled}
          onChange={(e) => setOnchainEnabled(e.target.checked)}
          className="accent-accent w-4 h-4"
        />
      </div>
      <div className="px-3 py-3 border-b border-border flex items-center justify-between">
        <div>
          <span className="text-sm">News Alerts</span>
          <p className="text-[10px] text-dim mt-0.5">Push notifications for high-impact news</p>
        </div>
        <input
          type="checkbox"
          checked={newsAlertsEnabled}
          onChange={(e) => setNewsAlertsEnabled(e.target.checked)}
          className="accent-accent w-4 h-4"
        />
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
        <h2 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">Risk Management</h2>
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

function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">{title}</h2>
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        {children}
      </div>
    </div>
  );
}
