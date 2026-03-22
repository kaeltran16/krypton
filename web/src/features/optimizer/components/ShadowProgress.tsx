import type { ShadowProgress as ShadowProgressType, ProposalChange } from "../types";

interface Props {
  group: string;
  progress: ShadowProgressType;
  changes: Record<string, ProposalChange>;
}

export default function ShadowProgress({ group, progress }: Props) {
  const pct = progress.target > 0 ? (progress.resolved / progress.target) * 100 : 0;

  return (
    <div className="border border-blue-500/20 rounded-xl bg-surface-container-low p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-widest text-blue-400">
          Shadow Mode Active
        </div>
        <span className="text-xs text-on-surface font-mono">
          {progress.resolved}/{progress.target}
        </span>
      </div>
      <div className="text-xs text-muted">{group.replace(/_/g, " ")}</div>
      <div className="h-2 bg-surface-container rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 transition-all duration-300 rounded-full"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <div className="text-[10px] text-muted text-center">
        {progress.complete ? "Evaluation complete \u2014 awaiting decision" : "Collecting signal results..."}
      </div>
    </div>
  );
}
