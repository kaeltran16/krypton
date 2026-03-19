import { useState, useEffect } from "react";
import { api, type MLTrainRequest, type MLTrainJob, type MLStatus, type MLBackfillJob, type MLTrainProgress } from "../../../shared/lib/api";

type Tab = "configure" | "training" | "history" | "backfill";

interface MLTrainingViewProps {
  onBack?: () => void;
}

// Track current training params for saving to history
let currentTrainingParams: MLTrainRequest | null = null;

export function MLTrainingView({ onBack }: MLTrainingViewProps) {
  const [tab, setTab] = useState<Tab>("configure");
  const [status, setStatus] = useState<MLStatus | null>(null);
  const [trainingJob, setTrainingJob] = useState<MLTrainJob | null>(null);
  const [backfillJob, setBackfillJob] = useState<MLBackfillJob | null>(null);
  const [history, setHistory] = useState<MLTrainJob[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [restoredParams, setRestoredParams] = useState<MLTrainRequest | null>(null);

  // Handlers for training operations
  async function handleStartTraining(params: MLTrainRequest) {
    try {
      // Input validation
      if (!params.timeframe) {
        throw new Error("Timeframe is required");
      }
      if ((params.lookback_days ?? 0) < 1) {
        throw new Error("Lookback days must be at least 1");
      }
      if ((params.epochs ?? 0) < 1) {
        throw new Error("Epochs must be at least 1");
      }
      if ((params.batch_size ?? 0) < 1) {
        throw new Error("Batch size must be at least 1");
      }

      currentTrainingParams = params;
      setError(null);
      const response = await api.startMLTraining(params);
      const job: MLTrainJob = {
        job_id: response.job_id,
        status: "running" as const,
      };
      setTrainingJob(job);
      setTab("training"); // Auto-switch to training tab
    } catch (error) {
      console.error("Failed to start training:", error);
      setError(error instanceof Error ? error : new Error("Failed to start training"));
    }
  }

  async function handleCancelTraining() {
    if (!trainingJob) return;
    try {
      setError(null);
      await api.cancelMLTraining(trainingJob.job_id);
      setTrainingJob({ ...trainingJob, status: "cancelled" });
    } catch (error) {
      console.error("Failed to cancel training:", error);
      setError(error instanceof Error ? error : new Error("Failed to cancel training"));
    }
  }

  // Backfill handlers
  async function handleStartBackfill(params: { timeframe: string; lookback_days: number }) {
    try {
      // Input validation
      if (!params.timeframe) {
        throw new Error("Timeframe is required");
      }
      if (params.lookback_days < 1) {
        throw new Error("Lookback days must be at least 1");
      }

      setError(null);
      const response = await api.startMLBackfill(params);
      const job: MLBackfillJob = {
        job_id: response.job_id,
        status: "running" as const,
      };
      setBackfillJob(job);
    } catch (error) {
      console.error("Failed to start backfill:", error);
      setError(error instanceof Error ? error : new Error("Failed to start backfill"));
    }
  }

  function handleCancelBackfill() {
    // API doesn't have cancel endpoint for backfill - stop tracking only
    setBackfillJob(backfillJob ? { ...backfillJob, status: "cancelled" as const } : null);
    // Note: The backfill will continue running on the server
  }

  // Load ML status on mount
  useEffect(() => {
    api.getMLStatus().then(setStatus).catch(() => {});
  }, []);

  // Load history from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("ml_training_history");
    if (saved) {
      try {
        setHistory(JSON.parse(saved));
      } catch {
        // Invalid JSON, ignore
      }
    }
  }, []);

  // Poll for backfill progress
  useEffect(() => {
    if (!backfillJob || backfillJob.status !== "running") return;

    const interval = setInterval(async () => {
      try {
        const updated = await api.getMLBackfillStatus(backfillJob.job_id);
        setBackfillJob(updated as MLBackfillJob);
      } catch {
        // Ignore errors, will retry
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [backfillJob?.job_id, backfillJob?.status]);

  return (
    <div className="p-3 space-y-4">
      {/* Error display */}
      {error && (
        <div className="bg-short/10 border border-short/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-short mt-0.5 shrink-0">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <div className="flex-1">
            <p className="text-xs text-short font-medium">Error</p>
            <p className="text-[10px] text-short/80 mt-0.5">{error.message}</p>
            <button
              onClick={() => setError(null)}
              className="text-[10px] text-short/60 hover:text-short underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      {onBack && (
        <div className="flex items-center justify-between">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-sm text-muted hover:text-foreground transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
            Back
          </button>
          <h1 className="text-lg font-semibold">ML Training</h1>
          <div className="w-12" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1.5 bg-card rounded-lg border border-border p-1">
        <TabButton active={tab === "configure"} onClick={() => setTab("configure")}>Configure</TabButton>
        <TabButton active={tab === "training"} onClick={() => setTab("training")}>Training</TabButton>
        <TabButton active={tab === "history"} onClick={() => setTab("history")}>History</TabButton>
        <TabButton active={tab === "backfill"} onClick={() => setTab("backfill")}>Backfill</TabButton>
      </div>

      {/* Tab Content */}
      {tab === "configure" && (
        <ConfigureTab
          status={status}
          onStartTraining={(params: MLTrainRequest) => {
            setRestoredParams(null); // Clear restored params after using
            handleStartTraining(params);
          }}
          trainingJob={trainingJob}
          initialConfig={restoredParams}
        />
      )}
      {tab === "training" && (
        <TrainingTab
          job={trainingJob}
          onCancel={() => handleCancelTraining()}
          onComplete={(job: MLTrainJob) => {
            setTab("history");
            setTrainingJob(null);
            saveToHistory(job);
          }}
          onSwitchToConfigure={() => setTab("configure")}
        />
      )}
      {tab === "history" && (
        <HistoryTab
          history={history}
          onRetrain={(jobId: string) => {
            const job = history.find((j) => j.job_id === jobId);
            if (job?.params) {
              setRestoredParams(job.params);
              setTab("configure");
            }
          }}
          onDelete={(jobId: string) => {
            setHistory((h) => h.filter((j) => j.job_id !== jobId));
            saveHistoryToStorage(history.filter((j) => j.job_id !== jobId));
          }}
        />
      )}
      {tab === "backfill" && (
        <BackfillTab
          job={backfillJob}
          onStartBackfill={(params: { timeframe: string; lookback_days: number }) => handleStartBackfill(params)}
          onCancel={() => handleCancelBackfill()}
        />
      )}
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-2 text-xs font-medium rounded-lg transition-colors ${
        active ? "bg-accent/15 text-accent" : "text-muted hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

function saveToHistory(job: MLTrainJob) {
  const saved = localStorage.getItem("ml_training_history");
  const history: MLTrainJob[] = saved ? JSON.parse(saved) : [];
  const jobWithParams = {
    ...job,
    created_at: new Date().toISOString(),
    params: currentTrainingParams || undefined,
  };
  history.unshift(jobWithParams);
  localStorage.setItem("ml_training_history", JSON.stringify(history.slice(0, 50))); // Keep last 50
}

function saveHistoryToStorage(history: MLTrainJob[]) {
  localStorage.setItem("ml_training_history", JSON.stringify(history));
}

// Helper components for Configure tab
const TIMEFRAMES = ["15m", "1h", "4h"] as const;

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-2 px-1">{title}</h2>
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        {children}
      </div>
    </div>
  );
}

function ConfigField({ label, value, children }: {
  label: string;
  value?: string | number;
  children: React.ReactNode;
}) {
  return (
    <div className="px-3 py-3 border-b border-border last:border-b-0">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs">{label}</span>
        {value !== undefined && (
          <span className="text-xs text-accent font-mono">{typeof value === "number" && value < 1 ? value.toFixed(4) : value}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function Select({ value, onChange, options }: {
  value: string;
  onChange: (v: string) => void;
  options: { label: string; value: string }[];
}) {
  return (
    <div className="flex gap-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`flex-1 py-2 rounded-lg text-xs font-medium transition-colors ${
            value === opt.value
              ? "bg-accent/15 text-accent border border-accent/30"
              : "bg-card-hover text-muted"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Slider({ min, max, step = 1, value, onChange, format }: {
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-accent"
      />
      <div className="flex justify-between text-[10px] text-dim mt-0.5">
        <span>{format ? format(min) : min}</span>
        <span>{format ? format(max) : max}</span>
      </div>
    </div>
  );
}

// Placeholder tab components (implement in next tasks)
interface ConfigureTabProps {
  status: MLStatus | null;
  onStartTraining: (params: MLTrainRequest) => void;
  trainingJob: MLTrainJob | null;
  initialConfig?: MLTrainRequest | null;
}

function ConfigureTab({ status, onStartTraining, trainingJob, initialConfig }: ConfigureTabProps) {
  const [config, setConfig] = useState<MLTrainRequest>({
    timeframe: "1h",
    lookback_days: 365,
    epochs: 100,
    batch_size: 64,
    hidden_size: 128,
    num_layers: 2,
    seq_len: 50,
    dropout: 0.3,
    lr: 0.001,
    label_horizon: 24,
    label_threshold_pct: 1.5,
  });
  const [showConfirm, setShowConfirm] = useState(false);

  // Restore config from saved params (for retrain)
  useEffect(() => {
    if (initialConfig) {
      setConfig(initialConfig);
    }
  }, [initialConfig]);

  // Reset to defaults
  function handleReset() {
    setConfig({
      timeframe: "1h",
      lookback_days: 365,
      epochs: 100,
      batch_size: 64,
      hidden_size: 128,
      num_layers: 2,
      seq_len: 50,
      dropout: 0.3,
      lr: 0.001,
      label_horizon: 24,
      label_threshold_pct: 1.5,
    });
  }

  function handleStart() {
    setShowConfirm(true);
  }

  function confirmStart() {
    setShowConfirm(false);
    onStartTraining(config);
  }

  return (
    <div className="space-y-4">
      {/* Warning about overwriting models */}
      {status && status.loaded_pairs.length > 0 && (
        <div className="bg-short/10 border border-short/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-short mt-0.5 shrink-0">
            <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="text-xs text-short">
            <span className="font-medium">Training will overwrite existing models.</span>
            <p className="mt-0.5 opacity-90">
              Current models: {status.loaded_pairs.map((p) => p.replace("_", "-").toUpperCase()).join(", ")}
            </p>
          </div>
        </div>
      )}

      {/* Data Parameters */}
      <SettingsSection title="Data Parameters">
        <ConfigField label="Timeframe">
          <Select
            value={config.timeframe!}
            onChange={(v) => setConfig({ ...config, timeframe: v as any })}
            options={TIMEFRAMES.map((t) => ({ label: t, value: t }))}
          />
        </ConfigField>

        <ConfigField label="Lookback Days" value={config.lookback_days}>
          <Slider
            min={30}
            max={1825}
            value={config.lookback_days!}
            onChange={(v) => setConfig({ ...config, lookback_days: v })}
          />
        </ConfigField>

        <ConfigField label="Label Horizon (hours)" value={config.label_horizon}>
          <Slider
            min={4}
            max={96}
            value={config.label_horizon!}
            onChange={(v) => setConfig({ ...config, label_horizon: v })}
          />
        </ConfigField>

        <ConfigField label="Label Threshold %" value={`${config.label_threshold_pct}%`}>
          <Slider
            min={0.1}
            max={10}
            step={0.1}
            value={config.label_threshold_pct!}
            onChange={(v) => setConfig({ ...config, label_threshold_pct: v })}
          />
        </ConfigField>
      </SettingsSection>

      {/* Model Parameters */}
      <SettingsSection title="Model Parameters">
        <ConfigField label="Epochs" value={config.epochs}>
          <Slider
            min={1}
            max={500}
            value={config.epochs!}
            onChange={(v) => setConfig({ ...config, epochs: v })}
          />
        </ConfigField>

        <ConfigField label="Batch Size" value={config.batch_size}>
          <Slider
            min={8}
            max={512}
            step={8}
            value={config.batch_size!}
            onChange={(v) => setConfig({ ...config, batch_size: v })}
          />
        </ConfigField>

        <ConfigField label="Hidden Size" value={config.hidden_size}>
          <Slider
            min={32}
            max={512}
            step={32}
            value={config.hidden_size!}
            onChange={(v) => setConfig({ ...config, hidden_size: v })}
          />
        </ConfigField>

        <ConfigField label="Num Layers" value={config.num_layers}>
          <Slider
            min={1}
            max={4}
            value={config.num_layers!}
            onChange={(v) => setConfig({ ...config, num_layers: v })}
          />
        </ConfigField>

        <ConfigField label="Sequence Length" value={config.seq_len}>
          <Slider
            min={25}
            max={200}
            value={config.seq_len!}
            onChange={(v) => setConfig({ ...config, seq_len: v })}
          />
        </ConfigField>

        <ConfigField label="Dropout" value={config.dropout}>
          <Slider
            min={0}
            max={0.7}
            step={0.05}
            value={config.dropout!}
            onChange={(v) => setConfig({ ...config, dropout: v })}
          />
        </ConfigField>

        <ConfigField label="Learning Rate" value={config.lr}>
          <Slider
            min={0.0001}
            max={0.01}
            step={0.0001}
            value={config.lr!}
            onChange={(v) => setConfig({ ...config, lr: v })}
            format={(v) => v.toExponential(2)}
          />
        </ConfigField>
      </SettingsSection>

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          onClick={handleReset}
          className="flex-1 bg-card rounded-lg border border-border px-4 py-3 text-sm font-medium hover:bg-card-hover transition-colors"
        >
          Reset to Defaults
        </button>
        <button
          onClick={handleStart}
          disabled={!!trainingJob}
          className="flex-1 bg-accent/15 text-accent border border-accent/30 rounded-lg px-4 py-3 text-sm font-medium hover:bg-accent/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Start Training
        </button>
      </div>

      {/* Confirmation Dialog */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card rounded-lg border border-border p-4 max-w-sm w-full">
            <h3 className="text-sm font-semibold mb-2">Confirm Training</h3>
            <p className="text-xs text-dim mb-4">
              This will overwrite existing models for selected pairs. Are you sure you want to proceed?
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 bg-card rounded-lg border border-border px-3 py-2 text-xs font-medium"
              >
                Cancel
              </button>
              <button
                onClick={confirmStart}
                className="flex-1 bg-short/15 text-short border border-short/30 rounded-lg px-3 py-2 text-xs font-medium"
              >
                Start Training
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Training tab implementation
interface TrainingTabProps {
  job: MLTrainJob | null;
  onCancel: () => void;
  onComplete: (job: MLTrainJob) => void;
  onSwitchToConfigure?: () => void;
}

function TrainingTab({ job, onCancel, onComplete, onSwitchToConfigure }: TrainingTabProps) {
  // Poll for job progress
  useEffect(() => {
    if (!job || job.status !== "running") return;

    const interval = setInterval(async () => {
      try {
        const updated = await api.getMLTrainingStatus(job.job_id);
        if (updated.status !== "running") {
          // Job completed or failed
          onComplete(updated as MLTrainJob);
        }
      } catch {
        // Ignore errors, will retry
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [job?.job_id, job?.status, onComplete]);

  if (!job) {
    return (
      <div className="bg-card rounded-lg border border-border p-6 text-center">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted mx-auto mb-3">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
        <p className="text-sm text-dim mb-4">No active training job</p>
        {onSwitchToConfigure && (
          <button
            onClick={onSwitchToConfigure}
            className="bg-accent/15 text-accent border border-accent/30 rounded-lg px-4 py-2 text-xs font-medium"
          >
            Configure Training
          </button>
        )}
      </div>
    );
  }

  const isRunning = job.status === "running";
  const progress = job.progress as Record<string, MLTrainProgress> || {};
  const pairs = Object.keys(progress);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-card rounded-lg border border-border p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isRunning ? "bg-accent animate-pulse" : "bg-muted"}`} />
            <span className="text-xs font-mono text-dim">{job.job_id}</span>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded ${
            job.status === "completed" ? "bg-long/15 text-long" :
            job.status === "failed" ? "bg-short/15 text-short" :
            job.status === "cancelled" ? "bg-dim/15 text-dim" :
            "bg-accent/15 text-accent"
          }`}>
            {job.status}
          </span>
        </div>
        {job.error && (
          <p className="text-xs text-short mt-2">{job.error}</p>
        )}
        {isRunning && (
          <button
            onClick={onCancel}
            className="mt-2 text-xs text-short hover:text-short/80 transition-colors"
          >
            Cancel Training
          </button>
        )}
      </div>

      {/* Progress Cards */}
      {pairs.length === 0 ? (
        <div className="bg-card rounded-lg border border-border p-4 text-center text-sm text-dim">
          {isRunning ? "Training initializing..." : "No pair progress data"}
        </div>
      ) : (
        <div className="space-y-3">
          {pairs.map((pair) => {
            const p = progress[pair];
            const pairDisplay = pair.replace("_", "-").toUpperCase();
            const progressPercent = (p.epoch / p.total_epochs) * 100;

            return (
              <div key={pair} className="bg-card rounded-lg border border-border p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">{pairDisplay}</span>
                  <span className="text-xs text-accent">{p.epoch}/{p.total_epochs}</span>
                </div>

                {/* Progress Bar */}
                <div className="h-1.5 bg-card-hover rounded-full overflow-hidden mb-2">
                  <div
                    className="h-full bg-accent transition-all duration-300"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-dim">Train Loss:</span>
                    <span className="ml-1 font-mono">{p.train_loss.toFixed(4)}</span>
                  </div>
                  <div>
                    <span className="text-dim">Val Loss:</span>
                    <span className="ml-1 font-mono">{p.val_loss.toFixed(4)}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Completed Summary */}
      {job.status === "completed" && job.result && (
        <div className="bg-long/10 border border-long/30 rounded-lg p-3">
          <h3 className="text-sm font-medium text-long mb-2">Training Completed</h3>
          <p className="text-xs text-dim">
            Check the History tab for detailed results per pair.
          </p>
        </div>
      )}
    </div>
  );
}

// History tab implementation
interface HistoryTabProps {
  history: MLTrainJob[];
  onRetrain: (jobId: string) => void;
  onDelete: (jobId: string) => void;
}

function HistoryTab({ history, onRetrain, onDelete }: HistoryTabProps) {
  if (history.length === 0) {
    return (
      <div className="bg-card rounded-lg border border-border p-6 text-center">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted mx-auto mb-3">
          <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-sm text-dim mb-4">No training history yet</p>
        <p className="text-xs text-dim">Completed training jobs will appear here</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {history.map((job) => (
        <HistoryCard key={job.job_id} job={job} onRetrain={onRetrain} onDelete={onDelete} />
      ))}
    </div>
  );
}

interface HistoryCardProps {
  job: MLTrainJob;
  onRetrain: (jobId: string) => void;
  onDelete: (jobId: string) => void;
}

function HistoryCard({ job, onRetrain, onDelete }: HistoryCardProps) {
  const isCompleted = job.status === "completed";
  const isFailed = job.status === "failed";
  // isCancelled is defined but not currently used in the UI
  const isCancelled = job.status === "cancelled";
  void isCancelled;

  const result = job.result as Record<string, any> | undefined;

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      {/* Card Header */}
      <div className="px-3 py-2 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded ${
            isCompleted ? "bg-long/15 text-long" :
            isFailed ? "bg-short/15 text-short" :
            "bg-dim/15 text-dim"
          }`}>
            {job.status}
          </span>
          <span className="text-xs font-mono text-dim">{job.job_id}</span>
        </div>
        <div className="flex gap-1.5">
          {isCompleted && (
            <button
              onClick={() => job.params && onRetrain(job.job_id)}
              disabled={!job.params}
              className="text-xs text-accent hover:text-accent/80 disabled:text-dim disabled:cursor-not-allowed"
            >
              Retrain
            </button>
          )}
          <button
            onClick={() => onDelete(job.job_id)}
            className="text-xs text-short hover:text-short/80"
          >
            Delete
          </button>
        </div>
      </div>

      {/* Error Message */}
      {isFailed && job.error && (
        <div className="px-3 py-2 bg-short/5 text-xs text-short">
          {job.error}
        </div>
      )}

      {/* Per-Pair Results */}
      {isCompleted && result && (
        <div className="p-3 space-y-2">
          {Object.entries(result).map(([pair, res]: [string, any]) => {
            const pairDisplay = pair.replace("_", "-").toUpperCase();
            return (
              <div key={pair} className="bg-card-hover rounded-lg p-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium">{pairDisplay}</span>
                  {res.flow_data_used && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent">
                      Flow Used
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[10px] text-dim">
                  <div>Best Epoch: <span className="text-foreground">{res.best_epoch}</span></div>
                  <div>Best Val Loss: <span className="text-foreground">{res.best_val_loss.toFixed(4)}</span></div>
                  <div>Total Epochs: <span className="text-foreground">{res.total_epochs}</span></div>
                  <div>Samples: <span className="text-foreground">{res.total_samples}</span></div>
                </div>
                {res.version && (
                  <div className="mt-1 text-[10px] text-dim">
                    Version: <span className="text-foreground">{res.version}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Timestamp */}
      {job.created_at && (
        <div className="px-3 py-2 border-t border-border text-[10px] text-dim">
          {new Date(job.created_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}

// Backfill tab implementation
interface BackfillTabProps {
  job: MLBackfillJob | null;
  onStartBackfill: (params: { timeframe: string; lookback_days: number }) => void;
  onCancel: () => void;
}

function BackfillTab({ job, onStartBackfill, onCancel }: BackfillTabProps) {
  const [timeframe, setTimeframe] = useState("1h");
  const [lookbackDays, setLookbackDays] = useState(365);

  const isRunning = job?.status === "running";
  const progress = job?.progress as Record<string, number> | undefined;
  const result = job?.result as Record<string, number> | undefined;
  const pairs = isRunning ? Object.keys(progress || {}) : Object.keys(result || {});

  return (
    <div className="space-y-4">
      {/* Form */}
      <div className="bg-card rounded-lg border border-border p-3 space-y-3">
        <h2 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-2">Backfill Settings</h2>

        <ConfigField label="Timeframe">
          <Select
            value={timeframe}
            onChange={setTimeframe}
            options={TIMEFRAMES.map((t) => ({ label: t, value: t }))}
          />
        </ConfigField>

        <ConfigField label="Lookback Days" value={lookbackDays}>
          <Slider
            min={30}
            max={1825}
            value={lookbackDays}
            onChange={setLookbackDays}
          />
        </ConfigField>

        {!isRunning ? (
          <button
            onClick={() => onStartBackfill({ timeframe, lookback_days: lookbackDays })}
            className="w-full bg-accent/15 text-accent border border-accent/30 rounded-lg px-4 py-2 text-sm font-medium hover:bg-accent/25 transition-colors"
          >
            Start Backfill
          </button>
        ) : (
          <button
            onClick={onCancel}
            className="w-full bg-short/15 text-short border border-short/30 rounded-lg px-4 py-2 text-sm font-medium hover:bg-short/25 transition-colors"
          >
            Cancel Backfill
          </button>
        )}
      </div>

      {/* Status */}
      {job && (
        <div className="bg-card rounded-lg border border-border p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${isRunning ? "bg-accent animate-pulse" : "bg-muted"}`} />
              <span className="text-xs font-mono text-dim">{job.job_id}</span>
            </div>
            <span className={`text-xs px-2 py-0.5 rounded ${
              job.status === "completed" ? "bg-long/15 text-long" :
              job.status === "failed" ? "bg-short/15 text-short" :
              "bg-accent/15 text-accent"
            }`}>
              {job.status}
            </span>
          </div>
          {job.error && (
            <p className="text-xs text-short mb-2">{job.error}</p>
          )}
        </div>
      )}

      {/* Per-Pair Progress */}
      {pairs.length > 0 && (
        <div className="space-y-2">
          {pairs.map((pair) => {
            const pairDisplay = pair.replace("_", "-").toUpperCase();
            const count = isRunning ? progress?.[pair] : result?.[pair];

            return (
              <div key={pair} className="bg-card rounded-lg border border-border p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{pairDisplay}</span>
                  <span className="text-xs text-accent font-mono">{count} candles</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Completed Summary */}
      {job?.status === "completed" && result && (
        <div className="bg-long/10 border border-long/30 rounded-lg p-3">
          <h3 className="text-sm font-medium text-long mb-1">Backfill Completed</h3>
          <p className="text-xs text-dim">
            {Object.values(result).reduce((sum: number, n: any) => sum + n, 0)} candles backfilled across {Object.keys(result).length} pairs.
          </p>
          <p className="text-xs text-dim mt-1">
            You can now proceed to training.
          </p>
        </div>
      )}

      {/* Cancelled Warning */}
      {job?.status === "cancelled" && (
        <div className="bg-accent/10 border border-accent/30 rounded-lg p-3">
          <h3 className="text-sm font-medium text-accent mb-1">Backfill Tracking Stopped</h3>
          <p className="text-xs text-dim">
            You stopped tracking this backfill job. The backfill continues running on the server in the background.
          </p>
          <p className="text-xs text-dim mt-1">
            Note: Starting a new backfill will create a separate job.
          </p>
        </div>
      )}
    </div>
  );
}
