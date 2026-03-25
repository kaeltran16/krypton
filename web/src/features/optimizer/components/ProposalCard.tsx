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

const PIPELINE_STEPS = ["pending", "shadow", "promoted"] as const;
const PIPELINE_LABELS: Record<string, string> = {
  pending: "Review",
  shadow: "Shadow",
  promoted: "Live",
};

function StatusPipeline({ status }: { status: string }) {
  const isFailed = status === "rejected" || status === "rolled_back";
  const activeIdx = PIPELINE_STEPS.indexOf(status as typeof PIPELINE_STEPS[number]);

  return (
    <div className="flex items-center gap-1">
      {PIPELINE_STEPS.map((step, i) => {
        const isActive = step === status;
        const isPast = activeIdx > i;
        const isFutureOfFailed = isFailed && i > 0;
        return (
          <div key={step} className="flex items-center gap-1">
            {i > 0 && (
              <div className={`w-3 h-px ${isPast ? "bg-long" : "bg-surface-container"}`} />
            )}
            <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${
              isActive
                ? STATUS_STYLE[status] || "bg-dim/15 text-muted"
                : isPast
                  ? "bg-long/15 text-long"
                  : isFutureOfFailed
                    ? "bg-surface-container text-muted/40"
                    : "bg-surface-container text-muted"
            }`}>
              {PIPELINE_LABELS[step]}
            </span>
          </div>
        );
      })}
      {isFailed && (
        <>
          <div className="w-3 h-px bg-error/30" />
          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-error/15 text-error">
            {status === "rejected" ? "Rejected" : "Rolled Back"}
          </span>
        </>
      )}
    </div>
  );
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
        </div>
        {p.created_at && (
          <span className="text-[10px] text-muted">
            {new Date(p.created_at).toLocaleDateString()}
          </span>
        )}
      </div>
      <StatusPipeline status={p.status} />

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
      <div className="space-y-1">
        <div className="text-[10px] text-muted">Backtest Results</div>
        <div className="flex flex-wrap gap-2">
          {[
            {
              label: "Profit Factor",
              value: bm.profit_factor.toFixed(2),
              color: bm.profit_factor >= 1.5 ? "text-long" : bm.profit_factor >= 1.0 ? "text-on-surface" : "text-short",
            },
            {
              label: "Win Rate",
              value: `${(bm.win_rate * 100).toFixed(0)}%`,
              color: bm.win_rate >= 0.55 ? "text-long" : bm.win_rate >= 0.45 ? "text-on-surface" : "text-short",
            },
            {
              label: "Risk:Reward",
              value: bm.avg_rr.toFixed(2),
              color: bm.avg_rr >= 1.5 ? "text-long" : bm.avg_rr >= 1.0 ? "text-on-surface" : "text-short",
            },
            {
              label: "Max DD",
              value: `${(bm.drawdown * 100).toFixed(1)}%`,
              color: bm.drawdown <= 0.1 ? "text-long" : bm.drawdown <= 0.2 ? "text-on-surface" : "text-short",
            },
            {
              label: "Signals",
              value: String(bm.signals_tested),
              color: "text-on-surface",
            },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-surface-container rounded px-2 py-1">
              <span className="text-[10px] text-muted">{label}</span>
              <span className={`ml-1 text-xs font-mono ${color}`}>{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="space-y-1.5">
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
                Promote Live
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
        {p.status === "pending" && (
          <div className="text-[10px] text-muted text-center">
            Approve starts shadow testing against live signals
          </div>
        )}
        {p.status === "shadow" && (
          <div className="text-[10px] text-muted text-center">
            Promote applies these parameters to the live engine
          </div>
        )}
        {p.status === "promoted" && (
          <div className="text-[10px] text-muted text-center">
            Rollback reverts to previous parameter values
          </div>
        )}
      </div>
    </div>
  );
}
