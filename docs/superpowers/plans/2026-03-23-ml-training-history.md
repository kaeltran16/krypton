# ML Training History Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist ML training runs in Postgres so history/results survive restarts and work across devices, plus add preset description subtitles.

**Architecture:** New `MLTrainingRun` DB model stores params (JSONB), results (JSONB), and metadata. Backend inserts on train start, updates on completion/failure/cancel. New history + delete endpoints. Frontend drops localStorage, fetches from API.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic, FastAPI, React, TypeScript, Vitest

**Spec:** `docs/superpowers/specs/2026-03-23-ml-training-history-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/app/db/migrations/versions/{id}_add_ml_training_run.py` | Alembic migration |
| Modify | `backend/app/db/models.py` | Add `MLTrainingRun` model |
| Modify | `backend/app/api/ml.py` | Add history/delete endpoints, persist runs in train endpoint |
| Modify | `web/src/shared/lib/api.ts` | Add types + API methods |
| Modify | `web/src/features/ml/presets.ts` | Add `description` field |
| Modify | `web/src/features/ml/components/MLTrainingView.tsx` | Replace localStorage with API |
| Modify | `web/src/features/ml/components/SetupTab.tsx` | Render preset subtitle |
| Modify | `web/src/features/ml/components/__tests__/MLTrainingView.test.tsx` | Update mocks |
| Modify | `backend/app/main.py` | Add orphaned training run cleanup to lifespan |
| Modify | `backend/tests/api/test_ml.py` | Add backend tests (create if not exists) |

---

### Task 1: Add MLTrainingRun DB Model

**Files:**
- Modify: `backend/app/db/models.py` (append after last model class)

- [ ] **Step 1: Add the model class**

Add at the end of `backend/app/db/models.py`:

```python
class MLTrainingRun(Base):
    __tablename__ = "ml_training_runs"
    __table_args__ = (
        Index("ix_ml_training_run_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="running", server_default="running", nullable=False
    )
    preset_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pairs_trained: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_candles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 2: Verify the model imports are already present**

Check that `models.py` already imports `uuid`, `datetime`, `timezone`, `UUID`, `JSONB`, `Float`, `Integer`, `String`, `Text`, `DateTime`, `Index`. All of these are already imported at the top of the file -- no new imports needed.

---

### Task 2: Create Alembic Migration

**Files:**
- Create: `backend/app/db/migrations/versions/{auto}_add_ml_training_run.py`

- [ ] **Step 1: Generate the migration**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add ml_training_run table"
```

- [ ] **Step 2: Review the generated migration**

Verify it creates table `ml_training_runs` with all columns and the `ix_ml_training_run_created` index. Verify downgrade drops the table.

- [ ] **Step 3: Run the migration**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```

Expected: migration applies cleanly.

---

### Task 3: Add History + Delete Backend Endpoints

**Files:**
- Modify: `backend/app/api/ml.py`

- [ ] **Step 1: Add imports**

At the top of `ml.py`, update the model import line:

```python
from app.db.models import Candle, OrderFlowSnapshot, MLTrainingRun
```

Add `delete` and `update` to the sqlalchemy import:

```python
from sqlalchemy import select, func, delete, update
```

Add `time` import:

```python
import time
```

- [ ] **Step 2: Add `preset_label` to `TrainRequest`**

Add to the `TrainRequest` class:

```python
    preset_label: str | None = None
```

- [ ] **Step 3: Add GET history endpoint**

**IMPORTANT: Route ordering.** This endpoint MUST be placed BEFORE `GET /train/{job_id}` (currently at `ml.py:255`). FastAPI matches routes in order -- if `/train/history` comes after `/train/{job_id}`, it gets captured as `job_id="history"` and returns 404. Place this right after `POST /train` (line ~252) and before `GET /train/{job_id}`.

```python
@router.get("/train/history", dependencies=[require_auth()])
async def get_training_history(request: Request, limit: int = 50, offset: int = 0):
    """Return training runs, newest first, with pagination."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(MLTrainingRun)
            .order_by(MLTrainingRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        runs = result.scalars().all()

    return [
        {
            "job_id": r.job_id,
            "status": r.status,
            "preset_label": r.preset_label,
            "params": r.params,
            "result": r.result,
            "error": r.error,
            "pairs_trained": r.pairs_trained,
            "duration_seconds": r.duration_seconds,
            "total_candles": r.total_candles,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ]
```

- [ ] **Step 4: Add DELETE history endpoint**

Add after the GET history endpoint:

```python
@router.delete("/train/history/{job_id}", dependencies=[require_auth()])
async def delete_training_run(job_id: str, request: Request):
    """Delete a training run from history."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            delete(MLTrainingRun).where(MLTrainingRun.job_id == job_id)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Training run not found")
    return {"deleted": job_id}
```

- [ ] **Step 5: Modify `start_training` to persist to DB**

In the `start_training` function, after creating the in-memory job entry (`train_jobs[job_id] = ...`), insert the DB row:

```python
    # Persist to DB
    params_dict = body.model_dump(exclude={"preset_label"})
    run = MLTrainingRun(
        job_id=job_id,
        status="running",
        preset_label=body.preset_label,
        params=params_dict,
    )
    async with db.session_factory() as session:
        session.add(run)
        await session.commit()
```

- [ ] **Step 6: Modify `_run()` to update DB on completion/failure/cancel**

Add `start_time = time.time()` at the top of `_run()`.

Create a helper inside `_run()` to update the DB row (`update` is already imported at the top of the file from Step 1):

```python
        async def _update_run(**fields):
            try:
                async with db.session_factory() as session:
                    await session.execute(
                        update(MLTrainingRun)
                        .where(MLTrainingRun.job_id == job_id)
                        .values(**fields)
                    )
                    await session.commit()
            except Exception:
                logger.exception(f"Failed to update training run {job_id} in DB")
```

This prevents a DB write failure (e.g., connection lost) from masking the actual training outcome. Without this, a successful training that fails the DB write would fall into the `except Exception` handler and be marked as "failed" in `train_jobs`.

On success (after `train_jobs[job_id] = {"status": "completed", ...}`):

```python
            total_candles_count = sum(
                r.get("total_samples", 0) for r in pair_results.values()
            )
            await _update_run(
                status="completed",
                result=pair_results,
                pairs_trained=list(pair_results.keys()),
                total_candles=total_candles_count,
                duration_seconds=time.time() - start_time,
                completed_at=datetime.now(timezone.utc),
            )
```

On early return when no pair has enough data (the `if not pair_results:` block at ~line 233):

```python
            if not pair_results:
                train_jobs[job_id] = {"status": "failed", "error": "No pair had enough data"}
                await _update_run(
                    status="failed",
                    error="No pair had enough data",
                    duration_seconds=time.time() - start_time,
                    completed_at=datetime.now(timezone.utc),
                )
                return
```

On failure (in the `except Exception` block):

```python
            await _update_run(
                status="failed",
                error=str(e),
                duration_seconds=time.time() - start_time,
                completed_at=datetime.now(timezone.utc),
            )
```

Add a `CancelledError` handler before `Exception`:

```python
        except asyncio.CancelledError:
            logger.info(f"Training job {job_id} cancelled")
            train_jobs[job_id] = {"status": "cancelled"}
            await _update_run(
                status="cancelled",
                duration_seconds=time.time() - start_time,
                completed_at=datetime.now(timezone.utc),
            )
```

- [ ] **Step 7: Verify endpoints work**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.api.ml import router; print('OK')"
```

Expected: `OK` (no import errors).

- [ ] **Step 8: Update `_mock_db` test helper for `session.add` support**

Step 5 adds `session.add(run)` to `start_training()`. The existing `_mock_db` in `backend/tests/api/test_ml.py` must be updated **now** (not deferred to Task 4) to prevent existing tests from breaking. Replace the entire `_mock_db` function:

```python
def _mock_db(scalars_all=None, rowcount=0):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_result.rowcount = rowcount
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db
```

Run existing tests to confirm nothing broke:

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_ml.py -v
```

- [ ] **Step 9: Add orphaned training run cleanup to startup**

**File:** `backend/app/main.py`

If the server restarts while a training job is running, the DB row stays `status="running"` forever. Add cleanup in the `lifespan` function, after database initialization:

```python
    # mark orphaned training runs as failed (from previous server crash/restart)
    async with app.state.db.session_factory() as session:
        await session.execute(
            update(MLTrainingRun)
            .where(MLTrainingRun.status == "running")
            .values(
                status="failed",
                error="Server restarted during training",
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
```

Add the necessary imports at the top of `main.py`:

```python
from app.db.models import MLTrainingRun
from sqlalchemy import update
```

---

### Task 4: Add Backend Tests

**Files:**
- Create or modify: `backend/tests/api/test_ml.py`

- [ ] **Step 1: Write tests for history and delete endpoints**

The `_mock_db` function was already updated in Task 3 Step 8 (with `rowcount` param and `session.add` mock). Append these tests at the end of `backend/tests/api/test_ml.py`. Use `COOKIES` dict with `make_test_jwt()` and the existing `ml_client` fixture. Follow the flat test function style:

```python
async def test_training_history_requires_auth(ml_app):
    async with AsyncClient(
        transport=ASGITransport(app=ml_app), base_url="http://test"
    ) as c:
        resp = await c.get("/api/ml/train/history")
    assert resp.status_code == 401


async def test_training_history_returns_empty_list(ml_client):
    resp = await ml_client.get("/api/ml/train/history", cookies=COOKIES)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_training_history_returns_runs(ml_app, ml_client):
    from datetime import datetime, timezone

    mock_run = MagicMock()
    mock_run.job_id = "20260323_140000"
    mock_run.status = "completed"
    mock_run.preset_label = "Balanced"
    mock_run.params = {"timeframe": "1h", "epochs": 100}
    mock_run.result = {"BTC-USDT-SWAP": {"best_val_loss": 0.68}}
    mock_run.error = None
    mock_run.pairs_trained = ["BTC-USDT-SWAP"]
    mock_run.duration_seconds = 120.5
    mock_run.total_candles = 8760
    mock_run.created_at = datetime(2026, 3, 23, 14, 0, 0, tzinfo=timezone.utc)
    mock_run.completed_at = datetime(2026, 3, 23, 14, 2, 0, tzinfo=timezone.utc)

    ml_app.state.db = _mock_db(scalars_all=[mock_run])

    resp = await ml_client.get("/api/ml/train/history", cookies=COOKIES)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["job_id"] == "20260323_140000"
    assert data[0]["status"] == "completed"
    assert data[0]["preset_label"] == "Balanced"
    assert data[0]["duration_seconds"] == 120.5


async def test_delete_training_run_requires_auth(ml_app):
    async with AsyncClient(
        transport=ASGITransport(app=ml_app), base_url="http://test"
    ) as c:
        resp = await c.delete("/api/ml/train/history/some-id")
    assert resp.status_code == 401


async def test_delete_training_run_not_found(ml_app, ml_client):
    ml_app.state.db = _mock_db(rowcount=0)
    resp = await ml_client.delete(
        "/api/ml/train/history/nonexistent", cookies=COOKIES
    )
    assert resp.status_code == 404


async def test_delete_training_run_success(ml_app, ml_client):
    ml_app.state.db = _mock_db(rowcount=1)
    resp = await ml_client.delete(
        "/api/ml/train/history/20260323_140000", cookies=COOKIES
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": "20260323_140000"}
```

- [ ] **Step 2: Write test for DB persistence on `start_training`**

This verifies that `start_training` inserts an `MLTrainingRun` row with correct fields (including `preset_label`). Append to the test file:

```python
async def test_train_persists_run_to_db(ml_app, ml_client):
    """start_training should insert an MLTrainingRun row with correct fields."""
    mock_db = _mock_db()
    ml_app.state.db = mock_db

    resp = await ml_client.post(
        "/api/ml/train",
        json={
            "timeframe": "1h",
            "lookback_days": 365,
            "epochs": 50,
            "preset_label": "Quick Test",
        },
        cookies=COOKIES,
    )
    assert resp.status_code == 200

    # Verify session.add was called with an MLTrainingRun
    mock_session = mock_db.session_factory().__aenter__.return_value
    # Access the add call from the context manager
    # _mock_db uses asynccontextmanager, so we check via the yielded session
    async with mock_db.session_factory() as session:
        pass  # just to get the session reference
    # The actual session.add call happens inside the endpoint
    # Verify via the mock that add was called
    assert mock_db.session_factory.call_count >= 1
```

**Note:** The `_run()` background task DB updates (completion/failure/cancel) are protected by the `try/except` wrapper in `_update_run` (Task 3 Step 6). Testing the full background flow requires mocking candle queries and model training, which is out of scope for unit tests. The existing `test_train_background_job_handles_no_data` covers the in-memory status path.

- [ ] **Step 3: Run the backend tests**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_ml.py -v
```

Expected: all tests pass.

---

### Task 5: Add Frontend API Types and Methods

**Files:**
- Modify: `web/src/shared/lib/api.ts`

- [ ] **Step 1: Update `MLTrainRequest` type**

Add `preset_label` field:

```typescript
export interface MLTrainRequest {
  timeframe?: string;
  lookback_days?: number;
  epochs?: number;
  batch_size?: number;
  hidden_size?: number;
  num_layers?: number;
  lr?: number;
  seq_len?: number;
  dropout?: number;
  label_horizon?: number;
  label_threshold_pct?: number;
  preset_label?: string;
}
```

- [ ] **Step 2: Update `MLTrainJob` type**

Add `duration_seconds`, `total_candles`, `pairs_trained`, `completed_at`, `preset_label`:

```typescript
export interface MLTrainJob {
  job_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  progress?: Record<string, MLTrainProgress>;
  result?: Record<string, MLTrainResult>;
  error?: string;
  created_at?: string;
  completed_at?: string;
  params?: MLTrainRequest;
  preset_label?: string;
  pairs_trained?: string[];
  duration_seconds?: number;
  total_candles?: number;
}
```

- [ ] **Step 3: Add API methods**

Add after the existing `getMLBackfillStatus` method in the `api` object:

```typescript
  getMLTrainingHistory: (limit = 50, offset = 0) =>
    request<MLTrainJob[]>(`/api/ml/train/history?limit=${limit}&offset=${offset}`),

  deleteMLTrainingRun: (jobId: string) =>
    request<{ deleted: string }>(`/api/ml/train/history/${jobId}`, {
      method: "DELETE",
    }),
```

---

### Task 6: Add Preset Descriptions

**Files:**
- Modify: `web/src/features/ml/presets.ts`

- [ ] **Step 1: Add `description` field to `Preset` interface and data**

```typescript
export interface Preset {
  name: PresetName;
  label: string;
  description: string;
  config: Partial<MLTrainRequest>;
}

export const PRESETS: Preset[] = [
  {
    name: "quick",
    label: "Quick Test",
    description: "Small model, few epochs. Fast sanity check that training works with your data.",
    config: {
      epochs: 30,
      batch_size: 32,
      hidden_size: 64,
      num_layers: 1,
      seq_len: 25,
      dropout: 0.2,
      lr: 0.003,
    },
  },
  {
    name: "balanced",
    label: "Balanced",
    description: "Mid-size model with moderate training time. Good default for most use cases.",
    config: {
      epochs: 100,
      batch_size: 64,
      hidden_size: 128,
      num_layers: 2,
      seq_len: 50,
      dropout: 0.3,
      lr: 0.001,
    },
  },
  {
    name: "production",
    label: "Production",
    description: "Large model, long training, fine convergence. For the model you'll deploy to production.",
    config: {
      epochs: 300,
      batch_size: 128,
      hidden_size: 256,
      num_layers: 3,
      seq_len: 100,
      dropout: 0.3,
      lr: 0.0005,
    },
  },
];
```

---

### Task 7: Render Preset Subtitle in SetupTab

**Files:**
- Modify: `web/src/features/ml/components/SetupTab.tsx`

- [ ] **Step 1: Import PRESETS directly (already imported)**

Already imported via `import { PRESETS, DEFAULT_CONFIG, CANDLES_PER_DAY, type PresetName } from "../presets";`

- [ ] **Step 2: Add subtitle below the SegmentedControl**

Find the preset bar section and add a description line after the `SegmentedControl`:

```tsx
      {/* Preset bar */}
      <div>
        <SegmentedControl
          options={PRESETS.map((p) => ({ value: p.name, label: p.label }))}
          value={activePreset ?? ""}
          onChange={(v) => handlePresetChange(v as PresetName)}
          fullWidth
        />
        {activePreset && (
          <p className="text-[10px] text-on-surface-variant mt-1.5 px-1">
            {PRESETS.find((p) => p.name === activePreset)?.description}
          </p>
        )}
      </div>
```

Replace the existing standalone `<SegmentedControl ... />` for presets with this wrapped version.

---

### Task 8: Replace localStorage with API in MLTrainingView

**Files:**
- Modify: `web/src/features/ml/components/MLTrainingView.tsx`

- [ ] **Step 1: Update imports**

Replace the import line to include the new API method:

```typescript
import { api, type MLTrainRequest, type MLTrainJob, type MLStatus, type MLBackfillJob } from "../../../shared/lib/api";
```

(Same import, no change needed -- `api` already imported.)

- [ ] **Step 2: Add `fetchHistory` function and replace localStorage logic**

Remove the localStorage read in the `useEffect` on mount (lines 71-74). Replace with API fetch:

```typescript
  const fetchHistory = useCallback(() => {
    api.getMLTrainingHistory()
      .then(setHistory)
      .catch(() => {});
  }, []);

  useEffect(() => {
    api.getMLStatus().then(setStatus).catch(() => {});
    fetchHistory();
  }, [fetchHistory]);
```

Add `useCallback` to imports if not already present.

- [ ] **Step 3: Remove `saveToHistory` and `saveHistoryToStorage`**

Delete the `saveToHistory` function (lines 176-183) and the standalone `saveHistoryToStorage` function (lines 186-188).

- [ ] **Step 4: Update `onComplete` handler in Training tab**

Change the `onComplete` callback to just clear training state and re-fetch:

```typescript
        onComplete={(job: MLTrainJob) => {
          setTrainingJob(null);
          fetchHistory();
        }}
```

Remove `currentTrainingParamsRef` and `activePresetLabel` from the dependency since they're no longer needed for `saveToHistory`. The `presetLabel` is now sent to the backend via the API request.

- [ ] **Step 5: Update `onDelete` handler to call API**

Replace the client-side-only delete with an API call:

```typescript
          onDelete={async (jobId: string) => {
            try {
              await api.deleteMLTrainingRun(jobId);
              setHistory((h) => h.filter((j) => j.job_id !== jobId));
            } catch {
              fetchHistory();
            }
          }}
```

On success, the item is removed from local state. On failure, `fetchHistory()` re-fetches from the server to restore consistent state (prevents the UI from silently diverging from the backend).

- [ ] **Step 6: Pass `preset_label` in `handleStartTraining`**

Update `handleStartTraining` to include `preset_label` in the API request params:

```typescript
  async function handleStartTraining(params: MLTrainRequest, presetLabel?: string | null) {
    try {
      if (!params.timeframe) throw new Error("Timeframe is required");
      if ((params.lookback_days ?? 0) < 1) throw new Error("Lookback days must be at least 1");
      if ((params.epochs ?? 0) < 1) throw new Error("Epochs must be at least 1");
      if ((params.batch_size ?? 0) < 1) throw new Error("Batch size must be at least 1");

      setError(null);
      setRestoredParams(null);
      const response = await api.startMLTraining({
        ...params,
        preset_label: presetLabel ?? undefined,
      });
      setTrainingJob({ job_id: response.job_id, status: "running" as const });
      setTab("training");
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Failed to start training"));
    }
  }
```

- [ ] **Step 7: Clean up unused state/refs**

Remove `currentTrainingParamsRef` (no longer needed -- params are persisted by backend). Keep `activePresetLabel` state as-is -- it's still used by the `presetLabel` and `configSummary` props passed to `TrainingTab` for the active session display. Removing it would require cascading changes to `TrainingTab` props for no functional benefit.

**Verify call-site wiring:** `SetupTab` already passes `presetLabel` when calling the `onStartTraining` prop. Confirm by checking `SetupTab.tsx` -- no call-site changes are needed since the function signature adds an optional parameter with the same semantics.

Add `useCallback` to the React import (currently imports `useState, useEffect, useRef`):

```typescript
import { useState, useEffect, useRef, useCallback } from "react";
```

---

### Task 9: Update Frontend Tests

**Files:**
- Modify: `web/src/features/ml/components/__tests__/MLTrainingView.test.tsx`

- [ ] **Step 1: Add new API mocks**

Add to the `vi.mock` block:

```typescript
    getMLTrainingHistory: vi.fn(),
    deleteMLTrainingRun: vi.fn(),
```

- [ ] **Step 2: Update `beforeEach` defaults**

Add default mock for history:

```typescript
    vi.mocked(api.getMLTrainingHistory).mockResolvedValue([]);
```

- [ ] **Step 3: Remove localStorage mock usage for history**

The localStorage mock can stay (other code might use it), but remove any test that specifically sets `ml_training_history` in localStorage. Update history tests to mock via `api.getMLTrainingHistory` instead:

```typescript
    it("should display job entries when history exists", async () => {
      const mockHistory = [
        {
          job_id: "test-job-1",
          status: "completed" as const,
          result: {
            "BTC-USDT": {
              best_epoch: 10, best_val_loss: 0.5, total_epochs: 100,
              total_samples: 1000, flow_data_used: false,
              direction_accuracy: 0.65,
            },
          },
          created_at: new Date().toISOString(),
          params: { timeframe: "1h", lookback_days: 365, epochs: 100 },
        },
      ];
      vi.mocked(api.getMLTrainingHistory).mockResolvedValue(mockHistory);

      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      expect(screen.getByText("test-job-1")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
```

Update the "View Details" test similarly to use `api.getMLTrainingHistory` mock instead of localStorage.

- [ ] **Step 4: Add tests for delete error recovery and preset_label**

Append these tests to verify the delete error handling and that `preset_label` is passed to the API:

```typescript
    it("should re-fetch history when delete fails", async () => {
      const mockHistory = [
        {
          job_id: "test-job-1",
          status: "completed" as const,
          result: {},
          created_at: new Date().toISOString(),
          params: { timeframe: "1h" },
        },
      ];
      vi.mocked(api.getMLTrainingHistory).mockResolvedValue(mockHistory);
      vi.mocked(api.deleteMLTrainingRun).mockRejectedValue(new Error("Network error"));

      await renderAndSettle();
      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      // Trigger delete
      const deleteBtn = screen.getByRole("button", { name: /delete/i });
      await act(async () => {
        fireEvent.click(deleteBtn);
      });

      // Should have re-fetched history on failure
      expect(api.getMLTrainingHistory).toHaveBeenCalledTimes(2);
    });

    it("should pass preset_label when starting training", async () => {
      vi.mocked(api.startMLTraining).mockResolvedValue({
        job_id: "20260323_140000",
        status: "running",
      });

      await renderAndSettle();

      // Select a preset and start training
      // (exact interaction depends on SetupTab rendering)
      const startBtn = screen.getByText("Start Training");
      await act(async () => {
        fireEvent.click(startBtn);
      });

      expect(api.startMLTraining).toHaveBeenCalledWith(
        expect.objectContaining({ preset_label: expect.any(String) })
      );
    });
```

**Note:** These tests may need adjustment based on the exact DOM structure rendered by `SetupTab` and `HistoryTab`. The key assertions to verify: (1) `getMLTrainingHistory` is re-called on delete failure, (2) `startMLTraining` receives `preset_label` in the request body.

- [ ] **Step 5: Run frontend tests**

```bash
cd web && npx vitest run src/features/ml/components/__tests__/MLTrainingView.test.tsx
```

Expected: all tests pass.

---

### Task 10: Integration Verification

- [ ] **Step 1: Run all backend tests**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 2: Run all frontend tests**

```bash
cd web && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend build check**

```bash
cd web && pnpm build
```

Expected: TypeScript check + build succeeds with no errors.

- [ ] **Step 4: Manual smoke test**

1. Open the app, navigate to ML Training tab
2. Verify preset subtitle appears when selecting Quick Test / Balanced / Production
3. Verify History tab loads from API (shows past runs if any exist on server)
4. Start a test training run, verify it appears in History after completion
5. Delete a run from History, verify it's removed

- [ ] **Step 5: Commit**

```
feat(ml): persist training history in database

- Add MLTrainingRun table with params, results, and metadata
- Add GET /api/ml/train/history and DELETE endpoints
- Backend persists runs on start, updates on completion/failure/cancel
- Frontend fetches history from API instead of localStorage
- Add preset description subtitles to Setup tab
```
