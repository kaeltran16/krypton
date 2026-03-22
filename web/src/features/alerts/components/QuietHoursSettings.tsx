import { useState, useEffect, useMemo } from "react";
import { useAlertStore } from "../store";
import { Toggle } from "../../../shared/components/Toggle";
import { Dropdown } from "../../../shared/components/Dropdown";
import { api } from "../../../shared/lib/api";

const inputCls = "w-full bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm min-h-[44px] focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none";

export function QuietHoursSettings() {
  const settings = useAlertStore((s) => s.settings);
  const fetchSettings = useAlertStore((s) => s.fetchSettings);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const timezoneOptions = useMemo(
    () => Intl.supportedValuesOf("timeZone")
      .filter(tz => ["America/", "Europe/", "Asia/", "Pacific/", "UTC"].some(p => tz.startsWith(p)))
      .map(tz => ({ value: tz, label: tz })),
    [],
  );

  if (!settings) return null;

  async function update(patch: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateAlertSettings(patch as any);
      useAlertStore.setState({ settings: updated });
    } catch {
      setError("Failed to save settings");
    }
    setSaving(false);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between min-h-[44px]">
        <span className="font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">Quiet Hours</span>
        <Toggle checked={settings.quiet_hours_enabled} onChange={(v) => update({ quiet_hours_enabled: v })} disabled={saving} />
      </div>

      {error && (
        <p className="text-error text-xs bg-error/10 rounded-lg p-2">{error}</p>
      )}

      {settings.quiet_hours_enabled && (
        <>
          <div className="flex gap-3">
            <label className="flex-1">
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Start</span>
              <input
                type="time"
                value={settings.quiet_hours_start}
                onChange={(e) => update({ quiet_hours_start: e.target.value })}
                className={inputCls}
              />
            </label>
            <label className="flex-1">
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">End</span>
              <input
                type="time"
                value={settings.quiet_hours_end}
                onChange={(e) => update({ quiet_hours_end: e.target.value })}
                className={inputCls}
              />
            </label>
          </div>
          <div>
            <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Timezone</span>
            <Dropdown
              value={settings.quiet_hours_tz}
              onChange={(v) => update({ quiet_hours_tz: v })}
              options={timezoneOptions}
              ariaLabel="Select timezone"
            />
          </div>
        </>
      )}
    </div>
  );
}
