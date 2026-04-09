import type { PrimitiveHoveredItem, Time, IPrimitivePaneView, IPrimitivePaneRenderer, ISeriesPrimitive } from "lightweight-charts";

import type { TrendLine } from "../../types";
import type { CanvasRenderingTarget2D } from "./types";

const HIT_MARGIN = 8;

type TrendCoords = { x1: number; y1: number; x2: number; y2: number } | null;

function distanceToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) {
    return Math.hypot(px - x1, py - y1);
  }
  let t = ((px - x1) * dx + (py - y1) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

class TrendRenderer implements IPrimitivePaneRenderer {
  private coords: TrendCoords = null;
  private readonly annotation: TrendLine;
  private readonly opacity: number;

  constructor(annotation: TrendLine, opacity: number) {
    this.annotation = annotation;
    this.opacity = opacity;
  }

  setCoords(coords: TrendCoords) {
    this.coords = coords;
  }

  draw(target: CanvasRenderingTarget2D): void {
    if (!this.coords) return;
    const ctx = target.context;
    ctx.save();
    ctx.globalAlpha = this.opacity;
    ctx.strokeStyle = this.annotation.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(this.coords.x1, this.coords.y1);
    ctx.lineTo(this.coords.x2, this.coords.y2);
    ctx.stroke();
    ctx.fillStyle = this.annotation.color;
    ctx.font = "10px Inter, sans-serif";
    ctx.fillText(this.annotation.label, this.coords.x2 + 4, this.coords.y2 - 4);
    ctx.restore();
  }
}

class TrendView implements IPrimitivePaneView {
  private readonly rendererInstance: TrendRenderer;

  constructor(rendererInstance: TrendRenderer) {
    this.rendererInstance = rendererInstance;
  }

  renderer(): IPrimitivePaneRenderer {
    return this.rendererInstance;
  }
}

export class TrendLinePrimitive implements ISeriesPrimitive<Time> {
  private readonly annotation: TrendLine;
  private readonly externalId: string;
  private readonly rendererInstance: TrendRenderer;
  private readonly view: TrendView;
  private coords: TrendCoords = null;
  private requestUpdate?: () => void;

  constructor(annotation: TrendLine, externalId: string, opacity = 1) {
    this.annotation = annotation;
    this.externalId = externalId;
    this.rendererInstance = new TrendRenderer(annotation, opacity);
    this.view = new TrendView(this.rendererInstance);
  }

  attached(params: { requestUpdate: () => void }) {
    this.requestUpdate = params.requestUpdate;
  }

  detached() {
    this.requestUpdate = undefined;
  }

  paneViews() {
    return [this.view];
  }

  updateAllViews() {
    this.rendererInstance.setCoords(this.coords);
  }

  priceAxisViews() {
    return [];
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    if (!this.coords) return null;
    if (
      distanceToSegment(
        x,
        y,
        this.coords.x1,
        this.coords.y1,
        this.coords.x2,
        this.coords.y2,
      ) <= HIT_MARGIN
    ) {
      return { externalId: this.externalId, cursorStyle: "pointer", zOrder: "top" };
    }
    return null;
  }

  setCoordinates(coords: TrendCoords) {
    this.coords = coords;
    this.requestUpdate?.();
  }

  getAnnotation() {
    return this.annotation;
  }
}
