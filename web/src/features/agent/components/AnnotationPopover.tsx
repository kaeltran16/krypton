import type { Annotation } from "../types";

interface Props {
  annotation: Annotation;
  x: number;
  y: number;
  onClose: () => void;
}

export function AnnotationPopover({ annotation, x, y, onClose }: Props) {
  return (
    <div
      className="absolute z-20 max-w-72 rounded-xl border border-white/10 bg-surface-container px-3 py-2 shadow-2xl"
      style={{ left: x, top: y }}
      role="dialog"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
          {annotation.type}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-[10px] text-white/40 hover:text-white/70"
        >
          Close
        </button>
      </div>
      {"label" in annotation && annotation.label ? (
        <div className="mb-1 text-xs font-medium text-white/85">{annotation.label}</div>
      ) : null}
      <div className="text-xs leading-relaxed text-white/70">{annotation.reasoning}</div>
    </div>
  );
}
