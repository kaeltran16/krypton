import { useState } from "react";
import { useSignalStore } from "../store";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";
import { OrderDialog } from "../../trading/components/OrderDialog";
import type { Signal, UserStatus } from "../types";

type StatusFilter = "ALL" | "ACTIVE" | UserStatus;

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "ACTIVE", label: "Active" },
  { value: "TRADED", label: "Traded" },
  { value: "SKIPPED", label: "Skipped" },
];

export function SignalFeed() {
  const { signals, selectedSignal, selectSignal, clearSelection } = useSignalStore();
  const [tradingSignal, setTradingSignal] = useState<Signal | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");

  const filtered =
    statusFilter === "ALL"
      ? signals
      : statusFilter === "ACTIVE"
        ? signals.filter((s) => !s.outcome || s.outcome === "PENDING")
        : signals.filter((s) => s.user_status === statusFilter);

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1.5">
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                statusFilter === value
                  ? "bg-accent/15 text-accent"
                  : "text-muted border border-border"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <ConnectionStatus />
      </div>

      {filtered.length === 0 ? (
        <p className="text-muted text-center text-sm mt-8">
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
