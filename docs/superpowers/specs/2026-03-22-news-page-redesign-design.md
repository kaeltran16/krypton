# News Page Redesign — Design Spec

## Overview

Holistic redesign of the news page: time-grouped feed, in-app article reader via bottom sheet, theme alignment with Arctic Terminal design system, and backend article extraction at ingest.

## Goals

1. **In-app reading** — extract article content at ingest, render in a slide-up reader sheet. Fall back to "Open original" link when extraction fails or is unavailable.
2. **Time grouping** — section the feed by Today / Yesterday / Earlier for faster scanning.
3. **Theme alignment** — update all news components to use M3 surface tokens, Space Grotesk headlines, uppercase tracking-widest labels, long/short semantic colors consistently.
4. **Fix stale tokens** — `NewsAlertToast` uses legacy tokens (`text-muted`, `text-dim`, `bg-card`, `border-accent`, `bg-accent`); migrate to M3.

## Non-Goals

- Real-time WebSocket news updates (future work)
- Sentiment or pair filters (backend supports them, but not adding to UI in this pass)
- Infinite scroll / pagination (keep current limit-based fetch)
- Pull-to-refresh gesture

---

## Backend Changes

### 1. New Column: `content_text`

Add a nullable `Text` column to `NewsEvent`:

```
content_text: Mapped[str | None] = mapped_column(Text)
```

Alembic migration adds the column with `ALTER TABLE news_events ADD COLUMN content_text TEXT`.

### 2. Article Extraction at Ingest

During news ingestion (wherever `NewsEvent` rows are created), after fetching the article URL:

- Use `trafilatura` to extract the main article text from the HTML.
- Store the extracted plain text in `content_text`. If extraction fails or returns empty, leave `content_text` as `NULL`.
- This is best-effort — extraction failure should not block the news event from being saved.

### 3. API Changes

Update `_news_to_dict` in `api/news.py` to include the new field:

```python
"content_text": n.content_text,
```

No new endpoints needed. The existing `/api/news` and `/api/news/recent` responses will include `content_text` (which may be `null`).

---

## Frontend Changes

### 1. Type Update

Add to `NewsEvent` in `features/news/types.ts`:

```typescript
content_text: string | null;
```

### 2. Time-Grouped Feed (`NewsFeed.tsx`)

Replace the flat list with grouped sections:

- Compute groups from `published_at`: **Today**, **Yesterday**, **Earlier**
- Render each group with a section header: `text-xs font-bold tracking-widest uppercase text-on-surface-variant` (matches HomeView section headers)
- Empty groups are not rendered
- If all groups are empty, show the existing empty state

### 3. Updated NewsCard (`NewsCard.tsx`)

Redesign to match SignalCard / HomeView patterns.

**Container semantics depend on the available action:**

| Condition | Element | Behavior |
|-----------|---------|----------|
| `content_text` exists | `<button>` | Opens reader sheet |
| No `content_text`, but `url` exists | `<a href={url} target="_blank" rel="noopener noreferrer">` | Opens in new tab |
| Neither | `<div>` (non-interactive) | No cursor-pointer, no press feedback |

Remove `aria-expanded` in all cases (inline expand is gone).

**Visual spec:**

- **Container**: `bg-surface-container-low rounded-lg p-4 border-l-4` (keep impact border color)
- **Header row**: impact badge + time/source + sentiment icon+label (right-aligned)
- **Headline**: `font-headline text-base font-bold leading-tight` (already correct)
- **Pair chips**: `bg-surface-container-highest px-2 py-1 rounded font-mono text-[10px] font-bold` (already correct)
- **Action hint** (new): bottom of card shows contextual hint:
  - If `content_text` exists: book icon + "Read article" in `text-xs text-primary/80`
  - If no `content_text` but `url` exists: external-link icon + "Open in browser" in `text-xs text-primary/80`
  - If neither: no hint shown
  - Note: use `text-xs` (12px) at `/80` opacity — not `text-[10px]` at `/60` — to meet WCAG AA 4.5:1 contrast against `bg-surface-container-low`.
- **Remove**: the inline expandable AI summary from the card (it moves to the reader sheet)

### 4. Reader Sheet (new component: `NewsReaderSheet.tsx`)

A bottom sheet that slides up when a news card with `content_text` is tapped.

**Implementation: use native `<dialog>` with the existing `.bottom-sheet` CSS class**, matching the `IndicatorSheet.tsx` pattern. This gives us free focus trapping, `Escape` to close, and backdrop-click-to-close via `showModal()`/`close()`. Do NOT build a custom sheet with manual backdrop/scroll-lock/focus-trap.

**Structure (inside the `<dialog>`):**

- **Dialog**: `<dialog ref={dialogRef} onClose={onClose} className="bottom-sheet" aria-label="Article reader">`
- **Backdrop click**: `onClick={(e) => { if (e.target === dialogRef.current) onClose(); }}` (same as IndicatorSheet)
- **Drag handle**: centered 40px wide bar, `bg-outline-variant`, top of sheet (visual affordance only)
- **Close button**: top-right `<button aria-label="Close article">` with `X` icon (same as IndicatorSheet)
- **Article header**:
  - Impact badge + sentiment badge (same as card)
  - Headline as `<h2 className="font-headline text-xl font-bold">`
  - Source + relative time + estimated read time in `text-on-surface-variant text-sm`
  - Read time: `Math.max(1, Math.ceil(content_text.split(/\s+/).length / 200))` min read (~200 WPM)
- **AI Summary box** (if `llm_summary` exists):
  - `bg-surface-container-lowest rounded-lg p-4 border border-outline-variant/10`
  - Zap icon + "Krypton AI Summary" label in `text-primary`
  - Summary text in `text-on-surface-variant text-sm leading-relaxed`
- **Article body**:
  - `content_text` rendered as paragraphs: split on `/\n{2,}/`, filter empty strings, wrap each in `<p>`
  - `text-on-surface text-[15px] leading-relaxed` (primary text color for long-form reading)
  - Wrap in `<article>` for semantics
  - Separated from header by `border-t border-outline-variant/15`
- **Footer bar**:
  - Affected pair chips (left)
  - "Open original" link button (right): `<a href={url} target="_blank" rel="noopener noreferrer">` styled as `bg-primary/10 border border-primary/20 rounded-lg text-primary text-xs`
  - Separated by `border-t border-outline-variant/15`

**Behavior:**
- Opens via state in `NewsView` (selected news event)
- Closes on: backdrop tap, `Escape` key, close button
- Sheet max-height: `85vh`, scrollable internally
- Focus returns to the triggering `NewsCard` on close
- Body scroll lock: add `document.body.style.overflow = 'hidden'` in a `useEffect` tied to open state, restore on cleanup. Native `<dialog>` backdrop does NOT prevent background scroll on iOS Safari.

**Accessibility:**
- `aria-label="Article reader"` on the `<dialog>`
- Headline is `<h2>`, AI summary heading can be `<h3>`
- Article body wrapped in `<article>`
- Close button has `aria-label="Close article"`
- Focus automatically moves into dialog on `showModal()` (native behavior)
- `Escape` key closes (native behavior)

### 5. NewsAlertToast Token Migration

Replace legacy tokens in `NewsAlertToast.tsx`:

| Old | New |
|-----|-----|
| `text-muted` | `text-on-surface-variant` |
| `text-dim` | `text-outline` |
| `bg-card` | `bg-surface-container` |
| `border-border` | `border-outline-variant` |
| `text-accent` | `text-primary` |
| `border-accent/40` | `border-primary/40` |
| `bg-accent/10` | `bg-primary/10` |

### 6. Remove NewsView Wrapper

`NewsView.tsx` is a pass-through (`return <NewsFeed />`). Either:
- Inline `NewsFeed` directly at the Layout call site, or
- Keep `NewsView` but have it own the reader sheet state and pass it down

Decision: keep `NewsView` as the orchestrator — it manages the reader sheet state and passes the selected event + close handler to both `NewsFeed` and `NewsReaderSheet`.

---

## Component Hierarchy

```
NewsView
  ├── NewsFeed
  │     ├── FilterBar (category segmented control + impact pills)
  │     ├── TimeGroup "Today"
  │     │     ├── NewsCard (<button> | <a> | <div> based on content)
  │     │     └── NewsCard
  │     ├── TimeGroup "Yesterday"
  │     │     └── NewsCard
  │     └── TimeGroup "Earlier"
  │           └── NewsCard
  └── NewsReaderSheet (<dialog>, conditional, when selectedEvent !== null)
```

---

## File Changes Summary

| File | Change |
|------|--------|
| `backend/app/db/models.py` | Add `content_text` column |
| `backend/alembic/versions/...` | Migration for new column |
| `backend/app/api/news.py` | Include `content_text` in response dict |
| `backend/app/collector/...` | Add `trafilatura` extraction at ingest |
| `web/src/features/news/types.ts` | Add `content_text` field |
| `web/src/features/news/components/NewsView.tsx` | Orchestrate reader sheet state |
| `web/src/features/news/components/NewsFeed.tsx` | Time grouping, pass onSelect |
| `web/src/features/news/components/NewsCard.tsx` | Redesign, conditional element type, action hint, remove inline expand |
| `web/src/features/news/components/NewsReaderSheet.tsx` | New — `<dialog>` bottom sheet reader |
| `web/src/features/news/components/NewsAlertToast.tsx` | Migrate all legacy tokens |
