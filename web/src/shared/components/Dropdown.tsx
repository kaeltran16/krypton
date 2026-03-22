import { useState, useRef, useEffect, useCallback } from "react";
import { ChevronDown, Check } from "lucide-react";
import { hapticTap } from "../lib/haptics";
import { useClickOutside } from "../hooks/useClickOutside";

export interface DropdownOption {
  value: string;
  label: string;
}

interface DropdownProps {
  options: DropdownOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  size?: "sm" | "md";
  fullWidth?: boolean;
}

export function Dropdown({
  options,
  value,
  onChange,
  placeholder = "Select…",
  ariaLabel,
  size = "md",
  fullWidth = true,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [focusIdx, setFocusIdx] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selected = options.find((o) => o.value === value);

  const close = useCallback(() => {
    setOpen(false);
    setFocusIdx(-1);
  }, []);

  useClickOutside(containerRef, close, open);

  // Scroll focused item into view
  useEffect(() => {
    if (!open || focusIdx < 0) return;
    const items = listRef.current?.children;
    if (items?.[focusIdx]) {
      (items[focusIdx] as HTMLElement).scrollIntoView({ block: "nearest" });
    }
  }, [focusIdx, open]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setOpen(true);
        setFocusIdx(options.findIndex((o) => o.value === value));
      }
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setFocusIdx((i) => (i + 1) % options.length);
        break;
      case "ArrowUp":
        e.preventDefault();
        setFocusIdx((i) => (i - 1 + options.length) % options.length);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (focusIdx >= 0) {
          hapticTap();
          onChange(options[focusIdx].value);
        }
        close();
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        close();
        break;
    }
  };

  const pick = (val: string) => {
    hapticTap();
    onChange(val);
    close();
  };

  const isSm = size === "sm";

  return (
    <div
      ref={containerRef}
      className={`relative ${fullWidth ? "w-full" : "w-fit"}`}
      onKeyDown={handleKeyDown}
    >
      {/* Trigger */}
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        onClick={() => {
          hapticTap();
          if (open) close();
          else {
            setOpen(true);
            setFocusIdx(options.findIndex((o) => o.value === value));
          }
        }}
        className={`flex items-center justify-between gap-2 bg-surface-container-lowest border border-outline-variant/20 rounded-lg text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary active:scale-[0.98] ${
          open ? "border-primary/50 ring-1 ring-primary/30" : ""
        } ${fullWidth ? "w-full" : ""} ${
          isSm ? "min-h-[32px] px-2.5 py-1 text-xs" : "min-h-[44px] px-3 py-2 text-sm"
        }`}
      >
        <span className={selected ? "text-on-surface truncate" : "text-on-surface-variant truncate"}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown
          size={isSm ? 12 : 14}
          className={`shrink-0 text-on-surface-variant transition-transform duration-150 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Panel */}
      {open && (
        <ul
          ref={listRef}
          role="listbox"
          aria-activedescendant={focusIdx >= 0 ? `dropdown-opt-${focusIdx}` : undefined}
          className={`absolute z-50 mt-1 left-0 right-0 max-h-60 overflow-y-auto rounded-lg border border-outline-variant/20 bg-surface-container backdrop-blur-xl shadow-lg shadow-black/30 ${
            isSm ? "py-0.5" : "py-1"
          }`}
        >
          {options.map((opt, i) => {
            const isSelected = opt.value === value;
            const isFocused = i === focusIdx;
            return (
              <li
                key={opt.value}
                id={`dropdown-opt-${i}`}
                role="option"
                aria-selected={isSelected}
                onMouseEnter={() => setFocusIdx(i)}
                onClick={() => pick(opt.value)}
                className={`flex items-center justify-between cursor-pointer transition-colors ${
                  isSm
                    ? "min-h-[32px] px-2.5 py-1 text-xs"
                    : "min-h-[44px] px-3 py-2 text-sm"
                } ${
                  isFocused
                    ? "bg-surface-container-high"
                    : ""
                } ${
                  isSelected
                    ? "text-primary font-medium"
                    : "text-on-surface"
                }`}
              >
                <span className="truncate">{opt.label}</span>
                {isSelected && (
                  <Check size={isSm ? 12 : 14} className="shrink-0 text-primary" />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
