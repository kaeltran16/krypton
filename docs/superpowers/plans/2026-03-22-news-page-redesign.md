# News Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the news page with time-grouped feed, in-app article reader via bottom sheet, backend article extraction at ingest, and migrate legacy tokens.

**Architecture:** Backend adds a `content_text` column to `NewsEvent`, extracts article text via `trafilatura` at ingest, and exposes it through existing API endpoints. Frontend introduces time-grouped sections (Today/Yesterday/Earlier), a `<dialog>`-based reader sheet for in-app article reading, conditional card interactivity based on available content, and migrates `NewsAlertToast` from legacy tokens to M3.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, trafilatura, React 19, TypeScript, Tailwind CSS v3, lucide-react

---

### Task 1: Add `trafilatura` dependency

**Files:**
- Modify: `backend/requirements.txt:22` (add before scipy line)

- [ ] **Step 1: Add trafilatura to requirements.txt**

Add `trafilatura` to `backend/requirements.txt` after `feedparser`:

```
feedparser==6.0.11
trafilatura>=2.0
```

- [ ] **Step 2: Rebuild the Docker container**

Run:
```bash
docker compose build api
docker compose up -d
```

- [ ] **Step 3: Verify trafilatura is importable**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python3 -c "import trafilatura; print(trafilatura.__version__)"
```
Expected: prints a version number without errors.

---

### Task 2: Add `content_text` column to `NewsEvent` model + migration

**Files:**
- Modify: `backend/app/db/models.py:140` (add column after `llm_summary`)
- Modify: `backend/tests/test_db_models.py` (add tests for new column)
- Create: `backend/app/db/migrations/versions/xxxx_add_content_text_to_news_events.py`

- [ ] **Step 1: Write the failing test**

Append to the existing `backend/tests/test_db_models.py`:

```python
def test_news_event_has_content_text_column():
    """Verify the content_text column exists on NewsEvent."""
    from app.db.models import NewsEvent
    columns = {c.name for c in NewsEvent.__table__.columns}
    assert "content_text" in columns


def test_news_event_content_text_is_nullable():
    """Verify content_text is nullable (optional)."""
    from app.db.models import NewsEvent
    col = NewsEvent.__table__.columns["content_text"]
    assert col.nullable is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/test_db_models.py::test_news_event_has_content_text_column -v
```
Expected: FAIL — `content_text` not found in columns.

- [ ] **Step 3: Add `content_text` column to the model**

In `backend/app/db/models.py`, after line 139 (`llm_summary`), add:

```python
content_text: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/test_db_models.py::test_news_event_has_content_text_column tests/test_db_models.py::test_news_event_content_text_is_nullable -v
```
Expected: PASS

- [ ] **Step 5: Generate Alembic migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add content_text to news_events"
```

Verify the generated migration contains `op.add_column('news_events', sa.Column('content_text', sa.Text(), nullable=True))` in `upgrade()` and `op.drop_column('news_events', 'content_text')` in `downgrade()`.

- [ ] **Step 6: Apply migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```
Expected: Migration applied successfully.

---

### Task 3: Add article extraction to news collector

**Files:**
- Modify: `backend/app/collector/news.py:288-302` (add extraction in persist loop)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/collector/test_news_extraction.py`:

```python
"""Test article text extraction at news ingest."""
from unittest.mock import patch, MagicMock

from app.collector.news import extract_article_text


def test_extract_article_text_returns_content():
    """Successful extraction returns article text."""
    html = "<html><body><article><p>Bitcoin surged to new highs today.</p></article></body></html>"
    with patch("app.collector.news.trafilatura.extract", return_value="Bitcoin surged to new highs today."):
        result = extract_article_text(html)
    assert result == "Bitcoin surged to new highs today."


def test_extract_article_text_returns_none_on_failure():
    """Failed extraction returns None."""
    with patch("app.collector.news.trafilatura.extract", return_value=None):
        result = extract_article_text("<html></html>")
    assert result is None


def test_extract_article_text_returns_none_on_empty():
    """Empty string extraction returns None."""
    with patch("app.collector.news.trafilatura.extract", return_value=""):
        result = extract_article_text("<html></html>")
    assert result is None


def test_extract_article_text_returns_none_on_exception():
    """Exception during extraction returns None."""
    with patch("app.collector.news.trafilatura.extract", side_effect=Exception("parse error")):
        result = extract_article_text("<html></html>")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/collector/test_news_extraction.py -v
```
Expected: FAIL — `extract_article_text` not defined.

- [ ] **Step 3: Implement `extract_article_text` and integrate into collector**

In `backend/app/collector/news.py`:

1. Add import at the top (after existing imports):
```python
import trafilatura
```

2. Add the extraction function (after `fingerprint_headline`):
```python
def extract_article_text(html: str) -> str | None:
    """Extract main article text from HTML using trafilatura. Returns None on failure."""
    try:
        text = trafilatura.extract(html)
        return text if text else None
    except Exception:
        return None
```

3. In the `_poll_cycle` persist loop (around line 290), after `pg_insert(NewsEvent).values(...)`, add `content_text` to the values dict. Before the persist loop, fetch article content for each headline. Modify the persist section as follows:

In the persist loop (line 288-319), before the `for h in scored:` loop, add concurrent fetching logic:

```python
# Fetch article content concurrently for extraction
async def _fetch_article(client: httpx.AsyncClient, h: dict, sem: asyncio.Semaphore):
    if not h.get("url"):
        h["content_text"] = None
        return
    async with sem:
        try:
            resp = await client.get(h["url"], follow_redirects=True)
            resp.raise_for_status()
            h["content_text"] = extract_article_text(resp.text)
        except Exception as e:
            logger.debug(f"Article fetch failed for {h.get('url', '?')}: {e}")
            h["content_text"] = None

sem = asyncio.Semaphore(5)
async with httpx.AsyncClient(timeout=10) as client:
    await asyncio.gather(*[_fetch_article(client, h, sem) for h in scored])
```

Then in the `pg_insert(NewsEvent).values(...)` call (line 291), add:
```python
content_text=h.get("content_text"),
```

after the `llm_summary` line.

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/collector/test_news_extraction.py -v
```
Expected: PASS

- [ ] **Step 5: Run existing news collector tests to ensure no regressions**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/collector/test_news_dedup.py tests/collector/test_news_processing.py -v
```
Expected: All existing tests PASS.

---

### Task 4: Include `content_text` in API response

**Files:**
- Modify: `backend/app/api/news.py:14-27` (add field to `_news_to_dict`)
- Modify: `backend/tests/api/test_news_endpoints.py` (update `_make_news_event` + add test)

- [ ] **Step 1: Write the failing test**

In `backend/tests/api/test_news_endpoints.py`, add after the existing tests:

```python
@pytest.mark.asyncio
async def test_get_news_includes_content_text():
    """API response includes content_text field."""
    news = [_make_news_event(id=1, content_text="Full article text here.")]
    app = FastAPI()
    app.state.settings = MagicMock(jwt_secret="test-jwt-secret")
    app.state.db = _mock_db(scalars_all=news)
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news", cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["content_text"] == "Full article text here."


@pytest.mark.asyncio
async def test_get_news_content_text_null_when_absent():
    """API response returns null content_text when not set."""
    news = [_make_news_event(id=1, content_text=None)]
    app = FastAPI()
    app.state.settings = MagicMock(jwt_secret="test-jwt-secret")
    app.state.db = _mock_db(scalars_all=news)
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news", cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["content_text"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_news_endpoints.py::test_get_news_includes_content_text tests/api/test_news_endpoints.py::test_get_news_content_text_null_when_absent -v
```
Expected: FAIL — `content_text` key not in response dict.

- [ ] **Step 3: Add `content_text` to `_news_to_dict`**

In `backend/app/api/news.py`, in `_news_to_dict` function (line 14-27), add after the `llm_summary` line:

```python
"content_text": n.content_text,
```

- [ ] **Step 4: Run all news endpoint tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_news_endpoints.py -v
```
Expected: ALL PASS (including the two new tests).

---

### Task 5: Add `content_text` to frontend `NewsEvent` type

**Files:**
- Modify: `web/src/features/news/types.ts:14` (add field after `llm_summary`)

- [ ] **Step 1: Add `content_text` field to the type**

In `web/src/features/news/types.ts`, after line 14 (`llm_summary`), add:

```typescript
content_text: string | null;
```

- [ ] **Step 2: Verify build passes**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds. Any type errors in consuming components will be addressed in subsequent tasks — this field is additive and all existing code reads from the `NewsEvent` type without destructuring all fields.

---

### Task 6: Build time-grouped `NewsFeed`

**Files:**
- Modify: `web/src/features/news/components/NewsFeed.tsx`

- [ ] **Step 1: Implement time grouping logic and update `NewsFeed`**

Replace `web/src/features/news/components/NewsFeed.tsx` with:

```tsx
import { useState } from "react";
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

  const groups = groupByTime(news);

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Category filter pills */}
      <div className="flex flex-wrap gap-3">
        <SegmentedControl options={CATEGORIES} value={category} onChange={setCategory} />
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
```

Key changes:
- Added `groupByTime()` utility that splits events into Today/Yesterday/Earlier
- Added `onSelectEvent` prop for reader sheet integration
- Renders section headers with `text-xs font-bold tracking-widest uppercase text-on-surface-variant`
- Empty groups are filtered out; if all empty, shows the existing empty state
- Passes `onSelect` to `NewsCard`

- [ ] **Step 2: Verify build passes**

Run:
```bash
cd web && pnpm build
```
Expected: Build may show type errors in `NewsCard` for the new `onSelect` prop — that's expected and will be fixed in Task 7.

---

### Task 7: Redesign `NewsCard` with conditional interactivity

**Files:**
- Modify: `web/src/features/news/components/NewsCard.tsx`

- [ ] **Step 1: Rewrite `NewsCard` with conditional element and action hint**

Replace `web/src/features/news/components/NewsCard.tsx` with:

```tsx
import { TrendingUp, TrendingDown, Minus, BookOpen, ExternalLink } from "lucide-react";
import type { NewsEvent } from "../types";
import { formatRelativeTime, formatPair } from "../../../shared/lib/format";

interface NewsCardProps {
  event: NewsEvent;
  onSelect?: (event: NewsEvent) => void;
}

const IMPACT_BORDER: Record<string, string> = {
  high: "border-l-error",
  medium: "border-l-primary/40",
  low: "border-l-on-surface-variant/20",
};

const IMPACT_BADGE: Record<string, string> = {
  high: "bg-error-container text-on-error",
  medium: "bg-surface-container-highest text-on-surface-variant",
  low: "bg-surface-container-highest text-on-surface-variant",
};

const SENTIMENT_ICON: Record<string, typeof TrendingUp> = {
  bullish: TrendingUp,
  bearish: TrendingDown,
  neutral: Minus,
};

const SENTIMENT_COLOR: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

const CARD_BASE = "w-full bg-surface-container-low rounded-lg p-4 border-l-4 text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary";

function CardContent({ event }: { event: NewsEvent }) {
  const SentimentIcon = event.sentiment ? SENTIMENT_ICON[event.sentiment] : null;

  return (
    <>
      {/* Header: impact badge + time + sentiment */}
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-3">
          {event.impact && (
            <span className={`text-[10px] tracking-widest px-2 py-0.5 uppercase rounded font-medium ${IMPACT_BADGE[event.impact] ?? ""}`}>
              {event.impact} Impact
            </span>
          )}
          <span className="text-xs text-on-surface-variant tabular">
            {event.published_at ? formatRelativeTime(event.published_at) : ""} {event.source ? `\u00B7 ${event.source}` : ""}
          </span>
        </div>
        {SentimentIcon && (
          <div className={`flex items-center gap-1 ${SENTIMENT_COLOR[event.sentiment!] ?? ""}`}>
            <SentimentIcon size={14} />
            <span className="text-[10px] uppercase tracking-widest">{event.sentiment}</span>
          </div>
        )}
      </div>

      {/* Headline */}
      <h3 className="font-headline text-base font-bold leading-tight mb-3">{event.headline}</h3>

      {/* Affected pairs */}
      {event.affected_pairs.length > 0 && event.affected_pairs[0] !== "ALL" && (
        <div className="flex flex-wrap gap-2 mb-2">
          {event.affected_pairs.map((pair) => (
            <div key={pair} className="bg-surface-container-highest px-2 py-1 rounded flex items-center gap-2">
              <span className="text-[10px] font-mono font-bold text-on-surface">{formatPair(pair)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Action hint */}
      {event.content_text ? (
        <div className="flex items-center gap-1.5 text-xs text-primary/80 mt-1">
          <BookOpen size={14} />
          Read article
        </div>
      ) : event.url ? (
        <div className="flex items-center gap-1.5 text-xs text-primary/80 mt-1">
          <ExternalLink size={14} />
          Open in browser
        </div>
      ) : null}
    </>
  );
}

export function NewsCard({ event, onSelect }: NewsCardProps) {
  const borderClass = IMPACT_BORDER[event.impact ?? "low"] ?? "border-l-outline-variant/20";

  // Has extractable content → button that opens reader sheet
  if (event.content_text) {
    return (
      <button
        onClick={() => onSelect?.(event)}
        className={`${CARD_BASE} hover:bg-surface-container cursor-pointer ${borderClass}`}
      >
        <CardContent event={event} />
      </button>
    );
  }

  // Has URL but no content → external link
  if (event.url) {
    return (
      <a
        href={event.url}
        target="_blank"
        rel="noopener noreferrer"
        className={`${CARD_BASE} hover:bg-surface-container block cursor-pointer ${borderClass}`}
      >
        <CardContent event={event} />
      </a>
    );
  }

  // Neither → non-interactive div
  return (
    <div className={`${CARD_BASE} ${borderClass}`}>
      <CardContent event={event} />
    </div>
  );
}
```

Key changes:
- Removed `expanded` state and inline AI summary (moves to reader sheet)
- Removed `aria-expanded`, `ChevronDown`, `Zap` imports
- Added `BookOpen`, `ExternalLink` icons
- Conditional wrapper: `<button>` (has content_text) / `<a>` (has url) / `<div>` (neither)
- Added action hint at bottom of card
- Added `onSelect` prop for reader sheet integration
- Extracted `CardContent` to avoid duplicating the card interior across three wrapper types

- [ ] **Step 2: Verify build passes**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds.

---

### Task 8: Build `NewsReaderSheet` component

**Files:**
- Create: `web/src/features/news/components/NewsReaderSheet.tsx`

- [ ] **Step 1: Create the reader sheet component**

Create `web/src/features/news/components/NewsReaderSheet.tsx`:

```tsx
import { useEffect, useRef } from "react";
import { X, Zap, ExternalLink } from "lucide-react";
import type { NewsEvent } from "../types";
import { formatRelativeTime, formatPair } from "../../../shared/lib/format";

interface NewsReaderSheetProps {
  event: NewsEvent | null;
  onClose: () => void;
}

const IMPACT_BADGE: Record<string, string> = {
  high: "bg-error-container text-on-error",
  medium: "bg-surface-container-highest text-on-surface-variant",
  low: "bg-surface-container-highest text-on-surface-variant",
};

const SENTIMENT_COLOR: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

function estimateReadTime(text: string): number {
  return Math.max(1, Math.ceil(text.split(/\s+/).length / 200));
}

export function NewsReaderSheet({ event, onClose }: NewsReaderSheetProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const open = event !== null && event.content_text !== null;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      dialog.showModal();
      document.body.style.overflow = "hidden";
    } else {
      dialog.close();
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
      className="bottom-sheet"
      style={{ maxHeight: "85dvh" }}
      aria-label="Article reader"
    >
      {event && event.content_text && (
        <div className="overflow-y-auto max-h-[85dvh]">
          {/* Drag handle */}
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 rounded-full bg-outline-variant" />
          </div>

          <div className="p-4">
            {/* Close button */}
            <div className="flex justify-end mb-2">
              <button
                onClick={onClose}
                aria-label="Close article"
                className="text-on-surface-variant p-2 hover:text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-lg"
              >
                <X size={20} />
              </button>
            </div>

            {/* Article header */}
            <div className="mb-4">
              <div className="flex items-center gap-2 mb-3">
                {event.impact && (
                  <span className={`text-[10px] tracking-widest px-2 py-0.5 uppercase rounded font-medium ${IMPACT_BADGE[event.impact] ?? ""}`}>
                    {event.impact}
                  </span>
                )}
                {event.sentiment && (
                  <span className={`text-[10px] uppercase tracking-widest font-medium ${SENTIMENT_COLOR[event.sentiment] ?? ""}`}>
                    {event.sentiment}
                  </span>
                )}
              </div>
              <h2 className="font-headline text-xl font-bold mb-2">{event.headline}</h2>
              <p className="text-on-surface-variant text-sm">
                {event.source}
                {event.published_at && ` · ${formatRelativeTime(event.published_at)}`}
                {` · ${estimateReadTime(event.content_text)} min read`}
              </p>
            </div>

            {/* AI Summary */}
            {event.llm_summary && (
              <div className="bg-surface-container-lowest rounded-lg p-4 border border-outline-variant/10 mb-4">
                <div className="flex items-center gap-2 mb-2">
                  <Zap size={14} className="text-primary" />
                  <h3 className="text-[10px] uppercase tracking-widest text-primary">Krypton AI Summary</h3>
                </div>
                <p className="text-sm text-on-surface-variant leading-relaxed">{event.llm_summary}</p>
              </div>
            )}

            {/* Article body */}
            <div className="border-t border-outline-variant/15 pt-4">
              <article>
                {event.content_text.split(/\n{2,}/).filter(Boolean).map((para, i) => (
                  <p key={i} className="text-on-surface text-[15px] leading-relaxed mb-4">
                    {para}
                  </p>
                ))}
              </article>
            </div>

            {/* Footer */}
            <div className="border-t border-outline-variant/15 pt-4 flex items-center justify-between">
              <div className="flex flex-wrap gap-2">
                {event.affected_pairs
                  .filter((p) => p !== "ALL")
                  .map((pair) => (
                    <div key={pair} className="bg-surface-container-highest px-2 py-1 rounded">
                      <span className="text-[10px] font-mono font-bold text-on-surface">{formatPair(pair)}</span>
                    </div>
                  ))}
              </div>
              {event.url && (
                <a
                  href={event.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 bg-primary/10 border border-primary/20 rounded-lg px-3 py-2 text-primary text-xs shrink-0"
                >
                  <ExternalLink size={12} />
                  Open original
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </dialog>
  );
}
```

Key implementation details:
- The `<dialog>` element is **always rendered** (never behind an early `return null`) so `dialogRef.current` is always available for `showModal()`/`close()` — content inside is conditionally rendered based on `event`
- Uses native `<dialog>` with `.bottom-sheet` CSS class (matching `IndicatorSheet.tsx` pattern)
- `showModal()`/`close()` for focus trapping and escape-to-close; native `<dialog>` restores focus to the triggering element on close
- Backdrop click closes via `onClick` handler comparing `e.target` to `dialogRef.current`
- Body scroll lock via `document.body.style.overflow = 'hidden'` (iOS Safari workaround)
- `max-height: 85dvh` (uses `dvh` to match the existing `.bottom-sheet` CSS convention, overrides default `70dvh`)
- Read time estimated at ~200 WPM
- Paragraphs split on `\n{2,}` and filtered for empty strings
- AI summary moved here from the card's inline expand

- [ ] **Step 2: Verify build passes**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds.

---

### Task 9: Wire up `NewsView` as orchestrator

**Files:**
- Modify: `web/src/features/news/components/NewsView.tsx`

- [ ] **Step 1: Update `NewsView` to manage reader sheet state**

Replace `web/src/features/news/components/NewsView.tsx` with:

```tsx
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
```

- [ ] **Step 2: Verify build passes**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds.

---

### Task 10: Migrate `NewsAlertToast` legacy tokens

**Files:**
- Modify: `web/src/features/news/components/NewsAlertToast.tsx`

- [ ] **Step 1: Replace all legacy tokens**

Replace `web/src/features/news/components/NewsAlertToast.tsx` with:

```tsx
import { useEffect, useState } from "react";
import { useNewsStore } from "../store";

const IMPACT_STYLES: Record<string, string> = {
  high: "border-short/40 bg-short/10",
  medium: "border-primary/40 bg-primary/10",
  low: "border-outline-variant bg-surface-container",
};

const SENTIMENT_STYLES: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

export function NewsAlertToast() {
  const alert = useNewsStore((s) => s.currentAlert);
  const dismiss = useNewsStore((s) => s.dismissAlert);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!alert) return;
    setExpanded(false);
    const timer = setTimeout(dismiss, 8000);
    return () => clearTimeout(timer);
  }, [alert, dismiss]);

  if (!alert) return null;

  const borderStyle = IMPACT_STYLES[alert.impact ?? "low"] ?? IMPACT_STYLES.low;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 p-3 animate-slide-down">
      <div
        className={`rounded-lg border p-3 shadow-lg backdrop-blur-md ${borderStyle}`}
        onClick={() => setExpanded(!expanded)}
        onTouchEnd={(e) => {
          if (expanded) {
            e.preventDefault();
            dismiss();
          }
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              {alert.impact && (
                <span className={`text-[10px] font-bold uppercase ${
                  alert.impact === "high" ? "text-short" : "text-primary"
                }`}>
                  {alert.impact}
                </span>
              )}
              {alert.sentiment && (
                <span className={`text-[10px] font-medium ${SENTIMENT_STYLES[alert.sentiment] ?? ""}`}>
                  {alert.sentiment}
                </span>
              )}
              <span className="text-[10px] text-outline">{alert.source}</span>
            </div>
            <p className="text-sm font-medium leading-snug">{alert.headline}</p>
            {expanded && alert.llm_summary && (
              <p className="mt-1.5 text-xs text-on-surface-variant leading-relaxed">
                {alert.llm_summary}
              </p>
            )}
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              dismiss();
            }}
            className="text-outline text-xs p-1"
          >
            &times;
          </button>
        </div>
      </div>
    </div>
  );
}
```

Token migration applied:
| Old | New |
|-----|-----|
| `text-muted` (line 64) | `text-on-surface-variant` |
| `text-dim` (lines 60, 74) | `text-outline` |
| `bg-card` (IMPACT_STYLES low) | `bg-surface-container` |
| `border-border` (IMPACT_STYLES low) | `border-outline-variant` |
| `text-accent` (line 50) | `text-primary` |
| `border-accent/40` (IMPACT_STYLES medium) | `border-primary/40` |
| `bg-accent/10` (IMPACT_STYLES medium) | `bg-primary/10` |

- [ ] **Step 2: Verify build passes**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds with no references to legacy tokens.

- [ ] **Step 3: Verify no legacy tokens remain in news feature**

Run a search to confirm no remaining legacy token usage:
```bash
cd web && grep -rn "text-muted\|text-dim\|bg-card\|border-border\|text-accent\|border-accent\|bg-accent" src/features/news/
```
Expected: No matches.

---

### Task 11: Final verification

- [ ] **Step 1: Run all backend tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v
```
Expected: ALL PASS

- [ ] **Step 2: Run frontend build**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds with no errors.

- [ ] **Step 3: Run frontend lint**

Run:
```bash
cd web && pnpm lint
```
Expected: No lint errors.

- [ ] **Step 4: Manual smoke test**

Start the dev server with `cd web && pnpm dev` and verify:
1. News page shows time-grouped sections (Today/Yesterday/Earlier headers)
2. Cards with article content show "Read article" hint and open the reader sheet on tap
3. Cards without content but with URL show "Open in browser" hint and link out
4. Reader sheet slides up from bottom, shows header/AI summary/article body/footer
5. Reader sheet closes on backdrop tap, Escape key, and close button
6. NewsAlertToast renders with correct M3 tokens (no visual regressions in toast colors)

- [ ] **Step 5: Commit all changes**

```bash
git add -A
git commit -m "feat(news): news page redesign — time-grouped feed, in-app reader sheet, article extraction, M3 token migration"
```
