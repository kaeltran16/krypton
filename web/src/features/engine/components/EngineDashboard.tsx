import { useEffect } from "react";
import { useEngineStore } from "../store";
import { RefreshCw } from "lucide-react";
import type { ParameterValue, EngineParameters } from "../types";

export function EngineDashboard() {
  const { params, loading, error, fetch, refresh } = useEngineStore();

  useEffect(() => { fetch(); }, [fetch]);

  if (loading) return <div className="p-4 text-on-surface-variant text-sm">Loading parameters...</div>;
  if (error) return <div className="p-4 text-error text-sm">Error: {error}</div>;
  if (!params) return null;

  const counts = countSources(params);

  const blendingParams = [
    { name: "ML Blend Weight", value: params.blending.ml_blend_weight.value, source: params.blending.ml_blend_weight.source },
    { name: "Signal Threshold", value: params.blending.thresholds.signal_threshold?.value ?? "—", source: params.blending.thresholds.signal_threshold?.source ?? "hardcoded" },
  ];

  const technicalParams = extractParams(params.technical.sigmoid_params, 2);
  const orderFlowParams = extractParams(params.order_flow.max_scores, 2);
  const onchainParams = extractNestedParams(params.onchain, 2);

  return (
    <div className="space-y-4">
      {/* Status Header */}
      <div className="flex gap-4">
        <div className="flex-1 bg-surface-container p-4 rounded-lg">
          <span className="text-xs font-headline font-bold uppercase tracking-widest text-on-surface-variant">Parameters</span>
          <div className="font-headline text-3xl font-bold tabular-nums tracking-tighter text-primary mt-1">
            {counts.configurable + counts.hardcoded}
          </div>
        </div>
        <div className="bg-surface-container-low p-4 rounded-lg flex flex-col justify-center">
          <span className="text-xs uppercase text-on-surface-variant mb-1">Configurable</span>
          <div className="flex items-baseline gap-2">
            <span className="font-headline text-2xl font-bold tabular-nums">{counts.configurable}</span>
            <span className="text-tertiary-dim text-xs">params</span>
          </div>
        </div>
      </div>

      {/* Parameter Categories */}
      <div className="grid grid-cols-2 gap-4">
        <ParamCategory title="Blending" params={blendingParams} />
        <ParamCategory title="Technical" params={technicalParams} />
        <ParamCategory title="Order Flow" params={orderFlowParams} />
        <ParamCategory title="On-Chain" params={onchainParams} />
      </div>

      {/* Refresh */}
      <button
        onClick={refresh}
        className="w-full bg-primary-container text-on-primary-fixed py-3 rounded-lg text-xs font-bold uppercase tracking-widest flex items-center justify-center gap-2 active:scale-[0.98] transition-transform focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
      >
        <RefreshCw size={14} />
        Refresh Parameters
      </button>
    </div>
  );
}

function ParamCategory({ title, params }: { title: string; params: { name: string; value: unknown; source: string }[] }) {
  return (
    <section className="bg-surface-container p-4 rounded-lg flex flex-col gap-3">
      <h2 className="text-xs font-headline font-bold uppercase tracking-wider text-primary">{title}</h2>
      <div className="space-y-2">
        {params.map((p) => (
          <div key={p.name} className={`bg-surface-container-lowest p-3 rounded ${p.source === "configurable" ? "border-l-2 border-primary/40" : ""}`}>
            <div className="flex justify-between text-[10px] text-on-surface-variant uppercase mb-1">
              <span>{p.name}</span>
              <span className={p.source === "configurable" ? "text-primary" : "text-outline"}>
                {p.source === "configurable" ? "Config" : "Fixed"}
              </span>
            </div>
            <span className="font-headline font-medium text-lg tabular-nums">{formatValue(p.value)}</span>
          </div>
        ))}
        {params.length === 0 && (
          <div className="text-[10px] text-on-surface-variant text-center py-2">No data</div>
        )}
      </div>
    </section>
  );
}

function formatValue(v: unknown): string {
  if (typeof v === "number") return v.toFixed(3);
  if (typeof v === "string") return v;
  return String(v ?? "—");
}

function countSources(params: EngineParameters): { configurable: number; hardcoded: number } {
  let configurable = 0, hardcoded = 0;
  function walk(obj: unknown) {
    if (obj && typeof obj === "object" && "source" in (obj as Record<string, unknown>) && "value" in (obj as Record<string, unknown>)) {
      const pv = obj as ParameterValue;
      if (pv.source === "configurable") configurable++;
      else hardcoded++;
    } else if (obj && typeof obj === "object") {
      for (const val of Object.values(obj as Record<string, unknown>)) {
        walk(val);
      }
    }
  }
  walk(params);
  return { configurable, hardcoded };
}

function extractParams(record: Record<string, ParameterValue>, limit: number): { name: string; value: unknown; source: string }[] {
  return Object.entries(record).slice(0, limit).map(([k, v]) => ({
    name: k.replace(/_/g, " "),
    value: v.value,
    source: v.source,
  }));
}

function extractNestedParams(obj: Record<string, unknown>, limit: number): { name: string; value: unknown; source: string }[] {
  const result: { name: string; value: unknown; source: string }[] = [];
  function walk(o: unknown, prefix: string) {
    if (result.length >= limit) return;
    if (o && typeof o === "object" && "source" in (o as Record<string, unknown>) && "value" in (o as Record<string, unknown>)) {
      const pv = o as ParameterValue;
      result.push({ name: prefix.replace(/_/g, " "), value: pv.value, source: pv.source });
    } else if (o && typeof o === "object") {
      for (const [k, v] of Object.entries(o as Record<string, unknown>)) {
        if (result.length >= limit) return;
        walk(v, prefix ? `${prefix} ${k}` : k);
      }
    }
  }
  walk(obj, "");
  return result;
}
