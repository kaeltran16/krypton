import type { MLTrainJob } from "../../../shared/lib/api";
import { Card } from "../../../shared/components/Card";
import { Badge } from "../../../shared/components/Badge";
import { SectionLabel } from "../../../shared/components/SectionLabel";

export const TIMEFRAMES = ["15m", "1h", "4h"] as const;

export function formatPairSlug(slug: string) {
  return slug.replace("_", "-").toUpperCase();
}

export function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <SectionLabel as="h2">{title}</SectionLabel>
      <Card padding="none" className="overflow-hidden">
        {children}
      </Card>
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
  const color =
    status === "completed" ? "tertiary" :
    status === "failed" ? "error" :
    status === "cancelled" ? "muted" :
    "primary";

  return (
    <Badge color={color} weight="medium" className="px-2">
      {status}
    </Badge>
  );
}
