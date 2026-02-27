import { useSignalStore } from "../store";

export function ConnectionStatus() {
  const connected = useSignalStore((s) => s.connected);

  return (
    <div className="flex items-center gap-2 text-xs text-gray-400">
      <div
        className={`w-2 h-2 rounded-full ${connected ? "bg-long" : "bg-short animate-pulse"}`}
      />
      {connected ? "Live" : "Reconnecting..."}
    </div>
  );
}
