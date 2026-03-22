# Risk Management Page Redesign

## Problem

The current Risk Management page is a static settings form with preset buttons for 4 parameters. It provides no visibility into live risk state (daily P&L, current exposure, position count, cooldown status). Two backend-supported fields (`max_position_size_usd`, `max_risk_per_trade_pct`) are not exposed in the UI. The page gives no reason to revisit after initial configuration.

## Design Decisions

- **Integrated layout**: each setting section shows its live status inline (progress bars, status dots, current values) rather than separating dashboard and settings
- **Color + Icon + Text states**: OK (green checkmark) / WARNING (amber warning triangle) / BLOCKED (red lock icon). Status communicated via color, icon, and text label — never color alone (WCAG `color-not-only`). Controls are never dimmed — users must always be able to adjust limits to unblock.
- **On-demand refresh**: single fetch on page load, manual refresh button (no polling or WebSocket)
- **Live cooldown countdown**: client-side `setInterval` ticking down from `last_sl_hit_at` timestamp
- **Single enriched endpoint**: new `GET /api/risk/status` returns settings + live state + per-rule evaluation in one payload

## Backend

### New Endpoint: `GET /api/risk/status`

Added to `app/api/risk.py`. Returns a composite response:

```json
{
  "settings": {
    "risk_per_trade": 0.01,
    "max_position_size_usd": null,
    "daily_loss_limit_pct": 0.03,
    "max_concurrent_positions": 3,
    "max_exposure_pct": 1.5,
    "cooldown_after_loss_minutes": 30,
    "max_risk_per_trade_pct": 0.02,
    "updated_at": "2026-03-22T09:00:00Z"
  },
  "state": {
    "equity": 10000.0,
    "daily_pnl_pct": -0.008,
    "open_positions_count": 1,
    "total_exposure_usd": 12000.0,
    "exposure_pct": 1.2,
    "last_sl_hit_at": "2026-03-22T10:30:00Z"
  },
  "rules": [
    {"rule": "daily_loss_limit", "status": "OK", "reason": "Daily P&L -0.8%, 2.2% remaining"},
    {"rule": "max_concurrent", "status": "OK", "reason": "1/3 positions open"},
    {"rule": "max_exposure", "status": "WARNING", "reason": "Exposure 120% approaching 150% limit"},
    {"rule": "cooldown", "status": "WARNING", "reason": "Cooldown active, 14min remaining"}
  ],
  "overall_status": "WARNING"
}
```

#### Rule Evaluation (not using `RiskGuard.check()`)

The existing `RiskGuard.check()` is designed for pre-trade evaluation and requires a `size_usd` parameter (the proposed trade size). The status endpoint has no trade to evaluate, so it builds rule evaluations directly in the endpoint handler:

- **daily_loss_limit**: `BLOCKED` if `|daily_pnl_pct| >= daily_loss_limit_pct`, `WARNING` if usage > 70%, else `OK`
- **max_concurrent**: `BLOCKED` if `open_positions_count >= max_concurrent_positions`, `WARNING` if `open_positions_count >= max_concurrent_positions - 1` AND `max_concurrent_positions >= 3` (for small limits like 2, skip WARNING to avoid being overly aggressive), else `OK`
- **max_exposure**: `BLOCKED` if `exposure_pct > max_exposure_pct`, `WARNING` if usage > 80%, else `OK`
- **cooldown**: `WARNING` if cooldown is active (time remaining > 0), else omitted from `rules[]` (same as `RiskGuard` behavior when cooldown is not configured or not triggered)

Note: `max_risk_per_trade` is omitted from the status rules — it only applies during pre-trade evaluation where a specific trade size is known. The setting is still displayed in the UI and configurable.

Note: Sections without a matching rule (Risk Per Trade, Max Position Size, Max Risk Per Trade) always render in OK state — they are pure settings with no live evaluation.

#### Data Sources

- **settings**: `RiskSettings` singleton table (existing), serialized via `_settings_to_dict()` (includes `updated_at`)
- **equity**: `app.state.okx_client.get_balance()` (existing)
- **daily_pnl_pct**: computed from today's resolved signals — query `Signal` where `outcome IN ('TP1_HIT', 'TP2_HIT', 'SL_HIT')` and `outcome_at >= today midnight UTC`, sum `outcome_pnl_pct` values, then **divide by 100** to convert to decimal fraction (the DB stores percentage values like `-1.5` for -1.5%, but `daily_loss_limit_pct` uses decimal fractions like `0.03` for 3%). Uses `outcome_at` (when P&L was realized), not `created_at`. No new tables. Note: this intentionally uses engine-tracked signal P&L rather than OKX fills (`get_fills_today()`), so the risk page reflects the engine's own risk exposure, not account-wide trading activity including manual trades.
- **open_positions_count / total_exposure_usd**: `app.state.okx_client.get_positions()` (existing), count and sum `abs(size * mark_price)`
- **exposure_pct**: `total_exposure_usd / equity` (computed server-side for convenience)
- **last_sl_hit_at**: query most recent signal with `outcome = 'SL_HIT'` from `Signal` table, return `outcome_at`

#### OKX Client Unavailable

When `okx_client` is None (demo mode or connection issue), return partial data: settings are populated normally, state fields default to zero (`equity: 0`, `daily_pnl_pct: 0`, etc.), all rules show OK. This keeps the page functional for settings configuration even without exchange connectivity.

#### Existing Endpoints Unchanged

- `GET /api/risk/settings` — still used internally
- `PUT /api/risk/settings` — still used for settings updates from frontend

### API Client Addition

Add `getRiskStatus()` method to `web/src/shared/lib/api.ts`:

```typescript
interface RiskState {
  equity: number;
  daily_pnl_pct: number;
  open_positions_count: number;
  total_exposure_usd: number;
  exposure_pct: number;
  last_sl_hit_at: string | null;
}

interface RiskRule {
  rule: string;
  status: "OK" | "WARNING" | "BLOCKED";
  reason: string;
}

interface RiskStatus {
  settings: RiskSettings;
  state: RiskState;
  rules: RiskRule[];
  overall_status: "OK" | "WARNING" | "BLOCKED";
}

getRiskStatus: () => request<RiskStatus>("/api/risk/status"),
```

## Frontend

### Component: `RiskPage.tsx`

Full rewrite of `web/src/features/settings/components/RiskPage.tsx`.

#### Lifecycle

1. **On mount**: fetch `GET /api/risk/status` → populate settings + live state
2. **On setting change**: `PUT /api/risk/settings` → re-fetch `/api/risk/status` to get updated rule evaluations
3. **Refresh button**: top-right corner, re-fetches `/api/risk/status`. Shows spinner on the icon during fetch and is disabled to prevent double-taps (`loading-buttons` guideline).

#### Sections (top to bottom)

| # | Section | Live State Display | Control | Progress Bar | Rule Key |
|---|---------|-------------------|---------|-------------|----------|
| 1 | Risk Per Trade | current % | 0.5% / 1% / 2% buttons | no | none (always OK) |
| 2 | Daily Loss Limit | `daily_pnl_pct` vs limit | 2% / 3% / 5% buttons | yes | `daily_loss_limit` |
| 3 | Max Positions | count / max | 2 / 3 / 5 buttons | no | `max_concurrent` |
| 4 | Max Exposure | `exposure_pct * 100`% / limit% (e.g., "120% / 150%") | 100% / 150% / 200% buttons | yes | `max_exposure` |
| 5 | Max Position Size | current USD cap | numeric input + "USD" label | no | none (always OK) |
| 6 | Max Risk Per Trade | current % | 1% / 2% / 5% buttons | no | none (always OK) |
| 7 | Loss Cooldown | countdown or "Inactive" | Off / 15m / 30m / 60m buttons | yes (drains) | `cooldown` |

#### Overall Status Indicator

Top of page, alongside the refresh button. Uses `aria-live="polite"` so screen readers announce status changes on refresh. Shows aggregate status:
- `text-long` green checkmark + "All Clear" — all rules passing
- `text-orange` amber warning triangle + "Warning" — at least one WARNING, no BLOCKED
- `text-error` red lock icon + "Blocked" — at least one BLOCKED

#### State Management

Local `useState` — no Zustand store. Page is self-contained and not consumed by other features.

### Visual States

Three states per rule section, driven by the matching entry in `rules[]`. Colors use theme tokens (`long`, `orange`, `error`) — not hardcoded hex. Each state is communicated via color + icon + text, never color alone (WCAG `color-not-only`). Status region uses `aria-live="polite"` so screen readers announce changes.

| State | Icon | Status Dot | Value Text | Progress Bar | Controls |
|-------|------|-----------|-----------|-------------|----------|
| OK | checkmark (Lucide `Check`) | `text-long` green | `text-long` | `bg-long` fill | normal |
| WARNING | warning triangle (Lucide `AlertTriangle`) | `text-orange` amber | `text-orange` | `bg-orange` fill | normal |
| BLOCKED | lock (Lucide `Lock`) | `text-error` red | `text-error` | `bg-error` 100% fill | normal (not dimmed) |

Icon appears inline next to section title, replacing the static accent bar. Sections without a matching rule key always render in OK state (checkmark icon).

Controls remain functional in all states — users can adjust limits to unblock. After saving, re-fetch shows updated evaluation. Controls are never dimmed; the status icon/dot/color communicate the state without suggesting disabled interactions.

Progress bars use `role="progressbar"` with `aria-valuenow`, `aria-valuemin="0"`, `aria-valuemax="100"`, and `aria-label` set to the rule's `reason` text from the API response.

### Cooldown Timer

When `last_sl_hit_at` is non-null and computed remaining time > 0:
- Remaining seconds computed as: `cooldown_after_loss_minutes * 60 - (Date.now() / 1000 - Date.parse(last_sl_hit_at) / 1000)`
- `useEffect` with `setInterval(1000)` decrements client-side
- Display format: `MM:SS` with tabular-nums, pulsing `text-orange` amber dot (pulsing animation respects `motion-reduce:animate-none`)
- Progress bar fill: `remaining / (cooldown_after_loss_minutes * 60)`
- At zero: optimistically flip to OK state (green dot, "Inactive", remove lock)
- Cleanup interval on unmount

When `cooldown` rule is absent from `rules[]` (cooldown not configured or not triggered): show "Inactive" with green dot, no timer.

Note: "Off" sends `null` (not `0`) for `cooldown_after_loss_minutes`, consistent with the existing frontend behavior.

### Max Position Size Input

The only section using a text input instead of preset buttons:
- Visible `<label>` element ("Max Position Size") above the input — not placeholder-only
- Numeric input with `inputMode="decimal"` to trigger numeric keyboard on mobile, min height 44px for touch targets
- Placeholder "Unlimited" shown when empty
- Save on blur or Enter key press
- Empty / cleared input sends `null` (removes cap → "No limit")
- Backend validates `gt=0` — input of 0 or negative shows inline error below the field
- Styled consistently with other sections (same card, same status icon pattern)

## Error Handling

- **Fetch fails on load**: error state with retry button
- **Settings update fails**: revert optimistic button selection, brief error text under section
- **No positions / demo account / OKX unavailable**: all states show OK with zero values (0 positions, 0% exposure, 0% daily P&L). Settings remain configurable.
- **No resolved signals today**: daily P&L returns 0.0
- **Cooldown expires between load and refresh**: client-side timer handles this — flips to green at zero. Next refresh confirms from backend.

## Testing

- Backend: test for `GET /api/risk/status` in `tests/api/` following existing `httpx.AsyncClient` + `ASGITransport` pattern
- Frontend: no new test files — existing patterns sufficient

## Files Changed

### Backend
- `backend/app/api/risk.py` — add `GET /api/risk/status` endpoint with response model and inline rule evaluation

### Frontend
- `web/src/shared/lib/api.ts` — add `RiskStatus`, `RiskState`, `RiskRule` types and `getRiskStatus()` method
- `web/src/features/settings/components/RiskPage.tsx` — full rewrite
