import { useEffect, useRef } from "react";

interface IndicatorDef {
  id: string;
  label: string;
  studyId: string;
}

interface IndicatorGroup {
  label: string;
  items: IndicatorDef[];
}

const INDICATOR_GROUPS: IndicatorGroup[] = [
  {
    label: "Moving Averages",
    items: [
      { id: "ema21", label: "EMA 21", studyId: "MAExp@tv-basicstudies" },
      { id: "ema50", label: "EMA 50", studyId: "MAExp@tv-basicstudies" },
      { id: "ema200", label: "EMA 200", studyId: "MAExp@tv-basicstudies" },
      { id: "sma21", label: "SMA 21", studyId: "MASimple@tv-basicstudies" },
      { id: "sma50", label: "SMA 50", studyId: "MASimple@tv-basicstudies" },
      { id: "sma200", label: "SMA 200", studyId: "MASimple@tv-basicstudies" },
    ],
  },
  {
    label: "Overlays",
    items: [
      { id: "bb", label: "Bollinger Bands", studyId: "BB@tv-basicstudies" },
      { id: "vwap", label: "VWAP", studyId: "VWAP@tv-basicstudies" },
      { id: "ichimoku", label: "Ichimoku Cloud", studyId: "IchimokuCloud@tv-basicstudies" },
      { id: "supertrend", label: "SuperTrend", studyId: "SuperTrend@tv-basicstudies" },
      { id: "psar", label: "Parabolic SAR", studyId: "PSAR@tv-basicstudies" },
      { id: "pivots", label: "Pivot Points", studyId: "PivotPointsStandard@tv-basicstudies" },
    ],
  },
  {
    label: "Oscillators",
    items: [
      { id: "rsi", label: "RSI", studyId: "RSI@tv-basicstudies" },
      { id: "macd", label: "MACD", studyId: "MACD@tv-basicstudies" },
      { id: "stochrsi", label: "Stochastic RSI", studyId: "StochasticRSI@tv-basicstudies" },
      { id: "cci", label: "CCI", studyId: "CCI@tv-basicstudies" },
      { id: "atr", label: "ATR", studyId: "ATR@tv-basicstudies" },
      { id: "adx", label: "ADX", studyId: "ADX@tv-basicstudies" },
      { id: "willr", label: "Williams %R", studyId: "WilliamsR@tv-basicstudies" },
      { id: "mfi", label: "MFI", studyId: "MFI@tv-basicstudies" },
      { id: "obv", label: "OBV", studyId: "OBV@tv-basicstudies" },
    ],
  },
];

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

export function getStudies(enabledIds: Set<string>): string[] {
  const studies: string[] = [];
  for (const group of INDICATOR_GROUPS) {
    for (const item of group.items) {
      if (enabledIds.has(item.id)) {
        studies.push(item.studyId);
      }
    }
  }
  return studies;
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
                  <span className="text-sm">{item.label}</span>
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
