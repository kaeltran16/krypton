import { MetricCard } from "../../../shared/components";
import type { MonitorSummary } from "../types";

export function SummaryCards({ summary }: { summary: MonitorSummary | null }) {
  if (!summary) return null;

  return (
    <div className="grid grid-cols-3 gap-3">
      <MetricCard label="Evaluations" value={summary.total_evaluations} />
      <MetricCard
        label="Emitted"
        value={`${summary.emitted_count} (${(summary.emission_rate * 100).toFixed(1)}%)`}
        accent="long"
      />
      <MetricCard label="Avg |Score|" value={summary.avg_abs_score.toFixed(1)} />
    </div>
  );
}
