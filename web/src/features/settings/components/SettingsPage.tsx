import { useState } from "react";
import { useSettingsStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import { useSignalStore } from "../../signals/store";
import type { Timeframe } from "../../signals/types";
import { QuietHoursSettings } from "../../alerts/components/QuietHoursSettings";
import { SettingsGroup } from "./SettingsGroup";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

function toggleItem<T>(list: T[], item: T, minOne = true): T[] {
  if (list.includes(item)) {
    if (minOne && list.length <= 1) return list;
    return list.filter((i) => i !== item);
  }
  return [...list, item];
}

export default function SettingsPage() {
  const {
    pairs, timeframes, threshold, notificationsEnabled, apiBaseUrl,
    onchainEnabled, newsAlertsEnabled, newsContextWindow,
    loading, syncError,
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled, setApiBaseUrl,
    setOnchainEnabled, setNewsAlertsEnabled, setNewsContextWindow,
  } = useSettingsStore();
  const connected = useSignalStore((s) => s.connected);
  const [pushStatus, setPushStatus] = useState<"idle" | "subscribing" | "error">("idle");

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

      {/* TRADING */}
      <SettingsGroup title="Trading">
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

        <div className="px-3 py-3 border-b border-border flex items-center justify-between">
          <div>
            <span className="text-sm">On-Chain Scoring</span>
            <p className="text-[11px] text-dim mt-0.5">Blend exchange flows and whale metrics</p>
          </div>
          <Toggle checked={onchainEnabled} onChange={setOnchainEnabled} />
        </div>

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

      {/* SYSTEM */}
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

