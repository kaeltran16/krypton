import { useState, useRef, useEffect, useLayoutEffect } from "react";
import { Info } from "lucide-react";

interface ParamDescription {
  description: string;
  pipeline_stage: string;
  range: string;
}

interface Props {
  name: string;
  descriptions?: Record<string, ParamDescription>;
}

export default function ParamInfoPopup({ name, descriptions }: Props) {
  const [open, setOpen] = useState(false);
  const [above, setAbove] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  const desc = descriptions?.[name];
  if (!desc) return null;

  useLayoutEffect(() => {
    if (!open || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    setAbove(rect.top > 140);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent | TouchEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("touchstart", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("touchstart", handler);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="min-w-[44px] min-h-[44px] flex items-center justify-center -m-4 text-muted hover:text-primary transition-colors"
        aria-label={`Info about ${name}`}
        aria-expanded={open}
      >
        <Info size={14} />
      </button>
      {open && (
        <div
          className={`absolute z-50 left-1/2 -translate-x-1/2 w-64 bg-surface-container-high border border-outline-variant/50 rounded-lg p-3 shadow-lg ${
            above ? "bottom-full mb-2" : "top-full mt-2"
          }`}
        >
          <p className="text-xs text-on-surface mb-1.5">{desc.description}</p>
          <div className="flex flex-col gap-1 text-[10px] text-muted">
            <span>Stage: {desc.pipeline_stage}</span>
            <span>Range: {desc.range}</span>
          </div>
          <div className={`absolute left-1/2 -translate-x-1/2 rotate-45 w-2 h-2 bg-surface-container-high border-outline-variant/50 ${
            above
              ? "bottom-0 translate-y-1/2 border-r border-b"
              : "top-0 -translate-y-1/2 border-l border-t"
          }`} />
        </div>
      )}
    </div>
  );
}
