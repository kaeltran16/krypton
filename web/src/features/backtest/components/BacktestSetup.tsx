import { useState, useId } from "react";
import { useBacktestStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { formatPair } from "../../../shared/lib/format";
import ParameterOverridePanel from "./ParameterOverridePanel";
import { Toggle } from "../../../shared/components/Toggle";
import { SectionLabel } from "../../../shared/components/SectionLabel";

const TIMEFRAMES = ["15m", "1h", "4h"] as const;

const INDICATORS = [
  { key: "adx", label: "ADX" },
  { key: "rsi", label: "RSI" },
  { key: "bb", label: "BB" },
  { key: "obv", label: "OBV" },
] as const;

export function BacktestSetup() {
  const { config, updateConfig, startRun, runLoading, runError, activeRun, cancelRun, startImport, importLoading, importStatus } = useBacktestStore();
  const [showImport, setShowImport] = useState(false);
  const [importDays, setImportDays] = useState(90);

  const isRunning = runLoading || activeRun?.status === "running";

  function handleWeightChange(key: "tech_weight" | "pattern_weight", value: number) {
    const other = key === "tech_weight" ? "pattern_weight" : "tech_weight";
    const clamped = Math.max(0, Math.min(100, value));
    updateConfig({ [key]: clamped, [other]: 100 - clamped });
  }

  return (
    <div className="space-y-4">
      {/* Pairs */}
      <Section title="Pairs">
        <div className="space-y-2">
          {AVAILABLE_PAIRS.map((pair) => (
            <button
              key={pair}
              onClick={() => {
                const next = config.pairs.includes(pair)
                  ? config.pairs.filter((p) => p !== pair)
                  : [...config.pairs, pair];
                if (next.length > 0) updateConfig({ pairs: next });
              }}
              className={`w-full flex items-center justify-between p-3 rounded border transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                config.pairs.includes(pair)
                  ? "bg-surface-container-lowest border-primary/30"
                  : "bg-surface-container-lowest border-outline-variant/20"
              }`}
            >
              <span className="text-sm font-medium text-on-surface">{formatPair(pair)}/USDT</span>
              {config.pairs.includes(pair) && (
                <span className="text-primary text-xs font-bold">&#10003;</span>
              )}
            </button>
          ))}
        </div>
      </Section>

      {/* Timeframe */}
      <Section title="Timeframe">
        <div className="flex gap-2">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => updateConfig({ timeframe: tf })}
              className={`flex-1 py-2 rounded-lg text-sm font-bold transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                config.timeframe === tf
                  ? "bg-primary-container text-on-primary-container"
                  : "bg-surface-container-lowest text-on-surface-variant"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </Section>

      {/* Date Range */}
      <Section title="Date Range">
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">From</label>
            <input
              type="date"
              value={config.date_from}
              onChange={(e) => updateConfig({ date_from: e.target.value })}
              className="w-full mt-1 p-2 bg-surface-container-lowest rounded border border-outline-variant/20 text-sm font-mono focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none text-on-surface"
            />
          </div>
          <div className="flex-1">
            <label className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">To</label>
            <input
              type="date"
              value={config.date_to}
              onChange={(e) => updateConfig({ date_to: e.target.value })}
              className="w-full mt-1 p-2 bg-surface-container-lowest rounded border border-outline-variant/20 text-sm font-mono focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none text-on-surface"
            />
          </div>
        </div>
      </Section>

      {/* Scoring Weights */}
      <Section title="Scoring Weights" collapsible summary={`Tech ${config.tech_weight}% / Pattern ${config.pattern_weight}%`}>
        <WeightSlider
          label="Technical"
          value={config.tech_weight}
          onChange={(v) => handleWeightChange("tech_weight", v)}
        />
        <WeightSlider
          label="Pattern"
          value={config.pattern_weight}
          onChange={(v) => handleWeightChange("pattern_weight", v)}
        />
        <div className="mt-2 space-y-2 opacity-40 pointer-events-none">
          <div className="flex items-center justify-between">
            <span className="text-sm text-on-surface-variant">Order Flow</span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-on-surface-variant font-mono">N/A</span>
              <span className="text-[10px] text-on-surface-variant" title="Historical data unavailable">
                &#9432;
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-on-surface-variant">On-Chain</span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-on-surface-variant font-mono">N/A</span>
              <span className="text-[10px] text-on-surface-variant" title="Historical data unavailable">
                &#9432;
              </span>
            </div>
          </div>
        </div>
      </Section>

      {/* Thresholds */}
      <Section title="Thresholds" collapsible summary={`Signal \u2265 ${config.signal_threshold}`}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-on-surface">Signal Threshold</span>
          <span className="text-sm font-mono text-primary font-bold">{config.signal_threshold}</span>
        </div>
        <input
          type="range"
          min={10}
          max={100}
          value={config.signal_threshold}
          onChange={(e) => updateConfig({ signal_threshold: Number(e.target.value) })}
          className="w-full accent-primary"
        />
        <div className="flex justify-between text-[10px] font-mono text-outline mt-0.5">
          <span>More signals</span>
          <span>Strong only</span>
        </div>
      </Section>

      {/* ML Blending */}
      <Section title="ML Blending" collapsible summary={config.ml_enabled ? `On \u00b7 \u2265 ${config.ml_confidence_threshold}%` : "Off"}>
        <div className="flex items-center justify-between">
          <span className="text-sm text-on-surface">Blend ML predictions</span>
          <Toggle checked={config.ml_enabled} onChange={() => updateConfig({ ml_enabled: !config.ml_enabled })} />
        </div>
        {config.ml_enabled && (
          <div className="mt-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-on-surface">ML Confidence</span>
              <span className="text-sm font-mono text-primary font-bold">{config.ml_confidence_threshold}%</span>
            </div>
            <input
              type="range"
              min={50}
              max={95}
              value={config.ml_confidence_threshold}
              onChange={(e) => updateConfig({ ml_confidence_threshold: Number(e.target.value) })}
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-[10px] font-mono text-outline mt-0.5">
              <span>More signals</span>
              <span>High confidence only</span>
            </div>
            <p className="text-[10px] text-on-surface-variant mt-2">
              Blends trained LSTM predictions with rule-based scores. Train a model first via Settings.
            </p>
          </div>
        )}
      </Section>

      {/* Indicators */}
      <Section title="Indicators" collapsible summary={`ADX RSI BB OBV${config.enable_patterns ? " + Patterns" : ""}`}>
        <div className="flex gap-1.5 flex-wrap">
          {INDICATORS.map(({ key, label }) => (
            <button
              key={key}
              className="px-3 py-1.5 rounded-full text-xs font-bold bg-primary/15 text-primary border border-primary/30"
            >
              {label}
            </button>
          ))}
          <button
            onClick={() => updateConfig({ enable_patterns: !config.enable_patterns })}
            className={`px-3 py-1.5 rounded-full text-xs font-bold transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
              config.enable_patterns
                ? "bg-primary/15 text-primary border border-primary/30"
                : "bg-surface-container-lowest text-on-surface-variant border border-transparent"
            }`}
          >
            Candlestick Patterns
          </button>
        </div>
      </Section>

      {/* Risk / Levels */}
      <Section title="Risk & Levels" collapsible summary={`SL ${config.sl_atr_multiplier}x \u00b7 TP1 ${config.tp1_atr_multiplier}x \u00b7 TP2 ${config.tp2_atr_multiplier}x \u00b7 Max ${config.max_concurrent_positions}`}>
        <NumberInput
          label="SL (ATR x)"
          value={config.sl_atr_multiplier}
          step={0.1}
          min={0.5}
          max={5}
          onChange={(v) => updateConfig({ sl_atr_multiplier: v })}
        />
        <NumberInput
          label="TP1 (ATR x)"
          value={config.tp1_atr_multiplier}
          step={0.1}
          min={0.5}
          max={10}
          onChange={(v) => updateConfig({ tp1_atr_multiplier: v })}
        />
        <NumberInput
          label="TP2 (ATR x)"
          value={config.tp2_atr_multiplier}
          step={0.1}
          min={0.5}
          max={10}
          onChange={(v) => updateConfig({ tp2_atr_multiplier: v })}
        />
        <NumberInput
          label="Max Positions"
          value={config.max_concurrent_positions}
          step={1}
          min={1}
          max={10}
          onChange={(v) => updateConfig({ max_concurrent_positions: v })}
        />
      </Section>

      {/* Import Data */}
      <Section title="Historical Data" collapsible summary={importStatus ? `${importStatus.total_imported} candles imported` : "No data imported"}>
        <button
          onClick={() => setShowImport(!showImport)}
          className="text-sm text-primary underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded"
        >
          {showImport ? "Hide import" : "Import historical candles"}
        </button>
        {showImport && (
          <div className="mt-2 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm text-on-surface-variant">Lookback</span>
              <div className="flex gap-1.5">
                {[30, 90, 180, 365].map((d) => (
                  <button
                    key={d}
                    onClick={() => setImportDays(d)}
                    className={`px-2.5 py-1 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                      importDays === d
                        ? "bg-primary/15 text-primary border border-primary/30"
                        : "bg-surface-container-lowest text-on-surface-variant"
                    }`}
                  >
                    {d}d
                  </button>
                ))}
              </div>
            </div>
            <button
              onClick={() => startImport(importDays)}
              disabled={importLoading}
              className="w-full py-2 rounded-lg text-sm font-medium bg-surface-container-lowest text-on-surface border border-outline-variant/20 hover:border-primary/30 transition-colors disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
            >
              {importLoading ? "Importing..." : `Import ${importDays} days of candles`}
            </button>
            {importStatus && (
              <p className="text-xs text-on-surface-variant">
                Status: {importStatus.status} — {importStatus.total_imported} candles imported
              </p>
            )}
          </div>
        )}
      </Section>

      {/* Parameter overrides */}
      <ParameterOverridePanel
        overrides={config.parameter_overrides || {}}
        onChange={(overrides) => updateConfig({ parameter_overrides: Object.keys(overrides).length > 0 ? overrides : undefined })}
      />

      {/* Run Button */}
      <div className="pt-2">
        {runError && (
          <p className="text-xs text-error mb-2">{runError}</p>
        )}
        {isRunning ? (
          <div className="space-y-2">
            <div className="w-full h-2 bg-surface-container-lowest rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full animate-pulse motion-reduce:animate-none" style={{ width: "60%" }} />
            </div>
            <button
              onClick={cancelRun}
              className="w-full py-3 rounded-lg text-sm font-medium bg-error/15 text-error border border-error/30 transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={startRun}
            className="w-full bg-primary-container text-on-primary-fixed py-4 rounded-lg font-headline font-bold text-xs tracking-widest uppercase active:scale-[0.98] transition-transform focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
          >
            Run Backtest
          </button>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
  collapsible,
  defaultOpen = false,
  summary,
}: {
  title: string;
  children: React.ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  summary?: string;
}) {
  const [isOpen, setIsOpen] = useState(!collapsible || defaultOpen);
  const contentId = useId();

  if (!collapsible) {
    return (
      <div>
        <SectionLabel>{title}</SectionLabel>
        <div className="bg-surface-container p-5 rounded">{children}</div>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-controls={contentId}
        className="w-full flex items-center gap-2 mb-1.5 px-1 text-left focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          className={`text-on-surface-variant transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
        >
          <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <SectionLabel className="flex-1 mb-0 px-0">{title}</SectionLabel>
        {!isOpen && summary && (
          <span className="text-[10px] text-on-surface-variant/70 font-mono truncate max-w-[60%] text-right">
            {summary}
          </span>
        )}
      </button>
      <div
        id={contentId}
        role="region"
        className={`grid motion-reduce:transition-none transition-[grid-template-rows] duration-200 ease-out ${
          isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="bg-surface-container p-5 rounded">{children}</div>
        </div>
      </div>
    </div>
  );
}

function WeightSlider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="mb-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-bold text-on-surface uppercase">{label}</span>
        <span className="text-[10px] font-mono text-primary font-bold">{value}%</span>
      </div>
      <div className="relative">
        <div className="h-2 w-full bg-surface-container-lowest rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full shadow-[0_0_8px_rgba(105,218,255,0.4)]"
            style={{ width: `${value}%` }}
          />
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-primary opacity-0 absolute top-0 left-0 h-2 cursor-pointer"
        />
      </div>
    </div>
  );
}

function NumberInput({
  label,
  value,
  step,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  step: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-outline-variant/10 last:border-0">
      <span className="text-sm text-on-surface">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-20 p-1.5 bg-surface-container-lowest rounded border border-outline-variant/20 text-sm font-mono text-right focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none text-on-surface"
      />
    </div>
  );
}
