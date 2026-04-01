import { useState, useMemo } from "react";
import type { MLTrainJob, MLTrainResult } from "../../../shared/lib/api";
import { Button } from "../../../shared/components/Button";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { LossChart } from "./LossChart";
import { formatPairSlug } from "./shared";
import { Card } from "../../../shared/components/Card";
import { MetricCard } from "../../../shared/components/MetricCard";
import { SectionLabel } from "../../../shared/components/SectionLabel";

interface ResultsTabProps {
  history: MLTrainJob[];
  onSwitchToSetup: () => void;
  /** When set, show this run instead of latest */
  selectedJobId?: string | null;
}

export function ResultsTab({ history, onSwitchToSetup, selectedJobId }: ResultsTabProps) {
  const [selectedPair, setSelectedPair] = useState<string>("");
  const [showConfig, setShowConfig] = useState(false);

  const completedRuns = useMemo(
    () => history.filter((j) => j.status === "completed" && j.result),
    [history],
  );

  const runA = selectedJobId
    ? completedRuns.find((r) => r.job_id === selectedJobId) ?? completedRuns[0]
    : completedRuns[0];

  if (!runA) {
    return (
      <Card className="text-center" padding="lg">
        <p className="text-sm text-on-surface-variant mb-4">No training results yet</p>
        <Button onClick={onSwitchToSetup}>
          Go to Setup
        </Button>
      </Card>
    );
  }

  const resultA = runA.result as Record<string, MLTrainResult>;
  const pairs = Object.keys(resultA);
  const activePair = selectedPair || pairs[0] || "";
  const pairA = resultA[activePair];

  return (
    <div className="space-y-4">
      {/* Header */}
      <h2 className="text-xs font-headline font-bold uppercase tracking-wider text-on-surface-variant">
        {selectedJobId ? `Run ${runA.job_id}` : "Latest Run"}
      </h2>

      {/* Pair selector */}
      {pairs.length > 1 && (
        <div className="overflow-x-auto">
          <SegmentedControl
            options={pairs.map((p) => ({ value: p, label: formatPairSlug(p) }))}
            value={activePair}
            onChange={setSelectedPair}
            variant="underline"
          />
        </div>
      )}

      {pairA && (
        <>
          {/* Performance summary */}
          <div className="grid grid-cols-3 gap-2">
            <MetricCard label="Val Loss" value={pairA.best_val_loss?.toFixed(4) ?? "—"} />
            <MetricCard label="Dir. Accuracy" value={pairA.direction_accuracy != null ? `${(pairA.direction_accuracy * 100).toFixed(1)}%` : "—"} />
            <MetricCard label="Samples" value={pairA.total_samples?.toLocaleString() ?? "—"} />
          </div>

          {/* Classification metrics table */}
          {pairA.precision_per_class && pairA.recall_per_class && (
            <Card padding="none" className="overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-outline-variant/10">
                    <th className="px-3 py-2 text-left text-on-surface-variant font-medium">Class</th>
                    <th className="px-3 py-2 text-right text-on-surface-variant font-medium">Precision</th>
                    <th className="px-3 py-2 text-right text-on-surface-variant font-medium">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  {([
                    { key: "long" as const, icon: "↑", color: "text-long" },
                    { key: "short" as const, icon: "↓", color: "text-short" },
                    { key: "neutral" as const, icon: "—", color: "text-muted" },
                  ]).map((cls) => (
                    <tr key={cls.key} className="border-b border-outline-variant/10 last:border-b-0">
                      <td className="px-3 py-2">
                        <span className={cls.color}>{cls.icon}</span>
                        <span className="ml-1.5 text-on-surface capitalize">{cls.key}</span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-on-surface">
                        {(pairA.precision_per_class![cls.key] * 100).toFixed(1)}%
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-on-surface">
                        {(pairA.recall_per_class![cls.key] * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          {runA.params && (
            <>
              <button
                onClick={() => setShowConfig(!showConfig)}
                className="w-full flex items-center justify-between text-xs text-muted py-2"
              >
                <span>Training Config</span>
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className={`transition-transform ${showConfig ? "rotate-180" : ""}`}
                >
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </button>
              <div className={`grid transition-[grid-template-rows] duration-200 ${showConfig ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
                <div className="overflow-hidden">
                  <Card padding="sm">
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                      {Object.entries(runA.params).map(([key, val]) => (
                        <div key={key} className="flex justify-between">
                          <span className="text-on-surface-variant">{key}</span>
                          <span className="font-mono text-on-surface">{typeof val === "number" && val < 1 ? val.toFixed(4) : String(val)}</span>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-1.5 mt-2 flex-wrap">
                      {pairA.flow_data_used && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/15 text-primary">Flow Used</span>
                      )}
                      {pairA.best_epoch && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant">Best Epoch: {pairA.best_epoch}</span>
                      )}
                      {pairA.version && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant">v{pairA.version}</span>
                      )}
                    </div>
                  </Card>
                </div>
              </div>
            </>
          )}

          {/* Loss curve from completed result */}
          {pairA.loss_history && pairA.loss_history.length > 0 && (
            <Card padding="sm">
              <SectionLabel>Loss Curve</SectionLabel>
              <LossChart data={pairA.loss_history} bestEpoch={pairA.best_epoch} height={240} />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
