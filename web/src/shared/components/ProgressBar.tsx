interface ProgressBarProps {
  value: number;
  color?: string;
  glow?: boolean;
  height?: "sm" | "md";
  label?: string;
  track?: string;
  className?: string;
}

export function ProgressBar({
  value,
  color = "bg-primary",
  glow = false,
  height = "md",
  label,
  track = "bg-surface-container-lowest",
  className = "",
}: ProgressBarProps) {
  const clamped = Math.min(Math.max(value, 0), 100);
  const h = height === "sm" ? "h-1" : "h-1.5";

  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className={[h, "w-full rounded-full overflow-hidden", track, className]
        .filter(Boolean)
        .join(" ")}
    >
      <div
        className={[
          "h-full rounded-full transition-all",
          color,
          glow ? "shadow-[0_0_8px] shadow-primary/40" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
