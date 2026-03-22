import { useState, useEffect, useRef, useMemo } from "react";
import { api, type MLTrainJob, type MLTrainProgress } from "../../../shared/lib/api";
import { Button } from "../../../shared/components/Button";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { StatusBadge, formatPairSlug } from "./shared";
import { LossChart } from "./LossChart";
import type { LossHistoryEntry } from "../types";

interface TrainingTabProps {
  job: MLTrainJob | null;
  onCancel: () => void;
  onComplete: (job: MLTrainJob) => void;
  onSwitchToSetup: () => void;
  presetLabel?: string | null;
  configSummary?: string | null;
}

export function TrainingTab({ job, onCancel, onComplete, onSwitchToSetup, presetLabel, configSummary }: TrainingTabProps) {
  const [selectedPair, setSelectedPair] = useState<string>("");
  const [lossData, setLossData] = useState<Record<string, LossHistoryEntry[]>>({});
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (!job || job.status !== "running") return;

    const interval = setInterval(async () => {
      try {
        const updated = await api.getMLTrainingStatus(job.job_id);

        if (updated.progress) {
          setLossData((prev) => {
            let changed = false;
            const next = { ...prev };
            for (const [pair, p] of Object.entries(updated.progress as Record<string, MLTrainProgress>)) {
              const existing = next[pair] || [];
              const lastEpoch = existing.length > 0 ? existing[existing.length - 1].epoch : 0;
              if (p.epoch > lastEpoch) {
                next[pair] = [...existing, { epoch: p.epoch, train_loss: p.train_loss, val_loss: p.val_loss }];
                changed = true;
              }
            }
            return changed ? next : prev;
          });

          const pairs = Object.keys(updated.progress);
          if (pairs.length > 0) {
            setSelectedPair((prev) => prev || pairs[pairs.length - 1]);
          }
        }

        if (updated.status !== "running") {
          onCompleteRef.current(updated as MLTrainJob);
        }
      } catch {
        // Ignore, will retry
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [job?.job_id, job?.status]);

  // Reset loss data when a new job starts
  useEffect(() => {
    if (job?.status === "running") {
      setLossData({});
      setSelectedPair("");
    }
  }, [job?.job_id]);

  if (!job) {
    return (
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-6 text-center">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-on-surface-variant mx-auto mb-3">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
        <p className="text-sm text-on-surface-variant mb-4">No active training job</p>
        <Button onClick={onSwitchToSetup}>
          Configure Training
        </Button>
      </div>
    );
  }

  const isRunning = job.status === "running";
  const progress = (job.progress as Record<string, MLTrainProgress>) || {};
  const pairs = Object.keys(progress);
  const currentProgress = selectedPair ? progress[selectedPair] : null;
  const currentLossData = selectedPair ? lossData[selectedPair] || [] : [];

  const bestValEntry = useMemo(() => {
    let best: LossHistoryEntry | null = null;
    for (const d of currentLossData) {
      if (d.val_loss != null && (best === null || d.val_loss < best.val_loss!)) best = d;
    }
    return best;
  }, [currentLossData]);

  return (
    <div className="space-y-4">
      {/* Job header */}
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isRunning ? "bg-primary animate-pulse motion-reduce:animate-none" : "bg-muted"}`} />
            <span className="text-xs font-mono text-on-surface-variant">{job.job_id}</span>
            <StatusBadge status={job.status} />
          </div>
          {isRunning && (
            <Button variant="danger" size="xs" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </div>
        {(presetLabel || configSummary) && (
          <p className="text-[10px] text-on-surface-variant mt-1">
            {presetLabel && <span className="text-primary font-medium">{presetLabel}</span>}
            {presetLabel && configSummary && <span> · </span>}
            {configSummary}
          </p>
        )}
        {job.error && <p className="text-xs text-error mt-2">{job.error}</p>}
      </div>

      {/* Pair selector */}
      {pairs.length > 1 && (
        <div className="overflow-x-auto">
          <SegmentedControl
            options={pairs.map((p) => ({ value: p, label: formatPairSlug(p) }))}
            value={selectedPair}
            onChange={setSelectedPair}
            variant="underline"
          />
        </div>
      )}

      {/* Loss curve chart */}
      {currentLossData.length > 0 && (
        <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
          <LossChart data={currentLossData} height={180} />
          {currentProgress && bestValEntry && (
            <p className="text-[10px] text-on-surface-variant text-center mt-2">
              Best val: {bestValEntry.val_loss?.toFixed(4)} @ epoch {bestValEntry.epoch}
            </p>
          )}
        </div>
      )}

      {/* Metrics grid */}
      {currentProgress && (
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: "Train Loss", value: currentProgress.train_loss.toFixed(4) },
            { label: "Val Loss", value: currentProgress.val_loss?.toFixed(4) ?? "—" },
            { label: "Direction Acc", value: currentProgress.direction_acc != null ? `${(currentProgress.direction_acc * 100).toFixed(1)}%` : "—" },
            { label: "Epoch", value: `${currentProgress.epoch}/${currentProgress.total_epochs}` },
          ].map((m) => (
            <div key={m.label} className="bg-surface-container rounded-lg border border-outline-variant/10 p-3 text-center">
              <p className="text-[10px] text-on-surface-variant mb-1">{m.label}</p>
              <p className="text-sm font-mono text-on-surface">{m.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Initializing state */}
      {isRunning && pairs.length === 0 && (
        <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-4 text-center text-sm text-on-surface-variant">
          Training initializing...
        </div>
      )}
    </div>
  );
}
