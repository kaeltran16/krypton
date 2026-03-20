import { useState } from "react";
import { useSettingsStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import { useSignalStore } from "../../signals/store";
import type { Timeframe } from "../../signals/types";
import { QuietHoursSettings } from "../../alerts/components/QuietHoursSettings";
import { SettingsGroup } from "./SettingsGroup";
import { Toggle } from "../../../shared/components/Toggle";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

const PAIR_NAMES: Record<string, string> = {
  "BTC-USDT-SWAP": "Bitcoin",
  "ETH-USDT-SWAP": "Ethereum",
  "WIF-USDT-SWAP": "dogwifhat",
};

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
        <div className="h-32 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        <div className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        <div className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-4">
      {syncError && (
        <div className="bg-error/10 border border-error/30 rounded-lg px-3 py-2 text-xs text-error">
          Settings sync failed — changes may not be saved
        </div>
      )}

      {/* TRADING */}
      <SettingsGroup title="Trading">
        <div className="px-3 py-3 border-b border-outline-variant/10">
          <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">Pairs</div>
          <div className="grid grid-cols-3 gap-2">
            {AVAILABLE_PAIRS.map((pair) => (
              <button
                key={pair}
                onClick={() => setPairs(toggleItem(pairs, pair))}
                className={`py-3 rounded-lg text-center transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                  pairs.includes(pair)
                    ? "bg-surface-container-highest border-b-2 border-primary"
                    : "bg-surface-container-highest"
                }`}
              >
                <span className="block font-headline font-bold text-sm">{pair.replace("-USDT-SWAP", "")}</span>
                <span className="block text-[10px] text-on-surface-variant">{PAIR_NAMES[pair] ?? pair}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="px-3 py-3 border-b border-outline-variant/10">
          <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">Timeframes</div>
          <div className="flex gap-1.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframes(toggleItem(timeframes, tf))}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                  timeframes.includes(tf)
                    ? "bg-surface-container-highest text-primary border border-primary/20"
                    : "bg-surface-container-lowest text-on-surface-variant"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        <div className="px-3 py-3 border-b border-outline-variant/10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-on-surface">Signal Threshold</span>
            <span className="font-headline font-bold text-lg tabular-nums text-primary">{threshold}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full accent-primary"
          />
          <div className="flex justify-between text-[10px] font-mono text-outline mt-0.5">
            <span>0</span>
            <span>100</span>
          </div>
        </div>

        <div className="px-3 py-3 border-b border-outline-variant/10 flex items-center justify-between">
          <div>
            <span className="text-sm text-on-surface">On-Chain Scoring</span>
            <p className="text-[10px] text-on-surface-variant mt-0.5">Blend exchange flows and whale metrics</p>
          </div>
          <Toggle checked={onchainEnabled} onChange={setOnchainEnabled} />
        </div>

        <div className="px-3 py-3 border-b border-outline-variant/10 flex items-center justify-between">
          <div>
            <span className="text-sm text-on-surface">News Alerts</span>
            <p className="text-[10px] text-on-surface-variant mt-0.5">Push for high-impact news</p>
          </div>
          <Toggle checked={newsAlertsEnabled} onChange={setNewsAlertsEnabled} />
        </div>

        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm text-on-surface">LLM News Window</span>
          <div className="bg-surface-container-lowest p-1 flex gap-1 rounded-lg">
            {[15, 30, 60].map((mins) => (
              <button
                key={mins}
                onClick={() => setNewsContextWindow(mins)}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                  newsContextWindow === mins
                    ? "bg-surface-container-high text-primary border border-primary/20"
                    : "text-on-surface-variant"
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
        <div className="px-3 py-3 border-b border-outline-variant/10 flex items-center justify-between">
          <div>
            <span className="text-sm text-on-surface">Push Notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-error mt-0.5">Permission denied</p>
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
        <div className="px-3 py-3 border-b border-outline-variant/10">
          <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">API Endpoint</div>
          <div className="bg-surface-container p-4 rounded-lg">
            <input
              type="url"
              value={apiBaseUrl}
              onChange={(e) => setApiBaseUrl(e.target.value)}
              className="w-full bg-surface-container-lowest px-3 py-2 rounded text-[11px] font-mono text-on-surface border border-outline-variant/20 focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
            />
            <div className="flex items-center gap-2 mt-2">
              <div className={`w-2 h-2 rounded-full ${connected ? "bg-tertiary-dim" : "bg-error animate-pulse motion-reduce:animate-none"}`} />
              <span className="text-[10px] font-mono text-outline">{connected ? "Connected" : "Disconnected"}</span>
            </div>
            <div className="flex gap-4 mt-1">
              <span className="text-[10px] font-mono text-outline">Latency: —</span>
              <span className="text-[10px] font-mono text-outline">SSL: Active</span>
            </div>
          </div>
        </div>
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm text-on-surface">Version</span>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-tertiary-dim" />
            <span className="text-sm text-on-surface-variant font-mono">1.0.0</span>
            <span className="text-[10px] text-on-surface-variant">System Operational</span>
          </div>
        </div>
      </SettingsGroup>
    </div>
  );
}

