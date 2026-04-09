import type { PrimitiveHoveredItem, Time, IPrimitivePaneView, IPrimitivePaneRenderer, ISeriesPrimitive } from "lightweight-charts";

import { theme } from "../../../../shared/theme";
import type { RegimeZone } from "../../types";
import type { CanvasRenderingTarget2D } from "./types";

const REGIME_COLORS: Record<RegimeZone["regime"], string> = {
  trending: theme.annotations.regime_trending,
  ranging: theme.annotations.regime_ranging,
  volatile: theme.annotations.regime_volatile,
  steady: theme.annotations.regime_steady,
};

type RegimeCoords = { x1: number; x2: number } | null;

class RegimeRenderer implements IPrimitivePaneRenderer {
  private coords: RegimeCoords = null;
  private readonly annotation: RegimeZone;
  private readonly opacity: number;

  constructor(annotation: RegimeZone, opacity: number) {
    this.annotation = annotation;
    this.opacity = opacity;
  }

  setCoords(coords: RegimeCoords) {
    this.coords = coords;
  }

  draw(target: CanvasRenderingTarget2D): void {
    if (!this.coords) return;
    const ctx = target.context;
    const height = target.mediaSize?.height ?? target.bitmapSize?.height ?? 0;
    const color = REGIME_COLORS[this.annotation.regime] ?? theme.annotations.regime_steady;

    ctx.save();
    ctx.globalAlpha = this.opacity * 0.08;
    ctx.fillStyle = color;
    ctx.fillRect(this.coords.x1, 0, this.coords.x2 - this.coords.x1, height);
    ctx.globalAlpha = this.opacity * 0.7;
    ctx.fillStyle = color;
    ctx.font = "9px Inter, sans-serif";
    ctx.fillText(
      `${this.annotation.regime} (${Math.round(this.annotation.confidence * 100)}%)`,
      this.coords.x1 + 4,
      14,
    );
    ctx.restore();
  }
}

class RegimeView implements IPrimitivePaneView {
  private readonly rendererInstance: RegimeRenderer;

  constructor(rendererInstance: RegimeRenderer) {
    this.rendererInstance = rendererInstance;
  }

  renderer(): IPrimitivePaneRenderer {
    return this.rendererInstance;
  }
}

export class RegimeZonePrimitive implements ISeriesPrimitive<Time> {
  private readonly annotation: RegimeZone;
  private readonly externalId: string;
  private readonly rendererInstance: RegimeRenderer;
  private readonly view: RegimeView;
  private coords: RegimeCoords = null;
  private requestUpdate?: () => void;

  constructor(annotation: RegimeZone, externalId: string, opacity = 1) {
    this.annotation = annotation;
    this.externalId = externalId;
    this.rendererInstance = new RegimeRenderer(annotation, opacity);
    this.view = new RegimeView(this.rendererInstance);
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
    if (x >= this.coords.x1 && x <= this.coords.x2 && y <= 20) {
      return { externalId: this.externalId, cursorStyle: "pointer", zOrder: "normal" };
    }
    return null;
  }

  setCoordinates(x1: number, x2: number) {
    this.coords = { x1, x2 };
    this.requestUpdate?.();
  }

  getAnnotation() {
    return this.annotation;
  }
}
