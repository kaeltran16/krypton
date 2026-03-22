const COLORS = ["#F0B90B", "#0ECB81", "#3B82F6", "#A855F7"];

interface Props {
  weights: Record<string, { value: unknown; source: string }>;
}

export default function WeightBar({ weights }: Props) {
  const items = Object.entries(weights).map(([name, w], i) => ({
    name,
    pct: Number(w.value) * 100,
    color: COLORS[i % COLORS.length],
  }));

  const ariaLabel = "Source weights: " +
    items.map((it) => `${it.name} ${it.pct.toFixed(0)}%`).join(", ");

  return (
    <div className="px-3 py-2">
      <div className="flex h-5 rounded overflow-hidden" role="img" aria-label={ariaLabel}>
        {items.map((it) => (
          <div
            key={it.name}
            style={{ width: `${it.pct}%`, backgroundColor: it.color }}
            className="h-full"
          />
        ))}
      </div>
      <div className="flex justify-between mt-1">
        {items.map((it) => (
          <span key={it.name} className="text-[10px]" style={{ color: it.color }}>
            {it.name} ({it.pct.toFixed(0)}%)
          </span>
        ))}
      </div>
    </div>
  );
}
