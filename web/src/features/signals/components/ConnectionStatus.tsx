import { useSignalStore } from "../store";

export function ConnectionStatus() {
  const connected = useSignalStore((s) => s.connected);

  return (
    <div className="flex items-center gap-2 px-2 py-1 bg-surface-container rounded-lg" role="status" aria-live="polite">
      <div className={`w-2 h-2 rounded-full ${connected ? "bg-long shadow-[0_0_8px_rgba(86,239,159,0.5)]" : "bg-short motion-safe:animate-pulse"}`} />
      <span className="text-[10px] font-medium text-on-surface-variant uppercase tracking-wider tabular">
        {connected ? "Connected (Live OKX Feed)" : "Reconnecting..."}
      </span>
    </div>
  );
}
