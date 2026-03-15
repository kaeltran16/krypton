import type { DetectedPattern } from "../types";

interface PatternBadgesProps {
  patterns: DetectedPattern[];
  compact?: boolean;
}

export function PatternBadges({ patterns }: PatternBadgesProps) {
  if (!patterns.length) return null;

  return (
    <div className="flex flex-wrap gap-1">
      {patterns.map((p) => (
        <span
          key={p.name}
          className={`text-[11px] px-1.5 py-0.5 rounded-full font-medium ${
            p.bias === "bullish"
              ? "bg-long/10 text-long"
              : p.bias === "bearish"
                ? "bg-short/10 text-short"
                : "bg-card-hover text-muted"
          }`}
        >
          {p.name}
        </span>
      ))}
    </div>
  );
}

interface PatternDetailRowProps {
  patterns: DetectedPattern[];
}

export function PatternDetailRow({ patterns }: PatternDetailRowProps) {
  if (!patterns.length) return null;

  return (
    <div className="p-4 border-b border-border">
      <h3 className="text-sm text-muted mb-2">Detected Patterns</h3>
      <div className="space-y-1.5">
        {patterns.map((p) => (
          <div key={p.name} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span
                className={`text-[11px] px-1.5 py-0.5 rounded-full ${
                  p.bias === "bullish"
                    ? "bg-long/10 text-long"
                    : p.bias === "bearish"
                      ? "bg-short/10 text-short"
                      : "bg-card-hover text-muted"
                }`}
              >
                {p.bias}
              </span>
              <span className="text-foreground">{p.name}</span>
            </div>
            <span className="text-xs text-muted font-mono">+{p.strength}pts</span>
          </div>
        ))}
      </div>
    </div>
  );
}
