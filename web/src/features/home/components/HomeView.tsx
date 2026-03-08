import { useState } from "react";
import { useAccount } from "../../dashboard/hooks/useAccount";
import { useSignalStats } from "../hooks/useSignalStats";
import { useRecentNews } from "../../news/hooks/useNews";
import { RecentSignals } from "./RecentSignals";
import { formatPrice, formatRelativeTime } from "../../../shared/lib/format";
import type { Portfolio, Position } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";
import type { NewsEvent } from "../../news/types";

export function HomeView() {
  const { portfolio, positions, loading: accountLoading, error, refresh } = useAccount();
  const { stats, loading: statsLoading } = useSignalStats();
  const { news: recentNews, loading: newsLoading } = useRecentNews(5);

  if (error && !portfolio) {
    return (
      <div className="flex flex-col gap-2 p-3">
        <div className="bg-card rounded-lg p-4 border border-border text-center">
          <p className="text-muted text-sm">Unable to load portfolio</p>
          <button
            onClick={refresh}
            className="mt-2 px-4 py-1.5 text-xs font-medium rounded-lg bg-accent/15 text-accent"
          >
            Retry
          </button>
        </div>
        <RecentSignals />
        <LatestNewsCard news={recentNews} loading={newsLoading} />
        <PerformanceCard stats={stats} loading={statsLoading} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-3">
      <AccountHeader portfolio={portfolio} loading={accountLoading} />
      <PortfolioStrip portfolio={portfolio} loading={accountLoading} />
      <OpenPositions positions={positions} loading={accountLoading} />
      <RecentSignals />
      <LatestNewsCard news={recentNews} loading={newsLoading} />
      <PerformanceCard stats={stats} loading={statsLoading} />
    </div>
  );
}

function AccountHeader({ portfolio, loading }: { portfolio: Portfolio | null; loading: boolean }) {
  if (loading) return <div className="h-20 bg-card rounded-lg animate-pulse" />;
  if (!portfolio) return null;

  const pnl = portfolio.unrealized_pnl;
  const pct = portfolio.total_equity > 0 ? (pnl / portfolio.total_equity) * 100 : 0;
  const isPositive = pnl >= 0;

  return (
    <div className="bg-card rounded-lg p-4 border border-border">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] text-muted uppercase tracking-wider">Account Balance</div>
          <div className="text-2xl font-mono font-bold mt-1">${formatPrice(portfolio.total_equity)}</div>
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

function PortfolioStrip({ portfolio, loading }: { portfolio: Portfolio | null; loading: boolean }) {
  if (loading || !portfolio) return null;

  const exposurePct = portfolio.total_equity > 0
    ? (portfolio.total_exposure / portfolio.total_equity * 100)
    : 0;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <div className="grid grid-cols-4 gap-2 text-center">
        <div>
          <div className={`text-sm font-mono font-bold ${portfolio.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
            {portfolio.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(portfolio.unrealized_pnl)}
          </div>
          <div className="text-[10px] text-muted uppercase">Unrealized</div>
        </div>
        <div>
          <div className="text-sm font-mono font-bold">${formatPrice(portfolio.available_balance)}</div>
          <div className="text-[10px] text-muted uppercase">Available</div>
        </div>
        <div>
          <div className="text-sm font-mono font-bold">{portfolio.margin_utilization.toFixed(1)}%</div>
          <div className="text-[10px] text-muted uppercase">Margin</div>
        </div>
        <div>
          <div className={`text-sm font-mono font-bold ${exposurePct > 100 ? "text-accent" : ""}`}>
            {exposurePct.toFixed(0)}%
          </div>
          <div className="text-[10px] text-muted uppercase">Exposure</div>
        </div>
      </div>
    </div>
  );
}

function OpenPositions({ positions, loading }: { positions: Position[]; loading: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null);

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
            const key = `${pos.pair}-${pos.side}`;
            const isLong = pos.side === "long";
            const isExpanded = expanded === key;

            return (
              <div key={key}>
                <button
                  onClick={() => setExpanded(isExpanded ? null : key)}
                  className="w-full px-3 py-2.5 flex items-center justify-between text-left"
                >
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
                </button>
                {isExpanded && (
                  <div className="px-3 pb-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <div className="text-muted">Entry Price</div>
                    <div className="font-mono text-right">${formatPrice(pos.avg_price)}</div>
                    <div className="text-muted">Mark Price</div>
                    <div className="font-mono text-right">${formatPrice(pos.mark_price)}</div>
                    <div className="text-muted">Size</div>
                    <div className="font-mono text-right">{pos.size}</div>
                    {pos.liquidation_price && (
                      <>
                        <div className="text-muted">Liquidation</div>
                        <div className="font-mono text-right text-short">${formatPrice(pos.liquidation_price)}</div>
                      </>
                    )}
                    <div className="text-muted">Leverage</div>
                    <div className="font-mono text-right">{pos.leverage}x</div>
                    <div className="text-muted">Margin</div>
                    <div className="font-mono text-right">${formatPrice(pos.margin)}</div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const IMPACT_BADGE: Record<string, string> = {
  high: "bg-short/20 text-short",
  medium: "bg-accent/20 text-accent",
};

const SENTIMENT_COLOR: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-muted",
};

function LatestNewsCard({ news, loading }: { news: NewsEvent[]; loading: boolean }) {
  if (loading) return <div className="h-16 bg-card rounded-lg animate-pulse" />;
  if (news.length === 0) return null;

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="px-3 pt-3 pb-2">
        <span className="text-[10px] text-muted uppercase tracking-wider">Latest News</span>
      </div>
      <div className="divide-y divide-border">
        {news.map((n) => (
          <div key={n.id} className="px-3 py-2 flex items-start gap-2">
            <div className="flex-1 min-w-0">
              <p className="text-xs leading-snug truncate">{n.headline}</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[10px] text-dim">{n.source}</span>
                {n.impact && (
                  <span className={`text-[9px] px-1 py-0.5 rounded font-medium ${IMPACT_BADGE[n.impact] ?? "bg-card-hover text-dim"}`}>
                    {n.impact}
                  </span>
                )}
                {n.sentiment && (
                  <span className={`text-[9px] font-medium ${SENTIMENT_COLOR[n.sentiment] ?? ""}`}>
                    {n.sentiment}
                  </span>
                )}
              </div>
            </div>
            <span className="text-[10px] text-dim whitespace-nowrap">
              {n.published_at ? formatRelativeTime(n.published_at) : ""}
            </span>
          </div>
        ))}
      </div>
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
