import { hapticTap } from "../lib/haptics";

interface PillSelectProps<T extends string | number> {
  options: readonly T[];
  selected: T | readonly T[];
  onToggle: (value: T) => void;
  multi?: boolean;
  renderLabel?: (value: T) => string;
  size?: "sm" | "md";
  equalWidth?: boolean;
  wrap?: boolean;
  className?: string;
}

export function PillSelect<T extends string | number>({
  options,
  selected,
  onToggle,
  multi = false,
  renderLabel,
  size = "md",
  equalWidth = false,
  wrap = false,
  className = "",
}: PillSelectProps<T>) {
  const isActive = (v: T) =>
    multi ? (selected as readonly T[]).includes(v) : selected === v;

  const sizeStyles = size === "sm"
    ? "px-3 py-1.5 text-xs min-h-[36px]"
    : "px-4 min-h-[44px] py-2 text-sm";

  const gapClass = size === "sm" ? "gap-1.5" : "gap-3";

  return (
    <div className={`flex ${wrap ? "flex-wrap" : ""} ${gapClass} ${className}`}>
      {options.map((opt) => (
        <button
          key={String(opt)}
          type="button"
          onClick={() => {
            hapticTap();
            onToggle(opt);
          }}
          className={[
            sizeStyles,
            equalWidth ? "flex-1" : "",
            "font-medium rounded-lg border transition-colors",
            "focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none",
            isActive(opt)
              ? "bg-primary/15 text-primary border-primary/30 font-bold"
              : size === "sm"
                ? "bg-transparent text-on-surface-variant border-outline-variant/30"
                : "bg-surface-container-lowest text-on-surface-variant border-transparent",
          ].join(" ")}
        >
          {renderLabel ? renderLabel(opt) : String(opt)}
        </button>
      ))}
    </div>
  );
}
