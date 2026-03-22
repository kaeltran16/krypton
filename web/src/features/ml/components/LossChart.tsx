import { useRef, useEffect, useMemo, useState } from "react";
import { theme } from "../../../shared/theme";

interface LossChartProps {
  data: { epoch: number; train_loss: number; val_loss: number | null }[];
  bestEpoch?: number;
  height?: number;
}

const PADDING = { top: 20, right: 70, bottom: 30, left: 50 };
const TRAIN_COLOR = theme.colors.accent;   // #0EB5E5
const VAL_COLOR = theme.colors.long;       // #2DD4A0
const GRID_COLOR = "rgba(94, 106, 125, 0.2)";
const TEXT_COLOR = theme.colors.muted;     // #8E9AAD
const BEST_COLOR = theme.colors.muted;

export function LossChart({ data, bestEpoch, height = 200 }: LossChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || data.length === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const plotW = width - PADDING.left - PADDING.right;
    const plotH = height - PADDING.top - PADDING.bottom;

    // Compute Y range from all loss values
    const allVals = data.flatMap((d) => [d.train_loss, d.val_loss].filter((v): v is number => v != null));
    if (allVals.length === 0) return;
    const yMin = Math.min(...allVals) * 0.95;
    const yMax = Math.max(...allVals) * 1.05;
    const yRange = yMax - yMin || 1;

    const xMin = data[0].epoch;
    const xMax = data[data.length - 1].epoch;
    const xRange = xMax - xMin || 1;

    const toX = (epoch: number) => PADDING.left + ((epoch - xMin) / xRange) * plotW;
    const toY = (loss: number) => PADDING.top + (1 - (loss - yMin) / yRange) * plotH;

    // Grid lines + Y labels
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 0.5;
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.fillStyle = TEXT_COLOR;
    ctx.textAlign = "right";
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {
      const val = yMin + (yRange * i) / yTicks;
      const y = toY(val);
      ctx.beginPath();
      ctx.moveTo(PADDING.left, y);
      ctx.lineTo(width - PADDING.right, y);
      ctx.stroke();
      ctx.fillText(val.toFixed(3), PADDING.left - 6, y + 3);
    }

    // X labels
    ctx.textAlign = "center";
    const xLabelCount = Math.min(data.length, 5);
    const xStep = Math.max(1, Math.floor(data.length / xLabelCount));
    for (let i = 0; i < data.length; i += xStep) {
      const x = toX(data[i].epoch);
      ctx.fillText(String(data[i].epoch), x, height - PADDING.bottom + 16);
    }

    // Best epoch vertical line
    if (bestEpoch != null) {
      const bx = toX(bestEpoch);
      ctx.save();
      ctx.strokeStyle = BEST_COLOR;
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.beginPath();
      ctx.moveTo(bx, PADDING.top);
      ctx.lineTo(bx, PADDING.top + plotH);
      ctx.stroke();
      ctx.restore();
    }

    // Draw polyline helper
    function drawLine(
      points: { x: number; y: number }[],
      color: string,
      dash: number[] = [],
    ) {
      if (points.length < 2) return;
      ctx!.save();
      ctx!.strokeStyle = color;
      ctx!.lineWidth = 1.5;
      ctx!.setLineDash(dash);
      ctx!.lineJoin = "round";
      ctx!.beginPath();
      ctx!.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx!.lineTo(points[i].x, points[i].y);
      }
      ctx!.stroke();
      ctx!.restore();
    }

    // Train loss line (solid)
    const trainPts = data.map((d) => ({ x: toX(d.epoch), y: toY(d.train_loss) }));
    drawLine(trainPts, TRAIN_COLOR);

    // Val loss line (dashed)
    const valPts = data
      .filter((d) => d.val_loss != null)
      .map((d) => ({ x: toX(d.epoch), y: toY(d.val_loss!) }));
    drawLine(valPts, VAL_COLOR, [6, 3]);

    // Legend (top-right)
    const legendX = width - PADDING.right + 8;
    const legendY = PADDING.top + 4;
    ctx.font = "10px Inter, system-ui, sans-serif";
    ctx.textAlign = "left";

    // Train legend
    ctx.strokeStyle = TRAIN_COLOR;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(legendX, legendY);
    ctx.lineTo(legendX + 16, legendY);
    ctx.stroke();
    ctx.fillStyle = TEXT_COLOR;
    ctx.fillText("Train", legendX + 20, legendY + 3);

    // Val legend
    ctx.strokeStyle = VAL_COLOR;
    ctx.setLineDash([6, 3]);
    ctx.beginPath();
    ctx.moveTo(legendX, legendY + 16);
    ctx.lineTo(legendX + 16, legendY + 16);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillText("Val", legendX + 20, legendY + 19);
  }, [data, bestEpoch, height, containerWidth]);

  const bestVal = useMemo(() => {
    if (data.length === 0) return null;
    let best: typeof data[0] | null = null;
    for (const d of data) {
      if (d.val_loss != null && (best === null || d.val_loss < best.val_loss!)) best = d;
    }
    return best;
  }, [data]);

  const ariaLabel = bestVal
    ? `Loss chart: best validation loss ${bestVal.val_loss?.toFixed(3)} at epoch ${bestVal.epoch} of ${data.length}`
    : "Loss chart: no data";

  return (
    <div ref={containerRef} className="w-full">
      <canvas
        ref={canvasRef}
        aria-label={ariaLabel}
        role="img"
        className="w-full"
      />
    </div>
  );
}
