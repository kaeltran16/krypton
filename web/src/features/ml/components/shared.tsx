import type { MLTrainJob } from "../../../shared/lib/api";

export const TIMEFRAMES = ["15m", "1h", "4h"] as const;

export function formatPairSlug(slug: string) {
  return slug.replace("_", "-").toUpperCase();
}

export function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-2 px-1 text-on-surface-variant">{title}</h2>
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden">
        {children}
      </div>
    </div>
  );
}

export function ConfigField({ label, value, children }: {
  label: string;
  value?: string | number;
  children: React.ReactNode;
}) {
  return (
    <div className="px-3 py-3 border-b border-outline-variant/10 last:border-b-0">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-on-surface">{label}</span>
        {value !== undefined && (
          <span className="text-xs text-primary font-mono">{typeof value === "number" && value < 1 ? value.toFixed(4) : value}</span>
        )}
      </div>
      {children}
    </div>
  );
}

export function Slider({ min, max, step = 1, value = 0, onChange, format }: {
  min: number;
  max: number;
  step?: number;
  value?: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
      <div className="flex justify-between text-[10px] text-outline mt-0.5">
        <span>{format ? format(min) : min}</span>
        <span>{format ? format(max) : max}</span>
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: MLTrainJob["status"] }) {
  const colors =
    status === "completed" ? "bg-tertiary-dim/15 text-tertiary-dim" :
    status === "failed" ? "bg-error/15 text-error" :
    status === "cancelled" ? "bg-outline/15 text-on-surface-variant" :
    "bg-primary/15 text-primary";

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors}`}>
      {status}
    </span>
  );
}
