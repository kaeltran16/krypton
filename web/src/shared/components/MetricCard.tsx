import { Card } from "./Card";
import type { ComponentProps } from "react";

type Accent = ComponentProps<typeof Card>["accent"];

interface MetricCardProps {
  label: string;
  value: string | number;
  color?: string;
  size?: "sm" | "md" | "lg";
  accent?: Accent;
  className?: string;
}

const sizeMap = {
  sm: "text-sm",
  md: "text-lg",
  lg: "text-2xl",
};

export function MetricCard({
  label,
  value,
  color = "text-on-surface",
  size = "sm",
  accent,
  className = "",
}: MetricCardProps) {
  return (
    <Card variant="low" padding="sm" border={false} accent={accent} className={className}>
      <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
        {label}
      </p>
      <p className={`font-headline font-bold tabular-nums mt-1 ${sizeMap[size]} ${color}`}>
        {value}
      </p>
    </Card>
  );
}
