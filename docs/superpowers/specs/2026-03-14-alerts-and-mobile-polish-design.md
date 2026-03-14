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

New infrastructure: `collector/ticker.py` subscribes to OKX `tickers` channel for all active pairs, caches latest price in Redis (`ticker:{pair}`), and invokes price alert evaluation on each message.

| Condition | Description | One-shot? |
|-----------|-------------|-----------|
| `crosses_above` | Price crosses above threshold | Yes |
| `crosses_below` | Price crosses below threshold | Yes |
| `pct_move` | Price moves X% within Y minutes | No |

For `pct_move`: the evaluator queries the Redis-cached price snapshots (stored every 1 minute by the ticker collector) to compute the percentage change over the configured window. This avoids maintaining in-memory state in the evaluator.

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
| Funding rate exceeds threshold | Funding rate spikes | After order flow poll (`rest_poller.py`) |

Note: funding rate comes from the order flow dictionary (`app.state.order_flow`), not from `traditional.py`. The alert evaluator has two indicator hooks: one after technical indicator computation, one after order flow polling.

#### Portfolio Alerts
Triggered on a **new periodic account balance polling loop**. Currently, account balance is only fetched on-demand via API endpoints. A new background task (`collector/account_poller.py`) polls OKX account balance every 60 seconds, caches in Redis (`account:balance`), and invokes portfolio alert evaluation on each fetch.

| Condition | Description |
|-----------|-------------|
| Drawdown from peak exceeds % | Risk warning (peak tracked in Redis) |
| Total PnL crosses threshold | Milestone / loss limit |
| Single position PnL exceeds loss | Per-position risk |

### Evaluation Flow

Each alert type hooks into a pipeline event:

```
Ticker WS message (new)       →  evaluate price alerts
Candle confirmed → indicators →  evaluate indicator alerts (RSI/ADX/BB)
Order flow polled              →  evaluate indicator alerts (funding rate)
Signal emitted                 →  evaluate signal alerts
Account polled (new, 60s)      →  evaluate portfolio alerts
```

Two new background loops are required: backend OKX ticker subscription and periodic account balance polling. The remaining alert types piggyback on existing events.

The evaluator (`engine/alert_evaluator.py`) reads active alert rules from DB, checks conditions against current values, and fires matches. It is stateless except for `pct_move` alerts which query Redis price snapshots.

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

- Client-side logic — backend always sends events, frontend decides presentation
- Configurable start/end times (default 22:00–08:00)
- Normal alerts held and delivered as batch summary when quiet hours end
- Critical alerts bypass quiet hours
- Global toggles for sound and vibration

### Data Model

```
Alert
├── id: UUID
├── type: enum (price, signal, indicator, portfolio)
├── label: str (user-friendly name, e.g. "BTC above 70k", auto-generated if not provided)
├── pair: str | null (null = all pairs)
├── timeframe: str | null (null = all, only for indicator type)
├── condition: str | null (crosses_above, crosses_below, pct_move, gt, lt — null for signal type)
├── threshold: float | null (null for signal type)
├── secondary_threshold: float | null (for pct_move: window in minutes)
├── filters: JSONB | null (for signal type: {pair, direction, min_score, timeframe})
├── urgency: enum (critical, normal, silent)
├── cooldown_minutes: int (default 15)
├── is_active: bool (default true)
├── is_one_shot: bool (default false)
├── last_triggered_at: datetime | null
├── created_at: datetime

AlertHistory
├── id: UUID
├── alert_id: FK → Alert
├── triggered_at: datetime
├── trigger_value: float
├── delivery_status: enum (delivered, failed, silenced_by_cooldown)
```

Notes:
- Signal alerts use `filters` JSONB column; other types use `condition` + `threshold`.
- `label` is included in WebSocket payloads so the frontend can display a human-readable notification without looking up the alert definition.
- `delivery_status` does not include `silenced_by_quiet_hours` — quiet hours are enforced client-side, so the backend cannot know. Quiet hours suppression is tracked in the frontend's local alert history only.

### API Endpoints

```
POST   /api/alerts              — create alert
GET    /api/alerts              — list active alerts
PATCH  /api/alerts/{id}         — update alert (urgency, threshold, active status)
DELETE /api/alerts/{id}         — delete alert
GET    /api/alerts/history      — triggered alert log (paginated)
```

### WebSocket Extension

Existing `/ws/signals` connection gains a new event type:

```json
{"type": "alert_triggered", "alert_id": "...", "label": "BTC above 70k", "trigger_value": 70.2, "urgency": "critical"}
```

No new WebSocket connection — reuses the existing backend signals WS. Alert broadcasts use a new `broadcast_alert()` method on `ConnectionManager` that sends to all connected clients (no pair/timeframe filtering), similar to the existing `broadcast_news()` pattern.

### Frontend: Alert Feature Module

New `features/alerts/` module:
- Alert creation form: pick type → pick pair → set condition → set urgency → save
- Active alerts list with edit/delete
- Alert history with triggered values and delivery status
- Accessible from the "More" tab

### Notification Settings

Stored in `features/settings/store.ts` (localStorage):

```
notification_settings:
├── quiet_hours_enabled: bool (default false)
├── quiet_hours_start: string ("22:00")
├── quiet_hours_end: string ("08:00")
├── sound_enabled: bool (default true)
├── vibration_enabled: bool (default true)
```

New "Notifications" section in the existing Settings tab with toggles and time pickers.

## Mobile Polish

Goal: make the PWA feel native on mobile — small targeted improvements, not a redesign.

### Gestures

- **Pull-to-refresh** on Home, Signals, and News tabs (triggers data refetch)
- **Swipe left/right** on signal cards to quick-journal (mark win/loss) or dismiss
- **Long-press** on a pair in the ticker bar to set a quick price alert

### Transitions & Animations

- Tab switches: subtle cross-fade (CSS transitions, no animation library)
- Signal cards: slide-up with fade on arrival
- Alert toast: slides down from top, auto-dismiss (3s normal, sticky for critical)

### Touch Targets

- Audit all interactive elements for minimum 44x44px tap targets (Apple HIG)
- Increase padding on chart timeframe selector buttons, pair selector chips
- Larger hit areas on signal card action buttons

### Haptic Feedback

Via `navigator.vibrate` where supported:
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
- `test_alert_api.py` — CRUD endpoints, validation, history pagination
- Existing pipeline tests updated to verify alert evaluation hooks

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

1. Alert system backend: DB models + Alembic migration, new infrastructure (ticker collector, account poller), alert evaluator, API endpoints
2. Alert system frontend: feature module, notification settings UI, WebSocket handling, toast component
3. Mobile polish: gestures, haptics, touch targets, transitions, PWA enhancements
