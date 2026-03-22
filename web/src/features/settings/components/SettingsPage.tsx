import { useState } from "react";
import { useSettingsStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import type { Timeframe } from "../../signals/types";
import { QuietHoursSettings } from "../../alerts/components/QuietHoursSettings";
import { Toggle } from "../../../shared/components/Toggle";
import { formatPair } from "../../../shared/lib/format";
import { PillSelect } from "../../../shared/components/PillSelect";
import { SectionLabel } from "../../../shared/components/SectionLabel";
import { Card } from "../../../shared/components/Card";
import { Skeleton } from "../../../shared/components/Skeleton";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

function toggleItem<T>(list: T[], item: T, minOne = true): T[] {
  if (list.includes(item)) {
    if (minOne && list.length <= 1) return list;
    return list.filter((i) => i !== item);
  }
  return [...list, item];
}

/* ── Shared card container (matches RiskSection without status icon) ── */

function SettingsCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card asSection>
      <h3 className="font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant mb-3">
        {title}
      </h3>
      {children}
    </Card>
  );
}



/* ── Main page ── */

export default function SettingsPage() {
  const {
    pairs, timeframes, threshold, notificationsEnabled,
    onchainEnabled, newsAlertsEnabled, newsContextWindow,
    loading, syncError,
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled,
    setOnchainEnabled, setNewsAlertsEnabled, setNewsContextWindow,
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

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        <Skeleton height="h-28" />
        <Skeleton height="h-20" />
        <Skeleton height="h-24" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      {syncError && (
        <div role="alert" className="bg-error/10 border border-error/30 rounded-lg px-3 py-2 text-xs text-error">
          Settings sync failed — changes may not be saved
        </div>
      )}

      {/* ── Trading ── */}
      <SectionLabel as="h2" color="primary">Trading</SectionLabel>

      <SettingsCard title="Pairs">
        <PillSelect
          options={AVAILABLE_PAIRS}
          selected={pairs}
          onToggle={(pair) => setPairs(toggleItem(pairs, pair))}
          multi
          equalWidth
          renderLabel={formatPair}
        />
      </SettingsCard>

      <SettingsCard title="Timeframes">
        <PillSelect
          options={TIMEFRAMES}
          selected={timeframes}
          onToggle={(tf) => setTimeframes(toggleItem(timeframes, tf))}
          multi
          equalWidth
        />
      </SettingsCard>

      <SettingsCard title="Signal Threshold">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-on-surface-variant">Minimum score to trigger a signal</span>
          <span className="font-headline text-2xl font-bold tabular-nums text-primary">{threshold}</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          className="styled-range w-full"
          aria-label="Signal threshold"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={threshold}
        />
        <div className="flex justify-between text-[10px] font-mono text-outline mt-1.5">
          <span>0</span>
          <span>100</span>
        </div>
      </SettingsCard>

      <SettingsCard title="On-Chain Scoring">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[11px] text-on-surface-variant mt-0.5">Blend exchange flows and whale metrics</p>
          </div>
          <Toggle checked={onchainEnabled} onChange={setOnchainEnabled} />
        </div>
      </SettingsCard>

      <SettingsCard title="News Alerts">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[11px] text-on-surface-variant mt-0.5">Push for high-impact news</p>
          </div>
          <Toggle checked={newsAlertsEnabled} onChange={setNewsAlertsEnabled} />
        </div>
      </SettingsCard>

      <SettingsCard title="LLM News Window">
        <PillSelect
          options={[15, 30, 60]}
          selected={newsContextWindow}
          onToggle={(mins) => setNewsContextWindow(mins)}
          equalWidth
          renderLabel={(mins) => `${mins}m`}
        />
      </SettingsCard>

      {/* ── Notifications ── */}
      <SectionLabel as="h2" color="primary">Notifications</SectionLabel>

      <SettingsCard title="Push Notifications">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-sm text-on-surface">Enable push notifications</span>
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
      </SettingsCard>

      <Card asSection>
        <QuietHoursSettings />
      </Card>
    </div>
  );
}
