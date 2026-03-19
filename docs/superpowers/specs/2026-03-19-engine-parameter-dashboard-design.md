# Engine Parameter Dashboard & Backtest Optimization UI

**Date:** 2026-03-19
**Status:** Draft

## Problem

The signal engine has 60+ tunable parameters spread across three sources (env config, DB tables, hardcoded constants). These parameters are tuned via backtesting but are invisible to the frontend. The user cannot see what the engine is using, cannot understand why signals fire the way they do, and must use direct DB access or env vars to adjust parameters after optimization.

## Goals

1. **Full parameter visibility** -- Read-only dashboard showing every engine parameter, grouped by category, with source annotations
2. **Per-signal parameter snapshots** -- Each signal records the parameter state at generation time, viewable from the signal card
3. **Backtest-driven optimization loop** -- UI to run backtests with parameter overrides, trigger automated optimization (regime weights, ATR multipliers), compare results, and apply winning configs
4. **Diff-based apply** -- Before applying optimized parameters, show a side-by-side diff of current vs proposed values with confirmation

## Non-Goals

- Real-time parameter streaming or polling
- Parameter version history or rollback (beyond git)
- Restricting the apply endpoint to backtest-originated changes only (the UI guides the workflow, but the API accepts any valid parameter changes)

---

## Backend Changes

### 1. Promote Env-Only Parameters to DB-Overridable

Currently, source weights (`engine_traditional_weight`, `engine_flow_weight`, etc.), LLM factor weights, ML threshold, and LLM threshold are env-only. These need to become runtime-mutable.

**Approach:** Add nullable columns to `PipelineSettings` for each promotable parameter. The env value remains the default; if the DB column is non-null, it overrides.

**Config resolution chain:** DB non-null > env var > hardcoded default in `Settings` model.

This differs from the existing `PipelineSettings` columns (e.g., `mean_rev_rsi_steepness`) which are NOT NULL with defaults. The nullable pattern is used here specifically because these are *overrides* of env values -- `None` means "use the env/default value." Existing NOT NULL columns remain unchanged.

New `PipelineSettings` columns (all nullable):
- `traditional_weight: float | None`
- `flow_weight: float | None`
- `onchain_weight: float | None`
- `pattern_weight: float | None`
- `ml_blend_weight: float | None` -- the weight used in `blend_with_ml()` after preliminary scoring, distinct from the 4 outer source weights above
- `ml_confidence_threshold: float | None`
- `llm_threshold: int | None`
- `llm_factor_weights: dict | None` (JSONB)
- `llm_factor_total_cap: float | None`
- `confluence_max_score: int | None`

The config resolution logic in `main.py` pipeline startup already loads `PipelineSettings` -- extend it to check these new columns and override the corresponding `app.state.settings` fields before starting pipeline tasks.

### 2. New Endpoint: `GET /api/engine/parameters`

Returns the full engine parameter set assembled from all sources, organized into categories. Each parameter value is annotated with `source`: either `"hardcoded"` (immutable, only changes with code deploys) or `"configurable"` (runtime-mutable via DB).

**Implementation:** A new module `backend/app/api/engine.py` with a router. The handler reads from `app.state.settings`, queries `PipelineSettings`, `RegimeWeights`, and `PerformanceTrackerRow` tables.

For hardcoded constants: rather than scraping module-level variables from 6+ engine modules, create a `backend/app/engine/constants.py` module that centralizes all hardcoded engine constants into a single dict-returning function (`get_engine_constants() -> dict`). The engine modules import from this central location. This avoids fragile import-and-read logic in the API handler and provides a single place to maintain the constant registry.

**Response structure:**

```json
{
  "technical": {
    "indicator_periods": {
      "adx": { "value": 14, "source": "hardcoded" },
      "rsi": { "value": 14, "source": "hardcoded" },
      "sma": { "value": 20, "source": "hardcoded" },
      "bb_std": { "value": 2, "source": "hardcoded" },
      "ema_spans": { "value": [9, 21, 50], "source": "hardcoded" },
      "obv_slope_window": { "value": 10, "source": "hardcoded" },
      "bb_width_percentile_window": { "value": 50, "source": "hardcoded" }
    },
    "sigmoid_params": {
      "trend_strength_center": { "value": 20, "source": "hardcoded" },
      "trend_strength_steepness": { "value": 0.25, "source": "hardcoded" },
      "vol_expansion_center": { "value": 50, "source": "hardcoded" },
      "vol_expansion_steepness": { "value": 0.08, "source": "hardcoded" },
      "trend_score_steepness": { "value": 0.30, "source": "hardcoded" },
      "obv_slope_steepness": { "value": 4, "source": "hardcoded" },
      "volume_ratio_steepness": { "value": 3.0, "source": "hardcoded" }
    },
    "mean_reversion": {
      "rsi_steepness": { "value": 0.25, "source": "configurable" },
      "bb_pos_steepness": { "value": 10.0, "source": "configurable" },
      "squeeze_steepness": { "value": 0.10, "source": "configurable" },
      "blend_ratio": { "value": 0.6, "source": "configurable" }
    }
  },
  "order_flow": {
    "max_scores": {
      "funding": { "value": 35, "source": "hardcoded" },
      "oi": { "value": 20, "source": "hardcoded" },
      "ls_ratio": { "value": 35, "source": "hardcoded" }
    },
    "sigmoid_steepnesses": {
      "funding": { "value": 8000, "source": "hardcoded" },
      "oi": { "value": 65, "source": "hardcoded" },
      "ls_ratio": { "value": 6, "source": "hardcoded" }
    },
    "regime_params": {
      "trending_floor": { "value": 0.3, "source": "hardcoded" },
      "roc_threshold": { "value": 0.0005, "source": "hardcoded" },
      "roc_steepness": { "value": 8000, "source": "hardcoded" },
      "ls_roc_scale": { "value": 0.003, "source": "hardcoded" },
      "recent_window": { "value": 3, "source": "hardcoded" },
      "baseline_window": { "value": 7, "source": "hardcoded" }
    }
  },
  "onchain": {
    "btc_profile": {
      "netflow_normalization": { "value": 3000, "source": "hardcoded" },
      "whale_baseline": { "value": 3, "source": "hardcoded" },
      "max_scores": {
        "netflow": { "value": 35, "source": "hardcoded" },
        "whale": { "value": 20, "source": "hardcoded" },
        "addresses": { "value": 15, "source": "hardcoded" },
        "nupl": { "value": 15, "source": "hardcoded" },
        "hashrate": { "value": 15, "source": "hardcoded" }
      }
    },
    "eth_profile": {
      "netflow_normalization": { "value": 50000, "source": "hardcoded" },
      "whale_baseline": { "value": 5, "source": "hardcoded" },
      "max_scores": {
        "netflow": { "value": 35, "source": "hardcoded" },
        "whale": { "value": 20, "source": "hardcoded" },
        "addresses": { "value": 15, "source": "hardcoded" },
        "staking": { "value": 15, "source": "hardcoded" },
        "gas": { "value": 15, "source": "hardcoded" }
      }
    }
  },
  "blending": {
    "source_weights": {
      "traditional": { "value": 0.40, "source": "configurable" },
      "flow": { "value": 0.22, "source": "configurable" },
      "onchain": { "value": 0.23, "source": "configurable" },
      "pattern": { "value": 0.15, "source": "configurable" }
    },
    "ml_blend_weight": { "value": 0.25, "source": "configurable" },
    "thresholds": {
      "signal": { "value": 40, "source": "configurable" },
      "llm": { "value": 20, "source": "configurable" },
      "ml_confidence": { "value": 0.65, "source": "configurable" }
    },
    "llm_factor_weights": {
      "support_proximity": { "value": 6.0, "source": "configurable" },
      "resistance_proximity": { "value": 6.0, "source": "configurable" },
      "level_breakout": { "value": 8.0, "source": "configurable" },
      "htf_alignment": { "value": 7.0, "source": "configurable" },
      "rsi_divergence": { "value": 7.0, "source": "configurable" },
      "volume_divergence": { "value": 6.0, "source": "configurable" },
      "macd_divergence": { "value": 6.0, "source": "configurable" },
      "volume_exhaustion": { "value": 5.0, "source": "configurable" },
      "funding_extreme": { "value": 5.0, "source": "configurable" },
      "crowded_positioning": { "value": 5.0, "source": "configurable" },
      "pattern_confirmation": { "value": 5.0, "source": "configurable" },
      "news_catalyst": { "value": 7.0, "source": "configurable" }
    },
    "llm_factor_cap": { "value": 35.0, "source": "configurable" },
    "confluence_max_score": { "value": 15, "source": "configurable" }
  },
  "levels": {
    "atr_defaults": {
      "sl": { "value": 1.5, "source": "hardcoded" },
      "tp1": { "value": 2.0, "source": "hardcoded" },
      "tp2": { "value": 3.0, "source": "hardcoded" }
    },
    "atr_guardrails": {
      "sl_bounds": { "value": [0.5, 3.0], "source": "hardcoded" },
      "tp1_min": { "value": 1.0, "source": "hardcoded" },
      "tp2_max": { "value": 8.0, "source": "hardcoded" },
      "rr_floor": { "value": 1.0, "source": "hardcoded" }
    },
    "phase1_scaling": {
      "strength_min": { "value": 0.8, "source": "hardcoded" },
      "sl_strength_max": { "value": 1.2, "source": "hardcoded" },
      "tp_strength_max": { "value": 1.4, "source": "hardcoded" },
      "vol_factor_min": { "value": 0.75, "source": "hardcoded" },
      "vol_factor_max": { "value": 1.25, "source": "hardcoded" }
    }
  },
  "patterns": {
    "strengths": {
      "bullish_engulfing": { "value": 15, "source": "hardcoded" },
      "bearish_engulfing": { "value": 15, "source": "hardcoded" },
      "morning_star": { "value": 15, "source": "hardcoded" },
      "evening_star": { "value": 15, "source": "hardcoded" },
      "three_white_soldiers": { "value": 15, "source": "hardcoded" },
      "three_black_crows": { "value": 15, "source": "hardcoded" },
      "marubozu": { "value": 13, "source": "hardcoded" },
      "hammer": { "value": 12, "source": "hardcoded" },
      "piercing_line": { "value": 12, "source": "hardcoded" },
      "dark_cloud_cover": { "value": 12, "source": "hardcoded" },
      "inverted_hammer": { "value": 10, "source": "hardcoded" },
      "doji": { "value": 8, "source": "hardcoded" },
      "spinning_top": { "value": 5, "source": "hardcoded" }
    }
  },
  "regime_weights": {
    "<pair>": {
      "<timeframe>": {
        "trending": {
          "inner_caps": { "trend": 38, "mean_rev": 22, "squeeze": 12, "volume": 28 },
          "outer_weights": { "tech": 0.45, "flow": 0.25, "onchain": 0.18, "pattern": 0.12 }
        },
        "ranging": { "...": "..." },
        "volatile": { "...": "..." }
      }
    }
  },
  "learned_atr": {
    "<pair>": {
      "<timeframe>": {
        "sl_atr": { "value": 1.5, "source": "configurable" },
        "tp1_atr": { "value": 2.0, "source": "configurable" },
        "tp2_atr": { "value": 3.0, "source": "configurable" },
        "last_optimized_at": "2026-03-18T12:00:00Z",
        "signal_count": 42
      }
    }
  },
  "performance_tracker": {
    "optimization_params": {
      "min_signals": { "value": 40, "source": "hardcoded" },
      "window_size": { "value": 100, "source": "hardcoded" },
      "trigger_interval": { "value": 10, "source": "hardcoded" }
    },
    "guardrails": {
      "sl_range": { "value": [0.8, 2.5], "source": "hardcoded" },
      "tp1_range": { "value": [1.0, 4.0], "source": "hardcoded" },
      "tp2_range": { "value": [2.0, 6.0], "source": "hardcoded" },
      "max_sl_adj": { "value": 0.3, "source": "hardcoded" },
      "max_tp_adj": { "value": 0.5, "source": "hardcoded" }
    }
  }
}
```

### 3. Signal Parameter Snapshots

**New column on `Signal` model:**
- `engine_snapshot: dict | None` (JSONB, nullable)

Populated in `run_pipeline` at signal creation time. Contains only the configurable (mutable) parameters:

```json
{
  "source_weights": { "traditional": 0.40, "flow": 0.22, "onchain": 0.23, "pattern": 0.15 },
  "ml_blend_weight": 0.25,
  "regime_mix": { "trending": 0.6, "ranging": 0.3, "volatile": 0.1 },
  "regime_caps": { "trend": 38, "mean_rev": 22, "squeeze": 12, "volume": 28 },
  "regime_outer": { "tech": 0.45, "flow": 0.25, "onchain": 0.18, "pattern": 0.12 },
  "atr_multipliers": { "sl": 1.5, "tp1": 2.0, "tp2": 3.0, "source": "performance_tracker" },
  "thresholds": { "signal": 40, "llm": 20, "ml_confidence": 0.65 },
  "mean_reversion": { "rsi_steepness": 0.25, "bb_pos_steepness": 10.0, "blend_ratio": 0.6 },
  "llm_factor_weights": { "support_proximity": 6.0, "...": "..." },
  "llm_factor_cap": 35.0,
  "confluence_max_score": 15
}
```

Note: `regime_mix` stores the full continuous mix dict (e.g., `{"trending": 0.6, "ranging": 0.3, "volatile": 0.1}`) rather than a single label, since the regime system uses continuous mixing not discrete classification. The `regime_caps` and `regime_outer` reflect the blended values used for that signal.

Hardcoded constants are excluded -- they only change with code deploys and can be read from the parameters endpoint.

**Migration:** Alembic migration adds nullable JSONB column `engine_snapshot` to `signals` table. Existing signals will have `null`.

### 4. Apply Endpoint: `POST /api/engine/apply`

**Request:** Uses dot-path keys that map to specific DB tables and columns.

```json
{
  "changes": {
    "blending.source_weights.traditional": 0.45,
    "blending.thresholds.signal": 35,
    "regime_weights.BTC-USDT-SWAP.15m.trending_trend_cap": 40,
    "learned_atr.BTC-USDT-SWAP.15m.current_sl_atr": 1.3
  },
  "confirm": false
}
```

**Dot-path to DB column mapping:**

| Dot-path prefix | DB Table | Column mapping |
|---|---|---|
| `blending.source_weights.<name>` | `PipelineSettings` | `<name>_weight` (e.g., `traditional_weight`) |
| `blending.thresholds.signal` | `PipelineSettings` | `signal_threshold` |
| `blending.thresholds.llm` | `PipelineSettings` | `llm_threshold` |
| `blending.thresholds.ml_confidence` | `PipelineSettings` | `ml_confidence_threshold` |
| `blending.ml_blend_weight` | `PipelineSettings` | `ml_blend_weight` |
| `blending.llm_factor_weights` | `PipelineSettings` | `llm_factor_weights` (JSONB, full replace) |
| `blending.llm_factor_cap` | `PipelineSettings` | `llm_factor_total_cap` |
| `mean_reversion.<param>` | `PipelineSettings` | `mean_rev_<param>` (e.g., `mean_rev_rsi_steepness`). Exception: `mean_reversion.squeeze_steepness` maps to column `squeeze_steepness` (no `mean_rev_` prefix). |
| `regime_weights.<pair>.<tf>.<col>` | `RegimeWeights` | Direct column name (e.g., `trending_trend_cap`). Lookup by `(pair, timeframe)`. |
| `learned_atr.<pair>.<tf>.<col>` | `PerformanceTrackerRow` | Direct column name (e.g., `current_sl_atr`). Lookup by `(pair, timeframe)`. |
| `confluence_max_score` | `PipelineSettings` | `confluence_max_score` |

**Behavior:**
- `confirm: false` (default) -- preview mode. Returns a diff array:
  ```json
  {
    "preview": true,
    "diff": [
      {
        "path": "blending.source_weights.traditional",
        "current": 0.40,
        "proposed": 0.45,
        "source": "configurable"
      }
    ]
  }
  ```
- `confirm: true` -- applies changes:
  1. Acquires `app.state.pipeline_settings_lock` to serialize writes
  2. Routes each parameter to its backing store (see mapping table above)
  3. Updates all in-memory stores:
     - `app.state.settings` for blending weights, thresholds, ML/LLM params
     - `app.state.scoring_params` for mean-reversion params (rsi_steepness, bb_pos_steepness, squeeze_steepness, blend_ratio)
     - `app.state.regime_weights[(pair, tf)]` for regime cap/weight changes
     - `app.state.performance_tracker.reload_cache()` for learned ATR values
  4. Returns `{ "applied": true, "diff": [...] }`

**Concurrency note:** The apply endpoint acquires `pipeline_settings_lock` before writing. For pipeline cycle safety, `run_pipeline` should snapshot the mutable parameters it needs at the start of each cycle (copy the relevant values from `app.state` into local variables). This prevents mid-cycle parameter mutation from producing signals with a mix of old and new values, and ensures the `engine_snapshot` accurately reflects what was used.

**Validation:** The endpoint validates proposed values against the same guardrails the optimizer uses (e.g., ATR within `SL_RANGE`, source weights summing to ~1.0).

### 5. Backtest Parameter Override Extension

**Extend `POST /api/backtest/run` request body:**

Add optional `parameter_overrides` field using the same dot-path key format as the apply endpoint. This ensures a single serialization convention across the system.

```json
{
  "pair": "BTC-USDT-SWAP",
  "timeframe": "1h",
  "start": "2026-01-01",
  "end": "2026-03-01",
  "parameter_overrides": {
    "blending.source_weights.traditional": 0.50,
    "blending.source_weights.flow": 0.20,
    "levels.atr_defaults.sl": 1.8
  }
}
```

**Mapping to BacktestConfig:** The backtester internally maps dot-path overrides to `BacktestConfig` fields:

| Dot-path | BacktestConfig field |
|---|---|
| `blending.source_weights.traditional` | `tech_weight` |
| `blending.source_weights.pattern` | `pattern_weight` |
| `blending.thresholds.signal` | `signal_threshold` |
| `blending.thresholds.ml_confidence` | `ml_confidence_threshold` |
| `levels.atr_defaults.sl` | `sl_atr_multiplier` |
| `levels.atr_defaults.tp1` | `tp1_atr_multiplier` |
| `levels.atr_defaults.tp2` | `tp2_atr_multiplier` |
| `confluence_max_score` | `confluence_max_score` |

Any override not in this mapping is ignored by the backtester (since the backtester does not use all engine parameters -- e.g., it excludes flow/onchain scoring).

**Store overrides in `BacktestRun`:** Add JSONB column `parameter_overrides` to persist the dot-path overrides for that run. This powers the Compare tab diff.

### 6. ATR Optimization Endpoint

**New endpoint: `POST /api/backtest/optimize-atr`**

```json
{
  "pair": "BTC-USDT-SWAP",
  "timeframe": "1h"
}
```

Runs the `PerformanceTracker.optimize()` logic on demand (using resolved signals from DB). Returns the proposed multipliers and the Sortino ratio used as the optimization metric (matching what the existing optimizer actually computes):

```json
{
  "current": { "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0 },
  "proposed": { "sl_atr": 1.3, "tp1_atr": 2.2, "tp2_atr": 3.5 },
  "metrics": {
    "signals_analyzed": 85,
    "current_sortino": 1.42,
    "proposed_sortino": 1.78
  }
}
```

Does not auto-apply -- the user reviews and uses the apply endpoint.

### 7. Regime Optimization: Behavioral Change

The existing `POST /api/backtest/optimize-regime` endpoint auto-saves optimized weights to the `RegimeWeights` table and hot-reloads into `app.state`. To align with the new diff-based apply flow:

- **Change:** The endpoint no longer auto-saves. It returns the proposed weights and optimization metrics.
- The user reviews the results in the Optimize tab and applies via the apply endpoint.
- This is a **breaking change** to the existing endpoint behavior.

---

## Frontend Changes

### 8. More Tab Sub-Navigation

**Refactor `web/src/features/more/MorePage.tsx`** from a 463-line monolith into a thin sub-tab router.

**Sub-tabs:** Settings | Risk | Engine | Backtest | ML | Alerts

Each sub-tab is a component under its respective feature directory:
- `features/settings/components/SettingsPage.tsx` -- extracted from MorePage (Trading + Notifications + System sections)
- `features/settings/components/RiskPage.tsx` -- extracted from MorePage (Risk Management section)
- `features/engine/components/EnginePage.tsx` -- new
- `features/backtest/components/BacktestView.tsx` -- existing, enhanced
- `features/ml/components/MLTrainingView.tsx` -- existing, unchanged
- `features/alerts/components/AlertsPage.tsx` -- existing, unchanged

**MorePage.tsx** becomes:
```tsx
const SUB_TABS = ['Settings', 'Risk', 'Engine', 'Backtest', 'ML', 'Alerts'] as const;

function MorePage() {
  const [activeTab, setActiveTab] = useState<SubTab>('Settings');
  return (
    <div>
      <SubTabBar tabs={SUB_TABS} active={activeTab} onChange={setActiveTab} />
      {activeTab === 'Settings' && <SettingsPage />}
      {activeTab === 'Risk' && <RiskPage />}
      {/* ... */}
    </div>
  );
}
```

Sub-tab bar uses the same pill-style horizontal scroll pattern already used inside BacktestView.

**Component refactoring note:** `BacktestView`, `MLTrainingView`, and `AlertsPage` currently render their own headers with back-arrow buttons (receiving `onBack` callbacks). When embedded as sub-tabs, these headers must be removed or made conditional (e.g., only render the header when `onBack` prop is provided). The sub-tab bar replaces the back-button navigation pattern.

### 9. Engine Parameter Dashboard (`features/engine/`)

**New feature directory structure:**
```
features/engine/
├── components/
│   ├── EnginePage.tsx          -- Main container, fetches params, renders categories
│   ├── ParameterCategory.tsx   -- Collapsible section for a category
│   ├── ParameterRow.tsx        -- Single parameter: name, value, source badge
│   ├── SourceBadge.tsx         -- "configurable" / "hardcoded" pill
│   ├── WeightBar.tsx           -- Horizontal stacked bar for source weights
│   └── RegimeGrid.tsx          -- Matrix view for regime caps/weights per pair/tf
├── hooks/
│   └── useEngineParameters.ts  -- Fetch + cache from GET /api/engine/parameters
├── store.ts                    -- Zustand store: cached params, loading/error state
└── types.ts                    -- TypeScript interfaces for parameter response
```

**Zustand store (`store.ts`):** Manages the cached parameter response, loading state, error state, and a `refresh()` action that re-fetches from the API. The store is also used by the backtest feature to populate the override panel with current live values.

**Categories rendered as collapsible accordion sections.** All collapsed by default except "Blending" (the most frequently referenced).

**Source badges:** `hardcoded` = gray, `configurable` = green. Subtle, small pills next to each value.

**Regime weights** use a compact grid layout: rows = regimes (trending/ranging/volatile), columns = dimensions (trend/mean_rev/squeeze/volume for inner caps; tech/flow/onchain/pattern for outer weights). One grid per pair/timeframe combination, with a pair/timeframe selector.

**Learned ATR** section shows a card per pair/timeframe with the three multipliers, last-optimized timestamp (relative, e.g., "2 days ago"), and signal count.

### 10. Signal Snapshot in Signal Cards

In `features/signals/`, extend the signal detail/card component with a collapsible "Engine Parameters" section. When expanded, it renders the `engine_snapshot` JSONB from the signal record using the same `ParameterRow` component.

Signals with `engine_snapshot: null` (pre-migration) show "Parameter snapshot not available" in muted text.

### 11. Backtest Enhancements

**Setup tab -- Parameter Override Panel:**
- Collapsible "Advanced: Parameter Overrides" section below existing config
- Shows only parameters the backtester supports (see mapping table in Section 5). Parameters the backtester ignores (e.g., flow/onchain weights, on-chain scoring constants) are excluded from the override panel to avoid confusion.
- Untouched parameters shown dimmed with live values; edited ones highlighted
- "Reset to Live" button clears all overrides
- Overrides sent as dot-path `parameter_overrides` in the backtest run request

**New "Optimize" tab (4th tab alongside Setup/Results/Compare):**
- Two sections: Regime Optimization and ATR Optimization
- Each has: pair/timeframe selector, "Run Optimization" button, progress indicator, results display
- Results show current vs proposed values in a diff table
- "Apply to Live" button triggers the apply flow

**Apply Flow Modal:**
- Triggered from Results tab ("Apply these parameters") or Optimize tab ("Apply to Live")
- Calls `POST /api/engine/apply` with `confirm: false` for preview
- Renders a diff table: parameter path | current | proposed | source
- Changed values highlighted. Confirm/Cancel buttons.
- On confirm, calls with `confirm: true`, shows success toast, refreshes Engine dashboard store

**Compare tab enhancement:**
- When comparing runs, show a "Parameter Differences" section listing which dot-path overrides differed between the selected runs

### 12. API Client Extensions

Add to `web/src/shared/lib/api.ts`:
- `getEngineParameters()` -- `GET /api/engine/parameters`
- `previewEngineApply(changes)` -- `POST /api/engine/apply` with `confirm: false`
- `confirmEngineApply(changes)` -- `POST /api/engine/apply` with `confirm: true`
- `optimizeAtr(pair, timeframe)` -- `POST /api/backtest/optimize-atr`

---

## Data Flow Summary

```
[Engine Parameters Endpoint] ──read──> [Engine Dashboard (read-only)]
                                              │
[Backtest Run + Overrides] ──run──> [Results] ─┤
[Regime/ATR Optimizer] ──optimize──> [Results] ─┤
                                              │
                                    [Apply Modal (diff preview)]
                                              │
                               [POST /api/engine/apply confirm=true]
                                              │
                              [Acquires pipeline_settings_lock]
                                              │
                                    [PipelineSettings / RegimeWeights /
                                     PerformanceTrackerRow updated in DB]
                                              │
                                    [In-memory stores refreshed:
                                     app.state.settings,
                                     app.state.scoring_params,
                                     app.state.regime_weights,
                                     performance_tracker._cache]
                                              │
                                    [Next pipeline cycle snapshots
                                     params and uses new values]

[Signal Generation] ──snapshot──> [Signal.engine_snapshot JSONB]
                                              │
                              [Signal Card "Engine Parameters" section]
```

---

## Migration Plan

Migrations should be run in this order due to dependencies:

1. **Migration 1 (independent):** Add `engine_snapshot` JSONB nullable column to `signals` table
2. **Migration 2 (must deploy before code that reads new columns):** Add nullable override columns to `PipelineSettings` table (`traditional_weight`, `flow_weight`, `onchain_weight`, `pattern_weight`, `ml_blend_weight`, `ml_confidence_threshold`, `llm_threshold`, `llm_factor_weights`, `llm_factor_total_cap`, `confluence_max_score`)
3. **Migration 3 (independent):** Add `parameter_overrides` JSONB nullable column to `backtest_runs` table

Migrations 1 and 3 are independent and can run in any order relative to code deployment (nullable columns, no code reads them until the feature ships). Migration 2 must be applied before deploying the config resolution code that reads the new columns.
