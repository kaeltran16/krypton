# Krypton - OKX Crypto Trading Copilot MVP Design

## overview

**Krypton** — AI-enhanced crypto futures trading copilot for OKX. Provides real-time trade signals by combining traditional technical analysis with LLM-powered contextual reasoning. Read-only — no trade execution.

## requirements

- **trading type:** futures/perpetuals on OKX
- **pairs:** 1-3 majors (BTC-USDT-SWAP, ETH-USDT-SWAP)
- **timeframe:** day trading (15m, 1h, 4h candles)
- **core feature:** trade signals with entry/SL/TP levels
- **interaction:** react native mobile app (OKX-style dark UI)
- **automation:** read-only, signals and recommendations only
- **LLM provider:** openrouter (model-agnostic)
- **deployment:** docker + docker-compose on VPS

## architecture

```
OKX WebSocket/REST API
    │
    ├── ws: candles (15m, 1h, 4h per pair)
    ├── ws: funding rate
    ├── ws: open interest
    └── rest: long/short ratio (polled every 5min)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                   BACKEND (Docker)                           │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  OKX Data    │───>│  Signal      │───>│  FastAPI     │  │
│  │  Collector   │    │  Engine      │    │  + WebSocket  │  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘  │
│                                                  │          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              PostgreSQL + Redis                       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                    WebSocket + Push Notifications
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              MOBILE APP (React Native / Expo)                │
│                                                             │
│  ┌────────────────────┐    ┌────────────────────┐          │
│  │  Signal Feed (Home) │    │  Settings           │          │
│  └────────────────────┘    └────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### docker-compose services

- **api** — fastapi backend (python 3.11)
- **postgres** — candle history, signal log
- **redis** — live data cache, rate limiting, websocket pub/sub

## signal engine (hybrid)

two-layer hybrid architecture: traditional indicators provide precise math, LLM adds contextual reasoning.

### layer 1: traditional engine (always runs)

```
technical analysis (weight in combined: 0.60 of traditional)
  - trend: EMA(9, 21, 50), MACD
  - momentum: RSI(14)
  - volatility: bollinger bands, ATR
  - output: technical_score (-100 to +100)

order flow analysis (weight in combined: 0.40 of traditional)
  - funding rate (current + 8h/24h trend)
  - open interest change (1h/4h/24h)
  - long/short ratio (OKX top traders)
  - output: order_flow_score (-100 to +100)

preliminary_score = technical * 0.60 + order_flow * 0.40
```

### layer 2: LLM analysis (runs when |preliminary_score| >= 30)

```
input:
  - all computed indicator values
  - order flow metrics
  - preliminary score + direction
  - recent candle data (last 20 candles)

provider: openrouter (model-agnostic, swap claude/gpt/llama)

output:
  - opinion: confirm | caution | contradict
  - confidence: HIGH | MEDIUM | LOW
  - explanation: human-readable analysis
  - suggested entry/SL/TP with reasoning
```

### combiner

```
traditional_score * 0.60 + llm_adjustment * 0.40

llm "confirm"    → boosts score by up to +20 points
llm "caution"    → dampens score by up to -15 points
llm "contradict" → caps final score at 40 (never triggers alert)
llm unavailable  → traditional score used standalone (weights not redistributed)
```

### signal output

```json
{
  "pair": "BTC-USDT-SWAP",
  "timeframe": "15m",
  "direction": "LONG",
  "final_score": 78,
  "confidence": "HIGH",
  "traditional_score": 72,
  "llm_opinion": "confirm",
  "explanation": "Strong bullish setup. RSI(32) recovering from oversold...",
  "levels": {
    "entry": 67420,
    "stop_loss": 66890,
    "take_profit_1": 67950,
    "take_profit_2": 68480
  },
  "timestamp": "2026-02-27T14:30:00Z"
}
```

## mobile app

### screen 1: signal feed (home)

- real-time signal cards via websocket
- color-coded: green (long), red (short), gray (neutral)
- tap card to expand full explanation + score breakdown
- filter by pair and timeframe
- only signals above configurable threshold (default: |score| >= 50)

### screen 2: settings

- pair selection (which futures pairs to monitor)
- alert threshold (minimum |score| to trigger notification)
- notification preferences (sound, vibration, quiet hours)
- OKX API key input (read-only key, optional for future features)

### UI direction

OKX-style dark theme for seamless context switching between apps:
- dark background (#121212 / #1A1A1A)
- accent green for long/profit, red for short/loss
- white primary text, gray secondary
- card-based layout with subtle borders
- compact data density — information-first
- monospace numbers for prices and scores

## data flow

1. OKX WebSocket delivers candle close event
2. data collector stores candle in postgres, caches in redis
3. signal engine triggered on candle close
4. layer 1 calculates indicators + order flow → preliminary score
5. if |preliminary_score| >= 30 → layer 2 sends data to openrouter LLM
6. combiner produces final score
7. if |final_score| >= threshold → signal saved to postgres
8. signal broadcast via websocket to connected mobile clients
9. push notification sent via expo for high-confidence signals

## error handling

| failure | behavior |
|---------|----------|
| OKX websocket drops | auto-reconnect with exponential backoff (1s→60s max), fall back to REST polling |
| traditional engine error | log error, no signal emitted for that candle |
| LLM API error/timeout | skip LLM layer, use traditional score standalone |
| LLM returns invalid response | parse error logged, fall back to traditional score |
| postgresql down | signals computed from redis cache, history not persisted until recovery |
| redis down | fall back to in-memory cache, reduced performance |
| mobile websocket drops | auto-reconnect, fetch missed signals via REST on reconnect |
| OKX API rate limit | backoff + queue (OKX allows 20 req/2s REST) |

## tech stack

| component | technology |
|-----------|-----------|
| backend | python 3.11 + fastapi + websocket |
| containerization | docker + docker-compose |
| database | postgresql |
| cache | redis |
| data source | OKX websocket + REST API |
| signal engine | hybrid: traditional (pandas-ta) + LLM (openrouter) |
| mobile | react native (expo) |
| UI | OKX-style dark theme |
| push notifications | expo push notifications |
| hosting | VPS with docker ($5-10/month) + openrouter API |

## LLM cost estimate

- ~288 candle closes/day (3 pairs x 96 fifteen-minute candles)
- pre-filter: only call LLM when |preliminary_score| >= 30
- estimated ~40-60 LLM calls/day
- at ~$0.02/call (fast model) → ~$1-2/day (~$30-60/month)

## expansion backlog (post-MVP)

- chart view with indicator overlays and signal levels
- position monitor (read OKX positions, show PnL/liquidation)
- trade journal (auto-log trades, track signal accuracy, monthly stats)
- ML pattern recognition layer (trained on own signal history)
- telegram alerts as secondary notification channel
- multi-timeframe confluence analysis
- backtesting engine for signal strategy validation

## decisions and trade-offs

| decision | rationale |
|----------|-----------|
| hybrid over LLM-first | LLMs can't reliably do math; traditional indicators handle precision. LLMs add contextual reasoning on top. system still works if LLM is unavailable. |
| hybrid over traditional-only | LLM catches patterns rigid rules miss (bear traps, divergences). richer explanations help trader make informed decisions. |
| openrouter over direct API | model-agnostic — swap claude/gpt/llama without code changes. single billing. same pattern used in SIEM project. |
| react native over flutter/PWA | cross-platform from one JS codebase. large ecosystem for real-time data. expo simplifies push notifications and builds. |
| docker over bare metal | reproducible deployment. easy to spin up postgres + redis alongside api. matches existing SIEM devops patterns. |
| read-only over trade execution | eliminates risk of bugs placing real orders. lower OKX API permission requirements. can add execution later as opt-in. |
| 2 screens over full dashboard | MVP focus — ship core value (signals) fast. chart/journal/positions are expansion features. |
