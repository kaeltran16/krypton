import { useState, useEffect, useRef } from "react";
import { api, type MLTrainRequest, type MLTrainJob, type MLStatus, type MLBackfillJob } from "../../../shared/lib/api";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { SetupTab } from "./SetupTab";
import { TrainingTab } from "./TrainingTab";
import { ResultsTab } from "./ResultsTab";
import { HistoryTab } from "./HistoryTab";
import type { MLTab, MLTrainJobWithMeta } from "../types";

export function MLTrainingView() {
  const currentTrainingParamsRef = useRef<MLTrainRequest | null>(null);
  const [tab, setTab] = useState<MLTab>("setup");
  const [status, setStatus] = useState<MLStatus | null>(null);
  const [trainingJob, setTrainingJob] = useState<MLTrainJob | null>(null);
  const [backfillJob, setBackfillJob] = useState<MLBackfillJob | null>(null);
  const [history, setHistory] = useState<MLTrainJob[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [restoredParams, setRestoredParams] = useState<MLTrainRequest | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [activePresetLabel, setActivePresetLabel] = useState<string | null>(null);

  // Handlers
  async function handleStartTraining(params: MLTrainRequest, presetLabel?: string | null) {
    try {
      if (!params.timeframe) throw new Error("Timeframe is required");
      if ((params.lookback_days ?? 0) < 1) throw new Error("Lookback days must be at least 1");
      if ((params.epochs ?? 0) < 1) throw new Error("Epochs must be at least 1");
      if ((params.batch_size ?? 0) < 1) throw new Error("Batch size must be at least 1");

      currentTrainingParamsRef.current = params;
      setActivePresetLabel(presetLabel ?? null);
      setError(null);
      setRestoredParams(null);
      const response = await api.startMLTraining(params);
      setTrainingJob({ job_id: response.job_id, status: "running" as const });
      setTab("training");
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Failed to start training"));
    }
  }

  async function handleCancelTraining() {
    if (!trainingJob) return;
    try {
      setError(null);
      await api.cancelMLTraining(trainingJob.job_id);
      setTrainingJob({ ...trainingJob, status: "cancelled" });
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Failed to cancel training"));
    }
  }

  async function handleStartBackfill(params: { timeframe: string; lookback_days: number }) {
    try {
      if (!params.timeframe) throw new Error("Timeframe is required");
      if (params.lookback_days < 1) throw new Error("Lookback days must be at least 1");
      setError(null);
      const response = await api.startMLBackfill(params);
      setBackfillJob({ job_id: response.job_id, status: "running" as const });
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Failed to start backfill"));
    }
  }

  function handleCancelBackfill() {
    setBackfillJob(backfillJob ? { ...backfillJob, status: "cancelled" as const } : null);
  }

  useEffect(() => {
    api.getMLStatus().then(setStatus).catch(() => {});
    const saved = localStorage.getItem("ml_training_history");
    if (saved) {
      try { setHistory(JSON.parse(saved)); } catch { /* ignore */ }
    }
  }, []);

  // Poll for backfill progress
  useEffect(() => {
    if (!backfillJob || backfillJob.status !== "running") return;
    const interval = setInterval(async () => {
      try {
        const updated = await api.getMLBackfillStatus(backfillJob.job_id);
        setBackfillJob(updated as MLBackfillJob);
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [backfillJob?.job_id, backfillJob?.status]);

  return (
    <div className="p-3 space-y-4">
      {error && (
        <div className="bg-error/10 border border-error/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-error mt-0.5 shrink-0">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <div className="flex-1">
            <p className="text-xs text-error font-medium">Error</p>
            <p className="text-[10px] text-error/80 mt-0.5">{error.message}</p>
            <button onClick={() => setError(null)} className="text-[10px] text-error/60 hover:text-error underline">
              Dismiss
            </button>
          </div>
        </div>
      )}

      <SegmentedControl
        options={[
          { value: "setup" as MLTab, label: "Setup" },
          { value: "training" as MLTab, label: "Training" },
          { value: "results" as MLTab, label: "Results" },
          { value: "history" as MLTab, label: "History" },
        ]}
        value={tab}
        onChange={setTab}
        fullWidth
      />

      {tab === "setup" && (
        <SetupTab
          status={status}
          onStartTraining={handleStartTraining}
          trainingJob={trainingJob}
          initialConfig={restoredParams}
          backfillJob={backfillJob}
          onStartBackfill={handleStartBackfill}
          onCancelBackfill={handleCancelBackfill}
        />
      )}
      {tab === "training" && (
        <TrainingTab
          job={trainingJob}
          onCancel={handleCancelTraining}
          onComplete={(job: MLTrainJob) => {
            setTrainingJob(null);
            saveToHistory(job, currentTrainingParamsRef.current, activePresetLabel);
          }}
          onSwitchToSetup={() => setTab("setup")}
          presetLabel={activePresetLabel}
          configSummary={currentTrainingParamsRef.current ? `${currentTrainingParamsRef.current.timeframe} · ${currentTrainingParamsRef.current.epochs}ep` : null}
        />
      )}
      {tab === "results" && (
        <ResultsTab
          history={history}
          onSwitchToSetup={() => setTab("setup")}
          selectedJobId={selectedResultId}
        />
      )}
      {tab === "history" && (
        <HistoryTab
          history={history}
          onViewDetails={(jobId: string) => {
            setSelectedResultId(jobId);
            setTab("results");
          }}
          onRetrain={(jobId: string) => {
            const job = history.find((j) => j.job_id === jobId);
            if (job?.params) {
              setRestoredParams(job.params);
              setTab("setup");
            }
          }}
          onDelete={(jobId: string) => {
            setHistory((h) => {
              const updated = h.filter((j) => j.job_id !== jobId);
              saveHistoryToStorage(updated);
              return updated;
            });
          }}
        />
      )}
    </div>
  );

  function saveToHistory(job: MLTrainJob, params: MLTrainRequest | null, presetLabel?: string | null) {
    const jobWithMeta: MLTrainJobWithMeta = { ...job, created_at: new Date().toISOString(), params: params || undefined, preset_label: presetLabel || undefined };
    setHistory((prev) => {
      const updated = [jobWithMeta, ...prev].slice(0, 50);
      saveHistoryToStorage(updated);
      return updated;
    });
  }
}

function saveHistoryToStorage(history: MLTrainJob[]) {
  localStorage.setItem("ml_training_history", JSON.stringify(history));
}
