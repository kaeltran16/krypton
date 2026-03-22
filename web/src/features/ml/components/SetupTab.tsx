import { useState, useEffect, useRef, useCallback } from "react";
import { api, type MLTrainRequest, type MLStatus, type MLTrainJob, type MLBackfillJob } from "../../../shared/lib/api";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { Button } from "../../../shared/components/Button";
import { SettingsSection, ConfigField, Slider, TIMEFRAMES, formatPairSlug } from "./shared";
import { PRESETS, DEFAULT_CONFIG, CANDLES_PER_DAY, type PresetName } from "../presets";
import type { DataReadinessMap } from "../types";

interface SetupTabProps {
  status: MLStatus | null;
  onStartTraining: (params: MLTrainRequest, presetLabel?: string | null) => void;
  trainingJob: MLTrainJob | null;
  initialConfig?: MLTrainRequest | null;
  backfillJob: MLBackfillJob | null;
  onStartBackfill: (params: { timeframe: string; lookback_days: number }) => void;
  onCancelBackfill: () => void;
}

export function SetupTab({
  status,
  onStartTraining,
  trainingJob,
  initialConfig,
  backfillJob,
  onStartBackfill,
  onCancelBackfill,
}: SetupTabProps) {
  const [config, setConfig] = useState<MLTrainRequest>({ ...DEFAULT_CONFIG });
  const [activePreset, setActivePreset] = useState<PresetName | null>("balanced");
  const [showConfirm, setShowConfirm] = useState(false);
  const [readiness, setReadiness] = useState<DataReadinessMap | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const backfillStartTimeRef = useRef<number | null>(null);

  const fetchReadiness = useCallback((timeframe: string) => {
    setReadinessLoading(true);
    setReadinessError(null);
    api.getMLDataReadiness(timeframe)
      .then(setReadiness)
      .catch((e) => setReadinessError(e.message))
      .finally(() => setReadinessLoading(false));
  }, []);

  useEffect(() => {
    if (initialConfig) {
      setConfig(initialConfig);
      setActivePreset(null);
    }
  }, [initialConfig]);

  useEffect(() => {
    if (config.timeframe) fetchReadiness(config.timeframe);
  }, [config.timeframe, fetchReadiness]);

  useEffect(() => {
    if (backfillJob?.status === "completed" && config.timeframe) {
      fetchReadiness(config.timeframe);
    }
  }, [backfillJob?.status, config.timeframe, fetchReadiness]);

  function handlePresetChange(preset: PresetName) {
    const found = PRESETS.find((p) => p.name === preset);
    if (found) {
      setConfig({ ...config, ...found.config });
      setActivePreset(preset);
    }
  }

  function handleReset() {
    setConfig({ ...DEFAULT_CONFIG });
    setActivePreset("balanced");
  }

  function updateConfig(patch: Partial<MLTrainRequest>) {
    setConfig({ ...config, ...patch });
    setActivePreset(null); // Manual change clears preset
  }

  const backfillRunning = backfillJob?.status === "running";
  const backfillProgress = backfillJob?.progress as Record<string, number> | undefined;
  const backfillResult = backfillJob?.result as Record<string, number> | undefined;

  useEffect(() => {
    if (backfillRunning && !backfillStartTimeRef.current) backfillStartTimeRef.current = Date.now();
    if (!backfillRunning) backfillStartTimeRef.current = null;
  }, [backfillRunning]);
  const anyInsufficient = readiness ? Object.values(readiness).some((r) => !r.sufficient) : false;

  return (
    <div className="space-y-4 pb-20">
      {/* Model overwrite warning */}
      {status && status.loaded_pairs.length > 0 && (
        <div className="bg-error/10 border border-error/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-error mt-0.5 shrink-0">
            <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="text-xs text-error">
            <span className="font-medium">Training will overwrite existing models.</span>
            <p className="mt-0.5 opacity-90">
              Current models: {status.loaded_pairs.map(formatPairSlug).join(", ")}
            </p>
          </div>
        </div>
      )}

      {/* Preset bar */}
      <SegmentedControl
        options={PRESETS.map((p) => ({ value: p.name, label: p.label }))}
        value={activePreset ?? ""}
        onChange={(v) => handlePresetChange(v as PresetName)}
        fullWidth
      />

      {/* Data readiness */}
      <SettingsSection title="Data Readiness">
        {readinessLoading ? (
          <div className="p-3 space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-6 bg-surface-container-highest rounded animate-pulse" />
            ))}
          </div>
        ) : readinessError ? (
          <div className="p-3">
            <p className="text-xs text-error mb-2">{readinessError}</p>
            <button
              onClick={() => fetchReadiness(config.timeframe ?? "1h")}
              className="text-xs text-primary hover:underline"
            >
              Retry
            </button>
          </div>
        ) : readiness ? (
          <div className="p-3 space-y-2">
            {Object.entries(readiness).map(([pair, info]) => (
              <div key={pair} className="flex items-center gap-2">
                <span className="text-xs text-on-surface w-28 shrink-0 truncate">{pair}</span>
                <div className="flex-1 h-2 bg-surface-container-highest rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${info.sufficient ? "bg-tertiary-dim" : "bg-error"}`}
                    style={{ width: `${Math.min(100, (info.count / 100) * 100)}%` }}
                  />
                </div>
                {info.sufficient ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-tertiary-dim shrink-0">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-error shrink-0">
                    <path d="M12 9v2m0 4h.01M12 3a9 9 0 100 18 9 9 0 000-18z" />
                  </svg>
                )}
                <span className="text-[10px] font-mono text-on-surface-variant w-14 text-right">{info.count}</span>
                {!info.sufficient && !backfillRunning && (
                  <button
                    onClick={() => onStartBackfill({ timeframe: config.timeframe ?? "1h", lookback_days: config.lookback_days ?? 365 })}
                    className="text-[10px] text-primary hover:underline shrink-0"
                  >
                    Backfill Now
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </SettingsSection>

      {/* Data Parameters */}
      <SettingsSection title="Data Parameters">
        <ConfigField label="Timeframe">
          <SegmentedControl
            options={TIMEFRAMES.map((t) => ({ label: t, value: t }))}
            value={config.timeframe ?? "1h"}
            onChange={(v) => updateConfig({ timeframe: v })}
            compact
          />
        </ConfigField>
        <ConfigField label="Lookback Days" value={config.lookback_days}>
          <Slider min={30} max={1825} value={config.lookback_days} onChange={(v) => updateConfig({ lookback_days: v })} />
        </ConfigField>
        <ConfigField label="Label Horizon (hours)" value={config.label_horizon}>
          <Slider min={4} max={96} value={config.label_horizon} onChange={(v) => updateConfig({ label_horizon: v })} />
        </ConfigField>
        <ConfigField label="Label Threshold %" value={`${config.label_threshold_pct}%`}>
          <Slider min={0.1} max={10} step={0.1} value={config.label_threshold_pct} onChange={(v) => updateConfig({ label_threshold_pct: v })} />
        </ConfigField>
      </SettingsSection>

      {/* Model Parameters */}
      <SettingsSection title="Model Parameters">
        <ConfigField label="Epochs" value={config.epochs}>
          <Slider min={1} max={500} value={config.epochs} onChange={(v) => updateConfig({ epochs: v })} />
        </ConfigField>
        <ConfigField label="Batch Size" value={config.batch_size}>
          <Slider min={8} max={512} step={8} value={config.batch_size} onChange={(v) => updateConfig({ batch_size: v })} />
        </ConfigField>
        <ConfigField label="Hidden Size" value={config.hidden_size}>
          <Slider min={32} max={512} step={32} value={config.hidden_size} onChange={(v) => updateConfig({ hidden_size: v })} />
        </ConfigField>
        <ConfigField label="Num Layers" value={config.num_layers}>
          <Slider min={1} max={4} value={config.num_layers} onChange={(v) => updateConfig({ num_layers: v })} />
        </ConfigField>
        <ConfigField label="Sequence Length" value={config.seq_len}>
          <Slider min={25} max={200} value={config.seq_len} onChange={(v) => updateConfig({ seq_len: v })} />
        </ConfigField>
        <ConfigField label="Dropout" value={config.dropout}>
          <Slider min={0} max={0.7} step={0.05} value={config.dropout ?? 0.3} onChange={(v) => updateConfig({ dropout: v })} />
        </ConfigField>
        <ConfigField label="Learning Rate" value={config.lr}>
          <Slider min={0.0001} max={0.01} step={0.0001} value={config.lr ?? 0.001} onChange={(v) => updateConfig({ lr: v })} format={(v) => v.toExponential(2)} />
        </ConfigField>
      </SettingsSection>

      {/* Inline Backfill */}
      <SettingsSection title="Backfill Data">
        <div className="p-3 space-y-3">
          {backfillRunning && backfillProgress ? (
            <div className="space-y-2">
              {(() => {
                const cpd = CANDLES_PER_DAY[config.timeframe ?? "1h"] ?? 24;
                const expected = (config.lookback_days ?? 365) * cpd;
                const totalFetched = Object.values(backfillProgress).reduce((a, b) => a + b, 0);
                const totalExpected = expected * Object.keys(backfillProgress).length;
                const overallPct = totalExpected > 0 ? (totalFetched / totalExpected) * 100 : 0;

                // ETA estimation
                let etaText = "Estimating...";
                if (overallPct >= 10 && backfillStartTimeRef.current) {
                  const elapsed = (Date.now() - backfillStartTimeRef.current) / 1000;
                  const remaining = (elapsed / overallPct) * (100 - overallPct);
                  const mins = Math.ceil(remaining / 60);
                  etaText = mins > 1 ? `~${mins}m remaining` : "< 1m remaining";
                }

                return (
                  <>
                    <p className="text-[10px] text-on-surface-variant text-right">{etaText}</p>
                    {Object.entries(backfillProgress).map(([pair, fetched]) => {
                      const pct = Math.min(100, (fetched / expected) * 100);
                      const isDone = backfillResult?.[pair] != null;
                      return (
                        <div key={pair}>
                          <div className="flex items-center justify-between text-xs mb-1">
                            <div className="flex items-center gap-1.5">
                              {isDone ? (
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-tertiary-dim">
                                  <path d="M20 6L9 17l-5-5" />
                                </svg>
                              ) : (
                                <div className="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                              )}
                              <span className="text-on-surface">{pair}</span>
                            </div>
                            <span className="text-on-surface-variant font-mono">{fetched} candles</span>
                          </div>
                          <div className="h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                            <div className="h-full bg-primary transition-all duration-300" style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </>
                );
              })()}
              <button onClick={onCancelBackfill} className="w-full text-xs text-error hover:text-error/80 py-2">
                Cancel Backfill
              </button>
            </div>
          ) : (
            <>
              <p className="text-xs text-on-surface-variant">
                Fetch historical candles for {config.timeframe} / {config.lookback_days} days.
              </p>
              {anyInsufficient && (
                <p className="text-xs text-error">Some pairs have insufficient data. Backfill recommended.</p>
              )}
              <button
                onClick={() => onStartBackfill({ timeframe: config.timeframe ?? "1h", lookback_days: config.lookback_days ?? 365 })}
                className="w-full bg-surface-container-highest text-on-surface rounded-lg px-4 py-2 text-xs font-medium hover:bg-surface-bright transition-colors"
              >
                Start Backfill
              </button>
            </>
          )}
        </div>
      </SettingsSection>

      {/* Sticky Action Buttons */}
      <div className="fixed bottom-0 left-0 right-0 bg-surface/90 backdrop-blur-lg border-t border-outline-variant/10 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] flex gap-2 z-40">
        <Button variant="secondary" size="lg" onClick={handleReset} className="flex-1">Reset to Defaults</Button>
        <Button variant="primary" size="lg" disabled={!!trainingJob} onClick={() => setShowConfirm(true)} className="flex-1">Start Training</Button>
      </div>

      {/* Confirmation Dialog */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-4 max-w-sm w-full">
            <h3 className="text-sm font-semibold mb-2">Confirm Training</h3>
            <p className="text-xs text-on-surface-variant mb-4">
              This will overwrite existing models for selected pairs. Are you sure you want to proceed?
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => setShowConfirm(false)} className="flex-1">Cancel</Button>
              <Button
                variant="solid"
                size="sm"
                onClick={() => {
                  setShowConfirm(false);
                  const label = activePreset ? PRESETS.find((p) => p.name === activePreset)?.label : null;
                  onStartTraining(config, label);
                }}
                className="flex-1"
              >
                Start
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
