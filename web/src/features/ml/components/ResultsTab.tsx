import { useState, useMemo } from "react";
import type { MLTrainJob, MLTrainResult } from "../../../shared/lib/api";
import { Button } from "../../../shared/components/Button";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { Toggle } from "../../../shared/components/Toggle";
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
  const [compareMode, setCompareMode] = useState(false);
  const [compareBId, setCompareBId] = useState<string>("");
  const [selectedPair, setSelectedPair] = useState<string>("");

  const completedRuns = useMemo(
    () => history.filter((j) => j.status === "completed" && j.result),
    [history],
  );

  const runA = selectedJobId
    ? completedRuns.find((r) => r.job_id === selectedJobId) ?? completedRuns[0]
    : completedRuns[0];

  const runB = compareMode
    ? completedRuns.find((r) => r.job_id === compareBId) ?? null
    : null;

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
      {/* Header with compare toggle */}
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-headline font-bold uppercase tracking-wider text-on-surface-variant">
          {selectedJobId ? `Run ${runA.job_id}` : "Latest Run"}
        </h2>
        {completedRuns.length >= 2 && (
          <div className="flex items-center gap-1 text-xs text-on-surface-variant">
            <span>Compare</span>
            <Toggle
              checked={compareMode}
              onChange={(v) => {
                setCompareMode(v);
                if (v && !compareBId && completedRuns.length > 1) {
                  setCompareBId(completedRuns[1].job_id);
                }
              }}
            />
          </div>
        )}
      </div>

      {/* Compare mode: run selectors */}
      {compareMode && (
        <div className="flex gap-2">
          <Card border={false} padding="sm" className="flex-1 border-2 border-primary/30">
            <p className="text-[10px] text-primary font-medium mb-1">Run A (Latest)</p>
            <p className="text-xs font-mono text-on-surface-variant">{runA.job_id}</p>
          </Card>
          <Card border={false} padding="sm" className="flex-1 border-2 border-purple/30">
            <p className="text-[10px] text-purple font-medium mb-1">Run B</p>
            <select
              value={compareBId}
              onChange={(e) => setCompareBId(e.target.value)}
              className="w-full bg-transparent text-xs font-mono text-on-surface-variant outline-none"
            >
              {completedRuns.filter((r) => r.job_id !== runA.job_id).map((r) => (
                <option key={r.job_id} value={r.job_id}>{r.job_id}</option>
              ))}
            </select>
          </Card>
        </div>
      )}

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

      {!compareMode && pairA ? (
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

          {/* Config used */}
          {runA.params && (
            <Card padding="sm">
              <SectionLabel>Config Used</SectionLabel>
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
          )}

          {/* Loss curve from completed result */}
          {pairA.loss_history && pairA.loss_history.length > 0 && (
            <Card padding="sm">
              <SectionLabel>Loss Curve</SectionLabel>
              <LossChart data={pairA.loss_history} bestEpoch={pairA.best_epoch} height={180} />
            </Card>
          )}
        </>
      ) : compareMode && runB ? (
        <CompareView runA={runA} runB={runB} pair={activePair} />
      ) : compareMode ? (
        <p className="text-xs text-on-surface-variant text-center py-4">Select Run B to compare.</p>
      ) : null}
    </div>
  );
}

function CompareView({ runA, runB, pair }: { runA: MLTrainJob; runB: MLTrainJob; pair: string }) {
  const a = (runA.result as Record<string, MLTrainResult>)?.[pair];
  const b = (runB.result as Record<string, MLTrainResult>)?.[pair];

  if (!a || !b) {
    return <p className="text-xs text-on-surface-variant text-center py-4">Pair not available in both runs.</p>;
  }

  type MetricRow = { label: string; valA: string; valB: string; aWins: boolean | null };

  const metrics: MetricRow[] = [
    {
      label: "Val Loss",
      valA: a.best_val_loss?.toFixed(4) ?? "—",
      valB: b.best_val_loss?.toFixed(4) ?? "—",
      aWins: a.best_val_loss != null && b.best_val_loss != null ? a.best_val_loss < b.best_val_loss : null,
    },
    {
      label: "Dir. Accuracy",
      valA: a.direction_accuracy != null ? `${(a.direction_accuracy * 100).toFixed(1)}%` : "—",
      valB: b.direction_accuracy != null ? `${(b.direction_accuracy * 100).toFixed(1)}%` : "—",
      aWins: a.direction_accuracy != null && b.direction_accuracy != null ? a.direction_accuracy > b.direction_accuracy : null,
    },
    {
      label: "Long Precision",
      valA: a.precision_per_class ? `${(a.precision_per_class.long * 100).toFixed(1)}%` : "—",
      valB: b.precision_per_class ? `${(b.precision_per_class.long * 100).toFixed(1)}%` : "—",
      aWins: a.precision_per_class && b.precision_per_class ? a.precision_per_class.long > b.precision_per_class.long : null,
    },
    {
      label: "Short Precision",
      valA: a.precision_per_class ? `${(a.precision_per_class.short * 100).toFixed(1)}%` : "—",
      valB: b.precision_per_class ? `${(b.precision_per_class.short * 100).toFixed(1)}%` : "—",
      aWins: a.precision_per_class && b.precision_per_class ? a.precision_per_class.short > b.precision_per_class.short : null,
    },
    {
      label: "Best Epoch",
      valA: String(a.best_epoch ?? "—"),
      valB: String(b.best_epoch ?? "—"),
      aWins: null, // Not a "better" metric
    },
    {
      label: "Flow Data",
      valA: a.flow_data_used ? "Yes" : "No",
      valB: b.flow_data_used ? "Yes" : "No",
      aWins: null,
    },
  ];

  const aWinCount = metrics.filter((m) => m.aWins === true).length;
  const totalComparable = metrics.filter((m) => m.aWins !== null).length;

  // Config diff
  const paramsA = runA.params || {};
  const paramsB = runB.params || {};
  const allKeys = [...new Set([...Object.keys(paramsA), ...Object.keys(paramsB)])];
  const diffs = allKeys.filter((k) => (paramsA as any)[k] !== (paramsB as any)[k]);

  return (
    <div className="space-y-4">
      {/* Metrics comparison table */}
      <Card padding="none" className="overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-outline-variant/10">
              <th className="px-3 py-2 text-left text-on-surface-variant font-medium">Metric</th>
              <th className="px-3 py-2 text-right font-medium text-primary">Run A</th>
              <th className="px-3 py-2 text-right font-medium text-purple">Run B</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m.label} className="border-b border-outline-variant/10 last:border-b-0">
                <td className="px-3 py-2 text-on-surface-variant">{m.label}</td>
                <td className={`px-3 py-2 text-right font-mono ${m.aWins === true ? "text-primary font-bold" : "text-on-surface"}`}>
                  {m.valA}
                </td>
                <td className={`px-3 py-2 text-right font-mono ${m.aWins === false ? "text-purple font-bold" : "text-on-surface"}`}>
                  {m.valB}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Config diff */}
      {diffs.length > 0 && (
        <Card padding="sm">
          <SectionLabel>Config Differences</SectionLabel>
          <div className="space-y-1 text-xs">
            {diffs.map((key) => (
              <div key={key} className="flex justify-between">
                <span className="text-on-surface-variant">{key}</span>
                <div className="flex gap-3">
                  <span className="font-mono text-primary">{String((paramsA as any)[key] ?? "—")}</span>
                  <span className="text-on-surface-variant">vs</span>
                  <span className="font-mono text-purple">{String((paramsB as any)[key] ?? "—")}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Summary */}
      <p className="text-xs text-on-surface-variant text-center">
        Run A wins on {aWinCount}/{totalComparable} metrics.
      </p>
    </div>
  );
}
