import { useState } from "react";
import { useNews } from "../hooks/useNews";
import { NewsCard } from "./NewsCard";
import type { NewsCategory, NewsImpact } from "../types";

type CategoryFilter = "all" | NewsCategory;
type ImpactFilter = "all" | NewsImpact;

export function NewsFeed() {
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [impact, setImpact] = useState<ImpactFilter>("all");

  const { news, loading } = useNews({
    category: category === "all" ? undefined : category,
    impact: impact === "all" ? undefined : impact,
    limit: 100,
  });

  return (
    <div className="flex flex-col gap-2 p-3">
      {/* Category filter chips */}
      <div className="flex gap-2 overflow-x-auto no-scrollbar">
        {(["all", "crypto", "macro"] as CategoryFilter[]).map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap ${
              category === c
                ? "bg-accent/15 text-accent border border-accent/30"
                : "bg-card text-muted border border-border"
            }`}
          >
            {c === "all" ? "All" : c.charAt(0).toUpperCase() + c.slice(1)}
          </button>
        ))}
        <div className="w-px bg-border flex-shrink-0" />
        {(["all", "high", "medium", "low"] as ImpactFilter[]).map((i) => (
          <button
            key={i}
            onClick={() => setImpact(i)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap ${
              impact === i
                ? "bg-accent/15 text-accent border border-accent/30"
                : "bg-card text-muted border border-border"
            }`}
          >
            {i === "all" ? "All" : i.charAt(0).toUpperCase() + i.slice(1)}
          </button>
        ))}
      </div>

      {/* News list */}
      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 bg-card rounded-lg animate-pulse border border-border" />
          ))}
        </div>
      ) : news.length === 0 ? (
        <div className="bg-card rounded-lg p-8 border border-border text-center">
          <p className="text-muted text-sm">No news events yet</p>
          <p className="text-dim text-xs mt-1">Headlines will appear as they are collected</p>
        </div>
      ) : (
        <div className="space-y-2">
          {news.map((event) => (
            <NewsCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}
