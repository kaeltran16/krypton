import type { AccountBalance } from "../../../shared/lib/api";
import { formatPrice } from "../../../shared/lib/format";

interface Props {
  balance: AccountBalance | null;
  loading: boolean;
}

export function AccountSummary({ balance, loading }: Props) {
  if (loading) return <div className="p-4 bg-card rounded-lg animate-pulse h-24" />;
  if (!balance) return null;

  const pnlColor = balance.unrealized_pnl >= 0 ? "text-long" : "text-short";

  return (
    <div className="p-4 bg-card rounded-lg space-y-2">
      <h2 className="text-sm text-gray-400">Account</h2>
      <div className="text-2xl font-mono font-bold">${formatPrice(balance.total_equity)}</div>
      <div className="flex gap-4 text-sm">
        <div>
          <span className="text-gray-400">Unrealized P&L </span>
          <span className={`font-mono ${pnlColor}`}>
            {balance.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(balance.unrealized_pnl)}
          </span>
        </div>
        {balance.currencies[0] && (
          <div>
            <span className="text-gray-400">Available </span>
            <span className="font-mono">{formatPrice(balance.currencies[0].available)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
