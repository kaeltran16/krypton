import { useSignalStore } from "../store";
import { useSignalWebSocket } from "../hooks/useSignalWebSocket";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";

export function SignalFeed() {
  useSignalWebSocket();
  const { signals, selectedSignal, selectSignal, clearSelection } =
    useSignalStore();

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">Signals</h1>
        <ConnectionStatus />
      </div>

      {signals.length === 0 ? (
        <p className="text-gray-500 text-center mt-12">
          Waiting for signals...
        </p>
      ) : (
        <div className="space-y-3">
          {signals.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              onSelect={selectSignal}
            />
          ))}
        </div>
      )}

      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
    </div>
  );
}
