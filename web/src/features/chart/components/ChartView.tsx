import { useState } from "react";
import { useChartData } from "../hooks/useChartData";
import { CandlestickChart } from "./CandlestickChart";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

export function ChartView() {
  const [pair, setPair] = useState<string>(AVAILABLE_PAIRS[0]);
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const { candles, loading } = useChartData(pair, timeframe);

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      <div className="p-4 flex items-center gap-3">
        <select
          value={pair}
          onChange={(e) => setPair(e.target.value)}
          className="bg-card border border-gray-800 rounded-lg px-3 py-2 text-sm"
        >
          {AVAILABLE_PAIRS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1.5 rounded text-sm ${
                timeframe === tf
                  ? "bg-long/20 text-long border border-long/30"
                  : "bg-card text-gray-400 border border-gray-800"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 px-4 pb-4">
        {loading ? (
          <div className="w-full h-full bg-card rounded-lg animate-pulse" />
        ) : (
          <CandlestickChart candles={candles} />
        )}
      </div>
    </div>
  );
}
