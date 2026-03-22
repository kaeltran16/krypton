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
  const activeIndex = options.findIndex((o) => o.value === value);

  if (isUnderline) {
    return (
      <div className={`flex gap-4 ${fullWidth ? "w-full" : "w-fit"}`}>
        {options.map((opt) => {
          const active = value === opt.value;
          return (
            <button
              key={opt.value}
              aria-pressed={active}
              onClick={() => {
                if (!active) { hapticTap(); onChange(opt.value); }
              }}
              className={`${compact ? "min-h-[36px]" : "min-h-[44px]"} pb-1 text-sm font-semibold border-b-2 transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                fullWidth ? "flex-1 text-center" : ""
              } ${active ? "text-on-surface border-primary" : "text-on-surface-variant border-transparent"}`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div
      className={`relative grid bg-surface-container p-1 rounded-xl ${fullWidth ? "w-full" : "w-fit"}`}
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {/* Sliding indicator */}
      <div
        className="absolute top-1 bottom-1 rounded-lg bg-primary/15 border border-primary/20 transition-transform duration-200 ease-out"
        style={{
          width: `calc(${100 / options.length}% - 0px)`,
          transform: `translateX(${activeIndex * 100}%)`,
        }}
      />
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            aria-pressed={active}
            onClick={() => {
              if (!active) { hapticTap(); onChange(opt.value); }
            }}
            className={`relative z-[1] ${compact ? "min-h-[32px]" : "min-h-[36px]"} px-4 ${compact ? "text-[11px]" : "text-xs"} font-semibold rounded-lg text-center transition-colors duration-200 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              active ? "text-primary" : "text-on-surface-variant"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
