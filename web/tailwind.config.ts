import type { Config } from "tailwindcss";
import { theme } from "./src/shared/theme";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: theme.colors,
      fontFamily: theme.fontFamily,
      borderRadius: theme.borderRadius,
      animation: {
        'slide-down': 'slideDown 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'fade-in': 'fadeIn 0.15s ease-in-out',
        'card-enter': 'cardEnter 0.35s cubic-bezier(0.16, 1, 0.3, 1) backwards',
        'pulse-glow': 'pulseGlow 2s ease-in-out 3',
      },
      keyframes: {
        slideDown: { '0%': { transform: 'translateY(-100%)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        slideUp: { '0%': { transform: 'translateY(20px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        cardEnter: { '0%': { transform: 'translateY(12px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        pulseGlow: { '0%, 100%': { boxShadow: '0 0 0 0 rgba(0, 207, 252, 0)' }, '50%': { boxShadow: '0 0 8px 2px rgba(0, 207, 252, 0.15)' } },
      },
    },
  },
  safelist: [
    "text-long", "text-short",
    "bg-long/5", "bg-short/5",
    "bg-long/10", "bg-short/10",
    "bg-long/15", "bg-short/15",
    "bg-long/20", "bg-short/20",
    "border-long/20", "border-short/20",
    "border-long/30", "border-short/30",
    "border-long/40", "border-short/40",
    "bg-accent/15", "bg-accent/20",
    "text-accent",
    "text-tertiary-dim", "text-error", "text-primary",
    "bg-tertiary-dim/10", "bg-tertiary-dim/20",
    "bg-error/10", "bg-error/20",
    "border-tertiary-dim/30", "border-error/30",
    "border-outline-variant/10", "border-outline-variant/15",
  ],
  plugins: [],
} satisfies Config;
