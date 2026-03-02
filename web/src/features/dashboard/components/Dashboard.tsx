import { useAccount } from "../hooks/useAccount";
import { AccountSummary } from "./AccountSummary";
import { PositionList } from "./PositionList";

export function Dashboard() {
  const { balance, positions, loading, error } = useAccount();

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-bold">Dashboard</h1>
      {error && (
        <div className="p-3 bg-short/10 border border-short/30 rounded-lg text-sm text-short">
          {error}
        </div>
      )}
      <AccountSummary balance={balance} loading={loading} />
      <PositionList positions={positions} />
    </div>
  );
}
