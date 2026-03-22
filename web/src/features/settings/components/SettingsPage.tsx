import { useState } from "react";
import { useSettingsStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import type { Timeframe } from "../../signals/types";
import { QuietHoursSettings } from "../../alerts/components/QuietHoursSettings";
import { Toggle } from "../../../shared/components/Toggle";
import { hapticTap } from "../../../shared/lib/haptics";

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
    <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">
      <h3 className="font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant mb-3">
        {title}
      </h3>
      {children}
    </section>
  );
}

/* ── Unified pill button row ── */

function PillSelect<T extends string | number>({
  options,
  selected,
  onToggle,
  multi = false,
  renderLabel,
}: {
  options: readonly T[];
  selected: T | readonly T[];
  onToggle: (value: T) => void;
  multi?: boolean;
  renderLabel?: (value: T) => string;
}) {
  const isActive = (v: T) =>
    multi ? (selected as readonly T[]).includes(v) : selected === v;

  return (
    <div className="flex gap-3">
      {options.map((opt) => (
        <button
          key={String(opt)}
          onClick={() => { hapticTap(); onToggle(opt); }}
          className={`flex-1 min-h-[44px] py-2 text-sm font-medium rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
            isActive(opt)
              ? "bg-primary/15 text-primary border border-primary/30 font-bold"
              : "bg-surface-container-lowest text-on-surface-variant"
          }`}
        >
          {renderLabel ? renderLabel(opt) : String(opt)}
        </button>
      ))}
    </div>
  );
}

/* ── Section label ── */

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[10px] font-bold text-primary uppercase tracking-widest opacity-80 px-1 mb-2">
      {children}
    </h2>
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
        <div className="h-28 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        <div className="h-20 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        <div className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
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
      <SectionLabel>Trading</SectionLabel>

      <SettingsCard title="Pairs">
        <PillSelect
          options={AVAILABLE_PAIRS}
          selected={pairs}
          onToggle={(pair) => setPairs(toggleItem(pairs, pair))}
          multi
          renderLabel={(pair) => pair.replace("-USDT-SWAP", "")}
        />
      </SettingsCard>

      <SettingsCard title="Timeframes">
        <PillSelect
          options={TIMEFRAMES}
          selected={timeframes}
          onToggle={(tf) => setTimeframes(toggleItem(timeframes, tf))}
          multi
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
          renderLabel={(mins) => `${mins}m`}
        />
      </SettingsCard>

      {/* ── Notifications ── */}
      <SectionLabel>Notifications</SectionLabel>

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

      <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">
        <QuietHoursSettings />
      </section>
    </div>
  );
}
