# Risk & Execution Improvements Design

Implements Section 3 from `krypton_improvements.md`: Fractional Kelly Position Sizing (3.1) and Partial Exit + ATR Trailing Stop (3.2).

---

## 3.1 Fractional Kelly Position Sizing

### Problem

Fixed 1% `risk_per_trade` ignores signal quality and recent performance. A strong signal after a winning streak should size larger than a borderline signal during a drawdown.

### Design

New pure function `compute_kelly_risk()` in `engine/risk.py`. Computes an adaptive `risk_per_trade` from recent resolved signal outcomes.

**Inputs:**
- `recent_outcomes: list[dict]` — resolved signals with `outcome` and `outcome_pnl_pct`
- `kelly_fraction: float = 0.35` — fractional Kelly multiplier (conservative)
- `min_signals: int = 50` — minimum resolved signals required
- `default_risk: float = 0.01` — fallback when insufficient history
- `floor: float = 0.005` — minimum risk (0.5%)
- `ceiling: float = 0.02` — maximum risk (2%)

**Logic:**
1. Filter to terminal outcomes: `TP1_HIT`, `TP2_HIT`, `SL_HIT`, `TP1_TRAIL`, `TP1_TP2`
2. If fewer than `min_signals` → return `default_risk` with `source: "default"`
3. Compute:
   - `win_rate` = wins / total (wins = all non-SL outcomes)
   - `avg_win` = mean of positive `outcome_pnl_pct`
   - `avg_loss` = mean of abs(negative `outcome_pnl_pct`)
   - Edge cases:
     - If `avg_loss == 0` (all wins): return `ceiling` with `source: "kelly"`
     - If `avg_win == 0` (all losses): return `floor` with `source: "kelly"`
     - If both are 0 (all breakeven): return `default_risk` with `source: "default"`
   - `odds` = `avg_win / avg_loss`
4. Kelly formula: `win_rate - (1 - win_rate) / odds`
5. Apply fractional multiplier: `kelly * kelly_fraction`
6. Clamp to `[floor, ceiling]`

**Returns:**
```python
{
    "risk_per_trade": float,  # clamped fractional Kelly value
    "kelly_raw": float,       # raw Kelly fraction before clamping
    "win_rate": float,
    "odds": float,
    "sample_size": int,
    "source": "kelly" | "default",
}
```

### Pipeline Integration

In `main.py`, before creating `PositionSizer`:
1. Query last 50+ resolved signals for the pair+timeframe (scoped to the specific `(pair, timeframe)` tuple)
2. Call `compute_kelly_risk(outcomes)`
3. Use returned `risk_per_trade` instead of the fixed `RiskSettings.risk_per_trade`
4. Store Kelly metadata in `risk_metrics` JSONB under a `"kelly"` key

Note: `min_signals=50` applies per `(pair, timeframe)`. New pairs will use `default_risk` until they accumulate enough history — this is the intended conservative behavior.

### Safety

All existing hard caps remain unchanged:
- `PositionSizer`: 25% equity cap, `max_position_size_usd`
- `RiskGuard`: daily loss limit, max concurrent positions, max exposure, cooldown

Kelly only adjusts the input `risk_per_trade` within `[0.5%, 2%]`. The system cannot over-leverage even if Kelly returns an extreme value.

---

## 3.2 Partial Exit + ATR Trailing Stop

### Problem

Outcome resolution is binary: full position exits at TP1, TP2, or SL. Exiting 100% at TP1 leaves gains on the table when trends continue. Holding 100% for TP2 risks full retracement.

### Design

Extend `resolve_signal_outcome()` in `engine/outcome_resolver.py` with a two-pass approach when ATR is provided.

**Updated signature:**
```python
def resolve_signal_outcome(
    signal: dict,
    candles: list[dict],
    atr: float | None = None,
    partial_fraction: float = 0.50,
) -> dict | None:
```

When `atr is None`, behavior is identical to today (full backward compatibility).

**Pass 1 — Find first level hit:**
- SL hit → return `SL_HIT` with full-position PnL (unchanged)
- TP2 hit before TP1 → return `TP2_HIT` with full-position PnL (price blew past TP1)
- TP1 hit → record partial exit, enter Pass 2

**Pass 2 — Trailing stop on remaining position:**

Pass 2 begins evaluation on the **candle after** the TP1 hit candle. The TP1-triggering candle is consumed by Pass 1 — this avoids intra-candle ambiguity where a wide candle could trigger both TP1 and the trail stop simultaneously.

- Initialize trailing stop:
  - LONG: `trail = tp1_price - 1.0 * atr`
  - SHORT: `trail = tp1_price + 1.0 * atr`
- For each candle after TP1 hit:
  - Update trail (ratchet only):
    - LONG: `trail = max(trail, candle_high - 1.0 * atr)`
    - SHORT: `trail = min(trail, candle_low + 1.0 * atr)`
  - Check TP2: if hit → outcome `TP1_TP2`, remainder closes at TP2 price
  - Check trail: if hit (LONG: `candle_low <= trail`, SHORT: `candle_high >= trail`) → outcome `TP1_TRAIL`, remainder closes at trail price
- If neither triggered by end of candles → return `None` (still PENDING)

**24h expiry interaction:** The 24h expiry timer runs from signal creation. If TP1 hit at hour 20 and the remainder is still trailing at hour 24, close the remainder at the last candle's close price. Outcome = `TP1_TRAIL`, blended PnL uses the market-close price for the remainder leg. This prevents zombie partial positions from lingering indefinitely.

The trail distance is fixed at `1.0 * ATR` for v1. Not configurable — avoids parameter sprawl before we have data on what works. Evaluate the multiplier after 50+ resolved `TP1_TRAIL` outcomes by comparing blended PnL against hypothetical 0.75× and 1.5× alternatives.

**Blended PnL:**
```
outcome_pnl_pct = partial_fraction * tp1_pnl + (1 - partial_fraction) * remainder_pnl
```

### New Outcome Types

| Outcome | Meaning |
|---------|---------|
| `SL_HIT` | Stop loss hit, full position (unchanged) |
| `TP1_HIT` | TP1 hit, full position exits (when atr=None, legacy) |
| `TP2_HIT` | TP2 hit, full position (price blew past TP1, or legacy) |
| `TP1_TRAIL` | TP1 hit (50% closed), trail stop hit on remainder |
| `TP1_TP2` | TP1 hit (50% closed), TP2 hit on remainder |

### Return Dict

Standard fields preserved for backward compatibility:
```python
{
    "outcome": "TP1_TRAIL",
    "outcome_pnl_pct": 1.85,                # blended
    "outcome_duration_minutes": 240,         # signal creation → final exit (trail/TP2)
    "outcome_at": <datetime>,                # final exit timestamp (trail/TP2 hit)
    # partial exit details (new fields, stored in risk_metrics JSONB)
    "partial_exit_pnl_pct": 1.20,
    "partial_exit_at": <datetime>,           # TP1 hit timestamp
    "trail_exit_pnl_pct": 2.50,
    "trail_exit_price": 68420.0,
}
```

For `TP1_TP2`:
```python
{
    "outcome": "TP1_TP2",
    "outcome_pnl_pct": 2.40,                # blended
    "partial_exit_pnl_pct": 1.20,
    "trail_exit_pnl_pct": 3.60,             # actually TP2 exit
    "trail_exit_price": <tp2_price>,
}
```

### ATR Sourcing

| Call site | ATR source |
|-----------|-----------|
| `check_pending_signals` (main.py) | Compute ATR(14) from the Redis candle cache already being loaded |
| `performance_tracker.replay_signal` | Already accepts `atr` parameter; update to pass it through to `resolve_signal_outcome` (currently not forwarded) |

### Signal Model

No migration needed:
- `outcome` column (`String(16)`): new values `TP1_TRAIL`, `TP1_TP2` fit
- `outcome_pnl_pct`: stores blended value
- `risk_metrics` (JSONB): stores partial exit breakdown (`partial_exit_pnl_pct`, `trail_exit_pnl_pct`, `trail_exit_price`)

### Downstream Impact

**Performance tracker:** `replay_signal` passes `atr` through → GP optimization learns from realistic partial-exit outcomes → Sortino surface reflects actual exit behavior.

**ML training data:** `TP1_TRAIL` and `TP1_TP2` are wins. Any code that maps resolved signal outcomes to win/loss categories (e.g., win rate calculations in `api/routes.py`, `api/risk.py`) must include these alongside `TP1_HIT` and `TP2_HIT`. Note: `ml/labels.py` generates training labels from future candle data and does not reference outcome types — no changes needed there.

**Optimizer (`optimizer.py`):** `record_resolution` receives `outcome_pnl_pct` — blended value works without changes.

**Frontend signals list:** New outcome badge colors for `TP1_TRAIL` and `TP1_TP2`. Update `OUTCOME_COLOR` and `OUTCOME_LABEL` maps in `SignalCard.tsx`.

**Hardcoded outcome filters:** `api/risk.py` daily P&L filter and `api/routes.py` win rate calculation both hardcode outcome lists. Update to include `TP1_TRAIL` and `TP1_TP2` as win outcomes.

**`check_pending_signals` in main.py:** Needs ATR computation added before calling `resolve_signal_outcome`. Use the same candle data already loaded from Redis.

---

## Files Modified

| File | Changes |
|------|---------|
| `engine/risk.py` | Add `compute_kelly_risk()` function |
| `engine/outcome_resolver.py` | Add two-pass resolution with trailing stop |
| `main.py` | Kelly computation before PositionSizer; ATR computation before outcome resolution; 24h expiry handling for partial exits |
| `engine/performance_tracker.py` | Pass `atr` through to `resolve_signal_outcome` in `replay_signal` |
| `api/routes.py` | Update win outcome list to include `TP1_TRAIL`, `TP1_TP2` |
| `api/risk.py` | Update daily P&L outcome filter to include `TP1_TRAIL`, `TP1_TP2` |
| `web/src/features/signals/` | Add `OUTCOME_COLOR` and `OUTCOME_LABEL` entries for new outcome types |
| `tests/engine/test_risk.py` | Tests for `compute_kelly_risk()` (edge cases: all wins, all losses, breakeven, insufficient history) |
| `tests/engine/test_outcome_resolver.py` | Tests for two-pass resolution, trailing stop behavior, 24h expiry with partial exit |
