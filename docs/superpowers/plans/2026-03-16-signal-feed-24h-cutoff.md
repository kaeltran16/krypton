# Signal Feed 24-Hour Cutoff Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter the signal feed to only show signals from the last 24 hours, removing stale clutter from the trading UI.

**Architecture:** Dual-layer filtering — backend `GET /signals` defaults to 24h window via a `since` query param, frontend applies a client-side 24h cutoff with a 60-second re-render timer to catch signals that age out during a session.

**Tech Stack:** FastAPI (Python), React 19, TypeScript, Zustand, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-16-signal-feed-24h-cutoff-design.md`

---

## Task 1: Backend — add `since` parameter to `GET /signals`

**Files:**
- Modify: `backend/app/api/routes.py:278-294`
- Test: `backend/tests/api/test_routes.py`

- [ ] **Step 1: Add `since` parameter to `get_signals`**

In `backend/app/api/routes.py`, modify the `get_signals` function (line 278). The `datetime`, `timedelta`, and `timezone` imports already exist at line 4.

Change the function signature and body from:

```python
    @router.get("/signals")
    async def get_signals(
        request: Request,
        _key: str = auth,
        pair: str | None = Query(None),
        timeframe: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
    ):
        db = request.app.state.db
        async with db.session_factory() as session:
            query = select(Signal).order_by(Signal.created_at.desc())
            if pair:
                query = query.where(Signal.pair == pair)
            if timeframe:
                query = query.where(Signal.timeframe == timeframe)
            query = query.limit(limit)
            result = await session.execute(query)
            return [_signal_to_dict(s) for s in result.scalars().all()]
```

To:

```python
    @router.get("/signals")
    async def get_signals(
        request: Request,
        _key: str = auth,
        pair: str | None = Query(None),
        timeframe: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        since: datetime | None = Query(None),
    ):
        db = request.app.state.db
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        async with db.session_factory() as session:
            query = select(Signal).order_by(Signal.created_at.desc())
            query = query.where(Signal.created_at >= since)
            if pair:
                query = query.where(Signal.pair == pair)
            if timeframe:
                query = query.where(Signal.timeframe == timeframe)
            query = query.limit(limit)
            result = await session.execute(query)
            return [_signal_to_dict(s) for s in result.scalars().all()]
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_routes.py -v`
Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/routes.py backend/tests/api/test_routes.py
git commit -m "feat: add since parameter to GET /signals with 24h default"
```

---

## Task 2: Frontend — add `since` to API client

**Files:**
- Modify: `web/src/shared/lib/api.ts:172-183`

- [ ] **Step 1: Add `since` to `getSignals` params**

In `web/src/shared/lib/api.ts`, change the `getSignals` method from:

```typescript
  getSignals: (params?: {
    pair?: string;
    timeframe?: string;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.pair) query.set("pair", params.pair);
    if (params?.timeframe) query.set("timeframe", params.timeframe);
    if (params?.limit) query.set("limit", String(params.limit));
    const qs = query.toString();
    return request<Signal[]>(`/api/signals${qs ? `?${qs}` : ""}`);
  },
```

To:

```typescript
  getSignals: (params?: {
    pair?: string;
    timeframe?: string;
    limit?: number;
    since?: string;
  }) => {
    const query = new URLSearchParams();
    if (params?.pair) query.set("pair", params.pair);
    if (params?.timeframe) query.set("timeframe", params.timeframe);
    if (params?.limit) query.set("limit", String(params.limit));
    if (params?.since) query.set("since", params.since);
    const qs = query.toString();
    return request<Signal[]>(`/api/signals${qs ? `?${qs}` : ""}`);
  },
```

- [ ] **Step 2: Commit**

```bash
git add web/src/shared/lib/api.ts
git commit -m "feat: add since parameter to getSignals API client"
```

---

## Task 3: Frontend — 24h cutoff filter in SignalFeed

**Files:**
- Modify: `web/src/features/signals/components/SignalFeed.tsx`

- [ ] **Step 1: Add 60-second re-render timer and 24h filter**

In `web/src/features/signals/components/SignalFeed.tsx`, add `useEffect` to the import:

```typescript
import { useEffect, useState } from "react";
```

Inside `SignalFeed()`, add the timer state and effect after the existing `useState` calls (after line 21):

```typescript
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);
```

Then replace the existing `filtered` logic (lines 23-28) with:

```typescript
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const recent = signals.filter((s) => new Date(s.created_at).getTime() > cutoff);

  const filtered =
    statusFilter === "ALL"
      ? recent
      : statusFilter === "ACTIVE"
        ? recent.filter((s) => !s.outcome || s.outcome === "PENDING")
        : recent.filter((s) => s.user_status === statusFilter);
```

- [ ] **Step 2: Update the empty state message**

Change the empty state text (line 53) from:

```typescript
          {statusFilter === "ALL" ? "Waiting for signals..." : `No ${statusFilter.toLowerCase()} signals`}
```

To:

```typescript
          {statusFilter === "ALL" ? "No signals in the last 24 hours" : `No ${statusFilter.toLowerCase()} signals`}
```

- [ ] **Step 3: Verify the dev server compiles**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/signals/components/SignalFeed.tsx
git commit -m "feat: filter signal feed to last 24 hours with periodic refresh"
```

---

## Task 4: Frontend — 24h cutoff in RecentSignals (Home tab)

**Files:**
- Modify: `web/src/features/home/components/RecentSignals.tsx`

- [ ] **Step 1: Add imports, 60s timer, and 24h cutoff**

In `web/src/features/home/components/RecentSignals.tsx`, add `useEffect` and `useState` imports:

```typescript
import { useEffect, useState } from "react";
```

Inside `RecentSignals()`, add a 60-second re-render timer (same pattern as SignalFeed) before the store selector:

```typescript
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);
```

Then change the store selector (line 7) from:

```typescript
  const signals = useSignalStore(useShallow((s) => s.signals.slice(0, 3)));
```

To:

```typescript
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const signals = useSignalStore(useShallow((s) =>
    s.signals.filter((sig) => new Date(sig.created_at).getTime() > cutoff).slice(0, 3)
  ));
```

- [ ] **Step 2: Update the empty state message**

Change the empty state text (line 18) from:

```typescript
        <p className="px-3 pb-3 text-sm text-dim">Waiting for signals...</p>
```

To:

```typescript
        <p className="px-3 pb-3 text-sm text-dim">No signals in the last 24 hours</p>
```

- [ ] **Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/home/components/RecentSignals.tsx
git commit -m "feat: apply 24h cutoff to home page recent signals"
```
