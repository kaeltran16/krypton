import { Card, ProgressBar } from "../../../shared/components";
import { formatPair } from "../../../shared/lib/format";
import type { PairSummary } from "../types";

export function PairBreakdown({ pairs }: { pairs: PairSummary[] }) {
  if (!pairs.length) return null;

  return (
    <div className="grid grid-cols-3 gap-3">
      {pairs.map((p) => (
        <Card key={p.pair} padding="sm">
          <p className="text-xs text-on-surface-variant mb-1">{formatPair(p.pair)}</p>
          <p className="text-sm font-bold text-on-surface">
            {p.emitted}
            <span className="text-on-surface-variant font-normal">/{p.total}</span>
          </p>
          <ProgressBar value={p.emission_rate * 100} height="sm" color="bg-primary" />
          <p className="text-[10px] text-on-surface-variant mt-1">
            {(p.emission_rate * 100).toFixed(1)}% rate
          </p>
        </Card>
      ))}
    </div>
  );
}
