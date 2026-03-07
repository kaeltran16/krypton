import { useState } from "react";
import { useSignalStore } from "../store";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";
import { OrderDialog } from "../../trading/components/OrderDialog";
import { PerformanceStrip } from "../../home/components/PerformanceStrip";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import type { Signal, UserStatus } from "../types";

type StatusFilter = "ALL" | UserStatus;

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "TRADED", label: "Traded" },
  { value: "SKIPPED", label: "Skipped" },
];

export function SignalFeed() {
  const { signals, selectedSignal, selectSignal, clearSelection } =
    useSignalStore();
  const [tradingSignal, setTradingSignal] = useState<Signal | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const { stats, loading: statsLoading } = useSignalStats();

  const filtered =
    statusFilter === "ALL"
      ? signals
      : signals.filter((s) => s.user_status === statusFilter);

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-bold uppercase tracking-wider text-gray-400">Feed</h1>
        <ConnectionStatus />
      </div>

      <PerformanceStrip stats={stats} loading={statsLoading} />

      <div className="flex gap-1.5">
        {FILTERS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setStatusFilter(value)}
            className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
              statusFilter === value
                ? "bg-gray-700 text-white"
                : "text-gray-500 border border-gray-800"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-gray-500 text-center text-sm mt-8">
          {statusFilter === "ALL" ? "Waiting for signals..." : `No ${statusFilter.toLowerCase()} signals`}
        </p>
      ) : (
        <div className="space-y-2">
          {filtered.map((signal) => (
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
