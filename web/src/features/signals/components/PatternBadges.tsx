import type { DetectedPattern } from "../types";

interface PatternBadgesProps {
  patterns: DetectedPattern[];
}

export function PatternBadges({ patterns }: PatternBadgesProps) {
  const visible = patterns.filter((p) => p.name?.trim());
  if (!visible.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {visible.map((p) => (
        <span
          key={p.name}
          className={`flex items-center gap-1 whitespace-nowrap bg-surface-container-highest px-2 py-1 rounded text-xs font-medium ${
            p.bias === "bullish"
              ? "text-long"
              : p.bias === "bearish"
                ? "text-short"
                : "text-on-surface"
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
    <div className="p-4 border-b border-outline-variant/10">
      <h3 className="text-xs uppercase tracking-widest text-on-surface-variant mb-3">Detected Patterns</h3>
      <div className="space-y-1.5">
        {patterns.map((p) => (
          <div key={p.name} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span
                className={`text-xs px-2 py-0.5 rounded ${
                  p.bias === "bullish"
                    ? "bg-long/10 text-long"
                    : p.bias === "bearish"
                      ? "bg-short/10 text-short"
                      : "bg-surface-container-highest text-on-surface-variant"
                }`}
              >
                {p.bias}
              </span>
              <span className="text-on-surface">{p.name}</span>
            </div>
            <span className="text-xs text-on-surface-variant font-mono tabular">+{p.strength}pts</span>
          </div>
        ))}
      </div>
    </div>
  );
}
