import type { PrimitiveHoveredItem, Time, IPrimitivePaneView, IPrimitivePaneRenderer, ISeriesPrimitive } from "lightweight-charts";

import { theme } from "../../../../shared/theme";
import type { PositionMarker } from "../../types";
import type { CanvasRenderingTarget2D } from "./types";

const HIT_MARGIN = 6;

type PositionCoords = { entry: number | null; sl: number | null; tp: number | null } | null;

class PositionRenderer implements IPrimitivePaneRenderer {
  private coords: PositionCoords = null;
  private readonly annotation: PositionMarker;
  private readonly opacity: number;

  constructor(annotation: PositionMarker, opacity: number) {
    this.annotation = annotation;
    this.opacity = opacity;
  }

  setCoords(coords: PositionCoords) {
    this.coords = coords;
  }

  draw(target: CanvasRenderingTarget2D): void {
    if (!this.coords || this.coords.entry === null) return;
    const ctx = target.context;
    const width = target.mediaSize?.width ?? target.bitmapSize?.width ?? 0;
    const entryColor =
      this.annotation.direction === "long"
        ? theme.annotations.position_long
        : theme.annotations.position_short;

    const drawLine = (y: number | null, color: string, label: string, dashed = false) => {
      if (y === null) return;
      ctx.save();
      ctx.globalAlpha = this.opacity;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      if (dashed) {
        ctx.setLineDash([5, 4]);
      }
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "10px Inter, sans-serif";
      ctx.fillText(label, 8, y - 4);
      ctx.restore();
    };

    drawLine(this.coords.entry, entryColor, "Entry");
    drawLine(this.coords.sl, theme.annotations.sl, "SL", true);
    drawLine(this.coords.tp, theme.annotations.tp, "TP", true);
  }
}

class PositionView implements IPrimitivePaneView {
  private readonly rendererInstance: PositionRenderer;

  constructor(rendererInstance: PositionRenderer) {
    this.rendererInstance = rendererInstance;
  }

  renderer(): IPrimitivePaneRenderer {
    return this.rendererInstance;
  }
}

export class PositionPrimitive implements ISeriesPrimitive<Time> {
  private readonly annotation: PositionMarker;
  private readonly externalId: string;
  private readonly rendererInstance: PositionRenderer;
  private readonly view: PositionView;
  private coords: PositionCoords = null;
  private requestUpdate?: () => void;

  constructor(annotation: PositionMarker, externalId: string, opacity = 1) {
    this.annotation = annotation;
    this.externalId = externalId;
    this.rendererInstance = new PositionRenderer(annotation, opacity);
    this.view = new PositionView(this.rendererInstance);
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

  hitTest(_x: number, y: number): PrimitiveHoveredItem | null {
    if (!this.coords) return null;
    const lines = [this.coords.entry, this.coords.sl, this.coords.tp].filter(
      (value): value is number => value !== null,
    );
    if (lines.some((lineY) => Math.abs(y - lineY) <= HIT_MARGIN)) {
      return { externalId: this.externalId, cursorStyle: "pointer", zOrder: "top" };
    }
    return null;
  }

  setCoordinates(coords: PositionCoords) {
    this.coords = coords;
    this.requestUpdate?.();
  }

  getAnnotation() {
    return this.annotation;
  }
}
