import { hapticTap } from "../lib/haptics";

interface SegmentedControlProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  fullWidth?: boolean;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  fullWidth = false,
}: SegmentedControlProps<T>) {
  return (
    <div
      className={`flex gap-1 bg-surface-container-lowest p-1 rounded-lg ${fullWidth ? "w-full" : "w-fit"}`}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          aria-pressed={value === opt.value}
          onClick={() => {
            hapticTap();
            onChange(opt.value);
          }}
          className={`min-h-[44px] px-4 text-xs font-semibold rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            fullWidth ? "flex-1" : ""
          } ${
            value === opt.value
              ? "bg-surface-container-highest text-primary"
              : "text-on-surface-variant hover:bg-surface-container-highest"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
