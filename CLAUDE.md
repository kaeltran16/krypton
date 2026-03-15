# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Krypton is a real-time crypto trading signal engine with a mobile-first PWA frontend. The backend ingests live OKX market data via WebSocket, runs a technical + LLM-based analysis pipeline, and emits trading signals. The frontend displays signals, charts, portfolio, and a trade journal.

## Repository Structure

```
krypton/
├── backend/          # FastAPI async API + signal engine
│   ├── app/
│   │   ├── api/      # REST endpoints + WebSocket handlers
│   │   ├── collector/ # OKX WebSocket + REST data ingestion
│   │   ├── db/       # SQLAlchemy models, Alembic migrations
│   │   ├── engine/   # Signal generation, scoring, risk management
│   │   ├── exchange/ # OKX REST API client (orders, account)
│   │   ├── push/     # Web Push notification dispatch
│   │   ├── prompts/  # LLM prompt templates
│   │   ├── config.py # Pydantic-settings + optional YAML overlay
│   │   └── main.py   # App factory, lifespan, pipeline orchestration
│   └── tests/
├── web/              # React PWA frontend
│   └── src/
│       ├── shared/   # API client, WebSocket manager, theme, utils
│       └── features/ # Vertical-slice feature modules
└── docker-compose.yml
```

## Development Commands

### Backend (runs in Docker)

```bash
# Start all services (API + Postgres + Redis)
docker compose up -d              # from project root or backend/

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
```

## Architecture

### Backend Pipeline (Signal Generation)

The core data flow on each confirmed candle:

1. **Ingest**: OKX WebSocket → `collector/` → Redis (rolling 200-candle cache) + Postgres upsert
2. **Score**: `engine/traditional.py` computes EMA/MACD/RSI/BB/ATR scores (-100 to +100), `compute_order_flow_score()` scores funding rate/OI/L-S ratio
3. **Combine**: `engine/combiner.py` blends tech + flow scores (60/40 default weight)
4. **LLM gate**: If |preliminary| >= `llm_threshold`, calls OpenRouter for LLM opinion
5. **Signal**: If |final| >= `signal_threshold`, calculates entry/SL/TP levels via ATR, enriches with position sizing from `engine/risk.py`, persists to Postgres, broadcasts via WebSocket
6. **Resolve**: Background loop (60s) checks PENDING signals against candle data for TP/SL hits or 24h expiry

### Backend Key Patterns

- **Auth**: All REST endpoints require `X-API-Key` header (validated against `settings.krypton_api_key`)
- **Shared state**: `app.state` carries settings, db, redis, WebSocket manager, OKX client, order flow dict
- **Config**: Two-layer system — `.env` via pydantic-settings, optional `config.yaml` overlay that flattens nested keys (e.g., `engine.signal_threshold` → `engine_signal_threshold`)
- **DB**: SQLAlchemy 2.0 async with asyncpg; 4 models: `Candle`, `Signal`, `RiskSettings`, `PushSubscription`
- **Tests**: pytest with `asyncio_mode = "auto"`. Test fixtures stub all external deps (no real DB/Redis/OKX needed). Uses `httpx.AsyncClient` with `ASGITransport` for API tests.

### Frontend Key Patterns

- **No router**: Navigation is `useState<Tab>` in `Layout.tsx` (home, chart, signals, journal, more)
- **Feature slices**: Each feature under `src/features/<name>/` has `components/`, `hooks/`, optionally `store.ts` (Zustand) and `types.ts`
- **Two WebSocket connections**: (1) Backend `/ws/signals` for signals + candle events (via `WebSocketManager` with exponential backoff), (2) OKX public WS for live ticker prices
- **Styling**: Tailwind CSS v3, no component library. Design tokens in `src/shared/theme.ts` → consumed by `tailwind.config.ts`. Key semantic colors: `surface`, `card`, `long` (green), `short` (red), `accent` (gold)
- **State**: Zustand stores — `signals/store.ts` (signals + candle pub/sub), `settings/store.ts` (persisted to localStorage)
- **API client**: `shared/lib/api.ts` — thin `fetch` wrapper with typed methods for every backend endpoint

### Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 (async), asyncpg, Redis, Alembic |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Zustand, lightweight-charts |
| Infra | Docker Compose (API + Postgres 16 + Redis 7) |
| External | OKX API (market data + trading), OpenRouter (LLM analysis) |

## Environment Notes

- No local Python installation — use `docker exec krypton-api-1 python3` to run Python scripts
- On Git Bash (Windows), prefix docker exec commands with `MSYS_NO_PATHCONV=1` to prevent path mangling of container paths

## Git Commits

- Never add Co-Authored-By or any author attribution lines to commit messages
- Do not make small incremental commits per task — commit once at the end of a feature/batch
- Do not use git worktrees — work directly on the current branch
