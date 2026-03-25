# Data Ingestion Hardening & New Signal Sources

## Problem Statement

The data ingestion layer has several reliability bugs that cause silent signal degradation, gaps between what scorers expect and what collectors provide, and missing data sources that would add genuinely orthogonal signal to the engine.

## Scope

Four categories of work, ordered by impact:

1. **Bug fixes** — things actively hurting signal quality now
2. **Reliability** — preventing silent degradation
3. **New data sources** — CVD and order book depth (the only two that add genuinely new signal axes)
4. **Gap fills** — wiring missing on-chain metrics the scorer already expects

## Out of Scope

- Fear & Greed Index, cross-exchange funding, options data, stablecoin supply, social sentiment, DeFi TVL, CME basis (all too slow for 15m-4H timeframes or too correlated with existing sources)
- Refactoring the combiner or regime system
- Changes to the frontend

---

## 1. Bug Fixes

### 1.1 WebSocket Missing Ping Interval

**File:** `backend/app/collector/ws_client.py`

**Problem:** `OKXWebSocketClient._run_loop` calls `websockets.connect(url)` without `ping_interval`. The ticker collector (`ticker.py:54`) sets `ping_interval=20`, but the main candle/funding/OI WebSocket does not. Without explicit pings, OKX can drop the connection after ~5 min of inactivity and the client won't detect it — candles stop flowing silently.

**Fix:** Add `ping_interval=20` to the `websockets.connect()` call in `_run_loop` (line 153).

### 1.2 Order Flow Not Preloaded on Startup

**File:** `backend/app/main.py` (lifespan function, ~line 1191)

**Problem:** `app.state.order_flow` is initialized as `{}` on every boot. The order flow scorer (`traditional.py:403`) needs 10 `OrderFlowSnapshot` rows (3 recent + 7 baseline) for rate-of-change detection. After restart, the first 10 signals have no RoC detection — contrarian adjustments are disabled.

**Fix:** After initializing `app.state.order_flow = {}`, query the last `OrderFlowSnapshot` per pair to seed the dict with latest funding_rate, open_interest, long_short_ratio values. The flow_history itself comes from DB queries at pipeline time (already works), but the current in-memory state needs seeding so the first candle's snapshot isn't empty.

### 1.3 OI Baseline Self-Comparison on Startup

**File:** `backend/app/main.py` (handle_open_interest, ~line 1023)

**Problem:** First OI update after restart uses `flow.get("open_interest", data["open_interest"])` which falls back to the current value, recording 0% change. This persists a misleading 0% OI change in the first `OrderFlowSnapshot`.

**Fix:** When preloading order flow (1.2), include the last known `open_interest` value. This makes the first OI delta meaningful.

### 1.4 Order Flow Snapshot Persistence Silent Failure

**File:** `backend/app/main.py` (run_pipeline, ~line 425-438)

**Problem:** DB write failures for `OrderFlowSnapshot` are caught and logged at `logger.debug()` — invisible in production. Lost snapshots create gaps in ML training data and flow_history.

**Fix:** Change to `logger.warning()`.

### 1.5 Wire `addr_trend_pct` From Existing History

**Files:** `backend/app/collector/onchain.py`, `backend/app/engine/onchain_scorer.py`

**Problem:** The collector stores raw `active_addresses` count in Redis and appends to a rolling 24h history list via `_append_history()` (`onchain.py:231`). The scorer expects `addr_trend_pct` but nothing computes the percentage trend from the stored history.

**Fix:** In the on-chain collector (or a helper called by the scorer), read the `onchain_hist:BTC-USDT-SWAP:active_addresses` Redis list, compute `(latest - oldest) / oldest` as a percentage, and store as `onchain:{pair}:addr_trend_pct` in Redis. This gives BTC 4/5 on-chain metrics instead of 3/5.

---

## 2. Reliability

### 2.1 Data Freshness Watchdog

**New file:** `backend/app/collector/watchdog.py`

**Problem:** No centralized monitoring for data staleness. If the candle WebSocket drops, the L/S poller fails, or on-chain keys expire from Redis, the system silently stops scoring well (or at all). The `/api/system/health` endpoint only reports pipeline cycle timestamp, not per-metric freshness.

**Fix:** Extract freshness computation into a shared module `backend/app/collector/freshness.py` with a `compute_freshness(app) -> dict` function. This function checks:
- Last candle timestamp per pair/timeframe (from Redis `candles:{pair}:{tf}` — decode last entry's timestamp)
- Last order flow update per pair (requires adding a `_last_updated` timestamp to `app.state.order_flow[pair]`)
- On-chain Redis key existence (`EXISTS onchain:{pair}:{metric}`)
- Last successful liquidation poll (add `_last_poll_ts` to `LiquidationCollector`)

The watchdog (`watchdog.py`) is a background coroutine (30s interval) that calls `compute_freshness()` and logs `WARNING` when any source exceeds its expected freshness threshold:
- Candles: 2x the timeframe interval (e.g., 30m for 15m candles)
- Order flow: 10 minutes
- On-chain: 15 minutes (1.5x the 10-min TTL)
- Liquidation: 10 minutes (2x the 5-min poll interval)

The existing `/api/system/health` endpoint also calls `compute_freshness()` to expose the same data for frontend consumption, replacing its current ad-hoc freshness calculations. Single source of truth for freshness logic.

### 2.2 Persist Liquidation Events to Redis

**File:** `backend/app/collector/liquidation.py`

**Problem:** Liquidation events are in-memory only (`self._events` dict). Restarting the server wipes the entire 24h window. The liquidation scorer has no data until events accumulate again over hours.

**Fix:** On each poll, `RPUSH` new events to `liq_events:{pair}` Redis list with 24h expiry. On startup, reload from Redis into `self._events`. Prune old events from both memory and Redis list.

Event format in Redis: JSON `{"price": float, "volume": float, "timestamp": iso_string, "side": string}`.

---

## 3. New Data Sources

### 3.1 CVD (Cumulative Volume Delta) from OKX Trades Channel

**Files:**
- Modify: `backend/app/collector/ws_client.py` (add trades channel subscription + parser)
- Modify: `backend/app/main.py` (add `handle_trade` callback, aggregate CVD in `app.state`)
- Modify: `backend/app/engine/traditional.py` (`compute_order_flow_score` — add CVD component)
- Modify: `backend/app/engine/constants.py` (add CVD constants, rebalance ORDER_FLOW max_scores)
- Modify: `backend/app/db/models.py` (add `cvd_delta` column to `OrderFlowSnapshot`)
- New migration: add `cvd_delta` column

**What CVD measures:** The running sum of buy-aggressor volume minus sell-aggressor volume from the OKX `trades` channel. Each trade message contains `[price, size, side, timestamp]` where side indicates the aggressor. This directly measures who is crossing the spread — information no current source captures.

**Collection design:**
- Subscribe to `trades` channel per pair on the public WebSocket (same connection as funding/OI)
- Parse trade messages: extract `size` and `side` ("buy" or "sell")
- Aggregate in `app.state.cvd[pair]` as a rolling structure:
  - `cumulative`: running CVD value (buy_vol - sell_vol)
  - `candle_delta`: CVD delta since last confirmed candle (reset on each candle)
  - `_last_updated`: timestamp for watchdog
- On confirmed candle: snapshot `candle_delta` into `OrderFlowSnapshot.cvd_delta`, reset accumulator
- Trades are high-frequency — aggregate in-memory only, snapshot per candle. No per-tick persistence.

**Scoring integration:**
- New component in `compute_order_flow_score`: CVD delta (max +/-20), directional (not contrarian)
- Rebalance ORDER_FLOW max_scores: `{"funding": 30, "oi": 20, "ls_ratio": 30, "cvd": 20}` (total = 100). **Note:** Current max_scores sum to 90 (35+20+35). This rebalance increases the order flow source's effective ceiling by ~11%. Shadow-test the rebalanced scores against recent signal history before promoting to live to verify regime weight stability is unaffected.
- CVD is directional like OI: `cvd_score = sigmoid_score(cvd_delta_normalized, center=0, steepness=X) * 20`
- NOT affected by contrarian_mult or trend_conviction (it measures actual behavior, not positioning)
- Normalization: `cvd_delta / average_volume_per_candle` to make the sigmoid input scale-independent

**Confidence update:** Use a dynamic denominator. Legacy 3 sources (funding, OI, L/S) are always counted as available. CVD is only counted when data is flowing. This prevents confidence inflation when sparse data arrives (e.g., only funding_rate present → 1/3 not 1/1):
```python
sources_available = 3 + (1 if cvd_delta is not None else 0)
flow_confidence = round(inputs_present / max(sources_available, 1), 4)
```
This replaces the current `inputs_present / 3.0`. When all 4 sources flow, denominator = 4. When CVD is down, denominator = 3 — no regression from today's behavior. When only 1 legacy source has data, confidence = 1/3 (not inflated to 1/1).

**Key signal:** CVD-price divergence. Price rising + CVD falling = buyer exhaustion. Price falling + CVD rising = seller exhaustion. The scorer doesn't need to detect divergence explicitly — the directional scoring naturally captures it because CVD will score opposite to the price trend when divergence occurs.

### 3.2 Order Book Depth from OKX Books5 Channel

**Files:**
- Modify: `backend/app/collector/ws_client.py` (add books5 subscription + parser)
- Modify: `backend/app/main.py` (add `handle_depth` callback, store in `app.state.order_book`)
- Modify: `backend/app/engine/liquidation_scorer.py` (add depth modifier to cluster scoring)
- Modify: `backend/app/engine/structure.py` (`collect_structure_levels` — modulate strength with depth)

**What it measures:** Top 5 bid and ask levels with sizes from OKX `books5` channel. Provides bid/ask volume imbalance near the current price.

**Collection design:**
- Subscribe to `books5` channel per pair on the public WebSocket
- Parse into `app.state.order_book[pair]`: `{"bids": [(price, size), ...], "asks": [(price, size), ...], "_last_updated": ts}`
- Purely real-time state — no persistence needed. Updates frequently (100ms+ from OKX).
- Compute aggregate metrics on read:
  - `bid_volume`: sum of top 5 bid sizes
  - `ask_volume`: sum of top 5 ask sizes
  - `imbalance_ratio`: `bid_volume / ask_volume` (>1 = bid-heavy, <1 = ask-heavy)

**NOT a new scoring source in the combiner.** Depth is a modifier, not a directional opinion. Bid-ask imbalance flips second-to-second; treating it as a standalone source would add noise.

**Integration point 1 — Liquidation scorer (`liquidation_scorer.py:64`):**

In `compute_liquidation_score`, for each cluster within 2 ATR of price, modulate the contribution by depth context:
- Cluster ABOVE price (bullish squeeze potential): check ask-side depth near cluster. Thin asks = amplify (1.3x). Thick asks = dampen (0.7x).
- Cluster BELOW price (bearish cascade potential): check bid-side depth near cluster. Thin bids = amplify (1.3x). Thick bids = dampen (0.7x).

The depth modifier is bounded to [0.7, 1.3] to prevent depth from overwhelming the liquidation signal.

How to determine "near cluster": check if any of the top 5 bid/ask levels fall within 0.5 ATR of the cluster center. If none do, depth_modifier = 1.0 (neutral — the book doesn't reach that far).

**Integration point 2 — Structure level strength (`structure.py:89`):**

In `collect_structure_levels`, after building the levels list, modulate each level's `strength` by depth:
- For support levels (below price): if heavy bids rest near the level, multiply strength by up to 1.5x
- For resistance levels (above price): if heavy asks rest near the level, multiply strength by up to 1.5x
- "Heavy" = bid/ask volume at that level exceeds 2x the average level volume across all top-5 entries

This makes `snap_levels_to_structure` naturally prefer levels where actual liquidity is resting, without changing the snapping logic itself.

Pass depth data through `compute_liquidation_score(events, price, atr, depth=None)` and `collect_structure_levels(candles, indicators, atr, liquidation_clusters=None, depth=None)` as optional parameters. When `depth=None`, behavior is unchanged (modifier = 1.0).

**Pipeline threading:** In `run_pipeline` (~line 400), extract depth from app state and pass to both scorers:
```python
order_book = getattr(app.state, "order_book", {})
depth = order_book.get(pair)
```
Then pass `depth=depth` to `compute_liquidation_score()` (~line 475) and `collect_structure_levels()` (~line 833).

---

## 4. Gap Fills (Deferred)

Sections 4.1 and 4.2 are **deferred to a separate PR**. Rationale: all three metrics (BTC hashrate, ETH gas, ETH staking) move on weekly/daily timescales with ambiguous directional interpretation on 15m-4H timeframes. The on-chain scorer already handles missing metrics gracefully (confidence scales down proportionally). The effort of adding 3 new external API integrations (with failure modes, rate limits, and API key management) is not justified by the marginal signal improvement.

For reference, the deferred work:

### 4.1 Add `hashrate_change_pct` Collection for BTC

**File:** `backend/app/collector/onchain.py`

The on-chain scorer expects `hashrate_change_pct` for BTC (+/-15 pts) but no collector code fetches it. Fix: In `_poll_tier1`, fetch BTC hashrate from `blockchain.info/q/hashrate` (free, no key). Hashrate moves on weekly timescales — minimal impact.

### 4.2 Add ETH Gas Price and Staking Data

**Files:** `backend/app/collector/onchain.py`, `backend/app/config.py`

The on-chain scorer defines `gas_trend_pct` and `staking_flow` for ETH but no collector provides them. Fix:
- **Gas price:** Etherscan API (`/api?module=gastracker&action=gasoracle`). Config field: `etherscan_api_key: str = ""` in `Settings`.
- **Staking flow:** Beaconcha.in API (`/api/v1/epoch/latest`). Config field: `beaconchain_api_key: str = ""` in `Settings`.

Both Tier 2 (30-min poll). Both metrics move slowly — marginal impact.

---

## Technical Constraints

- All new WebSocket subscriptions go on the existing public WS connection in `ws_client.py` (no new connections)
- All new in-memory state goes on `app.state` (consistent with existing pattern)
- All new Redis keys follow existing naming: `{category}:{pair}:{metric}`
- DB migrations via Alembic (one migration for `OrderFlowSnapshot.cvd_delta` column)
- Tests use existing `conftest.py` fixtures with stubbed app.state (no real DB/Redis/OKX). See section 5 for full test plan.
- New config values added to `PipelineSettings` where runtime-tunable, or `config.py` for static settings

## Dependencies

- No new Python packages required
- OKX `trades` and `books5` channels are on the same public WebSocket already connected
- Blockchain.info, Etherscan, and Beaconcha.in dependencies deferred (section 4)

---

## 5. Tests

All tests use existing `conftest.py` fixtures with stubbed `app.state` (no real DB/Redis/OKX). Redis is mocked via `AsyncMock()` with `side_effect` for key lookups. Follow existing patterns in `tests/engine/` and `tests/collector/`.

### 5.1 Bug Fix Tests

**File:** `tests/collector/test_ws_client.py` (extend)
- Verify `_run_loop` passes `ping_interval=20` to `websockets.connect()` (mock `websockets.connect` and assert kwargs)

**File:** `tests/test_pipeline.py` (extend)
- Test order flow preloading: seed `OrderFlowSnapshot` rows in mock DB, verify `app.state.order_flow[pair]` contains funding_rate/OI/L-S after lifespan init
- Test first OI update after preload uses the seeded value (not self-comparison to 0%)
- Test `OrderFlowSnapshot` write failure logs at `WARNING` level (not `DEBUG`)

**File:** `tests/engine/test_onchain_scorer.py` (extend)
- Test `addr_trend_pct` computation from Redis history list: given `onchain_hist:BTC-USDT-SWAP:active_addresses` with known values, verify `(latest - oldest) / oldest` result

### 5.2 Watchdog & Freshness Tests

**New file:** `tests/collector/test_freshness.py`
- Test `compute_freshness()` returns correct staleness for each source type
- Test candle staleness: mock Redis `candles:{pair}:{tf}` with old timestamp, verify `stale=True` when > 2x timeframe
- Test order flow staleness: mock `app.state.order_flow[pair]["_last_updated"]` older than 10 min
- Test on-chain staleness: mock Redis `EXISTS` returning 0 for expected keys
- Test liquidation staleness: mock `_last_poll_ts` older than 10 min
- Test all-fresh scenario returns no warnings

**New file:** `tests/collector/test_watchdog.py`
- Test watchdog logs WARNING when `compute_freshness()` reports stale sources (capture log output)
- Test watchdog does not log when all sources fresh

### 5.3 Liquidation Redis Persistence Tests

**File:** `tests/collector/test_liquidation_collector.py` (extend)
- Test `RPUSH` called on each poll with correct key format `liq_events:{pair}` and JSON payload
- Test `EXPIRE` set to 86400 on each write
- Test startup reload: mock `LRANGE liq_events:{pair}` returning JSON events, verify `self._events` populated
- Test prune: events older than 24h removed from both `self._events` and Redis list
- Test restart recovery: write events, simulate restart (new collector instance), verify events restored from Redis

### 5.4 CVD Tests

**New file:** `tests/collector/test_cvd.py`
- Test trade message parsing: given OKX trade message `{"arg": {...}, "data": [[price, size, "buy", ts]]}`, verify buy volume added to cumulative
- Test sell trade subtracts from cumulative
- Test `candle_delta` resets on confirmed candle callback
- Test `_last_updated` timestamp set on each trade
- Test multiple trades within one candle accumulate correctly

**File:** `tests/engine/test_traditional.py` (extend)
- Test CVD component in `compute_order_flow_score`: positive CVD delta yields positive score (max +20)
- Test CVD scoring is directional (NOT affected by `contrarian_mult`)
- Test CVD normalization: `cvd_delta / avg_volume` fed to sigmoid
- Test CVD absent (None/0): score = 0, no effect on other components
- Test max_scores rebalancing: verify funding=30, oi=20, ls_ratio=30, cvd=20 produce expected bounds
- Test dynamic confidence denominator: 3 sources present + CVD unavailable yields confidence 3/3=1.0 (no regression)
- Test all 4 sources present yields confidence 4/4=1.0

### 5.5 Order Book Depth Tests

**New file:** `tests/collector/test_depth.py`
- Test books5 message parsing into `app.state.order_book[pair]` structure
- Test `bid_volume` / `ask_volume` aggregation from top 5 levels
- Test `imbalance_ratio` computation: bid-heavy (>1), ask-heavy (<1), balanced (~1)
- Test `_last_updated` timestamp set on each update

**File:** `tests/engine/test_liquidation_scorer.py` (extend)
- Test `depth=None` produces unchanged behavior (modifier = 1.0)
- Test cluster ABOVE price with thin asks: modifier = 1.3x
- Test cluster ABOVE price with thick asks: modifier = 0.7x
- Test cluster BELOW price with thin bids: modifier = 1.3x
- Test cluster BELOW price with thick bids: modifier = 0.7x
- Test depth levels don't reach cluster: modifier = 1.0 (neutral)
- Test modifier bounded to [0.7, 1.3]

**File:** `tests/engine/test_structure.py` (extend)
- Test `depth=None` produces unchanged level strengths
- Test support level with heavy bids nearby: strength up to 1.5x
- Test resistance level with heavy asks nearby: strength up to 1.5x
- Test "heavy" threshold: volume > 2x average of all top-5 entries
- Test depth data with no levels near structure: strength unchanged

### 5.6 Integration / Shadow Tests

**File:** `tests/engine/test_traditional.py` (extend)
- Test full `compute_order_flow_score` with all 4 sources at extreme values: verify total clamped to ±100
- Test with only legacy 3 sources: verify scores match pre-CVD behavior (regression guard)

After deployment, run shadow comparison: replay recent signals through old (90-max) and new (100-max) scoring, compare regime weight distributions. This is a manual validation step, not an automated test.
