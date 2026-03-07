import type { Config } from "tailwindcss";
import { theme } from "./src/shared/theme";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: theme.colors,
      fontFamily: theme.fontFamily,
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
  ],
  plugins: [],
} satisfies Config;
