# ML Training Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the ML Training page from a monolithic 929-line file into a workflow-oriented, decomposed experience with loss visualization, data readiness checks, presets, richer metrics, and model comparison.

**Architecture:** Split the monolith into a shell + 4 tab components + shared utilities + canvas chart. Backend gains a data-readiness endpoint and enriched trainer metrics (direction accuracy, per-class precision/recall, loss history). All new data flows through existing in-memory job dicts (backend) and localStorage (frontend) — no DB schema changes.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS v3, Canvas API, FastAPI, SQLAlchemy 2.0 async, PyTorch

**Spec:** `docs/superpowers/specs/2026-03-22-ml-training-page-redesign-design.md`

---

## File Structure

### Backend (modify)

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/api/ml.py` | Modify | Add `GET /api/ml/data-readiness` endpoint; update `pair_results` construction in `_run()` to forward new trainer fields; add `direction_acc` to progress callback |
| `backend/app/ml/trainer.py` | Modify | Add post-training classification metrics computation (direction_accuracy, precision_per_class, recall_per_class, loss_history) |
| `backend/tests/api/test_ml.py` | Modify | Add tests for data-readiness endpoint and enriched pair_results |
| `backend/tests/ml/test_trainer.py` | Modify | Add test verifying new fields in trainer return dict |

### Frontend (create)

| File | Action | Responsibility |
|------|--------|----------------|
| `web/src/features/ml/types.ts` | Create | ML-specific types extracted/extended from api.ts |
| `web/src/features/ml/presets.ts` | Create | Quick Test / Balanced / Production config objects |
| `web/src/features/ml/components/shared.tsx` | Create | SettingsSection, ConfigField, Select, Slider reusable components |
| `web/src/features/ml/components/LossChart.tsx` | Create | Custom canvas loss curve chart (~80 lines) |
| `web/src/features/ml/components/SetupTab.tsx` | Create | Presets, data readiness, config sliders, inline backfill, sticky actions |
| `web/src/features/ml/components/TrainingTab.tsx` | Create | Live progress, loss chart, pair selector, metrics grid |
| `web/src/features/ml/components/ResultsTab.tsx` | Create | Detailed metrics, compare mode, config display |
| `web/src/features/ml/components/HistoryTab.tsx` | Create | Compact job list with view/retrain/delete actions |

### Frontend (modify)

| File | Action | Responsibility |
|------|--------|----------------|
| `web/src/features/ml/components/MLTrainingView.tsx` | Rewrite | Shell: tab state, job state, handlers, orchestration (~120 lines) |
| `web/src/shared/lib/api.ts` | Modify | Update MLTrainProgress/MLTrainResult types, add `getMLDataReadiness` method |
| `web/src/features/ml/components/__tests__/MLTrainingView.test.tsx` | Rewrite | Update tests for new tab structure |

---

## Task 1: Backend — Data Readiness Endpoint

**Files:**
- Modify: `backend/app/api/ml.py`
- Modify: `backend/tests/api/test_ml.py`

- [ ] **Step 1: Write the failing test for data-readiness endpoint**

Add to `backend/tests/api/test_ml.py`:

```python
async def test_data_readiness_returns_per_pair_counts(ml_app, ml_client):
    """GET /api/ml/data-readiness?timeframe=1h returns candle counts per pair."""
    from unittest.mock import MagicMock, AsyncMock
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    # Mock DB to return aggregate results
    mock_session = AsyncMock()
    mock_row_btc = MagicMock()
    mock_row_btc.pair = "BTC-USDT-SWAP"
    mock_row_btc.count = 8760
    mock_row_btc.oldest = datetime(2025, 3, 22, tzinfo=timezone.utc)

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row_btc]
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    ml_app.state.db.session_factory = fake_session

    resp = await ml_client.get("/api/ml/data-readiness?timeframe=1h", cookies=COOKIES)
    assert resp.status_code == 200
    data = resp.json()
    assert "BTC-USDT-SWAP" in data
    assert data["BTC-USDT-SWAP"]["count"] == 8760
    assert data["BTC-USDT-SWAP"]["sufficient"] is True


async def test_data_readiness_requires_timeframe(ml_client):
    """GET /api/ml/data-readiness without timeframe returns 422."""
    resp = await ml_client.get("/api/ml/data-readiness", cookies=COOKIES)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_ml.py::test_data_readiness_returns_per_pair_counts -v`
Expected: FAIL (404 — route doesn't exist yet)

- [ ] **Step 3: Implement the data-readiness endpoint**

Add to `backend/app/api/ml.py` (after the existing imports, add `func` to the sqlalchemy import):

```python
from sqlalchemy import select, func
```

Then add the endpoint (before the `start_training` endpoint):

```python
@router.get("/data-readiness", dependencies=[require_auth()])
async def get_data_readiness(timeframe: str, request: Request):
    """Return per-pair candle counts for a given timeframe."""
    db = request.app.state.db
    settings = request.app.state.settings

    async with db.session_factory() as session:
        result = await session.execute(
            select(
                Candle.pair,
                func.count().label("count"),
                func.min(Candle.timestamp).label("oldest"),
            )
            .where(Candle.timeframe == timeframe)
            .where(Candle.pair.in_(settings.pairs))
            .group_by(Candle.pair)
        )
        rows = result.all()

    data = {}
    for row in rows:
        data[row.pair] = {
            "count": row.count,
            "oldest": row.oldest.isoformat() if row.oldest else None,
            "sufficient": row.count >= 100,
        }

    # Include pairs with zero candles
    for pair in settings.pairs:
        if pair not in data:
            data[pair] = {"count": 0, "oldest": None, "sufficient": False}

    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_ml.py::test_data_readiness_returns_per_pair_counts tests/api/test_ml.py::test_data_readiness_requires_timeframe -v`
Expected: PASS

---

## Task 2: Backend — Enriched Trainer Metrics

**Files:**
- Modify: `backend/app/ml/trainer.py`
- Modify: `backend/tests/ml/test_trainer.py`

- [ ] **Step 1: Write the failing test for new trainer fields**

Add to `class TestTrainer` in `backend/tests/ml/test_trainer.py` (follows existing `synthetic_data` fixture and test conventions):

```python
    def test_train_returns_classification_metrics(self, synthetic_data):
        """Trainer.train() result includes direction_accuracy, precision_per_class, recall_per_class, loss_history."""
        features, direction, sl, tp1, tp2 = synthetic_data
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TrainConfig(
                epochs=3,
                batch_size=32,
                seq_len=50,
                hidden_size=32,
                num_layers=1,
                lr=1e-3,
                checkpoint_dir=tmpdir,
            )
            trainer = Trainer(config)
            result = trainer.train(features, direction, sl, tp1, tp2)

            # Existing fields still present
            assert "best_epoch" in result
            assert "best_val_loss" in result
            assert "train_loss" in result
            assert "val_loss" in result

            # New fields
            assert "direction_accuracy" in result
            assert isinstance(result["direction_accuracy"], float)
            assert 0.0 <= result["direction_accuracy"] <= 1.0

            assert "precision_per_class" in result
            for cls in ("long", "short", "neutral"):
                assert cls in result["precision_per_class"]
                assert 0.0 <= result["precision_per_class"][cls] <= 1.0

            assert "recall_per_class" in result
            for cls in ("long", "short", "neutral"):
                assert cls in result["recall_per_class"]
                assert 0.0 <= result["recall_per_class"][cls] <= 1.0

            assert "loss_history" in result
            assert len(result["loss_history"]) > 0
            entry = result["loss_history"][0]
            assert "epoch" in entry
            assert "train_loss" in entry
            assert "val_loss" in entry
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py::TestTrainer::test_train_returns_classification_metrics -v`
Expected: FAIL (KeyError on `direction_accuracy`)

- [ ] **Step 3: Implement enriched metrics in Trainer.train()**

At the end of `backend/app/ml/trainer.py`, replace the return block (lines ~295-302). After the versioned checkpoint save and before `return`, add the classification metrics computation:

```python
        # ── Compute classification metrics on validation set at best epoch ──
        direction_accuracy = 0.0
        precision_per_class = {"long": 0.0, "short": 0.0, "neutral": 0.0}
        recall_per_class = {"long": 0.0, "short": 0.0, "neutral": 0.0}

        if use_val:
            # Load best checkpoint for evaluation
            best_pt = os.path.join(cfg.checkpoint_dir, "best_model.pt")
            if os.path.exists(best_pt):
                model.load_state_dict(torch.load(best_pt, map_location=self.device, weights_only=True))

            model.eval()
            all_preds = []
            all_labels = []
            with torch.no_grad():
                for x, y_dir, _y_reg in val_loader:
                    x = x.to(self.device)
                    y_dir = y_dir.to(self.device)
                    dir_logits, _ = model(x)
                    preds = dir_logits.argmax(dim=1)
                    all_preds.extend(preds.cpu().numpy())
                    all_labels.extend(y_dir.cpu().numpy())

            all_preds = np.array(all_preds)
            all_labels = np.array(all_labels)

            # Direction accuracy
            direction_accuracy = float((all_preds == all_labels).mean()) if len(all_labels) > 0 else 0.0

            # Per-class precision and recall (manual — no sklearn)
            class_names = {0: "neutral", 1: "long", 2: "short"}
            for cls_id, cls_name in class_names.items():
                tp = int(((all_preds == cls_id) & (all_labels == cls_id)).sum())
                fp = int(((all_preds == cls_id) & (all_labels != cls_id)).sum())
                fn = int(((all_preds != cls_id) & (all_labels == cls_id)).sum())
                precision_per_class[cls_name] = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                recall_per_class[cls_name] = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        # Build loss_history for frontend chart
        loss_history = []
        for i in range(len(train_losses)):
            entry = {
                "epoch": i + 1,
                "train_loss": train_losses[i],
                "val_loss": val_losses[i] if i < len(val_losses) else None,
            }
            loss_history.append(entry)

        return {
            "train_loss": train_losses,
            "val_loss": val_losses,
            "best_epoch": best_epoch,
            "best_val_loss": best_val_loss,
            "version": version_tag,
            "lr_history": lr_history,
            "direction_accuracy": direction_accuracy,
            "precision_per_class": precision_per_class,
            "recall_per_class": recall_per_class,
            "loss_history": loss_history,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py::TestTrainer::test_train_returns_classification_metrics -v`
Expected: PASS

- [ ] **Step 5: Run all existing trainer tests to verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py -v`
Expected: All PASS

---

## Task 3: Backend — Forward New Fields + Enriched Progress

**Files:**
- Modify: `backend/app/api/ml.py` (lines 159-160 for progress callback, lines 178-185 for pair_results)

- [ ] **Step 1: Update the progress callback to include direction_acc**

In `backend/app/api/ml.py`, the `on_progress` closure (line 159-160) passes the trainer's progress dict straight through. The trainer already sends `train_loss` and `val_loss` per epoch. We need to add `direction_acc` to the trainer's progress callback.

In `backend/app/ml/trainer.py`, update the `progress_callback` call (around line 227-232) to include a live direction accuracy estimate:

```python
            if progress_callback:
                progress_callback({
                    "epoch": epoch + 1,
                    "total_epochs": cfg.epochs,
                    "train_loss": avg_train_loss,
                    "val_loss": avg_val_loss,
                    "direction_acc": None,  # computed at end only
                })
```

Note: Computing live direction_acc per epoch would slow training. We report `None` during training; the final value is in the completed result. The Training tab can show "—" until complete.

- [ ] **Step 2: Update pair_results construction to forward new fields**

In `backend/app/api/ml.py`, update the `pair_results[pair]` dict (lines 178-185):

```python
                pair_results[pair] = {
                    "best_epoch": pair_result["best_epoch"],
                    "best_val_loss": pair_result["best_val_loss"],
                    "total_epochs": len(pair_result["train_loss"]),
                    "total_samples": len(features),
                    "flow_data_used": flow_used,
                    "version": pair_result.get("version"),
                    "direction_accuracy": pair_result.get("direction_accuracy"),
                    "precision_per_class": pair_result.get("precision_per_class"),
                    "recall_per_class": pair_result.get("recall_per_class"),
                    "loss_history": pair_result.get("loss_history"),
                }
```

- [ ] **Step 3: Run all ML API tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_ml.py -v`
Expected: All PASS

- [ ] **Step 4: Run all ML tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ -v`
Expected: All PASS

---

## Task 4: Frontend — Types, Presets, API Client Updates

**Files:**
- Create: `web/src/features/ml/types.ts`
- Create: `web/src/features/ml/presets.ts`
- Modify: `web/src/shared/lib/api.ts`

- [ ] **Step 1: Create ML types file**

Create `web/src/features/ml/types.ts`:

```typescript
import type { MLTrainRequest, MLTrainJob } from "../../shared/lib/api";

export type MLTab = "setup" | "training" | "results" | "history";

export interface DataReadiness {
  count: number;
  oldest: string | null;
  sufficient: boolean;
}

export type DataReadinessMap = Record<string, DataReadiness>;

export interface LossHistoryEntry {
  epoch: number;
  train_loss: number;
  val_loss: number | null;
}

export interface ClassMetrics {
  long: number;
  short: number;
  neutral: number;
}

/** Extended pair result with classification metrics */
export interface PairResult {
  best_epoch: number;
  best_val_loss: number;
  total_epochs: number;
  total_samples: number;
  flow_data_used: boolean;
  version?: string;
  direction_accuracy?: number;
  precision_per_class?: ClassMetrics;
  recall_per_class?: ClassMetrics;
  loss_history?: LossHistoryEntry[];
}

export type { MLTrainRequest, MLTrainJob };
```

- [ ] **Step 2: Create presets file**

Create `web/src/features/ml/presets.ts`:

```typescript
import type { MLTrainRequest } from "../../shared/lib/api";

export type PresetName = "quick" | "balanced" | "production";

export interface Preset {
  name: PresetName;
  label: string;
  config: Partial<MLTrainRequest>;
}

export const PRESETS: Preset[] = [
  {
    name: "quick",
    label: "Quick Test",
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

export const DEFAULT_CONFIG: MLTrainRequest = {
  timeframe: "1h",
  lookback_days: 365,
  label_horizon: 24,
  label_threshold_pct: 1.5,
  ...PRESETS[1].config, // Balanced defaults
};

/** Candles per day for each timeframe — used for backfill progress estimation */
export const CANDLES_PER_DAY: Record<string, number> = {
  "15m": 96,
  "1h": 24,
  "4h": 6,
};
```

- [ ] **Step 3: Update API types and add data-readiness method**

In `web/src/shared/lib/api.ts`, update the `MLTrainProgress` interface (lines 24-29):

```typescript
export interface MLTrainProgress {
  epoch: number;
  total_epochs: number;
  train_loss: number;
  val_loss: number;
  direction_acc?: number;
}
```

Update the `MLTrainResult` interface (lines 31-38):

```typescript
export interface MLTrainResult {
  best_epoch: number;
  best_val_loss: number;
  total_epochs: number;
  total_samples: number;
  flow_data_used: boolean;
  version?: string;
  direction_accuracy?: number;
  precision_per_class?: { long: number; short: number; neutral: number };
  recall_per_class?: { long: number; short: number; neutral: number };
  loss_history?: { epoch: number; train_loss: number; val_loss: number }[];
}
```

Add the new API method in the `api` object (after `getMLStatus`):

```typescript
  getMLDataReadiness: (timeframe: string) =>
    request<Record<string, { count: number; oldest: string | null; sufficient: boolean }>>(
      `/api/ml/data-readiness?timeframe=${encodeURIComponent(timeframe)}`,
    ),
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors (there may be pre-existing ones unrelated to our changes)

---

## Task 5: Frontend — Shared Components Extraction

**Files:**
- Create: `web/src/features/ml/components/shared.tsx`

- [ ] **Step 1: Create shared.tsx with extracted components**

Extract `SettingsSection`, `ConfigField`, `Select`, and `Slider` from the current `MLTrainingView.tsx` (lines 232-310) into `web/src/features/ml/components/shared.tsx`:

```tsx
export const TIMEFRAMES = ["15m", "1h", "4h"] as const;

export function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-2 px-1 text-on-surface-variant">{title}</h2>
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden">
        {children}
      </div>
    </div>
  );
}

export function ConfigField({ label, value, children }: {
  label: string;
  value?: string | number;
  children: React.ReactNode;
}) {
  return (
    <div className="px-3 py-3 border-b border-outline-variant/10 last:border-b-0">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-on-surface">{label}</span>
        {value !== undefined && (
          <span className="text-xs text-primary font-mono">{typeof value === "number" && value < 1 ? value.toFixed(4) : value}</span>
        )}
      </div>
      {children}
    </div>
  );
}

export function Select({ value, onChange, options }: {
  value: string;
  onChange: (v: string) => void;
  options: { label: string; value: string }[];
}) {
  return (
    <div className="flex gap-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`flex-1 py-2 rounded-lg text-xs font-bold transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
            value === opt.value
              ? "bg-surface-container-highest text-primary border border-primary/20"
              : "bg-surface-container-lowest text-on-surface-variant"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export function Slider({ min, max, step = 1, value, onChange, format }: {
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
      <div className="flex justify-between text-[10px] text-outline mt-0.5">
        <span>{format ? format(min) : min}</span>
        <span>{format ? format(max) : max}</span>
      </div>
    </div>
  );
}

/** Status badge used in Training, Results, and History tabs */
export function StatusBadge({ status }: { status: string }) {
  const colors =
    status === "completed" ? "bg-tertiary-dim/15 text-tertiary-dim" :
    status === "failed" ? "bg-error/15 text-error" :
    status === "cancelled" ? "bg-outline/15 text-on-surface-variant" :
    "bg-primary/15 text-primary";

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors}`}>
      {status}
    </span>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors

---

## Task 6: Frontend — LossChart Canvas Component

**Files:**
- Create: `web/src/features/ml/components/LossChart.tsx`

- [ ] **Step 1: Create LossChart component**

Create `web/src/features/ml/components/LossChart.tsx`:

```tsx
import { useRef, useEffect } from "react";
import { theme } from "../../../shared/theme";

interface LossChartProps {
  data: { epoch: number; train_loss: number; val_loss: number | null }[];
  bestEpoch?: number;
  height?: number;
}

const PADDING = { top: 20, right: 70, bottom: 30, left: 50 };
const TRAIN_COLOR = theme.colors.accent;   // #0EB5E5
const VAL_COLOR = theme.colors.long;       // #2DD4A0
const GRID_COLOR = "rgba(94, 106, 125, 0.2)";
const TEXT_COLOR = theme.colors.muted;     // #8E9AAD
const BEST_COLOR = theme.colors.muted;

export function LossChart({ data, bestEpoch, height = 200 }: LossChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || data.length === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const plotW = width - PADDING.left - PADDING.right;
    const plotH = height - PADDING.top - PADDING.bottom;

    // Compute Y range from all loss values
    const allVals = data.flatMap((d) => [d.train_loss, d.val_loss].filter((v): v is number => v != null));
    if (allVals.length === 0) return;
    const yMin = Math.min(...allVals) * 0.95;
    const yMax = Math.max(...allVals) * 1.05;
    const yRange = yMax - yMin || 1;

    const xMin = data[0].epoch;
    const xMax = data[data.length - 1].epoch;
    const xRange = xMax - xMin || 1;

    const toX = (epoch: number) => PADDING.left + ((epoch - xMin) / xRange) * plotW;
    const toY = (loss: number) => PADDING.top + (1 - (loss - yMin) / yRange) * plotH;

    // Grid lines + Y labels
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 0.5;
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.fillStyle = TEXT_COLOR;
    ctx.textAlign = "right";
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {
      const val = yMin + (yRange * i) / yTicks;
      const y = toY(val);
      ctx.beginPath();
      ctx.moveTo(PADDING.left, y);
      ctx.lineTo(width - PADDING.right, y);
      ctx.stroke();
      ctx.fillText(val.toFixed(3), PADDING.left - 6, y + 3);
    }

    // X labels
    ctx.textAlign = "center";
    const xLabelCount = Math.min(data.length, 5);
    const xStep = Math.max(1, Math.floor(data.length / xLabelCount));
    for (let i = 0; i < data.length; i += xStep) {
      const x = toX(data[i].epoch);
      ctx.fillText(String(data[i].epoch), x, height - PADDING.bottom + 16);
    }

    // Best epoch vertical line
    if (bestEpoch != null) {
      const bx = toX(bestEpoch);
      ctx.save();
      ctx.strokeStyle = BEST_COLOR;
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.beginPath();
      ctx.moveTo(bx, PADDING.top);
      ctx.lineTo(bx, PADDING.top + plotH);
      ctx.stroke();
      ctx.restore();
    }

    // Draw polyline helper
    function drawLine(
      points: { x: number; y: number }[],
      color: string,
      dash: number[] = [],
    ) {
      if (points.length < 2) return;
      ctx!.save();
      ctx!.strokeStyle = color;
      ctx!.lineWidth = 1.5;
      ctx!.setLineDash(dash);
      ctx!.lineJoin = "round";
      ctx!.beginPath();
      ctx!.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx!.lineTo(points[i].x, points[i].y);
      }
      ctx!.stroke();
      ctx!.restore();
    }

    // Train loss line (solid)
    const trainPts = data.map((d) => ({ x: toX(d.epoch), y: toY(d.train_loss) }));
    drawLine(trainPts, TRAIN_COLOR);

    // Val loss line (dashed)
    const valPts = data
      .filter((d) => d.val_loss != null)
      .map((d) => ({ x: toX(d.epoch), y: toY(d.val_loss!) }));
    drawLine(valPts, VAL_COLOR, [6, 3]);

    // Legend (top-right)
    const legendX = width - PADDING.right + 8;
    const legendY = PADDING.top + 4;
    ctx.font = "10px Inter, system-ui, sans-serif";
    ctx.textAlign = "left";

    // Train legend
    ctx.strokeStyle = TRAIN_COLOR;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(legendX, legendY);
    ctx.lineTo(legendX + 16, legendY);
    ctx.stroke();
    ctx.fillStyle = TEXT_COLOR;
    ctx.fillText("Train", legendX + 20, legendY + 3);

    // Val legend
    ctx.strokeStyle = VAL_COLOR;
    ctx.setLineDash([6, 3]);
    ctx.beginPath();
    ctx.moveTo(legendX, legendY + 16);
    ctx.lineTo(legendX + 16, legendY + 16);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillText("Val", legendX + 20, legendY + 19);
  }, [data, bestEpoch, height]);

  // Build aria label
  const bestVal = data.length > 0
    ? data.filter((d) => d.val_loss != null).sort((a, b) => (a.val_loss ?? Infinity) - (b.val_loss ?? Infinity))[0]
    : null;
  const ariaLabel = bestVal
    ? `Loss chart: best validation loss ${bestVal.val_loss?.toFixed(3)} at epoch ${bestVal.epoch} of ${data.length}`
    : "Loss chart: no data";

  return (
    <div ref={containerRef} className="w-full">
      <canvas
        ref={canvasRef}
        aria-label={ariaLabel}
        role="img"
        className="w-full"
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors

---

## Task 7: Frontend — SetupTab

**Files:**
- Create: `web/src/features/ml/components/SetupTab.tsx`

- [ ] **Step 1: Create SetupTab component**

Create `web/src/features/ml/components/SetupTab.tsx`:

```tsx
import { useState, useEffect } from "react";
import { api, type MLTrainRequest, type MLStatus, type MLTrainJob, type MLBackfillJob } from "../../../shared/lib/api";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { SettingsSection, ConfigField, Select, Slider, TIMEFRAMES } from "./shared";
import { PRESETS, DEFAULT_CONFIG, CANDLES_PER_DAY, type PresetName } from "../presets";
import type { DataReadinessMap } from "../types";

interface SetupTabProps {
  status: MLStatus | null;
  onStartTraining: (params: MLTrainRequest, presetLabel?: string | null) => void;
  trainingJob: MLTrainJob | null;
  initialConfig?: MLTrainRequest | null;
  backfillJob: MLBackfillJob | null;
  onStartBackfill: (params: { timeframe: string; lookback_days: number }) => void;
  onCancelBackfill: () => void;
}

export function SetupTab({
  status,
  onStartTraining,
  trainingJob,
  initialConfig,
  backfillJob,
  onStartBackfill,
  onCancelBackfill,
}: SetupTabProps) {
  const [config, setConfig] = useState<MLTrainRequest>({ ...DEFAULT_CONFIG });
  const [activePreset, setActivePreset] = useState<PresetName | null>("balanced");
  const [showConfirm, setShowConfirm] = useState(false);
  const [readiness, setReadiness] = useState<DataReadinessMap | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [backfillStartTime, setBackfillStartTime] = useState<number | null>(null);

  // Restore config from retrain
  useEffect(() => {
    if (initialConfig) {
      setConfig(initialConfig);
      setActivePreset(null);
    }
  }, [initialConfig]);

  // Fetch data readiness on mount and timeframe change
  useEffect(() => {
    if (!config.timeframe) return;
    setReadinessLoading(true);
    setReadinessError(null);
    api.getMLDataReadiness(config.timeframe)
      .then(setReadiness)
      .catch((e) => setReadinessError(e.message))
      .finally(() => setReadinessLoading(false));
  }, [config.timeframe]);

  // Auto-refresh readiness after backfill completes
  useEffect(() => {
    if (backfillJob?.status === "completed" && config.timeframe) {
      api.getMLDataReadiness(config.timeframe)
        .then(setReadiness)
        .catch(() => {});
    }
  }, [backfillJob?.status, config.timeframe]);

  function handlePresetChange(preset: PresetName) {
    const found = PRESETS.find((p) => p.name === preset);
    if (found) {
      setConfig({ ...config, ...found.config });
      setActivePreset(preset);
    }
  }

  function handleReset() {
    setConfig({ ...DEFAULT_CONFIG });
    setActivePreset("balanced");
  }

  function updateConfig(patch: Partial<MLTrainRequest>) {
    setConfig({ ...config, ...patch });
    setActivePreset(null); // Manual change clears preset
  }

  const backfillRunning = backfillJob?.status === "running";
  const backfillProgress = backfillJob?.progress as Record<string, number> | undefined;
  const backfillResult = backfillJob?.result as Record<string, number> | undefined;

  // Track backfill start time for ETA
  useEffect(() => {
    if (backfillRunning && !backfillStartTime) setBackfillStartTime(Date.now());
    if (!backfillRunning) setBackfillStartTime(null);
  }, [backfillRunning]);
  const anyInsufficient = readiness ? Object.values(readiness).some((r) => !r.sufficient) : false;

  return (
    <div className="space-y-4 pb-20">
      {/* Model overwrite warning */}
      {status && status.loaded_pairs.length > 0 && (
        <div className="bg-error/10 border border-error/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-error mt-0.5 shrink-0">
            <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="text-xs text-error">
            <span className="font-medium">Training will overwrite existing models.</span>
            <p className="mt-0.5 opacity-90">
              Current models: {status.loaded_pairs.map((p) => p.replace("_", "-").toUpperCase()).join(", ")}
            </p>
          </div>
        </div>
      )}

      {/* Preset bar */}
      <SegmentedControl
        options={PRESETS.map((p) => ({ value: p.name, label: p.label }))}
        value={activePreset ?? ""}
        onChange={(v) => handlePresetChange(v as PresetName)}
        fullWidth
      />

      {/* Data readiness */}
      <SettingsSection title="Data Readiness">
        {readinessLoading ? (
          <div className="p-3 space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-6 bg-surface-container-highest rounded animate-pulse" />
            ))}
          </div>
        ) : readinessError ? (
          <div className="p-3">
            <p className="text-xs text-error mb-2">{readinessError}</p>
            <button
              onClick={() => {
                setReadinessLoading(true);
                setReadinessError(null);
                api.getMLDataReadiness(config.timeframe!)
                  .then(setReadiness)
                  .catch((e) => setReadinessError(e.message))
                  .finally(() => setReadinessLoading(false));
              }}
              className="text-xs text-primary hover:underline"
            >
              Retry
            </button>
          </div>
        ) : readiness ? (
          <div className="p-3 space-y-2">
            {Object.entries(readiness).map(([pair, info]) => (
              <div key={pair} className="flex items-center gap-2">
                <span className="text-xs text-on-surface w-28 shrink-0 truncate">{pair}</span>
                <div className="flex-1 h-2 bg-surface-container-highest rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${info.sufficient ? "bg-tertiary-dim" : "bg-error"}`}
                    style={{ width: `${Math.min(100, (info.count / 100) * 100)}%` }}
                  />
                </div>
                {info.sufficient ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-tertiary-dim shrink-0">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-error shrink-0">
                    <path d="M12 9v2m0 4h.01M12 3a9 9 0 100 18 9 9 0 000-18z" />
                  </svg>
                )}
                <span className="text-[10px] font-mono text-on-surface-variant w-14 text-right">{info.count}</span>
                {!info.sufficient && !backfillRunning && (
                  <button
                    onClick={() => onStartBackfill({ timeframe: config.timeframe!, lookback_days: config.lookback_days! })}
                    className="text-[10px] text-primary hover:underline shrink-0"
                  >
                    Backfill Now
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </SettingsSection>

      {/* Data Parameters */}
      <SettingsSection title="Data Parameters">
        <ConfigField label="Timeframe">
          <Select
            value={config.timeframe!}
            onChange={(v) => updateConfig({ timeframe: v })}
            options={TIMEFRAMES.map((t) => ({ label: t, value: t }))}
          />
        </ConfigField>
        <ConfigField label="Lookback Days" value={config.lookback_days}>
          <Slider min={30} max={1825} value={config.lookback_days!} onChange={(v) => updateConfig({ lookback_days: v })} />
        </ConfigField>
        <ConfigField label="Label Horizon (hours)" value={config.label_horizon}>
          <Slider min={4} max={96} value={config.label_horizon!} onChange={(v) => updateConfig({ label_horizon: v })} />
        </ConfigField>
        <ConfigField label="Label Threshold %" value={`${config.label_threshold_pct}%`}>
          <Slider min={0.1} max={10} step={0.1} value={config.label_threshold_pct!} onChange={(v) => updateConfig({ label_threshold_pct: v })} />
        </ConfigField>
      </SettingsSection>

      {/* Model Parameters */}
      <SettingsSection title="Model Parameters">
        <ConfigField label="Epochs" value={config.epochs}>
          <Slider min={1} max={500} value={config.epochs!} onChange={(v) => updateConfig({ epochs: v })} />
        </ConfigField>
        <ConfigField label="Batch Size" value={config.batch_size}>
          <Slider min={8} max={512} step={8} value={config.batch_size!} onChange={(v) => updateConfig({ batch_size: v })} />
        </ConfigField>
        <ConfigField label="Hidden Size" value={config.hidden_size}>
          <Slider min={32} max={512} step={32} value={config.hidden_size!} onChange={(v) => updateConfig({ hidden_size: v })} />
        </ConfigField>
        <ConfigField label="Num Layers" value={config.num_layers}>
          <Slider min={1} max={4} value={config.num_layers!} onChange={(v) => updateConfig({ num_layers: v })} />
        </ConfigField>
        <ConfigField label="Sequence Length" value={config.seq_len}>
          <Slider min={25} max={200} value={config.seq_len!} onChange={(v) => updateConfig({ seq_len: v })} />
        </ConfigField>
        <ConfigField label="Dropout" value={config.dropout}>
          <Slider min={0} max={0.7} step={0.05} value={config.dropout!} onChange={(v) => updateConfig({ dropout: v })} />
        </ConfigField>
        <ConfigField label="Learning Rate" value={config.lr}>
          <Slider min={0.0001} max={0.01} step={0.0001} value={config.lr!} onChange={(v) => updateConfig({ lr: v })} format={(v) => v.toExponential(2)} />
        </ConfigField>
      </SettingsSection>

      {/* Inline Backfill */}
      <SettingsSection title="Backfill Data">
        <div className="p-3 space-y-3">
          {backfillRunning && backfillProgress ? (
            <div className="space-y-2">
              {(() => {
                const cpd = CANDLES_PER_DAY[config.timeframe!] ?? 24;
                const expected = (config.lookback_days ?? 365) * cpd;
                const totalFetched = Object.values(backfillProgress).reduce((a, b) => a + b, 0);
                const totalExpected = expected * Object.keys(backfillProgress).length;
                const overallPct = totalExpected > 0 ? (totalFetched / totalExpected) * 100 : 0;

                // ETA estimation
                let etaText = "Estimating...";
                if (overallPct >= 10 && backfillStartTime) {
                  const elapsed = (Date.now() - backfillStartTime) / 1000;
                  const remaining = (elapsed / overallPct) * (100 - overallPct);
                  const mins = Math.ceil(remaining / 60);
                  etaText = mins > 1 ? `~${mins}m remaining` : "< 1m remaining";
                }

                return (
                  <>
                    <p className="text-[10px] text-on-surface-variant text-right">{etaText}</p>
                    {Object.entries(backfillProgress).map(([pair, fetched]) => {
                      const pct = Math.min(100, (fetched / expected) * 100);
                      const isDone = backfillResult?.[pair] != null;
                      return (
                        <div key={pair}>
                          <div className="flex items-center justify-between text-xs mb-1">
                            <div className="flex items-center gap-1.5">
                              {isDone ? (
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-tertiary-dim">
                                  <path d="M20 6L9 17l-5-5" />
                                </svg>
                              ) : (
                                <div className="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                              )}
                              <span className="text-on-surface">{pair}</span>
                            </div>
                            <span className="text-on-surface-variant font-mono">{fetched} candles</span>
                          </div>
                          <div className="h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                            <div className="h-full bg-primary transition-all duration-300" style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </>
                );
              })()}
              <button onClick={onCancelBackfill} className="w-full text-xs text-error hover:text-error/80 py-2">
                Cancel Backfill
              </button>
            </div>
          ) : (
            <>
              <p className="text-xs text-on-surface-variant">
                Fetch historical candles for {config.timeframe} / {config.lookback_days} days.
              </p>
              {anyInsufficient && (
                <p className="text-xs text-error">Some pairs have insufficient data. Backfill recommended.</p>
              )}
              <button
                onClick={() => onStartBackfill({ timeframe: config.timeframe!, lookback_days: config.lookback_days! })}
                className="w-full bg-surface-container-highest text-on-surface rounded-lg px-4 py-2 text-xs font-medium hover:bg-surface-bright transition-colors"
              >
                Start Backfill
              </button>
            </>
          )}
        </div>
      </SettingsSection>

      {/* Sticky Action Buttons */}
      <div className="fixed bottom-0 left-0 right-0 bg-surface/90 backdrop-blur-lg border-t border-outline-variant/10 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] flex gap-2 z-40">
        <button
          onClick={handleReset}
          className="flex-1 bg-surface-container rounded-lg border border-outline-variant/10 px-4 py-3 text-sm font-medium hover:bg-surface-container-highest transition-colors"
        >
          Reset to Defaults
        </button>
        <button
          onClick={() => setShowConfirm(true)}
          disabled={!!trainingJob}
          className="flex-1 bg-primary/15 text-primary border border-primary/30 rounded-lg px-4 py-3 text-sm font-medium hover:bg-primary/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Start Training
        </button>
      </div>

      {/* Confirmation Dialog */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-4 max-w-sm w-full">
            <h3 className="text-sm font-semibold mb-2">Confirm Training</h3>
            <p className="text-xs text-on-surface-variant mb-4">
              This will overwrite existing models for selected pairs. Are you sure you want to proceed?
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 bg-surface-container rounded-lg border border-outline-variant/10 px-3 py-2 text-xs font-medium"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowConfirm(false);
                  const label = activePreset ? PRESETS.find((p) => p.name === activePreset)?.label : null;
                  onStartTraining(config, label);
                }}
                className="flex-1 bg-error/15 text-error border border-error/30 rounded-lg px-3 py-2 text-xs font-medium"
              >
                Start Training
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors

---

## Task 8: Frontend — TrainingTab

**Files:**
- Create: `web/src/features/ml/components/TrainingTab.tsx`

- [ ] **Step 1: Create TrainingTab component**

Create `web/src/features/ml/components/TrainingTab.tsx`:

```tsx
import { useState, useEffect } from "react";
import { api, type MLTrainJob, type MLTrainProgress } from "../../../shared/lib/api";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { StatusBadge } from "./shared";
import { LossChart } from "./LossChart";
import type { LossHistoryEntry } from "../types";

interface TrainingTabProps {
  job: MLTrainJob | null;
  onCancel: () => void;
  onComplete: (job: MLTrainJob) => void;
  onSwitchToSetup: () => void;
  presetLabel?: string | null;
  configSummary?: string | null;
}

export function TrainingTab({ job, onCancel, onComplete, onSwitchToSetup, presetLabel, configSummary }: TrainingTabProps) {
  const [selectedPair, setSelectedPair] = useState<string>("");
  const [lossData, setLossData] = useState<Record<string, LossHistoryEntry[]>>({});

  // Poll for job progress
  useEffect(() => {
    if (!job || job.status !== "running") return;

    const interval = setInterval(async () => {
      try {
        const updated = await api.getMLTrainingStatus(job.job_id);

        // Accumulate loss data from progress
        if (updated.progress) {
          setLossData((prev) => {
            const next = { ...prev };
            for (const [pair, p] of Object.entries(updated.progress as Record<string, MLTrainProgress>)) {
              const existing = next[pair] || [];
              const lastEpoch = existing.length > 0 ? existing[existing.length - 1].epoch : 0;
              if (p.epoch > lastEpoch) {
                next[pair] = [...existing, { epoch: p.epoch, train_loss: p.train_loss, val_loss: p.val_loss }];
              }
            }
            return next;
          });

          // Auto-select the currently training pair
          const pairs = Object.keys(updated.progress);
          if (pairs.length > 0) {
            const currentPair = pairs[pairs.length - 1];
            setSelectedPair((prev) => prev || currentPair);
          }
        }

        if (updated.status !== "running") {
          onComplete(updated as MLTrainJob);
        }
      } catch {
        // Ignore, will retry
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [job?.job_id, job?.status, onComplete]);

  // Reset loss data when a new job starts
  useEffect(() => {
    if (job?.status === "running") {
      setLossData({});
      setSelectedPair("");
    }
  }, [job?.job_id]);

  if (!job) {
    return (
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-6 text-center">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-on-surface-variant mx-auto mb-3">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
        <p className="text-sm text-on-surface-variant mb-4">No active training job</p>
        <button onClick={onSwitchToSetup} className="bg-primary/15 text-primary border border-primary/30 rounded-lg px-4 py-2 text-xs font-medium">
          Configure Training
        </button>
      </div>
    );
  }

  const isRunning = job.status === "running";
  const progress = (job.progress as Record<string, MLTrainProgress>) || {};
  const pairs = Object.keys(progress);
  const currentProgress = selectedPair ? progress[selectedPair] : null;
  const currentLossData = selectedPair ? lossData[selectedPair] || [] : [];

  return (
    <div className="space-y-4">
      {/* Job header */}
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isRunning ? "bg-primary animate-pulse motion-reduce:animate-none" : "bg-muted"}`} />
            <span className="text-xs font-mono text-on-surface-variant">{job.job_id}</span>
            <StatusBadge status={job.status} />
          </div>
          {isRunning && (
            <button onClick={onCancel} className="text-xs text-error hover:text-error/80 transition-colors">
              Cancel
            </button>
          )}
        </div>
        {(presetLabel || configSummary) && (
          <p className="text-[10px] text-on-surface-variant mt-1">
            {presetLabel && <span className="text-primary font-medium">{presetLabel}</span>}
            {presetLabel && configSummary && <span> · </span>}
            {configSummary}
          </p>
        )}
        {job.error && <p className="text-xs text-error mt-2">{job.error}</p>}
      </div>

      {/* Pair selector */}
      {pairs.length > 1 && (
        <div className="overflow-x-auto">
          <SegmentedControl
            options={pairs.map((p) => ({ value: p, label: p.replace("_", "-").toUpperCase() }))}
            value={selectedPair}
            onChange={setSelectedPair}
            variant="underline"
          />
        </div>
      )}

      {/* Loss curve chart */}
      {currentLossData.length > 0 && (
        <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
          <LossChart data={currentLossData} height={180} />
          {currentProgress && (
            <p className="text-[10px] text-on-surface-variant text-center mt-2">
              Best val: {(() => {
                const best = currentLossData
                  .filter((d) => d.val_loss != null)
                  .sort((a, b) => (a.val_loss ?? Infinity) - (b.val_loss ?? Infinity))[0];
                return best ? `${best.val_loss?.toFixed(4)} @ epoch ${best.epoch}` : "—";
              })()}
            </p>
          )}
        </div>
      )}

      {/* Metrics grid */}
      {currentProgress && (
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: "Train Loss", value: currentProgress.train_loss.toFixed(4) },
            { label: "Val Loss", value: currentProgress.val_loss?.toFixed(4) ?? "—" },
            { label: "Direction Acc", value: currentProgress.direction_acc != null ? `${(currentProgress.direction_acc * 100).toFixed(1)}%` : "—" },
            { label: "Epoch", value: `${currentProgress.epoch}/${currentProgress.total_epochs}` },
          ].map((m) => (
            <div key={m.label} className="bg-surface-container rounded-lg border border-outline-variant/10 p-3 text-center">
              <p className="text-[10px] text-on-surface-variant mb-1">{m.label}</p>
              <p className="text-sm font-mono text-on-surface">{m.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Initializing state */}
      {isRunning && pairs.length === 0 && (
        <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-4 text-center text-sm text-on-surface-variant">
          Training initializing...
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors

---

## Task 9: Frontend — ResultsTab

**Files:**
- Create: `web/src/features/ml/components/ResultsTab.tsx`

- [ ] **Step 1: Create ResultsTab component**

Create `web/src/features/ml/components/ResultsTab.tsx`:

```tsx
import { useState, useMemo } from "react";
import type { MLTrainJob } from "../../../shared/lib/api";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { LossChart } from "./LossChart";
import type { PairResult } from "../types";

interface ResultsTabProps {
  history: MLTrainJob[];
  onSwitchToSetup: () => void;
  /** When set, show this run instead of latest */
  selectedJobId?: string | null;
}

export function ResultsTab({ history, onSwitchToSetup, selectedJobId }: ResultsTabProps) {
  const [compareMode, setCompareMode] = useState(false);
  const [compareBId, setCompareBId] = useState<string>("");
  const [selectedPair, setSelectedPair] = useState<string>("");

  const completedRuns = useMemo(
    () => history.filter((j) => j.status === "completed" && j.result),
    [history],
  );

  const runA = selectedJobId
    ? completedRuns.find((r) => r.job_id === selectedJobId) ?? completedRuns[0]
    : completedRuns[0];

  const runB = compareMode
    ? completedRuns.find((r) => r.job_id === compareBId) ?? null
    : null;

  if (!runA) {
    return (
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-6 text-center">
        <p className="text-sm text-on-surface-variant mb-4">No training results yet</p>
        <button onClick={onSwitchToSetup} className="bg-primary/15 text-primary border border-primary/30 rounded-lg px-4 py-2 text-xs font-medium">
          Go to Setup
        </button>
      </div>
    );
  }

  const resultA = runA.result as Record<string, PairResult>;
  const pairs = Object.keys(resultA);
  const activePair = selectedPair || pairs[0] || "";
  const pairA = resultA[activePair];

  return (
    <div className="space-y-4">
      {/* Header with compare toggle */}
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-headline font-bold uppercase tracking-wider text-on-surface-variant">
          {selectedJobId ? `Run ${runA.job_id}` : "Latest Run"}
        </h2>
        {completedRuns.length >= 2 && (
          <label className="flex items-center gap-2 text-xs text-on-surface-variant cursor-pointer">
            <span>Compare</span>
            <div
              onClick={() => {
                setCompareMode(!compareMode);
                if (!compareBId && completedRuns.length > 1) {
                  setCompareBId(completedRuns[1].job_id);
                }
              }}
              className={`w-9 h-5 rounded-full transition-colors relative cursor-pointer ${compareMode ? "bg-primary" : "bg-surface-container-highest"}`}
            >
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-on-surface transition-transform ${compareMode ? "translate-x-4" : "translate-x-0.5"}`} />
            </div>
          </label>
        )}
      </div>

      {/* Compare mode: run selectors */}
      {compareMode && (
        <div className="flex gap-2">
          <div className="flex-1 bg-surface-container rounded-lg border-2 border-primary/30 p-2">
            <p className="text-[10px] text-primary font-medium mb-1">Run A (Latest)</p>
            <p className="text-xs font-mono text-on-surface-variant">{runA.job_id}</p>
          </div>
          <div className="flex-1 bg-surface-container rounded-lg border-2 border-purple/30 p-2">
            <p className="text-[10px] text-purple font-medium mb-1">Run B</p>
            <select
              value={compareBId}
              onChange={(e) => setCompareBId(e.target.value)}
              className="w-full bg-transparent text-xs font-mono text-on-surface-variant outline-none"
            >
              {completedRuns.filter((r) => r.job_id !== runA.job_id).map((r) => (
                <option key={r.job_id} value={r.job_id}>{r.job_id}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Pair selector */}
      {pairs.length > 1 && (
        <div className="overflow-x-auto">
          <SegmentedControl
            options={pairs.map((p) => ({ value: p, label: p.replace("_", "-").toUpperCase() }))}
            value={activePair}
            onChange={setSelectedPair}
            variant="underline"
          />
        </div>
      )}

      {!compareMode && pairA ? (
        <>
          {/* Performance summary */}
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: "Val Loss", value: pairA.best_val_loss?.toFixed(4) ?? "—" },
              { label: "Dir. Accuracy", value: pairA.direction_accuracy != null ? `${(pairA.direction_accuracy * 100).toFixed(1)}%` : "—" },
              { label: "Samples", value: pairA.total_samples?.toLocaleString() ?? "—" },
            ].map((m) => (
              <div key={m.label} className="bg-surface-container rounded-lg border border-outline-variant/10 p-3 text-center">
                <p className="text-[10px] text-on-surface-variant mb-1">{m.label}</p>
                <p className="text-sm font-mono text-on-surface">{m.value}</p>
              </div>
            ))}
          </div>

          {/* Classification metrics table */}
          {pairA.precision_per_class && pairA.recall_per_class && (
            <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-outline-variant/10">
                    <th className="px-3 py-2 text-left text-on-surface-variant font-medium">Class</th>
                    <th className="px-3 py-2 text-right text-on-surface-variant font-medium">Precision</th>
                    <th className="px-3 py-2 text-right text-on-surface-variant font-medium">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  {([
                    { key: "long" as const, icon: "↑", color: "text-long" },
                    { key: "short" as const, icon: "↓", color: "text-short" },
                    { key: "neutral" as const, icon: "—", color: "text-muted" },
                  ]).map((cls) => (
                    <tr key={cls.key} className="border-b border-outline-variant/10 last:border-b-0">
                      <td className="px-3 py-2">
                        <span className={cls.color}>{cls.icon}</span>
                        <span className="ml-1.5 text-on-surface capitalize">{cls.key}</span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-on-surface">
                        {(pairA.precision_per_class![cls.key] * 100).toFixed(1)}%
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-on-surface">
                        {(pairA.recall_per_class![cls.key] * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Config used */}
          {runA.params && (
            <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
              <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-2 text-on-surface-variant">Config Used</h3>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                {Object.entries(runA.params).map(([key, val]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-on-surface-variant">{key}</span>
                    <span className="font-mono text-on-surface">{typeof val === "number" && val < 1 ? val.toFixed(4) : String(val)}</span>
                  </div>
                ))}
              </div>
              <div className="flex gap-1.5 mt-2 flex-wrap">
                {pairA.flow_data_used && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/15 text-primary">Flow Used</span>
                )}
                {pairA.best_epoch && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant">Best Epoch: {pairA.best_epoch}</span>
                )}
                {pairA.version && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant">v{pairA.version}</span>
                )}
              </div>
            </div>
          )}

          {/* Loss curve from completed result */}
          {pairA.loss_history && pairA.loss_history.length > 0 && (
            <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
              <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-2 text-on-surface-variant">Loss Curve</h3>
              <LossChart data={pairA.loss_history} bestEpoch={pairA.best_epoch} height={180} />
            </div>
          )}
        </>
      ) : compareMode && runB ? (
        <CompareView runA={runA} runB={runB} pair={activePair} />
      ) : compareMode ? (
        <p className="text-xs text-on-surface-variant text-center py-4">Select Run B to compare.</p>
      ) : null}
    </div>
  );
}

function CompareView({ runA, runB, pair }: { runA: MLTrainJob; runB: MLTrainJob; pair: string }) {
  const a = (runA.result as Record<string, PairResult>)?.[pair];
  const b = (runB.result as Record<string, PairResult>)?.[pair];

  if (!a || !b) {
    return <p className="text-xs text-on-surface-variant text-center py-4">Pair not available in both runs.</p>;
  }

  type MetricRow = { label: string; valA: string; valB: string; aWins: boolean | null };

  const metrics: MetricRow[] = [
    {
      label: "Val Loss",
      valA: a.best_val_loss?.toFixed(4) ?? "—",
      valB: b.best_val_loss?.toFixed(4) ?? "—",
      aWins: a.best_val_loss != null && b.best_val_loss != null ? a.best_val_loss < b.best_val_loss : null,
    },
    {
      label: "Dir. Accuracy",
      valA: a.direction_accuracy != null ? `${(a.direction_accuracy * 100).toFixed(1)}%` : "—",
      valB: b.direction_accuracy != null ? `${(b.direction_accuracy * 100).toFixed(1)}%` : "—",
      aWins: a.direction_accuracy != null && b.direction_accuracy != null ? a.direction_accuracy > b.direction_accuracy : null,
    },
    {
      label: "Long Precision",
      valA: a.precision_per_class ? `${(a.precision_per_class.long * 100).toFixed(1)}%` : "—",
      valB: b.precision_per_class ? `${(b.precision_per_class.long * 100).toFixed(1)}%` : "—",
      aWins: a.precision_per_class && b.precision_per_class ? a.precision_per_class.long > b.precision_per_class.long : null,
    },
    {
      label: "Short Precision",
      valA: a.precision_per_class ? `${(a.precision_per_class.short * 100).toFixed(1)}%` : "—",
      valB: b.precision_per_class ? `${(b.precision_per_class.short * 100).toFixed(1)}%` : "—",
      aWins: a.precision_per_class && b.precision_per_class ? a.precision_per_class.short > b.precision_per_class.short : null,
    },
    {
      label: "Best Epoch",
      valA: String(a.best_epoch ?? "—"),
      valB: String(b.best_epoch ?? "—"),
      aWins: null, // Not a "better" metric
    },
    {
      label: "Flow Data",
      valA: a.flow_data_used ? "Yes" : "No",
      valB: b.flow_data_used ? "Yes" : "No",
      aWins: null,
    },
  ];

  const aWinCount = metrics.filter((m) => m.aWins === true).length;
  const bWinCount = metrics.filter((m) => m.aWins === false).length;
  const totalComparable = metrics.filter((m) => m.aWins !== null).length;

  // Config diff
  const paramsA = runA.params || {};
  const paramsB = runB.params || {};
  const allKeys = [...new Set([...Object.keys(paramsA), ...Object.keys(paramsB)])];
  const diffs = allKeys.filter((k) => (paramsA as any)[k] !== (paramsB as any)[k]);

  return (
    <div className="space-y-4">
      {/* Metrics comparison table */}
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-outline-variant/10">
              <th className="px-3 py-2 text-left text-on-surface-variant font-medium">Metric</th>
              <th className="px-3 py-2 text-right font-medium text-primary">Run A</th>
              <th className="px-3 py-2 text-right font-medium text-purple">Run B</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m.label} className="border-b border-outline-variant/10 last:border-b-0">
                <td className="px-3 py-2 text-on-surface-variant">{m.label}</td>
                <td className={`px-3 py-2 text-right font-mono ${m.aWins === true ? "text-primary font-bold" : "text-on-surface"}`}>
                  {m.valA}
                </td>
                <td className={`px-3 py-2 text-right font-mono ${m.aWins === false ? "text-purple font-bold" : "text-on-surface"}`}>
                  {m.valB}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Config diff */}
      {diffs.length > 0 && (
        <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
          <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-2 text-on-surface-variant">Config Differences</h3>
          <div className="space-y-1 text-xs">
            {diffs.map((key) => (
              <div key={key} className="flex justify-between">
                <span className="text-on-surface-variant">{key}</span>
                <div className="flex gap-3">
                  <span className="font-mono text-primary">{String((paramsA as any)[key] ?? "—")}</span>
                  <span className="text-on-surface-variant">vs</span>
                  <span className="font-mono text-purple">{String((paramsB as any)[key] ?? "—")}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      <p className="text-xs text-on-surface-variant text-center">
        Run A wins on {aWinCount}/{totalComparable} metrics.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors

---

## Task 10: Frontend — HistoryTab

**Files:**
- Create: `web/src/features/ml/components/HistoryTab.tsx`

- [ ] **Step 1: Create HistoryTab component**

Create `web/src/features/ml/components/HistoryTab.tsx`:

```tsx
import { useState } from "react";
import type { MLTrainJob } from "../../../shared/lib/api";
import { StatusBadge } from "./shared";
import type { PairResult } from "../types";

interface HistoryTabProps {
  history: MLTrainJob[];
  onViewDetails: (jobId: string) => void;
  onRetrain: (jobId: string) => void;
  onDelete: (jobId: string) => void;
}

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function HistoryTab({ history, onViewDetails, onRetrain, onDelete }: HistoryTabProps) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (history.length === 0) {
    return (
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-6 text-center">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-on-surface-variant mx-auto mb-3">
          <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-sm text-on-surface-variant mb-4">No training history yet</p>
        <p className="text-xs text-on-surface-variant">Completed training jobs will appear here</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {history.map((job) => {
        const result = job.result as Record<string, PairResult> | undefined;
        const isCompleted = job.status === "completed";
        const isFailed = job.status === "failed";

        // Aggregate best metrics across pairs for summary
        let bestValLoss: number | null = null;
        let bestDirAcc: number | null = null;
        if (isCompleted && result) {
          for (const r of Object.values(result)) {
            if (bestValLoss === null || r.best_val_loss < bestValLoss) bestValLoss = r.best_val_loss;
            if (r.direction_accuracy != null && (bestDirAcc === null || r.direction_accuracy > bestDirAcc)) {
              bestDirAcc = r.direction_accuracy;
            }
          }
        }

        const pairCount = result ? Object.keys(result).length : 0;
        const presetLabel = (job as any).preset_label as string | undefined;
        const configSummary = job.params
          ? `${presetLabel ? presetLabel + " · " : ""}${job.params.timeframe ?? "—"} · ${job.params.epochs ?? "—"}ep · ${pairCount}p`
          : "";

        return (
          <div key={job.job_id} className="bg-surface-container rounded-lg border border-outline-variant/10 px-3 py-2.5">
            {/* Row 1: Status + job ID + time */}
            <div className="flex items-center gap-2 mb-1">
              <StatusBadge status={job.status} />
              <span className="text-[10px] font-mono text-on-surface-variant flex-1 truncate">{job.job_id}</span>
              {job.created_at && (
                <span className="text-[10px] text-on-surface-variant shrink-0">{timeAgo(job.created_at)}</span>
              )}
            </div>

            {/* Row 2: Config summary + metrics */}
            <div className="flex items-center justify-between text-[10px] text-on-surface-variant">
              <span>{configSummary}</span>
              {isCompleted && (
                <span className="font-mono">
                  {bestValLoss != null && <span>val: {bestValLoss.toFixed(4)}</span>}
                  {bestDirAcc != null && <span className="ml-2">acc: {(bestDirAcc * 100).toFixed(1)}%</span>}
                </span>
              )}
            </div>

            {/* Error message */}
            {isFailed && job.error && (
              <p className="text-[10px] text-error mt-1 truncate">{job.error}</p>
            )}

            {/* Action buttons */}
            <div className="flex gap-3 mt-2">
              {isCompleted && (
                <button
                  onClick={() => onViewDetails(job.job_id)}
                  className="text-[10px] text-primary hover:underline"
                >
                  View Details
                </button>
              )}
              {isCompleted && job.params && (
                <button
                  onClick={() => onRetrain(job.job_id)}
                  className="text-[10px] text-primary hover:underline"
                >
                  Retrain
                </button>
              )}
              <button
                onClick={() => setConfirmDeleteId(job.job_id)}
                className="text-[10px] text-error hover:underline"
              >
                Delete
              </button>
            </div>

            {/* Delete confirmation */}
            {confirmDeleteId === job.job_id && (
              <div className="mt-2 bg-error/5 border border-error/20 rounded p-2 flex items-center justify-between">
                <span className="text-[10px] text-error">Delete this run?</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => setConfirmDeleteId(null)}
                    className="text-[10px] text-on-surface-variant hover:text-on-surface"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => {
                      onDelete(job.job_id);
                      setConfirmDeleteId(null);
                    }}
                    className="text-[10px] text-error font-medium hover:underline"
                  >
                    Confirm
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors

---

## Task 11: Frontend — MLTrainingView Shell Rewrite

**Files:**
- Rewrite: `web/src/features/ml/components/MLTrainingView.tsx`

- [ ] **Step 1: Rewrite MLTrainingView as orchestration shell**

Replace the entire contents of `web/src/features/ml/components/MLTrainingView.tsx`:

```tsx
import { useState, useEffect, useRef } from "react";
import { api, type MLTrainRequest, type MLTrainJob, type MLStatus, type MLBackfillJob } from "../../../shared/lib/api";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { SetupTab } from "./SetupTab";
import { TrainingTab } from "./TrainingTab";
import { ResultsTab } from "./ResultsTab";
import { HistoryTab } from "./HistoryTab";
import type { MLTab } from "../types";

export function MLTrainingView() {
  const currentTrainingParamsRef = useRef<MLTrainRequest | null>(null);
  const [tab, setTab] = useState<MLTab>("setup");
  const [status, setStatus] = useState<MLStatus | null>(null);
  const [trainingJob, setTrainingJob] = useState<MLTrainJob | null>(null);
  const [backfillJob, setBackfillJob] = useState<MLBackfillJob | null>(null);
  const [history, setHistory] = useState<MLTrainJob[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [restoredParams, setRestoredParams] = useState<MLTrainRequest | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [activePresetLabel, setActivePresetLabel] = useState<string | null>(null);

  // Handlers
  async function handleStartTraining(params: MLTrainRequest, presetLabel?: string | null) {
    try {
      if (!params.timeframe) throw new Error("Timeframe is required");
      if ((params.lookback_days ?? 0) < 1) throw new Error("Lookback days must be at least 1");
      if ((params.epochs ?? 0) < 1) throw new Error("Epochs must be at least 1");
      if ((params.batch_size ?? 0) < 1) throw new Error("Batch size must be at least 1");

      currentTrainingParamsRef.current = params;
      setActivePresetLabel(presetLabel ?? null);
      setError(null);
      setRestoredParams(null);
      const response = await api.startMLTraining(params);
      setTrainingJob({ job_id: response.job_id, status: "running" as const });
      setTab("training");
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Failed to start training"));
    }
  }

  async function handleCancelTraining() {
    if (!trainingJob) return;
    try {
      setError(null);
      await api.cancelMLTraining(trainingJob.job_id);
      setTrainingJob({ ...trainingJob, status: "cancelled" });
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Failed to cancel training"));
    }
  }

  async function handleStartBackfill(params: { timeframe: string; lookback_days: number }) {
    try {
      if (!params.timeframe) throw new Error("Timeframe is required");
      if (params.lookback_days < 1) throw new Error("Lookback days must be at least 1");
      setError(null);
      const response = await api.startMLBackfill(params);
      setBackfillJob({ job_id: response.job_id, status: "running" as const });
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Failed to start backfill"));
    }
  }

  function handleCancelBackfill() {
    setBackfillJob(backfillJob ? { ...backfillJob, status: "cancelled" as const } : null);
  }

  // Load ML status on mount
  useEffect(() => {
    api.getMLStatus().then(setStatus).catch(() => {});
  }, []);

  // Load history from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("ml_training_history");
    if (saved) {
      try { setHistory(JSON.parse(saved)); } catch { /* ignore */ }
    }
  }, []);

  // Poll for backfill progress
  useEffect(() => {
    if (!backfillJob || backfillJob.status !== "running") return;
    const interval = setInterval(async () => {
      try {
        const updated = await api.getMLBackfillStatus(backfillJob.job_id);
        setBackfillJob(updated as MLBackfillJob);
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [backfillJob?.job_id, backfillJob?.status]);

  return (
    <div className="p-3 space-y-4">
      {/* Error display */}
      {error && (
        <div className="bg-error/10 border border-error/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-error mt-0.5 shrink-0">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <div className="flex-1">
            <p className="text-xs text-error font-medium">Error</p>
            <p className="text-[10px] text-error/80 mt-0.5">{error.message}</p>
            <button onClick={() => setError(null)} className="text-[10px] text-error/60 hover:text-error underline">
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <SegmentedControl
        options={[
          { value: "setup" as MLTab, label: "Setup" },
          { value: "training" as MLTab, label: "Training" },
          { value: "results" as MLTab, label: "Results" },
          { value: "history" as MLTab, label: "History" },
        ]}
        value={tab}
        onChange={setTab}
        fullWidth
      />

      {/* Tab Content */}
      {tab === "setup" && (
        <SetupTab
          status={status}
          onStartTraining={handleStartTraining}
          trainingJob={trainingJob}
          initialConfig={restoredParams}
          backfillJob={backfillJob}
          onStartBackfill={handleStartBackfill}
          onCancelBackfill={handleCancelBackfill}
        />
      )}
      {tab === "training" && (
        <TrainingTab
          job={trainingJob}
          onCancel={handleCancelTraining}
          onComplete={(job: MLTrainJob) => {
            setTrainingJob(null);
            saveToHistory(job, currentTrainingParamsRef.current, activePresetLabel);
          }}
          onSwitchToSetup={() => setTab("setup")}
          presetLabel={activePresetLabel}
          configSummary={currentTrainingParamsRef.current ? `${currentTrainingParamsRef.current.timeframe} · ${currentTrainingParamsRef.current.epochs}ep` : null}
        />
      )}
      {tab === "results" && (
        <ResultsTab
          history={history}
          onSwitchToSetup={() => setTab("setup")}
          selectedJobId={selectedResultId}
        />
      )}
      {tab === "history" && (
        <HistoryTab
          history={history}
          onViewDetails={(jobId: string) => {
            setSelectedResultId(jobId);
            setTab("results");
          }}
          onRetrain={(jobId: string) => {
            const job = history.find((j) => j.job_id === jobId);
            if (job?.params) {
              setRestoredParams(job.params);
              setTab("setup");
            }
          }}
          onDelete={(jobId: string) => {
            setHistory((h) => {
              const updated = h.filter((j) => j.job_id !== jobId);
              saveHistoryToStorage(updated);
              return updated;
            });
          }}
        />
      )}
    </div>
  );

  function saveToHistory(job: MLTrainJob, params: MLTrainRequest | null, presetLabel?: string | null) {
    const jobWithMeta = { ...job, created_at: new Date().toISOString(), params: params || undefined, preset_label: presetLabel || undefined } as MLTrainJob & { preset_label?: string };
    setHistory((prev) => {
      const updated = [jobWithMeta, ...prev].slice(0, 50);
      saveHistoryToStorage(updated);
      return updated;
    });
  }
}

function saveHistoryToStorage(history: MLTrainJob[]) {
  localStorage.setItem("ml_training_history", JSON.stringify(history));
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No new errors

- [ ] **Step 3: Verify dev server starts**

Run: `cd web && pnpm dev` (check it renders without runtime errors)
Expected: Page loads, Setup tab shows presets, sliders, data readiness section

---

## Task 12: Frontend — Update Tests

**Files:**
- Rewrite: `web/src/features/ml/components/__tests__/MLTrainingView.test.tsx`

- [ ] **Step 1: Rewrite tests for new tab structure**

Replace the entire contents of `web/src/features/ml/components/__tests__/MLTrainingView.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { MLTrainingView } from "../MLTrainingView";
import { api } from "../../../../shared/lib/api";

vi.mock("../../../../shared/lib/api", () => ({
  api: {
    getMLStatus: vi.fn(),
    getMLDataReadiness: vi.fn(),
    startMLTraining: vi.fn(),
    getMLTrainingStatus: vi.fn(),
    cancelMLTraining: vi.fn(),
    startMLBackfill: vi.fn(),
    getMLBackfillStatus: vi.fn(),
  },
}));

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    clear: vi.fn(() => { store = {}; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    get length() { return Object.keys(store).length; },
    key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

describe("MLTrainingView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    vi.mocked(api.getMLStatus).mockResolvedValue({ ml_enabled: true, loaded_pairs: [] });
    vi.mocked(api.getMLDataReadiness).mockResolvedValue({
      "BTC-USDT-SWAP": { count: 8760, oldest: "2025-03-22T00:00:00Z", sufficient: true },
      "ETH-USDT-SWAP": { count: 500, oldest: "2025-06-01T00:00:00Z", sufficient: true },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function renderAndSettle() {
    let result: ReturnType<typeof render>;
    await act(async () => {
      result = render(<MLTrainingView />);
    });
    return result!;
  }

  describe("Initial State", () => {
    it("should render new tab structure (Setup, Training, Results, History)", async () => {
      await renderAndSettle();

      expect(screen.getByText("Setup")).toBeInTheDocument();
      expect(screen.getByText("Training")).toBeInTheDocument();
      expect(screen.getByText("Results")).toBeInTheDocument();
      expect(screen.getByText("History")).toBeInTheDocument();
    });

    it("should load ML status on mount", async () => {
      await renderAndSettle();
      expect(api.getMLStatus).toHaveBeenCalledOnce();
    });

    it("should fetch data readiness on mount", async () => {
      await renderAndSettle();
      expect(api.getMLDataReadiness).toHaveBeenCalledWith("1h");
    });
  });

  describe("Setup Tab", () => {
    it("should render preset bar", async () => {
      await renderAndSettle();

      expect(screen.getByText("Quick Test")).toBeInTheDocument();
      expect(screen.getByText("Balanced")).toBeInTheDocument();
      expect(screen.getByText("Production")).toBeInTheDocument();
    });

    it("should render config sliders", async () => {
      await renderAndSettle();

      expect(screen.getByText("Timeframe")).toBeInTheDocument();
      expect(screen.getByText("Lookback Days")).toBeInTheDocument();
      expect(screen.getByText("Epochs")).toBeInTheDocument();
    });

    it("should show confirmation dialog when Start Training is clicked", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Start Training"));
      });

      expect(screen.getByText("Confirm Training")).toBeInTheDocument();
    });
  });

  describe("Training Tab", () => {
    it("should show empty state when no job is active", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Training"));
      });

      expect(screen.getByText("No active training job")).toBeInTheDocument();
    });
  });

  describe("Results Tab", () => {
    it("should show empty state when no completed runs exist", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Results"));
      });

      expect(screen.getByText("No training results yet")).toBeInTheDocument();
    });
  });

  describe("History Tab", () => {
    it("should display empty state when no history", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      expect(screen.getByText("No training history yet")).toBeInTheDocument();
    });

    it("should display job entries when history exists", async () => {
      const mockHistory = [
        {
          job_id: "test-job-1",
          status: "completed",
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
      localStorageMock.getItem.mockReturnValue(JSON.stringify(mockHistory));

      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      expect(screen.getByText("test-job-1")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });

    it("should navigate to Results when View Details is clicked", async () => {
      const mockHistory = [
        {
          job_id: "test-job-1",
          status: "completed",
          result: {
            "BTC-USDT": {
              best_epoch: 10, best_val_loss: 0.5, total_epochs: 100,
              total_samples: 1000, flow_data_used: false,
            },
          },
          created_at: new Date().toISOString(),
          params: { timeframe: "1h", lookback_days: 365, epochs: 100 },
        },
      ];
      localStorageMock.getItem.mockReturnValue(JSON.stringify(mockHistory));

      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      await act(async () => {
        fireEvent.click(screen.getByText("View Details"));
      });

      // Should now be on Results tab showing that run
      expect(screen.getByText("Run test-job-1")).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run the tests**

Run: `cd web && npx vitest run src/features/ml/components/__tests__/MLTrainingView.test.tsx`
Expected: All PASS

- [ ] **Step 3: Run full frontend test suite for regressions**

Run: `cd web && npx vitest run`
Expected: All PASS (or same pass/fail as before our changes)

---

## Task 13: Final Verification

- [ ] **Step 1: Run full backend test suite**

Run: `docker exec krypton-api-1 python -m pytest -v`
Expected: All PASS

- [ ] **Step 2: Run full frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 3: Manual smoke test**

Open the dev server (`pnpm dev`), navigate to ML Training:
- Setup tab: presets toggle config values, data readiness bars load, backfill works inline
- Training tab: shows empty state, starts training when triggered from Setup
- Results tab: shows empty state (or results if training completed)
- History tab: shows previous runs, View Details navigates to Results

- [ ] **Step 4: Final commit (squash if desired)**

```bash
git add -A
git commit -m "feat: ML training page redesign — workflow tabs, loss chart, data readiness, presets, metrics, compare mode"
```
