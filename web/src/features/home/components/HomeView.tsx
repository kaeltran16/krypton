import { useState, useMemo } from "react";
import { useAccount } from "../../dashboard/hooks/useAccount";
import { useSignalStats } from "../hooks/useSignalStats";
import { useRecentNews } from "../../news/hooks/useNews";
import { RecentSignals } from "./RecentSignals";
import { MiniSparkline } from "./MiniSparkline";
import { formatPrice, formatRelativeTime, formatPair } from "../../../shared/lib/format";
import { TrendingUp, TrendingDown } from "lucide-react";
import type { Portfolio, Position } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";
import type { NewsEvent } from "../../news/types";

export function HomeView() {
  const { portfolio, positions, loading: accountLoading, error, refresh } = useAccount();
  const { stats, loading: statsLoading } = useSignalStats();
  const { news: recentNews, loading: newsLoading } = useRecentNews(5);

  const equityCurve = useMemo(
    () => stats?.equity_curve.map((d) => d.cumulative_pnl) ?? [],
    [stats?.equity_curve]
  );

  if (error && !portfolio) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <div className="bg-surface-container rounded-lg p-4 text-center">
          <p className="text-on-surface-variant text-sm">Unable to load portfolio</p>
          <button
            onClick={refresh}
            className="mt-2 px-4 py-1.5 text-xs font-medium rounded-lg bg-surface-container-highest text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
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
    <div className="flex flex-col gap-3 p-4">
      <AccountHeader portfolio={portfolio} loading={accountLoading} equityCurve={equityCurve} />
      <PortfolioStrip portfolio={portfolio} loading={accountLoading} />
      <OpenPositions positions={positions} loading={accountLoading} />
      <RecentSignals />
      <LatestNewsCard news={recentNews} loading={newsLoading} />
      <PerformanceCard stats={stats} loading={statsLoading} />
    </div>
  );
}

function AccountHeader({ portfolio, loading, equityCurve = [] }: { portfolio: Portfolio | null; loading: boolean; equityCurve?: number[] }) {
  if (loading) return <div className="h-24 bg-surface-container rounded-lg animate-pulse" />;
  if (!portfolio) return null;

  const pnl = portfolio.unrealized_pnl;
  const pct = portfolio.total_equity > 0 ? (pnl / portfolio.total_equity) * 100 : 0;
  const isPositive = pnl >= 0;

  return (
    <div className="bg-surface-container rounded-lg p-5">
      <span className="text-on-surface-variant text-[10px] uppercase tracking-widest">Total Equity</span>
      <div className="font-headline text-3xl font-bold mt-1 tabular">${formatPrice(portfolio.total_equity)}</div>
      <div className="flex items-center gap-2 mt-3">
        <span className={`font-headline font-bold text-lg tabular ${isPositive ? "text-long" : "text-short"}`}>
          {isPositive ? "+" : ""}${formatPrice(Math.abs(pnl))}
        </span>
        <span className={`text-xs font-bold px-2 py-0.5 rounded tabular ${
          isPositive ? "bg-long/10 text-long" : "bg-short/10 text-short"
        }`}>
          {isPositive ? "+" : ""}{pct.toFixed(1)}%
        </span>
        {equityCurve.length >= 2 && (
          <MiniSparkline data={equityCurve} className="ml-auto opacity-80" />
        )}
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
    <div className="bg-surface-container-low rounded-lg p-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Unrealized</span>
          <span className={`font-headline font-bold text-sm tabular ${portfolio.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
            {portfolio.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(portfolio.unrealized_pnl)}
          </span>
        </div>
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Available</span>
          <span className="font-headline font-bold text-sm tabular">${formatPrice(portfolio.available_balance)}</span>
        </div>
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Margin</span>
          <span className="font-headline font-bold text-sm tabular">{portfolio.margin_utilization.toFixed(1)}%</span>
        </div>
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Exposure</span>
          <span className={`font-headline font-bold text-sm tabular ${exposurePct > 100 ? "text-primary" : ""}`}>
            {exposurePct.toFixed(0)}%
          </span>
        </div>
      </div>
    </div>
  );
}

function OpenPositions({ positions, loading }: { positions: Position[]; loading: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (loading) return <div className="h-16 bg-surface-container rounded-lg animate-pulse" />;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-baseline px-1">
        <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant">
          Open Positions ({positions.length})
        </h2>
      </div>
      {positions.length === 0 ? (
        <p className="px-1 text-sm text-outline">No open positions</p>
      ) : (
        <div className="space-y-2">
          {positions.map((pos) => {
            const key = `${pos.pair}-${pos.side}`;
            const isLong = pos.side === "long";
            const isExpanded = expanded === key;
            const DirIcon = isLong ? TrendingUp : TrendingDown;

            return (
              <div key={key} className="bg-surface-container-high rounded-lg overflow-hidden">
                <button
                  onClick={() => setExpanded(isExpanded ? null : key)}
                  aria-expanded={isExpanded}
                  aria-label={`${formatPair(pos.pair)} ${pos.side} position details`}
                  className="w-full p-3 flex items-center justify-between text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <div className="flex items-center gap-3">
                    <div className={`p-1.5 rounded ${isLong ? "bg-long/10" : "bg-short/10"}`}>
                      <DirIcon size={16} className={isLong ? "text-long" : "text-short"} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-headline font-bold text-sm">{formatPair(pos.pair)}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                          isLong ? "bg-long/20 text-long" : "bg-short/20 text-short"
                        }`}>
                          {pos.side.toUpperCase()} {pos.leverage}x
                        </span>
                      </div>
                      <span className="text-[10px] text-on-surface-variant tabular">Size: {pos.size}</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`font-headline font-bold text-sm block tabular ${pos.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
                      {pos.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(pos.unrealized_pnl)}
                    </span>
                    <span className="text-[10px] text-on-surface-variant tabular">${formatPrice(pos.mark_price)}</span>
                  </div>
                </button>
                {isExpanded && (
                  <div className="px-3 pb-3 grid grid-cols-3 gap-2 bg-surface-container-lowest/30">
                    <div>
                      <span className="text-[10px] text-on-surface-variant block uppercase">Entry</span>
                      <span className="text-xs font-medium tabular">${formatPrice(pos.avg_price)}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-on-surface-variant block uppercase">Mark</span>
                      <span className="text-xs font-medium tabular">${formatPrice(pos.mark_price)}</span>
                    </div>
                    {pos.liquidation_price && (
                      <div>
                        <span className="text-[10px] text-on-surface-variant block uppercase">Liq. Price</span>
                        <span className="text-xs font-medium text-short tabular">${formatPrice(pos.liquidation_price)}</span>
                      </div>
                    )}
                    <div>
                      <span className="text-[10px] text-on-surface-variant block uppercase">Margin</span>
                      <span className="text-xs font-medium tabular">${formatPrice(pos.margin)}</span>
                    </div>
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

const IMPACT_BORDER: Record<string, string> = {
  high: "border-l-error",
  medium: "border-l-primary/40",
};

const SENTIMENT_COLOR: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

function LatestNewsCard({ news, loading }: { news: NewsEvent[]; loading: boolean }) {
  if (loading) return <div className="h-16 bg-surface-container rounded-lg animate-pulse" />;
  if (news.length === 0) return null;

  return (
    <div className="space-y-3">
      <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant px-1">
        Latest News
      </h2>
      <div className="space-y-2">
        {news.map((n) => (
          <div key={n.id} className={`bg-surface-container-low rounded-lg p-3 border-l-4 ${IMPACT_BORDER[n.impact ?? ""] ?? "border-l-outline-variant/20"}`}>
            <p className="text-sm font-medium leading-snug">{n.headline}</p>
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-[10px] text-on-surface-variant tabular">{n.source}</span>
              {n.sentiment && (
                <span className={`text-[10px] font-medium ${SENTIMENT_COLOR[n.sentiment] ?? ""}`}>
                  {n.sentiment}
                </span>
              )}
              <span className="text-[10px] text-outline">{n.published_at ? formatRelativeTime(n.published_at) : ""}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PerformanceCard({ stats, loading }: { stats: SignalStats | null; loading: boolean }) {
  if (loading) return <div className="h-16 bg-surface-container rounded-lg animate-pulse" />;
  if (!stats || stats.total_resolved === 0) return null;

  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <div className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">Performance (7D)</div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className={`text-xl font-headline font-bold tabular ${stats.win_rate >= 50 ? "text-long" : "text-short"}`}>
            {stats.win_rate}%
          </div>
          <div className="text-[10px] text-on-surface-variant">Win Rate</div>
        </div>
        <div>
          <div className="text-xl font-headline font-bold tabular">{stats.avg_rr}</div>
          <div className="text-[10px] text-on-surface-variant">Avg R:R</div>
        </div>
        <div>
          <div className={`text-xl font-headline font-bold tabular ${netPnl >= 0 ? "text-long" : "text-short"}`}>
            {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
          </div>
          <div className="text-[10px] text-on-surface-variant">Net P&L</div>
        </div>
      </div>
    </div>
  );
}
