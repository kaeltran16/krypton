import { useMemo } from "react";
import { useAccount } from "../../dashboard/hooks/useAccount";
import { useSignalStats } from "../hooks/useSignalStats";
import { useRecentNews } from "../../news/hooks/useNews";
import { RecentSignals } from "./RecentSignals";
import { MiniSparkline } from "./MiniSparkline";
import { formatPrice, formatPricePrecision, formatRelativeTime, formatPair, formatElapsed } from "../../../shared/lib/format";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";
import { type Portfolio, type Position } from "../../../shared/lib/api";
import { Button } from "../../../shared/components/Button";
import { Badge } from "../../../shared/components/Badge";
import { MetricCard } from "../../../shared/components/MetricCard";
import { Skeleton } from "../../../shared/components/Skeleton";
import { SectionLabel } from "../../../shared/components/SectionLabel";
import { useNavigationStore } from "../../../shared/stores/navigation";
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

  return (
    <>
      {error && !portfolio ? (
        <div className="flex flex-col gap-3 p-4">
          <div className="bg-surface-container rounded-lg p-4 text-center">
            <p className="text-on-surface-variant text-sm">Unable to load portfolio</p>
            <Button variant="secondary" onClick={refresh} className="mt-2">Retry</Button>
          </div>
          <RecentSignals />
          <LatestNewsCard news={recentNews} loading={newsLoading} />
          <PerformanceCard stats={stats} loading={statsLoading} />
        </div>
      ) : (
        <div className="flex flex-col gap-3 p-4">
          <AccountHeader portfolio={portfolio} loading={accountLoading} equityCurve={equityCurve} />
          <PortfolioStrip portfolio={portfolio} positions={positions} loading={accountLoading} />
          <OpenPositions positions={positions} loading={accountLoading} onRefresh={refresh} />
          <RecentSignals />
          <LatestNewsCard news={recentNews} loading={newsLoading} />
          <PerformanceCard stats={stats} loading={statsLoading} />
        </div>
      )}
    </>
  );
}

function AccountHeader({ portfolio, loading, equityCurve = [] }: { portfolio: Portfolio | null; loading: boolean; equityCurve?: number[] }) {
  if (loading) return <Skeleton height="h-24" />;
  if (!portfolio) return null;

  const pnl = portfolio.unrealized_pnl;
  const pct = portfolio.total_equity > 0 ? (pnl / portfolio.total_equity) * 100 : 0;
  const isPositive = pnl >= 0;

  return (
    <div className="bg-surface-container rounded-lg p-5">
      <span className="text-on-surface-variant text-xs uppercase tracking-widest">Total Equity</span>
      <div className="font-headline text-3xl font-bold mt-1 tabular">${formatPrice(portfolio.total_equity)}</div>
      <div className="flex items-center gap-2 mt-3">
        <span className={`font-headline font-bold text-lg tabular ${isPositive ? "text-long" : "text-short"}`}>
          {isPositive ? "+" : ""}${formatPrice(Math.abs(pnl))}
        </span>
        <Badge color={isPositive ? "long" : "short"} className="px-2 tabular">
          {isPositive ? "+" : ""}{pct.toFixed(1)}%
        </Badge>
        {equityCurve.length >= 2 && (
          <MiniSparkline data={equityCurve} className="ml-auto opacity-80" />
        )}
      </div>
    </div>
  );
}

function PortfolioStrip({ portfolio, positions, loading }: { portfolio: Portfolio | null; positions: Position[]; loading: boolean }) {
  if (loading || !portfolio) return null;

  const exposurePct = portfolio.total_equity > 0
    ? (portfolio.total_exposure / portfolio.total_equity * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <MetricCard
        label="Positions"
        value={positions.length}
        color={positions.length > 0 ? "text-primary" : "text-on-surface"}
      />
      <MetricCard
        label="Available"
        value={`$${formatPrice(portfolio.available_balance)}`}
      />
      <MetricCard
        label="Margin"
        value={`${portfolio.margin_utilization.toFixed(1)}%`}
      />
      <MetricCard
        label="Exposure"
        value={`${exposurePct.toFixed(0)}%`}
        color={exposurePct > 100 ? "text-primary" : "text-on-surface"}
      />
    </div>
  );
}

function OpenPositions({ positions, loading }: { positions: Position[]; loading: boolean; onRefresh: () => void }) {
  const navigateToPosition = useNavigationStore((s) => s.navigateToPosition);

  if (loading) return <Skeleton height="h-20" />;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-baseline px-1">
        <SectionLabel as="h2">Open Positions ({positions.length})</SectionLabel>
      </div>
      {positions.length === 0 ? (
        <p className="px-1 text-sm text-outline">No open positions &mdash; the engine is monitoring for opportunities</p>
      ) : (
        <div className="space-y-2">
          {positions.map((pos) => {
            const key = `${pos.pair}-${pos.side}`;
            const isLong = pos.side === "long";
            const DirIcon = isLong ? TrendingUp : TrendingDown;
            const roi = pos.margin > 0 ? (pos.unrealized_pnl / pos.margin) * 100 : 0;
            const liqDist = pos.liquidation_price && pos.mark_price > 0
              ? Math.abs((pos.mark_price - pos.liquidation_price) / pos.mark_price * 100)
              : null;
            const timeOpen = formatElapsed(pos.created_at);

            return (
              <button
                key={key}
                onClick={() => navigateToPosition(pos.pair, pos.side)}
                aria-label={`${formatPair(pos.pair)} ${pos.side} position — tap for details`}
                className="w-full bg-surface-container-high rounded-lg p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary active:scale-[0.98] transition-transform"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`p-1.5 rounded ${isLong ? "bg-long/10" : "bg-short/10"}`}>
                      <DirIcon size={16} className={isLong ? "text-long" : "text-short"} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-headline font-bold text-sm">{formatPair(pos.pair)}</span>
                        <Badge color={isLong ? "long" : "short"}>
                          {pos.side.toUpperCase()} {pos.leverage}x
                        </Badge>
                      </div>
                      {timeOpen && (
                        <span className="text-xs text-on-surface-variant">{timeOpen}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-right">
                      <span className={`font-headline font-bold text-sm block tabular ${pos.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
                        {pos.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(pos.unrealized_pnl)}
                      </span>
                      <span className={`text-xs font-medium tabular ${roi >= 0 ? "text-long" : "text-short"}`}>
                        {roi >= 0 ? "+" : ""}{roi.toFixed(1)}%
                      </span>
                    </div>
                    <ChevronRight size={16} className="text-outline" />
                  </div>
                </div>
                <div className="flex items-center gap-4 mt-2 text-xs text-on-surface-variant">
                  <span className="tabular">Mark ${formatPricePrecision(pos.mark_price, pos.pair)}</span>
                  {liqDist != null && (
                    <span className="tabular text-short/80">Liq {liqDist.toFixed(1)}%</span>
                  )}
                </div>
              </button>
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
  if (loading) return <Skeleton height="h-24" />;

  return (
    <div className="space-y-3">
      <SectionLabel as="h2">Latest News</SectionLabel>
      {news.length === 0 ? (
        <p className="px-1 text-sm text-outline">No recent news &mdash; feeds are being monitored</p>
      ) : (
      <div className="space-y-2">
        {news.map((n) => {
          const cls = `bg-surface-container-low rounded-lg p-3 border-l-4 ${IMPACT_BORDER[n.impact ?? ""] ?? "border-l-outline-variant/20"}`;
          const inner = (
            <>
              <p className="text-sm font-medium leading-snug">{n.headline}</p>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-xs text-on-surface-variant tabular">{n.source}</span>
                {n.sentiment && (
                  <span className={`text-xs font-medium ${SENTIMENT_COLOR[n.sentiment] ?? ""}`}>
                    {n.sentiment}
                  </span>
                )}
                <span className="text-xs text-outline">{n.published_at ? formatRelativeTime(n.published_at) : ""}</span>
              </div>
            </>
          );

          return n.url ? (
            <a key={n.id} href={n.url} target="_blank" rel="noopener noreferrer" className={`block active:bg-surface-container/50 transition-colors ${cls}`}>
              {inner}
            </a>
          ) : (
            <div key={n.id} className={cls}>
              {inner}
            </div>
          );
        })}
      </div>
      )}
    </div>
  );
}

function PerformanceCard({ stats, loading }: { stats: SignalStats | null; loading: boolean }) {
  if (loading) return <Skeleton height="h-28" />;
  if (!stats || stats.total_resolved === 0) return null;

  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <div className="text-xs uppercase tracking-widest text-on-surface-variant mb-3">Performance (7D)</div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className={`text-xl font-headline font-bold tabular ${stats.win_rate >= 50 ? "text-long" : "text-short"}`}>
            {stats.win_rate}%
          </div>
          <div className="text-xs text-on-surface-variant">Win Rate</div>
        </div>
        <div>
          <div className="text-xl font-headline font-bold tabular">{stats.avg_rr}</div>
          <div className="text-xs text-on-surface-variant">Avg R:R</div>
        </div>
        <div>
          <div className={`text-xl font-headline font-bold tabular ${netPnl >= 0 ? "text-long" : "text-short"}`}>
            {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
          </div>
          <div className="text-xs text-on-surface-variant">Net P&L</div>
        </div>
      </div>
    </div>
  );
}
