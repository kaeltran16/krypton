import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown } from "lucide-react";
import { api, type Position } from "../../../shared/lib/api";
import { formatPrice, formatPricePrecision, formatPair, formatElapsed } from "../../../shared/lib/format";
import { Badge } from "../../../shared/components/Badge";
import { Button } from "../../../shared/components/Button";
import { Skeleton } from "../../../shared/components/Skeleton";
import { PartialCloseDialog } from "./PartialCloseDialog";
import { AdjustSlTpDialog } from "./AdjustSlTpDialog";
import { AddToPositionDialog } from "./AddToPositionDialog";

interface Props {
  positions: Position[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export function OpenPositions({ positions, loading, error, onRefresh }: Props) {
  const [fundingByPair, setFundingByPair] = useState<Record<string, number>>({});

  // Fetch funding costs once for all unique pairs
  useEffect(() => {
    if (positions.length === 0) return;
    const uniquePairs = [...new Set(positions.map((p) => p.pair))];
    Promise.all(
      uniquePairs.map((pair) =>
        api.getFundingCosts(pair)
          .then((r) => [pair, r.total_funding] as const)
          .catch(() => [pair, null] as const)
      )
    ).then((results) => {
      const map: Record<string, number> = {};
      for (const [pair, total] of results) {
        if (total != null) map[pair] = total;
      }
      setFundingByPair(map);
    });
  }, [positions]);

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton height="h-48" />
        <Skeleton height="h-48" />
      </div>
    );
  }

  if (error && positions.length === 0) {
    return (
      <div className="bg-surface-container rounded-lg p-6 text-center">
        <p className="text-on-surface-variant text-sm mb-3">Failed to load positions</p>
        <Button variant="secondary" onClick={onRefresh}>Retry</Button>
      </div>
    );
  }

  if (positions.length === 0) {
    return (
      <div className="bg-surface-container rounded-lg p-6 text-center">
        <p className="text-on-surface-variant text-sm">
          No open positions &mdash; the engine is monitoring for opportunities
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {positions.map((pos) => (
        <PositionCard
          key={`${pos.pair}-${pos.side}`}
          position={pos}
          fundingTotal={fundingByPair[pos.pair] ?? null}
          onRefresh={onRefresh}
        />
      ))}
    </div>
  );
}

type Dialog = "close" | "partial" | "sltp" | "add" | null;

function PositionCard({ position: pos, fundingTotal, onRefresh }: { position: Position; fundingTotal: number | null; onRefresh: () => void }) {
  const [dialog, setDialog] = useState<Dialog>(null);
  const [closing, setClosing] = useState(false);

  const isLong = pos.side === "long";
  const DirIcon = isLong ? TrendingUp : TrendingDown;
  const roi = pos.margin > 0 ? (pos.unrealized_pnl / pos.margin) * 100 : 0;
  const notional = Math.abs(pos.size * pos.mark_price);
  const liqDist = pos.liquidation_price && pos.mark_price > 0
    ? Math.abs((pos.mark_price - pos.liquidation_price) / pos.mark_price * 100)
    : null;
  const timeOpen = formatElapsed(pos.created_at);

  async function handleFullClose() {
    setClosing(true);
    try {
      await api.closePosition(pos.pair, pos.side);
      onRefresh();
    } catch {
      // refresh will show updated state
    } finally {
      setClosing(false);
    }
  }

  return (
    <>
      <div className="bg-surface-container-high rounded-lg overflow-hidden">
        {/* Header */}
        <div className="p-4 pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`p-1.5 rounded ${isLong ? "bg-long/10" : "bg-short/10"}`}>
                <DirIcon size={16} className={isLong ? "text-long" : "text-short"} />
              </div>
              <div className="flex items-center gap-2">
                <span className="font-headline font-bold text-sm">{formatPair(pos.pair)}</span>
                <Badge color={isLong ? "long" : "short"}>
                  {pos.side.toUpperCase()} {pos.leverage}x
                </Badge>
              </div>
            </div>
            {timeOpen && (
              <span className="text-xs text-on-surface-variant">{timeOpen}</span>
            )}
          </div>

          {/* P&L row */}
          <div className="flex items-baseline gap-3 mt-3">
            <span className={`font-headline font-bold text-lg tabular ${pos.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
              {pos.unrealized_pnl >= 0 ? "+" : ""}${formatPrice(Math.abs(pos.unrealized_pnl))}
            </span>
            <Badge color={roi >= 0 ? "long" : "short"} className="tabular">
              {roi >= 0 ? "+" : ""}{roi.toFixed(2)}%
            </Badge>
          </div>
        </div>

        {/* Data grid */}
        <div className="px-4 pb-3 grid grid-cols-3 gap-x-4 gap-y-2">
          <DataCell label="Entry" value={`$${formatPricePrecision(pos.avg_price, pos.pair)}`} />
          <DataCell label="Mark" value={`$${formatPricePrecision(pos.mark_price, pos.pair)}`} />
          <DataCell
            label="Liquidation"
            value={pos.liquidation_price
              ? `$${formatPricePrecision(pos.liquidation_price, pos.pair)}`
              : "—"
            }
            sub={liqDist != null ? `${liqDist.toFixed(1)}%` : undefined}
            subColor="text-short/80"
          />
          <DataCell label="Margin" value={`$${formatPrice(pos.margin)}`} />
          <DataCell label="Notional" value={`$${formatPrice(notional)}`} />
          <DataCell
            label="Funding"
            value={fundingTotal != null ? `$${fundingTotal.toFixed(4)}` : "—"}
            subColor={fundingTotal != null && fundingTotal < 0 ? "text-short/80" : "text-long/80"}
          />
        </div>

        {/* Action buttons */}
        <div className="px-4 pb-4 grid grid-cols-2 gap-2">
          <Button variant="short" size="sm" loading={closing} onClick={handleFullClose}>
            Close
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setDialog("partial")}>
            Partial Close
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setDialog("sltp")}>
            Adjust SL/TP
          </Button>
          <Button variant="primary" size="sm" onClick={() => setDialog("add")}>
            Add to Position
          </Button>
        </div>
      </div>

      {dialog === "partial" && (
        <PartialCloseDialog
          position={pos}
          onClose={() => setDialog(null)}
          onSuccess={() => { setDialog(null); onRefresh(); }}
        />
      )}
      {dialog === "sltp" && (
        <AdjustSlTpDialog
          position={pos}
          onClose={() => setDialog(null)}
          onSuccess={() => { setDialog(null); onRefresh(); }}
        />
      )}
      {dialog === "add" && (
        <AddToPositionDialog
          position={pos}
          onClose={() => setDialog(null)}
          onSuccess={() => { setDialog(null); onRefresh(); }}
        />
      )}
    </>
  );
}

function DataCell({ label, value, sub, subColor }: { label: string; value: string; sub?: string; subColor?: string }) {
  return (
    <div>
      <span className="text-[10px] text-on-surface-variant uppercase tracking-wider block">{label}</span>
      <span className="text-xs font-medium tabular">{value}</span>
      {sub && <span className={`text-[10px] ml-1 tabular ${subColor ?? ""}`}>{sub}</span>}
    </div>
  );
}
