import { useState, useEffect, useMemo } from "react";
import { useAlertStore } from "../store";
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
      <label className="flex items-center justify-between min-h-[44px]">
        <span className="text-sm">Quiet Hours</span>
        <input
          type="checkbox"
          checked={settings.quiet_hours_enabled}
          onChange={(e) => update({ quiet_hours_enabled: e.target.checked })}
          className="w-5 h-5"
          disabled={saving}
        />
      </label>

      {settings.quiet_hours_enabled && (
        <>
          <div className="flex gap-3">
            <label className="flex-1">
              <span className="text-xs text-muted">Start</span>
              <input
                type="time"
                value={settings.quiet_hours_start}
                onChange={(e) => update({ quiet_hours_start: e.target.value })}
                className="w-full bg-card border border-border rounded-lg p-2 text-sm min-h-[44px]"
              />
            </label>
            <label className="flex-1">
              <span className="text-xs text-muted">End</span>
              <input
                type="time"
                value={settings.quiet_hours_end}
                onChange={(e) => update({ quiet_hours_end: e.target.value })}
                className="w-full bg-card border border-border rounded-lg p-2 text-sm min-h-[44px]"
              />
            </label>
          </div>
          <label>
            <span className="text-xs text-muted">Timezone</span>
            <select
              value={settings.quiet_hours_tz}
              onChange={(e) => update({ quiet_hours_tz: e.target.value })}
              className="w-full bg-card border border-border rounded-lg p-2 text-sm min-h-[44px]"
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
