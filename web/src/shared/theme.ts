// ─── Design Tokens ─────────────────────────────────────────────
// "Arctic Terminal" — A's indigo identity + C's refined surfaces & structure.
// Single source of truth. Tailwind config consumes colors + fontFamily + borderRadius.
// Chart components import chart + indicators.

export const theme = {
  colors: {
    // ── M3 Surface Hierarchy (C's wider steps, cool blue-gray) ──
    surface: "#080c12",
    "surface-dim": "#060910",
    "surface-container-lowest": "#030508",
    "surface-container-low": "#0d1219",
    "surface-container": "#111820",
    "surface-container-high": "#1c2430",
    "surface-container-highest": "#243040",
    "surface-bright": "#283340",
    "surface-variant": "#1c2430",
    "surface-tint": "#8B9AFF",
    background: "#080c12",

    // ── Primary (A's indigo-blue) ──
    primary: "#8B9AFF",
    "primary-container": "#6775E0",
    "primary-dim": "#5A68D0",
    "primary-fixed": "#8B9AFF",
    "primary-fixed-dim": "#6775E0",
    "on-primary": "#1a1f45",
    "on-primary-container": "#c8cfff",
    "on-primary-fixed": "#0f1330",
    "on-primary-fixed-variant": "#2a3060",
    "inverse-primary": "#3D4AA0",

    // ── Secondary (C's cool neutral) ──
    secondary: "#DEE2EA",
    "secondary-container": "#404750",
    "secondary-dim": "#CDD1D9",
    "secondary-fixed": "#DEE2EA",
    "secondary-fixed-dim": "#CDD1D9",
    "on-secondary": "#4C5058",
    "on-secondary-container": "#C8CCD4",
    "on-secondary-fixed": "#3A3E46",
    "on-secondary-fixed-variant": "#565A62",

    // ── Tertiary (C's richer emerald / bullish) ──
    tertiary: "#A0F0C5",
    "tertiary-container": "#2DD4A0",
    "tertiary-dim": "#26C090",
    "tertiary-fixed": "#2DD4A0",
    "tertiary-fixed-dim": "#26C090",
    "on-tertiary": "#005E37",
    "on-tertiary-container": "#004D2D",
    "on-tertiary-fixed": "#004025",
    "on-tertiary-fixed-variant": "#006B3E",

    // ── Error (A's rose / bearish) ──
    error: "#FB7185",
    "error-container": "#9F1239",
    "error-dim": "#E11D48",
    "on-error": "#4C0519",
    "on-error-container": "#FFB3C1",

    // ── On-surface / text (C's blue-gray) ──
    "on-surface": "#E5EBF5",
    "on-surface-variant": "#8E9AAD",
    "on-background": "#E5EBF5",

    // ── Outline (C's) ──
    outline: "#5E6A7D",
    "outline-variant": "#344050",

    // ── Inverse ──
    "inverse-surface": "#EDF0F8",
    "inverse-on-surface": "#484E5A",

    // ── Legacy aliases ──
    long: "#2DD4A0",
    short: "#FB7185",
    accent: "#0EB5E5",
    foreground: "#E5EBF5",
    muted: "#8E9AAD",
    dim: "#5E6A7D",
    card: "#111820",
    "card-hover": "#1c2430",
    border: "#344050",

    // ── Extended palette (indigo-anchored, harmonized) ──
    blue: "#4DA3E8",
    purple: "#A78BFA",
    pink: "#E06090",
    orange: "#E89040",
    teal: "#20BCA8",
    indigo: "#818CF8",
    neutral: "#687080",
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
    nav: "rgba(28, 36, 48, 0.65)",
    card: "rgba(17, 24, 32, 0.65)",
    dialog: "rgba(8, 12, 18, 0.9)",
    border: "rgba(52, 64, 80, 0.30)",
    backdrop: "rgba(0, 0, 0, 0.7)",
    blur: { nav: "24px", dialog: "20px", card: "12px" },
  },

  chart: {
    background: "#080c12",
    text: "#8E9AAD",
    grid: "rgba(28, 36, 48, 0.3)",
    scaleBorder: "#344050",
    candleUp: "#2DD4A0",
    candleDown: "#FB7185",
    volumeUp: "rgba(45, 212, 160, 0.3)",
    volumeDown: "rgba(251, 113, 133, 0.3)",
    macdHistUp: "rgba(45, 212, 160, 0.6)",
    macdHistDown: "rgba(251, 113, 133, 0.6)",
  },

  indicators: {
    ema21: "#0EB5E5",
    ema50: "#8B9AFF",
    ema200: "#A78BFA",
    sma21: "#E89040",
    sma50: "#818CF8",
    sma200: "#E06090",
    rsi: "#8B9AFF",
    macd: "#0EB5E5",
    macdSignal: "#E89040",
    stochK: "#2DD4A0",
    stochD: "#FB7185",
    bb: "#687080",
    vwap: "#E89040",
    ichTenkan: "#8B9AFF",
    ichKijun: "#FB7185",
    ichSenkouA: "#2DD4A0",
    ichSenkouB: "#FB7185",
    supertrend: "#2DD4A0",
    psar: "#A78BFA",
    pivots: "#20BCA8",
    cci: "#E89040",
    atr: "#E06090",
    adx: "#A78BFA",
    willr: "#20BCA8",
    mfi: "#FB7185",
    obv: "#818CF8",
    curveColors: ["#0EB5E5", "#2DD4A0", "#FB7185", "#8B9AFF"],
  },
} as const;
