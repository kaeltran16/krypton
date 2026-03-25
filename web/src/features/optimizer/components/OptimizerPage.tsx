import { useEffect, useState } from "react";
import { RefreshCw, Info } from "lucide-react";
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
  const [showGuide, setShowGuide] = useState(false);

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

  const hasActivity = pendingProposals.length > 0 || status.active_shadow;

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
                Profit Factor{" "}
                {status.global_profit_factor === Infinity
                  ? "\u221E"
                  : status.global_profit_factor.toFixed(2)}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            icon={<Info size={16} />}
            onClick={() => setShowGuide((v) => !v)}
            aria-label="How it works"
          />
          <Button
            variant="ghost"
            icon={<RefreshCw size={16} className={loading ? "animate-spin" : ""} />}
            onClick={() => { fetchStatus(); fetchProposals(); }}
            aria-label="Refresh"
          />
        </div>
      </div>

      {/* How it works guide */}
      {showGuide && (
        <div className="border border-primary/20 rounded-xl bg-surface-container-low p-3 space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest text-primary">
            How it works
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-muted flex-wrap">
            <span className="px-1.5 py-0.5 rounded bg-accent/15 text-accent">Propose</span>
            <span>{">"}</span>
            <span className="px-1.5 py-0.5 rounded bg-long/15 text-long">Approve</span>
            <span>{">"}</span>
            <span className="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400">Shadow Test</span>
            <span>{">"}</span>
            <span className="px-1.5 py-0.5 rounded bg-long/15 text-long">Promote Live</span>
          </div>
          <p className="text-[11px] text-muted leading-relaxed">
            The engine detects underperforming parameters and proposes changes backed by backtests.
            <strong className="text-on-surface"> Approve</strong> starts shadow testing against live signals.
            <strong className="text-on-surface"> Promote</strong> applies changes to the live engine.
            You can <strong className="text-on-surface">Rollback</strong> any promoted change.
          </p>
        </div>
      )}

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
      {pendingProposals.length > 0 && (
        <div className="text-[10px] font-bold uppercase tracking-widest text-primary">
          Pending Review
        </div>
      )}
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

      {/* Empty state */}
      {!hasActivity && (
        <div className="flex flex-col items-center py-8 text-center">
          <div className="text-muted text-sm">No pending proposals</div>
          <p className="text-[11px] text-muted/60 mt-1 max-w-[240px]">
            The optimizer will propose parameter changes when it detects room for improvement.
          </p>
        </div>
      )}

      {/* Group health */}
      <GroupHealthTable groups={status.groups} />

      {/* History */}
      <ProposalHistory proposals={proposals} />
    </div>
  );
}
