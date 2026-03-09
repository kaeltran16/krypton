# Pipeline Settings Sync Design

## Goal

Store pipeline settings in the database so frontend changes are reflected in the backend immediately. Single-user, hot-reload approach.

## Current State

- Frontend settings (pairs, timeframes, threshold, onchainEnabled, newsAlertsEnabled, newsContextWindow) are stored in localStorage only — backend doesn't know about them
- Backend loads these values from config.yaml/.env at startup and never changes them
- RiskSettings is the only DB-backed settings model (singleton, id=1)

## Field Mapping

The same concepts have different names across layers. This table is the canonical reference:

| DB (PipelineSettings) | Backend (Settings) | Frontend (Zustand) | Notes |
|---|---|---|---|
| `pairs` | `pairs` | `pairs` | JSONB list, validated `^[A-Z]+-USDT-SWAP$` |
| `timeframes` | `timeframes` | `timeframes` | JSONB list, validated against `VALID_TIMEFRAMES` |
| `signal_threshold` | `engine_signal_threshold` | `threshold` | int, 0–100 |
| `onchain_enabled` | `onchain_enabled` | `onchainEnabled` | bool |
| `news_alerts_enabled` | `news_high_impact_push_enabled` | `newsAlertsEnabled` | Controls both LLM news context in pipeline AND push dispatch |
| `news_context_window` | `news_llm_context_window_minutes` | `newsContextWindow` | int, minutes |

The API layer uses the DB column names. Frontend maps to/from camelCase.

## Design

### 1. Database Model — `PipelineSettings`

New singleton table (same pattern as `RiskSettings`):

```python
class PipelineSettings(Base):
    __tablename__ = "pipeline_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    pairs: Mapped[list] = mapped_column(JSONB, default=["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    timeframes: Mapped[list] = mapped_column(JSONB, default=["15m", "1h", "4h"])
    signal_threshold: Mapped[int] = mapped_column(Integer, default=50)
    onchain_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    news_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    news_context_window: Mapped[int] = mapped_column(Integer, default=30)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_pipeline_settings_singleton"),
    )
```

Alembic migration seeds one row from current config.yaml defaults.

### 2. Backend API — `api/pipeline_settings.py`

New router mounted at `/api/pipeline`:

- **GET `/api/pipeline/settings`** — returns current PipelineSettings from DB
- **PUT `/api/pipeline/settings`** — partial update (same pattern as risk settings PUT)

#### Pydantic validation on PUT body

```python
VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
PAIR_PATTERN = re.compile(r"^[A-Z]+-USDT-SWAP$")

class PipelineSettingsUpdate(BaseModel):
    pairs: list[str] | None = None
    timeframes: list[str] | None = None
    signal_threshold: int | None = Field(None, ge=0, le=100)
    onchain_enabled: bool | None = None
    news_alerts_enabled: bool | None = None
    news_context_window: int | None = Field(None, ge=1, le=1440)

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v):
        if v is not None:
            if len(v) == 0:
                raise ValueError("pairs must not be empty")
            for p in v:
                if not PAIR_PATTERN.match(p):
                    raise ValueError(f"Invalid pair format: {p}")
        return v

    @field_validator("timeframes")
    @classmethod
    def validate_timeframes(cls, v):
        if v is not None:
            if len(v) == 0:
                raise ValueError("timeframes must not be empty")
            for tf in v:
                if tf not in VALID_TIMEFRAMES:
                    raise ValueError(f"Invalid timeframe: {tf}")
        return v
```

#### PUT handler logic

On PUT:
1. Validate input via Pydantic model above
2. Update DB row
3. Patch `app.state.settings` in-memory using `object.__setattr__()` (Pydantic BaseSettings is frozen by default — this is the same pattern used in `config.py` `model_post_init` for YAML overlay)
4. Map DB field names to Settings field names: `signal_threshold` → `engine_signal_threshold`, `news_alerts_enabled` → `news_high_impact_push_enabled`, `news_context_window` → `news_llm_context_window_minutes`
5. If pairs or timeframes changed → restart all collectors (see Section 3)
6. Return updated settings

#### Concurrency guard

Use an `asyncio.Lock` on `app.state` to serialize PUT requests that trigger collector restarts. This prevents concurrent re-subscription race conditions:

```python
# In lifespan:
app.state.pipeline_settings_lock = asyncio.Lock()

# In PUT handler:
async with request.app.state.pipeline_settings_lock:
    # ... update DB, patch settings, restart collectors
```

### 3. Hot Reload Mechanism

The pipeline already reads from `app.state.settings` on each cycle. By patching these in-memory on PUT via `object.__setattr__(settings, field, value)`:

- **signal_threshold** → `engine_signal_threshold` — next `run_pipeline()` uses new value immediately
- **onchain_enabled** — pipeline already has adaptive weight redistribution; if disabled, weight redistributes to other sources
- **news_alerts_enabled** → `news_high_impact_push_enabled` — pipeline checks this before push dispatch; also used to gate news context inclusion in LLM prompt
- **news_context_window** → `news_llm_context_window_minutes` — pipeline checks this before LLM/news processing

#### Collector restart on pairs/timeframes change

When pairs or timeframes change, **all four collectors** that hold pair/timeframe lists must be updated:

1. **OKXWebSocketClient** — stop and recreate with new pairs/timeframes (simplest approach; brief reconnection gap is acceptable for single-user)
2. **OKXRestPoller** — update `self.pairs` in-place (simple attribute, used in polling loop)
3. **OnChainCollector** — update `self.pairs` in-place
4. **NewsCollector** — update `self.pairs` in-place

To enable this, store all collector references on `app.state` during lifespan:

```python
app.state.ws_client = ws_client
app.state.rest_poller = rest_poller
app.state.onchain_collector = onchain_collector  # if enabled
app.state.news_collector = news_collector
```

For the WebSocket client, add a restart helper:

```python
async def restart_ws_client(app, new_pairs, new_timeframes):
    old_client = app.state.ws_client
    await old_client.stop()
    app.state.ws_task.cancel()

    new_client = OKXWebSocketClient(
        pairs=new_pairs,
        timeframes=new_timeframes,
        on_candle=lambda c: handle_candle_tick(app, c),
        on_funding_rate=lambda d: handle_funding_rate(app, d),
        on_open_interest=lambda d: handle_open_interest(app, d),
    )
    app.state.ws_client = new_client
    app.state.ws_task = asyncio.create_task(new_client.connect())
```

For REST/onchain/news collectors, just patch `self.pairs` — their polling loops will pick up the new list on the next iteration. No restart needed.

Also trigger `backfill_candles()` for any newly added pairs/timeframes so Redis has historical data ready for pipeline scoring.

### 4. Frontend Changes

**On app load:**
- Fetch GET /api/pipeline/settings
- Hydrate Zustand store with server values (server = source of truth)

**On setting change:**
- Update Zustand store immediately (optimistic UI)
- Debounced PUT /api/pipeline/settings (~500ms)
- On error: revert Zustand store to pre-change values and show error toast

Debounce implementation — custom hook using `useRef` + `setTimeout` (no new dependency):

```typescript
function useDebouncedSync(delayMs = 500) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const lastServerState = useRef<Partial<PipelineSettings>>({});

  const sync = useCallback((patch: Partial<PipelineSettings>) => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      try {
        await api.updatePipelineSettings(patch);
        lastServerState.current = { ...lastServerState.current, ...patch };
      } catch {
        // Revert to last known server state
        useSettingsStore.setState(lastServerState.current);
        // Show error toast
      }
    }, delayMs);
  }, [delayMs]);

  return sync;
}
```

**localStorage scope change:**
- Remove persistence for synced fields (pairs, timeframes, threshold, onchainEnabled, newsAlertsEnabled, newsContextWindow)
- Keep localStorage for client-only fields: `apiBaseUrl`, `notificationsEnabled`

### 5. What Stays in config.yaml/.env

Backend-only settings that users shouldn't touch:
- Database/Redis URLs, API keys, VAPID keys
- LLM timeout, scoring weights
- Collector polling intervals
- These config.yaml values become the initial seed for the DB row

### 6. Migration Path

1. Alembic migration creates `pipeline_settings` table
2. Seeds single row with defaults matching current config.yaml
3. Backend startup: load PipelineSettings from DB, patch onto `app.state.settings` using `object.__setattr__()` with the field name mapping. If no row exists (migration hasn't run), log a warning and continue with config.yaml defaults — don't crash
4. Frontend: on first load after deploy, fetches from API instead of localStorage

## Data Flow

```
User toggles setting in UI
  → Zustand store updates (instant UI feedback)
  → Debounced PUT /api/pipeline/settings
    → Pydantic validates input (pairs format, timeframe values, threshold range)
    → Acquire asyncio.Lock
    → DB update (PipelineSettings row)
    → app.state.settings patched via object.__setattr__() with field name mapping
    → If pairs/timeframes changed:
        → Restart OKX WebSocket client (stop old, create new)
        → Patch rest_poller.pairs, onchain_collector.pairs, news_collector.pairs
        → Backfill candles for newly added pairs/timeframes
    → Release lock
    → Return updated settings
    → On success: Zustand state already correct
    → On error: Zustand reverts to last server state, show error toast

App launch:
  → GET /api/pipeline/settings
  → Zustand store hydrated from server
  → localStorage only for apiBaseUrl, notificationsEnabled
  → If GET fails: use DEFAULT_SETTINGS as fallback, log warning
```

## Files to Create/Modify

### Backend
- **Modify:** `app/db/models.py` — add `PipelineSettings` model
- **Create:** `app/api/pipeline_settings.py` — new router with GET/PUT, validation, field mapping, lock, collector restart
- **Modify:** `app/main.py` — register router, store collector refs on `app.state`, load PipelineSettings on startup with graceful fallback, add `pipeline_settings_lock`
- **Modify:** `app/main.py` — pipeline reads threshold/toggles from patched settings (already does via `app.state.settings`)
- **Create:** Alembic migration for `pipeline_settings` table with seed row

### Frontend
- **Modify:** `src/features/settings/store.ts` — fetch from API on init, debounced PUT on change with revert-on-error
- **Modify:** `src/features/settings/types.ts` — add `PipelineSettings` API type for GET/PUT responses
- **Modify:** `src/shared/lib/api.ts` — add `getPipelineSettings` / `updatePipelineSettings` methods
- **Modify:** `src/features/more/components/MorePage.tsx` — loading state while fetching initial settings, error toast on save failure

### Tests
- **Create:** `tests/api/test_pipeline_settings.py` — GET returns seeded defaults, PUT partial update works, PUT with invalid pairs/timeframes returns 422, PUT patches app.state.settings correctly, field name mapping is correct
- **Modify:** existing test fixtures if needed to seed PipelineSettings row
