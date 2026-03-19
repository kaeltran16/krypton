import { useState } from "react";
import ParameterRow from "./ParameterRow";

interface Props {
  title: string;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  params?: Record<string, { value: unknown; source: "hardcoded" | "configurable" }>;
}

export default function ParameterCategory({ title, defaultOpen = false, children, params }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  const entries = params ? Object.entries(params) : [];

  return (
    <div className="border border-border/50 rounded-lg overflow-hidden mb-2">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-surface/50 hover:bg-surface transition-colors"
      >
        <span className="text-sm font-medium text-foreground">{title}</span>
        <span className="text-muted text-xs">{open ? "\u2212" : "+"}</span>
      </button>
      {open && (
        <div>
          {params &&
            entries.map(([key, param], i) => (
              <ParameterRow
                key={key}
                name={key}
                value={param.value}
                source={param.source}
                last={i === entries.length - 1}
              />
            ))}
          {children}
        </div>
      )}
    </div>
  );
}
