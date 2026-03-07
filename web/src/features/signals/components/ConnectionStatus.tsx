import { useSignalStore } from "../store";

export function ConnectionStatus() {
  const connected = useSignalStore((s) => s.connected);

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted">
      <div className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-long" : "bg-short animate-pulse"}`} />
      {connected ? "Live" : "..."}
    </div>
  );
}
