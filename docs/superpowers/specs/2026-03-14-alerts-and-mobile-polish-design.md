# Alerts & Mobile Polish Design Spec

## Problem

Krypton has basic web push for signal notifications but no user-configurable alert system. Users can't set price alerts, filter which signals trigger notifications, monitor indicator thresholds, or get portfolio warnings. Additionally, the PWA lacks mobile-native polish — no gestures, haptic feedback, or transition animations — making it feel like a website rather than a native app.

## Solution

Two sequential features:

1. **Alert system** — four alert types (price, signal, indicator, portfolio) with per-alert urgency levels and quiet hours
2. **Mobile polish** — gestures, haptic feedback, touch target improvements, animations, and PWA enhancements

## Alert System

### Alert Types & Conditions

#### Price Alerts
Triggered by a **new backend OKX ticker WebSocket subscription**. Currently, live ticker prices only exist in the frontend (direct OKX WS connection in `useLivePrice.ts`). The backend needs its own ticker feed to evaluate price alerts server-side, enabling push notifications even when the app is closed.

New infrastructure: `collector/ticker.py` subscribes to OKX `tickers` channel for all active pairs, caches latest price in Redis (`ticker:{pair}`), and invokes price alert evaluation at a **throttled cadence of once per second per pair** (not on every tick message — OKX tickers fire ~1-2 msg/s/pair). The evaluator caches active price alerts in Redis (`alerts:price`, invalidated on alert CRUD operations) to avoid per-tick DB queries.

| Condition | Description | One-shot? |
|-----------|-------------|-----------|
| `crosses_above` | Price crosses above threshold | Yes |
| `crosses_below` | Price crosses below threshold | Yes |
| `pct_move` | Price moves X% within Y minutes (window: 5–60 min) | No |

For `pct_move`: the evaluator queries Redis-cached price snapshots to compute the percentage change over the configured window. Snapshots are stored as a Redis sorted set per pair (`ticker_snapshots:{pair}`, score = unix timestamp, value = price) sampled once per minute by the ticker collector. Keys have a **90-minute TTL** to bound storage. Maximum allowed window (`secondary_threshold`) is 60 minutes. If the available snapshot range covers less than 80% of the configured window (e.g., after a backend restart), evaluation is skipped with a debug log until enough data accumulates.

#### Signal Alerts
Triggered on signal emission from the pipeline.

Signal alerts use a JSONB `filters` column instead of the generic `condition`/`threshold` fields, since they match on multiple dimensions simultaneously:

```json
{
  "pair": "BTC-USDT" | null,
  "direction": "LONG" | "SHORT" | null,
  "min_score": 60 | null,
  "timeframe": "1H" | null
}
```

All filter fields are optional (null = match all). A signal must match all non-null filters to trigger the alert.

#### Indicator Alerts
Triggered after `traditional.py` runs on each confirmed candle. Timeframe-aware — a "RSI > 70 on 1H" alert only evaluates on 1H candle closes.

| Condition | Description | Evaluation hook |
|-----------|-------------|-----------------|
| RSI above/below threshold | Mean reversion extremes | After `traditional.py` |
| ADX above threshold | Strong trend detected | After `traditional.py` |
| BB width percentile above/below | Volatility expansion/compression | After `traditional.py` |
| Funding rate exceeds threshold | Funding rate spikes | After `on_funding_rate()` WS callback |

Note: funding rate comes from the OKX public WebSocket (`on_funding_rate()` callback in `ws_client.py`), not from the REST poller (which only handles long/short ratio). The alert evaluator has two indicator hooks: one after technical indicator computation (`traditional.py`), one after the funding rate WebSocket callback.

#### Portfolio Alerts
Triggered on a **new periodic account balance polling loop**. Currently, account balance is only fetched on-demand via API endpoints. A new background task (`collector/account_poller.py`) polls OKX account balance every 60 seconds, caches in Redis (`account:balance`), and invokes portfolio alert evaluation on each fetch.

| Condition | Description |
|-----------|-------------|
| Drawdown from peak exceeds % | Risk warning (peak tracked in Redis + persisted to Alert `peak_value` column as fallback) |
| Total PnL crosses threshold | Milestone / loss limit |
| Single position PnL exceeds loss | Per-position risk |

### Evaluation Flow

Each alert type hooks into a pipeline event:

```
Ticker WS message (new, 1/s)  →  evaluate price alerts (Redis-cached alert list, invalidated on CRUD)
Candle confirmed → indicators →  evaluate indicator alerts (RSI/ADX/BB)
Funding rate WS callback       →  evaluate indicator alerts (funding rate)
Signal emitted                 →  evaluate signal alerts
Account polled (new, 60s)      →  evaluate portfolio alerts
```

Two new background loops are required: backend OKX ticker subscription and periodic account balance polling. The remaining alert types piggyback on existing events.

The evaluator (`engine/alert_evaluator.py`) checks conditions against current values and fires matches. It is stateless except for `pct_move` alerts which query Redis price snapshots. Price alert evaluation uses a Redis-cached list of active price alerts (`alerts:price` key), invalidated whenever alerts are created/updated/deleted via the API. Other alert types query DB directly since they fire at much lower frequency (candle confirmations, signal emissions).

### Alert Delivery

When an alert fires, two delivery mechanisms are used:

1. **WebSocket broadcast** — `broadcast_alert()` on `ConnectionManager` sends to all connected clients (for in-app display)
2. **Push notification** — `dispatch_push_for_alert()` in `push/dispatch.py` sends to all active `PushSubscription` entries (for when app is closed)

Push dispatch logic differs from signal push: alerts do **not** filter by subscription pairs/timeframes/threshold — the alert definition itself is the filter. The push payload includes `urgency` so the service worker can differentiate presentation:

```json
{
  "type": "alert",
  "alert_id": "...",
  "label": "BTC above 70k",
  "trigger_value": 70.2,
  "urgency": "critical"
}
```

**Silent** urgency alerts skip push dispatch entirely (WebSocket + history only). **Normal** and **Critical** alerts both dispatch push. Quiet hours suppression is handled server-side (see Quiet Hours section).

### Cooldown

Each alert has a configurable cooldown (default 15 minutes). Prevents spam when values oscillate around a threshold. One-shot alerts (price crosses) deactivate after firing instead of using cooldown.

### Urgency Levels

User-configurable per alert:

| Level | Push | Sound | Vibration | Quiet Hours |
|-------|------|-------|-----------|-------------|
| Critical | Yes | Yes | Yes | Ignored — always fires |
| Normal | Yes | Yes | Yes | Respected — held until quiet hours end |
| Silent | No | No | No | N/A — badge + in-app history only |

### Quiet Hours

- **Server-side enforcement** for push notifications — the backend checks quiet hours before dispatching push. This is necessary because service workers cannot access localStorage to check client-side settings.
- Quiet hours settings stored in the DB as a global config row (single-user system): `quiet_hours_enabled`, `quiet_hours_start`, `quiet_hours_end`, `quiet_hours_tz`. Managed via `PATCH /api/alerts/settings`.
- Configurable start/end times (default 22:00–08:00), timezone-aware (defaults to UTC, user sets their timezone once)
- Normal alerts during quiet hours: WebSocket event still fires (for in-app history), but **push notification is suppressed**. `AlertHistory.delivery_status` = `silenced_by_quiet_hours`.
- Critical alerts bypass quiet hours — always dispatched via both WS and push
- Global toggles for sound and vibration remain client-side (localStorage in settings store) since they only affect in-app presentation

### Data Model

Single-user system — alerts have no ownership column, matching the existing `PushSubscription` pattern. All alerts belong to the single API key holder.

```
Alert
├── id: UUID
├── type: enum (price, signal, indicator, portfolio)
├── label: str (user-friendly name, e.g. "BTC above 70k", auto-generated if not provided)
├── pair: str | null (null = all pairs, must be in active pairs list if set)
├── timeframe: str | null (null = all, only for indicator type)
├── condition: str | null (crosses_above, crosses_below, pct_move, gt, lt — null for signal type)
├── threshold: float | null (null for signal type)
├── secondary_threshold: float | null (for pct_move: window in minutes, range 5–60)
├── filters: JSONB | null (for signal type: {pair, direction, min_score, timeframe})
├── peak_value: float | null (for portfolio drawdown alerts: persisted peak balance, fallback if Redis loses state)
├── urgency: enum (critical, normal, silent)
├── cooldown_minutes: int (default 15, range 1–1440)
├── is_active: bool (default true)
├── is_one_shot: bool (default false)
├── last_triggered_at: datetime | null
├── created_at: datetime

AlertHistory
├── id: UUID
├── alert_id: FK → Alert
├── triggered_at: datetime
├── trigger_value: float
├── delivery_status: enum (delivered, failed, silenced_by_cooldown, silenced_by_quiet_hours)

AlertSettings (single row, global config)
├── quiet_hours_enabled: bool (default false)
├── quiet_hours_start: str (default "22:00")
├── quiet_hours_end: str (default "08:00")
├── quiet_hours_tz: str (default "UTC", IANA timezone)
```

Notes:
- Signal alerts use `filters` JSONB column; other types use `condition` + `threshold`.
- `label` is included in WebSocket payloads so the frontend can display a human-readable notification without looking up the alert definition.
- `peak_value` is persisted on portfolio drawdown alerts so the peak survives a Redis restart. On each evaluation, the evaluator reads from Redis first, falls back to `peak_value` column, and writes back to both on update.
- `AlertSettings` is a single-row table for global alert configuration. Quiet hours are enforced server-side to ensure push notifications are correctly suppressed even when the app is closed.

### Validation & Limits

- **Max 50 active alerts.** Creation rejected with 409 if limit reached.
- `pair` must be `null` or a member of the configured pairs list (`PipelineSettings.pairs`). When pairs are removed from `PipelineSettings`, alerts targeting removed pairs are automatically deactivated (`is_active = false`). The `PATCH /api/pipeline-settings` response includes a `deactivated_alerts_count` field when this occurs.
- `threshold` required for all types except signal. Must be positive for price alerts.
- `secondary_threshold` (pct_move window): integer, range 5–60 minutes.
- `cooldown_minutes`: range 1–1440 (1 min to 24 hours).
- Signal `filters.min_score`: range 0–100 if set.
- Signal `filters.timeframe`: must be a valid timeframe (15m, 1H, 4H) if set.

### Alert History Retention

`AlertHistory` rows are retained for **30 days**. A periodic cleanup task (runs daily via the existing lifespan background task pattern) deletes rows older than 30 days. The `GET /api/alerts/history` endpoint defaults to last 7 days with optional `since`/`until` query params.

### API Endpoints

```
POST   /api/alerts              — create alert
GET    /api/alerts              — list active alerts
PATCH  /api/alerts/{id}         — update alert (urgency, threshold, active status)
DELETE /api/alerts/{id}         — delete alert
GET    /api/alerts/history      — triggered alert log (paginated)
GET    /api/alerts/settings     — get alert settings (quiet hours)
PATCH  /api/alerts/settings     — update alert settings (quiet hours)
```

All endpoints require `X-API-Key` header, matching existing auth pattern.

### WebSocket Extension

Existing `/ws/signals` connection gains a new event type:

```json
{"type": "alert_triggered", "alert_id": "...", "label": "BTC above 70k", "trigger_value": 70.2, "urgency": "critical"}
```

No new WebSocket connection — reuses the existing backend signals WS. Alert broadcasts use a new `broadcast_alert()` method on `ConnectionManager` that sends to all connected clients (no pair/timeframe filtering), similar to the existing `broadcast_news()` pattern.

### Frontend: Alert Feature Module

New `features/alerts/` module:
- Alert creation form: pick type → pick pair → set condition → set urgency → save
  - Inline validation errors for invalid inputs (threshold, window range, etc.)
  - 409 "max alerts reached" → banner with count and link to manage existing alerts
- Active alerts list with edit/delete
  - Loading skeleton while fetching
  - Empty state: "No alerts configured" with CTA button to create first alert
- Alert history with triggered values and delivery status
  - Empty state: "No alerts triggered yet"
- Accessible from the "More" tab

### Notification Settings

Two layers, matching the existing settings pattern:

**Server-synced** (stored in `AlertSettings` DB table, synced via `PATCH /api/alerts/settings`):
```
├── quiet_hours_enabled: bool (default false)
├── quiet_hours_start: string ("22:00")
├── quiet_hours_end: string ("08:00")
├── quiet_hours_tz: string (user's IANA timezone, detected on first setup)
```

**Client-only** (stored in `features/settings/store.ts` localStorage):
```
├── sound_enabled: bool (default true)
├── vibration_enabled: bool (default true)
```

New "Notifications" section in the existing Settings tab with toggles, time pickers, and timezone selector.

## Mobile Polish

Goal: make the PWA feel native on mobile — small targeted improvements, not a redesign.

### Gestures

- **Pull-to-refresh** on Home, Signals, and News tabs (triggers data refetch)
- **Swipe left/right** on signal cards to quick-journal (mark win/loss) or dismiss. Uses `@use-gesture/react` (~3KB gzipped) for reliable touch handling (velocity thresholds, scroll discrimination). Only active on the Signals list view (not chart or other tabs). Partial swipe reveals a colored background (green for win, red for loss) as visual affordance.
- **Long-press** on a pair in the ticker bar to set a quick price alert. A subtle tooltip ("Hold to set alert") appears on first app launch, stored in localStorage to show only once.

### Transitions & Animations

- Tab switches: subtle cross-fade (CSS transitions, no animation library)
- Signal cards: slide-up with fade on arrival
- Alert toast: slides down from top, auto-dismiss (3s normal, sticky for critical)

### Touch Targets

- Audit all interactive elements for minimum 44x44px tap targets (Apple HIG)
- Increase padding on chart timeframe selector buttons, pair selector chips
- Larger hit areas on signal card action buttons

### Haptic Feedback

Via `navigator.vibrate` where supported (**Android only** — iOS Safari does not support this API). All haptic calls are wrapped in a `tryVibrate()` helper that no-ops when unsupported. The UX does not depend on haptics — they are purely additive.

- Short pulse on signal arrival
- Double pulse on critical alert
- Light tap on tab switch, pull-to-refresh trigger

### Responsive Refinements

- Safe area insets (`env(safe-area-inset-*)`) on bottom nav and top ticker — audit existing
- Prevent body scroll bounce on iOS (`overscroll-behavior: none`)
- Input zoom prevention on iOS (font-size >= 16px on all inputs)

### PWA Enhancements

- Splash screen / app icon audit for iOS and Android
- Confirm standalone display mode (no browser chrome)
- Status bar color matching app theme

## Testing Strategy

### Backend Tests

- `test_alert_evaluator.py` — unit tests for each alert type:
  - Price: crosses above/below, percentage move, cooldown respected
  - Signal: filter matching (pair, direction, score threshold, timeframe)
  - Indicator: RSI/ADX/BB/funding conditions, timeframe-aware evaluation
  - Portfolio: drawdown calculation, PnL thresholds
  - One-shot deactivation after firing
  - Cooldown prevents re-trigger within window
- `test_alert_api.py` — CRUD endpoints, validation (max 50 alerts, invalid pair/threshold/window rejected, required fields per type), history pagination with date filters, 30-day retention cleanup, alert settings CRUD
- `test_alert_push.py` — push dispatch for alerts (Normal/Critical dispatched, Silent skipped), quiet hours suppression (Normal suppressed, Critical bypasses), push payload format
- Existing pipeline tests updated to verify alert evaluation hooks and pair-removal deactivation

### Frontend Tests

- Alert creation form: correct condition options per alert type
- Alert list: active alerts display, edit/delete actions
- Notification toast: correct styling per urgency level
- Quiet hours: normal alerts suppressed, critical alerts pass through

### Mobile Polish — Manual Testing

- Pull-to-refresh on each tab
- Swipe gestures on signal cards
- 44px touch target audit
- Haptic feedback on supported devices
- Safe area rendering on iOS notch devices
- No input zoom on iOS
- PWA standalone mode verification

## Implementation Order

1. Alert system backend: DB models (Alert, AlertHistory, AlertSettings) + Alembic migration, new infrastructure (ticker collector, account poller), alert evaluator, push dispatch (`dispatch_push_for_alert`), API endpoints (CRUD + settings)
2. Alert system frontend: feature module (with loading/empty/error states), notification settings UI (quiet hours synced to server, sound/vibration client-only), WebSocket handling, toast component
3. Mobile polish: gestures (`@use-gesture/react`), haptics (`tryVibrate` helper, Android-only), touch targets, transitions, PWA enhancements
