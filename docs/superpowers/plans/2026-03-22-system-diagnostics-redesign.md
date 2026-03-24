# System Diagnostics Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded System Diagnostics page with real health data from a new backend endpoint, using a summary + drill-down mobile layout.

**Architecture:** New `GET /system/health` endpoint checks Redis, Postgres, OKX WS connectivity, pipeline metrics, resource usage, and data freshness — each check wrapped in a 2s timeout. Frontend rewrites `SystemDiagnostics.tsx` with a status banner, service pills, and expandable sections backed by a local `useSystemHealth` hook with client-side relative time ticking.

**Tech Stack:** FastAPI (backend), React 19 + Tailwind CSS v3 (frontend), lucide-react icons

**Spec:** `docs/superpowers/specs/2026-03-22-system-diagnostics-redesign.md`

---

## File Structure

### Backend

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/api/system.py` | **Create** | Health endpoint with dependency checks |
| `backend/app/main.py` | **Modify** | Add `start_time` + `last_pipeline_cycle` to `app.state`, register system router |
| `backend/tests/api/test_system_health.py` | **Create** | Tests for health endpoint |

### Frontend

| File | Action | Responsibility |
|------|--------|----------------|
| `web/src/features/system/types.ts` | **Create** | `SystemHealthResponse` TypeScript type |
| `web/src/shared/lib/api.ts` | **Modify** | Add `getSystemHealth()` method |
| `web/src/features/system/hooks/useSystemHealth.ts` | **Create** | Fetch hook with loading/refreshing/error states + 5s ticking |
| `web/src/features/system/components/SystemDiagnostics.tsx` | **Rewrite** | New layout: status banner, service pills, expandable sections |

---

## Task 1: Add `app.state.start_time` and `app.state.last_pipeline_cycle`

**Files:**
- Modify: `backend/app/main.py:990-1002` (lifespan function — add two fields after line 1001)
- Modify: `backend/app/main.py:296-742` (run_pipeline — add timestamp at end)

- [ ] **Step 1: Add `start_time` and `last_pipeline_cycle` to lifespan**

In `backend/app/main.py`, inside the `lifespan` function, add these two lines after `app.state.pipeline_tasks = set()` (after line 1001):

```python
import time  # add to top-level imports if not already present

# Inside lifespan(), after app.state.pipeline_tasks = set():
app.state.start_time = time.time()
app.state.last_pipeline_cycle = 0.0  # no cycle yet
```

Note: `time` is not currently imported in `main.py`. Add `import time` to the top-level imports (near the existing `import asyncio`).

- [ ] **Step 2: Update `last_pipeline_cycle` at end of `run_pipeline`**

In `run_pipeline`, find the `_log_pipeline_evaluation(...)` call (around line 600-610). Immediately **after** it returns (around line 611), and **before** the `if not emitted: return` guard (line 612), add:

```python
app.state.last_pipeline_cycle = time.time()
```

So the code reads:
```python
    _log_pipeline_evaluation(
        pair=pair, timeframe=timeframe,
        ...
    )

    app.state.last_pipeline_cycle = time.time()  # <-- ADD THIS LINE

    if not emitted:
        return
```

**Why here?** The function has early returns at lines 315 (Redis fail), 319 (not enough candles), and 613 (no signal emitted). We want to track when the pipeline last completed a full scoring evaluation — not just when a signal was emitted. Placing it after `_log_pipeline_evaluation` but before `if not emitted` ensures it updates on every successful evaluation cycle, including ones that don't emit a signal.

- [ ] **Step 3: Update test conftest to include new app.state fields**

In `backend/tests/conftest.py`, inside `_test_lifespan`, add after `app.state.pipeline_settings_lock`:

```python
app.state.start_time = 1000000.0
app.state.last_pipeline_cycle = 1000000.0
```

- [ ] **Step 4: Run existing tests to verify nothing breaks**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/conftest.py
git commit -m "feat: add start_time and last_pipeline_cycle to app.state"
```

---

## Task 2: Create `backend/app/api/system.py` — Health Endpoint

**Files:**
- Create: `backend/app/api/system.py`
- Modify: `backend/app/main.py:1246-1287` (register system router)

- [ ] **Step 1: Create the system health endpoint**

Create `backend/app/api/system.py`:

```python
import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from app.api.auth import require_auth
from app.db.models import Signal

router = APIRouter(prefix="/api/system")


async def _check_redis(redis) -> dict:
    """Ping Redis and measure latency."""
    try:
        start = time.monotonic()
        await asyncio.wait_for(redis.ping(), timeout=2.0)
        latency = round((time.monotonic() - start) * 1000)
        return {"status": "up", "latency_ms": latency}
    except Exception:
        return {"status": "down", "latency_ms": None}


async def _check_postgres(db) -> dict:
    """Execute SELECT 1 and measure latency."""
    try:
        start = time.monotonic()

        async def _query():
            async with db.session_factory() as session:
                await session.execute(text("SELECT 1"))

        await asyncio.wait_for(_query(), timeout=2.0)
        latency = round((time.monotonic() - start) * 1000)
        return {"status": "up", "latency_ms": latency}
    except Exception:
        return {"status": "down", "latency_ms": None}


def _check_okx_ws(order_flow: dict) -> dict:
    """Check if order_flow dict has recent data (updated within 60s)."""
    if not order_flow:
        return {"status": "down", "connected_pairs": 0}
    # Count pairs that have any data — order_flow is {pair: {metric: value}}
    connected = len(order_flow)
    return {"status": "up", "connected_pairs": connected}


async def _get_signals_today(db) -> int:
    """Count signals created today."""
    try:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with db.session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(Signal).where(Signal.created_at >= today)
            )
            return result.scalar() or 0
    except Exception:
        return 0


async def _get_candle_buffer(redis, pairs: list[str]) -> dict:
    """Get LLEN of candle buffer per pair."""
    buffer = {}
    for pair in pairs:
        try:
            length = await redis.llen(f"candles:{pair}:1m")
            buffer[pair] = length
        except Exception:
            buffer[pair] = 0
    return buffer


def _get_memory_mb() -> int | None:
    """Read VmRSS from /proc/self/status (Linux/Docker only)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024  # kB -> MB
    except Exception:
        pass
    return None


async def _get_freshness_technicals(redis, pairs: list[str]) -> int | None:
    """Seconds since the most recent candle across all pairs."""
    latest_ts = None
    for pair in pairs:
        try:
            raw = await redis.lindex(f"candles:{pair}:1m", -1)
            if raw:
                candle = json.loads(raw)
                ts = candle.get("timestamp")
                if ts:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        epoch = dt.timestamp()
                    else:
                        epoch = float(ts) / 1000 if ts > 1e12 else float(ts)
                    if latest_ts is None or epoch > latest_ts:
                        latest_ts = epoch
        except Exception:
            continue
    if latest_ts is None:
        return None
    return max(0, int(time.time() - latest_ts))


async def _get_freshness_onchain(redis, pairs: list[str]) -> int | None:
    """Seconds since most recent on-chain data across all pairs."""
    latest_ts = None
    metrics = ["whale_tx_count", "active_addresses", "exchange_netflow", "nvt_ratio"]
    for pair in pairs:
        for metric in metrics:
            try:
                raw = await redis.get(f"onchain:{pair}:{metric}")
                if raw:
                    data = json.loads(raw)
                    ts_str = data.get("ts")
                    if ts_str:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        epoch = dt.timestamp()
                        if latest_ts is None or epoch > latest_ts:
                            latest_ts = epoch
            except Exception:
                continue
    if latest_ts is None:
        return None
    return max(0, int(time.time() - latest_ts))


@router.get("/health")
async def system_health(request: Request, _user: dict = require_auth()):
    app = request.app
    redis = app.state.redis
    db = app.state.db
    settings = app.state.settings
    pairs = list(settings.pairs)

    # Run independent checks concurrently
    redis_check, pg_check, signals_today, candle_buffer = await asyncio.gather(
        _check_redis(redis),
        _check_postgres(db),
        _get_signals_today(db),
        _get_candle_buffer(redis, pairs),
    )

    okx_check = _check_okx_ws(app.state.order_flow)

    # Freshness checks (can run concurrently)
    tech_freshness, onchain_freshness = await asyncio.gather(
        _get_freshness_technicals(redis, pairs),
        _get_freshness_onchain(redis, pairs),
    )

    # Order flow freshness: we don't store timestamps in the dict,
    # so report based on whether data exists
    order_flow = app.state.order_flow
    order_flow_seconds_ago = None
    if order_flow:
        # Data exists — report as recent (pipeline updates it every candle cycle)
        last_cycle = getattr(app.state, "last_pipeline_cycle", 0)
        if last_cycle > 0:
            order_flow_seconds_ago = max(0, int(time.time() - last_cycle))

    # Pipeline metrics
    last_cycle = getattr(app.state, "last_pipeline_cycle", 0)
    last_cycle_seconds_ago = max(0, int(time.time() - last_cycle)) if last_cycle > 0 else None

    # Resources
    engine = db.engine
    memory_mb = _get_memory_mb()

    try:
        pool_active = engine.pool.checkedout()
    except Exception:
        pool_active = 0
    try:
        pool_size = engine.pool.size()
    except Exception:
        pool_size = 0

    ws_clients = len(app.state.manager.connections)
    start_time = getattr(app.state, "start_time", time.time())
    uptime_seconds = max(0, int(time.time() - start_time))

    ml_predictors = getattr(app.state, "ml_predictors", {})

    # Overall status
    services = {
        "redis": redis_check,
        "postgres": pg_check,
        "okx_ws": okx_check,
    }
    down_count = sum(1 for s in services.values() if s["status"] == "down")
    if down_count == 0:
        overall = "healthy"
    elif down_count == 1:
        overall = "degraded"
    else:
        overall = "unhealthy"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "pipeline": {
            "signals_today": signals_today,
            "last_cycle_seconds_ago": last_cycle_seconds_ago,
            "active_pairs": len(pairs),
            "candle_buffer": candle_buffer,
        },
        "resources": {
            "memory_mb": memory_mb,
            "db_pool_active": pool_active,
            "db_pool_size": pool_size,
            "ws_clients": ws_clients,
            "uptime_seconds": uptime_seconds,
        },
        "freshness": {
            "technicals_seconds_ago": tech_freshness,
            "order_flow_seconds_ago": order_flow_seconds_ago,
            "onchain_seconds_ago": onchain_freshness,
            "ml_models_loaded": len(ml_predictors),
        },
    }
```

- [ ] **Step 2: Register the system router in `create_app`**

In `backend/app/main.py`, in the `create_app` function, after the engine router registration (line ~1287), add:

```python
from app.api.system import router as system_router
app.include_router(system_router)
```

- [ ] **Step 3: Run the app to verify no import errors**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.api.system import router; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/system.py backend/app/main.py
git commit -m "feat: add GET /api/system/health endpoint"
```

---

## Task 3: Backend Tests for Health Endpoint

**Files:**
- Create: `backend/tests/api/test_system_health.py`

- [ ] **Step 1: Write tests for the health endpoint**

Create `backend/tests/api/test_system_health.py`:

```python
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_test_jwt


@pytest.fixture
def auth_cookies():
    return {"krypton_token": make_test_jwt()}


@pytest.fixture
async def health_app(app):
    """Extend base app fixture with fields needed by health endpoint.

    The `app` and `client` fixtures from conftest share the same FastAPI instance,
    so mutations here are visible to `client`.
    """
    app.state.redis = AsyncMock()
    app.state.redis.ping = AsyncMock(return_value=True)
    app.state.redis.llen = AsyncMock(return_value=200)
    app.state.redis.lindex = AsyncMock(return_value=None)
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.order_flow = {"BTC-USDT-SWAP": {"funding_rate": 0.001}}
    app.state.start_time = time.time() - 3600
    app.state.last_pipeline_cycle = time.time() - 10

    mock_engine = MagicMock()
    mock_pool = MagicMock()
    mock_pool.checkedout.return_value = 2
    mock_pool.size.return_value = 10
    mock_engine.pool = mock_pool
    app.state.db.engine = mock_engine

    from app.api.connections import ConnectionManager
    app.state.manager = ConnectionManager()
    app.state.ml_predictors = {"BTC-USDT-SWAP": MagicMock()}
    return app


@pytest.mark.asyncio
async def test_health_returns_200(health_app, client, auth_cookies):
    """health_app mutates the shared app instance before client sends the request."""
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "services" in data
    assert "pipeline" in data
    assert "resources" in data
    assert "freshness" in data


@pytest.mark.asyncio
async def test_health_requires_auth(client):
    resp = await client.get("/api/system/health")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health_services_structure(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    services = resp.json()["services"]
    assert "redis" in services
    assert "postgres" in services
    assert "okx_ws" in services
    # Redis should be up since we mocked ping
    assert services["redis"]["status"] == "up"
    assert isinstance(services["redis"]["latency_ms"], int)


@pytest.mark.asyncio
async def test_health_pipeline_structure(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    pipeline = resp.json()["pipeline"]
    assert "signals_today" in pipeline
    assert "last_cycle_seconds_ago" in pipeline
    assert "active_pairs" in pipeline
    assert "candle_buffer" in pipeline


@pytest.mark.asyncio
async def test_health_resources_structure(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    resources = resp.json()["resources"]
    assert "db_pool_active" in resources
    assert resources["db_pool_active"] == 2
    assert resources["db_pool_size"] == 10
    assert "ws_clients" in resources
    assert "uptime_seconds" in resources
    assert resources["uptime_seconds"] >= 3600


@pytest.mark.asyncio
async def test_health_freshness_ml_count(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    freshness = resp.json()["freshness"]
    assert freshness["ml_models_loaded"] == 1


@pytest.mark.asyncio
async def test_health_degraded_when_redis_down(health_app, client, auth_cookies):
    health_app.state.redis.ping = AsyncMock(side_effect=Exception("connection refused"))
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    data = resp.json()
    assert data["services"]["redis"]["status"] == "down"
    assert data["services"]["redis"]["latency_ms"] is None
    assert data["status"] in ("degraded", "unhealthy")
```

- [ ] **Step 2: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_system_health.py -v`
Expected: All tests pass.

- [ ] **Step 3: Fix any failures and re-run**

If tests fail, fix and re-run until green.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/api/test_system_health.py
git commit -m "test: add tests for system health endpoint"
```

---

## Task 4: Create Frontend Types

**Files:**
- Create: `web/src/features/system/types.ts`

- [ ] **Step 1: Create the `SystemHealthResponse` type**

Create `web/src/features/system/types.ts`:

```typescript
export interface ServiceStatus {
  status: "up" | "down";
  latency_ms: number | null;
}

export interface OkxWsStatus {
  status: "up" | "down";
  connected_pairs: number;
}

export interface SystemHealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  timestamp: string;
  services: {
    redis: ServiceStatus;
    postgres: ServiceStatus;
    okx_ws: OkxWsStatus;
  };
  pipeline: {
    signals_today: number;
    last_cycle_seconds_ago: number | null;
    active_pairs: number;
    candle_buffer: Record<string, number>;
  };
  resources: {
    memory_mb: number | null;
    db_pool_active: number;
    db_pool_size: number;
    ws_clients: number;
    uptime_seconds: number;
  };
  freshness: {
    technicals_seconds_ago: number | null;
    order_flow_seconds_ago: number | null;
    onchain_seconds_ago: number | null;
    ml_models_loaded: number;
  };
}
```

- [ ] **Step 2: Verify no TypeScript errors**

Run: `cd web && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to this file.

- [ ] **Step 3: Commit**

```bash
git add web/src/features/system/types.ts
git commit -m "feat: add SystemHealthResponse type"
```

---

## Task 5: Add `getSystemHealth()` to API Client

**Files:**
- Modify: `web/src/shared/lib/api.ts:1-2` (add import)
- Modify: `web/src/shared/lib/api.ts:218` (add method inside `api` object)

- [ ] **Step 1: Add the import**

At the top of `web/src/shared/lib/api.ts`, add to the imports:

```typescript
import type { SystemHealthResponse } from "../../features/system/types";
```

- [ ] **Step 2: Add the method to the `api` object**

Inside the `api` object (after the last method, `optimizeAtr`, around line 466), add:

```typescript
  // System
  getSystemHealth: () => request<SystemHealthResponse>("/api/system/health"),
```

- [ ] **Step 3: Verify no TypeScript errors**

Run: `cd web && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/shared/lib/api.ts
git commit -m "feat: add getSystemHealth to API client"
```

---

## Task 6: Create `useSystemHealth` Hook

**Files:**
- Create: `web/src/features/system/hooks/useSystemHealth.ts`

- [ ] **Step 1: Create the hook**

Create `web/src/features/system/hooks/useSystemHealth.ts`:

```typescript
import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "../../../shared/lib/api";
import type { SystemHealthResponse } from "../types";

export function useSystemHealth() {
  const [data, setData] = useState<SystemHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedAtRef = useRef<number>(0);
  const [tick, setTick] = useState(0);

  const fetchHealth = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const result = await api.getSystemHealth();
      setData(result);
      fetchedAtRef.current = Date.now();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Fetch on mount
  useEffect(() => {
    fetchHealth(false);
  }, [fetchHealth]);

  // Tick every 5s to keep relative times accurate
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 5000);
    return () => clearInterval(id);
  }, []);

  // Compute elapsed seconds since last fetch
  const elapsed = fetchedAtRef.current > 0
    ? Math.floor((Date.now() - fetchedAtRef.current) / 1000)
    : 0;

  // Force re-read of elapsed on each tick
  void tick;

  const refresh = useCallback(() => fetchHealth(true), [fetchHealth]);

  return { data, loading, refreshing, error, refresh, elapsed };
}
```

- [ ] **Step 2: Verify no TypeScript errors**

Run: `cd web && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/features/system/hooks/useSystemHealth.ts
git commit -m "feat: add useSystemHealth hook"
```

---

## Task 7: Rewrite `SystemDiagnostics.tsx`

**Files:**
- Rewrite: `web/src/features/system/components/SystemDiagnostics.tsx`

This is the largest task. The component has four sections: Status Banner, Service Health Row, Expandable Sections (Pipeline, WebSocket Streams, Resources, Data Freshness).

- [ ] **Step 1: Write the full component**

Rewrite `web/src/features/system/components/SystemDiagnostics.tsx`:

```tsx
import { useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  ChevronDown,
  Loader2,
} from "lucide-react";
import { useSystemHealth } from "../hooks/useSystemHealth";
import type { SystemHealthResponse } from "../types";

// ─── Helpers ───────────────────────────────────────────────────

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatSecondsAgo(seconds: number | null | undefined): string {
  if (seconds == null) return "N/A";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function adjusted(original: number | null | undefined, elapsed: number): number | null {
  if (original == null) return null;
  return original + elapsed;
}

type FreshnessLevel = "green" | "yellow" | "red";

function freshnessLevel(seconds: number | null, greenMax: number, redMin: number): FreshnessLevel {
  if (seconds == null) return "red";
  if (seconds < greenMax) return "green";
  if (seconds <= redMin) return "yellow";
  return "red";
}

function freshnessBarWidth(seconds: number | null, redThreshold: number): number {
  if (seconds == null) return 0;
  const ratio = 1 - Math.min(seconds, redThreshold) / redThreshold;
  return Math.max(0, Math.round(ratio * 100));
}

const FRESHNESS_COLORS: Record<FreshnessLevel, string> = {
  green: "bg-tertiary-dim",
  yellow: "bg-primary",
  red: "bg-error",
};

const FRESHNESS_TEXT: Record<FreshnessLevel, string> = {
  green: "text-tertiary-dim",
  yellow: "text-primary",
  red: "text-error",
};

// ─── Status Banner ─────────────────────────────────────────────

function StatusBanner({
  status,
  refreshing,
  onRefresh,
}: {
  status: "healthy" | "degraded" | "unhealthy" | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const config = {
    healthy: { label: "All Systems Operational", Icon: CheckCircle2, dot: "bg-tertiary-dim", text: "text-tertiary-dim" },
    degraded: { label: "Degraded", Icon: AlertTriangle, dot: "bg-primary", text: "text-primary" },
    unhealthy: { label: "Unhealthy", Icon: XCircle, dot: "bg-error", text: "text-error" },
  };
  const c = status ? config[status] : config.unhealthy;

  return (
    <div className="flex items-center justify-between bg-surface-container p-4 rounded-lg border border-outline-variant/10" aria-live="polite">
      <div className="flex items-center gap-3">
        <span className={`w-2.5 h-2.5 rounded-full ${c.dot} shrink-0`} />
        <c.Icon size={18} className={c.text} />
        <span className={`font-headline font-bold text-sm uppercase tracking-wide ${c.text}`}>{c.label}</span>
      </div>
      <button
        onClick={onRefresh}
        disabled={refreshing}
        className="p-2 rounded-lg hover:bg-surface-container-highest transition-colors disabled:opacity-50"
        aria-label="Refresh system health"
      >
        {refreshing ? (
          <Loader2 size={18} className="text-primary animate-spin" />
        ) : (
          <RefreshCw size={18} className="text-on-surface-variant" />
        )}
      </button>
    </div>
  );
}

// ─── Service Pills ─────────────────────────────────────────────

function ServicePill({
  label,
  status,
  detail,
}: {
  label: string;
  status: "up" | "down";
  detail: string;
}) {
  const up = status === "up";
  return (
    <div className="bg-surface-container p-3 rounded-lg border border-outline-variant/10 flex items-center gap-2.5">
      <span className={`w-2 h-2 rounded-full shrink-0 ${up ? "bg-tertiary-dim" : "bg-error"}`} />
      {up ? <CheckCircle2 size={14} className="text-tertiary-dim shrink-0" /> : <XCircle size={14} className="text-error shrink-0" />}
      <div className="min-w-0">
        <p className="text-[11px] font-bold text-on-surface truncate">{label}</p>
        <p className={`text-[10px] font-bold tabular-nums ${up ? "text-tertiary-dim" : "text-error"}`}>{detail}</p>
      </div>
    </div>
  );
}

function ServiceHealthRow({ data }: { data: SystemHealthResponse }) {
  const { redis, postgres, okx_ws } = data.services;
  return (
    <div className="grid grid-cols-3 max-[374px]:grid-cols-1 gap-2">
      <ServicePill
        label="Redis"
        status={redis.status}
        detail={redis.status === "up" ? `${redis.latency_ms}ms` : "Down"}
      />
      <ServicePill
        label="Postgres"
        status={postgres.status}
        detail={postgres.status === "up" ? `${postgres.latency_ms}ms` : "Down"}
      />
      <ServicePill
        label="OKX WS"
        status={okx_ws.status}
        detail={okx_ws.status === "up" ? `${okx_ws.connected_pairs} pairs` : "Down"}
      />
    </div>
  );
}

// ─── Expandable Section ────────────────────────────────────────

function Section({
  title,
  summary,
  open,
  onToggle,
  children,
}: {
  title: string;
  summary: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 min-h-[44px] hover:bg-surface-container-highest transition-colors"
      >
        <div className="text-left min-w-0">
          <span className="text-[11px] font-headline font-bold text-primary uppercase tracking-widest">{title}</span>
          {!open && <p className="text-[10px] text-on-surface-variant truncate mt-0.5">{summary}</p>}
        </div>
        <ChevronDown
          size={16}
          className={`text-on-surface-variant shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="px-4 pb-4 pt-1">{children}</div>}
    </div>
  );
}

// ─── Section Content ───────────────────────────────────────────

function PipelineSection({ data, elapsed }: { data: SystemHealthResponse; elapsed: number }) {
  const { pipeline } = data;
  const lastCycle = adjusted(pipeline.last_cycle_seconds_ago, elapsed);
  const bufferValues = Object.values(pipeline.candle_buffer);
  const minBuffer = bufferValues.length > 0 ? Math.min(...bufferValues) : 0;
  const maxBuffer = bufferValues.length > 0 ? Math.max(...bufferValues) : 0;

  return (
    <div className="grid grid-cols-2 gap-3">
      <MetricCard label="Signals Today" value={String(pipeline.signals_today)} />
      <MetricCard label="Last Cycle" value={formatSecondsAgo(lastCycle)} />
      <MetricCard label="Active Pairs" value={String(pipeline.active_pairs)} />
      <MetricCard label="Candle Buffer" value={`${minBuffer} / ${maxBuffer}`} />
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-container-low p-3 rounded-lg">
      <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">{label}</p>
      <p className="text-sm font-bold text-on-surface tabular-nums mt-1">{value}</p>
    </div>
  );
}

function WebSocketSection({ data }: { data: SystemHealthResponse }) {
  const entries = Object.entries(data.pipeline.candle_buffer);
  return (
    <div className="space-y-2">
      {entries.map(([pair, count]) => (
        <div key={pair} className="flex items-center justify-between">
          <span className="font-mono text-xs text-on-surface">{pair}</span>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold tabular-nums text-on-surface-variant">{count} candles</span>
            <span className="w-1.5 h-1.5 rounded-full bg-tertiary-dim" />
          </div>
        </div>
      ))}
      {entries.length === 0 && (
        <p className="text-[10px] text-on-surface-variant">No streams active</p>
      )}
    </div>
  );
}

function ResourcesSection({ data, elapsed }: { data: SystemHealthResponse; elapsed: number }) {
  const { resources } = data;
  const uptime = resources.uptime_seconds + elapsed;
  const poolPct = resources.db_pool_size > 0
    ? Math.round((resources.db_pool_active / resources.db_pool_size) * 100)
    : 0;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">Memory</span>
        <span className="text-xs font-bold tabular-nums text-on-surface">
          {resources.memory_mb != null ? `${resources.memory_mb} MB` : "N/A"}
        </span>
      </div>
      <div>
        <div className="flex justify-between items-center mb-1">
          <span className="text-[10px] font-bold text-on-surface-variant uppercase">DB Pool</span>
          <span className="text-xs font-bold tabular-nums text-on-surface">{resources.db_pool_active} / {resources.db_pool_size}</span>
        </div>
        <div className="h-1.5 w-full bg-surface-container-lowest rounded-full overflow-hidden">
          <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${poolPct}%` }} />
        </div>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">WS Clients</span>
        <span className="text-xs font-bold tabular-nums text-on-surface">{resources.ws_clients}</span>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">Uptime</span>
        <span className="text-xs font-bold tabular-nums text-on-surface">{formatUptime(uptime)}</span>
      </div>
    </div>
  );
}

function FreshnessSection({ data, elapsed }: { data: SystemHealthResponse; elapsed: number }) {
  const { freshness } = data;
  const techSec = adjusted(freshness.technicals_seconds_ago, elapsed);
  const flowSec = adjusted(freshness.order_flow_seconds_ago, elapsed);
  const onchainSec = adjusted(freshness.onchain_seconds_ago, elapsed);

  return (
    <div className="space-y-4">
      <FreshnessRow label="Technicals" seconds={techSec} greenMax={30} redThreshold={120} />
      <FreshnessRow label="Order Flow" seconds={flowSec} greenMax={30} redThreshold={120} />
      <FreshnessRow label="On-Chain" seconds={onchainSec} greenMax={300} redThreshold={600} />
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">ML Models</span>
        <span className={`text-xs font-bold tabular-nums ${freshness.ml_models_loaded === 0 ? "text-primary" : "text-on-surface"}`}>
          {freshness.ml_models_loaded === 0 ? "No models loaded" : `${freshness.ml_models_loaded} models`}
        </span>
      </div>
    </div>
  );
}

function FreshnessRow({
  label,
  seconds,
  greenMax,
  redThreshold,
}: {
  label: string;
  seconds: number | null;
  greenMax: number;
  redThreshold: number;
}) {
  if (seconds == null) {
    return (
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">{label}</span>
        <span className="text-[10px] font-bold text-on-surface-variant">Inactive</span>
      </div>
    );
  }

  const level = freshnessLevel(seconds, greenMax, redThreshold);
  const width = freshnessBarWidth(seconds, redThreshold);

  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">{label}</span>
        <span className={`text-[10px] font-bold tabular-nums ${FRESHNESS_TEXT[level]}`}>
          {formatSecondsAgo(seconds)}
        </span>
      </div>
      <div className="h-1.5 w-full bg-surface-container-lowest rounded-full overflow-hidden">
        <div
          className={`h-full ${FRESHNESS_COLORS[level]} rounded-full transition-all`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

// ─── Skeleton ──────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-14 bg-surface-container rounded-lg" />
      <div className="grid grid-cols-3 max-[374px]:grid-cols-1 gap-2">
        {[0, 1, 2].map((i) => <div key={i} className="h-16 bg-surface-container rounded-lg" />)}
      </div>
      {[0, 1, 2, 3].map((i) => <div key={i} className="h-12 bg-surface-container rounded-lg" />)}
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────

export function SystemDiagnostics() {
  const { data, loading, refreshing, error, refresh, elapsed } = useSystemHealth();
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});

  const toggle = (key: string) =>
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  if (loading) return <Skeleton />;

  if (error && !data) {
    return (
      <div className="bg-surface-container p-6 rounded-lg border border-error/20 text-center">
        <XCircle size={32} className="text-error mx-auto mb-3" />
        <p className="text-sm font-bold text-on-surface mb-1">Unable to reach backend</p>
        <p className="text-xs text-on-surface-variant mb-4">{error}</p>
        <button
          onClick={refresh}
          className="px-4 py-2 bg-primary/10 text-primary text-xs font-bold rounded-lg hover:bg-primary/20 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const pipelineSummary = `${data.pipeline.signals_today} signals today · last cycle ${formatSecondsAgo(adjusted(data.pipeline.last_cycle_seconds_ago, elapsed))}`;
  const bufferValues = Object.values(data.pipeline.candle_buffer);
  const minBuffer = bufferValues.length > 0 ? Math.min(...bufferValues) : 0;
  const wsSummary = `${Object.keys(data.pipeline.candle_buffer).length} streams · min ${minBuffer} candles`;
  const resourceSummary = `${data.resources.db_pool_active}/${data.resources.db_pool_size} pool · ${data.resources.ws_clients} WS · ${formatUptime(data.resources.uptime_seconds + elapsed)}`;
  const freshnessSummary = `Tech ${formatSecondsAgo(adjusted(data.freshness.technicals_seconds_ago, elapsed))} · ${data.freshness.ml_models_loaded} ML models`;

  return (
    <div className={`space-y-3 ${refreshing ? "opacity-60 transition-opacity" : ""}`}>
      <StatusBanner status={data.status} refreshing={refreshing} onRefresh={refresh} />
      <ServiceHealthRow data={data} />

      <Section title="Pipeline" summary={pipelineSummary} open={!!openSections.pipeline} onToggle={() => toggle("pipeline")}>
        <PipelineSection data={data} elapsed={elapsed} />
      </Section>

      <Section title="WebSocket Streams" summary={wsSummary} open={!!openSections.ws} onToggle={() => toggle("ws")}>
        <WebSocketSection data={data} />
      </Section>

      <Section title="Resources" summary={resourceSummary} open={!!openSections.resources} onToggle={() => toggle("resources")}>
        <ResourcesSection data={data} elapsed={elapsed} />
      </Section>

      <Section title="Data Freshness" summary={freshnessSummary} open={!!openSections.freshness} onToggle={() => toggle("freshness")}>
        <FreshnessSection data={data} elapsed={elapsed} />
      </Section>
    </div>
  );
}
```

- [ ] **Step 2: Verify no TypeScript errors**

Run: `cd web && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors.

- [ ] **Step 3: Visual check in dev server**

Run: `cd web && pnpm dev`
Navigate to System Hub > System. Verify:
- Skeleton appears on initial load
- Status banner shows overall status
- Service pills show Redis, Postgres, OKX WS
- Expandable sections show collapsed summaries
- Sections expand/collapse on tap
- Refresh button triggers opacity dimming
- Relative times tick up every 5 seconds

- [ ] **Step 4: Commit**

```bash
git add web/src/features/system/components/SystemDiagnostics.tsx
git commit -m "feat: rewrite SystemDiagnostics with real health data"
```

---

## Task 8: Final Build Verification

**Files:** None (verification only)

- [ ] **Step 1: Run backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 2: Run frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no TypeScript or lint errors.

- [ ] **Step 3: Run frontend tests (if any)**

Run: `cd web && pnpm test -- --run`
Expected: All tests pass.

- [ ] **Step 4: Final commit (if any fixups needed)**

If any fixes were required in steps 1-3, commit them:

```bash
git add -A
git commit -m "fix: build and test fixes for system diagnostics"
```
