# Pattern Recognition & Backtesting Engine Design

## Overview

Two complementary features for the Krypton signal engine:

1. **Pattern Recognition** — Candlestick and chart pattern detection integrated as a 4th scoring layer
2. **Backtesting Engine** — Full strategy tester with configurable parameters, historical data import, and frontend UI

---

## 1. Pattern Recognition

### Phase 1: Candlestick Patterns

**New module: `backend/app/engine/patterns.py`**

Rule-based candlestick pattern detector running on the candle array already fetched by `run_pipeline()` (last 50 from Redis — pattern detector uses the most recent 5-10 entries). Each pattern returns a signal bias (bullish/bearish) and strength score.

**12 core patterns:**

| Type | Patterns |
|------|----------|
| Single-candle | Hammer, Inverted Hammer, Doji, Spinning Top, Marubozu |
| Two-candle | Bullish Engulfing, Bearish Engulfing, Piercing Line, Dark Cloud Cover |
| Three-candle | Morning Star, Evening Star, Three White Soldiers, Three Black Crows |

**Scoring integration:**

- Each detected pattern contributes up to ±15 points to a new `pattern_score` (-100 to +100)
- Multiple patterns can stack (e.g., hammer + bullish engulfing = stronger signal)
- Patterns near key levels (Bollinger bands, EMA zones) get a 1.5x weight boost
- Combiner adds a 4th weight: `engine_pattern_weight` (default 15%)
- New default weights: tech 40% + flow 22% + on-chain 23% + pattern 15%
- `compute_preliminary_score()` signature extended to accept `pattern_score` + `pattern_weight` as new parameters
- Remove unused `engine_llm_weight` from `config.py` in the same change (dead config — LLM uses fixed-point adjustment, not a weight)

**Weight redistribution when data sources are unavailable:**

The existing `run_pipeline()` redistributes onchain weight when unavailable. With 4 weights, the full redistribution matrix:

| Unavailable Source | Redistribution Rule |
|--------------------|---------------------|
| On-chain only | tech gets +60% of onchain_w, flow gets +40% of onchain_w (existing behavior) |
| Flow only | tech gets +60% of flow_w, pattern gets +40% of flow_w |
| Flow + on-chain | tech gets +70% of freed weight, pattern gets +30% |
| Pattern (toggled off) | tech gets +60% of pattern_w, flow gets +40% of pattern_w |

Pattern weight is always available in live pipeline (pure computation), so redistribution only applies when explicitly toggled off via config. In backtesting, flow and on-chain are always unavailable — see Section 2b.

**Signal output:**

- New field `detected_patterns`: JSONB column on `Signal` model — array of `{name, type, bias, strength}`. Only populated for live signals (backtester stores its own `detected_patterns` per trade inside `BacktestRun.results` JSONB).
- Shown in signal detail bottom sheet as small badges

### Phase 2: Classical Chart Patterns

**Extends `backend/app/engine/patterns.py`** with a `ChartPatternDetector` class analyzing swing highs/lows over 50-100 candle lookback.

**7 patterns:**

| Type | Patterns |
|------|----------|
| Reversal | Double Top, Double Bottom, Head & Shoulders, Inverse H&S |
| Continuation | Ascending Triangle, Descending Triangle, Bull/Bear Flag |

**Detection approach:**

- Identify swing highs/lows using a pivot algorithm (local extremes within N-candle window)
- Match pivot sequences against pattern templates with tolerance thresholds (e.g., double top = two highs within 0.5% of each other with a trough between)
- Breakout confirmation: pattern fires only when price breaks the neckline/trendline with volume above average
- Target price calculation: breakout level ± pattern height (measured move projection)

**Scoring integration:**

- Chart patterns contribute to the same `pattern_score` as candlestick patterns
- Weighted heavier (up to ±25 pts) — higher-conviction, longer-forming structures
- Confirmed chart pattern + aligned candlestick pattern at breakout = maximum pattern score

**Output:**

- `detected_patterns` array includes chart patterns with additional fields: `{neckline, breakout_level, target_price}`
- Frontend: rendered as overlay annotations on the chart tab

**Timeline:** Phase 2 ships after Phase 1 is validated through the backtester.

---

## 2. Backtesting Engine

### 2a. Historical Data Import

**New module: `backend/app/collector/history.py`**

Bulk imports historical candles from OKX REST API.

**Endpoints:**

- `GET /api/v5/market/history-candles` — recent history
- `GET /api/v5/market/history-candles-long` — extended history (requires pagination)

**How it works:**

- OKX provides up to 1,440 candles per request, paginated by `after` timestamp
- Importer walks backwards from current time, page by page, until reaching desired lookback
- Upserts into existing `Candle` table using `ON CONFLICT DO NOTHING`
- Rate-limited: 50ms delays between requests (OKX 20 req/s limit)

**Available lookback:**

| Timeframe | Approx. Available History |
|-----------|--------------------------|
| 15m | ~6 months |
| 1h | ~2 years |
| 4h / 1D | Several years |

**API endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/backtest/import` | Trigger import for pairs + timeframes + lookback period. Returns job ID. |
| GET | `/api/backtest/import/{job_id}` | Check progress (candles imported, estimated remaining, status) |

All `/api/backtest/*` endpoints require `X-API-Key` auth (same `require_settings_api_key()` dependency as existing routes).

**Storage:** ~35k candles per pair for 1 year of 15m data. 10 pairs x 3 timeframes x 1 year ≈ 1M rows — well within Postgres comfort zone. Existing unique constraint on `(pair, timeframe, timestamp)` creates a B-tree index that supports prefix + range scans — efficient for the backtester's `WHERE pair = X AND timeframe = Y AND timestamp BETWEEN A AND B ORDER BY timestamp` queries. No additional index needed.

### 2b. Strategy Runner

**New module: `backend/app/engine/backtester.py`**

Replays historical candles through configurable scoring pipelines and records simulated trades.

**Configurable parameters per run:**

| Category | Parameters |
|----------|------------|
| Thresholds | `signal_threshold` (1-100), `llm_threshold` (disabled for backtesting) |
| Weights | tech / pattern (active in backtesting). Flow + on-chain sliders shown as disabled with tooltip "Historical data unavailable". Weights auto-renormalize to 100% across active sources. |
| Indicator toggles | EMA, MACD, RSI, BB, candlestick patterns, chart patterns (on/off each) |
| Risk | Risk per trade %, max concurrent positions |
| Levels | SL multiplier (ATR), TP1 multiplier, TP2 multiplier |

**Execution flow:**

1. Load candle range from Postgres for selected pairs + timeframes
2. Iterate candle-by-candle chronologically, maintaining 200-candle rolling window (same as live pipeline)
3. At each candle: run scoring pipeline (tech + pattern — no LLM calls)
4. If score crosses threshold: open simulated position with entry/SL/TP levels
5. On subsequent candles: check SL/TP hits, track open positions, enforce max concurrent limit
6. Record each simulated trade: entry time, exit time, direction, score, outcome, P&L %, duration, detected patterns

**Performance:**

- No DB writes during run — everything in memory, results persisted at end
- 1 year of 15m candles (~35k) per pair completes in seconds
- Max 2 concurrent backtest runs enforced server-side (reject with 429 if limit reached)
- Flow and on-chain data unavailable historically — backtester uses only tech + pattern scores, renormalized to 100% (e.g., if user set tech 70% / pattern 30%, those are used as-is; default backtest weights: tech 75% / pattern 25%)

**Job tracking:**

The `BacktestRun` model (Section 2c) doubles as the job tracker — a row is inserted with `status=running` when a run starts, updated to `completed`/`failed` when done. No separate job system needed. Import jobs use a lightweight in-memory dict (`app.state.import_jobs`) keyed by UUID — import progress is transient and doesn't need to survive restarts (user can re-trigger).

**API endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/backtest/run` | Accept parameter config, pairs, timeframe, date range. Creates `BacktestRun` row with `status=running`, returns run ID. |
| GET | `/api/backtest/run/{run_id}` | Poll status + results (reads from `BacktestRun` row) |
| POST | `/api/backtest/run/{run_id}/cancel` | Cancel a running backtest (sets a cancellation flag checked each candle iteration) |

### 2c. Results & Comparison

**New DB model: `BacktestRun`**

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| created_at | datetime | Run timestamp |
| status | enum | running / completed / failed / cancelled |
| config | JSONB | Full parameter snapshot |
| pairs | JSONB | List of pairs tested |
| timeframe | str | Timeframe used |
| date_from / date_to | datetime | Date range |
| results | JSONB | Aggregate stats + trade list |

**Aggregate stats computed per run:**

- Total trades, win rate %, average R:R
- Net P&L %, max drawdown %, profit factor
- Sharpe ratio, Sortino ratio
- Best/worst trade, average trade duration
- Win rate by pair, by direction (long vs short)
- Monthly P&L breakdown
- Equity curve data points (cumulative P&L over time)

**Comparison API:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/backtest/runs` | List all saved runs with summary stats |
| GET | `/api/backtest/runs/{id}` | Full results including trade list |
| POST | `/api/backtest/compare` | Accept 2-4 run IDs, return side-by-side stats + overlaid equity curves |
| DELETE | `/api/backtest/runs/{id}` | Delete old runs |

**Trade-level detail per simulated trade:**

```json
{
  "pair": "BTC-USDT-SWAP",
  "direction": "LONG",
  "entry_time": "2025-09-15T14:30:00Z",
  "exit_time": "2025-09-15T18:45:00Z",
  "entry_price": 62450.0,
  "exit_price": 63200.0,
  "sl": 61800.0,
  "tp1": 63100.0,
  "tp2": 63750.0,
  "outcome": "TP1_HIT",
  "pnl_pct": 1.2,
  "score": 72,
  "detected_patterns": ["Bullish Engulfing", "Morning Star"]
}
```

---

## 3. Frontend

### 3a. Backtest UI

Accessible from the **More tab** as a dedicated section (keeps 5-tab nav clean).

#### Setup View

- Pair multi-select (checkboxes for tracked pairs)
- Timeframe selector (15m / 1h / 4h)
- Date range picker (from / to)
- **Parameter controls** in collapsible sections:
  - Scoring weights: 4 sliders (tech / flow / on-chain / pattern) with visual bar, auto-normalizing to 100%
  - Thresholds: signal threshold slider
  - Indicator toggles: pill-style on/off for each (EMA, MACD, RSI, BB, candlestick patterns, chart patterns)
  - Risk: SL/TP ATR multiplier inputs, max concurrent positions
- "Run Backtest" button with progress bar + cancel button while running
- Flow and on-chain weight sliders greyed out with "Historical data unavailable" tooltip

#### Results View

- Stats strip: win rate, net P&L, max drawdown, Sharpe, total trades, profit factor
- Equity curve chart (lightweight-charts line series)
- Monthly P&L heatmap grid (green/red cells, same style as journal calendar)
- Trade list: scrollable with pair, direction badge, entry/exit times, P&L %, outcome badge
  - Tap to expand: score breakdown + detected patterns
- "Save Run" button to persist for comparison

**States:**
- **Loading:** progress bar with candle count / total estimate
- **Failed:** error message with "Retry" button (config preserved)
- **Cancelled:** "Run cancelled" notice with partial results if any trades were completed
- **Empty results:** "No trades generated — try lowering the signal threshold or adjusting weights" message
- **No historical data:** "Import historical data first" prompt with link to import action

#### Compare View

- Select 2-4 saved runs from a list
- Side-by-side stats table (rows = metrics, columns = runs)
- Overlaid equity curves (different colors per run)
- Best values highlighted in gold accent
- Compare button disabled with "Select at least 2 runs" hint when <2 runs selected
- Empty state when no saved runs: "Run a backtest and save it to start comparing"

### 3b. Pattern Recognition UI

#### Signal Cards (Signals Tab)

- Small pattern badges below the score bar on signal cards
- Pill-shaped tags: `Bullish Engulfing`, `Morning Star` in muted green/red matching signal direction

#### Signal Detail Bottom Sheet

- New "Patterns" row in score breakdown section
- Shows each detected pattern with type (candlestick/chart), bias, and strength contribution

#### Chart Tab (Phase 2 only)

- Chart pattern overlay annotations when viewing a pair with recent pattern detections:
  - Neckline/trendline as dashed line
  - Breakout level as horizontal marker
  - Target price as dotted line
- Toggle-able via "Patterns" chip in timeframe selector row (off by default)

#### Backtest Integration

- Trade list in backtest results shows detected patterns per trade
- Filter: "Show only pattern-triggered trades" to evaluate pattern recognition contribution

---

## 4. Testing

Tests per phase, following existing patterns (pytest + `asyncio_mode = "auto"`, `httpx.AsyncClient` with `ASGITransport`, stubbed external deps).

| Phase | Tests |
|-------|-------|
| 1 — Patterns | `tests/engine/test_patterns.py`: Feed known candle sequences (hammer, engulfing, morning star, etc.) and assert correct detection + score. Test stacking behavior. Test no false positives on random data. Test level-proximity boost with mock BB/EMA values. |
| 2 — Import | `tests/collector/test_history.py`: Mock OKX REST responses, verify pagination logic walks backwards correctly, verify `ON CONFLICT DO NOTHING` doesn't overwrite existing candles, verify rate limiting. |
| 3 — Backtester | `tests/engine/test_backtester.py`: Feed a small candle series with known scores, verify correct trade entries/exits. Test SL/TP hit detection. Test max concurrent position enforcement. Test cancellation flag stops iteration. |
| 4 — API | `tests/api/test_backtest.py`: Test all endpoints (import trigger, run, poll, list, compare, delete, cancel). Test auth required. Test 429 when max concurrent runs exceeded. |
| 6 — Pattern badges | Frontend: manual verification (pattern badges render on signal cards with correct colors). |

---

## 5. Implementation Order

| Phase | What | Depends On |
|-------|------|------------|
| 1 | Candlestick pattern detector + scoring integration | Nothing |
| 2 | Historical data import from OKX | Nothing |
| 3 | Backtester strategy runner | Phase 1 + 2 |
| 4 | BacktestRun model + results/comparison API | Phase 3 |
| 5 | Frontend: backtest setup + results + compare views | Phase 4 |
| 6 | Frontend: pattern badges on signals | Phase 1 |
| 7 | Chart pattern detector (Phase 2 patterns) | Phase 1 validated via Phase 3-5 |
| 8 | Frontend: chart pattern overlays | Phase 7 |

Phases 1 and 2 can be built in parallel. Phase 6 can ship alongside Phase 5.

---

## 6. New Files Summary

**Backend:**

| File | Purpose |
|------|---------|
| `app/engine/patterns.py` | Candlestick + chart pattern detection |
| `app/collector/history.py` | OKX historical candle bulk import |
| `app/engine/backtester.py` | Strategy replay engine |
| `app/api/backtest.py` | Backtest REST endpoints (import, run, results, compare) |
| `app/db/models.py` | Add `BacktestRun` model + `detected_patterns` to Signal |
| `alembic/versions/xxx_add_backtest.py` | Migration for BacktestRun table + Signal.detected_patterns |

**Frontend:**

| File | Purpose |
|------|---------|
| `src/features/backtest/` | New feature slice |
| `src/features/backtest/components/BacktestSetup.tsx` | Parameter config + run trigger |
| `src/features/backtest/components/BacktestResults.tsx` | Stats, equity curve, trade list |
| `src/features/backtest/components/BacktestCompare.tsx` | Side-by-side run comparison |
| `src/features/backtest/store.ts` | Zustand store for backtest state |
| `src/features/backtest/types.ts` | TypeScript types |
| `src/features/signals/components/PatternBadges.tsx` | Pattern pill badges for signal cards |
