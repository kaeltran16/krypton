import { useState } from "react";
import { useBacktestStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";

const TIMEFRAMES = ["15m", "1h", "4h"] as const;

const INDICATORS = [
  { key: "ema", label: "EMA" },
  { key: "macd", label: "MACD" },
  { key: "rsi", label: "RSI" },
  { key: "bb", label: "BB" },
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
        <div className="flex gap-1.5">
          {AVAILABLE_PAIRS.map((pair) => (
            <button
              key={pair}
              onClick={() => {
                const next = config.pairs.includes(pair)
                  ? config.pairs.filter((p) => p !== pair)
                  : [...config.pairs, pair];
                if (next.length > 0) updateConfig({ pairs: next });
              }}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                config.pairs.includes(pair)
                  ? "bg-accent/15 text-accent border border-accent/30"
                  : "bg-card-hover text-muted"
              }`}
            >
              {pair.replace("-USDT-SWAP", "")}
            </button>
          ))}
        </div>
      </Section>

      {/* Timeframe */}
      <Section title="Timeframe">
        <div className="flex gap-1.5">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => updateConfig({ timeframe: tf })}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                config.timeframe === tf
                  ? "bg-accent/15 text-accent border border-accent/30"
                  : "bg-card-hover text-muted"
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
            <label className="text-[10px] text-dim uppercase tracking-wider">From</label>
            <input
              type="date"
              value={config.date_from}
              onChange={(e) => updateConfig({ date_from: e.target.value })}
              className="w-full mt-1 p-2 bg-card-hover rounded-lg border border-border text-sm font-mono focus:border-accent/50 focus:outline-none text-foreground"
            />
          </div>
          <div className="flex-1">
            <label className="text-[10px] text-dim uppercase tracking-wider">To</label>
            <input
              type="date"
              value={config.date_to}
              onChange={(e) => updateConfig({ date_to: e.target.value })}
              className="w-full mt-1 p-2 bg-card-hover rounded-lg border border-border text-sm font-mono focus:border-accent/50 focus:outline-none text-foreground"
            />
          </div>
        </div>
      </Section>

      {/* Scoring Weights */}
      <Section title="Scoring Weights">
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
            <span className="text-sm text-muted">Order Flow</span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-dim font-mono">N/A</span>
              <span className="text-[10px] text-dim" title="Historical data unavailable">
                ⓘ
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted">On-Chain</span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-dim font-mono">N/A</span>
              <span className="text-[10px] text-dim" title="Historical data unavailable">
                ⓘ
              </span>
            </div>
          </div>
        </div>
      </Section>

      {/* Thresholds */}
      <Section title="Thresholds">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm">Signal Threshold</span>
          <span className="text-sm font-mono text-accent">{config.signal_threshold}</span>
        </div>
        <input
          type="range"
          min={10}
          max={100}
          value={config.signal_threshold}
          onChange={(e) => updateConfig({ signal_threshold: Number(e.target.value) })}
          className="w-full accent-accent"
        />
        <div className="flex justify-between text-[10px] text-dim mt-0.5">
          <span>More signals</span>
          <span>Strong only</span>
        </div>
      </Section>

      {/* Indicators */}
      <Section title="Indicators">
        <div className="flex gap-1.5 flex-wrap">
          {INDICATORS.map(({ key, label }) => (
            <button
              key={key}
              className="px-3 py-1.5 rounded-full text-xs font-medium bg-accent/15 text-accent border border-accent/30"
            >
              {label}
            </button>
          ))}
          <button
            onClick={() => updateConfig({ enable_patterns: !config.enable_patterns })}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              config.enable_patterns
                ? "bg-accent/15 text-accent border border-accent/30"
                : "bg-card-hover text-muted border border-transparent"
            }`}
          >
            Candlestick Patterns
          </button>
        </div>
      </Section>

      {/* Risk / Levels */}
      <Section title="Risk & Levels">
        <NumberInput
          label="SL (ATR ×)"
          value={config.sl_atr_multiplier}
          step={0.1}
          min={0.5}
          max={5}
          onChange={(v) => updateConfig({ sl_atr_multiplier: v })}
        />
        <NumberInput
          label="TP1 (ATR ×)"
          value={config.tp1_atr_multiplier}
          step={0.1}
          min={0.5}
          max={10}
          onChange={(v) => updateConfig({ tp1_atr_multiplier: v })}
        />
        <NumberInput
          label="TP2 (ATR ×)"
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
      <Section title="Historical Data">
        <button
          onClick={() => setShowImport(!showImport)}
          className="text-sm text-accent underline underline-offset-2"
        >
          {showImport ? "Hide import" : "Import historical candles"}
        </button>
        {showImport && (
          <div className="mt-2 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted">Lookback</span>
              <div className="flex gap-1.5">
                {[30, 90, 180, 365].map((d) => (
                  <button
                    key={d}
                    onClick={() => setImportDays(d)}
                    className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
                      importDays === d
                        ? "bg-accent/15 text-accent border border-accent/30"
                        : "bg-card-hover text-muted"
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
              className="w-full py-2 rounded-lg text-sm font-medium bg-card-hover text-foreground border border-border hover:border-accent/30 transition-colors disabled:opacity-50"
            >
              {importLoading ? "Importing..." : `Import ${importDays} days of candles`}
            </button>
            {importStatus && (
              <p className="text-xs text-muted">
                Status: {importStatus.status} — {importStatus.total_imported} candles imported
              </p>
            )}
          </div>
        )}
      </Section>

      {/* Run Button */}
      <div className="pt-2">
        {runError && (
          <p className="text-xs text-short mb-2">{runError}</p>
        )}
        {isRunning ? (
          <div className="space-y-2">
            <div className="w-full h-2 bg-card-hover rounded-full overflow-hidden">
              <div className="h-full bg-accent rounded-full animate-pulse" style={{ width: "60%" }} />
            </div>
            <button
              onClick={cancelRun}
              className="w-full py-3 rounded-lg text-sm font-medium bg-short/15 text-short border border-short/30 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={startRun}
            className="w-full py-3 rounded-lg text-sm font-semibold bg-accent text-surface transition-colors hover:bg-accent/90"
          >
            Run Backtest
          </button>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">{title}</h3>
      <div className="bg-card rounded-lg border border-border p-3">{children}</div>
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
        <span className="text-sm">{label}</span>
        <span className="text-sm font-mono text-accent">{value}%</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-accent"
      />
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
    <div className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
      <span className="text-sm">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-20 p-1.5 bg-card-hover rounded-lg border border-border text-sm font-mono text-right focus:border-accent/50 focus:outline-none text-foreground"
      />
    </div>
  );
}
