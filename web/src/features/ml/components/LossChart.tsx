import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { theme } from "../../../shared/theme";

interface LossChartProps {
  data: { epoch: number; train_loss: number; val_loss: number | null }[];
  bestEpoch?: number;
  height?: number;
}

const TRAIN_COLOR = theme.colors.accent;
const VAL_COLOR = theme.colors.long;
const GRID_COLOR = "rgba(94, 106, 125, 0.15)";
const TEXT_COLOR = theme.colors.muted;

export function LossChart({ data, bestEpoch, height = 240 }: LossChartProps) {
  const ariaLabel = useMemo(() => {
    if (data.length === 0) return "Loss chart: no data";
    let bestVal: typeof data[0] | null = null;
    for (const d of data) {
      if (d.val_loss != null && (bestVal === null || d.val_loss < bestVal.val_loss!)) bestVal = d;
    }
    return bestVal
      ? `Loss chart: best validation loss ${bestVal.val_loss?.toFixed(3)} at epoch ${bestVal.epoch} of ${data.length}`
      : `Loss chart: ${data.length} epochs`;
  }, [data]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-muted text-xs"
        style={{ height }}
      >
        No loss data yet
      </div>
    );
  }

  return (
    <div role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" />
          <XAxis
            dataKey="epoch"
            tick={{ fill: TEXT_COLOR, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fill: TEXT_COLOR, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => v.toFixed(3)}
          />
          <Tooltip
            contentStyle={{
              background: theme.colors["surface-container-highest"],
              border: `1px solid ${GRID_COLOR}`,
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: TEXT_COLOR }}
            itemStyle={{ padding: 0 }}
            labelFormatter={(v) => `Epoch ${v}`}
            formatter={(value) => typeof value === "number" ? value.toFixed(4) : String(value)}
          />
          <Legend
            verticalAlign="top"
            align="right"
            iconType="line"
            wrapperStyle={{ fontSize: 11, color: TEXT_COLOR, paddingBottom: 4 }}
          />
          {bestEpoch != null && (
            <ReferenceLine
              x={bestEpoch}
              stroke={TEXT_COLOR}
              strokeDasharray="6 3"
              label={{
                value: "Best",
                position: "top",
                fill: TEXT_COLOR,
                fontSize: 11,
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey="train_loss"
            name="Train"
            stroke={TRAIN_COLOR}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 3, fill: TRAIN_COLOR }}
          />
          <Line
            type="monotone"
            dataKey="val_loss"
            name="Val"
            stroke={VAL_COLOR}
            strokeWidth={2}
            strokeDasharray="8 4"
            dot={false}
            activeDot={{ r: 3, fill: VAL_COLOR }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
