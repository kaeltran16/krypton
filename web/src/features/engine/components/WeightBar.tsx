const COLORS = ["#F0B90B", "#0ECB81", "#3B82F6", "#A855F7"];

interface Props {
  weights: Record<string, { value: unknown; source: string }>;
}

export default function WeightBar({ weights }: Props) {
  const entries = Object.entries(weights);
  return (
    <div className="px-3 py-2">
      <div className="flex h-5 rounded overflow-hidden">
        {entries.map(([name, w], i) => {
          const v = Number(w.value);
          return (
            <div
              key={name}
              style={{ width: `${v * 100}%`, backgroundColor: COLORS[i % COLORS.length] }}
              className="flex items-center justify-center text-[9px] font-medium text-black"
              title={`${name}: ${(v * 100).toFixed(0)}%`}
            >
              {(v * 100).toFixed(0)}%
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-1">
        {entries.map(([name], i) => (
          <span key={name} className="text-[10px] text-muted" style={{ color: COLORS[i % COLORS.length] }}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
