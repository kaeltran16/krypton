export type NewsCategory = "crypto" | "macro";

export interface NewsEvent {
  id: number;
  headline: string;
  source: string;
  url: string;
  category: NewsCategory;
  affected_pairs: string[];
  content_text: string | null;
  published_at: string | null;
  created_at: string | null;
}

export interface NewsAlert {
  type: "news_alert";
  news: NewsEvent;
}
