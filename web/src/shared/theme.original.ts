// ─── Design Tokens ─────────────────────────────────────────────
// "The Kinetic Terminal" — M3 tonal surface hierarchy.
// Single source of truth. Tailwind config consumes colors + fontFamily + borderRadius.
// Chart components import chart + indicators.

export const theme = {
  colors: {
    // ── M3 Surface Hierarchy ──
    surface: "#0a0f14",
    "surface-dim": "#0a0f14",
    "surface-container-lowest": "#000000",
    "surface-container-low": "#0e141a",
    "surface-container": "#141a21",
    "surface-container-high": "#1a2028",
    "surface-container-highest": "#1f262f",
    "surface-bright": "#252d36",
    "surface-variant": "#1f262f",
    "surface-tint": "#69daff",
    background: "#0a0f14",

    // ── Primary (cyan) ──
    primary: "#69daff",
    "primary-container": "#00cffc",
    "primary-dim": "#00c0ea",
    "primary-fixed": "#00cffc",
    "primary-fixed-dim": "#00c0ea",
    "on-primary": "#004a5d",
    "on-primary-container": "#004050",
    "on-primary-fixed": "#002a35",
    "on-primary-fixed-variant": "#004a5c",
    "inverse-primary": "#006880",

    // ── Secondary (neutral) ──
    secondary: "#e1e2e7",
    "secondary-container": "#44474b",
    "secondary-dim": "#d3d4d9",
    "secondary-fixed": "#e1e2e7",
    "secondary-fixed-dim": "#d3d4d9",
    "on-secondary": "#4f5256",
    "on-secondary-container": "#cfd0d4",
    "on-secondary-fixed": "#3d4043",
    "on-secondary-fixed-variant": "#595c5f",

    // ── Tertiary (green/bullish) ──
    tertiary: "#c1ffd4",
    "tertiary-container": "#66fdac",
    "tertiary-dim": "#56ef9f",
    "tertiary-fixed": "#66fdac",
    "tertiary-fixed-dim": "#56ef9f",
    "on-tertiary": "#00683d",
    "on-tertiary-container": "#005e37",
    "on-tertiary-fixed": "#004a2a",
    "on-tertiary-fixed-variant": "#00693e",

    // ── Error (red/bearish) ──
    error: "#ff716c",
    "error-container": "#9f0519",
    "error-dim": "#d7383b",
    "on-error": "#490006",
    "on-error-container": "#ffa8a3",

    // ── On-surface / text ──
    "on-surface": "#e7ebf3",
    "on-surface-variant": "#a7abb3",
    "on-background": "#e7ebf3",

    // ── Outline ──
    outline: "#71767d",
    "outline-variant": "#43484f",

    // ── Inverse ──
    "inverse-surface": "#f7f9ff",
    "inverse-on-surface": "#50555c",

    // ── Legacy aliases (backward compat for existing components) ──
    long: "#56ef9f",
    short: "#ff716c",
    accent: "#00cffc",
    foreground: "#e7ebf3",
    muted: "#a7abb3",
    dim: "#71767d",
    card: "#141a21",
    "card-hover": "#1a2028",
    border: "#43484f",

    // ── Extended palette (indicators, tool icons, badges — unchanged) ──
    blue: "#3B82F6",
    purple: "#8B5CF6",
    pink: "#EC4899",
    orange: "#F97316",
    teal: "#14B8A6",
    indigo: "#6366F1",
    neutral: "#6B7280",
  },

  fontFamily: {
    sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
    headline: ["Space Grotesk", "system-ui", "sans-serif"],
    mono: ["JetBrains Mono", "Fira Code", "monospace"],
  },

  borderRadius: {
    DEFAULT: "0.125rem",
    lg: "0.25rem",
    xl: "0.5rem",
    pill: "0.75rem",
  },

  glass: {
    nav: "rgba(31, 38, 47, 0.60)",
    card: "rgba(20, 26, 33, 0.65)",
    dialog: "rgba(10, 15, 20, 0.9)",
    border: "rgba(67, 72, 79, 0.15)",
    backdrop: "rgba(0, 0, 0, 0.7)",
    blur: { nav: "24px", dialog: "20px", card: "12px" },
  },

  chart: {
    background: "#0a0f14",
    text: "#a7abb3",
    grid: "rgba(31, 38, 47, 0.3)",
    scaleBorder: "#43484f",
    candleUp: "#56ef9f",
    candleDown: "#ff716c",
    volumeUp: "rgba(86, 239, 159, 0.3)",
    volumeDown: "rgba(255, 113, 108, 0.3)",
    macdHistUp: "rgba(86, 239, 159, 0.6)",
    macdHistDown: "rgba(255, 113, 108, 0.6)",
  },

  indicators: {
    ema21: "#00cffc",
    ema50: "#69daff",
    ema200: "#A855F7",
    sma21: "#F59E0B",
    sma50: "#6366F1",
    sma200: "#EC4899",
    rsi: "#00cffc",
    macd: "#69daff",
    macdSignal: "#F97316",
    stochK: "#56ef9f",
    stochD: "#ff716c",
    bb: "#6B7280",
    vwap: "#F97316",
    ichTenkan: "#69daff",
    ichKijun: "#ff716c",
    ichSenkouA: "#56ef9f",
    ichSenkouB: "#ff716c",
    supertrend: "#56ef9f",
    psar: "#8B5CF6",
    pivots: "#14B8A6",
    cci: "#F97316",
    atr: "#EC4899",
    adx: "#8B5CF6",
    willr: "#14B8A6",
    mfi: "#ff716c",
    obv: "#6366F1",
    curveColors: ["#00cffc", "#56ef9f", "#ff716c", "#69daff"],
  },
} as const;
