import { useState, useEffect, useMemo } from "react";
import { useAlertStore } from "../store";
import { Toggle } from "../../../shared/components/Toggle";
import { api } from "../../../shared/lib/api";

export function QuietHoursSettings() {
  const settings = useAlertStore((s) => s.settings);
  const fetchSettings = useAlertStore((s) => s.fetchSettings);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const timezones = useMemo(
    () => Intl.supportedValuesOf("timeZone").filter(tz =>
      ["America/", "Europe/", "Asia/", "Pacific/", "UTC"].some(p => tz.startsWith(p))
    ),
    [],
  );

  if (!settings) return null;

  async function update(patch: Record<string, unknown>) {
    setSaving(true);
    try {
      const updated = await api.updateAlertSettings(patch as any);
      useAlertStore.setState({ settings: updated });
    } catch {}
    setSaving(false);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between min-h-[44px]">
        <span className="text-sm text-on-surface">Quiet Hours</span>
        <Toggle checked={settings.quiet_hours_enabled} onChange={(v) => update({ quiet_hours_enabled: v })} disabled={saving} />
      </div>

      {settings.quiet_hours_enabled && (
        <>
          <div className="flex gap-3">
            <label className="flex-1">
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Start</span>
              <input
                type="time"
                value={settings.quiet_hours_start}
                onChange={(e) => update({ quiet_hours_start: e.target.value })}
                className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm min-h-[44px] focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
              />
            </label>
            <label className="flex-1">
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">End</span>
              <input
                type="time"
                value={settings.quiet_hours_end}
                onChange={(e) => update({ quiet_hours_end: e.target.value })}
                className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm min-h-[44px] focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
              />
            </label>
          </div>
          <label>
            <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Timezone</span>
            <select
              value={settings.quiet_hours_tz}
              onChange={(e) => update({ quiet_hours_tz: e.target.value })}
              className="w-full bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm min-h-[44px] focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
            >
              {timezones.map((tz) => (
                <option key={tz} value={tz}>{tz}</option>
              ))}
            </select>
          </label>
        </>
      )}
    </div>
  );
}
