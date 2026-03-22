import { hapticTap } from "../lib/haptics";

interface SegmentedControlProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  fullWidth?: boolean;
  variant?: "pill" | "underline";
  compact?: boolean;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  fullWidth = false,
  variant = "pill",
  compact = false,
}: SegmentedControlProps<T>) {
  const isUnderline = variant === "underline";

  return (
    <div
      className={`flex ${isUnderline ? "gap-4" : "gap-1 bg-surface-container p-1 rounded-lg"} ${fullWidth ? "w-full" : "w-fit"}`}
    >
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            aria-pressed={active}
            onClick={() => {
              if (!active) {
                hapticTap();
                onChange(opt.value);
              }
            }}
            className={`${compact ? "min-h-[36px]" : "min-h-[44px]"} transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              fullWidth ? "flex-1 text-center" : ""
            } ${
              isUnderline
                ? `pb-1 text-sm font-semibold border-b-2 ${active ? "text-on-surface border-primary" : "text-on-surface-variant border-transparent"}`
                : `px-4 ${compact ? "text-[11px]" : "text-xs"} font-semibold rounded ${active ? "bg-primary/15 text-primary shadow-sm" : "text-on-surface-variant hover:text-on-surface"}`
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
