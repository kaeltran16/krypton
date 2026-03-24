# ML Training History Persistence + Preset Tooltips

## Problem

Training history is stored in browser localStorage and backend in-memory dicts. Both are lost on restart/device change. The user has trained models on production but the History, Results, and Training tabs all show empty states. Additionally, the preset labels (Quick Test / Balanced / Production) have no explanation of what they do.

## Solution

1. Persist all training runs in a new `ml_training_run` Postgres table with full params, results, and metadata.
2. Add API endpoints for history retrieval and deletion.
3. Frontend fetches history from the API instead of localStorage.
4. Add descriptive tooltips to training presets.

## Database Model: `MLTrainingRun`

New table `ml_training_run`. Uses `UUID(as_uuid=False)` PK with string default to match `BacktestRun` pattern. Stores params as a JSONB column (matches `BacktestRun.config` pattern) for simplicity and forward-compatibility with new params.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID(as_uuid=False) | PK, default=str(uuid4()) | Matches BacktestRun pattern |
| `job_id` | String(32) | unique, not null | Timestamp-based ID (e.g. `20260323_141500`) |
| `status` | String(16) | not null | `running` / `completed` / `failed` / `cancelled` |
| `preset_label` | String(32) | nullable | "Quick Test" / "Balanced" / "Production" / null (custom) |
| `params` | JSONB | not null | Full TrainRequest params (timeframe, epochs, batch_size, etc.) |
| `result` | JSONB | nullable | Per-pair results blob (see Result Schema below) |
| `error` | Text | nullable | Error message if failed |
| `pairs_trained` | JSONB | nullable | List of pair strings that were trained |
| `duration_seconds` | Float | nullable | Wall-clock training time |
| `total_candles` | Integer | nullable | Sum of candles used across all pairs |
| `created_at` | DateTime(tz) | not null, default=utcnow | Job start time |
| `completed_at` | DateTime(tz) | nullable | Job finish time |

Index: `ix_ml_training_run_created` on `created_at` for ordered queries.

### Result JSONB Schema

```json
{
  "BTC-USDT-SWAP": {
    "best_epoch": 42,
    "best_val_loss": 0.6812,
    "total_epochs": 100,
    "total_samples": 8500,
    "flow_data_used": true,
    "version": "v3",
    "direction_accuracy": 0.651,
    "precision_per_class": { "long": 0.72, "short": 0.58, "neutral": 0.61 },
    "recall_per_class": { "long": 0.65, "short": 0.52, "neutral": 0.70 },
    "loss_history": [
      { "epoch": 1, "train_loss": 1.05, "val_loss": 1.12 },
      { "epoch": 2, "train_loss": 0.98, "val_loss": 1.01 }
    ]
  }
}
```

## Backend Changes

### New API Endpoints

**`GET /api/ml/train/history`** (`dependencies=[require_auth()]`)
- Returns all training runs, newest first (ordered by `created_at DESC`)
- Response: list of objects, each containing: `id`, `job_id`, `status`, `preset_label`, `params` (the full TrainRequest JSONB), `result`, `error`, `pairs_trained`, `duration_seconds`, `total_candles`, `created_at`, `completed_at`
- No pagination (run count is naturally small)

**`DELETE /api/ml/train/history/{job_id}`** (`dependencies=[require_auth()]`)
- Hard-deletes a training run record
- Returns 200 with `{"deleted": job_id}` on success, 404 if not found
- Matches existing delete pattern (e.g. backtest.py, alerts.py)

### Modified Endpoints

**`POST /api/ml/train`**
- On start: insert `MLTrainingRun` row with status=running, all params, created_at
- Accept optional `preset_label` field in `TrainRequest`
- Record `start_time = time.time()` for duration calculation

**Training completion callback (inside `_run()`)**
- On success: update row with status=completed, result JSONB, pairs_trained, total_candles, duration_seconds, completed_at
- On failure: update row with status=failed, error, duration_seconds, completed_at
- On cancel (`asyncio.CancelledError`): catch in `_run()`, update row with status=cancelled, duration_seconds, completed_at

### In-Memory Dict

The `app.state.ml_train_jobs` dict remains for live progress polling during active training (epoch-by-epoch updates). The DB is the persistent record. No change to `GET /api/ml/train/{job_id}` for live status.

## Frontend Changes

### MLTrainingView.tsx

- Remove localStorage read/write for `ml_training_history`
- Remove `saveToHistory()` and `saveHistoryToStorage()` functions
- Add `fetchHistory()` that calls `GET /api/ml/train/history`
- Call `fetchHistory()` on mount and after training completes (replaces `saveToHistory` entirely -- backend persists the run, frontend just re-fetches)
- `onDelete` handler must call `api.deleteMLTrainingRun(jobId)` then re-fetch history (or optimistically remove from local state)
- Pass `preset_label` to `handleStartTraining` -> API call

### SetupTab.tsx

- Pass `preset_label` through to the API request body

### HistoryTab.tsx

- No changes to component interface -- it already receives `history: MLTrainJob[]`
- Data now comes from API instead of localStorage

### ResultsTab.tsx

- No changes needed -- already reads from the `history` prop

### API Client (api.ts)

- Add `getMLTrainingHistory()` method
- Add `deleteMLTrainingRun(jobId)` method
- Add `preset_label` to `MLTrainRequest` type
- Add `duration_seconds` and `total_candles` to `MLTrainJob` type (for display in HistoryTab)

### Preset Tooltips (presets.ts + SetupTab.tsx)

Add `description` field to each preset:

| Preset | Description |
|---|---|
| Quick Test | "Small model, few epochs. Fast sanity check that training works with your data." |
| Balanced | "Mid-size model with moderate training time. Good default for most use cases." |
| Production | "Large model, long training, fine convergence. For the model you'll deploy to production." |

Render as a subtitle below the preset segmented control (not hover tooltip -- poor UX on mobile). When a preset is selected, show its description text below the control in muted style.

## Migration

Alembic migration creates the `ml_training_run` table. No data migration needed -- previous runs were ephemeral.

## Files to Change

### Backend
- `backend/app/db/models.py` -- add `MLTrainingRun` model
- `backend/app/api/ml.py` -- add history endpoints, modify train endpoint to persist
- `backend/app/api/routes.py` -- no change needed (ml router already registered)
- New Alembic migration

### Frontend
- `web/src/shared/lib/api.ts` -- add types + API methods
- `web/src/features/ml/presets.ts` -- add `description` field to presets
- `web/src/features/ml/components/MLTrainingView.tsx` -- replace localStorage with API fetch, update onDelete to call API
- `web/src/features/ml/components/SetupTab.tsx` -- render preset subtitle
- `web/src/features/ml/components/__tests__/MLTrainingView.test.tsx` -- update mocks

### Backend Tests
- Add tests for `GET /api/ml/train/history` and `DELETE /api/ml/train/history/{job_id}`
