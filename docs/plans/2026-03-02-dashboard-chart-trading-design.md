# Phase 1: Dashboard, Chart & OKX Trading Integration

## Overview

Expand Krypton from a signal-only app to a full trading dashboard with real-time charts, OKX account integration, and semi-auto trade execution.

## Architecture

Backend-proxied approach: OKX private API keys stay server-side. All account and trading requests go through the backend. Frontend never handles credentials.

## UI Layout

4-tab PWA: Dashboard | Chart | Signals (existing) | Settings (existing)

## Backend Changes

### New: OKX Private Client (`app/exchange/okx_client.py`)

Authenticated REST client for OKX private API:
- `get_balance()` -- account equity, available balance, margin
- `get_positions()` -- open positions with unrealized P&L
- `place_order(pair, side, size, order_type, sl, tp)` -- place an order
- Uses HMAC-SHA256 signing per OKX API spec
- Configurable for demo/live via `OKX_DEMO` env var

### New: Account API (`app/api/account.py`)

- `GET /api/account/balance` -- proxied balance
- `GET /api/account/positions` -- proxied positions
- `POST /api/account/order` -- place order with validation
  - Requires: pair, direction, size, entry, stop_loss, take_profit
  - Validates params before forwarding to OKX
  - Returns order result

### New: Candles API (`app/api/candles.py`)

- `GET /api/candles?pair=...&timeframe=...&limit=200` -- historical candles from Redis

### Extended: WebSocket

Stream live candle ticks alongside signals:
- Message type `"candle"` with pair, timeframe, OHLCV, confirmed flag
- Frontend subscribes to candle updates for the selected pair/timeframe

### New Environment Variables

```
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
OKX_DEMO=true
```

## Frontend Changes

### New: Dashboard (`features/dashboard/`)

Three stacked sections:
1. **Account Summary** -- total equity, unrealized P&L, available balance
2. **Open Positions** -- pair, side, size, entry price, mark price, unrealized P&L, liquidation price. Color-coded by P&L.
3. **Recent Signals** -- signal cards with "Execute" button

### New: Chart (`features/chart/`)

- Pair selector (BTC-USDT-SWAP / ETH-USDT-SWAP)
- Timeframe buttons (15m, 1h, 4h)
- Full-width candlestick chart using `lightweight-charts`
- Overlays: EMA 9/21/50, Bollinger Bands
- Signal markers: green up-arrow (LONG), red down-arrow (SHORT)
- Live candle updates via WebSocket

### New: Trading Flow (`features/trading/`)

Order confirmation dialog:
1. Pre-filled from signal: pair, direction, entry, SL, TP
2. User inputs position size
3. User reviews and clicks "Confirm"
4. Backend validates and places order via OKX
5. Frontend shows success/failure

### Modified: Layout

Expand from 2 tabs to 4: Dashboard, Chart, Signals, Settings

### New Dependency

- `lightweight-charts` (TradingView open-source charting)

## Data Flow

```
OKX Public WS --> Backend Collector --> Redis Cache --> GET /api/candles --> Chart
OKX Public WS --> Backend Collector --> Signal Engine --> WS broadcast --> Signals tab
OKX Private API <-- Backend okx_client <-- POST /api/account/order <-- Trading dialog
OKX Private API --> Backend okx_client --> GET /api/account/* --> Dashboard
```

## Future Phases (not in scope)

- Backtesting engine
- Multi-exchange support (Binance, Bybit)
- Signal history table with hit-rate tracking
- Portfolio P&L tracking over time
