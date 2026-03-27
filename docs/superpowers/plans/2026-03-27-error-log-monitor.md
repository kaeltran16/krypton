# Error Log Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Structured JSON logging with error persistence to Postgres, a query API, and a standalone monitor HTML page.

**Architecture:** Replace Python's default log formatter with a JSON formatter across all environments. Add a custom logging handler that persists WARNING+ logs to an `error_log` table. Expose errors via a new API endpoint. Serve a standalone HTML monitor page through Nginx.

**Tech Stack:** Python logging, SQLAlchemy 2.0 async, FastAPI, vanilla HTML/JS

---

### File Structure

| File | Responsibility |
|------|----------------|
| New: `app/logging_config.py` | `JsonFormatter`, `DBErrorHandler`, `setup_logging()` |
| Modify: `app/main.py:9-12` | Replace `basicConfig` with `setup_logging()` call |
| Modify: `app/main.py:1358-1630` | Attach DB handler in lifespan, add cleanup task |
| Modify: `app/db/models.py` | New `ErrorLog` model |
| New: Alembic migration | `error_log` table |
| Modify: `app/api/system.py` | New `GET /api/system/errors` endpoint |
| Modify: `docker-compose.prod.yml` | Monitor volume mount on nginx |
| Modify: `nginx/nginx.conf` | `/monitor/` location block |
| New: `monitor/index.html` | Standalone monitoring page |
| New: `tests/test_logging.py` | Tests for formatter, handler, endpoint |

---

### Task 1: JSON Formatter

**Files:**
- Create: `backend/app/logging_config.py`
- Create: `backend/tests/test_logging.py`

- [ ] **Step 1: Write the failing test for JsonFormatter**

```python
# backend/tests/test_logging.py
import json
import logging

from app.logging_config import JsonFormatter


def test_json_formatter_basic():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.collector.onchain",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Tier 1 poll failed: timeout",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "ERROR"
    assert data["module"] == "app.collector.onchain"
    assert data["msg"] == "Tier 1 poll failed: timeout"
    assert "ts" in data


def test_json_formatter_extracts_pair():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.engine",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Processing BTC-USDT-SWAP candle",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["pair"] == "BTC-USDT-SWAP"


def test_json_formatter_no_pair():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.main",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Server starting",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "pair" not in data


def test_json_formatter_with_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.main",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Something failed",
        args=(),
        exc_info=exc_info,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert "traceback" in data
    assert "ValueError: test error" in data["traceback"]


def test_json_formatter_with_args():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.main",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="Failed for %s: %s",
        args=("BTC-USDT-SWAP", "timeout"),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["msg"] == "Failed for BTC-USDT-SWAP: timeout"
    assert data["pair"] == "BTC-USDT-SWAP"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/test_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.logging_config'`

- [ ] **Step 3: Implement JsonFormatter and setup_logging**

```python
# backend/app/logging_config.py
import json
import logging
import re
import traceback as tb_module
from datetime import datetime, timezone

_PAIR_RE = re.compile(r"\b([A-Z]{2,10}-USDT-SWAP)\b")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        entry: dict = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "module": record.name,
            "msg": message,
        }
        pair_match = _PAIR_RE.search(message)
        if pair_match:
            entry["pair"] = pair_match.group(1)
        if record.exc_info and record.exc_info[0] is not None:
            entry["traceback"] = "".join(tb_module.format_exception(*record.exc_info))
        return json.dumps(entry, default=str)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    level_name = __import__("os").environ.get("LOG_LEVEL", "INFO").upper()
    root.setLevel(logging.getLevelName(level_name))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/test_logging.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Wire setup_logging into main.py**

Replace lines 9-12 in `backend/app/main.py`:

```python
# old:
logging.basicConfig(
    level=logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO").upper()),
    format="%(levelname)s %(name)s: %(message)s",
)

# new:
from app.logging_config import setup_logging
setup_logging()
```

- [ ] **Step 6: Run existing tests to verify nothing broke**

Run: `docker exec krypton-api-1 python -m pytest -x -q`
Expected: All existing tests PASS

---

### Task 2: ErrorLog Model + Migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: Alembic migration

- [ ] **Step 1: Write the failing test for ErrorLog model**

Add to `backend/tests/test_logging.py`:

```python
from app.db.models import ErrorLog


def test_error_log_model_fields():
    row = ErrorLog(
        level="ERROR",
        module="app.collector.onchain",
        message="Tier 1 poll failed",
        traceback=None,
        pair="BTC-USDT-SWAP",
    )
    assert row.level == "ERROR"
    assert row.module == "app.collector.onchain"
    assert row.message == "Tier 1 poll failed"
    assert row.traceback is None
    assert row.pair == "BTC-USDT-SWAP"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/test_logging.py::test_error_log_model_fields -v`
Expected: FAIL with `ImportError: cannot import name 'ErrorLog'`

- [ ] **Step 3: Add ErrorLog model**

Append to the end of `backend/app/db/models.py`:

```python
class ErrorLog(Base):
    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    pair: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        Index("ix_error_log_timestamp", "timestamp"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/test_logging.py::test_error_log_model_fields -v`
Expected: PASS

- [ ] **Step 5: Generate Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add error_log table"`
Expected: New migration file created. Verify it contains `create_table('error_log', ...)` with the correct columns.

---

### Task 3: DBErrorHandler

**Files:**
- Modify: `backend/app/logging_config.py`
- Modify: `backend/tests/test_logging.py`

- [ ] **Step 1: Write the failing test for DBErrorHandler**

Add to `backend/tests/test_logging.py`:

```python
import asyncio
from unittest.mock import MagicMock, patch

from app.logging_config import DBErrorHandler


def test_db_handler_captures_error():
    mock_session_factory = MagicMock()
    handler = DBErrorHandler(session_factory=mock_session_factory)

    record = logging.LogRecord(
        name="app.collector.onchain",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="BTC-USDT-SWAP poll failed: timeout",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    assert len(handler._buffer) == 1
    entry = handler._buffer[0]
    assert entry["level"] == "ERROR"
    assert entry["module"] == "app.collector.onchain"
    assert entry["message"] == "BTC-USDT-SWAP poll failed: timeout"
    assert entry["pair"] == "BTC-USDT-SWAP"


def test_db_handler_ignores_info():
    mock_session_factory = MagicMock()
    handler = DBErrorHandler(session_factory=mock_session_factory)

    record = logging.LogRecord(
        name="app.main",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Server starting",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    assert len(handler._buffer) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/test_logging.py::test_db_handler_captures_error tests/test_logging.py::test_db_handler_ignores_info -v`
Expected: FAIL with `ImportError: cannot import name 'DBErrorHandler'`

- [ ] **Step 3: Implement DBErrorHandler**

Add to `backend/app/logging_config.py`:

```python
import asyncio
import threading
from app.db.models import ErrorLog


class DBErrorHandler(logging.Handler):
    """Buffers WARNING+ log records and flushes to the error_log table periodically."""

    FLUSH_INTERVAL = 5  # seconds
    MAX_BUFFER = 100

    def __init__(self, session_factory):
        super().__init__(level=logging.WARNING)
        self._session_factory = session_factory
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._flush_task: asyncio.Task | None = None

    def emit(self, record: logging.LogRecord):
        if record.levelno < logging.WARNING:
            return
        message = record.getMessage()
        pair_match = _PAIR_RE.search(message)
        entry = {
            "level": record.levelname,
            "module": record.name,
            "message": message,
            "traceback": (
                "".join(tb_module.format_exception(*record.exc_info))
                if record.exc_info and record.exc_info[0] is not None
                else None
            ),
            "pair": pair_match.group(1) if pair_match else None,
        }
        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self.MAX_BUFFER:
                self._schedule_flush()

    def _schedule_flush(self):
        try:
            loop = asyncio.get_running_loop()
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = loop.create_task(self._flush())
        except RuntimeError:
            pass  # no event loop running

    async def start_flush_loop(self):
        while True:
            await asyncio.sleep(self.FLUSH_INTERVAL)
            await self._flush()

    async def _flush(self):
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()
        try:
            async with self._session_factory() as session:
                for entry in batch:
                    session.add(ErrorLog(**entry))
                await session.commit()
        except Exception:
            import sys
            print(f"DBErrorHandler flush failed", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/test_logging.py -v`
Expected: All tests PASS

---

### Task 4: Wire DBErrorHandler + Cleanup into Lifespan

**Files:**
- Modify: `backend/app/main.py:1358-1630`

- [ ] **Step 1: Attach DBErrorHandler after DB is created in lifespan**

In `backend/app/main.py`, inside the `lifespan` function, after line 1366 (`app.state.db = db`), add:

```python
    from app.logging_config import DBErrorHandler
    db_log_handler = DBErrorHandler(session_factory=db.session_factory)
    logging.getLogger().addHandler(db_log_handler)
    db_log_flush_task = asyncio.create_task(db_log_handler.start_flush_loop())
```

- [ ] **Step 2: Add error log cleanup task**

In `backend/app/main.py`, after the alert cleanup loop (around line 1614), add:

```python
    async def error_log_cleanup_loop():
        while True:
            try:
                from app.db.models import ErrorLog
                async with db.session_factory() as session:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                    await session.execute(
                        ErrorLog.__table__.delete().where(ErrorLog.timestamp < cutoff)
                    )
                    # enforce hard cap of 10000 rows
                    count_result = await session.execute(
                        select(func.count()).select_from(ErrorLog)
                    )
                    total = count_result.scalar() or 0
                    if total > 10000:
                        excess = total - 10000
                        oldest = await session.execute(
                            select(ErrorLog.id)
                            .order_by(ErrorLog.timestamp)
                            .limit(excess)
                        )
                        ids_to_delete = [row[0] for row in oldest.all()]
                        if ids_to_delete:
                            await session.execute(
                                ErrorLog.__table__.delete().where(ErrorLog.id.in_(ids_to_delete))
                            )
                    await session.commit()
            except Exception as e:
                logger.error(f"Error log cleanup failed: {e}")
            await asyncio.sleep(3600)  # every hour

    error_log_cleanup_task = asyncio.create_task(error_log_cleanup_loop())
```

- [ ] **Step 3: Cancel tasks on shutdown**

In the shutdown section of `lifespan` (after line 1645 `watchdog_task.cancel()`), add:

```python
    db_log_flush_task.cancel()
    error_log_cleanup_task.cancel()
    logging.getLogger().removeHandler(db_log_handler)
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

Run: `docker exec krypton-api-1 python -m pytest -x -q`
Expected: All tests PASS

---

### Task 5: API Endpoint

**Files:**
- Modify: `backend/app/api/system.py`
- Modify: `backend/tests/api/test_system_health.py`

- [ ] **Step 1: Write the failing test for errors endpoint**

Add to `backend/tests/api/test_system_health.py`:

```python
@pytest.mark.asyncio
async def test_errors_returns_200(health_app, client, auth_cookies):
    resp = await client.get("/api/system/errors", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "errors" in data
    assert "total" in data
    assert "has_more" in data


@pytest.mark.asyncio
async def test_errors_requires_auth(client):
    resp = await client.get("/api/system/errors")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_system_health.py::test_errors_returns_200 tests/api/test_system_health.py::test_errors_requires_auth -v`
Expected: FAIL (404 or similar since endpoint doesn't exist)

- [ ] **Step 3: Implement the errors endpoint**

Add to `backend/app/api/system.py`:

```python
from app.db.models import ErrorLog

@router.get("/errors")
async def system_errors(
    request: Request,
    _user: dict = require_auth(),
    level: str | None = None,
    module: str | None = None,
    pair: str | None = None,
    limit: int = 50,
    offset: int = 0,
    since: str | None = None,
):
    db = request.app.state.db
    limit = min(limit, 200)

    query = select(ErrorLog).order_by(ErrorLog.timestamp.desc())
    count_query = select(func.count()).select_from(ErrorLog)

    if level:
        query = query.where(ErrorLog.level == level.upper())
        count_query = count_query.where(ErrorLog.level == level.upper())
    if module:
        query = query.where(ErrorLog.module.contains(module))
        count_query = count_query.where(ErrorLog.module.contains(module))
    if pair:
        query = query.where(ErrorLog.pair == pair)
        count_query = count_query.where(ErrorLog.pair == pair)
    if since:
        from datetime import datetime as dt
        try:
            since_dt = dt.fromisoformat(since.replace("Z", "+00:00"))
            query = query.where(ErrorLog.timestamp >= since_dt)
            count_query = count_query.where(ErrorLog.timestamp >= since_dt)
        except ValueError:
            pass

    query = query.offset(offset).limit(limit)

    try:
        async with db.session_factory() as session:
            result = await session.execute(query)
            rows = result.scalars().all()
            count_result = await session.execute(count_query)
            total = count_result.scalar() or 0
    except Exception:
        return {"errors": [], "total": 0, "has_more": False}

    return {
        "errors": [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "level": row.level,
                "module": row.module,
                "message": row.message,
                "traceback": row.traceback,
                "pair": row.pair,
            }
            for row in rows
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }
```

Also add `ErrorLog` to the imports at the top of `system.py` (line 9, alongside `Signal`):

```python
from app.db.models import Signal, ErrorLog
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_system_health.py -v`
Expected: All tests PASS (the mock DB will raise on execute, causing the except branch to return empty results, which is valid for the test assertions)

- [ ] **Step 5: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest -x -q`
Expected: All tests PASS

---

### Task 6: Monitor Page

**Files:**
- Create: `backend/monitor/index.html`

- [ ] **Step 1: Create the standalone HTML monitor page**

```html
<!-- backend/monitor/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Krypton Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: #0a0e17;
            color: #e1e5eb;
            min-height: 100vh;
        }
        .header {
            padding: 16px 24px;
            background: #111827;
            border-bottom: 1px solid #1f2937;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }
        .header h1 { font-size: 18px; color: #F0B90B; }
        .status-badge {
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .status-healthy { background: #064e3b; color: #0ECB81; }
        .status-degraded { background: #78350f; color: #F0B90B; }
        .status-unhealthy { background: #7f1d1d; color: #F6465D; }
        .login-bar {
            padding: 24px;
            display: flex;
            gap: 12px;
            align-items: center;
            justify-content: center;
        }
        .login-bar input {
            background: #1f2937;
            border: 1px solid #374151;
            color: #e1e5eb;
            padding: 8px 12px;
            border-radius: 6px;
            font-family: inherit;
            width: 360px;
        }
        .login-bar button, .filters button {
            background: #F0B90B;
            color: #0a0e17;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: bold;
            cursor: pointer;
        }
        .metrics {
            display: flex;
            gap: 16px;
            padding: 16px 24px;
            flex-wrap: wrap;
        }
        .metric-card {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 8px;
            padding: 12px 16px;
            min-width: 140px;
        }
        .metric-card .label { font-size: 11px; color: #6b7280; text-transform: uppercase; }
        .metric-card .value { font-size: 20px; font-weight: bold; margin-top: 4px; }
        .filters {
            padding: 12px 24px;
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
        }
        .filters select, .filters input {
            background: #1f2937;
            border: 1px solid #374151;
            color: #e1e5eb;
            padding: 6px 10px;
            border-radius: 6px;
            font-family: inherit;
            font-size: 13px;
        }
        .log-table {
            margin: 0 24px 24px;
            border: 1px solid #1f2937;
            border-radius: 8px;
            overflow: hidden;
        }
        table { width: 100%; border-collapse: collapse; }
        th {
            background: #111827;
            padding: 10px 12px;
            text-align: left;
            font-size: 11px;
            color: #6b7280;
            text-transform: uppercase;
            position: sticky;
            top: 0;
        }
        td {
            padding: 8px 12px;
            border-top: 1px solid #1f2937;
            font-size: 13px;
            vertical-align: top;
        }
        tr:hover { background: #111827; }
        tr.new-row { animation: highlight 2s ease-out; }
        @keyframes highlight {
            from { background: #1a2332; }
            to { background: transparent; }
        }
        .level-ERROR { color: #F6465D; }
        .level-WARNING { color: #F0B90B; }
        .level-CRITICAL { color: #ff4444; font-weight: bold; }
        .traceback-toggle {
            color: #6b7280;
            cursor: pointer;
            font-size: 12px;
            text-decoration: underline;
        }
        .traceback-content {
            display: none;
            white-space: pre-wrap;
            font-size: 11px;
            color: #9ca3af;
            margin-top: 6px;
            padding: 8px;
            background: #0d1117;
            border-radius: 4px;
            max-height: 200px;
            overflow-y: auto;
        }
        .pagination {
            padding: 12px 24px;
            display: flex;
            gap: 12px;
            align-items: center;
            justify-content: center;
        }
        .pagination button {
            background: #1f2937;
            color: #e1e5eb;
            border: 1px solid #374151;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
        }
        .pagination button:disabled { opacity: 0.4; cursor: default; }
        .empty { text-align: center; padding: 48px; color: #6b7280; }
        #app.hidden { display: none; }
    </style>
</head>
<body>
    <div id="login-screen">
        <div class="header">
            <h1>Krypton Monitor</h1>
        </div>
        <div class="login-bar">
            <input type="password" id="token-input" placeholder="Paste JWT token">
            <button onclick="doLogin()">Connect</button>
        </div>
    </div>

    <div id="app" class="hidden">
        <div class="header">
            <h1>Krypton Monitor</h1>
            <div>
                <span id="health-badge" class="status-badge">--</span>
                <span style="margin-left:12px;font-size:12px;color:#6b7280" id="last-update"></span>
            </div>
        </div>

        <div class="metrics" id="metrics-bar"></div>

        <div class="filters">
            <select id="filter-level">
                <option value="">All Levels</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
                <option value="CRITICAL">CRITICAL</option>
            </select>
            <input type="text" id="filter-module" placeholder="Module filter...">
            <select id="filter-pair">
                <option value="">All Pairs</option>
                <option value="BTC-USDT-SWAP">BTC-USDT-SWAP</option>
                <option value="ETH-USDT-SWAP">ETH-USDT-SWAP</option>
                <option value="WIF-USDT-SWAP">WIF-USDT-SWAP</option>
            </select>
            <button onclick="resetFilters()">Reset</button>
            <label style="font-size:12px;color:#6b7280;margin-left:auto">
                <input type="checkbox" id="auto-refresh" checked> Auto-refresh (10s)
            </label>
        </div>

        <div class="log-table">
            <table>
                <thead>
                    <tr>
                        <th style="width:170px">Timestamp</th>
                        <th style="width:80px">Level</th>
                        <th style="width:180px">Module</th>
                        <th style="width:110px">Pair</th>
                        <th>Message</th>
                    </tr>
                </thead>
                <tbody id="log-body"></tbody>
            </table>
        </div>
        <div id="empty-state" class="empty hidden">No errors found</div>

        <div class="pagination">
            <button id="btn-prev" onclick="prevPage()" disabled>&lt; Prev</button>
            <span id="page-info" style="font-size:13px;color:#6b7280"></span>
            <button id="btn-next" onclick="nextPage()" disabled>Next &gt;</button>
        </div>
    </div>

    <script>
        const API_BASE = window.location.origin;
        const PAGE_SIZE = 50;
        let token = '';
        let currentOffset = 0;
        let totalErrors = 0;
        let seenIds = new Set();
        let refreshTimer = null;

        function doLogin() {
            token = document.getElementById('token-input').value.trim();
            if (!token) return;
            sessionStorage.setItem('krypton_monitor_token', token);
            showApp();
        }

        function showApp() {
            document.getElementById('login-screen').classList.add('hidden');
            document.getElementById('app').classList.remove('hidden');
            fetchHealth();
            fetchErrors();
            startAutoRefresh();
        }

        function headers() {
            return { 'Cookie': 'krypton_token=' + token };
        }

        async function fetchHealth() {
            try {
                const resp = await fetch(API_BASE + '/api/system/health', {
                    credentials: 'include',
                    headers: headers(),
                });
                if (resp.status === 401) { logout(); return; }
                const data = await resp.json();

                const badge = document.getElementById('health-badge');
                badge.textContent = data.status;
                badge.className = 'status-badge status-' + data.status;

                const metrics = document.getElementById('metrics-bar');
                metrics.innerHTML = `
                    <div class="metric-card"><div class="label">Uptime</div><div class="value">${formatUptime(data.resources.uptime_seconds)}</div></div>
                    <div class="metric-card"><div class="label">Memory</div><div class="value">${data.resources.memory_mb || '--'}MB</div></div>
                    <div class="metric-card"><div class="label">Signals Today</div><div class="value">${data.pipeline.signals_today}</div></div>
                    <div class="metric-card"><div class="label">WS Clients</div><div class="value">${data.resources.ws_clients}</div></div>
                    <div class="metric-card"><div class="label">DB Pool</div><div class="value">${data.resources.db_pool_active}/${data.resources.db_pool_size}</div></div>
                    <div class="metric-card"><div class="label">Last Cycle</div><div class="value">${data.pipeline.last_cycle_seconds_ago != null ? data.pipeline.last_cycle_seconds_ago + 's' : '--'}</div></div>
                `;
                document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();
            } catch (e) {
                console.error('Health fetch failed:', e);
            }
        }

        async function fetchErrors() {
            const level = document.getElementById('filter-level').value;
            const module = document.getElementById('filter-module').value;
            const pair = document.getElementById('filter-pair').value;

            const params = new URLSearchParams();
            params.set('limit', PAGE_SIZE);
            params.set('offset', currentOffset);
            if (level) params.set('level', level);
            if (module) params.set('module', module);
            if (pair) params.set('pair', pair);

            try {
                const resp = await fetch(API_BASE + '/api/system/errors?' + params, {
                    credentials: 'include',
                    headers: headers(),
                });
                if (resp.status === 401) { logout(); return; }
                const data = await resp.json();
                totalErrors = data.total;
                renderErrors(data.errors);
                updatePagination(data.has_more);
            } catch (e) {
                console.error('Errors fetch failed:', e);
            }
        }

        function renderErrors(errors) {
            const tbody = document.getElementById('log-body');
            const empty = document.getElementById('empty-state');

            if (errors.length === 0) {
                tbody.innerHTML = '';
                empty.classList.remove('hidden');
                return;
            }
            empty.classList.add('hidden');

            tbody.innerHTML = errors.map(e => {
                const isNew = !seenIds.has(e.id);
                seenIds.add(e.id);
                const ts = e.timestamp ? new Date(e.timestamp).toLocaleString() : '--';
                const tbHtml = e.traceback
                    ? `<br><span class="traceback-toggle" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='block'?'none':'block'">traceback</span><div class="traceback-content">${escapeHtml(e.traceback)}</div>`
                    : '';
                return `<tr class="${isNew ? 'new-row' : ''}">
                    <td>${ts}</td>
                    <td class="level-${e.level}">${e.level}</td>
                    <td>${e.module}</td>
                    <td>${e.pair || '--'}</td>
                    <td>${escapeHtml(e.message)}${tbHtml}</td>
                </tr>`;
            }).join('');
        }

        function updatePagination(hasMore) {
            document.getElementById('btn-prev').disabled = currentOffset === 0;
            document.getElementById('btn-next').disabled = !hasMore;
            const page = Math.floor(currentOffset / PAGE_SIZE) + 1;
            const totalPages = Math.max(1, Math.ceil(totalErrors / PAGE_SIZE));
            document.getElementById('page-info').textContent = `Page ${page} of ${totalPages} (${totalErrors} total)`;
        }

        function prevPage() { currentOffset = Math.max(0, currentOffset - PAGE_SIZE); fetchErrors(); }
        function nextPage() { currentOffset += PAGE_SIZE; fetchErrors(); }

        function resetFilters() {
            document.getElementById('filter-level').value = '';
            document.getElementById('filter-module').value = '';
            document.getElementById('filter-pair').value = '';
            currentOffset = 0;
            fetchErrors();
        }

        function startAutoRefresh() {
            stopAutoRefresh();
            refreshTimer = setInterval(() => {
                if (document.getElementById('auto-refresh').checked) {
                    fetchHealth();
                    fetchErrors();
                }
            }, 10000);
        }
        function stopAutoRefresh() { if (refreshTimer) clearInterval(refreshTimer); }

        function logout() {
            sessionStorage.removeItem('krypton_monitor_token');
            token = '';
            stopAutoRefresh();
            document.getElementById('app').classList.add('hidden');
            document.getElementById('login-screen').classList.remove('hidden');
        }

        function formatUptime(seconds) {
            if (seconds == null) return '--';
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            return h > 0 ? h + 'h ' + m + 'm' : m + 'm';
        }

        function escapeHtml(str) {
            const d = document.createElement('div');
            d.textContent = str;
            return d.innerHTML;
        }

        // Filter change listeners
        document.getElementById('filter-level').addEventListener('change', () => { currentOffset = 0; fetchErrors(); });
        document.getElementById('filter-module').addEventListener('input', debounce(() => { currentOffset = 0; fetchErrors(); }, 500));
        document.getElementById('filter-pair').addEventListener('change', () => { currentOffset = 0; fetchErrors(); });

        function debounce(fn, ms) {
            let timer;
            return function(...args) { clearTimeout(timer); timer = setTimeout(() => fn.apply(this, args), ms); };
        }

        // Auto-login from session
        const savedToken = sessionStorage.getItem('krypton_monitor_token');
        if (savedToken) { token = savedToken; showApp(); }
    </script>
</body>
</html>
```

- [ ] **Step 2: Verify the file is valid HTML**

Open `backend/monitor/index.html` in a browser locally to confirm it renders (login screen should appear). No backend needed for this check.

---

### Task 7: Nginx + Docker Compose Config

**Files:**
- Modify: `backend/nginx/nginx.conf`
- Modify: `backend/docker-compose.prod.yml`

- [ ] **Step 1: Add /monitor/ location to nginx.conf**

In `backend/nginx/nginx.conf`, inside the HTTPS server block (after the main `location /` block, before the closing `}`), add:

```nginx
        # --- Monitor page (standalone) ---
        location /monitor/ {
            alias /var/www/monitor/;
            index index.html;
        }
```

- [ ] **Step 2: Add monitor volume mount to docker-compose.prod.yml**

In `backend/docker-compose.prod.yml`, add to the nginx service's volumes:

```yaml
      - ./monitor:/var/www/monitor:ro
```

So the nginx volumes section becomes:

```yaml
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - certbot-etc:/etc/letsencrypt:ro
      - certbot-var:/var/lib/letsencrypt
      - certbot-webroot:/var/www/certbot:ro
      - ./monitor:/var/www/monitor:ro
```

- [ ] **Step 3: Verify docker-compose.prod.yml is valid**

Run: `cd backend && docker compose -f docker-compose.prod.yml config --quiet`
Expected: No errors (exits silently)

---

### Task 8: Update Spec for Accuracy

**Files:**
- Modify: `docs/superpowers/specs/2026-03-27-error-log-monitor-design.md`

- [ ] **Step 1: Update spec to reflect final decisions**

Update the spec to remove references to `LOG_FORMAT` env var toggle. JSON logging is now unconditional across all environments. Remove section about `LOG_FORMAT=text` for dev and `LOG_FORMAT=json` in docker-compose.prod.yml environment. Also update auth references from `X-API-Key` to JWT.

---

### Task 9: Final Integration Test

- [ ] **Step 1: Run the full test suite**

Run: `docker exec krypton-api-1 python -m pytest -x -q`
Expected: All tests PASS

- [ ] **Step 2: Verify JSON log output**

Run: `docker exec krypton-api-1 python -c "import logging; from app.logging_config import setup_logging; setup_logging(); logging.getLogger('test').error('BTC-USDT-SWAP poll failed')"`
Expected: JSON line on stdout like `{"ts": "...", "level": "ERROR", "module": "test", "msg": "BTC-USDT-SWAP poll failed", "pair": "BTC-USDT-SWAP"}`
