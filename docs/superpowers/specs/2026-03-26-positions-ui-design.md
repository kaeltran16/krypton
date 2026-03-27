# Positions UI Redesign

## Overview

Upgrade the barebone positions display into a first-class trading experience. Two parts:
1. Enriched position cards on the Home tab (information-dense, tap to drill down)
2. Dedicated Positions tab replacing the News tab (full controls + trade history)

## Navigation Change

- Replace `news` tab with `positions` in bottom nav
- Tab type: `"home" | "chart" | "signals" | "positions" | "more"`
- Icon: `Layers` from lucide-react
- `Layout.tsx` props swap `news` → `positions`
- Lift `setTab` into a lightweight Zustand store (`shared/stores/navigation.ts`) so child components (e.g., Home position cards) can trigger tab changes. The store exposes `tab`, `setTab`, and `navigateToPosition(pair, side)` which sets tab to `positions` and stores the target position key for auto-scroll. `Layout.tsx` must fully migrate its `useState<Tab>` to this store — remove the local `useState` and read `tab`/`setTab` from the store so there is a single source of truth.
- News view moves to a sub-page under More: add `news` to `MorePage` `SubPage` type, place in the "Intelligence Hub" cluster with `Newspaper` icon, label "News", desc "Market news & sentiment". Remove `news` prop from `Layout` and `App.tsx`.
- Keep `NewsAlertToast` in `App.tsx` — it is independent of the News tab.

## Home Tab — Enriched Position Cards

The `OpenPositions` component in `HomeView.tsx` gets richer cards with no expand/collapse. Tapping a card calls `navigateToPosition(pair, side)` from the nav store, switching to the Positions tab scrolled to that position's detail card.

### Card layout (always visible):
- Pair name + side badge (LONG/SHORT + leverage)
- Unrealized P&L in USD + ROI % (computed: `pnl / margin * 100`)
- Notional value (`size × mark_price`)
- Time open — relative (e.g., "2h 14m", "3d") — requires `cTime` from OKX. If `cTime` is absent (some demo mode responses omit it), omit the time open field rather than showing a zero value.
- Liquidation distance % (`(mark - liq) / mark * 100`)

### Removed from Home:
- Expand/collapse behavior
- Inline "Close Position" button (moved to Positions tab)

## Positions Tab

New feature slice at `web/src/features/positions/`. SegmentedControl with two segments: **Open** | **History**.

### States (both segments)

- **Loading:** Skeleton cards (reuse existing `Skeleton` component)
- **Error:** Retry banner with message (match Home tab error pattern)
- **Empty (Open):** "No open positions — the engine is monitoring for opportunities"
- **Empty (History):** "No resolved signals yet"

### Open Segment — Position Detail Cards

Each open position rendered as a full detail card:

**Header row:** Pair + side badge (LONG/SHORT + leverage) + time open

**P&L row:** Unrealized P&L USD, ROI %, colored long/short

**Data grid (2×3):**
- Entry price
- Mark price
- Liquidation price (+ distance %)
- Margin used
- Notional value
- Funding cost (accumulated — from OKX `/api/v5/account/bills?type=8&instId={pair}`, type 8 = funding fee)

**Action buttons at bottom of each card:**

1. **Close** — full market close via existing `close_position`
2. **Partial Close** — sheet/dialog to input % or size to close. Uses new `POST /api/account/partial-close` endpoint. Add an optional `pos_side: str | None = None` parameter to the existing `OKXClient.place_order` method — when provided, use it directly for `posSide` instead of deriving from `side`. The endpoint passes `pos_side` through to `place_order`. No new OKX client method needed.
3. **Adjust SL/TP** — sheet/dialog showing current SL/TP (fetched from algo orders), inputs for new values. Backend flow: (a) fetch current pending algos for the pair to confirm state, (b) cancel old algo order — if cancel fails, return error immediately without attempting placement, (c) place new algo order. If placement fails after successful cancellation, return error with `sl_tp_removed: true` flag; frontend shows warning with retry option. The retry path must re-fetch algo state first (not blindly re-submit) to avoid duplicate algo orders.
4. **Add to Position** — sheet/dialog to input additional size. Uses existing `POST /api/account/order` endpoint (no new endpoint needed — `place_order` mapping is correct for opening side).

Each action dialog follows the `OrderDialog` pattern — sheet with inputs, confirmation, result feedback.

### History Segment

Resolved signals from the database. No OKX fill history — avoids brittle dedup logic between two sources.

**Source:** `signals` table where `outcome IS NOT NULL`, ordered by `outcome_at DESC`.

**History card layout:**
- Header: Pair + side badge + outcome badge (TP1_HIT, SL_HIT, EXPIRED — color-coded green/red/gray)
- P&L row: Realized P&L % (`outcome_pnl_pct`), duration (`outcome_duration_minutes` formatted as "4h 22m")
- Detail row: Entry price, SL/TP levels
- Signal info: Signal score + brief reason. Tappable to view full signal detail via existing `SignalDetail` sheet.

**Filtering:** Pair filter (All / BTC / ETH / WIF) via PillSelect at top.

**Pagination:** Load 20 at a time, "Load more" button (no infinite scroll).

## Backend Changes

### OKX Client (`okx_client.py`)

**Signing convention:** GET endpoints sign base path only (split on `?`), matching `get_fills_today`. POST endpoints sign path + body, matching `place_order`.

1. **`parse_positions_response`** — add `cTime` field as `created_at` (ISO timestamp). If `cTime` is absent, set `created_at` to `None`.
2. **`get_algo_orders_pending(pair)`** — GET `/api/v5/trade/orders-algo-pending?instType=SWAP&instId={pair}`. Sign base path only.
3. **`cancel_algo_order(algo_id)`** — POST `/api/v5/trade/cancel-algos`. Sign path + body.
4. **`place_order`** — add optional `pos_side: str | None = None` parameter. When provided, use it directly for `posSide` instead of deriving from `side`. This enables partial closes where `side` is the closing direction but `posSide` must match the position being reduced.
5. **`get_funding_costs(pair)`** — GET `/api/v5/account/bills?type=8&instId={pair}`. Sign base path only.

### API Endpoints (`api/account.py`)

1. **`GET /api/account/algo-orders?pair=X`** — returns active SL/TP for a position
2. **`POST /api/account/amend-algo`** — fetch current algos → cancel existing → place new (body: `{pair, side, size, sl_price?, tp_price?}`). If cancel fails, return error immediately. If cancel succeeds but placement fails, return error with `sl_tp_removed: true` flag so frontend can warn and offer retry.
3. **`POST /api/account/partial-close`** — close portion of position (body: `{pair, pos_side, size}`). Calls `place_order` with the closing `side` and explicit `pos_side`.
4. **`GET /api/account/trade-history?days=30&pair=`** — resolved signals from DB (`outcome IS NOT NULL`), ordered by `outcome_at DESC`, paginated (limit/offset).

### Frontend API Client (`api.ts`)

- `Position` type gets `created_at: string | null`
- New types:

```typescript
interface AlgoOrder {
  algo_id: string;
  pair: string;
  side: string;
  tp_trigger_price: number | null;
  sl_trigger_price: number | null;
  size: string;
  status: string;
}

interface TradeHistoryEntry {
  signal_id: number;
  pair: string;
  direction: "long" | "short";
  entry_price: number;
  sl_price: number | null;
  tp1_price: number | null;
  tp2_price: number | null;
  pnl_pct: number;
  duration_minutes: number;
  outcome: "TP1_HIT" | "SL_HIT" | "EXPIRED";
  signal_score: number;
  signal_reason: string | null;
  opened_at: string;
  closed_at: string;
}
```

- New methods: `getAlgoOrders`, `amendAlgo`, `partialClose`, `getTradeHistory`, `getFundingCosts`

### No new DB tables or migrations
History reads from existing `signals` table (resolved signals only). No OKX fill history integration.
