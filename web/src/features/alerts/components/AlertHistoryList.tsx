import { useEffect } from "react";
import { useAlertStore } from "../store";
import { CheckCircle, XCircle, Clock } from "lucide-react";
import { Skeleton } from "../../../shared/components/Skeleton";

const STATUS_STYLES: Record<string, string> = {
  delivered: "text-tertiary-dim",
  failed: "text-error",
  silenced_by_cooldown: "text-on-surface-variant",
  silenced_by_quiet_hours: "text-on-surface-variant",
};

const STATUS_ICON: Record<string, typeof CheckCircle> = {
  delivered: CheckCircle,
  failed: XCircle,
  silenced_by_cooldown: Clock,
  silenced_by_quiet_hours: Clock,
};

function getDateLabel(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const entryDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  if (entryDate.getTime() === today.getTime()) return "Today";
  if (entryDate.getTime() === yesterday.getTime()) return "Yesterday";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function AlertHistoryList() {
  const { history, historyLoading, fetchHistory } = useAlertStore();

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (historyLoading) {
    return (
      <div className="space-y-2">
        <Skeleton count={4} height="h-14" />
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div className="text-center py-12 text-on-surface-variant">
        <p className="text-lg mb-2">No alerts triggered yet</p>
        <p className="text-sm">Alert history will appear here</p>
      </div>
    );
  }

  // Group by date
  const groups: { label: string; entries: typeof history }[] = [];
  let currentLabel = "";
  for (const h of history) {
    const dl = getDateLabel(h.triggered_at);
    if (dl !== currentLabel) {
      currentLabel = dl;
      groups.push({ label: dl, entries: [] });
    }
    groups[groups.length - 1].entries.push(h);
  }

  return (
    <div className="bg-surface-container-lowest border border-outline-variant/20 rounded overflow-hidden">
      {/* Terminal header */}
      <div className="p-3 bg-surface-container flex items-center gap-2">
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-error/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-tertiary-dim/40" />
          <div className="w-2.5 h-2.5 rounded-full bg-primary/40" />
        </div>
        <span className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider ml-2">Terminal Alert Log</span>
      </div>

      {/* Log entries grouped by date */}
      <div className="p-4 space-y-4">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1.5">{group.label}</div>
            <div className="space-y-2.5">
              {group.entries.map((h) => {
                const Icon = STATUS_ICON[h.delivery_status] ?? Clock;
                return (
                  <div key={h.id} className="font-mono text-[11px] leading-relaxed">
                    {/* Desktop: single row */}
                    <div className="hidden sm:flex items-center gap-2">
                      <span className="text-on-surface-variant flex-shrink-0">
                        {new Date(h.triggered_at).toLocaleTimeString()}
                      </span>
                      <span className={`font-bold uppercase flex-shrink-0 ${STATUS_STYLES[h.delivery_status] ?? "text-on-surface-variant"}`}>
                        {h.delivery_status.replace(/_/g, " ")}
                      </span>
                      <span className="text-on-surface truncate">{h.alert_label ?? "Deleted alert"}</span>
                      <span className="text-on-surface-variant tabular-nums flex-shrink-0 ml-auto">val={h.trigger_value.toLocaleString()}</span>
                      <Icon size={12} className={`flex-shrink-0 ${STATUS_STYLES[h.delivery_status] ?? "text-on-surface-variant"}`} />
                    </div>
                    {/* Mobile: stacked */}
                    <div className="sm:hidden flex items-start gap-2">
                      <Icon size={12} className={`flex-shrink-0 mt-0.5 ${STATUS_STYLES[h.delivery_status] ?? "text-on-surface-variant"}`} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-on-surface truncate">{h.alert_label ?? "Deleted alert"}</span>
                          <span className="text-on-surface-variant tabular-nums flex-shrink-0">
                            {h.trigger_value.toLocaleString()}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className={`font-bold uppercase ${STATUS_STYLES[h.delivery_status] ?? "text-on-surface-variant"}`}>
                            {h.delivery_status.replace(/_/g, " ")}
                          </span>
                          <span className="text-on-surface-variant">
                            {new Date(h.triggered_at).toLocaleTimeString()}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
