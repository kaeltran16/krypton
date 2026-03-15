// ─── Design Tokens ─────────────────────────────────────────────
// Single source of truth for all visual constants.
// Tailwind config consumes `colors` + `fontFamily`.
// Chart components import `chart` + `indicators`.
// CSS custom properties in index.css mirror the `glass` + `gradient` values.

export const theme = {
  // ── Semantic colors (Tailwind utilities: bg-surface, text-muted, etc.) ──
  colors: {
    // Surfaces
    surface: "#0B0E11",
    card: "#12161C",
    "card-hover": "#1A1F28",
    border: "#1E2530",

    // Text
    foreground: "#EAECEF",
    muted: "#848E9C",
    dim: "#5E6673",

    // Trading
    long: "#0ECB81",
    short: "#F6465D",
    accent: "#F0B90B",

    // Extended palette (indicators, tool icons, badges)
    blue: "#3B82F6",
    purple: "#8B5CF6",
    pink: "#EC4899",
    orange: "#F97316",
    teal: "#14B8A6",
    indigo: "#6366F1",
    neutral: "#6B7280",
  },

  // ── Font stacks ──
  fontFamily: {
    sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
    mono: ["JetBrains Mono", "Fira Code", "monospace"],
  },

  // ── Body gradient stops ──
  gradient: {
    from: "#0d1117",
    via: "#0B0E11",
    to: "#080a0e",
  },

  // ── Glass / transparency (used in CSS via custom properties) ──
  glass: {
    card: "rgba(18, 22, 28, 0.65)",
    dialog: "rgba(18, 22, 28, 0.9)",
    border: "rgba(255, 255, 255, 0.06)",
    backdrop: "rgba(0, 0, 0, 0.7)",
    blur: { nav: "24px", dialog: "20px", card: "12px" },
  },

  // ── Chart config (lightweight-charts API) ──
  chart: {
    background: "#12161C",     // = colors.card
    text: "#848E9C",           // = colors.muted
    grid: "rgba(31, 41, 55, 0.5)",
    scaleBorder: "#1E2530",    // = colors.border
    candleUp: "#0ECB81",       // = colors.long
    candleDown: "#F6465D",     // = colors.short
    volumeUp: "rgba(14, 203, 129, 0.3)",
    volumeDown: "rgba(246, 70, 93, 0.3)",
    macdHistUp: "rgba(14, 203, 129, 0.6)",
    macdHistDown: "rgba(246, 70, 93, 0.6)",
  },

  // ── Indicator line colors (ordered for visual distinction) ──
  indicators: {
    ema21: "#F0B90B",    // accent / gold
    ema50: "#3B82F6",    // blue
    ema200: "#A855F7",   // violet
    sma21: "#F59E0B",    // amber
    sma50: "#6366F1",    // indigo
    sma200: "#EC4899",   // pink
    rsi: "#F0B90B",
    macd: "#3B82F6",
    macdSignal: "#F97316",
    stochK: "#10B981",
    stochD: "#EF4444",
    bb: "#6B7280",       // neutral
    vwap: "#F97316",
    ichTenkan: "#2196F3",
    ichKijun: "#EF4444",
    ichSenkouA: "#0ECB81",
    ichSenkouB: "#F6465D",
    supertrend: "#10B981",
    psar: "#8B5CF6",
    pivots: "#14B8A6",
    cci: "#F97316",
    atr: "#EC4899",
    adx: "#8B5CF6",
    willr: "#14B8A6",
    mfi: "#EF4444",
    obv: "#6366F1",
    curveColors: ["#F0B90B", "#0ECB81", "#F6465D", "#3B82F6"],
  },
} as const;
