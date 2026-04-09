import type { PrimitiveHoveredItem, Time, IPrimitivePaneView, IPrimitivePaneRenderer, ISeriesPrimitive } from "lightweight-charts";

import type { Zone } from "../../types";
import type { CanvasRenderingTarget2D } from "./types";

type ZoneCoords = { y1: number; y2: number; x1?: number; x2?: number } | null;

class ZoneRenderer implements IPrimitivePaneRenderer {
  private coords: ZoneCoords = null;
  private readonly annotation: Zone;
  private readonly opacity: number;

  constructor(annotation: Zone, opacity: number) {
    this.annotation = annotation;
    this.opacity = opacity;
  }

  setCoords(coords: ZoneCoords) {
    this.coords = coords;
  }

  draw(target: CanvasRenderingTarget2D): void {
    if (!this.coords) return;
    const ctx = target.context;
    const width = target.mediaSize?.width ?? target.bitmapSize?.width ?? 0;
    const { y1, y2, x1, x2 } = this.coords;
    const left = x1 ?? 0;
    const right = x2 ?? width;
    const top = Math.min(y1, y2);
    const height = Math.abs(y2 - y1);

    ctx.save();
    ctx.globalAlpha = this.opacity * 0.15;
    ctx.fillStyle = this.annotation.color;
    ctx.fillRect(left, top, right - left, height);
    ctx.globalAlpha = this.opacity * 0.45;
    ctx.strokeStyle = this.annotation.color;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(left, top, right - left, height);
    ctx.setLineDash([]);
    ctx.globalAlpha = this.opacity;
    ctx.fillStyle = this.annotation.color;
    ctx.font = "10px Inter, sans-serif";
    ctx.fillText(this.annotation.label, left + 4, top - 4);
    ctx.restore();
  }
}

class ZoneView implements IPrimitivePaneView {
  private readonly rendererInstance: ZoneRenderer;

  constructor(rendererInstance: ZoneRenderer) {
    this.rendererInstance = rendererInstance;
  }

  renderer(): IPrimitivePaneRenderer {
    return this.rendererInstance;
  }
}

export class ZonePrimitive implements ISeriesPrimitive<Time> {
  private readonly annotation: Zone;
  private readonly externalId: string;
  private readonly rendererInstance: ZoneRenderer;
  private readonly view: ZoneView;
  private coords: ZoneCoords = null;
  private requestUpdate?: () => void;

  constructor(annotation: Zone, externalId: string, opacity = 1) {
    this.annotation = annotation;
    this.externalId = externalId;
    this.rendererInstance = new ZoneRenderer(annotation, opacity);
    this.view = new ZoneView(this.rendererInstance);
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
    const { y1, y2, x1, x2 } = this.coords;
    const left = x1 ?? 0;
    const right = x2 ?? Number.MAX_SAFE_INTEGER;
    if (y >= Math.min(y1, y2) && y <= Math.max(y1, y2) && x >= left && x <= right) {
      return { externalId: this.externalId, cursorStyle: "pointer", zOrder: "normal" };
    }
    return null;
  }

  setCoordinates(coords: ZoneCoords) {
    this.coords = coords;
    this.requestUpdate?.();
  }

  getAnnotation() {
    return this.annotation;
  }
}
