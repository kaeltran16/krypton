import { useState } from "react";
import { api } from "../../../shared/lib/api";
import ApplyModal from "./ApplyModal";
import type { AtrOptimizationResult } from "../../engine/types";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { Dropdown } from "../../../shared/components/Dropdown";

const TIMEFRAMES = ["15m", "1h", "4h", "1D"];

export default function OptimizeTab() {
  const [pair, setPair] = useState<string>(AVAILABLE_PAIRS[0]);
  const [timeframe, setTimeframe] = useState(TIMEFRAMES[1]);
  const [atrResult, setAtrResult] = useState<AtrOptimizationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showApply, setShowApply] = useState(false);
  const [applyChanges, setApplyChanges] = useState<Record<string, number>>({});

  const runAtrOptimize = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.optimizeAtr(pair, timeframe);
      setAtrResult(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleApplyAtr = () => {
    if (!atrResult) return;
    setApplyChanges({
      [`learned_atr.${pair}.${timeframe}.current_sl_atr`]: atrResult.proposed.sl_atr,
      [`learned_atr.${pair}.${timeframe}.current_tp1_atr`]: atrResult.proposed.tp1_atr,
      [`learned_atr.${pair}.${timeframe}.current_tp2_atr`]: atrResult.proposed.tp2_atr,
    });
    setShowApply(true);
  };

  return (
    <div className="p-3 space-y-4">
      <div className="flex gap-2">
        <Dropdown
          value={pair}
          onChange={setPair}
          options={AVAILABLE_PAIRS.map((p) => ({ value: p, label: p }))}
          size="sm"
          fullWidth={false}
          ariaLabel="Select pair"
        />
        <Dropdown
          value={timeframe}
          onChange={setTimeframe}
          options={TIMEFRAMES.map((tf) => ({ value: tf, label: tf }))}
          size="sm"
          fullWidth={false}
          ariaLabel="Select timeframe"
        />
      </div>

      <div className="border border-outline-variant/30 rounded-lg p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-medium">ATR Optimization</h4>
          <button onClick={runAtrOptimize} disabled={loading}
            className="px-3 py-1.5 text-xs bg-primary/15 text-primary rounded-lg disabled:opacity-50">
            {loading ? "Running..." : "Optimize"}
          </button>
        </div>

        {error && <p className="text-xs text-error">{error}</p>}

        {atrResult && (
          <div className="space-y-2">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-on-surface-variant border-b border-outline-variant">
                  <th className="text-left py-1"></th>
                  <th className="text-right py-1">Current</th>
                  <th className="text-right py-1">Proposed</th>
                </tr>
              </thead>
              <tbody>
                {(["sl_atr", "tp1_atr", "tp2_atr"] as const).map((k) => (
                  <tr key={k} className="border-b border-outline-variant/10">
                    <td className="py-1.5 text-on-surface-variant">{k}</td>
                    <td className="text-right py-1.5 font-mono">{atrResult.current[k].toFixed(2)}</td>
                    <td className="text-right py-1.5 font-mono text-primary">{atrResult.proposed[k].toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="text-xs text-on-surface-variant">
              {atrResult.metrics.signals_analyzed} signals analyzed |
              Sortino: {atrResult.metrics.current_sortino?.toFixed(2) ?? "\u2014"} {"\u2192"} {atrResult.metrics.proposed_sortino?.toFixed(2) ?? "\u2014"}
            </div>
            <button onClick={handleApplyAtr}
              className="text-xs text-primary hover:text-primary/80">
              Apply to Live
            </button>
          </div>
        )}
      </div>

      {showApply && (
        <ApplyModal changes={applyChanges} onClose={() => setShowApply(false)} />
      )}
    </div>
  );
}
