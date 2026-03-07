# Mobile UI Redesign + Signal Accuracy Tracking

**Date:** 2026-03-05
**Scope:** Full mobile-first PWA UI overhaul (OKX-style) + backend signal accuracy tracking

---

## Design Goals

- **Mobile-first iOS PWA** — desktop is not a priority
- **OKX mobile app style** — dark, data-dense, crypto-native, touch-friendly
- **Signal accuracy tracking** — track whether signals hit TP/SL, show win rate and stats
- **Four tabs:** Home (overview), Chart (full analysis), Signals (feed + performance), More (account + settings)

---

## 1. Global Elements

### Sticky Top Bar (all tabs)
- Left: Pair selector dropdown (BTC-USDT, ETH-USDT, etc.)
- Right: Live price + 24h % change (green/red), real-time via WebSocket
- Height: ~44px, `backdrop-blur` background
- Subtle bottom border

### Bottom Navigation
- 4 tabs: Home, Chart, Signals, More
- iOS safe area padding for home indicator
- Active tab: green accent, inactive: gray

---

## 2. Home Tab (Overview)

Single scrollable view combining key data:

### Mini Chart (~200px)
- Compact candlestick chart for selected pair/timeframe
- Timeframe toggle (15m / 1h / 4h) below chart
- Tap chart to jump to full Chart tab

### Indicator Strip (horizontal scroll)
- Small pills: `RSI 62` `MACD` `EMA` `BB`
- Color-coded: green=bullish, red=bearish, gray=neutral

### Latest Signals (2-3 most recent)
- Compact signal cards: direction, score, pair, entry/TP/SL
- Tap to expand detail in bottom sheet
- "View all" link to Signals tab

### Signal Performance Strip
- Win rate %, average R:R, signals count (last 7d)

---

## 3. Chart Tab (Full Analysis)

### Main Chart (~65% screen height)
- Full candlestick chart with signal markers (triangles on candles where signals fired)
- Tap marker to see signal detail in bottom sheet
- EMA lines and Bollinger Bands as overlays
- Pinch-to-zoom, drag to scroll

### Timeframe Selector
- 15m / 1h / 4h toggle buttons

### Indicator Toggle Row
- Toggle buttons: EMA, BB, RSI, Volume
- Selected indicators show as sub-charts below main chart

### Sub-Charts (toggleable, ~80px each)
- RSI chart with overbought/oversold lines
- Volume bars

---

## 4. Signals Tab (Feed + Performance)

### Performance Header (7-day stats)
- Three-column grid: Win %, R:R, Signal count
- Per-pair breakdown below (e.g., "BTC: 72% win | ETH: 58%")

### Signal Feed (scrollable list)
- Each card shows: pair, direction, score, timeframe, entry/TP/SL
- Outcome badge on resolved signals: TP1_HIT, TP2_HIT, SL_HIT, EXPIRED
- Active (PENDING) signals show live P&L %
- Resolved signals show: actual % move, duration
- Tap for full detail in bottom sheet

---

## 5. More Tab (Account + Settings)

Expandable sections:
- Account balance + equity
- Open positions list
- Settings: pairs, timeframes, threshold, notifications, API URL

---

## 6. Signal Accuracy Tracking (Backend)

### Resolution Logic
Background task monitors price after signal emission:
- Price hits TP1 → `TP1_HIT`
- Price hits TP2 → `TP2_HIT`
- Price hits SL → `SL_HIT`
- 24h elapsed, nothing hit → `EXPIRED`
- Check on each candle close for the signal's pair/timeframe

### New Signal Model Fields
- `outcome`: enum (TP1_HIT, TP2_HIT, SL_HIT, EXPIRED, PENDING)
- `outcome_at`: timestamp
- `outcome_pnl_pct`: % move from entry to outcome price
- `outcome_duration_minutes`: resolution time

### Aggregate Stats (cached in Redis)
- Win rate = TP hits / total resolved
- Average R:R achieved
- Per-pair and per-timeframe breakdowns
- Rolling 7-day window

### API Endpoints
- `GET /api/signals/stats` — aggregate performance stats
- `GET /api/signals` — existing endpoint, add outcome fields to response

---

## 7. iOS PWA Considerations

- Safe area insets (notch + home indicator)
- `apple-mobile-web-app-capable` meta tag
- Standalone display mode
- Haptic feedback on new signal arrival (if supported)
- Pull-to-refresh on signal feed
- Bottom sheet modals (native-feeling slide-up)
- Touch targets minimum 44px
- Smooth 60fps scrolling
- `overscroll-behavior: none` to prevent Safari bounce
