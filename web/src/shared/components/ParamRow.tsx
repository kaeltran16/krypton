import type { ReactNode } from "react";

interface ParamRowProps {
  label: ReactNode;
  value: ReactNode;
  last?: boolean;
  className?: string;
}

export function ParamRow({ label, value, last = false, className = "" }: ParamRowProps) {
  return (
    <div
      className={[
        "flex items-center justify-between px-3 py-2",
        last ? "" : "border-b border-outline-variant/10",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="text-xs text-on-surface-variant">{label}</span>
      <span className="text-xs font-mono text-on-surface">{value}</span>
    </div>
  );
}
