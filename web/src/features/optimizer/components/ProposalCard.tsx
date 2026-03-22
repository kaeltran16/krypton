import { useState } from "react";
import type { Proposal } from "../types";
import ParamInfoPopup from "../../engine/components/ParamInfoPopup";
import { Button } from "../../../shared/components/Button";
import { humanizeKey } from "../../../shared/lib/format";

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-accent/15 text-accent",
  shadow: "bg-blue-500/15 text-blue-400",
  promoted: "bg-long/15 text-long",
  rejected: "bg-error/15 text-error",
  rolled_back: "bg-error/15 text-error",
  approved: "bg-long/15 text-long",
};

interface Props {
  proposal: Proposal;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
  actionLoading?: boolean;
  onApprove?: (id: number) => void;
  onReject?: (id: number) => void;
  onPromote?: (id: number) => void;
  onRollback?: (id: number) => void;
}

export default function ProposalCard({
  proposal,
  descriptions,
  actionLoading,
  onApprove,
  onReject,
  onPromote,
  onRollback,
}: Props) {
  const [confirmAction, setConfirmAction] = useState<"reject" | "rollback" | null>(null);
  const p = proposal;
  const changes = Object.entries(p.changes);
  const bm = p.backtest_metrics;

  const handleReject = () => {
    if (confirmAction === "reject") {
      onReject?.(p.id);
      setConfirmAction(null);
    } else {
      setConfirmAction("reject");
    }
  };

  const handleRollback = () => {
    if (confirmAction === "rollback") {
      onRollback?.(p.id);
      setConfirmAction(null);
    } else {
      setConfirmAction("rollback");
    }
  };

  return (
    <div className="border border-primary/20 rounded-xl bg-surface-container-low p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-medium text-on-surface">
            {humanizeKey(p.parameter_group)}
          </span>
          <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded-full ${
            STATUS_STYLE[p.status] || "bg-dim/15 text-muted"
          }`}>
            {p.status}
          </span>
        </div>
        {p.created_at && (
          <span className="text-[10px] text-muted">
            {new Date(p.created_at).toLocaleDateString()}
          </span>
        )}
      </div>

      {/* Diff table */}
      <div className="space-y-0.5">
        {changes.map(([key, change]) => (
          <div key={key} className="flex items-center justify-between gap-2 px-2 py-1 text-xs">
            <div className="flex items-center gap-1 min-w-0">
              <span className="text-muted truncate">{key}</span>
              <ParamInfoPopup name={key} descriptions={descriptions} />
            </div>
            <div className="flex items-center gap-1 font-mono shrink-0">
              <span className="text-short">{typeof change.current === "number" ? change.current.toFixed(3) : String(change.current ?? "—")}</span>
              <span className="text-muted">{"\u2192"}</span>
              <span className="text-long">{typeof change.proposed === "number" ? change.proposed.toFixed(3) : String(change.proposed)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Backtest metrics */}
      <div className="flex flex-wrap gap-2">
        {[
          { label: "PF", value: bm.profit_factor.toFixed(2) },
          { label: "Win", value: `${(bm.win_rate * 100).toFixed(0)}%` },
          { label: "R:R", value: bm.avg_rr.toFixed(2) },
          { label: "DD", value: `${(bm.drawdown * 100).toFixed(1)}%` },
          { label: "Signals", value: String(bm.signals_tested) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-surface-container rounded px-2 py-1">
            <span className="text-[10px] text-muted">{label}</span>
            <span className="ml-1 text-xs font-mono text-on-surface">{value}</span>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {p.status === "pending" && (
          <>
            <Button
              variant="primary"
              size="sm"
              loading={actionLoading}
              onClick={() => onApprove?.(p.id)}
              className="flex-1"
            >
              Approve
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={actionLoading}
              onClick={handleReject}
              className="flex-1"
            >
              {confirmAction === "reject" ? "Confirm Reject?" : "Reject"}
            </Button>
          </>
        )}
        {p.status === "shadow" && (
          <>
            <Button
              variant="primary"
              size="sm"
              loading={actionLoading}
              onClick={() => onPromote?.(p.id)}
              className="flex-1"
            >
              Promote Early
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={actionLoading}
              onClick={handleReject}
              className="flex-1"
            >
              {confirmAction === "reject" ? "Confirm Reject?" : "Reject"}
            </Button>
          </>
        )}
        {p.status === "promoted" && (
          <Button
            variant="danger"
            size="sm"
            disabled={actionLoading}
            onClick={handleRollback}
            className="flex-1"
          >
            {confirmAction === "rollback" ? "Confirm Rollback?" : "Rollback"}
          </Button>
        )}
      </div>
    </div>
  );
}
