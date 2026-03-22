# ML Training Page Redesign

## Overview

Redesign the ML Training page from a basic form-driven 4-tab layout into a workflow-oriented experience with training visualization, data readiness checks, hyperparameter presets, richer metrics, model comparison, and proper file decomposition.

## Current State

Single 929-line file (`MLTrainingView.tsx`) with 4 tabs: Configure, Training, History, Backfill. Training shows text-only metrics. History stored in localStorage. No loss curve visualization. No data readiness indicator. No presets. No model comparison. Backfill in its own tab despite being a pre-training step.

## Design Decisions

- **Tab structure**: Merge Configure + Backfill into "Setup" tab. Add "Results" tab for detailed metrics + comparison. New tabs: Setup, Training, Results, History.
- **Loss chart**: Custom `<canvas>` component (~80 lines, zero deps). Reusing `lightweight-charts` is overkill for two lines.
- **Metrics depth**: Moderate — direction accuracy + precision/recall per class (long/short/neutral). No confusion matrix or holdout test set.
- **Presets**: Three profiles (Quick Test, Balanced, Production). No custom save — "Retrain" from history covers that use case.
- **Page structure**: Approach B (Merged Flow) — natural workflow order without the rigidity of a wizard.

## Tab Designs

### Setup Tab (merged Configure + Backfill)

Top-to-bottom layout:

1. **Preset bar** — Uses `SegmentedControl` (pill variant, fullWidth) with three options: Quick Test, Balanced, Production. Selecting one fills all config sliders. Further manual slider changes are preserved until a different preset is selected. SegmentedControl already enforces 44px min touch targets and haptic feedback.
   - Quick Test: 30 epochs, batch=32, hidden=64, layers=1, seq_len=25, dropout=0.2, lr=0.003
   - Balanced: 100 epochs, batch=64, hidden=128, layers=2, seq_len=50, dropout=0.3, lr=0.001
   - Production: 300 epochs, batch=128, hidden=256, layers=3, seq_len=100, dropout=0.3, lr=0.0005

2. **Data readiness section** — Shows candle count per pair for the currently selected timeframe. Progress bars with dual indicators: green bar + checkmark icon when sufficient (>=100 candles), red/error bar + warning icon when insufficient (never rely on color alone). Numeric candle count shown as text beside each bar. "Backfill Now" button appears only when a pair has insufficient data. Fetches from new backend endpoint on mount and on timeframe change. Shows skeleton shimmer while loading. On fetch error, shows inline error message with retry button. Requires new backend endpoint.

3. **Data parameters** — Timeframe selector (15m/1h/4h), Lookback Days slider, Label Horizon slider, Label Threshold % slider. Same controls as current.

4. **Model parameters** — Epochs, Batch Size, Hidden Size, Num Layers, Sequence Length, Dropout, Learning Rate sliders. Same controls as current.

5. **Backfill section (inline)** — Uses the timeframe + lookback days already configured above. "Start Backfill" button. When running, shows per-pair progress with:
   - Progress bar calculated as `fetched / (lookback_days * candles_per_day)` where candles_per_day is a frontend constant: 96 for 15m, 24 for 1h, 6 for 4h
   - ETA estimated from elapsed rate (show "Estimating..." until >=10% progress for accuracy)
   - Per-pair status: spinner for active, checkmark for done
   - Auto-refreshes data readiness bars on completion

6. **Action buttons** — Sticky bar at bottom of viewport with safe-area padding. Contains Reset to Defaults (text/secondary) and Start Training (primary filled). Confirmation dialog same as current. Sticky position ensures the CTA is always reachable without scrolling past all config sections on mobile.

### Training Tab

When no job is active: empty state with "Configure Training" button (same as current).

When a job is running:

1. **Job header** — Pulsing indicator, job ID, status badge, preset name + config summary, cancel button.

2. **Loss curve chart** — Custom canvas component. Two lines: train loss (accent/#0EB5E5, solid) and val loss (long/#2DD4A0, dashed) over epochs. Uses theme tokens, not hardcoded colors. Y-axis: loss values. X-axis: epoch numbers. Updates live every 3s poll cycle. Shows "Best val: X @ epoch Y" text below the chart.

3. **Pair selector** — `SegmentedControl` (underline variant) to switch the chart between pairs. Horizontally scrollable if pairs exceed viewport width. Auto-advances to whichever pair is currently training.

4. **Metrics grid** — 2x2 card layout: Train Loss, Val Loss, Direction Accuracy, Best Epoch. Updated live.

The loss curve data comes from accumulating per-epoch progress reports. The component stores `{epoch, train_loss, val_loss}[]` in local state and appends on each poll.

### Results Tab

When no completed runs exist: empty state with "No training results yet" message and a "Go to Setup" button that navigates to the Setup tab.

**Default view (latest run):**

1. **Pair selector** — Same tab style as Training tab.

2. **Performance summary** — 3-column grid: Val Loss, Direction Accuracy, Total Samples.

3. **Classification metrics table** — Rows for Long, Short, Neutral. Columns for Precision and Recall. Each row has a directional icon alongside the label: arrow-up for Long (long/#2DD4A0), arrow-down for Short (short/#FB7185), dash for Neutral (muted/#8E9AAD). Color supplements the icon+text, never the sole indicator.

4. **Config used** — 2-column grid showing all hyperparameters. Tags for Flow Used, best epoch, model version.

5. **Final loss curve** — Same LossChart component, but rendering the complete loss_history from the result (not live data).

**Compare mode:**

Toggle switch in the header. When enabled:

1. **Run selectors** — Run A is always the latest (primary/#8B9AFF border). Run B is selectable from a dropdown of history entries (purple/#A78BFA border). Both use theme tokens.

2. **Metrics comparison table** — Rows: Val Loss, Dir. Accuracy, Long Precision, Short Precision, Best Epoch, Flow Data. Columns: Run A, Run B. Winning metric highlighted with color + bold.

3. **Config diff** — Only shows parameters that differ between the two runs.

4. **Summary line** — "Run A wins on X/Y metrics."

### History Tab

Compact list (no cards, denser layout). Each row:

- Status badge (completed/failed/cancelled), job ID (monospace), relative timestamp ("2h ago")
- Config summary line: preset name, timeframe, epochs, pair count
- Key metrics inline: val loss + direction accuracy (for completed jobs)
- Error message (for failed jobs)
- Action buttons: View Details (navigates to Results tab with that run loaded), Retrain (restores config to Setup tab), Delete (with confirmation dialog before removing)

## File Structure

Split the monolith into focused files:

```
web/src/features/ml/
  components/
    MLTrainingView.tsx    — Shell: tab state, job state, handlers, orchestration (~120 lines)
    SetupTab.tsx          — Presets, data readiness, config sliders, inline backfill (~200 lines)
    TrainingTab.tsx       — Live progress, loss chart, pair selector, metrics grid (~150 lines)
    ResultsTab.tsx        — Detailed metrics, compare mode, config display (~200 lines)
    HistoryTab.tsx        — Compact job list with actions (~100 lines)
    LossChart.tsx         — Custom canvas line chart component (~80 lines)
    shared.tsx            — SettingsSection, ConfigField, Select, Slider components (~80 lines)
  types.ts               — ML-specific types (extracted from api.ts)
  presets.ts              — Quick Test / Balanced / Production config objects
```

## LossChart Component

Canvas-based line chart. Props:
```ts
interface LossChartProps {
  data: { epoch: number; train_loss: number; val_loss: number }[];
  bestEpoch?: number;
  height?: number;
}
```

Renders:
- Two polylines with anti-aliased drawing: train loss (accent/#0EB5E5, solid line) and val loss (long/#2DD4A0, dashed line). Distinct line styles ensure colorblind accessibility — never rely on color alone.
- Y-axis: auto-scaled to data range with 3-4 tick labels
- X-axis: epoch numbers
- Optional vertical dashed line at bestEpoch (muted/#8E9AAD, dotted — visually distinct from val's dashes)
- Legend in top-right corner showing line style + color + label for each series
- Responsive width (fills container)
- Canvas element gets a dynamic `aria-label` summarizing the key insight (e.g., "Loss chart: best validation loss 0.032 at epoch 47 of 100")

No animation or zoom. Simple, static chart that re-renders when data changes. Uses `useRef` for canvas + `useEffect` to draw.

## Backend Changes

### New endpoint: `GET /api/ml/data-readiness`

Query params: `timeframe` (required)

Returns per-pair candle counts:
```json
{
  "BTC-USDT-SWAP": {"count": 8760, "oldest": "2025-03-22T00:00:00Z", "sufficient": true},
  "ETH-USDT-SWAP": {"count": 8744, "oldest": "2025-03-23T00:00:00Z", "sufficient": true},
  "WIF-USDT-SWAP": {"count": 312, "oldest": "2026-03-09T00:00:00Z", "sufficient": true}
}
```

`sufficient` is true when count >= 100 (minimum for training). Implementation: single SQL query with `COUNT(*)` and `MIN(timestamp)` grouped by pair, filtered by timeframe.

### Enriched trainer results

Add to the dict returned by `Trainer.train()`:

```python
{
    # Existing fields
    "best_epoch": int,
    "best_val_loss": float,
    "train_loss": list[float],  # already exists (per-epoch)
    "val_loss": list[float],    # already exists (per-epoch)
    # New fields
    "direction_accuracy": float,           # overall accuracy on val set
    "precision_per_class": {               # precision for each direction class
        "long": float,
        "short": float,
        "neutral": float,
    },
    "recall_per_class": {                  # recall for each direction class
        "long": float,
        "short": float,
        "neutral": float,
    },
    "loss_history": list[{                 # for Results tab loss curve
        "epoch": int,
        "train_loss": float,
        "val_loss": float,
    }],
}
```

These are computed at the end of training from validation set predictions at the best epoch checkpoint. Uses manual computation (no sklearn dependency — compute precision/recall from prediction counts directly).

### Update `pair_results` construction in `ml.py`

The `_run()` function in `ml.py` (lines 178-185) explicitly cherry-picks fields from the trainer result. This must be updated to forward the new fields:

```python
pair_results[pair] = {
    "best_epoch": pair_result["best_epoch"],
    "best_val_loss": pair_result["best_val_loss"],
    "total_epochs": len(pair_result["train_loss"]),
    "total_samples": len(features),
    "flow_data_used": flow_used,
    "version": pair_result.get("version"),
    # New fields
    "direction_accuracy": pair_result.get("direction_accuracy"),
    "precision_per_class": pair_result.get("precision_per_class"),
    "recall_per_class": pair_result.get("recall_per_class"),
    "loss_history": pair_result.get("loss_history"),
}
```

Without this change, the new trainer fields would be silently dropped and the Results tab would have no data.

### Enriched progress callback

Add `direction_acc` to per-epoch progress dict so the Training tab can display it live:

```python
{
    "epoch": int,
    "total_epochs": int,
    "train_loss": float,
    "val_loss": float,
    "direction_acc": float,  # new
}
```

### Propagation through the API

The `pair_results` dict construction in `ml.py:_run()` must be updated (see section above) to forward new fields. Once in `pair_results`, they flow through `GET /api/ml/train/{job_id}` automatically since that endpoint returns the full job dict.

The frontend `MLTrainResult` type in `api.ts` needs updating to include the new fields.

## Frontend Type Changes

Update `api.ts`:

```ts
export interface MLTrainProgress {
  epoch: number;
  total_epochs: number;
  train_loss: number;
  val_loss: number;
  direction_acc?: number;  // new
}

export interface MLTrainResult {
  best_epoch: number;
  best_val_loss: number;
  total_epochs: number;
  total_samples: number;
  flow_data_used: boolean;
  version?: string;
  // New fields
  direction_accuracy?: number;
  precision_per_class?: { long: number; short: number; neutral: number };
  recall_per_class?: { long: number; short: number; neutral: number };
  loss_history?: { epoch: number; train_loss: number; val_loss: number }[];
}
```

Optional fields for backwards compatibility with existing localStorage history entries.

## No DB Schema Changes

All new data flows through the existing in-memory job dict on the backend and localStorage on the frontend. No new tables or columns needed.
