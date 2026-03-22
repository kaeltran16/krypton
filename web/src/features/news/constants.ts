import type { NewsImpact, NewsSentiment } from "./types";

export const IMPACT_BADGE: Record<NewsImpact, string> = {
  high: "bg-error-container text-on-error",
  medium: "bg-surface-container-highest text-on-surface-variant",
  low: "bg-surface-container-highest text-on-surface-variant",
};

export const SENTIMENT_COLOR: Record<NewsSentiment, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};
