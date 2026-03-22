import { useState } from "react";
import type { MLTrainJob, MLTrainResult } from "../../../shared/lib/api";
import { Button } from "../../../shared/components/Button";
import { formatRelativeTime } from "../../../shared/lib/format";
import { StatusBadge } from "./shared";
import type { MLTrainJobWithMeta } from "../types";
import { Card } from "../../../shared/components/Card";

interface HistoryTabProps {
  history: MLTrainJob[];
  onViewDetails: (jobId: string) => void;
  onRetrain: (jobId: string) => void;
  onDelete: (jobId: string) => void;
}

export function HistoryTab({ history, onViewDetails, onRetrain, onDelete }: HistoryTabProps) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (history.length === 0) {
    return (
      <Card className="text-center" padding="lg">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-on-surface-variant mx-auto mb-3">
          <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-sm text-on-surface-variant mb-4">No training history yet</p>
        <p className="text-xs text-on-surface-variant">Completed training jobs will appear here</p>
      </Card>
    );
  }

  return (
    <div className="space-y-1">
      {history.map((job) => {
        const result = job.result as Record<string, MLTrainResult> | undefined;
        const isCompleted = job.status === "completed";
        const isFailed = job.status === "failed";

        // Aggregate best metrics across pairs for summary
        let bestValLoss: number | null = null;
        let bestDirAcc: number | null = null;
        if (isCompleted && result) {
          for (const r of Object.values(result)) {
            if (bestValLoss === null || r.best_val_loss < bestValLoss) bestValLoss = r.best_val_loss;
            if (r.direction_accuracy != null && (bestDirAcc === null || r.direction_accuracy > bestDirAcc)) {
              bestDirAcc = r.direction_accuracy;
            }
          }
        }

        const pairCount = result ? Object.keys(result).length : 0;
        const presetLabel = (job as MLTrainJobWithMeta).preset_label;
        const configSummary = job.params
          ? `${presetLabel ? presetLabel + " · " : ""}${job.params.timeframe ?? "—"} · ${job.params.epochs ?? "—"}ep · ${pairCount}p`
          : "";

        return (
          <Card key={job.job_id} padding="none" className="px-3 py-2.5">
            {/* Row 1: Status + job ID + time */}
            <div className="flex items-center gap-2 mb-1">
              <StatusBadge status={job.status} />
              <span className="text-[10px] font-mono text-on-surface-variant flex-1 truncate">{job.job_id}</span>
              {job.created_at && (
                <span className="text-[10px] text-on-surface-variant shrink-0">{formatRelativeTime(job.created_at)}</span>
              )}
            </div>

            {/* Row 2: Config summary + metrics */}
            <div className="flex items-center justify-between text-[10px] text-on-surface-variant">
              <span>{configSummary}</span>
              {isCompleted && (
                <span className="font-mono">
                  {bestValLoss != null && <span>val: {bestValLoss.toFixed(4)}</span>}
                  {bestDirAcc != null && <span className="ml-2">acc: {(bestDirAcc * 100).toFixed(1)}%</span>}
                </span>
              )}
            </div>

            {/* Error message */}
            {isFailed && job.error && (
              <p className="text-[10px] text-error mt-1 truncate">{job.error}</p>
            )}

            {/* Action buttons */}
            <div className="flex gap-3 mt-2">
              {isCompleted && (
                <Button
                  size="xs"
                  onClick={() => onViewDetails(job.job_id)}
                >
                  View Details
                </Button>
              )}
              {isCompleted && job.params && (
                <Button
                  size="xs"
                  onClick={() => onRetrain(job.job_id)}
                >
                  Retrain
                </Button>
              )}
              <Button
                variant="danger"
                size="xs"
                onClick={() => setConfirmDeleteId(job.job_id)}
              >
                Delete
              </Button>
            </div>

            {/* Delete confirmation */}
            {confirmDeleteId === job.job_id && (
              <div className="mt-2 bg-error/5 border border-error/20 rounded p-2 flex items-center justify-between">
                <span className="text-[10px] text-error">Delete this run?</span>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setConfirmDeleteId(null)}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="danger"
                    size="xs"
                    onClick={() => {
                      onDelete(job.job_id);
                      setConfirmDeleteId(null);
                    }}
                  >
                    Confirm
                  </Button>
                </div>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
