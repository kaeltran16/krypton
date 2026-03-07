import { useAccount } from "../../dashboard/hooks/useAccount";
import { useSignalStats } from "../hooks/useSignalStats";
import { RecentSignals } from "./RecentSignals";
import { formatPrice } from "../../../shared/lib/format";
import type { AccountBalance, Position } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";

interface Props {
  pair: string;
}

export function HomeView({ pair }: Props) {
  const { balance, positions, loading: accountLoading } = useAccount();
  const { stats, loading: statsLoading } = useSignalStats();

  return (
    <div className="flex flex-col gap-2 p-3">
      <AccountHeader balance={balance} loading={accountLoading} />
      <AccountStrip balance={balance} loading={accountLoading} />
      <OpenPositions positions={positions} loading={accountLoading} />
      <RecentSignals />
      <PerformanceCard stats={stats} loading={statsLoading} />
    </div>
  );
}

function AccountHeader({ balance, loading }: { balance: AccountBalance | null; loading: boolean }) {
  if (loading) return <div className="h-20 bg-card rounded-lg animate-pulse" />;
  if (!balance) return null;

  const pnl = balance.unrealized_pnl;
  const pct = balance.total_equity > 0 ? (pnl / balance.total_equity) * 100 : 0;
  const isPositive = pnl >= 0;

  return (
    <div className="bg-card rounded-lg p-4 border border-border">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] text-muted uppercase tracking-wider">Account Balance</div>
          <div className="text-2xl font-mono font-bold mt-1">${formatPrice(balance.total_equity)}</div>
        </div>
        <div className="text-right">
          <div className={`text-sm font-mono font-bold ${isPositive ? "text-long" : "text-short"}`}>
            {isPositive ? "+" : ""}{pct.toFixed(1)}%
          </div>
          <div className={`text-xs font-mono ${isPositive ? "text-long" : "text-short"}`}>
            {isPositive ? "+" : ""}${formatPrice(Math.abs(pnl))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountStrip({ balance, loading }: { balance: AccountBalance | null; loading: boolean }) {
  if (loading || !balance) return null;

  const available = balance.currencies[0]?.available ?? 0;
  const margin = balance.total_equity > 0
    ? ((balance.total_equity - available) / balance.total_equity * 100)
    : 0;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-sm font-mono font-bold ${balance.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
            {balance.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(balance.unrealized_pnl)}
          </div>
          <div className="text-[10px] text-muted uppercase">Unrealized P&L</div>
        </div>
        <div>
          <div className="text-sm font-mono font-bold">${formatPrice(available)}</div>
          <div className="text-[10px] text-muted uppercase">Available</div>
        </div>
        <div>
          <div className="text-sm font-mono font-bold">{margin.toFixed(1)}%</div>
          <div className="text-[10px] text-muted uppercase">Margin</div>
        </div>
      </div>
    </div>
  );
}

function OpenPositions({ positions, loading }: { positions: Position[]; loading: boolean }) {
  if (loading) return <div className="h-16 bg-card rounded-lg animate-pulse" />;

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="px-3 pt-3 pb-2">
        <span className="text-[10px] text-muted uppercase tracking-wider">
          Open Positions ({positions.length})
        </span>
      </div>
      {positions.length === 0 ? (
        <p className="px-3 pb-3 text-sm text-dim">No open positions</p>
      ) : (
        <div className="divide-y divide-border">
          {positions.map((pos) => {
            const isLong = pos.side === "long";
            return (
              <div key={`${pos.pair}-${pos.side}`} className="px-3 py-2.5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{pos.pair.replace("-USDT-SWAP", "")}</span>
                  <span className={`text-xs font-mono font-bold uppercase ${isLong ? "text-long" : "text-short"}`}>
                    {pos.side}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs font-mono">
                  <span className={pos.unrealized_pnl >= 0 ? "text-long" : "text-short"}>
                    {pos.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(pos.unrealized_pnl)}
                  </span>
                  <span className="text-muted">${formatPrice(pos.mark_price)}</span>
                  <span className="text-dim">{pos.size}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PerformanceCard({ stats, loading }: { stats: SignalStats | null; loading: boolean }) {
  if (loading) return <div className="h-16 bg-card rounded-lg animate-pulse" />;
  if (!stats || stats.total_resolved === 0) return null;

  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Performance (7D)</div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-lg font-mono font-bold ${stats.win_rate >= 50 ? "text-long" : "text-short"}`}>
            {stats.win_rate}%
          </div>
          <div className="text-[10px] text-muted">Win Rate</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold">{stats.avg_rr}</div>
          <div className="text-[10px] text-muted">Avg R:R</div>
        </div>
        <div>
          <div className={`text-lg font-mono font-bold ${netPnl >= 0 ? "text-long" : "text-short"}`}>
            {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
          </div>
          <div className="text-[10px] text-muted">Net P&L</div>
        </div>
      </div>
    </div>
  );
}
