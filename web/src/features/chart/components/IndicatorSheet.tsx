import { useEffect, useRef } from "react";

export interface IndicatorDef {
  id: string;
  label: string;
  pane: "overlay" | "oscillator";
  color: string;
}

interface IndicatorGroup {
  label: string;
  items: IndicatorDef[];
}

const INDICATOR_GROUPS: IndicatorGroup[] = [
  {
    label: "Moving Averages",
    items: [
      { id: "ema21", label: "EMA 21", pane: "overlay", color: "#F0B90B" },
      { id: "ema50", label: "EMA 50", pane: "overlay", color: "#3B82F6" },
      { id: "ema200", label: "EMA 200", pane: "overlay", color: "#A855F7" },
      { id: "sma21", label: "SMA 21", pane: "overlay", color: "#F59E0B" },
      { id: "sma50", label: "SMA 50", pane: "overlay", color: "#6366F1" },
      { id: "sma200", label: "SMA 200", pane: "overlay", color: "#EC4899" },
    ],
  },
  {
    label: "Overlays",
    items: [
      { id: "bb", label: "Bollinger Bands", pane: "overlay", color: "#6B7280" },
      { id: "vwap", label: "VWAP", pane: "overlay", color: "#F97316" },
      { id: "ichimoku", label: "Ichimoku Cloud", pane: "overlay", color: "#EF4444" },
      { id: "supertrend", label: "SuperTrend", pane: "overlay", color: "#10B981" },
      { id: "psar", label: "Parabolic SAR", pane: "overlay", color: "#8B5CF6" },
      { id: "pivots", label: "Support / Resistance", pane: "overlay", color: "#14B8A6" },
    ],
  },
  {
    label: "Oscillators",
    items: [
      { id: "rsi", label: "RSI", pane: "oscillator", color: "#F0B90B" },
      { id: "macd", label: "MACD", pane: "oscillator", color: "#3B82F6" },
      { id: "stochrsi", label: "Stochastic RSI", pane: "oscillator", color: "#10B981" },
      { id: "cci", label: "CCI", pane: "oscillator", color: "#F97316" },
      { id: "atr", label: "ATR", pane: "oscillator", color: "#EC4899" },
      { id: "adx", label: "ADX", pane: "oscillator", color: "#8B5CF6" },
      { id: "willr", label: "Williams %R", pane: "oscillator", color: "#14B8A6" },
      { id: "mfi", label: "MFI", pane: "oscillator", color: "#EF4444" },
      { id: "obv", label: "OBV", pane: "oscillator", color: "#6366F1" },
    ],
  },
];

// Flat map for chart to look up indicator config
export const INDICATOR_MAP = new Map<string, IndicatorDef>();
for (const group of INDICATOR_GROUPS) {
  for (const item of group.items) {
    INDICATOR_MAP.set(item.id, item);
  }
}

const OSCILLATOR_IDS = new Set(
  INDICATOR_GROUPS.find((g) => g.label === "Oscillators")!.items.map((i) => i.id)
);

export function hasOscillator(enabledIds: Set<string>): boolean {
  for (const id of enabledIds) {
    if (OSCILLATOR_IDS.has(id)) return true;
  }
  return false;
}

const STORAGE_KEY = "krypton:indicators";

export function getStoredIndicators(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw));
  } catch {}
  return new Set();
}

function saveIndicators(ids: Set<string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
}

interface Props {
  open: boolean;
  onClose: () => void;
  enabled: Set<string>;
  onToggle: (id: string) => void;
}

export function IndicatorSheet({ open, onClose, enabled, onToggle }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [open]);

  const handleToggle = (id: string) => {
    const next = new Set(enabled);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    saveIndicators(next);
    onToggle(id);
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
    >
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">Indicators</h2>
          <button onClick={onClose} className="text-muted p-1">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {INDICATOR_GROUPS.map((group) => (
          <div key={group.label} className="mb-4">
            <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-2">
              {group.label}
            </h3>
            <div className="space-y-1">
              {group.items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleToggle(item.id)}
                  className="flex items-center justify-between w-full px-3 py-2.5 rounded-lg active:bg-card-hover transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-sm">{item.label}</span>
                  </div>
                  <div
                    className={`w-9 h-5 rounded-full relative transition-colors ${
                      enabled.has(item.id) ? "bg-accent" : "bg-border"
                    }`}
                  >
                    <div
                      className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                        enabled.has(item.id) ? "translate-x-4" : "translate-x-0.5"
                      }`}
                    />
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </dialog>
  );
}
