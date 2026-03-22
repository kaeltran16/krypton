import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Card } from "./Card";

interface CollapsibleSectionProps {
  title: string;
  summary?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}

export function CollapsibleSection({
  title,
  summary,
  open,
  onToggle,
  children,
}: CollapsibleSectionProps) {
  return (
    <Card padding="none" className="overflow-hidden">
      <button
        aria-expanded={open}
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 min-h-[44px] hover:bg-surface-container-highest transition-colors"
      >
        <div className="text-left min-w-0">
          <span className="text-[11px] font-headline font-bold text-primary uppercase tracking-widest">
            {title}
          </span>
          {!open && summary && (
            <p className="text-[10px] text-on-surface-variant truncate mt-0.5">
              {summary}
            </p>
          )}
        </div>
        <ChevronDown
          size={16}
          className={`text-on-surface-variant shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="px-4 pb-4 pt-1">{children}</div>}
    </Card>
  );
}
