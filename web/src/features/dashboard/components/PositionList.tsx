import type { Position } from "../../../shared/lib/api";
import { formatPrice } from "../../../shared/lib/format";

interface Props {
  positions: Position[];
}

export function PositionList({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="p-4 bg-card rounded-lg">
        <h2 className="text-sm text-gray-400 mb-2">Open Positions</h2>
        <p className="text-gray-500 text-sm">No open positions</p>
      </div>
    );
  }

  return (
    <div className="p-4 bg-card rounded-lg">
      <h2 className="text-sm text-gray-400 mb-3">Open Positions</h2>
      <div className="space-y-3">
        {positions.map((pos) => (
          <PositionRow key={`${pos.pair}-${pos.side}`} position={pos} />
        ))}
      </div>
    </div>
  );
}

function PositionRow({ position }: { position: Position }) {
  const pnlColor = position.unrealized_pnl >= 0 ? "text-long" : "text-short";
  const sideColor = position.side === "long" ? "text-long" : "text-short";

  return (
    <div className="border border-gray-800 rounded-lg p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{position.pair}</span>
          <span className={`text-xs font-mono uppercase ${sideColor}`}>{position.side}</span>
          <span className="text-xs text-gray-500">{position.leverage}x</span>
        </div>
        <span className={`font-mono font-bold ${pnlColor}`}>
          {position.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(position.unrealized_pnl)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-2 text-xs text-gray-400">
        <div>Size: <span className="text-white font-mono">{position.size}</span></div>
        <div>Entry: <span className="text-white font-mono">{formatPrice(position.avg_price)}</span></div>
        <div>Mark: <span className="text-white font-mono">{formatPrice(position.mark_price)}</span></div>
      </div>
    </div>
  );
}
