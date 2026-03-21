import { useEffect, useState } from "react";
import { useEngineStore } from "../store";
import ParameterCategory from "./ParameterCategory";
import ParameterRow from "./ParameterRow";
import WeightBar from "./WeightBar";
import RegimeGrid from "./RegimeGrid";
import { Dropdown } from "../../../shared/components/Dropdown";

export default function EnginePage() {
  const { params, loading, error, fetch, refresh } = useEngineStore();
  const [selectedPair, setSelectedPair] = useState("");
  const [selectedTf, setSelectedTf] = useState("");

  useEffect(() => { fetch(); }, [fetch]);

  useEffect(() => {
    if (!params) return;
    const pairs = Object.keys(params.regime_weights || {});
    if (pairs.length > 0 && !selectedPair) {
      setSelectedPair(pairs[0]);
      const tfs = Object.keys(params.regime_weights[pairs[0]] || {});
      if (tfs.length > 0) setSelectedTf(tfs[0]);
    }
  }, [params, selectedPair]);

  if (loading) return <div className="p-4 text-muted text-sm">Loading parameters...</div>;
  if (error) return <div className="p-4 text-red-400 text-sm">Error: {error}</div>;
  if (!params) return null;

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

  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-foreground">Engine Parameters</h3>
        <button onClick={refresh} className="text-xs text-accent hover:text-accent/80">
          Refresh
        </button>
      </div>

      <ParameterCategory title="Blending" defaultOpen>
        <WeightBar weights={params.blending.source_weights} />
        <ParameterRow name="ml_blend_weight" value={params.blending.ml_blend_weight.value} source={params.blending.ml_blend_weight.source} />
        {Object.entries(params.blending.thresholds).map(([k, v], i, arr) => (
          <ParameterRow key={k} name={k} value={v.value} source={v.source} last={i === arr.length - 1} />
        ))}
      </ParameterCategory>

      <ParameterCategory title="LLM Factor Weights" params={params.blending.llm_factor_weights}>
        <ParameterRow name="factor_cap" value={params.blending.llm_factor_cap.value} source={params.blending.llm_factor_cap.source} last />
      </ParameterCategory>

      <ParameterCategory title="Technical — Indicators" params={params.technical.indicator_periods} />
      <ParameterCategory title="Technical — Sigmoid Params" params={params.technical.sigmoid_params} />
      <ParameterCategory title="Technical — Mean Reversion" params={params.technical.mean_reversion} />
      <ParameterCategory title="Order Flow" params={params.order_flow.regime_params}>
        {Object.entries(params.order_flow.max_scores).map(([k, v]) => (
          <ParameterRow key={k} name={`max_${k}`} value={v.value} source={v.source} />
        ))}
      </ParameterCategory>
      <ParameterCategory title="On-Chain — BTC" params={params.onchain.btc_profile as Record<string, any>} />
      <ParameterCategory title="On-Chain — ETH" params={params.onchain.eth_profile as Record<string, any>} />
      <ParameterCategory title="Levels & ATR" params={params.levels.atr_defaults} />
      <ParameterCategory title="ATR Guardrails" params={params.levels.atr_guardrails} />
      <ParameterCategory title="Phase 1 Scaling" params={params.levels.phase1_scaling} />
      <ParameterCategory title="Pattern Strengths" params={params.patterns.strengths} />
      <ParameterCategory title="Performance Tracker" params={params.performance_tracker.optimization_params} />
      <ParameterCategory title="Optimization Guardrails" params={params.performance_tracker.guardrails} />

      {allPairs.length > 0 && (
        <>
          <div className="flex gap-2 pt-2">
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

          {regimeData && (
            <ParameterCategory title={`Regime Weights — ${selectedPair} ${selectedTf}`}>
              <RegimeGrid regimes={regimeData} />
            </ParameterCategory>
          )}

          {learnedAtr && (
            <ParameterCategory title={`Learned ATR — ${selectedPair} ${selectedTf}`}>
              <ParameterRow name="sl_atr" value={learnedAtr.sl_atr.value} source={learnedAtr.sl_atr.source} />
              <ParameterRow name="tp1_atr" value={learnedAtr.tp1_atr.value} source={learnedAtr.tp1_atr.source} />
              <ParameterRow name="tp2_atr" value={learnedAtr.tp2_atr.value} source={learnedAtr.tp2_atr.source} />
              <ParameterRow name="last_optimized" value={learnedAtr.last_optimized_at || "never"} source="configurable" />
              <ParameterRow name="signal_count" value={learnedAtr.signal_count} source="configurable" last />
            </ParameterCategory>
          )}
        </>
      )}
    </div>
  );
}
