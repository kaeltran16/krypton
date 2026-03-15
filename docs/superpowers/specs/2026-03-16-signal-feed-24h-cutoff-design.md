# Signal Feed 24-Hour Cutoff

## Problem

The signal feed shows signals up to 5+ days old. Since the backend expires signals after 24 hours, anything older is fully resolved and no longer actionable. These stale signals clutter the feed.

## Solution

Filter signals to only show those created within the last 24 hours, both at the API level (reduce payload) and in the frontend (catch signals that age out during a session).

## Changes

### 1. Backend: `GET /signals` default `since` parameter

**File:** `backend/app/api/routes.py` — `get_signals` (line 278)

Add an optional `since` query parameter that defaults to 24 hours ago. Apply it as a `WHERE created_at >= since` filter on the query.

```python
from datetime import datetime, timedelta, timezone

async def get_signals(
    request: Request,
    _key: str = auth,
    pair: str | None = Query(None),
    timeframe: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    since: datetime | None = Query(None),
):
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
    # ... existing filters ...
    query = query.where(Signal.created_at >= since)
```

The journal, calendar, and stats endpoints are not affected — they have their own query logic.

### 2. Frontend: filter stale signals in `SignalFeed.tsx`

**File:** `web/src/features/signals/components/SignalFeed.tsx`

Before applying the status filter, filter out signals older than 24 hours:

```typescript
const cutoff = Date.now() - 24 * 60 * 60 * 1000;
const recent = signals.filter((s) => new Date(s.created_at).getTime() > cutoff);
```

Then apply the existing status filter on `recent` instead of `signals`.

Add a 60-second interval timer to force a re-render so that signals that age past 24h are dropped even if no new data arrives. Without this, stale signals would linger until the next render trigger.

Also apply the same 24h cutoff in the `RecentSignals` component on the Home tab, which reads `signals.slice(0, 3)` from the same store.

### 3. Frontend: API client — pass `since` parameter

**File:** `web/src/shared/lib/api.ts` — `getSignals`

Add optional `since` to the params type and pass it as a query parameter. The WebSocket hook can pass it on initial fetch, though the backend default already handles it.

## What stays the same

- Signal store (`store.ts`) — no changes, still holds up to 100 signals
- Journal tab, analytics, calendar — unaffected, query full history
- WebSocket real-time signals — unaffected, new signals are always <24h old
- Signal detail modal — unaffected

## Edge cases

- **Empty feed:** Update the empty state message to "No signals in the last 24 hours" when the 24h filter produces an empty result (vs the current "Waiting for signals..." which implies none were generated)
- **Timezone:** Backend uses UTC throughout; frontend compares against `Date.now()` which is UTC-based
- **WebSocket reconnection:** Re-fetches from API, which returns only 24h signals by default — works automatically
- **Signal outcome updates:** `updateSignal` patches in place without changing `created_at`, so the age filter still works correctly
