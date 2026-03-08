# Market Data & Signals Expansion — Design

**Date**: 2026-03-08
**Status**: Draft (revised after review)

## Goal

Enrich the signal pipeline with alternative data sources (on-chain metrics, news/macro events) and expose them through new UI surfaces. Three pillars:

1. **On-chain data** — quantitative scoring input blended into the signal pipeline
2. **News & events** — crypto + macro headlines scored by LLM, triggering standalone alerts and enriching the LLM gate
3. **Frontend** — dedicated News tab, alert toasts, signal-news correlation badges

## Architecture Overview

```
┌─────────────────┐   ┌─────────────────┐
│  On-Chain        │   │  News Collector  │
│  Collector       │   │  (API + RSS)     │
│  (5 min poll)    │   │  (2-3 min poll)  │
└───────┬─────────┘   └───────┬──────────┘
        │                     │
        ▼                     ▼
  Redis cache            Postgres + Redis
  (metrics by pair)      (headlines + LLM scores)
        │                     │
        ├──────────┬──────────┘
        ▼          ▼
  ┌──────────────────────┐
  │   Signal Pipeline     │
  │                       │
  │  Tech (50%)           │
  │  + Order Flow (25%)   │
  │  + On-Chain (25%)     │
  │  → LLM gate (with    │
  │    news context)      │
  └──────────┬────────────┘
             │
        ┌────┴────┐
        ▼         ▼
    Signals    News Alerts
    (existing)  (new type)
```

---

## 1. On-Chain Data Collector

### Module: `app/collector/onchain.py`

Background async loop polling two tiers of data sources every 5 minutes.

### Tier 1 — Free Public APIs

| Source | Metrics | Endpoint | Notes |
|--------|---------|----------|-------|
| Mempool.space | Large BTC transactions (>100 BTC), mempool fee pressure | `GET /api/mempool/recent` | No API key, reliable, well-documented |
| CoinGecko free tier | Developer activity, community metrics | `/api/v3/coins/{id}` | 10-30 req/min on free tier |

### Tier 2 — Freemium Providers (poll every 30 minutes, not 5)

| Source | Metrics | Free tier limit | Notes |
|--------|---------|-----------------|-------|
| CryptoQuant free tier | Exchange netflow, MVRV ratio | ~10 req/day | Poll every 30 min, cache aggressively |
| Glassnode free tier | Active addresses, exchange balance, NUPL | ~10 req/day | Poll every 30 min, cache aggressively |

> **Note:** Tier 2 free-tier limits are tight. The collector polls Tier 1 every 5 minutes but Tier 2 only every 30 minutes. If Tier 2 quotas are exhausted, the collector skips silently until the next day.

### Caching Strategy

- Redis key pattern: `onchain:{pair}:{metric}` with 10-min TTL
- Rolling 24h history per metric stored in Redis for trend calculation
- Graceful degradation: if a provider is down or rate-limited, skip it and use available data

### Scoring: `app/engine/onchain_scorer.py`

`compute_onchain_score(pair) → -100 to +100`

| Metric | Signal | Points |
|--------|--------|--------|
| Exchange netflow | Large inflows = bearish, outflows = bullish | ±35 |
| Whale movements | Transfers to exchanges = bearish, to cold wallets = bullish | ±25 |
| NUPL / MVRV | Extreme greed = bearish, extreme fear = bullish (contrarian) | ±20 |
| Active addresses trend | Rising = bullish momentum, falling = bearish | ±20 |

### Updated Combiner

Previous: `tech(60%) + flow(40%)` via single `engine_traditional_weight` knob.

New signature:

```python
def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    onchain_score: int,
    tech_weight: float = 0.50,
    flow_weight: float = 0.25,
    onchain_weight: float = 0.25,
) -> int:
    total = tech_weight + flow_weight + onchain_weight
    if abs(total - 1.0) > 0.01:
        # auto-normalize to prevent misconfiguration
        tech_weight, flow_weight, onchain_weight = (
            tech_weight / total, flow_weight / total, onchain_weight / total
        )
    return round(
        technical_score * tech_weight
        + order_flow_score * flow_weight
        + onchain_score * onchain_weight
    )
```

Three independent config keys (flat, matching existing convention):
- `engine_traditional_weight: 0.50`
- `engine_flow_weight: 0.25`
- `engine_onchain_weight: 0.25`

**Fallback when on-chain is unavailable:** The caller in `run_pipeline` passes `onchain_score=0` and redistributes weights: `tech_weight = settings.engine_traditional_weight + settings.engine_onchain_weight * 0.6`, `flow_weight = settings.engine_flow_weight + settings.engine_onchain_weight * 0.4`. This keeps the tech/flow ratio roughly preserved.

---

## 2. News & Events Collector

### Module: `app/collector/news.py`

Background async loop polling API sources and RSS feeds every 2-3 minutes.

### API Sources

| Source | Coverage | Notes |
|--------|----------|-------|
| CryptoPanic API (free tier) | 50+ crypto outlets, importance flags, currency filters | Primary crypto source |
| CoinGecko news endpoint | Supplementary crypto headlines | Backup |
| NewsData.io or GNews.io (free tier) | General world news with category filters | Macro/world events |

### RSS Feeds (configurable via `config.yaml`)

**Macro/Financial:**
- AP News Business
- CNBC Economy
- Federal Reserve press releases

**Crypto-specific:**
- CoinDesk
- Decrypt
- Bitcoin Magazine

**Geopolitical:**
- BBC News Top Stories

> **Dropped:** Reuters and Bloomberg public RSS feeds are behind authentication as of 2024. The collector validates all feed URLs on startup and logs a warning for any unreachable feed.

### RSS Configuration

See the `config.yaml` additions in Section 6 for the full feed list. Feeds are hot-configurable — add/remove URLs without code changes.

### Processing Pipeline

1. Poll all sources (APIs + RSS) on the configured interval
2. **Deduplicate** (two-pass):
   - **Pass 1 — URL exact match:** If article URL already exists in `news_events`, skip. Cheap O(1) lookup via unique constraint.
   - **Pass 2 — Headline fuzzy match:** Compare against headlines from the last 6 hours using `rapidfuzz.fuzz.ratio`. Threshold >85% = skip. Prefer the API source when both API and RSS produce the same headline (API has richer metadata).
3. Relevance filter: must mention a tracked pair or match a macro keyword
4. **LLM impact scoring** — batch up to 10 headlines per call to reduce cost:
   - **impact**: high / medium / low
   - **sentiment**: bullish / bearish / neutral
   - **affected_pairs**: specific coins or "ALL" for macro events
   - **summary**: one-sentence LLM explanation
   - **Daily budget:** max 200 LLM scoring calls/day (configurable). Once exhausted, new headlines are stored without impact/sentiment scoring and skipped for alerts.
5. Persist to Postgres (`NewsEvent` model)
6. If impact = high → broadcast `news_alert` via WebSocket + Web Push

### Database Model: `NewsEvent`

```python
class NewsEvent(Base):
    __tablename__ = "news_events"

    id: int                  # PK
    headline: str            # original headline
    source: str              # "reuters_rss", "cryptopanic", etc.
    url: str                 # link to original article (unique constraint for dedup)
    fingerprint: str         # sha256 of normalized headline, unique constraint for fuzzy dedup fallback
    category: str            # "crypto" | "macro"
    impact: str | None       # "high" | "medium" | "low" — nullable if LLM scoring skipped/failed
    sentiment: str | None    # "bullish" | "bearish" | "neutral" — nullable if LLM scoring skipped/failed
    affected_pairs: JSON     # ["BTC", "ETH"] or ["ALL"]
    llm_summary: str | None  # one-sentence explanation — nullable
    published_at: datetime   # original publish time
    alerted_at: datetime | None  # when push/WS alert was sent — prevents re-alerting on restart
    created_at: datetime     # when we ingested it

    __table_args__ = (
        UniqueConstraint("url", name="uq_news_url"),
        Index("ix_news_impact_published", "impact", published_at.desc()),
    )
```

### LLM Gate Enrichment

When the signal pipeline's LLM gate fires, query the last 30 minutes of high/medium impact `NewsEvent` rows matching the signal's pair (or "ALL"). Inject as a "Recent News Context" section in the LLM prompt.

---

## 3. WebSocket & Alert Integration

### New WebSocket Message Type

```json
{
  "type": "news_alert",
  "news": {
    "id": 123,
    "headline": "Fed holds rates steady, signals cuts in Q3",
    "source": "Reuters",
    "category": "macro",
    "impact": "high",
    "sentiment": "bullish",
    "affected_pairs": ["ALL"],
    "llm_summary": "Dovish forward guidance is risk-on for crypto",
    "published_at": "2026-03-08T14:30:00Z"
  }
}
```

Only `high` impact news gets pushed via WebSocket. Medium/low are queryable via REST.

High-impact news alerts also go through the Web Push pipeline, respecting user notification preferences.

> **Prerequisite:** `dispatch_push_for_signal` in `app/push/dispatch.py` exists but is **never called** from `run_pipeline`. Before building news push, wire signal push dispatch into `run_pipeline` (call after `persist_signal` + `broadcast`). Then add a parallel `dispatch_push_for_news` function following the same pattern. The `alerted_at` field on `NewsEvent` prevents duplicate push on app restart.

---

## 4. New REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/news` | Paginated news feed. Filters: `category`, `impact`, `sentiment`, `pair`, `limit` |
| GET | `/api/news/recent` | Last 24h of high+medium impact headlines (lightweight, for dashboard) |

---

## 5. Frontend Changes

### 5a. Navigation: Absorb Journal into Signals

Adding a 6th tab to the bottom nav makes it too crowded on mobile (5 icons + labels already fill ~375px). Instead:

- **Merge Journal into the Signals tab** as a toggle (Signals / Journal sub-views via segmented control at top)
- **Add News as the 5th tab**, replacing the Journal slot
- Bottom nav stays at 5 tabs: Home, Chart, Signals, **News**, More

The `Tab` type becomes `"home" | "chart" | "signals" | "news" | "more"`, and `SignalsView` gets an internal `activeView: "signals" | "journal"` state with a segmented control to switch.

### 5b. News Feed View (`features/news/`)

Full-screen scrollable list of all news events:
- **Filter chips** at top: All / Crypto / Macro, and High / Medium / Low impact
- **Each item shows**: headline, source tag, time ago, impact badge (red/orange/gray), sentiment badge (green/red/neutral), affected pairs, LLM summary (expandable)

### 5c. News Alert Toast

When a `news_alert` WebSocket message arrives:
- Slide-down toast/banner at top of screen
- Shows headline, impact badge, sentiment color
- Tap to expand LLM summary
- Auto-dismisses after 8 seconds, or swipe to dismiss

### 5d. Home Page News Section

New "Latest News" card below "Recent Signals":
- Shows 5 most recent high+medium impact headlines
- Each row: truncated headline, source, time ago, impact/sentiment badges
- "See all" links to the News tab

### 5e. Signal-News Correlation Badge

Signal cards that have correlated news events (high impact within ±30 min of signal creation) get a small newspaper icon badge. Tapping the badge shows the linked headline inline.

**Implementation:** Compute correlation at signal creation time (in `run_pipeline`), not at read time. Store `correlated_news_ids: list[int] | None` as a JSONB column on the `Signal` model. This avoids N+1 queries when fetching signal lists — the frontend just checks whether the field is non-empty to show the badge, and fetches the headline text from the news API only on tap.

---

## 6. Configuration

### `config.yaml` additions

Uses flat one-level nesting to match the existing `_YAML_SECTION_PREFIX` flattening in `config.py`. New prefix entries needed: `"onchain": "onchain_"` and `"news": "news_"`.

```yaml
engine:
  traditional_weight: 0.50    # flattens to engine_traditional_weight
  flow_weight: 0.25           # flattens to engine_flow_weight (NEW)
  onchain_weight: 0.25        # flattens to engine_onchain_weight (NEW)

onchain:
  poll_interval_seconds: 300        # Tier 1 interval
  tier2_poll_interval_seconds: 1800 # Tier 2 (CryptoQuant/Glassnode) — 30 min
  enabled: true

news:
  poll_interval_seconds: 150
  llm_context_window_minutes: 30
  high_impact_push_enabled: true
  llm_daily_budget: 200             # max LLM scoring calls per day
  relevance_keywords:
    - "interest rate"
    - "Fed"
    - "CPI"
    - "inflation"
    - "sanctions"
    - "war"
    - "tariff"
    - "regulation"
    - "crypto ban"
    - "SEC"
  rss_feeds:
    - url: "https://rss.app/feeds/v1.1/ap-news-business.xml"
      category: macro
    - url: "https://www.cnbc.com/id/20910258/device/rss/rss.html"
      category: macro
    - url: "https://www.coindesk.com/arc/outboundfeeds/rss/"
      category: crypto
    - url: "https://decrypt.co/feed"
      category: crypto
    - url: "https://feeds.bbci.co.uk/news/world/rss.xml"
      category: macro
    # add/remove without code changes
```

> **Note:** Reuters and Bloomberg RSS feeds are behind authentication as of 2024. Replaced with AP News, CNBC, and BBC which have reliable public feeds. The collector logs a warning on startup for any unreachable feed URL.

### More Page UI additions

- Toggle on-chain scoring on/off
- Toggle news alerts on/off
- Adjust LLM news context window (15 / 30 / 60 min)
- Scoring weights remain config.yaml-only (power-user territory)

---

## 7. Test Plan

All tests follow existing patterns: `asyncio_mode = "auto"`, pure function unit tests, `httpx.AsyncClient` with `ASGITransport` for API tests, `MagicMock`/`AsyncMock` for DB/Redis.

### Unit Tests

| File | Tests |
|------|-------|
| `tests/engine/test_onchain_scorer.py` | Score computation with various metric combinations; missing metrics return partial scores; all metrics missing returns 0 |
| `tests/engine/test_combiner.py` (extend) | 3-way `compute_preliminary_score` with all weights; auto-normalization when weights don't sum to 1.0; fallback weight redistribution when onchain unavailable |
| `tests/collector/test_news_dedup.py` | URL exact-match dedup; fuzzy headline dedup at thresholds (84% = keep, 86% = skip); API source preferred over RSS for same headline |
| `tests/collector/test_news_processing.py` | LLM batch scoring with mocked OpenRouter; daily budget enforcement (201st call skipped); headline stored without impact when LLM fails |

### Integration Tests

| File | Tests |
|------|-------|
| `tests/api/test_news_endpoints.py` | `GET /api/news` with filters (category, impact, pair); `GET /api/news/recent` returns only high+medium from last 24h; auth required |
| `tests/api/test_ws_news.py` | WebSocket receives `news_alert` messages for high-impact news; medium/low not pushed via WS |

### Existing Test Updates

| File | Change |
|------|--------|
| `tests/engine/test_combiner.py` | Update existing tests for new 3-param signature; add onchain weight tests |
| `tests/api/test_routes.py` | Verify news router is registered |

---

## 8. Graceful Degradation

| Failure | Behavior |
|---------|----------|
| All on-chain providers down | On-chain score = 0, caller redistributes weights: tech gets 60% of onchain share, flow gets 40% |
| News collector down | No news alerts, LLM gate runs without news context (same as today) |
| Single RSS feed unreachable | Skip it, log warning, retry next cycle. Startup health check logs all unreachable feeds. |
| LLM scoring fails for a headline | Store headline with `impact=NULL`/`sentiment=NULL`, don't alert |
| LLM daily budget exhausted | Store headlines without scoring, no alerts until budget resets at midnight UTC |
| CryptoPanic/GNews rate-limited | Fall back to RSS-only until quota resets |
| Tier 2 on-chain quota exhausted | Skip until next day, score with Tier 1 data only |

---

## 9. Summary of New/Modified Files

### Backend — New
- `app/collector/onchain.py` — on-chain data polling loop (Tier 1 @ 5min, Tier 2 @ 30min)
- `app/collector/news.py` — news + RSS polling loop with dedup (rapidfuzz)
- `app/engine/onchain_scorer.py` — on-chain scoring function
- `app/api/news.py` — news REST endpoints
- `app/push/news_dispatch.py` — Web Push dispatch for news alerts
- `app/db/migrations/versions/xxxx_create_news_events_table.py`
- `app/db/migrations/versions/xxxx_add_correlated_news_ids_to_signals.py`
- `tests/engine/test_onchain_scorer.py`
- `tests/collector/test_news_dedup.py`
- `tests/collector/test_news_processing.py`
- `tests/api/test_news_endpoints.py`
- `tests/api/test_ws_news.py`

### Backend — Modified
- `app/db/models.py` — add `NewsEvent` model, add `correlated_news_ids` JSONB column to `Signal`
- `app/engine/combiner.py` — 3-way weighted `compute_preliminary_score` with auto-normalization
- `app/engine/llm.py` — updated prompt template with `{news}` placeholder
- `app/prompts/signal_analysis.txt` — add "Recent News Context" section
- `app/api/routes.py` — register news router
- `app/api/ws.py` — add `broadcast_news` method to `ConnectionManager`
- `app/main.py` — wire push dispatch for signals (existing gap), start on-chain + news collector loops, compute `correlated_news_ids` at signal creation
- `app/config.py` — add `onchain`/`news` to `_YAML_SECTION_PREFIX`, add new Settings fields (`engine_flow_weight`, `engine_onchain_weight`, `onchain_*`, `news_*`)
- `tests/engine/test_combiner.py` — update for 3-param signature

### Frontend — New
- `features/news/` — components, hooks, types for News tab
- News alert toast component (shared)

### Frontend — Modified
- `Layout.tsx` — replace Journal tab with News tab (Journal moves into Signals as sub-view)
- `features/signals/` — add segmented control for Signals / Journal toggle
- `shared/lib/api.ts` — add news API methods
- WebSocket handler — add `news_alert` message type branch
- `features/signals/components/SignalCard.tsx` — news correlation badge (reads `correlated_news_ids`)
- `features/home/components/HomeView.tsx` — latest news section
- `features/more/components/MorePage.tsx` — on-chain + news toggle settings
