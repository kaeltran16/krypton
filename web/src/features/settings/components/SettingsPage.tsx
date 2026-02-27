import { useState } from "react";
import { useSettingsStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

function toggleItem<T>(list: T[], item: T, minOne = true): T[] {
  if (list.includes(item)) {
    if (minOne && list.length <= 1) return list;
    return list.filter((i) => i !== item);
  }
  return [...list, item];
}

export function SettingsPage() {
  const {
    pairs,
    timeframes,
    threshold,
    notificationsEnabled,
    apiBaseUrl,
    setPairs,
    setTimeframes,
    setThreshold,
    setNotificationsEnabled,
    setApiBaseUrl,
  } = useSettingsStore();

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
    <div className="p-4 space-y-6">
      <h1 className="text-xl font-bold">Settings</h1>

      <section>
        <h2 className="text-sm text-gray-400 mb-2">Trading Pairs</h2>
        <div className="space-y-2">
          {AVAILABLE_PAIRS.map((pair) => (
            <label
              key={pair}
              className="flex items-center gap-3 p-3 bg-card rounded-lg cursor-pointer"
            >
              <input
                type="checkbox"
                checked={pairs.includes(pair)}
                onChange={() => setPairs(toggleItem(pairs, pair))}
                className="accent-long w-4 h-4"
              />
              <span>{pair}</span>
            </label>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-sm text-gray-400 mb-2">Timeframes</h2>
        <div className="flex gap-2">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframes(toggleItem(timeframes, tf))}
              className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                timeframes.includes(tf)
                  ? "bg-long/20 text-long border border-long/30"
                  : "bg-card text-gray-400 border border-gray-800"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-sm text-gray-400 mb-2">
          Alert Threshold: <span className="text-white font-mono">{threshold}</span>
        </h2>
        <input
          type="range"
          min={0}
          max={100}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          className="w-full accent-long"
        />
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>All signals</span>
          <span>Strong only</span>
        </div>
      </section>

      <section>
        <label className="flex items-center justify-between p-3 bg-card rounded-lg cursor-pointer">
          <div>
            <span>Push Notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-short mt-1">Permission denied or not supported</p>
            )}
          </div>
          <input
            type="checkbox"
            checked={notificationsEnabled}
            disabled={pushStatus === "subscribing"}
            onChange={(e) => handleNotificationToggle(e.target.checked)}
            className="accent-long w-4 h-4"
          />
        </label>
      </section>

      <section>
        <h2 className="text-sm text-gray-400 mb-2">API Base URL</h2>
        <input
          type="url"
          value={apiBaseUrl}
          onChange={(e) => setApiBaseUrl(e.target.value)}
          className="w-full p-3 bg-card rounded-lg border border-gray-800 text-sm font-mono focus:border-long/50 focus:outline-none"
        />
      </section>
    </div>
  );
}
