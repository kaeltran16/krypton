import type { PrimitiveHoveredItem, Time, IPrimitivePaneView, IPrimitivePaneRenderer, ISeriesPrimitive } from "lightweight-charts";

import type { HorizontalLevel } from "../../types";
import type { CanvasRenderingTarget2D } from "./types";

const HIT_MARGIN = 6;

class HorizontalRenderer implements IPrimitivePaneRenderer {
  private y: number | null = null;
  private readonly annotation: HorizontalLevel;
  private readonly opacity: number;

  constructor(annotation: HorizontalLevel, opacity: number) {
    this.annotation = annotation;
    this.opacity = opacity;
  }

  setY(y: number | null) {
    this.y = y;
  }

  draw(target: CanvasRenderingTarget2D): void {
    if (this.y === null) return;
    const ctx = target.context;
    const width = target.mediaSize?.width ?? target.bitmapSize?.width ?? 0;

    ctx.save();
    ctx.globalAlpha = this.opacity;
    ctx.strokeStyle = this.annotation.color;
    ctx.lineWidth = 1;
    if (this.annotation.style === "dashed") {
      ctx.setLineDash([6, 4]);
    }
    ctx.beginPath();
    ctx.moveTo(0, this.y);
    ctx.lineTo(width, this.y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = this.annotation.color;
    ctx.font = "11px Inter, sans-serif";
    ctx.fillText(this.annotation.label, 8, this.y - 4);
    ctx.restore();
  }
}

class HorizontalView implements IPrimitivePaneView {
  private readonly rendererInstance: HorizontalRenderer;

  constructor(rendererInstance: HorizontalRenderer) {
    this.rendererInstance = rendererInstance;
  }

  renderer(): IPrimitivePaneRenderer {
    return this.rendererInstance;
  }
}

export class HorizontalPrimitive implements ISeriesPrimitive<Time> {
  private readonly annotation: HorizontalLevel;
  private readonly externalId: string;
  private readonly rendererInstance: HorizontalRenderer;
  private readonly view: HorizontalView;
  private y: number | null = null;
  private requestUpdate?: () => void;

  constructor(annotation: HorizontalLevel, externalId: string, opacity = 1) {
    this.annotation = annotation;
    this.externalId = externalId;
    this.rendererInstance = new HorizontalRenderer(annotation, opacity);
    this.view = new HorizontalView(this.rendererInstance);
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
    this.rendererInstance.setY(this.y);
  }

  priceAxisViews() {
    return [];
  }

  hitTest(_x: number, y: number): PrimitiveHoveredItem | null {
    if (this.y === null) return null;
    if (Math.abs(y - this.y) <= HIT_MARGIN) {
      return { externalId: this.externalId, cursorStyle: "pointer", zOrder: "top" };
    }
    return null;
  }

  setCoordinate(y: number | null) {
    this.y = y;
    this.requestUpdate?.();
  }

  getAnnotation() {
    return this.annotation;
  }
}
