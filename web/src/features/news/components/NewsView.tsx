import { useState } from "react";
import { NewsFeed } from "./NewsFeed";
import { NewsReaderSheet } from "./NewsReaderSheet";
import type { NewsEvent } from "../types";

export function NewsView() {
  const [selectedEvent, setSelectedEvent] = useState<NewsEvent | null>(null);

  return (
    <>
      <NewsFeed onSelectEvent={setSelectedEvent} />
      <NewsReaderSheet event={selectedEvent} onClose={() => setSelectedEvent(null)} />
    </>
  );
}
