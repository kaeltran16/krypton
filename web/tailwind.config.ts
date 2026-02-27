import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#121212",
        card: "#1A1A1A",
        long: "#22C55E",
        short: "#EF4444",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  safelist: [
    "text-long", "text-short",
    "bg-long/5", "bg-short/5",
    "bg-long/10", "bg-short/10",
    "bg-long/20",
    "border-long/30", "border-short/30",
  ],
  plugins: [],
} satisfies Config;
