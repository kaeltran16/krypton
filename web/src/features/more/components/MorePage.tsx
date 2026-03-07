import { useState } from "react";
import { useSettingsStore } from "../../settings/store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import { useSignalStore } from "../../signals/store";
import type { Timeframe } from "../../signals/types";

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
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled, setApiBaseUrl,
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

  return (
    <div className="p-3 space-y-4">
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
