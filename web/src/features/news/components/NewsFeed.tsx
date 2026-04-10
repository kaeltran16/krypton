import { useState, useMemo } from "react";
import { useNews } from "../hooks/useNews";
import { NewsCard } from "./NewsCard";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import type { NewsCategory, NewsEvent } from "../types";
import { Skeleton } from "../../../shared/components/Skeleton";

type CategoryFilter = "all" | NewsCategory;

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

  const { news, loading } = useNews({
    category: category === "all" ? undefined : category,
    limit: 100,
  });

  const groups = useMemo(() => groupByTime(news), [news]);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap gap-3">
        <SegmentedControl options={CATEGORIES} value={category} onChange={setCategory} />
      </div>

      {loading ? (
        <div className="space-y-3">
          <Skeleton count={3} height="h-24" />
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
