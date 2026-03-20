import { Terminal } from "lucide-react";

export function EngineHeader() {
  return (
    <header className="bg-surface flex items-center w-full px-4 h-14 z-40 sticky top-0 safe-top">
      <div className="flex items-center gap-3">
        <Terminal size={20} className="text-primary-container" />
        <span className="font-headline font-bold tracking-tight uppercase text-lg text-primary-container">
          Engine Control
        </span>
      </div>
    </header>
  );
}
