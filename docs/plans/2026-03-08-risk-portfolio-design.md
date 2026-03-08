# Risk & Portfolio Management Design

## Overview

Add comprehensive risk management and portfolio tracking to Krypton: position sizing recommendations, real-time portfolio dashboard, configurable risk controls with soft blocks, and advanced performance analytics.

**Assumptions:** Single-user system (API key auth). All positions are linear USDT-margined perpetuals on OKX. All timestamps in UTC.

## 1. Position Sizing Engine

### Backend: `backend/app/engine/risk.py` — `PositionSizer`

Calculates recommended position size per signal based on account equity and risk parameters.

**Inputs:** account equity (OKX, cached 30s in Redis), risk per trade %, entry price, stop-loss price

**Core formula (linear USDT-margined perps):**

```
risk_amount = equity × risk_per_trade
sl_distance = |entry - stop_loss| / entry
position_size_usd = risk_amount / sl_distance
position_size_base = position_size_usd / entry    # e.g. BTC quantity
```

Note: `position_size_base` is the quantity in the base asset (e.g., 0.3 BTC). OKX lot size and minimum order size are fetched from `/api/v5/public/instruments` and cached for 1 hour in Redis.

**Risk/Reward ratios:**

```
tp1_rr = |tp1 - entry| / |entry - stop_loss|
tp2_rr = |tp2 - entry| / |entry - stop_loss|
```

**Safety caps (applied after calculation):**

1. Clamp to `maxPositionSize` if set
2. Cap at 25% of account equity
3. Round down to OKX-compatible lot size (from instruments API)

### Signal enrichment

When a signal is generated, the backend enriches it with a `risk_metrics` field. **If OKX client is unavailable** (credentials not configured), `risk_metrics` is omitted (set to `null`) and the signal is still published normally with R:R ratios only.

```json
{
  "position_size_usd": 20270,
  "position_size_base": 0.3003,
  "risk_amount_usd": 150,
  "risk_pct": 1.0,
  "tp1_rr": 2.3,
  "tp2_rr": 4.1
}
```

### Frontend: Signal card "Risk" section

Each signal card displays: `Size: 0.3 BTC | Risk: $150 (1.0%) | R:R: 1:2.3 / 1:4.1`

If `risk_metrics` is null (OKX unavailable), show only R:R ratios (computed client-side from levels) and a muted "Connect OKX for sizing" hint.

Order dialog pre-fills recommended size when opened from a signal.

### User settings

- `riskPerTrade`: 0.5% / 1% / 2% / custom (default: 1%)
- `maxPositionSize`: optional USD cap
- Stored in `risk_settings` table (Postgres)

---

## 2. Portfolio Dashboard

### Backend: `GET /api/account/portfolio`

Aggregated view returning:

- Total equity, available balance, used margin
- Open positions with unrealized P&L
- Total exposure (sum of notional values)
- Margin utilization % (used_margin / total_equity)

Returns `{"error": "OKX not configured"}` with HTTP 503 if OKX client is unavailable.

### Frontend: Portfolio card on Home tab

Extend the existing `useAccount()` hook (which already polls every 10s) with the additional aggregation fields (exposure, margin utilization). No separate polling — reuse the existing 10s interval.

Collapsible card at the top of the Home dashboard:

```
Portfolio Overview
──────────────────
Equity     $15,234.50  (+2.1%)
Available  $12,100.00
Margin     $3,134.50   (20.6%)
──────────────────
Open Positions (2)
BTC LONG   +$245.30  (+1.2%)
ETH SHORT  -$32.10   (-0.4%)
──────────────────
Exposure   $20,500 (134% eq)
```

- Color-coded: green for profit, red for loss
- Tap position to expand: entry price, size, liquidation price, margin mode

**UI states:**
- **Loading:** skeleton placeholder matching card layout
- **Error / OKX unavailable:** "Unable to load portfolio" with retry button
- **Empty (no positions):** "No open positions" with muted text

---

## 3. Risk Controls

### Backend: `backend/app/engine/risk.py` — `RiskGuard`

Evaluates whether a trade should be allowed. Returns `RiskCheck` with status (`OK | WARNING | BLOCKED`), triggered rules, and reasons.

### Rules (all configurable):

| Rule | Default | Check |
|------|---------|-------|
| Daily loss limit | -3% of equity | Sum realized P&L from today's (UTC) fills via OKX `/api/v5/trade/fills-history`, cached 60s in Redis |
| Max concurrent positions | 3 | Count open positions from OKX |
| Max exposure | 150% of equity | Sum notional of all positions |
| Cooldown after loss | Off | Time since last SL_HIT signal globally (all pairs), checked against `signals` table |
| Max risk per trade | 2% | From position sizer |

### Backend endpoint

`POST /api/risk/check`

**Request schema:**
```json
{
  "pair": "BTCUSDT",
  "direction": "LONG",
  "size_usd": 20270
}
```

`size_usd` is the actual intended trade size (may differ from position sizer recommendation if user adjusted it in the order dialog).

**Response:**
```json
{
  "status": "BLOCKED",
  "rules": [
    {"rule": "daily_loss_limit", "status": "BLOCKED", "reason": "Daily loss -3.2% exceeds -3.0% limit"},
    {"rule": "max_concurrent", "status": "OK", "reason": "2/3 positions open"}
  ]
}
```

Returns HTTP 503 if OKX client is unavailable.

### Frontend: Soft blocks

- Call `/api/risk/check` when user taps "Trade" on a signal (before opening order dialog)
- **BLOCKED:** order button disabled, red banner with triggered rule(s), "Override" button requires typed confirmation ("OVERRIDE")
- **WARNING:** order button enabled, yellow advisory banner
- **OK:** normal flow
- **API error / 503:** show yellow "Risk check unavailable" banner, allow trading

### Override audit

When a user overrides a BLOCKED risk check, the override is logged by sending `override: true` and the triggered rules to `POST /api/account/order`. The order record (or a separate `risk_overrides` log entry in Redis) stores which rules were overridden, for post-trade journal review.

### Settings

Stored in `risk_settings` table in Postgres. Configurable via Settings ("More") tab UI under a new "Risk Management" section.

---

## 4. Performance Deep-Dive

### Backend: Extended `GET /api/signals/stats`

New metrics added to stats response:

| Metric | Formula | Guards |
|--------|---------|--------|
| Sharpe Ratio | `mean(daily_returns) / std(daily_returns) * sqrt(365)` | Returns `null` if < 7 days of data or std = 0 |
| Max Drawdown | Largest peak-to-trough decline in cumulative P&L | Returns `0` if no resolved trades |
| Profit Factor | `sum(winning_pnl) / abs(sum(losing_pnl))` | Returns `null` if no losing trades (avoid div/0) |
| Expectancy | `(win_rate * avg_win) - (loss_rate * avg_loss)` | Returns `null` if no resolved trades |
| Avg Hold Time | Mean `outcome_duration_minutes` | Returns `null` if no resolved trades |
| Best/Worst Trade | Highest and lowest `outcome_pnl_pct` | Returns `null` if no resolved trades |

**Daily returns derivation:** `SUM(outcome_pnl_pct) GROUP BY DATE(outcome_at)` on resolved signals (outcome != PENDING). This is signal-level return aggregation, not account equity snapshots.

All filterable by pair, timeframe, direction, date range.

### Frontend: "Deep Dive" section in Journal tab

```
Performance Metrics
──────────────────
Sharpe    1.82    Profit F 2.1
Max DD   -4.3%    Expectancy
Avg Hold  3.2h    +0.45%/trade
──────────────────
Best   +5.2% (BTC 4h LONG)
Worst  -2.1% (ETH 1h SHORT)
```

- Drawdown chart: line chart showing drawdown % over time
- Distribution histogram: P&L % distribution across trades
- Reactive to filter changes (pair/timeframe/date range)

**UI states:**
- **Loading:** skeleton placeholders for metric grid and charts
- **Empty (< 5 resolved trades):** "Need more resolved trades to show metrics" with muted text, hide charts
- **Null metrics:** show "—" dash instead of number with tooltip explaining why (e.g., "Not enough data")

---

## Data Model Changes

### New table: `risk_settings` (singleton)

Single-row table. Migration seeds one row with defaults. All reads fetch `id = 1`. Updates use `UPDATE WHERE id = 1`.

```sql
CREATE TABLE risk_settings (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  risk_per_trade FLOAT DEFAULT 0.01,
  max_position_size_usd FLOAT,
  daily_loss_limit_pct FLOAT DEFAULT 0.03,
  max_concurrent_positions INT DEFAULT 3,
  max_exposure_pct FLOAT DEFAULT 1.5,
  cooldown_after_loss_minutes INT,
  max_risk_per_trade_pct FLOAT DEFAULT 0.02,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed default row
INSERT INTO risk_settings (id) VALUES (1);
```

### Signal model extension

Add `risk_metrics` JSONB column (nullable) to the `signals` table.

Note: JSONB is acceptable since no analytics query aggregates over risk_metrics fields. If future analysis needs risk sizing data, consider denormalizing to flat columns at that point.

---

## Migrations (Alembic)

All migrations in `backend/app/db/migrations/versions/`.

### Migration 1: `create_risk_settings_table`
- `upgrade()`: CREATE `risk_settings` table with `CHECK (id = 1)`, INSERT seed row
- `downgrade()`: DROP TABLE `risk_settings`

### Migration 2: `add_risk_metrics_to_signals`
- `upgrade()`: `ALTER TABLE signals ADD COLUMN risk_metrics JSONB`
- `downgrade()`: `ALTER TABLE signals DROP COLUMN risk_metrics`

Both migrations are safe to deploy independently — no data loss on rollback since `risk_metrics` is nullable and `risk_settings` is new.

---

## OKX Client Additions

New methods needed on `OKXClient`:

- `get_instruments(inst_type="SWAP")` → fetch and cache (1h) lot size, min order size, tick size per instrument from `/api/v5/public/instruments`
- `get_fills_today()` → fetch today's (UTC) fills from `/api/v5/trade/fills-history` with `begin` = start of UTC day, cached 60s in Redis

---

## Testing

### Unit tests (`backend/tests/`)

- `test_position_sizer.py`: core formula, safety caps, edge cases (zero SL distance, very small equity, missing OKX client returns null)
- `test_risk_guard.py`: each rule in isolation (daily loss tripped, max positions tripped, cooldown active, OK scenario), aggregate result with mixed statuses
- `test_performance_metrics.py`: Sharpe with known data, div-by-zero guards, empty dataset returns nulls, profit factor with no losses

### Integration tests

- `test_risk_api.py`: `POST /api/risk/check` with valid/blocked/warning scenarios, 503 when OKX unavailable, auth required
- `test_portfolio_api.py`: `GET /api/account/portfolio` returns aggregated data, 503 when OKX unavailable

---

## Implementation Order

1. Alembic migrations (risk_settings table + risk_metrics column)
2. Position sizing engine + signal enrichment + unit tests
3. Risk settings CRUD API (`GET/PUT /api/risk/settings`)
4. Portfolio dashboard (backend endpoint + frontend, extend existing `useAccount` hook)
5. Risk controls (RiskGuard + `/api/risk/check` + frontend soft blocks + override logging)
6. Performance deep-dive metrics + charts + frontend empty/null states
