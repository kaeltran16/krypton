import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useOptimizerStore } from "../store";
import { useEngineStore } from "../../engine/store";
import { Button } from "../../../shared/components/Button";
import GroupHealthTable from "./GroupHealthTable";
import ProposalCard from "./ProposalCard";
import ShadowProgress from "./ShadowProgress";
import ProposalHistory from "./ProposalHistory";

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-surface-container rounded ${className}`} />;
}

function OptimizerSkeleton() {
  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-3 w-36" />
        </div>
        <Skeleton className="h-8 w-8 rounded-full" />
      </div>
      {[1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className="h-10 w-full rounded-lg" />
      ))}
    </div>
  );
}

export default function OptimizerPage() {
  const {
    status, proposals, loading, actionLoading, error,
    fetchStatus, fetchProposals,
    approve, reject, promote, rollback,
  } = useOptimizerStore();
  const { params, fetch: fetchEngine } = useEngineStore();
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    fetchStatus();
    fetchProposals();
    fetchEngine();
  }, [fetchStatus, fetchProposals, fetchEngine]);

  const descriptions = params?.descriptions;
  const pendingProposals = proposals.filter((p) => p.status === "pending");

  const withErrorHandling = (fn: (id: number) => Promise<void>) => async (id: number) => {
    setActionError(null);
    try {
      await fn(id);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  if (loading && !status) return <OptimizerSkeleton />;
  if (error) {
    return <div className="p-4 text-error text-sm">Error: {error}</div>;
  }
  if (!status) return null;

  return (
    <div className="p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-on-surface">Optimizer</h3>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-[10px] text-muted">
              {status.resolved_count} signals resolved
            </span>
            {status.global_profit_factor != null && (
              <span className="text-xs font-mono text-on-surface">
                PF {status.global_profit_factor === Infinity
                  ? "\u221E"
                  : status.global_profit_factor.toFixed(2)}
              </span>
            )}
          </div>
        </div>
        <Button
          variant="ghost"
          icon={<RefreshCw size={16} className={loading ? "animate-spin" : ""} />}
          onClick={() => { fetchStatus(); fetchProposals(); }}
          aria-label="Refresh"
        />
      </div>

      {/* Action error toast */}
      {actionError && (
        <div className="flex items-center justify-between px-3 py-2 bg-error/10 border border-error/20 rounded-lg">
          <span className="text-xs text-error">{actionError}</span>
          <button onClick={() => setActionError(null)} className="text-error text-xs ml-2">{"\u2715"}</button>
        </div>
      )}

      {/* Shadow progress */}
      {status.active_shadow && (
        <ShadowProgress
          group={status.active_shadow.group}
          progress={status.active_shadow.progress}
          changes={status.active_shadow.changes}
        />
      )}

      {/* Pending proposals */}
      {pendingProposals.map((p) => (
        <ProposalCard
          key={p.id}
          proposal={p}
          descriptions={descriptions}
          actionLoading={actionLoading}
          onApprove={withErrorHandling(approve)}
          onReject={withErrorHandling(reject)}
          onPromote={withErrorHandling(promote)}
          onRollback={withErrorHandling(rollback)}
        />
      ))}

      {/* Group health */}
      <GroupHealthTable groups={status.groups} />

      {/* History */}
      <ProposalHistory proposals={proposals} />
    </div>
  );
}
