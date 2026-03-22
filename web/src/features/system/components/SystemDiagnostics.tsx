import { useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  Loader2,
} from "lucide-react";
import { useSystemHealth } from "../hooks/useSystemHealth";
import type { SystemHealthResponse } from "../types";
import { Button } from "../../../shared/components/Button";
import { formatDurationSeconds, formatSecondsAgo } from "../../../shared/lib/format";
import { Card } from "../../../shared/components/Card";
import { CollapsibleSection } from "../../../shared/components/CollapsibleSection";
import { ProgressBar } from "../../../shared/components/ProgressBar";
import { ParamRow } from "../../../shared/components/ParamRow";
import { MetricCard } from "../../../shared/components/MetricCard";
import { Skeleton } from "../../../shared/components/Skeleton";

// ─── Helpers ───────────────────────────────────────────────────

function adjusted(original: number | null | undefined, elapsed: number): number | null {
  if (original == null) return null;
  return original + elapsed;
}

type FreshnessLevel = "green" | "yellow" | "red";

function freshnessLevel(seconds: number | null, greenMax: number, redMin: number): FreshnessLevel {
  if (seconds == null) return "red";
  if (seconds < greenMax) return "green";
  if (seconds <= redMin) return "yellow";
  return "red";
}

function freshnessBarWidth(seconds: number | null, redThreshold: number): number {
  if (seconds == null) return 0;
  const ratio = 1 - Math.min(seconds, redThreshold) / redThreshold;
  return Math.max(0, Math.round(ratio * 100));
}

const FRESHNESS_COLORS: Record<FreshnessLevel, string> = {
  green: "bg-tertiary-dim",
  yellow: "bg-primary",
  red: "bg-error",
};

const FRESHNESS_TEXT: Record<FreshnessLevel, string> = {
  green: "text-tertiary-dim",
  yellow: "text-primary",
  red: "text-error",
};

// ─── Status Banner ─────────────────────────────────────────────

function StatusBanner({
  status,
  refreshing,
  onRefresh,
}: {
  status: "healthy" | "degraded" | "unhealthy" | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const config = {
    healthy: { label: "All Systems Operational", Icon: CheckCircle2, dot: "bg-tertiary-dim", text: "text-tertiary-dim" },
    degraded: { label: "Degraded", Icon: AlertTriangle, dot: "bg-primary", text: "text-primary" },
    unhealthy: { label: "Unhealthy", Icon: XCircle, dot: "bg-error", text: "text-error" },
  };
  const c = status ? config[status] : config.unhealthy;

  return (
    <Card className="flex items-center justify-between" aria-live="polite">
      <div className="flex items-center gap-3">
        <span className={`w-2.5 h-2.5 rounded-full ${c.dot} shrink-0`} />
        <c.Icon size={18} className={c.text} />
        <span className={`font-headline font-bold text-sm uppercase tracking-wide ${c.text}`}>{c.label}</span>
      </div>
      <Button
        variant="ghost"
        icon={refreshing ? <Loader2 size={18} className="text-primary animate-spin" /> : <RefreshCw size={18} className="text-on-surface-variant" />}
        onClick={onRefresh}
        disabled={refreshing}
        aria-label="Refresh system health"
      />
    </Card>
  );
}

// ─── Service Pills ─────────────────────────────────────────────

function ServicePill({
  label,
  status,
  detail,
}: {
  label: string;
  status: "up" | "down";
  detail: string;
}) {
  const up = status === "up";
  return (
    <Card padding="sm" className="flex items-center gap-2.5">
      <span className={`w-2 h-2 rounded-full shrink-0 ${up ? "bg-tertiary-dim" : "bg-error"}`} />
      {up ? <CheckCircle2 size={14} className="text-tertiary-dim shrink-0" /> : <XCircle size={14} className="text-error shrink-0" />}
      <div className="min-w-0">
        <p className="text-[11px] font-bold text-on-surface truncate">{label}</p>
        <p className={`text-[10px] font-bold tabular-nums ${up ? "text-tertiary-dim" : "text-error"}`}>{detail}</p>
      </div>
    </Card>
  );
}

function ServiceHealthRow({ data }: { data: SystemHealthResponse }) {
  const { redis, postgres, okx_ws } = data.services;
  return (
    <div className="grid grid-cols-3 max-[374px]:grid-cols-1 gap-2">
      <ServicePill
        label="Redis"
        status={redis.status}
        detail={redis.status === "up" ? `${redis.latency_ms}ms` : "Down"}
      />
      <ServicePill
        label="Postgres"
        status={postgres.status}
        detail={postgres.status === "up" ? `${postgres.latency_ms}ms` : "Down"}
      />
      <ServicePill
        label="OKX WS"
        status={okx_ws.status}
        detail={okx_ws.status === "up" ? `${okx_ws.connected_pairs} pairs` : "Down"}
      />
    </div>
  );
}

// ─── Section Content ───────────────────────────────────────────

function PipelineSection({ data, elapsed }: { data: SystemHealthResponse; elapsed: number }) {
  const { pipeline } = data;
  const lastCycle = adjusted(pipeline.last_cycle_seconds_ago, elapsed);
  const bufferValues = Object.values(pipeline.candle_buffer);
  const minBuffer = bufferValues.length > 0 ? Math.min(...bufferValues) : 0;
  const maxBuffer = bufferValues.length > 0 ? Math.max(...bufferValues) : 0;

  return (
    <div className="grid grid-cols-2 gap-3">
      <MetricCard label="Signals Today" value={String(pipeline.signals_today)} />
      <MetricCard label="Last Cycle" value={formatSecondsAgo(lastCycle)} />
      <MetricCard label="Active Pairs" value={String(pipeline.active_pairs)} />
      <MetricCard label="Candle Buffer" value={`${minBuffer} / ${maxBuffer}`} />
    </div>
  );
}

function WebSocketSection({ data }: { data: SystemHealthResponse }) {
  const entries = Object.entries(data.pipeline.candle_buffer);
  return (
    <div className="space-y-2">
      {entries.map(([pair, count]) => (
        <div key={pair} className="flex items-center justify-between">
          <span className="font-mono text-xs text-on-surface">{pair}</span>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold tabular-nums text-on-surface-variant">{count} candles</span>
            <span className="w-1.5 h-1.5 rounded-full bg-tertiary-dim" />
          </div>
        </div>
      ))}
      {entries.length === 0 && (
        <p className="text-[10px] text-on-surface-variant">No streams active</p>
      )}
    </div>
  );
}

function ResourcesSection({ data, elapsed }: { data: SystemHealthResponse; elapsed: number }) {
  const { resources } = data;
  const uptime = resources.uptime_seconds + elapsed;
  const poolPct = resources.db_pool_size > 0
    ? Math.round((resources.db_pool_active / resources.db_pool_size) * 100)
    : 0;

  return (
    <div>
      <ParamRow label="Memory" value={resources.memory_mb != null ? `${resources.memory_mb} MB` : "N/A"} />
      <ParamRow
        label="DB Pool"
        value={
          <span className="flex flex-col items-end gap-0.5">
            <span>{resources.db_pool_active} / {resources.db_pool_size}</span>
            <ProgressBar value={poolPct} label="DB pool usage" className="w-16" />
          </span>
        }
      />
      <ParamRow label="WS Clients" value={String(resources.ws_clients)} />
      <ParamRow label="Uptime" value={formatDurationSeconds(uptime)} last />
    </div>
  );
}

function FreshnessSection({ data, elapsed }: { data: SystemHealthResponse; elapsed: number }) {
  const { freshness } = data;
  const techSec = adjusted(freshness.technicals_seconds_ago, elapsed);
  const flowSec = adjusted(freshness.order_flow_seconds_ago, elapsed);
  const onchainSec = adjusted(freshness.onchain_seconds_ago, elapsed);

  return (
    <div className="space-y-4">
      <FreshnessRow label="Technicals" seconds={techSec} greenMax={30} redThreshold={120} />
      <FreshnessRow label="Order Flow" seconds={flowSec} greenMax={30} redThreshold={120} />
      <FreshnessRow label="On-Chain" seconds={onchainSec} greenMax={300} redThreshold={600} />
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">ML Models</span>
        <span className={`text-xs font-bold tabular-nums ${freshness.ml_models_loaded === 0 ? "text-primary" : "text-on-surface"}`}>
          {freshness.ml_models_loaded === 0 ? "No models loaded" : `${freshness.ml_models_loaded} models`}
        </span>
      </div>
    </div>
  );
}

function FreshnessRow({
  label,
  seconds,
  greenMax,
  redThreshold,
}: {
  label: string;
  seconds: number | null;
  greenMax: number;
  redThreshold: number;
}) {
  if (seconds == null) {
    return (
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">{label}</span>
        <span className="text-[10px] font-bold text-on-surface-variant">Inactive</span>
      </div>
    );
  }

  const level = freshnessLevel(seconds, greenMax, redThreshold);
  const width = freshnessBarWidth(seconds, redThreshold);

  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">{label}</span>
        <span className={`text-[10px] font-bold tabular-nums ${FRESHNESS_TEXT[level]}`}>
          {formatSecondsAgo(seconds)}
        </span>
      </div>
      <ProgressBar value={width} color={FRESHNESS_COLORS[level]} label={label} />
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────

type SectionKey = "pipeline" | "ws" | "resources" | "freshness";

export function SystemDiagnostics() {
  const { data, loading, refreshing, error, refresh, elapsed } = useSystemHealth();
  const [openSections, setOpenSections] = useState<Partial<Record<SectionKey, boolean>>>({});

  const toggle = (key: SectionKey) =>
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  if (loading) return <div className="space-y-4"><Skeleton count={6} /></div>;

  if (error && !data) {
    return (
      <Card border={false} className="border border-error/20 text-center">
        <XCircle size={32} className="text-error mx-auto mb-3" />
        <p className="text-sm font-bold text-on-surface mb-1">Unable to reach backend</p>
        <p className="text-xs text-on-surface-variant mb-4">{error}</p>
        <Button variant="primary" size="sm" onClick={refresh}>Retry</Button>
      </Card>
    );
  }

  if (!data) return null;

  const pipelineSummary = `${data.pipeline.signals_today} signals today · last cycle ${formatSecondsAgo(adjusted(data.pipeline.last_cycle_seconds_ago, elapsed))}`;
  const bufferEntries = Object.entries(data.pipeline.candle_buffer);
  const minBuffer = bufferEntries.length > 0 ? Math.min(...bufferEntries.map(([, v]) => v)) : 0;
  const wsSummary = `${bufferEntries.length} streams · min ${minBuffer} candles`;
  const resourceSummary = `${data.resources.db_pool_active}/${data.resources.db_pool_size} pool · ${data.resources.ws_clients} WS · ${formatDurationSeconds(data.resources.uptime_seconds + elapsed)}`;
  const freshnessSummary = `Tech ${formatSecondsAgo(adjusted(data.freshness.technicals_seconds_ago, elapsed))} · ${data.freshness.ml_models_loaded} ML models`;

  return (
    <div className={`space-y-3 ${refreshing ? "opacity-60 transition-opacity" : ""}`}>
      <StatusBanner status={data.status} refreshing={refreshing} onRefresh={refresh} />
      <ServiceHealthRow data={data} />

      <CollapsibleSection title="Pipeline" summary={pipelineSummary} open={!!openSections.pipeline} onToggle={() => toggle("pipeline")}>
        <PipelineSection data={data} elapsed={elapsed} />
      </CollapsibleSection>

      <CollapsibleSection title="WebSocket Streams" summary={wsSummary} open={!!openSections.ws} onToggle={() => toggle("ws")}>
        <WebSocketSection data={data} />
      </CollapsibleSection>

      <CollapsibleSection title="Resources" summary={resourceSummary} open={!!openSections.resources} onToggle={() => toggle("resources")}>
        <ResourcesSection data={data} elapsed={elapsed} />
      </CollapsibleSection>

      <CollapsibleSection title="Data Freshness" summary={freshnessSummary} open={!!openSections.freshness} onToggle={() => toggle("freshness")}>
        <FreshnessSection data={data} elapsed={elapsed} />
      </CollapsibleSection>
    </div>
  );
}
