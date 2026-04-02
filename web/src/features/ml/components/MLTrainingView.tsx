import { useState, useEffect, useCallback } from "react";
import { api, type MLTrainRequest, type MLTrainJob, type MLBackfillJob } from "../../../shared/lib/api";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { useMLStore } from "../store";
import { SetupTab } from "./SetupTab";
import { TrainingTab } from "./TrainingTab";
import { ResultsTab } from "./ResultsTab";
import { HistoryTab } from "./HistoryTab";
import type { MLTab } from "../types";

export function MLTrainingView() {
  const [tab, setTab] = useState<MLTab>("setup");
  const [trainingJob, setTrainingJob] = useState<MLTrainJob | null>(null);
  const [backfillJob, setBackfillJob] = useState<MLBackfillJob | null>(null);
  const [history, setHistory] = useState<MLTrainJob[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [restoredParams, setRestoredParams] = useState<MLTrainRequest | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [activePresetLabel, setActivePresetLabel] = useState<string | null>(null);
  const [configSummary, setConfigSummary] = useState<string | null>(null);

  // Handlers
  async function handleStartTraining(params: MLTrainRequest, presetLabel?: string | null) {
    try {
      if (!params.timeframe) throw new Error("Timeframe is required");
      if ((params.lookback_days ?? 0) < 1) throw new Error("Lookback days must be at least 1");
      if ((params.epochs ?? 0) < 1) throw new Error("Epochs must be at least 1");
      if ((params.batch_size ?? 0) < 1) throw new Error("Batch size must be at least 1");

      setError(null);
      setRestoredParams(null);
      setActivePresetLabel(presetLabel ?? null);
      setConfigSummary(params.timeframe ? `${params.timeframe} · ${params.epochs}ep` : null);
      const response = await api.startMLTraining({
        ...params,
        preset_label: presetLabel ?? undefined,
      });
      localStorage.setItem("ml_training_job_id", response.job_id);
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
      localStorage.removeItem("ml_training_job_id");
      setTrainingJob(null);
      setTab("setup");
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

  const fetchHistory = useCallback(() => {
    return api.getMLTrainingHistory()
      .then(setHistory)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Recover running job from localStorage on mount
  useEffect(() => {
    const storedJobId = localStorage.getItem("ml_training_job_id");
    if (!storedJobId) return;

    api.getMLTrainingStatus(storedJobId)
      .then((job) => {
        if (job.status === "running") {
          setTrainingJob(job as MLTrainJob);
          setTab("training");
        } else {
          localStorage.removeItem("ml_training_job_id");
        }
      })
      .catch(() => {
        localStorage.removeItem("ml_training_job_id");
      });
  }, []);

  // subscribe to backfill updates from WS via Zustand store
  const wsBackfillStatus = useMLStore((s) => s.wsBackfillStatus);
  useEffect(() => {
    if (!wsBackfillStatus || !backfillJob) return;
    if (wsBackfillStatus.job_id === backfillJob.job_id) {
      setBackfillJob(wsBackfillStatus as MLBackfillJob);
    }
  }, [wsBackfillStatus, backfillJob?.job_id]);

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
          onComplete={async (completedJob: MLTrainJob) => {
            setTrainingJob(completedJob);
            localStorage.removeItem("ml_training_job_id");
            await fetchHistory().catch(() => {});
            setTab("results");
          }}
          onSwitchToSetup={() => {
            if (trainingJob?.params) {
              setRestoredParams(trainingJob.params as MLTrainRequest);
            }
            localStorage.removeItem("ml_training_job_id");
            setTrainingJob(null);
            setTab("setup");
          }}
          presetLabel={activePresetLabel}
          configSummary={configSummary}
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
          onDelete={async (jobId: string) => {
            try {
              await api.deleteMLTrainingRun(jobId);
              setHistory((h) => h.filter((j) => j.job_id !== jobId));
            } catch {
              fetchHistory();
            }
          }}
        />
      )}
    </div>
  );
}
