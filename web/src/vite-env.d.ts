/// <reference types="vite/client" />

declare module "fancy-canvas" {
  export interface CanvasRenderingTarget2D {
    context: CanvasRenderingContext2D;
    mediaSize?: {
      width: number;
      height: number;
    };
    bitmapSize?: {
      width: number;
      height: number;
    };
  }
}
