import type { DetectedPattern } from "../types";
import { Badge } from "../../../shared/components/Badge";

interface PatternBadgesProps {
  patterns: DetectedPattern[];
}

export function PatternBadges({ patterns }: PatternBadgesProps) {
  const visible = patterns.filter((p) => p.name?.trim());
  if (!visible.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {visible.map((p) => (
        <Badge
          key={p.name}
          color={p.bias === "bullish" ? "long" : p.bias === "bearish" ? "short" : "muted"}
          weight="medium"
          className="whitespace-nowrap px-2 py-1 gap-1"
        >
          {p.name}
        </Badge>
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
              <Badge
                color={p.bias === "bullish" ? "long" : p.bias === "bearish" ? "short" : "muted"}
                weight="medium"
                className="px-2"
              >
                {p.bias}
              </Badge>
              <span className="text-on-surface">{p.name}</span>
            </div>
            <span className="text-xs text-on-surface-variant font-mono tabular">+{p.strength}pts</span>
          </div>
        ))}
      </div>
    </div>
  );
}
