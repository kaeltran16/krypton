export type NewsCategory = "crypto" | "macro";
export type NewsImpact = "high" | "medium" | "low";
export type NewsSentiment = "bullish" | "bearish" | "neutral";

export interface NewsEvent {
  id: number;
  headline: string;
  source: string;
  url: string;
  category: NewsCategory;
  impact: NewsImpact | null;
  sentiment: NewsSentiment | null;
  affected_pairs: string[];
  llm_summary: string | null;
  published_at: string | null;
  created_at: string | null;
}

export interface NewsAlert {
  type: "news_alert";
  news: NewsEvent;
}
