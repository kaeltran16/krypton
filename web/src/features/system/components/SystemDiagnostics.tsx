import { useSignalStore } from "../../signals/store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { Wifi, Database, HardDrive, Cpu } from "lucide-react";

export function SystemDiagnostics() {
  const connected = useSignalStore((s) => s.connected);

  const healthCards = [
    { label: "Connectivity", status: connected ? "OPTIMAL" : "OFFLINE", color: connected ? "border-tertiary-dim" : "border-error", dotColor: connected ? "bg-tertiary-dim" : "bg-error", icon: Wifi },
    { label: "Database", status: "ACTIVE", color: "border-tertiary-dim", dotColor: "bg-tertiary-dim", icon: Database },
    { label: "Cache", status: "WARM", color: "border-primary", dotColor: "bg-primary", icon: HardDrive },
    { label: "ML Pipeline", status: "READY", color: "border-tertiary-dim", dotColor: "bg-tertiary-dim", icon: Cpu },
  ];

  return (
    <div className="space-y-6">
      {/* Health Summary */}
      <section className="grid grid-cols-2 gap-3">
        {healthCards.map((card) => (
          <div key={card.label} className={`bg-surface-container p-4 ${card.color} border-l-2 rounded-r-lg`}>
            <p className="text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-widest mb-1">{card.label}</p>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${card.dotColor} ${card.status === "OPTIMAL" ? "animate-pulse motion-reduce:animate-none" : ""}`} />
              <span className="text-sm font-bold tabular-nums">{card.status}</span>
            </div>
          </div>
        ))}
      </section>

      {/* WebSocket Streams */}
      <section className="bg-surface-container-low overflow-hidden rounded-lg">
        <div className="p-4 bg-surface-container flex justify-between items-center">
          <h2 className="font-headline font-bold text-xs tracking-tighter uppercase text-primary">WebSocket Streams</h2>
          <span className="text-[10px] tabular-nums bg-primary/10 text-primary px-2 py-0.5 rounded-full">{AVAILABLE_PAIRS.length} ACTIVE</span>
        </div>
        <div className="divide-y divide-outline-variant/10">
          {AVAILABLE_PAIRS.map((pair) => (
            <div key={pair} className="px-4 py-3 flex items-center justify-between">
              <span className="font-mono font-medium text-sm text-on-surface">{pair}</span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                connected
                  ? "text-tertiary-dim bg-tertiary-dim/10"
                  : "text-error bg-error/10"
              }`}>
                {connected ? "CONNECTED" : "DISCONNECTED"}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Infrastructure */}
      <section className="bg-surface-container p-5 border border-outline-variant/10 rounded-lg">
        <h2 className="font-headline font-bold text-xs tracking-tighter uppercase text-primary mb-5">Infrastructure</h2>
        <div className="space-y-4">
          <InfraRow label="Redis (Cache)" detail="In-memory store" status="ACTIVE" />
          <InfraRow label="PostgreSQL" detail="Primary database" status="ACTIVE" />
          <InfraRow label="Collector Service" detail="OKX WebSocket ingestion" status="RUNNING" />
        </div>
      </section>

      {/* Data Freshness */}
      <section className="bg-surface-container p-5 border border-outline-variant/10 rounded-lg">
        <h2 className="font-headline font-bold text-xs tracking-tighter uppercase text-primary mb-5">Data Freshness</h2>
        <div className="space-y-5">
          <FreshnessBar label="Technicals" lag="Live" pct={95} color="bg-tertiary-dim" />
          <FreshnessBar label="Order Flow" lag="Live" pct={98} color="bg-tertiary-dim" />
          <FreshnessBar label="On-Chain" lag="~2m" pct={70} color="bg-primary" />
        </div>
      </section>
    </div>
  );
}

function InfraRow({ label, detail, status }: { label: string; detail: string; status: string }) {
  return (
    <div className="flex items-start justify-between">
      <div>
        <p className="text-[11px] font-bold text-on-surface">{label}</p>
        <p className="text-[10px] text-on-surface-variant">{detail}</p>
      </div>
      <span className="text-[10px] text-tertiary-dim uppercase font-bold">{status}</span>
    </div>
  );
}

function FreshnessBar({ label, lag, pct, color }: { label: string; lag: string; pct: number; color: string }) {
  return (
    <div>
      <div className="flex justify-between text-[10px] font-bold uppercase mb-1">
        <span className="text-on-surface-variant">{label}</span>
        <span className={pct >= 90 ? "text-tertiary-dim" : "text-primary"}>{lag}</span>
      </div>
      <div className="h-1.5 w-full bg-surface-container-lowest overflow-hidden rounded-full">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
