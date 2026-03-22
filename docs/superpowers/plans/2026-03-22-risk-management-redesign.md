# Risk Management Page Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static risk settings page with an integrated view showing live risk state (daily P&L, exposure, positions, cooldown) alongside configurable settings, powered by a new composite `GET /api/risk/status` endpoint.

**Architecture:** New backend endpoint queries RiskSettings + OKX client + Signal table to build a composite risk status response with inline rule evaluations. Frontend RiskPage is fully rewritten to consume this endpoint, displaying per-rule status indicators (OK/WARNING/BLOCKED) with progress bars, a cooldown countdown timer, and a new numeric input for max position size.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, React 19, Tailwind CSS, Lucide icons

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `backend/tests/api/test_risk_status.py` | Tests for `GET /api/risk/status` endpoint |
| Modify | `backend/app/api/risk.py` | Add `GET /api/risk/status` endpoint with response models and rule evaluation |
| Modify | `web/src/shared/lib/api.ts` | Add `RiskStatus`/`RiskState` types, `getRiskStatus()` method |
| Modify | `web/src/features/settings/components/RiskPage.tsx` | Full rewrite with live status, progress bars, cooldown timer |

---

### Task 1: Write failing tests for `GET /api/risk/status`

**Files:**
- Create: `backend/tests/api/test_risk_status.py`

This task creates the test file with all test cases for the new endpoint. Tests follow the existing pattern from `tests/api/test_routes.py` using `httpx.AsyncClient` + `ASGITransport` with mock DB sessions.

- [ ] **Step 1: Write test file with all test cases**

```python
"""Tests for GET /api/risk/status composite endpoint."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.risk import router as risk_router
from tests.conftest import make_test_jwt


def _make_risk_settings(**overrides):
    """Create a mock RiskSettings ORM object."""
    rs = MagicMock()
    rs.risk_per_trade = overrides.get("risk_per_trade", 0.01)
    rs.max_position_size_usd = overrides.get("max_position_size_usd", None)
    rs.daily_loss_limit_pct = overrides.get("daily_loss_limit_pct", 0.03)
    rs.max_concurrent_positions = overrides.get("max_concurrent_positions", 3)
    rs.max_exposure_pct = overrides.get("max_exposure_pct", 1.5)
    rs.cooldown_after_loss_minutes = overrides.get("cooldown_after_loss_minutes", 30)
    rs.max_risk_per_trade_pct = overrides.get("max_risk_per_trade_pct", 0.02)
    rs.updated_at = overrides.get("updated_at", datetime(2026, 3, 22, 9, 0, tzinfo=timezone.utc))
    return rs


def _make_signal(outcome, outcome_at, outcome_pnl_pct):
    """Create a mock Signal ORM object."""
    sig = MagicMock()
    sig.outcome = outcome
    sig.outcome_at = outcome_at
    sig.outcome_pnl_pct = Decimal(str(outcome_pnl_pct))
    return sig


def _mock_db_for_status(risk_settings, resolved_signals=None, last_sl_signal=None):
    """Build a mock DB that handles the multiple queries in the status endpoint.

    The endpoint runs up to 3 queries in sequence:
    1. RiskSettings singleton
    2. Resolved signals for daily P&L (scalars().all())
    3. Last SL_HIT signal (scalar_one_or_none())
    """
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()

        if call_count == 1:
            # Query 1: RiskSettings
            result.scalar_one_or_none.return_value = risk_settings
        elif call_count == 2:
            # Query 2: Resolved signals for daily P&L
            result.scalars.return_value.all.return_value = resolved_signals or []
        elif call_count == 3:
            # Query 3: Last SL_HIT signal
            result.scalar_one_or_none.return_value = last_sl_signal
        return result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=fake_execute)

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db


def _make_app(okx_client=None, db=None):
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
    app.state.settings = mock_settings
    app.state.okx_client = okx_client
    app.state.db = db or MagicMock()
    app.include_router(risk_router)
    return app


def _make_okx(equity=10000.0, positions=None):
    okx = AsyncMock()
    okx.get_balance = AsyncMock(return_value={"total_equity": equity})
    okx.get_positions = AsyncMock(return_value=positions or [])
    return okx


@pytest.fixture
def auth_cookies():
    return {"krypton_token": make_test_jwt()}


@pytest.mark.asyncio
async def test_risk_status_all_ok(auth_cookies):
    """All rules OK: no positions, no daily loss, no cooldown."""
    rs = _make_risk_settings(cooldown_after_loss_minutes=30)
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_status"] == "OK"
    assert data["settings"]["risk_per_trade"] == 0.01
    assert data["state"]["equity"] == 10000.0
    assert data["state"]["open_positions_count"] == 0
    assert data["state"]["daily_pnl_pct"] == 0.0
    # All rules should be OK
    for rule in data["rules"]:
        assert rule["status"] == "OK"


@pytest.mark.asyncio
async def test_risk_status_daily_loss_blocked(auth_cookies):
    """daily_loss_limit rule → BLOCKED when daily P&L exceeds limit."""
    rs = _make_risk_settings(daily_loss_limit_pct=0.03)
    # Signals with outcome_pnl_pct summing to -4.0 (i.e., -4% in DB → -0.04 decimal)
    signals = [
        _make_signal("SL_HIT", datetime(2026, 3, 22, 10, 0, tzinfo=timezone.utc), -2.5),
        _make_signal("SL_HIT", datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc), -1.5),
    ]
    db = _mock_db_for_status(rs, resolved_signals=signals, last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    assert data["overall_status"] == "BLOCKED"
    daily_rule = next(r for r in data["rules"] if r["rule"] == "daily_loss_limit")
    assert daily_rule["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_risk_status_max_concurrent_blocked(auth_cookies):
    """max_concurrent rule → BLOCKED when positions at limit."""
    rs = _make_risk_settings(max_concurrent_positions=2)
    positions = [
        {"size": 1.0, "mark_price": 65000.0},
        {"size": 0.5, "mark_price": 3000.0},
    ]
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=positions)
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    pos_rule = next(r for r in data["rules"] if r["rule"] == "max_concurrent")
    assert pos_rule["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_risk_status_exposure_warning(auth_cookies):
    """max_exposure rule → WARNING when usage > 80%."""
    rs = _make_risk_settings(max_exposure_pct=1.5)
    positions = [{"size": 1.0, "mark_price": 13000.0}]  # 130% of 10k equity → > 80% of 150% limit
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=positions)
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    exp_rule = next(r for r in data["rules"] if r["rule"] == "max_exposure")
    assert exp_rule["status"] == "WARNING"


@pytest.mark.asyncio
async def test_risk_status_cooldown_warning(auth_cookies):
    """cooldown rule appears as WARNING when cooldown is active."""
    now = datetime.now(timezone.utc)
    last_sl = _make_signal("SL_HIT", now - timedelta(minutes=10), -1.0)
    rs = _make_risk_settings(cooldown_after_loss_minutes=30)
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=last_sl)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    cd_rule = next((r for r in data["rules"] if r["rule"] == "cooldown"), None)
    assert cd_rule is not None
    assert cd_rule["status"] == "WARNING"
    assert "remaining" in cd_rule["reason"].lower() or "min" in cd_rule["reason"].lower()


@pytest.mark.asyncio
async def test_risk_status_cooldown_omitted_when_inactive(auth_cookies):
    """cooldown rule omitted when not configured."""
    rs = _make_risk_settings(cooldown_after_loss_minutes=None)
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    cd_rules = [r for r in data["rules"] if r["rule"] == "cooldown"]
    assert len(cd_rules) == 0


@pytest.mark.asyncio
async def test_risk_status_no_okx_returns_zeros(auth_cookies):
    """When OKX client is None, state fields are zero, all rules OK."""
    rs = _make_risk_settings()
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    app = _make_app(okx_client=None, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"]["equity"] == 0
    assert data["state"]["open_positions_count"] == 0
    assert data["state"]["exposure_pct"] == 0
    assert data["overall_status"] == "OK"


@pytest.mark.asyncio
async def test_risk_status_requires_auth():
    """Endpoint requires authentication."""
    rs = _make_risk_settings()
    db = _mock_db_for_status(rs)
    app = _make_app(okx_client=None, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status")

    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_risk_status.py -v`
Expected: FAIL — `GET /api/risk/status` endpoint does not exist yet, tests should fail with 404 or import errors.

---

### Task 2: Implement `GET /api/risk/status` endpoint

**Files:**
- Modify: `backend/app/api/risk.py:1-161` (add new endpoint + response models after existing code)

- [ ] **Step 1: Add Pydantic response models and the status endpoint**

Add these imports at the top of `backend/app/api/risk.py` (merge with existing imports):

```python
from datetime import datetime, timezone
from sqlalchemy import select, and_
```

Add `and_` to the existing `sqlalchemy` import line. Then add this code **after** the existing `check_risk` endpoint (after line 161):

```python
class RiskStateResponse(BaseModel):
    equity: float
    daily_pnl_pct: float
    open_positions_count: int
    total_exposure_usd: float
    exposure_pct: float
    last_sl_hit_at: str | None


class RiskRuleResponse(BaseModel):
    rule: str
    status: str  # "OK" | "WARNING" | "BLOCKED"
    reason: str


class RiskStatusResponse(BaseModel):
    settings: dict
    state: RiskStateResponse
    rules: list[RiskRuleResponse]
    overall_status: str  # "OK" | "WARNING" | "BLOCKED"


@router.get("/status")
async def get_risk_status(request: Request, _user=require_auth()):
    db = request.app.state.db
    okx = request.app.state.okx_client

    # 1. Load risk settings
    async with db.session_factory() as session:
        result = await session.execute(
            select(RiskSettings).where(RiskSettings.id == 1)
        )
        rs = result.scalar_one_or_none()
    if not rs:
        raise HTTPException(500, "Risk settings not initialized")

    settings_dict = _settings_to_dict(rs)

    # 2. Gather live state (zeros if OKX unavailable)
    equity = 0.0
    daily_pnl_pct = 0.0
    open_positions_count = 0
    total_exposure_usd = 0.0
    exposure_pct = 0.0
    last_sl_hit_dt = None  # kept as datetime internally, converted to ISO string for response

    if okx:
        try:
            balance = await okx.get_balance()
            equity = balance["total_equity"] if balance else 0.0

            positions = await okx.get_positions()
            open_positions_count = len(positions)
            total_exposure_usd = sum(
                abs(p.get("size", 0) * p.get("mark_price", 0)) for p in positions
            )
            exposure_pct = total_exposure_usd / equity if equity > 0 else 0.0
        except Exception:
            pass

    # 3. Daily P&L from resolved signals (not OKX fills)
    async with db.session_factory() as session:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await session.execute(
            select(Signal).where(
                and_(
                    Signal.outcome.in_(["TP1_HIT", "TP2_HIT", "SL_HIT"]),
                    Signal.outcome_at >= today_start,
                )
            )
        )
        resolved = result.scalars().all()
        if resolved:
            raw_sum = sum(
                float(s.outcome_pnl_pct) for s in resolved if s.outcome_pnl_pct is not None
            )
            # DB stores percentage values (e.g. -1.5 for -1.5%), convert to decimal fraction
            daily_pnl_pct = raw_sum / 100.0

    # 4. Last SL hit timestamp (for cooldown)
    if rs.cooldown_after_loss_minutes:
        async with db.session_factory() as session:
            result = await session.execute(
                select(Signal)
                .where(Signal.outcome == "SL_HIT")
                .order_by(Signal.outcome_at.desc())
                .limit(1)
            )
            last_sl = result.scalar_one_or_none()
            if last_sl and last_sl.outcome_at:
                last_sl_hit_dt = last_sl.outcome_at

    # 5. Evaluate rules
    rules = []

    # daily_loss_limit
    usage_pct = abs(daily_pnl_pct) / rs.daily_loss_limit_pct if rs.daily_loss_limit_pct else 0
    remaining_pct = (rs.daily_loss_limit_pct - abs(daily_pnl_pct)) * 100
    if abs(daily_pnl_pct) >= rs.daily_loss_limit_pct:
        rules.append(RiskRuleResponse(
            rule="daily_loss_limit",
            status="BLOCKED",
            reason=f"Daily P&L {daily_pnl_pct*100:.1f}% hit {rs.daily_loss_limit_pct*100:.0f}% limit",
        ))
    elif usage_pct > 0.7:
        rules.append(RiskRuleResponse(
            rule="daily_loss_limit",
            status="WARNING",
            reason=f"Daily P&L {daily_pnl_pct*100:.1f}%, {remaining_pct:.1f}% remaining",
        ))
    else:
        rules.append(RiskRuleResponse(
            rule="daily_loss_limit",
            status="OK",
            reason=f"Daily P&L {daily_pnl_pct*100:.1f}%, {remaining_pct:.1f}% remaining",
        ))

    # max_concurrent
    if open_positions_count >= rs.max_concurrent_positions:
        rules.append(RiskRuleResponse(
            rule="max_concurrent",
            status="BLOCKED",
            reason=f"{open_positions_count}/{rs.max_concurrent_positions} positions open",
        ))
    elif (
        open_positions_count >= rs.max_concurrent_positions - 1
        and rs.max_concurrent_positions >= 3
    ):
        rules.append(RiskRuleResponse(
            rule="max_concurrent",
            status="WARNING",
            reason=f"{open_positions_count}/{rs.max_concurrent_positions} positions open",
        ))
    else:
        rules.append(RiskRuleResponse(
            rule="max_concurrent",
            status="OK",
            reason=f"{open_positions_count}/{rs.max_concurrent_positions} positions open",
        ))

    # max_exposure
    exp_usage = exposure_pct / rs.max_exposure_pct if rs.max_exposure_pct else 0
    if exposure_pct > rs.max_exposure_pct:
        rules.append(RiskRuleResponse(
            rule="max_exposure",
            status="BLOCKED",
            reason=f"Exposure {exposure_pct*100:.0f}% exceeds {rs.max_exposure_pct*100:.0f}% limit",
        ))
    elif exp_usage > 0.8:
        rules.append(RiskRuleResponse(
            rule="max_exposure",
            status="WARNING",
            reason=f"Exposure {exposure_pct*100:.0f}% approaching {rs.max_exposure_pct*100:.0f}% limit",
        ))
    else:
        rules.append(RiskRuleResponse(
            rule="max_exposure",
            status="OK",
            reason=f"Exposure {exposure_pct*100:.0f}% of {rs.max_exposure_pct*100:.0f}% limit",
        ))

    # cooldown (omitted when not configured or not triggered)
    if rs.cooldown_after_loss_minutes and last_sl_hit_dt:
        elapsed = (datetime.now(timezone.utc) - last_sl_hit_dt).total_seconds()
        remaining = rs.cooldown_after_loss_minutes * 60 - elapsed
        if remaining > 0:
            mins_left = int(remaining // 60)
            rules.append(RiskRuleResponse(
                rule="cooldown",
                status="WARNING",
                reason=f"Cooldown active, {mins_left}min remaining",
            ))

    # 6. Overall status
    statuses = [r.status for r in rules]
    if "BLOCKED" in statuses:
        overall = "BLOCKED"
    elif "WARNING" in statuses:
        overall = "WARNING"
    else:
        overall = "OK"

    return RiskStatusResponse(
        settings=settings_dict,
        state=RiskStateResponse(
            equity=equity,
            daily_pnl_pct=daily_pnl_pct,
            open_positions_count=open_positions_count,
            total_exposure_usd=total_exposure_usd,
            exposure_pct=exposure_pct,
            last_sl_hit_at=last_sl_hit_dt.isoformat() if last_sl_hit_dt else None,
        ),
        rules=rules,
        overall_status=overall,
    )
```

- [ ] **Step 2: Verify the `and_` import is added**

The existing imports at `backend/app/api/risk.py:8` have `from sqlalchemy import select`. Change this to:

```python
from sqlalchemy import select, and_
```

No other import changes needed — `datetime` and `timezone` are already imported.

- [ ] **Step 3: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_risk_status.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 4: Run existing risk tests to confirm no regression**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_risk_guard.py -v`
Expected: All existing tests PASS.

---

### Task 3: Add `getRiskStatus()` to frontend API client

**Files:**
- Modify: `web/src/shared/lib/api.ts`

- [ ] **Step 1: Add `RiskStatus` and `RiskState` types**

Add these interfaces after the existing `RiskCheckResult` interface (around line 170 in `web/src/shared/lib/api.ts`):

```typescript
export interface RiskState {
  equity: number;
  daily_pnl_pct: number;
  open_positions_count: number;
  total_exposure_usd: number;
  exposure_pct: number;
  last_sl_hit_at: string | null;
}

export interface RiskStatus {
  settings: RiskSettings;
  state: RiskState;
  rules: RiskRule[];
  overall_status: "OK" | "WARNING" | "BLOCKED";
}
```

- [ ] **Step 2: Add `getRiskStatus` method**

Add this method to the `api` object, after the `checkRisk` method (around line 243):

```typescript
  getRiskStatus: () => request<RiskStatus>("/api/risk/status"),
```

- [ ] **Step 3: Verify build**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors.

---

### Task 4: Rewrite RiskPage — full component with all 7 sections

**Files:**
- Modify: `web/src/features/settings/components/RiskPage.tsx` (full rewrite)

This task rewrites the entire page: overall status indicator, refresh button, all 7 sections (Risk Per Trade, Daily Loss Limit, Max Positions, Max Exposure, Max Position Size, Max Risk Per Trade, Loss Cooldown) with progress bars and cooldown countdown timer.

- [ ] **Step 1: Write the full RiskPage component**

Replace the entire contents of `web/src/features/settings/components/RiskPage.tsx` with:

```tsx
import { useState, useEffect, useCallback } from "react";
import { Check, AlertTriangle, Lock, RefreshCw } from "lucide-react";
import { api, type RiskSettings, type RiskRule, type RiskState, type RiskStatus } from "../../../shared/lib/api";

type Status = "OK" | "WARNING" | "BLOCKED";

const STATUS_STYLES: Record<Status, { dot: string; text: string; icon: typeof Check }> = {
  OK: { dot: "text-long", text: "text-long", icon: Check },
  WARNING: { dot: "text-orange", text: "text-orange", icon: AlertTriangle },
  BLOCKED: { dot: "text-error", text: "text-error", icon: Lock },
};

function getRule(rules: RiskRule[], key: string): RiskRule | undefined {
  return rules.find((r) => r.rule === key);
}

function statusFor(rules: RiskRule[], key: string): Status {
  return (getRule(rules, key)?.status ?? "OK") as Status;
}

function StatusIcon({ status }: { status: Status }) {
  const style = STATUS_STYLES[status];
  const Icon = style.icon;
  return <Icon className={`w-3.5 h-3.5 ${style.dot}`} />;
}

export default function RiskPage() {
  const [data, setData] = useState<RiskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const result = await api.getRiskStatus();
      setData(result);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  async function update(field: string, value: number | null) {
    if (!data) return;
    const prev = data;
    setSaving(true);
    setSectionError(null);
    try {
      await api.updateRiskSettings({ [field]: value });
      const refreshed = await api.getRiskStatus();
      setData(refreshed);
    } catch {
      setData(prev);
      setSectionError(field);
    } finally {
      setSaving(false);
    }
  }

  if (loading && !data) {
    return (
      <div className="p-3 space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-28 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        ))}
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-3 flex flex-col items-center gap-3 pt-16">
        <p className="text-sm text-on-surface-variant">Failed to load risk status</p>
        <button
          onClick={fetchStatus}
          className="px-4 py-2 text-xs font-bold rounded-lg bg-primary/15 text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { settings, state, rules, overall_status } = data;
  const overallStyle = STATUS_STYLES[overall_status as Status];
  const OverallIcon = overallStyle.icon;
  const overallLabel = overall_status === "OK" ? "All Clear" : overall_status === "WARNING" ? "Warning" : "Blocked";

  return (
    <div className="p-3 space-y-3">
      {/* Overall status + refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2" role="status" aria-live="polite">
          <OverallIcon className={`w-4 h-4 ${overallStyle.dot}`} />
          <span className={`text-sm font-bold ${overallStyle.text}`}>{overallLabel}</span>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loading}
          className="p-2 rounded-lg text-on-surface-variant hover:text-on-surface transition-colors disabled:opacity-50"
          aria-label="Refresh risk status"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`} />
        </button>
      </div>

      {/* 1. Risk Per Trade */}
      <RiskSection title="Risk Per Trade" status={statusFor(rules, "_none_")}>
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface mb-3">
          {(settings.risk_per_trade * 100).toFixed(1)}%
        </div>
        <PresetButtons
          options={[
            { label: "0.5%", value: 0.005 },
            { label: "1%", value: 0.01 },
            { label: "2%", value: 0.02 },
          ]}
          current={settings.risk_per_trade}
          onSelect={(v) => update("risk_per_trade", v)}
          saving={saving}
        />
        {sectionError === "risk_per_trade" && <SectionError />}
      </RiskSection>

      {/* 2. Daily Loss Limit */}
      <DailyLossSection settings={settings} state={state} rules={rules} update={update} saving={saving} sectionError={sectionError} />

      {/* 3. Max Positions */}
      <RiskSection title="Max Positions" status={statusFor(rules, "max_concurrent")}>
        <div className="flex items-center justify-between mb-3">
          <span className={`font-headline text-2xl font-bold tabular-nums ${STATUS_STYLES[statusFor(rules, "max_concurrent")].text}`}>
            {state.open_positions_count} / {settings.max_concurrent_positions}
          </span>
        </div>
        <PresetButtons
          options={[
            { label: "2", value: 2 },
            { label: "3", value: 3 },
            { label: "5", value: 5 },
          ]}
          current={settings.max_concurrent_positions}
          onSelect={(v) => update("max_concurrent_positions", v)}
          saving={saving}
        />
        <RuleReason rules={rules} ruleKey="max_concurrent" />
        {sectionError === "max_concurrent_positions" && <SectionError />}
      </RiskSection>

      {/* 4. Max Exposure */}
      <MaxExposureSection settings={settings} state={state} rules={rules} update={update} saving={saving} sectionError={sectionError} />

      {/* 5. Max Position Size */}
      <RiskSection title="Max Position Size" status={statusFor(rules, "_none2_")}>
        <MaxPositionSizeInput
          value={settings.max_position_size_usd}
          onSave={(v) => update("max_position_size_usd", v)}
          saving={saving}
        />
        {sectionError === "max_position_size_usd" && <SectionError />}
      </RiskSection>

      {/* 6. Max Risk Per Trade */}
      <RiskSection title="Max Risk Per Trade" status={statusFor(rules, "_none3_")}>
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface mb-3">
          {(settings.max_risk_per_trade_pct * 100).toFixed(0)}%
        </div>
        <PresetButtons
          options={[
            { label: "1%", value: 0.01 },
            { label: "2%", value: 0.02 },
            { label: "5%", value: 0.05 },
          ]}
          current={settings.max_risk_per_trade_pct}
          onSelect={(v) => update("max_risk_per_trade_pct", v)}
          saving={saving}
        />
        {sectionError === "max_risk_per_trade_pct" && <SectionError />}
      </RiskSection>

      {/* 7. Loss Cooldown */}
      <CooldownSection settings={settings} state={state} rules={rules} update={update} saving={saving} sectionError={sectionError} />
    </div>
  );
}

/* ── Shared sub-components ── */

function RiskSection({ title, status, children }: { title: string; status: Status; children: React.ReactNode }) {
  return (
    <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <StatusIcon status={status} />
        <span className="text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">{title}</span>
      </div>
      {children}
    </section>
  );
}

function PresetButtons({ options, current, onSelect, saving, compare }: {
  options: { label: string; value: number }[];
  current: number;
  onSelect: (v: number) => void;
  saving: boolean;
  compare?: (a: number, b: number) => boolean;
}) {
  const isActive = compare ?? ((a: number, b: number) => Math.abs(a - b) < 0.0001);
  return (
    <div className="flex gap-2">
      {options.map((opt) => (
        <button
          key={opt.label}
          onClick={() => onSelect(opt.value)}
          disabled={saving}
          className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
            isActive(current, opt.value)
              ? "bg-primary/15 text-primary border border-primary/30"
              : "bg-surface-container-lowest text-on-surface-variant"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function RuleReason({ rules, ruleKey }: { rules: RiskRule[]; ruleKey: string }) {
  const rule = getRule(rules, ruleKey);
  if (!rule) return null;
  const style = STATUS_STYLES[rule.status as Status];
  return <p className={`text-[11px] mt-2 ${style.text}`}>{rule.reason}</p>;
}

function SectionError() {
  return <p className="text-[11px] mt-2 text-error">Update failed. Try again.</p>;
}

function MaxPositionSizeInput({ value, onSave, saving }: {
  value: number | null;
  onSave: (v: number | null) => void;
  saving: boolean;
}) {
  const [input, setInput] = useState(value != null ? String(value) : "");
  const [inputError, setInputError] = useState<string | null>(null);

  useEffect(() => {
    setInput(value != null ? String(value) : "");
  }, [value]);

  function handleSave() {
    const trimmed = input.trim();
    if (trimmed === "") {
      setInputError(null);
      onSave(null);
      return;
    }
    const num = parseFloat(trimmed);
    if (isNaN(num) || num <= 0) {
      setInputError("Must be a positive number");
      return;
    }
    setInputError(null);
    onSave(num);
  }

  return (
    <div>
      <label htmlFor="max-position-size" className="block text-xs font-bold text-on-surface-variant mb-1.5">
        Max Position Size
      </label>
      <div className="flex items-center gap-2">
        <input
          id="max-position-size"
          type="text"
          inputMode="decimal"
          value={input}
          onChange={(e) => { setInput(e.target.value); setInputError(null); }}
          onBlur={handleSave}
          onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
          disabled={saving}
          placeholder="Unlimited"
          className="flex-1 min-h-[44px] px-3 py-2 text-sm bg-surface-container-lowest border border-outline-variant/20 rounded-lg text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <span className="text-xs font-bold text-on-surface-variant">USD</span>
      </div>
      {inputError && <p className="text-[11px] mt-1 text-error">{inputError}</p>}
    </div>
  );
}

/* ── Sections with progress bars ── */

function DailyLossSection({ settings, state, rules, update, saving, sectionError }: {
  settings: RiskSettings; state: RiskState; rules: RiskRule[];
  update: (field: string, value: number | null) => void; saving: boolean; sectionError: string | null;
}) {
  const status = statusFor(rules, "daily_loss_limit");
  const style = STATUS_STYLES[status];
  const usagePct = settings.daily_loss_limit_pct > 0
    ? Math.min(Math.abs(state.daily_pnl_pct) / settings.daily_loss_limit_pct * 100, 100)
    : 0;
  const rule = getRule(rules, "daily_loss_limit");

  return (
    <RiskSection title="Daily Loss Limit" status={status}>
      <div className={`font-headline text-2xl font-bold tabular-nums mb-1 ${style.text}`}>
        {(state.daily_pnl_pct * 100).toFixed(1)}% / {(settings.daily_loss_limit_pct * 100).toFixed(0)}%
      </div>
      <div
        className="h-1.5 bg-surface-container-lowest rounded-full overflow-hidden mb-3"
        role="progressbar"
        aria-valuenow={Math.round(usagePct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={rule?.reason ?? "Daily loss limit"}
      >
        <div
          className={`h-full rounded-full transition-all ${
            status === "BLOCKED" ? "bg-error" : status === "WARNING" ? "bg-orange" : "bg-long"
          }`}
          style={{ width: `${usagePct}%` }}
        />
      </div>
      <PresetButtons
        options={[
          { label: "2%", value: 0.02 },
          { label: "3%", value: 0.03 },
          { label: "5%", value: 0.05 },
        ]}
        current={settings.daily_loss_limit_pct}
        onSelect={(v) => update("daily_loss_limit_pct", v)}
        saving={saving}
      />
      <RuleReason rules={rules} ruleKey="daily_loss_limit" />
      {sectionError === "daily_loss_limit_pct" && <SectionError />}
    </RiskSection>
  );
}

function MaxExposureSection({ settings, state, rules, update, saving, sectionError }: {
  settings: RiskSettings; state: RiskState; rules: RiskRule[];
  update: (field: string, value: number | null) => void; saving: boolean; sectionError: string | null;
}) {
  const status = statusFor(rules, "max_exposure");
  const style = STATUS_STYLES[status];
  const usagePct = settings.max_exposure_pct > 0
    ? Math.min(state.exposure_pct / settings.max_exposure_pct * 100, 100)
    : 0;
  const rule = getRule(rules, "max_exposure");

  return (
    <RiskSection title="Max Exposure" status={status}>
      <div className={`font-headline text-2xl font-bold tabular-nums mb-1 ${style.text}`}>
        {(state.exposure_pct * 100).toFixed(0)}% / {(settings.max_exposure_pct * 100).toFixed(0)}%
      </div>
      <div
        className="h-1.5 bg-surface-container-lowest rounded-full overflow-hidden mb-3"
        role="progressbar"
        aria-valuenow={Math.round(usagePct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={rule?.reason ?? "Max exposure"}
      >
        <div
          className={`h-full rounded-full transition-all ${
            status === "BLOCKED" ? "bg-error" : status === "WARNING" ? "bg-orange" : "bg-long"
          }`}
          style={{ width: `${usagePct}%` }}
        />
      </div>
      <PresetButtons
        options={[
          { label: "100%", value: 1.0 },
          { label: "150%", value: 1.5 },
          { label: "200%", value: 2.0 },
        ]}
        current={settings.max_exposure_pct}
        onSelect={(v) => update("max_exposure_pct", v)}
        saving={saving}
        compare={(a, b) => Math.abs(a - b) < 0.001}
      />
      <RuleReason rules={rules} ruleKey="max_exposure" />
      {sectionError === "max_exposure_pct" && <SectionError />}
    </RiskSection>
  );
}

function CooldownSection({ settings, state, rules, update, saving, sectionError }: {
  settings: RiskSettings; state: RiskState; rules: RiskRule[];
  update: (field: string, value: number | null) => void; saving: boolean; sectionError: string | null;
}) {
  const cooldownRule = getRule(rules, "cooldown");
  const isActive = !!cooldownRule;
  const status: Status = isActive ? "WARNING" : "OK";
  const style = STATUS_STYLES[status];

  // Compute remaining seconds for countdown
  const cooldownMinutes = settings.cooldown_after_loss_minutes;
  let initialRemaining = 0;
  if (cooldownMinutes && state.last_sl_hit_at) {
    const elapsed = (Date.now() - Date.parse(state.last_sl_hit_at)) / 1000;
    initialRemaining = Math.max(0, cooldownMinutes * 60 - elapsed);
  }

  const [remaining, setRemaining] = useState(initialRemaining);

  useEffect(() => {
    if (cooldownMinutes && state.last_sl_hit_at) {
      const elapsed = (Date.now() - Date.parse(state.last_sl_hit_at)) / 1000;
      setRemaining(Math.max(0, cooldownMinutes * 60 - elapsed));
    } else {
      setRemaining(0);
    }
  }, [cooldownMinutes, state.last_sl_hit_at]);

  const timerActive = remaining > 0;

  useEffect(() => {
    if (!timerActive) return;
    const id = setInterval(() => {
      setRemaining((r) => {
        const next = r - 1;
        return next <= 0 ? 0 : next;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [timerActive]);
  const displayStatus: Status = timerActive ? "WARNING" : "OK";
  const displayStyle = STATUS_STYLES[displayStatus];

  const mins = Math.floor(remaining / 60);
  const secs = Math.floor(remaining % 60);
  const timerText = timerActive
    ? `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : "Inactive";

  const progressPct = cooldownMinutes && cooldownMinutes > 0
    ? Math.min(remaining / (cooldownMinutes * 60) * 100, 100)
    : 0;
  const progressRule = cooldownRule ?? { reason: "Loss cooldown" };

  return (
    <RiskSection title="Loss Cooldown" status={displayStatus}>
      <div className="flex items-center gap-2 mb-1">
        {timerActive && (
          <span className="w-2 h-2 rounded-full bg-orange animate-pulse motion-reduce:animate-none" />
        )}
        <span className={`font-headline text-2xl font-bold tabular-nums ${displayStyle.text}`}>
          {timerText}
        </span>
      </div>
      {cooldownMinutes && (
        <div
          className="h-1.5 bg-surface-container-lowest rounded-full overflow-hidden mb-3"
          role="progressbar"
          aria-valuenow={Math.round(progressPct)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={progressRule.reason}
        >
          <div
            className={`h-full rounded-full transition-all ${timerActive ? "bg-orange" : "bg-long"}`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}
      <PresetButtons
        options={[
          { label: "Off", value: 0 },
          { label: "15m", value: 15 },
          { label: "30m", value: 30 },
          { label: "60m", value: 60 },
        ]}
        current={cooldownMinutes ?? 0}
        onSelect={(v) => update("cooldown_after_loss_minutes", v === 0 ? null : v)}
        saving={saving}
        compare={(a, b) => a === b}
      />
      {sectionError === "cooldown_after_loss_minutes" && <SectionError />}
    </RiskSection>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors.

- [ ] **Step 3: Verify dev server renders**

Run: `cd web && pnpm dev` (manual visual check — page should load with skeleton, then populated sections)

---

### Task 5: Final verification, full test run, and commit

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS, no regressions.

- [ ] **Step 2: Run frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds with zero errors.

- [ ] **Step 3: Final commit (if any fixups needed)**

```bash
git add -A
git commit -m "feat: risk management page redesign — live status, progress bars, cooldown timer"
```
