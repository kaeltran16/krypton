import { useState, useEffect, useRef, useMemo } from "react";
import type { MLTrainJob } from "../../../shared/lib/api";
import { Button } from "../../../shared/components/Button";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { StatusBadge, formatPairSlug } from "./shared";
import { LossChart } from "./LossChart";
import { useMLTrainingSocket } from "../hooks/useMLTrainingSocket";
import type { LossEntry } from "../hooks/useMLTrainingSocket";
import { Card } from "../../../shared/components/Card";
import { MetricCard } from "../../../shared/components/MetricCard";

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
  const [completing, setCompleting] = useState(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const { status: wsStatus, progress, lossHistory, error: wsError, connected } =
    useMLTrainingSocket(job?.job_id ?? null);

  const pairs = Object.keys(progress);

  useEffect(() => {
    if (pairs.length > 0 && !pairs.includes(selectedPair)) {
      setSelectedPair(pairs[pairs.length - 1]);
    }
  }, [pairs.join(",")]);

  // Reset on new job
  useEffect(() => {
    if (job?.status === "running") {
      setSelectedPair("");
      setCompleting(false);
    }
  }, [job?.job_id]);

  // Handle completion/failure from WS
  useEffect(() => {
    if (!job || completing) return;
    if (wsStatus === "completed" || wsStatus === "failed" || wsStatus === "cancelled") {
      if (wsStatus === "completed") {
        setCompleting(true);
        const timer = setTimeout(() => {
          onCompleteRef.current({ ...job, status: "completed" } as MLTrainJob);
        }, 1000);
        return () => clearTimeout(timer);
      } else {
        onCompleteRef.current({ ...job, status: wsStatus, error: wsError ?? undefined } as MLTrainJob);
      }
    }
  }, [wsStatus]);

  if (!job) {
    return (
      <Card className="text-center" padding="lg">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-on-surface-variant mx-auto mb-3">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
        <p className="text-sm text-on-surface-variant mb-4">No active training job</p>
        <Button onClick={onSwitchToSetup}>
          Configure Training
        </Button>
      </Card>
    );
  }

  // Completion animation
  if (completing) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <div
          className="w-12 h-12 rounded-full bg-tertiary/20 flex items-center justify-center"
          style={{ animation: "scale-fade-in 300ms ease-out" }}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="text-tertiary">
            <path d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <p className="text-sm text-on-surface">Training complete</p>
        <style>{`@keyframes scale-fade-in { from { opacity: 0; transform: scale(0.5); } to { opacity: 1; transform: scale(1); } }`}</style>
      </div>
    );
  }

  // Failure state
  if (job.status === "failed" || wsStatus === "failed") {
    const errMsg = wsError || job.error || "Training failed";
    const isOOM = /memory|oom/i.test(errMsg);
    return (
      <div className="space-y-4 p-4">
        <div className="bg-error/10 border border-error/30 rounded-lg p-3" role="alert">
          <p className="text-sm text-error font-medium">Training failed</p>
          <p className="text-xs text-error/80 mt-1">{errMsg}</p>
          {isOOM && (
            <p className="text-xs text-muted mt-2">Consider reducing batch size or model size.</p>
          )}
        </div>
        <Button variant="secondary" size="lg" onClick={onSwitchToSetup} className="w-full">
          Retry with different settings
        </Button>
      </div>
    );
  }

  const isRunning = job.status === "running";
  const currentProgress = selectedPair ? progress[selectedPair] : null;
  const currentLossData = lossHistory[selectedPair] ?? [];

  const bestValEntry = useMemo(() => {
    let best: LossEntry | null = null;
    for (const d of currentLossData) {
      if (d.val_loss != null && (best === null || d.val_loss < best.val_loss!)) best = d;
    }
    return best;
  }, [currentLossData]);

  return (
    <div className="space-y-4">
      {/* Job header */}
      <Card padding="sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isRunning ? "bg-primary animate-pulse motion-reduce:animate-none" : "bg-muted"}`} />
            <span className="text-xs font-mono text-on-surface-variant">{job.job_id}</span>
            <StatusBadge status={job.status} />
            {!connected && wsError && (
              <span className="text-[10px] text-on-surface-variant ml-1">{wsError}</span>
            )}
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
      </Card>

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
        <Card padding="sm">
          <LossChart data={currentLossData} height={240} />
          {currentProgress && bestValEntry && (
            <p className="text-[10px] text-on-surface-variant text-center mt-2">
              Best val: {bestValEntry.val_loss?.toFixed(4)} @ epoch {bestValEntry.epoch}
            </p>
          )}
        </Card>
      )}

      {/* Metrics grid */}
      {currentProgress && (
        <div className="grid grid-cols-2 gap-2">
          <MetricCard label="Train Loss" value={currentProgress.train_loss.toFixed(4)} />
          <MetricCard label="Val Loss" value={currentProgress.val_loss?.toFixed(4) ?? "—"} />
          <MetricCard label="Direction Acc" value={currentProgress.direction_acc != null ? `${(currentProgress.direction_acc * 100).toFixed(1)}%` : "—"} />
          <MetricCard label="Epoch" value={`${currentProgress.epoch}/${currentProgress.total_epochs}`} />
        </div>
      )}

      {/* Initializing state */}
      {isRunning && pairs.length === 0 && (
        <Card className="text-center text-sm text-on-surface-variant">
          Training initializing...
        </Card>
      )}
    </div>
  );
}
