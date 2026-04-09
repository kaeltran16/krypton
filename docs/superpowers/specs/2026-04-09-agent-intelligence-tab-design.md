# Agent Intelligence Tab — Design Spec

**Date:** 2026-04-09
**Status:** Draft
**Scope:** Replace the chart tab with an agent-powered intelligence tab using Claude Code CLI + MCP server + skills

## Overview

Replace the existing chart tab (lightweight-charts candlestick viewer with 23 frontend-computed indicators) with an Agent Intelligence tab. Claude Code CLI, powered by a custom MCP server and skills, analyzes the engine's live state and produces annotated chart analysis. The chart becomes the agent's canvas — every annotation carries reasoning the user can click to reveal.

Desktop: full annotated chart + narrative panel.
Mobile: narrative-only feed (no chart, no annotations).

## What Gets Removed

The entire `web/src/features/chart/` directory (~1,628 lines):

- `components/CandlestickChart.tsx` (587 lines) — core chart rendering
- `components/ChartView.tsx` (142 lines) — tab entry point
- `components/IndicatorSheet.tsx` (161 lines) — indicator toggle modal
- `hooks/useChartData.ts` (159 lines) — OKX WebSocket candle streaming
- `lib/indicators.ts` (579 lines) — 23 indicator calculations

Tab reference in `App.tsx` and `Layout.tsx` rewired to new feature.

**Kept:**
- `shared/hooks/useLivePrice.ts` — still used for live price display
- `shared/lib/api.ts` candle-fetching methods — new chart still needs candle data

## Architecture

```
Claude Code CLI (on Windows host)
  + MCP config pointing to krypton MCP server
  + Skills: /market-brief, /pair-dive, /signal-explain, /position-check
      |
      v
MCP Server (Python, runs on host)
  connects to localhost:5432 (Postgres) + localhost:6379 (Redis)
  exposes 9 tools for reading engine state + 1 tool for writing analysis
      |
      v (post_analysis tool)
Backend (FastAPI in Docker)
  POST /api/agent/analysis → AgentAnalysis table
  GET /api/agent/analysis → serves to frontend
  WS broadcast agent_analysis event
      |
      v
Frontend (Agent tab)
  Desktop: annotated chart (70%) + narrative panel (30%)
  Mobile: narrative feed only
```

## 1. MCP Server

**Location:** `backend/mcp/`
**Runtime:** Python process on Windows host (outside Docker)
**Connection:** Direct to Postgres (`localhost:5432`) and Redis (`localhost:6379`) exposed by docker-compose
**Protocol:** MCP SDK (official `mcp` Python package), stdio transport. Use `FastMCP` server class with `async def` tool handlers — the SDK supports async natively with an asyncio event loop. **Validation task:** first implementation step is a smoke test confirming one async tool (e.g., `get_regime`) returns data when called via Claude Code CLI.

Reads directly from Postgres/Redis — does NOT call FastAPI endpoints. Reuses SQLAlchemy models from `backend/app/db/models.py`.

### Tools

| Tool | Args | Returns |
|------|------|---------|
| `get_candles` | pair, timeframe, limit? | OHLCV array from Redis cache |
| `get_regime` | pair? | Regime type, confidence, ADX, BB width per pair |
| `get_signals` | pair?, status?, limit? | Recent signals with scores, direction, levels |
| `get_signal_scores` | pair | Raw score breakdown (tech, flow, ML, combined) |
| `get_order_flow` | pair | Funding rate, OI change, L/S ratio, recent trend |
| `get_indicators` | pair, timeframe? | Computed indicator values at current candle (RSI, ADX, BB, MACD, etc.) |
| `get_performance` | pair? | Signal hit/miss history, win rate, avg P&L |
| `get_positions` | — | Current open OKX positions (pair, side, entry, size, unrealized PnL, leverage) |
| `post_analysis` | type, pair?, narrative, annotations, metadata | Writes analysis to backend via POST /api/agent/analysis (authenticates with `X-Agent-Key` header — see Auth section below) |
| `get_last_analysis` | type?, pair? | Most recent analysis for comparison |

`get_positions` calls OKX REST account endpoints using the same credentials the `exchange/` module uses.

## 2. Claude Code Skills

Located in `.claude/skills/`. Each skill instructs Claude to call MCP tools, reason over the data, and output structured analysis via `post_analysis`.

### `/market-brief`

Cross-pair overview. The primary daily skill.

**Flow:**
1. `get_regime` for all 3 pairs
2. `get_signal_scores` for each pair
3. `get_order_flow` for each pair
4. `get_indicators` for the pair with the highest absolute combined score (the "focus pair")
5. Reason over combined data
6. `post_analysis` with:
   - `type: "brief"`
   - `narrative`: 3-5 sentence market read covering all pairs (regime context, key observation, actionable takeaway)
   - `annotations`: produced for **all 3 pairs** (each annotation has a `pair` field). Frontend filters to the currently selected pair.
   - `metadata`: score breakdowns per pair, regime states, which pair was the focus

### `/pair-dive <pair>`

Deep single-pair analysis.

**Flow:**
1. All MCP tools called for the specified pair
2. Produces detailed annotated chart — key levels, regime assessment, flow interpretation, trend lines, zones
3. `post_analysis` with `type: "pair_dive"`, full annotation set

### `/signal-explain <signal_id>`

Post-hoc signal analysis. `signal_id` is a UUID from the `signals` table. Users obtain it by:
- Copying from the Signals tab in the app (signal detail view shows the ID)
- Using `get_signals` MCP tool output (which lists IDs)

**Flow:**
1. `get_signals` to fetch the specific signal by ID
2. `get_candles` for context around signal time
3. `get_indicators` and `get_order_flow` at signal time
4. Explains what happened, why the engine scored it that way
5. `post_analysis` with `type: "signal_explain"`, annotations around entry/SL/TP levels

### `/position-check`

Assess open positions.

**Flow:**
1. `get_positions` for current holdings
2. `get_regime` for each held pair
3. `get_order_flow` for each held pair
4. `get_indicators` for each held pair
5. `get_signal_scores` for each held pair
6. Per-position assessment: hold/scale/reduce/exit with reasoning
7. `post_analysis` with `type: "position_check"`, annotations showing entry, SL/TP, key levels

## 3. Backend Additions

### AgentAnalysis Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `type` | VARCHAR | `brief`, `pair_dive`, `signal_explain`, `position_check` |
| `pair` | VARCHAR (nullable) | Target pair, null for cross-pair briefs |
| `narrative` | TEXT | Agent's written analysis |
| `annotations` | JSONB | Chart drawing instructions |
| `metadata` | JSONB | Score breakdowns, regime data, structured extras |
| `created_at` | TIMESTAMP | When analysis was produced |

### Auth: Agent Key

The existing backend uses JWT cookies for user auth (`require_auth()` dependency). The MCP server is a machine client — it can't do cookie-based auth. Solution: a dedicated agent key.

- New setting: `agent_api_key` in `config.py` (loaded from `.env`).
- New dependency: `require_agent_key()` — validates `X-Agent-Key` header against `settings.agent_api_key`. Returns 401 if missing/invalid.
- Used only on `POST /api/agent/analysis`. The GET endpoint uses normal `require_auth()` (frontend user is authenticated via JWT).
- This is a single static secret, not a key management system — appropriate for a single-user app.

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST /api/agent/analysis` | `require_agent_key()` | MCP server writes analysis here. Validates annotations with Pydantic schema before storing — malformed annotations are stripped. |
| `GET /api/agent/analysis` | `require_auth()` | Frontend reads latest. Query params: `type?`, `pair?`, `limit?` (default 10). |

### WebSocket Event

New event type on existing `/ws/signals` connection:

```json
{
  "type": "agent_analysis",
  "data": { "id": "...", "type": "brief", "pair": null, "narrative": "...", "annotations": [...], "metadata": {...}, "created_at": "..." }
}
```

Broadcast when `POST /api/agent/analysis` receives a new entry. Frontend updates live without polling.

### Input Sanitization

The `POST /api/agent/analysis` endpoint validates and sanitizes before storing:
- **Pydantic validation:** `annotations` array validated against the Annotation union type schema. Missing required fields or wrong types cause that annotation to be stripped (not the entire request).
- **Text sanitization:** `reasoning` and `label` string fields are plain text only — strip any HTML tags before storing. Frontend renders these as React text nodes (not `innerHTML`), providing a second layer of XSS protection.
- **Annotation cap:** Maximum 30 annotations per analysis. Excess annotations are truncated to prevent chart performance issues.

## 4. Annotation Schema

Six annotation types. Every annotation has a `pair` field (for filtering when user switches pairs) and a `reasoning` field (shown when the user clicks the annotation on the chart).

```typescript
type Annotation =
  | HorizontalLevel
  | Zone
  | SignalMarker
  | RegimeZone
  | TrendLine
  | PositionMarker;

interface HorizontalLevel {
  type: "level";
  pair: string;
  price: number;
  label: string;
  style: "solid" | "dashed";
  color: string;
  reasoning: string;
}

interface Zone {
  type: "zone";
  pair: string;
  from_price: number;
  to_price: number;
  from_time?: number;
  to_time?: number;
  label: string;
  color: string;
  reasoning: string;
}

interface SignalMarker {
  type: "signal";
  pair: string;
  time: number;
  price: number;
  direction: "long" | "short";
  label: string;
  reasoning: string;
}

interface RegimeZone {
  type: "regime";
  pair: string;
  from_time: number;
  to_time: number;
  regime: "trending" | "ranging" | "volatile" | "steady";
  confidence: number;
  reasoning: string;
}

interface TrendLine {
  type: "trendline";
  pair: string;
  from: { time: number; price: number };
  to: { time: number; price: number };
  label: string;
  color: string;
  reasoning: string;
}

interface PositionMarker {
  type: "position";
  pair: string;
  entry_price: number;
  sl_price?: number;
  tp_price?: number;
  direction: "long" | "short";
  reasoning: string;
}
```

### Mapping to Lightweight Charts Primitives

| Annotation | Primitive Type | Rendering |
|------------|---------------|-----------|
| HorizontalLevel | Custom series primitive (price line with label) | Horizontal line at price, text label on price scale |
| Zone | Custom series primitive (rectangle) | Semi-transparent filled rectangle between price/time bounds |
| SignalMarker | Series marker (`createSeriesMarkers`) | Arrow up/down at candle with text label |
| RegimeZone | Custom series primitive (background shading) | Vertical band with regime-colored semi-transparent fill |
| TrendLine | Custom series primitive (line) | Line between two price/time points |
| PositionMarker | Custom series primitive (multi-line) | Entry as solid line, SL/TP as dashed lines, colored by direction |

All custom primitives implement `hitTest()` returning an `externalId`. Chart subscribes to `subscribeClick()` and shows a popover with the matching annotation's `reasoning` when clicked.

## 5. Frontend — Agent Intelligence Tab

### New Feature: `web/src/features/agent/`

```
features/agent/
  components/
    AgentView.tsx          — tab entry point, responsive layout switch
    AgentChart.tsx         — candlestick chart + annotation rendering
    NarrativePanel.tsx     — analysis text + score breakdown + history
    AnnotationPopover.tsx  — reasoning popover on annotation click
  hooks/
    useAgentAnalysis.ts    — fetch + WS subscription for analysis data
    useChartData.ts        — candle fetching + OKX WS streaming (rewritten)
  lib/
    primitives/            — lightweight-charts custom primitives
      HorizontalPrimitive.ts
      ZonePrimitive.ts
      RegimeZonePrimitive.ts
      TrendLinePrimitive.ts
      PositionPrimitive.ts
  types.ts                 — Annotation types, AgentAnalysis type
```

### Desktop Layout (>= 1024px)

Two-panel side-by-side:

- **Left (70%):** Candlestick chart with volume, live OKX streaming, agent annotations rendered as primitives. Click annotation to show popover with reasoning.
- **Right (30%):** Narrative panel.
  - Top: latest analysis narrative + structured metadata (score breakdown, regime state).
  - Bottom: collapsible history list. Click a past analysis to load its annotations onto the chart.
- **Header:** Pair selector dropdown, live price, timeframe pills (15m, 1h, 4h, 1D).
- **Footer (in right panel):** "Updated [timestamp]" + refresh button (re-fetches latest from API).

### Mobile Layout (< 1024px)

Narrative-only feed, no chart:

- Latest analysis narrative expanded with score breakdown
- History list of past analyses as collapsed accordion items
- Pair filter pills at top
- Same data, same API — just no chart component rendered

### Annotation Click Interaction (Desktop)

1. User clicks an annotation on the chart
2. `subscribeClick` fires, `hoveredObjectId` matched to annotation's `externalId`
3. `AnnotationPopover` renders near the click position
4. Shows: annotation label, reasoning text, annotation type badge
5. Click elsewhere or press Escape to dismiss

### Data Flow

1. `useAgentAnalysis` hook:
   - On mount: `GET /api/agent/analysis?limit=10` to load recent analyses
   - Subscribes to WebSocket `agent_analysis` events for live updates
   - Returns `{ analyses, latest, loading }`
2. `useChartData` hook (rewritten):
   - Same OKX REST + WS candle streaming logic
   - Simplified — no indicator computation, no crosshair OHLC state
   - Returns `{ candles, loading, onTickRef }`
3. When `latest` analysis changes, `AgentChart` reads its `annotations` and renders/updates primitives on the chart

### Tab Integration

- Tab renamed from "Chart" (BarChart3 icon) to "Agent" (new icon — Brain or Bot or Sparkles from lucide-react)
- `App.tsx` passes `<AgentView pair={selectedPair} />` instead of `<ChartView>`
- Tab bar order unchanged: Home, Agent, Signals, News/Positions, More

### Bundle Size

Current build is ~1.06 MB (near Cloudflare Workers limit). Mitigation:
- The agent tab replaces the chart tab — removing `indicators.ts` (579 lines of indicator math) offsets the new primitives code.
- Lazy-load `AgentChart` component (desktop only) via `React.lazy()` so primitives code is code-split and only loaded when the tab is active on desktop.
- Monitor bundle size in build output after implementation.

## 6. Configuration

### MCP Config (`.claude/mcp.json` or project-level)

```json
{
  "mcpServers": {
    "krypton": {
      "command": "python",
      "args": ["backend/mcp/server.py"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton",
        "REDIS_URL": "redis://localhost:6379",
        "OKX_API_KEY": "...",
        "OKX_SECRET_KEY": "...",
        "OKX_PASSPHRASE": "...",
        "AGENT_API_KEY": "...",
        "KRYPTON_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

**Credential safety:**
- `.claude/` is in `.gitignore` — config file won't be committed.
- OKX credentials are the same ones used by the backend (from `.env`). Copy them into the MCP config.
- `AGENT_API_KEY` must match the `agent_api_key` value in the backend's `.env`.
- Avoid committing a `.claude/mcp.json.example` with real values. The spec documents the structure; users fill in their own credentials.

### Environment

**Development:** MCP server runs on Windows host, connects to Docker-exposed ports (`localhost:5432` Postgres, `localhost:6379` Redis, `localhost:8000` API).

**Production:** Backend runs on a DigitalOcean droplet. MCP server still runs on the Windows host. To reach production data:
- SSH tunnel forwards remote Postgres/Redis to localhost: `ssh -L 5432:localhost:5432 -L 6379:localhost:6379 droplet`
- `KRYPTON_API_URL` points to the droplet's public URL (for `post_analysis` to write back)
- Same MCP server code, different env vars per environment

**Switching environments:** Use separate MCP config files or env var overrides. No code changes needed — only `DATABASE_URL`, `REDIS_URL`, and `KRYPTON_API_URL` differ between dev and prod.

**General:**
- Skills reference MCP tools by name — Claude Code discovers them at startup
- `AGENT_API_KEY` used by `post_analysis` tool to authenticate `POST /api/agent/analysis` via `X-Agent-Key` header

## 7. Error Handling

### MCP Server Failures

- **DB/Redis connection failure:** MCP tool returns a clear error message to Claude (e.g., "Cannot connect to Postgres at localhost:5432"). Claude reports the error in CLI output. No partial analysis posted. User sees the error in their terminal and can fix the connection.
- **OKX API error (rate limit, timeout):** `get_positions` catches the exception and returns `{"error": "OKX unavailable", "positions": []}`. Skills treat missing position data as non-fatal — analysis proceeds without position context, with a note in the narrative ("Position data unavailable").

### Backend Failures

- **`post_analysis` fails (backend down, auth error):** MCP tool reports the HTTP error to Claude. Claude surfaces it in CLI output. Analysis is lost — no retry or queue. User re-runs the skill after fixing the issue.
- **Malformed annotations:** `POST /api/agent/analysis` validates annotations with a Pydantic model before storing. Invalid annotations (missing required fields, wrong types) are stripped with a warning in the response. Valid annotations are stored normally.

### Frontend Failures

- **Chart primitive crash:** `AgentChart` wraps the annotation rendering layer in a React error boundary. If a primitive fails, the chart still shows candles — only annotations are lost. Error boundary shows "Failed to render annotations" message.
- **WebSocket disconnect:** Same reconnect logic as existing `/ws/signals` handler. Missed `agent_analysis` events are recovered on next `GET /api/agent/analysis` poll (triggered by tab focus or manual refresh).

## 8. Empty & Stale States

### Empty State (No Analyses)

**Desktop:** Chart renders live candles with volume (no annotations). Narrative panel shows:
- Heading: "No analyses yet"
- Body: "Run `/market-brief` from Claude Code CLI to generate your first analysis."
- Visually: muted text, centered in panel.

**Mobile:** Single centered message with the same text. No accordion, no pair filter — just the empty state message.

### Staleness

Every analysis displays a relative timestamp ("2h ago", "1d ago") in both the narrative panel header and history list items.

**Staleness thresholds:**
- **< 4 hours:** Fresh. Normal rendering.
- **4-24 hours:** Aging. Annotations render at 60% opacity. Timestamp shows in amber/yellow.
- **> 24 hours:** Stale. Annotations render at 30% opacity. "(stale)" badge next to timestamp. Narrative panel shows subtle banner: "This analysis is outdated. Re-run to refresh."

Staleness is purely visual — stale analyses are never auto-deleted or hidden. User decides when to refresh.

## 9. Annotation Display Rules

### One Analysis at a Time

The chart renders annotations from **one analysis only** — the latest by default. No stacking of multiple analyses.

- History list items are selectable. Clicking a past analysis switches the chart to display that analysis's annotations.
- The currently displayed analysis is highlighted in the history list.
- Switching analyses is instant (annotations are already loaded in memory from the initial API fetch).

### Pair Filtering

Annotations include a `pair` field (already present in `SignalMarker`, added to all annotation types — see schema update below). The chart filters annotations to match the currently selected pair.

For `/market-brief`:
- The agent picks the pair with the highest absolute combined score as the "focus pair."
- Annotations are produced for all 3 pairs (not just the focus).
- The narrative covers all pairs. The chart shows annotations for whichever pair is selected in the header dropdown.

### Timeframe Behavior

Annotations render at their stored timestamps regardless of the chart's selected timeframe. This is intentional:
- Price-level annotations (levels, zones, positions) are timeframe-agnostic — a support level is valid on any timeframe.
- Time-bound annotations (regime zones, signal markers) may span different numbers of candles on finer timeframes. This is expected behavior, not a bug.

No timeframe matching or filtering is applied.

## Non-Goals

- No in-app chat input (analysis triggered from CLI only)
- No autonomous/scheduled agent runs
- No frontend indicator computation (agent decides what to highlight)
- No drawing tools for the user (agent draws, user reads)
- No mobile chart rendering
