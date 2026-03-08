import { useState, useEffect, useCallback } from "react";
import { api } from "../../../shared/lib/api";
import type { NewsEvent } from "../types";

export function useNews(params?: {
  category?: string;
  impact?: string;
  limit?: number;
}) {
  const [news, setNews] = useState<NewsEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(() => {
    setLoading(true);
    api
      .getNews(params)
      .then(setNews)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [params?.category, params?.impact, params?.limit]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { news, loading, refresh: fetch };
}

export function useRecentNews(limit = 5) {
  const [news, setNews] = useState<NewsEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getRecentNews(limit)
      .then(setNews)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [limit]);

  return { news, loading };
}
