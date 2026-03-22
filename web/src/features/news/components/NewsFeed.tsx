import { useState, useMemo } from "react";
import { useNews } from "../hooks/useNews";
import { NewsCard } from "./NewsCard";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import type { NewsCategory, NewsEvent, NewsImpact } from "../types";

type CategoryFilter = "all" | NewsCategory;
type ImpactFilter = "all" | NewsImpact;

const CATEGORIES: { value: CategoryFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "crypto", label: "Crypto" },
  { value: "macro", label: "Macro" },
];

interface TimeGroup {
  label: string;
  events: NewsEvent[];
}

function groupByTime(events: NewsEvent[]): TimeGroup[] {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86400000);

  const today: NewsEvent[] = [];
  const yesterday: NewsEvent[] = [];
  const earlier: NewsEvent[] = [];

  for (const event of events) {
    const pubTime = event.published_at ? new Date(event.published_at).getTime() : 0;
    if (pubTime >= todayStart.getTime()) {
      today.push(event);
    } else if (pubTime >= yesterdayStart.getTime()) {
      yesterday.push(event);
    } else {
      earlier.push(event);
    }
  }

  return [
    { label: "Today", events: today },
    { label: "Yesterday", events: yesterday },
    { label: "Earlier", events: earlier },
  ].filter((g) => g.events.length > 0);
}

interface NewsFeedProps {
  onSelectEvent?: (event: NewsEvent) => void;
}

export function NewsFeed({ onSelectEvent }: NewsFeedProps) {
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [impact, setImpact] = useState<ImpactFilter>("all");

  const { news, loading } = useNews({
    category: category === "all" ? undefined : category,
    impact: impact === "all" ? undefined : impact,
    limit: 100,
  });

  const groups = useMemo(() => groupByTime(news), [news]);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap gap-3">
        <SegmentedControl options={CATEGORIES} value={category} onChange={setCategory} />
      </div>

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

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <div className="bg-surface-container rounded-lg p-8 text-center">
          <p className="text-on-surface-variant text-sm">No news events yet</p>
          <p className="text-outline text-xs mt-1">Headlines will appear as they are collected</p>
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map((group) => (
            <div key={group.label}>
              <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant mb-3">
                {group.label}
              </h2>
              <div className="space-y-3">
                {group.events.map((event) => (
                  <NewsCard key={event.id} event={event} onSelect={onSelectEvent} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
