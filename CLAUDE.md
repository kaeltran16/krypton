# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Krypton is a real-time crypto trading signal engine with a mobile-first PWA frontend. The backend ingests live OKX market data via WebSocket, runs a multi-source scoring pipeline (technical indicators, order flow, on-chain data, ML models, LLM analysis), and emits trading signals. The frontend displays signals, charts, portfolio, news, and alerts.

## Repository Structure

```
krypton/
├── backend/              # FastAPI async API + signal engine
│   ├── app/
│   │   ├── api/          # REST endpoints + WebSocket handlers
│   │   ├── collector/    # OKX WebSocket + REST data ingestion
│   │   ├── db/           # SQLAlchemy models, Alembic migrations
│   │   ├── engine/       # Signal generation, scoring, risk management
│   │   ├── exchange/     # OKX REST API client (orders, account)
│   │   ├── ml/           # PyTorch LSTM training + inference pipeline
│   │   ├── push/         # Web Push notification dispatch
│   │   ├── prompts/      # LLM prompt templates
│   │   ├── config.py     # Pydantic-settings + optional YAML overlay
│   │   └── main.py       # App factory, lifespan, pipeline orchestration
│   ├── tests/
│   └── docker-compose.yml
├── web/                  # React PWA frontend
│   └── src/
│       ├── shared/       # API client, WebSocket manager, theme, shared UI components
│       └── features/     # Vertical-slice feature modules
```

## Development Commands

### Backend (runs in Docker)

```bash
# Start all services (API + Postgres + Redis) — docker-compose.yml is in backend/
cd backend && docker compose up -d

# Run all tests
docker exec krypton-api-1 python -m pytest

# Run a single test file
docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py

# Run a specific test
docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::test_name -v

# Run Alembic migration
docker exec krypton-api-1 alembic upgrade head

# Create new migration
docker exec krypton-api-1 alembic revision --autogenerate -m "description"
```

The API container (`krypton-api-1`) volume-mounts the backend directory with `--reload`, so code changes apply immediately.

### Frontend

```bash
cd web
pnpm dev          # Vite dev server with HMR
pnpm build        # TypeScript check + production build
pnpm lint         # ESLint
pnpm test         # Vitest (or: npx vitest run)
pnpm deploy       # Cloudflare Workers deploy via Wrangler
```

## Architecture

### Backend Pipeline (Signal Generation)

The core data flow on each confirmed candle (orchestrated in `main.py:run_pipeline`):

1. **Ingest**: OKX WebSocket → `collector/` → Redis (rolling 200-candle cache) + Postgres upsert. Minimum 70 candles required for reliable indicators.
2. **Score**: `engine/traditional.py` computes ADX/RSI/BB/OBV/Volume scores (-100 to +100) across trend, mean-reversion, volatility, and volume dimensions. `compute_order_flow_score()` scores funding rate/OI/L-S ratio.
3. **Combine**: `engine/combiner.py` blends tech + flow + on-chain + pattern scores with adaptive weight normalization — if a source is unavailable, its weight redistributes proportionally to others.
4. **ML gate** (optional): Per-pair PyTorch models predict direction + confidence. `blend_with_ml()` integrates ML only if confidence >= threshold.
5. **LLM gate**: If |blended| >= `llm_threshold`, calls OpenRouter with full context. LLM opinion acts as a multiplier (confirm/caution/contradict), not an override.
6. **Signal**: If |final| >= `signal_threshold`, calculates entry/SL/TP levels via priority cascade (LLM explicit → ML regression → ATR defaults), enriches with position sizing from `engine/risk.py`, persists to Postgres, broadcasts via WebSocket + push notifications.
7. **Resolve**: Background loop (60s) checks PENDING signals against candle data for TP/SL hits or 24h expiry.

### Backend Key Patterns

- **Auth**: All REST endpoints require `X-API-Key` header (validated against `settings.krypton_api_key`). WebSocket validates at handshake via query param or header.
- **Shared state**: `app.state` carries settings, db, redis, WebSocket manager (`ConnectionManager`), OKX client, order flow dict, ML predictors, optimizer state, pipeline tasks set, and prompt template.
- **Config**: Two-layer system — `.env` via pydantic-settings, optional `config.yaml` overlay that flattens nested keys (e.g., `engine.signal_threshold` → `engine_signal_threshold`). `PipelineSettings` DB table can override at runtime.
- **DB**: SQLAlchemy 2.0 async with asyncpg. Models in `db/models.py`: `User`, `Candle`, `Signal`, `RiskSettings`, `NewsEvent`, `PushSubscription`, `PipelineSettings`, `OrderFlowSnapshot`, `BacktestRun`, `Alert`/`AlertHistory`/`AlertSettings`, `PerformanceTrackerRow`, `RegimeWeights`, `ParameterProposal`/`ShadowResult`, `MLTrainingRun`. Singleton tables use `CheckConstraint("id = 1")`.
- **JSONB columns**: `raw_indicators`, `risk_metrics`, `detected_patterns`, `correlated_news_ids` on Signal model — flexible schema without migrations.
- **Order flow is ephemeral**: `app.state.order_flow` dict is updated in-place by collectors, not persisted in real-time (only `OrderFlowSnapshot` records per candle).
- **Regime detection**: `engine/regime.py` computes continuous regime mix (trending/ranging/volatile/steady). Heuristic uses ADX + BB width; optional LightGBM classifier (`engine/regime_classifier.py`) replaces heuristic when trained and not stale (>30 days). `regime_labels.py` generates retrospective training labels. `RegimeWeights` DB table stores learned per-pair regime weights.
- **Parameter optimizer**: `engine/optimizer.py` monitors signal fitness, proposes parameter changes via counterfactual backtesting, validates in shadow mode before promotion. `ParameterProposal` + `ShadowResult` models track proposals. `engine/param_groups.py` defines tunable parameter groups with priority layers.
- **ATR optimization**: `PerformanceTracker` loads learned ATR multipliers per (pair, timeframe) from DB at startup; updates when signals resolve.
- **ML pipeline**: `ml/` module — `features.py` (feature matrix with momentum, regime, inter-pair features), `dataset.py`/`data_loader.py` (data prep), `model.py` (SignalLSTM), `trainer.py` (training loop + 3-member ensemble training via temporal splits), `predictor.py` (single-model inference), `ensemble_predictor.py` (weighted multi-model inference with staleness decay + disagreement penalty), `labels.py` (label generation). Per-pair models stored as checkpoints with JSON sidecar configs. `MLTrainingRun` persists training history.
- **Tests**: pytest with `asyncio_mode = "auto"`. Custom `_test_lifespan` in `conftest.py` stubs app.state without real DB/Redis/OKX. Uses `httpx.AsyncClient` with `ASGITransport`. Tests organized in subdirectories mirroring app structure (`tests/engine/`, `tests/ml/`, `tests/api/`, `tests/collector/`, `tests/exchange/`).

### Frontend Key Patterns

- **No router**: Navigation is `useState<Tab>` in `Layout.tsx` — tabs: home, chart, signals, news, more. Views stay mounted but hidden via CSS class toggling.
- **Feature slices**: Each feature under `src/features/<name>/` has `components/`, `hooks/`, optionally `store.ts` (Zustand) and `types.ts`. Features: home, chart, signals, settings, alerts, news, backtest, ml, engine, optimizer, dashboard, system, trading, auth, more.
- **Shared UI components**: `shared/components/` contains reusable primitives (Button, Card, Badge, Toggle, PillSelect, SegmentedControl, Skeleton, ProgressBar, MetricCard, FormField, CollapsibleSection, SubPageShell, EmptyState, SplashScreen, etc.) exported via barrel `index.ts`.
- **Three WebSocket connections**: (1) Backend `/ws/signals` for signals + candle events (via `WebSocketManager` with exponential backoff), (2) OKX public WS for live ticker prices (`useLivePrice`), (3) OKX business WS for live chart candles (`useChartData`).
- **Chart tick bypass**: Live chart candle ticks update via `onTickRef.current()` directly on the chart instance, bypassing React state. Only confirmed candles trigger React re-render + indicator recalc.
- **Styling**: Tailwind CSS v3, no component library. Design tokens in `src/shared/theme.ts` → consumed by `tailwind.config.ts`. Key semantic colors: `surface`, `card`, `long` (#0ECB81), `short` (#F6465D), `accent` (#F0B90B). Glass effects via `.glass-card` class with backdrop blur.
- **State**: Zustand stores — `signals/store.ts` (signals + candle pub/sub), `settings/store.ts` (debounced 500ms sync to backend with rollback on error, client-only fields in localStorage), `news/store.ts`, `alerts/store.ts`.
- **API client**: `shared/lib/api.ts` — thin `fetch` wrapper with 30+ typed methods. Auth via `X-API-Key` from `VITE_API_KEY` env var.
- **Mobile-first**: `min-h-dvh` for dynamic viewport, safe-area insets for notch/home indicator, `touch-action: manipulation` (no 300ms delay), haptic feedback on interactions (Android), 16px inputs to prevent iOS zoom.
- **Available pairs**: `BTC-USDT-SWAP`, `ETH-USDT-SWAP`, `WIF-USDT-SWAP` (defined in `shared/lib/constants.ts`).

### Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 (async), asyncpg, Redis, Alembic, PyTorch (CPU), LightGBM, Pandas |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v3, Zustand, lightweight-charts, vite-plugin-pwa |
| Infra | Docker Compose (API + Postgres 16 + Redis 7), Cloudflare Workers (frontend) |
| External | OKX API (market data + trading), OpenRouter (LLM analysis) |

## Environment Notes

- No local Python installation — use `docker exec krypton-api-1 python3` to run Python scripts
- On Git Bash (Windows), prefix docker exec commands with `MSYS_NO_PATHCONV=1` to prevent path mangling of container paths

## Git Commits

- Never add Co-Authored-By or any author attribution lines to commit messages
- Do not make small incremental commits per task — commit once at the end of a feature/batch
- Do not commit immediately after creating spec/plan markdown files — wait until there is accompanying implementation work
- Do not use git worktrees — work directly on the current branch

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
