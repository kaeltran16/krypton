import { useEffect, useState } from "react";
import { Radio } from "lucide-react";
import { useSignalStore } from "../store";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";
import { OrderDialog } from "../../trading/components/OrderDialog";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
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
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const recent = signals.filter((s) => new Date(s.created_at).getTime() > cutoff);

  const filtered =
    statusFilter === "ALL"
      ? recent
      : statusFilter === "ACTIVE"
        ? recent.filter((s) => !s.outcome || s.outcome === "PENDING")
        : recent.filter((s) => s.user_status === statusFilter);

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <SegmentedControl
          options={FILTERS}
          value={statusFilter}
          onChange={setStatusFilter}
        />
        <ConnectionStatus />
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center gap-3 mt-12 text-center">
          <Radio size={32} className="text-outline" />
          <p className="text-on-surface-variant text-sm">
            {statusFilter === "ALL" ? "No signals in the last 24 hours" : `No ${statusFilter.toLowerCase()} signals`}
          </p>
          <p className="text-outline text-xs">Signals appear as the engine detects opportunities</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((signal, i) => (
            <div key={signal.id} className={`motion-safe:animate-card-enter stagger-${Math.min(i + 1, 10)}`}>
              <SignalCard
                signal={signal}
                onSelect={selectSignal}
                onExecute={setTradingSignal}
              />
            </div>
          ))}
        </div>
      )}

      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
      <OrderDialog signal={tradingSignal} onClose={() => setTradingSignal(null)} />
    </div>
  );
}
