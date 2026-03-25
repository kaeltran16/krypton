import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useEngineStore } from "../store";
import ParameterCategory from "./ParameterCategory";
import ParameterRow from "./ParameterRow";
import WeightBar from "./WeightBar";
import RegimeGrid from "./RegimeGrid";
import { Dropdown } from "../../../shared/components/Dropdown";
import { Button } from "../../../shared/components/Button";
import PipelineFlow from "./PipelineFlow";
import { api } from "../../../shared/lib/api";
import { Card } from "../../../shared/components/Card";
import { SectionLabel } from "../../../shared/components/SectionLabel";
import { MetricCard } from "../../../shared/components/MetricCard";
import { Skeleton } from "../../../shared/components/Skeleton";
import type { ParameterDiff } from "../types";

export default function EnginePage() {
  const { params, loading, error, fetch, refresh } = useEngineStore();
  const liveScores = useEngineStore((s) => s.liveScores);
  const [selectedPair, setSelectedPair] = useState("");
  const [selectedTf, setSelectedTf] = useState("");
  const scoreKeys = useMemo(() => Object.keys(liveScores), [liveScores]);
  const [scorePair, setScorePair] = useState("");

  const [thresholds, setThresholds] = useState<{
    default: number;
    thresholds: { pair: string; regime: string; value: number }[];
  } | null>(null);
  const [thresholdsLoading, setThresholdsLoading] = useState(false);

  const [pendingEdit, setPendingEdit] = useState<{ path: string; value: number } | null>(null);
  const [applyDiff, setApplyDiff] = useState<ParameterDiff[] | null>(null);
  const [applyLoading, setApplyLoading] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  const handleEdit = async (dotPath: string, value: number) => {
    setPendingEdit({ path: dotPath, value });
    setApplyLoading(true);
    setApplyError(null);
    try {
      const result = await api.previewEngineApply({ [dotPath]: value });
      setApplyDiff(result.diff);
    } catch (e) {
      setApplyError((e as Error).message);
      setPendingEdit(null);
      setApplyDiff(null);
    } finally {
      setApplyLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!pendingEdit) return;
    setApplyLoading(true);
    try {
      await api.confirmEngineApply({ [pendingEdit.path]: pendingEdit.value });
      await refresh();
      setPendingEdit(null);
      setApplyDiff(null);
    } catch (e) {
      setApplyError((e as Error).message);
    } finally {
      setApplyLoading(false);
    }
  };

  const handleCancelApply = () => {
    setPendingEdit(null);
    setApplyDiff(null);
    setApplyError(null);
  };

  useEffect(() => { fetch(); }, [fetch]);

  useEffect(() => {
    setThresholdsLoading(true);
    api.getEngineThresholds()
      .then(setThresholds)
      .catch(() => {})
      .finally(() => setThresholdsLoading(false));
  }, []);

  useEffect(() => {
    if (!params) return;
    const pairs = Object.keys(params.regime_weights || {});
    if (pairs.length > 0 && !selectedPair) {
      setSelectedPair(pairs[0]);
      const tfs = Object.keys(params.regime_weights[pairs[0]] || {});
      if (tfs.length > 0) setSelectedTf(tfs[0]);
    }
  }, [params, selectedPair]);

  useEffect(() => {
    if (scoreKeys.length > 0 && !scorePair) setScorePair(scoreKeys[0]);
  }, [scoreKeys.length, scorePair]);

  if (loading && !params) {
    return (
      <div className="p-3 space-y-3">
        <Skeleton height="h-28" />
        <div className="grid grid-cols-3 gap-2">
          <Skeleton height="h-14" />
          <Skeleton height="h-14" />
          <Skeleton height="h-14" />
        </div>
        <Skeleton height="h-8" />
        <Skeleton height="h-10" count={4} />
      </div>
    );
  }
  if (error) return <div className="p-4 text-error text-sm">Error: {error}</div>;
  if (!params) return null;

  const descriptions = params.descriptions;

  const activeScores = scorePair ? liveScores[scorePair] : null;
  const pipelineNodes = useMemo(() =>
    activeScores
      ? {
          technical: { label: "Technical", score: activeScores.technical },
          order_flow: { label: "Order Flow", score: activeScores.order_flow },
          onchain: { label: "On-Chain", score: activeScores.onchain },
          patterns: { label: "Patterns", score: activeScores.patterns },
          regime_blend: { label: "Regime Blend", score: activeScores.regime_blend },
          ml_gate: { label: "ML Gate", score: activeScores.ml_gate },
          llm_gate: { label: "LLM Gate", score: activeScores.llm_gate },
          signal: { label: "Signal", score: activeScores.signal, emitted: activeScores.emitted },
        }
      : undefined,
    [activeScores],
  );

  const regimeData = selectedPair && selectedTf
    ? params.regime_weights?.[selectedPair]?.[selectedTf]
    : null;
  const learnedAtr = selectedPair && selectedTf
    ? params.learned_atr?.[selectedPair]?.[selectedTf]
    : null;

  const allPairs = [
    ...new Set([
      ...Object.keys(params.regime_weights || {}),
      ...Object.keys(params.learned_atr || {}),
    ]),
  ];
  const allTfs = selectedPair
    ? [
        ...new Set([
          ...Object.keys(params.regime_weights?.[selectedPair] || {}),
          ...Object.keys(params.learned_atr?.[selectedPair] || {}),
        ]),
      ]
    : [];

  const hasPerPairData = regimeData || learnedAtr;

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-on-surface">Engine</h2>
        <Button
          variant="ghost"
          icon={<RefreshCw size={16} className={loading ? "animate-spin" : ""} />}
          onClick={refresh}
          aria-label="Refresh parameters"
        />
      </div>

      {applyError && !applyDiff && (
        <div className="flex items-center justify-between px-3 py-2 bg-error/10 border border-error/20 rounded-lg">
          <span className="text-xs text-error">{applyError}</span>
          <button onClick={() => setApplyError(null)} className="text-error text-xs ml-2">{"\u2715"}</button>
        </div>
      )}

      {applyDiff && pendingEdit && (
        <Card variant="high" padding="sm" border>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-on-surface">Confirm Change</span>
            {applyError && <span className="text-[10px] text-error">{applyError}</span>}
          </div>
          {applyDiff.map((d) => (
            <div key={d.path} className="flex justify-between text-xs font-mono py-0.5">
              <span className="text-on-surface-variant">{d.path.split(".").pop()}</span>
              <span>
                <span className="text-on-surface-variant">{d.current ?? "\u2014"}</span>
                <span className="text-on-surface-variant mx-1">{"\u2192"}</span>
                <span className="text-primary">{d.proposed}</span>
              </span>
            </div>
          ))}
          <p className="text-[10px] text-muted mt-1">This changes live engine behavior.</p>
          <div className="flex gap-2 justify-end mt-2">
            <Button variant="ghost" size="sm" onClick={handleCancelApply}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={handleConfirm} loading={applyLoading}>Apply</Button>
          </div>
        </Card>
      )}

      <div className="space-y-2">
        {scoreKeys.length > 1 ? (
          <Dropdown
            value={scorePair}
            onChange={setScorePair}
            options={scoreKeys.map((k) => ({ value: k, label: k.replace(":", " · ") }))}
            size="sm"
            fullWidth={false}
            ariaLabel="Pipeline score pair"
          />
        ) : scorePair ? (
          <span className="text-[10px] text-muted">{scorePair.replace(":", " · ")}</span>
        ) : null}
        <PipelineFlow nodes={pipelineNodes} />
        {scoreKeys.length === 0 && (
          <p className="text-[10px] text-muted text-center">Waiting for pipeline scores…</p>
        )}
      </div>
      <SectionLabel as="h3" color="primary" className="-mb-1">Scoring Thresholds</SectionLabel>
      <div className="grid grid-cols-3 gap-2">
        <MetricCard label="Signal" value={formatThreshold(params.blending.thresholds.signal_threshold?.value)} />
        <MetricCard label="LLM" value={formatThreshold(params.blending.thresholds.llm_threshold?.value)} />
        <MetricCard label="ML Blend" value={formatThreshold(params.blending.ml_blend_weight?.value)} />
      </div>

      <SectionLabel as="h3" color="primary" className="-mb-1">Source Weights</SectionLabel>
      <Card padding="sm">
        <WeightBar weights={params.blending.source_weights} />
      </Card>

      <SectionLabel as="h3" color="primary" className="-mb-1">Parameters</SectionLabel>

      <ParameterCategory title="Blending" variant="hero" defaultOpen descriptions={descriptions} onEdit={handleEdit}>
        <ParameterRow name="ml_blend_weight" value={params.blending.ml_blend_weight.value} source={params.blending.ml_blend_weight.source} descriptions={descriptions} dotPath="blending.ml_blend_weight" onEdit={handleEdit} />
        {Object.entries(params.blending.thresholds).map(([k, v], i, arr) => (
          <ParameterRow key={k} name={k} value={v.value} source={v.source} descriptions={descriptions} dotPath={`blending.thresholds.${k}`} onEdit={handleEdit} last={i === arr.length - 1} />
        ))}

        <ParameterCategory title="LLM Factor Weights" variant="sub" descriptions={descriptions} onEdit={handleEdit}>
          {Object.entries(params.blending.llm_factor_weights).map(([k, v]) => (
            <ParameterRow key={k} name={k} value={v.value} source={v.source} descriptions={descriptions} dotPath={`blending.llm_factor_weights.${k}`} onEdit={handleEdit} />
          ))}
          <ParameterRow name="factor_cap" value={params.blending.llm_factor_cap.value} source={params.blending.llm_factor_cap.source} descriptions={descriptions} dotPath="blending.llm_factor_cap" onEdit={handleEdit} last />
        </ParameterCategory>
      </ParameterCategory>

      <ParameterCategory title="Technical — Indicators" params={params.technical.indicator_periods} descriptions={descriptions} />

      <ParameterCategory title="Sigmoid Params" variant="sub" params={params.technical.sigmoid_params} descriptions={descriptions} />
      <ParameterCategory title="Mean Reversion" variant="sub" params={params.technical.mean_reversion} descriptions={descriptions} onEdit={handleEdit} dotPathPrefix="mean_reversion" />

      <ParameterCategory title="Order Flow" params={params.order_flow.regime_params} descriptions={descriptions}>
        {Object.entries(params.order_flow.max_scores).map(([k, v]) => (
          <ParameterRow key={k} name={`max_${k}`} value={v.value} source={v.source} descriptions={descriptions} />
        ))}
      </ParameterCategory>

      <ParameterCategory title="On-Chain — BTC" params={params.onchain.btc_profile as Record<string, any>} descriptions={descriptions} />
      <ParameterCategory title="On-Chain — ETH" params={params.onchain.eth_profile as Record<string, any>} descriptions={descriptions} />
      <ParameterCategory title="Levels & ATR" params={params.levels.atr_defaults} descriptions={descriptions} />
      <ParameterCategory title="ATR Guardrails" params={params.levels.atr_guardrails} descriptions={descriptions} />
      <ParameterCategory title="Phase 1 Scaling" params={params.levels.phase1_scaling} descriptions={descriptions} />
      <ParameterCategory title="Pattern Strengths" params={params.patterns.strengths} descriptions={descriptions} />
      <ParameterCategory title="Performance Tracker" params={params.performance_tracker.optimization_params} descriptions={descriptions} />
      <ParameterCategory title="Optimization Guardrails" params={params.performance_tracker.guardrails} descriptions={descriptions} />

      {allPairs.length > 0 && (<>
        <SectionLabel as="h3" color="primary" className="-mb-1">Per-Pair Parameters</SectionLabel>
        <Card variant="low" padding="sm" border>

          <div className="flex gap-2 mb-3">
            <Dropdown
              value={selectedPair}
              onChange={(v) => {
                setSelectedPair(v);
                const tfs = Object.keys(params.regime_weights?.[v] || {});
                if (tfs.length > 0) setSelectedTf(tfs[0]);
              }}
              options={allPairs.map((p) => ({ value: p, label: p }))}
              size="sm"
              fullWidth={false}
              ariaLabel="Select pair"
            />
            <Dropdown
              value={selectedTf}
              onChange={setSelectedTf}
              options={allTfs.map((tf) => ({ value: tf, label: tf }))}
              size="sm"
              fullWidth={false}
              ariaLabel="Select timeframe"
            />
          </div>

          {!hasPerPairData && (
            <p className="text-on-surface-variant text-xs text-center py-4">No data for this pair/timeframe</p>
          )}

          {regimeData && (
            <ParameterCategory title={`Regime Weights — ${selectedPair} ${selectedTf}`} descriptions={descriptions}>
              <RegimeGrid regimes={regimeData} />
            </ParameterCategory>
          )}

          {learnedAtr && (
            <ParameterCategory title={`Learned ATR — ${selectedPair} ${selectedTf}`} descriptions={descriptions}>
              <ParameterRow name="sl_atr" value={learnedAtr.sl_atr.value} source={learnedAtr.sl_atr.source} descriptions={descriptions} dotPath={`learned_atr.${selectedPair}.${selectedTf}.current_sl_atr`} onEdit={handleEdit} />
              <ParameterRow name="tp1_atr" value={learnedAtr.tp1_atr.value} source={learnedAtr.tp1_atr.source} descriptions={descriptions} dotPath={`learned_atr.${selectedPair}.${selectedTf}.current_tp1_atr`} onEdit={handleEdit} />
              <ParameterRow name="tp2_atr" value={learnedAtr.tp2_atr.value} source={learnedAtr.tp2_atr.source} descriptions={descriptions} dotPath={`learned_atr.${selectedPair}.${selectedTf}.current_tp2_atr`} onEdit={handleEdit} />
              <ParameterRow name="last_optimized" value={learnedAtr.last_optimized_at || "never"} source="configurable" descriptions={descriptions} />
              <ParameterRow name="signal_count" value={learnedAtr.signal_count} source="configurable" descriptions={descriptions} last />
            </ParameterCategory>
          )}
        </Card>
      </>)}

      <SectionLabel as="h3" color="primary" className="-mb-1">Adaptive Thresholds</SectionLabel>
      <Card variant="low" padding="sm" border>
        {thresholdsLoading ? (
          <p className="text-on-surface-variant text-xs py-2">Loading...</p>
        ) : thresholds ? (
          <>
            <div className="bg-surface-container rounded-lg px-3 py-2 mb-2 inline-block">
              <span className="text-[10px] uppercase tracking-wider text-primary mr-2">Default</span>
              <span className="font-mono text-sm text-on-surface">{thresholds.default.toFixed(2)}</span>
            </div>
            {thresholds.thresholds.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-on-surface-variant text-left">
                      <th className="pb-1 pr-3 font-medium">Pair</th>
                      <th className="pb-1 pr-3 font-medium">Regime</th>
                      <th className="pb-1 font-medium text-right">Threshold</th>
                    </tr>
                  </thead>
                  <tbody>
                    {thresholds.thresholds.map((t) => (
                      <tr key={`${t.pair}-${t.regime}`} className="border-t border-outline-variant/10">
                        <td className="py-1 pr-3 text-on-surface font-mono">{t.pair}</td>
                        <td className="py-1 pr-3 text-on-surface-variant">{t.regime}</td>
                        <td className="py-1 text-on-surface font-mono text-right">{t.value.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-on-surface-variant text-xs text-center py-3">No learned overrides yet</p>
            )}
          </>
        ) : null}
      </Card>
    </div>
  );
}

function formatThreshold(v: unknown): string {
  if (typeof v === "number") return v.toFixed(2);
  if (typeof v === "string") return v;
  return "--";
}
