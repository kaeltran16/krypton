import { useId } from "react";
import { theme } from "../../../shared/theme";

interface MiniSparklineProps {
  data: number[];
  width?: number;
  height?: number;
  className?: string;
}

export function MiniSparkline({ data, width = 80, height = 24, className = "" }: MiniSparklineProps) {
  const gradId = useId();

  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 1;

  const points = data
    .map((v, i) => {
      const x = pad + (i / (data.length - 1)) * (width - pad * 2);
      const y = pad + (height - pad * 2) - ((v - min) / range) * (height - pad * 2);
      return `${x},${y}`;
    })
    .join(" ");

  const last = data[data.length - 1];
  const isPositive = last >= data[0];
  const color = isPositive ? theme.colors.long : theme.colors.short;

  const areaPoints = `${pad},${height - pad} ${points} ${width - pad},${height - pad}`;

  return (
    <svg
      aria-hidden="true"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={className}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon fill={`url(#${gradId})`} points={areaPoints} />
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" points={points} />
    </svg>
  );
}
