import { Check, AlertTriangle, XCircle } from "lucide-react";
import type { GroupHealth } from "../types";

const STATUS_CONFIG: Record<string, { bg: string; icon: typeof Check; label: string }> = {
  green: { bg: "bg-long", icon: Check, label: "Healthy" },
  yellow: { bg: "bg-accent", icon: AlertTriangle, label: "Needs eval" },
  red: { bg: "bg-error", icon: XCircle, label: "Degraded" },
};

interface Props {
  groups: GroupHealth[];
}

export default function GroupHealthTable({ groups }: Props) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-bold uppercase tracking-widest text-primary mb-2">
        Parameter Groups
      </div>
      {groups.map((g) => {
        const cfg = STATUS_CONFIG[g.status] || STATUS_CONFIG.green;
        const Icon = cfg.icon;
        return (
          <div
            key={g.group}
            className="flex items-center justify-between px-3 py-2 bg-surface-container rounded-lg"
          >
            <div className="flex items-center gap-2">
              <Icon size={12} className={g.status === "green" ? "text-long" : g.status === "yellow" ? "text-accent" : "text-error"} aria-label={cfg.label} />
              <span className="text-xs text-on-surface">{g.group.replace(/_/g, " ")}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-muted">
                {g.signals_since_last_opt} signals ago
              </span>
              {g.profit_factor != null && (
                <span className="text-xs font-mono text-on-surface">
                  PF {g.profit_factor === Infinity ? "\u221E" : g.profit_factor.toFixed(2)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
