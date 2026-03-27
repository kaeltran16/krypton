import { useState } from "react";
import { useEngineStore } from "../../engine/store";

const BACKTEST_PARAMS = [
  { path: "blending.source_weights.traditional", label: "Tech Weight" },
  { path: "blending.source_weights.pattern", label: "Pattern Weight" },
  { path: "blending.thresholds.signal", label: "Signal Threshold" },
  { path: "blending.thresholds.ml_confidence", label: "ML Confidence" },
  { path: "levels.atr_defaults.sl", label: "SL ATR" },
  { path: "levels.atr_defaults.tp1", label: "TP1 ATR" },
  { path: "levels.atr_defaults.tp2", label: "TP2 ATR" },
  { path: "blending.confluence.trend_alignment_steepness", label: "Confluence Steepness" },
  { path: "blending.confluence.adx_strength_center", label: "Confluence ADX Center" },
];

interface Props {
  overrides: Record<string, number>;
  onChange: (overrides: Record<string, number>) => void;
}

export default function ParameterOverridePanel({ overrides, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const params = useEngineStore((s) => s.params);

  const getLiveValue = (path: string): number | null => {
    if (!params) return null;
    const parts = path.split(".");
    let current: any = params;
    for (const p of parts) {
      current = current?.[p];
    }
    return current?.value ?? current ?? null;
  };

  const handleChange = (path: string, value: string) => {
    const num = parseFloat(value);
    if (isNaN(num)) {
      const next = { ...overrides };
      delete next[path];
      onChange(next);
    } else {
      onChange({ ...overrides, [path]: num });
    }
  };

  return (
    <div className="border border-outline-variant/30 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-surface-container/50"
      >
        <span className="text-xs font-medium text-on-surface-variant">Advanced: Parameter Overrides</span>
        <span className="text-on-surface-variant text-xs">{open ? "\u2212" : "+"}</span>
      </button>
      {open && (
        <div className="p-3 space-y-2">
          {BACKTEST_PARAMS.map(({ path, label }) => {
            const live = getLiveValue(path);
            const edited = path in overrides;
            return (
              <div key={path} className="flex items-center justify-between">
                <span className={`text-xs ${edited ? "text-on-surface" : "text-on-surface-variant"}`}>{label}</span>
                <input
                  type="number"
                  step="any"
                  placeholder={live?.toString() ?? ""}
                  value={overrides[path] ?? ""}
                  onChange={(e) => handleChange(path, e.target.value)}
                  className={`w-20 text-right text-xs font-mono px-2 py-1 bg-surface-container border rounded ${
                    edited ? "border-primary text-primary" : "border-outline-variant text-on-surface-variant"
                  }`}
                />
              </div>
            );
          })}
          <button
            onClick={() => onChange({})}
            className="text-xs text-on-surface-variant hover:text-on-surface"
          >
            Reset to Live
          </button>
        </div>
      )}
    </div>
  );
}
