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
    <div className="flex flex-col gap-4 p-4">
      {/* Category filter pills */}
      <div className="flex flex-wrap gap-3">
        <div className="bg-surface-container-low p-1 rounded-lg flex gap-1">
          {(["all", "crypto", "macro"] as CategoryFilter[]).map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`px-3 py-1.5 text-xs uppercase tracking-widest rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                category === c
                  ? "bg-surface-container-highest text-primary shadow-[0_0_8px_rgba(105,218,255,0.15)]"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {c === "all" ? "All" : c.charAt(0).toUpperCase() + c.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Impact level toggles */}
      <div className="flex items-center gap-3 overflow-x-auto pb-1 [mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]">
        <span className="text-[10px] uppercase tracking-widest text-on-surface-variant shrink-0">Impact:</span>
        {(["all", "high", "medium", "low"] as ImpactFilter[]).map((i) => {
          const dotColor = i === "high" ? "bg-short" : i === "medium" ? "bg-primary" : i === "low" ? "bg-on-surface-variant" : "";
          return (
            <button
              key={i}
              onClick={() => setImpact(i)}
              className={`flex items-center gap-2 px-3 py-1 rounded-full bg-surface-container border border-outline-variant/20 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                impact === i ? "border-primary/40" : "opacity-60"
              }`}
            >
              {dotColor && <div className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />}
              <span className="text-xs text-on-surface">
                {i === "all" ? "All" : i.charAt(0).toUpperCase() + i.slice(1)}
              </span>
            </button>
          );
        })}
      </div>

      {/* News list */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse" />
          ))}
        </div>
      ) : news.length === 0 ? (
        <div className="bg-surface-container rounded-lg p-8 text-center">
          <p className="text-on-surface-variant text-sm">No news events yet</p>
          <p className="text-outline text-xs mt-1">Headlines will appear as they are collected</p>
        </div>
      ) : (
        <div className="space-y-3">
          {news.map((event) => (
            <NewsCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}
