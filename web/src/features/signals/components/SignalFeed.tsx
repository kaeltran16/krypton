import { useState } from "react";
import { useSignalStore } from "../store";
import { useSignalWebSocket } from "../hooks/useSignalWebSocket";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";
import { OrderDialog } from "../../trading/components/OrderDialog";
import type { Signal } from "../types";

export function SignalFeed() {
  useSignalWebSocket();
  const { signals, selectedSignal, selectSignal, clearSelection } =
    useSignalStore();
  const [tradingSignal, setTradingSignal] = useState<Signal | null>(null);

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
              onExecute={setTradingSignal}
            />
          ))}
        </div>
      )}

      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
      <OrderDialog signal={tradingSignal} onClose={() => setTradingSignal(null)} />
    </div>
  );
}
