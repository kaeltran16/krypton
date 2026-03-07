# UI Revamp Design — OKX-Inspired Trading Terminal

## Overview

Full redesign of the Krypton frontend — both visual language and UX flow. Goal: pro trading terminal feel inspired by OKX's mobile app, but slightly more breathable with larger touch targets and more padding.

## Visual Language & Color System

### Theme System

Single source of truth in `web/src/shared/theme.ts`. Tailwind config imports from it. Swapping themes = changing one file.

### Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `bg-primary` | `#0B0E11` | App background |
| `bg-secondary` | `#12161C` | Cards, elevated surfaces |
| `bg-tertiary` | `#1A1F28` | Inputs, interactive areas, hover states |
| `border` | `#1E2530` | Subtle borders between sections |
| `text-primary` | `#EAECEF` | Primary text |
| `text-secondary` | `#848E9C` | Labels, secondary info |
| `text-tertiary` | `#5E6673` | Timestamps, disabled |
| `long` | `#0ECB81` | Buy/profit/bullish |
| `short` | `#F6465D` | Sell/loss/bearish |
| `accent` | `#F0B90B` | Highlights, active tabs, CTAs (gold) |

### Typography

- **UI text:** Inter or system sans-serif
- **Numbers/prices:** JetBrains Mono
- **Base size:** 14px
- **Section headers:** Uppercase, text-tertiary, 10-11px

### Spacing & Touch Targets

- Base unit: 12px
- Card internal padding: 12-16px
- Touch target minimum: 44px height
- Section gaps: 8px (tight) to 12px (standard)

### Borders & Depth

- No shadows
- 1px `border` color borders to separate sections
- Cards are flat with subtle border, not elevated

## Navigation & Layout

### 5-Tab Bottom Navigation

```
┌─────────────────────────────────────────┐
│              [TickerBar]                │
├─────────────────────────────────────────┤
│            Active View                  │
├─────────────────────────────────────────┤
│  Home    Chart   Signals  Journal  More │
└─────────────────────────────────────────┘
```

| Tab | Icon | Content |
|-----|------|---------|
| Home | Grid/dashboard | Account overview, market summary, quick stats |
| Chart | Candlestick | Full TradingView chart + timeframe selector |
| Signals | Lightning bolt | Signal feed with filters |
| Journal | Book | Analytics + calendar |
| More | Dots | Settings, API config |

- Icons: outlined when inactive (text-secondary), filled + gold accent when active
- Labels below icons in 10px text
- Fixed bottom bar with backdrop blur

### Top Bar (TickerBar)

- Deep background matching bg-secondary
- Gold highlight on selected pair
- Compact pair switcher dropdown
- Live price + 24h change

## Home Tab

At-a-glance command center — account status + market overview.

```
┌─────────────────────────────────────────┐
│  Account Balance          ▲ 2.4% today  │
│  $12,450.32               +$291.20      │
├─────────────────────────────────────────┤
│  Unrealized P&L    Available    Margin  │
│  +$84.20           $10,200     18.2%    │
├─────────────────────────────────────────┤
│  Open Positions (2)                     │
│  ┌───────────────────────────────────┐  │
│  │ BTC LONG   +1.2%   $67,420  0.1  │  │
│  │ ETH SHORT  -0.4%   $3,812   1.0  │  │
│  └───────────────────────────────────┘  │
├─────────────────────────────────────────┤
│  Recent Signals (3)                  →  │
│  ┌───────────────────────────────────┐  │
│  │ ⚡ BTC LONG  82  4h     2min ago  │  │
│  │ ⚡ ETH SHORT 74  1h    18min ago  │  │
│  │ ⚡ BTC SHORT 61  15m    1hr ago   │  │
│  └───────────────────────────────────┘  │
├─────────────────────────────────────────┤
│  Performance (7D)                       │
│  Win Rate    Avg R:R    Net P&L         │
│  68.2%       1.8:1      +4.2%           │
└─────────────────────────────────────────┘
```

Sections top-to-bottom:
1. **Account header** — Total balance with daily change, colored green/red
2. **Account strip** — 3-column: unrealized P&L, available balance, margin usage
3. **Open positions** — Compact rows: pair, direction badge, unrealized %, mark price, size
4. **Recent signals** — Latest 3, compact single-line. Arrow links to Signals tab
5. **Performance strip** — 7-day summary: win rate, avg R:R, net P&L

## Chart Tab

Maximizes TradingView widget with minimal chrome.

```
┌─────────────────────────────────────────┐
│  15m   1h   4h   1D                     │
├─────────────────────────────────────────┤
│                                         │
│           TradingView Chart             │
│           (fills available              │
│            vertical space)              │
│                                         │
├─────────────────────────────────────────┤
│  O 67,420  H 67,890  L 67,100  C 67,500│
│  Vol 1.2K          24h Chg +2.1%        │
└─────────────────────────────────────────┘
```

- **Timeframe selector** — Horizontal pills below TickerBar. Active = accent gold background. Options: 15m, 1h, 4h, 1D
- **Chart area** — TradingView widget fills all remaining vertical space
- **OHLC strip** — Bottom bar with Open, High, Low, Close + volume and 24h change in mono font
- **No order entry** — Chart stays clean. Orders placed via signal detail flow

## Signals Tab

Dedicated signal feed with filters and live updates.

```
┌─────────────────────────────────────────┐
│  All    Active    Traded    Skipped      │
├─────────────────────────────────────────┤
│  ┌───────────────────────────────────┐  │
│  │ ⚡ BTC-USDT        LONG     4h   │  │
│  │ Score 82          ██████████░░    │  │
│  │ Entry 67,420  SL 66,800  TP 68,400│  │
│  │ 2 min ago              TP1 ✓     │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │ ⚡ ETH-USDT        SHORT    1h   │  │
│  │ Score 74          ████████░░░░    │  │
│  │ Entry 3,812   SL 3,860   TP 3,740│  │
│  │ 18 min ago             Active     │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Signal cards:**
- Header: pair, direction badge (LONG green / SHORT red), timeframe pill
- Score: numeric + visual bar fill
- Levels: entry, SL, TP in mono font
- Footer: relative timestamp left, outcome/status badge right

**Filters:** horizontal pills — All (default), Active, Traded, Skipped

**Tap to expand:** bottom sheet with full breakdown (score split, AI analysis, price levels, notes, order entry button)

**Live updates:** new signals slide in from top with subtle animation. Connection status indicator in top-right of filter bar.

## Journal Tab

Two sub-views via segmented toggle: Analytics and Calendar.

### Analytics View

```
┌─────────────────────────────────────────┐
│  7D     30D     All                     │
├─────────────────────────────────────────┤
│  Win Rate   Avg R:R   Signals   Net P&L │
│  68.2%      1.8:1     24        +4.2%   │
├─────────────────────────────────────────┤
│  Equity Curve (SVG)                     │
├─────────────────────────────────────────┤
│  Pair Breakdown                         │
│  BTC    72% win   1.9 R:R    16 trades  │
│  ETH    62% win   1.6 R:R     8 trades  │
├─────────────────────────────────────────┤
│  Best Streak  5W  │  Worst Streak  3L   │
└─────────────────────────────────────────┘
```

- Period selector: 7D, 30D, All
- Stats strip, equity curve, pair breakdown, streak tracker
- Time-of-day heatmap removed (noise for most users)

### Calendar View

```
┌─────────────────────────────────────────┐
│  ◄         March 2026            ►      │
├──Mon─Tue─Wed─Thu─Fri─Sat─Sun───────────┤
│   Day cells colored by P&L              │
│   (green = profit, red = loss)          │
├─────────────────────────────────────────┤
│  Mar 5 — 3 signals, +1.8%              │
│  Signal list for selected day           │
└─────────────────────────────────────────┘
```

- Tap day to see signals below with outcome + P&L per signal
- Monthly summary in header

**Key change:** Signal feed removed from Journal — now in dedicated Signals tab. Journal is purely retrospective.

## More Tab

OKX-style grouped settings list.

```
┌─────────────────────────────────────────┐
│  TRADING                                │
├─────────────────────────────────────────┤
│  Pairs                    BTC, ETH  ›   │
│  Timeframes               15m, 1h   ›   │
│  Signal Threshold         ██░░░  65     │
├─────────────────────────────────────────┤
│  NOTIFICATIONS                          │
├─────────────────────────────────────────┤
│  Push Notifications            [  ●]    │
├─────────────────────────────────────────┤
│  CONNECTION                             │
├─────────────────────────────────────────┤
│  API URL              https://...   ›   │
│  Status                    ● Connected  │
├─────────────────────────────────────────┤
│  ABOUT                                  │
├─────────────────────────────────────────┤
│  Version                        1.0.0   │
└─────────────────────────────────────────┘
```

- Grouped rows with uppercase text-tertiary section headers
- Chevron rows open sub-screens/modals
- Toggles and sliders inline
- Account info moved to Home tab

## Technical Requirements

### Theme System
- `web/src/shared/theme.ts` — single source of truth for all design tokens
- `tailwind.config.ts` imports from theme file
- Both Tailwind classes (`bg-primary`) and JS access (`theme.colors.bgPrimary`) supported
- Swap themes by changing one file

### Key Changes from Current
1. Surface colors: `#121212` → `#0B0E11` (deeper)
2. Accent: green → gold (`#F0B90B`) for UI elements, green/red reserved for long/short
3. Navigation: 4 tabs → 5 tabs (signals split out from journal)
4. Home: mini-dashboard → full account overview + market summary
5. Journal: 3 sub-tabs → 2 (feed moved to Signals tab)
6. More: account info removed (moved to Home), pure settings
7. Borders: card shadows → flat 1px borders
8. Typography: add sans-serif for UI text, keep mono for numbers
