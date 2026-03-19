import type { RegimeCapWeights } from "../types";

interface Props {
  regimes: Record<string, RegimeCapWeights>;
}

const REGIMES = ["trending", "ranging", "volatile"] as const;

export default function RegimeGrid({ regimes }: Props) {
  if (!regimes || Object.keys(regimes).length === 0) return null;

  const capKeys = Object.keys(regimes[REGIMES[0]]?.inner_caps || {});
  const weightKeys = Object.keys(regimes[REGIMES[0]]?.outer_weights || {});

  return (
    <div className="px-3 py-2 space-y-3">
      <div>
        <div className="text-[10px] text-muted mb-1 uppercase">inner caps</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted">
              <th className="text-left font-normal py-1"></th>
              {capKeys.map((k) => (
                <th key={k} className="text-right font-normal py-1 px-1">{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {REGIMES.map((r) => (
              <tr key={r} className="border-t border-border/30">
                <td className="py-1 text-muted capitalize">{r}</td>
                {capKeys.map((k) => (
                  <td key={k} className="text-right py-1 px-1 font-mono">
                    {regimes[r]?.inner_caps[k] ?? "-"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="text-[10px] text-muted mb-1 uppercase">outer weights</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted">
              <th className="text-left font-normal py-1"></th>
              {weightKeys.map((k) => (
                <th key={k} className="text-right font-normal py-1 px-1">{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {REGIMES.map((r) => (
              <tr key={r} className="border-t border-border/30">
                <td className="py-1 text-muted capitalize">{r}</td>
                {weightKeys.map((k) => (
                  <td key={k} className="text-right py-1 px-1 font-mono">
                    {regimes[r]?.outer_weights[k]?.toFixed(2) ?? "-"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
