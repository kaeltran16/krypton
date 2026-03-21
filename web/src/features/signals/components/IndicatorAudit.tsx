import { computeRegime } from "../types";
import type { RawIndicators } from "../types";

interface IndicatorAuditProps {
  indicators: RawIndicators;
}

interface IndicatorRow {
  label: string;
  value: number;
  max: number;
  format: (v: number) => string;
  color?: string;
}

function getRows(ind: RawIndicators): IndicatorRow[] {
  const rows: IndicatorRow[] = [];

  if (ind.rsi != null) {
    rows.push({
      label: "RSI (14)",
      value: ind.rsi,
      max: 100,
      format: (v) => v.toFixed(1),
      color: ind.rsi > 70 ? "bg-error" : ind.rsi < 30 ? "bg-long" : "bg-primary",
    });
  }

  if (ind.adx != null) {
    rows.push({
      label: "ADX",
      value: ind.adx,
      max: 60,
      format: (v) => v.toFixed(1),
    });
  }

  if (ind.bb_pos != null) {
    rows.push({
      label: "BB Position",
      value: ind.bb_pos * 100,
      max: 100,
      format: (v) => `${v.toFixed(0)}%`,
    });
  }

  if (ind.vol_ratio != null) {
    rows.push({
      label: "Volume",
      value: Math.min(ind.vol_ratio * 50, 100),
      max: 100,
      format: () => `${ind.vol_ratio!.toFixed(2)}x avg`,
    });
  }

  if (ind.obv_slope != null) {
    rows.push({
      label: "OBV Flow",
      value: Math.min(Math.abs(ind.obv_slope) * 5000, 100),
      max: 100,
      format: () => (ind.obv_slope! >= 0 ? "Accumulation" : "Distribution"),
      color: ind.obv_slope >= 0 ? "bg-long" : "bg-short",
    });
  }

  return rows;
}

export function IndicatorAudit({ indicators }: IndicatorAuditProps) {
  const rows = getRows(indicators);
  if (rows.length === 0) return null;

  const regime = computeRegime(indicators);

  return (
    <div className="p-5 border-b border-outline-variant/10 space-y-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant">
        Indicator Breakdown
      </h3>

      {rows.map((row) => (
        <div key={row.label} className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-on-surface-variant">{row.label}</span>
            <span className="font-mono tabular-nums text-on-surface">
              {row.format(row.value)}
            </span>
          </div>
          <div
            role="progressbar"
            aria-valuenow={Math.round(row.value)}
            aria-valuemin={0}
            aria-valuemax={row.max}
            aria-label={`${row.label}: ${row.format(row.value)}`}
            className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden"
          >
            <div
              className={`h-full rounded-full transition-all ${row.color ?? "bg-primary"}`}
              style={{ width: `${Math.min((row.value / row.max) * 100, 100)}%` }}
            />
          </div>
        </div>
      ))}

      {regime && <RegimeBar regime={regime} />}
    </div>
  );
}

function RegimeBar({ regime }: { regime: { trending: number; ranging: number; volatile: number; dominant: string; dominantPct: number } }) {
  const total = regime.trending + regime.ranging + regime.volatile || 1;
  const pcts = {
    trending: (regime.trending / total) * 100,
    ranging: (regime.ranging / total) * 100,
    volatile: (regime.volatile / total) * 100,
  };
  const label = regime.dominant.charAt(0).toUpperCase() + regime.dominant.slice(1);

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-on-surface-variant">Market Regime</span>
        <span className="font-mono tabular-nums text-on-surface">{label}</span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={Math.round(Math.max(pcts.trending, pcts.ranging, pcts.volatile))}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Market Regime: ${label} (Trend ${pcts.trending.toFixed(0)}%, Range ${pcts.ranging.toFixed(0)}%, Vol ${pcts.volatile.toFixed(0)}%)`}
        className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden flex"
      >
        {pcts.trending > 0 && (
          <div className="h-full bg-primary" style={{ width: `${pcts.trending}%` }} />
        )}
        {pcts.ranging > 0 && (
          <div className="h-full bg-outline" style={{ width: `${pcts.ranging}%` }} />
        )}
        {pcts.volatile > 0 && (
          <div className="h-full bg-error" style={{ width: `${pcts.volatile}%` }} />
        )}
      </div>
      <div className="flex gap-3 text-[10px] text-on-surface-variant">
        <span>Trend {pcts.trending.toFixed(0)}%</span>
        <span>Range {pcts.ranging.toFixed(0)}%</span>
        <span>Vol {pcts.volatile.toFixed(0)}%</span>
      </div>
    </div>
  );
}
