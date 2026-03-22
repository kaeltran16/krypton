import type { ReactNode } from "react";

interface FormFieldProps {
  label: string;
  children: ReactNode;
  className?: string;
}

export const INPUT_STYLES =
  "w-full bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm min-h-[44px] focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none";

export function FormField({ label, children, className = "" }: FormFieldProps) {
  return (
    <label className={className}>
      <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1.5 mt-1 block">
        {label}
      </span>
      {children}
    </label>
  );
}
