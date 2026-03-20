import { type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { hapticTap } from "../lib/haptics";

interface SubPageShellProps {
  title: string;
  onBack: () => void;
  children: ReactNode;
}

export function SubPageShell({ title, onBack, children }: SubPageShellProps) {
  return (
    <div className="min-h-full">
      <div className="flex items-center gap-3 px-4 py-4">
        <button
          onClick={() => { hapticTap(); onBack(); }}
          className="p-1.5 hover:bg-surface-variant rounded-lg transition-colors"
        >
          <ArrowLeft size={20} className="text-primary" />
        </button>
        <h1 className="font-headline font-bold text-lg tracking-tight uppercase text-on-surface">
          {title}
        </h1>
      </div>
      <div className="px-4 pb-8">
        {children}
      </div>
    </div>
  );
}
