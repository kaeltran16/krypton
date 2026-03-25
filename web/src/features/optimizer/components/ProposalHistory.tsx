import { useState } from "react";
import type { Proposal } from "../types";
import { humanizeKey } from "../../../shared/lib/format";

interface Props {
  proposals: Proposal[];
}

export default function ProposalHistory({ proposals }: Props) {
  const [expanded, setExpanded] = useState(false);
  const resolved = proposals.filter((p) =>
    ["promoted", "rejected", "rolled_back"].includes(p.status)
  );
  if (resolved.length === 0) return null;

  const shown = expanded ? resolved : resolved.slice(0, 5);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between py-2 text-xs text-muted"
        aria-expanded={expanded}
        aria-label="Toggle proposal history"
      >
        <span className="uppercase tracking-wider font-bold text-[10px]">History</span>
        <span>{expanded ? "\u2212" : "+"}</span>
      </button>
      {(expanded || resolved.length <= 5) && (
        <div className="space-y-1">
          {shown.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between px-2 py-1.5 text-xs bg-surface-container/50 rounded"
            >
              <div className="flex items-center gap-2">
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${
                  p.status === "promoted" ? "bg-long/15 text-long" :
                  p.status === "rejected" || p.status === "rolled_back" ? "bg-error/15 text-error" :
                  "bg-accent/15 text-accent"
                }`}>
                  {p.status === "rolled_back" ? "rolled back" : p.status}
                </span>
                <span className="text-muted">{humanizeKey(p.parameter_group)}</span>
              </div>
              <span className="text-[10px] text-muted">
                {p.promoted_at
                  ? new Date(p.promoted_at).toLocaleDateString()
                  : p.created_at
                    ? new Date(p.created_at).toLocaleDateString()
                    : ""}
              </span>
            </div>
          ))}
          {!expanded && resolved.length > 5 && (
            <button
              onClick={() => setExpanded(true)}
              className="w-full text-center text-[10px] text-primary py-1"
            >
              Show {resolved.length - 5} more
            </button>
          )}
        </div>
      )}
    </div>
  );
}
