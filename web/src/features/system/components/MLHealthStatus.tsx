import { useEffect, useState } from "react";
import { api } from "../../../shared/lib/api";
import type { MLHealthResponse } from "../types";

export function MLHealthStatus() {
  const [data, setData] = useState<MLHealthResponse | null>(null);

  useEffect(() => {
    api.getMLHealth().then(setData).catch(() => {});
  }, []);

  if (!data) {
    return (
      <div className="space-y-2">
        <StatusRow label="ML Ensemble" value="Loading..." color="text-on-surface-variant" />
        <StatusRow label="Regime Classifier" value="Loading..." color="text-on-surface-variant" />
      </div>
    );
  }

  const { ensemble, regime_classifier } = data.ml_health;

  const ensembleColor =
    ensemble.members_loaded === 0
      ? "text-short"
      : ensemble.members_stale > 0
        ? "text-primary"
        : "text-long";

  const ensembleText =
    ensemble.members_loaded === 0
      ? "No models"
      : ensemble.members_stale > 0
        ? `${ensemble.members_loaded - ensemble.members_stale}/${ensemble.members_loaded} models, ${ensemble.members_stale} stale`
        : `${ensemble.members_loaded} models (${ensemble.pairs_loaded} pairs)`;

  const regimeColor = regime_classifier.active ? "text-long" : "text-primary";
  const regimeText = regime_classifier.active
    ? `Classifier active${regime_classifier.age_days !== null ? ` (${regime_classifier.age_days}d)` : ""}`
    : "Using heuristic fallback";

  return (
    <div className="space-y-2">
      <StatusRow label="ML Ensemble" value={ensembleText} color={ensembleColor} />
      <StatusRow label="Regime" value={regimeText} color={regimeColor} />
    </div>
  );
}

function StatusRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-[10px] font-bold text-on-surface-variant uppercase">{label}</span>
      <span className={`text-xs font-bold tabular-nums ${color}`}>{value}</span>
    </div>
  );
}
