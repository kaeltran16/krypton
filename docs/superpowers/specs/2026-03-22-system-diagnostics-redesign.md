# System Diagnostics Redesign

## Problem

The current System Diagnostics page displays entirely hardcoded data. Database shows "ACTIVE", Cache shows "WARM", ML Pipeline shows "READY" — none of these reflect actual system state. Data Freshness bars use fixed percentages. The only live element is WebSocket connectivity status.

## Goals

- Wire up real health checks, pipeline metrics, and resource usage from the backend
- Redesign the frontend with a summary + drill-down layout suitable for mobile
- Auto-fetch on page load with manual refresh — no continuous polling or history

## Non-Goals

- Historical metrics / sparklines / trend data
- Continuous WebSocket-pushed health updates
- New database tables or migrations
- Alerting or notification on health degradation

---

## Backend

### New Endpoint: `GET /system/health`

**File:** `backend/app/api/system.py`
**Auth:** Required (`X-API-Key`)
**Router prefix:** `/system`
**Registered in:** `main.py`

#### Response Schema

```json
{
  "status": "healthy | degraded | unhealthy",
  "timestamp": "ISO-8601",
  "services": {
    "redis": { "status": "up | down", "latency_ms": 2 },
    "postgres": { "status": "up | down", "latency_ms": 5 },
    "okx_ws": { "status": "up | down", "connected_pairs": 3 }
  },
  "pipeline": {
    "signals_today": 3,
    "last_cycle_seconds_ago": 12,
    "active_pairs": 3,
    "candle_buffer": { "BTC-USDT-SWAP": 200, "ETH-USDT-SWAP": 200, "WIF-USDT-SWAP": 185 }
  },
  "resources": {
    "memory_mb": 240,
    "db_pool_active": 3,
    "db_pool_size": 10,
    "ws_clients": 1,
    "uptime_seconds": 389580
  },
  "freshness": {
    "technicals_seconds_ago": 3,
    "order_flow_seconds_ago": 1,
    "onchain_seconds_ago": 107,
    "ml_models_loaded": 3
  }
}
```

#### Data Sources

| Field | Source |
|-------|--------|
| `services.redis` | `await redis.ping()` + timing |
| `services.postgres` | `SELECT 1` via async session + timing |
| `services.okx_ws` | Check if `app.state.order_flow` has recent data (updated by OKX WS collectors). "Recent" = last-update timestamp within 60 seconds; if older, report `"down"` |
| `pipeline.signals_today` | `SELECT COUNT(*) FROM signals WHERE created_at >= today` |
| `pipeline.last_cycle_seconds_ago` | `time.time() - app.state.last_pipeline_cycle` (new field on app.state, set at end of `run_pipeline`) |
| `pipeline.active_pairs` | `len(app.state.settings.pairs)` |
| `pipeline.candle_buffer` | `LLEN` on Redis key per pair (e.g., `candles:BTC-USDT-SWAP:1m`) |
| `resources.memory_mb` | Read `/proc/self/status` VmRSS field (Linux only — works in Docker container; not available in local dev on macOS/Windows) |
| `resources.db_pool_active` | `engine.pool.checkedout()` |
| `resources.db_pool_size` | `engine.pool.size()` |
| `resources.ws_clients` | `len(app.state.manager.connections)` |
| `resources.uptime_seconds` | `time.time() - app.state.start_time` (new field, set in lifespan) |
| `freshness.technicals_seconds_ago` | Derived from latest candle timestamp in Redis |
| `freshness.order_flow_seconds_ago` | `app.state.order_flow` dict last-update timestamp |
| `freshness.onchain_seconds_ago` | Check Redis `onchain:{pair}:{metric}` key timestamps; null if on-chain collector inactive |
| `freshness.ml_models_loaded` | `len(app.state.ml_predictors)` |

#### Error Handling

Each dependency check is wrapped in `try/except` with a 2-second `asyncio.wait_for` timeout. If a check fails, that service reports `"status": "down"` with `latency_ms: null`. The top-level `status` is:
- `"healthy"` — all services up
- `"degraded"` — one service down
- `"unhealthy"` — two or more services down

#### app.state Changes

Two new fields set during lifespan startup:
- `app.state.start_time = time.time()` — set once at startup
- `app.state.last_pipeline_cycle = time.time()` — updated at end of each `run_pipeline` call

---

## Frontend

### New Component: `SystemDiagnostics.tsx`

**Replaces** the existing `web/src/features/system/components/SystemDiagnostics.tsx`.

#### Layout (top to bottom)

1. **Status Banner** — always visible, wrapped in `aria-live="polite"` so status changes are announced to screen readers
   - Overall status text: "All Systems Operational" / "Degraded" / "Unhealthy"
   - Status icon: checkmark (healthy) / warning triangle (degraded) / X circle (unhealthy) — don't rely on color alone
   - Status dot color: green / yellow / red as secondary indicator
   - Refresh button (top-right) — disabled during fetch, icon swaps to spinner while loading
   - During refresh: apply `opacity-60` to all data sections below the banner to indicate stale data is being replaced

2. **Service Health Row** — always visible
   - 3-column grid on screens ≥375px; stacks to single column below 375px
   - One pill per service (Redis, Postgres, OKX WS)
   - Shows status dot + latency (or "Live" / "Down")
   - Green dot + checkmark when up, red dot + X icon when down — don't rely on color alone

3. **Expandable Sections** — collapsed by default, tap to toggle
   - Section headers: `min-h-[44px]`, full-width tap target, chevron icon (rotates on expand/collapse)
   - Each collapsed section shows a summary line (e.g., "3 signals today · last cycle 12s ago") so users can skip expanding when things are green. During initial load, summary lines show skeleton text.
   - All numeric values use `tabular-nums` / `font-variant-numeric: tabular-nums` to prevent layout shift on refresh

   **a) Pipeline** — 2x2 grid:
   - Signals Today — count
   - Last Cycle — formatted as relative time (see Relative Time Display below)
   - Active Pairs — count
   - Candle Buffer — show minimum buffer across all pairs as "185 / 200" (min / max); per-pair breakdown is in WebSocket Streams section

   **b) WebSocket Streams** — per-pair rows:
   - Pair name, candle count (from `candle_buffer` object), connection badge

   **c) Resources:**
   - Memory — displayed as formatted text "240 MB" (no progress bar — no meaningful max)
   - DB Pool — progress bar with label "3 / 10"
   - WS Clients — displayed as count (no progress bar — max is unbounded)
   - Uptime — formatted as compact `Xd Xh Xm` (e.g., "4d 12h 13m")

   **d) Data Freshness** — per-source rows with status bar + "last update" text:
   - If a freshness value is `null`, show "Inactive" in muted text (`text-on-surface-variant`) instead of a progress bar
   - If `ml_models_loaded` is 0, show "No models loaded" in warning color (`text-primary`)
   - Freshness thresholds and bar colors:

     | Source | Green (<) | Yellow | Red (>) |
     |--------|-----------|--------|---------|
     | Technicals | 30s | 30–120s | 120s |
     | Order Flow | 30s | 30–120s | 120s |
     | On-Chain | 300s | 300–600s | 600s |

   - Bar width = inverse proportion capped at the red threshold (e.g., technicals at 60s = `1 - 60/120 = 50%` width)
   - ML Models Loaded — show count as text (e.g., "3 models")

#### State Management

- **No Zustand store** — all state is local to the component (ephemeral UI)
- `useState` for expand/collapse toggles
- `useState` for health data + loading + error states

#### Relative Time Display

`last_cycle_seconds_ago` and freshness `*_seconds_ago` values go stale since there's no polling. To keep them accurate without WebSocket updates:
- Store the response `timestamp` alongside the data
- Run a `useEffect` interval (every 5s) that recomputes displayed relative times by adding elapsed client-side time to the original `seconds_ago` values
- This keeps "Last Cycle: 12s ago" ticking up to "Last Cycle: 17s ago" etc. without re-fetching

#### Hook: `useSystemHealth`

Local hook in the system feature directory. Responsibilities:
- Fetch `GET /system/health` on mount
- Expose `data`, `loading`, `refreshing`, `error`, `refresh()` function
- `loading` is true only on initial fetch (skeleton state); `refreshing` is true on subsequent refreshes (opacity dim state)
- `refresh()` re-fetches; sets `refreshing` = true (not `loading`) to avoid replacing content with skeletons

#### API Client Addition

Add `getSystemHealth()` to `web/src/shared/lib/api.ts`:
```typescript
getSystemHealth(): Promise<SystemHealthResponse>
```

#### Error States

- **Initial loading** — skeleton placeholders for the service pills, summary lines, and section content
- **Refreshing** — existing data stays visible with `opacity-60`; refresh button shows spinner and is disabled
- **Fetch error** — banner shows "Unable to reach backend" with retry button
- **Partial degradation** — rendered from the response data (red dots + X icons on failed services, "degraded" banner with warning triangle icon)

---

## Files Changed

### Backend
| File | Change |
|------|--------|
| `backend/app/api/system.py` | **New** — health endpoint with dependency checks |
| `backend/app/main.py` | Register system router, add `start_time` and `last_pipeline_cycle` to app.state |

### Frontend
| File | Change |
|------|--------|
| `web/src/features/system/components/SystemDiagnostics.tsx` | **Rewrite** — new layout with real data |
| `web/src/features/system/hooks/useSystemHealth.ts` | **New** — fetch hook |
| `web/src/features/system/types.ts` | **New** — `SystemHealthResponse` type |
| `web/src/shared/lib/api.ts` | Add `getSystemHealth()` method |

### No Changes To
- Database / migrations
- Existing WebSocket handlers
- Other feature modules
- Package dependencies (memory read via `/proc/self/status` — Linux/Docker only, no new deps)
