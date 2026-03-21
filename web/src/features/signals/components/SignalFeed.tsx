import { useEffect, useState } from "react";
import { Radio } from "lucide-react";
import { useSignalStore } from "../store";
import { SignalCard } from "./SignalCard";
import { OrderDialog } from "../../trading/components/OrderDialog";
import { EmptyState } from "../../../shared/components/EmptyState";
import { Dropdown } from "../../../shared/components/Dropdown";
import { hapticTap } from "../../../shared/lib/haptics";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { formatPair } from "../../../shared/lib/format";
import type { Signal, UserStatus } from "../types";

type StatusFilter = "ALL" | "ACTIVE" | UserStatus;
type PairFilter = "ALL" | (typeof AVAILABLE_PAIRS)[number];

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "ACTIVE", label: "Active" },
  { value: "TRADED", label: "Traded" },
  { value: "SKIPPED", label: "Skipped" },
];

const PAIR_OPTIONS = [
  { value: "ALL", label: "All pairs" },
  ...AVAILABLE_PAIRS.map((p) => ({ value: p, label: formatPair(p) })),
];

export function SignalFeed() {
  const { signals, selectSignal } = useSignalStore();
  const [tradingSignal, setTradingSignal] = useState<Signal | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [pairFilter, setPairFilter] = useState<PairFilter>("ALL");
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const recent = signals.filter((s) => new Date(s.created_at).getTime() > cutoff);

  const byPair = pairFilter === "ALL" ? recent : recent.filter((s) => s.pair === pairFilter);

  const filtered =
    statusFilter === "ALL"
      ? byPair
      : statusFilter === "ACTIVE"
        ? byPair.filter((s) => !s.outcome || s.outcome === "PENDING")
        : byPair.filter((s) => s.user_status === statusFilter);

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-2">
        <div className="flex gap-2 min-w-0">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              aria-pressed={statusFilter === f.value}
              onClick={() => {
                if (statusFilter !== f.value) {
                  hapticTap();
                  setStatusFilter(f.value);
                }
              }}
              className={`min-h-[36px] px-3.5 text-xs font-medium rounded-full whitespace-nowrap transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                statusFilter === f.value
                  ? "bg-primary/15 text-primary"
                  : "bg-surface-container text-on-surface-variant"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="ml-auto w-[120px] shrink-0">
          <Dropdown
            options={PAIR_OPTIONS}
            value={pairFilter}
            onChange={(v) => { hapticTap(); setPairFilter(v as PairFilter); }}
            ariaLabel="Filter by pair"
            size="sm"
            fullWidth
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<Radio size={32} />}
          title={statusFilter === "ALL" ? "No signals in the last 24 hours" : `No ${statusFilter.toLowerCase()} signals`}
          subtitle="Signals appear as the engine detects opportunities"
        />
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

      <OrderDialog signal={tradingSignal} onClose={() => setTradingSignal(null)} />
    </div>
  );
}
