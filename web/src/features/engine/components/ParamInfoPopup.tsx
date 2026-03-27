import { useState, useRef, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import { useClickOutside } from "../../../shared/hooks/useClickOutside";
import type { ParamDescription } from "../types";

interface Props {
  name: string;
  descriptions?: Record<string, ParamDescription>;
}

export default function ParamInfoPopup({ name, descriptions }: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number; above: boolean }>({ x: 0, y: 0, above: true });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const above = rect.top > 140;
    setPos({
      x: rect.left + rect.width / 2,
      y: above ? rect.top : rect.bottom,
      above,
    });
  }, [open]);

  useClickOutside(popupRef, () => setOpen(false), open);

  const desc = descriptions?.[name];
  if (!desc) return null;

  return (
    <>
      <button
        ref={triggerRef}
        onClick={() => setOpen(!open)}
        className="min-w-[44px] min-h-[44px] flex items-center justify-center -m-4 text-muted hover:text-primary transition-colors"
        aria-label={`Info about ${name}`}
        aria-expanded={open}
      >
        <Info size={14} />
      </button>
      {open && createPortal(
        <div
          ref={popupRef}
          className="fixed z-[100] w-64 bg-surface-container-high border border-outline-variant/50 rounded-lg p-3 shadow-lg"
          style={{
            left: pos.x,
            top: pos.above ? pos.y : pos.y + 8,
            transform: pos.above ? "translate(-50%, -100%) translateY(-8px)" : "translateX(-50%)",
          }}
        >
          <p className="text-xs text-on-surface mb-1.5">{desc.description}</p>
          <div className="flex flex-col gap-1 text-[10px] text-muted">
            <span>Stage: {desc.pipeline_stage}</span>
            <span>Range: {desc.range}</span>
          </div>
          <div
            className={`absolute left-1/2 -translate-x-1/2 rotate-45 w-2 h-2 bg-surface-container-high border-outline-variant/50 ${
              pos.above
                ? "bottom-0 translate-y-1/2 border-r border-b"
                : "top-0 -translate-y-1/2 border-l border-t"
            }`}
          />
        </div>,
        document.body,
      )}
    </>
  );
}
